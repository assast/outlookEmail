import importlib
import os

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
web = importlib.import_module('web_outlook_app')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'DATABASE', str(tmp_path / 'accounts.db'))
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', False)
    with web.app.app_context():
        web.init_db()
        web.set_setting(web.LOGIN_SESSION_VERSION_SETTING_KEY, web.DEFAULT_LOGIN_SESSION_VERSION)
    client = web.app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['login_session_version'] = web.DEFAULT_LOGIN_SESSION_VERSION
    return client


def add_account(email, sort_order=0, created_at='2026-01-01 00:00:00', group_id=1):
    with web.app.app_context():
        db = web.get_db()
        cursor = db.execute(
            'INSERT INTO accounts (email, sort_order, created_at, group_id) VALUES (?, ?, ?, ?)',
            (email, sort_order, created_at, group_id),
        )
        db.commit()
        return cursor.lastrowid


def account_ids(client, **params):
    data = client.get('/api/accounts', query_string=params).get_json()
    assert data['success']
    return [account['id'] for account in data['accounts']]


def move(client, account_id, target_id, position='before'):
    return client.post('/api/accounts/reorder', json={
        'account_id': account_id, 'target_id': target_id, 'position': position,
    })


def test_manual_order_survives_reinitialization_and_preserves_existing_sort_modes(client):
    a = add_account('z@example.com', 10, '2026-01-03 00:00:00')
    b = add_account('a@example.com', 20, '2026-01-02 00:00:00')
    c = add_account('c@example.com', 0, '2026-01-01 00:00:00')
    modes = [(by, order) for by in ['sort_order', 'created_at', 'email'] for order in ['asc', 'desc']]
    original = {(by, order): account_ids(client, sort_by=by, sort_order=order) for by, order in modes}
    assert account_ids(client, sort_by='manual') == [a, b, c]
    response = move(client, c, a)
    assert response.status_code == 200
    assert response.get_json()['success']
    assert account_ids(client, sort_by='manual', sort_order='desc') == [c, a, b]
    with web.app.app_context():
        web.init_db()
        assert [tuple(row) for row in web.get_db().execute('SELECT id, sort_order FROM accounts ORDER BY id')] == [(a, 10), (b, 20), (c, 0)]
    assert account_ids(client, sort_by='manual') == [c, a, b]
    for by, order in modes:
        assert account_ids(client, sort_by=by, sort_order=order) == original[(by, order)]
    assert move(client, c, b, 'after').status_code == 200
    assert account_ids(client, sort_by='manual') == [a, b, c]


def test_moves_preserve_hidden_rows_and_work_with_pagination_and_search(client):
    ids = [add_account(f'box{i}@example.com', i + 1) for i in range(6)]
    assert move(client, ids[4], ids[1]).status_code == 200
    expected = [ids[0], ids[4], ids[1], ids[2], ids[3], ids[5]]
    assert account_ids(client, sort_by='manual', limit=2) == expected[:2]
    assert account_ids(client, sort_by='manual', limit=2, offset=2) == expected[2:4]
    assert account_ids(client, sort_by='manual', limit=2, offset=4) == expected[4:]
    assert move(client, ids[0], ids[3], 'after').status_code == 200
    expected = [ids[4], ids[1], ids[2], ids[3], ids[0], ids[5]]
    assert account_ids(client, sort_by='manual') == expected
    response = client.get('/api/accounts/search', query_string={'q': 'example.com', 'sort_by': 'manual'})
    assert response.status_code == 200
    assert [a['id'] for a in response.get_json()['accounts']] == expected


def test_new_accounts_append_to_saved_manual_order(client):
    a = add_account('a@example.com', 1)
    b = add_account('b@example.com', 2)
    assert move(client, b, a).status_code == 200
    c = add_account('new@example.com', 1, '2026-02-01 00:00:00')
    assert account_ids(client, sort_by='manual') == [b, a, c]
    assert move(client, c, b).status_code == 200
    assert account_ids(client, sort_by='manual') == [c, b, a]


@pytest.mark.parametrize('body', [None, [], {}, {'account_id': True, 'target_id': 2, 'position': 'before'},
    {'account_id': '1', 'target_id': 2, 'position': 'before'},
    {'account_id': -1, 'target_id': 2, 'position': 'before'},
    {'account_id': 2**64, 'target_id': 2, 'position': 'before'},
    {'account_id': 1, 'target_id': 1, 'position': 'before'},
    {'account_id': 1, 'target_id': 2, 'position': 'sideways'}])
def test_invalid_moves_are_rejected_without_writes(client, body):
    a = add_account('a@example.com', 1)
    response = client.post('/api/accounts/reorder', json=body)
    assert response.status_code == 400
    with web.app.app_context():
        assert web.get_db().execute('SELECT manual_sort_order FROM accounts WHERE id = ?', (a,)).fetchone()[0] is None


def test_missing_target_does_not_change_order(client):
    a = add_account('a@example.com', 1)
    assert move(client, a, 999999).status_code == 400
    assert account_ids(client, sort_by='manual') == [a]
    with web.app.app_context():
        assert web.get_db().execute('SELECT manual_sort_order FROM accounts').fetchone()[0] is None


def test_reorder_requires_login_and_csrf(client, monkeypatch):
    a = add_account('a@example.com', 1)
    b = add_account('b@example.com', 2)
    anonymous = web.app.test_client()
    assert move(anonymous, a, b).status_code == 401
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_CHECK_DEFAULT', True)
    assert move(client, a, b).status_code == 400


def test_database_migration_keeps_legacy_accounts(client):
    a = add_account('legacy@example.com', 7)
    with web.app.app_context():
        db = web.get_db()
        db.execute('ALTER TABLE accounts DROP COLUMN manual_sort_order')
        db.commit()
        web.init_db()
        web.init_db()
        row = db.execute('SELECT id, sort_order, manual_sort_order FROM accounts').fetchone()
        assert tuple(row) == (a, 7, None)


def test_failed_write_rolls_back_the_entire_move(client):
    a = add_account('a@example.com', 1)
    b = add_account('b@example.com', 2)
    with web.app.app_context():
        db = web.get_db()
        db.execute("CREATE TRIGGER reject_manual_update BEFORE UPDATE OF manual_sort_order ON accounts BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        db.commit()
    assert move(client, b, a).status_code == 500
    with web.app.app_context():
        assert all(row[0] is None for row in web.get_db().execute('SELECT manual_sort_order FROM accounts'))
