#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows portable executable self-update support."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import quote

import requests

from outlook_web.runtime import is_frozen


UPDATE_HELPER_FLAG = "--apply-windows-update"
UPDATE_RESTART_FLAG = "--windows-update-restart"
UPDATE_HEALTH_FILE_FLAG = "--windows-update-health-file"
UPDATE_HEALTH_TOKEN_FLAG = "--windows-update-health-token"
UPDATE_RUNNER_FLAG = "--windows-update-runner"
UPDATE_RUNNER_PID_FLAG = "--windows-update-runner-pid"
UPDATE_TARGET_VERSION_FLAG = "--windows-update-target-version"
DEFAULT_REQUEST_TIMEOUT = (10, 60)
DEFAULT_HEALTH_TIMEOUT_SECONDS = 30
DEFAULT_COMPATIBILITY_READY_SECONDS = 3.0
REPLACEFILE_WRITE_THROUGH = 0x00000001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
ERROR_INSUFFICIENT_BUFFER = 122
NO_ERROR = 0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TCP_TABLE_OWNER_PID_LISTENER = 3


class WindowsUpdateError(RuntimeError):
    """An update failure that can be shown to the user."""


class WindowsUpdateCancelled(WindowsUpdateError):
    """The user cancelled an in-progress download."""


@dataclass(frozen=True)
class WindowsUpdatePaths:
    target: Path
    archive: Path
    archive_part: Path
    replacement: Path
    runner: Path
    backup: Path
    health: Path
    result: Path


DEFAULT_STATE: Dict[str, Any] = {
    "running": False,
    "stage": "idle",
    "started_at": None,
    "finished_at": None,
    "success": None,
    "message": "",
    "error": "",
    "target_version": "",
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "percent": None,
    "bytes_per_second": 0,
    "cancelable": False,
    "helper_pid": None,
}

_state_lock = threading.Lock()
_state: Dict[str, Any] = dict(DEFAULT_STATE)
_cancel_event = threading.Event()
_shutdown_lock = threading.Lock()
_shutdown_callback: Optional[Callable[[], None]] = None
_result_loaded_for: Optional[Path] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_version_label(version: str) -> str:
    value = str(version or "").strip()
    if not value:
        return ""
    return value if value.lower().startswith("v") else f"v{value}"


def _plain_version(version: str) -> str:
    return normalize_version_label(version).lstrip("vV")


def _configured_desktop_port() -> int:
    try:
        port = int(os.getenv("PORT", "5000"))
    except (TypeError, ValueError):
        return 5000
    return port if 1 <= port <= 65535 else 5000


def build_update_paths(executable_path: Optional[Path | str] = None) -> WindowsUpdatePaths:
    target = Path(executable_path or sys.executable).resolve()
    base_name = target.stem
    parent = target.parent
    return WindowsUpdatePaths(
        target=target,
        archive=parent / f"{base_name}.update.zip",
        archive_part=parent / f"{base_name}.update.zip.part",
        replacement=parent / f"{base_name}.new.exe",
        runner=parent / f"{base_name}.updater.exe",
        backup=parent / f"{base_name}.old.exe",
        health=parent / f"{base_name}.update-health.json",
        result=parent / f"{base_name}.update-result.json",
    )


def register_shutdown_callback(callback: Optional[Callable[[], None]]) -> None:
    global _shutdown_callback
    with _shutdown_lock:
        _shutdown_callback = callback


def _get_shutdown_callback() -> Optional[Callable[[], None]]:
    with _shutdown_lock:
        return _shutdown_callback


def get_windows_update_config(executable_path: Optional[Path | str] = None) -> Dict[str, Any]:
    windows_desktop = os.name == "nt" and is_frozen()
    reason = ""
    if not windows_desktop:
        reason = "Windows 在线升级仅支持打包后的 Windows 桌面版"
    elif _get_shutdown_callback() is None:
        reason = "桌面应用尚未完成启动"

    paths = build_update_paths(executable_path)
    return {
        "enabled": windows_desktop,
        "available": windows_desktop and not reason,
        "reason": reason,
        "executable_name": paths.target.name,
    }


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_result_state(paths: WindowsUpdatePaths) -> None:
    global _result_loaded_for
    with _state_lock:
        if _state.get("running") or _result_loaded_for == paths.result:
            return

    result = _read_json(paths.result)
    if not result:
        return
    _result_loaded_for = paths.result
    changes = {
        "running": False,
        "stage": "completed" if result.get("success") else "failed",
        "finished_at": result.get("finished_at"),
        "success": bool(result.get("success")),
        "message": str(result.get("message") or ""),
        "error": str(result.get("error") or ""),
        "target_version": str(result.get("target_version") or ""),
        "cancelable": False,
    }
    with _state_lock:
        if not _state.get("running"):
            _state.update(changes)


