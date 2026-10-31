"""Source policies and delivery identity are observable forwarding contracts."""

import importlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


_import_dir = tempfile.TemporaryDirectory(prefix='outlook-source-import-')
with patch.dict(os.environ, {
    'SECRET_KEY': os.environ.get('SECRET_KEY', 'source-forwarding-test'),
    'DATABASE_PATH': os.path.join(_import_dir.name, 'import.db'),
    'WERKZEUG_RUN_MAIN': 'false',
}):
    web = importlib.import_module('web_outlook_app')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'source-forwarding-test')
    monkeypatch.setattr(web, 'DATABASE', str(tmp_path / 'source.db'))
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', False)
    with web.app.app_context():
        web.init_db()
        client = web.app.test_client()
        with client.session_transaction() as session:
            session['logged_in'] = True
        yield client


def channel(client, name='工作群', kind='feishu', **config):
    if kind == 'feishu':
        config.setdefault('webhook_url', 'https://open.feishu.cn/open-apis/bot/v2/hook/' + str(abs(hash(name))))
    result = client.post('/api/notification-channels', json={
        'name': name, 'type': kind, 'config': config,
    })
    assert result.status_code == 200, result.get_json()
    assert result.get_json()['success']
    return result.get_json()['channel']['id']


def policy(client, scope, source_id=0, mode='custom', targets=(), match=''):
    response = client.put('/api/forwarding/policies', json={
        'scope_type': scope, 'scope_id': source_id, 'match_value': match,
        'mode': mode, 'channel_ids': list(targets),
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['success']


def account(email='source@example.com', group=1):
    db = web.get_db()
    row = db.execute("INSERT INTO accounts (email, account_type, group_id, forward_enabled) VALUES (?, 'imap', ?, 1)", (email, group))
    db.commit()
    return dict(db.execute('SELECT * FROM accounts WHERE id=?', (row.lastrowid,)).fetchone())


def worker():
    source_id, error = web.create_cloudflare_channel('测试 Worker', 'worker.example.com', 'example.com', 'test-password')
    assert not error
    return source_id


def legacy_default(client):
    """Construct the previous version's untouched global migration record."""
    target = channel(client, '原有 Telegram', kind='telegram', bot_token='old-token', chat_id='old-chat')
    db = web.get_db()
    db.execute("UPDATE notification_channels SET legacy_key='telegram' WHERE id=?", (target,))
    for key, value in {'forward_channels': 'telegram', 'telegram_bot_token': 'old-token', 'telegram_chat_id': 'old-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.execute("DELETE FROM forwarding_policies WHERE scope_type='normal_default'")
    pid = db.execute("INSERT INTO forwarding_policies(scope_type,mode,updated_at) VALUES('normal_default','custom',0)").lastrowid
    db.execute('INSERT INTO forwarding_policy_channels VALUES(?,?,?)', (pid, target, time.time() - 3600))
    db.execute("DELETE FROM settings WHERE key='source_forwarding_account_rules_v3'")
    db.commit()
    return target, web.forwarding_store.get_policy(db, 'normal_default')


def preview(client, **params):
    response = client.get('/api/forwarding/preview', query_string=params)
    assert response.status_code == 200, response.get_json()
    return response.get_json()['preview']


def test_account_overrides_group_and_can_restore_inheritance(client):
    a, b = channel(client, '分组飞书'), channel(client, '邮箱飞书')
    source = account()
    policy(client, 'group', 1, targets=[a])
    policy(client, 'account', source['id'], targets=[b])
    assert preview(client, account_id=source['id'])['channel_ids'] == [b]
    policy(client, 'account', source['id'], mode='off')
    assert preview(client, account_id=source['id'])['channel_ids'] == []
    policy(client, 'account', source['id'], mode='inherit')
    assert preview(client, account_id=source['id'])['channel_ids'] == [a]


def test_forwarding_workspace_is_separate_from_system_settings(client):
    from html.parser import HTMLParser

    class Parents(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.parents = [], {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get('id'):
                self.parents[attrs['id']] = [item[1] for item in self.stack]
            if tag not in {'input', 'br', 'hr', 'img', 'meta', 'link'}:
                self.stack.append((tag, attrs.get('id')))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    response = client.get('/forwarding')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    parser = Parents()
    parser.feed(html)
    for name in ['sourceForwardingConsole', 'forwardCheckIntervalSeconds', 'forwardPolicyList', 'notificationChannelList', 'sourceForwardingHistory']:
        assert 'forwardingManagementView' in parser.parents[name]
        assert 'settingsModal' not in parser.parents[name]
    assert 'data-target="forwardingSettingsSection"' not in html
    desktop_menu = html.split('id="desktopProjectManagementBtn"', 1)[1].split('</div>', 1)[0]
    assert 'onclick="showForwardingManagement()"' in desktop_menu


def test_runtime_settings_save_preserves_existing_notification_rules(client):
    target = channel(client)
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    before = client.get('/api/forwarding/policies').get_json()['policies']
    response = client.put('/api/settings', json={'forward_check_interval_seconds': 90, 'forward_keywords': 'important'})
    assert response.status_code == 200 and response.get_json()['success']
    assert client.get('/api/forwarding/policies').get_json()['policies'] == before
    settings = client.get('/api/settings').get_json()['settings']
    assert str(settings['forward_check_interval_seconds']) == '90'
    assert settings['forward_keywords'] == 'important'


def test_unimported_cf_address_overrides_domain_without_creating_mailbox(client):
    a, b = channel(client, '域名飞书'), channel(client, '地址飞书')
    source_id = worker()
    policy(client, 'cloudflare_domain', source_id, targets=[a], match='Example.COM')
    policy(client, 'cloudflare_address', source_id, targets=[b], match='special@example.com')
    assert preview(client, worker_id=source_id, address='special@EXAMPLE.com')['channel_ids'] == [b]
    assert preview(client, worker_id=source_id, address='other@example.com')['channel_ids'] == [a]
    assert web.get_db().execute('SELECT COUNT(*) FROM temp_emails').fetchone()[0] == 0


def test_same_mail_same_channel_notifies_once_but_other_mail_still_notifies(client):
    target = channel(client)
    source = account()
    policy(client, 'group', 1, targets=[target, target])
    policy(client, 'account', source['id'], targets=[target])
    items = [{'id': 'one', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'}]
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': items}), patch.object(
        web, 'fetch_forward_detail', side_effect=lambda _a, mid, _f: {'id': mid, 'subject': mid, 'body': '测试'},
    ), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        config = web.build_forwarding_job_config()
        web.process_forwarding_account(source, config)
        web.process_forwarding_account(source, config)
        assert send.call_count == 1
        items[0] = {**items[0], 'id': 'two', 'date': '2090-01-02T00:00:00Z'}
        web.process_forwarding_account(source, config)
        assert send.call_count == 2


def test_two_feishu_instances_have_independent_results(client):
    a, b = channel(client, '飞书 A'), channel(client, '飞书 B')
    source = account()
    policy(client, 'account', source['id'], targets=[a, b])
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [
        {'id': 'multi', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'},
    ]}), patch.object(web, 'fetch_forward_detail', return_value={'id': 'multi', 'subject': '双目标', 'body': '测试'}), patch.object(
        web, 'send_forward_feishu', return_value=True,
    ) as send:
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        assert send.call_count == 2


def test_channels_hide_and_preserve_credentials(client):
    target = channel(client, sign_secret='test-signature')
    response = client.get('/api/notification-channels').get_json()
    assert 'test-signature' not in str(response)
    result = client.put(f'/api/notification-channels/{target}', json={'name': '改名', 'config': {'sign_secret': ''}})
    assert result.get_json()['success']
    assert result.get_json()['channel']['config']['sign_secret_configured'] is True


def test_cf_exact_address_alone_starts_scanning(client):
    target, source_id = channel(client), worker()
    policy(client, 'cloudflare_address', source_id, targets=[target], match='only@example.com')
    assert preview(client, worker_id=source_id, address='only@example.com')['channel_ids'] == [target]
    assert preview(client, worker_id=source_id, address='other@example.com')['channel_ids'] == []


CF_FIXTURE = json.loads((Path(__file__).parent / 'fixtures/cloudflare/forwarding.json').read_text())


def cf_mail(mid, address='only@example.com', **values):
    return {**CF_FIXTURE['mail'], 'id': mid, 'address': address, **values}


def cf_setup(client):
    target, source_id = channel(client), worker()
    policy(client, 'cloudflare_address', source_id, targets=[target], match='only@example.com')
    return target, web.get_cloudflare_channel_by_id(source_id, include_secret=True)


def test_cf_unimported_mail_uses_envelope_and_receipt_time(client):
    _, source = cf_setup(client)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}), patch.object(
        web, 'send_forward_feishu', return_value=True,
    ) as send:
        result = web.process_cloudflare_forwarding_worker(source)
        assert not result['error'], result
        assert send.call_count == 1
        assert 'only@example.com' in send.call_args.args[0]
        web.process_cloudflare_forwarding_worker(source)
        assert send.call_count == 1
    db = web.get_db()
    assert db.execute('SELECT COUNT(*) FROM temp_emails').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM temp_email_messages').fetchone()[0] == 0


def test_cf_budget_resume_and_restart_do_not_repeat_success(client):
    _, source = cf_setup(client)
    rows = [cf_mail(i) for i in (3, 2, 1)]
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': rows}), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        first = web.process_cloudflare_forwarding_worker(source, {'cloudflare_scan_budget': 2})
        assert first['had_processing_failure']
        state = dict(web.get_db().execute('SELECT * FROM cloudflare_forward_scan_state').fetchone())
        assert state['checkpoint_id'] == 0 and state['scan_next_id'] == 1
        assert send.call_count == 2
        # A fresh connection on the second invocation is the restart boundary.
        second = web.process_cloudflare_forwarding_worker(source)
        assert not second['error'], second
        assert send.call_count == 3
        assert web.get_db().execute('SELECT checkpoint_id FROM cloudflare_forward_scan_state').fetchone()[0] == 3


def test_cf_failed_page_resumes_without_advancing_checkpoint(client):
    _, source = cf_setup(client)
    records = [cf_mail(i) for i in range(101, 0, -1)]
    fail = [True]

    def pages(**kwargs):
        if kwargs['offset'] == 100 and fail[0]:
            return {'success': False, 'error': 'temporary page failure'}
        return {'success': True, 'messages': records[kwargs['offset']:kwargs['offset'] + 100]}

    with patch.object(web, 'cloudflare_get_admin_messages', side_effect=pages), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        first = web.process_cloudflare_forwarding_worker(source)
        assert first['had_processing_failure']
        assert web.get_db().execute('SELECT checkpoint_id FROM cloudflare_forward_scan_state').fetchone()[0] == 0
        assert send.call_count == 100
        fail[0] = False
        second = web.process_cloudflare_forwarding_worker(source)
        assert not second['error'], second
        assert send.call_count == 101


def test_cf_offset_shift_recovers_unread_id_and_defers_new_upper(client):
    _, source = cf_setup(client)
    original = [cf_mail(i) for i in range(111, 0, -1)]
    shifted = [cf_mail(112)] + [row for row in original if row['id'] not in (50, 49)]

    def pages(**kwargs):
        rows = original if kwargs['offset'] == 0 else shifted
        return {'success': True, 'messages': rows[kwargs['offset']:kwargs['offset'] + 100]}

    with patch.object(web, 'cloudflare_get_admin_messages', side_effect=pages), patch.object(
        web, 'cloudflare_temp_request', side_effect=lambda _method, path, **_kwargs: cf_mail(int(path.rsplit('/', 1)[1])),
    ) as detail, patch.object(web, 'send_forward_feishu', return_value=True) as send:
        result = web.process_cloudflare_forwarding_worker(source)
        assert not result['error'], result
        assert send.call_count == 111
        assert any(call.args[1].endswith('/11') for call in detail.call_args_list)
        ids = web.get_db().execute('SELECT message_id FROM forwarding_events').fetchall()
        assert not any(r[0].startswith('112:') for r in ids)


@pytest.mark.parametrize('change', [{'address': ''}, {'created_at': ''}, {'raw': ''}, {'id': 'unstable'}])
def test_cf_bad_identity_never_silently_advances(client, change):
    _, source = cf_setup(client)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1, **change)]}), patch.object(web, 'send_forward_feishu') as send:
        result = web.process_cloudflare_forwarding_worker(source)
    assert result['had_processing_failure']
    assert web.get_db().execute('SELECT checkpoint_id FROM cloudflare_forward_scan_state').fetchone()[0] == 0
    send.assert_not_called()


