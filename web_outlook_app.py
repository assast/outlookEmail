#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用
基于 Flask 的 Web 界面，支持多邮箱管理和邮件查看
使用 SQLite 数据库存储邮箱信息，支持分组管理
支持 GPTMail 临时邮箱服务
"""

import email
import imaplib
import sqlite3
import os
import hashlib
import secrets
import time
import json
import re
import uuid
import threading
import bcrypt
import base64
import html
from datetime import datetime
from email.header import decode_header
from typing import Optional, List, Dict, Any
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, Response, make_response
from functools import wraps
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 尝试导入 Flask-WTF CSRF 保护
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False
    print("Warning: flask-wtf not installed. CSRF protection is disabled. Install with: pip install flask-wtf")

app = Flask(__name__)
# 强制从环境变量读取 secret_key，不提供默认值以防止安全漏洞
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
app.secret_key = secret_key
# 设置 session 过期时间（默认 7 天）
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 7  # 7 天

# Session Cookie 配置（适用于 HTTPS 代理环境）
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 信任代理头（适用于反向代理环境）
# 这确保 Flask 正确识别 HTTPS 请求
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

scheduler_instance = None
scheduler_lock = threading.Lock()


# 初始化 CSRF 保护（如果可用）
if CSRF_AVAILABLE:
    csrf = CSRFProtect(app)
    # 配置 CSRF
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF token 不过期
    app.config['WTF_CSRF_SSL_STRICT'] = False  # 允许非HTTPS环境（开发环境）
    print("CSRF protection enabled")

    # 创建CSRF排除装饰器
    def csrf_exempt(f):
        return csrf.exempt(f)
else:
    csrf = None
    # 显式禁用CSRF保护
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    print("CSRF protection disabled")

    # 创建空装饰器
    def csrf_exempt(f):
        return f

# 登录密码配置（可以修改为你想要的密码）
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "admin123")

# ==================== 配置 ====================
# Token 端点
TOKEN_URL_LIVE = "https://login.live.com/oauth20_token.srf"
TOKEN_URL_GRAPH = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
TOKEN_URL_IMAP = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

# IMAP 服务器配置
IMAP_SERVER_OLD = "outlook.office365.com"
IMAP_SERVER_NEW = "outlook.live.com"
IMAP_PORT = 993

# 数据库文件
DATABASE = os.getenv("DATABASE_PATH", "data/outlook_accounts.db")

# GPTMail API 配置
GPTMAIL_BASE_URL = os.getenv("GPTMAIL_BASE_URL", "https://mail.chatgpt.org.uk")
GPTMAIL_API_KEY = os.getenv("GPTMAIL_API_KEY", "gpt-test")  # 测试 API Key，可以修改为正式 Key

# DuckMail API 配置
DUCKMAIL_BASE_URL = os.getenv("DUCKMAIL_BASE_URL", "https://api.duckmail.sbs")
DUCKMAIL_API_KEY = os.getenv("DUCKMAIL_API_KEY", "")  # 可选，dk_ 前缀，用于私有域名

# Cloudflare Temp Email 配置
CLOUDFLARE_WORKER_DOMAIN = os.getenv("CLOUDFLARE_WORKER_DOMAIN") or os.getenv("WORKER_DOMAIN", "")
CLOUDFLARE_EMAIL_DOMAINS = os.getenv("CLOUDFLARE_EMAIL_DOMAINS") or os.getenv("EMAIL_DOMAIN", "")
CLOUDFLARE_ADMIN_PASSWORD = os.getenv("CLOUDFLARE_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD", "")

# 临时邮箱分组 ID（系统保留）
TEMP_EMAIL_GROUP_ID = -1

# 导出验证 Token 存储（内存存储，单 worker 模式下使用）
# 格式: {user_session_id: {'token': verify_token, 'expires': timestamp}}
export_verify_tokens = {}

# OAuth 配置
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "6daa9f56-5e67-4cb6-ae52-ef89ef912d36")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080")
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read"
]


# ==================== 登录速率限制 ====================

# 存储登录失败记录 {ip: {'count': int, 'last_attempt': timestamp, 'locked_until': timestamp}}
login_attempts = {}

# 速率限制配置
MAX_LOGIN_ATTEMPTS = 5  # 最大失败次数
LOCKOUT_DURATION = 300  # 锁定时长（秒）- 5分钟
ATTEMPT_WINDOW = 600    # 失败计数窗口（秒）- 10分钟


def check_rate_limit(ip: str) -> tuple[bool, Optional[int]]:
    """
    检查 IP 是否被速率限制
    返回: (是否允许登录, 剩余锁定秒数)
    """
    current_time = time.time()

    if ip not in login_attempts:
        return True, None

    attempt_data = login_attempts[ip]

    # 检查是否在锁定期内
    if 'locked_until' in attempt_data and current_time < attempt_data['locked_until']:
        remaining = int(attempt_data['locked_until'] - current_time)
        return False, remaining

    # 检查失败计数是否过期
    if current_time - attempt_data.get('last_attempt', 0) > ATTEMPT_WINDOW:
        # 重置计数
        login_attempts[ip] = {'count': 0, 'last_attempt': current_time}
        return True, None

    # 检查失败次数
    if attempt_data.get('count', 0) >= MAX_LOGIN_ATTEMPTS:
        # 锁定账号
        attempt_data['locked_until'] = current_time + LOCKOUT_DURATION
        remaining = LOCKOUT_DURATION
        return False, remaining

    return True, None


def record_login_failure(ip: str):
    """记录登录失败"""
    current_time = time.time()

    if ip not in login_attempts:
        login_attempts[ip] = {'count': 1, 'last_attempt': current_time}
    else:
        attempt_data = login_attempts[ip]
        # 如果在窗口期内，增加计数
        if current_time - attempt_data.get('last_attempt', 0) <= ATTEMPT_WINDOW:
            attempt_data['count'] = attempt_data.get('count', 0) + 1
        else:
            # 重置计数
            attempt_data['count'] = 1
        attempt_data['last_attempt'] = current_time


def reset_login_attempts(ip: str):
    """重置登录失败记录（登录成功时调用）"""
    if ip in login_attempts:
        del login_attempts[ip]


# ==================== 密码安全工具 ====================

def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配哈希值"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def is_password_hashed(password: str) -> bool:
    """检查密码是否已经是 bcrypt 哈希值"""
    return password.startswith('$2b$') or password.startswith('$2a$') or password.startswith('$2y$')


# ==================== 数据加密工具 ====================

# 全局加密器实例
_cipher_suite = None


def get_encryption_key() -> bytes:
    """
    从 SECRET_KEY 派生加密密钥
    使用 PBKDF2 从 SECRET_KEY 派生 32 字节密钥
    """
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY is required for encryption")

    # 使用固定盐（因为我们需要确保重启后能解密）
    # 注意：这里使用固定盐是为了确保密钥一致性，安全性依赖于 SECRET_KEY 的强度
    salt = b'outlook_email_encryption_salt_v1'

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key


def get_cipher() -> Fernet:
    """获取加密器实例（单例模式）"""
    global _cipher_suite
    if _cipher_suite is None:
        key = get_encryption_key()
        _cipher_suite = Fernet(key)
    return _cipher_suite


def encrypt_data(data: str) -> str:
    """
    加密敏感数据
    返回 base64 编码的加密字符串，带有 'enc:' 前缀标识
    """
    if not data:
        return data

    # 如果已经加密，直接返回
    if data.startswith('enc:'):
        return data

    cipher = get_cipher()
    encrypted = cipher.encrypt(data.encode('utf-8'))
    return 'enc:' + encrypted.decode('utf-8')


def decrypt_data(encrypted_data: str) -> str:
    """
    解密敏感数据
    如果数据未加密（没有 'enc:' 前缀），直接返回原始数据
    """
    if not encrypted_data:
        return encrypted_data

    # 如果没有加密标识，返回原始数据（向后兼容）
    if not encrypted_data.startswith('enc:'):
        return encrypted_data

    try:
        cipher = get_cipher()
        encrypted_bytes = encrypted_data[4:].encode('utf-8')  # 移除 'enc:' 前缀
        decrypted = cipher.decrypt(encrypted_bytes)
        return decrypted.decode('utf-8')
    except Exception as e:
        # 解密失败，可能是密钥变更或数据损坏
        import sys
        error_msg = f"Failed to decrypt data: {str(e)}"
        print(f"[ERROR] {error_msg}", file=sys.stderr)
        print(f"[ERROR] Data preview: {encrypted_data[:50]}...", file=sys.stderr)
        print(f"[ERROR] This usually means SECRET_KEY has changed or data is corrupted", file=sys.stderr)
        raise RuntimeError(error_msg)


def is_encrypted(data: str) -> bool:
    """检查数据是否已加密"""
    return data and data.startswith('enc:')


# ==================== 错误处理工具 ====================

def generate_trace_id() -> str:
    return uuid.uuid4().hex


def sanitize_error_details(details: Optional[str]) -> str:
    if not details:
        return ""
    sanitized = details
    patterns = [
        (r'(?i)(bearer\s+)[A-Za-z0-9\-._~\+/]+=*', r'\1***'),
        (r'(?i)(refresh_token|access_token|token|password|passwd|secret)\s*[:=]\s*\"?[A-Za-z0-9\-._~\+/]+=*\"?', r'\1=***'),
        (r'(?i)(\"refresh_token\"\s*:\s*\")[^\"]+(\"?)', r'\1***\2'),
        (r'(?i)(\"access_token\"\s*:\s*\")[^\"]+(\"?)', r'\1***\2'),
        (r'(?i)(\"password\"\s*:\s*\")[^\"]+(\"?)', r'\1***\2'),
        (r'(?i)(client_secret|refresh_token|access_token)=[^&\s]+', r'\1=***')
    ]
    for pattern, repl in patterns:
        sanitized = re.sub(pattern, repl, sanitized)
    return sanitized


def build_error_payload(
    code: str,
    message: str,
    err_type: str = "Error",
    status: int = 500,
    details: Any = None,
    trace_id: Optional[str] = None
) -> Dict[str, Any]:
    if details is not None and not isinstance(details, str):
        try:
            details = json.dumps(details, ensure_ascii=True)
        except Exception:
            details = str(details)
    sanitized_details = sanitize_error_details(details) if details else ""
    trace_id_value = trace_id or generate_trace_id()
    payload = {
        "code": code,
        "message": message,
        "type": err_type,
        "status": status,
        "details": sanitized_details,
        "trace_id": trace_id_value
    }
    try:
        app.logger.error(
            "trace_id=%s code=%s status=%s type=%s details=%s",
            trace_id_value,
            code,
            status,
            err_type,
            sanitized_details
        )
    except Exception:
        pass
    return payload


def get_response_details(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text or response.reason


# ==================== 数据库操作 ====================

def get_db():
    """获取数据库连接"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    """关闭数据库连接"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # 创建设置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建分组表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            color TEXT DEFAULT '#1a1a1a',
            sort_order INTEGER DEFAULT 0,
            is_system INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建邮箱账号表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT,
            client_id TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            group_id INTEGER,
            remark TEXT,
            status TEXT DEFAULT 'active',
            last_refresh_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )
    ''')
    
    # 创建临时邮箱表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建临时邮件表（存储从 GPTMail 获取的邮件）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_email_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            email_address TEXT NOT NULL,
            from_address TEXT,
            subject TEXT,
            content TEXT,
            html_content TEXT,
            has_html INTEGER DEFAULT 0,
            timestamp INTEGER,
            raw_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (email_address) REFERENCES temp_emails (email)
        )
    ''')

    # 创建账号刷新记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_refresh_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            account_email TEXT NOT NULL,
            refresh_type TEXT DEFAULT 'manual',
            status TEXT NOT NULL,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    ''')

    # 创建审计日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            user_ip TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建标签表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建账号标签关联表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_tags (
            account_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (account_id, tag_id),
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
        )
    ''')

    # 检查并添加缺失的列（数据库迁移）
    cursor.execute("PRAGMA table_info(accounts)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'group_id' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN group_id INTEGER DEFAULT 1')
    if 'remark' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN remark TEXT')
    if 'status' not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN status TEXT DEFAULT 'active'")
    if 'updated_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    if 'last_refresh_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN last_refresh_at TIMESTAMP')
    
    # 检查 groups 表是否有 is_system 列
    cursor.execute("PRAGMA table_info(groups)")
    group_columns = [col[1] for col in cursor.fetchall()]
    if 'sort_order' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN sort_order INTEGER DEFAULT 0')
    if 'is_system' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN is_system INTEGER DEFAULT 0')
    if 'proxy_url' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN proxy_url TEXT')

    # 检查 temp_emails 表是否有 DuckMail 相关列
    cursor.execute("PRAGMA table_info(temp_emails)")
    temp_columns = [col[1] for col in cursor.fetchall()]
    if 'provider' not in temp_columns:
        cursor.execute("ALTER TABLE temp_emails ADD COLUMN provider TEXT DEFAULT 'gptmail'")
    if 'duckmail_token' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN duckmail_token TEXT')
    if 'duckmail_account_id' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN duckmail_account_id TEXT')
    if 'duckmail_password' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN duckmail_password TEXT')
    if 'cloudflare_jwt' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN cloudflare_jwt TEXT')
    if 'cloudflare_address_id' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN cloudflare_address_id TEXT')
    
    # 创建默认分组
    cursor.execute('''
        INSERT OR IGNORE INTO groups (name, description, color)
        VALUES ('默认分组', '未分组的邮箱', '#666666')
    ''')
    
    # 创建临时邮箱分组（系统分组）
    cursor.execute('''
        INSERT OR IGNORE INTO groups (name, description, color, is_system)
        VALUES ('临时邮箱', 'GPTMail 临时邮箱服务', '#00bcf2', 1)
    ''')

    # 初始化分组排序值，保留已有顺序并确保临时邮箱固定在最前
    cursor.execute('SELECT id, name, sort_order FROM groups ORDER BY id')
    group_rows = cursor.fetchall()
    next_sort_order = 1
    for group_id, group_name, sort_order in group_rows:
        target_sort_order = 0 if group_name == '临时邮箱' else next_sort_order
        if group_name != '临时邮箱':
            next_sort_order += 1
        if sort_order != target_sort_order:
            cursor.execute(
                'UPDATE groups SET sort_order = ? WHERE id = ?',
                (target_sort_order, group_id)
            )
    
    # 初始化默认设置
    # 检查是否已有密码设置
    cursor.execute("SELECT value FROM settings WHERE key = 'login_password'")
    existing_password = cursor.fetchone()

    if existing_password:
        # 如果存在密码但是明文，则迁移为哈希
        password_value = existing_password[0]
        if not is_password_hashed(password_value):
            hashed_password = hash_password(password_value)
            cursor.execute('''
                UPDATE settings SET value = ? WHERE key = 'login_password'
            ''', (hashed_password,))
    else:
        # 首次初始化，哈希默认密码
        hashed_password = hash_password(LOGIN_PASSWORD)
        cursor.execute('''
            INSERT INTO settings (key, value)
            VALUES ('login_password', ?)
        ''', (hashed_password,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('gptmail_api_key', ?)
    ''', (GPTMAIL_API_KEY,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('duckmail_base_url', ?)
    ''', (DUCKMAIL_BASE_URL,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('duckmail_api_key', ?)
    ''', (DUCKMAIL_API_KEY,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_worker_domain', ?)
    ''', (CLOUDFLARE_WORKER_DOMAIN,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_email_domains', ?)
    ''', (CLOUDFLARE_EMAIL_DOMAINS,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_admin_password', ?)
    ''', (CLOUDFLARE_ADMIN_PASSWORD,))


    # 初始化刷新配置
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('refresh_interval_days', '30')
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('refresh_delay_seconds', '5')
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('refresh_cron', '0 2 * * *')
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('use_cron_schedule', 'false')
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('enable_scheduled_refresh', 'true')
    ''')

    # 创建索引以优化查询性能
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_last_refresh_at
        ON accounts(last_refresh_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_status
        ON accounts(status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_account_refresh_logs_account_id
        ON account_refresh_logs(account_id)
    ''')

    # 迁移现有明文数据为加密数据
    migrate_sensitive_data(conn)

    conn.commit()
    conn.close()


def migrate_sensitive_data(conn):
    """迁移现有明文敏感数据为加密数据"""
    cursor = conn.cursor()

    # 获取所有账号
    cursor.execute('SELECT id, password, refresh_token FROM accounts')
    accounts = cursor.fetchall()

    migrated_count = 0
    for account_id, password, refresh_token in accounts:
        needs_update = False
        new_password = password
        new_refresh_token = refresh_token

        # 检查并加密 password
        if password and not is_encrypted(password):
            new_password = encrypt_data(password)
            needs_update = True

        # 检查并加密 refresh_token
        if refresh_token and not is_encrypted(refresh_token):
            new_refresh_token = encrypt_data(refresh_token)
            needs_update = True

        # 更新数据库
        if needs_update:
            cursor.execute('''
                UPDATE accounts
                SET password = ?, refresh_token = ?
                WHERE id = ?
            ''', (new_password, new_refresh_token, account_id))
            migrated_count += 1

    if migrated_count > 0:
        print(f"已迁移 {migrated_count} 个账号的敏感数据为加密存储")


# ==================== 应用初始化 ====================

def init_app():
    """初始化应用（确保目录和数据库存在）"""
    # 确保 templates 目录存在
    os.makedirs('templates', exist_ok=True)
    
    # 确保数据目录存在
    data_dir = os.path.dirname(DATABASE)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    
    # 初始化数据库
    init_db()
    
    print("=" * 60)
    print("Outlook 邮件 Web 应用已初始化")
    print(f"数据库文件: {DATABASE}")
    print(f"GPTMail API: {GPTMAIL_BASE_URL}")
    print(f"DuckMail API: {DUCKMAIL_BASE_URL}")
    print(f"Cloudflare Temp Email Worker: {CLOUDFLARE_WORKER_DOMAIN or '未配置'}")
    print("=" * 60)


# 在模块加载时初始化应用
init_app()


# ==================== 设置操作 ====================

def get_setting(key: str, default: str = '') -> str:
    """获取设置值"""
    db = get_db()
    cursor = db.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    return row['value'] if row else default


def set_setting(key: str, value: str) -> bool:
    """设置值"""
    db = get_db()
    try:
        db.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))
        db.commit()
        return True
    except Exception:
        return False


def get_all_settings() -> Dict[str, str]:
    """获取所有设置"""
    db = get_db()
    cursor = db.execute('SELECT key, value FROM settings')
    rows = cursor.fetchall()
    return {row['key']: row['value'] for row in rows}


def get_login_password() -> str:
    """获取登录密码（优先从数据库读取）"""
    password = get_setting('login_password')
    return password if password else LOGIN_PASSWORD


def get_gptmail_api_key() -> str:
    """获取 GPTMail API Key（优先从数据库读取）"""
    api_key = get_setting('gptmail_api_key')
    return api_key if api_key else GPTMAIL_API_KEY


def get_external_api_key() -> str:
    """获取对外 API Key（从数据库读取，明文存储）"""
    return get_setting('external_api_key', '')


def get_duckmail_base_url() -> str:
    """获取 DuckMail API 基础 URL（优先从数据库读取）"""
    url = get_setting('duckmail_base_url')
    return url if url else DUCKMAIL_BASE_URL


def get_duckmail_api_key() -> str:
    """获取 DuckMail API Key（优先从数据库读取）"""
    api_key = get_setting('duckmail_api_key')
    return api_key if api_key else DUCKMAIL_API_KEY


def get_cloudflare_worker_domain() -> str:
    """获取 Cloudflare Temp Email Worker 域名"""
    domain = get_setting('cloudflare_worker_domain')
    return domain.strip() if domain else CLOUDFLARE_WORKER_DOMAIN.strip()


def get_cloudflare_email_domains() -> List[str]:
    """获取 Cloudflare Temp Email 可用域名列表"""
    raw_domains = get_setting('cloudflare_email_domains')
    value = raw_domains if raw_domains is not None else CLOUDFLARE_EMAIL_DOMAINS
    return [domain.strip() for domain in value.split(',') if domain.strip()]


def get_cloudflare_admin_password() -> str:
    """获取 Cloudflare Temp Email 管理密码"""
    password = get_setting('cloudflare_admin_password')
    return password if password is not None else CLOUDFLARE_ADMIN_PASSWORD


# ==================== 分组操作 ====================

def load_groups() -> List[Dict]:
    """加载所有分组（临时邮箱分组排在最前面）"""
    db = get_db()
    cursor = db.execute('''
        SELECT * FROM groups
        ORDER BY
            CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
            sort_order,
            id
    ''')
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_group_by_id(group_id: int) -> Optional[Dict]:
    """根据 ID 获取分组"""
    db = get_db()
    cursor = db.execute('SELECT * FROM groups WHERE id = ?', (group_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_movable_group_ids(db=None, exclude_group_id: Optional[int] = None) -> List[int]:
    """获取可排序分组 ID 列表（不含临时邮箱）"""
    database = db or get_db()
    query = '''
        SELECT id FROM groups
        WHERE name != '临时邮箱'
    '''
    params = []
    if exclude_group_id is not None:
        query += ' AND id != ?'
        params.append(exclude_group_id)
    query += ' ORDER BY sort_order, id'
    cursor = database.execute(query, tuple(params))
    return [row['id'] for row in cursor.fetchall()]


def apply_group_order(group_ids: List[int], db=None) -> None:
    """按给定顺序写入分组排序"""
    database = db or get_db()
    for index, group_id in enumerate(group_ids, start=1):
        database.execute('UPDATE groups SET sort_order = ? WHERE id = ?', (index, group_id))

    temp_group = database.execute(
        "SELECT id FROM groups WHERE name = '临时邮箱' LIMIT 1"
    ).fetchone()
    if temp_group:
        database.execute('UPDATE groups SET sort_order = 0 WHERE id = ?', (temp_group['id'],))


def normalize_group_order(db=None) -> None:
    """归一化分组顺序"""
    database = db or get_db()
    apply_group_order(get_movable_group_ids(database), database)


def clamp_group_position(sort_position: Optional[int], max_position: int) -> int:
    """限制分组位置范围，位置从 1 开始"""
    if max_position <= 0:
        return 1
    if sort_position is None:
        return max_position
    return max(1, min(sort_position, max_position))


def get_group_sort_position(group_id: int, db=None) -> Optional[int]:
    """获取分组在可排序列表中的位置（从 1 开始）"""
    group_ids = get_movable_group_ids(db)
    try:
        return group_ids.index(group_id) + 1
    except ValueError:
        return None


def set_group_position(group_id: int, sort_position: Optional[int], db=None) -> bool:
    """设置分组在可排序列表中的位置"""
    database = db or get_db()
    group = database.execute('SELECT id, name FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group or group['name'] == '临时邮箱':
        return False

    group_ids = get_movable_group_ids(database, exclude_group_id=group_id)
    target_position = clamp_group_position(sort_position, len(group_ids) + 1)
    group_ids.insert(target_position - 1, group_id)
    apply_group_order(group_ids, database)
    return True


def add_group(name: str, description: str = '', color: str = '#1a1a1a',
              proxy_url: str = '', sort_position: Optional[int] = None) -> Optional[int]:
    """添加分组"""
    db = get_db()
    try:
        cursor = db.execute(
            '''
            INSERT INTO groups (name, description, color, proxy_url, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (name, description, color, proxy_url or '', 999999)
        )
        group_id = cursor.lastrowid
        set_group_position(group_id, sort_position, db)
        db.commit()
        return group_id
    except sqlite3.IntegrityError:
        return None
    except Exception:
        return None


def update_group(group_id: int, name: str, description: str, color: str,
                 proxy_url: str = '', sort_position: Optional[int] = None) -> bool:
    """更新分组"""
    db = get_db()
    try:
        db.execute('''
            UPDATE groups SET name = ?, description = ?, color = ?, proxy_url = ?
            WHERE id = ?
        ''', (name, description, color, proxy_url or '', group_id))
        if not set_group_position(group_id, sort_position, db):
            return False
        db.commit()
        return True
    except Exception:
        return False


def delete_group(group_id: int) -> bool:
    """删除分组（将该分组下的邮箱移到默认分组）"""
    db = get_db()
    try:
        # 将该分组下的邮箱移到默认分组（id=1）
        db.execute('UPDATE accounts SET group_id = 1 WHERE group_id = ?', (group_id,))
        # 删除分组（不能删除默认分组）
        if group_id != 1:
            db.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        normalize_group_order(db)
        db.commit()
        return True
    except Exception:
        return False


def get_group_account_count(group_id: int) -> int:
    """获取分组下的邮箱数量"""
    db = get_db()
    cursor = db.execute('SELECT COUNT(*) as count FROM accounts WHERE group_id = ?', (group_id,))
    row = cursor.fetchone()
    return row['count'] if row else 0


def reorder_groups(group_ids: List[int]) -> bool:
    """重新排序分组，临时邮箱分组固定在最前面"""
    db = get_db()
    try:
        movable_ids = get_movable_group_ids(db)

        if set(group_ids) != set(movable_ids):
            return False

        apply_group_order(group_ids, db)
        db.commit()
        return True
    except Exception:
        return False


# ==================== 邮箱账号操作 ====================

def load_accounts(group_id: int = None) -> List[Dict]:
    """从数据库加载邮箱账号"""
    db = get_db()
    if group_id:
        cursor = db.execute('''
            SELECT a.*, g.name as group_name, g.color as group_color
            FROM accounts a
            LEFT JOIN groups g ON a.group_id = g.id
            WHERE a.group_id = ?
            ORDER BY a.created_at DESC
        ''', (group_id,))
    else:
        cursor = db.execute('''
            SELECT a.*, g.name as group_name, g.color as group_color
            FROM accounts a
            LEFT JOIN groups g ON a.group_id = g.id
            ORDER BY a.created_at DESC
        ''')
    rows = cursor.fetchall()
    accounts = []
    for row in rows:
        account = dict(row)
        # 解密敏感字段
        if account.get('password'):
            try:
                account['password'] = decrypt_data(account['password'])
            except Exception:
                pass  # 解密失败保持原值
        if account.get('refresh_token'):
            try:
                account['refresh_token'] = decrypt_data(account['refresh_token'])
            except Exception:
                pass  # 解密失败保持原值
        
        # 加载账号标签
        account['tags'] = get_account_tags(account['id'])
        accounts.append(account)
    return accounts


# ==================== 标签管理 ====================

def get_tags() -> List[Dict]:
    """获取所有标签"""
    db = get_db()
    cursor = db.execute('SELECT * FROM tags ORDER BY created_at DESC')
    return [dict(row) for row in cursor.fetchall()]


def add_tag(name: str, color: str) -> Optional[int]:
    """添加标签"""
    db = get_db()
    try:
        cursor = db.execute(
            'INSERT INTO tags (name, color) VALUES (?, ?)',
            (name, color)
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def delete_tag(tag_id: int) -> bool:
    """删除标签"""
    db = get_db()
    cursor = db.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
    db.commit()
    return cursor.rowcount > 0


def get_account_tags(account_id: int) -> List[Dict]:
    """获取账号的标签"""
    db = get_db()
    cursor = db.execute('''
        SELECT t.*
        FROM tags t
        JOIN account_tags at ON t.id = at.tag_id
        WHERE at.account_id = ?
        ORDER BY t.created_at DESC
    ''', (account_id,))
    return [dict(row) for row in cursor.fetchall()]


def add_account_tag(account_id: int, tag_id: int) -> bool:
    """给账号添加标签"""
    db = get_db()
    try:
        db.execute(
            'INSERT OR IGNORE INTO account_tags (account_id, tag_id) VALUES (?, ?)',
            (account_id, tag_id)
        )
        db.commit()
        return True
    except Exception:
        return False


def remove_account_tag(account_id: int, tag_id: int) -> bool:
    """移除账号标签"""
    db = get_db()
    db.execute(
        'DELETE FROM account_tags WHERE account_id = ? AND tag_id = ?',
        (account_id, tag_id)
    )
    db.commit()
    return True



def get_account_by_email(email_addr: str) -> Optional[Dict]:
    """根据邮箱地址获取账号"""
    db = get_db()
    cursor = db.execute('SELECT * FROM accounts WHERE email = ?', (email_addr,))
    row = cursor.fetchone()
    if not row:
        return None
    account = dict(row)
    # 解密敏感字段
    if account.get('password'):
        try:
            account['password'] = decrypt_data(account['password'])
        except Exception:
            pass
    if account.get('refresh_token'):
        try:
            account['refresh_token'] = decrypt_data(account['refresh_token'])
        except Exception:
            pass
    return account


def get_account_by_id(account_id: int) -> Optional[Dict]:
    """根据 ID 获取账号"""
    db = get_db()
    cursor = db.execute('''
        SELECT a.*, g.name as group_name, g.color as group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        WHERE a.id = ?
    ''', (account_id,))
    row = cursor.fetchone()
    if not row:
        return None
    account = dict(row)
    # 解密敏感字段
    if account.get('password'):
        try:
            account['password'] = decrypt_data(account['password'])
        except Exception:
            pass
    if account.get('refresh_token'):
        try:
            account['refresh_token'] = decrypt_data(account['refresh_token'])
        except Exception:
            pass
    return account


def add_account(email_addr: str, password: str, client_id: str, refresh_token: str,
                group_id: int = 1, remark: str = '') -> bool:
    """添加邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token

        db.execute('''
            INSERT INTO accounts (email, password, client_id, refresh_token, group_id, remark)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_account(account_id: int, email_addr: str, password: str, client_id: str,
                   refresh_token: str, group_id: int, remark: str, status: str) -> bool:
    """更新邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token

        db.execute('''
            UPDATE accounts
            SET email = ?, password = ?, client_id = ?, refresh_token = ?,
                group_id = ?, remark = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark, status, account_id))
        db.commit()
        return True
    except Exception:
        return False


def delete_account_by_id(account_id: int) -> bool:
    """删除邮箱账号"""
    db = get_db()
    try:
        db.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
        db.commit()
        return True
    except Exception:
        return False


def delete_account_by_email(email_addr: str) -> bool:
    """根据邮箱地址删除账号"""
    db = get_db()
    try:
        db.execute('DELETE FROM accounts WHERE email = ?', (email_addr,))
        db.commit()
        return True
    except Exception:
        return False


# ==================== 工具函数 ====================

def sanitize_input(text: str, max_length: int = 500) -> str:
    """
    净化用户输入，防止XSS攻击
    - 转义HTML特殊字符
    - 限制长度
    - 移除控制字符
    """
    if not text:
        return ""

    # 限制长度
    text = text[:max_length]

    # 移除控制字符（保留换行和制表符）
    text = ''.join(char for char in text if char.isprintable() or char in '\n\t')

    # 转义HTML特殊字符
    text = html.escape(text, quote=True)

    return text


def log_audit(action: str, resource_type: str, resource_id: str = None, details: str = None):
    """
    记录审计日志
    :param action: 操作类型（如 'export', 'delete', 'update'）
    :param resource_type: 资源类型（如 'account', 'group'）
    :param resource_id: 资源ID
    :param details: 详细信息
    """
    try:
        db = get_db()
        user_ip = request.remote_addr if request else 'unknown'
        db.execute('''
            INSERT INTO audit_logs (action, resource_type, resource_id, user_ip, details)
            VALUES (?, ?, ?, ?, ?)
        ''', (action, resource_type, resource_id, user_ip, details))
        db.commit()
    except Exception:
        # 审计日志失败不应影响主流程
        pass


def decode_header_value(header_value: str) -> str:
    """解码邮件头字段"""
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(str(header_value))
        decoded_string = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try:
                    decoded_string += part.decode(charset if charset else 'utf-8', 'replace')
                except (LookupError, UnicodeDecodeError):
                    decoded_string += part.decode('utf-8', 'replace')
            else:
                decoded_string += str(part)
        return decoded_string
    except Exception:
        return str(header_value) if header_value else ""


def get_email_body(msg) -> str:
    """提取邮件正文"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='replace')
                    break
                except Exception:
                    continue
            elif content_type == "text/html" and "attachment" not in content_disposition and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='replace')
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            body = payload.decode(charset, errors='replace')
        except Exception:
            body = str(msg.get_payload())
    
    return body


def get_email_html_body(msg) -> str:
    """提取邮件 HTML 正文"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/html" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='replace')
                except Exception:
                    continue
    elif msg.get_content_type() == "text/html":
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            return payload.decode(charset, errors='replace')
        except Exception:
            return ""

    return ""


def generate_random_temp_name() -> str:
    """生成临时邮箱用户名"""
    return f"{secrets.token_hex(3)}{secrets.randbelow(1000)}"


def build_cloudflare_domain_candidates(domain: str) -> List[str]:
    """为 Cloudflare 创建邮箱生成可回退的域名候选列表"""
    normalized = domain.strip().lower().lstrip('@').rstrip('.')
    if not normalized:
        return []

    candidates: List[str] = [normalized]
    labels = [label for label in normalized.split('.') if label]
    if len(labels) < 3:
        return candidates

    common_second_level_suffixes = {
        'com.cn', 'net.cn', 'org.cn', 'gov.cn', 'edu.cn',
        'co.uk', 'org.uk', 'ac.uk',
        'com.hk', 'com.sg',
        'com.au', 'net.au', 'org.au',
        'co.jp'
    }

    last_two = '.'.join(labels[-2:])
    last_three = '.'.join(labels[-3:]) if len(labels) >= 3 else ''

    if last_three and last_two in common_second_level_suffixes:
        if last_three not in candidates:
            candidates.append(last_three)
    elif last_two not in candidates:
        candidates.append(last_two)

    if last_three and last_three not in candidates:
        candidates.append(last_three)

    return candidates


def parse_raw_email_to_temp_message(email_addr: str, raw_email: str, fallback_id: str = None,
                                    fallback_timestamp: int = 0) -> Dict[str, Any]:
    """将原始邮件解析为统一的临时邮箱消息格式"""
    if isinstance(raw_email, str):
        msg = email.message_from_string(raw_email)
    else:
        msg = email.message_from_bytes(raw_email)

    text_content = get_email_body(msg)
    html_content = get_email_html_body(msg)
    message_id = decode_header_value(msg.get('Message-ID', '')).strip()
    date_header = decode_header_value(msg.get('Date', '')).strip()
    timestamp = fallback_timestamp

    if date_header:
        try:
            parsed_date = email.utils.parsedate_to_datetime(date_header)
            timestamp = int(parsed_date.timestamp())
        except Exception:
            pass

    final_message_id = (
        fallback_id
        or message_id
        or hashlib.sha256(f"{email_addr}\n{raw_email}".encode('utf-8', 'replace')).hexdigest()
    )

    return {
        'id': final_message_id,
        'from_address': decode_header_value(msg.get('From', '未知发件人')),
        'subject': decode_header_value(msg.get('Subject', '无主题')),
        'content': text_content,
        'html_content': html_content,
        'has_html': bool(html_content),
        'timestamp': timestamp,
        'raw_content': raw_email if isinstance(raw_email, str) else raw_email.decode('utf-8', 'replace')
    }


# 重写导入解析函数，支持多种账号字段顺序
def parse_account_string(account_str: str, account_format: str = 'client_id_refresh_token') -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 4 or not parts[0]:
        return None

    email_addr, password, third, fourth = parts[:4]

    if account_format == 'refresh_token_client_id':
        refresh_token = third
        client_id = fourth
    else:
        client_id = third
        refresh_token = fourth

    if not client_id or not refresh_token:
        return None

    return {
        'email': email_addr,
        'password': password,
        'client_id': client_id,
        'refresh_token': refresh_token
    }


# ==================== Graph API 方式 ====================


def build_proxies(proxy_url: str) -> Optional[Dict[str, str]]:
    """构建 requests 的 proxies 参数"""
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def get_access_token_graph_result(client_id: str, refresh_token: str, proxy_url: str = None) -> Dict[str, Any]:
    """获取 Graph API access_token（包含错误详情）"""
    try:
        proxies = build_proxies(proxy_url)
        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30,
            proxies=proxies
        )

        if res.status_code != 200:
            details = get_response_details(res)
            return {
                "success": False,
                "error": build_error_payload(
                    "GRAPH_TOKEN_FAILED",
                    "获取访问令牌失败",
                    "GraphAPIError",
                    res.status_code,
                    details
                )
            }

        payload = res.json()
        access_token = payload.get("access_token")
        if not access_token:
            return {
                "success": False,
                "error": build_error_payload(
                    "GRAPH_TOKEN_MISSING",
                    "获取访问令牌失败",
                    "GraphAPIError",
                    res.status_code,
                    payload
                )
            }

        return {"success": True, "access_token": access_token}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "GRAPH_TOKEN_EXCEPTION",
                "获取访问令牌失败",
                type(exc).__name__,
                500,
                str(exc)
            )
        }


def get_access_token_graph(client_id: str, refresh_token: str, proxy_url: str = None) -> Optional[str]:
    """获取 Graph API access_token"""
    result = get_access_token_graph_result(client_id, refresh_token, proxy_url)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_graph(client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20, proxy_url: str = None) -> Dict[str, Any]:
    """使用 Graph API 获取邮件列表（支持分页和文件夹选择）"""
    token_result = get_access_token_graph_result(client_id, refresh_token, proxy_url)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    try:
        # 根据文件夹类型选择 API 端点
        # 使用 Well-known folder names，这些是 Microsoft Graph API 的标准文件夹名称
        folder_map = {
            'inbox': 'inbox',
            'junkemail': 'junkemail',  # 垃圾邮件的标准名称
            'deleteditems': 'deleteditems',  # 已删除邮件的标准名称
            'trash': 'deleteditems'  # 垃圾箱的别名
        }
        folder_name = folder_map.get(folder.lower(), 'inbox')

        url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder_name}/messages"
        params = {
            "$top": top,
            "$skip": skip,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview",
            "$orderby": "receivedDateTime desc"
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": "outlook.body-content-type='text'"
        }

        proxies = build_proxies(proxy_url)
        res = requests.get(url, headers=headers, params=params, timeout=30, proxies=proxies)

        if res.status_code != 200:
            details = get_response_details(res)
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    "获取邮件失败，请检查账号配置",
                    "GraphAPIError",
                    res.status_code,
                    details
                )
            }

        return {"success": True, "emails": res.json().get("value", [])}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "EMAIL_FETCH_FAILED",
                "获取邮件失败，请检查账号配置",
                type(exc).__name__,
                500,
                str(exc)
            )
        }


def get_email_detail_graph(client_id: str, refresh_token: str, message_id: str, proxy_url: str = None) -> Optional[Dict]:
    """使用 Graph API 获取邮件详情"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url)
    if not access_token:
        return None
    
    try:
        url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}"
        params = {
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,body,bodyPreview"
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": "outlook.body-content-type='html'"
        }
        
        proxies = build_proxies(proxy_url)
        res = requests.get(url, headers=headers, params=params, timeout=30, proxies=proxies)
        
        if res.status_code != 200:
            return None
        
        return res.json()
    except Exception:
        return None


# ==================== IMAP 方式 ====================

def get_access_token_imap_result(client_id: str, refresh_token: str) -> Dict[str, Any]:
    """获取 IMAP access_token（包含错误详情）"""
    try:
        res = requests.post(
            TOKEN_URL_IMAP,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
            },
            timeout=30
        )

        if res.status_code != 200:
            details = get_response_details(res)
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_TOKEN_FAILED",
                    "获取访问令牌失败",
                    "IMAPError",
                    res.status_code,
                    details
                )
            }

        payload = res.json()
        access_token = payload.get("access_token")
        if not access_token:
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_TOKEN_MISSING",
                    "获取访问令牌失败",
                    "IMAPError",
                    res.status_code,
                    payload
                )
            }

        return {"success": True, "access_token": access_token}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "IMAP_TOKEN_EXCEPTION",
                "获取访问令牌失败",
                type(exc).__name__,
                500,
                str(exc)
            )
        }


