import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from email.message import EmailMessage
from unittest.mock import patch

import pytest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DATABASE_PATH', os.path.join(tempfile.mkdtemp(prefix='imap-batch-tests-'), 'test.db'))
mail_app = importlib.import_module('web_outlook_app')


class BatchMail:
    def __init__(self, reject_batch=False):
        self.calls = []
        self.reject_batch = reject_batch
        self.logged_out = False

    def login(self, *_args):
        return 'OK', []

    def authenticate(self, *_args):
        return 'OK', []

    def xatom(self, *_args):
        return 'OK', []

    def select(self, *_args, **_kwargs):
        return 'OK', [b'20']

    def search(self, *_args):
        return 'OK', [b' '.join(str(i).encode() for i in range(1, 21))]

    def uid(self, command, *args):
        if command == 'SEARCH':
            return 'OK', [b' '.join(str(i).encode() for i in range(101, 121))]
        return self.fetch(*args, uid=True)

    def fetch(self, message_set, query, uid=False):
        message_set = message_set.decode() if isinstance(message_set, bytes) else str(message_set)
        self.calls.append((message_set, query, uid))
        if self.reject_batch and ',' in message_set:
            return 'BAD', [b'message sets unsupported']
        data = []
        for identifier in reversed(message_set.split(',')):
            sequence = int(identifier) - 100 if uid else int(identifier)
            header = (
                f'Subject: Message {identifier}\r\n'
                'From: sender@example.com\r\n'
                'To: reader@example.com\r\n'
                'Cc: copy@example.com\r\n'
                'Delivered-To: hidden@example.com\r\n'
                '\r\n'
            ).encode()
            structure = b'("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 5000000 10)'
            if sequence == 20:
                structure = (b'(("TEXT" "PLAIN" NIL NIL NIL "7BIT" 30 1)'
                             b'("APPLICATION" "PDF" ("NAME" "report.pdf") NIL NIL "BASE64" 5000000'
                             b' NIL ("ATTACHMENT" ("FILENAME" "report.pdf"))) "MIXED")')
            metadata = (
                f'{sequence} (UID {sequence + 100} INTERNALDATE "14-Apr-2026 10:00:00 +0000" '
            ).encode() + b'BODYSTRUCTURE ' + structure + f' BODY[HEADER] {{{len(header)}}}'.encode()
            data.extend([(metadata, header), b' FLAGS (\\Seen))' if sequence == 20 else b' FLAGS ())'])
        return 'OK', data

    def logout(self):
        self.logged_out = True
        return 'BYE', []


def fetch_generic(mail, **kwargs):
    with patch.object(mail_app, 'create_imap_connection', return_value=mail):
        return mail_app.get_emails_imap_generic('reader@example.com', 'app-password', 'imap.example.com', **kwargs)


def test_list_batches_headers_without_downloading_bodies(caplog):
    mail = BatchMail()
    with caplog.at_level('INFO'):
        result = fetch_generic(mail)

    assert result['success']
    assert len(result['emails']) == 20
    assert len(mail.calls) == 1
    assert 'BODY.PEEK[HEADER]' in mail.calls[0][1]
    assert 'BODYSTRUCTURE' in mail.calls[0][1]
    assert 'RFC822)' not in mail.calls[0][1]
    assert 'BODY.PEEK[]' not in mail.calls[0][1]
    latest = next(item for item in result['emails'] if item['id'] == '120')
    assert latest['is_read'] is True
    assert latest['has_attachments'] is True
    assert latest['body_preview'] == ''
    assert latest['recipient_headers']['Delivered-To'] == ['hidden@example.com']
    assert next(item for item in result['emails'] if item['id'] == '119')['has_attachments'] is False
    assert mail.logged_out
    for stage in ['connect', 'login', 'select', 'search', 'fetch', 'parse', 'logout', 'total']:
        assert f'stage={stage} ' in caplog.text
    assert 'fetch_commands=1' in caplog.text
    assert 'app-password' not in caplog.text


def test_pagination_fetches_only_requested_uids():
    mail = BatchMail()
    result = fetch_generic(mail, skip=5, top=3)
    assert result['success']
    assert {item['id'] for item in result['emails']} == {'113', '114', '115'}
    assert result['has_more'] is True
    assert mail.calls[0][0] == '115,114,113'


def test_outlook_sequence_list_uses_same_header_batch():
    mail = BatchMail()
    with patch.object(mail_app, 'get_access_token_imap_result', return_value={'success': True, 'access_token': 'token'}), \
         patch.object(mail_app.imaplib, 'IMAP4_SSL', return_value=mail):
        result = mail_app.get_emails_imap_with_server('reader@outlook.com', 'client', 'refresh', top=3)
    assert result['success']
    assert {item['id'] for item in result['emails']} == {'18', '19', '20'}
    assert all(item['id_mode'] == 'sequence' for item in result['emails'])
    assert len(mail.calls) == 1
    assert mail.calls[0][2] is False
    assert 'BODY.PEEK[HEADER]' in mail.calls[0][1]


def test_rejected_batch_falls_back_to_headers_only():
    mail = BatchMail(reject_batch=True)
    result = fetch_generic(mail, top=3)
    assert result['success']
    assert {item['id'] for item in result['emails']} == {'118', '119', '120'}
    assert len(mail.calls) == 4
    assert all('BODY.PEEK[HEADER]' in query for _, query, _ in mail.calls)


