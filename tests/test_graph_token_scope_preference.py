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
        self.addCleanup(web_outlook_app.reset_graph_token_scope_cache)

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
                required_scope='https://graph.microsoft.com/Mail.Send',
            )

        first_call_scope = request.call_args_list[0].kwargs['data']['scope']
        self.assertEqual(first_call_scope, 'https://graph.microsoft.com/.default')
        self.assertNotIn('scope', request.call_args_list[-1].kwargs['data'])

    def test_write_operations_do_not_reuse_a_read_only_scope(self):
        operations = (
            ('send', 'https://graph.microsoft.com/Mail.Send', lambda: web_outlook_app.send_graph_mail_result(
                'client-id', 'refresh-token', ['recipient@example.com'], 'scope regression', 'test body',
            )),
            ('mark_read', 'https://graph.microsoft.com/Mail.ReadWrite', lambda:
             web_outlook_app.mark_emails_read_graph_result('client-id', 'refresh-token', ['message-id'])),
            ('delete', 'https://graph.microsoft.com/Mail.ReadWrite', lambda:
             web_outlook_app.delete_emails_graph('client-id', 'refresh-token', ['message-id'])),
        )
        for name, required_scope, operation in operations:
            with self.subTest(operation=name):
                web_outlook_app.reset_graph_token_scope_cache()
                web_outlook_app.remember_graph_token_scope(
                    'client-id', 'refresh-token', 'https://graph.microsoft.com/Mail.Read offline_access',
                )
                with patch.object(web_outlook_app, 'post_with_proxy_fallback', return_value=
                                  _FakeResponse(200, {'access_token': 'access-token'})) as token, \
                        patch.object(web_outlook_app, 'post_once_with_primary_proxy', return_value=
                                     _FakeResponse(202, {})) as send, \
                        patch.object(web_outlook_app, 'request_with_proxy_failover', return_value=
                                     _FakeResponse(200, {'responses': [{'id': '0', 'status': 204}]})) as batch:
                    result = operation()

                self.assertTrue(result['success'], result)
                token.assert_called_once()
                self.assertIn(required_scope, token.call_args.kwargs['data']['scope'].split())
                self.assertEqual(send.call_count + batch.call_count, 1)

    def test_send_scope_fallback_skips_candidates_without_send_permission(self):
        web_outlook_app.register_graph_token_scope_preference(
            'client-id', 'refresh-token', 'https://graph.microsoft.com/Mail.Read offline_access',
        )
        rejected = _FakeResponse(400, {'error': 'invalid_scope'})
        accepted = _FakeResponse(200, {'access_token': 'access-token'})
        with patch.object(web_outlook_app, 'post_with_proxy_fallback',
                          side_effect=[rejected, accepted]) as request:
            response = web_outlook_app.request_graph_token_response(
                'client-id', 'refresh-token', required_scope='https://graph.microsoft.com/Mail.Send',
            )

        self.assertIs(response, accepted)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs['data']['scope'], web_outlook_app.GRAPH_DEFAULT_TOKEN_SCOPE)

    def test_write_operations_can_keep_a_remembered_default_scope(self):
        web_outlook_app.remember_graph_token_scope(
            'client-id', 'refresh-token', web_outlook_app.GRAPH_DEFAULT_TOKEN_SCOPE,
        )
        with patch.object(web_outlook_app, 'post_with_proxy_fallback', return_value=
                          _FakeResponse(200, {'access_token': 'access-token'})) as request:
            web_outlook_app.request_graph_token_response(
                'client-id', 'refresh-token', required_scope='https://graph.microsoft.com/Mail.Send',
            )

        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['data']['scope'], web_outlook_app.GRAPH_DEFAULT_TOKEN_SCOPE)

    def test_write_requests_keep_compatible_custom_scope_names(self):
        for scope in ('Mail.Send offline_access', '.default'):
            with self.subTest(scope=scope):
                web_outlook_app.register_graph_token_scope_preference('client-id', 'refresh-token', scope)
                with patch.object(web_outlook_app, 'post_with_proxy_fallback', return_value=
                                  _FakeResponse(200, {'access_token': 'access-token'})) as request:
                    web_outlook_app.request_graph_token_response(
                        'client-id', 'refresh-token', required_scope='https://graph.microsoft.com/Mail.Send',
                    )

                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs['data']['scope'], scope)


