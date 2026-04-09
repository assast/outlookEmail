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
import smtplib
import bcrypt
import base64
import html
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote, urlparse, unquote
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

try:
    import socks
except ImportError:
    socks = None

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
proxy_socket_lock = threading.RLock()


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

try:
    with open('VERSION', 'r', encoding='utf-8') as version_file:
        APP_VERSION = version_file.read().strip() or '1.0.0'
except Exception:
    APP_VERSION = '1.0.0'

IMAP_IDENTITY_FIELDS = {
    'name': os.getenv('IMAP_ID_NAME', 'outlookEmail'),
    'version': os.getenv('IMAP_ID_VERSION', APP_VERSION),
    'vendor': os.getenv('IMAP_ID_VENDOR', 'outlookEmail'),
    'support-email': os.getenv('IMAP_ID_SUPPORT_EMAIL', ''),
}

MAIL_PROVIDERS = {
    "outlook": {
        "label": "Outlook",
        "imap_host": IMAP_SERVER_NEW,
        "imap_port": 993,
        "account_type": "outlook",
    },
    "gmail": {
        "label": "Gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "qq": {
        "label": "QQ邮箱",
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "163": {
        "label": "163邮箱",
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "126": {
        "label": "126邮箱",
        "imap_host": "imap.126.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "yahoo": {
        "label": "Yahoo",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "aliyun": {
        "label": "阿里邮箱",
        "imap_host": "imap.aliyun.com",
        "imap_port": 993,
        "account_type": "imap",
    },
    "custom": {
        "label": "自定义 IMAP",
        "imap_host": "",
        "imap_port": 993,
        "account_type": "imap",
    },
}

DOMAIN_PROVIDER_MAP = {
    "outlook.com": "outlook",
    "hotmail.com": "outlook",
    "live.com": "outlook",
    "live.cn": "outlook",
    "gmail.com": "gmail",
    "googlemail.com": "gmail",
    "qq.com": "qq",
    "foxmail.com": "qq",
    "163.com": "163",
    "126.com": "126",
    "yahoo.com": "yahoo",
    "yahoo.co.jp": "yahoo",
    "yahoo.co.uk": "yahoo",
    "aliyun.com": "aliyun",
    "alimail.com": "aliyun",
}

PROVIDER_FOLDER_MAP = {
    "gmail": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["[Gmail]/Spam", "[Gmail]/垃圾邮件"],
        "deleteditems": ["[Gmail]/Trash", "[Gmail]/已删除邮件"],
    },
    "qq": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["Junk", "&V4NXPpCuTvY-"],
        "deleteditems": ["Deleted Messages", "&XfJT0ZABkK5O9g-"],
    },
    "163": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["Junk", "&V4NXPpCuTvY-"],
        "deleteditems": ["Deleted Messages", "&XfJT0ZABkK5O9g-"],
    },
    "126": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["Junk", "&V4NXPpCuTvY-"],
        "deleteditems": ["Deleted Messages", "&XfJT0ZABkK5O9g-"],
    },
    "yahoo": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["Bulk Mail", "Spam"],
        "deleteditems": ["Trash"],
    },
    "_default": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["Junk", "Junk Email", "Spam", "SPAM", "Bulk Mail"],
        "deleteditems": ["Trash", "Deleted", "Deleted Items", "Deleted Messages"],
    },
}

IMAP_FOLDER_MATCH_ALIASES = {
    "inbox": {"inbox", "收件箱"},
    "junkemail": {"junk", "junk email", "spam", "bulk mail", "垃圾邮件", "垃圾箱"},
    "deleteditems": {"trash", "deleted", "deleted items", "deleted messages", "已删除邮件", "垃圾箱"},
}

FORWARD_CHANNEL_EMAIL = "email"
FORWARD_CHANNEL_TELEGRAM = "telegram"
FORWARD_CHANNEL_SMTP_SETTING = "smtp"
FORWARD_CHANNEL_TG_SETTING = "telegram"
SMTP_FORWARD_PROVIDERS = ('outlook', 'qq', '163', '126', 'yahoo', 'aliyun', 'custom')

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


def infer_provider_from_email(email_addr: str) -> str:
    if not email_addr or '@' not in email_addr:
        return 'custom'
    return DOMAIN_PROVIDER_MAP.get(email_addr.rsplit('@', 1)[-1].strip().lower(), 'custom')


def normalize_provider(provider: str, email_addr: str = '') -> str:
    provider = (provider or '').strip().lower()
    if provider == 'auto':
        provider = infer_provider_from_email(email_addr)
    if provider not in MAIL_PROVIDERS:
        provider = infer_provider_from_email(email_addr) if email_addr else 'outlook'
    if provider not in MAIL_PROVIDERS:
        provider = 'custom'
    return provider


def get_provider_meta(provider: str, email_addr: str = '') -> Dict[str, Any]:
    provider_key = normalize_provider(provider, email_addr)
    meta = dict(MAIL_PROVIDERS.get(provider_key, MAIL_PROVIDERS['custom']))
    meta['key'] = provider_key
    return meta


def get_imap_folder_candidates(provider: str, folder: str) -> List[str]:
    provider_key = (provider or '').strip().lower() or '_default'
    folder_key = (folder or 'inbox').strip().lower()
    folder_map = PROVIDER_FOLDER_MAP.get(provider_key, PROVIDER_FOLDER_MAP['_default'])
    return folder_map.get(folder_key, PROVIDER_FOLDER_MAP['_default'].get(folder_key, ['INBOX']))


def decode_imap_utf7(value: str) -> str:
    if not value or '&' not in value:
        return value or ''
    decoded_parts = []
    index = 0
    while index < len(value):
        if value[index] != '&':
            decoded_parts.append(value[index])
            index += 1
            continue
        end = value.find('-', index + 1)
        if end == -1:
            decoded_parts.append(value[index:])
            break
        if end == index + 1:
            decoded_parts.append('&')
            index = end + 1
            continue
        encoded = value[index + 1:end].replace(',', '/')
        padding = '=' * ((4 - len(encoded) % 4) % 4)
        try:
            decoded = base64.b64decode(f'{encoded}{padding}').decode('utf-16-be')
            decoded_parts.append(decoded)
        except Exception:
            decoded_parts.append(value[index:end + 1])
        index = end + 1
    return ''.join(decoded_parts)


def normalize_imap_mailbox_name(value: str) -> str:
    text = str(value or '').strip().strip('"')
    text = re.sub(r'\s+', ' ', text)
    return text.lower()


def extract_imap_list_mailbox_name(raw_item: Any) -> str:
    if raw_item is None:
        return ''
    line = raw_item.decode('utf-8', errors='ignore') if isinstance(raw_item, (bytes, bytearray)) else str(raw_item)
    line = line.strip()
    if not line:
        return ''
    quoted_parts = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
    if quoted_parts:
        return quoted_parts[-1].replace(r'\"', '"').replace(r'\\', '\\')
    return line.rsplit(' ', 1)[-1].strip('"')


def build_imap_mailbox_match_profile(mailbox_name: str) -> Dict[str, set[str]]:
    variants = []
    for candidate in [str(mailbox_name or '').strip()]:
        if candidate and candidate not in variants:
            variants.append(candidate)
        decoded_candidate = decode_imap_utf7(candidate)
        if decoded_candidate and decoded_candidate not in variants:
            variants.append(decoded_candidate)

    full_names = set()
    terminal_names = set()
    for variant in variants:
        normalized = normalize_imap_mailbox_name(variant)
        if normalized:
            full_names.add(normalized)
        terminal_segment = ''
        for segment in re.split(r'[./\\\\]+', variant):
            if normalize_imap_mailbox_name(segment):
                terminal_segment = segment
        terminal_normalized = normalize_imap_mailbox_name(terminal_segment)
        if terminal_normalized:
            terminal_names.add(terminal_normalized)
    return {'full': full_names, 'terminal': terminal_names}


def list_imap_mailboxes(mail) -> List[str]:
    try:
        status, folder_list = mail.list()
    except Exception:
        return []
    if status != 'OK' or not folder_list:
        return []

    mailboxes = []
    for raw_item in folder_list:
        mailbox_name = extract_imap_list_mailbox_name(raw_item)
        if mailbox_name and mailbox_name not in mailboxes:
            mailboxes.append(mailbox_name)
    return mailboxes