def test_timeout_does_not_retry_each_message(caplog):
    mail = BatchMail()
    with patch.object(mail, 'fetch', side_effect=TimeoutError('private error text')), caplog.at_level('INFO'):
        result = fetch_generic(mail)
    assert not result['success']
    assert 'stage=fetch ' in caplog.text
    assert 'error_type=TimeoutError' in caplog.text
    assert 'stage=total ' in caplog.text
    assert mail.logged_out


def test_list_does_not_trigger_detail_fetch():
    with patch.object(mail_app, 'get_email_detail_imap_generic_result') as detail:
        assert fetch_generic(BatchMail())['success']
    detail.assert_not_called()


def test_body_is_available_when_detail_is_requested(caplog):
    message = EmailMessage()
    message['Subject'] = 'Body on demand'
    message.set_content('Private message body')
    message.add_attachment(b'pdf-content', maintype='application', subtype='pdf', filename='report.pdf')
    mail = BatchMail()
    with patch.object(mail, 'uid', return_value=('OK', [(b'20 (UID 120 RFC822 {100}', message.as_bytes())])) as fetch, \
         patch.object(mail_app, 'create_imap_connection', return_value=mail), caplog.at_level('INFO'):
        result = mail_app.get_email_detail_imap_generic_result(
            'reader@example.com', 'app-password', 'imap.example.com', message_id='120', strict_id_mode=True,
        )
    assert result['success']
    assert 'Private message body' in result['email']['body']
    assert result['email']['attachments'][0]['name'] == 'report.pdf'
    fetch.assert_called_once_with('FETCH', '120', '(RFC822)')
    assert 'operation=detail' in caplog.text
    assert 'stage=parse ' in caplog.text
    assert 'Private message body' not in caplog.text
    assert mail.logged_out


@pytest.mark.parametrize('failure', [mail_app.imaplib.IMAP4.error('UID command error: BAD [unsupported]'),
                                   mail_app.imaplib.IMAP4.abort('connection closed')])
def test_protocol_rejection_can_fallback_but_disconnect_cannot(failure):
    mail = BatchMail()
    original = mail.fetch
    def fetch(*args, **kwargs):
        if ',' in args[0].decode():
            raise failure
        return original(*args, **kwargs)
    with patch.object(mail, 'fetch', side_effect=fetch):
        result = fetch_generic(mail, top=2)
    assert result['success'] is not isinstance(failure, mail_app.imaplib.IMAP4.abort)
    assert len(mail.calls) == (0 if isinstance(failure, mail_app.imaplib.IMAP4.abort) else 2)


def test_uid_list_ignores_missing_and_unsolicited_identifiers():
    mail = BatchMail()
    original = mail.fetch
    def fetch(*args, **kwargs):
        status, data = original(*args, **kwargs)
        data[0] = (data[0][0].replace(b'UID 120', b'UID 999'), data[0][1])
        data.extend([(b'88 (BODY[HEADER] {5}', b'Subject: unverified\r\n\r\n'), b')'])
        return status, data
    with patch.object(mail, 'fetch', side_effect=fetch):
        result = fetch_generic(mail, top=1)
    assert result['success']
    assert result['emails'] == []


def test_bodystructure_literal_filename_is_not_mistaken_for_headers():
    data = [
        (b'1 (UID 101 BODYSTRUCTURE ("APPLICATION" "PDF" ("NAME" {10}', b'report.pdf'),
        (b') NIL NIL "BASE64" 5000000) FLAGS () BODY[HEADER] {21}', b'Subject: attachment\r\n\r\n'),
        b')',
    ]
    items = mail_app.parse_imap_list_fetch_data(data, 'uid')
    assert len(items) == 1
    assert items[0]['subject'] == 'attachment'
    assert items[0]['has_attachments'] is True


def test_accepting_new_rows_preserves_preview_without_fetching_bodies():
    source = Path(__file__).resolve().parents[1].joinpath('static/js/index/05-emails.js').read_text()
    script = source + """
const assert = require('node:assert/strict');
let currentFolder = 'inbox', currentAccount = 'reader@example.com';
let currentEmails = [{id: '1', id_mode: 'uid', body_preview: 'Cached preview'}];
let currentMethod = 'imap', hasMoreEmails = false, currentSkip = 0, isTempEmailGroup = false;
const requests = [];
global.fetch = (...args) => { requests.push(args); return Promise.resolve({ok: true}); };
global.document = {getElementById: () => null};
getEmailListMethodMetadata = () => ({method: 'imap', remoteMethod: 'imap', methodLabel: 'IMAP'});
collectNewlySyncedEmailRows = (data, merged) => merged.newEmails;
for (const name of ['markNewlySyncedEmailRows', 'cacheEmailListResponse', 'updateEmailListHeader',
                    'renderEmailList', 'scheduleEmailListLoadCheck', 'scheduleNewEmailHighlightClear', 'hideNewMailNotice']) {
    eval(name + ' = () => {};');
}
pendingNewMailSyncs.set('key', {cacheKey: 'key', options: {folder: 'inbox'}, data: {emails: [
    {id: '1', id_mode: 'uid', body_preview: '', is_read: true},
    {id: '2', id_mode: 'uid', body_preview: ''}
]}});
assert.equal(applyPendingNewMailSync('key'), true);
assert.equal(currentEmails.length, 2);
assert.equal(currentEmails[0].body_preview, 'Cached preview');
assert.equal(currentEmails[0].is_read, true);
assert.equal(requests.length, 0);
console.log(JSON.stringify({rows: currentEmails.length, requests: requests.length}));
"""
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {'rows': 2, 'requests': 0}
