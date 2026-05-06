from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # These segmented files are executed into the shared `web_outlook_app`
    # globals at runtime. Importing from the assembled module keeps IDE
    # inspections from flagging the shared names as unresolved.
    from web_outlook_app import *  # noqa: F403


TOKEN_REFRESH_SCOPE_KEY = 'all_outlook'
VALID_ACCOUNT_REFRESH_STATUSES = {'success', 'failed', 'never'}
VALID_REFRESH_STATUS_FILTERS = {'all', 'success', 'failed', 'never'}
TOKEN_REFRESH_CONFLICT_MESSAGE = '已有 Token 全量刷新任务在执行，请稍后再试'
TOKEN_REFRESH_STOP_REQUESTED_MESSAGE = '已请求停止，当前账号处理完成后会结束任务'
TOKEN_REFRESH_STOPPED_MESSAGE = '已手动停止全量刷新任务'
token_refresh_stop_event = threading.Event()


def normalize_account_refresh_status_value(status: Any) -> str:
    normalized = str(status or '').strip().lower()
    if normalized in VALID_ACCOUNT_REFRESH_STATUSES:
        return normalized
    return 'never'


def normalize_refresh_status_filter(status: Any) -> str:
    normalized = str(status or '').strip().lower()
    if normalized in VALID_REFRESH_STATUS_FILTERS:
        return normalized
    return 'all'


def is_outlook_refreshable_account(account: Any) -> bool:
    account_type = str((account or {}).get('account_type', 'outlook') if isinstance(account, dict) else account['account_type'] or 'outlook').strip().lower()
    status = str((account or {}).get('status', 'active') if isinstance(account, dict) else account['status'] or 'active').strip().lower()
    return account_type == 'outlook' and status == 'active'


def ensure_token_refresh_state_row(db_conn=None) -> None:
    db = db_conn or get_db()
    db.execute(
        '''
        INSERT OR IGNORE INTO token_refresh_state (
            scope_key, trigger_type, status, total_count, success_count, failed_count, updated_at
        )
        VALUES (?, ?, ?, 0, 0, 0, CURRENT_TIMESTAMP)
        ''',
        (TOKEN_REFRESH_SCOPE_KEY, '', 'idle')
    )


def get_token_refresh_snapshot(db_conn=None) -> Dict[str, Any]:
    db = db_conn or get_db()
    ensure_token_refresh_state_row(db)
    row = db.execute(
        '''
        SELECT *
        FROM token_refresh_state
        WHERE scope_key = ?
        LIMIT 1
        ''',
        (TOKEN_REFRESH_SCOPE_KEY,)
    ).fetchone()
    return dict(row) if row else {}


def mark_token_refresh_snapshot_running(trigger_type: str, total_count: int, db_conn=None) -> None:
    db = db_conn or get_db()
    ensure_token_refresh_state_row(db)
    db.execute(
        '''
        UPDATE token_refresh_state
        SET trigger_type = ?,
            status = 'running',
            started_at = CURRENT_TIMESTAMP,
            finished_at = NULL,
            total_count = ?,
            success_count = 0,
            failed_count = 0,
            error_summary = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_key = ?
        ''',
        (trigger_type, max(0, int(total_count or 0)), TOKEN_REFRESH_SCOPE_KEY)
    )


def mark_token_refresh_snapshot_finished(trigger_type: str, total_count: int,
                                         success_count: int, failed_count: int,
                                         error_summary: str = '', db_conn=None,
                                         status_override: Optional[str] = None) -> None:
    db = db_conn or get_db()
    ensure_token_refresh_state_row(db)
    normalized_total = max(0, int(total_count or 0))
    normalized_success = max(0, int(success_count or 0))
    normalized_failed = max(0, int(failed_count or 0))
    if status_override in {'idle', 'success', 'partial_failed', 'failed'}:
        final_status = status_override
    elif normalized_total <= 0:
        final_status = 'idle'
    elif normalized_failed <= 0:
        final_status = 'success'
    elif normalized_success > 0:
        final_status = 'partial_failed'
    else:
        final_status = 'failed'

    db.execute(
        '''
        UPDATE token_refresh_state
        SET trigger_type = ?,
            status = ?,
            finished_at = CURRENT_TIMESTAMP,
            total_count = ?,
            success_count = ?,
            failed_count = ?,
            error_summary = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_key = ?
        ''',
        (
            trigger_type,
            final_status,
            normalized_total,
            normalized_success,
            normalized_failed,
            sanitize_error_details(error_summary)[:500] if error_summary else None,
            TOKEN_REFRESH_SCOPE_KEY,
        )
    )


def query_refreshable_accounts(db_conn=None, account_ids: Optional[List[int]] = None,
                               search: str = '', refresh_status: str = 'all',
                               page: int = 1, page_size: int = 100) -> Dict[str, Any]:
    db = db_conn or get_db()
    refresh_status = normalize_refresh_status_filter(refresh_status)
    page = max(1, int(page or 1))
    page_size = max(1, min(500, int(page_size or 100)))
    offset = (page - 1) * page_size

    where_clauses = [
        "COALESCE(a.account_type, 'outlook') = 'outlook'",
        "a.status = 'active'",
    ]
    params: List[Any] = []

    normalized_search = str(search or '').strip()
    if normalized_search:
        where_clauses.append('(a.email LIKE ? OR COALESCE(a.remark, \'\') LIKE ? OR COALESCE(g.name, \'\') LIKE ?)')
        like_value = f'%{normalized_search}%'
        params.extend([like_value, like_value, like_value])

    if refresh_status != 'all':
        where_clauses.append("COALESCE(NULLIF(a.last_refresh_status, ''), 'never') = ?")
        params.append(refresh_status)

    if account_ids is not None:
        normalized_ids = []
        seen_ids = set()
        for account_id in account_ids:
            try:
                normalized_id = int(account_id)
            except (TypeError, ValueError):
                continue
            if normalized_id <= 0 or normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            normalized_ids.append(normalized_id)
        if not normalized_ids:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        where_clauses.append(f"a.id IN ({','.join('?' * len(normalized_ids))})")
        params.extend(normalized_ids)

    where_sql = ' AND '.join(where_clauses)
    total_row = db.execute(
        f'''
        SELECT COUNT(*) AS total_count
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        WHERE {where_sql}
        ''',
        tuple(params)
    ).fetchone()
    total_count = total_row['total_count'] if total_row else 0

    rows = db.execute(
        f'''
        SELECT a.*, g.name AS group_name, g.color AS group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        WHERE {where_sql}
        ORDER BY
            CASE COALESCE(NULLIF(a.last_refresh_status, ''), 'never')
                WHEN 'failed' THEN 0
                WHEN 'never' THEN 1
                ELSE 2
            END,
            CASE WHEN a.last_refresh_at IS NULL OR a.last_refresh_at = '' THEN 1 ELSE 0 END,
            a.last_refresh_at DESC,
            a.created_at DESC,
            a.id DESC
        LIMIT ? OFFSET ?
        ''',
        tuple([*params, page_size, offset])
    ).fetchall()

    items = []
    for row in rows:
        account = resolve_account_record(row)
        account['tags'] = get_account_tags(account['id'])
        items.append(serialize_account_summary(account))

    return {
        'items': items,
        'total': total_count,
        'page': page,
        'page_size': page_size,
    }


