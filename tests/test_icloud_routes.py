import importlib
import os
import tempfile
from unittest.mock import Mock

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DATABASE_PATH', os.path.join(tempfile.mkdtemp(prefix='icloud-routes-'), 'app.db'))
web = importlib.import_module('web_outlook_app')

from outlook_web.icloud_protocol import DirectorySnapshot, HiddenAddress


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = str(tmp_path / 'app.db')
    monkeypatch.setattr(web, 'DATABASE', database)
    monkeypatch.setattr(web.icloud_manager, 'database', database)
    monkeypatch.setattr(web, 'icloud_wake', lambda _: None)
    monkeypatch.setattr(web.icloud_manager, 'schedule', lambda _: False)
    network = Mock(side_effect=AssertionError('offline test must not connect to IMAP'))
    monkeypatch.setattr(web, 'create_imap_connection', network)
    monkeypatch.setattr(web, 'fetch_imap_account_detail_response', lambda *args, **kwargs: {'success': False, 'error': 'no recipient evidence'})
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', False)
    with web.app.app_context():
        web.init_db()
        web.set_setting('external_api_key', 'icloud-test-key')
        assert web.add_account('receiver@icloud.com', '', '', '', account_type='imap', provider='icloud', imap_password='app-password')
        mailbox = web.get_account_by_email('receiver@icloud.com')
        store = web.icloud_store()
        account = store.save_account({'apple_id': 'apple@example.com', 'region': 'global', 'mailbox_account_id': mailbox['id']})
        store.sync(account['id'], DirectorySnapshot('web', (
            HiddenAddress('a', 'a@icloud.com', 'receiver@icloud.com', True),
            HiddenAddress('b', 'b@icloud.com', 'receiver@icloud.com', True),
        ), True))
    result = web.app.test_client()
    with result.session_transaction() as session:
        session['logged_in'] = True
    result.main_id, result.mailbox_id = account['id'], mailbox['id']
    yield result
    assert not network.called


def test_status_reads_are_local_and_management_requires_web_login_and_csrf(client, monkeypatch):
    perform = Mock(side_effect=AssertionError('status must not probe Apple'))
    monkeypatch.setattr(web.icloud_manager, 'perform', perform)
    response = client.get('/api/icloud/accounts')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert 'password_enc' not in response.get_data(as_text=True)
    with client.session_transaction() as session: session.clear()
    response = client.get('/api/icloud/accounts', headers={'X-API-Key': 'icloud-test-key'})
    assert response.status_code == 401
    with client.session_transaction() as session: session['logged_in'] = True
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', True)
    assert client.post(f'/api/icloud/accounts/{client.main_id}/login', json={'password': 'password'}).status_code == 400
    assert not perform.called


@pytest.mark.parametrize('channel', ['web', 'account'])
def test_manual_login_recovers_from_corrupt_saved_session(client, monkeypatch, channel):
    upstream = Mock()
    upstream.snapshot.return_value = {'state': 'verification_required'}
    upstream.expires_at = None
    factory = Mock(return_value=upstream)
    monkeypatch.setattr(web.icloud_manager, 'client_factory', factory)
    with web.app.app_context():
        store = web.icloud_store()
        store.db.execute("UPDATE icloud_sessions SET snapshot_enc='enc:broken' WHERE account_id=? AND channel=?",
                         (client.main_id, channel))
        store.db.commit()
    response = client.post(f'/api/icloud/accounts/{client.main_id}/login',
                           json={'channel': channel, 'password': 'replacement-password'})
    assert response.status_code == 200 and response.get_json()['state'] == 'verification_required'
    assert factory.call_args.kwargs['snapshot'] is None
    upstream.login.assert_called_once_with('replacement-password')
    assert 'replacement-password' not in response.get_data(as_text=True)
    with web.app.app_context():
        store = web.icloud_store()
        row = store.session(client.main_id, channel)
        assert store.unseal(row['snapshot_enc']) == {'state': 'verification_required'}


