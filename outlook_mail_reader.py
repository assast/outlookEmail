#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件读取测试工具
使用三种方式读取 Outlook 邮箱邮件：
1. 旧版 IMAP 方式 (outlook_imap_old_utils)
2. 新版 IMAP 方式 (outlook_imap_new_utils)
3. Graph API 方式 (graph_utils)
"""

import email
import imaplib
from email.header import decode_header
from typing import Optional, List, Dict, Any

import requests

# ==================== 配置参数 ====================
# 邮箱账号
EMAIL = "MollyPennington8418@outlook.com"
# 邮箱密码（通常不需要，OAuth2 认证时使用 refresh_token）
PASSWORD = "hwqennm1840830"
# OAuth2 refresh_token
CLIENT_ID = "dbc8e03a-b00c-46bd-ae65-b683e7707cb0"
# OAuth2 client_id
REFRESH_TOKEN= "M.C559_BAY.0.U.-CkGXiZtXP*c*fcSzidxyNCv1dRjtpWa1kSa6WeTuRQ5jBOMK6PGrs5IjySqXFSyy7YzDOyzx075GTnalJP4P3SQpKvQS4gL4L88ffUZJhiV4gjARF66e8JLRNB8rbhIQ7vX84HsX!psNA5*mh*14vBJ!7u9q7OqjTEXr3Jj!Zr0BF3t6dh6GQhBqx7cA66NAIC6IMgI73radRFmO53m3aUwgK3xGCsua10Ag7um3bfuNH39FpoY8zZfBlPWlXFA6vKWNPl48LNRANxk3sPvM4TQjkc1YFJTxlOI023qHupmA74K4XGH3HsIi!BJe10NkMzxWRVK0myek0LG10*HGYLcqbakcsIpHYPS17os6lVHY97Orayz70KiZ6xxlWFkHkLUV7m3kt9g!ClXi7F0w0r0$"
# 代理地址（可选，格式: host:port 或 http://host:port）
PROXY = None  # 例如: "127.0.0.1:7890"
# ================================================


# Token 端点
TOKEN_URL_LIVE = "https://login.live.com/oauth20_token.srf"
TOKEN_URL_GRAPH = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
TOKEN_URL_IMAP = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

# IMAP 服务器配置
IMAP_SERVER_OLD = "outlook.office365.com"
IMAP_SERVER_NEW = "outlook.live.com"
IMAP_PORT = 993


def print_separator(title: str):
    """打印分隔线"""
    print("\n" + "=" * 80)
    print(f"【{title}】")
    print("=" * 80)


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


def print_email_info(emails: List[Any], method_name: str):
    """打印邮件信息"""
    if not emails:
        print(f"❌ {method_name}: 未获取到邮件")
        return

    print(f"✅ {method_name}: 成功获取 {len(emails)} 封邮件\n")

    for i, msg in enumerate(emails[:5]):  # 只显示前5封
        print(f"  📧 邮件 {i + 1}:")

        # 根据邮件类型获取信息
        if isinstance(msg, dict):
            # Graph API 返回的是字典
            subject = msg.get("subject", "无主题")
            from_info = msg.get("from", {})
            sender = from_info.get("emailAddress", {}).get("address", "未知发件人")
            received_time = msg.get("receivedDateTime", "未知时间")
            print(f"     主题: {subject}")
            print(f"     发件人: {sender}")
            print(f"     时间: {received_time}")
        else:
            # IMAP 返回的是 email.message.EmailMessage
            subject = decode_header_value(msg.get("Subject", "无主题"))
            sender = decode_header_value(msg.get("From", "未知发件人"))
            date = msg.get("Date", "未知时间")
            print(f"     主题: {subject}")
            print(f"     发件人: {sender}")
            print(f"     时间: {date}")
        print()


# ==================== 方式1: 旧版 IMAP 方式 ====================

def get_access_token_old(account: str, client_id: str, refresh_token: str) -> Optional[str]:
    """
    旧版方式获取 access_token
    使用 login.live.com 端点
    """
    print("  🔑 正在获取 access_token (旧版 login.live.com)...")

    try:
        data = {
            'client_id': client_id,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }

        ret = requests.post(TOKEN_URL_LIVE, data=data, timeout=30)

        if ret.status_code != 200:
            print(f"  ❌ 获取 access_token 失败: {ret.status_code}")
            print(f"     响应: {ret.text[:200]}...")
            if "User account is found to be in service abuse mode" in ret.text:
                print("  ⚠️ 账号被封禁!")
            return None

        access_token = ret.json().get('access_token')
        if access_token:
            print(f"  ✅ 成功获取 access_token，长度: {len(access_token)}")
        return access_token

    except Exception as e:
        print(f"  ❌ 获取 access_token 异常: {e}")
        return None


def read_emails_imap_old(account: str, client_id: str, refresh_token: str, top: int = 10) -> Optional[List]:
    """
    方式1: 旧版 IMAP 方式读取邮件
    使用 outlook.office365.com 服务器
    """
    print_separator("方式1: 旧版 IMAP 方式 (outlook.office365.com)")

    # 1. 获取 access_token
    access_token = get_access_token_old(account, client_id, refresh_token)
    if not access_token:
        return None

    # 2. 连接 IMAP 服务器
    connection = None
    try:
        print(f"  📡 正在连接 IMAP 服务器: {IMAP_SERVER_OLD}...")
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_OLD, IMAP_PORT)

        # 3. XOAUTH2 认证
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1"
        connection.authenticate('XOAUTH2', lambda x: auth_string)
        print("  ✅ IMAP 认证成功")

        # 4. 选择收件箱
        connection.select("INBOX")

        # 5. 搜索邮件
        status, messages = connection.search(None, 'ALL')
        if status != 'OK' or not messages or not messages[0]:
            print("  ⚠️ 收件箱为空")
            return []

        message_ids = messages[0].split()
        print(f"  📬 收件箱共有 {len(message_ids)} 封邮件")

        # 6. 获取最近的邮件
        recent_ids = message_ids[-top:][::-1]  # 倒序，最新的在前

        emails = []
        for msg_id in recent_ids:
            try:
                status, msg_data = connection.fetch(msg_id, '(RFC822)')
                if status == 'OK' and msg_data and msg_data[0]:
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    emails.append(msg)
            except Exception as e:
                print(f"  ⚠️ 解析邮件 {msg_id} 失败: {e}")
                continue

        return emails

    except Exception as e:
        print(f"  ❌ IMAP 连接失败: {e}")
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


# ==================== 方式2: 新版 IMAP 方式 ====================

def get_access_token_imap(client_id: str, refresh_token: str) -> Optional[str]:
    """
    新版方式获取 IMAP access_token
    使用 login.microsoftonline.com/consumers 端点，IMAP scope
    """
    print("  🔑 正在获取 access_token (新版 IMAP scope)...")

    try:
        proxies = None
        if PROXY:
            proxies = {"all": f"http://{PROXY}" if not PROXY.startswith("http") else PROXY}

        res = requests.post(
            TOKEN_URL_IMAP,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
            },
            proxies=proxies,
            timeout=30
        )

        if res.status_code != 200:
            print(f"  ❌ 获取 access_token 失败: {res.status_code}")
            print(f"     响应: {res.text[:200]}...")
            if "User account is found to be in service abuse mode" in res.text:
                print("  ⚠️ 账号被封禁!")
            return None

        access_token = res.json().get("access_token")
        if access_token:
            print(f"  ✅ 成功获取 access_token，长度: {len(access_token)}")
        return access_token

    except Exception as e:
        print(f"  ❌ 获取 access_token 异常: {e}")
        return None


def read_emails_imap_new(account: str, client_id: str, refresh_token: str, top: int = 10) -> Optional[List]:
    """
    方式2: 新版 IMAP 方式读取邮件
    使用 outlook.live.com 服务器
    """
    print_separator("方式2: 新版 IMAP 方式 (outlook.live.com)")

    # 1. 获取 access_token
    access_token = get_access_token_imap(client_id, refresh_token)
    if not access_token:
        return None

    # 2. 连接 IMAP 服务器
    connection = None
    try:
        print(f"  📡 正在连接 IMAP 服务器: {IMAP_SERVER_NEW}...")
        connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT)

        # 3. XOAUTH2 认证
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)
        print("  ✅ IMAP 认证成功")

        # 4. 选择收件箱
        connection.select('"INBOX"')

        # 5. 搜索邮件
        status, messages = connection.search(None, 'ALL')
        if status != 'OK' or not messages or not messages[0]:
            print("  ⚠️ 收件箱为空")
            return []

        message_ids = messages[0].split()
        print(f"  📬 收件箱共有 {len(message_ids)} 封邮件")

        # 6. 获取最近的邮件
        recent_ids = message_ids[-top:][::-1]

        emails = []
        for msg_id in recent_ids:
            try:
                status, msg_data = connection.fetch(msg_id, '(RFC822)')
                if status == 'OK' and msg_data and msg_data[0]:
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    emails.append(msg)
            except Exception as e:
                print(f"  ⚠️ 解析邮件 {msg_id} 失败: {e}")
                continue

        return emails

    except Exception as e:
        print(f"  ❌ IMAP 连接失败: {e}")
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


# ==================== 方式3: Graph API 方式 ====================

def get_access_token_graph(client_id: str, refresh_token: str) -> Optional[str]:
    """
    Graph API 方式获取 access_token
    使用 login.microsoftonline.com/common 端点，Graph scope
    """
    print("  🔑 正在获取 access_token (Graph API)...")

    try:
        proxies = None
        if PROXY:
            proxies = {"all": f"http://{PROXY}" if not PROXY.startswith("http") else PROXY}

        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            proxies=proxies,
            timeout=30
        )

        if res.status_code != 200:
            print(f"  ❌ 获取 access_token 失败: {res.status_code}")
            print(f"     响应: {res.text[:200]}...")
            if "User account is found to be in service abuse mode" in res.text:
                print("  ⚠️ 账号被封禁!")
            return None

        access_token = res.json().get("access_token")
        if access_token:
            print(f"  ✅ 成功获取 access_token，长度: {len(access_token)}")
        return access_token

    except Exception as e:
        print(f"  ❌ 获取 access_token 异常: {e}")
        return None


def read_emails_graph(client_id: str, refresh_token: str, top: int = 10) -> Optional[List[Dict]]:
    """
    方式3: Graph API 方式读取邮件
    使用 Microsoft Graph API
    """
    print_separator("方式3: Graph API 方式")

    # 1. 获取 access_token
    access_token = get_access_token_graph(client_id, refresh_token)
    if not access_token:
        return None

    # 2. 调用 Graph API 获取邮件
    try:
        proxies = None
        if PROXY:
            proxies = {"http": f"http://{PROXY}", "https": f"http://{PROXY}"}

        print("  📡 正在调用 Graph API...")

        url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        params = {
            "$top": top,
            "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview",
            "$orderby": "receivedDateTime desc",
            "$count": "true"
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": "outlook.body-content-type='text'"
        }

        res = requests.get(url, headers=headers, params=params, proxies=proxies, timeout=30)

        if res.status_code != 200:
            print(f"  ❌ Graph API 调用失败: {res.status_code}")
            print(f"     响应: {res.text[:200]}...")
            return None

        data = res.json()
        messages = data.get("value", [])
        total = data.get("@odata.count", len(messages))
        print(f"  📬 收件箱共有 {total} 封邮件")

        return messages

    except Exception as e:
        print(f"  ❌ Graph API 调用异常: {e}")
        return None


# ==================== 主函数 ====================

def main():
    """主函数：使用三种方式读取邮件"""
    print("\n" + "🚀 Outlook 邮件读取测试工具")
    print("=" * 80)
    print(f"邮箱: {EMAIL}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Refresh Token: {REFRESH_TOKEN[:30]}..." if REFRESH_TOKEN else "未设置")
    print(f"代理: {PROXY if PROXY else '无'}")
    print("=" * 80)

    # 检查配置
    if EMAIL == "" or REFRESH_TOKEN == "":
        print("\n⚠️ 请先配置邮箱信息！")
        print("   修改脚本顶部的 EMAIL, REFRESH_TOKEN, CLIENT_ID 变量")
        return

    results = {}

    # 方式1: 旧版 IMAP
    try:
        emails_old = read_emails_imap_old(EMAIL, CLIENT_ID, REFRESH_TOKEN, top=10)
        print_email_info(emails_old, "旧版 IMAP")
        results["旧版 IMAP"] = "✅ 成功" if emails_old else "❌ 失败"
    except Exception as e:
        print(f"❌ 旧版 IMAP 异常: {e}")
        results["旧版 IMAP"] = f"❌ 异常: {e}"

    # 方式2: 新版 IMAP
    try:
        emails_new = read_emails_imap_new(EMAIL, CLIENT_ID, REFRESH_TOKEN, top=10)
        print_email_info(emails_new, "新版 IMAP")
        results["新版 IMAP"] = "✅ 成功" if emails_new else "❌ 失败"
    except Exception as e:
        print(f"❌ 新版 IMAP 异常: {e}")
        results["新版 IMAP"] = f"❌ 异常: {e}"

    # 方式3: Graph API
    try:
        emails_graph = read_emails_graph(CLIENT_ID, REFRESH_TOKEN, top=10)
        print_email_info(emails_graph, "Graph API")
        results["Graph API"] = "✅ 成功" if emails_graph else "❌ 失败"
    except Exception as e:
        print(f"❌ Graph API 异常: {e}")
        results["Graph API"] = f"❌ 异常: {e}"

    # 打印汇总
    print_separator("测试结果汇总")
    for method, result in results.items():
        print(f"  {method}: {result}")

    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()