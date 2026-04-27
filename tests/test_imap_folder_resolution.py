import importlib
import json
import os
import tempfile
import threading
import unittest
from email.message import EmailMessage
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
_temp_dir = tempfile.mkdtemp(prefix='outlookEmail-tests-')
os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class FakeMail:
    def __init__(self, selectable=None, list_entries=None, selectable_by_mode=None):
        self.selectable = set(selectable or [])
        self.selectable_by_mode = dict(selectable_by_mode or {})
        self.list_entries = list_entries or []
        self.select_calls = []
        self.logged_out = False
        self.xatom_calls = []

    def login(self, *_args, **_kwargs):
        return 'OK', [b'logged in']

    def xatom(self, name, *args):
        self.xatom_calls.append((name, args))
        return 'OK', [b'ID completed']

    def select(self, name, readonly=True):
        self.select_calls.append((name, readonly))
        if (name, readonly) in self.selectable_by_mode:
            return self.selectable_by_mode[(name, readonly)]
        if name in self.selectable:
            return 'OK', [b'']
        return 'NO', [b'folder not found']

    def list(self):
        return 'OK', self.list_entries

    def uid(self, *_args, **_kwargs):
        return 'OK', [b'']

    def search(self, *_args, **_kwargs):
        return 'OK', [b'']

    def fetch(self, *_args, **_kwargs):
        return 'OK', [b'']

    def logout(self):
        self.logged_out = True
        return 'BYE', [b'logout']


