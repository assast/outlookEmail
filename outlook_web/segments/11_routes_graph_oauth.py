from __future__ import annotations

import json
import os
import queue
import re
import threading
import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from flask import stream_with_context

if TYPE_CHECKING:
    from web_outlook_app import *  # noqa: F403


# ==================== Graph OAuth 自动提取 ====================

# client_id 和 redirect_uri 复用 01_bootstrap.py 中的 OAUTH_CLIENT_ID / OAUTH_REDIRECT_URI，
# 不再单独定义 GRAPH_EXTRACT_CLIENT_ID / GRAPH_EXTRACT_REDIRECT_URI 环境变量。
# scope 和 authority 为 Graph 自动提取专用，值与常规 OAuth 不同，保持独立。
GRAPH_EXTRACT_SCOPE = os.getenv(
    "GRAPH_EXTRACT_SCOPE",
    "offline_access https://outlook.office.com/IMAP.AccessAsUser.All",
)
GRAPH_EXTRACT_GRAPH_SCOPE = os.getenv(
    "GRAPH_EXTRACT_GRAPH_SCOPE",
    "offline_access https://graph.microsoft.com/Mail.Read",
)
GRAPH_EXTRACT_AUTHORITY = os.getenv("GRAPH_EXTRACT_AUTHORITY", "consumers")
GRAPH_EXTRACT_SCOPE_BY_MODE = {
    "imap": GRAPH_EXTRACT_SCOPE,
    "graph": GRAPH_EXTRACT_GRAPH_SCOPE,
}

# Backward-compatible aliases for existing docs/tests.
GRAPH_CLIENT_ID = OAUTH_CLIENT_ID
GRAPH_REDIRECT_URI = OAUTH_REDIRECT_URI
GRAPH_SCOPE = GRAPH_EXTRACT_SCOPE

GRAPH_OAUTH_TASKS: Dict[str, Dict[str, Any]] = {}
GRAPH_OAUTH_DONE = object()


def normalize_graph_oauth_mode(mode: Any) -> str:
    normalized = str(mode or "imap").strip().lower()
    return normalized if normalized in GRAPH_EXTRACT_SCOPE_BY_MODE else "imap"


def graph_oauth_mode_label(mode: str) -> str:
    return "Graph-only（不含 IMAP 权限）" if mode == "graph" else "Outlook IMAP"


def graph_oauth_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def graph_oauth_safe_details(details: Any) -> str:
    return sanitize_error_details(str(details or ""))[:500]


def graph_oauth_log(log: Optional[Callable[[str], None]], message: str) -> None:
    if log:
        log(graph_oauth_safe_details(message))


def make_graph_oauth_response(success: bool, error: str = "", details: str = "",
                              **extra: Any) -> Dict[str, Any]:
    payload = {"success": bool(success)}
    if error:
        payload["error"] = graph_oauth_safe_details(error)
    if details:
        payload["details"] = graph_oauth_safe_details(details)
    payload.update(extra)
    return payload


def build_graph_authorize_url(client_id: str, redirect_uri: str, scope: str,
                              authority: str) -> str:
    return (
        f"https://login.microsoftonline.com/{authority}/oauth2/v2.0/authorize"
        f"?client_id={urllib.parse.quote(client_id, safe='')}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&response_mode=query"
    )


def make_light_response(url: str, text: str = "", status_code: int = 200):
    return type("GraphOauthResponse", (), {
        "url": url,
        "text": text,
        "status_code": status_code,
        "headers": {},
    })()


def extract_hidden_inputs(html: str) -> Dict[str, str]:
    return {
        name: value
        for name, value in re.findall(
            r'<input[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
            html or "",
            re.IGNORECASE,
        )
    }


def absolute_form_action(action: str, current_url: str) -> str:
    action = (action or "").replace("&amp;", "&")
    if action.startswith("http"):
        return action
    base = urllib.parse.urlparse(current_url)
    if action.startswith("/"):
        return f"{base.scheme}://{base.netloc}{action}"
    path = urllib.parse.urljoin(f"{base.scheme}://{base.netloc}{base.path}", action)
    return path