def rank_imap_listed_mailboxes(folder: str, candidates: List[str], available_folders: List[str]) -> List[str]:
    candidate_names = set()
    for candidate in candidates:
        profile = build_imap_mailbox_match_profile(candidate)
        candidate_names.update(profile['full'])
        candidate_names.update(profile['terminal'])

    alias_names = {
        normalize_imap_mailbox_name(alias)
        for alias in IMAP_FOLDER_MATCH_ALIASES.get((folder or '').strip().lower(), set())
        if normalize_imap_mailbox_name(alias)
    }

    buckets = {
        'candidate_full': [],
        'candidate_segment': [],
        'alias_full': [],
        'alias_segment': [],
    }

    for mailbox_name in available_folders:
        profile = build_imap_mailbox_match_profile(mailbox_name)
        if profile['full'] & candidate_names:
            buckets['candidate_full'].append(mailbox_name)
        elif profile['terminal'] & candidate_names:
            buckets['candidate_segment'].append(mailbox_name)
        elif profile['full'] & alias_names:
            buckets['alias_full'].append(mailbox_name)
        elif profile['terminal'] & alias_names:
            buckets['alias_segment'].append(mailbox_name)

    ranked = []
    for bucket_name in ('candidate_full', 'candidate_segment', 'alias_full', 'alias_segment'):
        for mailbox_name in buckets[bucket_name]:
            if mailbox_name not in ranked:
                ranked.append(mailbox_name)
    return ranked


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
        db.execute('PRAGMA foreign_keys = ON')
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
    conn.execute('PRAGMA foreign_keys = ON')
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
            client_id TEXT DEFAULT '',
            refresh_token TEXT DEFAULT '',
            group_id INTEGER,
            remark TEXT,
            status TEXT DEFAULT 'active',
            account_type TEXT DEFAULT 'outlook',
            provider TEXT DEFAULT 'outlook',
            imap_host TEXT,
            imap_port INTEGER DEFAULT 993,
            imap_password TEXT,
            forward_enabled INTEGER DEFAULT 0,
            forward_last_checked_at TIMESTAMP,
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forward_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, message_id, channel),
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forwarding_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            account_email TEXT NOT NULL,
            message_id TEXT NOT NULL,
            channel TEXT NOT NULL,
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

    # 创建账号别名表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            alias_email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
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
    if 'account_type' not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN account_type TEXT DEFAULT 'outlook'")
    if 'provider' not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN provider TEXT DEFAULT 'outlook'")
    if 'imap_host' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN imap_host TEXT')
    if 'imap_port' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN imap_port INTEGER DEFAULT 993')
    if 'imap_password' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN imap_password TEXT')
    if 'forward_enabled' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN forward_enabled INTEGER DEFAULT 0')
    if 'forward_last_checked_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN forward_last_checked_at TIMESTAMP')
    
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

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_check_interval_minutes', '5')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_email_window_minutes', '0')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_include_junkemail', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_channels', 'auto')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('email_forward_recipient', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_host', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_port', '465')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_username', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_password', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_from_email', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_provider', 'custom')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_use_tls', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('smtp_use_ssl', 'true')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('telegram_bot_token', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('telegram_chat_id', '')
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

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_forward_enabled
        ON accounts(forward_enabled)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_forward_logs_lookup
        ON forward_logs(account_id, message_id, channel)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_forwarding_logs_account_created
        ON forwarding_logs(account_id, created_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_forwarding_logs_status_created
        ON forwarding_logs(status, created_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_account_aliases_account_id
        ON account_aliases(account_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_account_aliases_email
        ON account_aliases(alias_email)
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


def set_setting_encrypted(key: str, value: str) -> bool:
    normalized = value.strip() if isinstance(value, str) else value
    if normalized:
        normalized = encrypt_data(normalized)
    else:
        normalized = ''
    return set_setting(key, normalized)


def get_setting_decrypted(key: str, default: str = '') -> str:
    value = get_setting(key, default)
    if not value:
        return value
    try:
        return decrypt_data(value)
    except Exception:
        return value


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
        account = resolve_account_record(row)
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


def normalize_email_address(email_addr: str) -> str:
    return str(email_addr or '').strip().lower()


def get_account_aliases(account_id: int) -> List[str]:
    db = get_db()
    rows = db.execute(
        'SELECT alias_email FROM account_aliases WHERE account_id = ? ORDER BY created_at ASC, id ASC',
        (account_id,)
    ).fetchall()
    return [str(row['alias_email']).strip() for row in rows if row['alias_email']]


def email_exists_as_primary(email_addr: str, exclude_account_id: Optional[int] = None) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    if exclude_account_id is None:
        row = db.execute('SELECT id FROM accounts WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    else:
        row = db.execute(
            'SELECT id FROM accounts WHERE LOWER(email) = ? AND id != ? LIMIT 1',
            (normalized, exclude_account_id)
        ).fetchone()
    return row is not None


def email_exists_as_alias(email_addr: str, exclude_account_id: Optional[int] = None) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    if exclude_account_id is None:
        row = db.execute(
            'SELECT account_id FROM account_aliases WHERE LOWER(alias_email) = ? LIMIT 1',
            (normalized,)
        ).fetchone()
    else:
        row = db.execute(
            'SELECT account_id FROM account_aliases WHERE LOWER(alias_email) = ? AND account_id != ? LIMIT 1',
            (normalized, exclude_account_id)
        ).fetchone()
    return row is not None


def email_exists_as_temp(email_addr: str) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    row = db.execute('SELECT id FROM temp_emails WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    return row is not None


def validate_account_aliases(account_id: int, primary_email: str, aliases: List[str]) -> tuple[List[str], List[str]]:
    cleaned = []
    errors = []
    seen = set()
    primary_normalized = normalize_email_address(primary_email)

    for raw_alias in aliases:
        normalized = normalize_email_address(raw_alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        if normalized == primary_normalized:
            errors.append(f'别名 {normalized} 不能与主邮箱相同')
            continue
        if email_exists_as_primary(normalized, exclude_account_id=account_id):
            errors.append(f'别名 {normalized} 已被其他主邮箱占用')
            continue
        if email_exists_as_alias(normalized, exclude_account_id=account_id):
            errors.append(f'别名 {normalized} 已被其他账号使用')
            continue
        if email_exists_as_temp(normalized):
            errors.append(f'别名 {normalized} 与临时邮箱地址冲突')
            continue

        cleaned.append(normalized)

    return cleaned, errors


def replace_account_aliases(account_id: int, primary_email: str, aliases: List[str], db=None) -> tuple[bool, List[str], List[str]]:
    database = db or get_db()
    cleaned_aliases, errors = validate_account_aliases(account_id, primary_email, aliases)
    if errors:
        return False, cleaned_aliases, errors

    try:
        database.execute('DELETE FROM account_aliases WHERE account_id = ?', (account_id,))
        for alias_email in cleaned_aliases:
            database.execute(
                '''
                INSERT INTO account_aliases (account_id, alias_email, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ''',
                (account_id, alias_email)
            )
        return True, cleaned_aliases, []
    except sqlite3.IntegrityError:
        return False, cleaned_aliases, ['别名保存失败，可能存在重复或冲突']


def resolve_account_record(row: sqlite3.Row, matched_alias: str = '') -> Dict[str, Any]:
    account = dict(row)
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
    if account.get('imap_password'):
        try:
            account['imap_password'] = decrypt_data(account['imap_password'])
        except Exception:
            pass
    account['provider'] = normalize_provider(account.get('provider'), account.get('email', ''))
    account['account_type'] = account.get('account_type') or get_provider_meta(
        account['provider'], account.get('email', '')
    ).get('account_type', 'outlook')
    account['aliases'] = get_account_aliases(account['id'])
    account['alias_count'] = len(account['aliases'])
    account['requested_email'] = matched_alias or account.get('email', '')
    account['matched_alias'] = matched_alias if matched_alias else ''
    return account


def resolve_account_by_address(email_addr: str) -> Optional[Dict]:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return None

    db = get_db()
    row = db.execute('SELECT * FROM accounts WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    if row:
        return resolve_account_record(row)

    alias_row = db.execute(
        '''
        SELECT a.*, aa.alias_email AS matched_alias
        FROM account_aliases aa
        JOIN accounts a ON a.id = aa.account_id
        WHERE LOWER(aa.alias_email) = ?
        LIMIT 1
        ''',
        (normalized,)
    ).fetchone()
    if not alias_row:
        return None
    return resolve_account_record(alias_row, matched_alias=alias_row['matched_alias'])


def get_account_proxy_url(account: Optional[Dict[str, Any]]) -> str:
    if not account or not account.get('group_id'):
        return ''
    group = get_group_by_id(account['group_id'])
    if not group:
        return ''
    return group.get('proxy_url', '') or ''



def get_account_by_email(email_addr: str) -> Optional[Dict]:
    """根据邮箱地址获取账号"""
    return resolve_account_by_address(email_addr)


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
    return resolve_account_record(row)


def get_latest_account_refresh_log(account_id: int, db=None) -> Optional[Dict[str, Any]]:
    """获取账号最近一次刷新结果"""
    database = db or get_db()
    row = database.execute(
        '''
        SELECT status, error_message, created_at
        FROM account_refresh_logs
        WHERE account_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        ''',
        (account_id,)
    ).fetchone()
    return dict(row) if row else None


def serialize_account_summary(account: Dict[str, Any], last_refresh_log: Optional[Dict[str, Any]] = None,
                              include_client_meta: bool = True,
                              include_imap_meta: bool = True) -> Dict[str, Any]:
    """序列化账号摘要，默认隐藏敏感字段"""
    client_id = account.get('client_id') or ''
    payload = {
        'id': account['id'],
        'email': account['email'],
        'aliases': account.get('aliases', []),
        'alias_count': account.get('alias_count', 0),
        'group_id': account.get('group_id'),
        'group_name': account.get('group_name', '默认分组'),
        'group_color': account.get('group_color', '#666666'),
        'remark': account.get('remark', ''),
        'status': account.get('status', 'active'),
        'account_type': account.get('account_type', 'outlook'),
        'provider': account.get('provider', 'outlook'),
        'forward_enabled': bool(account.get('forward_enabled')),
        'last_refresh_at': account.get('last_refresh_at', ''),
        'last_refresh_status': last_refresh_log['status'] if last_refresh_log else None,
        'last_refresh_error': last_refresh_log['error_message'] if last_refresh_log else None,
        'created_at': account.get('created_at', ''),
        'updated_at': account.get('updated_at', ''),
        'tags': account.get('tags', [])
    }
    if include_client_meta:
        payload['client_id'] = (
            client_id[:8] + '...' if client_id and len(client_id) > 8 else client_id
        )
    if include_imap_meta:
        payload['imap_host'] = account.get('imap_host', '')
        payload['imap_port'] = account.get('imap_port', 993)
    return payload


def add_account(email_addr: str, password: str, client_id: str = '', refresh_token: str = '',
                group_id: int = 1, remark: str = '', account_type: str = 'outlook',
                provider: str = 'outlook', imap_host: str = '', imap_port: int = 993,
                imap_password: str = '', forward_enabled: bool = False) -> bool:
    """添加邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password
        provider_meta = get_provider_meta(provider, email_addr)
        provider = provider_meta['key']
        account_type = account_type or provider_meta.get('account_type', 'outlook')
        imap_host = imap_host or provider_meta.get('imap_host', '')
        imap_port = int(imap_port or provider_meta.get('imap_port', 993) or 993)
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password
        provider_meta = get_provider_meta(provider, email_addr)
        provider = provider_meta['key']
        account_type = account_type or provider_meta.get('account_type', 'outlook')
        imap_host = imap_host or provider_meta.get('imap_host', '')
        imap_port = int(imap_port or provider_meta.get('imap_port', 993) or 993)

        db.execute('''
            INSERT INTO accounts (
                email, password, client_id, refresh_token, group_id, remark,
                account_type, provider, imap_host, imap_port, imap_password, forward_enabled,
                forward_last_checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark,
            account_type, provider, imap_host, imap_port, encrypted_imap_password, 1 if forward_enabled else 0,
            datetime.utcnow().isoformat() if forward_enabled else None
        ))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_account(account_id: int, email_addr: str, password: str, client_id: str,
                   refresh_token: str, group_id: int, remark: str, status: str,
                   account_type: str = 'outlook', provider: str = 'outlook',
                   imap_host: str = '', imap_port: int = 993, imap_password: str = '',
                   forward_enabled: bool = False) -> bool:
    """更新邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password

        current_account = db.execute(
            'SELECT forward_enabled, forward_last_checked_at FROM accounts WHERE id = ?',
            (account_id,)
        ).fetchone()
        should_init_forward_cursor = bool(
            forward_enabled and current_account and not current_account['forward_enabled']
        )

        if should_init_forward_cursor:
            db.execute('''
                UPDATE accounts
                SET email = ?, password = ?, client_id = ?, refresh_token = ?,
                    group_id = ?, remark = ?, status = ?, account_type = ?, provider = ?,
                    imap_host = ?, imap_port = ?, imap_password = ?, forward_enabled = ?,
                    forward_last_checked_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark, status,
                account_type, provider, imap_host, imap_port, encrypted_imap_password, 1,
                datetime.utcnow().isoformat(), account_id
            ))
        else:
            db.execute('''
                UPDATE accounts
                SET email = ?, password = ?, client_id = ?, refresh_token = ?,
                    group_id = ?, remark = ?, status = ?, account_type = ?, provider = ?,
                    imap_host = ?, imap_port = ?, imap_password = ?, forward_enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark, status,
                account_type, provider, imap_host, imap_port, encrypted_imap_password, 1 if forward_enabled else 0,
                account_id
            ))
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


def delete_accounts_by_ids(account_ids: List[int]) -> Dict[str, Any]:
    """批量删除邮箱账号。"""
    db = get_db()
    normalized_ids = []
    seen_ids = set()
    for account_id in account_ids or []:
        try:
            normalized_id = int(account_id)
        except (TypeError, ValueError):
            continue
        if normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)

    if not normalized_ids:
        return {'success': False, 'error': '请选择要删除的账号'}

    placeholders = ','.join('?' * len(normalized_ids))
    rows = db.execute(f'''
        SELECT id, email
        FROM accounts
        WHERE id IN ({placeholders})
        ORDER BY email COLLATE NOCASE ASC
    ''', normalized_ids).fetchall()

    if not rows:
        return {'success': False, 'error': '未找到可删除的账号'}

    existing_ids = [row['id'] for row in rows]
    deleted_accounts = [{'id': row['id'], 'email': row['email']} for row in rows]
    missing_ids = [account_id for account_id in normalized_ids if account_id not in set(existing_ids)]

    try:
        delete_placeholders = ','.join('?' * len(existing_ids))
        db.execute(f'DELETE FROM accounts WHERE id IN ({delete_placeholders})', existing_ids)
        db.commit()
        return {
            'success': True,
            'deleted_count': len(existing_ids),
            'deleted_accounts': deleted_accounts,
            'missing_ids': missing_ids,
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}


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
def is_probable_client_id(value: str) -> bool:
    candidate = str(value or '').strip()
    if not candidate:
        return False
    try:
        uuid.UUID(candidate)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def resolve_outlook_token_order(third: str, fourth: str,
                                account_format: str = 'client_id_refresh_token') -> tuple[str, str]:
    third = str(third or '').strip()
    fourth = str(fourth or '').strip()

    # Azure / Microsoft public client_id is normally a UUID. If one side clearly
    # looks like client_id and the other does not, auto-detect the order so that
    # pasted import lines keep working even when the UI format selector is wrong.
    third_is_client_id = is_probable_client_id(third)
    fourth_is_client_id = is_probable_client_id(fourth)
    if third_is_client_id and not fourth_is_client_id:
        return third, fourth
    if fourth_is_client_id and not third_is_client_id:
        return fourth, third

    if account_format == 'refresh_token_client_id':
        return fourth, third
    return third, fourth


def parse_account_string(account_str: str, account_format: str = 'client_id_refresh_token') -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 4 or not parts[0]:
        return None

    email_addr, password, third, fourth = parts[:4]
    client_id, refresh_token = resolve_outlook_token_order(third, fourth, account_format)

    if not client_id or not refresh_token:
        return None

    return {
        'email': email_addr,
        'password': password,
        'client_id': client_id,
        'refresh_token': refresh_token
    }


# ==================== Graph API 方式 ====================


def parse_outlook_account_string(account_str: str, account_format: str = 'client_id_refresh_token') -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 4 or not parts[0]:
        return None

    email_addr, password, third, fourth = parts[:4]
    client_id, refresh_token = resolve_outlook_token_order(third, fourth, account_format)

    if not client_id or not refresh_token:
        return None

    return {
        'email': email_addr,
        'password': password,
        'client_id': client_id,
        'refresh_token': refresh_token,
        'provider': 'outlook',
        'account_type': 'outlook',
        'imap_host': IMAP_SERVER_NEW,
        'imap_port': IMAP_PORT,
        'imap_password': '',
    }


def parse_imap_account_string(account_str: str, provider: str = 'custom', imap_host: str = '', imap_port: int = 993) -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 2 or not parts[0]:
        return None

    email_addr = parts[0]
    password = parts[1]
    provider_meta = get_provider_meta(provider, email_addr)
    provider_key = provider_meta['key']

    if provider_key == 'custom':
        if len(parts) >= 4:
            imap_host = parts[2].strip() or imap_host
            try:
                imap_port = int(parts[3].strip() or imap_port or 993)
            except ValueError:
                return None
        if not imap_host:
            return None
    else:
        imap_host = provider_meta.get('imap_host', '')
        imap_port = int(provider_meta.get('imap_port', 993) or 993)

    if not password or not imap_host:
        return None

    return {
        'email': email_addr,
        'password': '',
        'client_id': '',
        'refresh_token': '',
        'provider': provider_key,
        'account_type': 'imap',
        'imap_host': imap_host,
        'imap_port': int(imap_port or 993),
        'imap_password': password,
    }


def parse_account_import(account_str: str, account_format: str = 'client_id_refresh_token',
                         provider: str = 'outlook', imap_host: str = '', imap_port: int = 993) -> Optional[Dict]:
    provider_key = normalize_provider(provider, account_str.split('----', 1)[0].strip() if account_str else '')
    if provider_key == 'outlook':
        return parse_outlook_account_string(account_str, account_format)
    return parse_imap_account_string(account_str, provider_key, imap_host, imap_port)


def build_proxies(proxy_url: str) -> Optional[Dict[str, str]]:
    """构建 requests 的 proxies 参数"""
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


@contextmanager
def proxy_socket_context(proxy_url: str):
    if not proxy_url or not socks:
        yield
        return

    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or '').lower()
    proxy_type_map = {
        'socks5': socks.SOCKS5,
        'socks5h': socks.SOCKS5,
        'socks4': socks.SOCKS4,
        'http': socks.HTTP,
        'https': socks.HTTP,
    }
    proxy_type = proxy_type_map.get(scheme)
    if not proxy_type or not parsed.hostname or not parsed.port:
        yield
        return

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    rdns = scheme == 'socks5h'

    with proxy_socket_lock:
        original_socket = socket.socket
        try:
            socks.set_default_proxy(
                proxy_type,
                parsed.hostname,
                parsed.port,
                username=username,
                password=password,
                rdns=rdns
            )
            socket.socket = socks.socksocket
            yield
        finally:
            socket.socket = original_socket
            socks.set_default_proxy()


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

def get_access_token_imap_result(client_id: str, refresh_token: str, proxy_url: str = None) -> Dict[str, Any]:
    """获取 IMAP access_token（包含错误详情）"""
    try:
        proxies = build_proxies(proxy_url)
        res = requests.post(
            TOKEN_URL_IMAP,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
            },
            timeout=30,
            proxies=proxies
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


def get_access_token_imap(client_id: str, refresh_token: str, proxy_url: str = None) -> Optional[str]:
    """获取 IMAP access_token"""
    result = get_access_token_imap_result(client_id, refresh_token, proxy_url)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_imap(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20, proxy_url: str = None) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页和文件夹选择）- 默认使用新版服务器"""
    return get_emails_imap_with_server(account, client_id, refresh_token, folder, skip, top, IMAP_SERVER_NEW, proxy_url)


def get_emails_imap_with_server(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20, server: str = IMAP_SERVER_NEW, proxy_url: str = None) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页、文件夹选择和服务器选择）"""
    token_result = get_access_token_imap_result(client_id, refresh_token, proxy_url)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(server, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        selected_folder, folder_diagnostics = resolve_imap_folder(connection, 'outlook', folder, readonly=True)
        if not selected_folder:
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    f"无法访问文件夹，请检查账号配置",
                    "IMAPSelectError",
                    500,
                    folder_diagnostics
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


def get_email_detail_imap(account: str, client_id: str, refresh_token: str, message_id: str, folder: str = 'inbox', proxy_url: str = None) -> Optional[Dict]:
    """使用 IMAP 获取邮件详情"""
    access_token = get_access_token_imap(client_id, refresh_token, proxy_url)
    if not access_token:
        return None

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        selected_folder, _ = resolve_imap_folder(connection, 'outlook', folder, readonly=True)
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

def strip_html_content(html_text: str) -> str:
    if not html_text:
        return ''
    text = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html_text)
    text = re.sub(r'(?is)<style.*?>.*?</style>', ' ', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_text_and_html(msg) -> tuple[str, str]:
    text_part = ''
    html_part = ''

    def decode_part(part) -> str:
        try:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            if isinstance(payload, (bytes, bytearray)):
                return payload.decode(charset, errors='replace')
            return str(payload) if payload is not None else ''
        except Exception:
            try:
                return str(part.get_payload())
            except Exception:
                return ''

    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get('Content-Disposition', '') or '').lower()
            if 'attachment' in disposition:
                continue
            content_type = (part.get_content_type() or '').lower()
            if content_type == 'text/plain' and not text_part:
                text_part = decode_part(part)
            elif content_type == 'text/html' and not html_part:
                html_part = decode_part(part)
            if text_part and html_part:
                break
    else:
        content_type = (msg.get_content_type() or '').lower()
        if content_type == 'text/html':
            html_part = decode_part(msg)
        else:
            text_part = decode_part(msg)

    return text_part or '', html_part or ''


def has_message_attachments(msg) -> bool:
    if not msg.is_multipart():
        return False
    for part in msg.walk():
        disposition = str(part.get('Content-Disposition', '') or '').lower()
        if 'attachment' in disposition:
            return True
    return False


def create_imap_connection(imap_host: str, imap_port: int = 993, proxy_url: str = ''):
    host = (imap_host or '').strip()
    port = int(imap_port or 993)
    if not host:
        raise ValueError('IMAP host 不能为空')
    try:
        with proxy_socket_context(proxy_url):
            return imaplib.IMAP4_SSL(host, port, timeout=30)
    except TypeError:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(30)
        try:
            with proxy_socket_context(proxy_url):
                return imaplib.IMAP4_SSL(host, port)
        finally:
            socket.setdefaulttimeout(old_timeout)


def quote_imap_id_value(value: str) -> str:
    return str(value or '').replace('\\', '\\\\').replace('"', r'\"')


def build_imap_id_payload() -> Optional[str]:
    parts = []
    for key, value in IMAP_IDENTITY_FIELDS.items():
        if not value:
            continue
        parts.append(f'"{quote_imap_id_value(key)}"')
        parts.append(f'"{quote_imap_id_value(value)}"')
    if not parts:
        return None
    return f'({" ".join(parts)})'


def send_imap_id(mail, provider: str, imap_host: str) -> Dict[str, Any]:
    payload = build_imap_id_payload()
    if not payload:
        return {'attempted': False, 'reason': 'empty_payload'}
    if not hasattr(mail, 'xatom'):
        return {'attempted': False, 'reason': 'xatom_not_supported'}

    try:
        status, response = mail.xatom('ID', payload)
        return {
            'attempted': True,
            'status': str(status),
            'response': sanitize_error_details(str(response or ''))[:300],
            'fields': [key for key, value in IMAP_IDENTITY_FIELDS.items() if value],
            'provider': provider,
            'imap_host': imap_host,
        }
    except Exception as exc:
        return {
            'attempted': True,
            'status': type(exc).__name__,
            'response': sanitize_error_details(str(exc))[:300],
            'fields': [key for key, value in IMAP_IDENTITY_FIELDS.items() if value],
            'provider': provider,
            'imap_host': imap_host,
        }


def build_imap_select_variants(folder_name: str) -> List[str]:
    raw_name = str(folder_name or '').strip()
    if not raw_name:
        return []

    unquoted_name = raw_name[1:-1] if raw_name.startswith('"') and raw_name.endswith('"') and len(raw_name) >= 2 else raw_name
    variants = []
    for candidate in (raw_name, unquoted_name, f'"{unquoted_name}"'):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def try_select_imap_folder(mail, folder_name: str, readonly: bool = True) -> tuple[Optional[str], List[Dict[str, Any]]]:
    if not folder_name:
        return None, []

    attempts = []
    readonly_modes = [readonly]
    if readonly:
        readonly_modes.append(False)

    for use_readonly in readonly_modes:
        for candidate in build_imap_select_variants(folder_name):
            try:
                status, response = mail.select(candidate, readonly=use_readonly)
                attempts.append({
                    'folder': candidate,
                    'readonly': use_readonly,
                    'status': str(status),
                    'response': sanitize_error_details(str(response or ''))[:200],
                })
                if status == 'OK':
                    return candidate, attempts
            except imaplib.IMAP4.readonly:
                attempts.append({
                    'folder': candidate,
                    'readonly': use_readonly,
                    'status': 'READONLY',
                    'response': 'mailbox selected as read-only',
                })
                return candidate, attempts
            except Exception as exc:
                attempts.append({
                    'folder': candidate,
                    'readonly': use_readonly,
                    'status': type(exc).__name__,
                    'response': sanitize_error_details(str(exc))[:200],
                })
    return None, attempts


def resolve_imap_folder(mail, provider: str, folder: str, readonly: bool = True) -> tuple[Optional[str], Dict[str, Any]]:
    candidates = []
    for folder_name in get_imap_folder_candidates(provider, folder):
        if folder_name and folder_name not in candidates:
            candidates.append(folder_name)

    select_attempts = []
    for folder_name in candidates:
        selected, attempts = try_select_imap_folder(mail, folder_name, readonly=readonly)
        select_attempts.extend(attempts)
        if selected:
            diagnostics = {'tried_folders': candidates}
            if attempts and any(not item.get('readonly', True) for item in attempts):
                diagnostics['fallback_mode'] = 'select'
            if select_attempts:
                diagnostics['select_attempts'] = select_attempts[-10:]
            return selected, diagnostics

    available_folders = list_imap_mailboxes(mail)
    ranked_folders = rank_imap_listed_mailboxes(folder, candidates, available_folders)
    for folder_name in ranked_folders:
        selected, attempts = try_select_imap_folder(mail, folder_name, readonly=readonly)
        select_attempts.extend(attempts)
        if selected:
            return selected, {
                'tried_folders': candidates,
                'available_folders': available_folders[:20],
                'matched_folders': ranked_folders[:10],
                'fallback_mode': 'select' if any(not item.get('readonly', True) for item in attempts) else '',
                'select_attempts': select_attempts[-10:],
            }

    diagnostics = {'tried_folders': candidates}
    if available_folders:
        diagnostics['available_folders'] = available_folders[:20]
    if ranked_folders:
        diagnostics['matched_folders'] = ranked_folders[:10]
    if select_attempts:
        diagnostics['select_attempts'] = select_attempts[-10:]
    return None, diagnostics


def normalize_imap_auth_error(provider: str, imap_host: str, raw_message: str) -> str:
    message = sanitize_error_details(str(raw_message or '')).strip() or 'IMAP 认证失败'
    if 'unsafe login' in message.lower():
        if (provider or '').strip().lower() in {'126', '163'}:
            return '网易邮箱拦截了当前 IMAP 登录（Unsafe Login），请在网页端开启 IMAP 并使用客户端授权码；若仍失败，说明当前网络或服务器 IP 被风控'
        return '邮箱服务商拦截了当前 IMAP 登录（Unsafe Login），请检查是否已开启 IMAP 并改用授权码'
    if (provider or '').strip().lower() == 'gmail':
        return 'IMAP 认证失败，请使用 Gmail 应用专用密码并确认已开启 IMAP'
    if ((provider or '').strip().lower() == 'outlook' or (imap_host or '').strip().lower() in {IMAP_SERVER_NEW, IMAP_SERVER_OLD}) and 'basicauthblocked' in message.lower():
        return 'Outlook 已阻止 Basic Auth，请改用 Outlook OAuth 导入'
    return message


def get_imap_access_block_error(provider: str, folder: str, diagnostics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    attempts = diagnostics.get('select_attempts') or []
    unsafe_attempts = []
    for item in attempts:
        response_text = str(item.get('response') or '')
        status_text = str(item.get('status') or '')
        if 'unsafe login' in response_text.lower() or 'unsafe login' in status_text.lower():
            unsafe_attempts.append(item)

    if not unsafe_attempts:
        return None

    provider_key = (provider or '').strip().lower()
    if provider_key in {'126', '163'}:
        message = '网易邮箱拦截了当前 IMAP 登录（Unsafe Login），请在网页端开启 IMAP 并使用客户端授权码；若仍失败，说明当前网络或服务器 IP 被网易风控'
    else:
        message = '邮箱服务商拦截了当前 IMAP 登录（Unsafe Login），请确认已开启 IMAP、使用授权码，并检查当前网络或代理是否被风控'

    return build_error_payload(
        'IMAP_UNSAFE_LOGIN_BLOCKED',
        message,
        'IMAPSecurityError',
        403,
        {
            'provider': provider,
            'folder': folder,
            **diagnostics,
        }
    )


def get_emails_imap_generic(email_addr: str, imap_password: str, imap_host: str,
                            imap_port: int = 993, folder: str = 'inbox',
                            provider: str = 'custom', skip: int = 0, top: int = 20,
                            proxy_url: str = '') -> Dict[str, Any]:
    mail = None
    imap_id_info = {}
    try:
        skip = max(0, int(skip or 0))
        top = max(1, int(top or 20))
        mail = create_imap_connection(imap_host, imap_port, proxy_url)
        try:
            mail.login(email_addr, imap_password)
        except imaplib.IMAP4.error as exc:
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_AUTH_FAILED',
                    normalize_imap_auth_error(provider, imap_host, str(exc)),
                    'IMAPAuthError',
                    401,
                    ''
                ),
                'error_code': 'IMAP_AUTH_FAILED'
            }

        imap_id_info = send_imap_id(mail, provider, imap_host)
        selected, folder_diagnostics = resolve_imap_folder(mail, provider, folder, readonly=True)
        if not selected:
            if imap_id_info:
                folder_diagnostics = {**folder_diagnostics, 'imap_id': imap_id_info}
            blocked_error = get_imap_access_block_error(provider, folder, folder_diagnostics)
            if blocked_error:
                return {
                    'success': False,
                    'error': blocked_error,
                    'error_code': 'IMAP_UNSAFE_LOGIN_BLOCKED'
                }
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_FOLDER_NOT_FOUND',
                    'IMAP 文件夹不存在或无权访问',
                    'IMAPFolderError',
                    400,
                    {
                        'provider': provider,
                        'folder': folder,
                        **folder_diagnostics,
                    }
                ),
                'error_code': 'IMAP_FOLDER_NOT_FOUND'
            }

        status, data = mail.uid('SEARCH', None, 'ALL')
        if status != 'OK':
            return {
                'success': False,
                'error': build_error_payload('IMAP_SEARCH_FAILED', 'IMAP 搜索邮件失败', 'IMAPSearchError', 502, status),
                'error_code': 'IMAP_SEARCH_FAILED'
            }

        uid_bytes = data[0] if data else b''
        if not uid_bytes:
            return {'success': True, 'emails': [], 'method': 'IMAP (Generic)', 'has_more': False}

        uids = uid_bytes.split()
        total = len(uids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip
        if start_idx >= end_idx:
            return {'success': True, 'emails': [], 'method': 'IMAP (Generic)', 'has_more': False}

        paged_uids = uids[start_idx:end_idx][::-1]
        emails_data = []
        for uid in paged_uids:
            try:
                f_status, f_data = mail.uid('FETCH', uid, '(FLAGS RFC822)')
                if f_status != 'OK' or not f_data:
                    continue
                raw_email = None
                flags_text = ''
                for item in f_data:
                    if not item:
                        continue
                    if isinstance(item, tuple) and len(item) >= 2:
                        flags_text = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], (bytes, bytearray)) else str(item[0])
                        raw_email = item[1]
                        break
                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                body_text, body_html = extract_text_and_html(msg)
                preview_source = body_text or strip_html_content(body_html)
                preview = preview_source[:200] + ('...' if len(preview_source) > 200 else '')
                emails_data.append({
                    'id': uid.decode('utf-8', errors='ignore') if isinstance(uid, (bytes, bytearray)) else str(uid),
                    'subject': decode_header_value(msg.get('Subject', '无主题')),
                    'from': decode_header_value(msg.get('From', '未知')),
                    'date': msg.get('Date', ''),
                    'is_read': '\\Seen' in (flags_text or ''),
                    'has_attachments': has_message_attachments(msg),
                    'body_preview': preview,
                })
            except Exception:
                continue

        return {
            'success': True,
            'emails': emails_data,
            'method': 'IMAP (Generic)',
            'has_more': total > end_idx
        }
    except Exception as exc:
        return {
            'success': False,
            'error': build_error_payload(
                'IMAP_CONNECT_FAILED',
                sanitize_error_details(str(exc)) or 'IMAP 连接失败',
                'IMAPConnectError',
                502,
                ''
            ),
            'error_code': 'IMAP_CONNECT_FAILED'
        }
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def get_email_detail_imap_generic_result(email_addr: str, imap_password: str, imap_host: str,
                                         imap_port: int = 993, message_id: str = '',
                                         folder: str = 'inbox', provider: str = 'custom',
                                         proxy_url: str = '') -> Dict[str, Any]:
    if not message_id:
        return {'success': False, 'error': build_error_payload('EMAIL_DETAIL_INVALID', 'message_id 不能为空', 'ValidationError', 400, '')}

    mail = None
    imap_id_info = {}
    try:
        mail = create_imap_connection(imap_host, imap_port, proxy_url)
        try:
            mail.login(email_addr, imap_password)
        except imaplib.IMAP4.error as exc:
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_AUTH_FAILED',
                    normalize_imap_auth_error(provider, imap_host, str(exc)),
                    'IMAPAuthError',
                    401,
                    ''
                )
            }

        imap_id_info = send_imap_id(mail, provider, imap_host)
        selected, folder_diagnostics = resolve_imap_folder(mail, provider, folder, readonly=True)
        if not selected:
            if imap_id_info:
                folder_diagnostics = {**folder_diagnostics, 'imap_id': imap_id_info}
            blocked_error = get_imap_access_block_error(provider, folder, folder_diagnostics)
            if blocked_error:
                return {
                    'success': False,
                    'error': blocked_error
                }
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_FOLDER_NOT_FOUND',
                    'IMAP 文件夹不存在或无权访问',
                    'IMAPFolderError',
                    400,
                    {
                        'provider': provider,
                        'folder': folder,
                        **folder_diagnostics,
                    }
                )
            }

        status, msg_data = mail.uid('FETCH', str(message_id), '(RFC822)')
        if status != 'OK' or not msg_data:
            return {'success': False, 'error': build_error_payload('EMAIL_DETAIL_FETCH_FAILED', '获取邮件详情失败', 'IMAPFetchError', 502, status)}

        raw_email = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw_email = item[1]
                break
        if not raw_email:
            return {'success': False, 'error': build_error_payload('EMAIL_DETAIL_FETCH_FAILED', '获取邮件详情失败', 'IMAPFetchError', 502, '')}

        msg = email.message_from_bytes(raw_email)
        body_text, body_html = extract_text_and_html(msg)
        body = body_html or body_text.replace('\n', '<br>')
        return {
            'success': True,
            'email': {
                'id': str(message_id),
                'subject': decode_header_value(msg.get('Subject', '无主题')),
                'from': decode_header_value(msg.get('From', '未知')),
                'to': decode_header_value(msg.get('To', '')),
                'cc': decode_header_value(msg.get('Cc', '')),
                'date': msg.get('Date', ''),
                'body': body,
                'body_type': 'html' if body_html else 'text'
            }
        }
    except Exception as exc:
        return {'success': False, 'error': build_error_payload('IMAP_CONNECT_FAILED', sanitize_error_details(str(exc)) or 'IMAP 连接失败', 'IMAPConnectError', 502, '')}
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def parse_email_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if 'T' in str(value):
            normalized = str(value).replace('Z', '+00:00')
            dt = datetime.fromisoformat(normalized)
        else:
            dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


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
            line = format_account_export_line(acc)
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

