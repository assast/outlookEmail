from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    # These segmented files are executed into the shared `web_outlook_app`
    # globals at runtime. Importing from the assembled module keeps IDE
    # inspections from flagging the shared names as unresolved.
    from web_outlook_app import *  # noqa: F403


EMAIL_SHARE_TOKEN_BYTES = 32
EMAIL_SHARE_DEFAULT_DURATION_MINUTES = 60 * 24
EMAIL_SHARE_MAX_DURATION_MINUTES = 60 * 24 * 365 * 5
EMAIL_SHARE_MAX_EMAIL_COUNT = 50
EMAIL_SHARE_CANDIDATE_PAGE_SIZE = EMAIL_SHARE_MAX_EMAIL_COUNT
EMAIL_SHARE_MAX_TIED_CANDIDATES_PER_FOLDER = 500
EMAIL_SHARE_STABLE_ID_MODES = {'graph', 'uid'}
EMAIL_SHARE_STATUS_ACTIVE = 'active'
EMAIL_SHARE_STATUS_EXPIRED = 'expired'
EMAIL_SHARE_STATUS_REVOKED = 'revoked'
EMAIL_SHARE_STATUS_INVALID = 'invalid'
EMAIL_SHARE_ALLOWED_FOLDERS = {'inbox', 'junkemail'}
EMAIL_SHARE_ALLOWED_FOLDER_ORDER = ('inbox', 'junkemail')
EMAIL_SHARE_ACCESS_TOUCH_MIN_SECONDS = 300


def generate_email_share_token() -> str:
    return secrets.token_urlsafe(EMAIL_SHARE_TOKEN_BYTES)


def hash_email_share_token(token: str) -> str:
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def parse_share_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or '').strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z'):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_timestamp(minutes_from_now: int) -> str:
    expires_at = utc_now_naive() + timedelta(minutes=int(minutes_from_now))
    return expires_at.strftime('%Y-%m-%d %H:%M:%S')


def get_email_share_status(share: Dict[str, Any]) -> str:
    if not share:
        return EMAIL_SHARE_STATUS_INVALID
    _, max_email_count_error = normalize_persisted_email_share_max_email_count(
        share.get('max_email_count')
    )
    if max_email_count_error:
        return EMAIL_SHARE_STATUS_INVALID
    if share.get('revoked_at'):
        return EMAIL_SHARE_STATUS_REVOKED
    if int(share.get('never_expires') or 0):
        return EMAIL_SHARE_STATUS_ACTIVE
    expires_at = parse_share_timestamp(share.get('expires_at'))
    if not expires_at or expires_at <= utc_now_naive():
        return EMAIL_SHARE_STATUS_EXPIRED
    return EMAIL_SHARE_STATUS_ACTIVE


def is_email_share_active(share: Dict[str, Any]) -> bool:
    return get_email_share_status(share) == EMAIL_SHARE_STATUS_ACTIVE


def build_email_share_url(token: str) -> str:
    if not token:
        return ''
    return url_for('view_email_share', token=token, _external=True)


def decrypt_email_share_token(share: Dict[str, Any]) -> str:
    return decrypt_data(str(share.get('token_encrypted') or ''))


def normalize_email_share_max_email_count(value: Any) -> tuple[Optional[int], Optional[str]]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, '邮件数量限制无效'
    if isinstance(value, int):
        max_email_count = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None, None
        if not normalized.isdecimal():
            return None, '邮件数量限制无效'
        max_email_count = int(normalized)
    else:
        return None, '邮件数量限制无效'

    if max_email_count <= 0 or max_email_count > EMAIL_SHARE_MAX_EMAIL_COUNT:
        return None, '邮件数量限制无效'
    return max_email_count, None


def normalize_persisted_email_share_max_email_count(
    value: Any
) -> tuple[Optional[int], Optional[str]]:
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, '邮件数量限制无效'
    if value <= 0 or value > EMAIL_SHARE_MAX_EMAIL_COUNT:
        return None, '邮件数量限制无效'
    return value, None


def get_email_share_max_email_count(share: Dict[str, Any]) -> Optional[int]:
    max_email_count, error = normalize_persisted_email_share_max_email_count(
        share.get('max_email_count')
    )
    return None if error else max_email_count


