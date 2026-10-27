import json
import sqlite3

import pytest
from cryptography.fernet import Fernet

from outlook_web.icloud_protocol import DirectorySnapshot, HiddenAddress
from outlook_web.icloud_store import ICloudStore, ManagedAddressUnavailable, init_icloud_schema


@pytest.fixture
def store():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''PRAGMA foreign_keys=ON;
        CREATE TABLE accounts(id INTEGER PRIMARY KEY,email TEXT,status TEXT DEFAULT 'active');
        CREATE TABLE temp_emails(id INTEGER PRIMARY KEY,email TEXT);
        CREATE TABLE account_aliases(id INTEGER PRIMARY KEY,account_id INTEGER,alias_email TEXT UNIQUE,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE);
        INSERT INTO accounts VALUES(1,'receiver@example.com','active');
        INSERT INTO account_aliases(account_id,alias_email) VALUES(1,'manual@example.com');''')
    init_icloud_schema(db)
    db.commit()
    yield ICloudStore(db, Fernet(Fernet.generate_key()))
    db.close()


def main(store, **data):
    return store.save_account(dict(apple_id='test@example.com', region='global', mailbox_account_id=1, **data))


def directory(*items):
    return DirectorySnapshot('web', tuple(HiddenAddress(remote, address, target, active) for remote, address, target, active in items), True)


def test_old_database_migration_is_idempotent_and_preserves_manual_aliases(store):
    init_icloud_schema(store.db)
    init_icloud_schema(store.db)
    assert store.db.execute('SELECT alias_email,icloud_alias_id FROM account_aliases').fetchone()[:] == ('manual@example.com', None)
    account = main(store)
    assert not account['auto_login']
    assert len(store.public(account)['sessions']) == 2
    with pytest.raises(ValueError, match='已存在'):
        main(store)
    assert store.save_account({'apple_id': 'test@example.com', 'region': 'cn'})['id'] != account['id']


def test_secret_roundtrip_preserves_spaces_and_never_appears_in_public_response(store, capsys):
    account = main(store, password=' enc: raw password ', code_url='https://code.example/?secret=token', auto_login=True)
    assert store.unseal(account['password_enc']) == ' enc: raw password '
    public = json.dumps(store.public(account))
    assert 'raw password' not in public and 'secret=token' not in public and 'enc:' not in public
    version = account['config_version']
    edited = store.save_account({'password': '', 'code_url': '', 'remark': '备注'}, account['id'])
    assert edited['password_enc'] == account['password_enc']
    assert edited['config_version'] == version
    with pytest.raises(ValueError, match='无法解密'):
        store.unseal('enc:broken-ciphertext')
    assert 'broken-ciphertext' not in capsys.readouterr().err
    with pytest.raises(ValueError, match='需要保存'):
        store.save_account({'clear_password': True}, account['id'])
    edited = store.save_account({'auto_login': False, 'clear_password': True}, account['id'])
    assert not edited['password_enc'] and edited['code_url_enc']


def test_session_compare_and_swap_rejects_stale_login_and_snapshot(store):
    account = main(store)
    assert store.save_session(account['id'], 'web', 1, 0, {'token': 'new'}, state='connected')
    assert not store.save_session(account['id'], 'web', 1, 0, {'token': 'stale'}, state='connected')
    store.takeover(account['id'])
    assert not store.save_session(account['id'], 'web', 1, 1, {'token': 'late'}, state='connected')
    row = store.session(account['id'], 'web')
    assert store.unseal(row['snapshot_enc']) == {'token': 'new'}


def test_authoritative_sync_projection_binding_and_tombstones(store):
    account = main(store)
    aliases = directory(('a', 'a@icloud.com', 'receiver@example.com', True), ('b', 'b@icloud.com', 'other@example.com', True))
    store.sync(account['id'], aliases)
    assert store.resolve('a@icloud.com')['mailbox_account_id'] == 1
    with pytest.raises(ManagedAddressUnavailable):
        store.resolve('b@icloud.com')
    with pytest.raises(ValueError, match='完整'):
        store.sync(account['id'], DirectorySnapshot('account', (), False))
    assert store.resolve('a@icloud.com')
    store.sync(account['id'], directory())
    with pytest.raises(ManagedAddressUnavailable):
        store.resolve('a@icloud.com')
    assert store.db.execute("SELECT 1 FROM account_aliases WHERE alias_email='manual@example.com'").fetchone()


@pytest.mark.parametrize('conflict', ['primary', 'manual', 'temp', 'other'])
def test_projection_never_takes_existing_ownership(store, conflict):
    account = main(store)
    if conflict == 'primary':
        store.db.execute("INSERT INTO accounts VALUES(2,'a@icloud.com','active')")
    elif conflict == 'manual':
        store.db.execute("INSERT INTO account_aliases(account_id,alias_email) VALUES(1,'a@icloud.com')")
    elif conflict == 'temp':
        store.db.execute("INSERT INTO temp_emails VALUES(1,'a@icloud.com')")
    else:
        other = store.save_account({'apple_id': 'other@example.com', 'region': 'global'})
        store.sync(other['id'], directory(('other', 'a@icloud.com', 'receiver@example.com', True)))
    store.db.commit()
    store.sync(account['id'], directory(('a', 'a@icloud.com', 'receiver@example.com', True), ('b', 'b@icloud.com', 'receiver@example.com', True)))
    assert store.public(store.account(account['id']))['aliases'][1]['conflict']
    assert store.resolve('b@icloud.com')


def test_disable_delete_and_unbind_only_remove_owned_mappings(store):
    account = main(store)
    store.sync(account['id'], directory(('a', 'a@icloud.com', 'receiver@example.com', True)))
    version = account['config_version']
    store.db.execute("UPDATE accounts SET status='disabled' WHERE id=1")
    store.db.commit()
    assert not store.allowed(store.account(account['id']))
    assert store.account(account['id'])['config_version'] > version
    with pytest.raises(ManagedAddressUnavailable):
        store.resolve('a@icloud.com')
    store.db.execute("UPDATE accounts SET status='active' WHERE id=1")
    store.db.commit()
    with store.db:
        store.project(account['id'])
    assert store.resolve('a@icloud.com')
    store.save_account({'mailbox_account_id': None}, account['id'])
    with pytest.raises(ManagedAddressUnavailable):
        store.resolve('a@icloud.com')
    assert store.allowed(store.account(account['id']))
    store.delete(account['id'])
    with pytest.raises(ManagedAddressUnavailable):
        store.resolve('a@icloud.com')
    assert store.db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM account_aliases WHERE alias_email='manual@example.com'").fetchone()[0] == 1


def test_deleted_mailbox_pauses_instead_of_guessing_another_binding(store):
    account = main(store)
    store.db.execute('DELETE FROM accounts WHERE id=1')
    store.db.commit()
    account = store.account(account['id'])
    assert account['mailbox_account_id'] is None and account['binding_lost']
    assert not store.allowed(account)


def test_downgrade_cleanup_only_removes_managed_projection(store):
    account = main(store)
    store.sync(account['id'], directory(('a', 'a@icloud.com', 'receiver@example.com', True)))
    with store.db:
        store.db.execute('UPDATE icloud_accounts SET enabled=0,config_version=config_version+1')
        store.db.execute('DELETE FROM account_aliases WHERE icloud_alias_id IS NOT NULL')
    assert [row[0] for row in store.db.execute('SELECT alias_email FROM account_aliases')] == ['manual@example.com']
    assert store.db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 1
    assert store.db.execute('SELECT COUNT(*) FROM icloud_hme_aliases').fetchone()[0] == 1
    assert not store.allowed(store.account(account['id']))