def test_managed_address_resolution_internal_external_and_invalid_no_fallback(client, monkeypatch):
    def page(account, folder, skip, top, *args):
        return {'success': True, 'emails': [
            {'id': 'b', 'to': 'b@icloud.com', 'folder': folder},
            {'id': 'a', 'to': 'a@icloud.com', 'folder': folder}], 'has_more': False}
    monkeypatch.setattr(web, 'fetch_account_folder_emails', page)
    internal = client.get('/api/emails/a@icloud.com?folder=inbox').get_json()
    assert [item['id'] for item in internal['emails']] == ['a']
    external = client.get('/api/external/emails?email=a@icloud.com&folder=inbox', headers={'X-API-Key': 'icloud-test-key'})
    assert external.status_code == 200 and [item['id'] for item in external.get_json()['emails']] == ['a']
    with web.app.app_context():
        store = web.icloud_store()
        store.save_account({'mailbox_account_id': None}, client.main_id)
    assert client.get('/api/emails/a@icloud.com').status_code == 404
    assert client.get('/api/external/emails?email=a@icloud.com', headers={'X-API-Key': 'icloud-test-key'}).status_code == 404


def test_other_address_detail_attachments_and_local_cache_cannot_leak(client, monkeypatch):
    monkeypatch.setattr(web, 'fetch_imap_account_detail_response', lambda *args, **kwargs: {
        'success': True, 'email': {'to': 'b@icloud.com', 'body': 'PRIVATE BODY', 'attachments': [{'name': 'PRIVATE FILE'}]}})
    response = client.get('/api/email/a@icloud.com/b?method=imap&folder=inbox')
    assert not response.get_json()['success'] and 'PRIVATE' not in response.get_data(as_text=True)
    download = Mock(side_effect=AssertionError('must check ownership before downloading'))
    monkeypatch.setattr(web, 'download_email_attachment_imap_generic_result', download)
    response = client.get('/api/email/a@icloud.com/b/attachments/file?method=imap')
    assert not response.get_json()['success'] and not download.called
    with web.app.app_context():
        web.set_setting('normal_mail_local_retention_enabled', 'true')
        web.clear_normal_mail_local_retention_enabled_cache()
        account = web.get_account_by_id(client.mailbox_id)
        web.upsert_retained_normal_mail_list_items(account, 'inbox', [
            {'id': 'a', 'to': 'other@example.com', 'recipient_headers': {'Delivered-To': ['a@icloud.com']}, 'folder': 'inbox'},
            {'id': 'b', 'to': 'b@icloud.com', 'folder': 'inbox'},
            {'id': 'unknown', 'folder': 'inbox', 'body_preview': 'a@icloud.com'},
        ])
    response = client.get('/api/emails/a@icloud.com?folder=inbox&source=local').get_json()
    assert response['success'] and [item['id'] for item in response['emails']] == ['a']


def test_regular_alias_edit_preserves_managed_sources_and_custom_imap_preset(client):
    response = client.put(f'/api/accounts/{client.mailbox_id}/aliases', json={'aliases': ['manual@example.com']})
    assert response.get_json()['success']
    with web.app.app_context():
        assert web.get_account_by_email('a@icloud.com')['icloud_address'] == 'a@icloud.com'
        assert web.get_account_by_email('manual@example.com')['matched_alias'] == 'manual@example.com'
        assert web.get_provider_meta('icloud')['imap_host'] == 'imap.mail.me.com'
        assert [web.infer_provider_from_email('x@' + domain) for domain in ('icloud.com', 'me.com', 'mac.com')] == ['icloud'] * 3
        assert web.normalize_provider('custom', 'x@icloud.com') == 'custom'
    details = client.get(f'/api/accounts/{client.mailbox_id}').get_json()['account']
    assert set(details['managed_aliases']) == {'a@icloud.com', 'b@icloud.com'}
    response = client.delete(f'/api/icloud/accounts/{client.main_id}', json={'confirm': True})
    assert response.get_json()['success']
    with web.app.app_context():
        assert web.get_account_by_id(client.mailbox_id)
        assert web.get_account_by_email('manual@example.com')


