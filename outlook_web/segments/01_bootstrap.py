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
from datetime import datetime, timedelta, timezone
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
from outlook_web.runtime import default_database_path, resource_path, resolve_secret_key, runtime_root

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

app = Flask(
    __name__,
    template_folder=str(resource_path("templates")),
    static_folder=str(resource_path("static")),
)
# 优先使用环境变量；打包后的桌面版会在首次启动时生成并持久化 secret_key
secret_key = resolve_secret_key()
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required for server deployments. "
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
HTTP_REQUEST_TIMEOUT = int(os.getenv("HTTP_REQUEST_TIMEOUT", "30"))
IMAP_TIMEOUT = int(os.getenv("IMAP_TIMEOUT", "45"))
MAIL_FETCH_OVERALL_TIMEOUT = int(
    os.getenv("MAIL_FETCH_OVERALL_TIMEOUT", str(max(HTTP_REQUEST_TIMEOUT, IMAP_TIMEOUT) + 5))
)

try:
    with resource_path('VERSION').open('r', encoding='utf-8') as version_file:
        APP_VERSION = version_file.read().strip() or '1.0.0'
except Exception:
    APP_VERSION = '1.0.0'

REPOSITORY_OWNER = os.getenv('REPOSITORY_OWNER', 'assast')
REPOSITORY_NAME = os.getenv('REPOSITORY_NAME', 'outlookEmail')
CHANGELOG_URL = os.getenv(
    'CHANGELOG_URL',
    f'https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/blob/main/CHANGELOG.md',
)
REPOSITORY_URL = os.getenv(
    'REPOSITORY_URL',
    f'https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}',
)
REPOSITORY_VERSION_URL = os.getenv(
    'REPOSITORY_VERSION_URL',
    f'https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/blob/main/VERSION',
)
LATEST_RELEASE_API_URL = os.getenv(
    'LATEST_RELEASE_API_URL',
    f'https://api.github.com/repos/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/latest',
)
RAW_VERSION_URL = os.getenv(
    'RAW_VERSION_URL',
    f'https://raw.githubusercontent.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/main/VERSION',
)
VERSION_CHECK_TIMEOUT = max(2, int(os.getenv('VERSION_CHECK_TIMEOUT', '5')))
VERSION_CHECK_CACHE_TTL = max(60, int(os.getenv('VERSION_CHECK_CACHE_TTL', '900')))
VERSION_CHECK_CACHE_LOCK = threading.Lock()
VERSION_CHECK_CACHE = {
    'expires_at': 0.0,
    'payload': None,
}


def normalize_version_label(version: str) -> str:
    value = str(version or '').strip()
    if not value:
        return ''
    return value if value.lower().startswith('v') else f'v{value}'


def parse_version_parts(version: str) -> Optional[tuple[int, int, int]]:
    normalized = normalize_version_label(version)
    if not normalized:
        return None

    match = re.match(r'^v(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$', normalized)
    if not match:
        return None

    return tuple(int(part) for part in match.groups())


def compare_version_labels(left: str, right: str) -> Optional[int]:
    left_parts = parse_version_parts(left)
    right_parts = parse_version_parts(right)
    if left_parts is None or right_parts is None:
        return None
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def _version_request_headers() -> Dict[str, str]:
    return {
        'Accept': 'application/vnd.github+json',
        'User-Agent': f'OutlookEmail/{normalize_version_label(APP_VERSION) or "v1.0.0"}',
    }