def queued_event(client, targets=None):
    targets = targets or [channel(client)]
    source = account()
    policy(client, 'account', source['id'], targets=targets)
    db = web.get_db()
    route = web.forwarding_store.resolve_policy(db, account_id=source['id'])
    eid = web.enqueue_forwarding_event(db, route, 'queued', 3786912000, ('主题', '正文', '', '邮件转发 正文'), source['email'])
    db.commit()
    return source, eid, db.execute('SELECT id FROM forwarding_deliveries WHERE event_id=? ORDER BY channel_id', (eid,)).fetchall()


def test_failed_target_retries_after_due_and_keeps_success(client, monkeypatch):
    a, b = channel(client, 'A'), channel(client, 'B')
    _, eid, deliveries = queued_event(client, [a, b])
    db = web.get_db()
    with patch.object(web, 'send_forward_feishu', side_effect=[True, False, True]) as send:
        assert web.process_notification_delivery(db, deliveries[0][0])[3]
        assert web.process_notification_delivery(db, deliveries[1][0])[1]
        assert not web.process_notification_delivery(db, deliveries[1][0])[3]
        assert send.call_count == 2
        due = db.execute('SELECT next_attempt_at FROM forwarding_deliveries WHERE id=?', (deliveries[1][0],)).fetchone()[0]
        monkeypatch.setattr(web.time, 'time', lambda: due + 1)
        assert web.process_notification_delivery(db, deliveries[1][0])[3]
        assert not web.process_notification_delivery(db, deliveries[0][0])[3]
        assert send.call_count == 3
    web.release_forwarding_payload(db, eid)
    assert db.execute('SELECT payload_json FROM forwarding_events WHERE id=?', (eid,)).fetchone()[0] is None


def test_delivery_send_holds_no_sqlite_writer(client):
    _, _, rows = queued_event(client)
    db = web.get_db()

    def network(*_args, **_kwargs):
        with sqlite3.connect(web.DATABASE, timeout=0.1) as probe:
            probe.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('source_writer_probe','ok')")
        return True

    with patch.object(web, 'send_forward_feishu', side_effect=network):
        assert web.process_notification_delivery(db, rows[0][0])[3]


def test_parallel_duplicate_claim_has_one_network_sender(client):
    _, _, rows = queued_event(client)
    started, release = threading.Event(), threading.Event()

    def network(*_args, **_kwargs):
        started.set()
        assert release.wait(3)
        return True

    def process():
        with web.app.app_context():
            conn = web.open_forwarding_db_connection()
            try:
                return web.process_notification_delivery(conn, rows[0][0])
            finally:
                conn.close()

    with patch.object(web, 'send_forward_feishu', side_effect=network) as send, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(process)
        try:
            assert started.wait(3)
            assert pool.submit(process).result(timeout=3)[1]
        finally:
            release.set()
        assert first.result(timeout=3)[3]
        assert send.call_count == 1


def test_stop_remove_and_auth_updates_preserve_expected_pending_state(client):
    source, _, rows = queued_event(client)
    db = web.get_db()
    target = db.execute('SELECT channel_id FROM forwarding_deliveries WHERE id=?', (rows[0][0],)).fetchone()[0]
    assert client.put(f'/api/notification-channels/{target}', json={'enabled': False}).get_json()['success']
    assert db.execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'blocked'
    assert client.put(f'/api/notification-channels/{target}', json={'enabled': True, 'config': {'sign_secret': 'new-auth'}}).get_json()['success']
    assert db.execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'pending'
    policy(client, 'account', source['id'], mode='off')
    assert db.execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'cancelled'


def test_destination_change_cancels_old_pending_and_no_fallback(client):
    source, _, rows = queued_event(client)
    db = web.get_db()
    target = db.execute('SELECT channel_id FROM forwarding_deliveries WHERE id=?', (rows[0][0],)).fetchone()[0]
    assert client.put(f'/api/notification-channels/{target}', json={'config': {'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/new-destination'}}).get_json()['success']
    assert db.execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'cancelled'
    assert preview(client, account_id=source['id'])['channel_ids'] == [target]