def format_account_export_line(account: Dict[str, Any]) -> str:
    if account.get('account_type') == 'imap':
        provider = account.get('provider', 'custom')
        imap_password = account.get('imap_password', '')
        if provider == 'custom':
            return f"{account['email']}----{imap_password}----{account.get('imap_host', '')}----{account.get('imap_port', 993)}"
        return f"{account['email']}----{imap_password}"
    return f"{account['email']}----{account.get('password', '')}----{account.get('client_id', '')}----{account.get('refresh_token', '')}"


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
        line = format_account_export_line(acc)
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
                    line = format_account_export_line(acc)
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
        last_refresh_log = get_latest_account_refresh_log(acc['id'], db)
        safe_accounts.append(serialize_account_summary(acc, last_refresh_log))
    return jsonify({'success': True, 'accounts': safe_accounts})


@app.route('/api/external/accounts', methods=['GET'])
@csrf_exempt
@api_key_required
def api_external_get_accounts():
    """对外 API：通过 API Key 获取邮箱账号列表"""
    group_id = request.args.get('group_id', type=int)
    accounts = load_accounts(group_id)
    db = get_db()

    safe_accounts = []
    for acc in accounts:
        last_refresh_log = get_latest_account_refresh_log(acc['id'], db)
        safe_accounts.append(
            serialize_account_summary(
                acc,
                last_refresh_log,
                include_client_meta=False,
                include_imap_meta=False
            )
        )

    return jsonify({
        'success': True,
        'total': len(safe_accounts),
        'accounts': safe_accounts
    })


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
        LEFT JOIN account_aliases aa ON a.id = aa.account_id
        LEFT JOIN account_tags at ON a.id = at.account_id
        LEFT JOIN tags t ON at.tag_id = t.id
        WHERE a.email LIKE ? OR a.remark LIKE ? OR t.name LIKE ? OR aa.alias_email LIKE ?
        ORDER BY a.created_at DESC
    ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))

    rows = cursor.fetchall()
    safe_accounts = []
    for row in rows:
        acc = dict(row)
        aliases = get_account_aliases(acc['id'])
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
            'aliases': aliases,
            'alias_count': len(aliases),
            'client_id': acc['client_id'][:8] + '...' if len(acc['client_id']) > 8 else acc['client_id'],
            'group_id': acc['group_id'],
            'group_name': acc['group_name'] if acc['group_name'] else '默认分组',
            'group_color': acc['group_color'] if acc['group_color'] else '#666666',
            'remark': acc['remark'] if acc['remark'] else '',
            'status': acc['status'] if acc['status'] else 'active',
            'account_type': acc.get('account_type', 'outlook'),
            'provider': acc.get('provider', 'outlook'),
            'forward_enabled': bool(acc.get('forward_enabled')),
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
            'account_type': account.get('account_type', 'outlook'),
            'provider': account.get('provider', 'outlook'),
            'imap_host': account.get('imap_host', ''),
            'imap_port': account.get('imap_port', 993),
            'imap_password': account.get('imap_password', ''),
            'aliases': account.get('aliases', []),
            'alias_count': account.get('alias_count', 0),
            'matched_alias': account.get('matched_alias', ''),
            'forward_enabled': bool(account.get('forward_enabled')),
            'group_id': account.get('group_id'),
            'group_name': account.get('group_name', '默认分组'),
            'remark': account.get('remark', ''),
            'status': account.get('status', 'active'),
            'created_at': account.get('created_at', ''),
            'updated_at': account.get('updated_at', '')
        }
    })


