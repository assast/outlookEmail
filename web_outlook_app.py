#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entrypoint for the segmented Outlook web app."""

import os
import threading
import webbrowser
from pathlib import Path

from outlook_web.runtime import is_frozen, notify_startup_error, record_startup_error
from werkzeug.serving import make_server


SEGMENT_FILES = (
    "01_bootstrap.py",
    "02_groups_accounts.py",
    "03_mail_helpers.py",
    "04_routes_groups_accounts.py",
    "05_routes_refresh_mail.py",
    "06_routes_temp_email.py",
    "07_routes_oauth_settings_external.py",
    "08_forwarding_scheduler_errors.py",
    "09_routes_system_update.py",
)

SEGMENTS_DIR = Path(__file__).resolve().parent / "outlook_web" / "segments"

def _load_segmented_app():
    if globals().get("_SEGMENTED_APP_LOADED"):
        return

    globals()["_SEGMENTED_APP_LOADED"] = True
    for segment_name in SEGMENT_FILES:
        segment_path = SEGMENTS_DIR / segment_name
        code = compile(segment_path.read_text(encoding="utf-8"), str(segment_path), "exec")
        exec(code, globals())

_load_segmented_app()


class DesktopServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.http_server = None
        self.thread = None
        self.ready = threading.Event()
        self.failed = threading.Event()
        self.error = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._serve, name="outlookemail-server", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=15)
        if self.failed.is_set():
            raise self.error
        if not self.ready.is_set():
            raise RuntimeError("桌面服务启动超时")

    def _serve(self) -> None:
        try:
            init_scheduler()
            self.http_server = make_server(self.host, self.port, app, threaded=True)
            self.ready.set()
            self.http_server.serve_forever()
        except Exception as exc:
            self.error = exc
            self.failed.set()
            self.ready.set()

    def stop(self) -> None:
        try:
            shutdown_scheduler()
        finally:
            if self.http_server is not None:
                try:
                    self.http_server.shutdown()
                except Exception:
                    pass


def run_windows_desktop(access_url: str, host: str, port: int) -> None:
    from outlook_web.windows_tray import WindowsTrayApp

    server = DesktopServer(host, port)
    server.start()

    def open_ui():
        webbrowser.open(access_url)

    def exit_app():
        server.stop()

    threading.Timer(1.0, open_ui).start()
    WindowsTrayApp("OutlookEmail", open_ui, exit_app).run()


def main():
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1" if is_frozen() else "0.0.0.0")
    debug = os.getenv("FLASK_ENV", "production") != "production"
    access_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    access_url = f"http://{access_host}:{port}"

    print("=" * 60)
    print("Outlook 邮件 Web 应用")
    print("=" * 60)
    print(f"访问地址: {access_url}")
    print(f"运行模式: {'开发' if debug else '生产'}")
    print("=" * 60)

    try:
        if is_frozen() and os.name == "nt":
            run_windows_desktop(access_url, host, port)
            return

        if is_frozen():
            threading.Timer(1.0, lambda: webbrowser.open(access_url)).start()

        init_scheduler()
        app.run(debug=debug, host=host, port=port)
    except Exception as exc:
        log_path = record_startup_error(exc)
        notify_startup_error(log_path)
        raise


if __name__ == "__main__":
    main()
