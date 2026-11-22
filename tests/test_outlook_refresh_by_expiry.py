import importlib
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
_test_database_dir = tempfile.mkdtemp(prefix='outlook-refresh-expiry-tests-')
os.environ['DATABASE_PATH'] = os.path.join(_test_database_dir, 'test.db')
web = importlib.import_module('web_outlook_app')
UTC8 = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 21, 2, 0, tzinfo=UTC8)


@pytest.fixture
def outlook_db(tmp_path):
    original_database = web.DATABASE
    web.DATABASE = str(tmp_path / 'outlook.db')
    web.init_db()
    with web.app.app_context():
        yield web.get_db()
    web.DATABASE = original_database


def _add_outlook(email, token='old-rt'):
    assert web.add_account(email, 'password', 'client-id', token)
    return web.get_account_by_email(email)


def test_due_refresh_selects_window_and_optional_unknown_anchors(outlook_db):
    due = _add_outlook('due@example.com')
    later = _add_outlook('later@example.com')
    unknown = _add_outlook('unknown@example.com')
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_expires_at = ? WHERE id = ?',
        ((NOW + timedelta(days=5)).isoformat(), due['id']),
    )
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_expires_at = ? WHERE id = ?',
        ((NOW + timedelta(days=8)).isoformat(), later['id']),
    )
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_updated_at = NULL, refresh_token_expires_at = NULL WHERE id = ?',
        (unknown['id'],),
    )
    outlook_db.execute(
        "UPDATE settings SET value = 'true' WHERE key = 'refresh_token_include_missing_anchor'"
    )
    accounts, unknown_count = web.load_due_outlook_accounts_for_refresh(outlook_db, now=NOW)
    assert {row['email'] for row in accounts} == {'due@example.com', 'unknown@example.com'}
    assert unknown_count == 1

    outlook_db.execute(
        "UPDATE settings SET value = 'false' WHERE key = 'refresh_token_include_missing_anchor'"
    )
    accounts, unknown_count = web.load_due_outlook_accounts_for_refresh(outlook_db, now=NOW)
    assert [row['email'] for row in accounts] == ['due@example.com']
    assert unknown_count == 0


def test_backfill_uses_rt_update_time_and_leaves_unknown_unknown(outlook_db):
    anchored = _add_outlook('anchored@example.com')
    unknown = _add_outlook('unknown@example.com')
    issue_at = NOW - timedelta(days=80)
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_updated_at = ?, refresh_token_expires_at = NULL WHERE id = ?',
        (issue_at.isoformat(), anchored['id']),
    )
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_updated_at = NULL, refresh_token_expires_at = NULL WHERE id = ?',
        (unknown['id'],),
    )
    result = web.backfill_refresh_token_expiry_anchors(outlook_db, default_lifetime_days=90)
    assert result == {'backfilled': 1, 'unknown': 1}
    expiry = outlook_db.execute(
        'SELECT refresh_token_expires_at FROM accounts WHERE id = ?', (anchored['id'],)
    ).fetchone()['refresh_token_expires_at']
    assert expiry == (issue_at + timedelta(days=90)).isoformat()
    assert outlook_db.execute(
        'SELECT refresh_token_expires_at FROM accounts WHERE id = ?', (unknown['id'],)
    ).fetchone()['refresh_token_expires_at'] is None


def test_settings_api_saves_expiry_window_defaults_and_unknown_policy(outlook_db):
    web.app.config['TESTING'] = True
    web.app.config['WTF_CSRF_ENABLED'] = False
    client = web.app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
    response = client.put('/api/settings', json={
        'refresh_token_expires_within_days': 9,
        'refresh_token_default_lifetime_days': 120,
        'refresh_token_include_missing_anchor': False,
    })
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success']
    with web.app.app_context():
        assert web.get_setting('refresh_token_expires_within_days') == '9'
        assert web.get_setting('refresh_token_default_lifetime_days') == '120'
        assert web.get_setting('refresh_token_include_missing_anchor') == 'false'


def test_rotated_refresh_token_saves_expiry_and_expected_token_is_checked(outlook_db):
    account = _add_outlook('rotate@example.com')
    assert web.persist_rotated_refresh_token(
        account['id'], 'new-rt', refresh_token_expires_in=3600,
        expected_refresh_token='old-rt', now=NOW,
    )
    saved = web.get_account_by_id(account['id'])
    assert saved['refresh_token'] == 'new-rt'
    assert saved['refresh_token_updated_at'] == NOW.isoformat()
    assert saved['refresh_token_expires_at'] == (NOW + timedelta(seconds=3600)).isoformat()
    assert not web.persist_rotated_refresh_token(
        account['id'], 'stale-rt', refresh_token_expires_in=3600,
        expected_refresh_token='old-rt', now=NOW,
    )
    assert web.get_account_by_id(account['id'])['refresh_token'] == 'new-rt'


def test_graph_scope_fallback_retries_same_rt_and_preserves_earlier_success(monkeypatch):
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.payload = payload
            self.text = ''

        def json(self):
            return self.payload

    post = Mock(side_effect=[
        Response(200, {'access_token': 'first-access', 'refresh_token': 'old-rt'}),
        Response(200, {'access_token': 'second-access', 'refresh_token': 'new-rt', 'refresh_token_expires_in': 3600}),
    ])
    monkeypatch.setattr(web, 'post_with_proxy_fallback', post)
    result = web.test_refresh_token('client-id', 'old-rt', authorization_type='graph')
    assert result == (True, None, 'new-rt', 'graph', 3600)
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs['data']['scope'] == 'https://graph.microsoft.com/.default'
    assert 'scope' not in post.call_args_list[1].kwargs['data']