def test_worker_delete_is_protected_by_unimported_address_rule(client):
    _, source = cf_setup(client)
    ok, error = web.delete_cloudflare_channel(source['id'])
    assert not ok and '通知' in error
    assert web.get_db().execute('SELECT COUNT(*) FROM temp_emails').fetchone()[0] == 0


@pytest.mark.parametrize('payload', [[], {}, {'name': 'x', 'type': []}, {'name': [], 'type': 'feishu'}, {'name': 'x', 'type': 'feishu', 'config': []}])
def test_invalid_channel_input_is_rejected_without_writes(client, payload):
    response = client.post('/api/notification-channels', json=payload)
    assert response.status_code == 400
    assert web.get_db().execute('SELECT COUNT(*) FROM notification_channels').fetchone()[0] == 0


def test_duplicate_names_policy_atomicity_and_protected_secrets(client):
    target = channel(client, 'Case', sign_secret='secret-for-test')
    assert client.post('/api/notification-channels', json={'name': 'case', 'type': 'wecom', 'config': {'webhook_url': 'https://example.com/hook'}}).status_code == 400
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    result = client.put('/api/forwarding/policies', json={'scope_type': 'account', 'scope_id': source['id'], 'mode': 'custom', 'channel_ids': [999999]})
    assert result.status_code == 400
    assert preview(client, account_id=source['id'])['channel_ids'] == [target]
    stored = web.get_db().execute('SELECT config_json FROM notification_channels').fetchone()[0]
    assert 'secret-for-test' not in stored and 'enc:' in stored
    assert client.delete(f'/api/notification-channels/{target}').status_code == 400


def test_new_endpoints_require_login_and_csrf(client, monkeypatch):
    anonymous = web.app.test_client()
    assert anonymous.get('/api/notification-channels').status_code == 401
    assert anonymous.get('/api/forwarding/preview?account_id=1').status_code == 401
    assert anonymous.patch('/api/forwarding/policies', json={}).status_code == 401
    if web.CSRF_AVAILABLE:
        monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', True)
        assert client.post('/api/notification-channels', json={}).status_code == 400
        assert client.patch('/api/forwarding/policies', json={}).status_code == 400
        assert web.get_db().execute('SELECT COUNT(*) FROM notification_channels').fetchone()[0] == 0


def test_migration_preserves_partial_success_and_is_idempotent(client):
    source = account()
    settings = {'forward_channels': 'smtp,telegram', 'smtp_host': 'smtp.example.com',
                'email_forward_recipient': 'archive@example.com', 'smtp_username': 'sender@example.com',
                'telegram_bot_token': 'synthetic-token', 'telegram_chat_id': 'chat'}
    db = web.get_db()
    for key, value in settings.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.execute("DELETE FROM settings WHERE key='source_forwarding_migrated'")
    db.execute("INSERT INTO forward_logs(account_id,message_id,channel) VALUES(?,'old','email')", (source['id'],))
    db.commit()
    web.init_db()
    web.init_db()
    assert db.execute('SELECT COUNT(*) FROM notification_channels').fetchone()[0] == 2
    assert dict(db.execute('SELECT * FROM accounts WHERE id=?', (source['id'],)).fetchone())['forward_last_checked_at'] == source['forward_last_checked_at']
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [{'id': 'old', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'}]}), patch.object(
        web, 'fetch_forward_detail', return_value={'id': 'old', 'body': 'old mail'},
    ), patch.object(web, 'send_forward_email', return_value=True) as smtp, patch.object(web, 'send_forward_telegram', return_value=True) as tg:
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        smtp.assert_not_called()
        tg.assert_called_once()
    assert db.execute("SELECT COUNT(*) FROM forwarding_deliveries WHERE status='succeeded'").fetchone()[0] == 2


def test_normal_received_boundary_uses_local_parser_timezone(client):
    target = channel(client)
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    received = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    try:
        with patch.dict(os.environ, {'TZ': 'Asia/Shanghai'}):
            time.tzset()
            with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [
                {'id': 'before-policy', 'date': received, 'folder': 'inbox'},
            ]}), patch.object(web, 'fetch_forward_detail', return_value={'id': 'before-policy', 'body': 'older receipt'}), patch.object(web, 'send_forward_feishu') as send:
                web.process_forwarding_account(source, web.build_forwarding_job_config())
                send.assert_not_called()
    finally:
        time.tzset()


def test_cf_cleared_upstream_is_visible_in_persistent_scan_status(client):
    _, source = cf_setup(client)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}), patch.object(web, 'send_forward_feishu', return_value=True):
        web.process_cloudflare_forwarding_worker(source)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': []}):
        result = web.process_cloudflare_forwarding_worker(source)
    assert result['error']
    assert web.get_db().execute('SELECT error_message FROM cloudflare_forward_scan_state').fetchone()[0]


def test_cf_only_job_runs_without_global_channels_or_normal_accounts(client):
    _, source = cf_setup(client)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        result = web.process_forwarding_job()
    assert result['success'] and result['feishu_success_count'] == 1
    assert result['cloudflare'][0]['worker_id'] == source['id']
    send.assert_called_once()


