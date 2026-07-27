import importlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.exceptions import BadRequest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-error-handler-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')
ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '01-core.js'


class ErrorHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.previous_testing = self.app.config.get('TESTING')
        self.previous_propagate = self.app.config.get('PROPAGATE_EXCEPTIONS')
        self.previous_csrf_enabled = self.app.config.get('WTF_CSRF_ENABLED')
        self.previous_csrf_check_default = self.app.config.get('WTF_CSRF_CHECK_DEFAULT')
        self.app.config['TESTING'] = False
        self.app.config['PROPAGATE_EXCEPTIONS'] = False
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.config['TESTING'] = self.previous_testing
        self.app.config['PROPAGATE_EXCEPTIONS'] = self.previous_propagate
        self.app.config['WTF_CSRF_ENABLED'] = self.previous_csrf_enabled
        if self.previous_csrf_check_default is None:
            self.app.config.pop('WTF_CSRF_CHECK_DEFAULT', None)
        else:
            self.app.config['WTF_CSRF_CHECK_DEFAULT'] = self.previous_csrf_check_default

    def test_unknown_route_keeps_http_exception_status_code(self):
        response = self.client.get('/.well-known/appspecific/com.chrome.devtools.json')

        self.assertEqual(response.status_code, 404)

    def test_non_http_exception_still_returns_500(self):
        with self.app.app_context():
            response, status_code = web_outlook_app.handle_exception(RuntimeError('boom'))

        self.assertEqual(status_code, 500)
        self.assertEqual(response.get_json()['success'], False)

    def test_generic_bad_request_keeps_format_error_message(self):
        with self.app.app_context():
            response, status_code = web_outlook_app.bad_request(BadRequest())

        self.assertEqual(status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['success'], False)
        self.assertEqual(payload['error'], '请求格式错误')
        self.assertNotIn('csrf_error', payload)

    @unittest.skipUnless(getattr(web_outlook_app, 'CSRF_AVAILABLE', False), 'Flask-WTF not installed')
    def test_csrf_error_exposes_flag_for_frontend_retry(self):
        from flask_wtf.csrf import CSRFError

        with self.app.app_context():
            response, status_code = web_outlook_app.bad_request(
                CSRFError('The CSRF token is missing.')
            )

        self.assertEqual(status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['success'], False)
        self.assertTrue(payload.get('csrf_error'))
        self.assertIn('CSRF', payload['error'])
        self.assertIn('csrf', str(payload.get('details', '')).lower())

    @unittest.skipUnless(getattr(web_outlook_app, 'CSRF_AVAILABLE', False), 'Flask-WTF not installed')
    def test_missing_csrf_on_account_import_and_oauth_exchange_exposes_flag(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = True
        with self.client.session_transaction() as session:
            session['logged_in'] = True

        with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens') as exchange_mock, \
             patch.object(web_outlook_app, 'add_accounts_bulk') as add_bulk_mock:
            exchange_response = self.client.post(
                '/api/oauth/exchange-token',
                json={'redirected_url': 'http://localhost:8080/?code=abc'},
            )
            import_response = self.client.post(
                '/api/accounts',
                json={
                    'account_string': 'a@example.com----pwd----client----refresh',
                    'group_id': 1,
                },
            )

        self.assertEqual(exchange_response.status_code, 400)
        exchange_payload = exchange_response.get_json()
        self.assertTrue(exchange_payload.get('csrf_error'))
        self.assertIn('CSRF', exchange_payload.get('error', ''))
        exchange_mock.assert_not_called()

        self.assertEqual(import_response.status_code, 400)
        import_payload = import_response.get_json()
        self.assertTrue(import_payload.get('csrf_error'))
        self.assertIn('CSRF', import_payload.get('error', ''))
        add_bulk_mock.assert_not_called()

    def test_frontend_csrf_retry_detects_csrf_error_flag(self):
        source = CORE_JS_PATH.read_text(encoding='utf-8')
        self.assertIn('payload?.csrf_error', source)
        self.assertRegex(
            source,
            re.compile(r'async function isCSRFFailureResponse\(response\)[\s\S]*csrf_error', re.M),
        )


if __name__ == '__main__':
    unittest.main()