def parse_alias_payload(raw_aliases: Any) -> List[str]:
    if isinstance(raw_aliases, str):
        values = raw_aliases.replace(',', '\n').splitlines()
    elif isinstance(raw_aliases, (list, tuple, set)):
        values = list(raw_aliases)
    else:
        values = []
    return [str(value or '').strip() for value in values if str(value or '').strip()]


@app.route('/api/accounts/<int:account_id>/aliases', methods=['GET'])
@login_required
def api_get_account_aliases_endpoint(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'}), 404
    return jsonify({
        'success': True,
        'account_id': account_id,
        'email': account.get('email', ''),
        'aliases': account.get('aliases', []),
    })


@app.route('/api/accounts/<int:account_id>/aliases', methods=['PUT'])
@login_required
def api_replace_account_aliases_endpoint(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'}), 404

    data = request.json or {}
    aliases = parse_alias_payload(data.get('aliases', []))
    db = get_db()
    success, cleaned_aliases, errors = replace_account_aliases(account_id, account.get('email', ''), aliases, db)
    if not success:
        db.rollback()
        return jsonify({'success': False, 'error': '；'.join(errors), 'errors': errors}), 400

    db.commit()
    return jsonify({
        'success': True,
        'message': f'已保存 {len(cleaned_aliases)} 个别名',
        'aliases': cleaned_aliases,
    })


@app.route('/api/accounts', methods=['POST'])
@login_required
def api_add_account():
    """添加账号"""
    data = request.json
    account_str = data.get('account_string', '')
    group_id = data.get('group_id', 1)
    account_format = data.get('account_format', 'client_id_refresh_token')
    provider = data.get('provider', 'outlook')
    forward_enabled = bool(data.get('forward_enabled', False))
    imap_host = (data.get('imap_host', '') or '').strip()
    try:
        imap_port = int(data.get('imap_port', 993) or 993)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'IMAP 端口无效'})
    
    if not account_str:
        return jsonify({'success': False, 'error': '请输入账号信息'})
    
    # 支持批量导入（多行）
    lines = account_str.strip().split('\n')
    added = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parsed = parse_account_import(line, account_format, provider, imap_host, imap_port)
        if parsed:
            if add_account(
                parsed['email'],
                parsed.get('password', ''),
                parsed.get('client_id', ''),
                parsed.get('refresh_token', ''),
                group_id,
                '',
                parsed.get('account_type', 'outlook'),
                parsed.get('provider', provider),
                parsed.get('imap_host', ''),
                parsed.get('imap_port', 993),
                parsed.get('imap_password', ''),
                forward_enabled
            ):
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
    account_type = data.get('account_type', 'outlook')
    provider = data.get('provider', 'outlook')
    imap_host = (data.get('imap_host', '') or '').strip()
    imap_port = data.get('imap_port', 993)
    imap_password = data.get('imap_password', '')
    group_id = data.get('group_id', 1)
    remark = sanitize_input(data.get('remark', ''), max_length=200)
    status = data.get('status', 'active')
    forward_enabled = bool(data.get('forward_enabled', False))
    aliases_provided = 'aliases' in data
    aliases = parse_alias_payload(data.get('aliases', [])) if aliases_provided else []

    provider_meta = get_provider_meta(provider, email_addr)
    is_outlook = (account_type == 'outlook') or provider_meta['key'] == 'outlook'
    if is_outlook:
        if not email_addr or not client_id or not refresh_token:
            return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})
        account_type = 'outlook'
        provider = 'outlook'
        imap_host = IMAP_SERVER_NEW
        imap_port = IMAP_PORT
        imap_password = ''
    else:
        if not email_addr or not imap_password:
            return jsonify({'success': False, 'error': '邮箱和 IMAP 密码不能为空'})
        if provider_meta['key'] == 'custom' and not imap_host:
            return jsonify({'success': False, 'error': '自定义 IMAP 必须填写服务器地址'})
        client_id = ''
        refresh_token = ''
        account_type = 'imap'
        provider = provider_meta['key']
        if provider != 'custom':
            imap_host = provider_meta.get('imap_host', '')
            imap_port = provider_meta.get('imap_port', 993)

    if False:
        return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})

    if aliases_provided:
        _, alias_errors = validate_account_aliases(account_id, email_addr, aliases)
        if alias_errors:
            return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})

    if update_account(
        account_id, email_addr, password, client_id, refresh_token, group_id, remark, status,
        account_type, provider, imap_host, imap_port, imap_password, forward_enabled
    ):
        cleaned_aliases = get_account_aliases(account_id)
        if aliases_provided:
            db = get_db()
            alias_success, cleaned_aliases, alias_errors = replace_account_aliases(account_id, email_addr, aliases, db)
            if not alias_success:
                db.rollback()
                return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})
            db.commit()
        return jsonify({'success': True, 'message': '账号更新成功', 'aliases': cleaned_aliases})
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