def get_access_token_imap(client_id: str, refresh_token: str) -> Optional[str]:
    """获取 IMAP access_token"""
    result = get_access_token_imap_result(client_id, refresh_token)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_imap(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页和文件夹选择）- 默认使用新版服务器"""
    return get_emails_imap_with_server(account, client_id, refresh_token, folder, skip, top, IMAP_SERVER_NEW)


def get_emails_imap_with_server(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20, server: str = IMAP_SERVER_NEW) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页、文件夹选择和服务器选择）"""
    token_result = get_access_token_imap_result(client_id, refresh_token)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    connection = None
    try:
        connection = imaplib.IMAP4_SSL(server, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        # 根据文件夹类型选择 IMAP 文件夹
        # 尝试多种可能的文件夹名称
        folder_map = {
            'inbox': ['"INBOX"', 'INBOX'],
            'junkemail': ['"Junk"', '"Junk Email"', 'Junk', '"垃圾邮件"'],
            'deleteditems': ['"Deleted"', '"Deleted Items"', '"Trash"', 'Deleted', '"已删除邮件"'],
            'trash': ['"Deleted"', '"Deleted Items"', '"Trash"', 'Deleted', '"已删除邮件"']
        }
        possible_folders = folder_map.get(folder.lower(), ['"INBOX"'])

        # 尝试选择文件夹
        selected_folder = None
        last_error = None
        for imap_folder in possible_folders:
            try:
                status, response = connection.select(imap_folder, readonly=True)
                if status == 'OK':
                    selected_folder = imap_folder
                    break
                else:
                    last_error = f"select {imap_folder} status={status}"
            except Exception as e:
                last_error = f"select {imap_folder} error={str(e)}"
                continue

        if not selected_folder:
            # 如果所有尝试都失败，列出所有可用文件夹以便调试
            try:
                status, folder_list = connection.list()
                available_folders = []
                if status == 'OK' and folder_list:
                    for folder_item in folder_list:
                        if isinstance(folder_item, bytes):
                            available_folders.append(folder_item.decode('utf-8', errors='ignore'))
                        else:
                            available_folders.append(str(folder_item))
                
                error_details = {
                    "last_error": last_error,
                    "tried_folders": possible_folders,
                    "available_folders": available_folders[:10]  # 只返回前10个
                }
            except Exception:
                error_details = {
                    "last_error": last_error,
                    "tried_folders": possible_folders
                }

            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    f"无法访问文件夹，请检查账号配置",
                    "IMAPSelectError",
                    500,
                    error_details
                )
            }

        status, messages = connection.search(None, 'ALL')
        if status != 'OK':
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    "获取邮件失败，请检查账号配置",
                    "IMAPSearchError",
                    500,
                    f"search status={status}"
                )
            }
        if not messages or not messages[0]:
            return {"success": True, "emails": []}

        message_ids = messages[0].split()
        # 计算分页范围
        total = len(message_ids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip

        if start_idx >= end_idx:
            return {"success": True, "emails": []}

        paged_ids = message_ids[start_idx:end_idx][::-1]  # 倒序，最新的在前

        emails = []
        for msg_id in paged_ids:
            try:
                status, msg_data = connection.fetch(msg_id, '(RFC822)')
                if status == 'OK' and msg_data and msg_data[0]:
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    emails.append({
                        'id': msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        'subject': decode_header_value(msg.get("Subject", "无主题")),
                        'from': decode_header_value(msg.get("From", "未知发件人")),
                        'date': msg.get("Date", "未知时间"),
                        'body_preview': get_email_body(msg)[:200] + "..." if len(get_email_body(msg)) > 200 else get_email_body(msg)
                    })
            except Exception:
                continue

        return {"success": True, "emails": emails}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "EMAIL_FETCH_FAILED",
                "获取邮件失败，请检查账号配置",
                type(exc).__name__,
                500,
                str(exc)
            )
        }
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def get_email_detail_imap(account: str, client_id: str, refresh_token: str, message_id: str, folder: str = 'inbox') -> Optional[Dict]:
    """使用 IMAP 获取邮件详情"""
    access_token = get_access_token_imap(client_id, refresh_token)
    if not access_token:
        return None

    connection = None
    try:
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        # 根据文件夹类型选择 IMAP 文件夹
        folder_map = {
            'inbox': ['"INBOX"', 'INBOX'],
            'junkemail': ['"Junk"', '"Junk Email"', 'Junk', '"垃圾邮件"'],
            'deleteditems': ['"Deleted"', '"Deleted Items"', '"Trash"', 'Deleted', '"已删除邮件"'],
            'trash': ['"Deleted"', '"Deleted Items"', '"Trash"', 'Deleted', '"已删除邮件"']
        }
        possible_folders = folder_map.get(folder.lower(), ['"INBOX"'])

        # 尝试选择文件夹
        selected_folder = None
        for imap_folder in possible_folders:
            try:
                status, response = connection.select(imap_folder, readonly=True)
                if status == 'OK':
                    selected_folder = imap_folder
                    break
            except Exception:
                continue

        if not selected_folder:
            return None

        status, msg_data = connection.fetch(message_id.encode() if isinstance(message_id, str) else message_id, '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            return None

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        return {
            'id': message_id,
            'subject': decode_header_value(msg.get("Subject", "无主题")),
            'from': decode_header_value(msg.get("From", "未知发件人")),
            'to': decode_header_value(msg.get("To", "")),
            'cc': decode_header_value(msg.get("Cc", "")),
            'date': msg.get("Date", "未知时间"),
            'body': get_email_body(msg)
        }
    except Exception:
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


# ==================== 登录验证 ====================

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': '请先登录', 'need_login': True}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def api_key_required(f):
    """API Key 验证装饰器（用于对外 API）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从 Header 或查询参数获取 API Key
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key') or request.args.get('apikey')
        if not api_key:
            return jsonify({'success': False, 'error': '缺少 API Key，请通过 Header X-API-Key 或查询参数 api_key 提供'}), 401

        # 验证 API Key
        stored_key = get_external_api_key()
        if not stored_key:
            return jsonify({'success': False, 'error': '未配置对外 API Key，请在系统设置中配置'}), 403

        if api_key != stored_key:
            return jsonify({'success': False, 'error': 'API Key 无效'}), 401

        return f(*args, **kwargs)
    return decorated_function


# ==================== Flask 路由 ====================

@app.route('/login', methods=['GET', 'POST'])
@csrf_exempt  # 登录接口排除CSRF保护（用户未登录时无法获取token）
def login():
    """登录页面"""
    if request.method == 'POST':
        try:
            # 获取客户端 IP
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(',')[0].strip()

            # 检查速率限制
            allowed, remaining_time = check_rate_limit(client_ip)
            if not allowed:
                return jsonify({
                    'success': False,
                    'error': f'登录失败次数过多，请在 {remaining_time} 秒后重试'
                }), 429

            data = request.json if request.is_json else request.form
            password = data.get('password', '')

            # 从数据库获取密码哈希
            stored_password = get_login_password()

            # 验证密码
            if verify_password(password, stored_password):
                # 登录成功，重置失败记录
                reset_login_attempts(client_ip)
                session['logged_in'] = True
                session.permanent = True
                session.modified = True  # 确保 Flask-Session 保存 session
                return jsonify({'success': True, 'message': '登录成功'})
            else:
                # 登录失败，记录失败次数
                record_login_failure(client_ip)
                return jsonify({'success': False, 'error': '密码错误'})
        except Exception as e:
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'登录处理失败: {str(e)}'}), 500

    # GET 请求返回登录页面
    return render_template('login.html')


@app.route('/logout')
def logout():
    """退出登录"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/favicon.ico')
def favicon():
    """返回内联 SVG favicon，避免 500 错误"""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <rect width="100" height="100" rx="20" fill="#1a1a1a"/>
        <text x="50" y="55" font-size="60" text-anchor="middle" dominant-baseline="middle">📧</text>
    </svg>'''
    response = make_response(svg)
    response.headers['Content-Type'] = 'image/svg+xml'
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    return response


@app.route('/')
@login_required
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/csrf-token', methods=['GET'])
@csrf_exempt  # CSRF token获取接口排除CSRF保护
def get_csrf_token():
    """获取CSRF Token"""
    if CSRF_AVAILABLE:
        token = generate_csrf()
        return jsonify({'csrf_token': token})
    else:
        return jsonify({'csrf_token': None, 'csrf_disabled': True})


# ==================== 分组 API ====================

@app.route('/api/groups', methods=['GET'])
@login_required
def api_get_groups():
    """获取所有分组"""
    groups = load_groups()
    movable_position = 1
    # 添加每个分组的邮箱数量
    for group in groups:
        if group['name'] == '临时邮箱':
            # 临时邮箱分组从 temp_emails 表获取数量
            group['account_count'] = get_temp_email_count()
            group['sort_position'] = None
        else:
            group['account_count'] = get_group_account_count(group['id'])
            group['sort_position'] = movable_position
            movable_position += 1
    return jsonify({'success': True, 'groups': groups})


@app.route('/api/groups/<int:group_id>', methods=['GET'])
@login_required
def api_get_group(group_id):
    """获取单个分组"""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})
    group['account_count'] = get_group_account_count(group_id)
    group['sort_position'] = get_group_sort_position(group_id)
    return jsonify({'success': True, 'group': group})


@app.route('/api/groups', methods=['POST'])
@login_required
def api_add_group():
    """添加分组"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=100)
    description = sanitize_input(data.get('description', ''), max_length=500)
    color = data.get('color', '#1a1a1a')
    proxy_url = data.get('proxy_url', '').strip()
    sort_position_raw = data.get('sort_position')

    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})

    try:
        sort_position = int(sort_position_raw) if sort_position_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '排序位置无效'})

    group_id = add_group(name, description, color, proxy_url, sort_position)
    if group_id:
        return jsonify({'success': True, 'message': '分组创建成功', 'group_id': group_id})
    else:
        return jsonify({'success': False, 'error': '分组名称已存在'})


@app.route('/api/groups/<int:group_id>', methods=['PUT'])
@login_required
def api_update_group(group_id):
    """更新分组"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=100)
    description = sanitize_input(data.get('description', ''), max_length=500)
    color = data.get('color', '#1a1a1a')
    proxy_url = data.get('proxy_url', '').strip()
    sort_position_raw = data.get('sort_position')

    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})

    try:
        sort_position = int(sort_position_raw) if sort_position_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '排序位置无效'})

    if update_group(group_id, name, description, color, proxy_url, sort_position):
        return jsonify({'success': True, 'message': '分组更新成功'})
    else:
        return jsonify({'success': False, 'error': '更新失败'})


@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
@login_required
def api_delete_group(group_id):
    """删除分组"""
    if group_id == 1:
        return jsonify({'success': False, 'error': '默认分组不能删除'})
    
    if delete_group(group_id):
        return jsonify({'success': True, 'message': '分组已删除，邮箱已移至默认分组'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/groups/reorder', methods=['PUT'])
@login_required
def api_reorder_groups():
    """重新排序分组"""
    data = request.json or {}
    group_ids = data.get('group_ids', [])

    if not isinstance(group_ids, list) or not all(isinstance(group_id, int) for group_id in group_ids):
        return jsonify({'success': False, 'error': '分组排序参数无效'})

    if reorder_groups(group_ids):
        return jsonify({'success': True, 'message': '分组排序已更新'})
    else:
        return jsonify({'success': False, 'error': '分组排序失败'})


@app.route('/api/groups/<int:group_id>/export')
@login_required
def api_export_group(group_id):
    """导出分组下的所有邮箱账号为 TXT 文件（需要二次验证）"""
    # 检查二次验证token（使用内存存储）
    verify_token = request.args.get('verify_token')
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})

    lines = []
    is_temp_group = group['name'] == '临时邮箱'

    if is_temp_group:
        # 临时邮箱分组从 temp_emails 表获取数据
        temp_emails = load_temp_emails()
        if not temp_emails:
            return jsonify({'success': False, 'error': '该分组下没有临时邮箱'})

        lines.append(group['name'])

        # 按渠道分组
        gptmail_list = [te for te in temp_emails if te.get('provider', 'gptmail') == 'gptmail']
        duckmail_list = [te for te in temp_emails if te.get('provider') == 'duckmail']
        cloudflare_list = [te for te in temp_emails if te.get('provider') == 'cloudflare']

        if gptmail_list:
            lines.append('[gptmail]')
            for te in gptmail_list:
                lines.append(te['email'])

        if duckmail_list:
            lines.append('[duckmail]')
            for te in duckmail_list:
                duckmail_password = decrypt_data(te.get('duckmail_password', '')) if te.get('duckmail_password') else ''
                lines.append(f"{te['email']}----{duckmail_password}")

        if cloudflare_list:
            lines.append('[cloudflare]')
            for te in cloudflare_list:
                cloudflare_jwt = decrypt_data(te.get('cloudflare_jwt', '')) if te.get('cloudflare_jwt') else ''
                lines.append(f"{te['email']}----{cloudflare_jwt}")

        log_audit('export', 'group', str(group_id), f"导出临时邮箱分组的 {len(temp_emails)} 个临时邮箱")
    else:
        # 普通分组从 accounts 表获取数据
        accounts = load_accounts(group_id)
        if not accounts:
            return jsonify({'success': False, 'error': '该分组下没有邮箱账号'})

        lines.append(group['name'])
        log_audit('export', 'group', str(group_id), f"导出分组 '{group['name']}' 的 {len(accounts)} 个账号")

        for acc in accounts:
            line = f"{acc['email']}----{acc.get('password', '')}----{acc['client_id']}----{acc['refresh_token']}"
            lines.append(line)

    content = '\n'.join(lines)

    # 生成文件名（使用 URL 编码处理中文）
    filename = f"{group['name']}_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.route('/api/accounts/export')
@login_required
def api_export_all_accounts():
    """导出所有邮箱账号为 TXT 文件（需要二次验证）"""
    # 检查二次验证token（使用内存存储）
    verify_token = request.args.get('verify_token')
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]


    # 使用 load_accounts 获取所有账号（自动解密）
    accounts = load_accounts()

    if not accounts:
        return jsonify({'success': False, 'error': '没有邮箱账号'})

    # 记录审计日志
    log_audit('export', 'all_accounts', None, f"导出所有账号，共 {len(accounts)} 个")

    # 生成导出内容（格式：email----password----client_id----refresh_token）
    lines = []
    for acc in accounts:
        line = f"{acc['email']}----{acc.get('password', '')}----{acc['client_id']}----{acc['refresh_token']}"
        lines.append(line)

    content = '\n'.join(lines)

    # 生成文件名（使用 URL 编码处理中文）
    filename = f"all_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.route('/api/accounts/export-selected', methods=['POST'])
@login_required
def api_export_selected_accounts():
    """导出选中分组的邮箱账号为 TXT 文件（需要二次验证）"""
    data = request.json
    group_ids = data.get('group_ids', [])
    verify_token = data.get('verify_token')

    # 检查二次验证token（使用内存存储）
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    
    # 检查是否过期
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 可选：验证 IP 一致性（增强安全性）
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    # 注意：由于 Cloudflare 可能使用不同边缘节点，IP 可能变化，暂不强制验证
    # if token_data['ip'] != client_ip:
    #     return jsonify({'success': False, 'error': 'IP 不匹配', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]

    if not group_ids:
        return jsonify({'success': False, 'error': '请选择要导出的分组'})

    # 获取选中分组下的所有账号
    all_lines = []
    total_count = 0
    for group_id in group_ids:
        group = get_group_by_id(group_id)
        if not group:
            continue

        if group['name'] == '临时邮箱':
            # 临时邮箱分组从 temp_emails 表获取数据
            temp_emails = load_temp_emails()
            if temp_emails:
                all_lines.append(group['name'])

                gptmail_list = [te for te in temp_emails if te.get('provider', 'gptmail') == 'gptmail']
                duckmail_list = [te for te in temp_emails if te.get('provider') == 'duckmail']
                cloudflare_list = [te for te in temp_emails if te.get('provider') == 'cloudflare']

                if gptmail_list:
                    all_lines.append('[gptmail]')
                    for te in gptmail_list:
                        all_lines.append(te['email'])
                        total_count += 1

                if duckmail_list:
                    all_lines.append('[duckmail]')
                    for te in duckmail_list:
                        duckmail_password = decrypt_data(te.get('duckmail_password', '')) if te.get('duckmail_password') else ''
                        all_lines.append(f"{te['email']}----{duckmail_password}")
                        total_count += 1

                if cloudflare_list:
                    all_lines.append('[cloudflare]')
                    for te in cloudflare_list:
                        cloudflare_jwt = decrypt_data(te.get('cloudflare_jwt', '')) if te.get('cloudflare_jwt') else ''
                        all_lines.append(f"{te['email']}----{cloudflare_jwt}")
                        total_count += 1
        else:
            accounts = load_accounts(group_id)
            if accounts:
                all_lines.append(group['name'])
                for acc in accounts:
                    line = f"{acc['email']}----{acc.get('password', '')}----{acc['client_id']}----{acc['refresh_token']}"
                    all_lines.append(line)
                    total_count += 1

    if total_count == 0:
        return jsonify({'success': False, 'error': '选中的分组下没有邮箱账号'})

    # 记录审计日志
    log_audit('export', 'selected_groups', ','.join(map(str, group_ids)), f"导出选中分组的 {total_count} 个账号")

    content = '\n'.join(all_lines)

    # 生成文件名
    filename = f"selected_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.route('/api/export/verify', methods=['POST'])
@login_required
def api_generate_export_verify_token():
    """生成导出验证token（二次验证）"""
    data = request.json
    password = data.get('password', '')

    # 验证密码
    db = get_db()
    cursor = db.execute("SELECT value FROM settings WHERE key = 'login_password'")
    result = cursor.fetchone()

    if not result:
        return jsonify({'success': False, 'error': '系统配置错误'})

    stored_password = result[0]
    if not verify_password(password, stored_password):
        return jsonify({'success': False, 'error': '密码错误'})

    # 生成一次性验证token
    verify_token = secrets.token_urlsafe(32)
    
    # 使用 IP + 时间戳 作为用户标识（因为 session cookie 可能不可靠）
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    # 存储到内存字典（设置5分钟过期）
    import time
    export_verify_tokens[verify_token] = {
        'ip': client_ip,
        'expires': time.time() + 300  # 5分钟有效期
    }
    
    # 清理过期的 token
    current_time = time.time()
    expired_tokens = [k for k, v in export_verify_tokens.items() if v['expires'] < current_time]
    for token in expired_tokens:
        del export_verify_tokens[token]

    return jsonify({'success': True, 'verify_token': verify_token})


# ==================== 邮箱账号 API ====================

@app.route('/api/accounts', methods=['GET'])
@login_required
def api_get_accounts():
    """获取所有账号"""
    group_id = request.args.get('group_id', type=int)
    accounts = load_accounts(group_id)

    # 获取每个账号的最后刷新状态
    db = get_db()

    # 返回时隐藏敏感信息
    safe_accounts = []
    for acc in accounts:
        # 查询该账号最后一次刷新记录
        cursor = db.execute('''
            SELECT status, error_message, created_at
            FROM account_refresh_logs
            WHERE account_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (acc['id'],))
        last_refresh_log = cursor.fetchone()

        safe_accounts.append({
            'id': acc['id'],
            'email': acc['email'],
            'client_id': acc['client_id'][:8] + '...' if len(acc['client_id']) > 8 else acc['client_id'],
            'group_id': acc.get('group_id'),
            'group_name': acc.get('group_name', '默认分组'),
            'group_color': acc.get('group_color', '#666666'),
            'remark': acc.get('remark', ''),
            'status': acc.get('status', 'active'),
            'last_refresh_at': acc.get('last_refresh_at', ''),
            'last_refresh_status': last_refresh_log['status'] if last_refresh_log else None,
            'last_refresh_error': last_refresh_log['error_message'] if last_refresh_log else None,
            'created_at': acc.get('created_at', ''),
            'updated_at': acc.get('updated_at', ''),
            'tags': acc.get('tags', [])
        })
    return jsonify({'success': True, 'accounts': safe_accounts})


