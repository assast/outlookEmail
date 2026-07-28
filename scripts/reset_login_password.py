#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置 Web 登录密码（忘记密码时的官方运维入口）。

不需要旧密码；需要能访问数据库文件的主机权限。
仅支持交互式终端输入新密码（不提供 --password / stdin 密码通道）。

与 Web 应用行为对齐：
- bcrypt 写入 settings.login_password
- 轮换 settings.login_session_version，使既有 Web/扩展会话失效
- 写入 audit_logs（不含密码）

用法:
  python scripts/reset_login_password.py
  DATABASE_PATH=/path/to/outlook_accounts.db python scripts/reset_login_password.py

Docker 示例:
  docker exec -it <container> python scripts/reset_login_password.py
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Optional, Tuple

# 与 outlook_web/segments/01_bootstrap.py / 设置页改密保持一致
MIN_PASSWORD_LENGTH = 8
LOGIN_PASSWORD_KEY = "login_password"
LOGIN_SESSION_VERSION_KEY = "login_session_version"
DEFAULT_DATABASE_RELATIVE = Path("data") / "outlook_accounts.db"


class ResetError(Exception):
    """可向用户展示的重置失败。"""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_dotenv_file(path: Path) -> None:
    """轻量加载 .env（仅处理 KEY=VALUE，不覆盖已有环境变量）。"""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value


def resolve_database_path() -> Path:
    """与应用一致：优先 DATABASE_PATH，否则项目 data/outlook_accounts.db。"""
    env_value = (os.getenv("DATABASE_PATH") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (project_root() / DEFAULT_DATABASE_RELATIVE).resolve()


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码（与应用 hash_password 一致）。"""
    try:
        import bcrypt
    except ImportError as exc:
        raise ResetError(
            "缺少 bcrypt 依赖，请先安装: pip install bcrypt"
        ) from exc
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        import bcrypt
    except ImportError:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def require_interactive_tty() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ResetError(
            "仅支持交互式终端重置密码。"
            "请在 TTY 中运行本脚本（例如 docker exec -it ...），"
            "不支持 --password、环境变量或管道传入新密码。"
        )


def validate_password_format(password: str) -> Optional[str]:
    """仅校验密码本身格式（空值、长度）；通过返回 None。"""
    if not password:
        return "新密码不能为空"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"密码长度至少为 {MIN_PASSWORD_LENGTH} 位"
    return None


def validate_new_password(password: str, confirm: str) -> Optional[str]:
    """返回错误信息；通过则返回 None。不写库。

    先做格式校验，再比对两次输入，避免格式问题被“不一致”掩盖。
    """
    format_error = validate_password_format(password)
    if format_error:
        return format_error
    if password != confirm:
        return "两次输入的密码不一致"
    return None


def prompt_new_password() -> str:
    """交互输入新密码：第一次输入后立即做格式校验，通过后再确认。"""
    require_interactive_tty()
    password = getpass.getpass("新登录密码: ")
    format_error = validate_password_format(password)
    if format_error:
        raise ResetError(format_error)
    confirm = getpass.getpass("确认新登录密码: ")
    if password != confirm:
        raise ResetError("两次输入的密码不一致")
    return password


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _upsert_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
        (key, value),
    )


def _get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def write_audit_log(conn: sqlite3.Connection, details: str) -> None:
    """写入审计日志；表不存在或失败时静默跳过（与应用 log_audit 一致）。"""
    if not _table_exists(conn, "audit_logs"):
        return
    try:
        conn.execute(
            """
            INSERT INTO audit_logs (action, resource_type, resource_id, user_ip, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "reset_login_password",
                "settings",
                LOGIN_PASSWORD_KEY,
                "cli",
                details,
            ),
        )
    except sqlite3.Error:
        pass


def reset_login_password(db_path: Path, new_password: str) -> Tuple[str, str]:
    """将新密码写入数据库并轮换会话版本。

    :return: (bcrypt_hash, new_session_version)
    :raises ResetError: 路径/库结构/策略校验失败（不写库）
    """
    error = validate_new_password(new_password, new_password)
    if error:
        raise ResetError(error)

    if not db_path.is_file():
        raise ResetError(
            f"数据库文件不存在: {db_path}\n"
            "请确认 DATABASE_PATH 或默认 data/outlook_accounts.db 是否正确。"
        )

    hashed = hash_password(new_password)
    new_version = secrets.token_urlsafe(24)

    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise ResetError(f"无法打开数据库: {db_path} ({exc})") from exc

    try:
        if not _table_exists(conn, "settings"):
            raise ResetError(
                f"数据库缺少 settings 表，不是有效的 OutlookEmail 库: {db_path}"
            )
        _upsert_setting(conn, LOGIN_PASSWORD_KEY, hashed)
        _upsert_setting(conn, LOGIN_SESSION_VERSION_KEY, new_version)
        write_audit_log(
            conn,
            "CLI 重置 Web 登录密码；已轮换 login_session_version",
        )
        conn.commit()
    except ResetError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise ResetError(f"写入数据库失败: {exc}") from exc
    finally:
        conn.close()

    return hashed, new_version


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "交互式重置 Web 登录密码（忘记密码时使用）。"
            "不需要旧密码；不支持通过参数或管道传入新密码。"
        ),
    )
    parser.add_argument(
        "--dry-run-check-db",
        action="store_true",
        help=argparse.SUPPRESS,  # 仅内部/测试可发现；不改变密码
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    # 先加载项目 .env，便于本地 DATABASE_PATH 与应用一致
    load_dotenv_file(project_root() / ".env")
    load_dotenv_file(project_root() / ".env.local")

    try:
        parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1

    db_path = resolve_database_path()
    print(f"数据库: {db_path}")
    print("说明: 重置不需要旧密码；成功后所有已登录会话将失效。")
    print("建议: 若服务正在运行，可先停止再重置（非强制）。")
    print("-" * 40)

    if not db_path.is_file():
        print(
            f"错误: 数据库文件不存在: {db_path}",
            file=sys.stderr,
        )
        return 1

    try:
        new_password = prompt_new_password()
        _hashed, _version = reset_login_password(db_path, new_password)
    except ResetError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，未修改密码。", file=sys.stderr)
        return 1

    print("-" * 40)
    print("已重置 Web 登录密码。")
    print("请使用刚才设置的新密码登录。")
    print("密码真相源是数据库 settings.login_password，不是环境变量 LOGIN_PASSWORD。")
    print(
        "在线改密或本脚本重置后，仅修改 docker-compose / .env 中的 LOGIN_PASSWORD "
        "不会覆盖已有库中的哈希。"
    )
    print("若 compose 中仍写着旧的 LOGIN_PASSWORD，建议改成备注或与新密码一致以免运维混淆。")
    print("既有 Web / 浏览器扩展登录会话已失效，需重新登录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
