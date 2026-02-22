#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用 - Windows 桌面版启动入口
使用 pywebview 创建原生桌面窗口，内嵌 WebView 渲染 Flask 页面
使用 waitress 替代 gunicorn（gunicorn 不支持 Windows）
"""

import os
import sys
import threading
import secrets
import socket


def get_base_dir() -> str:
    """
    获取应用基础目录（exe 所在目录）
    PyInstaller --onefile 模式下，sys._MEIPASS 指向临时解压目录，
    但数据文件需要存放在 exe 所在目录，确保持久化。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    """
    获取资源文件目录（templates 等）
    PyInstaller 打包后资源在 _MEIPASS 临时目录中
    """
    if getattr(sys, 'frozen', False):
        # noinspection PyProtectedMember
        return sys._MEIPASS  # type: ignore[attr-defined]
    else:
        return os.path.dirname(os.path.abspath(__file__))


def find_free_port() -> int:
    """自动寻找可用端口，避免端口冲突"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def setup_environment() -> tuple:
    """设置 Windows 运行环境，返回 (base_dir, data_dir)"""
    base_dir = get_base_dir()

    # 数据目录：exe 同级目录下的 data/
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    # 设置数据库路径为 exe 同级目录（确保数据持久化）
    db_path = os.path.join(data_dir, 'outlook_accounts.db')
    os.environ.setdefault('DATABASE_PATH', db_path)

    # 如果没有设置 SECRET_KEY，生成一个并持久化到文件
    secret_key_file = os.path.join(data_dir, '.secret_key')
    if not os.environ.get('SECRET_KEY'):
        if os.path.exists(secret_key_file):
            with open(secret_key_file, 'r', encoding='utf-8') as f:
                secret_key = f.read().strip()
        else:
            secret_key = secrets.token_hex(32)
            with open(secret_key_file, 'w', encoding='utf-8') as f:
                f.write(secret_key)
            print(f"已生成 SECRET_KEY 并保存到: {secret_key_file}")
        os.environ['SECRET_KEY'] = secret_key

    return base_dir, data_dir


def start_server(app, host: str, port: int):
    """在后台线程中启动 WSGI 服务器"""
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=4, url_scheme='http',
              _quiet=True)
    except ImportError:
        app.run(host=host, port=port, debug=False, use_reloader=False)


def main():
    """主入口"""
    base_dir, data_dir = setup_environment()

    port = int(os.environ.get('PORT', '0'))  # 0 = 自动寻找可用端口
    if port == 0:
        port = find_free_port()
    host = '127.0.0.1'

    print("=" * 60)
    print("  Outlook 邮件 Web 应用 (Windows 桌面版)")
    print("=" * 60)
    print(f"  数据目录: {data_dir}")
    print(f"  数据库:   {os.environ.get('DATABASE_PATH')}")
    print(f"  服务地址: http://{host}:{port}")
    print(f"  默认密码: admin123（请在设置中修改）")
    print("=" * 60)

    # 导入 Flask app（必须在环境变量设置之后）
    from web_outlook_app import app, init_scheduler

    # 修正 PyInstaller 打包后的模板路径
    resource_dir = get_resource_dir()
    app.template_folder = os.path.join(resource_dir, 'templates')

    # 初始化定时任务
    init_scheduler()

    # 在后台线程启动 HTTP 服务器
    server_thread = threading.Thread(
        target=start_server, args=(app, host, port), daemon=True
    )
    server_thread.start()

    # 等待服务器启动
    import time
    url = f'http://{host}:{port}'
    for _ in range(30):
        try:
            s = socket.create_connection((host, port), timeout=0.5)
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)

    # 使用 pywebview 创建原生桌面窗口
    try:
        import webview
        print("正在启动桌面窗口...")
        window = webview.create_window(
            title='Outlook 邮件管理',
            url=url,
            width=1280,
            height=800,
            min_size=(900, 600),
            resizable=True,
            text_select=True,
        )
        # 启动 pywebview 事件循环（阻塞，直到窗口关闭）
        webview.start(gui='edgechromium', debug=False)
        print("窗口已关闭，程序退出。")
    except ImportError:
        # pywebview 不可用时回退到浏览器
        print("pywebview 未安装，回退到浏览器模式...")
        import webbrowser
        webbrowser.open(url)
        print("已在浏览器中打开，关闭此窗口即可停止服务。")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
    except Exception as e:
        # WebView2 不可用等异常，回退到浏览器
        print(f"桌面窗口启动失败 ({e})，回退到浏览器模式...")
        import webbrowser
        webbrowser.open(url)
        print("已在浏览器中打开，关闭此窗口即可停止服务。")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
