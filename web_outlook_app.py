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
from datetime import datetime
from email.header import decode_header
from typing import Optional, List, Dict, Any
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, Response
from functools import wraps
import requests

app = Flask(__name__)
# 使用固定的 secret_key（从环境变量获取，或使用默认值）
# 这样可以确保重启后 session 不会失效
app.secret_key = os.getenv("SECRET_KEY", "outlook-mail-reader-secret-key-change-in-production")
# 设置 session 过期时间（默认 7 天）
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 7  # 7 天

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

# 临时邮箱分组 ID（系统保留）
TEMP_EMAIL_GROUP_ID = -1

# OAuth 配置
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "24d9a0ed-8787-4584-883c-2fd79308940a")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080")
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read"
]


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
    if 'is_system' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN is_system INTEGER DEFAULT 0')
    
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
    
    # 初始化默认设置
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('login_password', ?)
    ''', (LOGIN_PASSWORD,))

    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('gptmail_api_key', ?)
    ''', (GPTMAIL_API_KEY,))

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

    conn.commit()
    conn.close()


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


# ==================== 分组操作 ====================

def load_groups() -> List[Dict]:
    """加载所有分组（临时邮箱分组排在最前面）"""
    db = get_db()
    # 使用 CASE 语句让临时邮箱分组排在最前面
    cursor = db.execute('''
        SELECT * FROM groups
        ORDER BY
            CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
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


def add_group(name: str, description: str = '', color: str = '#1a1a1a') -> Optional[int]:
    """添加分组"""
    db = get_db()
    try:
        cursor = db.execute('''
            INSERT INTO groups (name, description, color)
            VALUES (?, ?, ?)
        ''', (name, description, color))
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def update_group(group_id: int, name: str, description: str, color: str) -> bool:
    """更新分组"""
    db = get_db()
    try:
        db.execute('''
            UPDATE groups SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (name, description, color, group_id))
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
    return [dict(row) for row in rows]


def get_account_by_email(email_addr: str) -> Optional[Dict]:
    """根据邮箱地址获取账号"""
    db = get_db()
    cursor = db.execute('SELECT * FROM accounts WHERE email = ?', (email_addr,))
    row = cursor.fetchone()
    return dict(row) if row else None


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
    return dict(row) if row else None


def add_account(email_addr: str, password: str, client_id: str, refresh_token: str, 
                group_id: int = 1, remark: str = '') -> bool:
    """添加邮箱账号"""
    db = get_db()
    try:
        db.execute('''
            INSERT INTO accounts (email, password, client_id, refresh_token, group_id, remark)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email_addr, password, client_id, refresh_token, group_id, remark))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_account(account_id: int, email_addr: str, password: str, client_id: str, 
                   refresh_token: str, group_id: int, remark: str, status: str) -> bool:
    """更新邮箱账号"""
    db = get_db()
    try:
        db.execute('''
            UPDATE accounts 
            SET email = ?, password = ?, client_id = ?, refresh_token = ?, 
                group_id = ?, remark = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (email_addr, password, client_id, refresh_token, group_id, remark, status, account_id))
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


def parse_account_string(account_str: str) -> Optional[Dict]:
    """
    解析账号字符串
    格式: email----password----client_id----refresh_token
    """
    parts = account_str.strip().split('----')
    if len(parts) >= 4:
        return {
            'email': parts[0],
            'password': parts[1],
            'client_id': parts[2],
            'refresh_token': parts[3]
        }
    return None


# ==================== Graph API 方式 ====================

def get_access_token_graph_result(client_id: str, refresh_token: str) -> Dict[str, Any]:
    """获取 Graph API access_token（包含错误详情）"""
    try:
        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30
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