@app.route('/api/accounts/batch-delete', methods=['POST'])
@login_required
def api_batch_delete_accounts():
    """批量删除账号"""
    data = request.get_json(silent=True) or {}
    result = delete_accounts_by_ids(data.get('account_ids') or [])
    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('error', '删除失败')})

    deleted_count = result.get('deleted_count', 0)
    missing_ids = result.get('missing_ids', [])
    message = f'已删除 {deleted_count} 个账号'
    if missing_ids:
        message += f'，忽略 {len(missing_ids)} 个不存在的账号'

    return jsonify({
        'success': True,
        'message': message,
        'deleted_count': deleted_count,
        'deleted_accounts': result.get('deleted_accounts', []),
        'missing_ids': missing_ids,
    })


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


def log_forwarding_result(account_id: int, account_email: str, message_id: str, channel: str,
                          status: str, error_message: str = None):
    """记录转发结果到数据库"""
    db = get_db()
    try:
        db.execute('''
            INSERT INTO forwarding_logs (account_id, account_email, message_id, channel, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            account_id,
            account_email,
            str(message_id or ''),
            channel,
            status,
            sanitize_error_details(error_message)[:500] if error_message else None,
        ))
        db.commit()
        return True
    except Exception as e:
        print(f"记录转发结果失败: {str(e)}")
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


def refresh_outlook_account_token(account: sqlite3.Row, refresh_type: str = 'manual') -> Dict[str, Any]:
    """刷新单个 Outlook 账号的 refresh token 并记录结果。"""
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
        error_msg = sanitize_error_details(f"解密 token 失败: {str(e)}")
        log_refresh_result(account_id, account_email, refresh_type, 'failed', error_msg)
        return {
            'success': False,
            'error_message': error_msg,
            'error_payload': build_error_payload(
                "TOKEN_DECRYPT_FAILED",
                "Token 解密失败",
                "DecryptionError",
                500,
                error_msg
            )
        }

    success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)
    sanitized_error = sanitize_error_details(error_msg) if error_msg else ''

    # 记录刷新结果
    log_refresh_result(account_id, account_email, refresh_type, 'success' if success else 'failed', sanitized_error or None)

    if success:
        return {'success': True, 'message': 'Token 刷新成功'}

    return {
        'success': False,
        'error_message': sanitized_error or '未知错误',
        'error_payload': build_error_payload(
            "TOKEN_REFRESH_FAILED",
            "Token 刷新失败",
            "RefreshTokenError",
            400,
            sanitized_error or "未知错误"
        )
    }


@app.route('/api/accounts/<int:account_id>/refresh', methods=['POST'])
@login_required
def api_refresh_account(account_id):
    """刷新单个账号的 token"""
    db = get_db()
    cursor = db.execute('SELECT id, email, client_id, refresh_token, group_id, account_type, provider FROM accounts WHERE id = ?', (account_id,))
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

    if (account['account_type'] or '').strip().lower() == 'imap':
        return jsonify({'success': False, 'error': 'IMAP 账号无需刷新 Token'})

    result = refresh_outlook_account_token(account, 'manual')
    if result['success']:
        return jsonify({'success': True, 'message': result['message']})
    return jsonify({'success': False, 'error': result['error_payload']})


@app.route('/api/accounts/refresh-selected', methods=['POST'])
@login_required
def api_refresh_selected_accounts():
    """刷新选中账号的 token。"""
    data = request.get_json(silent=True) or {}
    raw_account_ids = data.get('account_ids') or []

    if not isinstance(raw_account_ids, list):
        return jsonify({'success': False, 'error': '账号列表格式错误'})

    account_ids = []
    seen_ids = set()
    for account_id in raw_account_ids:
        try:
            normalized_id = int(account_id)
        except (TypeError, ValueError):
            continue
        if normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        account_ids.append(normalized_id)

    if not account_ids:
        return jsonify({'success': False, 'error': '请选择要刷新的账号'})

    db = get_db()
    placeholders = ','.join('?' * len(account_ids))
    cursor = db.execute(f'''
        SELECT id, email, client_id, refresh_token, group_id, account_type, provider
        FROM accounts
        WHERE id IN ({placeholders})
        ORDER BY email COLLATE NOCASE ASC
    ''', account_ids)
    accounts = cursor.fetchall()

    found_ids = {row['id'] for row in accounts}
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_list = []
    skipped_list = []

    missing_ids = [account_id for account_id in account_ids if account_id not in found_ids]
    for missing_id in missing_ids:
        skipped_count += 1
        skipped_list.append({
            'id': missing_id,
            'email': f'账号 #{missing_id}',
            'reason': '账号不存在或已删除'
        })

    for account in accounts:
        if (account['account_type'] or '').strip().lower() == 'imap':
            skipped_count += 1
            skipped_list.append({
                'id': account['id'],
                'email': account['email'],
                'reason': 'IMAP 账号无需刷新 Token'
            })
            continue

        result = refresh_outlook_account_token(account, 'manual')
        if result['success']:
            success_count += 1
            continue

        failed_count += 1
        failed_list.append({
            'id': account['id'],
            'email': account['email'],
            'error': result.get('error_message') or '未知错误'
        })

    requested_count = len(account_ids)
    processed_count = success_count + failed_count
    message_parts = [f'成功 {success_count}']
    if failed_count:
        message_parts.append(f'失败 {failed_count}')
    if skipped_count:
        message_parts.append(f'跳过 {skipped_count}')

    return jsonify({
        'success': True,
        'message': f'已处理 {requested_count} 个账号，' + '，'.join(message_parts),
        'requested_count': requested_count,
        'processed_count': processed_count,
        'success_count': success_count,
        'failed_count': failed_count,
        'skipped_count': skipped_count,
        'failed_list': failed_list,
        'skipped_list': skipped_list,
    })


@app.route('/api/accounts/refresh-all', methods=['GET'])
@login_required
def api_refresh_all_accounts():
    """刷新所有账号的 token（流式响应，实时返回进度）"""
    import json
    import time

    def generate():
        # 在生成器内部直接创建数据库连接
        conn = sqlite3.connect(DATABASE)
        conn.execute('PRAGMA foreign_keys = ON')
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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active' AND COALESCE(account_type, 'outlook') = 'outlook'")
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
        conn.execute('PRAGMA foreign_keys = ON')
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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active' AND COALESCE(account_type, 'outlook') = 'outlook'")
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


@app.route('/api/accounts/forwarding-logs', methods=['GET'])
@login_required
def api_get_forwarding_logs():
    """获取最近的转发记录"""
    db = get_db()
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    cursor = db.execute('''
        SELECT * FROM forwarding_logs
        WHERE created_at >= datetime('now', '-6 months')
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'],
            'message_id': row['message_id'],
            'channel': row['channel'],
            'status': row['status'],
            'error_message': row['error_message'],
            'created_at': row['created_at']
        })

    return jsonify({'success': True, 'logs': logs})


