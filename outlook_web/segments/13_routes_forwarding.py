"""Named notification channels and source routing endpoints."""


@app.route('/forwarding')
@login_required
def forwarding_management_page():
    return index()


def sync_legacy_forwarding(db=None, *, update_associations=True):
    db = db if db is not None else get_db()
    forwarding_store.sync_legacy(db, encrypt_data, decrypt_data, update_associations=update_associations)
    db.commit()


def notification_channel_payload(row, db=None):
    return forwarding_store.public_channel(db if db is not None else get_db(), row, decrypt_data)


def forwarding_api_error(exc):
    if isinstance(exc, sqlite3.IntegrityError):
        return jsonify({'success': False, 'error': '名称已存在或配置仍被引用'}), 400
    return jsonify({'success': False, 'error': str(exc)}), 400


@app.route('/api/notification-channels', methods=['GET', 'POST'])
@login_required
def api_notification_channels():
    db = get_db()
    if request.method == 'GET':
        return jsonify({'success': True, 'channels': [notification_channel_payload(dict(row), db)
                        for row in db.execute('SELECT * FROM notification_channels ORDER BY id')]})
    try:
        row = forwarding_store.save_channel(db, request.get_json(silent=True), encrypt_data, decrypt_data)
        db.commit()
        return jsonify({'success': True, 'channel': notification_channel_payload(row, db)})
    except (ValueError, sqlite3.IntegrityError) as exc:
        db.rollback()
        return forwarding_api_error(exc)


@app.route('/api/notification-channels/<int:channel_id>', methods=['PUT', 'DELETE'])
@login_required
def api_notification_channel(channel_id):
    db = get_db()
    try:
        old = forwarding_store.get_channel(db, channel_id)
        if not old:
            raise ValueError('通知渠道不存在')
        if request.method == 'DELETE':
            view = notification_channel_payload(old, db)
            if view['reference_count'] or view['pending_count']:
                raise ValueError(f"渠道仍有 {view['reference_count']} 个来源关联和 {view['pending_count']} 项未完成投递，请先解除关联或停用")
            db.execute('DELETE FROM notification_channels WHERE id=?', (channel_id,))
            db.commit()
            return jsonify({'success': True})
        row = forwarding_store.save_channel(db, request.get_json(silent=True), encrypt_data, decrypt_data, channel_id)
        db.commit()
        reconcile_forwarding_deliveries()
        return jsonify({'success': True, 'channel': notification_channel_payload(row, db)})
    except (ValueError, sqlite3.IntegrityError) as exc:
        db.rollback()
        return forwarding_api_error(exc)


def send_notification_instance(row, payload):
    config = forwarding_store.decode_config(row, decrypt_data)
    kind = row['type']
    if kind == 'smtp':
        return send_forward_email(payload[0], payload[1], payload[2], config=config)
    sender = {'telegram': send_forward_telegram, 'wecom': send_forward_wecom, 'feishu': send_forward_feishu}[kind]
    return sender(payload[3], config=config)


@app.route('/api/notification-channels/test', methods=['POST'])
@login_required
def api_notification_channel_test():
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict):
            raise ValueError('测试配置必须为对象')
        old = forwarding_store.get_channel(get_db(), data['id']) if data.get('id') else None
        if data.get('id') and not old:
            raise ValueError('通知渠道不存在')
        kind = data.get('type', old['type'] if old else '')
        if old and kind != old['type']:
            raise ValueError('不能改变测试实例类型')
        config = forwarding_store.merge_config(kind, data.get('config', {}), forwarding_store.decode_config(old, decrypt_data) if old else {})
        row = {'type': kind, 'config_json': forwarding_store.encode_config(config, encrypt_data)}
        payload = ('[邮件转发] 测试消息', '这是一条通知渠道测试消息。', '', '[邮件转发] 这是一条通知渠道测试消息。')
        try:
            success = send_notification_instance(row, payload)
        except Exception as exc:
            raise ValueError(safe_notification_error(exc, config)) from None
        return jsonify({'success': bool(success), 'message': '测试消息已发送' if success else '测试发送失败，请检查渠道配置'})
    except (ValueError, sqlite3.IntegrityError) as exc:
        return forwarding_api_error(exc)