def get_windows_update_state(executable_path: Optional[Path | str] = None) -> Dict[str, Any]:
    _load_result_state(build_update_paths(executable_path))
    with _state_lock:
        return dict(_state)


def _update_state(**changes: Any) -> Dict[str, Any]:
    with _state_lock:
        _state.update(changes)
        return dict(_state)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_before_update(paths: WindowsUpdatePaths) -> None:
    for path in (
        paths.archive,
        paths.archive_part,
        paths.replacement,
        paths.runner,
        paths.backup,
        paths.health,
        paths.result,
        paths.result.with_name(f"{paths.result.name}.tmp"),
    ):
        _safe_unlink(path)


def check_update_directory(paths: WindowsUpdatePaths) -> None:
    if not paths.target.is_file():
        raise WindowsUpdateError(f"当前程序文件不存在：{paths.target}")

    paths.target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{paths.target.stem}-update-probe-",
            suffix=".tmp",
            dir=paths.target.parent,
            delete=False,
        ) as probe_file:
            probe_file.write(b"update-probe")
            probe_path = Path(probe_file.name)
        renamed_probe = probe_path.with_suffix(".renamed")
        os.replace(probe_path, renamed_probe)
        renamed_probe.unlink()
    except OSError as exc:
        for candidate in (locals().get("probe_path"), locals().get("renamed_probe")):
            if isinstance(candidate, Path):
                _safe_unlink(candidate)
        raise WindowsUpdateError("当前 EXE 所在目录不可写，请将程序移动到普通可写目录后升级") from exc


def _release_api_url(repository_owner: str, repository_name: str, target_version: str) -> str:
    owner = quote(str(repository_owner or "").strip(), safe="")
    repository = quote(str(repository_name or "").strip(), safe="")
    tag = quote(normalize_version_label(target_version), safe="")
    return f"https://api.github.com/repos/{owner}/{repository}/releases/tags/{tag}"


def select_release_asset(release_payload: Dict[str, Any], target_version: str) -> Dict[str, Any]:
    expected_name = f"OutlookEmail-windows-x64-{_plain_version(target_version)}.zip"
    assets = release_payload.get("assets") if isinstance(release_payload, dict) else None
    if not isinstance(assets, list):
        assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("name") or "") != expected_name:
            continue
        download_url = str(asset.get("browser_download_url") or "").strip()
        if download_url:
            return {
                "name": expected_name,
                "download_url": download_url,
                "size": int(asset.get("size") or 0),
            }
    raise WindowsUpdateError(f"检测到新版本，但 Windows 更新包 {expected_name} 尚未发布，请稍后重试")