def extract_graph_refresh_token(
    email: str,
    password: str,
    *,
    client_id: str = OAUTH_CLIENT_ID,
    redirect_uri: str = OAUTH_REDIRECT_URI,
    scope: str = GRAPH_EXTRACT_SCOPE,
    authority: str = GRAPH_EXTRACT_AUTHORITY,
    log: Optional[Callable[[str], None]] = None,
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """使用纯 HTTP OAuth2 授权码流程提取 Outlook refresh_token。"""
    try:
        session = session_factory() if session_factory else requests.Session()
        session.trust_env = True
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            )
        })

        graph_oauth_log(log, f"获取 Microsoft 授权页面: {email}")
        resp = session.get(
            build_graph_authorize_url(client_id, redirect_uri, scope, authority),
            timeout=30,
            allow_redirects=True,
        )
        text = resp.text or ""

        flow_token = ""
        sft_tag = re.search(r'sFTTag.*?value=\\?"([^"\\]+)', text, re.DOTALL)
        if sft_tag:
            flow_token = sft_tag.group(1)
        if not flow_token:
            ppft = re.search(r'name="PPFT"[^>]*value="([^"]+)"', text, re.IGNORECASE)
            if ppft:
                flow_token = ppft.group(1)
        if not flow_token:
            return make_graph_oauth_response(False, "无法提取 Flow Token", "未在授权页面找到 PPFT 字段")

        post_url = ""
        urlpost_match = re.search(r'"urlPost"\s*:\s*"([^"]+)"', text)
        if urlpost_match:
            post_url = urlpost_match.group(1).replace("\\u0026", "&")
        if not post_url:
            post_url = "https://login.live.com/ppsecure/post.srf"

        ctx = ""
        sctx_match = re.search(r'"sCtx"\s*:\s*"([^"]+)"', text)
        if sctx_match:
            ctx = sctx_match.group(1)

        graph_oauth_log(log, "提交 Microsoft 登录凭据")
        resp2 = session.post(
            post_url,
            data={
                "login": email,
                "loginfmt": email,
                "passwd": password,
                "PPFT": flow_token,
                "ctx": ctx,
                "type": "11",
                "LoginOptions": "3",
                "i13": "0",
                "CookieDisclosure": "0",
                "IsFidoSupported": "0",
                "isSignupPost": "0",
                "i19": "16393",
            },
            timeout=30,
            allow_redirects=False,
        )

        # 检测登录失败的情况
        post_html = resp2.text or ""
        post_url_check = getattr(resp2, "url", "") or post_url

        if resp2.status_code == 200 and "ppsecure/post.srf" in post_url_check:
            # 情况1：检查JavaScript错误变量和HTML错误元素
            error_markers = [
                (r'sErrTxt["\s:=]+["\']([^"\']+)', "JavaScript错误信息"),
                (r'<div[^>]*id=["\']error["\'][^>]*>([^<]+)', "错误提示框"),
                (r'data-bind=["\']text:\s*unsafe_(\w+)["\']', "验证失败"),
                (r'<div[^>]*class=["\'][^"\']*error[^"\']*["\'][^>]*>([^<]+)', "错误样式"),
            ]

            for pattern, error_type in error_markers:
                match = re.search(pattern, post_html, re.IGNORECASE | re.DOTALL)
                if match:
                    error_detail = match.group(1).strip() if match.lastindex and len(match.groups()) > 0 else error_type
                    # 清理HTML标签
                    error_detail = re.sub(r'<[^>]+>', '', error_detail).strip()
                    return make_graph_oauth_response(
                        False,
                        "Microsoft 登录失败",
                        f"{error_type}: {graph_oauth_safe_details(error_detail)}"
                    )

            # 情况2：没有重定向且停留在post.srf，检查是否返回了登录表单
            if not resp2.headers.get("Location"):
                # 如果页面包含密码输入框，说明登录失败返回了登录页面
                if re.search(r'name=["\']passwd["\']', post_html, re.IGNORECASE):
                    # 尝试提取更具体的错误信息
                    specific_errors = [
                        (r'incorrect|invalid|wrong', "密码不正确或账号不存在"),
                        (r'verify|verification|confirm', "需要额外验证"),
                        (r'suspicious|unusual', "检测到异常活动"),
                        (r'disabled|locked|blocked', "账号被锁定或禁用"),
                    ]

                    error_hint = "密码不正确、账号不存在或需要额外验证"
                    for pattern, hint in specific_errors:
                        if re.search(pattern, post_html, re.IGNORECASE):
                            error_hint = hint
                            break

                    return make_graph_oauth_response(
                        False,
                        "登录凭据验证失败",
                        f"提交凭据后返回了登录表单，通常表示{error_hint}。请手动登录 https://outlook.live.com 确认账号状态。"
                    )

        for _ in range(5):
            html = resp2.text or ""
            if ("DoSubmit" in html or ("fmHF" in html and "onload" in html)) and "action=" in html:
                form_action_match = re.search(r'action="([^"]+)"', html)
                if form_action_match:
                    form_action = form_action_match.group(1).replace("&amp;", "&")
                    graph_oauth_log(log, "处理 Microsoft 中间自动提交页面")
                    resp2 = session.post(
                        form_action,
                        data=extract_hidden_inputs(html),
                        timeout=30,
                        allow_redirects=False,
                    )
                    continue
            break

        auth_code = None
        for _ in range(15):
            while resp2.status_code in (301, 302, 303, 307):
                loc = resp2.headers.get("Location", "")
                if "localhost" in loc:
                    resp2 = make_light_response(loc)
                    break
                resp2 = session.get(loc, timeout=30, allow_redirects=False)

            current_url = getattr(resp2, "url", "") or ""
            text = resp2.text if getattr(resp2, "text", "") else ""

            if "localhost" in current_url and "code=" in current_url:
                params = urllib.parse.parse_qs(urllib.parse.urlparse(current_url).query)
                auth_code = params.get("code", [None])[0]
                if auth_code:
                    graph_oauth_log(log, "已捕获授权码")
                    break

            if "localhost" in current_url and "error" in current_url:
                params = urllib.parse.parse_qs(urllib.parse.urlparse(current_url).query)
                err = params.get("error_description", params.get("error", ["?"]))[0]
                return make_graph_oauth_response(False, "OAuth 错误", err)

            if "Consent/Update" in current_url or "Consent/update" in current_url:
                server_data = re.search(r'ServerData\s*=\s*(\{.*?\});', text, re.DOTALL)
                if not server_data:
                    return make_graph_oauth_response(False, "同意页面处理失败", "无法解析 ServerData")
                graph_oauth_log(log, "接受 Outlook 授权同意页面")
                sd = json.loads(server_data.group(1))
                resp2 = session.post(
                    current_url,
                    data={
                        "ucaction": "Yes",
                        "client_id": sd.get("sClientId", ""),
                        "scope": sd.get("sRawInputScopes", ""),
                        "cscope": sd.get("sRawInputGrantedScopes", ""),
                        "canary": sd.get("sCanary", ""),
                    },
                    timeout=30,
                    allow_redirects=False,
                )
                continue

            if "proofs/Add" in current_url or "proofs/add" in current_url:
                form_match = re.search(
                    r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                    text,
                    re.DOTALL | re.IGNORECASE,
                )
                if not form_match:
                    return make_graph_oauth_response(False, "安全信息页面处理失败", "无法找到表单")
                graph_oauth_log(log, "跳过 Microsoft 安全信息添加页面")
                form_data = extract_hidden_inputs(form_match.group(2))
                form_data["action"] = "Skip"
                resp2 = session.post(
                    absolute_form_action(form_match.group(1), current_url),
                    data=form_data,
                    timeout=30,
                    allow_redirects=False,
                )
                continue

            form_match = re.search(
                r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                text,
                re.DOTALL | re.IGNORECASE,
            )
            if form_match:
                form_action = absolute_form_action(form_match.group(1), current_url)
                form_data = extract_hidden_inputs(form_match.group(2))
                if "consent" in form_action.lower() or "consent" in current_url.lower():
                    graph_oauth_log(log, "提交通用同意表单")
                    form_data["ucaccept"] = "Yes"

                resp2 = session.post(form_action, data=form_data, timeout=30, allow_redirects=False)
                while resp2.status_code in (301, 302, 303, 307):
                    loc = resp2.headers.get("Location", "")
                    if "localhost" in loc:
                        resp2 = make_light_response(loc)
                        break
                    if not loc:
                        break
                    resp2 = session.get(loc, timeout=30, allow_redirects=False)
                continue

            return make_graph_oauth_response(
                False,
                "授权流程卡住",
                f"在 {current_url[:100]} 无法继续 (status={resp2.status_code})",
            )

        if not auth_code:
            return make_graph_oauth_response(False, "未能获取授权码", "完成所有步骤但未捕获到授权码")

        graph_oauth_log(log, "使用授权码换取 Outlook token")
        token_resp = session.post(
            f"https://login.microsoftonline.com/{authority}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "scope": scope,
            },
            timeout=30,
        )
        token_data = token_resp.json()

        if "access_token" not in token_data:
            err = token_data.get("error_description", token_data.get("error", "?"))
            return make_graph_oauth_response(False, "Token 换取失败", err)

        refresh_token = str(token_data.get("refresh_token") or "").strip()
        if not refresh_token:
            return make_graph_oauth_response(False, "未获取到 refresh_token", "响应中包含 access_token 但没有 refresh_token")

        graph_oauth_log(log, "已获取 Outlook refresh_token")
        return {
            "success": True,
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
    except Exception as exc:
        return make_graph_oauth_response(False, f"异常: {type(exc).__name__}", str(exc))


def get_upload_account_for_graph_auth(account_id: int):
    db = get_db()
    return db.execute(
        '''
        SELECT id, email, password, is_authorized, remark
        FROM outlook_upload_accounts
        WHERE id = ?
        ''',
        (account_id,),
    ).fetchone()


def upsert_graph_authorized_account(email: str, password: str, client_id: str,
                                    refresh_token: str) -> Dict[str, Any]:
    db = get_db()
    existing = db.execute(
        'SELECT id FROM accounts WHERE LOWER(email) = ? LIMIT 1',
        (normalize_email_address(email),),
    ).fetchone()
    encrypted_password = encrypt_data(password) if password else password
    encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token

    if existing:
        account_id = int(existing['id'])
        db.execute(
            '''
            UPDATE accounts
            SET password = ?,
                client_id = ?,
                refresh_token = ?,
                account_type = 'outlook',
                provider = 'outlook',
                refresh_token_updated_at = CURRENT_TIMESTAMP,
                last_refresh_status = 'never',
                last_refresh_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (encrypted_password, client_id, encrypted_refresh_token, account_id),
        )
        return {"account_id": account_id, "created": False}

    cursor = db.execute(ACCOUNT_INSERT_SQL, build_account_insert_values(
        normalize_email_address(email),
        password,
        client_id,
        refresh_token,
        1,
        '',
        'outlook',
        'outlook',
        IMAP_SERVER_NEW,
        IMAP_PORT,
        '',
        False,
        None,
        'active',
    ))
    account_id = int(cursor.lastrowid)
    db.execute(
        '''
        UPDATE accounts
        SET refresh_token_updated_at = CURRENT_TIMESTAMP,
            last_refresh_status = 'never',
            last_refresh_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (account_id,),
    )
    return {"account_id": account_id, "created": True}


def mark_upload_account_authorized(account_id: int) -> None:
    get_db().execute(
        '''
        UPDATE outlook_upload_accounts
        SET is_authorized = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (account_id,),
    )


def save_graph_authorization_result(upload_row: Any, client_id: str,
                                    refresh_token: str) -> Dict[str, Any]:
    email = str(upload_row['email'] or '').strip()
    password = get_upload_account_plain_password(upload_row)
    save_result = upsert_graph_authorized_account(email, password, client_id, refresh_token)
    mark_upload_account_authorized(int(upload_row['id']))
    get_db().commit()
    return save_result


def run_graph_oauth_task(account_id: int, output_queue: "queue.Queue[Dict[str, Any] | object]",
                         mode: str = "imap") -> None:
    def emit(payload: Dict[str, Any]) -> None:
        output_queue.put(payload)

    def log(message: str) -> None:
        emit({"type": "log", "message": graph_oauth_safe_details(message)})

    with app.app_context():
        try:
            mode = normalize_graph_oauth_mode(mode)
            upload_row = get_upload_account_for_graph_auth(account_id)
            if not upload_row:
                emit({"type": "error", "success": False, "mode": mode, "message": "上传账号不存在"})
                emit({"type": "complete", "success": False})
                return

            email = str(upload_row['email'] or '').strip()
            password = get_upload_account_plain_password(upload_row)
            if not email or not password:
                emit({"type": "error", "success": False, "mode": mode, "message": "邮箱或密码为空"})
                emit({"type": "complete", "success": False})
                return

            mode_label = graph_oauth_mode_label(mode)
            scope = GRAPH_EXTRACT_SCOPE_BY_MODE[mode]
            emit({
                "type": "start",
                "email": email,
                "mode": mode,
                "message": f"开始 {mode_label} OAuth 授权",
            })
            log(f"授权模式: {mode_label}")
            log(f"授权 Scope: {scope}")
            result = extract_graph_refresh_token(email, password, scope=scope, log=log)
            if not result.get("success"):
                emit({
                    "type": "error",
                    "success": False,
                    "mode": mode,
                    "message": graph_oauth_safe_details(result.get("error") or "授权失败"),
                    "details": graph_oauth_safe_details(result.get("details") or ""),
                })
                emit({"type": "complete", "success": False})
                return

            client_id = str(result.get("client_id") or "").strip()
            refresh_token = str(result.get("refresh_token") or "").strip()
            log(f"验证 {mode_label} refresh_token")
            ok, error_msg, rotated_refresh_token = test_refresh_token(client_id, refresh_token)
            if not ok:
                emit({
                    "type": "error",
                    "success": False,
                    "mode": mode,
                    "message": f"{mode_label} refresh_token 验证失败",
                    "details": graph_oauth_safe_details(error_msg),
                })
                emit({"type": "complete", "success": False})
                return

            token_to_save = rotated_refresh_token or refresh_token
            save_result = save_graph_authorization_result(upload_row, client_id, token_to_save)
            emit({
                "type": "success",
                "success": True,
                "mode": mode,
                "email": email,
                "account_id": save_result["account_id"],
                "created": save_result["created"],
                "client_id": client_id,
                "message": "授权成功，已保存到正式账号",
            })
            emit({"type": "complete", "success": True})
        except Exception as exc:
            try:
                get_db().rollback()
            except Exception:
                pass
            emit({
                "type": "error",
                "success": False,
                "mode": normalize_graph_oauth_mode(mode),
                "message": "授权任务异常",
                "details": graph_oauth_safe_details(str(exc)),
            })
            emit({"type": "complete", "success": False})
        finally:
            output_queue.put(GRAPH_OAUTH_DONE)


@app.route('/api/oauth/graph-extract-token', methods=['POST'])
@login_required
def api_graph_extract_token():
    data = request.get_json(silent=True) or {}
    raw_account_id = data.get('account_id')
    try:
        account_id = int(raw_account_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'account_id 不能为空'}), 400

    row = get_upload_account_for_graph_auth(account_id)
    if not row:
        return jsonify({'success': False, 'error': '上传账号不存在'}), 404
    if not str(row['email'] or '').strip() or not str(row['password'] or ''):
        return jsonify({'success': False, 'error': '邮箱或密码为空'}), 400

    mode = normalize_graph_oauth_mode(data.get('mode'))
    task_id = uuid.uuid4().hex
    GRAPH_OAUTH_TASKS[task_id] = {'account_id': account_id, 'mode': mode}
    return jsonify({
        'success': True,
        'task_id': task_id,
        'mode': mode,
        'stream_url': f'/api/oauth/graph-extract-token/{task_id}/stream',
    })


@app.route('/api/oauth/graph-extract-token/<task_id>/stream', methods=['GET'])
@login_required
def api_graph_extract_token_stream(task_id: str):
    task = GRAPH_OAUTH_TASKS.pop(task_id, None)
    if not task:
        return Response(
            graph_oauth_sse({'type': 'error', 'success': False, 'message': '授权任务不存在或已过期'})
            + graph_oauth_sse({'type': 'complete', 'success': False}),
            mimetype='text/event-stream',
        )

    def generate():
        output_queue: "queue.Queue[Dict[str, Any] | object]" = queue.Queue()
        worker = threading.Thread(
            target=run_graph_oauth_task,
            args=(int(task['account_id']), output_queue, normalize_graph_oauth_mode(task.get('mode'))),
            name=f"graph-oauth-{task_id[:8]}",
            daemon=True,
        )
        worker.start()

        while True:
            payload = output_queue.get()
            if payload is GRAPH_OAUTH_DONE:
                break
            yield graph_oauth_sse(payload)
        worker.join(timeout=1)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
