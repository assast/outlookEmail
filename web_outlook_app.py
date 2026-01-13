#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用
基于 Flask 的 Web 界面，支持多邮箱管理和邮件查看
使用 SQLite 数据库存储邮箱信息，支持分组管理
"""

import email
import imaplib
import sqlite3
import os
import hashlib
import secrets
from datetime import datetime
from email.header import decode_header
from typing import Optional, List, Dict, Any
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, Response
from functools import wraps
import requests

app = Flask(__name__)
app.secret_key = os.urandom(24)

# 登录密码配置（可以修改为你想要的密码）
LOGIN_PASSWORD = "admin123"

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
DATABASE = "outlook_accounts.db"


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
    
    # 创建分组表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            color TEXT DEFAULT '#1a1a1a',
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups (id)
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
    
    # 创建默认分组
    cursor.execute('''
        INSERT OR IGNORE INTO groups (name, description, color)
        VALUES ('默认分组', '未分组的邮箱', '#666666')
    ''')
    
    conn.commit()
    conn.close()


# ==================== 分组操作 ====================

def load_groups() -> List[Dict]:
    """加载所有分组"""
    db = get_db()
    cursor = db.execute('SELECT * FROM groups ORDER BY id')
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

def get_access_token_graph(client_id: str, refresh_token: str) -> Optional[str]:
    """获取 Graph API access_token"""
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
            return None
        
        return res.json().get("access_token")
    except Exception:
        return None


def get_emails_graph(client_id: str, refresh_token: str, top: int = 20) -> Optional[List[Dict]]:
    """使用 Graph API 获取邮件列表"""
    access_token = get_access_token_graph(client_id, refresh_token)
    if not access_token:
        return None
    
    try:
        url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        params = {
            "$top": top,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview",
            "$orderby": "receivedDateTime desc"
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": "outlook.body-content-type='text'"
        }
        
        res = requests.get(url, headers=headers, params=params, timeout=30)
        
        if res.status_code != 200:
            return None
        
        return res.json().get("value", [])
    except Exception:
        return None


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

def get_access_token_imap(client_id: str, refresh_token: str) -> Optional[str]:
    """获取 IMAP access_token"""
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
            return None
        
        return res.json().get("access_token")
    except Exception:
        return None


def get_emails_imap(account: str, client_id: str, refresh_token: str, top: int = 20) -> Optional[List[Dict]]:
    """使用 IMAP 获取邮件列表"""
    access_token = get_access_token_imap(client_id, refresh_token)
    if not access_token:
        return None
    
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)
        connection.select('"INBOX"')
        
        status, messages = connection.search(None, 'ALL')
        if status != 'OK' or not messages or not messages[0]:
            return []
        
        message_ids = messages[0].split()
        recent_ids = message_ids[-top:][::-1]
        
        emails = []
        for msg_id in recent_ids:
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
        
        return emails
    except Exception:
        return None
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
        
        if password == LOGIN_PASSWORD:
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
    
    # 返回时隐藏敏感信息
    safe_accounts = []
    for acc in accounts:
        safe_accounts.append({
            'id': acc['id'],
            'email': acc['email'],
            'client_id': acc['client_id'][:8] + '...' if len(acc['client_id']) > 8 else acc['client_id'],
            'group_id': acc.get('group_id'),
            'group_name': acc.get('group_name', '默认分组'),
            'group_color': acc.get('group_color', '#666666'),
            'remark': acc.get('remark', ''),
            'status': acc.get('status', 'active'),
            'created_at': acc.get('created_at', ''),
            'updated_at': acc.get('updated_at', '')
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


# ==================== 邮件 API ====================

@app.route('/api/emails/<email_addr>')
@login_required
def api_get_emails(email_addr):
    """获取邮件列表"""
    account = get_account_by_email(email_addr)
    
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})
    
    method = request.args.get('method', 'graph')
    top = int(request.args.get('top', 20))
    
    if method == 'graph':
        emails = get_emails_graph(account['client_id'], account['refresh_token'], top)
        if emails is not None:
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
            return jsonify({'success': True, 'emails': formatted, 'method': 'Graph API'})
    
    # 如果 Graph API 失败，尝试 IMAP
    emails = get_emails_imap(account['email'], account['client_id'], account['refresh_token'], top)
    if emails is not None:
        return jsonify({'success': True, 'emails': emails, 'method': 'IMAP'})
    
    return jsonify({'success': False, 'error': '获取邮件失败，请检查账号配置'})


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


# ==================== 主程序 ====================

if __name__ == '__main__':
    # 确保 templates 目录存在
    os.makedirs('templates', exist_ok=True)
    
    # 初始化数据库
    init_db()
    
    port = 5001
    print("=" * 60)
    print("Outlook 邮件 Web 应用")
    print("=" * 60)
    print(f"访问地址: http://127.0.0.1:{port}")
    print(f"数据库文件: {DATABASE}")
    print("=" * 60)
    
    app.run(debug=True, host='127.0.0.1', port=port)