@app.route('/api/forwarding/policies', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@login_required
def api_forwarding_policies():
    db = get_db()
    try:
        if request.method == 'PATCH':
            db.execute('BEGIN IMMEDIATE')
            results = forwarding_store.update_policies(db, request.get_json(silent=True))
            db.commit()
            reconcile_forwarding_deliveries()
            return jsonify({'success': True, 'policies': results, 'count': len(results)})
        if request.method == 'DELETE':
            data = request.get_json(silent=True)
            if isinstance(data, dict) and 'policy_ids' in data:
                db.execute('BEGIN IMMEDIATE')
                rows = forwarding_store.selected_policies(db, data['policy_ids'])
                scopes = [(row['scope_type'], row['scope_id'], row['match_value']) for row in rows]
            else:
                scopes = forwarding_store.policy_scopes(db, data)
            for scope in scopes:
                if scope[0] in ('normal_default', 'cloudflare_worker'):
                    db.execute('DELETE FROM forwarding_policies WHERE scope_type=? AND scope_id=? AND match_value=?', scope)
                    if scope[0] == 'normal_default':
                        db.execute("UPDATE settings SET value='none' WHERE key='forward_channels'")
                else:
                    forwarding_store.save_policy(db, {'scope_type': scope[0], 'scope_id': scope[1], 'match_value': scope[2], 'mode': 'inherit'})
            db.commit()
            reconcile_forwarding_deliveries()
            return jsonify({'success': True, 'count': len(scopes)})
        if request.method in ('POST', 'PUT'):
            data = request.get_json(silent=True)
            scopes = forwarding_store.policy_scopes(db, data)
            results = [forwarding_store.save_policy(db, {**data, 'scope_type': scope[0], 'scope_id': scope[1], 'match_value': scope[2]}, create_only=request.method == 'POST') for scope in scopes]
            db.commit()
            reconcile_forwarding_deliveries()
            return jsonify({'success': True, 'policy': results[0], 'policies': results, 'count': len(results)})
        if request.args.get('scope_type'):
            data = {'scope_type': request.args['scope_type'], 'scope_id': request.args.get('scope_id', 0), 'match_value': request.args.get('match_value', '')}
            if 'scope_ids' in request.args:
                data['scope_ids'] = request.args['scope_ids'].split(',')
            results = [forwarding_store.get_policy(db, *scope) for scope in forwarding_store.policy_scopes(db, data)]
            return jsonify({'success': True, 'policy': results[0], 'policies': results})
        rows = db.execute('SELECT scope_type,scope_id,match_value FROM forwarding_policies ORDER BY scope_type,scope_id,match_value').fetchall()
        return jsonify({'success': True, 'policies': [forwarding_store.get_policy(db, *tuple(r)) for r in rows]})
    except (ValueError, sqlite3.IntegrityError) as exc:
        db.rollback()
        return forwarding_api_error(exc)


@app.route('/api/forwarding/preview', methods=['GET'])
@login_required
def api_forwarding_preview():
    try:
        if request.args.get('account_id'):
            result = forwarding_store.resolve_policy(get_db(), account_id=int(request.args['account_id']))
        else:
            result = forwarding_store.resolve_policy(get_db(), worker_id=int(request.args.get('worker_id', 0)), address=request.args.get('address', ''))
        return jsonify({'success': True, 'preview': result})
    except (ValueError, TypeError) as exc:
        return forwarding_api_error(exc)


def safe_notification_error(exc, config=None):
    text = stringify_forward_error(exc)
    for field, value in (config or {}).items():
        if field in forwarding_store.SECRET_FIELDS and isinstance(value, str) and value:
            text = text.replace(value, '[已隐藏]')
    text = re.sub(r'https?://\S+', '[通知地址已隐藏]', text)
    return text[:500] or '通知发送失败'


def resolve_event_policy(db, event):
    if event['source_type'] == 'account':
        return forwarding_store.resolve_policy(db, account_id=event['source_id'])
    return forwarding_store.resolve_policy(db, worker_id=event['source_id'], address=event['email_address'])


def reconcile_forwarding_deliveries(db=None, event_id=None):
    db = db if db is not None else get_db()
    query = "SELECT d.*,e.source_type,e.source_id,e.email_address FROM forwarding_deliveries d JOIN forwarding_events e ON e.id=d.event_id WHERE d.status IN ('pending','failed','blocked')"
    params = []
    if event_id is not None:
        query += ' AND e.id=?'
        params.append(event_id)
    for row in db.execute(query, params).fetchall():
        row = dict(row)
        channel = forwarding_store.get_channel(db, row['channel_id'])
        try:
            route = resolve_event_policy(db, row)
            cancelled = row['channel_id'] not in route['channel_ids'] or not channel or channel['target_version'] != row['target_version']
            cancelled = cancelled or row['source_type'] == 'account' and not route['eligible']
            blocked = not route['eligible'] or channel and not channel['enabled']
        except ValueError:
            cancelled, blocked = True, False
        state = 'cancelled' if cancelled else 'blocked' if blocked else 'pending' if row['status'] == 'blocked' else row['status']
        if state != row['status']:
            db.execute('UPDATE forwarding_deliveries SET status=?, updated_at=?, error_message=? WHERE id=?',
                       (state, time.time(), '来源或目标已关闭/移除' if cancelled else '来源或通知渠道已停用' if blocked else None, row['id']))
    db.commit()


def enqueue_forwarding_event(db, route, message_id, received_at, payload, source_name='', group_id=None):
    if not route['eligible'] or route['mode'] != 'custom':
        return None
    address = forwarding_store.normalize_address(route['email_address'])
    identity = (route['source_type'], route['source_id'], address, str(message_id))
    old = db.execute('SELECT id FROM forwarding_events WHERE source_type=? AND source_id=? AND email_address=? AND message_id=?', identity).fetchone()
    if old:
        return old['id']
    channel_ids = [cid for cid in sorted(set(route['channel_ids']))
                   if received_at >= route['active_since'].get(cid, 0)
                   or route.get('replay_requested_at', 0) > 0 and route['replay_requested_at'] >= route['active_since'].get(cid, 0)]
    if not channel_ids:
        return None
    now = time.time()
    inserted = db.execute('INSERT OR IGNORE INTO forwarding_events(source_type,source_id,email_address,message_id,received_at,source_name,group_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                          (*identity, received_at, source_name, group_id, json.dumps(payload, ensure_ascii=False), now))
    if not inserted.rowcount:
        return db.execute('SELECT id FROM forwarding_events WHERE source_type=? AND source_id=? AND email_address=? AND message_id=?', identity).fetchone()['id']
    event_id = inserted.lastrowid
    for channel_id in channel_ids:
        channel = forwarding_store.get_channel(db, channel_id)
        if not channel:
            continue
        succeeded = route['source_type'] == 'account' and channel['legacy_key'] and has_forward_log(
            db, route['source_id'], str(message_id), forwarding_store.LOG_TYPES[channel['type']],
        )
        status = 'succeeded' if succeeded else 'pending' if channel['enabled'] else 'blocked'
        db.execute('INSERT OR IGNORE INTO forwarding_deliveries(event_id,channel_id,channel_name,channel_type,target_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (event_id, channel_id, channel['name'], channel['type'], channel['target_version'], status, now, now))
    return event_id


def process_notification_delivery(db, delivery_id):
    started = time.monotonic()
    row = db.execute('SELECT d.*,e.source_type,e.source_id,e.email_address,e.message_id,e.payload_json FROM forwarding_deliveries d JOIN forwarding_events e ON e.id=d.event_id WHERE d.id=?', (delivery_id,)).fetchone()
    if not row:
        return True, False, 0.0, False
    row = dict(row)
    reconcile_forwarding_deliveries(db, row['event_id'])
    state = db.execute('SELECT status,next_attempt_at FROM forwarding_deliveries WHERE id=?', (delivery_id,)).fetchone()
    if state['status'] in ('succeeded', 'cancelled'):
        return True, False, 0.0, False
    now = time.time()
    if state['status'] in ('blocked', 'sending') or state['next_attempt_at'] > now:
        return False, True, 0.0, False
    channel = forwarding_store.get_channel(db, row['channel_id'])
    if not channel or not channel['enabled'] or channel['target_version'] != row['target_version']:
        reconcile_forwarding_deliveries(db, row['event_id'])
        return False, True, 0.0, False
    config = forwarding_store.decode_config(channel, decrypt_data)
    token = uuid.uuid4().hex
    claimed = db.execute("""UPDATE forwarding_deliveries SET status='sending',claim_token=?,attempts=attempts+1,updated_at=?
        WHERE id=? AND status IN ('pending','failed') AND next_attempt_at<=? AND EXISTS
        (SELECT 1 FROM notification_channels c WHERE c.id=forwarding_deliveries.channel_id AND c.enabled=1 AND c.target_version=?)""",
                         (token, now, delivery_id, now, row['target_version'])).rowcount
    db.commit()
    if not claimed:
        return False, True, 0.0, False
    error = None
    try:
        if not send_notification_instance(channel, json.loads(row['payload_json'])):
            raise ValueError({'smtp': 'SMTP', 'telegram': 'Telegram', 'wecom': '企业微信', 'feishu': '飞书'}[channel['type']] + ' 转发返回失败')
        if row['source_type'] == 'account':
            kind = forwarding_store.LOG_TYPES[channel['type']]
            if channel['legacy_key']:
                record_forward_log(db, row['source_id'], row['message_id'], kind)
            if not log_forwarding_result(row['source_id'], row['email_address'], row['message_id'], kind, 'success', db_conn=db):
                raise ValueError('成功历史写入失败，投递结果不确定')
        db.execute("UPDATE forwarding_deliveries SET status='succeeded',claim_token=NULL,error_message=NULL,updated_at=? WHERE id=? AND claim_token=?", (time.time(), delivery_id, token))
        db.execute("INSERT INTO forwarding_attempts(delivery_id,status,created_at) VALUES(?,'success',?)", (delivery_id, time.time()))
        db.commit()
    except Exception as exc:
        db.rollback()
        error = safe_notification_error(exc, config)
        attempts = db.execute('SELECT attempts FROM forwarding_deliveries WHERE id=?', (delivery_id,)).fetchone()[0]
        retry_at = time.time() + min(3600, 30 * 2 ** min(max(attempts - 1, 0), 7))
        if channel['type'] == 'feishu':
            key = hashlib.sha256(config['webhook_url'].encode()).hexdigest()
            with FEISHU_RATE_LOCK:
                cooldown = FEISHU_RATE_STATE.get(key, {}).get('retry_at', 0)
            retry_at = max(retry_at, time.time() + max(0, cooldown - time.monotonic()))
        db.execute("UPDATE forwarding_deliveries SET status='failed',claim_token=NULL,error_message=?,next_attempt_at=?,updated_at=? WHERE id=? AND claim_token=?",
                   (error, retry_at, time.time(), delivery_id, token))
        db.execute("INSERT INTO forwarding_attempts(delivery_id,status,error_message,created_at) VALUES(?,'failed',?,?)", (delivery_id, error, time.time()))
        if row['source_type'] == 'account':
            log_forwarding_result(row['source_id'], row['email_address'], row['message_id'], forwarding_store.LOG_TYPES[channel['type']], 'failed', error, db_conn=db)
        db.commit()
    app.logger.info('[forward] delivery=%s source=%s:%s target=%s type=%s status=%s duration_ms=%s',
                    delivery_id, row['source_type'], row['source_id'], row['channel_id'], channel['type'], 'failed' if error else 'success', elapsed_ms(started))
    return not error, bool(error), elapsed_ms(started), not error


def process_forwarding_event(db, event_id, result):
    if event_id is None:
        return True, False
    processed, failed = False, False
    rows = db.execute('SELECT id,channel_type FROM forwarding_deliveries WHERE event_id=? ORDER BY channel_id', (event_id,)).fetchall()
    if not rows:
        return True, False
    for row in rows:
        done, bad, duration, sent = process_notification_delivery(db, row['id'])
        result['channel_send_ms'] += duration
        if sent:
            result[forwarding_store.LOG_TYPES[row['channel_type']] + '_success_count'] += 1
        processed = processed or done
        failed = failed or bad
    release_forwarding_payload(db, event_id)
    return processed, failed


def release_forwarding_payload(db, event_id):
    db.execute("UPDATE forwarding_events SET payload_json=NULL WHERE id=? AND NOT EXISTS (SELECT 1 FROM forwarding_deliveries WHERE event_id=? AND status IN ('pending','failed','blocked','sending'))", (event_id, event_id))
    db.commit()


def retry_forwarding_deliveries():
    db = open_forwarding_db_connection()
    counts = {'processed_count': 0, 'failed_count': 0, 'channel_send_ms': 0,
              'email_success_count': 0, 'telegram_success_count': 0, 'wecom_success_count': 0, 'feishu_success_count': 0}
    try:
        # Called only after the shared run lock: a sending row left by an earlier
        # process has an uncertain remote result and can now be retried.
        db.execute("UPDATE forwarding_deliveries SET status='failed',claim_token=NULL,error_message='上次投递中断，远端结果不确定',next_attempt_at=? WHERE status='sending'", (time.time(),))
        db.commit()
        reconcile_forwarding_deliveries(db)
        ids = db.execute("SELECT DISTINCT event_id FROM forwarding_deliveries WHERE status IN ('pending','failed') AND next_attempt_at<=? ORDER BY id LIMIT 200", (time.time(),)).fetchall()
        for row in ids:
            _, failed = process_forwarding_event(db, row['event_id'], counts)
            counts['failed_count'] += int(failed)
        return counts
    finally:
        db.close()


def get_cloudflare_forwarding_workers():
    rows = get_db().execute("""SELECT DISTINCT w.* FROM cloudflare_channels w
        JOIN forwarding_policies p ON p.scope_id=w.id AND p.scope_type LIKE 'cloudflare_%'
        JOIN forwarding_policy_channels pc ON pc.policy_id=p.id
        WHERE w.enabled=1 AND p.mode='custom' ORDER BY w.id""").fetchall()
    return [dict(row) for row in rows]


def cloudflare_forward_item(item):
    if not isinstance(item, dict) or isinstance(item.get('id'), bool):
        raise ValueError('CF 邮件记录或稳定 ID 无效')
    try:
        upstream_id = int(item['id'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('CF 后台通知需要上游数字邮件 ID') from None
    if upstream_id < 1:
        raise ValueError('CF 邮件 ID 必须为正整数')
    address = forwarding_store.normalize_address(item.get('address', ''))
    received = item.get('created_at')
    if isinstance(received, (int, float)) and not isinstance(received, bool):
        received_at = float(received)
    else:
        try:
            parsed = datetime.fromisoformat(str(received).replace('Z', '+00:00'))
            received_at = (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).timestamp()
        except (ValueError, TypeError, OverflowError):
            raise ValueError('CF 邮件缺少可靠的上游接收时间') from None
    if not math.isfinite(received_at) or received_at <= 0:
        raise ValueError('CF 邮件接收时间无效')
    normalized = normalize_cloudflare_admin_mail_item(item, 0, address)
    if not normalized:
        raise ValueError('CF 邮件缺少可解析的原始内容')
    normalized['to'] = address
    normalized['date'] = datetime.fromtimestamp(received_at, timezone.utc).isoformat()
    raw = item.get('raw') or item.get('raw_content') or item.get('source_raw')
    raw_bytes = raw.encode('utf-8') if isinstance(raw, str) else raw
    # INTEGER PRIMARY KEY may be reused after deleting the highest row.
    # Receipt time and content also remain stable when a page is reread.
    identity = f'{upstream_id}:{received_at:g}:{hashlib.sha256(raw_bytes).hexdigest()[:24]}'
    return upstream_id, address, received_at, normalized, identity


def process_cloudflare_forwarding_worker(worker, job_config=None):
    with app.app_context():
        db = open_forwarding_db_connection()
        started = time.monotonic()
        result = {'worker_id': worker['id'], 'worker_name': worker['name'], 'fetched_count': 0,
                  'had_processing_failure': False, 'error': '', 'channel_send_ms': 0,
                  'email_success_count': 0, 'telegram_success_count': 0, 'wecom_success_count': 0, 'feishu_success_count': 0}
        event_ids, warnings = set(), []
        try:
            current = db.execute('SELECT enabled FROM cloudflare_channels WHERE id=?', (worker['id'],)).fetchone()
            if not current or not current['enabled']:
                return result
            state = db.execute('SELECT * FROM cloudflare_forward_scan_state WHERE worker_id=?', (worker['id'],)).fetchone()
            if not state:
                since = db.execute("SELECT MIN(c.active_since) FROM forwarding_policy_channels c JOIN forwarding_policies p ON p.id=c.policy_id WHERE p.scope_type LIKE 'cloudflare_%' AND p.scope_id=? AND p.mode='custom'", (worker['id'],)).fetchone()[0]
                db.execute('INSERT INTO cloudflare_forward_scan_state(worker_id,active_since,updated_at) VALUES(?,?,?)', (worker['id'], since if since is not None else time.time(), time.time()))
                db.commit()
                state = db.execute('SELECT * FROM cloudflare_forward_scan_state WHERE worker_id=?', (worker['id'],)).fetchone()
            state = dict(state)
            checkpoint, upper, next_id = state['checkpoint_id'], state['upper_id'], state['scan_next_id']
            offset, cache, minimum = state['next_offset'], {}, None

            def page(page_offset):
                response = cloudflare_get_admin_messages(limit=100, offset=page_offset, channel=worker)
                if not response.get('success'):
                    raise ValueError('CF 分页读取失败：' + str(response.get('error', '未知错误')))
                items = response.get('messages', [])
                try:
                    ids = [int(item['id']) for item in items]
                except (KeyError, TypeError, ValueError):
                    raise ValueError('CF 管理员列表缺少数字邮件 ID') from None
                if ids != sorted(ids, reverse=True) or len(ids) != len(set(ids)):
                    raise ValueError('CF 管理员列表未遵循稳定 ID 倒序契约')
                return {i: item for i, item in zip(ids, items)}

            cache = page(offset if upper is not None else 0)
            if upper is None:
                if not cache:
                    if checkpoint:
                        result['error'] = '上游邮件列表已清空，历史检查点无法核对'
                        result['had_processing_failure'] = True
                        db.execute('UPDATE cloudflare_forward_scan_state SET error_message=?,updated_at=? WHERE worker_id=?',
                                   (result['error'], time.time(), worker['id']))
                        db.commit()
                    return result
                upper = max(cache)
                next_id = upper
                offset = 0
                if upper < checkpoint:
                    checkpoint = 0
                    warnings.append('上游邮件 ID 已回退，按稳定邮件身份重新核对')
            minimum = min(cache) if cache else None
            # Reread the checkpoint row too, so an upstream highest-ID reuse
            # does not suppress a different newly received message.
            stop_id = max(1, checkpoint)
            completed = False
            budget = int((job_config or {}).get('cloudflare_scan_budget', 500))
            pages = 0
            while next_id is not None and next_id >= stop_id and budget > 0:
                if not db.execute('SELECT enabled FROM cloudflare_channels WHERE id=?', (worker['id'],)).fetchone()[0]:
                    break
                while cache and minimum > next_id and pages < 20:
                    offset += 100
                    cache = page(offset)
                    minimum = min(cache) if cache else None
                    pages += 1
                if pages >= 20:
                    break
                item = cache.get(next_id)
                if item is None:
                    # Offset movement or retention can hide a row in a page.
                    # A direct stable-ID read distinguishes an absent row from
                    # a request failure without advancing over unread mail.
                    item = cloudflare_temp_request('GET', f'/admin/mails/{next_id}', admin_auth=True, channel=worker)
                    if isinstance(item, dict) and item.get('success') is False:
                        raise ValueError('CF 按稳定 ID 恢复失败：' + str(item.get('error', '未知错误')))
                    if item is None:
                        warnings.append(f'上游邮件 ID {next_id} 已不可读取')
                        next_id -= 1
                        budget -= 1
                        db.execute('UPDATE cloudflare_forward_scan_state SET upper_id=?,scan_next_id=?,next_offset=?,updated_at=? WHERE worker_id=?',
                                   (upper, next_id, offset, time.time(), worker['id']))
                        db.commit()
                        continue
                upstream_id, address, received_at, detail, identity = cloudflare_forward_item(item)
                if upstream_id != next_id:
                    raise ValueError('CF 按 ID 返回了不一致的邮件记录')
                if checkpoint == 0 and received_at < state['active_since']:
                    completed = True
                    break
                route = forwarding_store.resolve_policy(db, worker_id=worker['id'], address=address)
                # Account-like payload is presentation only; no fake account is stored.
                event_id = None
                if forward_email_matches_policy(detail, route):
                    payload = build_forward_payload({'email': address}, detail)
                    event_id = enqueue_forwarding_event(db, route, identity, received_at, payload, worker['name'])
                if event_id is not None:
                    event_ids.add(event_id)
                next_id -= 1
                budget -= 1
                result['fetched_count'] += 1
                db.execute('UPDATE cloudflare_forward_scan_state SET upper_id=?,scan_next_id=?,next_offset=?,error_message=NULL,updated_at=? WHERE worker_id=?',
                           (upper, next_id, offset, time.time(), worker['id']))
                db.commit()
            completed = completed or next_id is not None and next_id < stop_id
            warning = '；'.join(warnings[:3]) or None
            if completed:
                db.execute('UPDATE cloudflare_forward_scan_state SET checkpoint_id=?,upper_id=NULL,scan_next_id=NULL,next_offset=0,error_message=?,updated_at=? WHERE worker_id=?',
                           (upper, warning, time.time(), worker['id']))
            else:
                warning = warning or '扫描未覆盖完整区间，下轮从稳定 ID 继续'
                db.execute('UPDATE cloudflare_forward_scan_state SET upper_id=?,scan_next_id=?,next_offset=?,error_message=?,updated_at=? WHERE worker_id=?',
                           (upper, next_id, offset, warning, time.time(), worker['id']))
            db.commit()
            result['error'] = warning or ''
            result['had_processing_failure'] = bool(warning)
        except Exception as exc:
            db.rollback()
            result['had_processing_failure'] = True
            result['error'] = safe_notification_error(exc, {'password': decrypt_data(worker.get('admin_password', ''))})
            db.execute('UPDATE cloudflare_forward_scan_state SET error_message=?,updated_at=? WHERE worker_id=?', (result['error'], time.time(), worker['id']))
            db.commit()
        finally:
            for event_id in sorted(event_ids):
                _, failed = process_forwarding_event(db, event_id, result)
                result['had_processing_failure'] = result['had_processing_failure'] or failed
            result['total_ms'] = elapsed_ms(started)
            app.logger.info('[forward] cf_worker=%s fetched=%s failed=%s total_ms=%s error=%s', worker['id'], result['fetched_count'], result['had_processing_failure'], result['total_ms'], result['error'])
            db.close()
        return result


def run_forwarding_sources_parallel(accounts, workers, config):
    results, cf_results = [], []
    jobs = [(process_forwarding_account, row, False) for row in accounts]
    jobs.extend((process_cloudflare_forwarding_worker, row, True) for row in workers)
    with ThreadPoolExecutor(max_workers=min(config['parallel_workers'], len(jobs)), thread_name_prefix='forward-source') as executor:
        futures = {executor.submit(fn, row, config): is_cf for fn, row, is_cf in jobs}
        for future in as_completed(futures):
            value = future.result()
            (cf_results if futures[future] else results).append(value)
    return results, cf_results


@app.route('/api/forwarding/sources', methods=['GET'])
@login_required
def api_forwarding_sources():
    db = get_db()
    accounts = [dict(r) for r in db.execute('SELECT id,email,group_id,status FROM accounts ORDER BY email COLLATE NOCASE')]
    groups = []
    for row in db.execute('SELECT id,name,parent_id,level,is_system FROM groups ORDER BY sort_order,id'):
        if row['is_system']:
            continue
        group = dict(row)
        ids = get_descendant_group_ids(group['id'], db)
        matching = [a for a in accounts if a['group_id'] in ids]
        group.update(descendant_ids=ids, account_count=len(matching), active_count=sum(a['status'] == 'active' for a in matching))
        groups.append(group)
    workers = [dict(r) for r in db.execute('SELECT id,name,email_domains,enabled FROM cloudflare_channels ORDER BY id')]
    return jsonify({'success': True, 'accounts': accounts, 'groups': groups, 'workers': workers})


@app.route('/api/forwarding/history', methods=['GET'])
@login_required
def api_forwarding_history():
    db = get_db()
    limit, offset = parse_log_pagination(request.args.get('limit'), request.args.get('offset'))
    current = '''SELECT d.id,e.source_type,e.source_id,e.source_name,e.email_address,e.group_id,
        e.message_id,d.channel_id,d.channel_name,d.channel_type,d.status,d.attempts,
        d.error_message,d.next_attempt_at,d.updated_at FROM forwarding_deliveries d
        JOIN forwarding_events e ON e.id=d.event_id'''
    legacy = '''SELECT -l.id AS id,'account' AS source_type,l.account_id AS source_id,
        l.account_email AS source_name,l.account_email AS email_address,NULL AS group_id,
        l.message_id,NULL AS channel_id,
        CASE l.channel WHEN 'email' THEN '原有 SMTP' WHEN 'telegram' THEN '原有 Telegram'
        WHEN 'wecom' THEN '原有企业微信' WHEN 'feishu' THEN '原有飞书' ELSE '邮件读取' END AS channel_name,
        CASE l.channel WHEN 'email' THEN 'smtp' ELSE l.channel END AS channel_type,
        CASE l.status WHEN 'success' THEN 'succeeded' ELSE l.status END AS status,
        1 AS attempts,l.error_message,0 AS next_attempt_at,
        COALESCE(CAST(strftime('%s',l.created_at) AS REAL),0) AS updated_at
        FROM forwarding_logs l WHERE NOT EXISTS
        (SELECT 1 FROM forwarding_events e JOIN forwarding_deliveries d ON d.event_id=e.id
        WHERE e.source_type='account' AND e.source_id=l.account_id AND e.message_id=l.message_id
        AND (CASE d.channel_type WHEN 'smtp' THEN 'email' ELSE d.channel_type END)=l.channel)'''
    query = f'SELECT * FROM ({current} UNION ALL {legacy}) history WHERE 1=1'
    params = []
    for arg in ('source_type', 'source_id', 'group_id', 'channel_id', 'status', 'email_address'):
        if request.args.get(arg):
            query += f' AND {arg}=?'
            params.append(request.args[arg].strip().lower() if arg == 'email_address' else request.args[arg])
    query += ' ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?'
    rows = [dict(row) for row in db.execute(query, params + [limit, offset])]
    for row in rows:
        row['attempt_history'] = [dict(r) for r in db.execute('SELECT status,error_message,created_at FROM forwarding_attempts WHERE delivery_id=? ORDER BY id', (row['id'],))]
    scans = [dict(r) for r in db.execute('SELECT s.*,w.name AS worker_name FROM cloudflare_forward_scan_state s JOIN cloudflare_channels w ON w.id=s.worker_id ORDER BY s.worker_id')]
    return jsonify({'success': True, 'history': rows, 'scans': scans, 'limit': limit, 'offset': offset})