def build_refresh_stats(db_conn=None) -> Dict[str, Any]:
    db = db_conn or get_db()
    ensure_token_refresh_state_row(db)
    snapshot = get_token_refresh_snapshot(db)

    counts_row = db.execute(
        '''
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN COALESCE(NULLIF(last_refresh_status, ''), 'never') = 'success' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN COALESCE(NULLIF(last_refresh_status, ''), 'never') = 'failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN COALESCE(NULLIF(last_refresh_status, ''), 'never') = 'never' THEN 1 ELSE 0 END) AS never_count
        FROM accounts
        WHERE status = 'active'
          AND COALESCE(account_type, 'outlook') = 'outlook'
        '''
    ).fetchone()

    total_count = counts_row['total_count'] if counts_row and counts_row['total_count'] is not None else 0
    success_count = counts_row['success_count'] if counts_row and counts_row['success_count'] is not None else 0
    failed_count = counts_row['failed_count'] if counts_row and counts_row['failed_count'] is not None else 0
    never_count = counts_row['never_count'] if counts_row and counts_row['never_count'] is not None else 0

    snapshot_status = str(snapshot.get('status') or '').strip().lower()
    last_refresh_time = snapshot.get('finished_at')
    if not last_refresh_time:
        row = db.execute(
            '''
            SELECT MAX(created_at) AS last_refresh_time
            FROM account_refresh_logs
            WHERE refresh_type IN ('manual', 'scheduled')
            '''
        ).fetchone()
        last_refresh_time = row['last_refresh_time'] if row else None

    if snapshot_status not in {'running', 'success', 'partial_failed', 'failed'}:
        if total_count <= 0 or never_count == total_count:
            snapshot_status = 'idle'
        elif failed_count <= 0:
            snapshot_status = 'success'
        elif success_count > 0:
            snapshot_status = 'partial_failed'
        else:
            snapshot_status = 'failed'

    return {
        'total': total_count,
        'success_count': success_count,
        'failed_count': failed_count,
        'never_count': never_count,
        'last_refresh_time': last_refresh_time,
        'last_refresh_status': snapshot_status,
        'running': snapshot_status == 'running',
        'trigger_type': snapshot.get('trigger_type') or '',
        'error_summary': snapshot.get('error_summary') or '',
    }


class TokenRefreshInProgressError(RuntimeError):
    """当前已有全量刷新任务执行中。"""


def cleanup_refresh_logs(db_conn=None) -> int:
    db = db_conn or get_db()
    should_commit = db_conn is None
    try:
        cursor = db.execute(
            "DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')"
        )
        if should_commit:
            db.commit()
        return max(0, int(cursor.rowcount or 0))
    except Exception:
        if should_commit:
            try:
                db.rollback()
            except Exception:
                pass
        raise


def clear_token_refresh_stop_request() -> None:
    token_refresh_stop_event.clear()


def request_token_refresh_stop() -> None:
    token_refresh_stop_event.set()


def is_token_refresh_stop_requested() -> bool:
    return token_refresh_stop_event.is_set()


def acquire_token_refresh_run_lock() -> None:
    if not token_refresh_run_lock.acquire(blocking=False):
        raise TokenRefreshInProgressError(TOKEN_REFRESH_CONFLICT_MESSAGE)


def release_token_refresh_run_lock(acquired: bool) -> None:
    if not acquired:
        return
    try:
        token_refresh_run_lock.release()
    except RuntimeError:
        pass


def build_refresh_error_summary(failed_list: List[Dict[str, Any]], fallback_message: str = '') -> str:
    parts = [
        f"{item.get('email') or 'unknown'}: {item.get('error') or '未知错误'}"
        for item in failed_list[:5]
    ]
    if not parts and fallback_message:
        parts.append(sanitize_error_details(fallback_message))
    return '; '.join(parts)


def finalize_stopped_full_refresh(conn, snapshot_trigger_type: str, total: int,
                                  success_count: int, failed_count: int,
                                  failed_list: List[Dict[str, Any]],
                                  delay_seconds: int = 0) -> Dict[str, Any]:
    processed_count = max(0, success_count + failed_count)
    if total <= 0:
        final_status = 'idle'
    elif processed_count <= 0:
        final_status = 'failed'
    elif processed_count < total:
        final_status = 'partial_failed' if success_count > 0 else 'failed'
    elif failed_count <= 0:
        final_status = 'success'
    elif success_count > 0:
        final_status = 'partial_failed'
    else:
        final_status = 'failed'

    error_summary = build_refresh_error_summary(failed_list, TOKEN_REFRESH_STOPPED_MESSAGE)
    mark_token_refresh_snapshot_finished(
        snapshot_trigger_type,
        total,
        success_count,
        failed_count,
        error_summary,
        conn,
        status_override=final_status
    )
    conn.commit()

    return build_stopped_refresh_payload(
        total,
        success_count,
        failed_count,
        failed_list,
        delay_seconds=delay_seconds,
        refresh_type=snapshot_trigger_type,
    )


def build_stopped_refresh_payload(total: int, success_count: int, failed_count: int,
                                  failed_list: List[Dict[str, Any]],
                                  delay_seconds: int = 0,
                                  refresh_type: str = '') -> Dict[str, Any]:
    processed_count = max(0, success_count + failed_count)
    return {
        'type': 'stopped',
        'message': TOKEN_REFRESH_STOPPED_MESSAGE,
        'total': total,
        'processed_count': processed_count,
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_list': failed_list,
        'delay_seconds': max(0, int(delay_seconds or 0)),
        'refresh_type': refresh_type,
    }


def wait_refresh_delay(delay_seconds: int) -> bool:
    import time as time_module

    remaining = max(0.0, float(delay_seconds or 0))
    while remaining > 0:
        if is_token_refresh_stop_requested():
            return False
        sleep_seconds = min(0.25, remaining)
        time_module.sleep(sleep_seconds)
        remaining -= sleep_seconds
    return not is_token_refresh_stop_requested()


def finalize_aborted_full_refresh(conn, snapshot_trigger_type: str, log_refresh_type: str,
                                  total: int, success_count: int, failed_count: int,
                                  failed_list: List[Dict[str, Any]], current_account=None,
                                  current_account_counted: bool = False,
                                  error: Exception | None = None) -> Dict[str, Any]:
    failure_message = sanitize_error_details(str(error or '未知错误')) or '未知错误'
    active_total = max(0, int(total or 0))

    if current_account is not None and not current_account_counted:
        failed_count += 1
        failed_item = {
            'id': current_account['id'],
            'email': current_account['email'],
            'error': failure_message,
        }
        failed_list.append(failed_item)
        try:
            log_refresh_result(
                current_account['id'],
                current_account['email'],
                log_refresh_type,
                'failed',
                failure_message,
                db_conn=conn
            )
            conn.commit()
        except Exception as log_error:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"记录异常刷新结果失败: {str(log_error)}")
        if active_total <= 0:
            active_total = success_count + failed_count

    final_status = 'partial_failed' if success_count > 0 else 'failed'
    error_summary = build_refresh_error_summary(failed_list, failure_message)
    mark_token_refresh_snapshot_finished(
        snapshot_trigger_type,
        active_total,
        success_count,
        failed_count,
        error_summary,
        conn,
        status_override=final_status
    )
    conn.commit()

    return {
        'type': 'error',
        'message': failure_message,
        'total': active_total,
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_list': failed_list,
        'refresh_type': snapshot_trigger_type,
    }


