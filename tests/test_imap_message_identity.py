"""IMAP message identity must survive EXPUNGE and never change ID namespaces."""

import importlib
import os
import tempfile
from email.message import EmailMessage
from email.policy import SMTP

import pytest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DATABASE_PATH', os.path.join(tempfile.mkdtemp(prefix='imap-identity-import-'), 'test.db'))
mail_app = importlib.import_module('web_outlook_app')


class Mailbox:
    def __init__(self, uids=(101, 102, 103), search_ok=False):
        self.messages = []
        self.search_ok = search_ok
        self.validity = 77
        self.include_uid = True
        self.uid_fetch_ok = True
        self.fetches = []
        self.stores = []
        self.expunge_log = []
        for uid, subject in zip(uids, ('Mail A', 'Mail B', 'Mail C')):
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = 'sender@example.com'
            msg['To'] = 'identity@aliyun.com'
            msg['Date'] = 'Tue, 20 Oct 2026 12:00:00 +0000'
            msg['Message-ID'] = f'<fixture-{uid}@example.com>'
            msg.set_content(f'Body of {subject}')
            msg.add_attachment(subject.encode(), maintype='application', subtype='octet-stream', filename=subject + '.txt')
            self.messages.append({'uid': uid, 'subject': subject, 'raw': msg.as_bytes(policy=SMTP), 'deleted': False})

    def remove(self, uid):
        self.messages[:] = [msg for msg in self.messages if msg['uid'] != uid]


class Connection:
    def __init__(self, box):
        self.box = box
        self.untagged_responses = {}

    def login(self, *args):
        return 'OK', []

    def authenticate(self, *args):
        return 'OK', []

    def xatom(self, *args):
        return 'OK', []

    def list(self):
        return 'OK', [b'(\\HasNoChildren) "/" "INBOX"']

    def select(self, folder, readonly=True):
        if folder.strip('"') != 'INBOX':
            return 'NO', [b'folder missing']
        self.untagged_responses['UIDVALIDITY'] = [str(self.box.validity).encode()]
        return 'OK', [str(len(self.box.messages)).encode()]

    def search(self, *args):
        if self.box.search_ok:
            return 'OK', [b' '.join(str(seq).encode() for seq in range(1, len(self.box.messages) + 1))]
        return 'BAD', [b'SEARCH rejected']

    def uid(self, command, *args):
        if command == 'SEARCH':
            if not self.box.search_ok:
                return 'BAD', [b'UID SEARCH rejected']
            return 'OK', [b' '.join(str(msg['uid']).encode() for msg in self.box.messages)]
        if command == 'FETCH':
            if not self.box.uid_fetch_ok:
                return 'BAD', [b'UID FETCH rejected']
            return self._fetch(*args, by_uid=True)
        if command == 'STORE':
            return self._store(*args, by_uid=True)
        return 'BAD', []

    def fetch(self, *args):
        return self._fetch(*args)

    def _fetch(self, identifiers, query, by_uid=False):
        ids = identifiers.decode() if isinstance(identifiers, bytes) else str(identifiers)
        self.box.fetches.append(('uid' if by_uid else 'sequence', ids, query))
        wanted = set(ids.split(','))
        result = []
        for seq, msg in enumerate(self.box.messages, 1):
            if str(msg['uid'] if by_uid else seq) not in wanted:
                continue
            uid_field = f'UID {msg["uid"]} ' if self.box.include_uid else ''
            if query == '(UID)':
                result.append(f'{seq} ({uid_field.strip()})'.encode())
                continue
            if 'HEADER' in query:
                payload = msg['raw'].split(b'\r\n\r\n', 1)[0] + b'\r\n\r\n'
                meta = (f'{seq} ({uid_field}FLAGS () INTERNALDATE "20-Oct-2026 12:00:00 +0000" '
                        f'BODY[HEADER] {{{len(payload)}}}').encode()
            else:
                payload = msg['raw']
                meta = f'{seq} ({uid_field}RFC822 {{{len(payload)}}}'.encode()
            result.extend([(meta, payload), b')'])
        return 'OK', result or [None]

    def store(self, *args):
        return self._store(*args)

    def _store(self, identifier, action, flags, by_uid=False):
        self.box.stores.append(('uid' if by_uid else 'sequence', str(identifier)))
        for seq, msg in enumerate(self.box.messages, 1):
            if str(msg['uid'] if by_uid else seq) == str(identifier) and 'Deleted' in flags:
                msg['deleted'] = True
        return 'OK', []

    def expunge(self):
        self.box.expunge_log.extend(msg['subject'] for msg in self.box.messages if msg['deleted'])
        self.box.messages[:] = [msg for msg in self.box.messages if not msg['deleted']]
        return 'OK', []

    def logout(self):
        return 'BYE', []


