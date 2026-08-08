import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-login-session-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')
ROOT_DIR = Path(__file__).resolve().parents[1]


class LoginSessionExpirationTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.previous_testing = self.app.config.get('TESTING')
        self.previous_csrf_enabled = self.app.config.get('WTF_CSRF_ENABLED')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            web_outlook_app.init_db()
            self.previous_password = web_outlook_app.get_setting('login_password')
            self.previous_version = web_outlook_app.get_setting(
                web_outlook_app.LOGIN_SESSION_VERSION_SETTING_KEY,
            )
            web_outlook_app.set_setting(
                'login_password',
                web_outlook_app.hash_password('login-test-password'),
            )
            web_outlook_app.set_setting(
                web_outlook_app.LOGIN_SESSION_VERSION_SETTING_KEY,
                web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION,
            )
            web_outlook_app.login_attempts.clear()
            web_outlook_app.extension_login_tokens.clear()

    def tearDown(self):
        with self.app.app_context():
            if self.previous_password is None:
                web_outlook_app.get_db().execute(
                    "DELETE FROM settings WHERE key = 'login_password'"
                )
            else:
                web_outlook_app.set_setting('login_password', self.previous_password)
            if self.previous_version is None:
                web_outlook_app.get_db().execute(
                    'DELETE FROM settings WHERE key = ?',
                    (web_outlook_app.LOGIN_SESSION_VERSION_SETTING_KEY,),
                )
            else:
                web_outlook_app.set_setting(
                    web_outlook_app.LOGIN_SESSION_VERSION_SETTING_KEY,
                    self.previous_version,
                )
            web_outlook_app.get_db().commit()
            web_outlook_app.login_attempts.clear()
            web_outlook_app.extension_login_tokens.clear()
        self.app.config['TESTING'] = self.previous_testing
        if self.previous_csrf_enabled is None:
            self.app.config.pop('WTF_CSRF_ENABLED', None)
        else:
            self.app.config['WTF_CSRF_ENABLED'] = self.previous_csrf_enabled

    def _login(self, client, now, duration=None):
        payload = {'password': 'login-test-password'}
        if duration is not None:
            payload['session_duration_days'] = duration
        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
            response = client.post('/login', json=payload)
        return response

    def test_login_options_and_default_record_absolute_expiration(self):
        now = 1_700_000_000
        expected_lifetime = 24 * 60 * 60

        self.assertEqual(
            self.app.config['PERMANENT_SESSION_LIFETIME'],
            180 * expected_lifetime,
        )
        for duration in web_outlook_app.LOGIN_SESSION_DURATION_OPTIONS:
            client = self.app.test_client()
            response = self._login(client, now, str(duration))
            self.assertEqual(response.status_code, 200)
            with client.session_transaction() as session:
                self.assertEqual(
                    session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                    now + duration * expected_lifetime,
                )

        default_client = self.app.test_client()
        response = self._login(default_client, now)
        self.assertEqual(response.status_code, 200)
        with default_client.session_transaction() as session:
            self.assertEqual(
                session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                now + web_outlook_app.DEFAULT_LOGIN_SESSION_DURATION_DAYS * expected_lifetime,
            )

    def test_invalid_duration_does_not_create_or_overwrite_session(self):
        now = 1_700_000_000
        response = self._login(self.client, now, 30)
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            original_expiration = session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY]

        for invalid_value in (60, None, True, 30.0, ''):
            with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
                response = self.client.post(
                    '/login',
                    json={
                        'password': 'login-test-password',
                        'session_duration_days': invalid_value,
                    },
                )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()['error'], '登录有效期无效')
            with self.client.session_transaction() as session:
                self.assertTrue(session.get('logged_in'))
                self.assertEqual(
                    session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                    original_expiration,
                )

    def test_expiration_is_absolute_and_protects_page_api_and_sse(self):
        now = 1_700_000_000
        duration = 7
        deadline = now + duration * 24 * 60 * 60

        active_client = self.app.test_client()
        self.assertEqual(self._login(active_client, now, duration).status_code, 200)
        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now + 1):
            active_response = active_client.get('/api/settings')
        self.assertEqual(active_response.status_code, 200)
        with active_client.session_transaction() as session:
            self.assertEqual(
                session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                deadline,
            )

        page_client = self.app.test_client()
        self.assertEqual(self._login(page_client, now, duration).status_code, 200)
        with patch.object(web_outlook_app, 'get_login_session_now', return_value=deadline):
            page_response = page_client.get('/')
        self.assertEqual(page_response.status_code, 302)
        self.assertTrue(page_response.headers['Location'].endswith('/login'))

        api_client = self.app.test_client()
        self.assertEqual(self._login(api_client, now, duration).status_code, 200)
        with patch.object(web_outlook_app, 'get_login_session_now', return_value=deadline):
            api_response = api_client.get('/api/settings')
            sse_response = api_client.get('/api/accounts/refresh-all')
        self.assertEqual(api_response.status_code, 401)
        self.assertTrue(api_response.get_json()['need_login'])
        self.assertEqual(sse_response.status_code, 401)
        with api_client.session_transaction() as session:
            self.assertFalse(session.get('logged_in'))
            self.assertIsNone(session.get(web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY))

    def test_legacy_session_migrates_and_password_change_preserves_deadline(self):
        now = 1_700_000_000
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['login_session_version'] = web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION

        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
            response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            migrated_expiration = session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY]
        self.assertEqual(
            migrated_expiration,
            now + web_outlook_app.DEFAULT_LOGIN_SESSION_DURATION_DAYS * 24 * 60 * 60,
        )

        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
            response = self.client.put(
                '/api/settings',
                json={
                    'login_password': 'new-login-password',
                    'current_login_password': 'login-test-password',
                },
            )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(
                session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                migrated_expiration,
            )

    def test_extension_login_uses_default_duration_and_ticket_remains_one_time(self):
        now = 1_700_000_000
        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
            response = self.client.post(
                '/api/extension/login',
                json={'password': 'login-test-password', 'next': '/#settings'},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['expires_in'], web_outlook_app.EXTENSION_LOGIN_TOKEN_TTL_SECONDS)

        with patch.object(web_outlook_app, 'get_login_session_now', return_value=now):
            launch_response = self.client.get(payload['launch_url'], follow_redirects=False)
        self.assertEqual(launch_response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(
                session[web_outlook_app.LOGIN_SESSION_EXPIRATION_KEY],
                now + web_outlook_app.DEFAULT_LOGIN_SESSION_DURATION_DAYS * 24 * 60 * 60,
            )

        reused_response = self.client.get(payload['launch_url'], follow_redirects=False)
        self.assertEqual(reused_response.status_code, 302)
        self.assertTrue(reused_response.headers['Location'].endswith('/login'))

    def test_login_template_exposes_duration_memory_without_password_storage(self):
        source = (ROOT_DIR / 'templates' / 'login.html').read_text(encoding='utf-8')

        self.assertIn('<option value="7">7 天</option>', source)
        self.assertIn('<option value="30" selected>30 天</option>', source)
        self.assertIn('<option value="90">90 天</option>', source)
        self.assertIn('<option value="180">180 天</option>', source)
        self.assertIn("const LOGIN_DURATION_STORAGE_KEY = 'outlook_login_duration_days';", source)
        self.assertIn('localStorage.getItem(LOGIN_DURATION_STORAGE_KEY)', source)
        self.assertIn('localStorage.setItem(LOGIN_DURATION_STORAGE_KEY, value)', source)
        self.assertIn('session_duration_days: sessionDuration.value', source)
        self.assertNotRegex(source, r'localStorage\.setItem\([^)]*password')


if __name__ == '__main__':
    unittest.main()