def finalize_aborted_retry_refresh(conn, log_refresh_type: str,
                                   total: int, success_count: int, failed_count: int,
                                   failed_list: List[Dict[str, Any]], current_account=None,
                                   current_account_counted: bool = False,
                                   error: Exception | None = None) -> Dict[str, Any]:
    failure_message = sanitize_error_details(str(error or '未知错误')) or '未知错误'
    active_total = max(0, int(total or 0))

    if current_account is not None and not current_account_counted:
        failed_count += 1
        failed_item = {
            'id': current_account['id'],
            'email': current_account['email'],
            'error': failure_message,
        }
        failed_list.append(failed_item)
        try:
            log_refresh_result(
                current_account['id'],
                current_account['email'],
                log_refresh_type,
                'failed',
                failure_message,
                db_conn=conn
            )
            conn.commit()
        except Exception as log_error:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"记录异常重试结果失败: {str(log_error)}")
        if active_total <= 0:
            active_total = success_count + failed_count

    return {
        'type': 'error',
        'message': failure_message,
        'total': active_total,
        'success_count': success_count,
        'failed_count': failed_count,
        'failed_list': failed_list,
        'refresh_type': 'retry_failed',
    }


def log_refresh_result(account_id: int, account_email: str, refresh_type: str, status: str,
                       error_message: str = None, db_conn=None):
    """记录刷新结果到数据库"""
    db = db_conn or get_db()
    should_commit = db_conn is None
    normalized_status = 'success' if str(status or '').strip().lower() == 'success' else 'failed'
    sanitized_error = sanitize_error_details(error_message)[:500] if error_message else None
    try:
        db.execute('''
            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
            VALUES (?, ?, ?, ?, ?)
        ''', (account_id, account_email, refresh_type, normalized_status, sanitized_error))

        db.execute(
            '''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP,
                last_refresh_status = ?,
                last_refresh_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (
                normalized_status,
                sanitized_error if normalized_status == 'failed' else None,
                account_id,
            )
        )

        if should_commit:
            db.commit()
        return True
    except Exception as e:
        if should_commit:
            try:
                db.rollback()
            except Exception:
                pass
        print(f"记录刷新结果失败: {str(e)}")
        return False


def persist_rotated_refresh_token(account_id: int, refresh_token: str, db_conn=None) -> bool:
    """保存微软返回的新 refresh_token。"""
    token_value = str(refresh_token or '').strip()
    if not token_value:
        return False

    db = db_conn or get_db()
    should_commit = db_conn is None
    try:
        db.execute(
            '''
            UPDATE accounts
            SET refresh_token = ?, refresh_token_updated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (encrypt_data(token_value), account_id)
        )
        if should_commit:
            db.commit()
        return True
    except Exception as e:
        if should_commit:
            try:
                db.rollback()
            except Exception:
                pass
        print(f"保存轮换 refresh_token 失败: {str(e)}")
        return False


def log_forwarding_result(account_id: int, account_email: str, message_id: str, channel: str,
                          status: str, error_message: str = None, db_conn=None):
    """记录转发结果到数据库"""
    db = db_conn or get_db()
    should_commit = db_conn is None
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
        if should_commit:
            db.commit()
        return True
    except Exception as e:
        if should_commit:
            try:
                db.rollback()
            except Exception:
                pass
        print(f"记录转发结果失败: {str(e)}")
        return False


def test_refresh_token(client_id: str, refresh_token: str, proxy_url: str = None,
                       fallback_proxy_urls: List[str] = None) -> tuple[bool, Optional[str], str]:
    """测试 refresh token 是否有效，返回 (是否成功, 错误信息, 新 refresh_token)"""
    try:
        # 尝试使用 Graph API 获取 access token
        # 使用与 get_access_token_graph 相同的 scope，确保一致性
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

        if res.status_code == 200:
            payload = {}
            try:
                payload = res.json()
            except Exception:
                payload = {}
            return True, None, str(payload.get('refresh_token') or '').strip()
        else:
            try:
                error_data = res.json()
            except Exception:
                error_data = {}
            error_msg = error_data.get('error_description', error_data.get('error', '未知错误'))
            return False, error_msg, ''
    except Exception as e:
        return False, f"请求异常: {str(e)}", ''


def refresh_outlook_account_token(account: sqlite3.Row, refresh_type: str = 'manual',
                                  db_conn=None) -> Dict[str, Any]:
    """刷新单个 Outlook 账号的 refresh token 并记录结果。"""
    account_id = account['id']
    account_email = account['email']
    client_id = account['client_id']
    encrypted_refresh_token = account['refresh_token']

    group_id = account['group_id']
    group_row = None
    if db_conn is not None and group_id:
        group_row = db_conn.execute(
            'SELECT proxy_url, fallback_proxy_url_1, fallback_proxy_url_2 FROM groups WHERE id = ?',
            (group_id,)
        ).fetchone()
    if group_row:
        proxy_url = get_group_proxy_url(dict(group_row))
        fallback_proxy_urls = get_group_proxy_failover_urls(dict(group_row))
    else:
        proxy_config = get_account_proxy_config(dict(account))
        proxy_url = proxy_config.get('proxy_url', '') or ''
        fallback_proxy_urls = get_account_proxy_failover_urls(dict(account))

    # 解密 refresh_token
    try:
        refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
    except Exception as e:
        error_msg = sanitize_error_details(f"解密 token 失败: {str(e)}")
        log_refresh_result(account_id, account_email, refresh_type, 'failed', error_msg, db_conn=db_conn)
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

    success, error_msg, rotated_refresh_token = test_refresh_token(
        client_id,
        refresh_token,
        proxy_url,
        fallback_proxy_urls,
    )
    sanitized_error = sanitize_error_details(error_msg) if error_msg else ''

    if success and rotated_refresh_token and rotated_refresh_token != refresh_token:
        persist_rotated_refresh_token(account_id, rotated_refresh_token, db_conn)

    # 记录刷新结果
    log_refresh_result(
        account_id,
        account_email,
        refresh_type,
        'success' if success else 'failed',
        sanitized_error or None,
        db_conn=db_conn
    )

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

    cleanup_refresh_logs()
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

    cleanup_refresh_logs()
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


def load_active_outlook_accounts_for_refresh(db_conn) -> List[sqlite3.Row]:
    cursor = db_conn.execute(
        '''
        SELECT id, email, client_id, refresh_token, group_id, status, account_type, provider
        FROM accounts
        WHERE status = 'active'
          AND COALESCE(account_type, 'outlook') = 'outlook'
        ORDER BY email COLLATE NOCASE ASC
        '''
    )
    return cursor.fetchall()


def load_failed_outlook_accounts_for_refresh(db_conn) -> List[sqlite3.Row]:
    cursor = db_conn.execute(
        '''
        SELECT id, email, client_id, refresh_token, group_id, status, account_type, provider
        FROM accounts
        WHERE status = 'active'
          AND COALESCE(account_type, 'outlook') = 'outlook'
          AND COALESCE(NULLIF(last_refresh_status, ''), 'never') = 'failed'
        ORDER BY last_refresh_at DESC, id DESC
        '''
    )
    return cursor.fetchall()


def get_refresh_delay_seconds(db_conn) -> int:
    row = db_conn.execute(
        "SELECT value FROM settings WHERE key = 'refresh_delay_seconds'"
    ).fetchone()
    try:
        return max(0, min(60, int(row['value']) if row and row['value'] is not None else 5))
    except (TypeError, ValueError):
        return 5


