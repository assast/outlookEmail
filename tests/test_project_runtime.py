import importlib
import io
import os
import pathlib
import sys
import tempfile
import types
import unittest
import zipfile
from email.message import EmailMessage
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-project-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class ProjectRuntimeTests(unittest.TestCase):
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
            db.execute('DELETE FROM project_account_events')
            db.execute('DELETE FROM project_accounts')
            db.execute('DELETE FROM project_group_scopes')
            db.execute('DELETE FROM projects')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM tags')
            db.execute('DELETE FROM temp_email_tags')
            db.execute('DELETE FROM temp_email_messages')
            db.execute('DELETE FROM temp_emails')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

    def _create_group(self, name: str) -> int:
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                '''
                INSERT INTO groups (name, description, color, sort_order, is_system)
                VALUES (?, '', '#123456', 999, 0)
                ''',
                (name,)
            )
            db.commit()
            return int(cursor.lastrowid)

    def _insert_account(self, email_addr: str, group_id: int = 1, status: str = 'active') -> int:
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', '', '', ?, '', ?, 'outlook', 'outlook', '', 993, '', 0)
                ''',
                (email_addr, group_id, status)
            )
            db.commit()
            return int(cursor.lastrowid)

    def _set_group_sort_order(self, group_id: int, sort_order: int):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('UPDATE groups SET sort_order = ? WHERE id = ?', (sort_order, group_id))
            db.commit()

    def _ordered_groups(self):
        with self.app.app_context():
            return web_outlook_app.load_groups()

    def _set_aliases(self, account_id: int, primary_email: str, aliases):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            success, cleaned_aliases, errors = web_outlook_app.replace_account_aliases(
                account_id,
                primary_email,
                list(aliases),
                db,
            )
            self.assertTrue(success, msg='；'.join(errors))
            db.commit()
            return cleaned_aliases

    def _create_tag(self, name: str, color: str = '#0078d4') -> int:
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                'INSERT INTO tags (name, color) VALUES (?, ?)',
                (name, color)
            )
            db.commit()
            return int(cursor.lastrowid)

    def _tag_account(self, account_id: int, tag_id: int):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                'INSERT INTO account_tags (account_id, tag_id) VALUES (?, ?)',
                (account_id, tag_id)
            )
            db.commit()

    def _set_account_remark(self, account_id: int, remark: str):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('UPDATE accounts SET remark = ? WHERE id = ?', (remark, account_id))
            db.commit()

    def _project_accounts(self, project_key: str):
        response = self.client.get(f'/api/projects/{project_key}/accounts')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        return payload['data']['accounts']

    def test_accounts_api_imports_and_pages_ten_thousand_accounts(self):
        account_lines = [
            f'bulk{i:05d}@example.com----imap-password-{i}'
            for i in range(10000)
        ]

        with patch.object(web_outlook_app, 'encrypt_data', side_effect=lambda value: value):
            response = self.client.post('/api/accounts', json={
                'account_string': '\n'.join(account_lines),
                'group_id': 1,
                'provider': 'gmail',
            })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['added_count'], 10000)

        first_page = self.client.get(
            '/api/accounts?group_id=1&limit=200&offset=0&sort_by=email&sort_order=asc'
        )
        self.assertEqual(first_page.status_code, 200)
        first_payload = first_page.get_json()
        self.assertTrue(first_payload['success'])
        self.assertEqual(first_payload['total'], 10000)
        self.assertEqual(len(first_payload['accounts']), 200)
        self.assertTrue(first_payload['has_more'])
        self.assertEqual(first_payload['accounts'][0]['email'], 'bulk00000@example.com')

        last_page = self.client.get(
            '/api/accounts?group_id=1&limit=200&offset=9800&sort_by=email&sort_order=asc'
        )
        self.assertEqual(last_page.status_code, 200)
        last_payload = last_page.get_json()
        self.assertTrue(last_payload['success'])
        self.assertEqual(len(last_payload['accounts']), 200)
        self.assertFalse(last_payload['has_more'])
        self.assertEqual(last_payload['accounts'][-1]['email'], 'bulk09999@example.com')

        max_page = self.client.get(
            '/api/accounts?group_id=1&limit=20000&offset=0&sort_by=email&sort_order=asc'
        )
        self.assertEqual(max_page.status_code, 200)
        max_payload = max_page.get_json()
        self.assertTrue(max_payload['success'])
        self.assertEqual(max_payload['limit'], 10000)
        self.assertEqual(len(max_payload['accounts']), 10000)
        self.assertFalse(max_payload['has_more'])

    def test_refresh_selected_stream_processes_selected_active_outlook_accounts(self):
        first_account_id = self._insert_account('first-selected@example.com')
        second_account_id = self._insert_account('second-selected@example.com')
        inactive_account_id = self._insert_account('inactive-selected@example.com', status='inactive')

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute("UPDATE settings SET value = '0' WHERE key = 'refresh_delay_seconds'")
            db.commit()

        task_response = self.client.post('/api/accounts/refresh-selected-stream', json={
            'account_ids': [second_account_id, inactive_account_id, first_account_id],
        })
        task_payload = task_response.get_json()
        self.assertEqual(task_response.status_code, 200)
        self.assertTrue(task_payload['success'])
        self.assertIn('/api/accounts/refresh-selected-stream/', task_payload['stream_url'])
        self.assertNotIn('account_ids', task_payload['stream_url'])

        with patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, '')) as token_mock:
            response = self.client.get(task_payload['stream_url'])
            body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.content_type)
        self.assertEqual(token_mock.call_count, 2)
        self.assertIn('"refresh_type": "manual_selected"', body)
        self.assertIn(f'"account_id": {second_account_id}', body)
        self.assertIn(f'"account_id": {first_account_id}', body)
        self.assertNotIn(f'"account_id": {inactive_account_id}', body)

        with patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, '')) as legacy_token_mock:
            legacy_response = self.client.get(
                f'/api/accounts/refresh-selected-stream?account_ids={first_account_id}'
            )
            legacy_body = legacy_response.get_data(as_text=True)
        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(legacy_token_mock.call_count, 0)
        self.assertIn('"type": "error"', legacy_body)
        self.assertIn('"refresh_type": "manual_selected"', legacy_body)

        with self.app.app_context():
            rows = web_outlook_app.get_db().execute(
                '''
                SELECT id, last_refresh_status
                FROM accounts
                WHERE id IN (?, ?, ?)
                ''',
                (first_account_id, second_account_id, inactive_account_id)
            ).fetchall()
        status_by_id = {row['id']: row['last_refresh_status'] for row in rows}
        self.assertEqual(status_by_id[first_account_id], 'success')
        self.assertEqual(status_by_id[second_account_id], 'success')
        self.assertEqual(status_by_id[inactive_account_id], 'never')

    def test_raw_email_endpoint_returns_graph_mime_source_as_text(self):
        account_id = self._insert_account('raw-graph@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "UPDATE accounts SET client_id = ?, refresh_token = ? WHERE id = ?",
                ('client-id', 'refresh-token', account_id),
            )
            db.commit()

        with patch.object(web_outlook_app, 'get_raw_email_graph', return_value=b'From: sender@example.com\r\nSubject: Raw Source\r\n\r\nHello'):
            response = self.client.get('/api/email/raw-graph@example.com/message-1/raw?method=graph&folder=inbox')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['filename'], 'message-1.eml')
        self.assertIn('Subject: Raw Source', payload['raw'])
        self.assertIn('原始邮件包含完整邮件头', payload['warning'])

    def test_raw_email_endpoint_returns_imap_mime_source_as_text(self):
        self._insert_account('raw-imap@example.com')

        with patch.object(web_outlook_app, 'get_raw_email_imap', return_value='From: sender@example.com\r\nSubject: IMAP Raw\r\n\r\nHello'):
            response = self.client.get('/api/email/raw-imap@example.com/42/raw?method=imap&folder=inbox')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['filename'], '42.eml')
        self.assertIn('Subject: IMAP Raw', payload['raw'])

    def test_csrf_token_endpoint_requires_login(self):
        anonymous_client = self.app.test_client()
        response = anonymous_client.get('/api/csrf-token')

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload['need_login'])

    def test_csrf_token_endpoint_disables_caching(self):
        response = self.client.get('/api/csrf-token')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn('csrf_token', payload)
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Pragma'), 'no-cache')
        self.assertEqual(response.headers.get('Expires'), '0')
        self.assertIn('Cookie', response.headers.get('Vary', ''))

    def test_version_status_reports_update_when_remote_repository_is_newer(self):
        with patch.object(
            web_outlook_app,
            'fetch_remote_version_snapshot',
            return_value={
                'release_version': 'v2.0.24',
                'release_url': 'https://example.com/releases/v2.0.24',
                'repository_version': 'v2.0.24',
                'errors': [],
            },
        ), patch.object(web_outlook_app, 'APP_VERSION', '2.0.23'):
            with self.app.app_context():
                web_outlook_app.VERSION_CHECK_CACHE['payload'] = None
                web_outlook_app.VERSION_CHECK_CACHE['expires_at'] = 0.0

            response = self.client.get('/api/version-status?refresh=1')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        version_status = payload['version_status']
        self.assertEqual(version_status['status'], 'update_available')
        self.assertEqual(version_status['badge_label'], '可更新')
        self.assertEqual(version_status['latest_version'], 'v2.0.24')
        self.assertIn('v2.0.24', version_status['hint'])

    def test_version_status_reports_up_to_date_when_release_matches(self):
        with patch.object(
            web_outlook_app,
            'fetch_remote_version_snapshot',
            return_value={
                'release_version': 'v2.0.24',
                'release_url': 'https://example.com/releases/v2.0.24',
                'repository_version': 'v2.0.24',
                'errors': [],
            },
        ), patch.object(web_outlook_app, 'APP_VERSION', '2.0.24'):
            with self.app.app_context():
                web_outlook_app.VERSION_CHECK_CACHE['payload'] = None
                web_outlook_app.VERSION_CHECK_CACHE['expires_at'] = 0.0

            response = self.client.get('/api/version-status?refresh=1')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        version_status = payload['version_status']
        self.assertEqual(version_status['status'], 'up_to_date')
        self.assertEqual(version_status['badge_label'], '稳定版')
        self.assertEqual(version_status['hint'], '与仓库发布版本同步')

    def test_start_project_all_scope_creates_project_and_accounts(self):
        self._insert_account('alpha@example.com')
        self._insert_account('beta@example.com')

        response = self.client.post(
            '/api/projects/start',
            json={'project_key': 'gpt', 'name': 'GPT Register'}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['data']['created'])
        self.assertEqual(payload['data']['added_count'], 2)
        self.assertEqual(payload['data']['total_count'], 2)

        accounts = self._project_accounts('gpt')
        self.assertEqual(len(accounts), 2)
        self.assertEqual({item['project_status'] for item in accounts}, {'toClaim'})

    def test_start_project_group_scope_only_replenishes_matching_groups(self):
        group_a = self._create_group('Project Group A')
        group_b = self._create_group('Project Group B')
        self._insert_account('a1@example.com', group_id=group_a)
        self._insert_account('b1@example.com', group_id=group_b)

        first = self.client.post(
            '/api/projects/start',
            json={'project_key': 'google', 'name': 'Google', 'group_ids': [group_a]}
        ).get_json()
        self.assertTrue(first['success'])
        self.assertEqual(first['data']['added_count'], 1)
        self.assertEqual(first['data']['total_count'], 1)

        self._insert_account('a2@example.com', group_id=group_a)
        self._insert_account('b2@example.com', group_id=group_b)

        second = self.client.post(
            '/api/projects/start',
            json={'project_key': 'google'}
        ).get_json()
        self.assertTrue(second['success'])
        self.assertFalse(second['data']['created'])
        self.assertEqual(second['data']['added_count'], 1)
        self.assertEqual(second['data']['total_count'], 2)

        accounts = self._project_accounts('google')
        self.assertEqual({item['email'] for item in accounts}, {'a1@example.com', 'a2@example.com'})

    def test_failed_account_requires_manual_reset_before_reclaim(self):
        account_id = self._insert_account('retry@example.com')
        self.client.post('/api/projects/start', json={'project_key': 'google', 'name': 'Google'})

        claim = self.client.post(
            '/api/projects/google/claim-random',
            json={'caller_id': 'worker-1', 'task_id': 'task-1'}
        ).get_json()
        self.assertTrue(claim['success'])
        claim_token = claim['data']['claim_token']

        failed = self.client.post(
            '/api/projects/google/complete-failed',
            json={
                'account_id': account_id,
                'claim_token': claim_token,
                'caller_id': 'worker-1',
                'task_id': 'task-1',
                'detail': 'provider blocked',
            }
        ).get_json()
        self.assertTrue(failed['success'])

        second_claim = self.client.post(
            '/api/projects/google/claim-random',
            json={'caller_id': 'worker-2', 'task_id': 'task-2'}
        ).get_json()
        self.assertFalse(second_claim['success'])

        reset = self.client.post(
            '/api/projects/google/reset-failed',
            json={'account_id': account_id, 'detail': 'manual retry'}
        ).get_json()
        self.assertTrue(reset['success'])

        third_claim = self.client.post(
            '/api/projects/google/claim-random',
            json={'caller_id': 'worker-3', 'task_id': 'task-3'}
        ).get_json()
        self.assertTrue(third_claim['success'])
        self.assertEqual(third_claim['data']['account_id'], account_id)

    def test_extension_login_rejects_wrong_password(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('extension-pass'))
            web_outlook_app.login_attempts.clear()

        anonymous_client = self.app.test_client()
        response = anonymous_client.post('/api/extension/login', json={
            'password': 'wrong-pass',
        })

        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], '密码错误')

    def test_extension_login_launch_url_sets_session_once(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('extension-pass'))
            web_outlook_app.login_attempts.clear()
            web_outlook_app.extension_login_tokens.clear()

        anonymous_client = self.app.test_client()
        response = anonymous_client.post('/api/extension/login', json={
            'password': 'extension-pass',
            'next': '/#settings',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn('/extension-login/', payload['launch_url'])
        self.assertEqual(payload['expires_in'], web_outlook_app.EXTENSION_LOGIN_TOKEN_TTL_SECONDS)

        launch_response = anonymous_client.get(payload['launch_url'], follow_redirects=False)
        self.assertEqual(launch_response.status_code, 302)
        self.assertEqual(launch_response.headers['Location'], '/#settings')

        with anonymous_client.session_transaction() as sess:
            self.assertTrue(sess.get('logged_in'))

        reused_response = anonymous_client.get(payload['launch_url'], follow_redirects=False)
        self.assertEqual(reused_response.status_code, 302)
        self.assertTrue(reused_response.headers['Location'].endswith('/login'))

    def test_delete_and_reimport_same_email_preserves_done_status(self):
        original_account_id = self._insert_account('done@example.com')
        self.client.post('/api/projects/start', json={'project_key': 'gpt', 'name': 'GPT'})

        claim = self.client.post(
            '/api/projects/gpt/claim-random',
            json={'caller_id': 'worker-1', 'task_id': 'task-1'}
        ).get_json()
        self.assertTrue(claim['success'])

        success = self.client.post(
            '/api/projects/gpt/complete-success',
            json={
                'account_id': original_account_id,
                'claim_token': claim['data']['claim_token'],
                'caller_id': 'worker-1',
                'task_id': 'task-1',
                'detail': 'completed',
            }
        ).get_json()
        self.assertTrue(success['success'])

        deleted = self.client.delete(f'/api/accounts/{original_account_id}').get_json()
        self.assertTrue(deleted['success'])

        new_account_id = self._insert_account('done@example.com')
        restarted = self.client.post('/api/projects/start', json={'project_key': 'gpt'}).get_json()
        self.assertTrue(restarted['success'])

        accounts = self._project_accounts('gpt')
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['account_id'], new_account_id)
        self.assertEqual(accounts[0]['project_status'], 'done')

        second_claim = self.client.post(
            '/api/projects/gpt/claim-random',
            json={'caller_id': 'worker-2', 'task_id': 'task-2'}
        ).get_json()
        self.assertFalse(second_claim['success'])

    def test_start_project_can_use_alias_emails(self):
        alpha_id = self._insert_account('alpha@example.com')
        self._set_aliases(alpha_id, 'alpha@example.com', ['alias-a@example.com', 'alias-b@example.com'])
        self._insert_account('beta@example.com')

        response = self.client.post(
            '/api/projects/start',
            json={'project_key': 'gpt', 'name': 'GPT Register', 'use_alias_email': True}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['data']['use_alias_email'])
        self.assertEqual(payload['data']['added_count'], 3)
        self.assertEqual(payload['data']['total_count'], 3)

        accounts = self._project_accounts('gpt')
        self.assertEqual(
            {item['email'] for item in accounts},
            {'alias-a@example.com', 'alias-b@example.com', 'beta@example.com'}
        )
        alias_rows = [item for item in accounts if item['primary_email'] == 'alpha@example.com']
        self.assertEqual(len(alias_rows), 2)

        claim = self.client.post(
            '/api/projects/gpt/claim-random',
            json={'caller_id': 'worker-1', 'task_id': 'task-1'}
        ).get_json()
        self.assertTrue(claim['success'])
        self.assertEqual(claim['data']['email'], 'alias-a@example.com')
        self.assertEqual(claim['data']['primary_email'], 'alpha@example.com')

    def test_restart_project_without_alias_flag_preserves_existing_alias_mode(self):
        alpha_id = self._insert_account('alpha@example.com')
        self._set_aliases(alpha_id, 'alpha@example.com', ['alias-a@example.com'])

        first = self.client.post(
            '/api/projects/start',
            json={'project_key': 'gpt', 'name': 'GPT Register', 'use_alias_email': True}
        ).get_json()
        self.assertTrue(first['success'])
        self.assertTrue(first['data']['use_alias_email'])
        self.assertEqual(first['data']['added_count'], 1)

        beta_id = self._insert_account('beta@example.com')
        self._set_aliases(beta_id, 'beta@example.com', ['alias-b@example.com'])

        restarted = self.client.post(
            '/api/projects/start',
            json={'project_key': 'gpt'}
        ).get_json()
        self.assertTrue(restarted['success'])
        self.assertTrue(restarted['data']['use_alias_email'])
        self.assertEqual(restarted['data']['added_count'], 1)

        accounts = self._project_accounts('gpt')
        self.assertEqual({item['email'] for item in accounts}, {'alias-a@example.com', 'alias-b@example.com'})

    def test_init_db_preserves_existing_custom_group_order(self):
        group_a = self._create_group('Alpha Group')
        group_b = self._create_group('Beta Group')

        self._set_group_sort_order(1, 2)
        self._set_group_sort_order(group_a, 3)
        self._set_group_sort_order(group_b, 1)

        with self.app.app_context():
            web_outlook_app.init_db()

        ordered_groups = self._ordered_groups()
        self.assertEqual(
            [group['name'] for group in ordered_groups],
            ['临时邮箱', 'Beta Group', '默认分组', 'Alpha Group']
        )
        self.assertEqual(
            [group['sort_order'] for group in ordered_groups],
            [0, 1, 2, 3]
        )

    def test_init_db_backfills_missing_group_sort_order_once(self):
        group_a = self._create_group('Gamma Group')
        group_b = self._create_group('Delta Group')

        self._set_group_sort_order(1, 0)
        self._set_group_sort_order(group_a, 0)
        self._set_group_sort_order(group_b, 0)

        with self.app.app_context():
            web_outlook_app.init_db()

        ordered_groups = self._ordered_groups()
        self.assertEqual(
            [group['name'] for group in ordered_groups],
            ['临时邮箱', '默认分组', 'Gamma Group', 'Delta Group']
        )
        self.assertEqual(
            [group['sort_order'] for group in ordered_groups],
            [0, 1, 2, 3]
        )

    def test_init_db_adds_account_sort_order_column(self):
        with self.app.app_context():
            columns = [
                row[1]
                for row in web_outlook_app.get_db().execute("PRAGMA table_info(accounts)").fetchall()
            ]

        self.assertIn('sort_order', columns)

    def test_init_db_creates_retained_normal_mail_schema(self):
        expected_columns = {
            'account_id',
            'folder',
            'provider_message_id',
            'id_mode',
            'subject',
            'sender',
            'recipients',
            'cc',
            'received_at',
            'received_at_sort',
            'is_read',
            'has_attachments',
            'body_preview',
            'body',
            'body_type',
            'attachments_json',
            'list_cached',
            'body_cached',
            'list_cached_at',
            'body_cached_at',
            'last_synced_at',
            'created_at',
            'updated_at',
        }

        with self.app.app_context():
            db = web_outlook_app.get_db()
            columns = {
                row['name']
                for row in db.execute("PRAGMA table_info(retained_normal_mail_messages)").fetchall()
            }
            indexes = {
                row['name']: bool(row['unique'])
                for row in db.execute("PRAGMA index_list(retained_normal_mail_messages)").fetchall()
            }
            unique_columns = [
                row['name']
                for row in db.execute(
                    "PRAGMA index_info(ux_retained_normal_mail_messages_key)"
                ).fetchall()
            ]
            list_index_columns = [
                row['name']
                for row in db.execute(
                    "PRAGMA index_info(idx_retained_normal_mail_messages_list)"
                ).fetchall()
            ]
            body_cache_index_columns = [
                row['name']
                for row in db.execute(
                    "PRAGMA index_info(idx_retained_normal_mail_messages_body_cache)"
                ).fetchall()
            ]

        self.assertTrue(expected_columns.issubset(columns))
        self.assertTrue(indexes['ux_retained_normal_mail_messages_key'])
        self.assertIn('idx_retained_normal_mail_messages_list', indexes)
        self.assertIn('idx_retained_normal_mail_messages_body_cache', indexes)
        self.assertEqual(
            unique_columns,
            ['account_id', 'folder', 'provider_message_id', 'id_mode']
        )
        self.assertEqual(
            list_index_columns,
            ['account_id', 'folder', 'received_at_sort', 'id']
        )
        self.assertEqual(
            body_cache_index_columns,
            ['account_id', 'folder', 'body_cached', 'received_at_sort']
        )

    def test_account_sort_order_roundtrips_through_account_apis(self):
        account_id = self._insert_account('sort@example.com')

        update_response = self.client.put(
            f'/api/accounts/{account_id}',
            json={
                'email': 'sort@example.com',
                'password': '',
                'client_id': 'client-id',
                'refresh_token': 'refresh-token',
                'account_type': 'outlook',
                'provider': 'outlook',
                'group_id': 1,
                'sort_order': 7,
                'remark': 'ordered',
                'aliases': [],
                'status': 'active',
                'forward_enabled': False,
            }
        )
        self.assertEqual(update_response.status_code, 200)
        update_payload = update_response.get_json()
        self.assertTrue(update_payload['success'])

        detail_response = self.client.get(f'/api/accounts/{account_id}')
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()
        self.assertTrue(detail_payload['success'])
        self.assertEqual(detail_payload['account']['sort_order'], 7)

        list_response = self.client.get('/api/accounts?group_id=1')
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.get_json()
        self.assertTrue(list_payload['success'])
        listed_account = next(item for item in list_payload['accounts'] if item['id'] == account_id)
        self.assertEqual(listed_account['sort_order'], 7)

        search_response = self.client.get('/api/accounts/search?q=sort@example.com')
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.get_json()
        self.assertTrue(search_payload['success'])
        self.assertEqual(search_payload['accounts'][0]['sort_order'], 7)

    def test_account_search_can_filter_to_group(self):
        target_group_id = self._create_group('搜索分组')
        self._insert_account('scope-filter-default@example.com', group_id=1)
        self._insert_account('scope-filter-target@example.com', group_id=target_group_id)
        self._insert_account('scope-filter-other@example.com', group_id=1)

        group_response = self.client.get(
            f'/api/accounts/search?q=scope-filter&group_id={target_group_id}&sort_by=email&sort_order=asc'
        )
        self.assertEqual(group_response.status_code, 200)
        group_payload = group_response.get_json()
        self.assertTrue(group_payload['success'])
        self.assertEqual(group_payload['total'], 1)
        self.assertEqual(
            [account['email'] for account in group_payload['accounts']],
            ['scope-filter-target@example.com']
        )

        all_response = self.client.get('/api/accounts/search?q=scope-filter&sort_by=email&sort_order=asc')
        self.assertEqual(all_response.status_code, 200)
        all_payload = all_response.get_json()
        self.assertTrue(all_payload['success'])
        self.assertEqual(all_payload['total'], 3)

    def test_account_search_accepts_whitespace_separated_email_list(self):
        self._insert_account('multi-first@example.com')
        self._insert_account('multi-second@example.com')
        alias_owner_id = self._insert_account('multi-alias-owner@example.com')
        self._set_aliases(alias_owner_id, 'multi-alias-owner@example.com', ['multi-alias@example.com'])
        self._insert_account('multi-other@example.com')

        response = self.client.get('/api/accounts/search', query_string={
            'q': 'multi-second@example.com\nmulti-alias@example.com multi-first@example.com',
            'sort_by': 'email',
            'sort_order': 'asc',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 3)
        self.assertEqual(
            [account['email'] for account in payload['accounts']],
            [
                'multi-alias-owner@example.com',
                'multi-first@example.com',
                'multi-second@example.com',
            ]
        )

    def test_account_search_splits_keywords_across_email_alias_remark_and_tag(self):
        email_match_id = self._insert_account('keyword-email@example.com')
        remark_match_id = self._insert_account('keyword-remark-owner@example.com')
        tag_match_id = self._insert_account('keyword-tag-owner@example.com')
        alias_match_id = self._insert_account('keyword-alias-owner@example.com')
        self._insert_account('keyword-other@example.com')

        self._set_account_remark(remark_match_id, '客户备注命中')
        tag_id = self._create_tag('重点标签')
        self._tag_account(tag_match_id, tag_id)
        self._set_aliases(alias_match_id, 'keyword-alias-owner@example.com', ['keyword-alias@example.com'])

        response = self.client.get('/api/accounts/search', query_string={
            'q': 'keyword-email\n客户备注 重点标签 keyword-alias@example.com',
            'sort_by': 'email',
            'sort_order': 'asc',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 4)
        self.assertEqual(
            [account['id'] for account in payload['accounts']],
            [
                alias_match_id,
                email_match_id,
                remark_match_id,
                tag_match_id,
            ]
        )

    def test_account_search_rejects_more_than_200_keywords(self):
        response = self.client.get('/api/accounts/search', query_string={
            'q': ' '.join(f'keyword-limit-{index}' for index in range(201)),
        })
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], '搜索关键词最多支持 200 个')

    def test_account_search_email_list_combines_group_scope_and_tag_filter(self):
        target_group_id = self._create_group('组合搜索分组')
        other_group_id = self._create_group('其他搜索分组')
        tag_id = self._create_tag('组合标签')

        primary_id = self._insert_account('combo-primary@example.com', group_id=target_group_id)
        alias_owner_id = self._insert_account('combo-alias-owner@example.com', group_id=target_group_id)
        self._set_aliases(alias_owner_id, 'combo-alias-owner@example.com', ['combo-alias@example.com'])
        untagged_id = self._insert_account('combo-untagged@example.com', group_id=target_group_id)
        outside_group_id = self._insert_account('combo-outside@example.com', group_id=other_group_id)

        self._tag_account(primary_id, tag_id)
        self._tag_account(alias_owner_id, tag_id)
        self._tag_account(outside_group_id, tag_id)

        response = self.client.get('/api/accounts/search', query_string={
            'q': 'combo-primary@example.com combo-alias@example.com combo-untagged@example.com combo-outside@example.com',
            'group_id': target_group_id,
            'tag_ids': str(tag_id),
            'sort_by': 'email',
            'sort_order': 'asc',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 2)
        self.assertEqual(
            [account['email'] for account in payload['accounts']],
            [
                'combo-alias-owner@example.com',
                'combo-primary@example.com',
            ]
        )
        self.assertNotIn(untagged_id, [account['id'] for account in payload['accounts']])

    def test_add_account_without_sort_order_uses_created_at_fallback(self):
        response = self.client.post(
            '/api/accounts',
            json={
                'account_string': 'created-sort@example.com----password----client-id----refresh-token',
                'group_id': 1,
                'provider': 'outlook',
            }
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                'SELECT sort_order FROM accounts WHERE email = ?',
                ('created-sort@example.com',)
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertIsNone(row['sort_order'])

    def test_accounts_api_import_applies_shared_metadata_to_new_accounts(self):
        existing_id = self._insert_account('metadata-existing@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            tag_id = db.execute(
                'INSERT INTO tags (name, color) VALUES (?, ?)',
                ('导入批次', '#0078d4')
            ).lastrowid
            db.commit()

        with patch.object(web_outlook_app, 'encrypt_data', side_effect=lambda value: value):
            response = self.client.post('/api/accounts', json={
                'account_string': '\n'.join([
                    'metadata-existing@example.com----old-password',
                    'metadata-new-a@example.com----imap-password-a',
                    'metadata-new-b@example.com----imap-password-b',
                ]),
                'group_id': 1,
                'provider': 'gmail',
                'remark': '统一导入备注',
                'status': 'inactive',
                'tag_ids': [tag_id],
            })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['added_count'], 2)
        self.assertEqual(payload['skipped_count'], 1)
        self.assertEqual(payload['tagged_count'], 2)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = db.execute(
                '''
                SELECT id, email, remark, status
                FROM accounts
                WHERE email IN (?, ?, ?)
                ORDER BY email
                ''',
                (
                    'metadata-existing@example.com',
                    'metadata-new-a@example.com',
                    'metadata-new-b@example.com',
                )
            ).fetchall()
            account_rows = {row['email']: dict(row) for row in rows}
            tagged_rows = db.execute(
                '''
                SELECT account_id
                FROM account_tags
                WHERE tag_id = ?
                ORDER BY account_id
                ''',
                (tag_id,)
            ).fetchall()

        self.assertEqual(account_rows['metadata-existing@example.com']['id'], existing_id)
        self.assertEqual(account_rows['metadata-existing@example.com']['remark'], '')
        self.assertEqual(account_rows['metadata-existing@example.com']['status'], 'active')
        self.assertEqual(account_rows['metadata-new-a@example.com']['remark'], '统一导入备注')
        self.assertEqual(account_rows['metadata-new-a@example.com']['status'], 'inactive')
        self.assertEqual(account_rows['metadata-new-b@example.com']['remark'], '统一导入备注')
        self.assertEqual(account_rows['metadata-new-b@example.com']['status'], 'inactive')
        self.assertEqual(
            {row['account_id'] for row in tagged_rows},
            {
                account_rows['metadata-new-a@example.com']['id'],
                account_rows['metadata-new-b@example.com']['id'],
            }
        )

    def test_update_account_without_sort_order_clears_custom_sort(self):
        account_id = self._insert_account('clear-sort@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('UPDATE accounts SET sort_order = 9 WHERE id = ?', (account_id,))
            db.commit()

        response = self.client.put(
            f'/api/accounts/{account_id}',
            json={
                'email': 'clear-sort@example.com',
                'password': '',
                'client_id': 'client-id',
                'refresh_token': 'refresh-token',
                'account_type': 'outlook',
                'provider': 'outlook',
                'group_id': 1,
                'remark': '',
                'aliases': [],
                'status': 'active',
                'forward_enabled': False,
            }
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                'SELECT sort_order FROM accounts WHERE id = ?',
                (account_id,)
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertIsNone(row['sort_order'])

    def test_settings_show_account_sort_order_roundtrips(self):
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['show_account_sort_order'], 'false')

        update_response = self.client.put(
            '/api/settings',
            json={'show_account_sort_order': False}
        )
        self.assertEqual(update_response.status_code, 200)
        update_payload = update_response.get_json()
        self.assertTrue(update_payload['success'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('show_account_sort_order'), 'false')

        refreshed_response = self.client.get('/api/settings')
        self.assertEqual(refreshed_response.status_code, 200)
        refreshed_payload = refreshed_response.get_json()
        self.assertTrue(refreshed_payload['success'])
        self.assertEqual(refreshed_payload['settings']['show_account_sort_order'], 'false')

    def test_webdav_backup_settings_require_login_password_when_changed(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))
            web_outlook_app.set_setting('webdav_backup_enabled', 'false')
            web_outlook_app.set_setting('webdav_backup_url', '')
            web_outlook_app.set_setting('webdav_backup_username', '')
            web_outlook_app.set_setting_encrypted('webdav_backup_password', '')
            web_outlook_app.set_setting('webdav_backup_cron', '0 3 * * *')

        response = self.client.put(
            '/api/settings',
            json={
                'webdav_backup_enabled': True,
                'webdav_backup_url': 'https://dav.example.com/backups',
                'webdav_backup_username': 'dav-user',
                'webdav_backup_password': 'dav-pass',
                'webdav_backup_cron': '0 4 * * *',
            }
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('登录密码', payload['error'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('webdav_backup_enabled'), 'false')
            self.assertEqual(web_outlook_app.get_setting('webdav_backup_url'), '')

    def test_webdav_backup_settings_save_with_login_password(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))
            web_outlook_app.set_setting('webdav_backup_enabled', 'false')
            web_outlook_app.set_setting('webdav_backup_url', '')
            web_outlook_app.set_setting('webdav_backup_username', '')
            web_outlook_app.set_setting_encrypted('webdav_backup_password', '')
            web_outlook_app.set_setting('webdav_backup_cron', '0 3 * * *')

        response = self.client.put(
            '/api/settings',
            json={
                'webdav_backup_enabled': True,
                'webdav_backup_url': 'https://dav.example.com/backups',
                'webdav_backup_username': 'dav-user',
                'webdav_backup_password': 'dav-pass',
                'webdav_backup_cron': '0 4 * * *',
                'webdav_backup_verify_password': 'current-password',
            }
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'], msg=payload.get('error'))

        settings_response = self.client.get('/api/settings')
        self.assertEqual(settings_response.status_code, 200)
        settings_payload = settings_response.get_json()
        self.assertTrue(settings_payload['success'])
        settings = settings_payload['settings']
        self.assertEqual(settings['webdav_backup_enabled'], 'true')
        self.assertEqual(settings['webdav_backup_url'], 'https://dav.example.com/backups')
        self.assertEqual(settings['webdav_backup_username'], 'dav-user')
        self.assertEqual(settings['webdav_backup_password'], 'dav-pass')
        self.assertEqual(settings['webdav_backup_cron'], '0 4 * * *')
        self.assertTrue(settings['webdav_backup_next_run'])

        with self.app.app_context():
            self.assertNotEqual(web_outlook_app.get_setting('webdav_backup_password'), 'dav-pass')

    def test_webdav_backup_cron_requires_five_fields_when_saving(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))
            web_outlook_app.set_setting('webdav_backup_enabled', 'false')
            web_outlook_app.set_setting('webdav_backup_url', '')
            web_outlook_app.set_setting('webdav_backup_username', '')
            web_outlook_app.set_setting_encrypted('webdav_backup_password', '')
            web_outlook_app.set_setting('webdav_backup_cron', '0 3 * * *')

        response = self.client.put(
            '/api/settings',
            json={
                'webdav_backup_enabled': True,
                'webdav_backup_url': 'https://dav.example.com/backups',
                'webdav_backup_username': 'dav-user',
                'webdav_backup_password': 'dav-pass',
                'webdav_backup_cron': '0 0 4 * * *',
                'webdav_backup_verify_password': 'current-password',
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('仅支持 5 段 Cron', payload['error'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('webdav_backup_cron'), '0 3 * * *')

    def test_all_groups_backup_uses_selected_group_export_shape(self):
        extra_group_id = self._create_group('备份分组')
        self._insert_account('default-export@example.com', group_id=1)
        self._insert_account('group-export@example.com', group_id=extra_group_id)

        with self.app.app_context():
            default_group = web_outlook_app.get_group_by_id(1)
            export_payload = web_outlook_app.build_all_groups_export_content()

        self.assertEqual(export_payload['total_count'], 2)
        self.assertIn(default_group['name'], export_payload['content'])
        self.assertIn('备份分组', export_payload['content'])
        self.assertIn('default-export@example.com', export_payload['content'])
        self.assertIn('group-export@example.com', export_payload['content'])

    def test_export_selected_accounts_uses_selected_account_ids(self):
        first_account_id = self._insert_account('first-selected-export@example.com')
        second_account_id = self._insert_account('second-selected-export@example.com')
        third_account_id = self._insert_account('third-selected-export@example.com')

        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                UPDATE accounts
                SET password = ?, client_id = ?, refresh_token = ?
                WHERE id = ?
                ''',
                ('first-pass', 'first-client', 'first-refresh', first_account_id)
            )
            db.execute(
                '''
                UPDATE accounts
                SET password = ?, client_id = ?, refresh_token = ?
                WHERE id = ?
                ''',
                ('second-pass', 'second-client', 'second-refresh', second_account_id)
            )
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('export-pass'))
            db.commit()

        verify_response = self.client.post('/api/export/verify', json={'password': 'export-pass'})
        self.assertEqual(verify_response.status_code, 200)
        verify_payload = verify_response.get_json()
        self.assertTrue(verify_payload['success'])

        response = self.client.post('/api/accounts/export-selected', json={
            'account_ids': [second_account_id, 999999, first_account_id],
            'verify_token': verify_payload['verify_token'],
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response.content_type)
        self.assertIn('selected_accounts_', response.headers.get('Content-Disposition', ''))
        self.assertEqual(
            response.get_data(as_text=True).splitlines(),
            [
                'second-selected-export@example.com----second-pass----second-client----second-refresh',
                'first-selected-export@example.com----first-pass----first-client----first-refresh',
            ]
        )
        self.assertNotIn('third-selected-export@example.com', response.get_data(as_text=True))

    def test_run_webdav_backup_uploads_all_group_export_file(self):
        self._insert_account('backup-upload@example.com', group_id=1)
        with self.app.app_context():
            web_outlook_app.set_setting('webdav_backup_enabled', 'true')
            web_outlook_app.set_setting('webdav_backup_url', 'https://dav.example.com/backups/')
            web_outlook_app.set_setting('webdav_backup_username', 'dav-user')
            web_outlook_app.set_setting_encrypted('webdav_backup_password', 'dav-pass')

            class ResponseStub:
                status_code = 201

            with patch.object(web_outlook_app.requests, 'put', return_value=ResponseStub()) as put_mock:
                result = web_outlook_app.run_webdav_backup()

        self.assertTrue(result['success'], msg=result.get('error'))
        put_mock.assert_called_once()
        call_args = put_mock.call_args
        self.assertTrue(call_args.args[0].startswith('https://dav.example.com/backups/all_groups_backup_'))
        self.assertEqual(call_args.kwargs['auth'], ('dav-user', 'dav-pass'))
        self.assertIn('backup-upload@example.com', call_args.kwargs['data'].decode('utf-8'))
        self.assertIn('默认分组', call_args.kwargs['data'].decode('utf-8'))

    def test_webdav_backup_test_uploads_without_login_password(self):
        class PutResponseStub:
            status_code = 201

        class DeleteResponseStub:
            status_code = 204

        with patch.object(web_outlook_app.requests, 'put') as put_mock:
            put_mock.return_value = PutResponseStub()
            with patch.object(web_outlook_app.requests, 'delete', return_value=DeleteResponseStub()) as delete_mock:
                response = self.client.post(
                    '/api/settings/test-webdav-backup',
                    json={
                        'config': {
                            'url': 'https://dav.example.com/backups',
                            'username': 'dav-user',
                            'password': 'dav-pass',
                        }
                    }
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'], msg=payload.get('error'))
        put_mock.assert_called_once()
        delete_mock.assert_called_once()
        self.assertEqual(put_mock.call_args.kwargs['auth'], ('dav-user', 'dav-pass'))

    def test_webdav_backup_test_uploads_and_cleans_test_file(self):
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))

        class PutResponseStub:
            status_code = 201

        class DeleteResponseStub:
            status_code = 204

        with patch.object(web_outlook_app.requests, 'put', return_value=PutResponseStub()) as put_mock, \
                patch.object(web_outlook_app.requests, 'delete', return_value=DeleteResponseStub()) as delete_mock:
            response = self.client.post(
                '/api/settings/test-webdav-backup',
                json={
                    'login_password': 'current-password',
                    'config': {
                        'url': 'https://dav.example.com/backups',
                        'username': 'dav-user',
                        'password': 'dav-pass',
                    }
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'], msg=payload.get('error'))
        self.assertIn('目录可写', payload['message'])
        put_mock.assert_called_once()
        delete_mock.assert_called_once()
        self.assertTrue(put_mock.call_args.args[0].startswith('https://dav.example.com/backups/outlookemail_webdav_test_'))
        self.assertEqual(put_mock.call_args.kwargs['auth'], ('dav-user', 'dav-pass'))
        self.assertEqual(delete_mock.call_args.kwargs['auth'], ('dav-user', 'dav-pass'))

    def test_webdav_backup_test_404_explains_missing_directory(self):
        class PutResponseStub:
            status_code = 404

        with patch.object(web_outlook_app.requests, 'put', return_value=PutResponseStub()):
            response = self.client.post(
                '/api/settings/test-webdav-backup',
                json={
                    'config': {
                        'url': 'https://dav.jianguoyun.com/dav',
                        'username': 'dav-user',
                        'password': 'dav-pass',
                    }
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['status_code'], 404)
        self.assertIn('目标目录不存在', payload['error'])
        self.assertIn('https://dav.jianguoyun.com/dav/mailBackup', payload['error'])

    def test_webdav_backup_test_409_explains_path_conflict(self):
        class PutResponseStub:
            status_code = 409

        with patch.object(web_outlook_app.requests, 'put', return_value=PutResponseStub()):
            response = self.client.post(
                '/api/settings/test-webdav-backup',
                json={
                    'config': {
                        'url': 'https://dav.jianguoyun.com/dav/mailBackup',
                        'username': 'dav-user',
                        'password': 'dav-pass',
                    }
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['status_code'], 409)
        self.assertIn('目标路径冲突', payload['error'])
        self.assertIn('先创建 mailBackup 文件夹', payload['error'])

    def test_manual_webdav_upload_requires_login_password(self):
        self._insert_account('manual-upload@example.com', group_id=1)
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))

        with patch.object(web_outlook_app.requests, 'put') as put_mock:
            response = self.client.post(
                '/api/settings/upload-webdav-backup',
                json={
                    'config': {
                        'url': 'https://dav.example.com/backups',
                        'username': 'dav-user',
                        'password': 'dav-pass',
                    }
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('登录密码', payload['error'])
        put_mock.assert_not_called()

    def test_manual_webdav_upload_uses_current_form_config(self):
        self._insert_account('manual-upload@example.com', group_id=1)
        with self.app.app_context():
            web_outlook_app.set_setting('login_password', web_outlook_app.hash_password('current-password'))

        class PutResponseStub:
            status_code = 201

        with patch.object(web_outlook_app.requests, 'put', return_value=PutResponseStub()) as put_mock:
            response = self.client.post(
                '/api/settings/upload-webdav-backup',
                json={
                    'login_password': 'current-password',
                    'config': {
                        'url': 'https://dav.example.com/manual',
                        'username': 'manual-user',
                        'password': 'manual-pass',
                    }
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'], msg=payload.get('error'))
        self.assertTrue(payload['filename'].startswith('all_groups_backup_'))
        put_mock.assert_called_once()
        self.assertTrue(put_mock.call_args.args[0].startswith('https://dav.example.com/manual/all_groups_backup_'))
        self.assertEqual(put_mock.call_args.kwargs['auth'], ('manual-user', 'manual-pass'))
        self.assertIn('manual-upload@example.com', put_mock.call_args.kwargs['data'].decode('utf-8'))

    def test_download_all_oauth_imap_attachments_uses_requested_id_mode(self):
        account_id = self._insert_account('user@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                """
                UPDATE accounts
                SET client_id = 'client-id', refresh_token = 'refresh-token'
                WHERE id = ?
                """,
                (account_id,),
            )
            db.commit()

        detail = {'attachments': [{'id': 'attachment-1', 'name': 'report.txt'}]}
        with patch.object(web_outlook_app, 'get_email_detail_imap', return_value=detail) as detail_mock, \
                patch.object(web_outlook_app, 'download_email_attachment_for_account', return_value={
                    'success': True,
                    'filename': 'report.txt',
                    'content_type': 'text/plain',
                    'content': b'attachment body',
                }):
            response = self.client.get(
                '/api/email/user@example.com/42/attachments/download-all'
                '?method=imap&folder=inbox&id_mode=sequence'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/zip')
        detail_mock.assert_called_once_with(
            'user@example.com',
            'client-id',
            'refresh-token',
            '42',
            'inbox',
            '',
            ['', ''],
            'sequence',
        )

    def test_single_oauth_imap_attachment_download_uses_uid_id_mode(self):
        account_id = self._insert_account('user@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                """
                UPDATE accounts
                SET client_id = 'client-id', refresh_token = 'refresh-token'
                WHERE id = ?
                """,
                (account_id,),
            )
            db.commit()

        with patch.object(web_outlook_app, 'download_email_attachment_imap_result', return_value={
            'success': True,
            'filename': 'report.txt',
            'content_type': 'text/plain',
            'content': b'attachment body',
        }) as download_mock:
            response = self.client.get(
                '/api/email/user@example.com/42/attachments/attachment-1'
                '?method=imap&folder=inbox&id_mode=uid'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'attachment body')
        self.assertIn("filename*=UTF-8''report.txt", response.headers.get('Content-Disposition', ''))
        download_mock.assert_called_once_with(
            'user@example.com',
            'client-id',
            'refresh-token',
            '42',
            'attachment-1',
            'inbox',
            '',
            ['', ''],
            'uid',
        )

    def test_single_oauth_imap_attachment_download_uses_sequence_id_mode(self):
        account_id = self._insert_account('user@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                """
                UPDATE accounts
                SET client_id = 'client-id', refresh_token = 'refresh-token'
                WHERE id = ?
                """,
                (account_id,),
            )
            db.commit()

        with patch.object(web_outlook_app, 'download_email_attachment_imap_result', return_value={
            'success': True,
            'filename': 'report.txt',
            'content_type': 'text/plain',
            'content': b'attachment body',
        }) as download_mock:
            response = self.client.get(
                '/api/email/user@example.com/42/attachments/attachment-1'
                '?method=imap&folder=inbox&id_mode=sequence'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'attachment body')
        download_mock.assert_called_once_with(
            'user@example.com',
            'client-id',
            'refresh-token',
            '42',
            'attachment-1',
            'inbox',
            '',
            ['', ''],
            'sequence',
        )

    def test_graph_attachment_download_ignores_id_mode_contract(self):
        account_id = self._insert_account('user@example.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                """
                UPDATE accounts
                SET client_id = 'client-id', refresh_token = 'refresh-token'
                WHERE id = ?
                """,
                (account_id,),
            )
            db.commit()

        with patch.object(web_outlook_app, 'download_email_attachment_graph_result', return_value={
            'success': True,
            'filename': 'graph.txt',
            'content_type': 'text/plain',
            'content': b'graph body',
        }) as graph_download_mock, \
                patch.object(web_outlook_app, 'download_email_attachment_imap_result') as imap_download_mock:
            response = self.client.get(
                '/api/email/user@example.com/graph-message/attachments/graph-attachment'
                '?method=graph&folder=inbox&id_mode=sequence'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'graph body')
        self.assertIn("filename*=UTF-8''graph.txt", response.headers.get('Content-Disposition', ''))
        graph_download_mock.assert_called_once_with(
            'client-id',
            'refresh-token',
            'graph-message',
            'graph-attachment',
            '',
            ['', ''],
        )
        imap_download_mock.assert_not_called()

    def test_standard_imap_attachment_download_still_works_without_id_mode(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', '', '', 1, '', 'active', 'imap', 'custom', 'imap.example.com', 993, 'secret', 0)
                ''',
                ('imap-user@example.com',),
            )
            db.commit()

        with patch.object(web_outlook_app, 'download_email_attachment_imap_generic_result', return_value={
            'success': True,
            'filename': 'imap.txt',
            'content_type': 'text/plain',
            'content': b'imap body',
        }) as generic_download_mock:
            response = self.client.get(
                '/api/email/imap-user@example.com/imap-message/attachments/imap-attachment'
                '?method=imap&folder=inbox'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'imap body')
        generic_download_mock.assert_called_once_with(
            'imap-user@example.com',
            'secret',
            'imap.example.com',
            993,
            'imap-message',
            'imap-attachment',
            'inbox',
            'custom',
            '',
        )

    def test_imap_attachment_detail_and_download_route(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', '', '', 1, '', 'active', 'imap', 'custom', 'imap.example.com', 993, 'secret', 0)
                ''',
                ('user@example.com',)
            )
            db.commit()

        message = EmailMessage()
        message['Subject'] = 'Attachment Detail'
        message['From'] = 'sender@example.com'
        message['To'] = 'user@example.com'
        message.set_content('body line 1\nbody line 2')
        message.add_attachment(
            b'attachment body',
            maintype='text',
            subtype='plain',
            filename='report.txt',
        )
        message.add_attachment(
            b'second body',
            maintype='text',
            subtype='plain',
            filename='invoice.txt',
        )
        raw_email = message.as_bytes()

        class AttachmentMail:
            def __init__(self):
                self.logged_out = False

            def login(self, *_args, **_kwargs):
                return 'OK', [b'logged in']

            def xatom(self, *_args, **_kwargs):
                return 'OK', [b'ID completed']

            def select(self, name, readonly=True):
                if name in {'INBOX', '"INBOX"'}:
                    return 'OK', [b'1']
                return 'NO', [b'folder not found']

            def list(self):
                return 'OK', [b'(\\HasNoChildren) "." "INBOX"']

            def uid(self, command, *args, **_kwargs):
                if command == 'FETCH':
                    return 'OK', [(b'1 (RFC822 {256}', raw_email)]
                if command == 'SEARCH':
                    return 'OK', [b'1']
                return 'OK', [b'']

            def fetch(self, *_args, **_kwargs):
                return 'OK', [(b'1 (RFC822 {256}', raw_email)]

            def logout(self):
                self.logged_out = True
                return 'BYE', [b'logout']

        mail = AttachmentMail()
        with patch.object(web_outlook_app, 'create_imap_connection', return_value=mail):
            detail_response = self.client.get('/api/email/user@example.com/msg-1?method=imap&folder=inbox')
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.get_json()
            self.assertTrue(detail_payload['success'])
            self.assertEqual(detail_payload['email']['attachments'][0]['id'], 'attachment-1')
            self.assertEqual(detail_payload['email']['attachments'][0]['name'], 'report.txt')
            self.assertEqual(detail_payload['email']['body'], 'body line 1\nbody line 2\n')

            download_response = self.client.get('/api/email/user@example.com/msg-1/attachments/attachment-1?method=imap&folder=inbox')
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.data, b'attachment body')
            self.assertIn("filename*=UTF-8''report.txt", download_response.headers.get('Content-Disposition', ''))

            zip_response = self.client.get('/api/email/user@example.com/msg-1/attachments/download-all?method=imap&folder=inbox')
            self.assertEqual(zip_response.status_code, 200)
            self.assertEqual(zip_response.mimetype, 'application/zip')
            self.assertIn("filename*=UTF-8''attachments.zip", zip_response.headers.get('Content-Disposition', ''))
            self.assertIsNone(zip_response.headers.get('Content-Length'))
            with zipfile.ZipFile(io.BytesIO(zip_response.data)) as archive:
                self.assertEqual(set(archive.namelist()), {'report.txt', 'invoice.txt'})
                self.assertEqual(archive.read('report.txt'), b'attachment body')
                self.assertEqual(archive.read('invoice.txt'), b'second body')


class FrontendColorPickerTests(unittest.TestCase):
    def test_color_picker_initialization_block_calls_init_once(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')

        init_start = core_js.index("document.addEventListener('DOMContentLoaded'")
        init_end = core_js.index('function handleExtensionLaunchHash', init_start)
        init_block = core_js[init_start:init_end]

        self.assertEqual(init_block.count('initColorPicker();'), 1)

    def test_color_picker_binding_is_idempotent(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')

        function_start = core_js.index('function initColorPicker()')
        function_end = core_js.index('// 初始化邮件列表滚动监听', function_start)
        init_color_picker = core_js[function_start:function_end]

        self.assertIn("option.dataset.colorPickerBound === 'true'", init_color_picker)
        self.assertIn("option.dataset.colorPickerBound = 'true';", init_color_picker)
        self.assertLess(
            init_color_picker.index("option.dataset.colorPickerBound = 'true';"),
            init_color_picker.index("option.addEventListener('click'")
        )


class FrontendEmailListSecurityTests(unittest.TestCase):
    def setUp(self):
        self.emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

    def test_email_rows_use_delegated_clicks_without_inline_handlers(self):
        self.assertNotIn('onclick="${clickHandler}', self.emails_js)
        self.assertNotIn("onclick=\"${clickHandler}('${email.id}', ${index})\"", self.emails_js)
        self.assertIn('data-email-id="${escapeHtml(String(email.id || \'\'))}"', self.emails_js)
        self.assertIn('data-email-index="${index}"', self.emails_js)
        self.assertIn('function handleEmailListClick(event)', self.emails_js)
        self.assertIn("container.addEventListener('click', handleEmailListClick);", self.emails_js)
        self.assertIn('selectEmail(emailId, emailIndex);', self.emails_js)

    def test_email_checkbox_uses_delegated_click_without_inline_toggle(self):
        self.assertNotIn("toggleEmailSelection('${email.id}')", self.emails_js)
        self.assertIn('event.stopPropagation();', self.emails_js)
        self.assertIn('toggleEmailSelection(checkboxWrapper.dataset.emailId);', self.emails_js)
        self.assertIn('class="email-checkbox-wrapper" data-email-id=', self.emails_js)

    def test_detail_load_error_message_is_rendered_as_text(self):
        self.assertNotIn("${data.error && data.error.message ? data.error.message : '加载失败'}", self.emails_js)
        self.assertIn("const errorText = container.querySelector('.empty-state-text');", self.emails_js)
        self.assertIn("errorText.textContent = data.error && data.error.message ? data.error.message : '加载失败';", self.emails_js)

    def test_delete_emails_removes_matching_cached_rows_and_preserves_unrelated_detail(self):
        self.assertIn('function removeDeletedEmailsFromCachedLists(deletedIds, account = currentAccount)', self.emails_js)
        self.assertIn('cacheValue.emails = cacheValue.emails.filter(email => !normalizedIds.has(String(email.id)));', self.emails_js)
        self.assertIn('removeDeletedEmailsFromCachedLists(deletedIds);', self.emails_js)
        self.assertIn('if (currentEmailDetail && deletedIds.has(String(currentEmailDetail.id)))', self.emails_js)


class FrontendEmailBodyRetentionAndIframeTests(unittest.TestCase):
    def setUp(self):
        self.emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

    def test_body_retention_failed_requests_are_retryable(self):
        self.assertIn('const requestedKeys = items', self.emails_js)
        self.assertIn('requestedKeys.forEach(key => requestedBodyRetentionKeys.add(key));', self.emails_js)
        self.assertIn('requestedKeys.forEach(key => requestedBodyRetentionKeys.delete(key));', self.emails_js)
        self.assertIn('if (data && data.success === false)', self.emails_js)

    def test_normal_detail_iframe_resize_resources_are_cleaned(self):
        self.assertIn('const normalDetailIframeResizeResources = { timers: [], observer: null };', self.emails_js)
        self.assertIn('function cleanupNormalDetailIframeResizeResources()', self.emails_js)
        self.assertIn('cleanupNormalDetailIframeResizeResources();', self.emails_js)
        self.assertIn("const container = document.getElementById('emailDetail');", self.emails_js)
        self.assertIn('normalDetailIframeResizeResources.timers.push(window.setTimeout(adjustHeight, delay));', self.emails_js)
        self.assertIn('resources.observer.disconnect();', self.emails_js)
        self.assertIn('if (!iframe.isConnected)', self.emails_js)

    def test_fullscreen_iframe_resize_resources_are_cleaned(self):
        self.assertIn('const fullscreenIframeResizeResources = { timers: [], observer: null };', self.emails_js)
        self.assertIn('function cleanupFullscreenIframeResizeResources()', self.emails_js)
        self.assertIn('cleanupFullscreenIframeResizeResources();', self.emails_js)
        self.assertIn("const modal = document.getElementById('fullscreenEmailModal');", self.emails_js)
        self.assertIn('fullscreenIframeResizeResources.timers.push(window.setTimeout(adjustHeight, delay));', self.emails_js)
        self.assertIn('resources.observer.disconnect();', self.emails_js)

class FrontendTimezoneBootstrapTests(unittest.TestCase):
    def test_settings_js_no_longer_updates_timezone_in_add_account_flow(self):
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')

        self.assertEqual(settings_js.count('setAppTimeZone(appTimeZone);'), 2)
        self.assertIn("settings.app_timezone = appTimeZone;", settings_js)
        self.assertIn("showToast('时间展示已生效，定时任务重启后生效', 'success');", settings_js)

    def test_frontend_bootstraps_saved_timezone_before_loading_groups(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        oauth_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '06-utils-oauth.js').read_text(encoding='utf-8')
        refresh_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '08-refresh.js').read_text(encoding='utf-8')

        self.assertIn('async function loadAppTimeZoneFromSettings()', core_js)
        self.assertIn("fetch('/api/settings'", core_js)
        self.assertIn('await loadAppTimeZoneFromSettings();', core_js)
        self.assertLess(core_js.index('await loadAppTimeZoneFromSettings();'), core_js.index('loadGroups();'))
        self.assertIn('setShowAccountCreatedAt(String(data?.settings?.show_account_created_at) !== \'false\');', core_js)
        self.assertIn('setShowAccountSortOrder(String(data?.settings?.show_account_sort_order) === \'true\');', core_js)
        self.assertIn('const timeZone = getAppTimeZone();', oauth_js)
        self.assertIn('timeZone: getAppTimeZone()', refresh_js)

    def test_webdav_backup_settings_ui_is_present(self):
        settings_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-management.html').read_text(encoding='utf-8')
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')
        settings_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'index', '06-modals-toast.css').read_text(encoding='utf-8')

        self.assertIn('id="settingsWebdavBackupSection"', settings_html)
        self.assertIn('id="webdavBackupEnabled"', settings_html)
        self.assertIn('id="webdavBackupCron"', settings_html)
        self.assertIn('id="webdavBackupVerifyPassword"', settings_html)
        self.assertIn('id="testWebdavBackupBtn"', settings_html)
        self.assertIn('id="uploadWebdavBackupBtn"', settings_html)
        self.assertIn('id="webdavBackupTestResult"', settings_html)
        self.assertIn('请先在 WebDAV 服务中创建目录', settings_html)
        self.assertIn('https://dav.jianguoyun.com/dav/mailBackup', settings_html)
        self.assertLess(settings_html.index('id="webdavBackupPassword"'), settings_html.index('id="testWebdavBackupBtn"'))
        self.assertLess(settings_html.index('id="testWebdavBackupBtn"'), settings_html.index('id="webdavBackupCron"'))
        self.assertIn('selectWebdavBackupCronExample', settings_html)
        self.assertIn('async function validateWebdavBackupCronExpression()', settings_js)
        self.assertIn('async function testWebdavBackup()', settings_js)
        self.assertIn('async function uploadWebdavBackupNow()', settings_js)
        self.assertIn("fetch('/api/settings/test-webdav-backup'", settings_js)
        self.assertIn("fetch('/api/settings/upload-webdav-backup'", settings_js)
        self.assertIn('expected_fields: 5', settings_js)
        self.assertIn('settings.webdav_backup_verify_password = webdavBackupVerifyPassword;', settings_js)
        self.assertIn('.settings-sidebar-list', settings_css)
        self.assertIn('overflow-y: auto;', settings_css)
        self.assertIn('scrollbar-width: thin;', settings_css)

    def test_retention_status_poll_uses_backoff_constants(self):
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')

        self.assertIn('NORMAL_MAIL_RETENTION_STATUS_INITIAL_POLL_MS = 2000', settings_js)
        self.assertIn('NORMAL_MAIL_RETENTION_STATUS_MAX_POLL_MS = 10000', settings_js)
        self.assertIn('function nextNormalMailRetentionStatusPollDelay()', settings_js)
        self.assertIn('normalMailRetentionStatusPollDelayMs * 1.5', settings_js)
        self.assertIn('resetNormalMailRetentionStatusPollDelay();', settings_js)
        self.assertNotIn('}, 1000);', settings_js)

    def test_temp_email_list_uses_selected_tag_filters(self):
        temp_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '03-temp-emails.js').read_text(encoding='utf-8')

        self.assertIn('selectedTagFilters.size > 0', temp_js)
        self.assertNotIn('selectedTagIds', temp_js)

    def test_temp_email_cloudflare_global_search_is_case_insensitive(self):
        temp_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '03-temp-emails.js').read_text(encoding='utf-8')

        self.assertIn('const normalizedSearchQuery = searchQuery.toLowerCase();', temp_js)
        self.assertIn('cloudflareGlobalLabel.toLowerCase().includes(normalizedSearchQuery)', temp_js)

    def test_account_search_terms_are_not_limited_to_emails(self):
        groups_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '02-groups.js').read_text(encoding='utf-8')

        self.assertNotIn('isAccountEmailSearchTerm', groups_js)
        self.assertNotIn('splitTerms.every', groups_js)
        self.assertIn('return Array.from(new Set(splitTerms));', groups_js)
        self.assertIn('ACCOUNT_SEARCH_MAX_TERMS = 200', groups_js)
        self.assertIn('搜索关键词最多支持 200 个', groups_js)

    def test_save_settings_separates_saved_refresh_failure(self):
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')

        refresh_block = (
            "try {\n"
            "                await loadGroups();\n"
            "                await refreshVisibleAccountList(false);\n"
            "            } catch (error) {\n"
            "                showToast('设置已保存，但列表刷新失败，请刷新页面', 'warning');"
        )

        self.assertIn(refresh_block, settings_js)
        self.assertIn("showToast('设置已保存，但列表刷新失败，请刷新页面', 'warning');", settings_js)
        self.assertIn("showToast('保存设置失败', 'error');\n                return;", settings_js)
        self.assertLess(
            settings_js.index('if (!data.success)'),
            settings_js.index("showToast('设置已保存，但列表刷新失败，请刷新页面', 'warning');")
        )

    def test_attachment_download_url_builders_include_id_mode(self):
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        self.assertIn('function appendEmailIdModeParam(query, email)', emails_js)
        self.assertIn("query.set('id_mode', idMode);", emails_js)
        self.assertIn('appendEmailIdModeParam(query, email);', emails_js)
        self.assertIn('function buildAttachmentDownloadUrl(email, attachment)', emails_js)
        self.assertIn('function buildAllAttachmentsDownloadUrl(email)', emails_js)
        self.assertIn('new URLSearchParams()', emails_js)

    def test_attachment_download_links_use_busy_fetch_handler(self):
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        self.assertIn('function downloadEmailAttachmentFile(event, link)', emails_js)
        self.assertIn('onclick="downloadEmailAttachmentFile(event, this)"', emails_js)
        self.assertIn("link.textContent = isDownloading ? '打包中...' : link.dataset.defaultLabel;", emails_js)
        self.assertIn("action.textContent = isDownloading ? '下载中...' : '下载';", emails_js)
        self.assertIn("showToast(pendingMessage, 'info');", emails_js)

    def test_local_retention_load_more_keeps_source_local(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')

        self.assertIn('function buildLoadMoreEmailsUrl(nextSkip)', core_js)
        self.assertIn("query.set('source', 'local');", core_js)
        self.assertIn("currentMethod === 'local' || cache?.local_retention === true", core_js)
        self.assertIn('buildLoadMoreEmailsUrl(nextSkip)', core_js)
        self.assertNotIn('?method=${currentMethod}&folder=${currentFolder}&skip=${nextSkip}&top=20', core_js)

    def test_local_retention_load_more_applies_pending_new_mail_first(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        load_more_block = core_js[
            core_js.index('async function loadMoreEmails()'):
            core_js.index('            isLoadingMore = true;', core_js.index('async function loadMoreEmails()'))
        ]
        self.assertIn('function hasPendingNewMailSync', emails_js)
        self.assertIn('hasPendingNewMailSync(currentAccount, currentFolder)', load_more_block)
        self.assertIn('applyPendingNewMailSync();', load_more_block)

    def test_normal_mail_retention_clear_invalidates_frontend_cache(self):
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')

        self.assertIn('function invalidateNormalMailRetentionCaches(options = {})', core_js)
        self.assertIn('isNormalMailRetentionCache(cacheValue)', core_js)
        self.assertIn("invalidateNormalMailRetentionCaches({ resetCurrentView: true });", settings_js)
        self.assertIn('wasRetentionEnabled && !normalMailLocalRetentionEnabled', settings_js)

    def test_new_mail_notice_stages_rows_until_user_accepts(self):
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        queue_start = emails_js.index('function queuePendingNewMailSync')
        apply_start = emails_js.index('function applyPendingNewMailSync')
        queue_block = emails_js[queue_start:apply_start]
        apply_block = emails_js[apply_start:emails_js.index('function applyMergedRemoteEmailSync')]

        self.assertIn('pendingNewMailSyncs.set(syncKey', queue_block)
        self.assertIn('announceNewlySyncedEmailRows(data, newlySyncedRows, options.folder, syncKey);', queue_block)
        self.assertNotIn('currentEmails =', queue_block)
        self.assertNotIn('renderEmailList(currentEmails);', queue_block)
        self.assertNotIn('mergedEmails:', queue_block)

        self.assertIn('const mergeResult = mergeEmailListByStableKey(', apply_block)
        self.assertIn('currentEmails = mergeResult.emails;', apply_block)
        self.assertIn('renderEmailList(currentEmails);', apply_block)
        self.assertIn('requestBodyRetentionForNewRows(newlySyncedRows, pending.options.folder);', apply_block)
        self.assertIn('scheduleNewEmailHighlightClear();', apply_block)

        self.assertIn("notice.setAttribute('role', 'button');", emails_js)
        self.assertIn("notice.setAttribute('tabindex', '0');", emails_js)
        self.assertIn('notice.replaceChildren();', emails_js)
        self.assertIn("hint.textContent = '点击显示';", emails_js)
        self.assertIn('NEW_EMAIL_HIGHLIGHT_CLEAR_DELAY_MS', emails_js)
        self.assertNotIn('已自动显示', emails_js)
        self.assertNotIn('cacheRemoteEmailSyncResult', emails_js)

    def test_provider_fallback_uses_id_mode_for_detail_raw_and_attachments(self):
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        self.assertIn('function getCurrentEmailRemoteActionMethod(emailItem = {})', emails_js)
        self.assertIn("if (idMode === 'graph')", emails_js)
        self.assertIn("if (idMode === 'uid' || idMode === 'sequence')", emails_js)
        self.assertIn('method: getCurrentEmailRemoteActionMethod(selectedEmail)', emails_js)
        self.assertIn("query.set('method', getCurrentEmailRemoteActionMethod(email));", emails_js)
        self.assertIn('const method = encodeURIComponent(getCurrentEmailRemoteActionMethod(currentEmailDetail));', emails_js)
        self.assertIn("id_mode: data.email?.id_mode || selectedEmail?.id_mode || ''", emails_js)

    def test_account_sort_ui_uses_sort_order_and_created_at(self):
        layout_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')
        settings_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-management.html').read_text(encoding='utf-8')
        dialog_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-primary.html').read_text(encoding='utf-8')
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        groups_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '02-groups.js').read_text(encoding='utf-8')
        settings_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '07-settings.js').read_text(encoding='utf-8')

        self.assertNotIn('data-sort="refresh_time"', layout_html)
        self.assertIn('data-sort="sort_order"', layout_html)
        self.assertIn('data-sort="created_at"', layout_html)
        self.assertIn('id="settingsShowAccountCreatedAt"', settings_html)
        self.assertIn('id="settingsShowAccountSortOrder"', settings_html)
        self.assertIn('id="settingsShowGroupId"', settings_html)
        self.assertIn('id="editSortOrder"', dialog_html)
        self.assertIn("let currentSortBy = 'sort_order';", groups_js)
        self.assertIn("currentSortBy === 'sort_order'", groups_js)
        self.assertIn("currentSortBy === 'created_at'", groups_js)
        self.assertNotIn("currentSortBy === 'refresh_time'", groups_js)
        self.assertIn('shouldShowAccountCreatedAt()', groups_js)
        self.assertIn('shouldShowAccountSortOrder()', groups_js)
        self.assertIn('排序值 ${escapeHtml(String(sortOrder))}', groups_js)
        self.assertIn('formatAbsoluteDateTime(acc.created_at)', groups_js)
        self.assertIn("document.getElementById('editSortOrder').value = Number(acc.sort_order || 0);", settings_js)
        self.assertIn("document.getElementById('settingsShowAccountCreatedAt').checked = String(data.settings.show_account_created_at) !== 'false';", settings_js)
        self.assertIn('settings.show_account_created_at = showAccountCreatedAt;', settings_js)
        self.assertIn("document.getElementById('settingsShowAccountSortOrder').checked = String(data.settings.show_account_sort_order) === 'true';", settings_js)
        self.assertIn('settings.show_account_sort_order = showAccountSortOrder;', settings_js)
        self.assertIn("document.getElementById('settingsShowGroupId').checked = String(data.settings.show_group_id) !== 'false';", settings_js)
        self.assertIn('settings.show_group_id = showGroupId;', settings_js)
        self.assertIn("setShowGroupId(String(data?.settings?.show_group_id) !== 'false');", core_js)
        self.assertIn('if (!shouldShowGroupId()) {', core_js)

    def test_settings_ui_reorganizes_general_and_gptmail_sections(self):
        settings_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-management.html').read_text(encoding='utf-8')

        general_section = settings_html.split('id="settingsGeneralSection"', 1)[1].split('</section>', 1)[0]
        gptmail_section = settings_html.split('id="settingsAccessSection"', 1)[1].split('</section>', 1)[0]

        self.assertIn('GPTMail 临时邮箱设置', settings_html)
        self.assertIn('id="settingsPassword"', general_section)
        self.assertIn('id="settingsExternalApiKey"', general_section)
        self.assertIn('id="settingsShowGroupId"', general_section)
        self.assertNotIn('id="settingsApiKey"', general_section)

        self.assertIn('id="settingsApiKey"', gptmail_section)
        self.assertNotIn('id="settingsPassword"', gptmail_section)
        self.assertNotIn('id="settingsExternalApiKey"', gptmail_section)

    def test_temp_mail_settings_sections_are_placed_last(self):
        settings_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-management.html').read_text(encoding='utf-8')

        self.assertLess(settings_html.index('data-target="settingsGeneralSection"'), settings_html.index('data-target="settingsRefreshSection"'))
        self.assertLess(settings_html.index('data-target="settingsRefreshSection"'), settings_html.index('data-target="forwardingSettingsSection"'))
        self.assertLess(settings_html.index('data-target="forwardingSettingsSection"'), settings_html.index('data-target="settingsAccessSection"'))
        self.assertLess(settings_html.index('data-target="settingsAccessSection"'), settings_html.index('data-target="settingsDuckMailSection"'))
        self.assertLess(settings_html.index('data-target="settingsDuckMailSection"'), settings_html.index('data-target="settingsCloudflareSection"'))

        self.assertLess(settings_html.index('id="forwardingSettingsSection"'), settings_html.index('id="settingsAccessSection"'))
        self.assertLess(settings_html.index('id="settingsAccessSection"'), settings_html.index('id="settingsDuckMailSection"'))
        self.assertLess(settings_html.index('id="settingsDuckMailSection"'), settings_html.index('id="settingsCloudflareSection"'))

    def test_version_popover_mentions_docker_only_online_update_setup(self):
        layout_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')

        self.assertIn('仅 Docker 版本支持在线更新', layout_html)
        self.assertIn('README 中的「启用界面 Docker 在线更新」', layout_html)
        self.assertIn('https://github.com/assast/outlookEmail#readme', layout_html)

    def test_version_chip_shows_upgrade_badge_markup_and_logic(self):
        layout_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        navbar_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'index', '02-navbar.css').read_text(encoding='utf-8')

        self.assertIn('id="appVersionUpgradeBadge"', layout_html)
        self.assertIn('aria-hidden="true"', layout_html)
        self.assertIn('stroke="currentColor"', layout_html)
        self.assertNotIn('id="appVersionUpgradeBadge" hidden>升级</span>', layout_html)
        self.assertIn("const upgradeBadgeEl = document.getElementById('appVersionUpgradeBadge');", core_js)
        self.assertIn("const shouldShowUpgradeBadge = state === 'update_available';", core_js)
        self.assertIn('upgradeBadgeEl.hidden = !shouldShowUpgradeBadge;', core_js)
        self.assertIn('loadVersionStatus();', core_js)
        self.assertIn('.app-version-chip__upgrade-badge {', navbar_css)
        self.assertIn('background: linear-gradient(180deg, #fef3c7 0%, #fde68a 100%);', navbar_css)
        self.assertIn('color: #92400e;', navbar_css)
        self.assertIn('.app-version-chip__upgrade-badge svg {', navbar_css)

    def test_version_chip_uses_up_arrow_icon_and_respects_hidden_attribute(self):
        layout_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')
        navbar_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'index', '02-navbar.css').read_text(encoding='utf-8')

        self.assertIn('<path d="M8 12.5V3.5"></path>', layout_html)
        self.assertIn('<path d="M4.5 7L8 3.5 11.5 7"></path>', layout_html)
        self.assertIn('.app-version-chip__upgrade-badge[hidden] {', navbar_css)

    def test_refresh_management_ui_uses_account_workbench_layout(self):
        settings_html = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-management.html').read_text(encoding='utf-8')
        core_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '01-core.js').read_text(encoding='utf-8')
        refresh_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '08-refresh.js').read_text(encoding='utf-8')
        batch_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '10-batch-actions.js').read_text(encoding='utf-8')
        modal_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'index', '06-modals-toast.css').read_text(encoding='utf-8')

        self.assertIn('id="refreshSearchInput"', settings_html)
        self.assertIn('id="refreshAccountList"', settings_html)
        self.assertIn('id="stopRefreshBtn"', settings_html)
        self.assertIn('id="refreshLogsList"', settings_html)
        self.assertIn('id="refreshSelectedSummary"', settings_html)
        self.assertIn('id="refreshSelectVisibleBtn"', settings_html)
        self.assertIn('id="refreshSelectedBtn"', settings_html)
        self.assertIn('id="refreshDeleteSelectedBtn"', settings_html)
        self.assertIn('class="refresh-account-table-wrap"', settings_html)
        self.assertIn('data-status="never"', settings_html)
        self.assertNotIn('id="refreshProgressBanner"', settings_html)
        self.assertNotIn('onclick="loadFailedLogs()"', settings_html)
        self.assertNotIn('onclick="loadRefreshLogs()"', settings_html)
        self.assertIn("setModalVisible('genericConfirmModal', true);", core_js)
        self.assertIn('async function loadRefreshStatusList()', refresh_js)
        self.assertIn('async function startRefreshEventStream(url, options = {})', refresh_js)
        self.assertIn('async function stopFullRefresh()', refresh_js)
        self.assertIn("refreshModalState.eventSource = eventSource;", refresh_js)
        self.assertIn("data.type === 'account_result'", refresh_js)
        self.assertIn("data.type === 'stopped'", refresh_js)
        self.assertIn('/api/accounts/refresh-failed-stream', refresh_js)
        self.assertIn("selectedAccountIds: new Set()", refresh_js)
        self.assertIn("function toggleRefreshVisibleSelection()", refresh_js)
        self.assertIn("function clearRefreshSelectionForScopeChange()", refresh_js)
        self.assertIn("if (nextQuery !== refreshModalState.query)", refresh_js)
        self.assertIn("if (nextStatus !== refreshModalState.status)", refresh_js)
        self.assertIn("async function refreshSelectedRefreshAccounts()", refresh_js)
        self.assertIn("async function deleteSelectedRefreshAccounts()", refresh_js)
        self.assertIn("await refreshVisibleAccountList(true);", refresh_js)
        self.assertIn("fetch('/api/accounts/refresh-selected-stream'", refresh_js)
        self.assertIn('data.stream_url', refresh_js)
        self.assertNotIn('/api/accounts/refresh-selected-stream?', refresh_js)
        self.assertIn("fetch('/api/accounts/batch-delete'", refresh_js)
        self.assertIn('<table class="refresh-account-table">', refresh_js)
        self.assertIn('class="refresh-account-select-checkbox"', refresh_js)
        self.assertIn("function setRefreshStatusFilter(status, triggerEl = null)", refresh_js)
        self.assertIn("async function openRefreshModalWithStatus(status = 'all')", refresh_js)
        self.assertNotIn('showFailedListFromData', refresh_js)
        self.assertNotIn('loadRefreshLogs', refresh_js)
        self.assertNotIn('setRefreshProgressBanner', refresh_js)
        self.assertIn("await openRefreshModalWithStatus('failed');", batch_js)
        self.assertIn('.refresh-log-panel', modal_css)
        self.assertIn('.refresh-log-list', modal_css)
        self.assertIn('.refresh-account-table-wrap', modal_css)
        self.assertIn('.refresh-account-table', modal_css)
        self.assertIn('.refresh-batch-actions', modal_css)
        self.assertIn('.refresh-account-select-checkbox', modal_css)
        self.assertIn('.refresh-filter-chip', modal_css)
        self.assertNotIn('.refresh-progress-banner', modal_css)


class DesktopPackagedRuntimeTests(unittest.TestCase):
    def test_frozen_macos_main_uses_desktop_app_runner(self):
        runner_calls = []

        def fake_run_desktop_app(access_url, host, port):
            runner_calls.append((access_url, host, port))

        with patch.dict(os.environ, {
            'PORT': '51234',
            'HOST': '127.0.0.1',
            'FLASK_ENV': 'production',
        }, clear=False), \
             patch.object(web_outlook_app, 'is_frozen', return_value=True), \
             patch.object(web_outlook_app.os, 'name', 'posix'), \
             patch.object(web_outlook_app.sys, 'platform', 'darwin'), \
             patch.object(web_outlook_app, 'run_desktop_app', side_effect=fake_run_desktop_app), \
             patch.object(web_outlook_app, 'init_scheduler') as init_scheduler, \
             patch.object(web_outlook_app.app, 'run') as app_run, \
             patch('builtins.print'):
            web_outlook_app.main()

        self.assertEqual(runner_calls, [('http://127.0.0.1:51234', '127.0.0.1', 51234)])
        init_scheduler.assert_not_called()
        app_run.assert_not_called()

    def test_desktop_app_tray_exit_stops_background_server(self):
        events = []

        class FakeServer:
            def __init__(self, host, port):
                events.append(('server', host, port))

            def start(self):
                events.append('start')

            def stop(self):
                events.append('stop')

        class FakeTimer:
            def __init__(self, delay, callback):
                self.delay = delay
                self.callback = callback

            def start(self):
                events.append(('timer', self.delay))

        class FakeTrayApp:
            def __init__(self, tooltip, on_open, on_exit):
                self.tooltip = tooltip
                self.on_open = on_open
                self.on_exit = on_exit

            def run(self):
                events.append(('tray', self.tooltip))
                self.on_exit()

        fake_tray_module = types.ModuleType('outlook_web.windows_tray')
        fake_tray_module.WindowsTrayApp = FakeTrayApp

        with patch.object(web_outlook_app, 'DesktopServer', FakeServer), \
             patch.object(web_outlook_app.threading, 'Timer', FakeTimer), \
             patch.dict(sys.modules, {'outlook_web.windows_tray': fake_tray_module}):
            web_outlook_app.run_desktop_app('http://127.0.0.1:51234', '127.0.0.1', 51234)

        self.assertEqual(events, [
            ('server', '127.0.0.1', 51234),
            'start',
            ('timer', 1.0),
            ('tray', 'OutlookEmail'),
            'stop',
        ])

class SchedulerTimezoneMigrationTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute("DELETE FROM settings WHERE key = 'app_timezone'")
            db.execute("UPDATE settings SET value = 'true' WHERE key = 'enable_scheduled_refresh'")
            db.execute("UPDATE settings SET value = 'false' WHERE key = 'use_cron_schedule'")
            db.commit()

        web_outlook_app.shutdown_scheduler()

    def tearDown(self):
        web_outlook_app.shutdown_scheduler()

    def test_init_db_restores_default_timezone_for_legacy_database(self):
        with self.app.app_context():
            web_outlook_app.init_db()

            self.assertEqual(
                web_outlook_app.get_setting('app_timezone'),
                web_outlook_app.DEFAULT_APP_TIMEZONE,
            )
            self.assertEqual(
                web_outlook_app.get_app_timezone(),
                web_outlook_app.DEFAULT_APP_TIMEZONE,
            )

    def test_scheduler_uses_default_timezone_when_legacy_database_lacks_setting(self):
        class FakeScheduler:
            def __init__(self, timezone=None):
                self.timezone = timezone
                self.jobs = []
                self.started = False

            def add_job(self, func=None, trigger=None, **kwargs):
                self.jobs.append({'func': func, 'trigger': trigger, **kwargs})

            def start(self):
                self.started = True

            def shutdown(self, wait=True):
                self.started = False

        def fake_cron_trigger(**kwargs):
            return {'trigger': 'cron', 'kwargs': kwargs}

        with self.app.app_context():
            web_outlook_app.init_db()
            self.assertEqual(web_outlook_app.get_setting('app_timezone'), web_outlook_app.DEFAULT_APP_TIMEZONE)

        with patch('apscheduler.schedulers.background.BackgroundScheduler', FakeScheduler), \
             patch('apscheduler.triggers.cron.CronTrigger', side_effect=fake_cron_trigger), \
             patch('atexit.register'), \
             patch('builtins.print'):
            scheduler = web_outlook_app.init_scheduler()

        self.assertIsInstance(scheduler, FakeScheduler)
        self.assertTrue(scheduler.started)
        self.assertEqual(str(scheduler.timezone), web_outlook_app.DEFAULT_APP_TIMEZONE)
        self.assertTrue(any(job.get('id') == 'token_refresh' for job in scheduler.jobs))

    def test_scheduler_supports_forward_interval_sixty_minutes(self):
        class FakeScheduler:
            def __init__(self, timezone=None):
                self.timezone = timezone
                self.jobs = []
                self.started = False

            def add_job(self, func=None, trigger=None, **kwargs):
                self.jobs.append({'func': func, 'trigger': trigger, **kwargs})

            def start(self):
                self.started = True

            def shutdown(self, wait=True):
                self.started = False

        def fake_cron_trigger(**kwargs):
            return {'trigger': 'cron', 'kwargs': kwargs}

        with self.app.app_context():
            web_outlook_app.init_db()
            self.assertTrue(web_outlook_app.set_setting('forward_check_interval_minutes', '60'))
            web_outlook_app.shutdown_scheduler()

        with patch('apscheduler.schedulers.background.BackgroundScheduler', FakeScheduler), \
             patch('apscheduler.triggers.cron.CronTrigger', side_effect=fake_cron_trigger), \
             patch('atexit.register'), \
             patch('builtins.print'):
            scheduler = web_outlook_app.init_scheduler()

        self.assertIsInstance(scheduler, FakeScheduler)
        self.assertTrue(scheduler.started)
        forward_job = next(job for job in scheduler.jobs if job.get('id') == 'forward_mail')
        self.assertEqual(forward_job['trigger']['kwargs']['minute'], 0)
        self.assertNotIn('*/60', str(forward_job['trigger']['kwargs']))

    def test_scheduler_atexit_callback_is_idempotent_after_manual_shutdown(self):
        registered_callbacks = []

        class FakeScheduler:
            def __init__(self, timezone=None):
                self.timezone = timezone
                self.jobs = []
                self.started = False
                self.shutdown_calls = 0

            def add_job(self, func=None, trigger=None, **kwargs):
                self.jobs.append({'func': func, 'trigger': trigger, **kwargs})

            def start(self):
                self.started = True

            def shutdown(self, wait=True):
                self.shutdown_calls += 1
                if not self.started:
                    raise RuntimeError('Scheduler is not running')
                self.started = False

        def fake_cron_trigger(**kwargs):
            return {'trigger': 'cron', 'kwargs': kwargs}

        with self.app.app_context():
            web_outlook_app.init_db()
            web_outlook_app.shutdown_scheduler()

        with patch('apscheduler.schedulers.background.BackgroundScheduler', FakeScheduler), \
             patch('apscheduler.triggers.cron.CronTrigger', side_effect=fake_cron_trigger), \
             patch('atexit.register', side_effect=lambda fn: registered_callbacks.append(fn)), \
             patch('builtins.print'):
            scheduler = web_outlook_app.init_scheduler()

        self.assertIsInstance(scheduler, FakeScheduler)
        self.assertEqual(len(registered_callbacks), 1)

        web_outlook_app.shutdown_scheduler()
        registered_callbacks[0]()

        self.assertEqual(scheduler.shutdown_calls, 1)
        self.assertFalse(scheduler.started)


if __name__ == '__main__':
    unittest.main()
