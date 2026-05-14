import importlib
import io
import os
import pathlib
import sys
import tempfile
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

        self.assertIn('id="settingsWebdavBackupSection"', settings_html)
        self.assertIn('id="webdavBackupEnabled"', settings_html)
        self.assertIn('id="webdavBackupCron"', settings_html)
        self.assertIn('id="webdavBackupVerifyPassword"', settings_html)
        self.assertIn('id="testWebdavBackupBtn"', settings_html)
        self.assertIn('id="uploadWebdavBackupBtn"', settings_html)
        self.assertIn('id="webdavBackupTestResult"', settings_html)
        self.assertIn('selectWebdavBackupCronExample', settings_html)
        self.assertIn('async function validateWebdavBackupCronExpression()', settings_js)
        self.assertIn('async function testWebdavBackup()', settings_js)
        self.assertIn('async function uploadWebdavBackupNow()', settings_js)
        self.assertIn("fetch('/api/settings/test-webdav-backup'", settings_js)
        self.assertIn("fetch('/api/settings/upload-webdav-backup'", settings_js)
        self.assertIn('expected_fields: 5', settings_js)
        self.assertIn('settings.webdav_backup_verify_password = webdavBackupVerifyPassword;', settings_js)

    def test_temp_email_list_uses_selected_tag_filters(self):
        temp_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '03-temp-emails.js').read_text(encoding='utf-8')

        self.assertIn('selectedTagFilters.size > 0', temp_js)
        self.assertNotIn('selectedTagIds', temp_js)

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

    def test_attachment_download_links_use_busy_fetch_handler(self):
        emails_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '05-emails.js').read_text(encoding='utf-8')

        self.assertIn('function downloadEmailAttachmentFile(event, link)', emails_js)
        self.assertIn('onclick="downloadEmailAttachmentFile(event, this)"', emails_js)
        self.assertIn("link.textContent = isDownloading ? '打包中...' : link.dataset.defaultLabel;", emails_js)
        self.assertIn("action.textContent = isDownloading ? '下载中...' : '下载';", emails_js)
        self.assertIn("showToast(pendingMessage, 'info');", emails_js)

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