@pytest.fixture
def mailbox_api(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_app, 'DATABASE', str(tmp_path / 'identity.db'))
    monkeypatch.setitem(mail_app.app.config, 'TESTING', True)
    monkeypatch.setitem(mail_app.app.config, 'WTF_CSRF_ENABLED', False)
    mail_app.clear_normal_mail_local_retention_enabled_cache()
    with mail_app.app.app_context():
        mail_app.init_db()
        mail_app.add_account('identity@aliyun.com', '', account_type='imap', provider='aliyun',
                             imap_host='imap.aliyun.com', imap_password='fixture-password')
    box = Mailbox()
    monkeypatch.setattr(mail_app, 'create_imap_connection', lambda *args, **kwargs: Connection(box))
    client = mail_app.app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
    yield box, client
    mail_app.clear_normal_mail_local_retention_enabled_cache()


def listed_b(client):
    result = client.get('/api/emails/identity@aliyun.com?folder=inbox&prefer_local=0').get_json()
    assert result['success'], result
    return next(item for item in result['emails'] if item['subject'] == 'Mail B')


def detail(client, item, suffix=''):
    return client.get(f'/api/email/identity@aliyun.com/{item["id"]}{suffix}'
                      f'?method=imap&folder=inbox&id_mode={item["id_mode"]}&prefer_local=0')


def action(client, item, operation='delete'):
    return client.post('/api/emails/' + operation, json={
        'email': 'identity@aliyun.com', 'method': 'imap', 'folder': 'inbox',
        'items': [{'id': item['id'], 'id_mode': item['id_mode'], 'folder': 'inbox'}],
    }).get_json()


