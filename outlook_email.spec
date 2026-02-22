# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将 Outlook 邮件 Web 应用打包为 Windows exe

使用方法:
    pyinstaller outlook_email.spec

生成两个版本:
    - dist/OutlookEmail/OutlookEmail.exe  (目录模式，启动快)
    - dist/OutlookEmail.exe               (单文件模式，便于分发)
"""

import os

block_cipher = None

# 应用基本信息
APP_NAME = 'OutlookEmail'
ENTRY_SCRIPT = 'run_windows.py'

# 需要打包的数据文件
datas = [
    ('templates', 'templates'),       # HTML 模板
    ('web_outlook_app.py', '.'),      # 主应用（作为模块导入）
]

# 如果有 img 目录也打包进去
if os.path.exists('img'):
    datas.append(('img', 'img'))

# 隐式导入（PyInstaller 可能扫描不到的模块）
hiddenimports = [
    'waitress',
    'waitress.server',
    'waitress.task',
    'waitress.channel',
    'waitress.receiver',
    'waitress.buffers',
    'waitress.parser',
    'waitress.utilities',
    'flask',
    'flask.json',
    'flask_wtf',
    'flask_wtf.csrf',
    'werkzeug',
    'werkzeug.middleware.proxy_fix',
    'jinja2',
    'markupsafe',
    'requests',
    'requests.adapters',
    'urllib3',
    'socks',            # PySocks
    'sockshandler',
    'bcrypt',
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.kdf.pbkdf2',
    'cryptography.hazmat.backends',
    'apscheduler',
    'apscheduler.schedulers.background',
    'apscheduler.triggers.interval',
    'apscheduler.triggers.cron',
    'croniter',
    'sqlite3',
    'email',
    'imaplib',
]

# Analysis 配置
a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',        # 不需要 GUI 框架
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        '_tkinter',
        'unittest',
        'test',
        'xmlrpc',
        'pydoc',
    ],
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
    console=True,          # 保留控制台窗口显示日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # 可替换为 .ico 图标文件路径
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
    console=True,          # 保留控制台窗口显示日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # 可替换为 .ico 图标文件路径
)
