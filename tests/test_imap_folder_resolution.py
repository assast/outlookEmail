import importlib
import json
import os
import tempfile
import threading
import unittest
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

    def logout(self):
        self.logged_out = True
        return 'BYE', [b'logout']


class ImapFolderResolutionTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