def test_parallel_sources_share_worker_limit_without_slow_account_blocking_cf(client):
    target, _ = cf_setup(client)
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    web.set_setting('forward_execution_mode', 'parallel')
    web.set_setting('forward_parallel_workers', '2')
    cf_seen = threading.Event()

    def normal(*_args):
        assert cf_seen.wait(3), 'CF was blocked behind the ordinary source'
        return {'success': True, 'emails': [{'id': 'normal', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'}]}

    def cf(**_kwargs):
        cf_seen.set()
        return {'success': True, 'messages': [cf_mail(1)]}

    with patch.object(web, 'fetch_forward_candidates', side_effect=normal), patch.object(web, 'fetch_forward_detail', return_value={'id': 'normal', 'body': 'normal mail'}), patch.object(
        web, 'cloudflare_get_admin_messages', side_effect=cf,
    ), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        result = web.process_forwarding_job()
    assert result['success'] and result['failed_count'] == 0, result
    assert send.call_count == 2


def test_legacy_and_new_history_share_pagination_and_address_filter(client):
    source, _, _ = queued_event(client)
    web.log_forwarding_result(source['id'], source['email'], 'legacy', 'telegram', 'failed', 'old failure')
    first = client.get('/api/forwarding/history?limit=1&email_address=source@example.com').get_json()
    second = client.get('/api/forwarding/history?limit=1&offset=1&email_address=source@example.com').get_json()
    assert len(first['history']) == len(second['history']) == 1
    assert first['history'][0]['id'] != second['history'][0]['id']
    assert 'config_json' not in str(first) and 'webhook_url' not in str(first)


def test_instance_draft_test_preserves_own_credentials_and_is_not_saved(client):
    target = channel(client, sign_secret='own-signature')
    web.set_setting_encrypted('feishu_webhook_url', 'https://open.feishu.cn/open-apis/bot/v2/hook/other-global')
    before = web.get_db().execute('SELECT config_json FROM notification_channels WHERE id=?', (target,)).fetchone()[0]
    with patch.object(web, 'send_forward_feishu', return_value=True) as send:
        result = client.post('/api/notification-channels/test', json={'id': target, 'config': {'webhook_url': '', 'clear_sign_secret': True}})
    assert result.get_json()['success']
    assert send.call_args.kwargs['config']['webhook_url'] != web.get_setting_decrypted('feishu_webhook_url')
    assert send.call_args.kwargs['config']['sign_secret'] == ''
    assert web.get_db().execute('SELECT config_json FROM notification_channels WHERE id=?', (target,)).fetchone()[0] == before
    assert web.get_db().execute('SELECT COUNT(*) FROM forwarding_events').fetchone()[0] == 0


def test_failure_redacts_channel_credentials(client):
    source, _, rows = queued_event(client)
    db = web.get_db()
    target = web.forwarding_store.get_channel(db, db.execute('SELECT channel_id FROM forwarding_deliveries').fetchone()[0])
    config = web.forwarding_store.decode_config(target, web.decrypt_data)
    with patch.object(web, 'send_forward_feishu', side_effect=RuntimeError(config['webhook_url'])):
        assert web.process_notification_delivery(db, rows[0][0])[1]
    errors = db.execute('SELECT error_message FROM forwarding_attempts').fetchall()
    assert config['webhook_url'] not in str([tuple(r) for r in errors])


def test_schema_migration_failure_rolls_back_and_releases_connection(client):
    db = web.get_db()
    db.execute("DELETE FROM settings WHERE key='source_forwarding_migrated'")
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_bot_token','plain-test-token')")
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('telegram_chat_id','chat')")
    db.commit()
    with patch.object(web, 'encrypt_data', side_effect=RuntimeError('synthetic encryption failure')):
        with pytest.raises(RuntimeError):
            web.init_db()
    assert db.execute("SELECT value FROM settings WHERE key='source_forwarding_migrated'").fetchone() is None
    assert db.execute('SELECT COUNT(*) FROM notification_channels').fetchone()[0] == 0
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('writer-after-rollback','ok')")
    db.commit()


def test_tiered_groups_account_move_and_delete_cleanup(client):
    a, b = channel(client, '父组'), channel(client, '子组')
    db = web.get_db()
    root = db.execute("INSERT INTO groups(name,level) VALUES('路由父组',1)").lastrowid
    child = db.execute("INSERT INTO groups(name,parent_id,level) VALUES('路由子组',?,2)", (root,)).lastrowid
    leaf = db.execute("INSERT INTO groups(name,parent_id,level) VALUES('路由叶组',?,3)", (child,)).lastrowid
    db.commit()
    source = account(group=leaf)
    policy(client, 'group', root, targets=[a])
    policy(client, 'group', child, targets=[b])
    assert preview(client, account_id=source['id'])['channel_ids'] == [b]
    policy(client, 'account', source['id'], targets=[a])
    db.execute('UPDATE accounts SET group_id=1 WHERE id=?', (source['id'],))
    db.commit()
    assert preview(client, account_id=source['id'])['channel_ids'] == [a]
    assert web.delete_account_by_id(source['id'])
    assert db.execute("SELECT 1 FROM forwarding_policies WHERE scope_type='account' AND scope_id=?", (source['id'],)).fetchone() is None


@pytest.mark.parametrize('selection,expected', [('auto', 1), ('none', 0), ('telegram', 1)])
def test_legacy_selection_migration_and_new_boundary_survives_sync(client, selection, expected):
    db = web.get_db()
    source = account()
    for key, value in {'forward_channels': selection, 'telegram_bot_token': 'test-token', 'telegram_chat_id': 'test-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.commit()
    web.sync_legacy_forwarding()
    migrated = web.forwarding_store.get_policy(db, 'account', source['id'])
    assert len(migrated['channel_ids']) == expected
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None
    target = db.execute("SELECT id FROM notification_channels WHERE legacy_key='telegram'").fetchone()[0]
    policy(client, 'normal_default', mode='off')
    policy(client, 'normal_default', targets=[target])
    since = web.forwarding_store.get_policy(db, 'normal_default')['active_since'][target]
    assert since > 0
    web.build_forwarding_job_config()
    assert web.forwarding_store.get_policy(db, 'normal_default')['active_since'][target] == since


def test_remove_exact_address_override_allows_worker_deletion(client):
    _, source = cf_setup(client)
    response = client.delete('/api/forwarding/policies', json={'scope_type': 'cloudflare_address', 'scope_id': source['id'], 'match_value': 'only@example.com'})
    assert response.get_json()['success']
    assert web.delete_cloudflare_channel(source['id'])[0]
    assert web.get_db().execute("SELECT COUNT(*) FROM forwarding_policies WHERE scope_type LIKE 'cloudflare_%'").fetchone()[0] == 0


def test_success_audit_failure_is_not_committed_as_success(client):
    _, _, rows = queued_event(client)
    with patch.object(web, 'send_forward_feishu', return_value=True), patch.object(web, 'log_forwarding_result', return_value=False):
        result = web.process_notification_delivery(web.get_db(), rows[0][0])
    assert result[1]
    assert web.get_db().execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'failed'
    assert web.get_db().execute("SELECT 1 FROM forwarding_attempts WHERE status='success'").fetchone() is None


def test_explicit_account_cursor_reset_authorizes_unseen_history(client):
    target = channel(client)
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    received = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [{'id': 'explicit-history', 'date': received, 'folder': 'inbox'}]}), patch.object(
        web, 'fetch_forward_detail', return_value={'id': 'explicit-history', 'body': 'historical mail'},
    ), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        send.assert_not_called()
        response = client.post(f"/api/accounts/{source['id']}/forwarding/reset-cursor", json={'mode': 'clear', 'trigger_check': False})
        assert response.get_json()['success']
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        send.assert_called_once()


def test_cf_event_write_failure_rolls_back_progress_and_event(client):
    _, source = cf_setup(client)
    real_enqueue = web.enqueue_forwarding_event

    def fail_after_insert(*args, **kwargs):
        real_enqueue(*args, **kwargs)
        raise RuntimeError('synthetic database write failure')

    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}), patch.object(web, 'enqueue_forwarding_event', side_effect=fail_after_insert):
        result = web.process_cloudflare_forwarding_worker(source)
    assert result['had_processing_failure']
    assert web.get_db().execute('SELECT checkpoint_id FROM cloudflare_forward_scan_state').fetchone()[0] == 0
    assert web.get_db().execute('SELECT COUNT(*) FROM forwarding_events').fetchone()[0] == 0


def test_destination_changed_during_claim_never_receives_old_payload(client):
    _, _, rows = queued_event(client)
    db = web.get_db()
    target_id = db.execute('SELECT channel_id FROM forwarding_deliveries').fetchone()[0]
    new_url = 'https://open.feishu.cn/open-apis/bot/v2/hook/new-audience'

    class Connection:
        changed = False

        def execute(self, *args):
            return db.execute(*args)

        def rollback(self):
            db.rollback()

        def commit(self):
            db.commit()
            if not self.changed and db.execute('SELECT status FROM forwarding_deliveries').fetchone()[0] == 'sending':
                self.changed = True
                other = web.open_forwarding_db_connection()
                try:
                    web.forwarding_store.save_channel(other, {'config': {'webhook_url': new_url}}, web.encrypt_data, web.decrypt_data, target_id)
                    other.commit()
                finally:
                    other.close()

    with patch.object(web, 'send_forward_feishu', return_value=True) as send:
        web.process_notification_delivery(Connection(), rows[0][0])
    assert not send.called or send.call_args.kwargs['config']['webhook_url'] != new_url


def test_proxy_failover_logs_do_not_expose_notification_url_or_token(client, caplog):
    target = channel(client, '代理 TG', 'telegram', bot_token='sensitive-bot-token', chat_id='chat', proxy_url='http://proxy.example:8080')
    url = 'https://api.telegram.org/botsensitive-bot-token/sendMessage'
    with patch.object(web.requests, 'request', side_effect=[web.requests.ConnectionError(url), Mock(ok=True)]):
        response = client.post('/api/notification-channels/test', json={'id': target, 'config': {}})
    assert not response.get_json()['success']
    assert 'sensitive-bot-token' not in caplog.text
    assert url not in caplog.text
    assert url not in str(response.get_json())


def test_notification_policy_does_not_require_legacy_account_switch(client):
    target = channel(client)
    source = account()
    db = web.get_db()
    db.execute('UPDATE accounts SET forward_enabled=0 WHERE id=?', (source['id'],))
    db.commit()
    policy(client, 'account', source['id'], targets=[target])
    result = preview(client, account_id=source['id'])
    assert result['eligible'] and result['channel_ids'] == [target]
    assert source['id'] in [r['id'] for r in web.get_forwarding_enabled_accounts()]