@app.route('/api/accounts/forwarding-logs/failed', methods=['GET'])
@login_required
def api_get_failed_forwarding_logs():
    """获取最近失败的转发记录"""
    db = get_db()
    limit = int(request.args.get('limit', 100))

    cursor = db.execute('''
        SELECT * FROM forwarding_logs
        WHERE status = 'failed'
        AND created_at >= datetime('now', '-6 months')
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit,))

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'],
            'message_id': row['message_id'],
            'channel': row['channel'],
            'status': row['status'],
            'error_message': row['error_message'],
            'created_at': row['created_at']
        })

    return jsonify({'success': True, 'logs': logs})


@app.route('/api/accounts/<int:account_id>/forwarding-logs', methods=['GET'])
@login_required
def api_get_account_forwarding_logs(account_id):
    """获取单个账号的转发记录"""
    db = get_db()
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))
    failed_only = str(request.args.get('failed_only', '')).strip().lower() in ('1', 'true', 'yes', 'on')

    query = '''
        SELECT * FROM forwarding_logs
        WHERE account_id = ?
        AND created_at >= datetime('now', '-6 months')
    '''
    params = [account_id]
    if failed_only:
        query += " AND status = 'failed'"
    query += '''
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    '''
    params.extend([limit, offset])

    cursor = db.execute(query, tuple(params))

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'],
            'message_id': row['message_id'],
            'channel': row['channel'],
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

def delete_emails_imap(email_addr: str, client_id: str, refresh_token: str, message_ids: List[str], server: str,
                       proxy_url: str = None) -> Dict[str, Any]:
    """通过 IMAP 删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url)
    if not access_token:
        return {"success": False, "error": "获取 Access Token 失败"}
        
    try:
        # 生成 OAuth2 认证字符串
        auth_string = 'user=%s\x01auth=Bearer %s\x01\x01' % (email_addr, access_token)
        
        # 连接 IMAP
        with proxy_socket_context(proxy_url):
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


VALID_MAIL_FOLDERS = {'inbox', 'junkemail', 'deleteditems', 'all'}


def normalize_folder_name(folder: str) -> str:
    value = (folder or 'inbox').strip().lower()
    if value in {'both', 'combined'}:
        return 'all'
    if value in {'trash'}:
        return 'deleteditems'
    return value or 'inbox'


def get_query_arg_preserve_plus(name: str, default: str = '') -> str:
    raw_query = request.query_string.decode('utf-8', errors='ignore')
    if raw_query:
        for chunk in raw_query.split('&'):
            if not chunk:
                continue
            key, sep, value = chunk.partition('=')
            if unquote(key) == name:
                return unquote(value) if sep else ''
    return request.args.get(name, default)


def format_graph_email_item(item: Dict[str, Any], folder: str) -> Dict[str, Any]:
    return {
        'id': item.get('id'),
        'subject': item.get('subject', '无主题'),
        'from': item.get('from', {}).get('emailAddress', {}).get('address', '未知'),
        'date': item.get('receivedDateTime', ''),
        'is_read': item.get('isRead', False),
        'has_attachments': item.get('hasAttachments', False),
        'body_preview': item.get('bodyPreview', ''),
        'folder': folder,
    }


def format_email_items(items: List[Dict[str, Any]], folder: str) -> List[Dict[str, Any]]:
    formatted = []
    for item in items:
        row = dict(item)
        row['folder'] = row.get('folder') or folder
        formatted.append(row)
    return formatted


def merge_folder_results(results: Dict[str, Dict[str, Any]], skip: int, top: int) -> Dict[str, Any]:
    successful = {folder: result for folder, result in results.items() if result.get('success')}
    if not successful:
        details = {folder: result.get('error') for folder, result in results.items()}
        return {
            'success': False,
            'error': '无法获取邮件，所有方式均失败',
            'details': details
        }

    merged = []
    methods = []
    has_more = False
    partial_errors = {}
    for folder, result in results.items():
        if result.get('success'):
            merged.extend(result.get('emails', []))
            if result.get('method'):
                methods.append(result['method'])
            has_more = has_more or bool(result.get('has_more'))
        else:
            partial_errors[folder] = result.get('error')

    merged.sort(key=lambda item: parse_email_datetime(item.get('date')) or datetime.min, reverse=True)
    sliced = merged[skip:skip + top]

    unique_methods = []
    for method in methods:
        if method and method not in unique_methods:
            unique_methods.append(method)

    response = {
        'success': True,
        'emails': sliced,
        'method': ' / '.join(unique_methods) if unique_methods else '',
        'has_more': has_more or len(merged) > skip + top,
    }
    if partial_errors:
        response['partial'] = True
        response['details'] = partial_errors
    return response


def fetch_account_folder_emails(account: Dict[str, Any], folder: str, skip: int, top: int,
                                proxy_url: str = '') -> Dict[str, Any]:
    folder_name = normalize_folder_name(folder)
    if folder_name not in VALID_MAIL_FOLDERS or folder_name == 'all':
        return {
            'success': False,
            'error': f'folder 参数无效，支持: {", ".join(sorted(VALID_MAIL_FOLDERS - {"all"} | {"all"}))}'
        }

    if account.get('account_type') == 'imap':
        result = get_emails_imap_generic(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            account.get('imap_port', 993),
            folder_name,
            account.get('provider', 'custom'),
            skip,
            top,
            proxy_url
        )
        if result.get('success'):
            return {
                'success': True,
                'emails': format_email_items(result.get('emails', []), folder_name),
                'method': result.get('method', 'IMAP (Generic)'),
                'has_more': bool(result.get('has_more')),
            }
        return {
            'success': False,
            'error': result.get('error', '获取邮件失败'),
            'details': {'imap_generic': result.get('error')}
        }

    all_errors = {}
    graph_result = get_emails_graph(account['client_id'], account['refresh_token'], folder_name, skip, top, proxy_url)
    if graph_result.get('success'):
        return {
            'success': True,
            'emails': [format_graph_email_item(item, folder_name) for item in graph_result.get('emails', [])],
            'method': 'Graph API',
            'has_more': len(graph_result.get('emails', [])) >= top,
        }

    graph_error = graph_result.get('error')
    all_errors['graph'] = graph_error
    if isinstance(graph_error, dict) and graph_error.get('type') in ('ProxyError', 'ConnectionError'):
        return {
            'success': False,
            'error': '代理连接失败，请检查分组代理设置',
            'details': all_errors
        }

    imap_new_result = get_emails_imap_with_server(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        folder_name,
        skip,
        top,
        IMAP_SERVER_NEW,
        proxy_url
    )
    if imap_new_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_new_result.get('emails', []), folder_name),
            'method': 'IMAP (New)',
            'has_more': bool(imap_new_result.get('has_more')),
        }
    all_errors['imap_new'] = imap_new_result.get('error')

    imap_old_result = get_emails_imap_with_server(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        folder_name,
        skip,
        top,
        IMAP_SERVER_OLD,
        proxy_url
    )
    if imap_old_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_old_result.get('emails', []), folder_name),
            'method': 'IMAP (Old)',
            'has_more': bool(imap_old_result.get('has_more')),
        }
    all_errors['imap_old'] = imap_old_result.get('error')

    return {
        'success': False,
        'error': '无法获取邮件，所有方式均失败',
        'details': all_errors
    }


def fetch_account_emails(account: Dict[str, Any], folder: str, skip: int, top: int) -> Dict[str, Any]:
    proxy_url = get_account_proxy_url(account)
    folder_name = normalize_folder_name(folder)
    if folder_name not in VALID_MAIL_FOLDERS:
        return {
            'success': False,
            'error': f'folder 参数无效，支持: {", ".join(sorted(VALID_MAIL_FOLDERS))}'
        }

    if folder_name == 'all':
        merged_top = max(1, min(100, top * 2))
        return merge_folder_results(
            {
                'inbox': fetch_account_folder_emails(account, 'inbox', skip, top, proxy_url),
                'junkemail': fetch_account_folder_emails(account, 'junkemail', skip, top, proxy_url),
            },
            0,
            merged_top
        )

    return fetch_account_folder_emails(account, folder_name, skip, top, proxy_url)


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

    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))
    result = fetch_account_emails(account, folder, skip, top)
    if result.get('success'):
        db = get_db()
        db.execute(
            '''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (account['id'],)
        )
        db.commit()
    return jsonify(result)

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

    proxy_url = get_account_proxy_url(account)

    # 1. 优先尝试 Graph API
    if account.get('account_type') == 'imap':
        return jsonify({'success': False, 'error': 'IMAP 账号暂不支持批量删除邮件'})

    graph_res = delete_emails_graph(account['client_id'], account['refresh_token'], message_ids, proxy_url)
    if graph_res['success']:
        return jsonify(graph_res)

    # 如果是代理错误，不再回退 IMAP
    graph_error = graph_res.get('error', '')
    if isinstance(graph_error, str) and 'ProxyError' in graph_error:
        return jsonify(graph_res)
    
    # 2. 尝试 IMAP 回退（新服务器）
    imap_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_NEW, proxy_url)
    if imap_res['success']:
        return jsonify(imap_res)

    # 3. 尝试 IMAP 回退（旧服务器）
    imap_old_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_OLD, proxy_url)
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
    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    proxy_url = get_account_proxy_url(account)

    if account.get('account_type') == 'imap':
        detail_result = get_email_detail_imap_generic_result(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            account.get('imap_port', 993),
            message_id,
            folder,
            account.get('provider', 'custom'),
            proxy_url
        )
        if detail_result.get('success'):
            return jsonify(detail_result)
        return jsonify({'success': False, 'error': detail_result.get('error', '获取邮件详情失败')})

    if method == 'graph':
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
    detail = get_email_detail_imap(account['email'], account['client_id'], account['refresh_token'], message_id, folder, proxy_url)
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
    settings['forward_channels'] = get_forward_channels()
    settings['forward_check_interval_minutes'] = get_setting('forward_check_interval_minutes', '5')
    settings['forward_email_window_minutes'] = get_setting('forward_email_window_minutes', '0')
    settings['forward_include_junkemail'] = get_setting('forward_include_junkemail', 'false')
    settings['email_forward_recipient'] = get_setting('email_forward_recipient', '')
    settings['smtp_host'] = get_setting('smtp_host', '')
    settings['smtp_port'] = get_setting('smtp_port', '465')
    settings['smtp_username'] = get_setting('smtp_username', '')
    settings['smtp_password'] = get_setting_decrypted('smtp_password', '')
    settings['smtp_from_email'] = get_setting('smtp_from_email', '')
    settings['smtp_provider'] = normalize_smtp_forward_provider(get_setting('smtp_provider', 'custom'))
    settings['smtp_use_tls'] = get_setting('smtp_use_tls', 'false')
    settings['smtp_use_ssl'] = get_setting('smtp_use_ssl', 'true')
    settings['telegram_bot_token'] = get_setting_decrypted('telegram_bot_token', '')
    settings['telegram_chat_id'] = get_setting('telegram_chat_id', '')
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

    if 'forward_check_interval_minutes' in data:
        try:
            minutes = int(data['forward_check_interval_minutes'])
            if minutes < 1 or minutes > 60:
                errors.append('转发检查间隔必须在 1-60 分钟之间')
            elif set_setting('forward_check_interval_minutes', str(minutes)):
                updated.append('转发检查间隔')
            else:
                errors.append('保存转发检查间隔失败')
        except ValueError:
            errors.append('转发检查间隔必须是数字')

    if 'forward_email_window_minutes' in data:
        try:
            minutes = int(data['forward_email_window_minutes'])
            if minutes < 0 or minutes > 10080:
                errors.append('转发邮件时间范围必须在 0-10080 分钟之间')
            elif set_setting('forward_email_window_minutes', str(minutes)):
                updated.append('转发邮件时间范围')
            else:
                errors.append('保存转发邮件时间范围失败')
        except ValueError:
            errors.append('转发邮件时间范围必须是数字')

    if 'forward_include_junkemail' in data:
        include_junk = str(data['forward_include_junkemail']).lower()
        if include_junk in ('true', 'false'):
            if set_setting('forward_include_junkemail', include_junk):
                updated.append('转发垃圾箱邮件')
            else:
                errors.append('保存转发垃圾箱邮件失败')
        else:
            errors.append('转发垃圾箱邮件必须是 true 或 false')

    if 'forward_channels' in data:
        forward_channels = normalize_forward_channel_settings(data['forward_channels'])
        stored_value = ','.join(forward_channels) if forward_channels else 'none'
        if set_setting('forward_channels', stored_value):
            updated.append('转发渠道')
        else:
            errors.append('保存转发渠道失败')

    if 'email_forward_recipient' in data:
        if set_setting('email_forward_recipient', data['email_forward_recipient'].strip()):
            updated.append('邮件转发收件箱')
        else:
            errors.append('保存邮件转发收件箱失败')

    if 'smtp_host' in data:
        if set_setting('smtp_host', data['smtp_host'].strip()):
            updated.append('SMTP 主机')
        else:
            errors.append('保存 SMTP 主机失败')

    if 'smtp_port' in data:
        try:
            smtp_port = int(data['smtp_port'])
            if smtp_port <= 0 or smtp_port > 65535:
                errors.append('SMTP 端口无效')
            elif set_setting('smtp_port', str(smtp_port)):
                updated.append('SMTP 端口')
            else:
                errors.append('保存 SMTP 端口失败')
        except ValueError:
            errors.append('SMTP 端口必须是数字')

    if 'smtp_username' in data:
        if set_setting('smtp_username', data['smtp_username'].strip()):
            updated.append('SMTP 用户名')
        else:
            errors.append('保存 SMTP 用户名失败')

    if 'smtp_password' in data:
        if set_setting_encrypted('smtp_password', data['smtp_password'].strip()):
            updated.append('SMTP 密码')
        else:
            errors.append('保存 SMTP 密码失败')

    if 'smtp_from_email' in data:
        if set_setting('smtp_from_email', data['smtp_from_email'].strip()):
            updated.append('SMTP 发件人')
        else:
            errors.append('保存 SMTP 发件人失败')

    if 'smtp_provider' in data:
        smtp_provider = normalize_smtp_forward_provider(data['smtp_provider'])
        if str(data['smtp_provider']).strip().lower() not in SMTP_FORWARD_PROVIDERS:
            errors.append('SMTP 邮箱类型无效')
        elif set_setting('smtp_provider', smtp_provider):
            updated.append('SMTP 邮箱类型')
        else:
            errors.append('保存 SMTP 邮箱类型失败')

    if 'smtp_use_tls' in data:
        if set_setting('smtp_use_tls', str(data['smtp_use_tls']).lower()):
            updated.append('SMTP TLS')
        else:
            errors.append('保存 SMTP TLS 失败')

    if 'smtp_use_ssl' in data:
        if set_setting('smtp_use_ssl', str(data['smtp_use_ssl']).lower()):
            updated.append('SMTP SSL')
        else:
            errors.append('保存 SMTP SSL 失败')

    if 'telegram_bot_token' in data:
        if set_setting_encrypted('telegram_bot_token', data['telegram_bot_token'].strip()):
            updated.append('Telegram Bot Token')
        else:
            errors.append('保存 Telegram Bot Token 失败')

    if 'telegram_chat_id' in data:
        if set_setting('telegram_chat_id', data['telegram_chat_id'].strip()):
            updated.append('Telegram Chat ID')
        else:
            errors.append('保存 Telegram Chat ID 失败')

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

def get_bool_setting(key: str, default: bool = False) -> bool:
    value = str(get_setting(key, 'true' if default else 'false')).strip().lower()
    return value in ('1', 'true', 'yes', 'on')


def normalize_forward_channel_settings(raw_channels: Any) -> list[str]:
    if isinstance(raw_channels, str):
        values = raw_channels.split(',')
    elif isinstance(raw_channels, (list, tuple, set)):
        values = list(raw_channels)
    else:
        values = []

    normalized = []
    channel_aliases = {
        'email': FORWARD_CHANNEL_SMTP_SETTING,
        'smtp': FORWARD_CHANNEL_SMTP_SETTING,
        'tg': FORWARD_CHANNEL_TG_SETTING,
        'telegram': FORWARD_CHANNEL_TG_SETTING,
    }

    for item in values:
        channel = channel_aliases.get(str(item).strip().lower())
        if channel and channel not in normalized:
            normalized.append(channel)
    return normalized