def test_sequence_pagination_returns_uid_with_mailbox_generation(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    assert item['id_mode'] == 'uid'
    assert item['id'] == 'imap:77:102'
    assert any(mode == 'sequence' and 'HEADER' in query for mode, _, query in box.fetches)


def test_detail_and_raw_survive_expunge_of_an_earlier_message(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    box.remove(101)
    result = detail(client, item).get_json()
    assert result['success'], result
    assert result['email']['subject'] == 'Mail B'
    raw = detail(client, item, '/raw').get_json()
    assert raw['success'] and 'Subject: Mail B' in raw['raw']


def test_deleted_uid_is_not_reinterpreted_as_a_sequence(mailbox_api):
    box, client = mailbox_api
    box.search_ok = True
    item = listed_b(client)
    box.remove(102)
    box.fetches.clear()
    result = detail(client, item).get_json()
    assert not result['success']
    assert result['error']['code'] == 'EMAIL_NOT_FOUND'
    assert all(mode == 'uid' for mode, _, _ in box.fetches)


@pytest.mark.parametrize('operation', ['delete', 'mark-read'])
def test_stale_sequence_actions_are_rejected_without_writing(mailbox_api, operation):
    box, client = mailbox_api
    box.remove(101)
    result = action(client, {'id': '2', 'id_mode': 'sequence'}, operation)
    assert not result['success']
    assert box.stores == [] and box.expunge_log == []


@pytest.mark.parametrize('operation', ['delete', 'mark-read'])
def test_uid_actions_target_the_original_message_after_expunge(mailbox_api, operation):
    box, client = mailbox_api
    item = listed_b(client)
    box.remove(101)
    result = action(client, item, operation)
    assert result['success'], result
    assert box.expunge_log == (['Mail B'] if operation == 'delete' else [])
    assert box.stores == [('uid', '102')]


def test_deleted_target_does_not_store_or_expunge_other_messages(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    box.remove(102)
    result = action(client, item)
    assert not result['success']
    assert box.stores == [] and box.expunge_log == []


def test_attachment_uses_the_same_stable_identity_as_its_detail(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    before = detail(client, item).get_json()
    assert before['success'], before
    attachment_id = before['email']['attachments'][0]['id']
    box.remove(101)
    response = detail(client, item, '/attachments/' + attachment_id)
    assert response.status_code == 200
    assert response.data == b'Mail B'


def test_mailbox_uidvalidity_change_rejects_old_reads_and_writes(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    box.validity = 78
    box.fetches.clear()
    result = detail(client, item).get_json()
    assert not result['success']
    assert result['error']['code'] == 'IMAP_MESSAGE_ID_EXPIRED'
    assert not action(client, item)['success']
    assert box.fetches == [] and box.stores == [] and box.expunge_log == []


def test_uid_fetch_rejection_never_falls_back_to_an_unverified_sequence(mailbox_api):
    box, client = mailbox_api
    item = listed_b(client)
    box.uid_fetch_ok = False
    box.fetches.clear()
    assert not detail(client, item).get_json()['success']
    assert not action(client, item)['success']
    assert box.stores == [] and box.expunge_log == []
    assert box.fetches == []


def test_list_missing_uid_fails_instead_of_exposing_a_sequence(mailbox_api):
    box, client = mailbox_api
    box.include_uid = False
    result = client.get('/api/emails/identity@aliyun.com?folder=inbox').get_json()
    assert not result['success']


def test_legacy_sequence_detail_is_rejected_even_if_a_numeric_uid_exists(mailbox_api):
    box, client = mailbox_api
    box.messages[0]['uid'] = 2
    result = detail(client, {'id': '2', 'id_mode': 'sequence'}).get_json()
    assert not result['success']
    assert result['error']['code'] == 'IMAP_MESSAGE_ID_EXPIRED'
    assert box.fetches == []


def test_oauth_imap_uses_stable_uids_for_list_detail_and_raw(mailbox_api, monkeypatch):
    box, _client = mailbox_api
    box.search_ok = True
    monkeypatch.setattr(mail_app, 'get_access_token_imap_result',
                        lambda *args: {'success': True, 'access_token': 'fixture-token'})
    monkeypatch.setattr(mail_app.imaplib, 'IMAP4_SSL', lambda *args, **kwargs: Connection(box))
    listing = mail_app.get_emails_imap_with_server('reader@outlook.com', 'client', 'refresh')
    assert listing['success'], listing
    item = next(item for item in listing['emails'] if item['subject'] == 'Mail B')
    assert item['id'] == 'imap:77:102' and item['id_mode'] == 'uid'
    box.remove(101)
    result = mail_app.get_email_detail_imap_result('reader@outlook.com', 'client', 'refresh', item['id'])
    assert result['success'] and result['email']['subject'] == 'Mail B'
    raw = mail_app.get_raw_email_imap('reader@outlook.com', 'client', 'refresh', item['id'])
    assert b'Subject: Mail B' in raw


def test_uid_response_must_match_the_requested_identity(mailbox_api, monkeypatch):
    box, client = mailbox_api
    item = listed_b(client)
    original = Connection.uid

    def wrong_uid(connection, command, *args):
        status, data = original(connection, command, *args)
        if command == 'FETCH':
            data = [(entry[0].replace(b'UID 102', b'UID 999'), entry[1]) if isinstance(entry, tuple) else entry
                    for entry in data]
        return status, data

    monkeypatch.setattr(Connection, 'uid', wrong_uid)
    result = detail(client, item).get_json()
    assert not result['success']
    assert result['error']['code'] == 'IMAP_MESSAGE_ID_EXPIRED'


def test_new_generation_does_not_overwrite_retained_old_generation(mailbox_api):
    box, client = mailbox_api
    mail_app.set_normal_mail_local_retention_enabled_cache(True)
    old = listed_b(client)
    assert detail(client, old).get_json()['email']['subject'] == 'Mail B'
    box.validity = 78
    box.messages[1]['subject'] = 'Replacement B'
    box.messages[1]['raw'] = box.messages[1]['raw'].replace(b'Mail B', b'Replacement B')
    listing = client.get('/api/emails/identity@aliyun.com?folder=inbox&prefer_local=0').get_json()
    new = next(item for item in listing['emails'] if item['subject'] == 'Replacement B')
    assert new['id'] != old['id']
    with mail_app.app.app_context():
        rows = mail_app.get_db().execute(
            'SELECT provider_message_id, subject FROM retained_normal_mail_messages '
            'WHERE provider_message_id IN (?, ?)', (old['id'], new['id'])
        ).fetchall()
        assert {row['provider_message_id']: row['subject'] for row in rows} == {
            old['id']: 'Mail B', new['id']: 'Replacement B',
        }


def test_startup_invalidates_unsafe_legacy_imap_cache_only_once(mailbox_api):
    _box, _client = mailbox_api
    with mail_app.app.app_context():
        db = mail_app.get_db()
        account = mail_app.get_account_by_email('identity@aliyun.com')
        for identifier, mode in [('2', 'sequence'), ('102', 'uid'), ('graph-id', 'graph'), ('imap:77:102', 'uid')]:
            db.execute('INSERT INTO retained_normal_mail_messages '
                       '(account_id, folder, provider_message_id, id_mode, body, body_cached) '
                       'VALUES (?, ?, ?, ?, ?, 1)',
                       (account['id'], 'inbox', identifier, mode, 'preserved original body'))
        db.execute("DELETE FROM settings WHERE key = 'imap_uid_identity_cache_migrated'")
        db.commit()
        mail_app.init_db()
        rows = db.execute('SELECT provider_message_id, list_cached, body_cached, body '
                          'FROM retained_normal_mail_messages').fetchall()
        assert {row[0] for row in rows if row[1] or row[2]} == {'graph-id', 'imap:77:102'}
        assert all(row[3] == 'preserved original body' for row in rows)
        db.execute("UPDATE retained_normal_mail_messages SET list_cached=1, body_cached=1, body='rebuilt' "
                   "WHERE provider_message_id='102'")
        db.commit()
        mail_app.init_db()
        assert db.execute('SELECT COUNT(*) FROM retained_normal_mail_messages').fetchone()[0] == 4
        assert tuple(db.execute("SELECT list_cached, body_cached, body FROM retained_normal_mail_messages "
                                "WHERE provider_message_id='102'").fetchone()) == (1, 1, 'rebuilt')