class AccountGraphTokenScopePersistenceTests(unittest.TestCase):
    email = 'scope-test@example.com'

    def setUp(self):
        web_outlook_app.reset_graph_token_scope_cache()
        self.addCleanup(web_outlook_app.reset_graph_token_scope_cache)
        with web_outlook_app.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM accounts WHERE email = ?', (self.email,))
            db.commit()

    def _add_account(self, scope=''):
        self.assertTrue(web_outlook_app.add_account(
            self.email, 'password', 'scope-client-id', 'scope-refresh-token',
            graph_token_scope=scope,
        ))
        return web_outlook_app.get_account_by_email(self.email)

    def _update_scope(self, account, scope):
        self.assertTrue(web_outlook_app.update_account(
            account['id'], account['email'], '', account['client_id'],
            account['refresh_token'], account.get('group_id') or 1, None, '', 'active',
            account_type='outlook', provider='outlook', graph_token_scope=scope,
        ))

    def _request_token(self, account):
        with patch.object(web_outlook_app, 'post_with_proxy_fallback', return_value=
                          _FakeResponse(200, {'access_token': 'access-token'})) as request:
            web_outlook_app.request_graph_token_response(account['client_id'], account['refresh_token'])
        return request.call_args.kwargs['data']['scope']

    def test_add_account_persists_scope_and_registers_preference(self):
        explicit_scope = 'https://graph.microsoft.com/Mail.Read offline_access'
        with web_outlook_app.app.app_context():
            account = self._add_account(explicit_scope)
            self.assertEqual(account['graph_token_scope'], explicit_scope)
            self.assertEqual(
                web_outlook_app.get_preferred_graph_token_scope(
                    'scope-client-id', 'scope-refresh-token',
                ),
                explicit_scope,
            )

    def test_update_account_can_clear_scope_back_to_auto(self):
        explicit_scope = 'https://graph.microsoft.com/Mail.Read offline_access'
        with web_outlook_app.app.app_context():
            account = self._add_account(explicit_scope)
            self.assertEqual(self._request_token(account), explicit_scope)
            self._update_scope(account, '')
            # 保存后立即失效，不依赖下一次读取账号来刷新进程内配置。
            self.assertEqual(web_outlook_app.get_preferred_graph_token_scope(
                account['client_id'], account['refresh_token'],
            ), '')
            refreshed = web_outlook_app.get_account_by_id(account['id'])
            self.assertEqual(refreshed['graph_token_scope'], '')
            self.assertEqual(
                web_outlook_app.get_preferred_graph_token_scope(
                    'scope-client-id', 'scope-refresh-token',
                ),
                '',
            )

    def test_returning_to_auto_restores_send_capable_token_requests(self):
        with web_outlook_app.app.app_context():
            account = self._add_account('https://graph.microsoft.com/Mail.Read offline_access')
            self._request_token(account)
            self._update_scope(account, '')
            account = web_outlook_app.get_account_by_id(account['id'])

        def exchange(_url, **kwargs):
            scope = kwargs['data']['scope']
            token = 'send-token' if 'https://graph.microsoft.com/Mail.Send' in scope.split() else 'read-token'
            return _FakeResponse(200, {'access_token': token})

        def submit(_url, **kwargs):
            if kwargs['headers']['Authorization'] == 'Bearer send-token':
                return _FakeResponse(202, {})
            return _FakeResponse(403, {'error': {'code': 'ErrorAccessDenied'}})

        with patch.object(web_outlook_app, 'post_with_proxy_fallback', side_effect=exchange), \
                patch.object(web_outlook_app, 'post_once_with_primary_proxy', side_effect=submit) as send:
            result = web_outlook_app.send_graph_mail_result(
                account['client_id'], account['refresh_token'],
                ['recipient@example.com'], 'scope regression', 'test body',
            )

        self.assertTrue(result['success'], result)
        self.assertTrue(result['submitted'])
        send.assert_called_once()

    def test_auto_account_lookup_keeps_the_remembered_scope(self):
        with web_outlook_app.app.app_context():
            account = self._add_account()
            rejected = _FakeResponse(400, {'error': 'invalid_scope'})
            accepted = _FakeResponse(200, {'access_token': 'access-token'})
            with patch.object(web_outlook_app, 'post_with_proxy_fallback',
                              side_effect=[rejected, rejected, rejected, accepted]):
                web_outlook_app.request_graph_token_response(account['client_id'], account['refresh_token'])
            account = web_outlook_app.get_account_by_id(account['id'])
            self.assertEqual(self._request_token(account), web_outlook_app.GRAPH_DEFAULT_TOKEN_SCOPE)

    def test_background_forwarding_uses_persisted_scope_after_restart(self):
        with web_outlook_app.app.app_context():
            account = self._add_account()
            for scope in (web_outlook_app.GRAPH_DEFAULT_TOKEN_SCOPE,
                          'https://graph.microsoft.com/Mail.Read offline_access'):
                with self.subTest(scope=scope):
                    self._update_scope(account, scope)
                    web_outlook_app.reset_graph_token_scope_cache()
                    # 后台任务使用独立连接读取的原始账号，不能先调用普通账号解析器。
                    row = next(row for row in web_outlook_app.get_forwarding_enabled_accounts()
                               if row['id'] == account['id'])
                    with patch.object(web_outlook_app, 'post_with_proxy_fallback', return_value=
                                      _FakeResponse(200, {'access_token': 'access-token'})) as request, \
                            patch.object(web_outlook_app, 'get_with_proxy_fallback', return_value=
                                         _FakeResponse(200, {'value': []})):
                        result = web_outlook_app.process_forwarding_account(row, {'include_junkemail': False})

                    self.assertFalse(result['had_processing_failure'], result)
                    request.assert_called_once()
                    self.assertEqual(request.call_args.kwargs['data']['scope'], scope)


if __name__ == '__main__':
    unittest.main()