def resolve_release_asset(
    repository_owner: str,
    repository_name: str,
    target_version: str,
    request_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = requests.get(
        _release_api_url(repository_owner, repository_name, target_version),
        headers=dict(request_headers or {}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    if response.status_code == 404:
        raise WindowsUpdateError("检测到新版本，但对应的 Windows 更新包尚未发布，请稍后重试")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise WindowsUpdateError("GitHub Release 返回了无效数据")
    return select_release_asset(payload, target_version)


def _download_release_asset(
    asset: Dict[str, Any],
    paths: WindowsUpdatePaths,
    request_headers: Optional[Dict[str, str]] = None,
) -> None:
    _update_state(
        stage="downloading",
        message="正在下载 Windows 更新包",
        cancelable=True,
        downloaded_bytes=0,
        total_bytes=int(asset.get("size") or 0),
        percent=0.0 if asset.get("size") else None,
        bytes_per_second=0,
    )
    response = requests.get(
        str(asset["download_url"]),
        headers=dict(request_headers or {}),
        stream=True,
        allow_redirects=True,
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    header_size = int(response.headers.get("Content-Length") or 0)
    total_bytes = header_size or int(asset.get("size") or 0)
    downloaded_bytes = 0
    speed_samples: deque[Tuple[float, int]] = deque()

    try:
        with paths.archive_part.open("wb") as archive_file:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if _cancel_event.is_set():
                    raise WindowsUpdateCancelled("已取消 Windows 在线升级")
                if not chunk:
                    continue
                archive_file.write(chunk)
                downloaded_bytes += len(chunk)
                now = time.monotonic()
                speed_samples.append((now, downloaded_bytes))
                while len(speed_samples) > 1 and now - speed_samples[0][0] > 3.0:
                    speed_samples.popleft()
                if len(speed_samples) > 1:
                    elapsed = max(now - speed_samples[0][0], 0.001)
                    bytes_per_second = int((downloaded_bytes - speed_samples[0][1]) / elapsed)
                else:
                    bytes_per_second = 0
                percent = round(downloaded_bytes * 100 / total_bytes, 1) if total_bytes else None
                _update_state(
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                    percent=percent,
                    bytes_per_second=bytes_per_second,
                )
    finally:
        response.close()

    if total_bytes and downloaded_bytes != total_bytes:
        raise WindowsUpdateError(
            f"Windows 更新包下载不完整：应为 {total_bytes} 字节，实际为 {downloaded_bytes} 字节"
        )
    os.replace(paths.archive_part, paths.archive)
    _update_state(
        downloaded_bytes=downloaded_bytes,
        total_bytes=total_bytes,
        percent=100.0 if total_bytes else None,
        bytes_per_second=0,
        cancelable=False,
    )


def extract_release_executable(archive_path: Path, destination: Path) -> None:
    _update_state(stage="extracting", message="正在解压新版本", cancelable=False)
    part_path = destination.with_name(f"{destination.name}.part")
    _safe_unlink(part_path)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            candidates = [
                info
                for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).name.lower() == "outlookemail.exe"
            ]
            if len(candidates) != 1:
                raise WindowsUpdateError("Windows 更新包中未找到唯一的 OutlookEmail.exe")
            with archive.open(candidates[0], "r") as source, part_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        os.replace(part_path, destination)
    except zipfile.BadZipFile as exc:
        raise WindowsUpdateError("Windows 更新包不是有效的 ZIP 文件") from exc
    finally:
        _safe_unlink(part_path)


def _helper_command(
    paths: WindowsUpdatePaths,
    *,
    target_version: str,
    health_token: str,
    parent_pid: int,
) -> list[str]:
    return [
        str(paths.runner),
        UPDATE_HELPER_FLAG,
        "--target",
        str(paths.target),
        "--replacement",
        str(paths.replacement),
        "--backup",
        str(paths.backup),
        "--archive",
        str(paths.archive),
        "--health-file",
        str(paths.health),
        "--result-file",
        str(paths.result),
        "--health-token",
        health_token,
        "--target-version",
        normalize_version_label(target_version),
        "--parent-pid",
        str(parent_pid),
        "--health-timeout",
        str(DEFAULT_HEALTH_TIMEOUT_SECONDS),
        "--health-port",
        str(_configured_desktop_port()),
    ]


def _run_update_job(
    paths: WindowsUpdatePaths,
    *,
    repository_owner: str,
    repository_name: str,
    target_version: str,
    request_headers: Optional[Dict[str, str]],
) -> None:
    helper_process: Optional[subprocess.Popen] = None
    try:
        _update_state(stage="resolving", message="正在查找 Windows 更新包", cancelable=False)
        asset = resolve_release_asset(
            repository_owner,
            repository_name,
            target_version,
            request_headers=request_headers,
        )
        _download_release_asset(asset, paths, request_headers=request_headers)
        extract_release_executable(paths.archive, paths.replacement)
        shutil.copy2(paths.target, paths.runner)
        health_token = secrets.token_urlsafe(24)
        _safe_unlink(paths.health)
        _update_state(stage="restarting", message="更新包已就绪，正在重启应用", cancelable=False)
        helper_process = subprocess.Popen(
            _helper_command(
                paths,
                target_version=target_version,
                health_token=health_token,
                parent_pid=os.getpid(),
            ),
            cwd=str(paths.target.parent),
            close_fds=True,
        )
        _update_state(helper_pid=helper_process.pid)
        shutdown_callback = _get_shutdown_callback()
        if shutdown_callback is None:
            raise WindowsUpdateError("桌面应用关闭回调不可用")
        time.sleep(0.25)
        if helper_process.poll() is not None:
            raise WindowsUpdateError("Windows 升级辅助进程启动失败")
        shutdown_callback()
    except WindowsUpdateCancelled as exc:
        _safe_unlink(paths.archive_part)
        _safe_unlink(paths.archive)
        _update_state(
            running=False,
            stage="cancelled",
            finished_at=_utc_now(),
            success=False,
            message=str(exc),
            error="",
            cancelable=False,
            bytes_per_second=0,
        )
    except Exception as exc:
        if helper_process is not None and helper_process.poll() is None:
            helper_process.terminate()
        for path in (
            paths.archive_part,
            paths.archive,
            paths.replacement,
            paths.runner,
            paths.health,
        ):
            _safe_unlink(path)
        _update_state(
            running=False,
            stage="failed",
            finished_at=_utc_now(),
            success=False,
            message="Windows 在线升级失败",
            error=str(exc),
            cancelable=False,
            bytes_per_second=0,
        )


def start_windows_update(
    *,
    repository_owner: str,
    repository_name: str,
    target_version: str,
    request_headers: Optional[Dict[str, str]] = None,
    executable_path: Optional[Path | str] = None,
) -> Tuple[bool, str]:
    config = get_windows_update_config(executable_path)
    if not config["available"]:
        return False, str(config["reason"] or "Windows 在线升级不可用")
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", str(target_version or "").strip()):
        return False, "目标版本号无效"

    paths = build_update_paths(executable_path)
    try:
        check_update_directory(paths)
    except WindowsUpdateError as exc:
        return False, str(exc)

    with _state_lock:
        if _state.get("running"):
            return False, "Windows 在线升级正在进行中"
        _cleanup_before_update(paths)
        _cancel_event.clear()
        _state.clear()
        _state.update(DEFAULT_STATE)
        _state.update({
            "running": True,
            "stage": "queued",
            "started_at": _utc_now(),
            "message": "Windows 在线升级已开始",
            "target_version": normalize_version_label(target_version),
        })

    thread = threading.Thread(
        target=_run_update_job,
        kwargs={
            "paths": paths,
            "repository_owner": repository_owner,
            "repository_name": repository_name,
            "target_version": target_version,
            "request_headers": dict(request_headers or {}),
        },
        name="windows-update",
        daemon=True,
    )
    thread.start()
    return True, "Windows 在线升级已开始"


def cancel_windows_update() -> Tuple[bool, str]:
    with _state_lock:
        if not _state.get("running"):
            return False, "当前没有正在进行的 Windows 在线升级"
        if _state.get("stage") != "downloading" or not _state.get("cancelable"):
            return False, "当前升级阶段不能取消"
        _state["message"] = "正在取消 Windows 在线升级"
        _state["cancelable"] = False
    _cancel_event.set()
    return True, "正在取消 Windows 在线升级"


def _wait_for_process_exit(process_id: int, timeout_seconds: float) -> bool:
    if process_id <= 0:
        return True
    if os.name != "nt":
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                os.kill(process_id, 0)
            except OSError:
                return True
            time.sleep(0.1)
        return False

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, process_id)
    if not handle:
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, max(0, int(timeout_seconds * 1000)))
        return result == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def replace_file_windows(target: Path, replacement: Path, backup: Optional[Path]) -> None:
    if os.name != "nt":
        raise WindowsUpdateError("ReplaceFileW 仅支持 Windows")
    backup_value = str(backup) if backup is not None else None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    replace_file.restype = ctypes.c_bool
    result = replace_file(
        str(target),
        str(replacement),
        backup_value,
        REPLACEFILE_WRITE_THROUGH,
        None,
        None,
    )
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())