def run_full_refresh(snapshot_trigger_type: str, log_refresh_type: str,
                     progress_callback=None, db_conn=None) -> Dict[str, Any]:
    lock_acquired = False
    owns_connection = db_conn is None
    conn = db_conn or sqlite3.connect(DATABASE)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row
    accounts: List[sqlite3.Row] = []
    delay_seconds = 0
    total = 0
    success_count = 0
    failed_count = 0
    failed_list: List[Dict[str, Any]] = []
    current_account = None
    current_account_counted = False

    try:
        acquire_token_refresh_run_lock()
        lock_acquired = True
        clear_token_refresh_stop_request()
        cleanup_refresh_logs(conn)
        conn.commit()

        accounts = load_active_outlook_accounts_for_refresh(conn)
        delay_seconds = get_refresh_delay_seconds(conn)
        total = len(accounts)

        mark_token_refresh_snapshot_running(snapshot_trigger_type, total, conn)
        conn.commit()

        if progress_callback:
            progress_callback({
                'type': 'start',
                'total': total,
                'delay_seconds': delay_seconds,
                'refresh_type': snapshot_trigger_type,
            })

        for index, account in enumerate(accounts, 1):
            if is_token_refresh_stop_requested():
                stopped_payload = finalize_stopped_full_refresh(
                    conn,
                    snapshot_trigger_type,
                    total,
                    success_count,
                    failed_count,
                    failed_list,
                    delay_seconds
                )
                if progress_callback:
                    progress_callback(stopped_payload)
                return stopped_payload

            current_account = account
            current_account_counted = False
            if progress_callback:
                progress_callback({
                    'type': 'progress',
                    'current': index,
                    'total': total,
                    'account_id': account['id'],
                    'email': account['email'],
                    'success_count': success_count,
                    'failed_count': failed_count,
                })

            result = refresh_outlook_account_token(account, log_refresh_type, db_conn=conn)
            conn.commit()

            if result.get('success'):
                success_count += 1
            else:
                failed_count += 1
                failed_list.append({
                    'id': account['id'],
                    'email': account['email'],
                    'error': result.get('error_message') or '未知错误',
                })
            current_account_counted = True
            if progress_callback:
                progress_callback({
                    'type': 'account_result',
                    'current': index,
                    'total': total,
                    'account_id': account['id'],
                    'email': account['email'],
                    'status': 'success' if result.get('success') else 'failed',
                    'error_message': result.get('error_message') or '',
                    'success_count': success_count,
                    'failed_count': failed_count,
                })
            if is_token_refresh_stop_requested():
                stopped_payload = finalize_stopped_full_refresh(
                    conn,
                    snapshot_trigger_type,
                    total,
                    success_count,
                    failed_count,
                    failed_list,
                    delay_seconds
                )
                if progress_callback:
                    progress_callback(stopped_payload)
                return stopped_payload

            current_account = None

            if index < total and delay_seconds > 0:
                if progress_callback:
                    progress_callback({'type': 'delay', 'seconds': delay_seconds})
                if not wait_refresh_delay(delay_seconds):
                    stopped_payload = finalize_stopped_full_refresh(
                        conn,
                        snapshot_trigger_type,
                        total,
                        success_count,
                        failed_count,
                        failed_list,
                        delay_seconds
                    )
                    if progress_callback:
                        progress_callback(stopped_payload)
                    return stopped_payload

        error_summary = build_refresh_error_summary(failed_list)
        mark_token_refresh_snapshot_finished(
            snapshot_trigger_type,
            total,
            success_count,
            failed_count,
            error_summary,
            conn
        )
        conn.commit()

        result_payload = {
            'type': 'complete',
            'total': total,
            'success_count': success_count,
            'failed_count': failed_count,
            'failed_list': failed_list,
            'delay_seconds': delay_seconds,
            'refresh_type': snapshot_trigger_type,
        }
        if progress_callback:
            progress_callback(result_payload)
        return result_payload
    except TokenRefreshInProgressError:
        raise
    except Exception as exc:
        error_payload = finalize_aborted_full_refresh(
            conn,
            snapshot_trigger_type,
            log_refresh_type,
            total,
            success_count,
            failed_count,
            failed_list,
            current_account=current_account,
            current_account_counted=current_account_counted,
            error=exc
        )
        if progress_callback:
            progress_callback(error_payload)
        raise
    finally:
        if owns_connection:
            conn.close()
        clear_token_refresh_stop_request()
        release_token_refresh_run_lock(lock_acquired)


def stream_full_refresh_events(snapshot_trigger_type: str, log_refresh_type: str):
    import json

    conn = None
    lock_acquired = False
    accounts: List[sqlite3.Row] = []
    delay_seconds = 0
    total = 0
    success_count = 0
    failed_count = 0
    failed_list: List[Dict[str, Any]] = []
    current_account = None
    current_account_counted = False

    try:
        acquire_token_refresh_run_lock()
        lock_acquired = True
        clear_token_refresh_stop_request()
        conn = sqlite3.connect(DATABASE)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.row_factory = sqlite3.Row

        cleanup_refresh_logs(conn)
        conn.commit()

        accounts = load_active_outlook_accounts_for_refresh(conn)
        delay_seconds = get_refresh_delay_seconds(conn)
        total = len(accounts)

        mark_token_refresh_snapshot_running(snapshot_trigger_type, total, conn)
        conn.commit()
        yield f"data: {json.dumps({'type': 'start', 'total': total, 'delay_seconds': delay_seconds, 'refresh_type': snapshot_trigger_type})}\n\n"

        for index, account in enumerate(accounts, 1):
            if is_token_refresh_stop_requested():
                stopped_payload = finalize_stopped_full_refresh(
                    conn,
                    snapshot_trigger_type,
                    total,
                    success_count,
                    failed_count,
                    failed_list,
                    delay_seconds
                )
                yield f"data: {json.dumps(stopped_payload)}\n\n"
                return

            current_account = account
            current_account_counted = False
            yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'account_id': account['id'], 'email': account['email'], 'success_count': success_count, 'failed_count': failed_count})}\n\n"

            result = refresh_outlook_account_token(account, log_refresh_type, db_conn=conn)
            conn.commit()

            if result.get('success'):
                success_count += 1
            else:
                failed_count += 1
                failed_list.append({
                    'id': account['id'],
                    'email': account['email'],
                    'error': result.get('error_message') or '未知错误',
                })
            current_account_counted = True
            yield f"data: {json.dumps({'type': 'account_result', 'current': index, 'total': total, 'account_id': account['id'], 'email': account['email'], 'status': 'success' if result.get('success') else 'failed', 'error_message': result.get('error_message') or '', 'success_count': success_count, 'failed_count': failed_count})}\n\n"
            if is_token_refresh_stop_requested():
                stopped_payload = finalize_stopped_full_refresh(
                    conn,
                    snapshot_trigger_type,
                    total,
                    success_count,
                    failed_count,
                    failed_list,
                    delay_seconds
                )
                yield f"data: {json.dumps(stopped_payload)}\n\n"
                return

            current_account = None

            if index < total and delay_seconds > 0:
                yield f"data: {json.dumps({'type': 'delay', 'seconds': delay_seconds})}\n\n"
                if not wait_refresh_delay(delay_seconds):
                    stopped_payload = finalize_stopped_full_refresh(
                        conn,
                        snapshot_trigger_type,
                        total,
                        success_count,
                        failed_count,
                        failed_list,
                        delay_seconds
                    )
                    yield f"data: {json.dumps(stopped_payload)}\n\n"
                    return

        error_summary = build_refresh_error_summary(failed_list)
        mark_token_refresh_snapshot_finished(
            snapshot_trigger_type,
            total,
            success_count,
            failed_count,
            error_summary,
            conn
        )
        conn.commit()
        yield f"data: {json.dumps({'type': 'complete', 'total': total, 'success_count': success_count, 'failed_count': failed_count, 'failed_list': failed_list, 'delay_seconds': delay_seconds, 'refresh_type': snapshot_trigger_type})}\n\n"
    except TokenRefreshInProgressError as exc:
        yield f"data: {json.dumps({'type': 'conflict', 'message': str(exc), 'refresh_type': snapshot_trigger_type})}\n\n"
    except Exception as exc:
        if conn is not None:
            error_payload = finalize_aborted_full_refresh(
                conn,
                snapshot_trigger_type,
                log_refresh_type,
                total,
                success_count,
                failed_count,
                failed_list,
                current_account=current_account,
                current_account_counted=current_account_counted,
                error=exc
            )
            yield f"data: {json.dumps(error_payload)}\n\n"
        else:
            failure_message = sanitize_error_details(str(exc)) or '未知错误'
            yield f"data: {json.dumps({'type': 'error', 'message': failure_message, 'refresh_type': snapshot_trigger_type})}\n\n"
    finally:
        if conn is not None:
            conn.close()
        clear_token_refresh_stop_request()
        release_token_refresh_run_lock(lock_acquired)