@pytest.mark.parametrize('scope', ['account', 'group', 'cloudflare_worker'])
def test_bulk_source_policy_save_is_atomic_and_deduplicates_sources(client, scope):
    target = channel(client)
    db = web.get_db()
    if scope == 'account':
        ids = [account('first@example.com')['id'], account('second@example.com')['id']]
    elif scope == 'group':
        ids = [db.execute('INSERT INTO groups(name) VALUES(?)', (name,)).lastrowid for name in ('第一组', '第二组')]
        db.commit()
    else:
        ids = [web.create_cloudflare_channel(name, 'worker.example.com', 'example.com', 'test-password')[0] for name in ('Worker A', 'Worker B')]
    response = client.put('/api/forwarding/policies', json={'scope_type': scope, 'scope_ids': [*ids, ids[0]], 'mode': 'custom', 'channel_ids': [target]})
    assert response.status_code == 200, response.get_json()
    assert len(response.get_json()['policies']) == 2
    for source_id in ids:
        assert web.forwarding_store.get_policy(db, scope, source_id)['channel_ids'] == [target]
    bad = client.put('/api/forwarding/policies', json={'scope_type': scope, 'scope_ids': [ids[0], 99999999], 'mode': 'off'})
    assert bad.status_code == 400
    assert web.forwarding_store.get_policy(db, scope, ids[0])['channel_ids'] == [target]
    read = client.get('/api/forwarding/policies', query_string={'scope_type': scope, 'scope_ids': ','.join(map(str, ids))})
    assert len(read.get_json()['policies']) == 2


def test_bulk_remove_override_restores_automatic_group_inheritance(client):
    inherited, custom = channel(client, '上层目标'), channel(client, '独立目标')
    ids = [account('one@example.com')['id'], account('two@example.com')['id']]
    policy(client, 'group', 1, targets=[inherited])
    for source_id in ids:
        policy(client, 'account', source_id, targets=[custom])
    response = client.delete('/api/forwarding/policies', json={'scope_type': 'account', 'scope_ids': ids})
    assert response.get_json()['success']
    assert all(preview(client, account_id=source_id)['channel_ids'] == [inherited] for source_id in ids)


def test_batch_delete_policy_ids_handles_mixed_sources_and_preserves_unselected_rules(client):
    target, other = channel(client, '上层目标'), channel(client, '独立目标')
    first, unselected = account('batch@example.com'), account('keep@example.com')
    worker_id = worker()
    policy(client, 'normal_default', targets=[target])
    policy(client, 'group', 1, targets=[target])
    policy(client, 'account', first['id'], targets=[other])
    policy(client, 'account', unselected['id'], targets=[other])
    policy(client, 'cloudflare_worker', worker_id, targets=[target])
    policy(client, 'cloudflare_address', worker_id, targets=[other], match='special@example.com')
    db = web.get_db()
    scopes = [('normal_default', 0, ''), ('group', 1, ''), ('account', first['id'], ''), ('cloudflare_address', worker_id, 'special@example.com')]
    ids = [web.forwarding_store.get_policy(db, *scope)['id'] for scope in scopes]
    response = client.delete('/api/forwarding/policies', json={'policy_ids': ids + ids[:1]})
    assert response.status_code == 200 and response.get_json()['count'] == 4
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None
    assert all(web.forwarding_store.get_policy(db, *scope)['mode'] == 'inherit' for scope in scopes[1:])
    assert preview(client, account_id=unselected['id'])['channel_ids'] == [other]
    assert preview(client, worker_id=worker_id, address='special@example.com')['channel_ids'] == [target]


@pytest.mark.parametrize('ids', [[], None, [True], [0], ['1'], [1.5]])
def test_batch_delete_rejects_invalid_policy_ids_without_changes(client, ids):
    before = client.get('/api/forwarding/policies').get_json()['policies']
    response = client.delete('/api/forwarding/policies', json={'policy_ids': ids})
    assert response.status_code == 400
    assert client.get('/api/forwarding/policies').get_json()['policies'] == before


@pytest.mark.parametrize('stale_kind', ['missing', 'removed'])
def test_batch_delete_missing_rule_rejects_entire_batch(client, stale_kind):
    target = channel(client)
    source = account()
    policy(client, 'account', source['id'], targets=[target])
    db = web.get_db()
    before = web.forwarding_store.get_policy(db, 'account', source['id'])
    stale_id = 99999999
    if stale_kind == 'removed':
        removed = account('removed-rule@example.com')
        policy(client, 'account', removed['id'], targets=[target])
        stale_id = web.forwarding_store.get_policy(db, 'account', removed['id'])['id']
        client.delete('/api/forwarding/policies', json={'scope_type': 'account', 'scope_id': removed['id']})
    response = client.delete('/api/forwarding/policies', json={'policy_ids': [before['id'], stale_id]})
    assert response.status_code == 400
    assert web.forwarding_store.get_policy(db, 'account', source['id']) == before


def test_batch_delete_rolls_back_earlier_removals_on_write_failure(client):
    target = channel(client)
    source = account()
    db = web.get_db()
    db.execute("UPDATE notification_channels SET legacy_key='feishu' WHERE id=?", (target,))
    db.commit()
    policy(client, 'normal_default', targets=[target])
    policy(client, 'account', source['id'], targets=[target])
    before = client.get('/api/forwarding/policies').get_json()['policies']
    ids = [row['id'] for row in before]
    with patch.object(web.forwarding_store, 'save_policy', side_effect=ValueError('模拟删除失败')):
        response = client.delete('/api/forwarding/policies', json={'policy_ids': ids})
    assert response.status_code == 400
    assert client.get('/api/forwarding/policies').get_json()['policies'] == before
    assert db.execute("SELECT value FROM settings WHERE key='forward_channels'").fetchone()[0] == 'feishu'


@pytest.mark.parametrize('scope', ['account', 'group', 'cloudflare_worker'])
def test_create_policy_rejects_existing_rule_atomically_until_deleted(client, scope):
    original, replacement = channel(client, '原渠道'), channel(client, '新渠道')
    db = web.get_db()
    if scope == 'account':
        ids = [account('create-one@example.com')['id'], account('create-two@example.com')['id']]
    elif scope == 'group':
        ids = [db.execute('INSERT INTO groups(name) VALUES(?)', (name,)).lastrowid for name in ('新增第一组', '新增第二组')]
        db.commit()
    else:
        ids = [web.create_cloudflare_channel(name, 'worker.example.com', 'example.com', 'test-password')[0] for name in ('新增 Worker A', '新增 Worker B')]
    data = {'scope_type': scope, 'scope_ids': [ids[0]], 'mode': 'custom', 'channel_ids': [original]}
    created = client.post('/api/forwarding/policies', json=data)
    assert created.status_code == 200, created.get_json()
    before = web.forwarding_store.get_policy(db, scope, ids[0])
    conflict = client.post('/api/forwarding/policies', json={**data, 'scope_ids': ids, 'channel_ids': [replacement]})
    assert conflict.status_code == 400 and '先删除' in conflict.get_json()['error']
    assert web.forwarding_store.get_policy(db, scope, ids[0]) == before
    assert web.forwarding_store.get_policy(db, scope, ids[1])['id'] is None
    assert client.delete('/api/forwarding/policies', json=data).status_code == 200
    created = client.post('/api/forwarding/policies', json={**data, 'channel_ids': [replacement]})
    assert created.status_code == 200, created.get_json()
    assert web.forwarding_store.get_policy(db, scope, ids[0])['channel_ids'] == [replacement]


def test_legacy_disabled_accounts_stay_off_without_overwriting_explicit_rules(client):
    db = web.get_db()
    for key, value in {'forward_channels': 'telegram', 'telegram_bot_token': 'old-token', 'telegram_chat_id': 'old-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.commit()
    web.sync_legacy_forwarding()
    old_off = account('old-off@example.com')
    configured = account('configured@example.com')
    target = channel(client)
    policy(client, 'account', configured['id'], targets=[target])
    db.execute('UPDATE accounts SET forward_enabled=0')
    db.execute("DELETE FROM settings WHERE key IN ('source_forwarding_migrated','source_forwarding_account_rules_v3')")
    db.commit()
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'account', old_off['id'])['mode'] == 'off'
    assert preview(client, account_id=old_off['id'])['channel_ids'] == []
    assert preview(client, account_id=configured['id'])['channel_ids'] == [target]
    policy(client, 'account', old_off['id'], mode='inherit')
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'account', old_off['id'])['mode'] == 'inherit'