def _restore_backup(target: Path, backup: Path) -> None:
    if not backup.exists():
        return
    if target.exists():
        replace_file_windows(target, backup, None)
    else:
        os.replace(backup, target)


def _startup_command(
    target: Path,
    *,
    runner: Path,
    runner_pid: int,
    target_version: str,
    health_file: Optional[Path] = None,
    health_token: str = "",
) -> list[str]:
    command = [
        str(target),
        UPDATE_RESTART_FLAG,
        UPDATE_RUNNER_FLAG,
        str(runner),
        UPDATE_RUNNER_PID_FLAG,
        str(runner_pid),
        UPDATE_TARGET_VERSION_FLAG,
        normalize_version_label(target_version),
    ]
    if health_file is not None:
        command.extend([
            UPDATE_HEALTH_FILE_FLAG,
            str(health_file),
            UPDATE_HEALTH_TOKEN_FLAG,
            health_token,
        ])
    return command


def _wait_for_health(
    health_file: Path,
    health_token: str,
    process: subprocess.Popen,
    timeout_seconds: int,
    *,
    target: Path,
    target_version: str,
    health_port: int,
    compatibility_ready_seconds: float = DEFAULT_COMPATIBILITY_READY_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    compatibility_ready_since: Optional[float] = None
    expected_version = normalize_version_label(target_version)
    while True:
        now = time.monotonic()
        if now >= deadline:
            return False

        health = _read_json(health_file)
        if health.get("token") == health_token and health.get("ready") is True:
            return normalize_version_label(str(health.get("version") or "")) == expected_version

        if _target_listener_pids(target, health_port):
            if compatibility_ready_since is None:
                compatibility_ready_since = now
            if now - compatibility_ready_since >= compatibility_ready_seconds:
                return True
        else:
            compatibility_ready_since = None

        time.sleep(0.25)


def _windows_tcp_listener_pids(port: int) -> set[int]:
    if os.name != "nt" or not 1 <= int(port) <= 65535:
        return set()

    class TcpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("state", ctypes.c_ulong),
            ("local_address", ctypes.c_ulong),
            ("local_port", ctypes.c_ulong),
            ("remote_address", ctypes.c_ulong),
            ("remote_port", ctypes.c_ulong),
            ("owning_pid", ctypes.c_ulong),
        ]

    iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_bool,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    get_table.restype = ctypes.c_ulong

    size = ctypes.c_ulong(0)
    result = get_table(
        None,
        ctypes.byref(size),
        False,
        socket.AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    )
    if result not in (NO_ERROR, ERROR_INSUFFICIENT_BUFFER) or size.value < ctypes.sizeof(ctypes.c_ulong):
        return set()

    buffer = ctypes.create_string_buffer(size.value)
    result = get_table(
        buffer,
        ctypes.byref(size),
        False,
        socket.AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    )
    if result != NO_ERROR:
        return set()

    entry_count = ctypes.c_ulong.from_buffer_copy(buffer.raw[: ctypes.sizeof(ctypes.c_ulong)]).value
    row_size = ctypes.sizeof(TcpRowOwnerPid)
    first_row_offset = ctypes.sizeof(ctypes.c_ulong)
    listener_pids: set[int] = set()
    for index in range(entry_count):
        offset = first_row_offset + index * row_size
        if offset + row_size > size.value:
            break
        row = TcpRowOwnerPid.from_buffer_copy(buffer.raw[offset : offset + row_size])
        if socket.ntohs(int(row.local_port) & 0xFFFF) == port:
            listener_pids.add(int(row.owning_pid))
    return listener_pids