def test_mail_token_exchange_persists_rotated_rt_and_expiry(outlook_db, monkeypatch):
    account = _add_outlook('mail-rotation@example.com')
    account.update(web.get_account_by_id(account['id']))
    monkeypatch.setattr(web, '_get_access_token_graph_result_core', Mock(return_value={
        'success': True,
        'access_token': 'access-token',
        'refresh_token': 'mail-rotated-rt',
        'refresh_token_expires_in': 7200,
    }))
    result = web.get_access_token_graph_result(
        'client-id', 'old-rt', account=account,
    )
    assert result['success']
    assert web.get_account_by_id(account['id'])['refresh_token'] == 'mail-rotated-rt'
    expiry = datetime.fromisoformat(web.get_account_by_id(account['id'])['refresh_token_expires_at'])
    assert abs((expiry - (datetime.now(UTC8) + timedelta(seconds=7200))).total_seconds()) <= 2


def test_mail_token_exchange_without_rotation_preserves_anchor(outlook_db, monkeypatch):
    account = _add_outlook('mail-no-rotation@example.com')
    original_expiry = account['refresh_token_expires_at']
    persist = Mock(wraps=web.persist_rotated_refresh_token)
    monkeypatch.setattr(web, 'persist_rotated_refresh_token', persist)
    monkeypatch.setattr(web, '_get_access_token_graph_result_core', Mock(return_value={
        'success': True,
        'access_token': 'access-token',
        'refresh_token': 'old-rt',
        'refresh_token_expires_in': 7200,
    }))
    result = web.get_access_token_graph_result(
        'client-id', 'old-rt', account=account,
    )
    assert result['success']
    persist.assert_not_called()
    assert web.get_account_by_id(account['id'])['refresh_token_expires_at'] == original_expiry


def test_imap_mail_token_exchange_persists_rotated_rt(outlook_db, monkeypatch):
    account = _add_outlook('imap-mail-rotation@example.com')
    account.update(web.get_account_by_id(account['id']))
    monkeypatch.setattr(web, '_get_access_token_imap_result_core', Mock(return_value={
        'success': True,
        'access_token': 'access-token',
        'refresh_token': 'imap-rotated-rt',
        'refresh_token_expires_in': 1800,
    }))
    result = web.get_access_token_imap_result('client-id', 'old-rt', account=account)
    assert result['success']
    saved = web.get_account_by_id(account['id'])
    assert saved['refresh_token'] == 'imap-rotated-rt'
    expiry = datetime.fromisoformat(saved['refresh_token_expires_at'])
    assert abs((expiry - (datetime.now(UTC8) + timedelta(seconds=1800))).total_seconds()) <= 2


def test_same_account_token_exchanges_are_serialized(outlook_db):
    account = _add_outlook('concurrent@example.com')
    first_account = dict(web.get_account_by_id(account['id']))
    second_account = dict(web.get_account_by_id(account['id']))
    first_entered = threading.Event()
    release_first = threading.Event()
    observed_tokens = []

    def exchange(_client_id, refresh_token, _proxy_url, _fallbacks):
        observed_tokens.append(refresh_token)
        if refresh_token == 'old-rt':
            first_entered.set()
            assert release_first.wait(timeout=5)
            next_token = 'first-rt'
        else:
            next_token = 'second-rt'
        return {
            'success': True,
            'access_token': 'access-token',
            'refresh_token': next_token,
            'refresh_token_expires_in': 3600,
        }

    def run(account_record):
        with web.app.app_context():
            return web._get_access_token_for_account(
                exchange, 'client-id', 'old-rt', '', None, account_record,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, first_account)
        assert first_entered.wait(timeout=5)
        second = executor.submit(run, second_account)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert observed_tokens == ['old-rt', 'first-rt']
    assert web.get_account_by_id(account['id'])['refresh_token'] == 'second-rt'


def test_full_refresh_keeps_manual_all_and_scheduled_due_sets_separate(outlook_db, monkeypatch):
    due = _add_outlook('due@example.com')
    later = _add_outlook('later@example.com')
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_expires_at = ? WHERE id = ?',
        ((NOW + timedelta(days=2)).isoformat(), due['id']),
    )
    outlook_db.execute(
        'UPDATE accounts SET refresh_token_expires_at = ? WHERE id = ?',
        ((NOW + timedelta(days=40)).isoformat(), later['id']),
    )
    outlook_db.execute("UPDATE settings SET value = '7' WHERE key = 'refresh_token_expires_within_days'")
    processed = []
    monkeypatch.setattr(web, 'refresh_outlook_account_token', lambda account, *_a, **_kw: (
        processed.append(account['email']) or {'success': True, 'token_rotated': False}
    ))
    due_result = web.run_full_refresh('scheduled', 'scheduled', db_conn=outlook_db, due_only=True)
    assert due_result['total'] == 1
    assert due_result['unknown_anchor_count'] == 0
    assert processed == ['due@example.com']

    processed.clear()
    manual_result = web.run_full_refresh('manual_all', 'manual', db_conn=outlook_db)
    assert manual_result['total'] == 2
    assert set(processed) == {'due@example.com', 'later@example.com'}