# ==================== 标签 API ====================

@app.route('/api/tags', methods=['GET'])
@login_required
def api_get_tags():
    """获取所有标签"""
    return jsonify({'success': True, 'tags': get_tags()})


@app.route('/api/tags', methods=['POST'])
@login_required
def api_add_tag():
    """添加标签"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=50)
    color = data.get('color', '#1a1a1a')

    if not name:
        return jsonify({'success': False, 'error': '标签名称不能为空'})

    tag_id = add_tag(name, color)
    if tag_id:
        return jsonify({'success': True, 'tag': {'id': tag_id, 'name': name, 'color': color}})
    else:
        return jsonify({'success': False, 'error': '标签名称已存在'})


@app.route('/api/tags/<int:tag_id>', methods=['DELETE'])
@login_required
def api_delete_tag(tag_id):
    """删除标签"""
    if delete_tag(tag_id):
        return jsonify({'success': True, 'message': '标签已删除'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/accounts/tags', methods=['POST'])
@login_required
def api_batch_manage_tags():
    """批量管理账号标签"""
    data = request.json
    account_ids = data.get('account_ids', [])
    tag_id = data.get('tag_id')
    action = data.get('action')  # add, remove

    if not account_ids or not tag_id or not action:
        return jsonify({'success': False, 'error': '参数不完整'})

    count = 0
    for acc_id in account_ids:
        if action == 'add':
            if add_account_tag(acc_id, tag_id):
                count += 1
        elif action == 'remove':
            if remove_account_tag(acc_id, tag_id):
                count += 1

    return jsonify({'success': True, 'message': f'成功处理 {count} 个账号'})


@app.route('/api/accounts/batch-update-group', methods=['POST'])
@login_required
def api_batch_update_account_group():
    """批量更新账号分组"""
    data = request.json
    account_ids = data.get('account_ids', [])
    group_id = data.get('group_id')

    if not account_ids:
        return jsonify({'success': False, 'error': '请选择要修改的账号'})

    if not group_id:
        return jsonify({'success': False, 'error': '请选择目标分组'})

    # 验证分组存在
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '目标分组不存在'})

    # 检查是否是临时邮箱分组（系统保留分组）
    if group.get('is_system'):
        return jsonify({'success': False, 'error': '不能移动到系统分组'})

    # 批量更新
    db = get_db()
    try:
        placeholders = ','.join('?' * len(account_ids))
        db.execute(f'''
            UPDATE accounts SET group_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
        ''', [group_id] + account_ids)
        db.commit()
        return jsonify({
            'success': True,
            'message': f'已将 {len(account_ids)} 个账号移动到「{group["name"]}」分组'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@app.route('/api/accounts/search', methods=['GET'])
@login_required
def api_search_accounts():
    """全局搜索账号"""
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'success': True, 'accounts': []})

    db = get_db()
    # 支持搜索邮箱、备注和标签
    cursor = db.execute('''
        SELECT DISTINCT a.*, g.name as group_name, g.color as group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        LEFT JOIN account_tags at ON a.id = at.account_id
        LEFT JOIN tags t ON at.tag_id = t.id
        WHERE a.email LIKE ? OR a.remark LIKE ? OR t.name LIKE ?
        ORDER BY a.created_at DESC
    ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

    rows = cursor.fetchall()
    safe_accounts = []
    for row in rows:
        acc = dict(row)
        # 加载账号标签
        acc['tags'] = get_account_tags(acc['id'])
        
        # 查询该账号最后一次刷新记录
        refresh_cursor = db.execute('''
            SELECT status, error_message, created_at
            FROM account_refresh_logs
            WHERE account_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (acc['id'],))
        last_refresh_log = refresh_cursor.fetchone()

        safe_accounts.append({
            'id': acc['id'],
            'email': acc['email'],
            'client_id': acc['client_id'][:8] + '...' if len(acc['client_id']) > 8 else acc['client_id'],
            'group_id': acc['group_id'],
            'group_name': acc['group_name'] if acc['group_name'] else '默认分组',
            'group_color': acc['group_color'] if acc['group_color'] else '#666666',
            'remark': acc['remark'] if acc['remark'] else '',
            'status': acc['status'] if acc['status'] else 'active',
            'created_at': acc['created_at'] if acc['created_at'] else '',
            'updated_at': acc['updated_at'] if acc['updated_at'] else '',
            'tags': acc['tags'],
            'last_refresh_at': acc.get('last_refresh_at', ''),
            'last_refresh_status': last_refresh_log['status'] if last_refresh_log else None,
            'last_refresh_error': last_refresh_log['error_message'] if last_refresh_log else None
        })

    return jsonify({'success': True, 'accounts': safe_accounts})


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
@login_required
def api_get_account(account_id):
    """获取单个账号详情"""
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})
    
    return jsonify({
        'success': True,
        'account': {
            'id': account['id'],
            'email': account['email'],
            'password': account['password'],
            'client_id': account['client_id'],
            'refresh_token': account['refresh_token'],
            'group_id': account.get('group_id'),
            'group_name': account.get('group_name', '默认分组'),
            'remark': account.get('remark', ''),
            'status': account.get('status', 'active'),
            'created_at': account.get('created_at', ''),
            'updated_at': account.get('updated_at', '')
        }
    })


@app.route('/api/accounts', methods=['POST'])
@login_required
def api_add_account():
    """添加账号"""
    data = request.json
    account_str = data.get('account_string', '')
    group_id = data.get('group_id', 1)
    account_format = data.get('account_format', 'client_id_refresh_token')
    
    if not account_str:
        return jsonify({'success': False, 'error': '请输入账号信息'})
    
    # 支持批量导入（多行）
    lines = account_str.strip().split('\n')
    added = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parsed = parse_account_string(line, account_format)
        if parsed:
            if add_account(parsed['email'], parsed['password'], 
                          parsed['client_id'], parsed['refresh_token'], group_id):
                added += 1
    
    if added > 0:
        return jsonify({'success': True, 'message': f'成功添加 {added} 个账号'})
    else:
        return jsonify({'success': False, 'error': '没有新账号被添加（可能格式错误或已存在）'})


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
@login_required
def api_update_account(account_id):
    """更新账号"""
    data = request.json

    # 检查是否只更新状态
    if 'status' in data and len(data) == 1:
        # 只更新状态
        return api_update_account_status(account_id, data['status'])

    email_addr = data.get('email', '')
    password = data.get('password', '')
    client_id = data.get('client_id', '')
    refresh_token = data.get('refresh_token', '')
    group_id = data.get('group_id', 1)
    remark = sanitize_input(data.get('remark', ''), max_length=200)
    status = data.get('status', 'active')

    if not email_addr or not client_id or not refresh_token:
        return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})

    if update_account(account_id, email_addr, password, client_id, refresh_token, group_id, remark, status):
        return jsonify({'success': True, 'message': '账号更新成功'})
    else:
        return jsonify({'success': False, 'error': '更新失败'})


def api_update_account_status(account_id: int, status: str):
    """只更新账号状态"""
    db = get_db()
    try:
        db.execute('''
            UPDATE accounts
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, account_id))
        db.commit()
        return jsonify({'success': True, 'message': '状态更新成功'})
    except Exception:
        return jsonify({'success': False, 'error': '更新失败'})


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def api_delete_account(account_id):
    """删除账号"""
    if delete_account_by_id(account_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/accounts/email/<email_addr>', methods=['DELETE'])
@login_required
def api_delete_account_by_email(email_addr):
    """根据邮箱地址删除账号"""
    if delete_account_by_email(email_addr):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


# ==================== 账号刷新 API ====================

def log_refresh_result(account_id: int, account_email: str, refresh_type: str, status: str, error_message: str = None):
    """记录刷新结果到数据库"""
    db = get_db()
    try:
        db.execute('''
            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
            VALUES (?, ?, ?, ?, ?)
        ''', (account_id, account_email, refresh_type, status, error_message))

        # 更新账号的最后刷新时间
        if status == 'success':
            db.execute('''
                UPDATE accounts
                SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (account_id,))

        db.commit()
        return True
    except Exception as e:
        print(f"记录刷新结果失败: {str(e)}")
        return False


def test_refresh_token(client_id: str, refresh_token: str, proxy_url: str = None) -> tuple[bool, str]:
    """测试 refresh token 是否有效，返回 (是否成功, 错误信息)"""
    try:
        # 尝试使用 Graph API 获取 access token
        # 使用与 get_access_token_graph 相同的 scope，确保一致性
        proxies = build_proxies(proxy_url)
        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30,
            proxies=proxies
        )

        if res.status_code == 200:
            return True, None
        else:
            error_data = res.json()
            error_msg = error_data.get('error_description', error_data.get('error', '未知错误'))
            return False, error_msg
    except Exception as e:
        return False, f"请求异常: {str(e)}"


@app.route('/api/accounts/<int:account_id>/refresh', methods=['POST'])
@login_required
def api_refresh_account(account_id):
    """刷新单个账号的 token"""
    db = get_db()
    cursor = db.execute('SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE id = ?', (account_id,))
    account = cursor.fetchone()

    if not account:
        error_payload = build_error_payload(
            "ACCOUNT_NOT_FOUND",
            "账号不存在",
            "NotFoundError",
            404,
            f"account_id={account_id}"
        )
        return jsonify({'success': False, 'error': error_payload})

    account_id = account['id']
    account_email = account['email']
    client_id = account['client_id']
    encrypted_refresh_token = account['refresh_token']

    # 获取分组代理设置
    proxy_url = ''
    if account['group_id']:
        group = get_group_by_id(account['group_id'])
        if group:
            proxy_url = group.get('proxy_url', '') or ''

    # 解密 refresh_token
    try:
        refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
    except Exception as e:
        error_msg = f"解密 token 失败: {str(e)}"
        log_refresh_result(account_id, account_email, 'manual', 'failed', error_msg)
        error_payload = build_error_payload(
            "TOKEN_DECRYPT_FAILED",
            "Token 解密失败",
            "DecryptionError",
            500,
            error_msg
        )
        return jsonify({'success': False, 'error': error_payload})

    # 测试 refresh token
    success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

    # 记录刷新结果
    log_refresh_result(account_id, account_email, 'manual', 'success' if success else 'failed', error_msg)

    if success:
        return jsonify({'success': True, 'message': 'Token 刷新成功'})

    error_payload = build_error_payload(
        "TOKEN_REFRESH_FAILED",
        "Token 刷新失败",
        "RefreshTokenError",
        400,
        error_msg or "未知错误"
    )
    return jsonify({'success': False, 'error': error_payload})


@app.route('/api/accounts/refresh-all', methods=['GET'])
@login_required
def api_refresh_all_accounts():
    """刷新所有账号的 token（流式响应，实时返回进度）"""
    import json
    import time

    def generate():
        # 在生成器内部直接创建数据库连接
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row

        try:
            # 获取刷新间隔配置
            cursor_settings = conn.execute("SELECT value FROM settings WHERE key = 'refresh_delay_seconds'")
            delay_row = cursor_settings.fetchone()
            delay_seconds = int(delay_row['value']) if delay_row else 5

            # 清理超过半年的刷新记录
            try:
                conn.execute("DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')")
                conn.commit()
            except Exception as e:
                print(f"清理旧记录失败: {str(e)}")

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active'")
            accounts = cursor.fetchall()

            total = len(accounts)
            success_count = 0
            failed_count = 0
            failed_list = []

            # 发送开始信息
            yield f"data: {json.dumps({'type': 'start', 'total': total, 'delay_seconds': delay_seconds})}\n\n"

            for index, account in enumerate(accounts, 1):
                account_id = account['id']
                account_email = account['email']
                client_id = account['client_id']
                encrypted_refresh_token = account['refresh_token']

                # 解密 refresh_token
                try:
                    refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
                except Exception as e:
                    # 解密失败，记录错误
                    failed_count += 1
                    error_msg = f"解密 token 失败: {str(e)}"
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })
                    try:
                        conn.execute('''
                            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (account_id, account_email, 'manual', 'failed', error_msg))
                        conn.commit()
                    except Exception:
                        pass
                    continue

                # 发送当前处理的账号信息
                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                # 获取分组代理设置
                proxy_url = ''
                group_id = account['group_id']
                if group_id:
                    group_cursor = conn.execute('SELECT proxy_url FROM groups WHERE id = ?', (group_id,))
                    group_row = group_cursor.fetchone()
                    if group_row:
                        proxy_url = group_row['proxy_url'] or ''

                # 测试 refresh token
                success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

                # 记录刷新结果（使用当前连接）
                try:
                    conn.execute('''
                        INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (account_id, account_email, 'manual', 'success' if success else 'failed', error_msg))

                    # 更新账号的最后刷新时间
                    if success:
                        conn.execute('''
                            UPDATE accounts
                            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        ''', (account_id,))

                    conn.commit()
                except Exception as e:
                    print(f"记录刷新结果失败: {str(e)}")

                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })

                # 间隔控制（最后一个账号不需要延迟）
                if index < total and delay_seconds > 0:
                    yield f"data: {json.dumps({'type': 'delay', 'seconds': delay_seconds})}\n\n"
                    time.sleep(delay_seconds)

            # 发送完成信息
            yield f"data: {json.dumps({'type': 'complete', 'total': total, 'success_count': success_count, 'failed_count': failed_count, 'failed_list': failed_list})}\n\n"

        finally:
            conn.close()

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/accounts/<int:account_id>/retry-refresh', methods=['POST'])
@login_required
def api_retry_refresh_account(account_id):
    """重试单个失败账号的刷新"""
    return api_refresh_account(account_id)


@app.route('/api/accounts/refresh-failed', methods=['POST'])
@login_required
def api_refresh_failed_accounts():
    """重试所有失败的账号"""
    db = get_db()

    # 获取最近一次刷新失败的账号列表
    cursor = db.execute('''
        SELECT DISTINCT a.id, a.email, a.client_id, a.refresh_token
        FROM accounts a
        INNER JOIN (
            SELECT account_id, MAX(created_at) as last_refresh
            FROM account_refresh_logs
            GROUP BY account_id
        ) latest ON a.id = latest.account_id
        INNER JOIN account_refresh_logs l ON a.id = l.account_id AND l.created_at = latest.last_refresh
        WHERE l.status = 'failed' AND a.status = 'active'
    ''')
    accounts = cursor.fetchall()

    success_count = 0
    failed_count = 0
    failed_list = []

    for account in accounts:
        account_id = account['id']
        account_email = account['email']
        client_id = account['client_id']
        encrypted_refresh_token = account['refresh_token']

        # 解密 refresh_token
        try:
            refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
        except Exception as e:
            # 解密失败，记录错误
            failed_count += 1
            error_msg = f"解密 token 失败: {str(e)}"
            failed_list.append({
                'id': account_id,
                'email': account_email,
                'error': error_msg
            })
            log_refresh_result(account_id, account_email, 'retry', 'failed', error_msg)
            continue

        # 测试 refresh token
        success, error_msg = test_refresh_token(client_id, refresh_token)

        # 记录刷新结果
        log_refresh_result(account_id, account_email, 'retry', 'success' if success else 'failed', error_msg)

        if success:
            success_count += 1
        else:
            failed_count += 1
            failed_list.append({
                'id': account_id,
                'email': account_email,
                'error': error_msg
            })

    return jsonify({
        'success': True,
        'total': len(accounts),
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_list': failed_list
    })


@app.route('/api/accounts/trigger-scheduled-refresh', methods=['GET'])
@login_required
def api_trigger_scheduled_refresh():
    """手动触发定时刷新（支持强制刷新）"""
    import json
    from datetime import datetime, timedelta

    force = request.args.get('force', 'false').lower() == 'true'

    # 获取配置
    refresh_interval_days = int(get_setting('refresh_interval_days', '30'))

    # 检查上次刷新时间
    db = get_db()
    cursor = db.execute('''
        SELECT MAX(created_at) as last_refresh
        FROM account_refresh_logs
        WHERE refresh_type = 'scheduled'
    ''')
    row = cursor.fetchone()
    last_refresh = row['last_refresh'] if row and row['last_refresh'] else None

    # 判断是否需要刷新（force=true 时跳过检查）
    if not force and last_refresh:
        last_refresh_time = datetime.fromisoformat(last_refresh)
        next_refresh_time = last_refresh_time + timedelta(days=refresh_interval_days)
        if datetime.now() < next_refresh_time:
            return jsonify({
                'success': False,
                'message': f'距离上次刷新未满 {refresh_interval_days} 天，下次刷新时间：{next_refresh_time.strftime("%Y-%m-%d %H:%M:%S")}',
                'last_refresh': last_refresh,
                'next_refresh': next_refresh_time.isoformat()
            })

    # 执行刷新（使用流式响应）
    def generate():
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row

        try:
            # 获取刷新间隔配置
            cursor_settings = conn.execute("SELECT value FROM settings WHERE key = 'refresh_delay_seconds'")
            delay_row = cursor_settings.fetchone()
            delay_seconds = int(delay_row['value']) if delay_row else 5

            # 清理超过半年的刷新记录
            try:
                conn.execute("DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')")
                conn.commit()
            except Exception as e:
                print(f"清理旧记录失败: {str(e)}")

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active'")
            accounts = cursor.fetchall()

            total = len(accounts)
            success_count = 0
            failed_count = 0
            failed_list = []

            yield f"data: {json.dumps({'type': 'start', 'total': total, 'delay_seconds': delay_seconds, 'refresh_type': 'scheduled'})}\n\n"

            for index, account in enumerate(accounts, 1):
                account_id = account['id']
                account_email = account['email']
                client_id = account['client_id']
                encrypted_refresh_token = account['refresh_token']

                # 解密 refresh_token
                try:
                    refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
                except Exception as e:
                    # 解密失败，记录错误
                    failed_count += 1
                    error_msg = f"解密 token 失败: {str(e)}"
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })
                    try:
                        conn.execute('''
                            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (account_id, account_email, 'scheduled', 'failed', error_msg))
                        conn.commit()
                    except Exception:
                        pass
                    continue

                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                # 获取分组代理设置
                proxy_url = ''
                group_id = account['group_id']
                if group_id:
                    group_cursor = conn.execute('SELECT proxy_url FROM groups WHERE id = ?', (group_id,))
                    group_row = group_cursor.fetchone()
                    if group_row:
                        proxy_url = group_row['proxy_url'] or ''

                success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

                try:
                    conn.execute('''
                        INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (account_id, account_email, 'scheduled', 'success' if success else 'failed', error_msg))

                    if success:
                        conn.execute('''
                            UPDATE accounts
                            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        ''', (account_id,))

                    conn.commit()
                except Exception as e:
                    print(f"记录刷新结果失败: {str(e)}")

                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })

                if index < total and delay_seconds > 0:
                    yield f"data: {json.dumps({'type': 'delay', 'seconds': delay_seconds})}\n\n"
                    time.sleep(delay_seconds)

            yield f"data: {json.dumps({'type': 'complete', 'total': total, 'success_count': success_count, 'failed_count': failed_count, 'failed_list': failed_list})}\n\n"

        finally:
            conn.close()

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/accounts/refresh-logs', methods=['GET'])
@login_required
def api_get_refresh_logs():
    """获取所有账号的刷新历史（只返回全量刷新：manual 和 scheduled，近半年）"""
    db = get_db()
    limit = int(request.args.get('limit', 1000))
    offset = int(request.args.get('offset', 0))

    cursor = db.execute('''
        SELECT l.*, a.email as account_email
        FROM account_refresh_logs l
        LEFT JOIN accounts a ON l.account_id = a.id
        WHERE l.refresh_type IN ('manual', 'scheduled')
        AND l.created_at >= datetime('now', '-6 months')
        ORDER BY l.created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'] or row['account_email'],
            'refresh_type': row['refresh_type'],
            'status': row['status'],
            'error_message': row['error_message'],
            'created_at': row['created_at']
        })

    return jsonify({'success': True, 'logs': logs})


@app.route('/api/accounts/<int:account_id>/refresh-logs', methods=['GET'])
@login_required
def api_get_account_refresh_logs(account_id):
    """获取单个账号的刷新历史"""
    db = get_db()
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))

    cursor = db.execute('''
        SELECT * FROM account_refresh_logs
        WHERE account_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (account_id, limit, offset))

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'],
            'refresh_type': row['refresh_type'],
            'status': row['status'],
            'error_message': row['error_message'],
            'created_at': row['created_at']
        })

    return jsonify({'success': True, 'logs': logs})


@app.route('/api/accounts/refresh-logs/failed', methods=['GET'])
@login_required
def api_get_failed_refresh_logs():
    """获取所有失败的刷新记录"""
    db = get_db()

    # 获取每个账号最近一次失败的刷新记录
    cursor = db.execute('''
        SELECT l.*, a.email as account_email, a.status as account_status
        FROM account_refresh_logs l
        INNER JOIN (
            SELECT account_id, MAX(created_at) as last_refresh
            FROM account_refresh_logs
            GROUP BY account_id
        ) latest ON l.account_id = latest.account_id AND l.created_at = latest.last_refresh
        LEFT JOIN accounts a ON l.account_id = a.id
        WHERE l.status = 'failed'
        ORDER BY l.created_at DESC
    ''')

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'] or row['account_email'],
            'account_status': row['account_status'],
            'refresh_type': row['refresh_type'],
            'status': row['status'],
            'error_message': row['error_message'],
            'created_at': row['created_at']
        })

    return jsonify({'success': True, 'logs': logs})


@app.route('/api/accounts/refresh-stats', methods=['GET'])
@login_required
def api_get_refresh_stats():
    """获取刷新统计信息（统计当前失败状态的邮箱数量）"""
    db = get_db()

    cursor = db.execute('''
        SELECT MAX(created_at) as last_refresh_time
        FROM account_refresh_logs
        WHERE refresh_type IN ('manual', 'scheduled')
    ''')
    row = cursor.fetchone()
    last_refresh_time = row['last_refresh_time'] if row else None

    cursor = db.execute('''
        SELECT COUNT(*) as total_accounts
        FROM accounts
        WHERE status = 'active'
    ''')
    total_accounts = cursor.fetchone()['total_accounts']

    cursor = db.execute('''
        SELECT COUNT(DISTINCT l.account_id) as failed_count
        FROM account_refresh_logs l
        INNER JOIN (
            SELECT account_id, MAX(created_at) as last_refresh
            FROM account_refresh_logs
            GROUP BY account_id
        ) latest ON l.account_id = latest.account_id AND l.created_at = latest.last_refresh
        INNER JOIN accounts a ON l.account_id = a.id
        WHERE l.status = 'failed' AND a.status = 'active'
    ''')
    failed_count = cursor.fetchone()['failed_count']

    return jsonify({
        'success': True,
        'stats': {
            'total': total_accounts,
            'success_count': total_accounts - failed_count,
            'failed_count': failed_count,
            'last_refresh_time': last_refresh_time
        }
    })


# ==================== 邮件 API ====================



# ==================== Email Deletion Helpers ====================

def delete_emails_graph(client_id: str, refresh_token: str, message_ids: List[str], proxy_url: str = None) -> Dict[str, Any]:
    """通过 Graph API 批量删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url)
    if not access_token:
        return {"success": False, "error": "获取 Access Token 失败"}

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    # Graph API 不支持一次性批量删除所有邮件，需要逐个删除
    # 但可以使用 batch 请求来优化
    # https://learn.microsoft.com/en-us/graph/json-batching
    
    # 限制每批次请求数量（Graph API 限制为 20）
    BATCH_SIZE = 20
    success_count = 0
    failed_count = 0
    errors = []

    for i in range(0, len(message_ids), BATCH_SIZE):
        batch = message_ids[i:i + BATCH_SIZE]
        
        # 构造 batch 请求 body
        batch_requests = []
        for idx, msg_id in enumerate(batch):
            batch_requests.append({
                "id": str(idx),
                "method": "DELETE",
                "url": f"/me/messages/{msg_id}"
            })
        
        try:
            proxies = build_proxies(proxy_url)
            response = requests.post(
                "https://graph.microsoft.com/v1.0/$batch",
                headers=headers,
                json={"requests": batch_requests},
                timeout=30,
                proxies=proxies
            )
            
            if response.status_code == 200:
                results = response.json().get("responses", [])
                for res in results:
                    if res.get("status") in [200, 204]:
                        success_count += 1
                    else:
                        failed_count += 1
                        # 记录具体错误
                        errors.append(f"Msg ID: {batch[int(res['id'])]}, Status: {res.get('status')}")
            else:
                failed_count += len(batch)
                errors.append(f"Batch request failed: {response.text}")
                
        except Exception as e:
            failed_count += len(batch)
            errors.append(f"Network error: {str(e)}")

    return {
        "success": failed_count == 0,
        "success_count": success_count,
        "failed_count": failed_count,
        "errors": errors
    }

