import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-graph-token-scope-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class GraphTokenScopePreferenceTests(unittest.TestCase):
    def setUp(self):
        web_outlook_app.reset_graph_token_scope_cache()

    def test_last_successful_scope_is_tried_first_next_time(self):
        rejected = _FakeResponse(400, {'error': 'invalid_scope'})
        accepted = _FakeResponse(200, {'access_token': 'access-token'})

        with patch.object(
            web_outlook_app,
            'post_with_proxy_fallback',
            side_effect=[rejected, rejected, rejected, accepted],
        ) as first_request:
            web_outlook_app.request_graph_token_response('client-id', 'refresh-token')

        self.assertEqual(
            first_request.call_args.kwargs['data']['scope'],
            'https://graph.microsoft.com/.default',
        )

        with patch.object(
            web_outlook_app,
            'post_with_proxy_fallback',
            return_value=accepted,
        ) as second_request:
            web_outlook_app.request_graph_token_response('client-id', 'refresh-token')

        second_request.assert_called_once()
        self.assertEqual(
            second_request.call_args.kwargs['data']['scope'],
            'https://graph.microsoft.com/.default',
        )

    def test_explicit_scope_preference_is_tried_first(self):
        accepted = _FakeResponse(200, {'access_token': 'access-token'})
        explicit_scope = 'https://graph.microsoft.com/Mail.Read offline_access'
        web_outlook_app.register_graph_token_scope_preference(
            'client-id', 'refresh-token', explicit_scope,
        )

        with patch.object(
            web_outlook_app,
            'post_with_proxy_fallback',
            return_value=accepted,
        ) as request:
            web_outlook_app.request_graph_token_response('client-id', 'refresh-token')

        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['data']['scope'], explicit_scope)

    def test_original_scope_fallback_path_ignores_preference(self):
        accepted = _FakeResponse(200, {'access_token': 'access-token'})
        web_outlook_app.register_graph_token_scope_preference(
            'client-id', 'refresh-token',
            'https://graph.microsoft.com/Mail.Read offline_access',
        )

        with patch.object(
            web_outlook_app,
            'post_with_proxy_fallback',
            return_value=accepted,
        ) as request:
            web_outlook_app.request_graph_token_response(
                'client-id', 'refresh-token', include_original_scope_fallback=True,
            )

        first_call_scope = request.call_args_list[0].kwargs['data']['scope']
        self.assertEqual(first_call_scope, 'https://graph.microsoft.com/.default')


class AccountGraphTokenScopePersistenceTests(unittest.TestCase):
    email = 'scope-test@example.com'

    def setUp(self):
        web_outlook_app.reset_graph_token_scope_cache()
        with web_outlook_app.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM accounts WHERE email = ?', (self.email,))
            db.commit()

    def test_add_account_persists_scope_and_registers_preference(self):
        explicit_scope = 'https://graph.microsoft.com/Mail.Read offline_access'
        with web_outlook_app.app.app_context():
            added = web_outlook_app.add_account(
                self.email, 'password', 'scope-client-id', 'scope-refresh-token',
                graph_token_scope=explicit_scope,
            )
            self.assertTrue(added)
            account = web_outlook_app.get_account_by_email(self.email)
            self.assertEqual(account['graph_token_scope'], explicit_scope)
            self.assertEqual(
                web_outlook_app.get_preferred_graph_token_scope(
                    'scope-client-id', 'scope-refresh-token',
                ),
                explicit_scope,
            )

    def test_update_account_can_clear_scope_back_to_auto(self):
        explicit_scope = 'https://graph.microsoft.com/.default'
        with web_outlook_app.app.app_context():
            web_outlook_app.add_account(
                self.email, 'password', 'scope-client-id', 'scope-refresh-token',
                graph_token_scope=explicit_scope,
            )
            account = web_outlook_app.get_account_by_email(self.email)
            updated = web_outlook_app.update_account(
                account['id'], account['email'], '', account['client_id'],
                account['refresh_token'], account.get('group_id') or 1, None, '', 'active',
                account_type='outlook', provider='outlook',
                graph_token_scope='',
            )
            self.assertTrue(updated)
            refreshed = web_outlook_app.get_account_by_id(account['id'])
            self.assertEqual(refreshed['graph_token_scope'], '')
            self.assertEqual(
                web_outlook_app.get_preferred_graph_token_scope(
                    'scope-client-id', 'scope-refresh-token',
                ),
                '',
            )


if __name__ == '__main__':
    unittest.main()
