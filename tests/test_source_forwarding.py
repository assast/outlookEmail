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
    if web.CSRF_AVAILABLE:
        monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', True)
        assert client.post('/api/notification-channels', json={}).status_code == 400
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
    for key, value in {'forward_channels': selection, 'telegram_bot_token': 'test-token', 'telegram_chat_id': 'test-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.commit()
    web.sync_legacy_forwarding()
    default = web.forwarding_store.get_policy(db, 'normal_default')
    assert len(default['channel_ids']) == expected
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
    db.execute("DELETE FROM settings WHERE key='source_forwarding_account_switch_retired'")
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
    assert default['mode'] == ('custom' if expected else 'off')
    for source in sources:
        result = preview(client, account_id=source['id'])
        old_enabled = source['id'] == sources[0]['id']
        assert {row['type'] for row in result['channels']} == (expected if old_enabled else set())
        rule = web.forwarding_store.get_policy(db, 'account', source['id'])
        if old_enabled:
            assert rule['id'] is None
        else:
            assert rule['mode'] == 'off'
        saved = db.execute('SELECT forward_last_checked_at FROM accounts WHERE id=?', (source['id'],)).fetchone()[0]
        assert saved == source['forward_last_checked_at']
    assert db.execute("SELECT COUNT(*) FROM notification_channels WHERE legacy_key IS NOT NULL").fetchone()[0] == 3


def test_selection_upgrade_repairs_untouched_default_but_preserves_manual_rules(client):
    db = web.get_db()
    source = account()
    policy(client, 'account', source['id'], mode='off')
    for key, value in {'forward_channels': ' TG ', 'telegram_bot_token': 'old-token', 'telegram_chat_id': 'old-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.execute("DELETE FROM settings WHERE key='source_forwarding_channel_selection_v2'")
    db.commit()
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'normal_default')['mode'] == 'custom'
    assert preview(client, account_id=source['id'])['mode'] == 'off'
    policy(client, 'normal_default', mode='off')
    db.execute("DELETE FROM settings WHERE key='source_forwarding_channel_selection_v2'")
    db.execute("UPDATE settings SET value='telegram' WHERE key='forward_channels'")
    db.commit()
    web.init_db()
    assert web.forwarding_store.get_policy(db, 'normal_default')['mode'] == 'off'


def test_selection_repair_keeps_previously_disabled_accounts_off_and_new_accounts_inherit(client):
    db = web.get_db()
    old_enabled = account('enabled-before-upgrade@example.com')
    old_disabled = account('disabled-before-upgrade@example.com')
    db.execute('UPDATE accounts SET forward_enabled=0 WHERE id=?', (old_disabled['id'],))
    for key, value in {'forward_channels': ' TG ', 'telegram_bot_token': 'old-token', 'telegram_chat_id': 'old-chat'}.items():
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('source_forwarding_account_switch_retired','1')")
    db.execute("DELETE FROM settings WHERE key='source_forwarding_channel_selection_v2'")
    db.commit()
    web.init_db()
    assert {row['type'] for row in preview(client, account_id=old_enabled['id'])['channels']} == {'telegram'}
    assert preview(client, account_id=old_disabled['id'])['mode'] == 'off'
    assert web.add_account('new-after-upgrade@example.com', '', 'test-client', 'test-refresh', group_id=1)
    added = web.get_account_by_email('new-after-upgrade@example.com')
    web.init_db()
    assert preview(client, account_id=added['id'])['mode'] == 'custom'
    assert web.forwarding_store.get_policy(db, 'account', added['id'])['id'] is None


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
