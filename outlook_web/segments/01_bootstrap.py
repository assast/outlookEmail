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
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.header import decode_header
from pathlib import Path, PurePosixPath
from typing import Optional, List, Dict, Any
from urllib.parse import quote, urlparse, unquote
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, Response, make_response
from functools import wraps
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from outlook_web.runtime import default_database_path, resource_path, resolve_secret_key, runtime_root
from outlook_web.mail_datetime import parse_mail_datetime

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

# CORS 支持：仅对外部 API (/api/external/*) 启用跨域访问
@app.after_request
def add_cors_headers_for_external_api(response):
    if request.path.startswith('/api/external/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
        response.headers['Access-Control-Max-Age'] = '86400'
    return response

scheduler_instance = None
scheduler_lock = threading.Lock()
token_refresh_run_lock = threading.Lock()
webdav_backup_run_lock = threading.Lock()
forwarding_run_lock = threading.Lock()
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
DEFAULT_APP_TIMEZONE = (os.getenv("APP_TIMEZONE", "Asia/Shanghai") or "Asia/Shanghai").strip()
FALLBACK_APP_TIMEZONE = "UTC"
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
RAW_CHANGELOG_URL = os.getenv(
    'RAW_CHANGELOG_URL',
    f'https://raw.githubusercontent.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/main/CHANGELOG.md',
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


def _clean_release_note_line(line: str) -> str:
    text = re.sub(r'^\s*(?:[-*+]|\d+\.)\s+', '', str(line or '').strip())
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[`*_]+', '', text)
    return text.strip()


def _extract_release_note_items(markdown_text: str, version: str = '') -> List[str]:
    normalized_version = normalize_version_label(version)
    plain_version = normalized_version.lstrip('v')
    lines = str(markdown_text or '').splitlines()
    selected_lines = lines

    if plain_version:
        heading_pattern = re.compile(
            rf'^##+\s+(?:\[\s*v?{re.escape(plain_version)}\s*\]|v?{re.escape(plain_version)})(?:\s|$)',
            flags=re.IGNORECASE,
        )
        start_index = None
        for index, line in enumerate(lines):
            if heading_pattern.search(line.strip()):
                start_index = index + 1
                break
        if start_index is not None:
            end_index = len(lines)
            for index in range(start_index, len(lines)):
                if re.match(r'^##\s+', lines[index].strip()):
                    end_index = index
                    break
            selected_lines = lines[start_index:end_index]

    items: List[str] = []
    for line in selected_lines:
        if not re.match(r'^\s*(?:[-*+]|\d+\.)\s+', line):
            continue
        item = _clean_release_note_line(line)
        if item:
            items.append(item)
        if len(items) >= 8:
            break

    return items


def _release_note_entry(title: str, items: List[str], url: str = '') -> Dict[str, Any]:
    return {
        'title': title,
        'items': items,
        'url': url,
    }


def _extract_changelog_release_entries(markdown_text: str, limit: int = 3) -> List[Dict[str, Any]]:
    lines = str(markdown_text or '').splitlines()
    headings: List[tuple[int, str, str]] = []
    heading_pattern = re.compile(r'^##\s+(?:\[\s*(v?\d+\.\d+\.\d+[^]\s]*)\s*\]|(v?\d+\.\d+\.\d+[^\s]*))', flags=re.IGNORECASE)

    for index, line in enumerate(lines):
        match = heading_pattern.match(line.strip())
        if not match:
            continue
        version = normalize_version_label(match.group(1) or match.group(2) or '')
        if version:
            headings.append((index, version, line.strip()))

    entries: List[Dict[str, Any]] = []
    for heading_index, version, _heading_text in headings[:limit]:
        end_index = len(lines)
        for index in range(heading_index + 1, len(lines)):
            if re.match(r'^##\s+', lines[index].strip()):
                end_index = index
                break
        items = _extract_release_note_items('\n'.join(lines[heading_index + 1:end_index]))
        if items:
            entries.append(_release_note_entry(version, items, CHANGELOG_URL))

    return entries


def _empty_release_notes() -> Dict[str, Any]:
    return {
        'source': '',
        'title': '',
        'items': [],
        'entries': [],
        'url': '',
    }


def build_release_notes_payload(source: str, title: str, body: str, url: str, version: str) -> Dict[str, Any]:
    items = _extract_release_note_items(body, version)
    if not items:
        return _empty_release_notes()
    entry = _release_note_entry(title or version, items, url)
    return {
        'source': source,
        'title': entry['title'],
        'items': items,
        'entries': [entry],
        'url': url,
    }


def fetch_changelog_release_notes(version: str) -> Dict[str, Any]:
    response = requests.get(
        RAW_CHANGELOG_URL,
        headers=_version_request_headers(),
        timeout=VERSION_CHECK_TIMEOUT,
    )
    response.raise_for_status()
    entries = _extract_changelog_release_entries(response.text, limit=3)
    if not entries:
        return build_release_notes_payload(
            'changelog',
            version,
            response.text,
            CHANGELOG_URL,
            version,
        )
    return {
        'source': 'changelog',
        'title': entries[0]['title'],
        'items': entries[0]['items'],
        'entries': entries,
        'url': CHANGELOG_URL,
    }


def fetch_remote_version_snapshot() -> Dict[str, Any]:
    release_version = ''
    release_url = ''
    release_title = ''
    release_body = ''
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
        release_title = str(release_payload.get('name', '')).strip()
        release_body = str(release_payload.get('body', '')).strip()
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
        'release_title': release_title,
        'release_body': release_body,
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
        'release_notes': _empty_release_notes(),
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
            payload['release_notes'] = build_release_notes_payload(
                'release',
                snapshot.get('release_title') or latest_version,
                snapshot.get('release_body', ''),
                snapshot.get('release_url') or latest_url,
                latest_version,
            )
        else:
            payload['hint'] = f'仓库最新版本为 {latest_version}'
        try:
            changelog_release_notes = fetch_changelog_release_notes(latest_version)
            if changelog_release_notes['items']:
                payload['release_notes'] = changelog_release_notes
        except Exception as exc:
            payload['errors'].append(f'changelog:{exc}')
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

SKIN_CLASSIC_ID = 'classic'
SKIN_SOURCE_BUILTIN = 'builtin'
SKIN_SOURCE_UPLOAD = 'upload'
SKIN_SOURCE_GIT = 'git'
SKIN_MANIFEST_FILENAME = 'skin.json'
SKIN_METADATA_FILENAME = '.outlook-skin-meta.json'
SKIN_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
SKIN_MAX_CSS_BYTES = 200 * 1024
SKIN_MAX_PREVIEW_BYTES = 1024 * 1024
SKIN_MAX_ZIP_BYTES = 5 * 1024 * 1024
SKIN_ALLOWED_PREVIEW_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
SKIN_BLOCKED_EXTRA_EXTENSIONS = {
    '.js', '.mjs', '.cjs', '.sh', '.bash', '.zsh', '.py',
    '.html', '.htm', '.exe', '.bat', '.cmd', '.ps1',
}
INDEX_CSS_FILES = (
    'css/index/01-base.css',
    'css/index/02-navbar.css',
    'css/index/03-layout.css',
    'css/index/04-account-panel.css',
    'css/index/05-email-content.css',
    'css/index/06-modals-toast.css',
    'css/index/07-meta.css',
    'css/index/08-responsive.css',
)
INDEX_JS_FILES = (
    'js/index/01-core.js',
    'js/index/02-groups.js',
    'js/index/03-temp-emails.js',
    'js/index/04-accounts.js',
    'js/index/05-emails.js',
    'js/index/06-utils-oauth.js',
    'js/index/07-settings.js',
    'js/index/08-refresh.js',
    'js/index/09-tags.js',
    'js/index/10-batch-actions.js',
    'js/index/11-email-shares.js',
    'js/index/12-outlook-upload-accounts.js',
)

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
CLOUDFLARE_AI_USERNAME_DEFAULT_PROMPT = os.getenv(
    "CLOUDFLARE_AI_USERNAME_PROMPT",
    "Generate {count} realistic, corporate-style American email username prefixes.\n"
    "Return only a JSON array of lowercase usernames. Seed: {seed}",
)

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


def get_index_columns(cursor, index_name: str) -> List[str]:
    return [
        row[2]
        for row in cursor.execute(f'PRAGMA index_info({index_name})').fetchall()
        if row[2]
    ]


def ensure_index_columns(cursor, index_name: str, table_name: str,
                         expected_columns: List[str], create_sql: str) -> None:
    """仅当索引缺失或列顺序变化时重建索引，避免每次启动都 DROP/CREATE。"""
    indexes = {
        row[1]
        for row in cursor.execute(f'PRAGMA index_list({table_name})').fetchall()
    }
    if index_name in indexes and get_index_columns(cursor, index_name) == expected_columns:
        return
    cursor.execute(f'DROP INDEX IF EXISTS {index_name}')
    cursor.execute(create_sql)


def normalize_group_sort_orders_on_startup(cursor) -> None:
    """启动时归一化分组顺序，但保留已有自定义顺序。"""
    cursor.execute(
        '''
        SELECT DISTINCT parent_id
        FROM groups
        '''
    )
    parent_ids = [row[0] for row in cursor.fetchall()]

    for parent_id in parent_ids:
        if parent_id is None:
            parent_filter = 'parent_id IS NULL'
            params = ()
        else:
            parent_filter = 'parent_id = ?'
            params = (parent_id,)

        cursor.execute(
            f'''
            SELECT id, name, sort_order
            FROM groups
            WHERE {parent_filter}
            ORDER BY
                CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
                CASE
                    WHEN name = '临时邮箱' THEN 0
                    WHEN COALESCE(sort_order, 0) > 0 THEN sort_order
                    ELSE 2147483647
                END,
                id
            ''',
            params
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

    cursor.execute(
        '''
        UPDATE groups
        SET parent_id = NULL, level = 1
        WHERE name = '临时邮箱' OR is_system = 1
        '''
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
            parent_id INTEGER DEFAULT NULL,
            level INTEGER DEFAULT 1 CHECK(level IN (1,2,3)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(parent_id) REFERENCES groups(id)
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
            sort_order INTEGER DEFAULT 0,
            remark TEXT,
            status TEXT DEFAULT 'active',
            account_type TEXT DEFAULT 'outlook',
            provider TEXT DEFAULT 'outlook',
            imap_host TEXT,
            imap_port INTEGER DEFAULT 993,
            imap_password TEXT,
            forward_enabled INTEGER DEFAULT 0,
            forward_last_checked_at TIMESTAMP,
            proxy_url TEXT DEFAULT '',
            fallback_proxy_url_1 TEXT DEFAULT '',
            fallback_proxy_url_2 TEXT DEFAULT '',
            last_refresh_at TIMESTAMP,
            last_refresh_status TEXT DEFAULT 'never',
            last_refresh_error TEXT,
            refresh_token_updated_at TIMESTAMP,
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cloudflare_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            worker_domain TEXT NOT NULL,
            email_domains TEXT DEFAULT '',
            admin_password TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute("PRAGMA table_info(cloudflare_channels)")
    cloudflare_channel_columns = cursor.fetchall()
    cloudflare_email_domain_column = next(
        (column for column in cloudflare_channel_columns if column[1] == 'email_domains'),
        None,
    )
    if cloudflare_email_domain_column and int(cloudflare_email_domain_column[3]) == 1:
        cursor.execute('ALTER TABLE cloudflare_channels RENAME TO cloudflare_channels_old')
        cursor.execute('''
            CREATE TABLE cloudflare_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                worker_domain TEXT NOT NULL,
                email_domains TEXT DEFAULT '',
                admin_password TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            INSERT INTO cloudflare_channels
            (id, name, worker_domain, email_domains, admin_password, enabled, is_default, created_at, updated_at)
            SELECT id, name, worker_domain, COALESCE(email_domains, ''), admin_password, enabled, is_default, created_at, updated_at
            FROM cloudflare_channels_old
        ''')
        cursor.execute('DROP TABLE cloudflare_channels_old')

    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cloudflare_channels_single_default
        ON cloudflare_channels(is_default)
        WHERE is_default = 1
    ''')

    cursor.execute('''
        SELECT LOWER(name) AS normalized_name
        FROM cloudflare_channels
        GROUP BY LOWER(name)
        HAVING COUNT(*) > 1
    ''')
    for conflict in cursor.fetchall():
        normalized_name = conflict[0]
        conflict_rows = cursor.execute(
            '''
            SELECT id, name
            FROM cloudflare_channels
            WHERE LOWER(name) = ?
            ORDER BY id
            ''',
            (normalized_name,)
        ).fetchall()
        used_names = {
            str(row[0] or '').strip().lower()
            for row in cursor.execute('SELECT name FROM cloudflare_channels').fetchall()
        }
        for duplicate_row in conflict_rows[1:]:
            channel_id = duplicate_row[0]
            base_name = str(duplicate_row[1] or '').strip() or f'cloudflare-{channel_id}'
            candidate = f'{base_name}-{channel_id}'
            counter = 2
            while candidate.lower() in used_names:
                candidate = f'{base_name}-{channel_id}-{counter}'
                counter += 1
            cursor.execute(
                'UPDATE cloudflare_channels SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (candidate, channel_id),
            )
            used_names.add(candidate.lower())

    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cloudflare_channels_name_lower
        ON cloudflare_channels(LOWER(name))
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
        CREATE TABLE IF NOT EXISTS token_refresh_state (
            scope_key TEXT PRIMARY KEY,
            trigger_type TEXT DEFAULT '',
            status TEXT DEFAULT 'idle',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            total_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            error_summary TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # 创建普通邮箱本地保留邮件表（列表元数据 + 已缓存正文）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS retained_normal_mail_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            folder TEXT NOT NULL DEFAULT 'inbox',
            provider_message_id TEXT NOT NULL,
            id_mode TEXT NOT NULL DEFAULT '',
            subject TEXT DEFAULT '无主题',
            sender TEXT DEFAULT '未知',
            recipients TEXT DEFAULT '',
            cc TEXT DEFAULT '',
            received_at TEXT DEFAULT '',
            received_at_sort REAL DEFAULT 0,
            is_read INTEGER NOT NULL DEFAULT 0,
            has_attachments INTEGER NOT NULL DEFAULT 0,
            body_preview TEXT DEFAULT '',
            body TEXT,
            body_type TEXT DEFAULT 'text',
            attachments_json TEXT DEFAULT '[]',
            list_cached INTEGER NOT NULL DEFAULT 1,
            body_cached INTEGER NOT NULL DEFAULT 0,
            list_cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            body_cached_at TIMESTAMP,
            last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_share_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            token_encrypted TEXT NOT NULL,
            expires_at TIMESTAMP,
            never_expires INTEGER NOT NULL DEFAULT 0,
            revoked_at TIMESTAMP,
            last_accessed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_email_share_links_account
        ON email_share_links(account_id, created_at)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_email_share_links_status
        ON email_share_links(revoked_at, expires_at, never_expires)
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

    # 创建临时邮箱标签关联表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_email_tags (
            temp_email_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (temp_email_id, tag_id),
            FOREIGN KEY (temp_email_id) REFERENCES temp_emails (id) ON DELETE CASCADE,
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

    # 外部上传的 Outlook 账号暂存表（账号/密码/是否授权，独立于 accounts）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outlook_upload_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_authorized INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            remark TEXT DEFAULT '',
            source TEXT DEFAULT 'external_api',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_outlook_upload_email
        ON outlook_upload_accounts(email)
    ''')

    # 检查并添加缺失的列（数据库迁移）
    cursor.execute("PRAGMA table_info(accounts)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'group_id' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN group_id INTEGER DEFAULT 1')
    if 'sort_order' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN sort_order INTEGER DEFAULT 0')
    if 'remark' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN remark TEXT')
    if 'status' not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN status TEXT DEFAULT 'active'")
    if 'updated_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    if 'last_refresh_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN last_refresh_at TIMESTAMP')
    if 'last_refresh_status' not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN last_refresh_status TEXT DEFAULT 'never'")
    if 'last_refresh_error' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN last_refresh_error TEXT')
    if 'refresh_token_updated_at' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN refresh_token_updated_at TIMESTAMP')
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
    if 'proxy_url' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN proxy_url TEXT')
    if 'fallback_proxy_url_1' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN fallback_proxy_url_1 TEXT')
    if 'fallback_proxy_url_2' not in columns:
        cursor.execute('ALTER TABLE accounts ADD COLUMN fallback_proxy_url_2 TEXT')
    
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
    if 'parent_id' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN parent_id INTEGER DEFAULT NULL')
    if 'level' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN level INTEGER DEFAULT 1')
    cursor.execute('''
        UPDATE groups
        SET parent_id = NULL,
            level = COALESCE(NULLIF(level, 0), 1)
        WHERE parent_id IS NULL
    ''')

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
    if 'cloudflare_channel_id' not in temp_columns:
        cursor.execute('ALTER TABLE temp_emails ADD COLUMN cloudflare_channel_id INTEGER')

    cursor.execute("PRAGMA table_info(retained_normal_mail_messages)")
    retained_normal_mail_columns = {row[1] for row in cursor.fetchall()}
    if 'received_at_sort' not in retained_normal_mail_columns:
        cursor.execute('ALTER TABLE retained_normal_mail_messages ADD COLUMN received_at_sort REAL DEFAULT 0')

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
    cursor.execute("UPDATE groups SET parent_id = NULL, level = 1 WHERE name IN ('默认分组', '临时邮箱')")

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
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_ai_username_enabled', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_ai_username_api_url', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_ai_username_model', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_ai_username_api_key', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('cloudflare_ai_username_prompt', ?)
    ''', (CLOUDFLARE_AI_USERNAME_DEFAULT_PROMPT,))

    cursor.execute('SELECT COUNT(*) FROM cloudflare_channels')
    cloudflare_channel_count = cursor.fetchone()[0]
    if cloudflare_channel_count == 0:
        legacy_worker_row = cursor.execute(
            "SELECT value FROM settings WHERE key = 'cloudflare_worker_domain'"
        ).fetchone()
        legacy_domains_row = cursor.execute(
            "SELECT value FROM settings WHERE key = 'cloudflare_email_domains'"
        ).fetchone()
        legacy_password_row = cursor.execute(
            "SELECT value FROM settings WHERE key = 'cloudflare_admin_password'"
        ).fetchone()
        legacy_worker_domain = str(legacy_worker_row[0] if legacy_worker_row and legacy_worker_row[0] is not None else '').strip()
        legacy_email_domains = str(legacy_domains_row[0] if legacy_domains_row and legacy_domains_row[0] is not None else '').strip()
        legacy_admin_password = str(legacy_password_row[0] if legacy_password_row and legacy_password_row[0] is not None else '').strip()
        if legacy_worker_domain and legacy_admin_password:
            cursor.execute(
                '''
                INSERT INTO cloudflare_channels
                (name, worker_domain, email_domains, admin_password, enabled, is_default)
                VALUES (?, ?, ?, ?, 1, 1)
                ''',
                (
                    'default',
                    legacy_worker_domain,
                    legacy_email_domains,
                    encrypt_data(legacy_admin_password),
                )
            )

    cursor.execute(
        '''
        SELECT id FROM cloudflare_channels
        WHERE is_default = 1
        ORDER BY id
        LIMIT 1
        '''
    )
    default_cloudflare_channel = cursor.fetchone()
    if default_cloudflare_channel:
        cursor.execute(
            '''
            UPDATE temp_emails
            SET cloudflare_channel_id = ?
            WHERE provider = 'cloudflare'
              AND (cloudflare_channel_id IS NULL OR cloudflare_channel_id = '')
            ''',
            (default_cloudflare_channel[0],)
        )


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
        VALUES ('app_timezone', ?)
    ''', (DEFAULT_APP_TIMEZONE or 'Asia/Shanghai',))
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('show_account_created_at', 'true')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('show_account_sort_order', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('show_group_id', 'true')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('normal_mail_local_retention_enabled', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('active_skin_id', ?)
    ''', (SKIN_CLASSIC_ID,))
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('skin_last_error', '')
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_check_interval_minutes', '5')
    ''')
    forward_interval_minutes_row = cursor.execute(
        "SELECT value FROM settings WHERE key = 'forward_check_interval_minutes'"
    ).fetchone()
    try:
        forward_interval_minutes = max(
            1,
            min(60, int(forward_interval_minutes_row[0] if forward_interval_minutes_row else '5'))
        )
    except (TypeError, ValueError):
        forward_interval_minutes = 5
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_check_interval_seconds', ?)
    ''', (str(forward_interval_minutes * 60),))
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_execution_mode', 'serial')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_parallel_workers', '4')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('forward_account_delay_seconds', '0')
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
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_enabled', 'false')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_url', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_username', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_password', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_cron', '0 3 * * *')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_last_run_at', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_last_status', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_last_message', '')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('webdav_backup_last_filename', '')
    ''')

    # 创建索引以优化查询性能
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_last_refresh_at
        ON accounts(last_refresh_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_last_refresh_status
        ON accounts(last_refresh_status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_status
        ON accounts(status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_sort_order
        ON accounts(sort_order)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_group_created
        ON accounts(group_id, created_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_group_sort_order
        ON accounts(group_id, sort_order)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_group_email
        ON accounts(group_id, email)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_accounts_group_email_nocase
        ON accounts(group_id, email COLLATE NOCASE)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_groups_parent_id
        ON groups(parent_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_account_refresh_logs_account_id
        ON account_refresh_logs(account_id)
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO token_refresh_state (
            scope_key, trigger_type, status, total_count, success_count, failed_count, updated_at
        )
        VALUES ('all_outlook', '', 'idle', 0, 0, 0, CURRENT_TIMESTAMP)
    ''')

    cursor.execute('''
        UPDATE accounts
        SET last_refresh_status = COALESCE(
            NULLIF(last_refresh_status, ''),
            (
                SELECT l.status
                FROM account_refresh_logs l
                WHERE l.account_id = accounts.id
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT 1
            ),
            CASE
                WHEN last_refresh_at IS NOT NULL THEN 'success'
                ELSE 'never'
            END
        )
        WHERE last_refresh_status IS NULL OR last_refresh_status = ''
    ''')

    cursor.execute('''
        UPDATE accounts
        SET last_refresh_error = (
            SELECT l.error_message
            FROM account_refresh_logs l
            WHERE l.account_id = accounts.id
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT 1
        )
        WHERE COALESCE(last_refresh_status, 'never') = 'failed'
          AND (last_refresh_error IS NULL OR last_refresh_error = '')
          AND EXISTS (
              SELECT 1
              FROM account_refresh_logs l
              WHERE l.account_id = accounts.id
          )
    ''')

    cursor.execute('''
        UPDATE accounts
        SET last_refresh_error = NULL
        WHERE COALESCE(last_refresh_status, 'never') != 'failed'
          AND last_refresh_error IS NOT NULL
    ''')

    cursor.execute('''
        UPDATE accounts
        SET last_refresh_at = (
            SELECT l.created_at
            FROM account_refresh_logs l
            WHERE l.account_id = accounts.id
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1
            FROM account_refresh_logs l
            WHERE l.account_id = accounts.id
        )
          AND (
              last_refresh_at IS NULL OR
              last_refresh_at < (
                  SELECT l.created_at
                  FROM account_refresh_logs l
                  WHERE l.account_id = accounts.id
                  ORDER BY l.created_at DESC, l.id DESC
                  LIMIT 1
              )
          )
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
        CREATE UNIQUE INDEX IF NOT EXISTS ux_retained_normal_mail_messages_key
        ON retained_normal_mail_messages(account_id, folder, provider_message_id, id_mode)
    ''')

    ensure_index_columns(
        cursor,
        'idx_retained_normal_mail_messages_list',
        'retained_normal_mail_messages',
        ['account_id', 'folder', 'received_at_sort', 'id'],
        '''
        CREATE INDEX idx_retained_normal_mail_messages_list
        ON retained_normal_mail_messages(account_id, folder, received_at_sort DESC, id DESC)
        '''
    )

    ensure_index_columns(
        cursor,
        'idx_retained_normal_mail_messages_body_cache',
        'retained_normal_mail_messages',
        ['account_id', 'folder', 'body_cached', 'received_at_sort'],
        '''
        CREATE INDEX idx_retained_normal_mail_messages_body_cache
        ON retained_normal_mail_messages(account_id, folder, body_cached, received_at_sort DESC)
        '''
    )

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

    # 回填历史保留邮件的规范化排序时间，保持旧数据库升级后分页顺序稳定。
    backfill_retained_normal_mail_received_at_sort(conn)

    # 迁移现有明文数据为加密数据
    migrate_sensitive_data(conn)

    conn.commit()
    conn.close()



def backfill_retained_normal_mail_received_at_sort(conn) -> int:
    """为旧保留邮件行回填可排序时间戳；事务提交由调用方负责。"""
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT id, received_at
            FROM retained_normal_mail_messages
            WHERE COALESCE(received_at_sort, 0) = 0
              AND COALESCE(received_at, '') <> ''
        ''')
    except sqlite3.OperationalError:
        return 0

    updates = []
    for row_id, received_at in cursor.fetchall():
        parsed = parse_mail_datetime(received_at)
        if not parsed:
            continue
        updates.append((parsed.timestamp(), row_id))

    if not updates:
        return 0

    cursor.executemany(
        'UPDATE retained_normal_mail_messages SET received_at_sort = ? WHERE id = ?',
        updates
    )
    return len(updates)

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
        if key == 'normal_mail_local_retention_enabled':
            cache_updater = globals().get('set_normal_mail_local_retention_enabled_cache')
            if callable(cache_updater):
                cache_updater(value)
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


def is_valid_app_timezone_name(value: str) -> bool:
    candidate = str(value or '').strip()
    if not candidate:
        return False
    try:
        ZoneInfo(candidate)
        return True
    except Exception:
        return False


def normalize_app_timezone_name(value: str, default: str = DEFAULT_APP_TIMEZONE) -> str:
    candidate = str(value or '').strip()
    if is_valid_app_timezone_name(candidate):
        return candidate

    fallback = str(default or '').strip()
    if is_valid_app_timezone_name(fallback):
        return fallback

    return FALLBACK_APP_TIMEZONE


def get_app_timezone() -> str:
    return normalize_app_timezone_name(get_setting('app_timezone', DEFAULT_APP_TIMEZONE))


def get_app_timezone_info():
    return ZoneInfo(get_app_timezone())


def get_all_settings() -> Dict[str, str]:
    """获取所有设置"""
    db = get_db()
    cursor = db.execute('SELECT key, value FROM settings')
    rows = cursor.fetchall()
    return {row['key']: row['value'] for row in rows}


# ==================== 皮肤管理 ====================

class SkinValidationError(ValueError):
    """皮肤包格式或安全校验失败。"""


def normalize_skin_id(value: str) -> str:
    candidate = str(value or '').strip().lower()
    return candidate if SKIN_ID_PATTERN.fullmatch(candidate) else ''


def get_skin_data_root() -> Path:
    root = Path(DATABASE).expanduser().resolve().parent / 'skins'
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_skin_source_root(source_type: str) -> Path:
    normalized_source = str(source_type or '').strip().lower()
    if normalized_source not in (SKIN_SOURCE_UPLOAD, SKIN_SOURCE_GIT):
        raise SkinValidationError('皮肤来源类型无效')
    root = get_skin_data_root() / normalized_source
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_skin_relative_path(value: str, field_name: str = '路径') -> Path:
    raw_value = str(value or '').strip().replace('\\', '/')
    if not raw_value:
        raise SkinValidationError(f'{field_name}不能为空')

    posix_path = PurePosixPath(raw_value)
    if posix_path.is_absolute():
        raise SkinValidationError(f'{field_name}不能是绝对路径')
    if any(part in ('', '.', '..') for part in posix_path.parts):
        raise SkinValidationError(f'{field_name}不能包含路径穿越')

    return Path(*posix_path.parts)


def resolve_skin_package_file(package_dir: Path, relative_path: str, field_name: str = '路径') -> Path:
    base_dir = Path(package_dir).resolve()
    candidate = (base_dir / safe_skin_relative_path(relative_path, field_name)).resolve()
    if os.path.commonpath([str(base_dir), str(candidate)]) != str(base_dir):
        raise SkinValidationError(f'{field_name}不能指向皮肤包目录外')
    return candidate


def compute_skin_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as file_obj:
        for chunk in iter(lambda: file_obj.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def compute_static_assets_hash(relative_paths) -> str:
    digest = hashlib.sha256()
    static_root = Path(app.static_folder)
    for relative_path in relative_paths:
        digest.update(str(relative_path).encode('utf-8'))
        digest.update(b'\0')
        with (static_root / relative_path).open('rb') as file_obj:
            for chunk in iter(lambda: file_obj.read(65536), b''):
                digest.update(chunk)
    return digest.hexdigest()[:16]


def get_frontend_asset_hash() -> str:
    return compute_static_assets_hash(INDEX_CSS_FILES + INDEX_JS_FILES)


def get_builtin_editorial_skin_css_path() -> Path:
    return Path(app.static_folder) / 'css' / 'editorial.css'


def get_builtin_editorial_skin_asset_hash() -> str:
    try:
        return compute_skin_file_hash(get_builtin_editorial_skin_css_path())
    except Exception:
        return 'editorial'


def read_skin_json(path: Path) -> Dict[str, Any]:
    try:
        with Path(path).open('r', encoding='utf-8') as file_obj:
            payload = json.load(file_obj)
    except json.JSONDecodeError as exc:
        raise SkinValidationError(f'skin.json 格式无效: {exc}') from exc
    except OSError as exc:
        raise SkinValidationError(f'读取 skin.json 失败: {exc}') from exc

    if not isinstance(payload, dict):
        raise SkinValidationError('skin.json 必须是 JSON 对象')
    return payload


def validate_skin_file_size(path: Path, max_bytes: int, label: str) -> None:
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        raise SkinValidationError(f'{label}不可读取: {exc}') from exc
    if size > max_bytes:
        raise SkinValidationError(f'{label}超过大小限制')


def validate_skin_extra_files(package_dir: Path, allowed_paths: set[str]) -> None:
    base_dir = Path(package_dir).resolve()
    for file_path in base_dir.rglob('*'):
        if not file_path.is_file():
            continue

        relative = file_path.relative_to(base_dir).as_posix()
        suffix = file_path.suffix.lower()
        if file_path.name == SKIN_METADATA_FILENAME:
            continue
        if suffix in SKIN_BLOCKED_EXTRA_EXTENSIONS:
            raise SkinValidationError(f'皮肤包包含不允许的文件类型: {relative}')
        if relative in allowed_paths:
            continue
        if suffix == '.css':
            validate_skin_file_size(file_path, SKIN_MAX_CSS_BYTES, f'CSS 文件 {relative}')
            continue
        if suffix in SKIN_ALLOWED_PREVIEW_EXTENSIONS:
            validate_skin_file_size(file_path, SKIN_MAX_PREVIEW_BYTES, f'图片文件 {relative}')
            continue
        if (
            suffix in ('.md', '.txt')
            or file_path.name.upper() in ('README', 'LICENSE')
            or file_path.name in ('.gitignore', '.gitattributes')
        ):
            validate_skin_file_size(file_path, SKIN_MAX_PREVIEW_BYTES, f'说明文件 {relative}')
            continue
        raise SkinValidationError(f'皮肤包包含不支持的文件: {relative}')


def validate_skin_package_directory(package_dir: Path) -> Dict[str, Any]:
    base_dir = Path(package_dir).resolve()
    manifest_path = base_dir / SKIN_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise SkinValidationError('皮肤包缺少 skin.json')

    manifest = read_skin_json(manifest_path)
    skin_id = normalize_skin_id(manifest.get('id'))
    if not skin_id:
        raise SkinValidationError('skin.json 的 id 只能包含小写字母、数字、下划线和短横线')
    if skin_id == SKIN_CLASSIC_ID:
        raise SkinValidationError('classic 是内置皮肤 ID，不能用于自定义皮肤')

    name = str(manifest.get('name') or '').strip()
    version = str(manifest.get('version') or '').strip()
    entry = str(manifest.get('entry') or '').strip()
    if not name:
        raise SkinValidationError('skin.json 缺少 name')
    if not version:
        raise SkinValidationError('skin.json 缺少 version')
    if not entry:
        raise SkinValidationError('skin.json 缺少 entry')
    if Path(entry).suffix.lower() != '.css':
        raise SkinValidationError('entry 必须指向 CSS 文件')

    entry_path = resolve_skin_package_file(base_dir, entry, 'entry')
    if not entry_path.is_file():
        raise SkinValidationError('entry 指向的 CSS 文件不存在')
    validate_skin_file_size(entry_path, SKIN_MAX_CSS_BYTES, 'CSS 文件')

    preview = str(manifest.get('preview') or '').strip()
    preview_path = None
    if preview:
        if Path(preview).suffix.lower() not in SKIN_ALLOWED_PREVIEW_EXTENSIONS:
            raise SkinValidationError('preview 必须是 png、jpg、gif 或 webp 图片')
        preview_path = resolve_skin_package_file(base_dir, preview, 'preview')
        if not preview_path.is_file():
            raise SkinValidationError('preview 指向的图片文件不存在')
        validate_skin_file_size(preview_path, SKIN_MAX_PREVIEW_BYTES, '预览图')

    allowed_paths = {
        SKIN_MANIFEST_FILENAME,
        safe_skin_relative_path(entry, 'entry').as_posix(),
    }
    if preview:
        allowed_paths.add(safe_skin_relative_path(preview, 'preview').as_posix())
    validate_skin_extra_files(base_dir, allowed_paths)

    return {
        'id': skin_id,
        'name': name,
        'version': version,
        'entry': safe_skin_relative_path(entry, 'entry').as_posix(),
        'description': str(manifest.get('description') or '').strip(),
        'preview': safe_skin_relative_path(preview, 'preview').as_posix() if preview else '',
        'asset_hash': compute_skin_file_hash(entry_path),
    }


def read_skin_install_metadata(skin_dir: Path) -> Dict[str, Any]:
    metadata_path = Path(skin_dir) / SKIN_METADATA_FILENAME
    if not metadata_path.is_file():
        return {}
    try:
        with metadata_path.open('r', encoding='utf-8') as file_obj:
            payload = json.load(file_obj)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_skin_install_metadata(skin_dir: Path, metadata: Dict[str, Any]) -> None:
    metadata_path = Path(skin_dir) / SKIN_METADATA_FILENAME
    with metadata_path.open('w', encoding='utf-8') as file_obj:
        json.dump(metadata, file_obj, ensure_ascii=False, indent=2, sort_keys=True)


def build_builtin_skin_record(skin_id: str = SKIN_CLASSIC_ID, active: bool = False) -> Dict[str, Any]:
    last_error = get_setting('skin_last_error', '') if active else ''
    if skin_id == 'editorial':
        return {
            'id': 'editorial',
            'name': '雅致暗蓝',
            'version': APP_VERSION,
            'description': '深邃幽蓝与微光边框，搭配极简大字字重，提供沉浸社论级排版质感。',
            'entry': 'theme.css',
            'preview': '',
            'source_type': SKIN_SOURCE_BUILTIN,
            'builtin': True,
            'active': active,
            'status': 'ok',
            'asset_hash': get_builtin_editorial_skin_asset_hash(),
            'last_error': last_error,
            'git_url': '',
            'git_ref': '',
        }
    return {
        'id': SKIN_CLASSIC_ID,
        'name': '经典',
        'version': APP_VERSION,
        'description': '当前默认界面皮肤',
        'entry': '',
        'preview': '',
        'source_type': SKIN_SOURCE_BUILTIN,
        'builtin': True,
        'active': active,
        'status': 'ok',
        'asset_hash': SKIN_CLASSIC_ID,
        'last_error': last_error,
        'git_url': '',
        'git_ref': '',
    }


def build_skin_record_from_dir(skin_dir: Path, source_type: str, active: bool = False) -> Dict[str, Any]:
    metadata = read_skin_install_metadata(skin_dir)
    try:
        manifest = validate_skin_package_directory(skin_dir)
        status = 'ok'
        validation_error = ''
    except SkinValidationError as exc:
        manifest = {
            'id': normalize_skin_id(metadata.get('id')) or Path(skin_dir).name,
            'name': str(metadata.get('name') or Path(skin_dir).name),
            'version': str(metadata.get('version') or ''),
            'entry': str(metadata.get('entry') or ''),
            'description': str(metadata.get('description') or ''),
            'preview': str(metadata.get('preview') or ''),
            'asset_hash': str(metadata.get('asset_hash') or ''),
        }
        status = 'invalid'
        validation_error = str(exc)

    last_error = validation_error or str(metadata.get('last_error') or '')
    return {
        'id': manifest['id'],
        'name': manifest['name'],
        'version': manifest['version'],
        'description': manifest.get('description', ''),
        'entry': manifest.get('entry', ''),
        'preview': manifest.get('preview', ''),
        'source_type': source_type,
        'builtin': False,
        'active': active,
        'status': status,
        'asset_hash': manifest.get('asset_hash', ''),
        'last_error': last_error,
        'git_url': str(metadata.get('git_url') or ''),
        'git_ref': str(metadata.get('git_ref') or ''),
        'installed_at': str(metadata.get('installed_at') or ''),
        'updated_at': str(metadata.get('updated_at') or ''),
    }


def list_custom_skin_records(active_skin_id: str = '') -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    root = get_skin_data_root()
    for source_type in (SKIN_SOURCE_UPLOAD, SKIN_SOURCE_GIT):
        source_root = root / source_type
        if not source_root.is_dir():
            continue
        for skin_dir in sorted(source_root.iterdir(), key=lambda item: item.name):
            if not skin_dir.is_dir() or skin_dir.name.startswith('.'):
                continue
            records.append(build_skin_record_from_dir(
                skin_dir,
                source_type,
                active=normalize_skin_id(active_skin_id) == normalize_skin_id(skin_dir.name),
            ))
    return records


def get_skin_record_by_id(skin_id: str) -> Optional[Dict[str, Any]]:
    normalized_id = normalize_skin_id(skin_id)
    if normalized_id == SKIN_CLASSIC_ID:
        return build_builtin_skin_record(SKIN_CLASSIC_ID)
    if normalized_id == 'editorial':
        return build_builtin_skin_record('editorial')
    if not normalized_id:
        return None

    for record in list_custom_skin_records():
        if normalize_skin_id(record.get('id')) == normalized_id:
            return record
    return None


def get_skin_directory(record: Dict[str, Any]) -> Optional[Path]:
    if not record or record.get('builtin'):
        return None
    source_type = str(record.get('source_type') or '').strip().lower()
    skin_id = normalize_skin_id(record.get('id'))
    if source_type not in (SKIN_SOURCE_UPLOAD, SKIN_SOURCE_GIT) or not skin_id:
        return None
    return get_skin_source_root(source_type) / skin_id


def record_skin_error(skin_id: str, error: str) -> None:
    normalized_id = normalize_skin_id(skin_id)
    message = str(error or '').strip()
    if not normalized_id or normalized_id in (SKIN_CLASSIC_ID, 'editorial'):
        set_setting('skin_last_error', message)
        return

    record = get_skin_record_by_id(normalized_id)
    skin_dir = get_skin_directory(record or {})
    if not skin_dir:
        set_setting('skin_last_error', message)
        return
    metadata = read_skin_install_metadata(skin_dir)
    metadata['last_error'] = message
    metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_skin_install_metadata(skin_dir, metadata)


def clear_skin_error(skin_id: str) -> None:
    record_skin_error(skin_id, '')


def get_configured_active_skin_id() -> str:
    return normalize_skin_id(get_setting('active_skin_id', SKIN_CLASSIC_ID)) or SKIN_CLASSIC_ID


def resolve_active_skin_record() -> Dict[str, Any]:
    configured_id = get_configured_active_skin_id()
    record = get_skin_record_by_id(configured_id)
    if not record or record.get('status') != 'ok':
        if configured_id not in (SKIN_CLASSIC_ID, 'editorial'):
            record_skin_error(configured_id, f'当前皮肤 {configured_id} 不可用，已回退到 classic')
        return build_builtin_skin_record(SKIN_CLASSIC_ID, active=True)

    record['active'] = True
    return record


def get_skin_settings_payload() -> Dict[str, Any]:
    configured_id = get_configured_active_skin_id()
    active_record = resolve_active_skin_record()
    effective_id = active_record['id']
    skins = [
        build_builtin_skin_record(SKIN_CLASSIC_ID, active=effective_id == SKIN_CLASSIC_ID),
        build_builtin_skin_record('editorial', active=effective_id == 'editorial')
    ]
    skins.extend(list_custom_skin_records(active_skin_id=effective_id))
    return {
        'configured_skin_id': configured_id,
        'active_skin_id': effective_id,
        'active_skin': active_record,
        'skins': skins,
        'asset_hash': active_record.get('asset_hash') or SKIN_CLASSIC_ID,
    }


def set_active_skin(skin_id: str) -> tuple[bool, str, Optional[Dict[str, Any]]]:
    normalized_id = normalize_skin_id(skin_id)
    if not normalized_id:
        return False, '皮肤 ID 无效', None

    record = get_skin_record_by_id(normalized_id)
    if not record:
        return False, '皮肤不存在', None
    if record.get('status') != 'ok':
        return False, record.get('last_error') or '皮肤不可用', None

    if set_setting('active_skin_id', normalized_id):
        clear_skin_error(normalized_id)
        return True, '', get_skin_record_by_id(normalized_id)
    return False, '保存当前皮肤失败', None


def get_active_skin_asset_hash() -> str:
    return str(resolve_active_skin_record().get('asset_hash') or SKIN_CLASSIC_ID)


def get_active_skin_css() -> tuple[str, str]:
    record = resolve_active_skin_record()
    if record.get('id') == SKIN_CLASSIC_ID:
        return '/* classic skin: base styles */\n', SKIN_CLASSIC_ID
    if record.get('id') == 'editorial':
        try:
            css_path = get_builtin_editorial_skin_css_path()
            return css_path.read_text(encoding='utf-8'), compute_skin_file_hash(css_path)
        except Exception as exc:
            record_skin_error('editorial', f'读取内置皮肤 CSS 失败: {exc}')
            return '/* skin unavailable, fallback to classic */\n', SKIN_CLASSIC_ID

    skin_dir = get_skin_directory(record)
    if not skin_dir:
        record_skin_error(record.get('id'), '皮肤目录不存在')
        return '/* skin unavailable, fallback to classic */\n', SKIN_CLASSIC_ID

    try:
        css_path = resolve_skin_package_file(skin_dir, record.get('entry', ''), 'entry')
        validate_skin_file_size(css_path, SKIN_MAX_CSS_BYTES, 'CSS 文件')
        return css_path.read_text(encoding='utf-8'), str(record.get('asset_hash') or compute_skin_file_hash(css_path))
    except Exception as exc:
        record_skin_error(record.get('id'), f'读取皮肤 CSS 失败: {exc}')
        return '/* skin unavailable, fallback to classic */\n', SKIN_CLASSIC_ID


def ensure_skin_id_is_installable(skin_id: str, source_type: str) -> None:
    if skin_id in (SKIN_CLASSIC_ID, 'editorial'):
        raise SkinValidationError(f'{skin_id} 是内置皮肤，不能覆盖')
    existing = get_skin_record_by_id(skin_id)
    if existing and existing.get('source_type') != source_type:
        raise SkinValidationError('相同皮肤 ID 已由其他来源安装')


def replace_skin_directory_atomically(source_dir: Path, target_dir: Path) -> None:
    target_parent = Path(target_dir).parent
    target_parent.mkdir(parents=True, exist_ok=True)
    backup_dir = target_parent / f'.backup-{Path(target_dir).name}-{uuid.uuid4().hex}'
    if Path(target_dir).exists():
        Path(target_dir).rename(backup_dir)

    try:
        Path(source_dir).rename(target_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        if Path(target_dir).exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        if backup_dir.exists():
            backup_dir.rename(target_dir)
        raise


def install_skin_from_directory(
    package_dir: Path,
    source_type: str,
    source_config: Optional[Dict[str, Any]] = None,
    expected_skin_id: str = '',
) -> Dict[str, Any]:
    normalized_source = str(source_type or '').strip().lower()
    if normalized_source not in (SKIN_SOURCE_UPLOAD, SKIN_SOURCE_GIT):
        raise SkinValidationError('皮肤来源类型无效')

    manifest = validate_skin_package_directory(package_dir)
    skin_id = manifest['id']
    if expected_skin_id and skin_id != normalize_skin_id(expected_skin_id):
        raise SkinValidationError('更新后的皮肤 ID 与已安装皮肤不一致')
    ensure_skin_id_is_installable(skin_id, normalized_source)

    source_root = get_skin_source_root(normalized_source)
    target_dir = source_root / skin_id
    temp_dir = source_root / f'.install-{skin_id}-{uuid.uuid4().hex}'
    shutil.copytree(
        package_dir,
        temp_dir,
        ignore=shutil.ignore_patterns('.git', SKIN_METADATA_FILENAME, '__pycache__'),
    )
    copied_manifest = validate_skin_package_directory(temp_dir)

    now_text = datetime.now(timezone.utc).isoformat()
    existing_metadata = read_skin_install_metadata(target_dir)
    metadata = {
        **copied_manifest,
        'source_type': normalized_source,
        'installed_at': existing_metadata.get('installed_at') or now_text,
        'updated_at': now_text,
        'last_error': '',
    }
    if source_config:
        metadata.update({
            key: str(value or '').strip()
            for key, value in source_config.items()
            if key in ('git_url', 'git_ref')
        })
    write_skin_install_metadata(temp_dir, metadata)
    replace_skin_directory_atomically(temp_dir, target_dir)
    return build_skin_record_from_dir(target_dir, normalized_source)


def zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def extract_zip_skin_package(zip_path: Path, output_dir: Path) -> None:
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise SkinValidationError('上传文件不是有效 zip') from exc

    with archive:
        total_size = 0
        for info in archive.infolist():
            if zip_entry_is_symlink(info):
                raise SkinValidationError('zip 包不能包含符号链接')
            relative_path = safe_skin_relative_path(info.filename, 'zip 文件路径')
            if info.is_dir():
                continue
            total_size += int(info.file_size or 0)
            if total_size > SKIN_MAX_ZIP_BYTES:
                raise SkinValidationError('zip 包内容超过大小限制')
            suffix = Path(relative_path).suffix.lower()
            if suffix in SKIN_BLOCKED_EXTRA_EXTENSIONS:
                raise SkinValidationError(f'zip 包包含不允许的文件类型: {relative_path.as_posix()}')

            destination = (Path(output_dir) / relative_path).resolve()
            base_dir = Path(output_dir).resolve()
            if os.path.commonpath([str(base_dir), str(destination)]) != str(base_dir):
                raise SkinValidationError('zip 包包含路径穿越')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, 'r') as source_file, destination.open('wb') as target_file:
                shutil.copyfileobj(source_file, target_file)


def install_uploaded_skin_file(uploaded_file) -> Dict[str, Any]:
    if not uploaded_file:
        raise SkinValidationError('请选择 zip 皮肤包')
    if request.content_length and request.content_length > SKIN_MAX_ZIP_BYTES:
        raise SkinValidationError('上传文件超过大小限制')

    with tempfile.TemporaryDirectory(prefix='outlook-skin-upload-') as temp_root:
        temp_root_path = Path(temp_root)
        zip_path = temp_root_path / 'skin.zip'
        uploaded_file.save(zip_path)
        validate_skin_file_size(zip_path, SKIN_MAX_ZIP_BYTES, 'zip 皮肤包')
        package_dir = temp_root_path / 'package'
        package_dir.mkdir()
        extract_zip_skin_package(zip_path, package_dir)
        return install_skin_from_directory(package_dir, SKIN_SOURCE_UPLOAD)


def normalize_git_skin_url(value: str) -> str:
    git_url = str(value or '').strip()
    if not git_url:
        raise SkinValidationError('请输入 Git 仓库地址')
    if len(git_url) > 1000 or git_url.startswith('-') or '\n' in git_url or '\r' in git_url:
        raise SkinValidationError('Git 仓库地址无效')
    return git_url


def normalize_git_skin_ref(value: str) -> str:
    git_ref = str(value or '').strip()
    if len(git_ref) > 128 or git_ref.startswith('-') or '\n' in git_ref or '\r' in git_ref:
        raise SkinValidationError('Git ref 无效')
    return git_ref


def install_git_skin_package(git_url: str, git_ref: str = '', expected_skin_id: str = '') -> Dict[str, Any]:
    normalized_url = normalize_git_skin_url(git_url)
    normalized_ref = normalize_git_skin_ref(git_ref)
    if not shutil.which('git'):
        raise SkinValidationError('当前环境未安装 git，无法从仓库安装皮肤')

    with tempfile.TemporaryDirectory(prefix='outlook-skin-git-') as temp_root:
        repo_dir = Path(temp_root) / 'repo'
        command = ['git', 'clone', '--depth', '1']
        if normalized_ref:
            command.extend(['--branch', normalized_ref])
        command.extend([normalized_url, str(repo_dir)])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or 'git clone 失败').strip()
            raise SkinValidationError(f'拉取 Git 皮肤失败: {sanitize_error_details(message)}')

        git_dir = repo_dir / '.git'
        if git_dir.exists():
            shutil.rmtree(git_dir, ignore_errors=True)
        return install_skin_from_directory(
            repo_dir,
            SKIN_SOURCE_GIT,
            source_config={'git_url': normalized_url, 'git_ref': normalized_ref},
            expected_skin_id=expected_skin_id,
        )


def update_git_skin_package(skin_id: str) -> Dict[str, Any]:
    record = get_skin_record_by_id(skin_id)
    if not record or record.get('source_type') != SKIN_SOURCE_GIT:
        raise SkinValidationError('该皮肤不是 Git 来源')
    git_url = str(record.get('git_url') or '').strip()
    git_ref = str(record.get('git_ref') or '').strip()
    if not git_url:
        raise SkinValidationError('该皮肤缺少 Git 来源地址')
    return install_git_skin_package(git_url, git_ref, expected_skin_id=record['id'])


def delete_custom_skin(skin_id: str) -> tuple[bool, str]:
    normalized_id = normalize_skin_id(skin_id)
    if not normalized_id or normalized_id in (SKIN_CLASSIC_ID, 'editorial'):
        return False, f'不能删除内置 {normalized_id} 皮肤'
    if get_configured_active_skin_id() == normalized_id:
        return False, '不能删除当前启用的皮肤，请先切换到其他皮肤'

    record = get_skin_record_by_id(normalized_id)
    skin_dir = get_skin_directory(record or {})
    if not skin_dir or not skin_dir.exists():
        return False, '皮肤不存在'
    shutil.rmtree(skin_dir)
    return True, ''


def get_login_password() -> str:
    """获取登录密码（优先从数据库读取）"""
    password = get_setting('login_password')
    return password if password else LOGIN_PASSWORD


def verify_login_password(password: str) -> bool:
    """校验当前登录密码。"""
    stored_password = get_login_password()
    if is_password_hashed(stored_password):
        return verify_password(password or '', stored_password)
    return secrets.compare_digest(str(password or ''), str(stored_password or ''))


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
