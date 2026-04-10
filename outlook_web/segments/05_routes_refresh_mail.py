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


def test_refresh_token(client_id: str, refresh_token: str, proxy_url: str = None) -> tuple[bool, str]:
    """测试 refresh token 是否有效，返回 (是否成功, 错误信息)"""
    try:
        # 尝试使用 Graph API 获取 access token
        # 使用与 get_access_token_graph 相同的 scope，确保一致性
        proxies = build_proxies(proxy_url)
        res = requests.post(
            TOKEN_URL_GRAPH,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30,
            proxies=proxies
        )

        if res.status_code == 200:
            return True, None
        else:
            error_data = res.json()
            error_msg = error_data.get('error_description', error_data.get('error', '未知错误'))
            return False, error_msg
    except Exception as e:
        return False, f"请求异常: {str(e)}"


def refresh_outlook_account_token(account: sqlite3.Row, refresh_type: str = 'manual') -> Dict[str, Any]:
    """刷新单个 Outlook 账号的 refresh token 并记录结果。"""
    account_id = account['id']
    account_email = account['email']
    client_id = account['client_id']
    encrypted_refresh_token = account['refresh_token']

    # 获取分组代理设置
    proxy_url = ''
    if account['group_id']:
        group = get_group_by_id(account['group_id'])
        if group:
            proxy_url = group.get('proxy_url', '') or ''

    # 解密 refresh_token
    try:
        refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
    except Exception as e:
        error_msg = sanitize_error_details(f"解密 token 失败: {str(e)}")
        log_refresh_result(account_id, account_email, refresh_type, 'failed', error_msg)
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

    success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)
    sanitized_error = sanitize_error_details(error_msg) if error_msg else ''

    # 记录刷新结果
    log_refresh_result(account_id, account_email, refresh_type, 'success' if success else 'failed', sanitized_error or None)

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


@app.route('/api/accounts/refresh-all', methods=['GET'])
@login_required
def api_refresh_all_accounts():
    """刷新所有账号的 token（流式响应，实时返回进度）"""
    import json
    import time

    def generate():
        # 在生成器内部直接创建数据库连接
        conn = sqlite3.connect(DATABASE)
        conn.execute('PRAGMA foreign_keys = ON')
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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active' AND COALESCE(account_type, 'outlook') = 'outlook'")
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
                encrypted_refresh_token = account['refresh_token']

                # 解密 refresh_token
                try:
                    refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
                except Exception as e:
                    # 解密失败，记录错误
                    failed_count += 1
                    error_msg = f"解密 token 失败: {str(e)}"
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })
                    try:
                        conn.execute('''
                            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (account_id, account_email, 'manual', 'failed', error_msg))
                        conn.commit()
                    except Exception:
                        pass
                    continue

                # 发送当前处理的账号信息
                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                # 获取分组代理设置
                proxy_url = ''
                group_id = account['group_id']
                if group_id:
                    group_cursor = conn.execute('SELECT proxy_url FROM groups WHERE id = ?', (group_id,))
                    group_row = group_cursor.fetchone()
                    if group_row:
                        proxy_url = group_row['proxy_url'] or ''

                # 测试 refresh token
                success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

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
        encrypted_refresh_token = account['refresh_token']

        # 解密 refresh_token
        try:
            refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
        except Exception as e:
            # 解密失败，记录错误
            failed_count += 1
            error_msg = f"解密 token 失败: {str(e)}"
            failed_list.append({
                'id': account_id,
                'email': account_email,
                'error': error_msg
            })
            log_refresh_result(account_id, account_email, 'retry', 'failed', error_msg)
            continue

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
        conn.execute('PRAGMA foreign_keys = ON')
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

            cursor = conn.execute("SELECT id, email, client_id, refresh_token, group_id FROM accounts WHERE status = 'active' AND COALESCE(account_type, 'outlook') = 'outlook'")
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
                encrypted_refresh_token = account['refresh_token']

                # 解密 refresh_token
                try:
                    refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
                except Exception as e:
                    # 解密失败，记录错误
                    failed_count += 1
                    error_msg = f"解密 token 失败: {str(e)}"
                    failed_list.append({
                        'id': account_id,
                        'email': account_email,
                        'error': error_msg
                    })
                    try:
                        conn.execute('''
                            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (account_id, account_email, 'scheduled', 'failed', error_msg))
                        conn.commit()
                    except Exception:
                        pass
                    continue

                yield f"data: {json.dumps({'type': 'progress', 'current': index, 'total': total, 'email': account_email, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                # 获取分组代理设置
                proxy_url = ''
                group_id = account['group_id']
                if group_id:
                    group_cursor = conn.execute('SELECT proxy_url FROM groups WHERE id = ?', (group_id,))
                    group_row = group_cursor.fetchone()
                    if group_row:
                        proxy_url = group_row['proxy_url'] or ''

                success, error_msg = test_refresh_token(client_id, refresh_token, proxy_url)

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



# ==================== Email Deletion Helpers ====================