def serialize_email_share_row(row: Any) -> Dict[str, Any]:
    share = dict(row)
    status = get_email_share_status(share)
    token = ''
    share_url = ''
    try:
        token = decrypt_email_share_token(share)
        share_url = build_email_share_url(token)
    except Exception:
        app.logger.warning('Failed to decrypt email share token for share id=%s', share.get('id'))

    return {
        'id': share.get('id'),
        'account_id': share.get('account_id'),
        'email': share.get('email') or '',
        'expires_at': share.get('expires_at'),
        'never_expires': bool(share.get('never_expires')),
        'max_email_count': get_email_share_max_email_count(share),
        'revoked_at': share.get('revoked_at'),
        'last_accessed_at': share.get('last_accessed_at'),
        'created_at': share.get('created_at'),
        'updated_at': share.get('updated_at'),
        'status': status,
        'share_url': share_url,
    }


def query_email_share_rows(account_id: Optional[int] = None) -> list[Dict[str, Any]]:
    db = get_db()
    params = []
    where_sql = ''
    if account_id is not None:
        where_sql = 'WHERE s.account_id = ?'
        params.append(int(account_id))
    rows = db.execute(
        f'''
        SELECT s.*, a.email
        FROM email_share_links s
        JOIN accounts a ON a.id = s.account_id
        {where_sql}
        ORDER BY s.created_at DESC, s.id DESC
        ''',
        tuple(params)
    ).fetchall()
    return [serialize_email_share_row(row) for row in rows]


def get_email_share_row_by_id(share_id: int) -> Optional[Dict[str, Any]]:
    row = get_db().execute(
        '''
        SELECT s.*, a.email
        FROM email_share_links s
        JOIN accounts a ON a.id = s.account_id
        WHERE s.id = ?
        LIMIT 1
        ''',
        (int(share_id),)
    ).fetchone()
    return dict(row) if row else None


def get_email_share_row_by_token(token: str) -> Optional[Dict[str, Any]]:
    normalized_token = str(token or '').strip()
    if not normalized_token:
        return None
    row = get_db().execute(
        '''
        SELECT s.*, a.email
        FROM email_share_links s
        JOIN accounts a ON a.id = s.account_id
        WHERE s.token_hash = ?
        LIMIT 1
        ''',
        (hash_email_share_token(normalized_token),)
    ).fetchone()
    return dict(row) if row else None