def _safe_response_json(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def fetch_remote_version_snapshot() -> Dict[str, Any]:
    release_version = ''
    release_url = ''
    repository_version = ''
    errors = []

    try:
        release_response = requests.get(
            LATEST_RELEASE_API_URL,
            headers=_version_request_headers(),
            timeout=VERSION_CHECK_TIMEOUT,
        )
        release_response.raise_for_status()
        release_payload = _safe_response_json(release_response)
        release_version = normalize_version_label(release_payload.get('tag_name', ''))
        release_url = str(release_payload.get('html_url', '')).strip()
    except Exception as exc:
        errors.append(f'release:{exc}')

    try:
        repository_response = requests.get(
            RAW_VERSION_URL,
            headers=_version_request_headers(),
            timeout=VERSION_CHECK_TIMEOUT,
        )
        repository_response.raise_for_status()
        repository_version = normalize_version_label(repository_response.text)
    except Exception as exc:
        errors.append(f'repository:{exc}')

    return {
        'release_version': release_version,
        'release_url': release_url,
        'repository_version': repository_version,
        'errors': errors,
    }


def build_version_status_payload() -> Dict[str, Any]:
    current_version = normalize_version_label(APP_VERSION) or 'v1.0.0'
    current_parts = parse_version_parts(current_version)
    snapshot = fetch_remote_version_snapshot()

    release_version = snapshot['release_version']
    repository_version = snapshot['repository_version']
    latest_version = ''
    latest_source = ''
    latest_url = ''

    release_parts = parse_version_parts(release_version)
    repository_parts = parse_version_parts(repository_version)
    valid_candidates = []
    if release_parts is not None:
        valid_candidates.append(('release', release_version, release_parts, snapshot['release_url'] or REPOSITORY_URL))
    if repository_parts is not None:
        valid_candidates.append(('repository', repository_version, repository_parts, REPOSITORY_VERSION_URL))

    if valid_candidates:
        latest_source, latest_version, _latest_parts, latest_url = max(valid_candidates, key=lambda item: item[2])

    payload = {
        'current_version': current_version,
        'latest_version': latest_version,
        'latest_release_version': release_version,
        'latest_repository_version': repository_version,
        'status': 'unknown',
        'badge_label': '检查失败',
        'hint': '暂时无法获取仓库版本信息',
        'source': latest_source,
        'update_url': latest_url or CHANGELOG_URL,
        'release_url': snapshot['release_url'] or REPOSITORY_URL,
        'repository_url': REPOSITORY_VERSION_URL,
        'changelog_url': CHANGELOG_URL,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'errors': snapshot['errors'],
    }

    if current_parts is None:
        payload['hint'] = f'当前版本号 {current_version} 无法参与比较'
        return payload

    if not latest_version:
        return payload

    current_vs_latest = compare_version_labels(current_version, latest_version)
    current_vs_release = compare_version_labels(current_version, release_version) if release_version else None
    current_vs_repository = compare_version_labels(current_version, repository_version) if repository_version else None

    if current_vs_latest is None:
        payload['hint'] = f'当前版本号 {current_version} 无法参与比较'
        return payload

    if current_vs_latest < 0:
        payload['status'] = 'update_available'
        payload['badge_label'] = '可更新'
        if latest_source == 'release':
            payload['hint'] = f'发现新版本 {latest_version}'
        else:
            payload['hint'] = f'仓库最新版本为 {latest_version}'
        return payload

    if current_vs_release is not None and current_vs_release > 0:
        payload['status'] = 'ahead'
        payload['badge_label'] = '开发版'
        payload['hint'] = '当前版本高于已发布版本'
        payload['update_url'] = CHANGELOG_URL
        return payload

    if current_vs_repository is not None and current_vs_repository > 0:
        payload['status'] = 'ahead'
        payload['badge_label'] = '开发版'
        payload['hint'] = '当前版本高于仓库主分支版本'
        payload['update_url'] = CHANGELOG_URL
        return payload

    payload['status'] = 'up_to_date'
    payload['badge_label'] = '稳定版'
    if current_vs_release == 0:
        payload['hint'] = '与仓库发布版本同步'
        payload['source'] = 'release'
        payload['update_url'] = CHANGELOG_URL
    elif current_vs_repository == 0:
        payload['hint'] = '与仓库当前版本同步'
        payload['source'] = 'repository'
        payload['update_url'] = CHANGELOG_URL
    else:
        payload['hint'] = '当前版本已是最新'
        payload['update_url'] = CHANGELOG_URL
    return payload


def get_version_status_payload(force_refresh: bool = False) -> Dict[str, Any]:
    now = time.time()
    with VERSION_CHECK_CACHE_LOCK:
        cached_payload = VERSION_CHECK_CACHE.get('payload')
        expires_at = float(VERSION_CHECK_CACHE.get('expires_at', 0.0) or 0.0)
        if not force_refresh and cached_payload and expires_at > now:
            return dict(cached_payload)

        payload = build_version_status_payload()
        VERSION_CHECK_CACHE['payload'] = payload
        VERSION_CHECK_CACHE['expires_at'] = now + VERSION_CHECK_CACHE_TTL
        return dict(payload)

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
    "2925": {
        "label": "2925邮箱",
        "imap_host": "imap.2925.com",
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
    "2925.com": "2925",
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
    "2925": {
        "inbox": ["INBOX", "Inbox"],
        "junkemail": ["&V4NXPnux-", "Junk", "Junk Email", "Spam", "SPAM"],
        "deleteditems": ["&XfJT0ZAB-", "Trash", "Deleted", "Deleted Items", "Deleted Messages"],
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
FORWARD_CHANNEL_WECOM = "wecom"
FORWARD_CHANNEL_SMTP_SETTING = "smtp"
FORWARD_CHANNEL_TG_SETTING = "telegram"
FORWARD_CHANNEL_WECOM_SETTING = "wecom"
SMTP_FORWARD_PROVIDERS = ('outlook', 'qq', '163', '126', 'yahoo', 'aliyun', 'custom')

# 数据库文件
DATABASE = os.getenv("DATABASE_PATH", str(default_database_path()))

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
    if provider == 'custom':
        inferred = infer_provider_from_email(email_addr) if email_addr else 'custom'
        if inferred == '2925':
            provider = inferred
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
    secret_key = resolve_secret_key()
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


def normalize_group_sort_orders_on_startup(cursor) -> None:
    """启动时归一化分组顺序，但保留已有自定义顺序。"""
    cursor.execute(
        '''
        SELECT id, name, sort_order
        FROM groups
        ORDER BY
            CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
            CASE
                WHEN name = '临时邮箱' THEN 0
                WHEN COALESCE(sort_order, 0) > 0 THEN sort_order
                ELSE 2147483647
            END,
            id
        '''
    )
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

    # 创建项目表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            project_key TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            scope_mode TEXT NOT NULL DEFAULT 'all',
            use_alias_email INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            last_scope_synced_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建项目分组范围表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_group_scopes (
            project_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project_id, group_id)
        )
    ''')

    # 创建项目账号关系表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            account_id INTEGER,
            normalized_email TEXT NOT NULL,
            email_snapshot TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'toClaim',
            deleted_from_status TEXT DEFAULT '',
            source_group_id INTEGER,
            caller_id TEXT DEFAULT '',
            task_id TEXT DEFAULT '',
            claim_token TEXT,
            claimed_at TIMESTAMP,
            lease_expires_at TIMESTAMP,
            last_result TEXT DEFAULT '',
            last_result_detail TEXT DEFAULT '',
            claim_count INTEGER NOT NULL DEFAULT 0,
            first_claimed_at TIMESTAMP,
            last_claimed_at TIMESTAMP,
            done_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, normalized_email)
        )
    ''')

    # 创建项目账号事件表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_account_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            account_id INTEGER,
            normalized_email TEXT NOT NULL,
            project_account_id INTEGER,
            action TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            caller_id TEXT DEFAULT '',
            task_id TEXT DEFAULT '',
            claim_token TEXT,
            detail TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_accounts_project_status
        ON project_accounts(project_id, status)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_accounts_project_lease
        ON project_accounts(project_id, lease_expires_at)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_accounts_account_id
        ON project_accounts(account_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_accounts_project_email
        ON project_accounts(project_id, normalized_email)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_group_scopes_group_id
        ON project_group_scopes(group_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_project_events_project_created
        ON project_account_events(project_id, created_at)
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
    if 'fallback_proxy_url_1' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN fallback_proxy_url_1 TEXT')
    if 'fallback_proxy_url_2' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN fallback_proxy_url_2 TEXT')

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

    cursor.execute("PRAGMA table_info(project_accounts)")
    project_account_columns = [col[1] for col in cursor.fetchall()]
    if project_account_columns:
        if 'account_id' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN account_id INTEGER')
        if 'normalized_email' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN normalized_email TEXT DEFAULT ''")
        if 'email_snapshot' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN email_snapshot TEXT DEFAULT ''")
        if 'status' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN status TEXT DEFAULT 'toClaim'")
        if 'deleted_from_status' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN deleted_from_status TEXT DEFAULT ''")
        if 'source_group_id' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN source_group_id INTEGER')
        if 'caller_id' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN caller_id TEXT DEFAULT ''")
        if 'task_id' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN task_id TEXT DEFAULT ''")
        if 'claim_token' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN claim_token TEXT')
        if 'claimed_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN claimed_at TIMESTAMP')
        if 'lease_expires_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN lease_expires_at TIMESTAMP')
        if 'last_result' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN last_result TEXT DEFAULT ''")
        if 'last_result_detail' not in project_account_columns:
            cursor.execute("ALTER TABLE project_accounts ADD COLUMN last_result_detail TEXT DEFAULT ''")
        if 'claim_count' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN claim_count INTEGER DEFAULT 0')
        if 'first_claimed_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN first_claimed_at TIMESTAMP')
        if 'last_claimed_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN last_claimed_at TIMESTAMP')
        if 'done_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN done_at TIMESTAMP')
        if 'created_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        if 'updated_at' not in project_account_columns:
            cursor.execute('ALTER TABLE project_accounts ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')

    cursor.execute("PRAGMA table_info(projects)")
    project_columns = [col[1] for col in cursor.fetchall()]
    if project_columns:
        if 'use_alias_email' not in project_columns:
            cursor.execute('ALTER TABLE projects ADD COLUMN use_alias_email INTEGER NOT NULL DEFAULT 0')

    cursor.execute("PRAGMA table_info(project_account_events)")
    project_event_columns = [col[1] for col in cursor.fetchall()]
    if project_event_columns:
        if 'account_id' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN account_id INTEGER')
        if 'normalized_email' not in project_event_columns:
            cursor.execute("ALTER TABLE project_account_events ADD COLUMN normalized_email TEXT DEFAULT ''")
        if 'project_account_id' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN project_account_id INTEGER')
        if 'action' not in project_event_columns:
            cursor.execute("ALTER TABLE project_account_events ADD COLUMN action TEXT DEFAULT ''")
        if 'from_status' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN from_status TEXT')
        if 'to_status' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN to_status TEXT')
        if 'caller_id' not in project_event_columns:
            cursor.execute("ALTER TABLE project_account_events ADD COLUMN caller_id TEXT DEFAULT ''")
        if 'task_id' not in project_event_columns:
            cursor.execute("ALTER TABLE project_account_events ADD COLUMN task_id TEXT DEFAULT ''")
        if 'claim_token' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN claim_token TEXT')
        if 'detail' not in project_event_columns:
            cursor.execute("ALTER TABLE project_account_events ADD COLUMN detail TEXT DEFAULT ''")
        if 'created_at' not in project_event_columns:
            cursor.execute('ALTER TABLE project_account_events ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    
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

    # 归一化分组排序值，临时邮箱固定在最前，其他分组保留已有相对顺序。
    normalize_group_sort_orders_on_startup(cursor)
    
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
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('telegram_proxy_url', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('wecom_webhook_url', '')
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
    # 确保数据目录存在
    data_dir = os.path.dirname(DATABASE)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    
    # 初始化数据库
    init_db()
    
    print("=" * 60)
    print("Outlook 邮件 Web 应用已初始化")
    print(f"数据库文件: {DATABASE}")
    print(f"运行目录: {runtime_root()}")
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