def delete_emails_graph(client_id: str, refresh_token: str, message_ids: List[str], proxy_url: str = None) -> Dict[str, Any]:
    """通过 Graph API 批量删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url)
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
            proxies = build_proxies(proxy_url)
            response = requests.post(
                "https://graph.microsoft.com/v1.0/$batch",
                headers=headers,
                json={"requests": batch_requests},
                timeout=30,
                proxies=proxies
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
                       proxy_url: str = None) -> Dict[str, Any]:
    """通过 IMAP 删除邮件（永久删除）"""
    access_token = get_access_token_graph(client_id, refresh_token, proxy_url)
    if not access_token:
        return {"success": False, "error": "获取 Access Token 失败"}
        
    try:
        # 生成 OAuth2 认证字符串
        auth_string = 'user=%s\x01auth=Bearer %s\x01\x01' % (email_addr, access_token)
        
        # 连接 IMAP
        with proxy_socket_context(proxy_url):
            imap = imaplib.IMAP4_SSL(server, IMAP_PORT)
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


def format_graph_email_item(item: Dict[str, Any], folder: str) -> Dict[str, Any]:
    return {
        'id': item.get('id'),
        'subject': item.get('subject', '无主题'),
        'from': item.get('from', {}).get('emailAddress', {}).get('address', '未知'),
        'date': item.get('receivedDateTime', ''),
        'is_read': item.get('isRead', False),
        'has_attachments': item.get('hasAttachments', False),
        'body_preview': item.get('bodyPreview', ''),
        'folder': folder,
    }


def format_email_items(items: List[Dict[str, Any]], folder: str) -> List[Dict[str, Any]]:
    formatted = []
    for item in items:
        row = dict(item)
        row['folder'] = row.get('folder') or folder
        formatted.append(row)
    return formatted


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
    for folder, result in results.items():
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
    }
    if partial_errors:
        response['partial'] = True
        response['details'] = partial_errors
    return response


def fetch_account_folder_emails(account: Dict[str, Any], folder: str, skip: int, top: int,
                                proxy_url: str = '') -> Dict[str, Any]:
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
            }
        return {
            'success': False,
            'error': result.get('error', '获取邮件失败'),
            'details': {'imap_generic': result.get('error')}
        }

    all_errors = {}
    graph_result = get_emails_graph(account['client_id'], account['refresh_token'], folder_name, skip, top, proxy_url)
    if graph_result.get('success'):
        return {
            'success': True,
            'emails': [format_graph_email_item(item, folder_name) for item in graph_result.get('emails', [])],
            'method': 'Graph API',
            'has_more': len(graph_result.get('emails', [])) >= top,
        }

    graph_error = graph_result.get('error')
    all_errors['graph'] = graph_error
    if isinstance(graph_error, dict) and graph_error.get('type') in ('ProxyError', 'ConnectionError'):
        connection_error_message = (
            '代理连接失败，请检查分组代理设置'
            if proxy_url
            else '连接 Microsoft 服务失败，请检查服务器网络、DNS 或上游访问能力'
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
        proxy_url
    )
    if imap_new_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_new_result.get('emails', []), folder_name),
            'method': 'IMAP (New)',
            'has_more': bool(imap_new_result.get('has_more')),
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
        proxy_url
    )
    if imap_old_result.get('success'):
        return {
            'success': True,
            'emails': format_email_items(imap_old_result.get('emails', []), folder_name),
            'method': 'IMAP (Old)',
            'has_more': bool(imap_old_result.get('has_more')),
        }
    all_errors['imap_old'] = imap_old_result.get('error')

    return {
        'success': False,
        'error': '无法获取邮件，所有方式均失败',
        'details': all_errors
    }


def fetch_account_emails(account: Dict[str, Any], folder: str, skip: int, top: int) -> Dict[str, Any]:
    proxy_url = get_account_proxy_url(account)
    folder_name = normalize_folder_name(folder)
    if folder_name not in VALID_MAIL_FOLDERS:
        return {
            'success': False,
            'error': f'folder 参数无效，支持: {", ".join(sorted(VALID_MAIL_FOLDERS))}'
        }

    if folder_name == 'all':
        merged_top = max(1, min(100, top * 2))
        return merge_folder_results(
            {
                'inbox': fetch_account_folder_emails(account, 'inbox', skip, top, proxy_url),
                'junkemail': fetch_account_folder_emails(account, 'junkemail', skip, top, proxy_url),
            },
            0,
            merged_top
        )

    return fetch_account_folder_emails(account, folder_name, skip, top, proxy_url)


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
    if result.get('success'):
        db = get_db()
        db.execute(
            '''
            UPDATE accounts
            SET last_refresh_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (account['id'],)
        )
        db.commit()
    return jsonify(result)

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

    # 1. 优先尝试 Graph API
    if account.get('account_type') == 'imap':
        return jsonify({'success': False, 'error': 'IMAP 账号暂不支持批量删除邮件'})

    graph_res = delete_emails_graph(account['client_id'], account['refresh_token'], message_ids, proxy_url)
    if graph_res['success']:
        return jsonify(graph_res)

    # 如果是代理错误，不再回退 IMAP
    graph_error = graph_res.get('error', '')
    if isinstance(graph_error, str) and 'ProxyError' in graph_error:
        return jsonify(graph_res)
    
    # 2. 尝试 IMAP 回退（新服务器）
    imap_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_NEW, proxy_url)
    if imap_res['success']:
        return jsonify(imap_res)

    # 3. 尝试 IMAP 回退（旧服务器）
    imap_old_res = delete_emails_imap(account['email'], account['client_id'], account['refresh_token'], message_ids, IMAP_SERVER_OLD, proxy_url)
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
        detail = get_email_detail_graph(account['client_id'], account['refresh_token'], message_id, proxy_url)
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
    detail = get_email_detail_imap(account['email'], account['client_id'], account['refresh_token'], message_id, folder, proxy_url)
    if detail:
        return jsonify({'success': True, 'email': detail})

    return jsonify({'success': False, 'error': '获取邮件详情失败'})
