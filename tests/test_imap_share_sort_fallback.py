"""Restricted IMAP shares must keep INTERNALDATE ordering without SORT."""

import re
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from test_imap_message_identity import Connection, mailbox_api, mail_app


class ShareConnection(Connection):
    def __init__(self, box):
        super().__init__(box)
        self.capabilities = box.capabilities

    def uid(self, command, *args):
        self.box.commands.append((command, *args))
        if command == 'SORT':
            if self.box.sort_error:
                raise self.box.sort_error
            return self.box.sort_status, [b'SORT unavailable']
        if command == 'SEARCH' and self.box.search_error:
            raise self.box.search_error
        if command == 'FETCH' and args[1] == '(UID INTERNALDATE)':
            self.box.elapsed += self.box.scan_delay
            wanted = str(args[0]).split(',')
            rows = []
            for seq, message in enumerate(self.box.messages, 1):
                if str(message['uid']) in wanted and message['uid'] != self.box.omitted_uid:
                    date = message.get('internaldate', '20-Oct-2026 12:00:00 +0000')
                    rows.append(f'{seq} (UID {message["uid"]} INTERNALDATE "{date}")'.encode())
            return 'OK', rows
        return super().uid(command, *args)

    def _fetch(self, *args, **kwargs):
        status, data = super()._fetch(*args, **kwargs)
        result = []
        for entry in data:
            if isinstance(entry, tuple):
                metadata, payload = entry
                uid = int(re.search(rb'UID (\d+)', metadata).group(1))
                message = next(item for item in self.box.messages if item['uid'] == uid)
                date = message.get('internaldate', '20-Oct-2026 12:00:00 +0000')
                metadata = re.sub(rb'INTERNALDATE "[^"]+"',
                                  ('INTERNALDATE "' + date + '"').encode(), metadata)
                entry = (metadata, payload)
            result.append(entry)
        return status, result


@pytest.fixture
def share_mailbox(mailbox_api, monkeypatch):
    box, admin = mailbox_api
    box.search_ok = True
    box.capabilities = (b'IMAP4rev1', b'IDLE')
    box.sort_status = 'BAD'
    box.sort_error = None
    box.search_error = None
    box.commands = []
    box.omitted_uid = None
    box.elapsed = 0
    box.scan_delay = 0
    monkeypatch.setattr(mail_app, 'create_imap_connection', lambda *args: ShareConnection(box))
    with mail_app.app.app_context():
        mail_app.add_account('share107@gmail.com', '', account_type='imap', provider='gmail',
                             imap_host='imap.gmail.com', imap_password='fixture-password')
        account = mail_app.get_account_by_email('share107@gmail.com')
    created = admin.post('/api/email-shares', json={
        'account_id': account['id'], 'max_email_count': 1, 'duration_minutes': 60,
    }).get_json()
    assert created['success'], created
    token = created['share']['share_url'].rsplit('/', 1)[-1]
    return box, mail_app.app.test_client(), token


@pytest.mark.parametrize('status', ['NO', 'BAD'])
def test_sort_protocol_rejection_falls_back_to_uid_metadata(share_mailbox, status):
    box, _client, _token = share_mailbox
    box.capabilities = (b'IMAP4rev1', b'SORT')
    box.sort_status = status
    identifiers, attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers == [b'103', b'102', b'101']
    assert box.commands[0][0] == 'SORT'
    assert box.commands[1] == ('SEARCH', None, 'ALL')
    assert attempts[-1]['status'] == 'OK'


def test_sort_bad_command_exception_can_use_uid_search(share_mailbox):
    box, _client, _token = share_mailbox
    box.capabilities = (b'IMAP4rev1', b'SORT')
    box.sort_error = mail_app.imaplib.IMAP4.error('UID command error: BAD [Unknown command]')
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers == [b'103', b'102', b'101']


def test_missing_sort_capability_skips_sort_and_reads_metadata_in_batches(share_mailbox, monkeypatch):
    box, _client, _token = share_mailbox
    monkeypatch.setattr(mail_app, 'IMAP_SHARE_METADATA_BATCH_SIZE', 2, raising=False)
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers == [b'103', b'102', b'101']
    assert box.commands[0] == ('SEARCH', None, 'ALL')
    fetches = [args for command, *args in box.commands if command == 'FETCH']
    assert len(fetches) == 2
    assert all(args[1] == '(UID INTERNALDATE)' and len(args[0].split(',')) <= 2 for args in fetches)


@pytest.mark.parametrize('error', [
    TimeoutError('timeout'), mail_app.imaplib.IMAP4.abort('connection lost'),
    mail_app.imaplib.IMAP4.error('unknown response from server'),
])
def test_broken_sort_connection_is_not_reused_for_fallback(share_mailbox, error):
    box, _client, _token = share_mailbox
    box.capabilities = (b'IMAP4rev1', b'SORT')
    box.sort_error = error
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers is None
    assert [command[0] for command in box.commands] == ['SORT']


