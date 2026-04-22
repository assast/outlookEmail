import importlib
import os
import pathlib
import sys
import tempfile
import unittest
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
        self.assertIn('const timeZone = getAppTimeZone();', oauth_js)
        self.assertIn('timeZone: getAppTimeZone()', refresh_js)


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


if __name__ == '__main__':
    unittest.main()