def get_access_token_graph(client_id: str, refresh_token: str) -> Optional[str]:
    """获取 Graph API access_token"""
    result = get_access_token_graph_result(client_id, refresh_token)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_graph(client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20) -> Dict[str, Any]:
    """使用 Graph API 获取邮件列表（支持分页和文件夹选择）"""
    token_result = get_access_token_graph_result(client_id, refresh_token)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    try:
        # 根据文件夹类型选择 API 端点
        folder_map = {
            'inbox': 'inbox',
            'junkemail': 'junkemail',
            'deleteditems': 'deleteditems',
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

        res = requests.get(url, headers=headers, params=params, timeout=30)

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


def get_email_detail_graph(client_id: str, refresh_token: str, message_id: str) -> Optional[Dict]:
    """使用 Graph API 获取邮件详情"""
    access_token = get_access_token_graph(client_id, refresh_token)
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
        
        res = requests.get(url, headers=headers, params=params, timeout=30)
        
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
    """使用 IMAP 获取邮件列表（支持分页和文件夹选择）"""
    token_result = get_access_token_imap_result(client_id, refresh_token)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    connection = None
    try:
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        # 根据文件夹类型选择 IMAP 文件夹
        folder_map = {
            'inbox': '"INBOX"',
            'junkemail': '"Junk Email"',
            'deleteditems': '"Deleted Items"',
            'trash': '"Deleted Items"'  # 垃圾箱的别名
        }
        imap_folder = folder_map.get(folder.lower(), '"INBOX"')

        status, _ = connection.select(imap_folder)
        if status != 'OK':
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    "获取邮件失败，请检查账号配置",
                    "IMAPSelectError",
                    500,
                    f"select status={status}"
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


def get_email_detail_imap(account: str, client_id: str, refresh_token: str, message_id: str) -> Optional[Dict]:
    """使用 IMAP 获取邮件详情"""
    access_token = get_access_token_imap(client_id, refresh_token)
    if not access_token:
        return None
    
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)
        connection.select('"INBOX"')
        
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


# ==================== Flask 路由 ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        password = data.get('password', '')
        
        # 从数据库获取密码，如果没有则使用默认密码
        correct_password = get_login_password()
        
        if password == correct_password:
            session['logged_in'] = True
            session.permanent = True
            return jsonify({'success': True, 'message': '登录成功'})
        else:
            return jsonify({'success': False, 'error': '密码错误'})
    
    # GET 请求返回登录页面
    return render_template('login.html')