def stream_failed_refresh_events():
    import json

    conn = None
    lock_acquired = False
    accounts: List[sqlite3.Row] = []
    delay_seconds = 0
    total = 0
    success_count = 0
    failed_count = 0
    failed_list: List[Dict[str, Any]] = []
    current_account = None
    current_account_counted = False

    try:
        acquire_token_refresh_run_lock()
        lock_acquired = True
        clear_token_refresh_stop_request()
        conn = sqlite3.connect(DATABASE)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.row_factory = sqlite3.Row

        cleanup_refresh_logs(conn)
        conn.commit()

        accounts = load_failed_outlook_accounts_for_refresh(conn)
        delay_seconds = get_refresh_delay_seconds(conn)
        total = len(accounts)

        yield f"data: {json.dumps({'type': 'start', 'total': total, 'delay_seconds': delay_seconds, 'refresh_type': 'retry_failed'})}\n\n"

        for index, account in enumerate(accounts, 1):
            if is_token_refresh_stop_requested():
                yield f"data: {json.dumps(build_stopped_refresh_payload(total, success_count, failed_count, failed_list, delay_seconds=delay_seconds, refresh_type='retry_failed'))}\n\n"
                return

            current_account = account
            current_account_counted = False
            yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'account_id': account['id'], 'email': account['email'], 'success_count': success_count, 'failed_count': failed_count})}\n\n"

            result = refresh_outlook_account_token(account, 'retry', db_conn=conn)
            conn.commit()

            if result.get('success'):
                success_count += 1
            else:
                failed_count += 1
                failed_list.append({
                    'id': account['id'],
                    'email': account['email'],
                    'error': result.get('error_message') or '未知错误',
                })
            current_account_counted = True

            yield f"data: {json.dumps({'type': 'account_result', 'current': index, 'total': total, 'account_id': account['id'], 'email': account['email'], 'status': 'success' if result.get('success') else 'failed', 'error_message': result.get('error_message') or '', 'success_count': success_count, 'failed_count': failed_count})}\n\n"

            if is_token_refresh_stop_requested():
                yield f"data: {json.dumps(build_stopped_refresh_payload(total, success_count, failed_count, failed_list, delay_seconds=delay_seconds, refresh_type='retry_failed'))}\n\n"
                return

            current_account = None

            if index < total and delay_seconds > 0:
                yield f"data: {json.dumps({'type': 'delay', 'seconds': delay_seconds, 'refresh_type': 'retry_failed'})}\n\n"
                if not wait_refresh_delay(delay_seconds):
                    yield f"data: {json.dumps(build_stopped_refresh_payload(total, success_count, failed_count, failed_list, delay_seconds=delay_seconds, refresh_type='retry_failed'))}\n\n"
                    return

        yield f"data: {json.dumps({'type': 'complete', 'total': total, 'success_count': success_count, 'failed_count': failed_count, 'failed_list': failed_list, 'delay_seconds': delay_seconds, 'refresh_type': 'retry_failed'})}\n\n"
    except TokenRefreshInProgressError as exc:
        yield f"data: {json.dumps({'type': 'conflict', 'message': str(exc), 'refresh_type': 'retry_failed'})}\n\n"
    except Exception as exc:
        if conn is not None:
            error_payload = finalize_aborted_retry_refresh(
                conn,
                'retry',
                total,
                success_count,
                failed_count,
                failed_list,
                current_account=current_account,
                current_account_counted=current_account_counted,
                error=exc
            )
            yield f"data: {json.dumps(error_payload)}\n\n"
        else:
            failure_message = sanitize_error_details(str(exc)) or '未知错误'
            yield f"data: {json.dumps({'type': 'error', 'message': failure_message, 'refresh_type': 'retry_failed'})}\n\n"
    finally:
        if conn is not None:
            conn.close()
        clear_token_refresh_stop_request()
        release_token_refresh_run_lock(lock_acquired)


@app.route('/api/accounts/refresh-all', methods=['GET'])
@login_required
def api_refresh_all_accounts():
    """刷新所有账号的 token（流式响应，实时返回进度）"""
    return Response(stream_full_refresh_events('manual_all', 'manual'), mimetype='text/event-stream')


@app.route('/api/accounts/<int:account_id>/retry-refresh', methods=['POST'])
@login_required
def api_retry_refresh_account(account_id):
    """重试单个失败账号的刷新"""
    return api_refresh_account(account_id)


@app.route('/api/accounts/refresh-failed-stream', methods=['GET'])
@login_required
def api_refresh_failed_accounts_stream():
    """流式重试所有失败账号"""
    return Response(stream_failed_refresh_events(), mimetype='text/event-stream')