def normalize_smtp_forward_provider(value: str) -> str:
    provider = str(value or '').strip().lower()
    if provider not in SMTP_FORWARD_PROVIDERS:
        return 'custom'
    return provider


def get_configured_forward_channels() -> list[str]:
    channels = []
    if get_setting('email_forward_recipient', '').strip() and get_setting('smtp_host', '').strip():
        channels.append(FORWARD_CHANNEL_SMTP_SETTING)
    if get_setting_decrypted('telegram_bot_token', '').strip() and get_setting('telegram_chat_id', '').strip():
        channels.append(FORWARD_CHANNEL_TG_SETTING)
    return channels


def get_forward_channels() -> list[str]:
    raw_channels = get_setting('forward_channels', 'auto').strip().lower()
    if raw_channels in ('', 'auto'):
        return get_configured_forward_channels()
    if raw_channels == 'none':
        return []
    return normalize_forward_channel_settings(raw_channels)


def has_forward_log(conn, account_id: int, message_id: str, channel: str) -> bool:
    row = conn.execute(
        'SELECT 1 FROM forward_logs WHERE account_id = ? AND message_id = ? AND channel = ? LIMIT 1',
        (account_id, str(message_id), channel)
    ).fetchone()
    return row is not None


def record_forward_log(conn, account_id: int, message_id: str, channel: str):
    conn.execute(
        'INSERT OR IGNORE INTO forward_logs (account_id, message_id, channel) VALUES (?, ?, ?)',
        (account_id, str(message_id), channel)
    )


def send_forward_email(subject: str, body_text: str, body_html: str = '') -> bool:
    recipient = get_setting('email_forward_recipient', '').strip()
    host = get_setting('smtp_host', '').strip()
    if not recipient or not host:
        return False

    port = int(get_setting('smtp_port', '465') or 465)
    username = get_setting('smtp_username', '').strip()
    password = get_setting_decrypted('smtp_password', '').strip()
    smtp_from_email = get_setting('smtp_from_email', '').strip()
    from_email = smtp_from_email or username
    if not from_email:
        return False
    use_tls = get_bool_setting('smtp_use_tls', False)
    use_ssl = get_bool_setting('smtp_use_ssl', True)

    message = EmailMessage()
    message['From'] = from_email
    message['To'] = recipient
    message['Subject'] = subject
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype='html')

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=20) as client:
        if not use_ssl:
            client.ehlo()
            if use_tls:
                client.starttls()
                client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(message)
    return True


def send_forward_email_with_config(config: Dict[str, Any], subject: str, body_text: str, body_html: str = '') -> bool:
    recipient = str(config.get('recipient', '') or '').strip()
    host = str(config.get('host', '') or '').strip()
    if not recipient or not host:
        return False

    port = int(config.get('port') or 465)
    username = str(config.get('username', '') or '').strip()
    password = str(config.get('password', '') or '')
    from_email = str(config.get('from_email', '') or '').strip() or username
    if not from_email:
        return False
    use_tls = str(config.get('use_tls', '')).lower() in ('1', 'true', 'yes', 'on')
    use_ssl = str(config.get('use_ssl', '')).lower() in ('1', 'true', 'yes', 'on')

    message = EmailMessage()
    message['From'] = from_email
    message['To'] = recipient
    message['Subject'] = subject
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype='html')

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=20) as client:
        if not use_ssl:
            client.ehlo()
            if use_tls:
                client.starttls()
                client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(message)
    return True


def send_forward_telegram(text: str) -> bool:
    bot_token = get_setting_decrypted('telegram_bot_token', '').strip()
    chat_id = get_setting('telegram_chat_id', '').strip()
    if not bot_token or not chat_id:
        return False
    response = requests.post(
        f'https://api.telegram.org/bot{bot_token}/sendMessage',
        json={
            'chat_id': chat_id,
            'text': text[:4000],
            'disable_web_page_preview': True,
        },
        timeout=15
    )
    return response.ok


def send_forward_telegram_with_config(config: Dict[str, Any], text: str) -> bool:
    bot_token = str(config.get('bot_token', '') or '').strip()
    chat_id = str(config.get('chat_id', '') or '').strip()
    if not bot_token or not chat_id:
        return False
    response = requests.post(
        f'https://api.telegram.org/bot{bot_token}/sendMessage',
        json={
            'chat_id': chat_id,
            'text': text[:4000],
            'disable_web_page_preview': True,
        },
        timeout=15
    )
    return response.ok


def build_forward_payload(account: Dict[str, Any], email_detail: Dict[str, Any]) -> tuple[str, str, str, str]:
    subject = email_detail.get('subject') or '无主题'
    sender = email_detail.get('from') or '未知'
    received_at = email_detail.get('date') or ''
    body = email_detail.get('body') or ''
    body_text = strip_html_content(body) if email_detail.get('body_type') == 'html' else strip_html_content(body.replace('<br>', '\n'))
    body_text = body_text[:2000]

    title = f"[邮件转发] {subject}"
    plain = f"账号: {account.get('email','')}\n发件人: {sender}\n时间: {received_at}\n主题: {subject}\n\n{body_text}"
    html_body = (
        f"<p><strong>账号:</strong> {html.escape(account.get('email', ''))}</p>"
        f"<p><strong>发件人:</strong> {html.escape(sender)}</p>"
        f"<p><strong>时间:</strong> {html.escape(received_at)}</p>"
        f"<p><strong>主题:</strong> {html.escape(subject)}</p><hr>{body}"
    )
    telegram_text = f"新邮件转发\n账号: {account.get('email','')}\n发件人: {sender}\n主题: {subject}\n时间: {received_at}\n\n{body_text[:1200]}"
    return title, plain, html_body, telegram_text


def fetch_forward_candidates(account: Dict[str, Any], top: int = 20, folder: str = 'inbox') -> List[Dict[str, Any]]:
    proxy_url = get_account_proxy_url(account)
    result = fetch_account_folder_emails(account, folder, 0, top, proxy_url)
    if not result.get('success'):
        return []
    return result.get('emails', [])


def fetch_forward_detail(account: Dict[str, Any], message_id: str, folder: str = 'inbox') -> Optional[Dict[str, Any]]:
    proxy_url = get_account_proxy_url(account)
    if account.get('account_type') == 'imap':
        result = get_email_detail_imap_generic_result(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            account.get('imap_port', 993),
            message_id,
            folder,
            account.get('provider', 'custom'),
            proxy_url
        )
        return result.get('email') if result.get('success') else None

    detail = get_email_detail_graph(account.get('client_id', ''), account.get('refresh_token', ''), message_id, proxy_url)
    if not detail:
        return None
    return {
        'id': detail.get('id'),
        'subject': detail.get('subject', '无主题'),
        'from': detail.get('from', {}).get('emailAddress', {}).get('address', '未知'),
        'to': ', '.join([r.get('emailAddress', {}).get('address', '') for r in detail.get('toRecipients', [])]),
        'cc': ', '.join([r.get('emailAddress', {}).get('address', '') for r in detail.get('ccRecipients', [])]),
        'date': detail.get('receivedDateTime', ''),
        'body': detail.get('body', {}).get('content', ''),
        'body_type': detail.get('body', {}).get('contentType', 'text').lower()
    }


def process_forwarding_job():
    with app.app_context():
        conn = sqlite3.connect(DATABASE)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.row_factory = sqlite3.Row
        try:
            forward_channels = set(get_forward_channels())
            email_enabled = FORWARD_CHANNEL_SMTP_SETTING in forward_channels and bool(
                get_setting('email_forward_recipient', '').strip() and get_setting('smtp_host', '').strip()
            )
            telegram_enabled = FORWARD_CHANNEL_TG_SETTING in forward_channels and bool(
                get_setting_decrypted('telegram_bot_token', '').strip() and get_setting('telegram_chat_id', '').strip()
            )
            include_junkemail = get_bool_setting('forward_include_junkemail', False)
            try:
                forward_window_minutes = max(0, min(10080, int(get_setting('forward_email_window_minutes', '0') or '0')))
            except (TypeError, ValueError):
                forward_window_minutes = 0
            forward_window_start = datetime.now() - timedelta(minutes=forward_window_minutes) if forward_window_minutes > 0 else None
            if not email_enabled and not telegram_enabled:
                print('[forward] skip job: no active channels configured')
                return

            accounts = conn.execute(
                "SELECT * FROM accounts WHERE status = 'active' AND forward_enabled = 1"
            ).fetchall()
            print(
                f"[forward] start job: accounts={len(accounts)} email_enabled={email_enabled} telegram_enabled={telegram_enabled}"
            )
            for row in accounts:
                account = dict(row)
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
                if account.get('imap_password'):
                    try:
                        account['imap_password'] = decrypt_data(account['imap_password'])
                    except Exception:
                        pass

                cursor_time = parse_email_datetime(account.get('forward_last_checked_at', ''))
                folders_to_scan = ['inbox']
                if include_junkemail:
                    folders_to_scan.append('junkemail')
                emails = []
                for folder_name in folders_to_scan:
                    emails.extend(fetch_forward_candidates(account, 20, folder_name))
                recent_emails = []
                skipped_before_cursor = 0
                email_success_count = 0
                telegram_success_count = 0
                latest_success_time = cursor_time
                had_processing_failure = False
                for item in emails:
                    dt = parse_email_datetime(item.get('date', ''))
                    if forward_window_start and dt and dt < forward_window_start:
                        app.logger.info(
                            '[forward] skip email older than window: account=%s message_id=%s email_time=%s window_start=%s',
                            account.get('email', ''),
                            item.get('id', ''),
                            item.get('date', ''),
                            forward_window_start.isoformat(),
                        )
                        continue
                    if cursor_time and dt and dt <= cursor_time:
                        skipped_before_cursor += 1
                        app.logger.info(
                            '[forward] skip email before cursor: account=%s message_id=%s email_time=%s cursor=%s',
                            account.get('email', ''),
                            item.get('id', ''),
                            item.get('date', ''),
                            account.get('forward_last_checked_at', ''),
                        )
                        continue
                    recent_emails.append((dt, item))
                app.logger.info(
                    '[forward] account candidates: account=%s fetched=%s pending=%s skipped_before_cursor=%s cursor=%s',
                    account.get('email', ''),
                    len(emails),
                    len(recent_emails),
                    skipped_before_cursor,
                    account.get('forward_last_checked_at', ''),
                )

                recent_emails.sort(key=lambda pair: pair[0] or datetime.min)

                for item_time, item in recent_emails:
                    detail = fetch_forward_detail(account, item.get('id'), item.get('folder', 'inbox'))
                    if not detail:
                        had_processing_failure = True
                        log_forwarding_result(
                            account['id'],
                            account.get('email', ''),
                            item.get('id', ''),
                            'detail',
                            'failed',
                            '获取邮件详情失败',
                        )
                        app.logger.warning(
                            '[forward] skip email detail fetch failed: account=%s message_id=%s',
                            account.get('email', ''),
                            item.get('id', ''),
                        )
                        continue
                    title, plain, html_body, telegram_text = build_forward_payload(account, detail)
                    message_processed = False
                    message_failed = False
                    if email_enabled:
                        if has_forward_log(conn, account['id'], detail['id'], FORWARD_CHANNEL_EMAIL):
                            app.logger.info(
                                '[forward] skip already forwarded email: account=%s message_id=%s channel=%s',
                                account.get('email', ''),
                                detail.get('id', ''),
                                FORWARD_CHANNEL_EMAIL,
                            )
                            message_processed = True
                        else:
                            try:
                                if send_forward_email(title, plain, html_body):
                                    record_forward_log(conn, account['id'], detail['id'], FORWARD_CHANNEL_EMAIL)
                                    log_forwarding_result(
                                        account['id'],
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_EMAIL,
                                        'success',
                                    )
                                    email_success_count += 1
                                    message_processed = True
                                else:
                                    message_failed = True
                                    log_forwarding_result(
                                        account['id'],
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_EMAIL,
                                        'failed',
                                        'SMTP 转发返回失败',
                                    )
                                    app.logger.warning(
                                        '[forward] send email returned false: account=%s message_id=%s channel=%s',
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_EMAIL,
                                    )
                            except Exception as exc:
                                message_failed = True
                                log_forwarding_result(
                                    account['id'],
                                    account.get('email', ''),
                                    detail.get('id', ''),
                                    FORWARD_CHANNEL_EMAIL,
                                    'failed',
                                    str(exc),
                                )
                                app.logger.warning(
                                    '[forward] send email failed: account=%s message_id=%s channel=%s error=%s',
                                    account.get('email', ''),
                                    detail.get('id', ''),
                                    FORWARD_CHANNEL_EMAIL,
                                    str(exc),
                                )
                    if telegram_enabled:
                        if has_forward_log(conn, account['id'], detail['id'], FORWARD_CHANNEL_TELEGRAM):
                            app.logger.info(
                                '[forward] skip already forwarded email: account=%s message_id=%s channel=%s',
                                account.get('email', ''),
                                detail.get('id', ''),
                                FORWARD_CHANNEL_TELEGRAM,
                            )
                            message_processed = True
                        else:
                            try:
                                if send_forward_telegram(telegram_text):
                                    record_forward_log(conn, account['id'], detail['id'], FORWARD_CHANNEL_TELEGRAM)
                                    log_forwarding_result(
                                        account['id'],
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_TELEGRAM,
                                        'success',
                                    )
                                    telegram_success_count += 1
                                    message_processed = True
                                else:
                                    message_failed = True
                                    log_forwarding_result(
                                        account['id'],
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_TELEGRAM,
                                        'failed',
                                        'Telegram 转发返回失败',
                                    )
                                    app.logger.warning(
                                        '[forward] send telegram returned false: account=%s message_id=%s channel=%s',
                                        account.get('email', ''),
                                        detail.get('id', ''),
                                        FORWARD_CHANNEL_TELEGRAM,
                                    )
                            except Exception as exc:
                                message_failed = True
                                log_forwarding_result(
                                    account['id'],
                                    account.get('email', ''),
                                    detail.get('id', ''),
                                    FORWARD_CHANNEL_TELEGRAM,
                                    'failed',
                                    str(exc),
                                )
                                app.logger.warning(
                                    '[forward] send telegram failed: account=%s message_id=%s channel=%s error=%s',
                                    account.get('email', ''),
                                    detail.get('id', ''),
                                    FORWARD_CHANNEL_TELEGRAM,
                                    str(exc),
                                )

                    if message_failed:
                        had_processing_failure = True
                        continue
                    if message_processed and item_time and (latest_success_time is None or item_time > latest_success_time):
                        latest_success_time = item_time

                cursor_value = account.get('forward_last_checked_at', '')
                cursor_updated = False
                if latest_success_time and (cursor_time is None or latest_success_time > cursor_time):
                    cursor_value = latest_success_time.isoformat()
                    conn.execute(
                        'UPDATE accounts SET forward_last_checked_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                        (cursor_value, account['id'])
                    )
                    cursor_updated = True
                else:
                    conn.execute(
                        'UPDATE accounts SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                        (account['id'],)
                    )
                conn.commit()
                print(
                    f"[forward] account done: account={account.get('email', '')} email_success={email_success_count} telegram_success={telegram_success_count} cursor_updated={cursor_updated} cursor={cursor_value} had_failure={had_processing_failure}"
                )
        except Exception as exc:
            print(f"[forward] job failed: {str(exc)}")
            raise
        finally:
            conn.close()