def delete_emails_imap(email_addr: str, client_id: str, refresh_token: str, message_ids: List[str], server: str) -> Dict[str, Any]:
    """通过 IMAP 删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token)
    if not access_token:
        return {"success": False, "error": "获取 Access Token 失败"}
        
    try:
        # 生成 OAuth2 认证字符串
        auth_string = 'user=%s\x01auth=Bearer %s\x01\x01' % (email_addr, access_token)
        
        # 连接 IMAP
        imap = imaplib.IMAP4_SSL(server, IMAP_PORT)
        imap.authenticate('XOAUTH2', lambda x: auth_string.encode('utf-8'))
        
        # 选择文件夹
        imap.select('INBOX')
        
        # IMAP 删除需要 UID。如果我们没有 UID，这很难。
        # 鉴于我们只实现了 Graph 删除，并且 fallback 到 IMAP 比较复杂，
        # 这里暂时返回不支持，或仅做简单的尝试（如果 ID 恰好是 UID）
        # 但通常 Graph ID 不是 UID。
        
        return {"success": False, "error": "IMAP 删除暂不支持 (ID 格式不兼容)"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route('/api/emails/<email_addr>')
@login_required
def api_get_emails(email_addr):
    """获取邮件列表（支持分页，不使用缓存）"""
    account = get_account_by_email(email_addr)

    if not account:
        error_payload = build_error_payload(
            "ACCOUNT_NOT_FOUND",
            "账号不存在",
            "NotFoundError",
            404,
            f"email={email_addr}"
        )
        return jsonify({'success': False, 'error': error_payload})

    folder = request.args.get('folder', 'inbox')  # inbox, junkemail, deleteditems
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))

    # 获取分组代理设置
    proxy_url = ''
    if account.get('group_id'):
        group = get_group_by_id(account['group_id'])
        if group:
            proxy_url = group.get('proxy_url', '') or ''

    # 收集所有错误信息
    all_errors = {}

    # 1. 尝试 Graph API
    graph_result = get_emails_graph(account['client_id'], account['refresh_token'], folder, skip, top, proxy_url)
    if graph_result.get("success"):
        emails = graph_result.get("emails", [])
        # 更新刷新时间
        db = get_db()
        db.execute('''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
        ''', (email_addr,))
        db.commit()

        # 格式化 Graph API 返回的数据
        formatted = []
        for e in emails:
            formatted.append({
                'id': e.get('id'),
                'subject': e.get('subject', '无主题'),
                'from': e.get('from', {}).get('emailAddress', {}).get('address', '未知'),
                'date': e.get('receivedDateTime', ''),
                'is_read': e.get('isRead', False),
                'has_attachments': e.get('hasAttachments', False),
                'body_preview': e.get('bodyPreview', '')
            })

        return jsonify({
            'success': True,
            'emails': formatted,
            'method': 'Graph API',
            'has_more': len(formatted) >= top
        })
    else:
        graph_error = graph_result.get("error")
        all_errors["graph"] = graph_error

        # 如果是代理错误，不再回退 IMAP
        if isinstance(graph_error, dict) and graph_error.get('type') in ('ProxyError', 'ConnectionError'):
            return jsonify({
                'success': False,
                'error': '代理连接失败，请检查分组代理设置',
                'details': all_errors
            })

    imap_new_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_NEW
    )
    if imap_new_result.get("success"):
        return jsonify({
            'success': True,
            'emails': imap_new_result.get("emails", []),
            'method': 'IMAP (New)',
            'has_more': False # IMAP 分页暂未完全实现，视情况
        })
    else:
        all_errors["imap_new"] = imap_new_result.get("error")

    # 3. 尝试旧版 IMAP (outlook.office365.com)
    imap_old_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_OLD
    )
    if imap_old_result.get("success"):
        return jsonify({
            'success': True,
            'emails': imap_old_result.get("emails", []),
            'method': 'IMAP (Old)',
            'has_more': False
        })
    else:
        all_errors["imap_old"] = imap_old_result.get("error")

    return jsonify({
        'success': False, 
        'error': '无法获取邮件，所有方式均失败',
        'details': all_errors
    })

@app.route('/api/emails/delete', methods=['POST'])
@login_required
def api_delete_emails():
    """批量删除邮件（永久删除）"""
    data = request.json
    email_addr = data.get('email', '')
    message_ids = data.get('ids', [])
    
    if not email_addr or not message_ids:
        return jsonify({'success': False, 'error': '参数不完整'})

    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})

    # 获取分组代理设置
    proxy_url = ''
    if account.get('group_id'):
        group = get_group_by_id(account['group_id'])
        if group:
            proxy_url = group.get('proxy_url', '') or ''

    # 1. 优先尝试 Graph API
    graph_res = delete_emails_graph(account['client_id'], account['refresh_token'], message_ids, proxy_url)
    if graph_res['success']:
        return jsonify(graph_res)

    # 如果是代理错误，不再回退 IMAP
    graph_error = graph_res.get('error', '')
    if isinstance(graph_error, str) and 'ProxyError' in graph_error:
        return jsonify(graph_res)
    
    # 2. 尝试 IMAP 回退（新服务器）
    imap_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_NEW)
    if imap_res['success']:
        return jsonify(imap_res)

    # 3. 尝试 IMAP 回退（旧服务器）
    imap_old_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_OLD)
    if imap_old_res['success']:
        return jsonify(imap_old_res)

    # 所有方式均失败，返回 Graph API 的错误
    return jsonify(graph_res)



@app.route('/api/email/<email_addr>/<path:message_id>')
@login_required
def api_get_email_detail(email_addr, message_id):
    """获取邮件详情"""
    account = get_account_by_email(email_addr)

    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})

    method = request.args.get('method', 'graph')
    folder = request.args.get('folder', 'inbox')

    if method == 'graph':
        # 获取分组代理设置
        proxy_url = ''
        if account.get('group_id'):
            group = get_group_by_id(account['group_id'])
            if group:
                proxy_url = group.get('proxy_url', '') or ''

        detail = get_email_detail_graph(account['client_id'], account['refresh_token'], message_id, proxy_url)
        if detail:
            return jsonify({
                'success': True,
                'email': {
                    'id': detail.get('id'),
                    'subject': detail.get('subject', '无主题'),
                    'from': detail.get('from', {}).get('emailAddress', {}).get('address', '未知'),
                    'to': ', '.join([r.get('emailAddress', {}).get('address', '') for r in detail.get('toRecipients', [])]),
                    'cc': ', '.join([r.get('emailAddress', {}).get('address', '') for r in detail.get('ccRecipients', [])]),
                    'date': detail.get('receivedDateTime', ''),
                    'body': detail.get('body', {}).get('content', ''),
                    'body_type': detail.get('body', {}).get('contentType', 'text')
                }
            })

    # 如果 Graph API 失败，尝试 IMAP
    detail = get_email_detail_imap(account['email'], account['client_id'], account['refresh_token'], message_id, folder)
    if detail:
        return jsonify({'success': True, 'email': detail})

    return jsonify({'success': False, 'error': '获取邮件详情失败'})


# ==================== GPTMail 临时邮箱 API ====================

def gptmail_request(method: str, endpoint: str, params: dict = None, json_data: dict = None) -> Optional[Dict]:
    """发送 GPTMail API 请求"""
    try:
        url = f"{GPTMAIL_BASE_URL}{endpoint}"
        # 从数据库获取 API Key
        api_key = get_gptmail_api_key()
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers, params=params, timeout=30)
        else:
            return None
        
        if response.status_code == 200:
            return response.json()
        else:
            return {'success': False, 'error': f'API 请求失败: {response.status_code}'}
    except Exception as e:
        return {'success': False, 'error': f'请求异常: {str(e)}'}


def generate_temp_email(prefix: str = None, domain: str = None) -> Optional[str]:
    """生成临时邮箱地址"""
    json_data = {}
    if prefix:
        json_data['prefix'] = prefix
    if domain:
        json_data['domain'] = domain
    
    if json_data:
        result = gptmail_request('POST', '/api/generate-email', json_data=json_data)
    else:
        result = gptmail_request('GET', '/api/generate-email')
    
    if result and result.get('success'):
        return result.get('data', {}).get('email')
    return None


def get_temp_emails_from_api(email_addr: str) -> Optional[List[Dict]]:
    """从 GPTMail API 获取邮件列表"""
    result = gptmail_request('GET', '/api/emails', params={'email': email_addr})
    
    if result and result.get('success'):
        return result.get('data', {}).get('emails', [])
    return None


def get_temp_email_detail_from_api(message_id: str) -> Optional[Dict]:
    """从 GPTMail API 获取邮件详情"""
    result = gptmail_request('GET', f'/api/email/{message_id}')
    
    if result and result.get('success'):
        return result.get('data')
    return None


def delete_temp_email_from_api(message_id: str) -> bool:
    """从 GPTMail API 删除邮件"""
    result = gptmail_request('DELETE', f'/api/email/{message_id}')
    return result and result.get('success', False)


def clear_temp_emails_from_api(email_addr: str) -> bool:
    """清空 GPTMail 邮箱的所有邮件"""
    result = gptmail_request('DELETE', '/api/emails/clear', params={'email': email_addr})
    return result and result.get('success', False)


# ==================== Cloudflare Temp Email API ====================

def cloudflare_temp_request(method: str, endpoint: str, jwt: str = None,
                            admin_auth: bool = False, params: dict = None,
                            json_data: dict = None) -> Optional[Dict]:
    """发送 Cloudflare Temp Email API 请求"""
    worker_domain = get_cloudflare_worker_domain().strip()
    if not worker_domain:
        return {'success': False, 'error': '未配置 Cloudflare Worker 域名'}

    try:
        url = f"https://{worker_domain}{endpoint}"
        headers = {"Content-Type": "application/json"}

        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        if admin_auth:
            admin_password = get_cloudflare_admin_password().strip()
            if not admin_password:
                return {'success': False, 'error': '未配置 Cloudflare 管理密码'}
            headers["x-admin-auth"] = admin_password

        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, params=params, json=json_data, timeout=30)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers, params=params, timeout=30)
        else:
            return {'success': False, 'error': '不支持的请求方法'}

        if response.status_code in (200, 201):
            try:
                return response.json()
            except Exception:
                return {'success': False, 'error': 'Cloudflare API 响应不是有效 JSON'}
        if response.status_code == 204:
            return {'success': True}

        try:
            error_data = response.json()
            error_message = error_data.get('message') or error_data.get('error') or response.text
        except Exception:
            error_message = response.text or f'API 请求失败: {response.status_code}'
        return {'success': False, 'error': error_message}
    except Exception as e:
        return {'success': False, 'error': f'请求异常: {str(e)}'}


def cloudflare_get_domains() -> tuple[List[str], Optional[str]]:
    """获取 Cloudflare Temp Email 可用域名列表"""
    domains = get_cloudflare_email_domains()
    if domains:
        return domains, None
    return [], '未配置 Cloudflare 邮箱域名，请在设置中填写'


def cloudflare_create_address(username: str = None, domain: str = None) -> Optional[Dict]:
    """创建 Cloudflare Temp Email 地址"""
    domains = get_cloudflare_email_domains()
    selected_domain = domain or (domains[0] if domains else None)
    if not selected_domain:
        return {'success': False, 'error': '未配置可用域名'}

    email_name = username or generate_random_temp_name()
    last_error: Optional[Dict] = None

    for candidate_domain in build_cloudflare_domain_candidates(selected_domain):
        payload = {
            'enablePrefix': True,
            'name': email_name,
            'domain': candidate_domain
        }
        result = cloudflare_temp_request('POST', '/admin/new_address', admin_auth=True, json_data=payload)
        if result and result.get('jwt') and result.get('address'):
            return result

        last_error = result
        error_text = str((result or {}).get('error', '')).lower()
        if 'invalid domain' not in error_text:
            break

    if last_error and 'invalid domain' in str(last_error.get('error', '')).lower():
        last_error['error'] = (
            f"{last_error.get('error')}，请确认该域名已配置到 cloudflare_temp_email 的 DOMAINS/DEFAULT_DOMAINS，"
            "且如使用子域名收信，已按官方文档完成子域名邮箱配置"
        )
    return last_error


def cloudflare_get_messages(jwt: str, limit: int = 50, offset: int = 0) -> Optional[List[Dict]]:
    """获取 Cloudflare Temp Email 邮件列表"""
    result = cloudflare_temp_request(
        'GET',
        '/api/mails',
        jwt=jwt,
        params={'limit': limit, 'offset': offset}
    )
    if result and isinstance(result.get('results'), list):
        return result['results']
    return None


def cloudflare_delete_address(address_id: str) -> bool:
    """删除 Cloudflare Temp Email 地址"""
    if not address_id:
        return False
    result = cloudflare_temp_request('DELETE', f'/admin/delete_address/{quote(str(address_id))}', admin_auth=True)
    return result is not None and result.get('success', False)


# ==================== DuckMail 临时邮箱 API ====================

def duckmail_request(method: str, endpoint: str, token: str = None,
                     json_data: dict = None, params: dict = None) -> Optional[Dict]:
    """发送 DuckMail API 请求"""
    try:
        base_url = get_duckmail_base_url().rstrip('/')
        url = f"{base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
        elif method.upper() == 'PATCH':
            response = requests.patch(url, headers=headers, json=json_data, timeout=30)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers, params=params, timeout=30)
        else:
            return None

        if response.status_code == 204:
            return {'success': True}
        elif response.status_code in (200, 201):
            return response.json()
        else:
            try:
                err = response.json()
                return {'success': False, 'error': err.get('message', f'API 请求失败: {response.status_code}')}
            except Exception:
                return {'success': False, 'error': f'API 请求失败: {response.status_code}'}
    except Exception as e:
        return {'success': False, 'error': f'请求异常: {str(e)}'}


def duckmail_get_domains() -> tuple:
    """获取 DuckMail 可用域名列表，返回 (domains_list, error_msg)"""
    api_key = get_duckmail_api_key()
    token = api_key if api_key else None
    result = duckmail_request('GET', '/domains', token=token)
    if result and 'hydra:member' in result:
        domains = [d for d in result['hydra:member'] if d.get('isVerified', False)]
        return domains, None
    error = result.get('error', '获取域名失败') if result else '无法连接 DuckMail API'
    return [], error


def duckmail_create_account(address: str, password: str) -> Optional[Dict]:
    """创建 DuckMail 邮箱账户，返回账户信息"""
    api_key = get_duckmail_api_key()
    token = api_key if api_key else None
    result = duckmail_request('POST', '/accounts', token=token,
                              json_data={'address': address, 'password': password})
    if result and result.get('id'):
        return result
    return result  # 返回错误信息


def duckmail_get_token(address: str, password: str) -> Optional[Dict]:
    """获取 DuckMail Bearer Token"""
    result = duckmail_request('POST', '/token',
                              json_data={'address': address, 'password': password})
    if result and result.get('token'):
        return result
    return result


def duckmail_get_messages(token: str, page: int = 1) -> Optional[List[Dict]]:
    """获取 DuckMail 邮件列表"""
    result = duckmail_request('GET', '/messages', token=token, params={'page': page})
    if result and 'hydra:member' in result:
        return result['hydra:member']
    return None


def duckmail_get_message_detail(token: str, message_id: str) -> Optional[Dict]:
    """获取 DuckMail 邮件详情（含 body）"""
    result = duckmail_request('GET', f'/messages/{message_id}', token=token)
    if result and result.get('id'):
        return result
    return None


def duckmail_delete_message(token: str, message_id: str) -> bool:
    """删除 DuckMail 邮件"""
    result = duckmail_request('DELETE', f'/messages/{message_id}', token=token)
    return result is not None and result.get('success', False)


def duckmail_delete_account(token: str, account_id: str) -> bool:
    """删除 DuckMail 账户"""
    result = duckmail_request('DELETE', f'/accounts/{account_id}', token=token)
    return result is not None and result.get('success', False)


def duckmail_refresh_token(email_addr: str) -> Optional[str]:
    """刷新 DuckMail Token（使用存储的密码重新获取）"""
    temp_email = get_temp_email_by_address(email_addr)
    if not temp_email or temp_email.get('provider') != 'duckmail':
        return None

    password = temp_email.get('duckmail_password', '')
    if password:
        password = decrypt_data(password)

    if not password:
        return None

    result = duckmail_get_token(email_addr, password)
    if result and result.get('token'):
        new_token = result['token']
        # 更新数据库中的 Token
        db = get_db()
        db.execute('UPDATE temp_emails SET duckmail_token = ? WHERE email = ?',
                   (encrypt_data(new_token), email_addr))
        db.commit()
        return new_token
    return None


def get_duckmail_token_for_email(email_addr: str) -> Optional[str]:
    """获取临时邮箱的 DuckMail Token，过期则自动刷新"""
    temp_email = get_temp_email_by_address(email_addr)
    if not temp_email or temp_email.get('provider') != 'duckmail':
        return None

    token = temp_email.get('duckmail_token', '')
    if token:
        token = decrypt_data(token)

    if not token:
        # Token 不存在，尝试刷新
        token = duckmail_refresh_token(email_addr)

    return token


# ==================== 临时邮箱数据库操作 ====================

def get_temp_email_group_id() -> int:
    """获取临时邮箱分组的 ID"""
    db = get_db()
    cursor = db.execute("SELECT id FROM groups WHERE name = '临时邮箱'")
    row = cursor.fetchone()
    return row['id'] if row else 2


def load_temp_emails() -> List[Dict]:
    """加载所有临时邮箱"""
    db = get_db()
    cursor = db.execute('SELECT * FROM temp_emails ORDER BY created_at DESC')
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_temp_email_by_address(email_addr: str) -> Optional[Dict]:
    """根据邮箱地址获取临时邮箱"""
    db = get_db()
    cursor = db.execute('SELECT * FROM temp_emails WHERE email = ?', (email_addr,))
    row = cursor.fetchone()
    return dict(row) if row else None


def add_temp_email(email_addr: str, provider: str = 'gptmail',
                   duckmail_token: str = None, duckmail_account_id: str = None,
                   duckmail_password: str = None, cloudflare_jwt: str = None,
                   cloudflare_address_id: str = None) -> bool:
    """添加临时邮箱"""
    db = get_db()
    try:
        db.execute('''INSERT INTO temp_emails (
                        email, provider, duckmail_token, duckmail_account_id, duckmail_password,
                        cloudflare_jwt, cloudflare_address_id
                      ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (email_addr, provider,
                    encrypt_data(duckmail_token) if duckmail_token else None,
                    duckmail_account_id,
                    encrypt_data(duckmail_password) if duckmail_password else None,
                    encrypt_data(cloudflare_jwt) if cloudflare_jwt else None,
                    cloudflare_address_id))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_cloudflare_jwt_for_email(email_addr: str) -> Optional[str]:
    """获取临时邮箱的 Cloudflare JWT"""
    temp_email = get_temp_email_by_address(email_addr)
    if not temp_email or temp_email.get('provider') != 'cloudflare':
        return None

    token = temp_email.get('cloudflare_jwt', '')
    if token:
        return decrypt_data(token)
    return None


def delete_temp_email(email_addr: str) -> bool:
    """删除临时邮箱及其所有邮件"""
    db = get_db()
    try:
        db.execute('DELETE FROM temp_email_messages WHERE email_address = ?', (email_addr,))
        db.execute('DELETE FROM temp_emails WHERE email = ?', (email_addr,))
        db.commit()
        return True
    except Exception:
        return False


def save_temp_email_messages(email_addr: str, messages: List[Dict]) -> int:
    """保存临时邮件到数据库"""
    db = get_db()
    saved = 0
    for msg in messages:
        try:
            db.execute('''
                INSERT OR REPLACE INTO temp_email_messages
                (message_id, email_address, from_address, subject, content, html_content, has_html, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg.get('id'),
                email_addr,
                msg.get('from_address', ''),
                msg.get('subject', ''),
                msg.get('content', ''),
                msg.get('html_content', ''),
                1 if msg.get('has_html') else 0,
                msg.get('timestamp', 0)
            ))
            saved += 1
        except Exception:
            continue
    db.commit()
    return saved


def get_temp_email_messages(email_addr: str) -> List[Dict]:
    """获取临时邮箱的所有邮件（从数据库）"""
    db = get_db()
    cursor = db.execute('''
        SELECT * FROM temp_email_messages
        WHERE email_address = ?
        ORDER BY timestamp DESC
    ''', (email_addr,))
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_temp_email_message_by_id(message_id: str) -> Optional[Dict]:
    """根据 ID 获取临时邮件"""
    db = get_db()
    cursor = db.execute('SELECT * FROM temp_email_messages WHERE message_id = ?', (message_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def delete_temp_email_message(message_id: str) -> bool:
    """删除临时邮件"""
    db = get_db()
    try:
        db.execute('DELETE FROM temp_email_messages WHERE message_id = ?', (message_id,))
        db.commit()
        return True
    except Exception:
        return False


def get_temp_email_count() -> int:
    """获取临时邮箱数量"""
    db = get_db()
    cursor = db.execute('SELECT COUNT(*) as count FROM temp_emails')
    row = cursor.fetchone()
    return row['count'] if row else 0


# ==================== 临时邮箱 API 路由 ====================

@app.route('/api/temp-emails', methods=['GET'])
@login_required
def api_get_temp_emails():
    """获取所有临时邮箱"""
    emails = load_temp_emails()
    return jsonify({'success': True, 'emails': emails})


@app.route('/api/temp-emails/import', methods=['POST'])
@login_required
def api_import_temp_emails():
    """导入临时邮箱（根据渠道使用不同格式）"""
    data = request.json
    import_text = data.get('account_string', '').strip()
    provider = data.get('provider', 'gptmail')

    if not import_text:
        return jsonify({'success': False, 'error': '请输入要导入的临时邮箱'})

    lines = import_text.strip().split('\n')
    added = 0
    updated = 0
    skipped = 0
    token_errors = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        try:
            if provider == 'duckmail':
                # DuckMail 格式：邮箱----密码
                parts = line.split('----')
                if len(parts) >= 2:
                    email_addr = parts[0].strip()
                    duckmail_password = parts[1].strip()

                    if email_addr and duckmail_password:
                        # 检查是否已存在，如果存在则更新密码
                        existing = get_temp_email_by_address(email_addr)
                        if existing:
                            # 更新密码和 provider
                            db = get_db()
                            db.execute('UPDATE temp_emails SET duckmail_password = ?, provider = ? WHERE email = ?',
                                       (encrypt_data(duckmail_password), 'duckmail', email_addr))
                            db.commit()
                            updated += 1
                        else:
                            if not add_temp_email(
                                email_addr, provider='duckmail',
                                duckmail_token=None,
                                duckmail_account_id=None,
                                duckmail_password=duckmail_password
                            ):
                                skipped += 1
                                continue
                            added += 1

                        # 尝试获取 Token（非阻塞，失败不影响导入）
                        try:
                            token_result = duckmail_get_token(email_addr, duckmail_password)
                            if token_result and token_result.get('token'):
                                db = get_db()
                                db.execute('UPDATE temp_emails SET duckmail_token = ? WHERE email = ?',
                                           (encrypt_data(token_result['token']), email_addr))
                                db.commit()
                            else:
                                token_errors.append(email_addr)
                        except Exception:
                            token_errors.append(email_addr)
                    else:
                        skipped += 1
                else:
                    skipped += 1
            elif provider == 'cloudflare':
                # Cloudflare 格式：邮箱----JWT
                parts = line.split('----')
                if len(parts) >= 2:
                    email_addr = parts[0].strip()
                    cloudflare_jwt = parts[1].strip()

                    if email_addr and cloudflare_jwt and '@' in email_addr:
                        existing = get_temp_email_by_address(email_addr)
                        db = get_db()
                        if existing:
                            db.execute(
                                'UPDATE temp_emails SET cloudflare_jwt = ?, provider = ? WHERE email = ?',
                                (encrypt_data(cloudflare_jwt), 'cloudflare', email_addr)
                            )
                            db.commit()
                            updated += 1
                        elif add_temp_email(
                            email_addr,
                            provider='cloudflare',
                            cloudflare_jwt=cloudflare_jwt
                        ):
                            added += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
            else:
                # GPTMail 格式：每行一个邮箱地址
                email_addr = line.strip()
                if email_addr and '@' in email_addr:
                    existing = get_temp_email_by_address(email_addr)
                    if existing:
                        updated += 1
                    elif add_temp_email(email_addr, provider='gptmail'):
                        added += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception:
            skipped += 1

    total = added + updated
    if total > 0:
        log_audit('import', 'temp_emails', None, f"导入 {added} 个新临时邮箱，更新 {updated} 个已有邮箱")
        msg = ''
        if added > 0:
            msg += f'新增 {added} 个临时邮箱'
        if updated > 0:
            msg += ('，' if msg else '') + f'更新 {updated} 个已有邮箱'
        if skipped > 0:
            msg += f'，跳过 {skipped} 个（格式错误）'
        if token_errors:
            msg += f'，{len(token_errors)} 个邮箱 Token 获取失败（不影响使用，获取邮件时会自动重试）'
        return jsonify({
            'success': True,
            'message': msg
        })
    else:
        return jsonify({'success': False, 'error': '没有新的临时邮箱被导入（可能格式错误）'})


@app.route('/api/duckmail/domains', methods=['GET'])
@login_required
def api_get_duckmail_domains():
    """获取 DuckMail 可用域名列表"""
    domains, error = duckmail_get_domains()
    if error:
        return jsonify({'success': False, 'error': error, 'domains': []})
    return jsonify({
        'success': True,
        'domains': [{'id': d.get('id'), 'domain': d.get('domain')} for d in domains]
    })


@app.route('/api/cloudflare/domains', methods=['GET'])
@login_required
def api_get_cloudflare_domains():
    """获取 Cloudflare Temp Email 可用域名列表"""
    domains, error = cloudflare_get_domains()
    if error:
        return jsonify({'success': False, 'error': error, 'domains': []})
    return jsonify({
        'success': True,
        'domains': [{'domain': domain} for domain in domains]
    })


@app.route('/api/temp-emails/generate', methods=['POST'])
@login_required
def api_generate_temp_email():
    """生成新的临时邮箱（支持 GPTMail、DuckMail 和 Cloudflare）"""
    data = request.json or {}
    provider = data.get('provider', 'gptmail')

    if provider == 'duckmail':
        # DuckMail: 需要 domain、username、password
        domain = data.get('domain', '')
        username = data.get('username', '')
        password = data.get('password', '')

        if not domain or not username:
            return jsonify({'success': False, 'error': '请输入用户名和域名'})
        if len(username) < 3:
            return jsonify({'success': False, 'error': '用户名至少 3 个字符'})
        if not password or len(password) < 6:
            return jsonify({'success': False, 'error': '密码至少 6 个字符'})

        email_addr = f"{username}@{domain}"

        # 检查本地数据库是否已存在
        existing = get_temp_email_by_address(email_addr)
        if existing:
            return jsonify({'success': False, 'error': '邮箱已存在'})

        # 1. 创建账户
        account_result = duckmail_create_account(email_addr, password)
        if not account_result or not account_result.get('id'):
            error_msg = account_result.get('error', '创建 DuckMail 账户失败') if account_result else '创建 DuckMail 账户失败'
            return jsonify({'success': False, 'error': error_msg})

        account_id = account_result['id']

        # 2. 获取 Token
        token_result = duckmail_get_token(email_addr, password)
        if not token_result or not token_result.get('token'):
            error_msg = token_result.get('error', '获取 DuckMail Token 失败') if token_result else '获取 DuckMail Token 失败'
            return jsonify({'success': False, 'error': error_msg})

        token = token_result['token']

        # 3. 保存到数据库
        if add_temp_email(email_addr, provider='duckmail',
                         duckmail_token=token,
                         duckmail_account_id=account_id,
                         duckmail_password=password):
            return jsonify({'success': True, 'email': email_addr, 'message': 'DuckMail 临时邮箱创建成功'})
        else:
            return jsonify({'success': False, 'error': '邮箱已存在'})
    elif provider == 'cloudflare':
        domain = data.get('domain', '').strip()
        username = data.get('username', '').strip() or None

        if username and len(username) < 3:
            return jsonify({'success': False, 'error': '用户名至少 3 个字符，或留空随机生成'})
        if not domain:
            domains = get_cloudflare_email_domains()
            if not domains:
                return jsonify({'success': False, 'error': '请先在设置中配置 Cloudflare 邮箱域名'})
            domain = domains[0]

        result = cloudflare_create_address(username=username, domain=domain)
        if not result:
            return jsonify({'success': False, 'error': '创建 Cloudflare 临时邮箱失败'})

        email_addr = result.get('address')
        jwt = result.get('jwt')
        address_id = result.get('id') or result.get('address_id')

        if not email_addr or not jwt:
            return jsonify({'success': False, 'error': result.get('error', 'Cloudflare 返回数据不完整')})

        if add_temp_email(
            email_addr,
            provider='cloudflare',
            cloudflare_jwt=jwt,
            cloudflare_address_id=address_id
        ):
            return jsonify({'success': True, 'email': email_addr, 'message': 'Cloudflare 临时邮箱创建成功'})
        return jsonify({'success': False, 'error': '邮箱已存在'})
    else:
        # GPTMail: 保持原有逻辑
        prefix = data.get('prefix')
        domain = data.get('domain')

        email_addr = generate_temp_email(prefix, domain)

        if email_addr:
            if add_temp_email(email_addr, provider='gptmail'):
                return jsonify({'success': True, 'email': email_addr, 'message': '临时邮箱创建成功'})
            else:
                return jsonify({'success': False, 'error': '邮箱已存在'})
        else:
            return jsonify({'success': False, 'error': '生成临时邮箱失败，请稍后重试'})


@app.route('/api/temp-emails/<path:email_addr>', methods=['DELETE'])
@login_required
def api_delete_temp_email(email_addr):
    """删除临时邮箱"""
    temp_email = get_temp_email_by_address(email_addr)

    # DuckMail: 额外调用删除账户 API
    if temp_email and temp_email.get('provider') == 'duckmail':
        token = get_duckmail_token_for_email(email_addr)
        account_id = temp_email.get('duckmail_account_id', '')
        if token and account_id:
            duckmail_delete_account(token, account_id)
    elif temp_email and temp_email.get('provider') == 'cloudflare':
        cloudflare_delete_address(temp_email.get('cloudflare_address_id', ''))

    if delete_temp_email(email_addr):
        return jsonify({'success': True, 'message': '临时邮箱已删除'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/temp-emails/<path:email_addr>/messages', methods=['GET'])
@login_required
def api_get_temp_email_messages(email_addr):
    """获取临时邮箱的邮件列表"""
    temp_email = get_temp_email_by_address(email_addr)
    provider = temp_email.get('provider', 'gptmail') if temp_email else 'gptmail'

    if provider == 'duckmail':
        # DuckMail: 使用 Bearer Token 获取邮件
        token = get_duckmail_token_for_email(email_addr)
        if not token:
            # Token 获取失败，尝试用密码刷新
            token = duckmail_refresh_token(email_addr)
        if not token:
            return jsonify({'success': False, 'error': 'DuckMail Token 获取失败，请检查密码是否正确或 DuckMail 服务是否可用'})

        messages = duckmail_get_messages(token)
        if messages is None:
            # Token 可能过期，尝试刷新
            token = duckmail_refresh_token(email_addr)
            if token:
                messages = duckmail_get_messages(token)

        if messages is None:
            return jsonify({'success': False, 'error': '获取 DuckMail 邮件失败'})

        # 转换为统一格式并保存到数据库
        unified_messages = []
        for msg in messages:
            from_info = msg.get('from', {})
            from_addr = from_info.get('address', '') if isinstance(from_info, dict) else str(from_info)
            unified_messages.append({
                'id': msg.get('id', ''),
                'from_address': from_addr,
                'subject': msg.get('subject', '无主题'),
                'content': msg.get('text', ''),
                'html_content': msg.get('html', [''])[0] if isinstance(msg.get('html'), list) else (msg.get('html', '') or ''),
                'has_html': bool(msg.get('html')),
                'timestamp': int(datetime.fromisoformat(msg['createdAt'].replace('Z', '+00:00')).timestamp()) if msg.get('createdAt') else 0
            })
        save_temp_email_messages(email_addr, unified_messages)

        formatted = []
        for msg in unified_messages:
            formatted.append({
                'id': msg.get('id'),
                'from': msg.get('from_address', '未知'),
                'subject': msg.get('subject', '无主题'),
                'body_preview': (msg.get('content', '') or '')[:200],
                'date': msg.get('timestamp', 0),
                'timestamp': msg.get('timestamp', 0),
                'has_html': 1 if msg.get('has_html') else 0
            })

        return jsonify({
            'success': True,
            'emails': formatted,
            'count': len(formatted),
            'method': 'DuckMail'
        })
    elif provider == 'cloudflare':
        jwt = get_cloudflare_jwt_for_email(email_addr)
        if not jwt:
            return jsonify({'success': False, 'error': 'Cloudflare JWT 不存在，请重新导入或创建邮箱'})

        messages = cloudflare_get_messages(jwt)
        if messages is None:
            return jsonify({'success': False, 'error': '获取 Cloudflare 邮件失败'})

        unified_messages = []
        for index, msg in enumerate(messages):
            raw_email = msg.get('raw')
            if not raw_email:
                continue
            fallback_id = msg.get('id') or f"{email_addr}-{index}-{hashlib.sha256(raw_email.encode('utf-8', 'replace')).hexdigest()}"
            fallback_timestamp = 0
            for key in ('createdAt', 'created_at', 'date'):
                if msg.get(key):
                    try:
                        fallback_timestamp = int(datetime.fromisoformat(str(msg[key]).replace('Z', '+00:00')).timestamp())
                        break
                    except Exception:
                        continue
            unified_messages.append(
                parse_raw_email_to_temp_message(email_addr, raw_email, fallback_id, fallback_timestamp)
            )

        save_temp_email_messages(email_addr, unified_messages)

        formatted = []
        for msg in unified_messages:
            formatted.append({
                'id': msg.get('id'),
                'from': msg.get('from_address', '未知'),
                'subject': msg.get('subject', '无主题'),
                'body_preview': (msg.get('content', '') or '')[:200],
                'date': msg.get('timestamp', 0),
                'timestamp': msg.get('timestamp', 0),
                'has_html': 1 if msg.get('has_html') else 0
            })

        return jsonify({
            'success': True,
            'emails': formatted,
            'count': len(formatted),
            'method': 'Cloudflare'
        })
    else:
        # GPTMail: 保持原有逻辑
        api_messages = get_temp_emails_from_api(email_addr)

        if api_messages:
            save_temp_email_messages(email_addr, api_messages)

        messages = get_temp_email_messages(email_addr)

        formatted = []
        for msg in messages:
            formatted.append({
                'id': msg.get('message_id'),
                'from': msg.get('from_address', '未知'),
                'subject': msg.get('subject', '无主题'),
                'body_preview': (msg.get('content', '') or '')[:200],
                'date': msg.get('created_at', ''),
                'timestamp': msg.get('timestamp', 0),
                'has_html': msg.get('has_html', 0)
            })

        return jsonify({
            'success': True,
            'emails': formatted,
            'count': len(formatted),
            'method': 'GPTMail'
        })


@app.route('/api/temp-emails/<path:email_addr>/messages/<path:message_id>', methods=['GET'])
@login_required
def api_get_temp_email_message_detail(email_addr, message_id):
    """获取临时邮件详情"""
    temp_email = get_temp_email_by_address(email_addr)
    provider = temp_email.get('provider', 'gptmail') if temp_email else 'gptmail'

    if provider == 'duckmail':
        # 先检查本地缓存
        msg = get_temp_email_message_by_id(message_id)

        # 如果有 HTML 内容直接返回本地缓存
        if msg and msg.get('has_html') and msg.get('html_content'):
            return jsonify({
                'success': True,
                'email': {
                    'id': msg.get('message_id'),
                    'from': msg.get('from_address', '未知'),
                    'to': email_addr,
                    'subject': msg.get('subject', '无主题'),
                    'body': msg.get('html_content') if msg.get('has_html') else msg.get('content', ''),
                    'body_type': 'html' if msg.get('has_html') else 'text',
                    'date': msg.get('created_at', ''),
                    'timestamp': msg.get('timestamp', 0)
                }
            })

        # 从 DuckMail API 获取详情（含 body）
        token = get_duckmail_token_for_email(email_addr)
        if not token:
            return jsonify({'success': False, 'error': 'DuckMail Token 无效'})

        detail = duckmail_get_message_detail(token, message_id)
        if detail:
            from_info = detail.get('from', {})
            from_addr = from_info.get('address', '') if isinstance(from_info, dict) else str(from_info)
            html_content = detail.get('html', [''])[0] if isinstance(detail.get('html'), list) else (detail.get('html', '') or '')
            text_content = detail.get('text', '')

            # 更新本地缓存
            save_temp_email_messages(email_addr, [{
                'id': detail.get('id', ''),
                'from_address': from_addr,
                'subject': detail.get('subject', '无主题'),
                'content': text_content,
                'html_content': html_content,
                'has_html': bool(html_content),
                'timestamp': int(datetime.fromisoformat(detail['createdAt'].replace('Z', '+00:00')).timestamp()) if detail.get('createdAt') else 0
            }])

            body = html_content if html_content else text_content
            body_type = 'html' if html_content else 'text'

            return jsonify({
                'success': True,
                'email': {
                    'id': detail.get('id'),
                    'from': from_addr,
                    'to': email_addr,
                    'subject': detail.get('subject', '无主题'),
                    'body': body,
                    'body_type': body_type,
                    'date': detail.get('createdAt', ''),
                    'timestamp': int(datetime.fromisoformat(detail['createdAt'].replace('Z', '+00:00')).timestamp()) if detail.get('createdAt') else 0
                }
            })
        else:
            return jsonify({'success': False, 'error': '获取邮件详情失败'})
    elif provider == 'cloudflare':
        msg = get_temp_email_message_by_id(message_id)

        if not msg:
            jwt = get_cloudflare_jwt_for_email(email_addr)
            if not jwt:
                return jsonify({'success': False, 'error': 'Cloudflare JWT 无效'})

            messages = cloudflare_get_messages(jwt)
            if messages is None:
                return jsonify({'success': False, 'error': '获取 Cloudflare 邮件失败'})

            parsed_messages = []
            for index, item in enumerate(messages):
                raw_email = item.get('raw')
                if not raw_email:
                    continue
                fallback_id = item.get('id') or f"{email_addr}-{index}-{hashlib.sha256(raw_email.encode('utf-8', 'replace')).hexdigest()}"
                parsed_messages.append(parse_raw_email_to_temp_message(email_addr, raw_email, fallback_id))
            save_temp_email_messages(email_addr, parsed_messages)
            msg = get_temp_email_message_by_id(message_id)

        if msg:
            return jsonify({
                'success': True,
                'email': {
                    'id': msg.get('message_id'),
                    'from': msg.get('from_address', '未知'),
                    'to': email_addr,
                    'subject': msg.get('subject', '无主题'),
                    'body': msg.get('html_content') if msg.get('has_html') else msg.get('content', ''),
                    'body_type': 'html' if msg.get('has_html') else 'text',
                    'date': msg.get('created_at', ''),
                    'timestamp': msg.get('timestamp', 0)
                }
            })
        return jsonify({'success': False, 'error': '邮件不存在'})
    else:
        # GPTMail: 保持原有逻辑
        msg = get_temp_email_message_by_id(message_id)

        if not msg:
            api_msg = get_temp_email_detail_from_api(message_id)
            if api_msg:
                save_temp_email_messages(email_addr, [api_msg])
                msg = get_temp_email_message_by_id(message_id)

        if msg:
            return jsonify({
                'success': True,
                'email': {
                    'id': msg.get('message_id'),
                    'from': msg.get('from_address', '未知'),
                    'to': email_addr,
                    'subject': msg.get('subject', '无主题'),
                    'body': msg.get('html_content') if msg.get('has_html') else msg.get('content', ''),
                    'body_type': 'html' if msg.get('has_html') else 'text',
                    'date': msg.get('created_at', ''),
                    'timestamp': msg.get('timestamp', 0)
                }
            })
        else:
            return jsonify({'success': False, 'error': '邮件不存在'})


@app.route('/api/temp-emails/<path:email_addr>/messages/<path:message_id>', methods=['DELETE'])
@login_required
def api_delete_temp_email_message(email_addr, message_id):
    """删除临时邮件"""
    return jsonify({'success': False, 'error': '临时邮箱单封删信功能已暂时关闭'})


@app.route('/api/temp-emails/<path:email_addr>/clear', methods=['DELETE'])
@login_required
def api_clear_temp_email_messages(email_addr):
    """清空临时邮箱的所有邮件"""
    return jsonify({'success': False, 'error': '临时邮箱清空功能已暂时关闭'})


@app.route('/api/temp-emails/<path:email_addr>/refresh', methods=['POST'])
@login_required
def api_refresh_temp_email_messages(email_addr):
    """刷新临时邮箱的邮件"""
    temp_email = get_temp_email_by_address(email_addr)
    provider = temp_email.get('provider', 'gptmail') if temp_email else 'gptmail'

    if provider == 'duckmail':
        token = get_duckmail_token_for_email(email_addr)
        if not token:
            return jsonify({'success': False, 'error': 'DuckMail Token 无效，请尝试重新创建邮箱'})

        messages = duckmail_get_messages(token)
        if messages is None:
            # Token 可能过期，尝试刷新
            token = duckmail_refresh_token(email_addr)
            if token:
                messages = duckmail_get_messages(token)

        if messages is not None:
            unified_messages = []
            for msg in messages:
                from_info = msg.get('from', {})
                from_addr = from_info.get('address', '') if isinstance(from_info, dict) else str(from_info)
                unified_messages.append({
                    'id': msg.get('id', ''),
                    'from_address': from_addr,
                    'subject': msg.get('subject', '无主题'),
                    'content': msg.get('text', ''),
                    'html_content': msg.get('html', [''])[0] if isinstance(msg.get('html'), list) else (msg.get('html', '') or ''),
                    'has_html': bool(msg.get('html')),
                    'timestamp': int(datetime.fromisoformat(msg['createdAt'].replace('Z', '+00:00')).timestamp()) if msg.get('createdAt') else 0
                })
            saved = save_temp_email_messages(email_addr, unified_messages)

            formatted = []
            for msg in unified_messages:
                formatted.append({
                    'id': msg.get('id'),
                    'from': msg.get('from_address', '未知'),
                    'subject': msg.get('subject', '无主题'),
                    'body_preview': (msg.get('content', '') or '')[:200],
                    'date': msg.get('timestamp', 0),
                    'timestamp': msg.get('timestamp', 0),
                    'has_html': 1 if msg.get('has_html') else 0
                })

            return jsonify({
                'success': True,
                'emails': formatted,
                'count': len(formatted),
                'new_count': saved,
                'method': 'DuckMail'
            })
        else:
            return jsonify({'success': False, 'error': '获取 DuckMail 邮件失败'})
    elif provider == 'cloudflare':
        jwt = get_cloudflare_jwt_for_email(email_addr)
        if not jwt:
            return jsonify({'success': False, 'error': 'Cloudflare JWT 无效，请重新导入或创建邮箱'})

        messages = cloudflare_get_messages(jwt)
        if messages is None:
            return jsonify({'success': False, 'error': '获取 Cloudflare 邮件失败'})

        unified_messages = []
        for index, item in enumerate(messages):
            raw_email = item.get('raw')
            if not raw_email:
                continue
            fallback_id = item.get('id') or f"{email_addr}-{index}-{hashlib.sha256(raw_email.encode('utf-8', 'replace')).hexdigest()}"
            fallback_timestamp = 0
            for key in ('createdAt', 'created_at', 'date'):
                if item.get(key):
                    try:
                        fallback_timestamp = int(datetime.fromisoformat(str(item[key]).replace('Z', '+00:00')).timestamp())
                        break
                    except Exception:
                        continue
            unified_messages.append(
                parse_raw_email_to_temp_message(email_addr, raw_email, fallback_id, fallback_timestamp)
            )
        saved = save_temp_email_messages(email_addr, unified_messages)

        formatted = []
        for msg in unified_messages:
            formatted.append({
                'id': msg.get('id'),
                'from': msg.get('from_address', '未知'),
                'subject': msg.get('subject', '无主题'),
                'body_preview': (msg.get('content', '') or '')[:200],
                'date': msg.get('timestamp', 0),
                'timestamp': msg.get('timestamp', 0),
                'has_html': 1 if msg.get('has_html') else 0
            })

        return jsonify({
            'success': True,
            'emails': formatted,
            'count': len(formatted),
            'new_count': saved,
            'method': 'Cloudflare'
        })
    else:
        # GPTMail: 保持原有逻辑
        api_messages = get_temp_emails_from_api(email_addr)

        if api_messages is not None:
            saved = save_temp_email_messages(email_addr, api_messages)
            messages = get_temp_email_messages(email_addr)

            formatted = []
            for msg in messages:
                formatted.append({
                    'id': msg.get('message_id'),
                    'from': msg.get('from_address', '未知'),
                    'subject': msg.get('subject', '无主题'),
                    'body_preview': (msg.get('content', '') or '')[:200],
                    'date': msg.get('created_at', ''),
                    'timestamp': msg.get('timestamp', 0),
                    'has_html': msg.get('has_html', 0)
                })

            return jsonify({
                'success': True,
                'emails': formatted,
                'count': len(formatted),
                'new_count': saved,
                'method': 'GPTMail'
            })
        else:
            return jsonify({'success': False, 'error': '获取邮件失败'})


# ==================== OAuth Token API ====================

@app.route('/api/oauth/auth-url', methods=['GET'])
@login_required
def api_get_oauth_auth_url():
    """生成 OAuth 授权 URL"""
    import urllib.parse

    base_auth_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    params = {
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(OAUTH_SCOPES),
        "state": "12345"
    }
    auth_url = f"{base_auth_url}?{urllib.parse.urlencode(params)}"

    return jsonify({
        'success': True,
        'auth_url': auth_url,
        'client_id': OAUTH_CLIENT_ID,
        'redirect_uri': OAUTH_REDIRECT_URI
    })


@app.route('/api/oauth/exchange-token', methods=['POST'])
@login_required
def api_exchange_oauth_token():
    """使用授权码换取 Refresh Token"""
    import urllib.parse

    data = request.json
    redirected_url = data.get('redirected_url', '').strip()

    if not redirected_url:
        return jsonify({'success': False, 'error': '请提供授权后的完整 URL'})

    # 从 URL 中提取 code
    try:
        parsed_url = urllib.parse.urlparse(redirected_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        auth_code = query_params['code'][0]
    except (KeyError, IndexError):
        return jsonify({'success': False, 'error': '无法从 URL 中提取授权码，请检查 URL 是否正确'})

    # 使用 Code 换取 Token (Public Client 不需要 client_secret)
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    token_data = {
        "client_id": OAUTH_CLIENT_ID,
        "code": auth_code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": " ".join(OAUTH_SCOPES)
    }

    try:
        response = requests.post(token_url, data=token_data, timeout=30)
    except Exception as e:
        return jsonify({'success': False, 'error': f'请求失败: {str(e)}'})

    if response.status_code == 200:
        tokens = response.json()
        refresh_token = tokens.get('refresh_token')

        if not refresh_token:
            return jsonify({'success': False, 'error': '未能获取 Refresh Token'})

        return jsonify({
            'success': True,
            'refresh_token': refresh_token,
            'client_id': OAUTH_CLIENT_ID,
            'token_type': tokens.get('token_type'),
            'expires_in': tokens.get('expires_in'),
            'scope': tokens.get('scope')
        })
    else:
        error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        error_msg = error_data.get('error_description', response.text)
        return jsonify({'success': False, 'error': f'获取令牌失败: {error_msg}'})


# ==================== 设置 API ====================

@app.route('/api/settings/validate-cron', methods=['POST'])
@login_required
def api_validate_cron():
    """验证 Cron 表达式"""
    try:
        from croniter import croniter
        from datetime import datetime
    except ImportError:
        return jsonify({'success': False, 'error': 'croniter 库未安装，请运行: pip install croniter'})

    data = request.json
    cron_expr = data.get('cron_expression', '').strip()

    if not cron_expr:
        return jsonify({'success': False, 'error': 'Cron 表达式不能为空'})

    try:
        base_time = datetime.now()
        cron = croniter(cron_expr, base_time)

        next_run = cron.get_next(datetime)

        future_runs = []
        temp_cron = croniter(cron_expr, base_time)
        for _ in range(5):
            future_runs.append(temp_cron.get_next(datetime).isoformat())

        return jsonify({
            'success': True,
            'valid': True,
            'next_run': next_run.isoformat(),
            'future_runs': future_runs
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'valid': False,
            'error': f'Cron 表达式无效: {str(e)}'
        })


@app.route('/api/settings', methods=['GET'])
@login_required
def api_get_settings():
    """获取所有设置"""
    settings = get_all_settings()
    # 隐藏密码的部分字符
    if 'login_password' in settings:
        pwd = settings['login_password']
        if len(pwd) > 2:
            settings['login_password_masked'] = pwd[0] + '*' * (len(pwd) - 2) + pwd[-1]
        else:
            settings['login_password_masked'] = '*' * len(pwd)
    # 返回解密后的对外 API Key
    settings['external_api_key'] = get_external_api_key()
    # 返回 DuckMail 设置
    settings['duckmail_base_url'] = get_duckmail_base_url()
    settings['duckmail_api_key'] = get_duckmail_api_key()
    settings['cloudflare_worker_domain'] = get_cloudflare_worker_domain()
    settings['cloudflare_email_domains'] = ', '.join(get_cloudflare_email_domains())
    settings['cloudflare_admin_password'] = get_cloudflare_admin_password()
    return jsonify({'success': True, 'settings': settings})


@app.route('/api/settings', methods=['PUT'])
@login_required
def api_update_settings():
    """更新设置"""
    data = request.json
    updated = []
    errors = []

    # 更新登录密码
    if 'login_password' in data:
        new_password = data['login_password'].strip()
        if new_password:
            if len(new_password) < 8:
                errors.append('密码长度至少为 8 位')
            else:
                # 哈希新密码
                hashed_password = hash_password(new_password)
                if set_setting('login_password', hashed_password):
                    updated.append('登录密码')
                else:
                    errors.append('更新登录密码失败')

    # 更新 GPTMail API Key
    if 'gptmail_api_key' in data:
        new_api_key = data['gptmail_api_key'].strip()
        if new_api_key:
            if set_setting('gptmail_api_key', new_api_key):
                updated.append('GPTMail API Key')
            else:
                errors.append('更新 GPTMail API Key 失败')

    # 更新刷新周期
    if 'refresh_interval_days' in data:
        try:
            days = int(data['refresh_interval_days'])
            if days < 1 or days > 90:
                errors.append('刷新周期必须在 1-90 天之间')
            elif set_setting('refresh_interval_days', str(days)):
                updated.append('刷新周期')
            else:
                errors.append('更新刷新周期失败')
        except ValueError:
            errors.append('刷新周期必须是数字')

    # 更新刷新间隔
    if 'refresh_delay_seconds' in data:
        try:
            seconds = int(data['refresh_delay_seconds'])
            if seconds < 0 or seconds > 60:
                errors.append('刷新间隔必须在 0-60 秒之间')
            elif set_setting('refresh_delay_seconds', str(seconds)):
                updated.append('刷新间隔')
            else:
                errors.append('更新刷新间隔失败')
        except ValueError:
            errors.append('刷新间隔必须是数字')

    # 更新 Cron 表达式
    if 'refresh_cron' in data:
        cron_expr = data['refresh_cron'].strip()
        if cron_expr:
            try:
                from croniter import croniter
                from datetime import datetime
                croniter(cron_expr, datetime.now())
                if set_setting('refresh_cron', cron_expr):
                    updated.append('Cron 表达式')
                else:
                    errors.append('更新 Cron 表达式失败')
            except ImportError:
                errors.append('croniter 库未安装')
            except Exception as e:
                errors.append(f'Cron 表达式无效: {str(e)}')

    # 更新刷新策略
    if 'use_cron_schedule' in data:
        use_cron = str(data['use_cron_schedule']).lower()
        if use_cron in ('true', 'false'):
            if set_setting('use_cron_schedule', use_cron):
                updated.append('刷新策略')
            else:
                errors.append('更新刷新策略失败')
        else:
            errors.append('刷新策略必须是 true 或 false')

    # 更新定时刷新开关
    if 'enable_scheduled_refresh' in data:
        enable = str(data['enable_scheduled_refresh']).lower()
        if enable in ('true', 'false'):
            if set_setting('enable_scheduled_refresh', enable):
                updated.append('定时刷新开关')
            else:
                errors.append('更新定时刷新开关失败')
        else:
            errors.append('定时刷新开关必须是 true 或 false')

    # 更新对外 API Key
    if 'external_api_key' in data:
        new_ext_key = data['external_api_key'].strip()
        if new_ext_key:
            if set_setting('external_api_key', new_ext_key):
                updated.append('对外 API Key')
            else:
                errors.append('更新对外 API Key 失败')
        else:
            if set_setting('external_api_key', ''):
                updated.append('对外 API Key（已清空）')

    # 更新 DuckMail 设置
    if 'duckmail_base_url' in data:
        new_url = data['duckmail_base_url'].strip()
        if set_setting('duckmail_base_url', new_url):
            updated.append('DuckMail API 地址')
        else:
            errors.append('更新 DuckMail API 地址失败')

    if 'duckmail_api_key' in data:
        new_dk_key = data['duckmail_api_key'].strip()
        if set_setting('duckmail_api_key', new_dk_key):
            updated.append('DuckMail API Key')
        else:
            errors.append('更新 DuckMail API Key 失败')

    if 'cloudflare_worker_domain' in data:
        new_domain = data['cloudflare_worker_domain'].strip()
        if set_setting('cloudflare_worker_domain', new_domain):
            updated.append('Cloudflare Worker 域名')
        else:
            errors.append('更新 Cloudflare Worker 域名失败')

    if 'cloudflare_email_domains' in data:
        new_domains = data['cloudflare_email_domains'].strip()
        if set_setting('cloudflare_email_domains', new_domains):
            updated.append('Cloudflare 邮箱域名')
        else:
            errors.append('更新 Cloudflare 邮箱域名失败')

    if 'cloudflare_admin_password' in data:
        new_password = data['cloudflare_admin_password'].strip()
        if set_setting('cloudflare_admin_password', new_password):
            updated.append('Cloudflare 管理密码')
        else:
            errors.append('更新 Cloudflare 管理密码失败')

    if errors:
        return jsonify({'success': False, 'error': '；'.join(errors)})

    if updated:
        return jsonify({'success': True, 'message': f'已更新：{", ".join(updated)}'})
    else:
        return jsonify({'success': False, 'error': '没有需要更新的设置'})


# ==================== 对外 API ====================

@app.route('/api/external/emails', methods=['GET'])
@csrf_exempt
@api_key_required
def api_external_get_emails():
    """对外 API：通过 API Key 获取邮件列表"""
    email_addr = request.args.get('email', '').strip()
    folder = request.args.get('folder', 'inbox').strip().lower()
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))

    if not email_addr:
        return jsonify({'success': False, 'error': '缺少 email 参数'}), 400

    # 验证 folder 参数
    valid_folders = ['inbox', 'junkemail']
    if folder not in valid_folders:
        return jsonify({'success': False, 'error': f'folder 参数无效，支持: {", ".join(valid_folders)}'}), 400

    # 限制分页大小
    if top > 50:
        top = 50

    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '邮箱账号不存在'}), 404

    # 获取分组代理设置
    proxy_url = ''
    if account.get('group_id'):
        group = get_group_by_id(account['group_id'])
        if group:
            proxy_url = group.get('proxy_url', '') or ''

    # 收集所有错误信息
    all_errors = {}

    # 1. 尝试 Graph API
    graph_result = get_emails_graph(account['client_id'], account['refresh_token'], folder, skip, top, proxy_url)
    if graph_result.get('success'):
        emails = graph_result.get('emails', [])
        formatted = []
        for e in emails:
            formatted.append({
                'id': e.get('id'),
                'subject': e.get('subject', '无主题'),
                'from': e.get('from', {}).get('emailAddress', {}).get('address', '未知'),
                'date': e.get('receivedDateTime', ''),
                'is_read': e.get('isRead', False),
                'has_attachments': e.get('hasAttachments', False),
                'body_preview': e.get('bodyPreview', '')
            })
        return jsonify({
            'success': True,
            'emails': formatted,
            'method': 'Graph API',
            'has_more': len(formatted) >= top
        })
    else:
        graph_error = graph_result.get('error')
        all_errors['graph'] = graph_error
        if isinstance(graph_error, dict) and graph_error.get('type') in ('ProxyError', 'ConnectionError'):
            return jsonify({'success': False, 'error': '代理连接失败', 'details': all_errors})

    # 2. 尝试新版 IMAP
    imap_new_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_NEW
    )
    if imap_new_result.get('success'):
        return jsonify({
            'success': True,
            'emails': imap_new_result.get('emails', []),
            'method': 'IMAP (New)',
            'has_more': False
        })
    else:
        all_errors['imap_new'] = imap_new_result.get('error')

    # 3. 尝试旧版 IMAP
    imap_old_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_OLD
    )
    if imap_old_result.get('success'):
        return jsonify({
            'success': True,
            'emails': imap_old_result.get('emails', []),
            'method': 'IMAP (Old)',
            'has_more': False
        })
    else:
        all_errors['imap_old'] = imap_old_result.get('error')

    return jsonify({'success': False, 'error': '无法获取邮件，所有方式均失败', 'details': all_errors})


# ==================== 定时任务调度器 ====================

def init_scheduler():
    """初始化定时任务调度器"""
    global scheduler_instance

    with scheduler_lock:
        if scheduler_instance is not None:
            return scheduler_instance

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            import atexit

            scheduler = BackgroundScheduler()

            with app.app_context():
                enable_scheduled = get_setting('enable_scheduled_refresh', 'true').lower() == 'true'

                if not enable_scheduled:
                    print("✓ 定时刷新已禁用")
                    return None

                use_cron = get_setting('use_cron_schedule', 'false').lower() == 'true'

                if use_cron:
                    cron_expr = get_setting('refresh_cron', '0 2 * * *')
                    try:
                        from croniter import croniter
                        from datetime import datetime
                        croniter(cron_expr, datetime.now())

                        parts = cron_expr.split()
                        if len(parts) == 5:
                            minute, hour, day, month, day_of_week = parts
                            trigger = CronTrigger(
                                minute=minute,
                                hour=hour,
                                day=day,
                                month=month,
                                day_of_week=day_of_week
                            )
                            scheduler.add_job(
                                func=scheduled_refresh_task,
                                trigger=trigger,
                                id='token_refresh',
                                name='Token 定时刷新',
                                replace_existing=True
                            )
                            scheduler.start()
                            scheduler_instance = scheduler
                            print(f"✓ 定时任务已启动：Cron 表达式 '{cron_expr}'")
                            atexit.register(lambda: scheduler.shutdown())
                            return scheduler_instance
                        else:
                            print(f"⚠ Cron 表达式格式错误，回退到默认配置")
                    except Exception as e:
                        print(f"⚠ Cron 表达式解析失败: {str(e)}，回退到默认配置")

                refresh_interval_days = int(get_setting('refresh_interval_days', '30'))
                scheduler.add_job(
                    func=scheduled_refresh_task,
                    trigger=CronTrigger(hour=2, minute=0),
                    id='token_refresh',
                    name='Token 定时刷新',
                    replace_existing=True
                )

                scheduler.start()
                scheduler_instance = scheduler
                print(f"✓ 定时任务已启动：每天凌晨 2:00 检查刷新（周期：{refresh_interval_days} 天）")

            atexit.register(lambda: scheduler.shutdown())

            return scheduler_instance
        except ImportError:
            print("⚠ APScheduler 未安装，定时任务功能不可用")
            print("  安装命令：pip install APScheduler>=3.10.0")
            return None
        except Exception as e:
            print(f"⚠ 定时任务初始化失败：{str(e)}")
            return None


def ensure_scheduler_started():
    """确保调度器已启动（兼容 gunicorn / docker compose）"""
    if os.getenv('WERKZEUG_RUN_MAIN') == 'false':
        return None
    return init_scheduler()


def scheduled_refresh_task():
    """定时刷新任务（由调度器调用）"""
    from datetime import datetime, timedelta

    try:
        with app.app_context():
            enable_scheduled = get_setting('enable_scheduled_refresh', 'true').lower() == 'true'

            if not enable_scheduled:
                print(f"[定时任务] 定时刷新已禁用，跳过执行")
                return

            use_cron = get_setting('use_cron_schedule', 'false').lower() == 'true'

            if use_cron:
                print(f"[定时任务] 使用 Cron 调度，直接执行刷新...")
                trigger_refresh_internal()
                print(f"[定时任务] Token 刷新完成")
                return

            refresh_interval_days = int(get_setting('refresh_interval_days', '30'))

        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('''
            SELECT MAX(created_at) as last_refresh
            FROM account_refresh_logs
            WHERE refresh_type = 'scheduled'
        ''')
        row = cursor.fetchone()
        conn.close()

        last_refresh = row['last_refresh'] if row and row['last_refresh'] else None

        if last_refresh:
            last_refresh_time = datetime.fromisoformat(last_refresh)
            next_refresh_time = last_refresh_time + timedelta(days=refresh_interval_days)
            if datetime.now() < next_refresh_time:
                print(f"[定时任务] 距离上次刷新未满 {refresh_interval_days} 天，跳过本次刷新")
                return

        print(f"[定时任务] 开始执行 Token 刷新...")
        trigger_refresh_internal()
        print(f"[定时任务] Token 刷新完成")

    except Exception as e:
        print(f"[定时任务] 执行失败：{str(e)}")


ensure_scheduler_started()


def trigger_refresh_internal():
    """内部触发刷新（不通过 HTTP）"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    try:
        # 获取刷新间隔配置
        cursor_settings = conn.execute("SELECT value FROM settings WHERE key = 'refresh_delay_seconds'")
        delay_row = cursor_settings.fetchone()
        delay_seconds = int(delay_row['value']) if delay_row else 5

        # 清理超过半年的刷新记录
        conn.execute("DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')")
        conn.commit()

        cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active'")
        accounts = cursor.fetchall()

        total = len(accounts)
        success_count = 0
        failed_count = 0

        for index, account in enumerate(accounts, 1):
            account_id = account['id']
            account_email = account['email']
            client_id = account['client_id']
            encrypted_refresh_token = account['refresh_token']

            try:
                refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
            except Exception as e:
                failed_count += 1
                error_msg = f"解密 token 失败: {str(e)}"
                conn.execute('''
                    INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                    VALUES (?, ?, ?, ?, ?)
                ''', (account_id, account_email, 'scheduled', 'failed', error_msg))
                conn.commit()
                continue

            # 获取分组代理设置
            proxy_url = ''
            group_id = account['group_id']
            if group_id:
                group_cursor = conn.execute('SELECT proxy_url FROM groups WHERE id = ?', (group_id,))
                group_row = group_cursor.fetchone()
                if group_row:
                    proxy_url = group_row['proxy_url'] or ''

            success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

            conn.execute('''
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (account_id, account_email, 'scheduled', 'success' if success else 'failed', error_msg))

            if success:
                conn.execute('''
                    UPDATE accounts
                    SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (account_id,))
                success_count += 1
            else:
                failed_count += 1

            conn.commit()

            if index < total and delay_seconds > 0:
                time.sleep(delay_seconds)

        print(f"[定时任务] 刷新结果：总计 {total}，成功 {success_count}，失败 {failed_count}")

    finally:
        conn.close()


# ==================== 错误处理 ====================

@app.errorhandler(400)
def bad_request(error):
    """处理400错误"""
    print(f"400 Bad Request: {error}")
    return jsonify({'success': False, 'error': '请求格式错误'}), 400


@app.errorhandler(Exception)
def handle_exception(error):
    """处理未捕获的异常"""
    print(f"Unhandled exception: {error}")
    import traceback
    traceback.print_exc()
    return jsonify({'success': False, 'error': str(error)}), 500


# ==================== 主程序 ====================

if __name__ == '__main__':
    # 从环境变量获取配置
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    debug = os.getenv('FLASK_ENV', 'production') != 'production'

    print("=" * 60)
    print("Outlook 邮件 Web 应用")
    print("=" * 60)
    print(f"访问地址: http://{host}:{port}")
    print(f"运行模式: {'开发' if debug else '生产'}")
    print("=" * 60)

    app.run(debug=debug, host=host, port=port)

    # 初始化定时任务
    scheduler = init_scheduler()

    app.run(debug=debug, host=host, port=port)