@app.route('/api/accounts/refresh-failed', methods=['POST'])
@login_required
def api_refresh_failed_accounts():
    """重试所有失败的账号"""
    cleanup_refresh_logs()
    db = get_db()
    accounts = load_failed_outlook_accounts_for_refresh(db)

    success_count = 0
    failed_count = 0
    failed_list = []

    for account in accounts:
        result = refresh_outlook_account_token(account, 'retry')
        if result['success']:
            success_count += 1
        else:
            failed_count += 1
            failed_list.append({
                'id': account['id'],
                'email': account['email'],
                'error': result.get('error_message') or '未知错误'
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

    last_refresh = build_refresh_stats(get_db()).get('last_refresh_time')

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
    snapshot_type = 'manual_all' if force else 'scheduled'
    log_type = 'manual' if force else 'scheduled'
    return Response(stream_full_refresh_events(snapshot_type, log_type), mimetype='text/event-stream')


@app.route('/api/accounts/stop-full-refresh', methods=['POST'])
@login_required
def api_stop_full_refresh():
    """请求停止当前全量刷新任务。"""
    if not token_refresh_run_lock.locked():
        clear_token_refresh_stop_request()
        return jsonify({
            'success': False,
            'message': '当前没有进行中的全量刷新任务'
        }), 409

    request_token_refresh_stop()
    return jsonify({
        'success': True,
        'message': TOKEN_REFRESH_STOP_REQUESTED_MESSAGE,
    })


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

    cursor = db.execute('''
        SELECT
            a.id AS account_id,
            a.email AS account_email,
            a.status AS account_status,
            a.last_refresh_status AS status,
            a.last_refresh_error AS error_message,
            a.last_refresh_at AS created_at
        FROM accounts a
        WHERE a.status = 'active'
          AND COALESCE(a.account_type, 'outlook') = 'outlook'
          AND COALESCE(NULLIF(a.last_refresh_status, ''), 'never') = 'failed'
        ORDER BY a.last_refresh_at DESC, a.id DESC
    ''')

    logs = []
    for row in cursor.fetchall():
        logs.append({
            'id': row['account_id'],
            'account_id': row['account_id'],
            'account_email': row['account_email'],
            'account_status': row['account_status'],
            'refresh_type': 'latest',
            'status': row['status'] or 'failed',
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
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'}), 404
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

    return jsonify({
        'success': True,
        'logs': logs,
        'account': {
            'id': account['id'],
            'email': account.get('email', ''),
            'status': account.get('status', 'active'),
            'forward_enabled': bool(account.get('forward_enabled')),
            'forward_last_checked_at': account.get('forward_last_checked_at', ''),
        }
    })


@app.route('/api/accounts/refresh-stats', methods=['GET'])
@login_required
def api_get_refresh_stats():
    """获取刷新统计信息（统计当前失败状态的邮箱数量）"""
    return jsonify({'success': True, 'stats': build_refresh_stats()})


@app.route('/api/accounts/refresh-status-list', methods=['GET'])
@login_required
def api_get_refresh_status_list():
    """获取 Token 刷新管理所需的账号状态列表。"""
    q = request.args.get('q', '')
    status = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 100, type=int)

    payload = query_refreshable_accounts(
        get_db(),
        search=q,
        refresh_status=status,
        page=page,
        page_size=page_size,
    )
    payload['stats'] = build_refresh_stats(get_db())
    return jsonify({'success': True, **payload})


# ==================== 邮件 API ====================



# ==================== Email Deletion Helpers ====================

def delete_emails_graph(client_id: str, refresh_token: str, message_ids: List[str], proxy_url: str = None,
                        fallback_proxy_urls: List[str] = None) -> Dict[str, Any]:
    """通过 Graph API 批量删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url, fallback_proxy_urls)
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
            response = request_with_proxy_failover(
                'post',
                "https://graph.microsoft.com/v1.0/$batch",
                headers=headers,
                json={"requests": batch_requests},
                timeout=30,
                proxy_url=proxy_url,
                fallback_proxy_urls=fallback_proxy_urls,
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
                       proxy_url: str = None, fallback_proxy_urls: List[str] = None) -> Dict[str, Any]:
    """通过 IMAP 删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url, fallback_proxy_urls)
    if not access_token:
        return {"success": False, "error": "获取 Access Token 失败"}
        
    try:
        # 生成 OAuth2 认证字符串
        auth_string = 'user=%s\x01auth=Bearer %s\x01\x01' % (email_addr, access_token)
        
        # 连接 IMAP
        with proxy_socket_context(proxy_url):
            imap = imaplib.IMAP4_SSL(server, IMAP_PORT, timeout=IMAP_TIMEOUT)
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


def normalize_email_action_items(raw_items: Any, fallback_folder: str = 'inbox') -> List[Dict[str, str]]:
    normalized_items: List[Dict[str, str]] = []
    for raw_item in raw_items or []:
        if isinstance(raw_item, dict):
            message_id = str(raw_item.get('id') or raw_item.get('message_id') or '').strip()
            folder = normalize_folder_name(raw_item.get('folder', fallback_folder))
            id_mode = str(raw_item.get('id_mode') or '').strip().lower()
        else:
            message_id = str(raw_item or '').strip()
            folder = normalize_folder_name(fallback_folder)
            id_mode = ''

        if not message_id:
            continue

        normalized_items.append({
            'id': message_id,
            'folder': folder,
            'id_mode': id_mode,
        })
    return normalized_items


def merge_email_action_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged_updated_ids: List[str] = []
    merged_errors: List[Any] = []
    success_count = 0
    failed_count = 0

    for result in results or []:
        success_count += int(result.get('success_count', 0) or 0)
        failed_count += int(result.get('failed_count', 0) or 0)
        merged_updated_ids.extend([str(item) for item in (result.get('updated_ids') or []) if str(item)])
        merged_errors.extend(result.get('errors') or [])

    deduped_updated_ids = list(dict.fromkeys(merged_updated_ids))
    merged_result = {
        'success': failed_count == 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'updated_ids': deduped_updated_ids,
        'errors': merged_errors,
    }
    if merged_errors:
        merged_result['error'] = merged_errors[0]
    return merged_result


def normalize_email_list_item(item: Dict[str, Any], folder: str) -> Dict[str, Any]:
    row = dict(item or {})
    row['subject'] = row.get('subject', '无主题')
    row['from'] = row.get('from', '未知')
    row['to'] = str(row.get('to', '') or '')
    row['date'] = row.get('date', '')
    row['is_read'] = bool(row.get('is_read', False))
    row['has_attachments'] = bool(row.get('has_attachments', False))
    row['body_preview'] = row.get('body_preview', '')
    row['folder'] = row.get('folder') or folder
    row['id_mode'] = row.get('id_mode', '')
    return row


def format_graph_email_item(item: Dict[str, Any], folder: str) -> Dict[str, Any]:
    return normalize_email_list_item({
        'id': item.get('id'),
        'subject': item.get('subject', '无主题'),
        'from': item.get('from', {}).get('emailAddress', {}).get('address', '未知'),
        'to': ', '.join([
            recipient.get('emailAddress', {}).get('address', '')
            for recipient in (item.get('toRecipients') or [])
            if recipient.get('emailAddress', {}).get('address', '')
        ]),
        'date': item.get('receivedDateTime', ''),
        'is_read': item.get('isRead', False),
        'has_attachments': item.get('hasAttachments', False),
        'body_preview': item.get('bodyPreview', ''),
        'folder': folder,
        'id_mode': 'graph',
    }, folder)


def format_email_items(items: List[Dict[str, Any]], folder: str) -> List[Dict[str, Any]]:
    return [normalize_email_list_item(item, folder) for item in items]


def is_transport_error_payload(error_payload: Any) -> bool:
    if not isinstance(error_payload, dict):
        return False
    error_type = str(error_payload.get('type') or '').strip()
    return error_type in {
        'ProxyError',
        'ConnectionError',
        'ConnectTimeout',
        'ReadTimeout',
        'Timeout',
    }


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
    folder_summaries = {}
    for folder, result in results.items():
        folder_summary = {
            'success': bool(result.get('success')),
            'fetched_count': len(result.get('emails', [])) if result.get('success') else 0,
            'has_more': bool(result.get('has_more')) if result.get('success') else False,
        }
        request_method = str(result.get('request_method') or '').strip().lower()
        if request_method in {'graph', 'imap'}:
            folder_summary['request_method'] = request_method
        if result.get('method'):
            folder_summary['method'] = result['method']
        if not result.get('success') and result.get('error') is not None:
            folder_summary['error'] = result.get('error')
        folder_summaries[folder] = folder_summary

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
        'folder_summaries': folder_summaries,
    }
    if partial_errors:
        response['partial'] = True
        response['details'] = partial_errors
    return response


def fetch_account_folder_emails(account: Dict[str, Any], folder: str, skip: int, top: int,
                                proxy_url: str = '', fallback_proxy_urls: List[str] = None) -> Dict[str, Any]:
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
                'request_method': 'imap',
            }
        return {
            'success': False,
            'error': result.get('error', '获取邮件失败'),
            'details': {'imap_generic': result.get('error')}
        }

    all_errors = {}
    graph_result = get_emails_graph(
        account['client_id'],
        account['refresh_token'],
        folder_name,
        skip,
        top,
        proxy_url,
        fallback_proxy_urls,
    )
    if graph_result.get('success'):
        return {
            'success': True,
            'emails': [format_graph_email_item(item, folder_name) for item in graph_result.get('emails', [])],
            'method': 'Graph API',
            'has_more': len(graph_result.get('emails', [])) >= top,
            'request_method': 'graph',
        }

    graph_error = graph_result.get('error')
    all_errors['graph'] = graph_error
    if is_transport_error_payload(graph_error):
        connection_error_message = (
            '代理连接失败或请求超时，请检查分组代理设置'
            if proxy_url
            else '连接 Microsoft 服务失败或超时，请检查服务器网络、DNS 或上游访问能力'
        )
        return {
            'success': False,
            'error': connection_error_message,
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
        proxy_url,
        fallback_proxy_urls,
    )
    if imap_new_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_new_result.get('emails', []), folder_name),
            'method': 'IMAP (New)',
            'has_more': bool(imap_new_result.get('has_more')),
            'request_method': 'imap',
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
        proxy_url,
        fallback_proxy_urls,
    )
    if imap_old_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_old_result.get('emails', []), folder_name),
            'method': 'IMAP (Old)',
            'has_more': bool(imap_old_result.get('has_more')),
            'request_method': 'imap',
        }
    all_errors['imap_old'] = imap_old_result.get('error')

    return {
        'success': False,
        'error': '无法获取邮件，所有方式均失败',
        'details': all_errors
    }


