from __future__ import annotations

import os
import sqlite3
import threading
import time

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    # These segmented files are executed into the shared `web_outlook_app`
    # globals at runtime. Importing from the assembled module keeps IDE
    # inspections from flagging the shared names as unresolved.
    from web_outlook_app import *  # noqa: F403


# ==================== OAuth Token API ====================

def extract_oauth_authorization_code(redirected_url: str) -> tuple[bool, str, str]:
    """从 OAuth 回调 URL 提取授权码。"""
    import urllib.parse

    normalized_url = str(redirected_url or '').strip()
    if not normalized_url:
        return False, '', '请提供授权后的完整 URL'

    try:
        parsed_url = urllib.parse.urlparse(normalized_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        auth_code = str(query_params['code'][0] or '').strip()
    except (KeyError, IndexError):
        return False, '', '无法从 URL 中提取授权码，请检查 URL 是否正确'

    if not auth_code:
        return False, '', '无法从 URL 中提取授权码，请检查 URL 是否正确'
    return True, auth_code, ''


def exchange_oauth_code_for_tokens(redirected_url: str) -> Dict[str, Any]:
    """使用授权后的回调 URL 换取 Microsoft OAuth token。"""
    success, auth_code, error_message = extract_oauth_authorization_code(redirected_url)
    if not success:
        return {'success': False, 'error': error_message}

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
        return {'success': False, 'error': f'请求失败: {sanitize_error_details(str(e))}'}

    if response.status_code != 200:
        try:
            error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        except Exception:
            error_data = {}
        error_msg = error_data.get('error_description', response.text)
        return {'success': False, 'error': f'获取令牌失败: {sanitize_error_details(error_msg)}'}

    tokens = response.json()
    refresh_token = str(tokens.get('refresh_token') or '').strip()
    if not refresh_token:
        return {'success': False, 'error': '未能获取 Refresh Token'}

    return {
        'success': True,
        'refresh_token': refresh_token,
        'client_id': OAUTH_CLIENT_ID,
        'token_type': tokens.get('token_type'),
        'expires_in': tokens.get('expires_in'),
        'scope': tokens.get('scope')
    }


def update_account_authorization_for_reauth(account_id: int, client_id: str, refresh_token: str, db_conn=None) -> bool:
    """只更新已有 Outlook 账号的授权字段，并清理旧刷新失败状态。"""
    token_value = str(refresh_token or '').strip()
    client_id_value = str(client_id or '').strip()
    if not token_value or not client_id_value:
        return False

    db = db_conn or get_db()
    should_commit = db_conn is None
    try:
        db.execute(
            '''
            UPDATE accounts
            SET client_id = ?,
                refresh_token = ?,
                refresh_token_updated_at = CURRENT_TIMESTAMP,
                last_refresh_status = 'never',
                last_refresh_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (client_id_value, encrypt_data(token_value), account_id)
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
        print(f"更新账号重新授权信息失败: {sanitize_error_details(str(e))}")
        return False


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
    data = request.get_json(silent=True) or {}
    token_result = exchange_oauth_code_for_tokens(data.get('redirected_url', ''))
    return jsonify(token_result)


@app.route('/api/accounts/<int:account_id>/reauthorize', methods=['POST'])
@login_required
def api_reauthorize_account(account_id):
    """为已有 Outlook 账号重新授权，并立即执行一次刷新验证。"""
    db = get_db()
    account = db.execute(
        '''
        SELECT id, email, client_id, refresh_token, group_id, account_type, provider
        FROM accounts
        WHERE id = ?
        ''',
        (account_id,)
    ).fetchone()

    if not account:
        return jsonify({
            'success': False,
            'error': build_error_payload(
                "ACCOUNT_NOT_FOUND",
                "账号不存在",
                "NotFoundError",
                404,
                f"account_id={account_id}"
            )
        }), 404

    if (account['account_type'] or 'outlook').strip().lower() == 'imap':
        return jsonify({
            'success': False,
            'error': build_error_payload(
                "ACCOUNT_REAUTH_UNSUPPORTED",
                "IMAP 账号不支持重新授权",
                "UnsupportedAccountTypeError",
                400,
                f"account_id={account_id}"
            )
        }), 400

    data = request.get_json(silent=True) or {}
    token_result = exchange_oauth_code_for_tokens(data.get('redirected_url', ''))
    if not token_result.get('success'):
        return jsonify({
            'success': False,
            'error': build_error_payload(
                "OAUTH_EXCHANGE_FAILED",
                "重新授权失败",
                "OAuthExchangeError",
                400,
                token_result.get('error') or '未知错误'
            )
        }), 400

    if not update_account_authorization_for_reauth(
        account_id,
        token_result.get('client_id', ''),
        token_result.get('refresh_token', ''),
        db
    ):
        db.rollback()
        return jsonify({
            'success': False,
            'error': build_error_payload(
                "ACCOUNT_REAUTH_SAVE_FAILED",
                "保存重新授权信息失败",
                "DatabaseError",
                500,
                f"account_id={account_id}"
            )
        }), 500

    db.commit()

    refreshed_account = db.execute(
        '''
        SELECT id, email, client_id, refresh_token, group_id, account_type, provider
        FROM accounts
        WHERE id = ?
        ''',
        (account_id,)
    ).fetchone()
    validation_result = refresh_outlook_account_token(refreshed_account, 'reauthorize', db_conn=db)
    db.commit()

    if validation_result.get('success'):
        return jsonify({
            'success': True,
            'message': '重新授权成功，Token 刷新验证通过',
            'authorization_updated': True,
            'validation': {
                'success': True,
                'status': 'success',
                'message': validation_result.get('message') or 'Token 刷新成功'
            }
        })

    return jsonify({
        'success': True,
        'message': '重新授权已保存，但自动刷新验证失败',
        'authorization_updated': True,
        'validation': {
            'success': False,
            'status': 'failed',
            'error': validation_result.get('error_payload'),
            'error_message': validation_result.get('error_message') or '未知错误'
        }
    })


# ==================== 设置 API ====================

WEBDAV_BACKUP_SETTING_KEYS = (
    'webdav_backup_enabled',
    'webdav_backup_url',
    'webdav_backup_username',
    'webdav_backup_password',
    'webdav_backup_cron',
)


def normalize_bool_setting_value(value) -> str:
    return 'true' if str(value).strip().lower() in ('1', 'true', 'yes', 'on') else 'false'


def normalize_webdav_backup_setting_value(key: str, value) -> str:
    if key == 'webdav_backup_enabled':
        return normalize_bool_setting_value(value)
    return str(value or '').strip()


def get_current_webdav_backup_setting_value(key: str) -> str:
    if key == 'webdav_backup_password':
        return get_setting_decrypted(key, '')
    if key == 'webdav_backup_enabled':
        return normalize_bool_setting_value(get_setting(key, 'false'))
    if key == 'webdav_backup_cron':
        return get_setting(key, '0 3 * * *')
    return get_setting(key, '')


def has_webdav_backup_setting_changes(data) -> bool:
    for key in WEBDAV_BACKUP_SETTING_KEYS:
        if key not in data:
            continue
        incoming_value = normalize_webdav_backup_setting_value(key, data.get(key))
        current_value = normalize_webdav_backup_setting_value(key, get_current_webdav_backup_setting_value(key))
        if incoming_value != current_value:
            return True
    return False


def validate_cron_expression_for_timezone(cron_expr: str, time_zone: str):
    if not cron_expr:
        return 'Cron 表达式不能为空'
    if not is_valid_app_timezone_name(time_zone):
        return 'Invalid time zone'
    try:
        from croniter import croniter
        from datetime import datetime
        croniter(cron_expr, datetime.now(ZoneInfo(time_zone)))
        return None
    except ImportError:
        return 'croniter 库未安装'
    except Exception as exc:
        return f'Cron 表达式无效: {str(exc)}'


def validate_five_field_cron_expression_for_timezone(cron_expr: str, time_zone: str):
    normalized = str(cron_expr or '').strip()
    if not normalized:
        return 'Cron 表达式不能为空'
    if len(normalized.split()) != 5:
        return '仅支持 5 段 Cron'
    return validate_cron_expression_for_timezone(normalized, time_zone)


def build_cron_preview(cron_expr: str, time_zone: str, count: int = 5):
    from croniter import croniter
    from datetime import datetime

    tzinfo = ZoneInfo(time_zone)
    base_time = datetime.now(tzinfo)
    cron = croniter(cron_expr, base_time)
    next_run = cron.get_next(datetime)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=tzinfo)

    future_runs = [next_run.isoformat()]
    for _ in range(max(0, count - 1)):
        future_run = cron.get_next(datetime)
        if future_run.tzinfo is None:
            future_run = future_run.replace(tzinfo=tzinfo)
        future_runs.append(future_run.isoformat())

    return {
        'next_run': next_run.isoformat(),
        'future_runs': future_runs,
        'time_zone': time_zone,
    }


NORMAL_MAIL_RETENTION_TEXT_COLUMNS = (
    'folder',
    'provider_message_id',
    'id_mode',
    'subject',
    'sender',
    'recipients',
    'cc',
    'received_at',
    'body_preview',
    'body',
    'body_type',
    'attachments_json',
    'list_cached_at',
    'body_cached_at',
    'last_synced_at',
    'created_at',
    'updated_at',
)


NORMAL_MAIL_RETENTION_CLEAR_STATUS_LOCK = threading.Lock()
NORMAL_MAIL_RETENTION_CLEAR_RETRY_ATTEMPTS = 3
NORMAL_MAIL_RETENTION_CLEAR_RETRY_DELAY_SECONDS = 0.05
NORMAL_MAIL_RETENTION_CLEAR_STATUS = {
    'state': 'idle',
    'message': '普通邮箱本地缓存清理空闲',
}


def set_normal_mail_retention_clear_status(state: str, message: str):
    with NORMAL_MAIL_RETENTION_CLEAR_STATUS_LOCK:
        NORMAL_MAIL_RETENTION_CLEAR_STATUS.update({
            'state': state,
            'message': message,
        })
        return dict(NORMAL_MAIL_RETENTION_CLEAR_STATUS)


def get_normal_mail_retention_clear_status():
    with NORMAL_MAIL_RETENTION_CLEAR_STATUS_LOCK:
        return dict(NORMAL_MAIL_RETENTION_CLEAR_STATUS)


def is_sqlite_database_locked_error(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and 'database is locked' in str(exc).lower()


def clear_retained_normal_mail_cache_rows() -> int:
    db = get_db()
    last_error = None
    for attempt in range(NORMAL_MAIL_RETENTION_CLEAR_RETRY_ATTEMPTS):
        try:
            cursor = db.execute('DELETE FROM retained_normal_mail_messages')
            db.commit()
            return int(cursor.rowcount if cursor.rowcount is not None else 0)
        except sqlite3.OperationalError as exc:
            db.rollback()
            if not is_sqlite_database_locked_error(exc):
                raise
            last_error = exc
            if attempt + 1 >= NORMAL_MAIL_RETENTION_CLEAR_RETRY_ATTEMPTS:
                break
            time.sleep(NORMAL_MAIL_RETENTION_CLEAR_RETRY_DELAY_SECONDS * (attempt + 1))
    raise last_error or sqlite3.OperationalError('database is locked')


def run_normal_mail_retention_clear_operation():
    with app.app_context():
        try:
            deleted_count = clear_retained_normal_mail_cache_rows()
        except Exception as exc:
            set_normal_mail_retention_clear_status('failed', f'清理失败：{exc}')
            return
        set_normal_mail_retention_clear_status(
            'succeeded',
            f'已清理 {deleted_count} 封普通邮箱本地缓存邮件',
        )


def start_normal_mail_retention_clear_operation():
    worker = threading.Thread(
        target=run_normal_mail_retention_clear_operation,
        name='normal-mail-retention-clear',
        daemon=True,
    )
    with NORMAL_MAIL_RETENTION_CLEAR_STATUS_LOCK:
        if NORMAL_MAIL_RETENTION_CLEAR_STATUS.get('state') == 'running':
            status = dict(NORMAL_MAIL_RETENTION_CLEAR_STATUS)
            status['already_running'] = True
            return status
        NORMAL_MAIL_RETENTION_CLEAR_STATUS.update({
            'state': 'running',
            'message': '正在清理普通邮箱本地缓存…',
        })
        worker.start()
        status = dict(NORMAL_MAIL_RETENTION_CLEAR_STATUS)
        status['already_running'] = False
    return status


def get_normal_mail_retention_db_file_bytes() -> int:
    if not DATABASE or not os.path.exists(DATABASE):
        return 0
    return max(0, int(os.path.getsize(DATABASE)))


NORMAL_MAIL_RETENTION_SIZE_SQL_TERMS = tuple(
    "length(CAST(coalesce(" + column + ", '') AS BLOB))"
    for column in NORMAL_MAIL_RETENTION_TEXT_COLUMNS
)
NORMAL_MAIL_RETENTION_SIZE_SQL = ' + '.join(NORMAL_MAIL_RETENTION_SIZE_SQL_TERMS)


def get_normal_mail_retention_size_sql() -> str:
    return NORMAL_MAIL_RETENTION_SIZE_SQL


def get_normal_mail_retention_storage_stats():
    db = get_db()
    size_sql = get_normal_mail_retention_size_sql()
    def query_retention_stats():
        return db.execute(
            f'''
            SELECT
                COUNT(*) AS saved_message_count,
                COALESCE(SUM(CASE WHEN body_cached = 1 THEN 1 ELSE 0 END), 0)
                    AS cached_body_count,
                COALESCE(SUM({size_sql}), 0) AS estimated_retained_bytes
            FROM retained_normal_mail_messages
            '''
        ).fetchone()

    row = query_retention_stats()
    clear_status = get_normal_mail_retention_clear_status()
    if clear_status.get('state') == 'succeeded':
        row = query_retention_stats()

    enabled_value = normalize_bool_setting_value(
        get_setting('normal_mail_local_retention_enabled', 'false')
    )
    return {
        'enabled': enabled_value == 'true',
        'saved_message_count': int(row['saved_message_count'] or 0),
        'cached_body_count': int(row['cached_body_count'] or 0),
        'estimated_retained_bytes': int(row['estimated_retained_bytes'] or 0),
        'db_file_bytes': get_normal_mail_retention_db_file_bytes(),
        'clear_status': clear_status,
    }


@app.route('/api/settings/normal-mail-retention/status', methods=['GET'])
@login_required
def api_get_normal_mail_retention_status():
    """返回普通邮箱本地保留统计，供设置页展示。"""
    return jsonify({
        'success': True,
        'status': get_normal_mail_retention_storage_stats(),
    })


@app.route('/api/settings/normal-mail-retention/clear', methods=['POST'])
@login_required
def api_clear_normal_mail_retention_cache():
    """显式启动普通邮箱本地保留缓存清理。"""
    status = start_normal_mail_retention_clear_operation()
    return jsonify({
        'success': True,
        'status': status,
        'already_running': bool(status.get('already_running', False)),
    })


@app.route('/api/settings/validate-cron', methods=['POST'])
@login_required
def api_validate_cron():
    """验证 Cron 表达式"""
    try:
        from croniter import croniter  # noqa: F401
    except ImportError:
        return jsonify({'success': False, 'error': 'croniter 库未安装，请运行: pip install croniter'})

    data = request.json or {}
    cron_expr = data.get('cron_expression', '').strip()
    requested_timezone = str(data.get('time_zone', '')).strip()
    expected_fields = data.get('expected_fields')

    if not cron_expr:
        return jsonify({'success': False, 'error': 'Cron 表达式不能为空'})

    if expected_fields is not None:
        try:
            expected_field_count = int(expected_fields)
        except (TypeError, ValueError):
            expected_field_count = 0
        if expected_field_count > 0 and len(cron_expr.split()) != expected_field_count:
            return jsonify({
                'success': False,
                'valid': False,
                'error': f'仅支持 {expected_field_count} 段 Cron'
            })

    if requested_timezone and not is_valid_app_timezone_name(requested_timezone):
        return jsonify({'success': False, 'error': 'Invalid time zone'})

    preview_timezone = normalize_app_timezone_name(requested_timezone, get_app_timezone())

    try:
        preview = build_cron_preview(cron_expr, preview_timezone)
        return jsonify({
            'success': True,
            'valid': True,
            'next_run': preview['next_run'],
            'future_runs': preview['future_runs'],
            'time_zone': preview['time_zone']
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
    settings.pop('cloudflare_ai_username_api_key', None)
    cloudflare_ai_api_key = get_setting_decrypted('cloudflare_ai_username_api_key', '')
    settings['cloudflare_ai_username_enabled'] = get_setting('cloudflare_ai_username_enabled', 'false')
    settings['cloudflare_ai_username_api_url'] = get_setting('cloudflare_ai_username_api_url', '')
    settings['cloudflare_ai_username_model'] = get_setting('cloudflare_ai_username_model', '')
    settings['cloudflare_ai_username_prompt'] = get_setting(
        'cloudflare_ai_username_prompt',
        CLOUDFLARE_AI_USERNAME_DEFAULT_PROMPT,
    )
    settings['cloudflare_ai_username_api_key_configured'] = bool(cloudflare_ai_api_key)
    settings['cloudflare_ai_username_api_key_masked'] = '********' if cloudflare_ai_api_key else ''
    settings['app_timezone'] = get_app_timezone()
    settings['show_account_created_at'] = get_setting('show_account_created_at', 'true')
    settings['show_account_sort_order'] = get_setting('show_account_sort_order', 'false')
    settings['show_group_id'] = get_setting('show_group_id', 'true')
    settings['normal_mail_local_retention_enabled'] = get_setting(
        'normal_mail_local_retention_enabled',
        'false',
    )
    skin_settings = get_skin_settings_payload()
    settings['active_skin_id'] = skin_settings['active_skin_id']
    settings['configured_skin_id'] = skin_settings['configured_skin_id']
    settings['active_skin'] = skin_settings['active_skin']
    settings['active_skin_asset_hash'] = skin_settings['asset_hash']
    settings['forward_channels'] = get_forward_channels()
    settings['forward_check_interval_minutes'] = get_setting('forward_check_interval_minutes', '5')
    settings['forward_check_interval_seconds'] = str(normalize_forward_check_interval_seconds())
    forward_execution_mode = normalize_forward_execution_mode()
    settings['forward_execution_mode'] = forward_execution_mode
    settings['forward_parallel_workers'] = str(normalize_forward_parallel_workers())
    settings['forward_account_delay_seconds'] = (
        '0' if forward_execution_mode == 'parallel' else get_setting('forward_account_delay_seconds', '0')
    )
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
    settings['telegram_proxy_url'] = get_setting('telegram_proxy_url', '')
    settings['wecom_webhook_url'] = get_setting_decrypted('wecom_webhook_url', '')
    settings['webdav_backup_enabled'] = get_setting('webdav_backup_enabled', 'false')
    settings['webdav_backup_url'] = get_setting('webdav_backup_url', '')
    settings['webdav_backup_username'] = get_setting('webdav_backup_username', '')
    settings['webdav_backup_password'] = get_setting_decrypted('webdav_backup_password', '')
    settings['webdav_backup_cron'] = get_setting('webdav_backup_cron', '0 3 * * *')
    settings['webdav_backup_last_run_at'] = get_setting('webdav_backup_last_run_at', '')
    settings['webdav_backup_last_status'] = get_setting('webdav_backup_last_status', '')
    settings['webdav_backup_last_message'] = get_setting('webdav_backup_last_message', '')
    settings['webdav_backup_last_filename'] = get_setting('webdav_backup_last_filename', '')
    settings['webdav_backup_next_run'] = ''
    cron_error = validate_five_field_cron_expression_for_timezone(settings['webdav_backup_cron'], settings['app_timezone'])
    if not cron_error:
        try:
            settings['webdav_backup_next_run'] = build_cron_preview(
                settings['webdav_backup_cron'],
                settings['app_timezone'],
                count=1,
            )['next_run']
        except Exception:
            settings['webdav_backup_next_run'] = ''
    return jsonify({'success': True, 'settings': settings})


@app.route('/api/settings', methods=['PUT'])
@login_required
def api_update_settings():
    """更新设置"""
    data = request.json or {}
    updated = []
    errors = []

    webdav_backup_changed = has_webdav_backup_setting_changes(data)
    if webdav_backup_changed:
        confirm_password = str(data.get('webdav_backup_verify_password', ''))
        if not confirm_password:
            return jsonify({'success': False, 'error': '修改 WebDAV 备份设置需要验证登录密码'})
        if not verify_login_password(confirm_password):
            return jsonify({'success': False, 'error': 'WebDAV 备份设置验证失败：登录密码错误'})

        proposed_backup = {
            key: normalize_webdav_backup_setting_value(key, get_current_webdav_backup_setting_value(key))
            for key in WEBDAV_BACKUP_SETTING_KEYS
        }
        for key in WEBDAV_BACKUP_SETTING_KEYS:
            if key in data:
                proposed_backup[key] = normalize_webdav_backup_setting_value(key, data.get(key))

        if proposed_backup['webdav_backup_enabled'] == 'true':
            backup_url = proposed_backup['webdav_backup_url']
            parsed_url = urlparse(backup_url)
            if not backup_url:
                return jsonify({'success': False, 'error': '启用 WebDAV 备份时必须填写 WebDAV 目录 URL'})
            if parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc:
                return jsonify({'success': False, 'error': 'WebDAV 目录 URL 必须是有效的 http(s) 地址'})

            backup_timezone = str(data.get('app_timezone') or get_app_timezone()).strip()
            backup_timezone = normalize_app_timezone_name(backup_timezone, get_app_timezone())
            cron_error = validate_five_field_cron_expression_for_timezone(proposed_backup['webdav_backup_cron'], backup_timezone)
            if cron_error:
                return jsonify({'success': False, 'error': cron_error})

    # 更新登录密码：必须验证当前密码；成功后轮换会话版本，使其他已登录会话失效
    if 'login_password' in data:
        new_password = str(data.get('login_password') or '').strip()
        if new_password:
            if len(new_password) < 8:
                return jsonify({'success': False, 'error': '密码长度至少为 8 位'})
            current_password = str(data.get('current_login_password') or '')
            if not current_password:
                return jsonify({'success': False, 'error': '修改登录密码需要验证当前密码'})
            if not verify_login_password(current_password):
                return jsonify({'success': False, 'error': '当前登录密码错误'})
            hashed_password = hash_password(new_password)
            if not set_setting('login_password', hashed_password):
                return jsonify({'success': False, 'error': '更新登录密码失败'})
            new_session_version = rotate_login_session_version()
            # 当前改密会话继续有效，其余旧会话在下次请求时失效
            session['logged_in'] = True
            session.permanent = True
            bind_login_session_version(new_session_version)
            updated.append('登录密码')

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

    if 'app_timezone' in data:
        app_timezone = str(data['app_timezone']).strip()
        if not is_valid_app_timezone_name(app_timezone):
            errors.append('Invalid time zone')
        elif set_setting('app_timezone', app_timezone):
            updated.append('Time zone')
        else:
            errors.append('Failed to save time zone')

    if 'show_account_created_at' in data:
        show_created_at = str(data['show_account_created_at']).lower()
        if show_created_at in ('true', 'false'):
            if set_setting('show_account_created_at', show_created_at):
                updated.append('创建时间展示')
            else:
                errors.append('更新创建时间展示失败')
        else:
            errors.append('创建时间展示必须是 true 或 false')

    if 'show_account_sort_order' in data:
        show_sort_order = str(data['show_account_sort_order']).lower()
        if show_sort_order in ('true', 'false'):
            if set_setting('show_account_sort_order', show_sort_order):
                updated.append('排序值展示')
            else:
                errors.append('更新排序值展示失败')
        else:
            errors.append('排序值展示必须是 true 或 false')

    if 'show_group_id' in data:
        show_group_id = str(data['show_group_id']).lower()
        if show_group_id in ('true', 'false'):
            if set_setting('show_group_id', show_group_id):
                updated.append('组ID展示')
            else:
                errors.append('更新组ID展示失败')
        else:
            errors.append('组ID展示必须是 true 或 false')

    if 'normal_mail_local_retention_enabled' in data:
        retention_enabled = str(data['normal_mail_local_retention_enabled']).strip().lower()
        if retention_enabled in ('true', 'false'):
            normalized_retention_enabled = normalize_bool_setting_value(retention_enabled)
            if set_setting(
                'normal_mail_local_retention_enabled',
                normalized_retention_enabled,
            ):
                set_normal_mail_local_retention_enabled_cache(normalized_retention_enabled)
                updated.append('普通邮箱本地保留开关')
            else:
                errors.append('更新普通邮箱本地保留开关失败')
        else:
            errors.append('普通邮箱本地保留开关必须是 true 或 false')

    if 'active_skin_id' in data:
        success, error, _skin = set_active_skin(data.get('active_skin_id'))
        if success:
            updated.append('当前皮肤')
        else:
            errors.append(error or '保存当前皮肤失败')

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

    if 'cloudflare_ai_username_enabled' in data:
        enabled = normalize_bool_setting_value(data['cloudflare_ai_username_enabled'])
        if set_setting('cloudflare_ai_username_enabled', enabled):
            updated.append('Cloudflare AI 用户名开关')
        else:
            errors.append('保存 Cloudflare AI 用户名开关失败')

    if 'cloudflare_ai_username_api_url' in data:
        if set_setting('cloudflare_ai_username_api_url', str(data['cloudflare_ai_username_api_url']).strip()):
            updated.append('Cloudflare AI API 地址')
        else:
            errors.append('保存 Cloudflare AI API 地址失败')

    if 'cloudflare_ai_username_model' in data:
        if set_setting('cloudflare_ai_username_model', str(data['cloudflare_ai_username_model']).strip()):
            updated.append('Cloudflare AI 模型')
        else:
            errors.append('保存 Cloudflare AI 模型失败')

    if 'cloudflare_ai_username_prompt' in data:
        prompt = str(data['cloudflare_ai_username_prompt'] or '').strip() or CLOUDFLARE_AI_USERNAME_DEFAULT_PROMPT
        if set_setting('cloudflare_ai_username_prompt', prompt):
            updated.append('Cloudflare AI 提示词')
        else:
            errors.append('保存 Cloudflare AI 提示词失败')

    if data.get('cloudflare_ai_username_clear_api_key'):
        if set_setting_encrypted('cloudflare_ai_username_api_key', ''):
            updated.append('Cloudflare AI API Key（已清空）')
        else:
            errors.append('清空 Cloudflare AI API Key 失败')
    elif 'cloudflare_ai_username_api_key' in data:
        ai_api_key = str(data['cloudflare_ai_username_api_key'] or '').strip()
        if ai_api_key:
            if set_setting_encrypted('cloudflare_ai_username_api_key', ai_api_key):
                updated.append('Cloudflare AI API Key')
            else:
                errors.append('保存 Cloudflare AI API Key 失败')

    forward_execution_mode_for_delay = normalize_forward_execution_mode()
    forward_account_delay_updated = False

    if 'forward_check_interval_minutes' in data:
        try:
            minutes = int(data['forward_check_interval_minutes'])
            if minutes < 1 or minutes > 60:
                errors.append('转发检查间隔必须在 1-60 分钟之间')
            elif set_setting('forward_check_interval_minutes', str(minutes)):
                updated.append('转发检查间隔')
                if 'forward_check_interval_seconds' not in data:
                    if not set_setting('forward_check_interval_seconds', str(minutes * 60)):
                        errors.append('保存转发秒级轮询间隔失败')
            else:
                errors.append('保存转发检查间隔失败')
        except ValueError:
            errors.append('转发检查间隔必须是数字')

    if 'forward_check_interval_seconds' in data:
        try:
            seconds = parse_forward_check_interval_seconds_input(data['forward_check_interval_seconds'])
            if set_setting('forward_check_interval_seconds', str(seconds)):
                updated.append('转发秒级轮询间隔')
            else:
                errors.append('保存转发秒级轮询间隔失败')
        except ValueError as exc:
            errors.append(str(exc))

    if 'forward_execution_mode' in data:
        try:
            execution_mode = parse_forward_execution_mode_input(data['forward_execution_mode'])
            if set_setting('forward_execution_mode', execution_mode):
                updated.append('转发执行模式')
                forward_execution_mode_for_delay = execution_mode
            else:
                errors.append('保存转发执行模式失败')
        except ValueError as exc:
            errors.append(str(exc))

    if 'forward_parallel_workers' in data:
        try:
            workers = parse_forward_parallel_workers_input(data['forward_parallel_workers'])
            if set_setting('forward_parallel_workers', str(workers)):
                updated.append('转发并行 worker 数')
            else:
                errors.append('保存转发并行 worker 数失败')
        except ValueError as exc:
            errors.append(str(exc))

    if 'forward_account_delay_seconds' in data:
        try:
            seconds = (
                0 if forward_execution_mode_for_delay == 'parallel'
                else int(data['forward_account_delay_seconds'])
            )
            if seconds < 0 or seconds > 60:
                errors.append('账号间拉取间隔必须在 0-60 秒之间')
            elif set_setting('forward_account_delay_seconds', str(seconds)):
                updated.append('账号间拉取间隔')
                forward_account_delay_updated = True
            else:
                errors.append('保存账号间拉取间隔失败')
        except (TypeError, ValueError):
            errors.append('账号间拉取间隔必须是数字')

    if (
        'forward_execution_mode' in data
        and forward_execution_mode_for_delay == 'parallel'
        and not forward_account_delay_updated
    ):
        if set_setting('forward_account_delay_seconds', '0'):
            updated.append('账号间拉取间隔')
        else:
            errors.append('保存账号间拉取间隔失败')

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

    if 'telegram_proxy_url' in data:
        if set_setting('telegram_proxy_url', data['telegram_proxy_url'].strip()):
            updated.append('Telegram 代理')
        else:
            errors.append('保存 Telegram 代理失败')

    if 'wecom_webhook_url' in data:
        if set_setting_encrypted('wecom_webhook_url', data['wecom_webhook_url'].strip()):
            updated.append('企业微信 Webhook')
        else:
            errors.append('保存企业微信 Webhook 失败')

    if 'webdav_backup_enabled' in data:
        enabled = normalize_bool_setting_value(data['webdav_backup_enabled'])
        if set_setting('webdav_backup_enabled', enabled):
            updated.append('WebDAV 备份开关')
        else:
            errors.append('保存 WebDAV 备份开关失败')

    if 'webdav_backup_url' in data:
        if set_setting('webdav_backup_url', str(data['webdav_backup_url']).strip()):
            updated.append('WebDAV 目录 URL')
        else:
            errors.append('保存 WebDAV 目录 URL 失败')

    if 'webdav_backup_username' in data:
        if set_setting('webdav_backup_username', str(data['webdav_backup_username']).strip()):
            updated.append('WebDAV 用户名')
        else:
            errors.append('保存 WebDAV 用户名失败')

    if 'webdav_backup_password' in data:
        if set_setting_encrypted('webdav_backup_password', str(data['webdav_backup_password']).strip()):
            updated.append('WebDAV 密码')
        else:
            errors.append('保存 WebDAV 密码失败')

    if 'webdav_backup_cron' in data:
        cron_expr = str(data['webdav_backup_cron']).strip()
        backup_timezone = normalize_app_timezone_name(str(data.get('app_timezone') or get_app_timezone()).strip(), get_app_timezone())
        cron_error = validate_five_field_cron_expression_for_timezone(cron_expr, backup_timezone)
        if cron_error:
            errors.append(cron_error)
        elif set_setting('webdav_backup_cron', cron_expr):
            updated.append('WebDAV 备份 Cron')
        else:
            errors.append('保存 WebDAV 备份 Cron 失败')

    if errors:
        return jsonify({'success': False, 'error': '；'.join(errors)})

    if updated:
        return jsonify({'success': True, 'message': f'已更新：{", ".join(updated)}'})
    else:
        return jsonify({'success': False, 'error': '没有需要更新的设置'})


# ==================== 皮肤管理 API ====================

@app.route('/api/skins', methods=['GET'])
@login_required
def api_list_skins():
    return jsonify({
        'success': True,
        **get_skin_settings_payload(),
    })


@app.route('/api/skins/<skin_id>/activate', methods=['POST'])
@login_required
def api_activate_skin(skin_id):
    success, error, skin = set_active_skin(skin_id)
    if not success:
        return jsonify({'success': False, 'error': error or '启用皮肤失败'})
    return jsonify({
        'success': True,
        'message': '皮肤已启用',
        'active_skin': skin,
        'asset_hash': get_active_skin_asset_hash(),
    })


@app.route('/api/skins/upload', methods=['POST'])
@login_required
def api_upload_skin():
    uploaded_file = request.files.get('skin') or request.files.get('file')
    try:
        skin = install_uploaded_skin_file(uploaded_file)
    except SkinValidationError as exc:
        return jsonify({'success': False, 'error': str(exc)})
    except Exception as exc:
        return jsonify({'success': False, 'error': f'安装上传皮肤失败: {sanitize_error_details(str(exc))}'})

    return jsonify({
        'success': True,
        'message': '皮肤已安装',
        'skin': skin,
    })


@app.route('/api/skins/git/install', methods=['POST'])
@login_required
def api_install_git_skin():
    data = request.get_json(silent=True) or {}
    try:
        skin = install_git_skin_package(data.get('git_url'), data.get('git_ref', ''))
    except SkinValidationError as exc:
        return jsonify({'success': False, 'error': str(exc)})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': '拉取 Git 皮肤超时'})
    except Exception as exc:
        return jsonify({'success': False, 'error': f'安装 Git 皮肤失败: {sanitize_error_details(str(exc))}'})

    return jsonify({
        'success': True,
        'message': 'Git 皮肤已安装',
        'skin': skin,
    })


@app.route('/api/skins/<skin_id>/git/update', methods=['POST'])
@login_required
def api_update_git_skin(skin_id):
    try:
        skin = update_git_skin_package(skin_id)
    except SkinValidationError as exc:
        return jsonify({'success': False, 'error': str(exc)})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': '更新 Git 皮肤超时'})
    except Exception as exc:
        return jsonify({'success': False, 'error': f'更新 Git 皮肤失败: {sanitize_error_details(str(exc))}'})

    return jsonify({
        'success': True,
        'message': 'Git 皮肤已更新',
        'skin': skin,
    })


@app.route('/api/skins/<skin_id>', methods=['DELETE'])
@login_required
def api_delete_skin(skin_id):
    success, error = delete_custom_skin(skin_id)
    if not success:
        return jsonify({'success': False, 'error': error or '删除皮肤失败'})
    return jsonify({'success': True, 'message': '皮肤已删除'})


# ==================== 对外 API ====================

@app.route('/api/external/emails', methods=['GET'])
@csrf_exempt
@api_key_required
def api_external_get_emails():
    """对外 API：通过 API Key 获取邮件列表"""
    email_addr = get_query_arg_preserve_plus('email', '').strip()
    folder = request.args.get('folder', 'inbox').strip().lower()
    skip = parse_non_negative_int(request.args.get('skip', 0), 0)
    top = parse_non_negative_int(request.args.get('top', 20), 20, 50)

    if not email_addr:
        return jsonify({'success': False, 'error': '缺少 email 参数'}), 400

    # 验证 folder 参数
    valid_folders = ['inbox', 'junkemail']
    if folder not in valid_folders:
        return jsonify({'success': False, 'error': f'folder 参数无效，支持: {", ".join(valid_folders)}'}), 400

    account = resolve_account_for_email_api(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '邮箱账号不存在'}), 404

    # 获取代理设置：账号级配置优先，未配置时继承分组代理
    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)

    # 收集所有错误信息
    all_errors = {}

    # 1. 尝试 Graph API
    graph_result = get_emails_graph(
        account['client_id'],
        account['refresh_token'],
        folder,
        skip,
        top,
        proxy_url,
        fallback_proxy_urls,
    )
    if graph_result.get('success'):
        emails = graph_result.get('emails', [])
        formatted = [format_graph_email_item(e, folder) for e in emails]
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
            return jsonify({'success': False, 'error': '账号代理或分组代理连接失败', 'details': all_errors})

    # 2. 尝试新版 IMAP
    imap_new_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_NEW, proxy_url, fallback_proxy_urls
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
        folder, skip, top, IMAP_SERVER_OLD, proxy_url, fallback_proxy_urls
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


@app.route('/api/external/outlook/upload', methods=['POST'])
@csrf_exempt
@api_key_required
def api_external_upload_outlook():
    """对外 API：上传 Outlook 邮箱账号密码到上传表（默认未授权）。

    支持单条 {email, password, remark?} 或批量 {accounts: [...]}。
    """
    data = request.get_json(silent=True) or {}

    raw_accounts = data.get('accounts')
    if isinstance(raw_accounts, list) and raw_accounts:
        items = [
            {
                'email': item.get('email', ''),
                'password': item.get('password', ''),
                'remark': item.get('remark', ''),
            }
            for item in raw_accounts
            if isinstance(item, dict)
        ]
    elif data.get('email'):
        items = [{
            'email': data.get('email', ''),
            'password': data.get('password', ''),
            'remark': data.get('remark', ''),
        }]
    else:
        return jsonify({'success': False, 'error': '请求体需包含 email/password 或非空 accounts 数组'}), 400

    summary = add_upload_accounts_bulk(items)
    return jsonify({'success': True, **summary})


@app.route('/api/outlook-upload-accounts', methods=['GET'])
@login_required
def api_list_outlook_upload_accounts():
    """分页查询外部上传的 Outlook 账号，供前端弹框表格展示。"""
    page = parse_non_negative_int(request.args.get('page', 1), 1) or 1
    page_size = parse_non_negative_int(request.args.get('page_size', 20), 20, 200)
    keyword = str(request.args.get('keyword', '') or '').strip()
    result = query_upload_accounts_page(page=page, page_size=page_size, keyword=keyword)
    return jsonify({'success': True, **result})


@app.route('/api/outlook-upload-accounts', methods=['POST'])
@login_required
def api_add_outlook_upload_account():
    """添加单个外部上传的 Outlook 账号。"""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email', '') or '').strip()
    password = str(data.get('password', '') or '').strip()
    remark = str(data.get('remark', '') or '').strip()

    if not email:
        return jsonify({'success': False, 'error': '邮箱不能为空'}), 400
    if not password:
        return jsonify({'success': False, 'error': '密码不能为空'}), 400

    result = add_upload_account(email, password, remark)
    db = get_db()
    db.commit()

    if result['status'] == 'added':
        return jsonify({'success': True, 'message': '添加成功', 'account': result})
    elif result['status'] == 'duplicate':
        return jsonify({'success': False, 'error': '该邮箱已存在'}), 400
    else:
        return jsonify({'success': False, 'error': '邮箱格式无效'}), 400


@app.route('/api/outlook-upload-accounts/<int:account_id>', methods=['PUT'])
@login_required
def api_update_outlook_upload_account(account_id):
    """更新指定 ID 的外部上传账号（邮箱 / 密码 / 备注）。

    请求体字段都可选；password 留空表示保持原密码；email/remark 不传入则保持原值。
    """
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    remark = data.get('remark')

    if email is not None:
        email = str(email).strip()
    if password is not None:
        password = str(password)
    if remark is not None:
        remark = str(remark).strip()

    result = update_upload_account(
        account_id,
        email=email,
        password=password,
        remark=remark,
    )
    status = result.get('status')
    if status == 'updated':
        db = get_db()
        db.commit()
        return jsonify({'success': True, 'message': '修改成功', 'account': result})
    if status == 'not_found':
        return jsonify({'success': False, 'error': '账号不存在'}), 404
    if status == 'duplicate':
        return jsonify({'success': False, 'error': '该邮箱已存在'}), 400
    if status == 'invalid':
        return jsonify({'success': False, 'error': '邮箱格式无效'}), 400
    return jsonify({'success': False, 'error': '修改失败'}), 400


@app.route('/api/outlook-upload-accounts/<int:account_id>', methods=['DELETE'])
@login_required
def api_delete_outlook_upload_account(account_id):
    """删除指定 ID 的外部上传账号。"""
    success = delete_upload_account(account_id)
    if success:
        db = get_db()
        db.commit()
        return jsonify({'success': True, 'message': '删除成功'})
    else:
        return jsonify({'success': False, 'error': '账号不存在'}), 404


@app.route('/api/accounts/<int:account_id>/outlook-auto-auth', methods=['POST'])
@login_required
def api_queue_account_for_outlook_auto_auth(account_id):
    """将已有 Outlook 正式账号加入 Outlook 自动化授权队列。

    从服务端读取正式账号邮箱和密码，调用显式重新入队 helper 写入
    outlook_upload_accounts。不返回密码。
    """
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({
            'success': False,
            'error': build_error_payload(
                'ACCOUNT_NOT_FOUND',
                '账号不存在',
                'NotFoundError',
                404,
                f'account_id={account_id}',
            ),
        }), 404

    account_type = str(account.get('account_type') or 'outlook').lower()
    if account_type == 'imap':
        return jsonify({
            'success': False,
            'error': build_error_payload(
                'ACCOUNT_AUTO_AUTH_UNSUPPORTED',
                'IMAP 账号不支持加入 Outlook 自动化授权',
                'UnsupportedError',
                400,
                f'account_id={account_id} type=imap',
            ),
        }), 400

    email = str(account.get('email') or '').strip()
    password = str(account.get('password') or '').strip()
    if not email or not password:
        return jsonify({
            'success': False,
            'error': build_error_payload(
                'ACCOUNT_PASSWORD_MISSING',
                '账号密码为空或无法解密，请先在编辑中设置密码',
                'ValidationError',
                400,
                f'account_id={account_id}',
            ),
        }), 400

    remark = str(account.get('remark') or '').strip()
    result = upsert_upload_account_for_auto_auth(email, password, remark)
    if result['status'] == 'invalid':
        return jsonify({
            'success': False,
            'error': build_error_payload(
                'ACCOUNT_AUTO_AUTH_INVALID',
                '邮箱或密码无效，无法加入自动授权',
                'ValidationError',
                400,
                f'account_id={account_id}',
            ),
        }), 400

    get_db().commit()

    return jsonify({
        'success': True,
        'message': '已加入自动授权' if result['status'] == 'added' else '已重新加入自动授权',
        'upload_account_id': result['id'],
        'email': result['email'],
        'status': result['status'],
    })
