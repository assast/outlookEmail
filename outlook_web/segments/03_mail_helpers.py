from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # These segmented files are executed into the shared `web_outlook_app`
    # globals at runtime. Importing from the assembled module keeps IDE
    # inspections from flagging the shared names as unresolved.
    from web_outlook_app import *  # noqa: F403


def build_proxies(proxy_url: str) -> Optional[Dict[str, str]]:
    """构建 requests 的 proxies 参数"""
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def build_direct_proxies() -> Dict[str, None]:
    """显式禁用 requests 的环境代理，确保走直连"""
    return {"http": None, "https": None, "all": None}


DIRECT_PROXY_SENTINEL = "__DIRECT__"


def normalize_proxy_candidate(proxy_value: Any) -> str:
    value = str(proxy_value or '').strip()
    if not value:
        return ''
    if value.lower() == 'direct' or value == '直连':
        return DIRECT_PROXY_SENTINEL
    return value


def get_proxy_failover_candidates(primary_proxy_url: str = '',
                                  fallback_proxy_urls: Optional[List[str]] = None) -> List[tuple[str, str]]:
    primary = normalize_proxy_candidate(primary_proxy_url)
    if not primary:
        return []

    candidates: List[tuple[str, str]] = [('primary', primary)]
    seen = {primary}

    for index, raw_candidate in enumerate(fallback_proxy_urls or [], start=1):
        candidate = normalize_proxy_candidate(raw_candidate)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append((f'fallback{index}', candidate))

    return candidates


def is_proxy_connection_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.ProxyError):
        return True
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    if not isinstance(exc, requests.exceptions.ConnectionError):
        return False
    message = str(exc).lower()
    return any(marker in message for marker in (
        'socks',
        'proxy',
        'tunnel connection failed',
        'connection refused',
        'host unreachable',
    ))


def should_retry_next_proxy(exc: Exception, proxy_candidate: str) -> bool:
    if proxy_candidate == DIRECT_PROXY_SENTINEL:
        return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    return is_proxy_connection_error(exc)


def build_request_kwargs_for_proxy(kwargs: Dict[str, Any], proxy_candidate: str) -> Dict[str, Any]:
    request_kwargs = dict(kwargs)
    if proxy_candidate == DIRECT_PROXY_SENTINEL:
        request_kwargs['proxies'] = build_direct_proxies()
        return request_kwargs

    proxies = build_proxies(proxy_candidate)
    if proxies:
        request_kwargs['proxies'] = proxies
    return request_kwargs


def request_with_proxy_failover(method: str, url: str, *, proxy_url: str = None,
                                fallback_proxy_urls: Optional[List[str]] = None, **kwargs):
    candidates = get_proxy_failover_candidates(proxy_url or '', fallback_proxy_urls)
    if not candidates:
        return requests.request(method, url, **kwargs)

    last_exc = None
    for index, (label, candidate) in enumerate(candidates):
        request_kwargs = build_request_kwargs_for_proxy(kwargs, candidate)
        try:
            response = requests.request(method, url, **request_kwargs)
            if index > 0:
                app.logger.warning(
                    "Proxy candidate %s succeeded for %s %s after previous failures",
                    label,
                    method.upper(),
                    url,
                )
            return response
        except Exception as exc:
            last_exc = exc
            if index == len(candidates) - 1 or not should_retry_next_proxy(exc, candidate):
                raise
            app.logger.warning(
                "Proxy candidate %s failed for %s %s: %s",
                label,
                method.upper(),
                url,
                sanitize_error_details(str(exc)),
            )

    if last_exc:
        raise last_exc
    raise RuntimeError(f"请求失败: {method.upper()} {url}")


def post_with_proxy_fallback(url: str, *, proxy_url: str = None,
                             fallback_proxy_urls: Optional[List[str]] = None, **kwargs):
    return request_with_proxy_failover(
        'post',
        url,
        proxy_url=proxy_url,
        fallback_proxy_urls=fallback_proxy_urls,
        **kwargs
    )


def get_with_proxy_fallback(url: str, *, proxy_url: str = None,
                            fallback_proxy_urls: Optional[List[str]] = None, **kwargs):
    return request_with_proxy_failover(
        'get',
        url,
        proxy_url=proxy_url,
        fallback_proxy_urls=fallback_proxy_urls,
        **kwargs
    )


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