def fetch_account_emails(account: Dict[str, Any], folder: str, skip: int, top: int) -> Dict[str, Any]:
    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)
    folder_name = normalize_folder_name(folder)
    if folder_name not in VALID_MAIL_FOLDERS:
        return {
            'success': False,
            'error': f'folder 参数无效，支持: {", ".join(sorted(VALID_MAIL_FOLDERS))}'
        }

    if folder_name == 'all':
        merged_top = max(1, min(100, top * 2))
        folder_jobs = ('inbox', 'junkemail')
        results = {}
        executor = ThreadPoolExecutor(max_workers=len(folder_jobs), thread_name_prefix='mail-folder-fetch')
        future_map = {
            folder_job: executor.submit(
                fetch_account_folder_emails,
                account,
                folder_job,
                skip,
                top,
                proxy_url,
                fallback_proxy_urls,
            )
            for folder_job in folder_jobs
        }
        try:
            done, not_done = wait(future_map.values(), timeout=MAIL_FETCH_OVERALL_TIMEOUT)
            for folder_job, future in future_map.items():
                if future in done:
                    try:
                        results[folder_job] = future.result()
                    except Exception as exc:
                        results[folder_job] = {
                            'success': False,
                            'error': build_error_payload(
                                'EMAIL_FETCH_FAILED',
                                '获取邮件失败，请检查账号配置',
                                type(exc).__name__,
                                500,
                                str(exc)
                            )
                        }
                    continue

                future.cancel()
                results[folder_job] = {
                    'success': False,
                    'error': build_error_payload(
                        'EMAIL_FETCH_TIMEOUT',
                        '获取邮件超时，请稍后重试',
                        'TimeoutError',
                        504,
                        f'folder={folder_job}, timeout={MAIL_FETCH_OVERALL_TIMEOUT}s'
                    )
                }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return merge_folder_results(
            results,
            0,
            merged_top
        )

    return fetch_account_folder_emails(account, folder_name, skip, top, proxy_url, fallback_proxy_urls)


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
    return jsonify(result)


@app.route('/api/emails/mark-read', methods=['POST'])
@login_required
def api_mark_emails_read():
    """批量标记邮件为已读"""
    data = request.json or {}
    email_addr = str(data.get('email') or '').strip()
    method = str(data.get('method') or 'graph').strip().lower()
    fallback_folder = normalize_folder_name(data.get('folder', 'inbox'))
    raw_items = data.get('items')
    if raw_items is None:
        raw_items = data.get('ids', [])

    items = normalize_email_action_items(raw_items, fallback_folder)
    if not email_addr or not items:
        return jsonify({'success': False, 'error': '参数不完整'})

    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})

    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)

    if account.get('account_type') == 'imap':
        result = mark_emails_read_imap_generic_result(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            items,
            account.get('imap_port', 993),
            account.get('provider', 'custom'),
            proxy_url
        )
        return jsonify(result)

    graph_items = []
    imap_items = []
    for item in items:
        id_mode = str(item.get('id_mode') or '').strip().lower()
        if id_mode == 'graph':
            graph_items.append(item)
        elif id_mode in {'uid', 'sequence'}:
            imap_items.append(item)
        elif method == 'graph':
            graph_items.append(item)
        else:
            imap_items.append(item)

    results = []
    if graph_items:
        results.append(mark_emails_read_graph_result(
            account['client_id'],
            account['refresh_token'],
            [item['id'] for item in graph_items],
            proxy_url,
            fallback_proxy_urls,
        ))

    if imap_items:
        imap_result = mark_emails_read_imap_batch(
            account['email'],
            account['client_id'],
            account['refresh_token'],
            imap_items,
            IMAP_SERVER_NEW,
            proxy_url,
            fallback_proxy_urls,
        )
        if not imap_result.get('success') and imap_result.get('success_count', 0) == 0:
            imap_result = mark_emails_read_imap_batch(
                account['email'],
                account['client_id'],
                account['refresh_token'],
                imap_items,
                IMAP_SERVER_OLD,
                proxy_url,
                fallback_proxy_urls,
            )
        results.append(imap_result)

    return jsonify(merge_email_action_results(results))

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
    fallback_proxy_urls = get_account_proxy_failover_urls(account)

    # 1. 优先尝试 Graph API
    if account.get('account_type') == 'imap':
        return jsonify({'success': False, 'error': 'IMAP 账号暂不支持批量删除邮件'})

    graph_res = delete_emails_graph(account['client_id'], account['refresh_token'], message_ids, proxy_url, fallback_proxy_urls)
    if graph_res['success']:
        return jsonify(graph_res)

    # 如果是代理错误，不再回退 IMAP
    graph_error = graph_res.get('error', '')
    if isinstance(graph_error, str) and 'ProxyError' in graph_error:
        return jsonify(graph_res)
    
    # 2. 尝试 IMAP 回退（新服务器）
    imap_res = delete_emails_imap(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        message_ids,
        IMAP_SERVER_NEW,
        proxy_url,
        fallback_proxy_urls,
    )
    if imap_res['success']:
        return jsonify(imap_res)

    # 3. 尝试 IMAP 回退（旧服务器）
    imap_old_res = delete_emails_imap(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        message_ids,
        IMAP_SERVER_OLD,
        proxy_url,
        fallback_proxy_urls,
    )
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
    fallback_proxy_urls = get_account_proxy_failover_urls(account)

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
        detail = get_email_detail_graph(
            account['client_id'],
            account['refresh_token'],
            message_id,
            proxy_url,
            fallback_proxy_urls,
        )
        if detail:
            attachments = []
            if detail.get('hasAttachments'):
                attachments = get_email_attachments_graph(
                    account['client_id'],
                    account['refresh_token'],
                    message_id,
                    proxy_url,
                    fallback_proxy_urls,
                ) or []
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
                    'body_type': detail.get('body', {}).get('contentType', 'text'),
                    'attachments': attachments,
                }
            })

    # 如果 Graph API 失败，尝试 IMAP
    detail = get_email_detail_imap(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        message_id,
        folder,
        proxy_url,
        fallback_proxy_urls,
    )
    if detail:
        return jsonify({'success': True, 'email': detail})

    return jsonify({'success': False, 'error': '获取邮件详情失败'})


