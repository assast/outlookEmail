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
EMAIL_SHARE_STATUS_ACTIVE = 'active'
EMAIL_SHARE_STATUS_EXPIRED = 'expired'
EMAIL_SHARE_STATUS_REVOKED = 'revoked'
EMAIL_SHARE_STATUS_INVALID = 'invalid'
EMAIL_SHARE_ALLOWED_FOLDERS = {'inbox', 'junkemail'}
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


def parse_email_share_create_payload(data: Dict[str, Any]) -> tuple[Optional[int], bool, Optional[str]]:
    never_expires, bool_error = normalize_email_share_bool(data.get('never_expires'))
    if bool_error:
        return None, False, bool_error
    if never_expires:
        return None, True, None
    duration = normalize_share_duration_minutes(
        data.get('duration_minutes', EMAIL_SHARE_DEFAULT_DURATION_MINUTES)
    )
    if duration is None:
        return None, False, '分享时长无效'
    return duration, False, None


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

    duration_minutes, never_expires, duration_error = parse_email_share_create_payload(data)
    if duration_error:
        return jsonify({'success': False, 'error': duration_error}), 400

    token = generate_email_share_token()
    expires_at = None if never_expires else utc_timestamp(duration_minutes)
    db = get_db()
    cursor = db.execute(
        '''
        INSERT INTO email_share_links (
            account_id, token_hash, token_encrypted, expires_at, never_expires
        )
        VALUES (?, ?, ?, ?, ?)
        ''',
        (
            int(account['id']),
            hash_email_share_token(token),
            encrypt_data(token),
            expires_at,
            1 if never_expires else 0,
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
    id_mode = str(request.args.get('id_mode') or '').strip().lower()
    return jsonify(fetch_email_detail_for_account(account, message_id, method, folder, id_mode))