def touch_email_share_access(share_id: int) -> None:
    db = get_db()
    db.execute(
        '''
        UPDATE email_share_links
        SET last_accessed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (int(share_id),)
    )
    db.commit()


def should_touch_email_share_access(share: Dict[str, Any]) -> bool:
    last_accessed_at = parse_share_timestamp(share.get('last_accessed_at'))
    if not last_accessed_at:
        return True
    return last_accessed_at <= utc_now_naive() - timedelta(seconds=EMAIL_SHARE_ACCESS_TOUCH_MIN_SECONDS)


def resolve_active_email_share(token: str) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    share = get_email_share_row_by_token(token)
    if not share:
        return None, None, EMAIL_SHARE_STATUS_INVALID

    status = get_email_share_status(share)
    if status != EMAIL_SHARE_STATUS_ACTIVE:
        return share, None, status

    account = get_account_by_id(int(share['account_id']))
    if not account:
        return share, None, EMAIL_SHARE_STATUS_INVALID

    if should_touch_email_share_access(share):
        touch_email_share_access(int(share['id']))
    return share, account, status


def normalize_share_duration_minutes(value: Any) -> Optional[int]:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return None
    if duration <= 0 or duration > EMAIL_SHARE_MAX_DURATION_MINUTES:
        return None
    return duration


def normalize_email_share_bool(value: Any) -> tuple[Optional[bool], Optional[str]]:
    if isinstance(value, bool):
        return value, None
    if value is None:
        return False, None
    if isinstance(value, int) and value in (0, 1):
        return bool(value), None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'on'}:
            return True, None
        if normalized in {'false', '0', 'no', 'off', ''}:
            return False, None
    return None, 'never_expires 参数无效'


def parse_email_share_create_payload(
    data: Dict[str, Any]
) -> tuple[Optional[int], bool, Optional[int], Optional[str]]:
    max_email_count, max_count_error = normalize_email_share_max_email_count(
        data.get('max_email_count')
    )
    if max_count_error:
        return None, False, None, max_count_error

    never_expires, bool_error = normalize_email_share_bool(data.get('never_expires'))
    if bool_error:
        return None, False, None, bool_error
    if never_expires:
        return None, True, max_email_count, None
    duration = normalize_share_duration_minutes(
        data.get('duration_minutes', EMAIL_SHARE_DEFAULT_DURATION_MINUTES)
    )
    if duration is None:
        return None, False, None, '分享时长无效'
    return duration, False, max_email_count, None


def email_share_error_payload(status: str) -> Dict[str, Any]:
    if status == EMAIL_SHARE_STATUS_EXPIRED:
        message = '分享链接已过期'
    elif status == EMAIL_SHARE_STATUS_REVOKED:
        message = '分享链接已取消'
    else:
        message = '分享链接无效'
    return {'success': False, 'status': status, 'error': message}


def reject_share_if_account_mismatch(account: Dict[str, Any]) -> Optional[Any]:
    requested_email = str(request.args.get('email') or '').strip()
    if not requested_email:
        return None
    if normalize_email_address(requested_email) != normalize_email_address(account.get('email', '')):
        return jsonify({'success': False, 'error': '分享链接无权访问该邮箱'}), 403
    return None


def normalize_email_share_folder_response(raw_folder: Any) -> tuple[Optional[str], Optional[Any]]:
    folder = normalize_folder_name(raw_folder or 'inbox')
    if folder not in EMAIL_SHARE_ALLOWED_FOLDERS:
        allowed = ', '.join(sorted(EMAIL_SHARE_ALLOWED_FOLDERS))
        return None, (jsonify({'success': False, 'error': f'分享链接仅支持访问: {allowed}'}), 400)
    return folder, None


def email_share_message_datetime(email: Dict[str, Any]) -> Optional[datetime]:
    return parse_email_datetime(str(email.get('date') or ''))


def email_share_message_sort_key(email: Dict[str, Any]) -> tuple[datetime, str, str]:
    received_at = email_share_message_datetime(email)
    if received_at is None:
        raise ValueError('邮件接收时间无效')
    return (received_at, str(email.get('id') or ''), str(email.get('folder') or ''))


def normalize_email_share_message_id_mode(value: Any) -> str:
    return str(value or '').strip().lower()


def email_share_visible_messages_error() -> Dict[str, Any]:
    return {'success': False, 'error': '无法验证分享链接可访问邮件范围'}


def get_email_share_visible_message_method(email: Dict[str, Any]) -> str:
    return str(email.get('_share_request_method') or '').strip().lower()


def find_email_share_visible_message(
    emails: list[Dict[str, Any]], message_id: str, folder: str, id_mode: str
) -> Optional[Dict[str, Any]]:
    return next((
        email for email in emails
        if str(email.get('id') or '') == str(message_id)
        and normalize_folder_name(email.get('folder')) == folder
        and normalize_email_share_message_id_mode(email.get('id_mode')) == id_mode
    ), None)


def collect_email_share_candidate_page(
    result: Dict[str, Any], folder: str, state: Dict[str, Any], requested_top: int,
    candidates: list[Dict[str, Any]], seen_candidates: set[tuple[str, str, str]],
    methods: list[str],
) -> Optional[Dict[str, Any]]:
    raw_emails = result.get('emails') or []
    if not isinstance(raw_emails, list):
        return email_share_visible_messages_error()

    request_method = str(result.get('request_method') or '').strip().lower()
    if request_method not in {'graph', 'imap'}:
        return email_share_visible_messages_error()
    if state['request_method'] not in (None, request_method):
        return email_share_visible_messages_error()

    state['request_method'] = request_method
    state['fetched_count'] += len(raw_emails)
    state['has_more'] = bool(result.get('has_more'))
    if (
        len(raw_emails) > requested_top
        or (state['has_more'] and len(raw_emails) != requested_top)
    ):
        return email_share_visible_messages_error()
    if state['fetched_count'] > EMAIL_SHARE_MAX_TIED_CANDIDATES_PER_FOLDER:
        return email_share_visible_messages_error()
    state['skip'] += requested_top if state['has_more'] else len(raw_emails)

    method = str(result.get('method') or '').strip()
    if method and method not in methods:
        methods.append(method)

    page_dates = []
    expected_id_mode = 'graph' if request_method == 'graph' else 'uid'
    for item in raw_emails:
        if not isinstance(item, dict) or not item.get('id'):
            return email_share_visible_messages_error()

        candidate = dict(item)
        candidate['folder'] = folder
        id_mode = normalize_email_share_message_id_mode(candidate.get('id_mode'))
        received_at = email_share_message_datetime(candidate)
        if (
            received_at is None
            or id_mode not in EMAIL_SHARE_STABLE_ID_MODES
            or id_mode != expected_id_mode
        ):
            return email_share_visible_messages_error()

        candidate['_share_request_method'] = request_method
        page_dates.append(received_at)
        candidate_key = (folder, str(candidate['id']), id_mode)
        if candidate_key not in seen_candidates:
            seen_candidates.add(candidate_key)
            candidates.append(candidate)

    state['oldest_date'] = min(page_dates) if page_dates else None
    return None


def resolve_email_share_visible_messages(
    account: Dict[str, Any], max_email_count: int
) -> Dict[str, Any]:
    candidates = []
    methods = []
    seen_candidates = set()
    folder_states = {
        folder: {
            'skip': 0,
            'fetched_count': 0,
            'has_more': False,
            'oldest_date': None,
            'request_method': None,
        }
        for folder in EMAIL_SHARE_ALLOWED_FOLDER_ORDER
    }
    missing_marker = object()
    previous_disable_record = account.get('_disable_authorization_type_record', missing_marker)
    account['_disable_authorization_type_record'] = True
    stable_ids_context_token = email_share_stable_ids_context.set(True)

    try:
        for folder in EMAIL_SHARE_ALLOWED_FOLDER_ORDER:
            result = fetch_account_emails(
                account, folder, 0, EMAIL_SHARE_CANDIDATE_PAGE_SIZE
            )
            if not result.get('success'):
                app.logger.warning(
                    'Unable to resolve visible shared emails for account_id=%s folder=%s',
                    account.get('id'),
                    folder,
                )
                return email_share_visible_messages_error()
            error = collect_email_share_candidate_page(
                result,
                folder,
                folder_states[folder],
                EMAIL_SHARE_CANDIDATE_PAGE_SIZE,
                candidates,
                seen_candidates,
                methods,
            )
            if error:
                return error

        while True:
            sorted_candidates = sorted(candidates, key=email_share_message_sort_key, reverse=True)
            cutoff_date = (
                email_share_message_datetime(sorted_candidates[max_email_count - 1])
                if len(sorted_candidates) >= max_email_count
                else None
            )
            if len(sorted_candidates) >= max_email_count and cutoff_date is None:
                return email_share_visible_messages_error()
            folders_to_fetch = [
                folder for folder in EMAIL_SHARE_ALLOWED_FOLDER_ORDER
                if folder_states[folder]['has_more']
                and (
                    cutoff_date is None
                    or folder_states[folder]['oldest_date'] is None
                    or folder_states[folder]['oldest_date'] >= cutoff_date
                )
            ]
            if not folders_to_fetch:
                break

            for folder in folders_to_fetch:
                state = folder_states[folder]
                remaining = EMAIL_SHARE_MAX_TIED_CANDIDATES_PER_FOLDER - state['fetched_count']
                if remaining <= 0:
                    return email_share_visible_messages_error()
                result = fetch_account_emails(
                    account,
                    folder,
                    state['skip'],
                    min(EMAIL_SHARE_CANDIDATE_PAGE_SIZE, remaining),
                )
                if not result.get('success'):
                    app.logger.warning(
                        'Unable to extend visible shared emails for account_id=%s folder=%s',
                        account.get('id'),
                        folder,
                    )
                    return email_share_visible_messages_error()
                error = collect_email_share_candidate_page(
                    result,
                    folder,
                    state,
                    min(EMAIL_SHARE_CANDIDATE_PAGE_SIZE, remaining),
                    candidates,
                    seen_candidates,
                    methods,
                )
                if error:
                    return error
    finally:
        if previous_disable_record is missing_marker:
            account.pop('_disable_authorization_type_record', None)
        else:
            account['_disable_authorization_type_record'] = previous_disable_record
        email_share_stable_ids_context.reset(stable_ids_context_token)

    candidates.sort(key=email_share_message_sort_key, reverse=True)
    return {
        'success': True,
        'emails': candidates[:max_email_count],
        'method': ' / '.join(methods),
    }


def fetch_limited_email_share_emails(
    account: Dict[str, Any], folder: str, skip: int, top: int, max_email_count: int
) -> Dict[str, Any]:
    if skip >= max_email_count:
        return {'success': True, 'emails': [], 'method': '', 'has_more': False}

    visible_result = resolve_email_share_visible_messages(account, max_email_count)
    if not visible_result.get('success'):
        return visible_result

    folder_emails = [
        email for email in visible_result['emails']
        if normalize_folder_name(email.get('folder')) == folder
    ]
    return {
        'success': True,
        'emails': [
            {key: value for key, value in email.items() if not key.startswith('_share_')}
            for email in folder_emails[skip:skip + top]
        ],
        'method': visible_result.get('method', ''),
        'has_more': len(folder_emails) > skip + top,
    }


@app.route('/api/email-shares', methods=['POST'])
@login_required
def api_create_email_share():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}

    account = None
    account_id = data.get('account_id')
    if account_id:
        try:
            account = get_account_by_id(int(account_id))
        except (TypeError, ValueError):
            account = None
    if not account:
        email_addr = str(data.get('email') or '').strip()
        if email_addr:
            account = get_account_by_email(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '邮箱账号不存在'}), 404

    duration_minutes, never_expires, max_email_count, payload_error = parse_email_share_create_payload(data)
    if payload_error:
        return jsonify({'success': False, 'error': payload_error}), 400

    token = generate_email_share_token()
    expires_at = None if never_expires else utc_timestamp(duration_minutes)
    db = get_db()
    cursor = db.execute(
        '''
        INSERT INTO email_share_links (
            account_id, token_hash, token_encrypted, expires_at, never_expires, max_email_count
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (
            int(account['id']),
            hash_email_share_token(token),
            encrypt_data(token),
            expires_at,
            1 if never_expires else 0,
            max_email_count,
        )
    )
    db.commit()

    share = get_email_share_row_by_id(int(cursor.lastrowid))
    return jsonify({
        'success': True,
        'share': serialize_email_share_row(share),
    })


@app.route('/api/email-shares', methods=['GET'])
@login_required
def api_list_email_shares():
    account_id = request.args.get('account_id')
    normalized_account_id = None
    if account_id is not None and str(account_id).strip() != '':
        try:
            normalized_account_id = int(account_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'account_id 参数无效'}), 400
        if normalized_account_id <= 0:
            return jsonify({'success': False, 'error': 'account_id 参数无效'}), 400
    return jsonify({'success': True, 'shares': query_email_share_rows(normalized_account_id)})


