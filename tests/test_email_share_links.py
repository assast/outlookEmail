import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta
from urllib.parse import urlparse
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-share-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class EmailShareLinkTests(unittest.TestCase):
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
            db.execute('DELETE FROM email_share_links')
            db.execute('DELETE FROM accounts')
            db.commit()

    def _insert_account(self, email_addr='shared@example.com'):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', 'client-id', 'refresh-token', 1, '', 'active',
                        'outlook', 'outlook', '', 993, '', 0)
                ''',
                (email_addr,)
            )
            db.commit()
            return int(cursor.lastrowid)

    def _create_share(self, account_id, **payload):
        data = {'account_id': account_id, 'duration_minutes': 60}
        data.update(payload)
        response = self.client.post('/api/email-shares', json=data)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        return body['share']

    def _token_from_share_url(self, share_url):
        return urlparse(share_url).path.rstrip('/').split('/')[-1]

    @staticmethod
    def _share_folder_result(emails, method='Graph API', request_method='graph', has_more=False):
        return {
            'success': True,
            'emails': [dict(email) for email in emails],
            'method': method,
            'request_method': request_method,
            'has_more': has_more,
        }

    def _make_share_folder_fetch(self, folder_emails, expected_top, request_method='graph'):
        def fetch(_account, folder, skip, top):
            self.assertEqual(skip, 0)
            self.assertEqual(top, expected_top)
            return self._share_folder_result(
                folder_emails[folder],
                method='Graph API' if request_method == 'graph' else 'IMAP (New)',
                request_method=request_method,
            )

        return fetch

    def test_email_share_schema_migrates_max_email_count_and_preserves_legacy_rows(self):
        account_id = self._insert_account()
        legacy_token = 'legacy-share-token'
        with self.app.app_context():
            db = web_outlook_app.get_db()
            create_sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'email_share_links'"
            ).fetchone()['sql']
            self.assertIn('max_email_count BETWEEN 1 AND 50', create_sql)
            db.execute('DROP TABLE email_share_links')
            db.execute(
                '''
                CREATE TABLE email_share_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    token_encrypted TEXT NOT NULL,
                    expires_at TIMESTAMP,
                    never_expires INTEGER NOT NULL DEFAULT 0,
                    revoked_at TIMESTAMP,
                    last_accessed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
                )
                '''
            )
            db.execute(
                '''
                INSERT INTO email_share_links (
                    account_id, token_hash, token_encrypted, expires_at, never_expires
                )
                VALUES (?, ?, ?, '2099-01-01 00:00:00', 0)
                ''',
                (
                    account_id,
                    web_outlook_app.hash_email_share_token(legacy_token),
                    web_outlook_app.encrypt_data(legacy_token),
                )
            )
            db.commit()

            web_outlook_app.init_db()
            columns = {
                row['name']
                for row in db.execute('PRAGMA table_info(email_share_links)').fetchall()
            }
            migrated_row = db.execute(
                'SELECT max_email_count FROM email_share_links WHERE token_hash = ?',
                (web_outlook_app.hash_email_share_token(legacy_token),)
            ).fetchone()
            self.assertIn('max_email_count', columns)
            self.assertIsNone(migrated_row['max_email_count'])

            web_outlook_app.init_db()

    def test_create_share_validates_and_serializes_email_visibility_limit(self):
        account_id = self._insert_account()
        limited_share = self._create_share(account_id, max_email_count=2)
        unlimited_share = self._create_share(account_id, max_email_count='')

        self.assertEqual(limited_share['max_email_count'], 2)
        self.assertIsNone(unlimited_share['max_email_count'])

        token = self._token_from_share_url(limited_share['share_url'])
        status_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.get_json()['max_email_count'], 2)

        list_response = self.client.get('/api/email-shares')
        self.assertEqual(list_response.status_code, 200)
        shares_by_id = {share['id']: share for share in list_response.get_json()['shares']}
        self.assertEqual(shares_by_id[limited_share['id']]['max_email_count'], 2)
        self.assertIsNone(shares_by_id[unlimited_share['id']]['max_email_count'])

        for invalid_count in (0, -1, 51, '1.5', True):
            response = self.client.post('/api/email-shares', json={
                'account_id': account_id,
                'duration_minutes': 60,
                'max_email_count': invalid_count,
            })
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.get_json()['success'])

    def test_limited_share_global_visibility_blocks_pagination_bypass(self):
        account_id = self._insert_account()
        share = self._create_share(account_id, max_email_count=2)
        token = self._token_from_share_url(share['share_url'])
        folder_emails = {
            'inbox': [
                {'id': 'inbox-2', 'date': '2026-01-02T12:02:00Z', 'id_mode': 'graph'},
                {'id': 'inbox-1', 'date': '2026-01-02T12:01:00Z', 'id_mode': 'graph'},
            ],
            'junkemail': [
                {'id': 'junk-old', 'date': '2026-01-02T11:59:00Z', 'id_mode': 'graph'},
            ],
        }

        with patch.object(
            web_outlook_app,
            'fetch_account_emails',
            side_effect=self._make_share_folder_fetch(folder_emails, expected_top=web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE),
        ) as list_mock:
            first_response = self.client.get(
                f'/api/share/email/{token}/emails?folder=inbox&skip=0&top=1'
            )
            second_response = self.client.get(
                f'/api/share/email/{token}/emails?folder=inbox&skip=1&top=1'
            )
            overflow_response = self.client.get(
                f'/api/share/email/{token}/emails?folder=inbox&skip=2&top=50'
            )

        first_data = first_response.get_json()
        second_data = second_response.get_json()
        overflow_data = overflow_response.get_json()
        self.assertEqual([email['id'] for email in first_data['emails']], ['inbox-2'])
        self.assertTrue(first_data['has_more'])
        self.assertEqual([email['id'] for email in second_data['emails']], ['inbox-1'])
        self.assertFalse(second_data['has_more'])
        self.assertEqual(overflow_data['emails'], [])
        self.assertFalse(overflow_data['has_more'])
        self.assertEqual(list_mock.call_count, 4)
        self.assertTrue(all(
            call.args[2:] == (0, web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE)
            for call in list_mock.call_args_list
        ))
        self.assertNotIn('_share_request_method', first_data['emails'][0])

    def test_limited_share_detail_requires_visible_message_id_and_mode(self):
        account_id = self._insert_account()
        share = self._create_share(account_id, max_email_count=1)
        token = self._token_from_share_url(share['share_url'])
        folder_emails = {
            'inbox': [
                {'id': 'allowed', 'date': '2026-01-02T12:02:00Z', 'id_mode': 'uid'},
            ],
            'junkemail': [
                {'id': 'outside', 'date': '2026-01-02T12:01:00Z', 'id_mode': 'uid'},
            ],
        }

        with patch.object(
            web_outlook_app,
            'fetch_account_emails',
            side_effect=self._make_share_folder_fetch(
                folder_emails, expected_top=web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE, request_method='imap'
            ),
        ), patch.object(
            web_outlook_app,
            'fetch_email_detail_for_account',
            return_value={'success': True, 'email': {'id': 'allowed'}},
        ) as detail_mock:
            allowed_response = self.client.get(
                f'/api/share/email/{token}/email/allowed?folder=inbox&id_mode=uid&method=graph'
            )
            self.assertEqual(allowed_response.status_code, 200)
            self.assertTrue(allowed_response.get_json()['success'])
            self.assertEqual(detail_mock.call_args.args[1:], ('allowed', 'imap', 'inbox', 'uid'))
            self.assertEqual(detail_mock.call_args.kwargs, {
                'strict_id_mode': True,
                'force_method': True,
            })

            detail_mock.reset_mock()
            outside_response = self.client.get(
                f'/api/share/email/{token}/email/outside?folder=junkemail&id_mode=uid'
            )
            mode_bypass_response = self.client.get(
                f'/api/share/email/{token}/email/allowed?folder=inbox&id_mode=sequence'
            )

        self.assertEqual(outside_response.status_code, 404)
        self.assertEqual(mode_bypass_response.status_code, 404)
        detail_mock.assert_not_called()

    def test_limited_share_visibility_is_dynamic_across_folders_with_stable_ordering(self):
        account = {'id': 42, 'email': 'shared@example.com'}
        folder_emails = {
            'inbox': [
                {'id': 'inbox-a', 'date': '2026-01-02T12:00:00Z', 'id_mode': 'graph'},
                {'id': 'inbox-b', 'date': '2026-01-02T12:00:00Z', 'id_mode': 'graph'},
            ],
            'junkemail': [
                {'id': 'junk-old', 'date': '2026-01-02T11:00:00Z', 'id_mode': 'graph'},
            ],
        }

        with patch.object(
            web_outlook_app,
            'fetch_account_emails',
            side_effect=self._make_share_folder_fetch(folder_emails, expected_top=web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE),
        ):
            initial_visible = web_outlook_app.resolve_email_share_visible_messages(account, 2)
            folder_emails['junkemail'] = [
                {'id': 'junk-new', 'date': '2026-01-02T13:00:00Z', 'id_mode': 'graph'},
            ]
            updated_visible = web_outlook_app.resolve_email_share_visible_messages(account, 2)

        self.assertEqual(
            [email['id'] for email in initial_visible['emails']],
            ['inbox-b', 'inbox-a'],
        )
        self.assertEqual(
            [email['id'] for email in updated_visible['emails']],
            ['junk-new', 'inbox-b'],
        )

    def test_limited_share_expands_tied_timestamp_candidates_before_sorting(self):
        account = {'id': 42, 'email': 'shared@example.com'}
        tied_date = '2026-01-02T12:00:00Z'
        inbox_first_page = [
            {'id': 'a', 'date': tied_date, 'id_mode': 'graph'},
            *[
                {'id': f'{index:02d}', 'date': tied_date, 'id_mode': 'graph'}
                for index in range(web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE - 1)
            ],
        ]
        calls = []

        def fetch(_account, folder, skip, top):
            calls.append((folder, skip, top))
            self.assertTrue(web_outlook_app.email_share_stable_ids_context.get())
            self.assertEqual(top, web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE)
            if folder == 'inbox' and skip == 0:
                return self._share_folder_result(inbox_first_page, has_more=True)
            if folder == 'inbox' and skip == web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE:
                return self._share_folder_result([
                    {'id': 'b', 'date': tied_date, 'id_mode': 'graph'},
                ])
            if folder == 'junkemail' and skip == 0:
                return self._share_folder_result([])
            self.fail(f'Unexpected candidate page: {(folder, skip, top)}')

        with patch.object(web_outlook_app, 'fetch_account_emails', side_effect=fetch):
            visible_result = web_outlook_app.resolve_email_share_visible_messages(account, 1)

        self.assertTrue(visible_result['success'])
        self.assertEqual([email['id'] for email in visible_result['emails']], ['b'])
        self.assertEqual(calls, [
            ('inbox', 0, web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE),
            ('junkemail', 0, web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE),
            ('inbox', web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE,
             web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE),
        ])
        self.assertNotIn('_disable_authorization_type_record', account)
        self.assertFalse(web_outlook_app.email_share_stable_ids_context.get())

    def test_limited_share_rejects_incomplete_candidate_page(self):
        account = {'id': 42, 'email': 'shared@example.com'}

        def fetch(_account, folder, skip, top):
            if folder == 'inbox':
                return self._share_folder_result([
                    {'id': 'inbox-new', 'date': '2026-01-02T12:00:00Z', 'id_mode': 'graph'},
                ], has_more=True)
            return self._share_folder_result([])

        with patch.object(web_outlook_app, 'fetch_account_emails', side_effect=fetch):
            visible_result = web_outlook_app.resolve_email_share_visible_messages(account, 1)

        self.assertFalse(visible_result['success'])
        self.assertEqual(visible_result['error'], '无法验证分享链接可访问邮件范围')

    def test_limited_share_rejects_excessive_tied_timestamp_candidates(self):
        account = {'id': 42, 'email': 'shared@example.com'}
        tied_date = '2026-01-02T12:00:00Z'

        def fetch(_account, folder, skip, top):
            if folder == 'junkemail':
                return self._share_folder_result([])
            return self._share_folder_result([
                {
                    'id': f'inbox-{skip + index}',
                    'date': tied_date,
                    'id_mode': 'graph',
                }
                for index in range(top)
            ], has_more=True)

        with patch.object(web_outlook_app, 'fetch_account_emails', side_effect=fetch):
            visible_result = web_outlook_app.resolve_email_share_visible_messages(account, 1)

        self.assertFalse(visible_result['success'])
        self.assertEqual(visible_result['error'], '无法验证分享链接可访问邮件范围')

    def test_limited_share_does_not_record_mixed_mail_channels(self):
        account = {
            'id': 42,
            'email': 'shared@example.com',
            'client_id': 'client-id',
            'refresh_token': 'refresh-token',
            'account_type': 'outlook',
            'authorization_type': '',
        }
        graph_email = {
            'id': 'graph-inbox',
            'subject': 'Graph inbox',
            'from': {'emailAddress': {'address': 'sender@example.com'}},
            'toRecipients': [],
            'receivedDateTime': '2026-01-02T12:02:00Z',
            'isRead': False,
            'hasAttachments': False,
            'bodyPreview': '',
        }

        def graph_fetch(_client_id, _refresh_token, folder, *_args):
            if folder == 'inbox':
                return {'success': True, 'emails': [graph_email]}
            return {'success': False, 'error': 'Graph unavailable'}

        def imap_fetch(*_args, **_kwargs):
            self.assertTrue(web_outlook_app.email_share_stable_ids_context.get())
            return {
                'success': True,
                'emails': [{
                    'id': 'imap-junk',
                    'date': '2026-01-02T12:01:00Z',
                    'id_mode': 'uid',
                }],
                'has_more': False,
            }

        with patch.object(web_outlook_app, 'get_emails_graph', side_effect=graph_fetch), \
             patch.object(web_outlook_app, 'get_emails_imap_with_server', side_effect=imap_fetch), \
             patch.object(web_outlook_app, 'record_account_authorization_type') as record_channel:
            visible_result = web_outlook_app.resolve_email_share_visible_messages(account, 2)

        self.assertTrue(visible_result['success'])
        self.assertEqual(
            [email['id'] for email in visible_result['emails']],
            ['graph-inbox', 'imap-junk'],
        )
        record_channel.assert_not_called()
        self.assertEqual(account['authorization_type'], '')
        self.assertNotIn('_disable_authorization_type_record', account)
        self.assertFalse(web_outlook_app.email_share_stable_ids_context.get())

    def test_limited_share_rejects_nonstable_imap_candidates(self):
        account_id = self._insert_account()
        share = self._create_share(account_id, max_email_count=1)
        token = self._token_from_share_url(share['share_url'])
        folder_emails = {
            'inbox': [
                {'id': '10', 'date': '2026-01-02T12:02:00Z', 'id_mode': 'sequence'},
            ],
            'junkemail': [],
        }

        with patch.object(
            web_outlook_app,
            'fetch_account_emails',
            side_effect=self._make_share_folder_fetch(
                folder_emails,
                expected_top=web_outlook_app.EMAIL_SHARE_CANDIDATE_PAGE_SIZE,
                request_method='imap',
            ),
        ) as list_mock:
            response = self.client.get(f'/api/share/email/{token}/emails?folder=inbox')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['success'])
        self.assertEqual(response.get_json()['error'], '无法验证分享链接可访问邮件范围')
        self.assertEqual(list_mock.call_count, 1)

    def test_limited_share_imap_candidates_use_uid_arrival_sort(self):
        class FakeImapConnection:
            def __init__(self):
                self.uid_calls = []

            def uid(self, *args):
                self.uid_calls.append(args)
                return 'OK', [b'90 89 88']

        connection = FakeImapConnection()
        message_ids, attempts = web_outlook_app.search_imap_message_uids_by_arrival(connection)

        self.assertEqual(message_ids, [b'90', b'89', b'88'])
        self.assertEqual(connection.uid_calls, [
            ('SORT', '(REVERSE ARRIVAL)', 'UTF-8', 'ALL'),
        ])
        self.assertEqual(attempts[0]['mode'], 'uid-arrival-sort')

    def test_limited_share_forced_detail_channel_does_not_record_preference(self):
        account = {
            'id': 42,
            'email': 'shared@example.com',
            'client_id': 'client-id',
            'refresh_token': 'refresh-token',
            'account_type': 'outlook',
            'authorization_type': '',
        }

        with patch.object(
            web_outlook_app,
            'fetch_graph_detail_response',
            return_value={'success': True, 'email': {'id': 'allowed'}},
        ), patch.object(web_outlook_app, 'record_account_authorization_type') as record_channel:
            result = web_outlook_app.fetch_email_detail_for_account(
                account,
                'allowed',
                method='graph',
                folder='inbox',
                id_mode='graph',
                force_method=True,
            )

        self.assertTrue(result['success'])
        record_channel.assert_not_called()

    def test_limited_share_outlook_imap_list_uses_uid_arrival_sort(self):
        raw_email = (
            b'Subject: shared code\r\n'
            b'From: sender@example.com\r\n'
            b'To: shared@example.com\r\n'
            b'\r\n'
            b'123456\r\n'
        )

        class FakeImapConnection:
            def __init__(self):
                self.uid_calls = []
                self.fetch_calls = []
                self.logged_out = False

            def authenticate(self, *_args):
                return 'OK', [b'authenticated']

            def uid(self, command, *args):
                self.uid_calls.append((command, *args))
                if command == 'SORT':
                    return 'OK', [b'42']
                if command == 'FETCH':
                    return 'OK', [(
                        b'42 (INTERNALDATE "14-Apr-2026 10:00:00 +0000" RFC822 {64}',
                        raw_email,
                    )]
                return 'NO', []

            def fetch(self, *args):
                self.fetch_calls.append(args)
                return 'NO', []

            def logout(self):
                self.logged_out = True
                return 'BYE', [b'logout']

        connection = FakeImapConnection()
        context_token = web_outlook_app.email_share_stable_ids_context.set(True)
        try:
            with patch.object(
                web_outlook_app,
                'get_access_token_imap_result',
                return_value={'success': True, 'access_token': 'token'},
            ), patch.object(
                web_outlook_app.imaplib,
                'IMAP4_SSL',
                return_value=connection,
            ), patch.object(
                web_outlook_app,
                'resolve_imap_folder',
                return_value=('INBOX', {}),
            ):
                result = web_outlook_app.get_emails_imap_with_server(
                    'shared@example.com',
                    'client-id',
                    'refresh-token',
                    top=1,
                )
        finally:
            web_outlook_app.email_share_stable_ids_context.reset(context_token)

        self.assertTrue(result['success'])
        self.assertEqual(result['emails'][0]['id'], '42')
        self.assertEqual(result['emails'][0]['id_mode'], 'uid')
        self.assertFalse(result['has_more'])
        self.assertEqual(connection.uid_calls, [
            ('SORT', '(REVERSE ARRIVAL)', 'UTF-8', 'ALL'),
            ('FETCH', b'42', '(INTERNALDATE RFC822)'),
        ])
        self.assertEqual(connection.fetch_calls, [])
        self.assertTrue(connection.logged_out)

    def test_limited_share_strict_imap_lookup_never_falls_back_to_sequence(self):
        class FakeImapConnection:
            def __init__(self):
                self.uid_calls = []
                self.fetch_calls = []

            def uid(self, *args):
                self.uid_calls.append(args)
                return 'NO', []

            def fetch(self, *args):
                self.fetch_calls.append(args)
                return 'OK', [(b'ignored', b'outside-range-message')]

        connection = FakeImapConnection()
        status, _data, mode, attempts = web_outlook_app.fetch_imap_message(
            connection,
            '10',
            '(RFC822)',
            preferred_mode='uid',
            allow_id_mode_fallback=False,
        )

        self.assertEqual(status, 'NO')
        self.assertEqual(mode, '')
        self.assertEqual(len(attempts), 1)
        self.assertEqual(connection.uid_calls, [('FETCH', '10', '(RFC822)')])
        self.assertEqual(connection.fetch_calls, [])

    def test_persisted_invalid_email_visibility_limit_fails_closed(self):
        account_id = self._insert_account()
        invalid_limits = {
            'invalid-limit-zero': 0,
            'invalid-limit-too-large': 51,
            'invalid-limit-text': 'not-an-integer',
        }
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DROP TABLE email_share_links')
            db.execute(
                '''
                CREATE TABLE email_share_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    token_encrypted TEXT NOT NULL,
                    expires_at TIMESTAMP,
                    never_expires INTEGER NOT NULL DEFAULT 0,
                    max_email_count INTEGER,
                    revoked_at TIMESTAMP,
                    last_accessed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
                )
                '''
            )
            for invalid_token, invalid_limit in invalid_limits.items():
                db.execute(
                    '''
                    INSERT INTO email_share_links (
                        account_id, token_hash, token_encrypted, expires_at,
                        never_expires, max_email_count
                    )
                    VALUES (?, ?, ?, '2099-01-01 00:00:00', 0, ?)
                    ''',
                    (
                        account_id,
                        web_outlook_app.hash_email_share_token(invalid_token),
                        web_outlook_app.encrypt_data(invalid_token),
                        invalid_limit,
                    )
                )
            db.commit()
            web_outlook_app.init_db()

        with patch.object(web_outlook_app, 'fetch_account_emails') as fetch_mock:
            for invalid_token in invalid_limits:
                status_response = self.client.get(f'/api/share/email/{invalid_token}/status')
                emails_response = self.client.get(
                    f'/api/share/email/{invalid_token}/emails?folder=inbox&skip=50'
                )

                self.assertEqual(status_response.status_code, 404)
                self.assertEqual(status_response.get_json()['status'], 'invalid')
                self.assertEqual(emails_response.status_code, 404)
                self.assertEqual(emails_response.get_json()['status'], 'invalid')
        fetch_mock.assert_not_called()

    def test_create_timed_and_never_expiring_shares_and_list_copy_urls(self):
        account_id = self._insert_account()

        timed_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'duration_minutes': 60}
        )
        self.assertEqual(timed_response.status_code, 200)
        timed_share = timed_response.get_json()['share']
        self.assertFalse(timed_share['never_expires'])
        self.assertTrue(timed_share['expires_at'])
        self.assertIn('/share/email/', timed_share['share_url'])

        never_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': True, 'duration_minutes': -1}
        )
        self.assertEqual(never_response.status_code, 200)
        never_share = never_response.get_json()['share']
        self.assertTrue(never_share['never_expires'])
        self.assertIsNone(never_share['expires_at'])
        self.assertIn('/share/email/', never_share['share_url'])

        missing_response = self.client.post(
            '/api/email-shares',
            json={'email': 'missing@example.com', 'duration_minutes': 60}
        )
        self.assertEqual(missing_response.status_code, 404)

        invalid_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'duration_minutes': 0}
        )
        self.assertEqual(invalid_response.status_code, 400)

        list_response = self.client.get('/api/email-shares')
        self.assertEqual(list_response.status_code, 200)
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 2)
        self.assertTrue(all(share['share_url'] for share in shares))

    def test_create_share_strictly_parses_never_expires(self):
        account_id = self._insert_account()

        string_false_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': 'false', 'duration_minutes': 30}
        )
        self.assertEqual(string_false_response.status_code, 200)
        string_false_share = string_false_response.get_json()['share']
        self.assertFalse(string_false_share['never_expires'])
        self.assertTrue(string_false_share['expires_at'])

        invalid_bool_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': 'maybe', 'duration_minutes': 30}
        )
        self.assertEqual(invalid_bool_response.status_code, 400)

    def test_list_shares_filters_by_positive_account_id_only(self):
        account_id = self._insert_account('shared@example.com')
        other_account_id = self._insert_account('other@example.com')
        self._create_share(account_id)
        self._create_share(other_account_id)

        filtered_response = self.client.get(f'/api/email-shares?account_id={account_id}')
        self.assertEqual(filtered_response.status_code, 200)
        filtered_shares = filtered_response.get_json()['shares']
        self.assertEqual(len(filtered_shares), 1)
        self.assertEqual(filtered_shares[0]['account_id'], account_id)

        zero_response = self.client.get('/api/email-shares?account_id=0')
        self.assertEqual(zero_response.status_code, 400)

        invalid_response = self.client.get('/api/email-shares?account_id=not-a-number')
        self.assertEqual(invalid_response.status_code, 400)

    def test_cancel_expired_never_expiring_and_invalid_token_status(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        cancel_response = self.client.post(f"/api/email-shares/{share['id']}/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.get_json()['share']['status'], 'revoked')

        repeat_cancel_response = self.client.post(f"/api/email-shares/{share['id']}/cancel")
        self.assertEqual(repeat_cancel_response.status_code, 200)
        self.assertEqual(repeat_cancel_response.get_json()['share']['status'], 'revoked')

        revoked_status = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(revoked_status.status_code, 404)
        self.assertEqual(revoked_status.get_json()['status'], 'revoked')

        expired_token = 'expired-token'
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO email_share_links (
                    account_id, token_hash, token_encrypted, expires_at, never_expires
                )
                VALUES (?, ?, ?, '2000-01-01 00:00:00', 0)
                ''',
                (
                    account_id,
                    web_outlook_app.hash_email_share_token(expired_token),
                    web_outlook_app.encrypt_data(expired_token),
                )
            )
            db.commit()

        expired_status = self.client.get(f'/api/share/email/{expired_token}/status')
        self.assertEqual(expired_status.status_code, 404)
        self.assertEqual(expired_status.get_json()['status'], 'expired')

        never_share = self._create_share(account_id, never_expires=True, duration_minutes=-1)
        never_token = self._token_from_share_url(never_share['share_url'])
        never_status = self.client.get(f'/api/share/email/{never_token}/status')
        self.assertEqual(never_status.status_code, 200)
        self.assertTrue(never_status.get_json()['never_expires'])

        invalid_status = self.client.get('/api/share/email/not-a-real-token/status')
        self.assertEqual(invalid_status.status_code, 404)
        self.assertEqual(invalid_status.get_json()['status'], 'invalid')

    def test_anonymous_share_list_and_detail_are_bound_to_shared_account(self):
        account_id = self._insert_account('shared@example.com')
        self._insert_account('other@example.com')
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value={
            'success': True,
            'emails': [{'id': 'msg-1', 'subject': 'Shared Mail', 'folder': 'inbox'}],
            'method': 'Graph API',
            'has_more': False,
        }) as list_mock:
            list_response = self.client.get(f'/api/share/email/{token}/emails?folder=inbox')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()['emails'][0]['subject'], 'Shared Mail')
        self.assertEqual(list_mock.call_args.args[0]['email'], 'shared@example.com')

        forbidden_response = self.client.get(
            f'/api/share/email/{token}/emails?email=other@example.com'
        )
        self.assertEqual(forbidden_response.status_code, 403)

        with patch.object(web_outlook_app, 'fetch_email_detail_for_account', return_value={
            'success': True,
            'email': {'id': 'msg-1', 'subject': 'Detail'}
        }) as detail_mock:
            detail_response = self.client.get(f'/api/share/email/{token}/email/msg-1?folder=inbox')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.get_json()['email']['subject'], 'Detail')
        self.assertEqual(detail_mock.call_args.args[0]['email'], 'shared@example.com')

    def test_anonymous_share_rejects_unlisted_folders(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        with patch.object(web_outlook_app, 'fetch_account_emails') as list_mock:
            deleted_response = self.client.get(f'/api/share/email/{token}/emails?folder=deleteditems')
            all_response = self.client.get(f'/api/share/email/{token}/emails?folder=all')
        self.assertEqual(deleted_response.status_code, 400)
        self.assertEqual(all_response.status_code, 400)
        list_mock.assert_not_called()

        with patch.object(web_outlook_app, 'fetch_email_detail_for_account') as detail_mock:
            detail_response = self.client.get(
                f'/api/share/email/{token}/email/msg-1?folder=deleteditems'
            )
        self.assertEqual(detail_response.status_code, 400)
        detail_mock.assert_not_called()

    def test_share_access_timestamp_is_throttled(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        first_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(first_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            first_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            recent_timestamp = first_row['last_accessed_at']

        second_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(second_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            second_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            self.assertEqual(second_row['last_accessed_at'], recent_timestamp)

            stale_timestamp = (
                web_outlook_app.utc_now_naive()
                - timedelta(seconds=web_outlook_app.EMAIL_SHARE_ACCESS_TOUCH_MIN_SECONDS + 30)
            ).strftime('%Y-%m-%d %H:%M:%S')
            db.execute(
                'UPDATE email_share_links SET last_accessed_at = ? WHERE id = ?',
                (stale_timestamp, share['id'])
            )
            db.commit()

        third_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(third_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            third_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            self.assertNotEqual(third_row['last_accessed_at'], stale_timestamp)

    def test_share_access_does_not_grant_management_or_write_permissions(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        anonymous = self.app.test_client()
        management_response = anonymous.get('/api/email-shares')
        self.assertEqual(management_response.status_code, 401)

        write_response = anonymous.post(f'/api/share/email/{token}/emails')
        self.assertEqual(write_response.status_code, 405)

        admin_write_response = anonymous.post('/api/emails/delete', json={
            'email': 'shared@example.com',
            'ids': ['msg-1'],
        })
        self.assertEqual(admin_write_response.status_code, 401)

    def test_delete_and_batch_operations_on_shares(self):
        account_id = self._insert_account()
        share1 = self._create_share(account_id)
        share2 = self._create_share(account_id)
        share3 = self._create_share(account_id)

        # test single delete
        delete_response = self.client.delete(f'/api/email-shares/{share1["id"]}')
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.get_json()['success'])

        # verify deleted
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 2)
        self.assertNotIn(share1['id'], [s['id'] for s in shares])

        # test batch cancel
        batch_cancel_response = self.client.post('/api/email-shares/batch-cancel', json={
            'share_ids': [share2['id'], share3['id']]
        })
        self.assertEqual(batch_cancel_response.status_code, 200)
        self.assertTrue(batch_cancel_response.get_json()['success'])

        # verify cancelled
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        for s in shares:
            if s['id'] in [share2['id'], share3['id']]:
                self.assertEqual(s['status'], 'revoked')

        # test batch delete
        batch_delete_response = self.client.post('/api/email-shares/batch-delete', json={
            'share_ids': [share2['id'], share3['id']]
        })
        self.assertEqual(batch_delete_response.status_code, 200)
        self.assertTrue(batch_delete_response.get_json()['success'])

        # verify deleted
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 0)


class EmailShareFrontendContractTests(unittest.TestCase):
    def test_admin_ui_contains_share_entry_points(self):
        layout = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')
        dialogs = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-primary.html').read_text(encoding='utf-8')
        groups_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '02-groups.js').read_text(encoding='utf-8')
        shares_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '11-email-shares.js').read_text(encoding='utf-8')

        self.assertIn('emailShareManagementBtn', layout)
        self.assertIn('createEmailShareModal', dialogs)
        self.assertIn('emailShareManagementModal', dialogs)
        self.assertIn('data-account-action="share"', groups_js)
        self.assertIn('function createEmailShare()', shares_js)
        self.assertIn('function cancelEmailShare', shares_js)
        self.assertIn('emailShareVisibilityMode', dialogs)
        self.assertIn('emailShareMaxEmailCount', dialogs)
        self.assertIn('emailShareRollingWarning', dialogs)
        self.assertIn('max_email_count: maxEmailCount', shares_js)
        self.assertIn('formatEmailShareVisibility', shares_js)

    def test_share_page_contains_read_only_shell(self):
        template = pathlib.Path(ROOT_DIR, 'templates', 'email_share.html').read_text(encoding='utf-8')
        share_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'email-share.js').read_text(encoding='utf-8')
        share_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'email-share.css').read_text(encoding='utf-8')

        self.assertIn('shareEmailList', template)
        self.assertIn('shareEmailDetail', template)
        self.assertIn('shareVisibilityHint', template)
        self.assertIn('/api/share/email/', share_js)
        self.assertIn('renderShareVisibilityHint(status.max_email_count)', share_js)
        self.assertIn('仅显示收件箱和垃圾邮件中当前最新 ${count} 封邮件', share_js)
        self.assertIn('.overlay-screen[hidden]', share_css)
        self.assertNotIn("shareStatusAttr !== 'active'", share_js)
        self.assertNotIn('/api/emails/delete', share_js)
        self.assertNotIn('/api/email-shares', share_js)


if __name__ == '__main__':
    unittest.main()