def _windows_process_image_path(process_id: int) -> Optional[Path]:
    if os.name != "nt" or process_id <= 0:
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    open_process.restype = ctypes.c_void_p
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    query_image.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_bool

    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buffer))
        if not query_image(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value)
    finally:
        close_handle(handle)


def _target_listener_pids(target: Path, port: int) -> set[int]:
    expected = os.path.normcase(os.path.abspath(str(target)))
    matches: set[int] = set()
    for process_id in _windows_tcp_listener_pids(port):
        image_path = _windows_process_image_path(process_id)
        if image_path is None:
            continue
        if os.path.normcase(os.path.abspath(str(image_path))) == expected:
            matches.add(process_id)
    return matches


def _terminate_windows_process_tree(process_id: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(process_id), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _terminate_process(process: subprocess.Popen, *, target: Path, health_port: int) -> None:
    if os.name == "nt":
        process_ids = _target_listener_pids(target, health_port)
        if process.poll() is None:
            process_ids.add(process.pid)
        for process_id in process_ids:
            try:
                _terminate_windows_process_tree(process_id)
            except (OSError, subprocess.SubprocessError):
                pass
    elif process.poll() is None:
        process.terminate()

    if process.poll() is not None:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _write_update_result(
    result_file: Path,
    *,
    success: bool,
    target_version: str,
    message: str,
    error: str = "",
) -> None:
    _write_json_atomic(result_file, {
        "success": success,
        "target_version": normalize_version_label(target_version),
        "message": message,
        "error": error,
        "finished_at": _utc_now(),
    })


def _run_helper(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    replacement = Path(args.replacement).resolve()
    backup = Path(args.backup).resolve()
    archive = Path(args.archive).resolve()
    health_file = Path(args.health_file).resolve()
    result_file = Path(args.result_file).resolve()
    runner = Path(sys.executable).resolve()
    target_version = normalize_version_label(args.target_version)
    new_process: Optional[subprocess.Popen] = None

    if not _wait_for_process_exit(args.parent_pid, 60):
        _write_update_result(
            result_file,
            success=False,
            target_version=target_version,
            message="旧版本未能正常退出",
            error="等待旧版本退出超时",
        )
        return 1

    try:
        _safe_unlink(backup)
        _safe_unlink(health_file)
        replace_file_windows(target, replacement, backup)
        new_process = subprocess.Popen(
            _startup_command(
                target,
                runner=runner,
                runner_pid=os.getpid(),
                target_version=target_version,
                health_file=health_file,
                health_token=args.health_token,
            ),
            cwd=str(target.parent),
            close_fds=True,
        )
        if _wait_for_health(
            health_file,
            args.health_token,
            new_process,
            args.health_timeout,
            target=target,
            target_version=target_version,
            health_port=args.health_port,
        ):
            _write_update_result(
                result_file,
                success=True,
                target_version=target_version,
                message=f"已升级到 {target_version}",
            )
            _safe_unlink(backup)
            _safe_unlink(archive)
            _safe_unlink(health_file)
            return 0
        raise WindowsUpdateError("新版本未能在限定时间内启动")
    except Exception as exc:
        if new_process is not None:
            _terminate_process(new_process, target=target, health_port=args.health_port)
        try:
            _restore_backup(target, backup)
        except Exception as restore_exc:
            _write_update_result(
                result_file,
                success=False,
                target_version=target_version,
                message="新版本启动失败，且旧版本自动恢复失败",
                error=f"{exc}; restore: {restore_exc}",
            )
            return 1

        _safe_unlink(archive)
        _safe_unlink(health_file)
        _write_update_result(
            result_file,
            success=False,
            target_version=target_version,
            message="新版本启动失败，已恢复旧版本",
            error=str(exc),
        )
        subprocess.Popen(
            _startup_command(
                target,
                runner=runner,
                runner_pid=os.getpid(),
                target_version=target_version,
            ),
            cwd=str(target.parent),
            close_fds=True,
        )
        return 1


def _helper_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(UPDATE_HELPER_FLAG, action="store_true", dest="apply_update")
    parser.add_argument("--target", required=True)
    parser.add_argument("--replacement", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--health-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--health-token", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--health-timeout", type=int, default=DEFAULT_HEALTH_TIMEOUT_SECONDS)
    parser.add_argument("--health-port", type=int, default=5000)
    return parser


def run_update_helper_if_requested(argv: Optional[Iterable[str]] = None) -> Optional[int]:
    arguments = list(argv if argv is not None else sys.argv)
    if UPDATE_HELPER_FLAG not in arguments:
        return None
    args, _unknown = _helper_parser().parse_known_args(arguments[1:])
    return _run_helper(args)


def parse_update_startup_context(argv: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    arguments = list(argv if argv is not None else sys.argv)
    context: Dict[str, Any] = {
        "restarted": UPDATE_RESTART_FLAG in arguments,
        "health_file": "",
        "health_token": "",
        "runner": "",
        "runner_pid": 0,
        "target_version": "",
    }
    value_flags = {
        UPDATE_HEALTH_FILE_FLAG: "health_file",
        UPDATE_HEALTH_TOKEN_FLAG: "health_token",
        UPDATE_RUNNER_FLAG: "runner",
        UPDATE_RUNNER_PID_FLAG: "runner_pid",
        UPDATE_TARGET_VERSION_FLAG: "target_version",
    }
    for index, argument in enumerate(arguments[:-1]):
        key = value_flags.get(argument)
        if key is None:
            continue
        value: Any = arguments[index + 1]
        if key == "runner_pid":
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0
        context[key] = value
    return context


def mark_update_startup_healthy(context: Dict[str, Any], current_version: str) -> None:
    health_file = str(context.get("health_file") or "").strip()
    health_token = str(context.get("health_token") or "").strip()
    if not health_file or not health_token:
        return
    _write_json_atomic(Path(health_file), {
        "ready": True,
        "token": health_token,
        "version": normalize_version_label(current_version),
        "ready_at": _utc_now(),
    })


def schedule_runner_cleanup(context: Dict[str, Any]) -> None:
    runner_value = str(context.get("runner") or "").strip()
    runner_pid = int(context.get("runner_pid") or 0)
    if not runner_value or runner_pid <= 0:
        return
    runner = Path(runner_value)

    def cleanup() -> None:
        _wait_for_process_exit(runner_pid, 60)
        for _attempt in range(20):
            try:
                runner.unlink(missing_ok=True)
                return
            except OSError:
                time.sleep(0.25)

    threading.Thread(target=cleanup, name="windows-update-cleanup", daemon=True).start()
