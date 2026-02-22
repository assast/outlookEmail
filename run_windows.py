#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用 - Windows 桌面版启动入口（--onefile 模式）
使用 pywebview 创建原生桌面窗口，waitress 作为 WSGI 服务器
"""

import os
import sys
import threading
import secrets
import socket


def get_base_dir() -> str:
    """获取 exe 所在真实目录（数据持久化位置）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def find_free_port() -> int:
    """自动寻找可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def ensure_secret_key():
    """确保 SECRET_KEY 存在，没有则生成并持久化到 data/.secret_key"""
    if os.environ.get('SECRET_KEY'):
        return

    base_dir = get_base_dir()
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    secret_key_file = os.path.join(data_dir, '.secret_key')
    if os.path.exists(secret_key_file):
        with open(secret_key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key:
            os.environ['SECRET_KEY'] = key
            return

    key = secrets.token_hex(32)
    with open(secret_key_file, 'w', encoding='utf-8') as f:
        f.write(key)
    os.environ['SECRET_KEY'] = key
    print(f"已生成 SECRET_KEY -> {secret_key_file}")


def start_server(app, host: str, port: int):
    """在后台线程中启动 WSGI 服务器"""
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=4,
              url_scheme='http', _quiet=True)
    except ImportError:
        app.run(host=host, port=port, debug=False, use_reloader=False)


def main():
    # 1) 设置 SECRET_KEY（必须在 import web_outlook_app 之前）
    ensure_secret_key()

    # 2) 导入 Flask app（此时 web_outlook_app.py 自动处理 template/数据库路径）
    from web_outlook_app import app, init_scheduler

    port = int(os.environ.get('PORT', '0'))
    if port == 0:
        port = find_free_port()
    host = '127.0.0.1'

    base_dir = get_base_dir()
    data_dir = os.path.join(base_dir, 'data')

    print("=" * 60)
    print("  Outlook 邮件 Web 应用 (Windows 桌面版)")
    print("=" * 60)
    print(f"  数据目录: {data_dir}")
    print(f"  服务地址: http://{host}:{port}")
    print(f"  默认密码: admin123（请在设置中修改）")
    print("=" * 60)

    # 3) 初始化定时任务
    init_scheduler()

    # 4) 后台启动 HTTP 服务
    server_thread = threading.Thread(
        target=start_server, args=(app, host, port), daemon=True
    )
    server_thread.start()

    # 5) 等待服务器就绪
    import time
    url = f'http://{host}:{port}'
    for _ in range(50):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)

    # 6) 启动桌面窗口
    try:
        import webview
        print("正在启动桌面窗口...")
        webview.create_window(
            title='Outlook 邮件管理',
            url=url,
            width=1280,
            height=800,
            min_size=(900, 600),
            resizable=True,
            text_select=True,
        )
        webview.start(gui='edgechromium', debug=False)
        print("窗口已关闭，程序退出。")
    except Exception as e:
        # pywebview 不可用或 WebView2 缺失时回退到浏览器
        print(f"桌面窗口不可用 ({e})，使用浏览器打开...")
        import webbrowser
        webbrowser.open(url)
        print("已在浏览器中打开，关闭此命令行窗口即可停止服务。")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
