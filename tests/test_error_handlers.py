import importlib
import os
import tempfile
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-error-handler-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class ErrorHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.previous_testing = self.app.config.get('TESTING')
        self.previous_propagate = self.app.config.get('PROPAGATE_EXCEPTIONS')
        self.app.config['TESTING'] = False
        self.app.config['PROPAGATE_EXCEPTIONS'] = False
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.config['TESTING'] = self.previous_testing
        self.app.config['PROPAGATE_EXCEPTIONS'] = self.previous_propagate

    def test_unknown_route_keeps_http_exception_status_code(self):
        response = self.client.get('/.well-known/appspecific/com.chrome.devtools.json')

        self.assertEqual(response.status_code, 404)

    def test_non_http_exception_still_returns_500(self):
        with self.app.app_context():
            response, status_code = web_outlook_app.handle_exception(RuntimeError('boom'))

        self.assertEqual(status_code, 500)
        self.assertEqual(response.get_json()['success'], False)


if __name__ == '__main__':
    unittest.main()