@app.route('/api/email-shares/<int:share_id>/cancel', methods=['POST'])
@login_required
def api_cancel_email_share(share_id):
    share = get_email_share_row_by_id(share_id)
    if not share:
        return jsonify({'success': False, 'error': '分享记录不存在'}), 404

    db = get_db()
    db.execute(
        '''
        UPDATE email_share_links
        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (int(share_id),)
    )
    db.commit()
    updated = get_email_share_row_by_id(share_id)
    return jsonify({'success': True, 'share': serialize_email_share_row(updated)})


@app.route('/api/email-shares/<int:share_id>', methods=['DELETE'])
@login_required
def api_delete_email_share(share_id):
    share = get_email_share_row_by_id(share_id)
    if not share:
        return jsonify({'success': False, 'error': '分享记录不存在'}), 404

    db = get_db()
    try:
        db.execute('DELETE FROM email_share_links WHERE id = ?', (int(share_id),))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': f'删除失败: {str(e)}'})


@app.route('/api/email-shares/batch-cancel', methods=['POST'])
@login_required
def api_batch_cancel_email_shares():
    data = request.get_json(silent=True) or {}
    share_ids = data.get('share_ids') or []
    if not isinstance(share_ids, list):
        return jsonify({'success': False, 'error': '参数无效'}), 400
    if not share_ids:
        return jsonify({'success': True, 'message': '未选择任何记录'})

    try:
        ids = [int(x) for x in share_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '包含无效的 ID'}), 400

    db = get_db()
    try:
        placeholders = ','.join(['?'] * len(ids))
        db.execute(
            f'''
            UPDATE email_share_links
            SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            ''',
            tuple(ids)
        )
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': f'批量取消失败: {str(e)}'})


@app.route('/api/email-shares/batch-delete', methods=['POST'])
@login_required
def api_batch_delete_email_shares():
    data = request.get_json(silent=True) or {}
    share_ids = data.get('share_ids') or []
    if not isinstance(share_ids, list):
        return jsonify({'success': False, 'error': '参数无效'}), 400
    if not share_ids:
        return jsonify({'success': True, 'message': '未选择任何记录'})

    try:
        ids = [int(x) for x in share_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '包含无效的 ID'}), 400

    db = get_db()
    try:
        placeholders = ','.join(['?'] * len(ids))
        db.execute(
            f'DELETE FROM email_share_links WHERE id IN ({placeholders})',
            tuple(ids)
        )
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': f'批量删除失败: {str(e)}'})



@app.route('/share/email/<token>')
def view_email_share(token):
    share = get_email_share_row_by_token(token)
    status = get_email_share_status(share or {})
    account_email = share.get('email') if share else ''
    return render_template(
        'email_share.html',
        share_token=token,
        share_status=status,
        account_email=account_email,
    )


@app.route('/api/share/email/<token>/status', methods=['GET'])
def api_email_share_status(token):
    share, account, status = resolve_active_email_share(token)
    if status != EMAIL_SHARE_STATUS_ACTIVE:
        return jsonify(email_share_error_payload(status)), 404
    return jsonify({
        'success': True,
        'status': status,
        'email': account.get('email', ''),
        'never_expires': bool(share.get('never_expires')),
        'expires_at': share.get('expires_at'),
        'max_email_count': get_email_share_max_email_count(share),
    })


@app.route('/api/share/email/<token>/emails', methods=['GET'])
def api_email_share_get_emails(token):
    folder, folder_error = normalize_email_share_folder_response(request.args.get('folder', 'inbox'))
    if folder_error:
        return folder_error

    share, account, status = resolve_active_email_share(token)
    if status != EMAIL_SHARE_STATUS_ACTIVE:
        return jsonify(email_share_error_payload(status)), 404

    mismatch_response = reject_share_if_account_mismatch(account)
    if mismatch_response:
        return mismatch_response

    skip = parse_non_negative_int(request.args.get('skip', 0), 0)
    top = parse_non_negative_int(request.args.get('top', 20), 20, 50)
    max_email_count = get_email_share_max_email_count(share)
    if max_email_count is not None:
        return jsonify(fetch_limited_email_share_emails(
            account, folder, skip, top, max_email_count
        ))
    return jsonify(fetch_account_emails(account, folder, skip, top))


@app.route('/api/share/email/<token>/email/<path:message_id>', methods=['GET'])
def api_email_share_get_email_detail(token, message_id):
    folder, folder_error = normalize_email_share_folder_response(request.args.get('folder', 'inbox'))
    if folder_error:
        return folder_error

    share, account, status = resolve_active_email_share(token)
    if status != EMAIL_SHARE_STATUS_ACTIVE:
        return jsonify(email_share_error_payload(status)), 404

    mismatch_response = reject_share_if_account_mismatch(account)
    if mismatch_response:
        return mismatch_response

    method = request.args.get('method', 'graph')
    id_mode = normalize_email_share_message_id_mode(request.args.get('id_mode'))
    max_email_count = get_email_share_max_email_count(share)
    if max_email_count is not None:
        visible_result = resolve_email_share_visible_messages(account, max_email_count)
        if not visible_result.get('success'):
            return jsonify(visible_result)
        visible_email = find_email_share_visible_message(
            visible_result['emails'], message_id, folder, id_mode
        )
        if not visible_email:
            return jsonify({'success': False, 'error': '邮件不存在或无权访问'}), 404
        method = get_email_share_visible_message_method(visible_email)

    return jsonify(fetch_email_detail_for_account(
        account,
        message_id,
        method,
        folder,
        id_mode,
        strict_id_mode=max_email_count is not None,
        force_method=max_email_count is not None,
    ))
