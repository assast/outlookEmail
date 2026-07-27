#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/reset_login_password.py 单元与集成测试。"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT_DIR / "scripts" / "reset_login_password.py"


def load_reset_module():
    spec = importlib.util.spec_from_file_location(
        "reset_login_password",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


reset_mod = load_reset_module()


def create_app_like_db(path: Path, password_hash: str = "old-not-bcrypt", session_version: str = "0") -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                user_ip TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (reset_mod.LOGIN_PASSWORD_KEY, password_hash),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (reset_mod.LOGIN_SESSION_VERSION_KEY, session_version),
        )
        conn.commit()
    finally:
        conn.close()


class ResetLoginPasswordTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(prefix="reset-login-password-")
        self.db_path = Path(self._tmpdir.name) / "outlook_accounts.db"
        self.old_session = "session-before-reset"
        # 旧值用明文占位即可；重置后应变成 bcrypt
        create_app_like_db(
            self.db_path,
            password_hash="legacy-old-password",
            session_version=self.old_session,
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def _read_setting(self, key: str) -> str:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
            self.assertIsNotNone(row)
            return row[0]
        finally:
            conn.close()

    def test_successful_reset_updates_hash_and_rotates_session(self):
        old_hash = self._read_setting(reset_mod.LOGIN_PASSWORD_KEY)
        hashed, new_version = reset_mod.reset_login_password(
            self.db_path,
            "new-password-1",
        )

        self.assertTrue(hashed.startswith("$2"))
        self.assertNotEqual(old_hash, hashed)
        self.assertEqual(
            self._read_setting(reset_mod.LOGIN_PASSWORD_KEY),
            hashed,
        )
        self.assertEqual(
            self._read_setting(reset_mod.LOGIN_SESSION_VERSION_KEY),
            new_version,
        )
        self.assertNotEqual(new_version, self.old_session)
        self.assertTrue(reset_mod.verify_password("new-password-1", hashed))
        self.assertFalse(reset_mod.verify_password("legacy-old-password", hashed))

    def test_short_password_does_not_write(self):
        with self.assertRaises(reset_mod.ResetError) as ctx:
            reset_mod.reset_login_password(self.db_path, "short")
        self.assertIn("8", str(ctx.exception))

        self.assertEqual(
            self._read_setting(reset_mod.LOGIN_PASSWORD_KEY),
            "legacy-old-password",
        )
        self.assertEqual(
            self._read_setting(reset_mod.LOGIN_SESSION_VERSION_KEY),
            self.old_session,
        )

    def test_validate_mismatched_confirmation(self):
        err = reset_mod.validate_new_password("new-password-1", "new-password-2")
        self.assertIsNotNone(err)
        self.assertIn("不一致", err or "")

    def test_validate_format_before_mismatch(self):
        # 格式错误应优先于“不一致”，避免短密码被误报为两次不一致
        err = reset_mod.validate_new_password("short", "other")
        self.assertIsNotNone(err)
        self.assertIn("8", err or "")
        self.assertNotIn("不一致", err or "")

    def test_prompt_rejects_short_password_before_confirm(self):
        # 第一次输入格式不过关时，不应再要求确认密码
        getpass_calls = []

        def fake_getpass(prompt=""):
            getpass_calls.append(prompt)
            if len(getpass_calls) == 1:
                return "short"
            self.fail("短密码格式校验失败后不应再提示确认密码")

        with patch.object(sys.stdin, "isatty", return_value=True), patch.object(
            sys.stdout, "isatty", return_value=True
        ), patch.object(reset_mod.getpass, "getpass", side_effect=fake_getpass):
            with self.assertRaises(reset_mod.ResetError) as ctx:
                reset_mod.prompt_new_password()
        self.assertIn("8", str(ctx.exception))
        self.assertEqual(len(getpass_calls), 1)
        self.assertIn("新登录密码", getpass_calls[0])

    def test_missing_database_file(self):
        missing = Path(self._tmpdir.name) / "no-such.db"
        with self.assertRaises(reset_mod.ResetError) as ctx:
            reset_mod.reset_login_password(missing, "new-password-1")
        self.assertIn(str(missing), str(ctx.exception))

    def test_custom_database_path_env_resolution(self):
        custom = Path(self._tmpdir.name) / "custom.db"
        create_app_like_db(custom, password_hash="x", session_version="v0")
        with patch.dict(os.environ, {"DATABASE_PATH": str(custom)}, clear=False):
            resolved = reset_mod.resolve_database_path()
        self.assertEqual(resolved, custom.resolve())
        hashed, _version = reset_mod.reset_login_password(custom, "custom-pass-99")
        conn = sqlite3.connect(str(custom))
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (reset_mod.LOGIN_PASSWORD_KEY,),
            ).fetchone()
            self.assertEqual(row[0], hashed)
        finally:
            conn.close()
        # 默认库未被改动
        self.assertEqual(
            self._read_setting(reset_mod.LOGIN_PASSWORD_KEY),
            "legacy-old-password",
        )

    def test_audit_log_written_without_password_plaintext(self):
        secret = "super-secret-password-xyz"
        reset_mod.reset_login_password(self.db_path, secret)

        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT action, resource_type, resource_id, user_ip, details FROM audit_logs"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            action, resource_type, resource_id, user_ip, details = rows[0]
            self.assertEqual(action, "reset_login_password")
            self.assertEqual(resource_type, "settings")
            self.assertEqual(resource_id, reset_mod.LOGIN_PASSWORD_KEY)
            self.assertEqual(user_ip, "cli")
            blob = " ".join(str(part) for part in rows[0])
            self.assertNotIn(secret, blob)
        finally:
            conn.close()

    def test_non_tty_prompt_rejected(self):
        with patch.object(sys.stdin, "isatty", return_value=False), patch.object(
            sys.stdout, "isatty", return_value=True
        ):
            with self.assertRaises(reset_mod.ResetError) as ctx:
                reset_mod.prompt_new_password()
        self.assertIn("交互", str(ctx.exception))

    def test_main_success_with_mocked_getpass(self):
        with patch.dict(os.environ, {"DATABASE_PATH": str(self.db_path)}, clear=False), patch.object(
            sys.stdin, "isatty", return_value=True
        ), patch.object(
            sys.stdout, "isatty", return_value=True
        ), patch.object(
            reset_mod.getpass,
            "getpass",
            side_effect=["integration-pass-1", "integration-pass-1"],
        ):
            code = reset_mod.main([])
        self.assertEqual(code, 0)
        stored = self._read_setting(reset_mod.LOGIN_PASSWORD_KEY)
        self.assertTrue(reset_mod.verify_password("integration-pass-1", stored))
        self.assertNotEqual(
            self._read_setting(reset_mod.LOGIN_SESSION_VERSION_KEY),
            self.old_session,
        )

    def test_main_missing_db_returns_error(self):
        missing = Path(self._tmpdir.name) / "missing.db"
        with patch.dict(os.environ, {"DATABASE_PATH": str(missing)}, clear=False):
            code = reset_mod.main([])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