@pytest.mark.parametrize('selection,expected', [
    ('auto', {'smtp', 'telegram', 'feishu'}),
    ('telegram', {'telegram'}),
    ('email,tg', {'smtp', 'telegram'}),
    (' Telegram , FEISHU ', {'telegram', 'feishu'}),
    ('none', set()),
])
def test_legacy_migration_preserves_selected_channels_for_both_account_switch_states(client, selection, expected):
    db = web.get_db()
    sources = [account('legacy-on@example.com'), account('legacy-off@example.com')]
    db.execute('UPDATE accounts SET forward_enabled=0 WHERE id=?', (sources[1]['id'],))
    settings = {'forward_channels': selection, 'smtp_host': 'smtp.example.com', 'smtp_username': 'sender@example.com',
                'email_forward_recipient': 'archive@example.com', 'telegram_bot_token': 'migration-test-token',
                'telegram_chat_id': 'migration-test-chat', 'feishu_webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/migration-test'}
    for key, value in settings.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.execute("DELETE FROM settings WHERE key IN ('source_forwarding_migrated','source_forwarding_account_switch_retired','source_forwarding_channel_selection_v2')")
    db.commit()
    web.init_db()
    web.init_db()
    default = web.forwarding_store.get_policy(db, 'normal_default')
    assert default['id'] is None
    for source in sources:
        result = preview(client, account_id=source['id'])
        old_enabled = source['id'] == sources[0]['id']
        assert {row['type'] for row in result['channels']} == (expected if old_enabled else set())
        rule = web.forwarding_store.get_policy(db, 'account', source['id'])
        if old_enabled:
            assert rule['mode'] == ('custom' if expected else 'off')
            assert rule['updated_at'] == 0
        else:
            assert rule['mode'] == 'off'
        saved = db.execute('SELECT forward_last_checked_at FROM accounts WHERE id=?', (source['id'],)).fetchone()[0]
        assert saved == source['forward_last_checked_at']
    assert db.execute("SELECT COUNT(*) FROM notification_channels WHERE legacy_key IS NOT NULL").fetchone()[0] == 3


def test_selection_upgrade_repairs_untouched_default_but_preserves_manual_rules(client):
    db = web.get_db()
    source = account()
    policy(client, 'account', source['id'], mode='off')
    legacy_default(client)
    db.execute("UPDATE settings SET value=' TG ' WHERE key='forward_channels'")
    db.commit()
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None
    assert preview(client, account_id=source['id'])['mode'] == 'off'
    policy(client, 'normal_default', mode='off')
    db.execute("DELETE FROM settings WHERE key='source_forwarding_account_rules_v3'")
    db.execute("UPDATE settings SET value='telegram' WHERE key='forward_channels'")
    db.commit()
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'normal_default')['mode'] == 'off'


def test_selection_repair_keeps_previously_disabled_accounts_off_and_new_accounts_inherit(client):
    db = web.get_db()
    old_enabled = account('enabled-before-upgrade@example.com')
    old_disabled = account('disabled-before-upgrade@example.com')
    db.execute('UPDATE accounts SET forward_enabled=0 WHERE id=?', (old_disabled['id'],))
    legacy_default(client)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('source_forwarding_account_switch_retired','1')")
    db.execute("DELETE FROM settings WHERE key='source_forwarding_account_rules_v3'")
    db.commit()
    web.init_db()
    assert {row['type'] for row in preview(client, account_id=old_enabled['id'])['channels']} == {'telegram'}
    assert preview(client, account_id=old_disabled['id'])['mode'] == 'off'
    group_target = channel(client, '新分组目标')
    policy(client, 'group', 1, targets=[group_target])
    assert web.add_account('new-after-upgrade@example.com', '', 'test-client', 'test-refresh', group_id=1)
    added = web.get_account_by_email('new-after-upgrade@example.com')
    web.init_db()
    assert preview(client, account_id=added['id'])['mode'] == 'custom'
    assert preview(client, account_id=added['id'])['channel_ids'] == [group_target]
    assert web.forwarding_store.get_policy(db, 'account', added['id'])['id'] is None


def test_legacy_default_becomes_per_account_rules_with_original_boundaries(client):
    enabled, disabled, manual = account('old-on@example.com'), account('old-off@example.com'), account('manual@example.com')
    target, default = legacy_default(client)
    db = web.get_db()
    db.execute('UPDATE accounts SET forward_enabled=0 WHERE id=?', (disabled['id'],))
    db.commit()
    manual_target = channel(client, '手工目标')
    group_id = db.execute("INSERT INTO groups(name) VALUES('手工分组')").lastrowid
    db.commit()
    grouped = account('manual-group@example.com', group=group_id)
    policy(client, 'group', group_id, targets=[manual_target])
    policy(client, 'account', manual['id'], targets=[manual_target])
    before_manual = web.forwarding_store.get_policy(db, 'account', manual['id'])
    web.init_db()
    web.init_db()
    migrated = web.forwarding_store.get_policy(db, 'account', enabled['id'])
    assert migrated['mode'] == 'custom' and migrated['channel_ids'] == [target]
    assert migrated['active_since'] == default['active_since']
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None
    assert preview(client, account_id=disabled['id'])['mode'] == 'off'
    assert web.forwarding_store.get_policy(db, 'account', manual['id']) == before_manual
    assert web.forwarding_store.get_policy(db, 'account', grouped['id'])['id'] is None
    assert preview(client, account_id=grouped['id'])['channel_ids'] == [manual_target]
    policy(client, 'account', enabled['id'], mode='inherit')
    web.init_db()
    web.build_forwarding_job_config()
    assert web.forwarding_store.get_policy(db, 'account', enabled['id'])['mode'] == 'inherit'
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None


def test_legacy_settings_update_account_rules_without_creating_default_or_overwriting_manual_rules(client):
    db = web.get_db()
    enabled, manual = account('compat-on@example.com'), account('compat-manual@example.com')
    for key, value in {'forward_channels': 'telegram', 'telegram_bot_token': 'old-token', 'telegram_chat_id': 'old-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.commit()
    web.sync_legacy_forwarding()
    manual_target = channel(client, '手工通知目标')
    policy(client, 'account', manual['id'], targets=[manual_target])
    before = web.forwarding_store.get_policy(db, 'account', manual['id'])
    result = client.put('/api/settings', json={'forward_channels': []})
    assert result.status_code == 200 and result.get_json()['success']
    assert preview(client, account_id=enabled['id'])['mode'] == 'off'
    assert web.forwarding_store.get_policy(db, 'account', manual['id']) == before
    assert web.forwarding_store.get_policy(db, 'normal_default')['id'] is None


def test_legacy_account_conversion_failure_rolls_back_default_and_all_accounts(client):
    account('first-conversion@example.com')
    account('second-conversion@example.com')
    _, before = legacy_default(client)
    db = web.get_db()
    real_save = web.forwarding_store.save_policy
    calls = []

    def fail_second(db, data, **kwargs):
        calls.append(data)
        if len(calls) == 2:
            raise ValueError('模拟第二个账号迁移失败')
        return real_save(db, data, **kwargs)

    with patch.object(web.forwarding_store, 'save_policy', side_effect=fail_second), pytest.raises(ValueError):
        web.init_db()
    assert web.forwarding_store.get_policy(db, 'normal_default') == before
    assert db.execute("SELECT COUNT(*) FROM forwarding_policies WHERE scope_type='account'").fetchone()[0] == 0
    assert db.execute("SELECT value FROM settings WHERE key='source_forwarding_account_rules_v3'").fetchone() is None


def test_new_account_automatically_uses_group_without_backfilling_old_mail(client):
    target = channel(client)
    policy(client, 'group', 1, targets=[target])
    assert web.add_account('joined@example.com', '', 'test-client', 'test-refresh', group_id=1)
    source = web.get_account_by_email('joined@example.com')
    assert preview(client, account_id=source['id'])['channel_ids'] == [target]
    received = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [{'id': 'before-join', 'date': received, 'folder': 'inbox'}]}), patch.object(
        web, 'fetch_forward_detail', return_value={'id': 'before-join', 'body': 'old mail'},
    ) as detail:
        web.process_forwarding_account(source, web.build_forwarding_job_config())
        detail.assert_not_called()


def rule_options(client, scope, source_id, targets, keywords='', **extra):
    response = client.put('/api/forwarding/policies', json={
        'scope_type': scope, 'scope_id': source_id, 'mode': 'custom', 'channel_ids': targets,
        'keywords': keywords, **extra,
    })
    assert response.status_code == 200, response.get_json()
    return response.get_json()['policy']


