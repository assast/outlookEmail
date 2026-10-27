import sqlite3
import threading

import pytest
from cryptography.fernet import Fernet

from outlook_web import icloud_manager as module
from outlook_web.icloud_manager import ICloudManager
from outlook_web.icloud_protocol import AppleProtocolError, DirectorySnapshot, HiddenAddress
from outlook_web.icloud_store import init_icloud_schema, ManagedAddressUnavailable


class FakeClient:
    failure = None
    before_return = None
    mutations = []
    directory_result = DirectorySnapshot('web', (), True)
    def __init__(self, apple_id, region, channel, snapshot=None, proxy='', cancelled=lambda: False):
        self.cancelled = cancelled
        self.state = (snapshot or {}).get('state', 'signed_out')
        self.expires_at = None
    def check(self):
        if self.cancelled(): raise AppleProtocolError('cancelled')
    def snapshot(self): return {'state': self.state, 'token': 'synthetic-token'}
    def close(self): pass
    def renew(self):
        self.check()
        if self.failure: raise self.failure
        if self.before_return: self.before_return()
        self.state = 'connected'
        self.expires_at = 1900
    def login(self, password):
        self.check()
        if self.failure: raise self.failure
        self.state = 'verification_required'
    def verify(self, code):
        self.check()
        if self.failure: raise self.failure
        self.state = 'connected'
    def generate(self): return 'pending@icloud.com'
    def mutate(self, action, payload):
        self.check()
        self.mutations.append((action, payload))
        if self.failure: raise self.failure
        return {}
    def directory(self):
        if self.failure: raise self.failure
        return self.directory_result