class ImapFolderResolutionTests(unittest.TestCase):
    def test_2925_domain_maps_to_builtin_provider(self):
        meta = web_outlook_app.get_provider_meta('custom', 'user@2925.com')

        self.assertEqual(meta['key'], '2925')
        self.assertEqual(meta['imap_host'], 'imap.2925.com')
        self.assertEqual(meta['imap_port'], 993)

    def test_parse_outlook_import_default_order(self):
        parsed = web_outlook_app.parse_outlook_account_string(
            'user@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA_refresh',
            'client_id_refresh_token',
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['client_id'], '24d9a0ed-8787-4584-883c-2fd79308940a')
        self.assertEqual(parsed['refresh_token'], '0.AXEA_refresh')

    def test_parse_outlook_import_reversed_order_even_when_selector_is_default(self):
        parsed = web_outlook_app.parse_outlook_account_string(
            'user@outlook.com----password123----0.AXEA_refresh----24d9a0ed-8787-4584-883c-2fd79308940a',
            'client_id_refresh_token',
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['client_id'], '24d9a0ed-8787-4584-883c-2fd79308940a')
        self.assertEqual(parsed['refresh_token'], '0.AXEA_refresh')

    def test_resolve_126_inbox_from_listed_folder(self):
        mail = FakeMail(
            selectable={'INBOX.收件箱'},
            list_entries=[
                b'(\\HasNoChildren) "." "INBOX.Archive"',
                '(\\HasNoChildren) "." "INBOX.收件箱"'.encode('utf-8'),
            ],
        )

        selected, diagnostics = web_outlook_app.resolve_imap_folder(mail, '126', 'inbox', readonly=True)

        self.assertEqual(selected, 'INBOX.收件箱')
        self.assertIn('INBOX.收件箱', diagnostics.get('matched_folders', []))
        self.assertNotIn('INBOX.Archive', diagnostics.get('matched_folders', []))

    def test_resolve_junk_folder_from_terminal_alias(self):
        mail = FakeMail(
            selectable={'INBOX.Spam'},
            list_entries=[b'(\\HasNoChildren) "." "INBOX.Spam"'],
        )

        selected, diagnostics = web_outlook_app.resolve_imap_folder(mail, 'custom', 'junkemail', readonly=True)

        self.assertEqual(selected, 'INBOX.Spam')
        self.assertEqual(diagnostics.get('matched_folders'), ['INBOX.Spam'])

    def test_imap_folder_not_found_returns_available_folders(self):
        mail = FakeMail(
            selectable=set(),
            list_entries=[b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren) "." "INBOX.Archive"'],
        )

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@example.com',
                imap_password='secret',
                imap_host='imap.example.com',
                folder='deleteditems',
                provider='custom',
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'IMAP_FOLDER_NOT_FOUND')
        details = json.loads(result['error']['details'])
        self.assertEqual(details['folder'], 'deleteditems')
        self.assertEqual(details['provider'], 'custom')
        self.assertEqual(details['available_folders'], ['INBOX', 'INBOX.Archive'])
        self.assertTrue(mail.logged_out)

    def test_gmail_imap_list_uses_internaldate_for_sorting(self):
        raw_old_header = (
            b"Subject: older-header\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@gmail.com\r\n"
            b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
            b"\r\n"
            b"body old\r\n"
        )
        raw_new_header = (
            b"Subject: newer-header\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@gmail.com\r\n"
            b"Date: Mon, 01 Jan 2026 00:00:00 +0000\r\n"
            b"\r\n"
            b"body new\r\n"
        )

        class GmailListMail(FakeMail):
            def uid(self, command, *args, **kwargs):
                if command == 'SEARCH':
                    return 'OK', [b'1 2']
                if command == 'FETCH':
                    uid = args[0]
                    uid_text = uid.decode('utf-8') if isinstance(uid, (bytes, bytearray)) else str(uid)
                    if uid_text == '1':
                        return 'OK', [(
                            b'1 (FLAGS () INTERNALDATE "14-Apr-2026 10:00:00 +0000" RFC822 {128}',
                            raw_old_header,
                        )]
                    if uid_text == '2':
                        return 'OK', [(
                            b'2 (FLAGS () INTERNALDATE "13-Apr-2026 10:00:00 +0000" RFC822 {128}',
                            raw_new_header,
                        )]
                return super().uid(command, *args, **kwargs)

        mail = GmailListMail(selectable={'INBOX'})

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@gmail.com',
                imap_password='app-password',
                imap_host='imap.gmail.com',
                provider='gmail',
                folder='inbox',
                top=20,
            )

        self.assertTrue(result['success'])
        self.assertEqual([item['id'] for item in result['emails']], ['1', '2'])
        self.assertEqual(result['emails'][0]['date'], '14-Apr-2026 10:00:00 +0000')
        self.assertTrue(mail.logged_out)

    def test_gmail_imap_list_reads_seen_flag_from_split_fetch_response(self):
        raw_email = (
            b"Subject: seen-mail\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@gmail.com\r\n"
            b"Date: Tue, 14 Apr 2026 08:20:50 +0000\r\n"
            b"\r\n"
            b"hello gmail\r\n"
        )

        class GmailSeenMail(FakeMail):
            def uid(self, command, *args, **kwargs):
                if command == 'SEARCH':
                    return 'OK', [b'11']
                if command == 'FETCH':
                    return 'OK', [
                        (
                            b'11 (INTERNALDATE "14-Apr-2026 08:20:50 +0000" RFC822 {128}',
                            raw_email,
                        ),
                        b' FLAGS (\\Seen))',
                    ]
                return super().uid(command, *args, **kwargs)

        mail = GmailSeenMail(selectable={'INBOX'})

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@gmail.com',
                imap_password='app-password',
                imap_host='imap.gmail.com',
                provider='gmail',
                folder='inbox',
                top=20,
            )

        self.assertTrue(result['success'])
        self.assertEqual(len(result['emails']), 1)
        self.assertTrue(result['emails'][0]['is_read'])
        self.assertEqual(result['emails'][0]['subject'], 'seen-mail')
        self.assertTrue(mail.logged_out)

    def test_parse_email_datetime_accepts_parenthesized_timezone_name(self):
        parsed = web_outlook_app.parse_email_datetime('Tue, 14 Apr 2026 08:20:50 +0000 (UTC)')

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 4)
        self.assertEqual(parsed.day, 14)

    def test_fallback_from_examine_to_select_for_126_inbox(self):
        mail = FakeMail(
            selectable_by_mode={
                ('INBOX', True): ('NO', [b'EXAMINE not supported']),
                ('"INBOX"', True): ('NO', [b'EXAMINE not supported']),
                ('INBOX', False): ('OK', [b'12']),
            },
            list_entries=[b'(\\HasNoChildren) "." "INBOX"'],
        )

        selected, diagnostics = web_outlook_app.resolve_imap_folder(mail, '126', 'inbox', readonly=True)

        self.assertEqual(selected, 'INBOX')
        self.assertEqual(diagnostics.get('fallback_mode'), 'select')
        self.assertIn(('INBOX', True), mail.select_calls)
        self.assertIn(('INBOX', False), mail.select_calls)

    def test_unsafe_login_is_classified_as_provider_block(self):
        unsafe = "Unsafe Login. Please contact kefu@188.com for help"
        mail = FakeMail(
            selectable_by_mode={
                ('INBOX', True): ('NO', [unsafe.encode('utf-8')]),
                ('"INBOX"', True): ('NO', [unsafe.encode('utf-8')]),
                ('INBOX', False): ('NO', [unsafe.encode('utf-8')]),
                ('"INBOX"', False): ('NO', [unsafe.encode('utf-8')]),
            },
            list_entries=[b'(\\HasNoChildren) "." "INBOX"'],
        )

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@126.com',
                imap_password='secret',
                imap_host='imap.126.com',
                folder='inbox',
                provider='126',
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'IMAP_UNSAFE_LOGIN_BLOCKED')
        self.assertEqual(result['error']['status'], 403)
        self.assertEqual(result['error']['code'], 'IMAP_UNSAFE_LOGIN_BLOCKED')
        self.assertIn('Unsafe Login', result['error']['message'])
        self.assertEqual(mail.xatom_calls[0][0], 'ID')

    def test_send_imap_id_after_login(self):
        mail = FakeMail(
            selectable={'INBOX'},
            list_entries=[b'(\\HasNoChildren) "." "INBOX"'],
        )

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@126.com',
                imap_password='secret',
                imap_host='imap.126.com',
                folder='inbox',
                provider='126',
            )

        self.assertTrue(result['success'])
        self.assertEqual(mail.xatom_calls[0][0], 'ID')
        payload = mail.xatom_calls[0][1][0]
        self.assertIn('"name" "outlookEmail"', payload)
        self.assertIn('"version"', payload)

    def test_custom_imap_list_falls_back_to_plain_search_when_uid_search_fails(self):
        raw_email = (
            b"Subject: inbox message\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@example.com\r\n"
            b"Date: Tue, 14 Apr 2026 08:20:50 +0000\r\n"
            b"\r\n"
            b"hello\r\n"
        )

        class SearchFallbackMail(FakeMail):
            def uid(self, command, *args, **kwargs):
                if command == 'SEARCH':
                    return 'BAD', [b'UID SEARCH unsupported']
                return super().uid(command, *args, **kwargs)

            def search(self, *_args, **_kwargs):
                return 'OK', [b'7']

            def fetch(self, message_id, _query):
                self.select_calls.append((f'FETCH:{message_id}', False))
                return 'OK', [(
                    b'7 (FLAGS (\\Seen) INTERNALDATE "14-Apr-2026 08:20:50 +0000" RFC822 {128}',
                    raw_email,
                )]

        mail = SearchFallbackMail(selectable={'INBOX'}, list_entries=[b'(\\HasNoChildren) "." "INBOX"'])

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@example.com',
                imap_password='secret',
                imap_host='imap.example.com',
                folder='inbox',
                provider='custom',
            )

        self.assertTrue(result['success'])
        self.assertEqual(len(result['emails']), 1)
        self.assertEqual(result['emails'][0]['id'], '7')
        self.assertEqual(result['emails'][0]['subject'], 'inbox message')

    def test_custom_imap_detail_falls_back_to_plain_fetch_when_uid_fetch_fails(self):
        raw_email = (
            b"Subject: detail message\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@example.com\r\n"
            b"Date: Tue, 14 Apr 2026 08:20:50 +0000\r\n"
            b"\r\n"
            b"detail body\r\n"
        )

        class FetchFallbackMail(FakeMail):
            def uid(self, command, *args, **kwargs):
                if command == 'FETCH':
                    return 'BAD', [b'UID FETCH unsupported']
                return super().uid(command, *args, **kwargs)

            def fetch(self, message_id, _query):
                return 'OK', [(
                    b'9 (RFC822 {128}',
                    raw_email,
                )]

        mail = FetchFallbackMail(selectable={'INBOX'}, list_entries=[b'(\\HasNoChildren) "." "INBOX"'])

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_email_detail_imap_generic_result(
                email_addr='user@example.com',
                imap_password='secret',
                imap_host='imap.example.com',
                message_id='9',
                folder='inbox',
                provider='custom',
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['email']['id'], '9')
        self.assertEqual(result['email']['subject'], 'detail message')
        self.assertIn('detail body', result['email']['body'])

    def test_custom_imap_detail_falls_back_when_uid_fetch_returns_ok_without_payload(self):
        raw_email = (
            b"Subject: detail fallback payload\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@example.com\r\n"
            b"Date: Tue, 14 Apr 2026 08:20:50 +0000\r\n"
            b"\r\n"
            b"detail body from sequence fetch\r\n"
        )

        class EmptyUidFetchMail(FakeMail):
            def uid(self, command, *args, **kwargs):
                if command == 'FETCH':
                    return 'OK', [None]
                return super().uid(command, *args, **kwargs)

            def fetch(self, message_id, _query):
                if str(message_id) == '9':
                    return 'OK', [(
                        b'9 (RFC822 {128}',
                        raw_email,
                    )]
                return 'NO', [b'not found']

        mail = EmptyUidFetchMail(selectable={'INBOX'}, list_entries=[b'(\\HasNoChildren) "." "INBOX"'])

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_email_detail_imap_generic_result(
                email_addr='user@example.com',
                imap_password='secret',
                imap_host='imap.example.com',
                message_id='9',
                folder='inbox',
                provider='custom',
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['email']['id'], '9')
        self.assertEqual(result['email']['subject'], 'detail fallback payload')
        self.assertIn('detail body from sequence fetch', result['email']['body'])

    def test_custom_imap_uses_exists_count_when_search_returns_empty(self):
        raw_email = (
            b"Subject: exists fallback\r\n"
            b"From: sender@example.com\r\n"
            b"To: user@example.com\r\n"
            b"Date: Tue, 14 Apr 2026 08:20:50 +0000\r\n"
            b"\r\n"
            b"exists body\r\n"
        )

        class ExistsFallbackMail(FakeMail):
            def select(self, name, readonly=True):
                self.select_calls.append((name, readonly))
                if name in {'INBOX', '"INBOX"'}:
                    return 'OK', [b'1']
                return 'NO', [b'folder not found']

            def uid(self, command, *args, **kwargs):
                if command == 'SEARCH':
                    return 'OK', [b'']
                return super().uid(command, *args, **kwargs)

            def search(self, *_args, **_kwargs):
                raise web_outlook_app.imaplib.IMAP4.error("SEARCH command error")

            def fetch(self, message_id, _query):
                if str(message_id) == '1':
                    return 'OK', [(
                        b'1 (FLAGS () INTERNALDATE "14-Apr-2026 08:20:50 +0000" RFC822 {128}',
                        raw_email,
                    )]
                return 'NO', [b'not found']

        mail = ExistsFallbackMail(list_entries=[b'(\\HasNoChildren) "." "INBOX"'])

        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            result = web_outlook_app.get_emails_imap_generic(
                email_addr='user@example.com',
                imap_password='secret',
                imap_host='imap.example.com',
                folder='inbox',
                provider='custom',
            )

        self.assertTrue(result['success'])
        self.assertEqual(len(result['emails']), 1)
        self.assertEqual(result['emails'][0]['id'], '1')
        self.assertEqual(result['emails'][0]['subject'], 'exists fallback')

    def test_fetch_account_emails_all_fetches_in_parallel(self):
        account = {
            'email': 'user@outlook.com',
            'account_type': 'oauth',
        }
        barrier = threading.Barrier(2, timeout=1)

        def fake_fetch(target_account, folder, skip, top, proxy_url='', fallback_proxy_urls=None):
            self.assertIs(target_account, account)
            self.assertEqual(skip, 0)
            self.assertEqual(top, 20)
            self.assertEqual(proxy_url, 'socks5://primary')
            self.assertEqual(fallback_proxy_urls, ['socks5://fallback'])
            try:
                barrier.wait()
            except threading.BrokenBarrierError as exc:
                raise AssertionError('folder=all 仍然是串行抓取') from exc
            return {
                'success': True,
                'emails': [{
                    'id': folder,
                    'folder': folder,
                    'date': '2026-01-01T00:00:00Z' if folder == 'inbox' else '2026-01-02T00:00:00Z',
                }],
                'method': f'method-{folder}',
                'has_more': False,
            }

        with patch.object(web_outlook_app, 'get_account_proxy_url', return_value='socks5://primary'):
            with patch.object(web_outlook_app, 'get_account_proxy_failover_urls', return_value=['socks5://fallback']):
                with patch.object(web_outlook_app, 'fetch_account_folder_emails', side_effect=fake_fetch):
                    result = web_outlook_app.fetch_account_emails(account, 'all', 0, 20)

        self.assertTrue(result['success'])
        self.assertEqual([email['folder'] for email in result['emails']], ['junkemail', 'inbox'])
        self.assertEqual(result['method'], 'method-inbox / method-junkemail')


class ExternalAccountsApiTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_refresh_logs')
            db.execute('DELETE FROM accounts')
            db.execute('DELETE FROM tags')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

            self.assertTrue(web_outlook_app.set_setting('external_api_key', 'test-external-key'))

            tag_id = web_outlook_app.add_tag('核心', '#1a1a1a')
            self.assertIsNotNone(tag_id)

            added = web_outlook_app.add_account(
                'user@outlook.com',
                'password123',
                '24d9a0ed-8787-4584-883c-2fd79308940a',
                '0.AXEA_refresh',
                group_id=1,
                remark='主账号',
                forward_enabled=True
            )
            self.assertTrue(added)

            account = web_outlook_app.get_account_by_email('user@outlook.com')
            self.assertIsNotNone(account)

            alias_ok, _, alias_errors = web_outlook_app.replace_account_aliases(
                account['id'],
                account['email'],
                ['alias@example.com'],
                db
            )
            self.assertTrue(alias_ok, alias_errors)
            db.commit()

            self.assertTrue(web_outlook_app.add_account_tag(account['id'], tag_id))
            db.execute(
                '''
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (account['id'], account['email'], 'manual', 'success', None)
            )
            db.commit()

    def test_external_accounts_requires_api_key(self):
        response = self.client.get('/api/external/accounts')

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('API Key', payload['error'])

    def test_external_emails_requires_api_key(self):
        response = self.client.get('/api/external/emails?email=user@outlook.com&folder=inbox')

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('API Key', payload['error'])

    def test_internal_emails_requires_login(self):
        response = self.client.get('/api/emails/user@outlook.com?folder=inbox')

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload['need_login'])
        self.assertEqual(payload['error'], '请先登录')

    def test_internal_emails_does_not_update_last_refresh_time(self):
        expected_result = {
            'success': True,
            'emails': [{'id': 'inbox-1', 'folder': 'inbox', 'date': '2026-01-01T00:00:00Z'}],
            'method': 'Graph API',
            'has_more': False,
        }

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                UPDATE accounts
                SET last_refresh_at = ?
                WHERE email = ?
                ''',
                ('2026-01-10 12:34:56', 'user@outlook.com')
            )
            db.commit()

        with self.client.session_transaction() as session:
            session['logged_in'] = True

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=expected_result) as fetch_mock:
            response = self.client.get('/api/emails/user@outlook.com?folder=inbox')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload, expected_result)
        fetch_mock.assert_called_once()

        with self.app.app_context():
            db = web_outlook_app.get_db()
            row = db.execute(
                'SELECT last_refresh_at FROM accounts WHERE email = ?',
                ('user@outlook.com',)
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row['last_refresh_at'], '2026-01-10 12:34:56')

    def test_update_account_requires_login(self):
        response = self.client.put(
            '/api/accounts/1',
            json={'remark': 'updated without login'}
        )

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload['need_login'])
        self.assertEqual(payload['error'], '请先登录')

    def test_dynamic_endpoint_overrides_keep_required_guards(self):
        self.assertTrue(getattr(self.app.view_functions['api_update_account'], '_requires_login', False))
        self.assertTrue(getattr(self.app.view_functions['api_get_emails'], '_requires_login', False))
        self.assertTrue(getattr(self.app.view_functions['api_external_get_emails'], '_requires_api_key', False))

    def test_external_accounts_returns_sanitized_accounts(self):
        with self.app.app_context():
            group_id = web_outlook_app.add_group('代理组', '带代理的账号', '#123456')
            self.assertIsNotNone(group_id)
            added = web_outlook_app.add_account(
                'other@example.com',
                'password456',
                '',
                '',
                group_id=group_id,
                remark='次账号',
                account_type='imap',
                provider='custom',
                imap_host='imap.example.com',
                imap_port=993,
                imap_password='imap-secret',
                forward_enabled=False
            )
            self.assertTrue(added)

        response = self.client.get(
            '/api/external/accounts?group_id=1',
            headers={'X-API-Key': 'test-external-key'}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        self.assertEqual(len(payload['accounts']), 1)

        account = payload['accounts'][0]
        self.assertEqual(account['email'], 'user@outlook.com')
        self.assertEqual(account['aliases'], ['alias@example.com'])
        self.assertEqual(account['alias_count'], 1)
        self.assertEqual(account['group_id'], 1)
        self.assertEqual(account['group_name'], '默认分组')
        self.assertEqual(account['remark'], '主账号')
        self.assertEqual(account['status'], 'active')
        self.assertEqual(account['provider'], 'outlook')
        self.assertTrue(account['forward_enabled'])
        self.assertEqual(account['last_refresh_status'], 'success')
        self.assertIsNone(account['last_refresh_error'])
        self.assertEqual(account['tags'][0]['name'], '核心')
        self.assertNotIn('password', account)
        self.assertNotIn('refresh_token', account)
        self.assertNotIn('client_id', account)
        self.assertNotIn('imap_host', account)
        self.assertNotIn('imap_port', account)

    def test_external_emails_supports_all_folder(self):
        expected_result = {
            'success': True,
            'emails': [
                {'id': 'junk-1', 'folder': 'junkemail', 'date': '2026-01-02T00:00:00Z'},
                {'id': 'inbox-1', 'folder': 'inbox', 'date': '2026-01-01T00:00:00Z'},
            ],
            'method': 'Graph API / IMAP (New)',
            'has_more': False,
        }

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=expected_result) as fetch_mock:
            response = self.client.get(
                '/api/external/emails?email=user@outlook.com&folder=all&skip=0&top=20',
                headers={'X-API-Key': 'test-external-key'}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload, expected_result)

        called_account, called_folder, called_skip, called_top = fetch_mock.call_args.args
        self.assertEqual(called_account['email'], 'user@outlook.com')
        self.assertEqual(called_folder, 'all')
        self.assertEqual(called_skip, 0)
        self.assertEqual(called_top, 20)

    def test_external_emails_plus_address_falls_back_to_base_email(self):
        expected_result = {
            'success': True,
            'emails': [{'id': 'inbox-1', 'folder': 'inbox', 'date': '2026-01-01T00:00:00Z'}],
            'method': 'Graph API',
            'has_more': False,
        }

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=expected_result) as fetch_mock:
            response = self.client.get(
                '/api/external/emails?email=user+verify@outlook.com&folder=inbox&top=1',
                headers={'X-API-Key': 'test-external-key'}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['requested_email'], 'user+verify@outlook.com')
        self.assertEqual(payload['resolved_email'], 'user@outlook.com')

        called_account, called_folder, called_skip, called_top = fetch_mock.call_args.args
        self.assertEqual(called_account['email'], 'user@outlook.com')
        self.assertEqual(called_folder, 'inbox')
        self.assertEqual(called_skip, 0)
        self.assertEqual(called_top, 1)

    def test_external_emails_plus_address_prefers_exact_match(self):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                'user+vip@outlook.com',
                'password456',
                'client-id-plus',
                'refresh-token-plus',
                group_id=1,
                remark='plus 账号'
            )
            self.assertTrue(added)

        expected_result = {
            'success': True,
            'emails': [{'id': 'inbox-plus', 'folder': 'inbox', 'date': '2026-01-03T00:00:00Z'}],
            'method': 'Graph API',
            'has_more': False,
        }

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=expected_result) as fetch_mock:
            response = self.client.get(
                '/api/external/emails?email=user+vip@outlook.com&folder=inbox&top=1',
                headers={'X-API-Key': 'test-external-key'}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['requested_email'], 'user+vip@outlook.com')
        self.assertEqual(payload['resolved_email'], 'user+vip@outlook.com')

        called_account, called_folder, called_skip, called_top = fetch_mock.call_args.args
        self.assertEqual(called_account['email'], 'user+vip@outlook.com')
        self.assertEqual(called_folder, 'inbox')
        self.assertEqual(called_skip, 0)
        self.assertEqual(called_top, 1)

    def test_external_emails_plus_address_falls_back_to_alias_with_plus(self):
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('user@outlook.com')
            self.assertIsNotNone(account)
            alias_ok, _, alias_errors = web_outlook_app.replace_account_aliases(
                account['id'],
                account['email'],
                ['alias@example.com', 'alias+team@example.com'],
                web_outlook_app.get_db()
            )
            self.assertTrue(alias_ok, alias_errors)
            web_outlook_app.get_db().commit()

        expected_result = {
            'success': True,
            'emails': [{'id': 'inbox-alias-plus', 'folder': 'inbox', 'date': '2026-01-04T00:00:00Z'}],
            'method': 'Graph API',
            'has_more': False,
        }

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=expected_result) as fetch_mock:
            response = self.client.get(
                '/api/external/emails?email=alias+team+notice@example.com&folder=inbox&top=1',
                headers={'X-API-Key': 'test-external-key'}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['requested_email'], 'alias+team+notice@example.com')
        self.assertEqual(payload['resolved_email'], 'user@outlook.com')
        self.assertEqual(payload['matched_alias'], 'alias+team@example.com')

        called_account, called_folder, called_skip, called_top = fetch_mock.call_args.args
        self.assertEqual(called_account['email'], 'user@outlook.com')
        self.assertEqual(called_account['matched_alias'], 'alias+team@example.com')
        self.assertEqual(called_folder, 'inbox')
        self.assertEqual(called_skip, 0)
        self.assertEqual(called_top, 1)


class BatchForwardingApiTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_refresh_logs')
            db.execute('DELETE FROM accounts')
            db.execute('DELETE FROM tags')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

            self.assertTrue(web_outlook_app.add_account(
                'disabled-forward@outlook.com',
                'password123',
                'client-id-disabled',
                'refresh-token-disabled',
                group_id=1,
                forward_enabled=False
            ))
            self.assertTrue(web_outlook_app.add_account(
                'enabled-forward@outlook.com',
                'password123',
                'client-id-enabled',
                'refresh-token-enabled',
                group_id=1,
                forward_enabled=True
            ))

            disabled_account = web_outlook_app.get_account_by_email('disabled-forward@outlook.com')
            enabled_account = web_outlook_app.get_account_by_email('enabled-forward@outlook.com')
            self.assertIsNotNone(disabled_account)
            self.assertIsNotNone(enabled_account)

            self.disabled_account_id = disabled_account['id']
            self.enabled_account_id = enabled_account['id']
            self.disabled_cursor_before = disabled_account.get('forward_last_checked_at')
            self.enabled_cursor_before = enabled_account.get('forward_last_checked_at')

    def test_batch_enable_forwarding_only_updates_disabled_accounts(self):
        response = self.client.post(
            '/api/accounts/batch-update-forwarding',
            json={
                'account_ids': [self.disabled_account_id, self.enabled_account_id],
                'forward_enabled': True,
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['updated_count'], 1)
        self.assertEqual(payload['unchanged_count'], 1)

        with self.app.app_context():
            disabled_account = web_outlook_app.get_account_by_id(self.disabled_account_id)
            enabled_account = web_outlook_app.get_account_by_id(self.enabled_account_id)

        self.assertTrue(disabled_account['forward_enabled'])
        self.assertTrue(disabled_account['forward_last_checked_at'])
        self.assertEqual(enabled_account['forward_last_checked_at'], self.enabled_cursor_before)

    def test_batch_disable_forwarding_only_updates_enabled_accounts(self):
        response = self.client.post(
            '/api/accounts/batch-update-forwarding',
            json={
                'account_ids': [self.disabled_account_id, self.enabled_account_id],
                'forward_enabled': False,
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['updated_count'], 1)
        self.assertEqual(payload['unchanged_count'], 1)

        with self.app.app_context():
            disabled_account = web_outlook_app.get_account_by_id(self.disabled_account_id)
            enabled_account = web_outlook_app.get_account_by_id(self.enabled_account_id)

        self.assertFalse(disabled_account['forward_enabled'])
        self.assertEqual(disabled_account['forward_last_checked_at'], self.disabled_cursor_before)
        self.assertFalse(enabled_account['forward_enabled'])
        self.assertEqual(enabled_account['forward_last_checked_at'], self.enabled_cursor_before)


class TempEmailTagsApiTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM temp_email_tags')
            db.execute('DELETE FROM temp_email_messages')
            db.execute('DELETE FROM temp_emails')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM tags')
            db.commit()

            self.primary_tag_id = web_outlook_app.add_tag('临时重点', '#111111')
            self.secondary_tag_id = web_outlook_app.add_tag('待清理', '#ff6600')
            self.assertTrue(web_outlook_app.add_temp_email('case-one@example.com', provider='gptmail'))
            self.assertTrue(web_outlook_app.add_temp_email('case-two@example.com', provider='duckmail'))

            self.temp_email_one = web_outlook_app.get_temp_email_by_address('case-one@example.com')
            self.temp_email_two = web_outlook_app.get_temp_email_by_address('case-two@example.com')
            self.assertIsNotNone(self.temp_email_one)
            self.assertIsNotNone(self.temp_email_two)

    def test_get_temp_emails_returns_tags(self):
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_temp_email_tag(self.temp_email_one['id'], self.primary_tag_id))

        response = self.client.get('/api/temp-emails')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        email_map = {item['email']: item for item in payload['emails']}
        self.assertIn('case-one@example.com', email_map)
        self.assertEqual(email_map['case-one@example.com']['tags'][0]['name'], '临时重点')
        self.assertEqual(email_map['case-two@example.com']['tags'], [])

    def test_batch_manage_temp_email_tags_add_and_remove(self):
        add_response = self.client.post(
            '/api/temp-emails/tags',
            json={
                'temp_email_ids': [self.temp_email_one['id'], self.temp_email_two['id']],
                'tag_id': self.secondary_tag_id,
                'action': 'add',
            }
        )

        self.assertEqual(add_response.status_code, 200)
        add_payload = add_response.get_json()
        self.assertTrue(add_payload['success'])

        with self.app.app_context():
            first_tags = web_outlook_app.get_temp_email_tags(self.temp_email_one['id'])
            second_tags = web_outlook_app.get_temp_email_tags(self.temp_email_two['id'])

        self.assertEqual([tag['name'] for tag in first_tags], ['待清理'])
        self.assertEqual([tag['name'] for tag in second_tags], ['待清理'])

        remove_response = self.client.post(
            '/api/temp-emails/tags',
            json={
                'temp_email_ids': [self.temp_email_one['id']],
                'tag_id': self.secondary_tag_id,
                'action': 'remove',
            }
        )

        self.assertEqual(remove_response.status_code, 200)
        remove_payload = remove_response.get_json()
        self.assertTrue(remove_payload['success'])

        with self.app.app_context():
            first_tags = web_outlook_app.get_temp_email_tags(self.temp_email_one['id'])
            second_tags = web_outlook_app.get_temp_email_tags(self.temp_email_two['id'])

        self.assertEqual(first_tags, [])
        self.assertEqual([tag['name'] for tag in second_tags], ['待清理'])


class AssetRenderingTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_index_uses_bundled_stylesheet_route(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

        response = self.client.get('/')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/assets/index.css"', html)
        self.assertNotIn('href="/static/index.css"', html)

    def test_bundled_stylesheet_contains_combined_css_without_imports(self):
        response = self.client.get('/assets/index.css')
        css = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/css')
        self.assertNotIn('@import', css)
        self.assertIn('.toast', css)
        self.assertIn('.group-panel', css)
        self.assertIn('.account-panel', css)


class RefreshTokenProxyFallbackTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_refresh_logs')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

            group_id = web_outlook_app.add_group(
                '代理刷新组',
                '测试代理失败后直连重试',
                '#225588',
                'socks5://127.0.0.1:1080',
                'http://127.0.0.1:7891',
                'direct',
            )
            self.assertIsNotNone(group_id)
            self.group_id = group_id

            added = web_outlook_app.add_account(
                'proxy-refresh@outlook.com',
                'password123',
                '24d9a0ed-8787-4584-883c-2fd79308940a',
                '0.AXEA_refresh',
                group_id=group_id,
                remark='代理刷新测试账号',
                forward_enabled=False,
            )
            self.assertTrue(added)

            account = web_outlook_app.get_account_by_email('proxy-refresh@outlook.com')
            self.assertIsNotNone(account)
            self.account_id = account['id']

    def test_refresh_account_retries_with_fallback_proxies_in_order(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {'access_token': 'access-token'}

        proxy_error = web_outlook_app.requests.exceptions.ConnectionError(
            'SOCKSHTTPSConnectionPool(host=\'login.microsoftonline.com\', port=443): '
            'Max retries exceeded with url: /common/oauth2/v2.0/token '
            '(Caused by NewConnectionError("SOCKSHTTPSConnection(host=\'login.microsoftonline.com\', '
            'port=443): Failed to establish a new connection: 0x04: Host unreachable"))'
        )

        http_proxy_error = web_outlook_app.requests.exceptions.ProxyError(
            'HTTPSConnectionPool(host=\'login.microsoftonline.com\', port=443): '
            'Max retries exceeded with url: /common/oauth2/v2.0/token '
            '(Caused by ProxyError(\'Unable to connect to proxy\', OSError(\'proxy connect failed\')))'
        )

        with patch.object(web_outlook_app.requests, 'request', side_effect=[proxy_error, http_proxy_error, FakeResponse()]) as mocked_request:
            response = self.client.post(f'/api/accounts/{self.account_id}/refresh')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['message'], 'Token 刷新成功')
        self.assertEqual(mocked_request.call_count, 3)
        self.assertEqual(
            mocked_request.call_args_list[0].kwargs['proxies'],
            {'http': 'socks5://127.0.0.1:1080', 'https': 'socks5://127.0.0.1:1080'},
        )
        self.assertEqual(
            mocked_request.call_args_list[1].kwargs['proxies'],
            {'http': 'http://127.0.0.1:7891', 'https': 'http://127.0.0.1:7891'},
        )
        self.assertEqual(
            mocked_request.call_args_list[2].kwargs['proxies'],
            {'http': None, 'https': None, 'all': None},
        )

        with self.app.app_context():
            db = web_outlook_app.get_db()
            log_row = db.execute(
                '''
                SELECT status, error_message
                FROM account_refresh_logs
                WHERE account_id = ?
                ORDER BY id DESC
                LIMIT 1
                ''',
                (self.account_id,),
            ).fetchone()

        self.assertIsNotNone(log_row)
        self.assertEqual(log_row['status'], 'success')
        self.assertIsNone(log_row['error_message'])

    def test_refresh_account_persists_rotated_refresh_token(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    'access_token': 'access-token',
                    'refresh_token': '0.AXEA_rotated_manual',
                }

        with patch.object(web_outlook_app.requests, 'request', return_value=FakeResponse()):
            response = self.client.post(f'/api/accounts/{self.account_id}/refresh')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        with self.app.app_context():
            refreshed = web_outlook_app.get_account_by_id(self.account_id)

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed['refresh_token'], '0.AXEA_rotated_manual')

    def test_trigger_refresh_internal_persists_rotated_refresh_token(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    'access_token': 'access-token',
                    'refresh_token': '0.AXEA_rotated_scheduled',
                }

        with patch.object(web_outlook_app.requests, 'request', return_value=FakeResponse()):
            web_outlook_app.trigger_refresh_internal()

        with self.app.app_context():
            refreshed = web_outlook_app.get_account_by_id(self.account_id)

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed['refresh_token'], '0.AXEA_rotated_scheduled')

        with self.app.app_context():
            db = web_outlook_app.get_db()
            account_row = db.execute(
                '''
                SELECT last_refresh_status, last_refresh_error, last_refresh_at, refresh_token_updated_at
                FROM accounts
                WHERE id = ?
                ''',
                (self.account_id,),
            ).fetchone()
            snapshot_row = db.execute(
                '''
                SELECT trigger_type, status, total_count, success_count, failed_count, finished_at
                FROM token_refresh_state
                WHERE scope_key = 'all_outlook'
                '''
            ).fetchone()

        self.assertEqual(account_row['last_refresh_status'], 'success')
        self.assertIsNone(account_row['last_refresh_error'])
        self.assertIsNotNone(account_row['last_refresh_at'])
        self.assertIsNotNone(account_row['refresh_token_updated_at'])
        self.assertEqual(snapshot_row['trigger_type'], 'scheduled')
        self.assertEqual(snapshot_row['status'], 'success')
        self.assertEqual(snapshot_row['total_count'], 1)
        self.assertEqual(snapshot_row['success_count'], 1)
        self.assertEqual(snapshot_row['failed_count'], 0)
        self.assertIsNotNone(snapshot_row['finished_at'])

    def test_run_full_refresh_marks_failed_snapshot_on_unexpected_exception(self):
        with self.assertRaises(RuntimeError):
            with patch.object(web_outlook_app, 'refresh_outlook_account_token', side_effect=RuntimeError('boom')):
                web_outlook_app.run_full_refresh('scheduled', 'scheduled')

        with self.app.app_context():
            db = web_outlook_app.get_db()
            account_row = db.execute(
                '''
                SELECT last_refresh_status, last_refresh_error
                FROM accounts
                WHERE id = ?
                ''',
                (self.account_id,),
            ).fetchone()
            snapshot_row = db.execute(
                '''
                SELECT status, total_count, success_count, failed_count, error_summary
                FROM token_refresh_state
                WHERE scope_key = 'all_outlook'
                '''
            ).fetchone()

        self.assertEqual(account_row['last_refresh_status'], 'failed')
        self.assertEqual(account_row['last_refresh_error'], 'boom')
        self.assertEqual(snapshot_row['status'], 'failed')
        self.assertEqual(snapshot_row['total_count'], 1)
        self.assertEqual(snapshot_row['success_count'], 0)
        self.assertEqual(snapshot_row['failed_count'], 1)
        self.assertIn('boom', snapshot_row['error_summary'])

    def test_run_full_refresh_rejects_when_another_full_refresh_is_running(self):
        web_outlook_app.token_refresh_run_lock.acquire()
        try:
            with self.assertRaises(web_outlook_app.TokenRefreshInProgressError):
                web_outlook_app.run_full_refresh('scheduled', 'scheduled')
        finally:
            web_outlook_app.token_refresh_run_lock.release()

    def test_stream_full_refresh_events_yields_conflict_when_locked(self):
        web_outlook_app.token_refresh_run_lock.acquire()
        stream = web_outlook_app.stream_full_refresh_events('manual_all', 'manual')
        try:
            first_event = next(stream)
        finally:
            stream.close()
            web_outlook_app.token_refresh_run_lock.release()

        payload = json.loads(first_event.removeprefix('data: ').strip())
        self.assertEqual(payload['type'], 'conflict')
        self.assertIn('已有 Token 全量刷新任务在执行', payload['message'])

    def test_cleanup_refresh_logs_removes_entries_older_than_six_months(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_refresh_logs')
            db.execute(
                '''
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', '-8 months'))
                ''',
                (self.account_id, 'proxy-refresh@outlook.com', 'manual', 'failed', 'old failure')
            )
            db.execute(
                '''
                INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', '-2 months'))
                ''',
                (self.account_id, 'proxy-refresh@outlook.com', 'manual', 'success', None)
            )
            db.commit()

            deleted_count = web_outlook_app.cleanup_refresh_logs()

            remaining_rows = db.execute(
                '''
                SELECT status, error_message
                FROM account_refresh_logs
                ORDER BY created_at ASC, id ASC
                '''
            ).fetchall()

        self.assertEqual(deleted_count, 1)
        self.assertEqual(len(remaining_rows), 1)
        self.assertEqual(remaining_rows[0]['status'], 'success')
        self.assertIsNone(remaining_rows[0]['error_message'])

    def test_refresh_status_list_filters_by_latest_status(self):
        with self.app.app_context():
            self.assertTrue(
                web_outlook_app.add_account(
                    'success-status@example.com',
                    'password123',
                    '24d9a0ed-8787-4584-883c-2fd79308940a',
                    '0.AXEA_success',
                    group_id=self.group_id,
                    remark='成功账号',
                    forward_enabled=False,
                )
            )
            self.assertTrue(
                web_outlook_app.add_account(
                    'never-status@example.com',
                    'password123',
                    '24d9a0ed-8787-4584-883c-2fd79308940a',
                    '0.AXEA_never',
                    group_id=self.group_id,
                    remark='从未刷新账号',
                    forward_enabled=False,
                )
            )
            self.assertTrue(
                web_outlook_app.add_account(
                    'imap-hidden@example.com',
                    'password123',
                    '',
                    '',
                    group_id=self.group_id,
                    remark='不应出现在刷新列表',
                    account_type='imap',
                    provider='custom',
                    imap_host='imap.example.com',
                    imap_port=993,
                    imap_password='imap-secret',
                    forward_enabled=False,
                )
            )

            db = web_outlook_app.get_db()
            db.execute(
                '''
                UPDATE accounts
                SET last_refresh_status = 'failed',
                    last_refresh_error = 'proxy timeout',
                    last_refresh_at = '2026-04-27 10:00:00'
                WHERE id = ?
                ''',
                (self.account_id,),
            )
            db.execute(
                '''
                UPDATE accounts
                SET last_refresh_status = 'success',
                    last_refresh_error = NULL,
                    last_refresh_at = '2026-04-27 11:00:00'
                WHERE email = ?
                ''',
                ('success-status@example.com',),
            )
            db.execute(
                '''
                UPDATE token_refresh_state
                SET trigger_type = 'manual_all',
                    status = 'partial_failed',
                    finished_at = '2026-04-27 11:30:00',
                    total_count = 3,
                    success_count = 1,
                    failed_count = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE scope_key = 'all_outlook'
                '''
            )
            db.commit()

        response = self.client.get('/api/accounts/refresh-status-list?status=failed&q=proxy&page=1&page_size=20')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        self.assertEqual(len(payload['items']), 1)
        self.assertEqual(payload['items'][0]['email'], 'proxy-refresh@outlook.com')
        self.assertEqual(payload['items'][0]['last_refresh_status'], 'failed')
        self.assertEqual(payload['items'][0]['last_refresh_error'], 'proxy timeout')
        self.assertEqual(payload['stats']['total'], 3)
        self.assertEqual(payload['stats']['success_count'], 1)
        self.assertEqual(payload['stats']['failed_count'], 1)
        self.assertEqual(payload['stats']['never_count'], 1)
        self.assertEqual(payload['stats']['last_refresh_status'], 'partial_failed')
        self.assertEqual(payload['stats']['last_refresh_time'], '2026-04-27 11:30:00')

    def test_group_api_persists_proxy_failover_fields(self):
        response = self.client.put(
            f'/api/groups/{self.group_id}',
            json={
                'name': '代理刷新组',
                'description': '测试代理失败后直连重试',
                'color': '#225588',
                'proxy_url': 'socks5://127.0.0.1:1080',
                'fallback_proxy_url_1': 'socks5://127.0.0.1:2080',
                'fallback_proxy_url_2': '直连',
                'sort_position': 1,
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        response = self.client.get(f'/api/groups/{self.group_id}')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['group']['fallback_proxy_url_1'], 'socks5://127.0.0.1:2080')
        self.assertEqual(payload['group']['fallback_proxy_url_2'], '直连')


class TelegramForwardingProxySettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    def test_settings_api_persists_telegram_proxy_url(self):
        response = self.client.put(
            '/api/settings',
            json={
                'telegram_bot_token': '123456:abcdef',
                'telegram_chat_id': '-1001234567890',
                'telegram_proxy_url': 'socks5://127.0.0.1:1080',
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['telegram_proxy_url'], 'socks5://127.0.0.1:1080')

    def test_send_forward_telegram_uses_configured_proxy(self):
        class FakeResponse:
            ok = True

        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting_encrypted('telegram_bot_token', '123456:abcdef'))
            self.assertTrue(web_outlook_app.set_setting('telegram_chat_id', '-1001234567890'))
            self.assertTrue(web_outlook_app.set_setting('telegram_proxy_url', 'socks5://127.0.0.1:1080'))

        with self.app.app_context():
            with patch.object(web_outlook_app.requests, 'request', return_value=FakeResponse()) as mocked_request:
                success = web_outlook_app.send_forward_telegram('telegram proxy test')

        self.assertTrue(success)
        self.assertEqual(mocked_request.call_count, 1)
        self.assertEqual(mocked_request.call_args.args[:2], ('post', 'https://api.telegram.org/bot123456:abcdef/sendMessage'))
        self.assertEqual(
            mocked_request.call_args.kwargs['proxies'],
            {'http': 'socks5://127.0.0.1:1080', 'https': 'socks5://127.0.0.1:1080'},
        )

    def test_settings_api_persists_wecom_webhook_url(self):
        response = self.client.put(
            '/api/settings',
            json={
                'wecom_webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key',
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(
            payload['settings']['wecom_webhook_url'],
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key',
        )

    def test_send_forward_wecom_uses_configured_webhook(self):
        class FakeResponse:
            ok = True

        with self.app.app_context():
            self.assertTrue(
                web_outlook_app.set_setting_encrypted(
                    'wecom_webhook_url',
                    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key',
                )
            )

        with self.app.app_context():
            with patch.object(web_outlook_app.requests, 'request', return_value=FakeResponse()) as mocked_request:
                success = web_outlook_app.send_forward_wecom('wecom webhook test')

        self.assertTrue(success)
        self.assertEqual(mocked_request.call_count, 1)
        self.assertEqual(
            mocked_request.call_args.args[:2],
            ('post', 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key'),
        )
        self.assertEqual(
            mocked_request.call_args.kwargs['json'],
            {'msgtype': 'text', 'text': {'content': 'wecom webhook test'}},
        )


class AppTimezoneSettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    def test_settings_api_persists_app_timezone(self):
        response = self.client.put(
            '/api/settings',
            json={'app_timezone': 'America/Los_Angeles'}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['app_timezone'], 'America/Los_Angeles')

    def test_settings_api_rejects_invalid_app_timezone(self):
        response = self.client.put(
            '/api/settings',
            json={'app_timezone': 'Mars/Olympus_Mons'}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('Invalid time zone', payload['error'])

    def test_settings_api_persists_show_account_created_at(self):
        response = self.client.put(
            '/api/settings',
            json={'show_account_created_at': False}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['show_account_created_at'], 'false')

    def test_validate_cron_uses_requested_timezone(self):
        response = self.client.post(
            '/api/settings/validate-cron',
            json={
                'cron_expression': '0 2 * * *',
                'time_zone': 'UTC',
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['valid'])
        self.assertEqual(payload['time_zone'], 'UTC')
        self.assertTrue(payload['next_run'].endswith('+00:00'))


class MultiChannelForwardingTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM forward_logs')
            db.execute('DELETE FROM forwarding_logs')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_refresh_logs')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

            self.assertTrue(web_outlook_app.set_setting('forward_channels', 'smtp,telegram'))
            self.assertTrue(web_outlook_app.set_setting('email_forward_recipient', 'main@example.com'))
            self.assertTrue(web_outlook_app.set_setting('smtp_host', 'smtp.example.com'))
            self.assertTrue(web_outlook_app.set_setting_encrypted('telegram_bot_token', '123456:abcdef'))
            self.assertTrue(web_outlook_app.set_setting('telegram_chat_id', '-1001234567890'))

            self.assertTrue(web_outlook_app.add_account(
                'multi-channel@example.com',
                'password123',
                'client-id',
                'refresh-token',
                group_id=1,
                forward_enabled=True
            ))
            account = web_outlook_app.get_account_by_email('multi-channel@example.com')
            self.assertIsNotNone(account)
            self.account_id = account['id']
            db.execute(
                'UPDATE accounts SET forward_last_checked_at = NULL WHERE id = ?',
                (self.account_id,),
            )
            db.commit()

    def test_process_forwarding_job_sends_to_all_enabled_channels(self):
        email_item = {
            'id': 'message-1',
            'folder': 'inbox',
            'date': '2026-04-15T07:00:00Z',
        }
        email_detail = {
            'id': 'message-1',
            'subject': 'test subject',
            'from': 'sender@example.com',
            'date': '2026-04-15T07:00:00Z',
            'body': 'hello world',
            'body_type': 'text',
        }

        with patch.object(web_outlook_app, 'fetch_forward_candidates', return_value={'success': True, 'emails': [email_item], 'error': ''}):
            with patch.object(web_outlook_app, 'fetch_forward_detail', return_value=email_detail):
                with patch.object(web_outlook_app, 'send_forward_email', return_value=True) as email_mock:
                    with patch.object(web_outlook_app, 'send_forward_telegram', return_value=True) as tg_mock:
                        web_outlook_app.process_forwarding_job()

        self.assertEqual(email_mock.call_count, 1)
        self.assertEqual(tg_mock.call_count, 1)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = db.execute(
                '''
                SELECT channel, status
                FROM forwarding_logs
                WHERE account_id = ? AND message_id = ?
                ORDER BY channel
                ''',
                (self.account_id, 'message-1'),
            ).fetchall()
            forward_log_rows = db.execute(
                '''
                SELECT channel
                FROM forward_logs
                WHERE account_id = ? AND message_id = ?
                ORDER BY channel
                ''',
                (self.account_id, 'message-1'),
            ).fetchall()

        self.assertEqual(
            [(row['channel'], row['status']) for row in rows],
            [('email', 'success'), ('telegram', 'success')],
        )
        self.assertEqual(
            [row['channel'] for row in forward_log_rows],
            ['email', 'telegram'],
        )

    def test_process_forwarding_job_keeps_retrying_missing_channel_when_other_channel_already_logged(self):
        email_item = {
            'id': 'message-2',
            'folder': 'inbox',
            'date': '2026-04-15T08:00:00Z',
        }
        email_detail = {
            'id': 'message-2',
            'subject': 'retry tg',
            'from': 'sender@example.com',
            'date': '2026-04-15T08:00:00Z',
            'body': 'hello retry',
            'body_type': 'text',
        }

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                'INSERT OR IGNORE INTO forward_logs (account_id, message_id, channel) VALUES (?, ?, ?)',
                (self.account_id, 'message-2', 'email'),
            )
            db.commit()

        with patch.object(web_outlook_app, 'fetch_forward_candidates', return_value={'success': True, 'emails': [email_item], 'error': ''}):
            with patch.object(web_outlook_app, 'fetch_forward_detail', return_value=email_detail):
                with patch.object(web_outlook_app, 'send_forward_email', return_value=True) as email_mock:
                    with patch.object(web_outlook_app, 'send_forward_telegram', return_value=True) as tg_mock:
                        web_outlook_app.process_forwarding_job()

        self.assertEqual(email_mock.call_count, 0)
        self.assertEqual(tg_mock.call_count, 1)

    def test_extract_message_attachments_returns_metadata_and_content(self):
        message = EmailMessage()
        message['Subject'] = 'Attachment Test'
        message['From'] = 'sender@example.com'
        message['To'] = 'user@example.com'
        message.set_content('body text')
        message.add_attachment(
            b'hello attachment',
            maintype='text',
            subtype='plain',
            filename='report.txt',
        )

        parsed = web_outlook_app.email.message_from_bytes(message.as_bytes())
        attachments = web_outlook_app.extract_message_attachments(parsed, include_content=True)

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['id'], 'attachment-1')
        self.assertEqual(attachments[0]['name'], 'report.txt')
        self.assertEqual(attachments[0]['content_type'], 'text/plain')
        self.assertEqual(attachments[0]['content'], b'hello attachment')


if __name__ == '__main__':
    unittest.main()
