# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 — 仅 --onefile 模式
生成单个 OutlookEmail.exe，模板内嵌，数据库外置持久化

使用: pyinstaller outlook_email.spec
"""

block_cipher = None

a = Analysis(
    ['run_windows.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),          # 内嵌到 _MEIPASS/templates
        ('web_outlook_app.py', '.'),         # 内嵌到 _MEIPASS/
    ],
    hiddenimports=[
        # WSGI 服务器
        'waitress', 'waitress.server', 'waitress.task',
        'waitress.channel', 'waitress.receiver', 'waitress.buffers',
        'waitress.parser', 'waitress.utilities',
        # 桌面窗口
        'webview',
        # Flask
        'flask', 'flask.json', 'flask_wtf', 'flask_wtf.csrf',
        'werkzeug', 'werkzeug.middleware.proxy_fix',
        'jinja2', 'markupsafe',
        # HTTP
        'requests', 'requests.adapters', 'urllib3',
        'socks', 'sockshandler',
        # 加密
        'bcrypt',
        'cryptography', 'cryptography.fernet',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'cryptography.hazmat.backends',
        # 定时任务
        'apscheduler', 'apscheduler.schedulers.background',
        'apscheduler.triggers.interval', 'apscheduler.triggers.cron',
        'croniter',
        # 标准库
        'sqlite3', 'email', 'imaplib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter', 'matplotlib', 'numpy', 'pandas',
        'scipy', 'PIL', 'cv2', 'torch', 'tensorflow',
        'unittest', 'test', 'xmlrpc', 'pydoc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OutlookEmail',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 保留控制台显示日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 可替换为 .ico 图标路径
)