@pytest.fixture
def manager(tmp_path):
    path = str(tmp_path / 'icloud.db')
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE accounts(id INTEGER PRIMARY KEY,email TEXT,status TEXT,proxy_url TEXT);
        CREATE TABLE account_aliases(id INTEGER PRIMARY KEY,account_id INTEGER,alias_email TEXT UNIQUE);
        CREATE TABLE temp_emails(id INTEGER PRIMARY KEY,email TEXT);
        INSERT INTO accounts VALUES(1,'receiver@example.com','active','');''')
    init_icloud_schema(db)
    db.commit(); db.close()
    cipher = Fernet(Fernet.generate_key())
    result = ICloudManager(path, lambda: cipher, FakeClient, clock=lambda: 1000)
    FakeClient.failure = None; FakeClient.before_return = None; FakeClient.mutations = []
    with result.store() as store:
        account = store.save_account({'apple_id': 'test@example.com', 'region': 'global', 'mailbox_account_id': 1})
    result.account_id = account['id']
    yield result
    result.stop()


def connect(manager, channel='web'):
    with manager.store() as store:
        account = store.account(manager.account_id)
        row = store.session(account['id'], channel)
        store.save_session(account['id'], channel, account['config_version'], row['revision'], {'state': 'connected'},
            state='connected', mode='renew', next_attempt=1000)


def test_renewal_persists_rotation_and_uses_independent_cadences(manager, monkeypatch):
    connect(manager)
    monkeypatch.setattr(module, 'fetch_code_response', lambda _: pytest.fail('healthy renewal must not read codes'))
    manager.perform(manager.account_id, 'web', 'renew')
    with manager.store() as store:
        row = store.session(manager.account_id, 'web')
        assert row['state'] == 'connected' and store.unseal(row['snapshot_enc'])['token'] == 'synthetic-token'
        assert row['next_attempt'] == 1720
    assert 1240 <= manager.next_renewal('account', 2000) <= 1360
    assert manager.next_renewal('account', 1100) == 1080


def test_persistent_backoff_retry_after_and_remarks_do_not_reset_state(manager):
    connect(manager)
    FakeClient.failure = AppleProtocolError('temporary_failure', 'web_validate', 503, 3600)
    with pytest.raises(AppleProtocolError): manager.perform(manager.account_id, 'web', 'renew')
    with manager.store() as store:
        before = store.session(manager.account_id, 'web')
        assert before['next_attempt'] == 4600 and before['mode'] == 'renew'
        store.save_account({'remark': 'new note'}, manager.account_id)
        store.save_account({'enabled': False}, manager.account_id)
        store.save_account({'enabled': True}, manager.account_id)
        after = store.session(manager.account_id, 'web')
        assert (after['next_attempt'], after['failures']) == (before['next_attempt'], before['failures'])


def test_manual_pause_only_relevant_credentials_resume_and_corrupt_state_is_not_used(manager):
    connect(manager)
    FakeClient.failure = AppleProtocolError('account_action_required', 'web_validate', 412)
    with pytest.raises(AppleProtocolError): manager.perform(manager.account_id, 'web', 'renew')
    with manager.store() as store:
        store.save_account({'remark': 'note'}, manager.account_id)
        assert store.session(manager.account_id, 'web')['state'] == 'manual_required'
        store.save_account({'password': 'new password'}, manager.account_id)
        assert store.session(manager.account_id, 'web')['state'] == 'signed_out'
        store.db.execute("UPDATE icloud_sessions SET snapshot_enc='enc:broken' WHERE account_id=? AND channel='web'", (manager.account_id,))
        store.db.commit()
    with pytest.raises(ValueError, match='无法解密'): manager._load(manager.account_id, 'web')
    with manager.store() as store:
        assert store.session(manager.account_id, 'web')['state'] == 'manual_required'


@pytest.mark.parametrize('channel', ['web', 'account'])
def test_manual_login_replaces_unreadable_snapshot_and_completes_verification(manager, monkeypatch, channel):
    other_channel = 'account' if channel == 'web' else 'web'
    connect(manager, other_channel)
    snapshots = []

    def factory(*args, **kwargs):
        snapshots.append(kwargs['snapshot'])
        return FakeClient(*args, **kwargs)

    monkeypatch.setattr(manager, 'client_factory', factory)
    with manager.store() as store:
        store.db.execute("UPDATE icloud_sessions SET snapshot_enc='enc:broken' WHERE account_id=? AND channel=?",
                         (manager.account_id, channel))
        store.db.commit()
        store.save_account({'password': 'new password'}, manager.account_id)
        store.takeover(manager.account_id)
        other_before = store.session(manager.account_id, other_channel)
    assert manager.perform(manager.account_id, channel, 'login', password='new password') == 'verification_required'
    assert snapshots == [None]
    assert manager.perform(manager.account_id, channel, 'verify', code='123456') == 'connected'
    with manager.store() as store:
        row = store.session(manager.account_id, channel)
        assert row['state'] == 'connected' and row['last_error'] == ''
        assert store.unseal(row['snapshot_enc'])['state'] == 'connected'
        assert store.session(manager.account_id, other_channel) == other_before


@pytest.mark.parametrize('channel', ['web', 'account'])
@pytest.mark.parametrize('action', ['renew', 'verify'])
def test_unreadable_snapshot_still_blocks_renewal_and_verification(manager, monkeypatch, channel, action):
    with manager.store() as store:
        store.db.execute("UPDATE icloud_sessions SET snapshot_enc='enc:broken' WHERE account_id=? AND channel=?",
                         (manager.account_id, channel))
        store.db.commit()
    monkeypatch.setattr(manager, 'client_factory', lambda *args, **kwargs: pytest.fail('unreadable session must not reach Apple'))
    with pytest.raises(ValueError, match='无法解密'):
        manager.perform(manager.account_id, channel, action, code='123456')
    with manager.store() as store:
        row = store.session(manager.account_id, channel)
        assert row['state'] == 'manual_required' and row['last_error'] == 'configuration_required'
        assert row['snapshot_enc'] == 'enc:broken'


def test_manual_takeover_and_shutdown_reject_late_network_results_without_write_lock(manager):
    connect(manager)
    def takeover():
        # Runs during the simulated network request using a different SQLite connection.
        with manager.store() as store: store.takeover(manager.account_id)
    FakeClient.before_return = staticmethod(takeover)
    with pytest.raises(AppleProtocolError, match='cancelled'): manager.perform(manager.account_id, 'web', 'renew')
    with manager.store() as store:
        assert store.unseal(store.session(manager.account_id, 'web')['snapshot_enc']) == {'state': 'connected'}
    FakeClient.before_return = staticmethod(manager.stop)
    with pytest.raises(AppleProtocolError, match='cancelled'): manager.perform(manager.account_id, 'web', 'renew')


def test_automatic_wait_releases_lock_and_manual_takeover_prevents_code_submission(manager, monkeypatch):
    with manager.store() as store:
        store.save_account({'password': ' password ', 'code_url': 'https://code.example/', 'auto_login': True}, manager.account_id)
    reads = []
    monkeypatch.setattr(module, 'fetch_code_response', lambda url: reads.append(url) or '验证码:123456')
    original_wait = manager.stopped.wait
    def wait(seconds):
        assert seconds == 5
        assert manager.lock(manager.account_id).acquire(blocking=False)
        manager.lock(manager.account_id).release()
        with manager.store() as store: store.takeover(manager.account_id, logout=True)
        return False
    monkeypatch.setattr(manager.stopped, 'wait', wait)
    with pytest.raises(AppleProtocolError, match='cancelled'): manager.auto_login(manager.account_id, 'web')
    assert len(reads) == 1
    with manager.store() as store: assert store.session(manager.account_id, 'web')['state'] == 'signed_out'


def test_automatic_old_code_polls_at_most_18_times_and_persists_login_backoff(manager, monkeypatch):
    with manager.store() as store:
        store.save_account({'password': 'password', 'code_url': 'https://code.example/', 'auto_login': True}, manager.account_id)
    reads = []
    monkeypatch.setattr(module, 'fetch_code_response', lambda _: reads.append(1) or '验证码:123456')
    monkeypatch.setattr(manager.stopped, 'wait', lambda seconds: False)
    with pytest.raises(AppleProtocolError): manager.auto_login(manager.account_id, 'web')
    assert len(reads) == 19
    with manager.store() as store:
        row = store.session(manager.account_id, 'web')
        assert 1300 <= row['next_attempt'] <= 1360 and row['failures'] == 1 and row['mode'] == 'login'


def test_uncertain_reservation_is_durable_and_not_replayed_by_sync(manager):
    connect(manager)
    FakeClient.failure = AppleProtocolError('temporary_failure', 'directory')
    with pytest.raises(AppleProtocolError): manager.aliases(manager.account_id, 'create', label='label', note='note')
    assert [item[0] for item in FakeClient.mutations] == ['reserve']
    with manager.store() as store:
        alias = store.public(store.account(manager.account_id))['aliases'][0]
        assert alias['state'] == 'pending' and alias['label'] == 'label'
        with pytest.raises(ManagedAddressUnavailable): store.resolve('pending@icloud.com')
    FakeClient.failure = None
    manager.aliases(manager.account_id, 'sync')
    assert len(FakeClient.mutations) == 1
    with manager.store() as store: assert store.public(store.account(manager.account_id))['aliases'][0]['state'] == 'pending'


def test_scheduler_restores_one_shot_jobs_without_shortening_backoff(manager):
    connect(manager)
    with manager.store() as store:
        row = store.session(manager.account_id, 'web')
        store.save_session(manager.account_id, 'web', 1, row['revision'], next_attempt=5000)
    class Scheduler:
        jobs = {}
        def get_job(self, id): return self.jobs.get(id)
        def remove_job(self, id): self.jobs.pop(id)
        def add_job(self, func, trigger, **kwargs):
            assert trigger == 'date'
            self.jobs[kwargs['id']] = kwargs
    scheduler = Scheduler()
    assert manager.restore(scheduler)
    manager.schedule(manager.account_id)
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[f'icloud:{manager.account_id}:web']['run_date'].timestamp() == 5000
    manager.stop()
    assert not manager.current(manager.account_id, 1, 0)


def test_queued_old_renewal_cannot_adopt_a_new_manual_challenge(manager):
    connect(manager)
    with manager.store() as store:
        old = store.session(manager.account_id, 'web')
        account = store.takeover(manager.account_id)
        store.save_session(manager.account_id, 'web', account['config_version'], old['revision'], {'state': 'verification_required'},
                           state='verification_required', mode='login')
    with pytest.raises(AppleProtocolError, match='cancelled'):
        manager.perform(manager.account_id, 'web', 'renew', expected_version=1, expected_revision=old['revision'])
    with manager.store() as store: assert store.session(manager.account_id, 'web')['state'] == 'verification_required'


def test_dispatch_deduplicates_same_account_and_keeps_other_accounts_independent(manager, monkeypatch):
    connect(manager)
    with manager.store() as store:
        other = store.save_account({'apple_id': 'second@example.com', 'region': 'global'})
        store.save_session(other['id'], 'web', 1, 0, {'state': 'connected'}, state='connected', mode='renew', next_attempt=1000)
    entered = {manager.account_id: threading.Event(), other['id']: threading.Event()}
    release, completed = threading.Event(), threading.Event()
    calls = []
    def perform(account_id, *args, **kwargs):
        calls.append(account_id)
        entered[account_id].set()
        release.wait(2)
        if len(calls) == 2: completed.set()
    monkeypatch.setattr(manager, 'perform', perform)
    manager.dispatch(manager.account_id, 'web')
    manager.dispatch(manager.account_id, 'web')
    manager.dispatch(other['id'], 'web')
    try:
        assert all(event.wait(1) for event in entered.values())
        assert sorted(calls) == sorted(entered)
    finally:
        release.set()
        completed.wait(1)


def test_remote_lifecycle_requires_ownership_confirmation_and_retains_history(manager):
    connect(manager)
    with manager.store() as store:
        store.sync(manager.account_id, DirectorySnapshot('web', (HiddenAddress('actual-id', 'a@icloud.com', 'receiver@example.com', True),), True))
        alias_id = store.public(store.account(manager.account_id))['aliases'][0]['id']
        other = store.save_account({'apple_id': 'other@example.com', 'region': 'global'})
    with pytest.raises(ValueError, match='不属于'): manager.aliases(other['id'], 'deactivate', alias_id=alias_id)
    with pytest.raises(ValueError, match='先停用'): manager.aliases(manager.account_id, 'delete', alias_id=alias_id, confirmed=True)
    assert FakeClient.mutations == []
    manager.aliases(manager.account_id, 'deactivate', alias_id=alias_id)
    with manager.store() as store:
        assert store.alias(manager.account_id, alias_id)['state'] == 'inactive'
        with pytest.raises(ManagedAddressUnavailable): store.resolve('a@icloud.com')
    with pytest.raises(ValueError, match='明确确认'): manager.aliases(manager.account_id, 'delete', alias_id=alias_id)
    manager.aliases(manager.account_id, 'delete', alias_id=alias_id, confirmed=True)
    assert FakeClient.mutations == [('deactivate', {'anonymousId': 'actual-id'}), ('delete', {'anonymousId': 'actual-id'})]
    with manager.store() as store:
        assert store.alias(manager.account_id, alias_id)['state'] == 'removed'
        assert store.db.execute('SELECT 1 FROM accounts WHERE id=1').fetchone()


def test_successful_reservation_stores_actual_id_before_directory_catches_up(manager, monkeypatch):
    connect(manager)
    monkeypatch.setattr(FakeClient, 'mutate', lambda self, action, payload: {'hme': {'hme': 'pending@icloud.com', 'anonymousId': 'actual-reserved-id'}})
    manager.aliases(manager.account_id, 'create', label='label', note='note')
    with manager.store() as store:
        row = store.public(store.account(manager.account_id))['aliases'][0]
        assert row['remote_id'] == 'actual-reserved-id' and row['state'] == 'pending'
        assert row['pending_action'] == 'create'