def download_email_attachment_for_account(account, method, message_id, attachment_id, folder, proxy_url, fallback_proxy_urls):
    if account.get('account_type') == 'imap':
        return download_email_attachment_imap_generic_result(
            account['email'],
            account.get('imap_password', ''),
            account.get('imap_host', ''),
            account.get('imap_port', 993),
            message_id,
            attachment_id,
            folder,
            account.get('provider', 'custom'),
            proxy_url
        )

    if method == 'graph':
        return download_email_attachment_graph_result(
            account['client_id'],
            account['refresh_token'],
            message_id,
            attachment_id,
            proxy_url,
            fallback_proxy_urls,
        )

    return download_email_attachment_imap_result(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        message_id,
        attachment_id,
        folder,
        proxy_url,
        fallback_proxy_urls,
    )


def get_email_attachment_metadata_for_download(account, method, message_id, folder, proxy_url, fallback_proxy_urls):
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
            return {'success': True, 'attachments': detail_result.get('email', {}).get('attachments', [])}
        return {'success': False, 'error': detail_result.get('error', '获取附件列表失败')}

    if method == 'graph':
        attachments = get_email_attachments_graph(
            account['client_id'],
            account['refresh_token'],
            message_id,
            proxy_url,
            fallback_proxy_urls,
        )
        if attachments is None:
            return {'success': False, 'error': '获取附件列表失败'}
        return {'success': True, 'attachments': attachments}

    detail = get_email_detail_imap(
        account['email'],
        account['client_id'],
        account['refresh_token'],
        message_id,
        folder,
        proxy_url,
        fallback_proxy_urls,
    )
    if detail:
        return {'success': True, 'attachments': detail.get('attachments', [])}
    return {'success': False, 'error': '获取附件列表失败'}


def build_zip_attachment_name(filename, used_names):
    filename = sanitize_attachment_filename(filename, 'attachment')
    name_root, dot, extension = filename.rpartition('.')
    if not dot or not name_root:
        name_root = filename
        extension = ''

    candidate = filename
    counter = 2
    while candidate in used_names:
        suffix = f" ({counter})"
        candidate = f"{name_root}{suffix}.{extension}" if extension else f"{name_root}{suffix}"
        counter += 1
    used_names.add(candidate)
    return candidate


ZIP_STREAM_CHUNK_SIZE = 64 * 1024


class StreamingZipBuffer:
    def __init__(self):
        self._position = 0
        self._chunks = []

    def write(self, data):
        if not data:
            return 0
        chunk = bytes(data)
        self._chunks.append(chunk)
        self._position += len(chunk)
        return len(chunk)

    def tell(self):
        return self._position

    def seek(self, *_args, **_kwargs):
        raise OSError('streaming zip buffer does not support seek')

    def flush(self):
        pass

    def drain(self):
        chunks = self._chunks
        self._chunks = []
        return chunks


def iter_zip_content_chunks(content, chunk_size=ZIP_STREAM_CHUNK_SIZE):
    if isinstance(content, str):
        content = content.encode('utf-8')
    content = content or b''
    for offset in range(0, len(content), chunk_size):
        yield content[offset:offset + chunk_size]


def drain_streaming_zip_buffer(zip_buffer):
    for chunk in zip_buffer.drain():
        if chunk:
            yield chunk


def stringify_attachment_download_error(error):
    if isinstance(error, dict):
        return str(error.get('message') or error.get('code') or error)
    return str(error or '获取附件失败')


def stream_email_attachments_zip(account, method, message_id, attachments, folder, proxy_url, fallback_proxy_urls):
    import zipfile

    zip_buffer = StreamingZipBuffer()
    used_names = set()
    error_lines = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for attachment in attachments:
            result = download_email_attachment_for_account(
                account,
                method,
                message_id,
                attachment.get('id'),
                folder,
                proxy_url,
                fallback_proxy_urls,
            )
            if not result.get('success'):
                attachment_name = sanitize_attachment_filename(
                    attachment.get('name', ''),
                    str(attachment.get('id') or 'attachment')
                )
                error_lines.append(f"{attachment_name}: {stringify_attachment_download_error(result.get('error'))}")
                continue

            zip_name = build_zip_attachment_name(
                result.get('filename') or attachment.get('name') or 'attachment',
                used_names
            )
            content = result.get('content', b'') or b''
            with archive.open(zip_name, 'w') as entry:
                yield from drain_streaming_zip_buffer(zip_buffer)
                for chunk in iter_zip_content_chunks(content):
                    entry.write(chunk)
                    yield from drain_streaming_zip_buffer(zip_buffer)
            yield from drain_streaming_zip_buffer(zip_buffer)

        if error_lines:
            error_name = build_zip_attachment_name('download-errors.txt', used_names)
            error_content = '\n'.join(error_lines)
            with archive.open(error_name, 'w') as entry:
                yield from drain_streaming_zip_buffer(zip_buffer)
                for chunk in iter_zip_content_chunks(error_content):
                    entry.write(chunk)
                    yield from drain_streaming_zip_buffer(zip_buffer)
            yield from drain_streaming_zip_buffer(zip_buffer)

    yield from drain_streaming_zip_buffer(zip_buffer)


@app.route('/api/email/<email_addr>/<path:message_id>/attachments/download-all')
@login_required
def api_download_all_email_attachments(email_addr, message_id):
    """打包下载邮件所有附件"""
    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})

    method = request.args.get('method', 'graph')
    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)
    metadata_result = get_email_attachment_metadata_for_download(
        account,
        method,
        message_id,
        folder,
        proxy_url,
        fallback_proxy_urls,
    )
    if not metadata_result.get('success'):
        return jsonify({'success': False, 'error': metadata_result.get('error', '获取附件列表失败')})

    attachments = [attachment for attachment in metadata_result.get('attachments', []) if attachment.get('id')]
    if not attachments:
        return jsonify({'success': False, 'error': '没有可下载附件'})

    response = Response(
        stream_email_attachments_zip(
            account,
            method,
            message_id,
            attachments,
            folder,
            proxy_url,
            fallback_proxy_urls,
        ),
        mimetype='application/zip'
    )
    response.headers['Content-Disposition'] = "attachment; filename*=UTF-8''attachments.zip"
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/email/<email_addr>/<path:message_id>/attachments/<path:attachment_id>')
@login_required
def api_download_email_attachment(email_addr, message_id, attachment_id):
    """下载邮件附件"""
    account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})

    method = request.args.get('method', 'graph')
    folder = normalize_folder_name(request.args.get('folder', 'inbox'))
    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)
    result = download_email_attachment_for_account(
        account,
        method,
        message_id,
        attachment_id,
        folder,
        proxy_url,
        fallback_proxy_urls,
    )

    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('error', '获取附件失败')})

    filename = sanitize_attachment_filename(result.get('filename', ''), 'attachment')
    encoded_filename = quote(filename)
    content_type = result.get('content_type', 'application/octet-stream') or 'application/octet-stream'
    response = Response(result.get('content', b''), mimetype=content_type)
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return response
