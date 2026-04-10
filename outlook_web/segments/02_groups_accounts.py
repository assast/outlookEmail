def get_cloudflare_admin_password() -> str:
    """获取 Cloudflare Temp Email 管理密码"""
    password = get_setting('cloudflare_admin_password')
    return password if password is not None else CLOUDFLARE_ADMIN_PASSWORD


# ==================== 分组操作 ====================

def load_groups() -> List[Dict]:
    """加载所有分组（临时邮箱分组排在最前面）"""
    db = get_db()
    cursor = db.execute('''
        SELECT * FROM groups
        ORDER BY
            CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
            sort_order,
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


def get_movable_group_ids(db=None, exclude_group_id: Optional[int] = None) -> List[int]:
    """获取可排序分组 ID 列表（不含临时邮箱）"""
    database = db or get_db()
    query = '''
        SELECT id FROM groups
        WHERE name != '临时邮箱'
    '''
    params = []
    if exclude_group_id is not None:
        query += ' AND id != ?'
        params.append(exclude_group_id)
    query += ' ORDER BY sort_order, id'
    cursor = database.execute(query, tuple(params))
    return [row['id'] for row in cursor.fetchall()]


def apply_group_order(group_ids: List[int], db=None) -> None:
    """按给定顺序写入分组排序"""
    database = db or get_db()
    for index, group_id in enumerate(group_ids, start=1):
        database.execute('UPDATE groups SET sort_order = ? WHERE id = ?', (index, group_id))

    temp_group = database.execute(
        "SELECT id FROM groups WHERE name = '临时邮箱' LIMIT 1"
    ).fetchone()
    if temp_group:
        database.execute('UPDATE groups SET sort_order = 0 WHERE id = ?', (temp_group['id'],))


def normalize_group_order(db=None) -> None:
    """归一化分组顺序"""
    database = db or get_db()
    apply_group_order(get_movable_group_ids(database), database)


def clamp_group_position(sort_position: Optional[int], max_position: int) -> int:
    """限制分组位置范围，位置从 1 开始"""
    if max_position <= 0:
        return 1
    if sort_position is None:
        return max_position
    return max(1, min(sort_position, max_position))


def get_group_sort_position(group_id: int, db=None) -> Optional[int]:
    """获取分组在可排序列表中的位置（从 1 开始）"""
    group_ids = get_movable_group_ids(db)
    try:
        return group_ids.index(group_id) + 1
    except ValueError:
        return None


def set_group_position(group_id: int, sort_position: Optional[int], db=None) -> bool:
    """设置分组在可排序列表中的位置"""
    database = db or get_db()
    group = database.execute('SELECT id, name FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group or group['name'] == '临时邮箱':
        return False

    group_ids = get_movable_group_ids(database, exclude_group_id=group_id)
    target_position = clamp_group_position(sort_position, len(group_ids) + 1)
    group_ids.insert(target_position - 1, group_id)
    apply_group_order(group_ids, database)
    return True


def add_group(name: str, description: str = '', color: str = '#1a1a1a',
              proxy_url: str = '', sort_position: Optional[int] = None) -> Optional[int]:
    """添加分组"""
    db = get_db()
    try:
        cursor = db.execute(
            '''
            INSERT INTO groups (name, description, color, proxy_url, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (name, description, color, proxy_url or '', 999999)
        )
        group_id = cursor.lastrowid
        set_group_position(group_id, sort_position, db)
        db.commit()
        return group_id
    except sqlite3.IntegrityError:
        return None
    except Exception:
        return None


def update_group(group_id: int, name: str, description: str, color: str,
                 proxy_url: str = '', sort_position: Optional[int] = None) -> bool:
    """更新分组"""
    db = get_db()
    try:
        db.execute('''
            UPDATE groups SET name = ?, description = ?, color = ?, proxy_url = ?
            WHERE id = ?
        ''', (name, description, color, proxy_url or '', group_id))
        if not set_group_position(group_id, sort_position, db):
            return False
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
        normalize_group_order(db)
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


def reorder_groups(group_ids: List[int]) -> bool:
    """重新排序分组，临时邮箱分组固定在最前面"""
    db = get_db()
    try:
        movable_ids = get_movable_group_ids(db)

        if set(group_ids) != set(movable_ids):
            return False

        apply_group_order(group_ids, db)
        db.commit()
        return True
    except Exception:
        return False


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
    accounts = []
    for row in rows:
        account = resolve_account_record(row)
        account['tags'] = get_account_tags(account['id'])
        accounts.append(account)
    return accounts


# ==================== 标签管理 ====================

def get_tags() -> List[Dict]:
    """获取所有标签"""
    db = get_db()
    cursor = db.execute('SELECT * FROM tags ORDER BY created_at DESC')
    return [dict(row) for row in cursor.fetchall()]


def add_tag(name: str, color: str) -> Optional[int]:
    """添加标签"""
    db = get_db()
    try:
        cursor = db.execute(
            'INSERT INTO tags (name, color) VALUES (?, ?)',
            (name, color)
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def delete_tag(tag_id: int) -> bool:
    """删除标签"""
    db = get_db()
    cursor = db.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
    db.commit()
    return cursor.rowcount > 0


def get_account_tags(account_id: int) -> List[Dict]:
    """获取账号的标签"""
    db = get_db()
    cursor = db.execute('''
        SELECT t.*
        FROM tags t
        JOIN account_tags at ON t.id = at.tag_id
        WHERE at.account_id = ?
        ORDER BY t.created_at DESC
    ''', (account_id,))
    return [dict(row) for row in cursor.fetchall()]


def add_account_tag(account_id: int, tag_id: int) -> bool:
    """给账号添加标签"""
    db = get_db()
    try:
        db.execute(
            'INSERT OR IGNORE INTO account_tags (account_id, tag_id) VALUES (?, ?)',
            (account_id, tag_id)
        )
        db.commit()
        return True
    except Exception:
        return False


def remove_account_tag(account_id: int, tag_id: int) -> bool:
    """移除账号标签"""
    db = get_db()
    db.execute(
        'DELETE FROM account_tags WHERE account_id = ? AND tag_id = ?',
        (account_id, tag_id)
    )
    db.commit()
    return True


def normalize_email_address(email_addr: str) -> str:
    return str(email_addr or '').strip().lower()


def get_account_aliases(account_id: int) -> List[str]:
    db = get_db()
    rows = db.execute(
        'SELECT alias_email FROM account_aliases WHERE account_id = ? ORDER BY created_at ASC, id ASC',
        (account_id,)
    ).fetchall()
    return [str(row['alias_email']).strip() for row in rows if row['alias_email']]


def email_exists_as_primary(email_addr: str, exclude_account_id: Optional[int] = None) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    if exclude_account_id is None:
        row = db.execute('SELECT id FROM accounts WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    else:
        row = db.execute(
            'SELECT id FROM accounts WHERE LOWER(email) = ? AND id != ? LIMIT 1',
            (normalized, exclude_account_id)
        ).fetchone()
    return row is not None


def email_exists_as_alias(email_addr: str, exclude_account_id: Optional[int] = None) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    if exclude_account_id is None:
        row = db.execute(
            'SELECT account_id FROM account_aliases WHERE LOWER(alias_email) = ? LIMIT 1',
            (normalized,)
        ).fetchone()
    else:
        row = db.execute(
            'SELECT account_id FROM account_aliases WHERE LOWER(alias_email) = ? AND account_id != ? LIMIT 1',
            (normalized, exclude_account_id)
        ).fetchone()
    return row is not None


def email_exists_as_temp(email_addr: str) -> bool:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return False
    db = get_db()
    row = db.execute('SELECT id FROM temp_emails WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    return row is not None


def validate_account_aliases(account_id: int, primary_email: str, aliases: List[str]) -> tuple[List[str], List[str]]:
    cleaned = []
    errors = []
    seen = set()
    primary_normalized = normalize_email_address(primary_email)

    for raw_alias in aliases:
        normalized = normalize_email_address(raw_alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        if normalized == primary_normalized:
            errors.append(f'别名 {normalized} 不能与主邮箱相同')
            continue
        if email_exists_as_primary(normalized, exclude_account_id=account_id):
            errors.append(f'别名 {normalized} 已被其他主邮箱占用')
            continue
        if email_exists_as_alias(normalized, exclude_account_id=account_id):
            errors.append(f'别名 {normalized} 已被其他账号使用')
            continue
        if email_exists_as_temp(normalized):
            errors.append(f'别名 {normalized} 与临时邮箱地址冲突')
            continue

        cleaned.append(normalized)

    return cleaned, errors


def replace_account_aliases(account_id: int, primary_email: str, aliases: List[str], db=None) -> tuple[bool, List[str], List[str]]:
    database = db or get_db()
    cleaned_aliases, errors = validate_account_aliases(account_id, primary_email, aliases)
    if errors:
        return False, cleaned_aliases, errors

    try:
        database.execute('DELETE FROM account_aliases WHERE account_id = ?', (account_id,))
        for alias_email in cleaned_aliases:
            database.execute(
                '''
                INSERT INTO account_aliases (account_id, alias_email, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ''',
                (account_id, alias_email)
            )
        return True, cleaned_aliases, []
    except sqlite3.IntegrityError:
        return False, cleaned_aliases, ['别名保存失败，可能存在重复或冲突']


def resolve_account_record(row: sqlite3.Row, matched_alias: str = '') -> Dict[str, Any]:
    account = dict(row)
    if account.get('password'):
        try:
            account['password'] = decrypt_data(account['password'])
        except Exception:
            pass
    if account.get('refresh_token'):
        try:
            account['refresh_token'] = decrypt_data(account['refresh_token'])
        except Exception:
            pass
    if account.get('imap_password'):
        try:
            account['imap_password'] = decrypt_data(account['imap_password'])
        except Exception:
            pass
    account['provider'] = normalize_provider(account.get('provider'), account.get('email', ''))
    account['account_type'] = account.get('account_type') or get_provider_meta(
        account['provider'], account.get('email', '')
    ).get('account_type', 'outlook')
    account['aliases'] = get_account_aliases(account['id'])
    account['alias_count'] = len(account['aliases'])
    account['requested_email'] = matched_alias or account.get('email', '')
    account['matched_alias'] = matched_alias if matched_alias else ''
    return account


def resolve_account_by_address(email_addr: str) -> Optional[Dict]:
    normalized = normalize_email_address(email_addr)
    if not normalized:
        return None

    db = get_db()
    row = db.execute('SELECT * FROM accounts WHERE LOWER(email) = ? LIMIT 1', (normalized,)).fetchone()
    if row:
        return resolve_account_record(row)

    alias_row = db.execute(
        '''
        SELECT a.*, aa.alias_email AS matched_alias
        FROM account_aliases aa
        JOIN accounts a ON a.id = aa.account_id
        WHERE LOWER(aa.alias_email) = ?
        LIMIT 1
        ''',
        (normalized,)
    ).fetchone()
    if not alias_row:
        return None
    return resolve_account_record(alias_row, matched_alias=alias_row['matched_alias'])


def get_account_proxy_url(account: Optional[Dict[str, Any]]) -> str:
    if not account or not account.get('group_id'):
        return ''
    group = get_group_by_id(account['group_id'])
    if not group:
        return ''
    return group.get('proxy_url', '') or ''



def get_account_by_email(email_addr: str) -> Optional[Dict]:
    """根据邮箱地址获取账号"""
    return resolve_account_by_address(email_addr)


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
    if not row:
        return None
    return resolve_account_record(row)


def get_latest_account_refresh_log(account_id: int, db=None) -> Optional[Dict[str, Any]]:
    """获取账号最近一次刷新结果"""
    database = db or get_db()
    row = database.execute(
        '''
        SELECT status, error_message, created_at
        FROM account_refresh_logs
        WHERE account_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        ''',
        (account_id,)
    ).fetchone()
    return dict(row) if row else None


def serialize_account_summary(account: Dict[str, Any], last_refresh_log: Optional[Dict[str, Any]] = None,
                              include_client_meta: bool = True,
                              include_imap_meta: bool = True) -> Dict[str, Any]:
    """序列化账号摘要，默认隐藏敏感字段"""
    client_id = account.get('client_id') or ''
    payload = {
        'id': account['id'],
        'email': account['email'],
        'aliases': account.get('aliases', []),
        'alias_count': account.get('alias_count', 0),
        'group_id': account.get('group_id'),
        'group_name': account.get('group_name', '默认分组'),
        'group_color': account.get('group_color', '#666666'),
        'remark': account.get('remark', ''),
        'status': account.get('status', 'active'),
        'account_type': account.get('account_type', 'outlook'),
        'provider': account.get('provider', 'outlook'),
        'forward_enabled': bool(account.get('forward_enabled')),
        'last_refresh_at': account.get('last_refresh_at', ''),
        'last_refresh_status': last_refresh_log['status'] if last_refresh_log else None,
        'last_refresh_error': last_refresh_log['error_message'] if last_refresh_log else None,
        'created_at': account.get('created_at', ''),
        'updated_at': account.get('updated_at', ''),
        'tags': account.get('tags', [])
    }
    if include_client_meta:
        payload['client_id'] = (
            client_id[:8] + '...' if client_id and len(client_id) > 8 else client_id
        )
    if include_imap_meta:
        payload['imap_host'] = account.get('imap_host', '')
        payload['imap_port'] = account.get('imap_port', 993)
    return payload


def add_account(email_addr: str, password: str, client_id: str = '', refresh_token: str = '',
                group_id: int = 1, remark: str = '', account_type: str = 'outlook',
                provider: str = 'outlook', imap_host: str = '', imap_port: int = 993,
                imap_password: str = '', forward_enabled: bool = False) -> bool:
    """添加邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password
        provider_meta = get_provider_meta(provider, email_addr)
        provider = provider_meta['key']
        account_type = account_type or provider_meta.get('account_type', 'outlook')
        imap_host = imap_host or provider_meta.get('imap_host', '')
        imap_port = int(imap_port or provider_meta.get('imap_port', 993) or 993)
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password
        provider_meta = get_provider_meta(provider, email_addr)
        provider = provider_meta['key']
        account_type = account_type or provider_meta.get('account_type', 'outlook')
        imap_host = imap_host or provider_meta.get('imap_host', '')
        imap_port = int(imap_port or provider_meta.get('imap_port', 993) or 993)

        db.execute('''
            INSERT INTO accounts (
                email, password, client_id, refresh_token, group_id, remark,
                account_type, provider, imap_host, imap_port, imap_password, forward_enabled,
                forward_last_checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark,
            account_type, provider, imap_host, imap_port, encrypted_imap_password, 1 if forward_enabled else 0,
            datetime.now(timezone.utc).isoformat() if forward_enabled else None
        ))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_account(account_id: int, email_addr: str, password: str, client_id: str,
                   refresh_token: str, group_id: int, remark: str, status: str,
                   account_type: str = 'outlook', provider: str = 'outlook',
                   imap_host: str = '', imap_port: int = 993, imap_password: str = '',
                   forward_enabled: bool = False) -> bool:
    """更新邮箱账号"""
    db = get_db()
    try:
        # 加密敏感字段
        encrypted_password = encrypt_data(password) if password else password
        encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else refresh_token
        encrypted_imap_password = encrypt_data(imap_password) if imap_password else imap_password

        current_account = db.execute(
            'SELECT forward_enabled, forward_last_checked_at FROM accounts WHERE id = ?',
            (account_id,)
        ).fetchone()
        should_init_forward_cursor = bool(
            forward_enabled and current_account and not current_account['forward_enabled']
        )

        if should_init_forward_cursor:
            db.execute('''
                UPDATE accounts
                SET email = ?, password = ?, client_id = ?, refresh_token = ?,
                    group_id = ?, remark = ?, status = ?, account_type = ?, provider = ?,
                    imap_host = ?, imap_port = ?, imap_password = ?, forward_enabled = ?,
                    forward_last_checked_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark, status,
                account_type, provider, imap_host, imap_port, encrypted_imap_password, 1,
                datetime.now(timezone.utc).isoformat(), account_id
            ))
        else:
            db.execute('''
                UPDATE accounts
                SET email = ?, password = ?, client_id = ?, refresh_token = ?,
                    group_id = ?, remark = ?, status = ?, account_type = ?, provider = ?,
                    imap_host = ?, imap_port = ?, imap_password = ?, forward_enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                email_addr, encrypted_password, client_id, encrypted_refresh_token, group_id, remark, status,
                account_type, provider, imap_host, imap_port, encrypted_imap_password, 1 if forward_enabled else 0,
                account_id
            ))
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


def normalize_account_ids(account_ids: List[int]) -> List[int]:
    """归一化账号 ID 列表，过滤非法值并去重。"""
    normalized_ids = []
    seen_ids = set()
    for account_id in account_ids or []:
        try:
            normalized_id = int(account_id)
        except (TypeError, ValueError):
            continue
        if normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)
    return normalized_ids


def delete_accounts_by_ids(account_ids: List[int]) -> Dict[str, Any]:
    """批量删除邮箱账号。"""
    db = get_db()
    normalized_ids = normalize_account_ids(account_ids)

    if not normalized_ids:
        return {'success': False, 'error': '请选择要删除的账号'}

    placeholders = ','.join('?' * len(normalized_ids))
    rows = db.execute(f'''
        SELECT id, email
        FROM accounts
        WHERE id IN ({placeholders})
        ORDER BY email COLLATE NOCASE ASC
    ''', normalized_ids).fetchall()

    if not rows:
        return {'success': False, 'error': '未找到可删除的账号'}

    existing_ids = [row['id'] for row in rows]
    deleted_accounts = [{'id': row['id'], 'email': row['email']} for row in rows]
    missing_ids = [account_id for account_id in normalized_ids if account_id not in set(existing_ids)]

    try:
        delete_placeholders = ','.join('?' * len(existing_ids))
        db.execute(f'DELETE FROM accounts WHERE id IN ({delete_placeholders})', existing_ids)
        db.commit()
        return {
            'success': True,
            'deleted_count': len(existing_ids),
            'deleted_accounts': deleted_accounts,
            'missing_ids': missing_ids,
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}


def update_accounts_forwarding_by_ids(account_ids: List[int], forward_enabled: bool) -> Dict[str, Any]:
    """批量更新账号转发开关。"""
    db = get_db()
    normalized_ids = normalize_account_ids(account_ids)

    if not normalized_ids:
        return {'success': False, 'error': '请选择要修改的账号'}

    placeholders = ','.join('?' * len(normalized_ids))
    rows = db.execute(
        f'''
        SELECT id, email, COALESCE(forward_enabled, 0) AS forward_enabled
        FROM accounts
        WHERE id IN ({placeholders})
        ORDER BY email COLLATE NOCASE ASC
        ''',
        normalized_ids
    ).fetchall()

    if not rows:
        return {'success': False, 'error': '未找到可修改的账号'}

    target_value = 1 if forward_enabled else 0
    existing_ids = [row['id'] for row in rows]
    existing_id_set = set(existing_ids)
    missing_ids = [account_id for account_id in normalized_ids if account_id not in existing_id_set]
    updated_rows = [row for row in rows if int(row['forward_enabled'] or 0) != target_value]
    updated_ids = [row['id'] for row in updated_rows]
    updated_accounts = [{'id': row['id'], 'email': row['email']} for row in updated_rows]
    unchanged_count = len(rows) - len(updated_rows)

    try:
        if updated_ids:
            update_placeholders = ','.join('?' * len(updated_ids))
            if forward_enabled:
                db.execute(
                    f'''
                    UPDATE accounts
                    SET forward_enabled = 1,
                        forward_last_checked_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({update_placeholders})
                    ''',
                    [datetime.now(timezone.utc).isoformat()] + updated_ids
                )
            else:
                db.execute(
                    f'''
                    UPDATE accounts
                    SET forward_enabled = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({update_placeholders})
                    ''',
                    updated_ids
                )
            db.commit()

        return {
            'success': True,
            'updated_count': len(updated_ids),
            'updated_accounts': updated_accounts,
            'unchanged_count': unchanged_count,
            'missing_ids': missing_ids,
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}


def set_account_forward_cursor(account_id: int, cursor_value: Optional[str]) -> bool:
    """设置账号转发游标。"""
    db = get_db()
    try:
        db.execute(
            '''
            UPDATE accounts
            SET forward_last_checked_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (cursor_value, account_id)
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


# ==================== 工具函数 ====================

def sanitize_input(text: str, max_length: int = 500) -> str:
    """
    净化用户输入，防止XSS攻击
    - 转义HTML特殊字符
    - 限制长度
    - 移除控制字符
    """
    if not text:
        return ""

    # 限制长度
    text = text[:max_length]

    # 移除控制字符（保留换行和制表符）
    text = ''.join(char for char in text if char.isprintable() or char in '\n\t')

    # 转义HTML特殊字符
    text = html.escape(text, quote=True)

    return text


def log_audit(action: str, resource_type: str, resource_id: str = None, details: str = None):
    """
    记录审计日志
    :param action: 操作类型（如 'export', 'delete', 'update'）
    :param resource_type: 资源类型（如 'account', 'group'）
    :param resource_id: 资源ID
    :param details: 详细信息
    """
    try:
        db = get_db()
        user_ip = request.remote_addr if request else 'unknown'
        db.execute('''
            INSERT INTO audit_logs (action, resource_type, resource_id, user_ip, details)
            VALUES (?, ?, ?, ?, ?)
        ''', (action, resource_type, resource_id, user_ip, details))
        db.commit()
    except Exception:
        # 审计日志失败不应影响主流程
        pass


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


def get_email_html_body(msg) -> str:
    """提取邮件 HTML 正文"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/html" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='replace')
                except Exception:
                    continue
    elif msg.get_content_type() == "text/html":
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            return payload.decode(charset, errors='replace')
        except Exception:
            return ""

    return ""


def generate_random_temp_name() -> str:
    """生成临时邮箱用户名"""
    return f"{secrets.token_hex(3)}{secrets.randbelow(1000)}"


def build_cloudflare_domain_candidates(domain: str) -> List[str]:
    """为 Cloudflare 创建邮箱生成可回退的域名候选列表"""
    normalized = domain.strip().lower().lstrip('@').rstrip('.')
    if not normalized:
        return []

    candidates: List[str] = [normalized]
    labels = [label for label in normalized.split('.') if label]
    if len(labels) < 3:
        return candidates

    common_second_level_suffixes = {
        'com.cn', 'net.cn', 'org.cn', 'gov.cn', 'edu.cn',
        'co.uk', 'org.uk', 'ac.uk',
        'com.hk', 'com.sg',
        'com.au', 'net.au', 'org.au',
        'co.jp'
    }

    last_two = '.'.join(labels[-2:])
    last_three = '.'.join(labels[-3:]) if len(labels) >= 3 else ''

    if last_three and last_two in common_second_level_suffixes:
        if last_three not in candidates:
            candidates.append(last_three)
    elif last_two not in candidates:
        candidates.append(last_two)

    if last_three and last_three not in candidates:
        candidates.append(last_three)

    return candidates


def parse_raw_email_to_temp_message(email_addr: str, raw_email: str, fallback_id: str = None,
                                    fallback_timestamp: int = 0) -> Dict[str, Any]:
    """将原始邮件解析为统一的临时邮箱消息格式"""
    if isinstance(raw_email, str):
        msg = email.message_from_string(raw_email)
    else:
        msg = email.message_from_bytes(raw_email)

    text_content = get_email_body(msg)
    html_content = get_email_html_body(msg)
    message_id = decode_header_value(msg.get('Message-ID', '')).strip()
    date_header = decode_header_value(msg.get('Date', '')).strip()
    timestamp = fallback_timestamp

    if date_header:
        try:
            parsed_date = email.utils.parsedate_to_datetime(date_header)
            timestamp = int(parsed_date.timestamp())
        except Exception:
            pass

    final_message_id = (
        fallback_id
        or message_id
        or hashlib.sha256(f"{email_addr}\n{raw_email}".encode('utf-8', 'replace')).hexdigest()
    )

    return {
        'id': final_message_id,
        'from_address': decode_header_value(msg.get('From', '未知发件人')),
        'subject': decode_header_value(msg.get('Subject', '无主题')),
        'content': text_content,
        'html_content': html_content,
        'has_html': bool(html_content),
        'timestamp': timestamp,
        'raw_content': raw_email if isinstance(raw_email, str) else raw_email.decode('utf-8', 'replace')
    }


# 重写导入解析函数，支持多种账号字段顺序
def is_probable_client_id(value: str) -> bool:
    candidate = str(value or '').strip()
    if not candidate:
        return False
    try:
        uuid.UUID(candidate)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def resolve_outlook_token_order(third: str, fourth: str,
                                account_format: str = 'client_id_refresh_token') -> tuple[str, str]:
    third = str(third or '').strip()
    fourth = str(fourth or '').strip()

    # Azure / Microsoft public client_id is normally a UUID. If one side clearly
    # looks like client_id and the other does not, auto-detect the order so that
    # pasted import lines keep working even when the UI format selector is wrong.
    third_is_client_id = is_probable_client_id(third)
    fourth_is_client_id = is_probable_client_id(fourth)
    if third_is_client_id and not fourth_is_client_id:
        return third, fourth
    if fourth_is_client_id and not third_is_client_id:
        return fourth, third

    if account_format == 'refresh_token_client_id':
        return fourth, third
    return third, fourth


def parse_account_string(account_str: str, account_format: str = 'client_id_refresh_token') -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 4 or not parts[0]:
        return None

    email_addr, password, third, fourth = parts[:4]
    client_id, refresh_token = resolve_outlook_token_order(third, fourth, account_format)

    if not client_id or not refresh_token:
        return None

    return {
        'email': email_addr,
        'password': password,
        'client_id': client_id,
        'refresh_token': refresh_token
    }


# ==================== Graph API 方式 ====================


def parse_outlook_account_string(account_str: str, account_format: str = 'client_id_refresh_token') -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 4 or not parts[0]:
        return None

    email_addr, password, third, fourth = parts[:4]
    client_id, refresh_token = resolve_outlook_token_order(third, fourth, account_format)

    if not client_id or not refresh_token:
        return None

    return {
        'email': email_addr,
        'password': password,
        'client_id': client_id,
        'refresh_token': refresh_token,
        'provider': 'outlook',
        'account_type': 'outlook',
        'imap_host': IMAP_SERVER_NEW,
        'imap_port': IMAP_PORT,
        'imap_password': '',
    }


def parse_imap_account_string(account_str: str, provider: str = 'custom', imap_host: str = '', imap_port: int = 993) -> Optional[Dict]:
    parts = [part.strip() for part in account_str.strip().split('----')]
    if len(parts) < 2 or not parts[0]:
        return None

    email_addr = parts[0]
    password = parts[1]
    provider_meta = get_provider_meta(provider, email_addr)
    provider_key = provider_meta['key']

    if provider_key == 'custom':
        if len(parts) >= 4:
            imap_host = parts[2].strip() or imap_host
            try:
                imap_port = int(parts[3].strip() or imap_port or 993)
            except ValueError:
                return None
        if not imap_host:
            return None
    else:
        imap_host = provider_meta.get('imap_host', '')
        imap_port = int(provider_meta.get('imap_port', 993) or 993)

    if not password or not imap_host:
        return None

    return {
        'email': email_addr,
        'password': '',
        'client_id': '',
        'refresh_token': '',
        'provider': provider_key,
        'account_type': 'imap',
        'imap_host': imap_host,
        'imap_port': int(imap_port or 993),
        'imap_password': password,
    }


def parse_account_import(account_str: str, account_format: str = 'client_id_refresh_token',
                         provider: str = 'outlook', imap_host: str = '', imap_port: int = 993) -> Optional[Dict]:
    provider_key = normalize_provider(provider, account_str.split('----', 1)[0].strip() if account_str else '')
    if provider_key == 'outlook':
        return parse_outlook_account_string(account_str, account_format)
    return parse_imap_account_string(account_str, provider_key, imap_host, imap_port)

