import importlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '01-core.js'
SETTINGS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '07-settings.js'
INDEX_TEMPLATE_PATH = ROOT_DIR / 'templates' / 'index.html'
SETTINGS_TEMPLATE_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-management.html'

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-mail-timeout-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class MailFetchTimeoutSettingsTests(unittest.TestCase):
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
            db.execute("DELETE FROM settings WHERE key = 'mail_fetch_timeout_seconds'")
            db.commit()

    def test_get_mail_fetch_timeout_uses_env_default_when_setting_absent(self):
        with self.app.app_context(), patch.dict(
            os.environ,
            {'MAIL_FETCH_OVERALL_TIMEOUT': '95'},
            clear=False,
        ):
            self.assertEqual(web_outlook_app.get_mail_fetch_timeout_seconds(), 95)

    def test_get_mail_fetch_timeout_setting_overrides_env(self):
        with self.app.app_context(), patch.dict(
            os.environ,
            {'MAIL_FETCH_OVERALL_TIMEOUT': '95'},
            clear=False,
        ):
            self.assertTrue(web_outlook_app.set_setting('mail_fetch_timeout_seconds', '180'))

            self.assertEqual(web_outlook_app.get_mail_fetch_timeout_seconds(), 180)

    def test_get_mail_fetch_timeout_without_app_context_uses_env_default(self):
        with patch.dict(os.environ, {'MAIL_FETCH_OVERALL_TIMEOUT': '88'}, clear=False):
            self.assertEqual(web_outlook_app.get_mail_fetch_timeout_seconds(), 88)

    def test_settings_api_exposes_and_updates_mail_fetch_timeout(self):
        with patch.dict(os.environ, {'MAIL_FETCH_OVERALL_TIMEOUT': '120'}, clear=False):
            response = self.client.get('/api/settings')
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['mail_fetch_timeout_seconds'], '120')

        response = self.client.put('/api/settings', json={'mail_fetch_timeout_seconds': 180})
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertIn('邮件获取超时', payload['message'])
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('mail_fetch_timeout_seconds'), '180')

    def test_settings_api_rejects_mail_fetch_timeout_outside_range(self):
        response = self.client.put('/api/settings', json={'mail_fetch_timeout_seconds': 10})
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload['success'])
        self.assertIn('30-300', payload['error'])

    def test_fetch_all_folders_uses_configured_mail_fetch_timeout(self):
        account = {
            'email': 'slow-imap@example.com',
            'account_type': 'imap',
            'provider': 'gmail',
        }
        captured = {}

        def fake_wait(futures, timeout=None):
            futures = list(futures)
            captured['timeout'] = timeout
            return {futures[0]}, set(futures[1:])

        with self.app.app_context(), patch.object(
            web_outlook_app,
            'get_mail_fetch_timeout_seconds',
            return_value=87,
        ), patch.object(
            web_outlook_app,
            'fetch_account_folder_emails',
            return_value={'success': True, 'emails': [], 'has_more': False},
        ), patch.object(web_outlook_app, 'wait', side_effect=fake_wait):
            result = web_outlook_app.fetch_account_emails(account, 'all', 0, 10)

        self.assertEqual(captured['timeout'], 87)
        self.assertTrue(result['partial'])
        self.assertIn('timeout=87s', str(result['details']))

    def test_frontend_mail_fetch_timeout_updates_email_list_request_timeout(self):
        source = CORE_JS_PATH.read_text(encoding='utf-8')
        start = source.index('const DEFAULT_MAIL_FETCH_TIMEOUT_SECONDS')
        end = source.index('const EMAIL_DETAIL_REQUEST_TIMEOUT_MS')
        timeout_source = source[start:end]
        script = f"""
const window = {{ OUTLOOK_EMAIL_CONFIG: {{ mailFetchTimeoutSeconds: 95 }} }};
{timeout_source}
const values = {{
    initialSeconds: getMailFetchTimeoutSeconds(),
    initialRequestMs: EMAIL_LIST_REQUEST_TIMEOUT_MS,
}};
setMailFetchTimeoutSeconds(180);
values.updatedSeconds = getMailFetchTimeoutSeconds();
values.updatedRequestMs = EMAIL_LIST_REQUEST_TIMEOUT_MS;
setMailFetchTimeoutSeconds(10);
values.clampedMinSeconds = getMailFetchTimeoutSeconds();
values.clampedMinRequestMs = EMAIL_LIST_REQUEST_TIMEOUT_MS;
setMailFetchTimeoutSeconds(500);
values.clampedMaxSeconds = getMailFetchTimeoutSeconds();
values.clampedMaxRequestMs = EMAIL_LIST_REQUEST_TIMEOUT_MS;
console.log(JSON.stringify(values));
"""
        result = subprocess.run(
            ['node', '-e', script],
            check=True,
            text=True,
            capture_output=True,
        )
        values = json.loads(result.stdout)

        self.assertEqual(values['initialSeconds'], 95)
        self.assertEqual(values['initialRequestMs'], 105000)
        self.assertEqual(values['updatedSeconds'], 180)
        self.assertEqual(values['updatedRequestMs'], 190000)
        self.assertEqual(values['clampedMinSeconds'], 30)
        self.assertEqual(values['clampedMinRequestMs'], 40000)
        self.assertEqual(values['clampedMaxSeconds'], 300)
        self.assertEqual(values['clampedMaxRequestMs'], 310000)

    def test_frontend_settings_template_and_js_bind_mail_fetch_timeout(self):
        index_template = INDEX_TEMPLATE_PATH.read_text(encoding='utf-8')
        settings_template = SETTINGS_TEMPLATE_PATH.read_text(encoding='utf-8')
        settings_js = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn('mailFetchTimeoutSeconds', index_template)
        self.assertIn('id="mailFetchTimeoutSeconds"', settings_template)
        self.assertIn('min="30" max="300"', settings_template)
        self.assertIn("data.settings.mail_fetch_timeout_seconds", settings_js)
        self.assertIn("settings.mail_fetch_timeout_seconds = mailFetchTimeoutSeconds", settings_js)
        self.assertIn('setMailFetchTimeoutSeconds(mailFetchTimeoutSeconds)', settings_js)


if __name__ == '__main__':
    unittest.main()
