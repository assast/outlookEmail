#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用 - Windows 启动入口
用于 PyInstaller 打包后的 Windows exe 运行
使用 waitress 替代 gunicorn（gunicorn 不支持 Windows）
"""

import os
import sys
import webbrowser
import threading
import secrets


def get_base_dir() -> str:
    """
    获取应用基础目录
    PyInstaller --onefile 模式下，sys._MEIPASS 指向临时解压目录，
    但数据文件需要存放在 exe 所在目录，确保持久化。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境，脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    """
    获取资源文件目录（templates 等）
    PyInstaller 打包后资源在 _MEIPASS 临时目录中
    """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


def setup_environment():
    """设置 Windows 运行环境"""
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

    # 设置模板目录（PyInstaller 打包后模板在 _MEIPASS 中）
    resource_dir = get_resource_dir()
    template_dir = os.path.join(resource_dir, 'templates')
    os.environ.setdefault('TEMPLATE_DIR', template_dir)

    return base_dir, data_dir


def open_browser(port: int):
    """延迟打开浏览器"""
    import time
    time.sleep(1.5)
    webbrowser.open(f'http://127.0.0.1:{port}')


def main():
    """主入口"""
    base_dir, data_dir = setup_environment()

    port = int(os.environ.get('PORT', '5000'))
    host = os.environ.get('HOST', '127.0.0.1')  # Windows 默认只监听本地

    print("=" * 60)
    print("  Outlook 邮件 Web 应用 (Windows)")
    print("=" * 60)
    print(f"  数据目录: {data_dir}")
    print(f"  数据库:   {os.environ.get('DATABASE_PATH')}")
    print(f"  访问地址: http://{host}:{port}")
    print(f"  默认密码: admin123（请在设置中修改）")
    print("=" * 60)
    print("  提示: 关闭此窗口即可停止服务")
    print("=" * 60)

    # 修改 Flask app 的 template_folder
    # 需要在导入 web_outlook_app 之前设置好环境变量
    from web_outlook_app import app, init_scheduler

    # 修正 PyInstaller 打包后的模板路径
    resource_dir = get_resource_dir()
    app.template_folder = os.path.join(resource_dir, 'templates')

    # 初始化定时任务
    scheduler = init_scheduler()

    # 自动打开浏览器
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    # 使用 waitress 作为 WSGI 服务器
    try:
        from waitress import serve
        print(f"\n使用 waitress 服务器启动...")
        serve(app, host=host, port=port, threads=4, url_scheme='http')
    except ImportError:
        print("\nwaitress 未安装，使用 Flask 内置开发服务器...")
        print("建议安装 waitress 获得更好性能: pip install waitress")
        app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