def test_rule_keywords_override_parent_and_ignore_old_global_setting(client):
    target = channel(client)
    first, second = account('first@example.com'), account('second@example.com')
    rule_options(client, 'group', 1, [target], keywords='group-only')
    saved = rule_options(client, 'account', first['id'], [target], keywords='Urgent\nurgent\n账单')
    assert saved['keywords'] == 'Urgent\n账单'
    assert preview(client, account_id=first['id'])['keywords'] == 'Urgent\n账单'
    assert preview(client, account_id=second['id'])['keywords'] == 'group-only'
    web.set_setting('forward_keywords', 'must-not-apply')
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [
        {'id': 'rule-mail', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'},
    ]}), patch.object(web, 'fetch_forward_detail', return_value={
        'id': 'rule-mail', 'subject': 'hello', 'body': '<p>URGENT</p>', 'body_type': 'html',
    }), patch.object(web, 'send_forward_feishu', return_value=True) as send:
        config = web.build_forwarding_job_config()
        web.process_forwarding_account(first, config)
        web.process_forwarding_account(second, config)
        assert send.call_count == 1


def test_rule_options_upgrade_preserves_legacy_values_and_runs_once(client):
    a = channel(client, 'SMTP A', 'smtp', recipient='old-a@example.com', host='smtp.example.com', username='sender@example.com')
    b = channel(client, 'SMTP B', 'smtp', recipient='old-b@example.com', host='smtp.example.com', username='sender@example.com')
    source, wid = account(), worker()
    policy(client, 'account', source['id'], targets=[a, b])
    policy(client, 'cloudflare_worker', wid, targets=[a])
    db = web.get_db()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('forward_keywords','legacy\nLegacy\n关键字')")
    db.execute("DELETE FROM settings WHERE key='source_forwarding_rule_options_v4'")
    before = web.forwarding_store.get_policy(db, 'account', source['id'])
    db.execute('ALTER TABLE forwarding_policies DROP COLUMN keywords')
    db.execute('ALTER TABLE forwarding_policies DROP COLUMN senders')
    db.commit()
    web.init_db()
    migrated = web.forwarding_store.get_policy(db, 'account', source['id'])
    assert migrated['keywords'] == 'legacy\n关键字'
    assert migrated['senders'] == ''
    assert [web.forwarding_store.decode_config(web.forwarding_store.get_channel(db, cid), web.decrypt_data)['recipient'] for cid in (a, b)] == ['old-a@example.com', 'old-b@example.com']
    assert migrated['active_since'] == before['active_since']
    assert migrated['updated_at'] == before['updated_at']
    assert preview(client, worker_id=wid, address='any@example.com')['keywords'] == ''
    rule_options(client, 'account', source['id'], [a], keywords='custom')
    manual = web.forwarding_store.get_policy(db, 'account', source['id'])
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'account', source['id']) == manual


def test_cf_rule_keywords_filter_before_enqueue_and_advance_scan(client):
    target, source = cf_setup(client)
    rule_options(client, 'cloudflare_address', source['id'], [target], keywords='never-match', match_value='only@example.com')
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}), patch.object(web, 'send_forward_feishu') as send:
        result = web.process_cloudflare_forwarding_worker(source)
    assert not result['error'], result
    send.assert_not_called()
    assert web.get_db().execute('SELECT COUNT(*) FROM forwarding_events').fetchone()[0] == 0
    assert web.get_db().execute('SELECT checkpoint_id FROM cloudflare_forward_scan_state').fetchone()[0] == 1


@pytest.mark.parametrize(('detail', 'expected'), [
    ({'from': 'Alerts <ALERTS@example.com>', 'subject': 'URGENT'}, True),
    ({'from': 'billing@example.com', 'body': '<p>urgent</p>', 'body_type': 'html'}, True),
    ({'from': 'alerts@example.com', 'body': 'newsletter'}, False),
    ({'from': 'other@example.com', 'subject': 'urgent'}, False),
    ({'from': 'alerts@example.com.evil.test', 'subject': 'urgent'}, False),
    ({'from': '"alerts@example.com" <other@example.com>', 'subject': 'urgent'}, False),
    ({'subject': 'urgent'}, False),
])
def test_rule_sender_and_keywords_both_must_match(client, detail, expected):
    target, source = channel(client), account()
    saved = rule_options(client, 'account', source['id'], [target], keywords='urgent',
                         senders=' Alerts@example.com\nalerts@EXAMPLE.com\n billing@example.com ')
    assert saved['senders'] == 'alerts@example.com\nbilling@example.com'
    route = web.forwarding_store.resolve_policy(web.get_db(), account_id=source['id'])
    assert web.forward_email_matches_policy(detail, route) is expected


@pytest.mark.parametrize('allowed', [False, True])
def test_sender_filter_routes_normal_and_cf_mail_and_retains_smtp_configuration(client, allowed):
    smtp = channel(client, 'SMTP', 'smtp', recipient='archive@example.com', host='smtp.example.com',
                   username='shared@example.com', from_email='shared@example.com')
    source, wid = account(), worker()
    rule_options(client, 'account', source['id'], [smtp], senders='other@example.com' if allowed else 'allowed@example.com')
    rule_options(client, 'cloudflare_worker', wid, [smtp], senders='sender@example.net' if allowed else 'allowed@example.com')
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': [
        {'id': 'blocked', 'date': '2090-01-01T00:00:00Z', 'folder': 'inbox'},
    ]}), patch.object(web, 'fetch_forward_detail', return_value={'id': 'blocked', 'from': 'other@example.com'}), patch.object(
        web, 'send_forward_email', return_value=True,
    ) as send:
        result = web.process_forwarding_account(source, web.build_forwarding_job_config())
        assert result['cursor_updated'] and not result['had_processing_failure']
        with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [cf_mail(1)]}):
            result = web.process_cloudflare_forwarding_worker(web.get_cloudflare_channel_by_id(wid, include_secret=True))
        assert not result['error']
        assert send.call_count == (2 if allowed else 0)
        for call in send.call_args_list:
            assert call.kwargs['config']['from_email'] == 'shared@example.com'
            assert call.kwargs['config']['recipient'] == 'archive@example.com'
    assert web.forwarding_store.decode_config(web.forwarding_store.get_channel(web.get_db(), smtp), web.decrypt_data)['from_email'] == 'shared@example.com'


@pytest.mark.parametrize('options', [{'keywords': None}, {'keywords': []}, {'senders': []},
                                     {'senders': 'bad-address'}, {'senders': '*@example.com'}])
def test_invalid_rule_conditions_do_not_partially_create_bulk_rules(client, options):
    target = channel(client)
    sources = [account('first@example.com')['id'], account('second@example.com')['id']]
    response = client.post('/api/forwarding/policies', json={
        'scope_type': 'account', 'scope_ids': sources, 'mode': 'custom', 'channel_ids': [target], **options,
    })
    assert response.status_code == 400
    assert web.get_db().execute("SELECT COUNT(*) FROM forwarding_policies WHERE scope_type='account'").fetchone()[0] == 0


def test_rule_options_schema_failure_rolls_back_and_can_retry(client):
    target, source = channel(client), account()
    policy(client, 'account', source['id'], targets=[target])
    db = web.get_db()
    db.execute("DELETE FROM settings WHERE key='source_forwarding_rule_options_v4'")
    db.execute('ALTER TABLE forwarding_policies DROP COLUMN keywords')
    db.execute('ALTER TABLE forwarding_policies DROP COLUMN senders')
    db.commit()
    with patch.object(web.forwarding_store, 'normalize_keywords', side_effect=ValueError('模拟规则条件迁移失败')):
        with pytest.raises(ValueError):
            web.init_db()
    assert not db.execute("SELECT 1 FROM settings WHERE key='source_forwarding_rule_options_v4'").fetchone()
    assert 'keywords' not in {row['name'] for row in db.execute('PRAGMA table_info(forwarding_policies)')}
    web.init_db()
    assert preview(client, account_id=source['id'])['senders'] == ''