def get_access_token_graph_result(client_id: str, refresh_token: str, proxy_url: str = None,
                                  fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """获取 Graph API access_token（包含错误详情）"""
    try:
        res = post_with_proxy_fallback(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
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


def get_access_token_graph(client_id: str, refresh_token: str, proxy_url: str = None,
                           fallback_proxy_urls: Optional[List[str]] = None) -> Optional[str]:
    """获取 Graph API access_token"""
    result = get_access_token_graph_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_graph(client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0,
                     top: int = 20, proxy_url: str = None,
                     fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 Graph API 获取邮件列表（支持分页和文件夹选择）"""
    token_result = get_access_token_graph_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
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
            "$select": "id,subject,from,toRecipients,receivedDateTime,isRead,hasAttachments,bodyPreview",
            "$orderby": "receivedDateTime desc"
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Prefer": "outlook.body-content-type='text'"
        }

        res = get_with_proxy_fallback(
            url,
            headers=headers,
            params=params,
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
        )

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


def get_raw_email_graph(client_id: str, refresh_token: str, message_id: str, proxy_url: str = None,
                        fallback_proxy_urls: Optional[List[str]] = None) -> Optional[bytes]:
    """使用 Graph API 获取原始 MIME 邮件源码。"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return None

    try:
        url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/$value"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        res = get_with_proxy_fallback(
            url,
            headers=headers,
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
        )
        if res.status_code != 200:
            return None
        return res.content
    except Exception:
        return None


def get_email_detail_graph(client_id: str, refresh_token: str, message_id: str, proxy_url: str = None,
                           fallback_proxy_urls: Optional[List[str]] = None) -> Optional[Dict]:
    """使用 Graph API 获取邮件详情"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url, fallback_proxy_urls)
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
        
        res = get_with_proxy_fallback(
            url,
            headers=headers,
            params=params,
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
        )
        
        if res.status_code != 200:
            return None
        
        return res.json()
    except Exception:
        return None


def mark_emails_read_graph_result(client_id: str, refresh_token: str, message_ids: List[str],
                                  proxy_url: str = None,
                                  fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 Graph API 批量标记邮件为已读"""
    normalized_ids = [str(message_id or '').strip() for message_id in (message_ids or []) if str(message_id or '').strip()]
    if not normalized_ids:
        return {
            'success': False,
            'success_count': 0,
            'failed_count': 0,
            'updated_ids': [],
            'errors': ['message_ids 不能为空'],
        }

    token_result = get_access_token_graph_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not token_result.get('success'):
        return {
            'success': False,
            'success_count': 0,
            'failed_count': len(normalized_ids),
            'updated_ids': [],
            'errors': [token_result.get('error')],
        }

    access_token = token_result.get('access_token')
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    batch_size = 20
    updated_ids: List[str] = []
    errors: List[Any] = []

    for index in range(0, len(normalized_ids), batch_size):
        batch = normalized_ids[index:index + batch_size]
        batch_requests = []
        for batch_index, message_id in enumerate(batch):
            batch_requests.append({
                'id': str(batch_index),
                'method': 'PATCH',
                'url': f'/me/messages/{message_id}',
                'headers': {
                    'Content-Type': 'application/json',
                },
                'body': {
                    'isRead': True,
                },
            })

        try:
            response = request_with_proxy_failover(
                'post',
                'https://graph.microsoft.com/v1.0/$batch',
                headers=headers,
                json={'requests': batch_requests},
                timeout=HTTP_REQUEST_TIMEOUT,
                proxy_url=proxy_url,
                fallback_proxy_urls=fallback_proxy_urls,
            )
        except Exception as exc:
            errors.extend({
                'id': message_id,
                'error': build_error_payload(
                    'EMAIL_MARK_READ_FAILED',
                    '标记邮件已读失败',
                    type(exc).__name__,
                    500,
                    str(exc)
                )
            } for message_id in batch)
            continue

        if response.status_code != 200:
            error_payload = build_error_payload(
                'EMAIL_MARK_READ_FAILED',
                '标记邮件已读失败',
                'GraphAPIError',
                response.status_code,
                get_response_details(response)
            )
            errors.extend({'id': message_id, 'error': error_payload} for message_id in batch)
            continue

        response_items = response.json().get('responses', [])
        response_map = {str(item.get('id')): item for item in response_items}

        for batch_index, message_id in enumerate(batch):
            item = response_map.get(str(batch_index))
            status_code = int(item.get('status', 0) or 0) if item else 0
            if status_code in {200, 202, 204}:
                updated_ids.append(message_id)
                continue

            error_body = item.get('body') if item else ''
            errors.append({
                'id': message_id,
                'error': build_error_payload(
                    'EMAIL_MARK_READ_FAILED',
                    '标记邮件已读失败',
                    'GraphAPIError',
                    status_code or 500,
                    error_body or '批处理返回空响应'
                )
            })

    success_count = len(updated_ids)
    failed_count = len(normalized_ids) - success_count
    return {
        'success': failed_count == 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'updated_ids': updated_ids,
        'errors': errors,
    }


def get_email_attachments_graph(client_id: str, refresh_token: str, message_id: str, proxy_url: str = None,
                                fallback_proxy_urls: Optional[List[str]] = None) -> Optional[List[Dict[str, Any]]]:
    """使用 Graph API 获取邮件附件列表"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return None

    try:
        url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        params = {
            "$select": "id,name,contentType,size,isInline,contentId"
        }

        res = get_with_proxy_fallback(
            url,
            headers=headers,
            params=params,
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
        )

        if res.status_code != 200:
            return None

        attachments = []
        for index, item in enumerate(res.json().get("value", []), start=1):
            attachments.append({
                "id": item.get("id", ""),
                "name": sanitize_attachment_filename(item.get("name", ""), f"attachment-{index}"),
                "content_type": item.get("contentType", "application/octet-stream") or "application/octet-stream",
                "size": int(item.get("size", 0) or 0),
                "is_inline": bool(item.get("isInline", False)),
                "content_id": str(item.get("contentId", "") or "").strip("<>"),
            })

        return attachments
    except Exception:
        return None


def download_email_attachment_graph_result(client_id: str, refresh_token: str, message_id: str, attachment_id: str,
                                           proxy_url: str = None,
                                           fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 Graph API 下载邮件附件"""
    token_result = get_access_token_graph_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        metadata_url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments/{attachment_id}"
        metadata_res = get_with_proxy_fallback(
            metadata_url,
            headers=headers,
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
        )
        if metadata_res.status_code != 200:
            return {
                "success": False,
                "error": build_error_payload(
                    "ATTACHMENT_FETCH_FAILED",
                    "获取附件失败",
                    "GraphAPIError",
                    metadata_res.status_code,
                    get_response_details(metadata_res)
                )
            }

        metadata = metadata_res.json()
        raw_content = metadata.get("contentBytes")
        if raw_content:
            try:
                content = base64.b64decode(raw_content)
            except Exception as exc:
                return {
                    "success": False,
                    "error": build_error_payload(
                        "ATTACHMENT_DECODE_FAILED",
                        "解析附件内容失败",
                        type(exc).__name__,
                        500,
                        str(exc)
                    )
                }
        else:
            content_url = f"{metadata_url}/$value"
            content_res = get_with_proxy_fallback(
                content_url,
                headers=headers,
                timeout=HTTP_REQUEST_TIMEOUT,
                proxy_url=proxy_url,
                fallback_proxy_urls=fallback_proxy_urls,
            )
            if content_res.status_code != 200:
                return {
                    "success": False,
                    "error": build_error_payload(
                        "ATTACHMENT_FETCH_FAILED",
                        "获取附件失败",
                        "GraphAPIError",
                        content_res.status_code,
                        get_response_details(content_res)
                    )
                }
            content = content_res.content

        return {
            "success": True,
            "filename": sanitize_attachment_filename(metadata.get("name", ""), "attachment"),
            "content_type": metadata.get("contentType", "application/octet-stream") or "application/octet-stream",
            "content": content,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "ATTACHMENT_FETCH_FAILED",
                "获取附件失败",
                type(exc).__name__,
                500,
                str(exc)
            )
        }


# ==================== IMAP 方式 ====================

def get_access_token_imap_result(client_id: str, refresh_token: str, proxy_url: str = None,
                                 fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """获取 IMAP access_token（包含错误详情）"""
    try:
        res = post_with_proxy_fallback(
            TOKEN_URL_IMAP,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
            },
            timeout=HTTP_REQUEST_TIMEOUT,
            proxy_url=proxy_url,
            fallback_proxy_urls=fallback_proxy_urls,
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


def get_access_token_imap(client_id: str, refresh_token: str, proxy_url: str = None,
                          fallback_proxy_urls: Optional[List[str]] = None) -> Optional[str]:
    """获取 IMAP access_token"""
    result = get_access_token_imap_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_imap(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0,
                    top: int = 20, proxy_url: str = None,
                    fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页和文件夹选择）- 默认使用新版服务器"""
    return get_emails_imap_with_server(
        account,
        client_id,
        refresh_token,
        folder,
        skip,
        top,
        IMAP_SERVER_NEW,
        proxy_url,
        fallback_proxy_urls,
    )


def get_emails_imap_with_server(account: str, client_id: str, refresh_token: str, folder: str = 'inbox', skip: int = 0, top: int = 20, server: str = IMAP_SERVER_NEW, proxy_url: str = None) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页、文件夹选择和服务器选择）"""
def get_emails_imap_with_server(account: str, client_id: str, refresh_token: str, folder: str = 'inbox',
                                skip: int = 0, top: int = 20, server: str = IMAP_SERVER_NEW,
                                proxy_url: str = None,
                                fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页、文件夹选择和服务器选择）"""
    token_result = get_access_token_imap_result(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(server, IMAP_PORT, timeout=IMAP_TIMEOUT)
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
                status, msg_data = connection.fetch(msg_id, '(INTERNALDATE RFC822)')
                if status == 'OK' and msg_data and msg_data[0]:
                    raw_email = msg_data[0][1]
                    internal_date = extract_imap_internaldate(msg_data[0][0])
                    msg = email.message_from_bytes(raw_email)
                    body_preview = get_email_body(msg)

                    emails.append({
                        'id': msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        'subject': decode_header_value(msg.get("Subject", "无主题")),
                        'from': decode_header_value(msg.get("From", "未知发件人")),
                        'to': decode_header_value(msg.get("To", "")),
                        'date': internal_date or msg.get("Date", "未知时间"),
                        'id_mode': 'sequence',
                        'body_preview': body_preview[:200] + "..." if len(body_preview) > 200 else body_preview
                    })
            except Exception:
                continue

        emails.sort(key=lambda item: parse_email_datetime(item.get('date')) or datetime.min, reverse=True)
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


def get_raw_email_imap(account: str, client_id: str, refresh_token: str, message_id: str,
                       folder: str = 'inbox', proxy_url: str = None,
                       fallback_proxy_urls: Optional[List[str]] = None) -> Optional[bytes]:
    """使用 Outlook IMAP 获取原始 MIME 邮件源码。"""
    access_token = get_access_token_imap(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return None

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT, timeout=IMAP_TIMEOUT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        selected_folder, _ = resolve_imap_folder(connection, 'outlook', folder, readonly=True)
        if not selected_folder:
            return None

        status, msg_data = connection.fetch(message_id.encode() if isinstance(message_id, str) else message_id, '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            return None
        return msg_data[0][1]
    except Exception:
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def get_email_detail_imap(account: str, client_id: str, refresh_token: str, message_id: str,
                          folder: str = 'inbox', proxy_url: str = None,
                          fallback_proxy_urls: Optional[List[str]] = None) -> Optional[Dict]:
    """使用 IMAP 获取邮件详情"""
    access_token = get_access_token_imap(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return None

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT, timeout=IMAP_TIMEOUT)
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
        return build_email_detail_from_message(msg, str(message_id))
    except Exception:
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


# ==================== 登录验证 ====================

def extract_imap_internaldate(fetch_metadata: Any) -> str:
    if isinstance(fetch_metadata, (bytes, bytearray)):
        metadata_text = fetch_metadata.decode('utf-8', errors='ignore')
    else:
        metadata_text = str(fetch_metadata or '')

    match = re.search(r'INTERNALDATE "([^"]+)"', metadata_text)
    if not match:
        return ''
    return match.group(1).strip()


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


def sanitize_attachment_filename(filename: str, fallback: str = 'attachment') -> str:
    decoded = decode_header_value(filename or '').strip()
    if not decoded:
        return fallback

    cleaned = re.sub(r'[\r\n]+', ' ', decoded).strip()
    cleaned = cleaned.replace('/', '_').replace('\\', '_')
    return cleaned or fallback


def extract_message_attachments(msg, include_content: bool = False) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    attachment_number = 0

    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = str(part.get('Content-Disposition', '') or '').lower()
        filename = part.get_filename()
        has_filename = bool(filename)
        is_attachment = 'attachment' in disposition
        is_inline = 'inline' in disposition

        if not (is_attachment or is_inline or has_filename):
            continue

        attachment_number += 1
        payload = part.get_payload(decode=True) or b''
        item = {
            'id': f'attachment-{attachment_number}',
            'name': sanitize_attachment_filename(filename or '', f'attachment-{attachment_number}'),
            'content_type': (part.get_content_type() or 'application/octet-stream').lower(),
            'size': len(payload),
            'is_inline': bool(is_inline and not is_attachment),
            'content_id': str(part.get('Content-ID', '') or '').strip('<>'),
        }
        if include_content:
            item['content'] = payload
        attachments.append(item)

    return attachments


def get_message_attachment_by_id(msg, attachment_id: str) -> Optional[Dict[str, Any]]:
    for attachment in extract_message_attachments(msg, include_content=True):
        if attachment.get('id') == attachment_id:
            return attachment
    return None


def get_raw_email_imap_generic(email_addr: str, imap_password: str, imap_host: str,
                               imap_port: int, message_id: str, folder: str = 'inbox',
                               provider: str = 'custom', proxy_url: str = '') -> Optional[bytes]:
    """使用通用 IMAP 获取原始 MIME 邮件源码。"""
    if not message_id:
        return None

    connection = None
    try:
        connection = create_imap_connection(imap_host, imap_port, proxy_url)
        connection.login(email_addr, imap_password)
        selected_folder, search_mode = resolve_imap_folder(connection, provider, folder, readonly=True)
        if not selected_folder:
            return None

        status, msg_data = fetch_imap_message_by_id(
            connection,
            str(message_id),
            '(RFC822)',
            preferred_mode='uid' if search_mode == 'uid' else (search_mode or 'uid')
        )
        if status != 'OK' or not msg_data or not msg_data[0]:
            return None
        return msg_data[0][1]
    except Exception:
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def build_email_detail_from_message(msg, message_id: str, date_value: str = '') -> Dict[str, Any]:
    body_text, body_html = extract_text_and_html(msg)
    return {
        'id': str(message_id),
        'subject': decode_header_value(msg.get('Subject', '无主题')),
        'from': decode_header_value(msg.get('From', '未知发件人')),
        'to': decode_header_value(msg.get('To', '')),
        'cc': decode_header_value(msg.get('Cc', '')),
        'date': date_value or msg.get('Date', ''),
        'body': body_html or body_text,
        'body_type': 'html' if body_html else 'text',
        'attachments': extract_message_attachments(msg),
    }


def has_message_attachments(msg) -> bool:
    return len(extract_message_attachments(msg)) > 0


def create_imap_connection(imap_host: str, imap_port: int = 993, proxy_url: str = ''):
    host = (imap_host or '').strip()
    port = int(imap_port or 993)
    if not host:
        raise ValueError('IMAP host 不能为空')
    try:
        with proxy_socket_context(proxy_url):
            return imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT)
    except TypeError:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(IMAP_TIMEOUT)
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


def extract_imap_exists_count(select_response: Any) -> int:
    if isinstance(select_response, (list, tuple)):
        for item in select_response:
            if isinstance(item, (bytes, bytearray)):
                text = item.decode('utf-8', errors='ignore').strip()
            else:
                text = str(item or '').strip()
            if text.isdigit():
                try:
                    return int(text)
                except ValueError:
                    continue
    text = str(select_response or '')
    match = re.search(r"\b(\d+)\b", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


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


def search_imap_message_ids(mail) -> tuple[Optional[List[bytes]], str, List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []

    try:
        status, data = mail.uid('SEARCH', None, 'ALL')
        attempts.append({
            'mode': 'uid',
            'status': str(status),
            'response': sanitize_error_details(str(data or ''))[:200],
        })
        if status == 'OK':
            payload = data[0] if data else b''
            return payload.split() if payload else [], 'uid', attempts
    except Exception as exc:
        attempts.append({
            'mode': 'uid',
            'status': type(exc).__name__,
            'response': sanitize_error_details(str(exc))[:200],
        })

    try:
        status, data = mail.search(None, 'ALL')
        attempts.append({
            'mode': 'sequence',
            'status': str(status),
            'response': sanitize_error_details(str(data or ''))[:200],
        })
        if status == 'OK':
            payload = data[0] if data else b''
            return payload.split() if payload else [], 'sequence', attempts
    except Exception as exc:
        attempts.append({
            'mode': 'sequence',
            'status': type(exc).__name__,
            'response': sanitize_error_details(str(exc))[:200],
        })

    return None, '', attempts


def build_sequence_message_ids(total_messages: int) -> List[bytes]:
    if total_messages <= 0:
        return []
    return [str(index).encode('utf-8') for index in range(1, total_messages + 1)]


def has_imap_fetch_payload(data: Any) -> bool:
    if not data:
        return False

    items = data if isinstance(data, (list, tuple)) else [data]
    for item in items:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        payload = item[1]
        if payload is None:
            continue
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        if isinstance(payload, (bytes, bytearray)):
            if payload:
                return True
            continue
        if str(payload):
            return True
    return False


def parse_imap_fetch_response(data: Any) -> tuple[bytes | None, str]:
    raw_email = None
    response_fragments: List[str] = []
    items = data if isinstance(data, (list, tuple)) else [data]

    for item in items:
        if item is None:
            continue

        if isinstance(item, tuple):
            tuple_items = list(item)
            if tuple_items:
                head = tuple_items[0]
                if isinstance(head, memoryview):
                    head = head.tobytes()
                if isinstance(head, (bytes, bytearray)):
                    response_fragments.append(head.decode('utf-8', errors='ignore'))
                elif head is not None:
                    response_fragments.append(str(head))

            for payload in tuple_items[1:]:
                if isinstance(payload, memoryview):
                    payload = payload.tobytes()
                if raw_email is None and isinstance(payload, (bytes, bytearray)) and payload:
                    raw_email = bytes(payload)
                    continue
                if isinstance(payload, (bytes, bytearray)):
                    response_fragments.append(payload.decode('utf-8', errors='ignore'))
                elif payload is not None:
                    response_fragments.append(str(payload))
            continue

        if isinstance(item, memoryview):
            item = item.tobytes()
        if isinstance(item, (bytes, bytearray)):
            response_fragments.append(item.decode('utf-8', errors='ignore'))
        else:
            response_fragments.append(str(item))

    return raw_email, ' '.join(fragment for fragment in response_fragments if fragment).strip()


def fetch_imap_message(mail, message_id: Any, query: str, preferred_mode: str = 'uid') -> tuple[str, Any, str, List[Dict[str, Any]]]:
    message_text = message_id.decode('utf-8', errors='ignore') if isinstance(message_id, (bytes, bytearray)) else str(message_id)
    modes = [preferred_mode]
    if preferred_mode != 'uid':
        modes.append('uid')
    if preferred_mode != 'sequence':
        modes.append('sequence')

    attempts: List[Dict[str, Any]] = []
    for mode in modes:
        try:
            if mode == 'uid':
                status, data = mail.uid('FETCH', message_id, query)
            else:
                status, data = mail.fetch(message_text, query)
            payload_present = has_imap_fetch_payload(data)
            attempts.append({
                'mode': mode,
                'status': str(status),
                'response': sanitize_error_details(str(data or ''))[:200],
                'payload_present': payload_present,
            })
            if status == 'OK' and payload_present:
                return status, data, mode, attempts
        except Exception as exc:
            attempts.append({
                'mode': mode,
                'status': type(exc).__name__,
                'response': sanitize_error_details(str(exc))[:200],
            })
    return 'NO', None, '', attempts


def store_imap_message_flags(mail, message_id: Any, action: str = '+FLAGS.SILENT',
                             flags: str = r'(\Seen)',
                             preferred_mode: str = 'uid') -> tuple[bool, str, List[Dict[str, Any]]]:
    message_text = message_id.decode('utf-8', errors='ignore') if isinstance(message_id, (bytes, bytearray)) else str(message_id)
    modes = [preferred_mode]
    if preferred_mode != 'uid':
        modes.append('uid')
    if preferred_mode != 'sequence':
        modes.append('sequence')

    attempts: List[Dict[str, Any]] = []
    for mode in modes:
        try:
            if mode == 'uid':
                status, data = mail.uid('STORE', message_id, action, flags)
            else:
                status, data = mail.store(message_text, action, flags)
            attempts.append({
                'mode': mode,
                'status': str(status),
                'response': sanitize_error_details(str(data or ''))[:200],
            })
            if status == 'OK':
                return True, mode, attempts
        except Exception as exc:
            attempts.append({
                'mode': mode,
                'status': type(exc).__name__,
                'response': sanitize_error_details(str(exc))[:200],
            })
    return False, '', attempts


def mark_email_items_seen_imap(mail, items: List[Dict[str, Any]], provider: str,
                               default_mode: str = 'uid') -> Dict[str, Any]:
    success_count = 0
    updated_ids: List[str] = []
    errors: List[Any] = []
    grouped_items: Dict[str, List[Dict[str, Any]]] = {}

    for item in items or []:
        message_id = str(item.get('id', '') or '').strip()
        folder = str(item.get('folder', 'inbox') or 'inbox').strip().lower()
        if not message_id:
            errors.append({
                'id': '',
                'error': build_error_payload(
                    'EMAIL_MARK_READ_INVALID',
                    'message_id 不能为空',
                    'ValidationError',
                    400,
                    item
                )
            })
            continue
        grouped_items.setdefault(folder, []).append({
            'id': message_id,
            'folder': folder,
            'id_mode': str(item.get('id_mode', '') or '').strip().lower(),
        })

    for folder, folder_items in grouped_items.items():
        selected_folder, folder_diagnostics = resolve_imap_folder(mail, provider, folder, readonly=False)
        if not selected_folder:
            folder_error = build_error_payload(
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
            errors.extend({'id': item['id'], 'error': folder_error} for item in folder_items)
            continue

        for item in folder_items:
            preferred_mode = item.get('id_mode') or default_mode
            success, used_mode, attempts = store_imap_message_flags(
                mail,
                item['id'],
                preferred_mode=preferred_mode
            )
            if success:
                success_count += 1
                updated_ids.append(item['id'])
                item['id_mode'] = used_mode
                continue

            errors.append({
                'id': item['id'],
                'error': build_error_payload(
                    'EMAIL_MARK_READ_FAILED',
                    '标记邮件已读失败',
                    'IMAPStoreError',
                    502,
                    {
                        'provider': provider,
                        'folder': selected_folder,
                        'message_id': item['id'],
                        'store_attempts': attempts[:10],
                    }
                )
            })

    total_count = sum(len(group) for group in grouped_items.values())
    failed_count = total_count - success_count + sum(1 for item in errors if not item.get('id'))
    return {
        'success': failed_count == 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'updated_ids': updated_ids,
        'errors': errors,
    }


def mark_emails_read_imap_batch(email_addr: str, client_id: str, refresh_token: str,
                                items: List[Dict[str, Any]], server: str = IMAP_SERVER_NEW,
                                proxy_url: str = None,
                                fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    access_token = get_access_token_imap(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return {
            'success': False,
            'success_count': 0,
            'failed_count': len(items or []),
            'updated_ids': [],
            'errors': [build_error_payload('IMAP_TOKEN_FAILED', '获取访问令牌失败', 'IMAPError', 401, '')],
        }

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(server, IMAP_PORT, timeout=IMAP_TIMEOUT)
        auth_string = f"user={email_addr}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)
        return mark_email_items_seen_imap(connection, items, 'outlook', default_mode='sequence')
    except Exception as exc:
        return {
            'success': False,
            'success_count': 0,
            'failed_count': len(items or []),
            'updated_ids': [],
            'errors': [build_error_payload('IMAP_CONNECT_FAILED', 'IMAP 连接失败', type(exc).__name__, 502, str(exc))],
        }
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def mark_emails_read_imap_generic_result(email_addr: str, imap_password: str, imap_host: str,
                                         items: List[Dict[str, Any]], imap_port: int = 993,
                                         provider: str = 'custom', proxy_url: str = '') -> Dict[str, Any]:
    mail = None
    try:
        mail = create_imap_connection(imap_host, imap_port, proxy_url)
        try:
            mail.login(email_addr, imap_password)
        except imaplib.IMAP4.error as exc:
            return {
                'success': False,
                'success_count': 0,
                'failed_count': len(items or []),
                'updated_ids': [],
                'errors': [build_error_payload(
                    'IMAP_AUTH_FAILED',
                    normalize_imap_auth_error(provider, imap_host, str(exc)),
                    'IMAPAuthError',
                    401,
                    ''
                )],
            }

        send_imap_id(mail, provider, imap_host)
        return mark_email_items_seen_imap(mail, items, provider, default_mode='uid')
    except Exception as exc:
        return {
            'success': False,
            'success_count': 0,
            'failed_count': len(items or []),
            'updated_ids': [],
            'errors': [build_error_payload('IMAP_CONNECT_FAILED', sanitize_error_details(str(exc)) or 'IMAP 连接失败', 'IMAPConnectError', 502, '')],
        }
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


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

        selected_exists = 0
        for attempt in reversed(folder_diagnostics.get('select_attempts') or []):
            if str(attempt.get('status') or '') == 'OK':
                selected_exists = extract_imap_exists_count(attempt.get('response'))
                if selected_exists > 0:
                    break

        message_ids, search_mode, search_attempts = search_imap_message_ids(mail)
        if message_ids is None:
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_SEARCH_FAILED',
                    'IMAP 搜索邮件失败',
                    'IMAPSearchError',
                    502,
                    {'attempts': search_attempts[:10]}
                ),
                'error_code': 'IMAP_SEARCH_FAILED'
            }

        if not message_ids and selected_exists > 0:
            message_ids = build_sequence_message_ids(selected_exists)
            search_mode = 'sequence'

        if not message_ids:
            return {'success': True, 'emails': [], 'method': 'IMAP (Generic)', 'has_more': False}

        total = len(message_ids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip
        if start_idx >= end_idx:
            return {'success': True, 'emails': [], 'method': 'IMAP (Generic)', 'has_more': False}

        paged_uids = message_ids[start_idx:end_idx][::-1]
        emails_data = []
        for uid in paged_uids:
            try:
                f_status, f_data, fetch_mode, _fetch_attempts = fetch_imap_message(
                    mail, uid, '(FLAGS INTERNALDATE RFC822)', preferred_mode=search_mode or 'uid'
                )
                if f_status != 'OK' or not f_data:
                    continue
                raw_email, fetch_response_text = parse_imap_fetch_response(f_data)
                if not raw_email:
                    continue
                internal_date = extract_imap_internaldate(fetch_response_text)

                msg = email.message_from_bytes(raw_email)
                body_text, body_html = extract_text_and_html(msg)
                preview_source = body_text or strip_html_content(body_html)
                preview = preview_source[:200] + ('...' if len(preview_source) > 200 else '')
                emails_data.append({
                    'id': uid.decode('utf-8', errors='ignore') if isinstance(uid, (bytes, bytearray)) else str(uid),
                    'subject': decode_header_value(msg.get('Subject', '无主题')),
                    'from': decode_header_value(msg.get('From', '未知')),
                    'to': decode_header_value(msg.get('To', '')),
                    'date': internal_date or msg.get('Date', ''),
                    'id_mode': search_mode or 'uid',
                    'is_read': bool(re.search(r'\\Seen\b', fetch_response_text, flags=re.IGNORECASE)),
                    'has_attachments': has_message_attachments(msg),
                    'body_preview': preview,
                })
            except Exception:
                continue

        emails_data.sort(key=lambda item: parse_email_datetime(item.get('date')) or datetime.min, reverse=True)
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

        status, msg_data, _fetch_mode, _fetch_attempts = fetch_imap_message(
            mail, str(message_id), '(RFC822)', preferred_mode='uid'
        )
        if status != 'OK' or not msg_data:
            return {
                'success': False,
                'error': build_error_payload(
                    'EMAIL_DETAIL_FETCH_FAILED',
                    '获取邮件详情失败',
                    'IMAPFetchError',
                    502,
                    {
                        'status': status,
                        'provider': provider,
                        'folder': selected,
                        'message_id': str(message_id),
                        'fetch_attempts': _fetch_attempts[:10],
                    }
                )
            }

        raw_email = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw_email = item[1]
                break
        if not raw_email:
            return {
                'success': False,
                'error': build_error_payload(
                    'EMAIL_DETAIL_FETCH_FAILED',
                    '获取邮件详情失败',
                    'IMAPFetchError',
                    502,
                    {
                        'provider': provider,
                        'folder': selected,
                        'message_id': str(message_id),
                        'fetch_attempts': _fetch_attempts[:10],
                    }
                )
            }

        msg = email.message_from_bytes(raw_email)
        return {
            'success': True,
            'email': build_email_detail_from_message(msg, str(message_id))
        }
    except Exception as exc:
        return {'success': False, 'error': build_error_payload('IMAP_CONNECT_FAILED', sanitize_error_details(str(exc)) or 'IMAP 连接失败', 'IMAPConnectError', 502, '')}
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def download_email_attachment_imap_result(account: str, client_id: str, refresh_token: str, message_id: str,
                                          attachment_id: str, folder: str = 'inbox', proxy_url: str = None,
                                          fallback_proxy_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """使用 Outlook IMAP 下载邮件附件"""
    access_token = get_access_token_imap(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return {
            'success': False,
            'error': build_error_payload(
                'IMAP_TOKEN_FAILED',
                '获取访问令牌失败',
                'IMAPError',
                401,
                ''
            )
        }

    connection = None
    try:
        with proxy_socket_context(proxy_url):
            connection = imaplib.IMAP4_SSL(IMAP_SERVER_NEW, IMAP_PORT, timeout=IMAP_TIMEOUT)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode('utf-8')
        connection.authenticate('XOAUTH2', lambda x: auth_string)

        selected_folder, _ = resolve_imap_folder(connection, 'outlook', folder, readonly=True)
        if not selected_folder:
            return {
                'success': False,
                'error': build_error_payload(
                    'IMAP_FOLDER_NOT_FOUND',
                    'IMAP 文件夹不存在或无权访问',
                    'IMAPFolderError',
                    400,
                    {'folder': folder}
                )
            }

        status, msg_data = connection.fetch(message_id.encode() if isinstance(message_id, str) else message_id, '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            return {
                'success': False,
                'error': build_error_payload(
                    'ATTACHMENT_FETCH_FAILED',
                    '获取附件失败',
                    'IMAPFetchError',
                    502,
                    {'message_id': str(message_id)}
                )
            }

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        attachment = get_message_attachment_by_id(msg, attachment_id)
        if not attachment:
            return {
                'success': False,
                'error': build_error_payload(
                    'ATTACHMENT_NOT_FOUND',
                    '附件不存在',
                    'NotFoundError',
                    404,
                    {'attachment_id': attachment_id}
                )
            }

        return {
            'success': True,
            'filename': attachment.get('name', 'attachment'),
            'content_type': attachment.get('content_type', 'application/octet-stream'),
            'content': attachment.get('content', b''),
        }
    except Exception as exc:
        return {
            'success': False,
            'error': build_error_payload(
                'ATTACHMENT_FETCH_FAILED',
                '获取附件失败',
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


def download_email_attachment_imap_generic_result(email_addr: str, imap_password: str, imap_host: str,
                                                  imap_port: int = 993, message_id: str = '',
                                                  attachment_id: str = '', folder: str = 'inbox',
                                                  provider: str = 'custom', proxy_url: str = '') -> Dict[str, Any]:
    """使用通用 IMAP 下载邮件附件"""
    if not message_id or not attachment_id:
        return {'success': False, 'error': build_error_payload('ATTACHMENT_INVALID', '附件参数不完整', 'ValidationError', 400, '')}

    mail = None
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

        send_imap_id(mail, provider, imap_host)
        selected, folder_diagnostics = resolve_imap_folder(mail, provider, folder, readonly=True)
        if not selected:
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

        status, msg_data, _fetch_mode, fetch_attempts = fetch_imap_message(
            mail, str(message_id), '(RFC822)', preferred_mode='uid'
        )
        if status != 'OK' or not msg_data:
            return {
                'success': False,
                'error': build_error_payload(
                    'ATTACHMENT_FETCH_FAILED',
                    '获取附件失败',
                    'IMAPFetchError',
                    502,
                    {
                        'provider': provider,
                        'folder': selected,
                        'message_id': str(message_id),
                        'fetch_attempts': fetch_attempts[:10],
                    }
                )
            }

        raw_email = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw_email = item[1]
                break
        if not raw_email:
            return {
                'success': False,
                'error': build_error_payload(
                    'ATTACHMENT_FETCH_FAILED',
                    '获取附件失败',
                    'IMAPFetchError',
                    502,
                    {
                        'provider': provider,
                        'folder': selected,
                        'message_id': str(message_id),
                    }
                )
            }

        msg = email.message_from_bytes(raw_email)
        attachment = get_message_attachment_by_id(msg, attachment_id)
        if not attachment:
            return {
                'success': False,
                'error': build_error_payload(
                    'ATTACHMENT_NOT_FOUND',
                    '附件不存在',
                    'NotFoundError',
                    404,
                    {'attachment_id': attachment_id}
                )
            }

        return {
            'success': True,
            'filename': attachment.get('name', 'attachment'),
            'content_type': attachment.get('content_type', 'application/octet-stream'),
            'content': attachment.get('content', b''),
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
            )
        }
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
        value_str = str(value).strip()
        value_str = re.sub(r'\s+\([A-Za-z0-9_./+-]+\)$', '', value_str)
        if re.match(r'^\d{4}-\d{2}-\d{2}T', value_str):
            normalized = value_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(normalized)
        elif re.match(r'^\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$', value_str):
            dt = datetime.strptime(value_str, '%d-%b-%Y %H:%M:%S %z')
        else:
            dt = parsedate_to_datetime(value_str)
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
    decorated_function._requires_login = True
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
    decorated_function._requires_api_key = True
    return decorated_function


def assert_endpoint_protection(endpoint: str, protection_attr: str, protection_name: str):
    """确保动态替换后的 endpoint 仍然保留必须的鉴权保护。"""
    view_func = app.view_functions.get(endpoint)
    if view_func is None:
        raise RuntimeError(f'Endpoint 未注册: {endpoint}')
    if not getattr(view_func, protection_attr, False):
        raise RuntimeError(f'Endpoint {endpoint} 缺少 {protection_name} 保护')


# ==================== Flask 路由 ====================
