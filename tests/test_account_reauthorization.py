import importlib
import os
import sqlite3
import tempfile
import urllib.parse
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-reauthorize-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class AccountReauthorizationTests(unittest.TestCase):
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
            db.execute('DELETE FROM account_refresh_logs')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM tags')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

    def _add_outlook_account(self, email='reauth@example.com'):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                email,
                'mail-password',
                'old-client-id',
                'old-refresh-token',
                group_id=1,
                remark='keep remark',
                account_type='outlook',
                provider='outlook',
                forward_enabled=True,
                sort_order=7,
                status='active',
                proxy_url='socks5://account-primary:1080',
                fallback_proxy_url_1='http://account-fallback:7890',
                fallback_proxy_url_2='direct',
            )
            self.assertTrue(added)
            account = web_outlook_app.get_account_by_email(email)
            alias_success, _, alias_errors = web_outlook_app.replace_account_aliases(
                account['id'],
                email,
                ['alias@example.com'],
            )
            self.assertTrue(alias_success, alias_errors)
            tag_id = web_outlook_app.add_tag('核心', '#123456')
            db = web_outlook_app.get_db()
            db.execute(
                'INSERT INTO account_tags (account_id, tag_id) VALUES (?, ?)',
                (account['id'], tag_id),
            )
            db.execute(
                '''
                UPDATE accounts
                SET last_refresh_status = 'failed',
                    last_refresh_error = 'old refresh failure',
                    last_refresh_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (account['id'],),
            )
            db.commit()
            return account['id']

    def _token_result(self):
        return {
            'success': True,
            'client_id': 'new-client-id',
            'refresh_token': 'new-refresh-token',
            'token_type': 'Bearer',
            'expires_in': 3600,
            'scope': 'offline_access',
        }

    def _post_reauthorize(self, account_id):
        return self.client.post(
            f'/api/accounts/{account_id}/reauthorize',
            json={'redirected_url': 'http://localhost:8080/?code=auth-code'},
        )

    def test_reauthorize_updates_only_authorization_fields_and_preserves_account_metadata(self):
        account_id = self._add_outlook_account()

        def fake_refresh(account, refresh_type='manual', db_conn=None):
            with sqlite3.connect(web_outlook_app.DATABASE) as external_conn:
                external_conn.row_factory = sqlite3.Row
                external_row = external_conn.execute(
                    '''
                    SELECT client_id, last_refresh_status, last_refresh_error
                    FROM accounts
                    WHERE id = ?
                    ''',
                    (account['id'],),
                ).fetchone()
                self.assertEqual(external_row['client_id'], 'new-client-id')
                self.assertEqual(external_row['last_refresh_status'], 'never')
                self.assertIsNone(external_row['last_refresh_error'])

            row = db_conn.execute(
                'SELECT last_refresh_status, last_refresh_error FROM accounts WHERE id = ?',
                (account['id'],),
            ).fetchone()
            self.assertEqual(row['last_refresh_status'], 'never')
            self.assertIsNone(row['last_refresh_error'])
            web_outlook_app.log_refresh_result(
                account['id'],
                account['email'],
                refresh_type,
                'success',
                db_conn=db_conn,
            )
            return {'success': True, 'message': 'Token 刷新成功'}

        with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens', return_value=self._token_result()), \
             patch.object(web_outlook_app, 'refresh_outlook_account_token', side_effect=fake_refresh):
            response = self._post_reauthorize(account_id)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['authorization_updated'])
        self.assertTrue(payload['validation']['success'])

        with self.app.app_context():
            account = web_outlook_app.get_account_by_id(account_id)
            tag_names = [tag['name'] for tag in web_outlook_app.get_account_tags(account_id)]
            raw = web_outlook_app.get_db().execute(
                '''
                SELECT refresh_token, refresh_token_updated_at, last_refresh_status,
                       last_refresh_error, last_refresh_at
                FROM accounts
                WHERE id = ?
                ''',
                (account_id,),
            ).fetchone()

        self.assertEqual(account['email'], 'reauth@example.com')
        self.assertEqual(account['password'], 'mail-password')
        self.assertEqual(account['client_id'], 'new-client-id')
        self.assertEqual(account['refresh_token'], 'new-refresh-token')
        self.assertEqual(account['group_id'], 1)
        self.assertEqual(account['remark'], 'keep remark')
        self.assertEqual(account['status'], 'active')
        self.assertTrue(account['forward_enabled'])
        self.assertEqual(account['sort_order'], 7)
        self.assertEqual(account['proxy_url'], 'socks5://account-primary:1080')
        self.assertEqual(account['fallback_proxy_url_1'], 'http://account-fallback:7890')
        self.assertEqual(account['fallback_proxy_url_2'], 'direct')
        self.assertEqual(account['aliases'], ['alias@example.com'])
        self.assertEqual(tag_names, ['核心'])
        self.assertTrue(raw['refresh_token'].startswith('enc:'))
        self.assertIsNotNone(raw['refresh_token_updated_at'])
        self.assertEqual(raw['last_refresh_status'], 'success')
        self.assertIsNone(raw['last_refresh_error'])
        self.assertIsNotNone(raw['last_refresh_at'])

    def test_reauthorize_rejects_imap_account_without_modifying_data(self):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                'imap@example.com',
                '',
                '',
                '',
                group_id=1,
                account_type='imap',
                provider='gmail',
                imap_host='imap.gmail.com',
                imap_password='imap-secret',
            )
            self.assertTrue(added)
            account_id = web_outlook_app.get_account_by_email('imap@example.com')['id']

        with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens') as exchange_mock:
            response = self._post_reauthorize(account_id)

        exchange_mock.assert_not_called()
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error']['code'], 'ACCOUNT_REAUTH_UNSUPPORTED')

        with self.app.app_context():
            account = web_outlook_app.get_account_by_id(account_id)
        self.assertEqual(account['account_type'], 'imap')
        self.assertEqual(account['client_id'], '')
        self.assertEqual(account['refresh_token'], '')
        self.assertEqual(account['imap_password'], 'imap-secret')

    def test_reauthorize_rejects_missing_account_without_creating_account(self):
        with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens') as exchange_mock:
            response = self._post_reauthorize(9999)

        exchange_mock.assert_not_called()
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error']['code'], 'ACCOUNT_NOT_FOUND')

        with self.app.app_context():
            count_row = web_outlook_app.get_db().execute('SELECT COUNT(*) AS total FROM accounts').fetchone()
        self.assertEqual(count_row['total'], 0)

    def test_reauthorize_persists_new_refresh_failure_when_validation_fails(self):
        account_id = self._add_outlook_account('failed-validation@example.com')

        def fake_refresh(account, refresh_type='manual', db_conn=None):
            row = db_conn.execute(
                'SELECT last_refresh_status, last_refresh_error FROM accounts WHERE id = ?',
                (account['id'],),
            ).fetchone()
            self.assertEqual(row['last_refresh_status'], 'never')
            self.assertIsNone(row['last_refresh_error'])
            web_outlook_app.log_refresh_result(
                account['id'],
                account['email'],
                refresh_type,
                'failed',
                'new validation failure',
                db_conn=db_conn,
            )
            return {
                'success': False,
                'error_message': 'new validation failure',
                'error_payload': web_outlook_app.build_error_payload(
                    'TOKEN_REFRESH_FAILED',
                    'Token 刷新失败',
                    'RefreshTokenError',
                    400,
                    'new validation failure',
                ),
            }

        with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens', return_value=self._token_result()), \
             patch.object(web_outlook_app, 'refresh_outlook_account_token', side_effect=fake_refresh):
            response = self._post_reauthorize(account_id)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['authorization_updated'])
        self.assertFalse(payload['validation']['success'])
        self.assertEqual(payload['validation']['status'], 'failed')
        self.assertEqual(payload['validation']['error']['code'], 'TOKEN_REFRESH_FAILED')

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                '''
                SELECT last_refresh_status, last_refresh_error, last_refresh_at, refresh_token_updated_at
                FROM accounts
                WHERE id = ?
                ''',
                (account_id,),
            ).fetchone()
            account = web_outlook_app.get_account_by_id(account_id)

        self.assertEqual(account['refresh_token'], 'new-refresh-token')
        self.assertIsNotNone(row['refresh_token_updated_at'])
        self.assertEqual(row['last_refresh_status'], 'failed')
        self.assertEqual(row['last_refresh_error'], 'new validation failure')
        self.assertIsNotNone(row['last_refresh_at'])

    @unittest.skipUnless(getattr(web_outlook_app, 'CSRF_AVAILABLE', False), 'Flask-WTF not installed')
    def test_reauthorize_requires_csrf_when_protection_is_enabled(self):
        original_csrf_enabled = self.app.config.get('WTF_CSRF_ENABLED')
        original_csrf_check_default = self.app.config.get('WTF_CSRF_CHECK_DEFAULT')
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = True
        try:
            with patch.object(web_outlook_app, 'exchange_oauth_code_for_tokens') as exchange_mock:
                response = self._post_reauthorize(123)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = original_csrf_enabled
            if original_csrf_check_default is None:
                self.app.config.pop('WTF_CSRF_CHECK_DEFAULT', None)
            else:
                self.app.config['WTF_CSRF_CHECK_DEFAULT'] = original_csrf_check_default

        self.assertEqual(response.status_code, 400)
        exchange_mock.assert_not_called()

    def test_auth_url_route_uses_imap_only_manual_scope(self):
        response = self.client.get('/api/oauth/auth-url')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['client_id'], web_outlook_app.OAUTH_CLIENT_ID)
        self.assertEqual(payload['redirect_uri'], web_outlook_app.OAUTH_REDIRECT_URI)

        auth_query = urllib.parse.parse_qs(
            urllib.parse.urlparse(payload['auth_url']).query
        )
        scope = auth_query['scope'][0]
        self.assertEqual(scope, ' '.join(web_outlook_app.OAUTH_SCOPES))
        self.assertIn('offline_access', scope)
        self.assertIn('https://outlook.office.com/IMAP.AccessAsUser.All', scope)
        self.assertNotIn('https://graph.microsoft.com/', scope)

    def test_exchange_token_route_keeps_existing_preview_response_shape(self):
        class FakeResponse:
            status_code = 200
            headers = {'content-type': 'application/json'}

            @staticmethod
            def json():
                return {
                    'refresh_token': 'preview-refresh-token',
                    'token_type': 'Bearer',
                    'expires_in': 3600,
                    'scope': 'offline_access',
                }

        with patch.object(web_outlook_app.requests, 'post', return_value=FakeResponse()) as post_mock:
            response = self.client.post(
                '/api/oauth/exchange-token',
                json={'redirected_url': 'http://localhost:8080/?code=preview-code'},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['refresh_token'], 'preview-refresh-token')
        self.assertEqual(payload['client_id'], web_outlook_app.OAUTH_CLIENT_ID)
        self.assertEqual(payload['token_type'], 'Bearer')
        self.assertEqual(post_mock.call_args.kwargs['data']['code'], 'preview-code')
        self.assertEqual(post_mock.call_args.kwargs['data']['scope'], ' '.join(web_outlook_app.OAUTH_SCOPES))
        self.assertIn('https://outlook.office.com/IMAP.AccessAsUser.All', post_mock.call_args.kwargs['data']['scope'])
        self.assertNotIn('https://graph.microsoft.com/', post_mock.call_args.kwargs['data']['scope'])


if __name__ == '__main__':
    unittest.main()