@app.route('/logout')
def logout():
    """退出登录"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """主页"""
    return render_template('index.html')


# ==================== 分组 API ====================

@app.route('/api/groups', methods=['GET'])
@login_required
def api_get_groups():
    """获取所有分组"""
    groups = load_groups()
    # 添加每个分组的邮箱数量
    for group in groups:
        if group['name'] == '临时邮箱':
            # 临时邮箱分组从 temp_emails 表获取数量
            group['account_count'] = get_temp_email_count()
        else:
            group['account_count'] = get_group_account_count(group['id'])
    return jsonify({'success': True, 'groups': groups})


@app.route('/api/groups/<int:group_id>', methods=['GET'])
@login_required
def api_get_group(group_id):
    """获取单个分组"""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})
    group['account_count'] = get_group_account_count(group_id)
    return jsonify({'success': True, 'group': group})


@app.route('/api/groups', methods=['POST'])
@login_required
def api_add_group():
    """添加分组"""
    data = request.json
    name = data.get('name', '').strip()
    description = data.get('description', '')
    color = data.get('color', '#1a1a1a')
    
    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})
    
    group_id = add_group(name, description, color)
    if group_id:
        return jsonify({'success': True, 'message': '分组创建成功', 'group_id': group_id})
    else:
        return jsonify({'success': False, 'error': '分组名称已存在'})


@app.route('/api/groups/<int:group_id>', methods=['PUT'])
@login_required
def api_update_group(group_id):
    """更新分组"""
    data = request.json
    name = data.get('name', '').strip()
    description = data.get('description', '')
    color = data.get('color', '#1a1a1a')
    
    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})
    
    if update_group(group_id, name, description, color):
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


@app.route('/api/groups/<int:group_id>/export')
@login_required
def api_export_group(group_id):
    """导出分组下的所有邮箱账号为 TXT 文件"""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})
    
    # 获取该分组下的所有账号（完整信息）
    db = get_db()
    cursor = db.execute('''
        SELECT email, password, client_id, refresh_token
        FROM accounts
        WHERE group_id = ?
        ORDER BY created_at DESC
    ''', (group_id,))
    accounts = cursor.fetchall()
    
    if not accounts:
        return jsonify({'success': False, 'error': '该分组下没有邮箱账号'})
    
    # 生成导出内容（格式：email----password----client_id----refresh_token）
    lines = []
    for acc in accounts:
        line = f"{acc['email']}----{acc['password'] or ''}----{acc['client_id']}----{acc['refresh_token']}"
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
    """导出所有邮箱账号为 TXT 文件"""
    # 获取所有账号（完整信息）
    db = get_db()
    cursor = db.execute('''
        SELECT email, password, client_id, refresh_token
        FROM accounts
        ORDER BY created_at DESC
    ''')
    accounts = cursor.fetchall()
    
    if not accounts:
        return jsonify({'success': False, 'error': '没有邮箱账号'})
    
    # 生成导出内容（格式：email----password----client_id----refresh_token）
    lines = []
    for acc in accounts:
        line = f"{acc['email']}----{acc['password'] or ''}----{acc['client_id']}----{acc['refresh_token']}"
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
    """导出选中分组的邮箱账号为 TXT 文件"""
    data = request.json
    group_ids = data.get('group_ids', [])
    
    if not group_ids:
        return jsonify({'success': False, 'error': '请选择要导出的分组'})
    
    # 获取选中分组下的所有账号
    db = get_db()
    placeholders = ','.join(['?' for _ in group_ids])
    cursor = db.execute(f'''
        SELECT email, password, client_id, refresh_token
        FROM accounts
        WHERE group_id IN ({placeholders})
        ORDER BY group_id, created_at DESC
    ''', group_ids)
    accounts = cursor.fetchall()
    
    if not accounts:
        return jsonify({'success': False, 'error': '选中的分组下没有邮箱账号'})
    
    # 生成导出内容
    lines = []
    for acc in accounts:
        line = f"{acc['email']}----{acc['password'] or ''}----{acc['client_id']}----{acc['refresh_token']}"
        lines.append(line)
    
    content = '\n'.join(lines)
    
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
            'updated_at': acc.get('updated_at', '')
        })
    return jsonify({'success': True, 'accounts': safe_accounts})


@app.route('/api/accounts/search', methods=['GET'])
@login_required
def api_search_accounts():
    """全局搜索账号"""
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'success': True, 'accounts': []})

    db = get_db()
    cursor = db.execute('''
        SELECT a.*, g.name as group_name, g.color as group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        WHERE a.email LIKE ?
        ORDER BY a.email
    ''', (f'%{query}%',))

    safe_accounts = []
    for row in cursor.fetchall():
        safe_accounts.append({
            'id': row['id'],
            'email': row['email'],
            'client_id': row['client_id'][:8] + '...' if len(row['client_id']) > 8 else row['client_id'],
            'group_id': row['group_id'],
            'group_name': row['group_name'] if row['group_name'] else '默认分组',
            'group_color': row['group_color'] if row['group_color'] else '#666666',
            'remark': row['remark'] if row['remark'] else '',
            'status': row['status'] if row['status'] else 'active',
            'created_at': row['created_at'] if row['created_at'] else '',
            'updated_at': row['updated_at'] if row['updated_at'] else ''
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
    
    if not account_str:
        return jsonify({'success': False, 'error': '请输入账号信息'})
    
    # 支持批量导入（多行）
    lines = account_str.strip().split('\n')
    added = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parsed = parse_account_string(line)
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
    remark = data.get('remark', '')
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


def test_refresh_token(client_id: str, refresh_token: str) -> tuple[bool, str]:
    """测试 refresh token 是否有效，返回 (是否成功, 错误信息)"""
    try:
        # 尝试使用 Graph API 获取 access token
        # 使用与 get_access_token_graph 相同的 scope，确保一致性
        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30
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
    cursor = db.execute('SELECT id, email, client_id, refresh_token FROM accounts WHERE id = ?', (account_id,))
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
    refresh_token = account['refresh_token']

    # 测试 refresh token
    success, error_msg = test_refresh_token(client_id, refresh_token)

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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token FROM accounts WHERE status = 'active'")
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
                refresh_token = account['refresh_token']

                # 发送当前处理的账号信息
                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                # 测试 refresh token
                success, error_msg = test_refresh_token(client_id, refresh_token)

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
        refresh_token = account['refresh_token']

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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token FROM accounts WHERE status = 'active'")
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
                refresh_token = account['refresh_token']

                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                success, error_msg = test_refresh_token(client_id, refresh_token)

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

    method = request.args.get('method', 'graph')
    folder = request.args.get('folder', 'inbox')  # inbox, junkemail, deleteditems
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))

    graph_error = None
    if method == 'graph':
        # 每次只查询20封邮件
        graph_result = get_emails_graph(account['client_id'], account['refresh_token'], folder, skip, top)
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

        graph_error = graph_result.get("error")

    # 如果 Graph API 失败，尝试 IMAP
    imap_result = get_emails_imap(account['email'], account['client_id'], account['refresh_token'], folder, skip, top)
    if imap_result.get("success"):
        emails = imap_result.get("emails", [])
        # 更新刷新时间
        db = get_db()
        db.execute('''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
        ''', (email_addr,))
        db.commit()

        return jsonify({
            'success': True,
            'emails': emails,
            'method': 'IMAP',
            'has_more': len(emails) >= top
        })

    imap_error = imap_result.get("error")
    combined_details = {}
    if graph_error:
        combined_details["graph"] = graph_error
    if imap_error:
        combined_details["imap"] = imap_error
    details = combined_details or imap_error or graph_error or "未知错误"
    error_payload = build_error_payload(
        "EMAIL_FETCH_FAILED",
        "获取邮件失败，请检查账号配置",
        "EmailFetchError",
        502,
        details
    )
    return jsonify({'success': False, 'error': error_payload})


@app.route('/api/email/<email_addr>/<path:message_id>')
@login_required
def api_get_email_detail(email_addr, message_id):
    """获取邮件详情"""
    account = get_account_by_email(email_addr)
    
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})
    
    method = request.args.get('method', 'graph')
    
    if method == 'graph':
        detail = get_email_detail_graph(account['client_id'], account['refresh_token'], message_id)
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
    detail = get_email_detail_imap(account['email'], account['client_id'], account['refresh_token'], message_id)
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


def add_temp_email(email_addr: str) -> bool:
    """添加临时邮箱"""
    db = get_db()
    try:
        db.execute('INSERT INTO temp_emails (email) VALUES (?)', (email_addr,))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


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


@app.route('/api/temp-emails/generate', methods=['POST'])
@login_required
def api_generate_temp_email():
    """生成新的临时邮箱"""
    data = request.json or {}
    prefix = data.get('prefix')
    domain = data.get('domain')
    
    email_addr = generate_temp_email(prefix, domain)
    
    if email_addr:
        if add_temp_email(email_addr):
            return jsonify({'success': True, 'email': email_addr, 'message': '临时邮箱创建成功'})
        else:
            return jsonify({'success': False, 'error': '邮箱已存在'})
    else:
        return jsonify({'success': False, 'error': '生成临时邮箱失败，请稍后重试'})


@app.route('/api/temp-emails/<path:email_addr>', methods=['DELETE'])
@login_required
def api_delete_temp_email(email_addr):
    """删除临时邮箱"""
    if delete_temp_email(email_addr):
        return jsonify({'success': True, 'message': '临时邮箱已删除'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/temp-emails/<path:email_addr>/messages', methods=['GET'])
@login_required
def api_get_temp_email_messages(email_addr):
    """获取临时邮箱的邮件列表"""
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
    delete_temp_email_from_api(message_id)
    if delete_temp_email_message(message_id):
        return jsonify({'success': True, 'message': '邮件已删除'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/temp-emails/<path:email_addr>/clear', methods=['DELETE'])
@login_required
def api_clear_temp_email_messages(email_addr):
    """清空临时邮箱的所有邮件"""
    clear_temp_emails_from_api(email_addr)
    db = get_db()
    try:
        db.execute('DELETE FROM temp_email_messages WHERE email_address = ?', (email_addr,))
        db.commit()
        return jsonify({'success': True, 'message': '邮件已清空'})
    except Exception:
        return jsonify({'success': False, 'error': '清空失败'})


@app.route('/api/temp-emails/<path:email_addr>/refresh', methods=['POST'])
@login_required
def api_refresh_temp_email_messages(email_addr):
    """刷新临时邮箱的邮件"""
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
            if len(new_password) < 4:
                errors.append('密码长度至少为 4 位')
            elif set_setting('login_password', new_password):
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

    if errors:
        return jsonify({'success': False, 'error': '；'.join(errors)})

    if updated:
        return jsonify({'success': True, 'message': f'已更新：{", ".join(updated)}'})
    else:
        return jsonify({'success': False, 'error': '没有需要更新的设置'})


# ==================== 定时任务调度器 ====================

def init_scheduler():
    """初始化定时任务调度器"""
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
                        print(f"✓ 定时任务已启动：Cron 表达式 '{cron_expr}'")
                        atexit.register(lambda: scheduler.shutdown())
                        return scheduler
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
            print(f"✓ 定时任务已启动：每天凌晨 2:00 检查刷新（周期：{refresh_interval_days} 天）")

        atexit.register(lambda: scheduler.shutdown())

        return scheduler
    except ImportError:
        print("⚠ APScheduler 未安装，定时任务功能不可用")
        print("  安装命令：pip install APScheduler>=3.10.0")
        return None
    except Exception as e:
        print(f"⚠ 定时任务初始化失败：{str(e)}")
        return None


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

        cursor = conn.execute("SELECT id, email, client_id, refresh_token FROM accounts WHERE status = 'active'")
        accounts = cursor.fetchall()

        total = len(accounts)
        success_count = 0
        failed_count = 0

        for index, account in enumerate(accounts, 1):
            account_id = account['id']
            account_email = account['email']
            client_id = account['client_id']
            refresh_token = account['refresh_token']

            success, error_msg = test_refresh_token(client_id, refresh_token)

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

    # 初始化定时任务
    scheduler = init_scheduler()

    app.run(debug=debug, host=host, port=port)