def test_search_response_over_line_limit_fails_closed(share_mailbox):
    box, _client, _token = share_mailbox
    box.search_error = mail_app.imaplib.IMAP4.error('got more than 1000000 bytes')
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers is None
    assert [command[0] for command in box.commands] == ['SEARCH']


def test_metadata_scan_has_one_total_timeout_budget(share_mailbox, monkeypatch):
    box, _client, _token = share_mailbox
    box.scan_delay = mail_app.IMAP_TIMEOUT + 1
    monkeypatch.setattr(mail_app, 'IMAP_SHARE_METADATA_BATCH_SIZE', 1, raising=False)
    monkeypatch.setattr(mail_app, 'time', SimpleNamespace(monotonic=lambda: box.elapsed))
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers is None
    assert [command[0] for command in box.commands] == ['SEARCH', 'FETCH']


def test_gmail_limited_share_works_without_sort(share_mailbox):
    box, client, token = share_mailbox
    result = client.get(f'/api/share/email/{token}/emails?folder=inbox').get_json()
    assert result['success'], result
    assert len(result['emails']) == 1
    assert result['emails'][0]['id_mode'] == 'uid'
    assert result['emails'][0]['id'].startswith('imap:77:')
    assert not any(command[0] == 'SORT' for command in box.commands)


def test_outlook_imap_share_works_without_sort(share_mailbox, monkeypatch):
    box, _client, _token = share_mailbox
    monkeypatch.setattr(mail_app, 'get_access_token_imap_result',
                        lambda *args: {'success': True, 'access_token': 'fixture-token'})
    monkeypatch.setattr(mail_app.imaplib, 'IMAP4_SSL', lambda *args, **kwargs: ShareConnection(box))
    context = mail_app.email_share_stable_ids_context.set(True)
    try:
        result = mail_app.get_emails_imap_with_server('reader@outlook.com', 'client', 'refresh')
    finally:
        mail_app.email_share_stable_ids_context.reset(context)
    assert result['success'], result
    assert all(item['id_mode'] == 'uid' for item in result['emails'])


@pytest.mark.parametrize('failure', ['missing_uid', 'invalid_date'])
def test_incomplete_metadata_never_grants_access_to_an_older_mail(share_mailbox, failure):
    box, client, token = share_mailbox
    if failure == 'missing_uid':
        box.omitted_uid = 101
    else:
        box.messages[0]['internaldate'] = 'invalid-date'
    result = client.get(f'/api/share/email/{token}/emails?folder=inbox').get_json()
    assert not result['success']
    assert not any(command[0] == 'FETCH' and 'HEADER' in command[2] for command in box.commands)


def test_metadata_order_compares_actual_times_across_timezones(share_mailbox):
    box, _client, _token = share_mailbox
    for message, date in zip(box.messages, (
        '06-Nov-2026 10:00:00 +0800', '06-Nov-2026 03:00:00 +0000', '05-Nov-2026 23:30:00 -0200',
    )):
        message['internaldate'] = date
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers == [b'102', b'101', b'103']


def test_metadata_scan_restores_the_socket_timeout_after_failure(share_mailbox):
    box, _client, _token = share_mailbox
    box.omitted_uid = 101
    connection = ShareConnection(box)
    timeouts = []
    connection.sock = SimpleNamespace(gettimeout=lambda: 12, settimeout=timeouts.append)
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(connection)
    assert identifiers is None
    assert timeouts and all(0 < value <= 12 for value in timeouts)
    assert timeouts[-1] == 12


def test_empty_mailbox_does_not_fetch_metadata(share_mailbox):
    box, _client, _token = share_mailbox
    box.messages = []
    identifiers, _attempts = mail_app.search_imap_message_uids_by_arrival(ShareConnection(box))
    assert identifiers == []
    assert [command[0] for command in box.commands] == ['SEARCH']


def test_uid_order_cannot_expose_imported_old_mail_outside_latest_window(share_mailbox):
    box, client, token = share_mailbox
    box.messages = []
    for uid in range(1, 52):
        subject = 'Latest mail' if uid == 1 else f'Imported old mail {uid}'
        date = '06-Nov-2026 12:00:00 +0000' if uid == 1 else f'01-Jan-2020 00:00:{uid:02d} +0000'
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = 'sender@example.com'
        msg['To'] = 'share107@gmail.com'
        msg['Date'] = format_datetime(datetime.strptime(date, '%d-%b-%Y %H:%M:%S %z'))
        msg.set_content(subject + ' body')
        box.messages.append({'uid': uid, 'subject': subject, 'raw': msg.as_bytes(policy=SMTP),
                             'internaldate': date, 'deleted': False})
    listing = client.get(f'/api/share/email/{token}/emails?folder=inbox').get_json()
    assert listing['success'], listing
    assert [item['id'] for item in listing['emails']] == ['imap:77:1']
    latest = client.get(f'/api/share/email/{token}/email/imap:77:1?folder=inbox&id_mode=uid')
    old = client.get(f'/api/share/email/{token}/email/imap:77:51?folder=inbox&id_mode=uid')
    assert latest.status_code == 200 and latest.get_json()['success']
    assert old.status_code == 404