@pytest.mark.parametrize('cf', [False, True])
def test_rule_conditions_inherit_together_and_restore_after_delete(client, cf):
    target = channel(client)
    sid = worker() if cf else account()['id']
    rule_options(client, 'cloudflare_worker' if cf else 'group', sid if cf else 1, [target],
                 keywords='parent', senders='parent@example.com')
    params = {'worker_id': sid, 'address': 'only@example.com'} if cf else {'account_id': sid}
    assert preview(client, **params)['senders'] == 'parent@example.com'
    scope = 'cloudflare_address' if cf else 'account'
    match = 'only@example.com' if cf else ''
    rule_options(client, scope, sid, [target], match_value=match)
    assert preview(client, **params)['keywords'] == preview(client, **params)['senders'] == ''
    response = client.delete('/api/forwarding/policies', json={'scope_type': scope, 'scope_id': sid, 'match_value': match})
    assert response.get_json()['success']
    assert preview(client, **params)['keywords'] == 'parent'
    assert preview(client, **params)['senders'] == 'parent@example.com'


def test_failed_delivery_keeps_original_filter_acceptance_and_does_not_repeat_success(client):
    target, source = channel(client), account()
    rule_options(client, 'account', source['id'], [target], keywords='accepted', senders='old@example.com')
    db = web.get_db()
    event_id = web.enqueue_forwarding_event(db, web.forwarding_store.resolve_policy(db, account_id=source['id']),
        'accepted-before-change', time.time() + 1, ('title', 'body', '', 'summary'))
    db.commit()
    with patch.object(web, 'send_forward_feishu', return_value=False):
        web.process_forwarding_event(db, event_id, web.build_forwarding_account_result(source))
    rule_options(client, 'account', source['id'], [target], keywords='changed', senders='new@example.com')
    db.execute('UPDATE forwarding_deliveries SET next_attempt_at=0')
    db.commit()
    with patch.object(web, 'send_forward_feishu', return_value=True) as send:
        web.retry_forwarding_deliveries()
        web.retry_forwarding_deliveries()
    assert send.call_count == 1
    assert db.execute('SELECT status FROM forwarding_deliveries WHERE event_id=?', (event_id,)).fetchone()[0] == 'succeeded'


def test_cf_filter_change_does_not_backfill_previously_filtered_checkpoint_mail(client):
    target, source = cf_setup(client)
    now = time.time()
    rule_options(client, 'cloudflare_address', source['id'], [target], keywords='never-match', match_value='only@example.com')
    mail = cf_mail(1, created_at=now + 1)
    with patch.object(web, 'cloudflare_get_admin_messages', return_value={'success': True, 'messages': [mail]}), patch.object(
        web, 'send_forward_feishu', return_value=True,
    ) as send:
        assert not web.process_cloudflare_forwarding_worker(source)['error']
        with patch.object(web.time, 'time', return_value=now + 2):
            rule_options(client, 'cloudflare_address', source['id'], [target], match_value='only@example.com')
        assert not web.process_cloudflare_forwarding_worker(source)['error']
    send.assert_not_called()


@pytest.mark.parametrize('scope', ['normal_default', 'account', 'group', 'cloudflare_worker', 'cloudflare_domain', 'cloudflare_address'])
def test_edit_rules_by_id_keeps_identity_and_only_changes_requested_fields(client, scope):
    a, b = channel(client, '原渠道'), channel(client, '第二渠道')
    db = web.get_db()
    if scope == 'normal_default':
        sources = [(0, '')]
    elif scope == 'account':
        sources = [(account('edit-one@example.com')['id'], ''), (account('edit-two@example.com')['id'], '')]
    elif scope == 'group':
        sources = [(db.execute('INSERT INTO groups(name) VALUES(?)', (name,)).lastrowid, '') for name in ('编辑组一', '编辑组二')]
        db.commit()
    elif scope == 'cloudflare_worker':
        sources = [(worker(), '')]
    else:
        wid = worker()
        sources = [(wid, name) for name in (('one.example.com', 'two.example.com') if scope == 'cloudflare_domain' else ('one@example.com', 'two@example.com'))]
    before = [rule_options(client, scope, sid, [a if i == 0 else b], keywords='old',
                           senders=f'sender{i}@example.com', match_value=match) for i, (sid, match) in enumerate(sources)]
    response = client.patch('/api/forwarding/policies', json={
        'policy_ids': [p['id'] for p in before] + [before[0]['id']], 'changes': {'keywords': 'urgent\nURGENT'},
    })
    assert response.status_code == 200, response.get_json()
    after = response.get_json()['policies']
    assert response.get_json()['count'] == len(before)
    for old, new in zip(before, after):
        assert new['keywords'] == 'urgent'
        for key in ('id', 'scope_type', 'scope_id', 'match_value', 'channel_ids', 'senders', 'mode'):
            assert new[key] == old[key]


@pytest.mark.parametrize('invalid', [
    {'policy_ids': []}, {'policy_ids': [True]}, {'policy_ids': ['1']},
    {'changes': {}}, {'changes': {'scope_id': 3}}, {'changes': {'scope_type': 'group'}},
    {'changes': {'match_value': 'elsewhere@example.com'}}, {'changes': {'mode': 'inherit'}},
    {'changes': {'senders': []}}, {'changes': {'channel_ids': [999999]}},
])
def test_edit_rules_rejects_invalid_requests_without_changes(client, invalid):
    target, source = channel(client), account()
    current = rule_options(client, 'account', source['id'], [target], keywords='keep')
    response = client.patch('/api/forwarding/policies', json={
        'policy_ids': [current['id']], 'changes': {'keywords': 'new'}, **invalid,
    })
    assert response.status_code == 400
    assert client.get('/api/forwarding/policies', query_string={'scope_type': 'account', 'scope_id': source['id']}).get_json()['policy'] == current


@pytest.mark.parametrize('bad_selection', ['mixed', 'missing', 'removed'])
def test_bulk_edit_rejects_mixed_or_stale_rules_atomically(client, bad_selection):
    target, source = channel(client), account()
    current = rule_options(client, 'account', source['id'], [target], keywords='keep')
    second = 999999
    if bad_selection == 'mixed':
        second = rule_options(client, 'group', 1, [target])['id']
    elif bad_selection == 'removed':
        second_source = account('stale@example.com')
        second = rule_options(client, 'account', second_source['id'], [target])['id']
        client.delete('/api/forwarding/policies', json={'policy_ids': [second]})
    before = client.get('/api/forwarding/policies').get_json()['policies']
    response = client.patch('/api/forwarding/policies', json={'policy_ids': [current['id'], second], 'changes': {'keywords': 'new'}})
    assert response.status_code == 400
    assert client.get('/api/forwarding/policies').get_json()['policies'] == before


def test_bulk_edit_write_failure_rolls_back_every_rule(client):
    target = channel(client)
    before = [rule_options(client, 'account', account(address)['id'], [target], keywords='old') for address in ('one@example.com', 'two@example.com')]
    real_save = web.forwarding_store.save_policy
    calls = []

    def fail_second(db, data, **kwargs):
        calls.append(data)
        if len(calls) == 2:
            raise ValueError('模拟第二条规则编辑失败')
        return real_save(db, data, **kwargs)

    with patch.object(web.forwarding_store, 'save_policy', side_effect=fail_second):
        response = client.patch('/api/forwarding/policies', json={'policy_ids': [p['id'] for p in before], 'changes': {'mode': 'off'}})
    assert response.status_code == 400
    assert client.get('/api/forwarding/policies').get_json()['policies'] == before


def test_edit_rule_cancels_removed_pending_target_without_resending_success(client):
    a, b = channel(client, '成功目标'), channel(client, '移除目标')
    source, eid, deliveries = queued_event(client, [a, b])
    db = web.get_db()
    with patch.object(web, 'send_forward_feishu', return_value=True):
        web.process_notification_delivery(db, deliveries[0][0])
    current = web.forwarding_store.get_policy(db, 'account', source['id'])
    response = client.patch('/api/forwarding/policies', json={'policy_ids': [current['id']], 'changes': {'channel_ids': [a]}})
    assert response.status_code == 200, response.get_json()
    assert [row[0] for row in db.execute('SELECT status FROM forwarding_deliveries WHERE event_id=? ORDER BY channel_id', (eid,))] == ['succeeded', 'cancelled']
    with patch.object(web, 'send_forward_feishu') as send:
        web.process_forwarding_event(db, eid, web.build_forwarding_account_result(source))
    send.assert_not_called()
