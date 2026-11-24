import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-not-junk-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class NotJunkActionTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM email_share_links')
            db.execute('DELETE FROM accounts')
            db.execute('DELETE FROM retained_normal_mail_messages')
            db.commit()

    # ---------- 辅助 ----------
    def _insert_account(self, email_addr='shared@example.com', account_type='outlook'):
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
                        ?, 'outlook', '', 993, '', 0)
                ''',
                (email_addr, account_type)
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
        return body['share']['share_url'].rstrip('/').split('/')[-1]

    def _insert_cached_row(self, account_id, folder, message_id, id_mode='graph'):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode, subject, sender,
                    received_at, received_at_sort, list_cached, body_cached
                ) VALUES (?, ?, ?, ?, 's', 'f', '2026-01-01', 1, 1, 0)
                ''',
                (account_id, folder, message_id, id_mode),
            )
            db.commit()

    def _cached_rows(self, account_id):
        with self.app.app_context():
            return web_outlook_app.get_db().execute(
                'SELECT folder, provider_message_id FROM retained_normal_mail_messages '
                'WHERE account_id = ? ORDER BY provider_message_id', (account_id,)
            ).fetchall()

    # ---------- 前端结构 ----------
    def test_share_page_has_mobile_folder_tabs(self):
        template = pathlib.Path(ROOT_DIR, 'templates', 'email_share.html').read_text(encoding='utf-8')
        css = pathlib.Path(ROOT_DIR, 'static', 'css', 'email-share.css').read_text(encoding='utf-8')
        share_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'email-share.js').read_text(encoding='utf-8')

        self.assertIn('shareFolderTabs', template)
        self.assertIn('data-folder="junkemail"', template)
        self.assertIn('folder-tab', template)
        self.assertIn('.folder-tabs', css)
        self.assertIn('@media (max-width: 1024px)', css)
        self.assertIn('markEmailNotJunk', share_js)
        self.assertIn('/not-junk', share_js)

    def test_admin_toolbar_has_not_junk_button(self):
        layout = pathlib.Path(
            ROOT_DIR, 'templates', 'partials', 'index', 'layout.html'
        ).read_text(encoding='utf-8')
        emails_js = pathlib.Path(
            ROOT_DIR, 'static', 'js', 'index', '05-emails.js'
        ).read_text(encoding='utf-8')

        self.assertIn('markNotJunkBtn', layout)
        self.assertIn('markCurrentEmailNotJunk', layout)
        self.assertIn('markCurrentEmailNotJunk', emails_js)
        self.assertIn('/api/emails/not-junk', emails_js)
        self.assertIn('invalidateEmailListCache(currentAccount, \'junkemail\')', emails_js)

    def test_share_page_renders_mobile_folder_tabs(self):
        account_id = self._insert_account()
        token = self._create_share(account_id)
        response = self.client.get('/share/email/%s' % token)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('shareFolderTabs', html)
        self.assertIn('data-folder="junkemail"', html)

    def test_admin_page_renders_not_junk_button(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('markNotJunkBtn', html)

    # ---------- 分享页接口 ----------
    def test_share_not_junk_moves_message_and_clears_cached_row(self):
        account_id = self._insert_account()
        token = self._create_share(account_id)
        self._insert_cached_row(account_id, 'junkemail', 'msg-1')
        move_result = {
            'success': True, 'success_count': 1, 'failed_count': 0,
            'moved_ids': ['msg-1'], 'new_message_ids': ['new-1'], 'errors': [],
        }
        with patch.object(
            web_outlook_app, 'move_account_emails_to_folder', return_value=move_result
        ) as move_mock:
            response = self.client.post(
                '/api/share/email/%s/not-junk' % token,
                json={'items': [{'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'}]},
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['moved_ids'], ['msg-1'])
        self.assertEqual(body['cached_rows_deleted'], 1)
        move_mock.assert_called_once()
        self.assertEqual(self._cached_rows(account_id), [])

    def test_share_not_junk_rejects_non_junk_folder(self):
        account_id = self._insert_account()
        token = self._create_share(account_id)
        response = self.client.post(
            '/api/share/email/%s/not-junk' % token,
            json={'items': [{'id': 'msg-1', 'folder': 'inbox'}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_share_not_junk_rejects_invalid_share(self):
        response = self.client.post(
            '/api/share/email/not-a-real-token/not-junk',
            json={'items': [{'id': 'msg-1', 'folder': 'junkemail'}]},
        )
        self.assertEqual(response.status_code, 404)

    def test_limited_share_rejects_message_outside_visible_window(self):
        account_id = self._insert_account()
        token = self._create_share(account_id, max_email_count=5)
        with patch.object(
            web_outlook_app, 'resolve_email_share_visible_messages',
            return_value={'success': True, 'emails': [
                {'id': 'visible-1', 'folder': 'junkemail', 'id_mode': 'graph'},
            ]},
        ), patch.object(web_outlook_app, 'move_account_emails_to_folder') as move_mock:
            response = self.client.post(
                '/api/share/email/%s/not-junk' % token,
                json={'items': [{'id': 'hidden-1', 'folder': 'junkemail', 'id_mode': 'graph'}]},
            )
        self.assertEqual(response.status_code, 404)
        move_mock.assert_not_called()

    # ---------- 后台接口 ----------
    def test_admin_not_junk_requires_login(self):
        anonymous = self.app.test_client()
        response = anonymous.post(
            '/api/emails/not-junk',
            json={'email': 'shared@example.com', 'items': [{'id': 'msg-1', 'folder': 'junkemail'}]},
        )
        self.assertIn(response.status_code, (302, 401, 403))

    def test_admin_not_junk_moves_message(self):
        account_id = self._insert_account('shared@example.com')
        self._insert_cached_row(account_id, 'junkemail', 'msg-1')
        move_result = {
            'success': True, 'success_count': 1, 'failed_count': 0,
            'moved_ids': ['msg-1'], 'new_message_ids': [], 'errors': [],
        }
        with patch.object(
            web_outlook_app, 'move_account_emails_to_folder', return_value=move_result
        ):
            response = self.client.post(
                '/api/emails/not-junk',
                json={
                    'email': 'shared@example.com',
                    'items': [{'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'}],
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(self._cached_rows(account_id), [])

    # ---------- 搬移实现 ----------
    def test_graph_move_uses_batch_requests(self):
        items = [{'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'}]
        with patch.object(
            web_outlook_app, 'get_access_token_graph', return_value='token'
        ), patch.object(
            web_outlook_app, 'request_with_proxy_failover',
            return_value=_FakeResponse(200, {'responses': [
                {'id': '0', 'status': 201, 'body': {'id': 'new-1'}},
            ]}),
        ) as request_mock:
            result = web_outlook_app.move_emails_graph(
                'client-id', 'refresh-token', items, destination='inbox'
            )
        self.assertTrue(result['success'])
        self.assertEqual(result['moved_ids'], ['msg-1'])
        self.assertEqual(result['new_message_ids'], ['new-1'])
        request_args, request_kwargs = request_mock.call_args
        self.assertEqual(request_args[1], 'https://graph.microsoft.com/v1.0/$batch')
        sent = request_kwargs['json']['requests'][0]
        self.assertEqual(sent['method'], 'POST')
        self.assertIn('/move', sent['url'])
        self.assertEqual(sent['body'], {'destinationId': 'inbox'})

    def test_graph_move_reports_batch_failure(self):
        items = [{'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'}]
        with patch.object(
            web_outlook_app, 'get_access_token_graph', return_value='token'
        ), patch.object(
            web_outlook_app, 'request_with_proxy_failover',
            return_value=_FakeResponse(200, {'responses': [
                {'id': '0', 'status': 403, 'body': {'error': {'message': 'denied'}}},
            ]}),
        ):
            result = web_outlook_app.move_emails_graph(
                'client-id', 'refresh-token', items, destination='inbox'
            )
        self.assertFalse(result['success'])
        self.assertEqual(result['failed_count'], 1)

    def test_imap_move_appends_with_internal_date_and_deletes_source(self):
        calls = []

        class FakeMail:
            def uid(self, command, *args):
                calls.append((command, args))
                if command == 'FETCH' and args[1] == '(RFC822.SIZE)':
                    return 'OK', [b'1 (RFC822.SIZE 2048)']
                if command == 'FETCH' and args[1] == '(INTERNALDATE RFC822)':
                    return 'OK', [(
                        b'1 (INTERNALDATE "24-Nov-2026 01:42:56 +0000" RFC822 {11}',
                        b'Subject: x',
                    )]
                return 'OK', [b'']

            def append(self, mailbox, flags, date_time, message):
                calls.append(('APPEND', (mailbox, date_time, message)))
                return 'OK', [b'[APPENDUID 1 100]']

            def expunge(self):
                calls.append(('EXPUNGE', ()))
                return 'OK', [b'']

        with patch.object(
            web_outlook_app, 'resolve_imap_folder',
            side_effect=lambda _mail, _provider, folder, readonly=True: (
                '"INBOX"' if folder == 'inbox' else '"Spam"', {}
            ),
        ), patch.object(
            web_outlook_app, 'resolve_imap_message_uid', return_value='7'
        ), patch.object(
            web_outlook_app, 'store_imap_message_flags', return_value=(True, 'uid', [])
        ):
            result = web_outlook_app.move_email_items_imap(
                FakeMail(), [{'id': '7', 'folder': 'junkemail', 'id_mode': 'uid'}],
                destination='inbox', provider='aliyun',
            )
        self.assertTrue(result['success'])
        self.assertEqual(result['moved_ids'], ['7'])
        append_calls = [call for call in calls if call[0] == 'APPEND']
        self.assertEqual(
            append_calls,
            [('APPEND', ('"INBOX"', '"24-Nov-2026 01:42:56 +0000"', b'Subject: x'))],
        )
        self.assertIn(('EXPUNGE', ()), calls)
        self.assertFalse([call for call in calls if call[0] == 'COPY'])

    def test_imap_move_keeps_source_when_append_fails(self):
        calls = []

        class FakeMail:
            def uid(self, command, *args):
                if command == 'FETCH' and args[1] == '(RFC822.SIZE)':
                    return 'OK', [b'1 (RFC822.SIZE 2048)']
                return 'OK', [(b'1 (INTERNALDATE "24-Nov-2026 01:42:56 +0000" RFC822 {11}', b'x')]

            def append(self, mailbox, flags, date_time, message):
                calls.append(('APPEND', (mailbox,)))
                return 'NO', [b'quota exceeded']

            def expunge(self):
                calls.append(('EXPUNGE', ()))
                return 'OK', [b'']

        with patch.object(
            web_outlook_app, 'resolve_imap_folder',
            side_effect=lambda _mail, _provider, folder, readonly=True: ('"INBOX"', {}),
        ), patch.object(
            web_outlook_app, 'resolve_imap_message_uid', return_value='7'
        ), patch.object(
            web_outlook_app, 'store_imap_message_flags'
        ) as store_mock:
            result = web_outlook_app.move_email_items_imap(
                FakeMail(), [{'id': '7', 'folder': 'junkemail', 'id_mode': 'uid'}],
                destination='inbox', provider='aliyun',
            )
        self.assertFalse(result['success'])
        store_mock.assert_not_called()
        self.assertNotIn(('EXPUNGE', ()), calls)

    def test_resolve_imap_item_uid_converts_sequence_number(self):
        class FakeMail:
            def fetch(self, message_id, query):
                self.calls = getattr(self, 'calls', []) + [(message_id, query)]
                return 'OK', [b'2 (UID 42)']

        mail = FakeMail()
        uid = web_outlook_app.resolve_imap_item_uid(
            mail, {'id': '2', 'folder': 'junkemail', 'id_mode': 'sequence'}
        )
        self.assertEqual(uid, '42')
        self.assertEqual(mail.calls, [('2', '(UID)')])

    # ---------- 缓存清理 ----------
    def test_cache_cleanup_only_removes_moved_ids(self):
        account_id = self._insert_account()
        self._insert_cached_row(account_id, 'junkemail', 'msg-1')
        self._insert_cached_row(account_id, 'junkemail', 'msg-2')
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('shared@example.com')
            deleted = web_outlook_app.delete_retained_normal_mail_rows_after_move(
                account,
                [
                    {'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'},
                    {'id': 'msg-2', 'folder': 'junkemail', 'id_mode': 'graph'},
                ],
                {'moved_ids': ['msg-1']},
            )
        self.assertEqual(deleted, 1)
        self.assertEqual(
            [row['provider_message_id'] for row in self._cached_rows(account_id)],
            ['msg-2'],
        )

    def test_cache_cleanup_keeps_same_id_in_other_folder(self):
        account_id = self._insert_account()
        self._insert_cached_row(account_id, 'junkemail', 'msg-1')
        self._insert_cached_row(account_id, 'inbox', 'msg-1')
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('shared@example.com')
            web_outlook_app.delete_retained_normal_mail_rows_after_move(
                account,
                [{'id': 'msg-1', 'folder': 'junkemail', 'id_mode': 'graph'}],
                {'moved_ids': ['msg-1']},
            )
        self.assertEqual(
            [(row['folder'], row['provider_message_id']) for row in self._cached_rows(account_id)],
            [('inbox', 'msg-1')],
        )


if __name__ == '__main__':
    unittest.main()
