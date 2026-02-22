# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将 Outlook 邮件 Web 应用打包为 Windows exe（桌面窗口版）

使用方法:
    pyinstaller outlook_email.spec
"""

import os

block_cipher = None

APP_NAME = 'OutlookEmail'
ENTRY_SCRIPT = 'run_windows.py'

datas = [
    ('templates', 'templates'),
    ('web_outlook_app.py', '.'),
]

if os.path.exists('img'):
    datas.append(('img', 'img'))

hiddenimports = [
    # WSGI 服务器
    'waitress', 'waitress.server', 'waitress.task',
    'waitress.channel', 'waitress.receiver', 'waitress.buffers',
    'waitress.parser', 'waitress.utilities',
    # 桌面窗口
    'webview',
    # Flask 及相关
    'flask', 'flask.json', 'flask_wtf', 'flask_wtf.csrf',
    'werkzeug', 'werkzeug.middleware.proxy_fix',
    'jinja2', 'markupsafe',
    # HTTP 及代理
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
]

excludes = [
    'tkinter', '_tkinter', 'matplotlib', 'numpy', 'pandas',
    'scipy', 'PIL', 'cv2', 'torch', 'tensorflow',
    'unittest', 'test', 'xmlrpc', 'pydoc',
]

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ==================== 目录模式 (--onedir) ====================
exe_onedir = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe_onedir,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# ==================== 单文件模式 (--onefile) ====================
exe_onefile = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME + '_portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