def test_project_history_does_not_restore_eligibility_after_unbinding(client):
    with web.app.app_context():
        web.start_project('icloud-project', use_alias_email=True, use_alias_email_provided=True)
        db = web.get_db()
        before = list(db.execute('SELECT normalized_email FROM project_accounts'))
        assert {row[0] for row in before} == {'a@icloud.com', 'b@icloud.com'}
        web.icloud_store().save_account({'mailbox_account_id': None}, client.main_id)
        assert web.claim_project_account('icloud-project', 'worker', 'task') is None
        assert db.execute('SELECT COUNT(*) FROM project_accounts').fetchone()[0] == 2
        assert not db.execute('SELECT 1 FROM account_aliases WHERE icloud_alias_id IS NOT NULL').fetchone()


def test_removed_managed_address_cannot_be_imported_as_an_unfiltered_primary(client):
    with web.app.app_context():
        web.icloud_store().save_account({'mailbox_account_id': None}, client.main_id)
        assert not web.add_account('a@icloud.com', '', '', '', account_type='imap', provider='icloud', imap_password='app-password')
    assert client.get('/api/emails/a@icloud.com').status_code == 404


def test_preexisting_manual_alias_conflict_keeps_manual_ownership(client):
    with web.app.app_context():
        db = web.get_db()
        db.execute('INSERT INTO account_aliases(account_id,alias_email) VALUES (?,?)', (client.mailbox_id, 'manual@icloud.com'))
        db.commit()
        store = web.icloud_store()
        store.sync(client.main_id, DirectorySnapshot('web', (HiddenAddress('conflict', 'manual@icloud.com', 'receiver@icloud.com', True),), True))
        account = web.get_account_by_email('manual@icloud.com')
        assert account['id'] == client.mailbox_id and not account.get('icloud_address')


def test_only_icloud_can_start_scheduler_when_other_features_are_disabled(client, monkeypatch):
    import apscheduler.schedulers.background
    import threading
    import time
    class Scheduler:
        def __init__(self, **kwargs): self.jobs = {}; self.started = False
        def get_job(self, id): return self.jobs.get(id)
        def remove_job(self, id): self.jobs.pop(id)
        def add_job(self, func=None, trigger=None, **kwargs): self.jobs[kwargs['id']] = kwargs
        def start(self): self.started = True
        def shutdown(self, **kwargs): pass
    monkeypatch.setattr(apscheduler.schedulers.background, 'BackgroundScheduler', Scheduler)
    monkeypatch.setattr(web, 'scheduler_instance', None)
    monkeypatch.setattr(web.icloud_manager, 'scheduler', None)
    monkeypatch.setattr(web.icloud_manager, 'stopped', threading.Event())
    monkeypatch.setattr(web.icloud_manager, 'epoch', web.icloud_manager.epoch)
    # This case uses real planning; other route tests suppress it to stay local.
    monkeypatch.setattr(web.icloud_manager, 'schedule', type(web.icloud_manager).schedule.__get__(web.icloud_manager))
    with web.app.app_context():
        web.set_setting('enable_scheduled_refresh', 'false')
        store = web.icloud_store()
        row = store.session(client.main_id, 'web')
        store.save_session(client.main_id, 'web', 1, row['revision'], {'state': 'connected'},
                           state='connected', mode='renew', next_attempt=time.time() + 600)
    try:
        scheduler = web.init_scheduler()
        assert scheduler.started
        assert set(scheduler.jobs) == {f'icloud:{client.main_id}:web'}
    finally:
        web.shutdown_scheduler()