@app.route('/api/accounts/trigger-forwarding-check', methods=['POST'])
@login_required
def api_trigger_forwarding_check():
    """手动触发一次转发检查"""
    try:
        process_forwarding_job()
        return jsonify({'success': True, 'message': '已触发一次转发检查，请查看转发历史或容器日志'})
    except Exception as exc:
        return jsonify({'success': False, 'error': f'触发转发检查失败: {str(exc)}'})


@app.route('/api/settings/test-forward-channel', methods=['POST'])
@login_required
def api_test_forward_channel():
    data = request.json or {}
    channel = str(data.get('channel', '') or '').strip().lower()
    config = data.get('config', {}) or {}

    subject = f'[测试消息] 转发链路检测 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    body_text = (
        '这是一条由系统主动发送的测试消息。\n'
        '如果你收到了这条消息，说明当前转发链路配置可用。'
    )
    body_html = (
        '<p>这是一条由系统主动发送的测试消息。</p>'
        '<p>如果你收到了这条消息，说明当前转发链路配置可用。</p>'
    )
    telegram_text = f'{subject}\n\n这是一条由系统主动发送的测试消息。\n如果你收到了这条消息，说明当前转发链路配置可用。'

    try:
        if channel == 'smtp':
            smtp_config = config.get('smtp', {}) if isinstance(config, dict) else {}
            if not send_forward_email_with_config(smtp_config, subject, body_text, body_html):
                return jsonify({'success': False, 'error': 'SMTP 测试发送失败，请检查当前表单配置'})
            return jsonify({'success': True, 'message': 'SMTP 测试消息已发送，请检查收件箱'})

        if channel == 'telegram':
            telegram_config = config.get('telegram', {}) if isinstance(config, dict) else {}
            if not send_forward_telegram_with_config(telegram_config, telegram_text):
                return jsonify({'success': False, 'error': 'Telegram 测试发送失败，请检查当前表单配置'})
            return jsonify({'success': True, 'message': 'Telegram 测试消息已发送，请检查目标会话'})

        return jsonify({'success': False, 'error': '未知转发渠道'})
    except Exception as exc:
        return jsonify({'success': False, 'error': f'测试失败: {str(exc)}'})


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
                            forward_interval = max(1, min(60, int(get_setting('forward_check_interval_minutes', '5') or '5')))
                            scheduler.add_job(
                                func=process_forwarding_job,
                                trigger=CronTrigger(minute=f'*/{forward_interval}'),
                                id='forward_mail',
                                name='邮件转发轮询',
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

                forward_interval = max(1, min(60, int(get_setting('forward_check_interval_minutes', '5') or '5')))
                scheduler.add_job(
                    func=process_forwarding_job,
                    trigger=CronTrigger(minute=f'*/{forward_interval}'),
                    id='forward_mail',
                    name='邮件转发轮询',
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
        conn.execute('PRAGMA foreign_keys = ON')
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
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row

    try:
        # 获取刷新间隔配置
        cursor_settings = conn.execute("SELECT value FROM settings WHERE key = 'refresh_delay_seconds'")
        delay_row = cursor_settings.fetchone()
        delay_seconds = int(delay_row['value']) if delay_row else 5

        # 清理超过半年的刷新记录
        conn.execute("DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')")
        conn.commit()

        cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active' AND COALESCE(account_type, 'outlook') = 'outlook'")
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

def api_update_account_v2(account_id):
    data = request.json or {}

    if 'status' in data and len(data) == 1:
        return api_update_account_status(account_id, data['status'])

    email_addr = (data.get('email', '') or '').strip()
    password = data.get('password', '') or ''
    client_id = (data.get('client_id', '') or '').strip()
    refresh_token = (data.get('refresh_token', '') or '').strip()
    account_type = (data.get('account_type', 'outlook') or 'outlook').strip().lower()
    provider = (data.get('provider', 'outlook') or 'outlook').strip().lower()
    imap_host = (data.get('imap_host', '') or '').strip()
    imap_password = data.get('imap_password', '') or ''
    group_id = data.get('group_id', 1)
    remark = sanitize_input(data.get('remark', ''), max_length=200)
    status = data.get('status', 'active')
    forward_enabled = bool(data.get('forward_enabled', False))
    aliases_provided = 'aliases' in data
    aliases = parse_alias_payload(data.get('aliases', [])) if aliases_provided else []

    try:
        group_id = int(group_id or 1)
    except (TypeError, ValueError):
        group_id = 1

    try:
        imap_port = int(data.get('imap_port', 993) or 993)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'IMAP 端口无效'})

    provider_meta = get_provider_meta(provider, email_addr)
    is_outlook = account_type == 'outlook' or provider_meta['key'] == 'outlook'

    if is_outlook:
        if not email_addr or not client_id or not refresh_token:
            return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})
        account_type = 'outlook'
        provider = 'outlook'
        imap_host = IMAP_SERVER_NEW
        imap_port = IMAP_PORT
        imap_password = ''
    else:
        if not email_addr or not imap_password:
            return jsonify({'success': False, 'error': '邮箱和 IMAP 密码不能为空'})
        account_type = 'imap'
        provider = provider_meta['key']
        client_id = ''
        refresh_token = ''
        password = ''
        if provider == 'custom':
            if not imap_host:
                return jsonify({'success': False, 'error': '自定义 IMAP 必须填写服务器地址'})
        else:
            imap_host = provider_meta.get('imap_host', '')
            imap_port = int(provider_meta.get('imap_port', 993) or 993)

    if aliases_provided:
        _, alias_errors = validate_account_aliases(account_id, email_addr, aliases)
        if alias_errors:
            return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})

    if update_account(
        account_id,
        email_addr,
        password,
        client_id,
        refresh_token,
        group_id,
        remark,
        status,
        account_type,
        provider,
        imap_host,
        imap_port,
        imap_password,
        forward_enabled
    ):
        cleaned_aliases = get_account_aliases(account_id)
        if aliases_provided:
            db = get_db()
            alias_success, cleaned_aliases, alias_errors = replace_account_aliases(account_id, email_addr, aliases, db)
            if not alias_success:
                db.rollback()
                return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})
            db.commit()
        return jsonify({'success': True, 'message': '账号更新成功', 'aliases': cleaned_aliases})
    return jsonify({'success': False, 'error': '更新失败'})


def api_get_emails_v2(email_addr):
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

    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))
    subject_contains = request.args.get('subject_contains', '').strip().lower()
    from_contains = request.args.get('from_contains', '').strip().lower()
    keyword = request.args.get('keyword', '').strip().lower()
    result = fetch_account_emails(account, folder, skip, top)
    if result.get('success'):
        if subject_contains or from_contains or keyword:
            result['emails'] = [
                item for item in result.get('emails', [])
                if email_matches_filters(account, item, subject_contains, from_contains, keyword)
            ]
        db = get_db()
        db.execute(
            '''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (account['id'],)
        )
        db.commit()
    return jsonify(result)


def api_external_get_emails_v2():
    email_addr = get_query_arg_preserve_plus('email', '').strip()
    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 1))
    subject_contains = get_query_arg_preserve_plus('subject_contains', '').strip().lower()
    from_contains = get_query_arg_preserve_plus('from_contains', '').strip().lower()
    keyword = get_query_arg_preserve_plus('keyword', '').strip().lower()

    if not email_addr:
        return jsonify({'success': False, 'error': '缺少 email 参数'}), 400

    valid_folders = sorted(VALID_MAIL_FOLDERS)
    if folder not in VALID_MAIL_FOLDERS:
        return jsonify({'success': False, 'error': f'folder 参数无效，仅支持 {", ".join(valid_folders)}'}), 400

    if top > 50:
        top = 50

    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '邮箱账号不存在'}), 404
    result = fetch_account_emails(account, folder, skip, top)
    if result.get('success'):
        if subject_contains or from_contains or keyword:
            result['emails'] = [
                item for item in result.get('emails', [])
                if email_matches_filters(account, item, subject_contains, from_contains, keyword)
            ]
        result['requested_email'] = email_addr
        result['resolved_email'] = account.get('email', '')
        if account.get('matched_alias'):
            result['matched_alias'] = account.get('matched_alias')
    return jsonify(result)


def email_matches_filters(account: Dict[str, Any], item: Dict[str, Any],
                          subject_contains: str = '', from_contains: str = '',
                          keyword: str = '') -> bool:
    subject = str(item.get('subject', '') or '')
    sender = str(item.get('from', '') or '')
    preview = str(item.get('body_preview', '') or '')

    if subject_contains and subject_contains not in subject.lower():
        return False
    if from_contains and from_contains not in sender.lower():
        return False
    if not keyword:
        return True

    base_text = '\n'.join([subject, preview]).lower()
    if keyword in base_text:
        return True

    proxy_url = get_account_proxy_url(account)
    if account.get('account_type') == 'imap':
        detail_payload = get_email_detail_imap_generic_result(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            account.get('imap_port', 993),
            str(item.get('id', '')),
            item.get('folder', 'inbox'),
            account.get('provider', 'custom'),
            proxy_url
        )
        if detail_payload and detail_payload.get('success'):
            body = str((detail_payload.get('email') or {}).get('body', '') or '')
            return keyword in strip_html_content(body).lower()
        return False

    detail = get_email_detail_graph(
        account.get('client_id', ''),
        account.get('refresh_token', ''),
        str(item.get('id', '')),
        proxy_url
    )
    if not detail:
        return False
    body = str((detail.get('body') or {}).get('content', '') or '')
    return keyword in strip_html_content(body).lower()


app.view_functions['api_update_account'] = api_update_account_v2
app.view_functions['api_get_emails'] = api_get_emails_v2
app.view_functions['api_external_get_emails'] = api_external_get_emails_v2


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

    init_scheduler()
    app.run(debug=debug, host=host, port=port)

    # 初始化定时任务
    init_scheduler()
