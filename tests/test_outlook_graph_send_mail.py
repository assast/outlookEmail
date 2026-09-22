import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-graph-send-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {'content-type': 'application/json'}
        self.text = text
        self.reason = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class OutlookGraphSendMailTests(unittest.TestCase):
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
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

    def _add_outlook_account(self, email='sender@outlook.com', authorization_type='graph'):
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                email,
                '',
                'client-id',
                'refresh-token',
                group_id=1,
                account_type='outlook',
                provider='outlook',
            ))
            account = web_outlook_app.get_account_by_email(email)
            db = web_outlook_app.get_db()
            db.execute(
                'UPDATE accounts SET authorization_type = ? WHERE id = ?',
                (authorization_type, account['id']),
            )
            db.commit()
            return account['id']

    def _add_standard_imap_account(self, email='sender@gmail.com'):
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                email,
                '',
                '',
                '',
                group_id=1,
                account_type='imap',
                provider='gmail',
                imap_host='imap.gmail.com',
                imap_password='imap-password',
            ))
            return web_outlook_app.get_account_by_email(email)['id']

    def _post_send(self, account_id, **overrides):
        data = {
            'account_id': account_id,
            'recipients': ['recipient@example.com'],
            'subject': '测试主题',
            'body': '测试正文',
        }
        data.update(overrides)
        return self.client.post('/api/outlook/send-mail', json=data)

    def test_graph_token_scope_candidates_keep_legacy_read_write_fallback_without_mail_send(self):
        candidates = dict(web_outlook_app.get_graph_token_scope_candidates())

        self.assertIn('https://graph.microsoft.com/Mail.Send', candidates['configured'])
        self.assertNotIn('https://graph.microsoft.com/Mail.Send', candidates['read_write'])
        self.assertIn('https://graph.microsoft.com/Mail.ReadWrite', candidates['read_write'])
        self.assertNotIn('https://graph.microsoft.com/Mail.Send', candidates['read'])
        self.assertNotIn('https://graph.microsoft.com/Mail.ReadWrite', candidates['read'])

    def test_send_helper_submits_text_mail_once_without_explicit_sent_items_override(self):
        graph_response = FakeResponse(202, {})
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ) as token_mock, patch.object(web_outlook_app.requests, 'request', return_value=graph_response) as request_mock:
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['Recipient@example.com', 'recipient@example.com'],
                '主题',
                '正文',
                proxy_url='http://primary-proxy:8080',
                fallback_proxy_urls=['http://fallback-proxy:8081'],
            )

        token_mock.assert_called_once_with(
            'client-id',
            'refresh-token',
            'http://primary-proxy:8080',
            ['http://fallback-proxy:8081'],
        )
        self.assertTrue(result['success'])
        self.assertTrue(result['submitted'])
        self.assertEqual(result['message'], '邮件已提交发送')
        request_mock.assert_called_once()
        method, url = request_mock.call_args.args
        request_kwargs = request_mock.call_args.kwargs
        self.assertEqual(method, 'post')
        self.assertEqual(url, 'https://graph.microsoft.com/v1.0/me/sendMail')
        self.assertEqual(request_kwargs['headers']['Authorization'], 'Bearer access-token')
        self.assertEqual(
            request_kwargs['json']['message']['body'],
            {'contentType': 'Text', 'content': '正文'},
        )
        self.assertEqual(
            request_kwargs['json']['message']['toRecipients'],
            [{'emailAddress': {'address': 'recipient@example.com'}}],
        )
        self.assertNotIn('from', request_kwargs['json']['message'])
        self.assertNotIn('saveToSentItems', request_kwargs['json'])
        self.assertFalse(request_kwargs['allow_redirects'])

    def test_send_helper_does_not_follow_post_redirects(self):
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(web_outlook_app.requests, 'request') as request_mock:
            for status_code in (307, 308):
                with self.subTest(status_code=status_code):
                    request_mock.reset_mock()
                    request_mock.return_value = FakeResponse(
                        status_code,
                        {'error': {'code': 'Redirect', 'message': 'Redirect response'}},
                    )

                    result = web_outlook_app.send_graph_mail_result(
                        'client-id',
                        'refresh-token',
                        ['recipient@example.com'],
                        '主题',
                        '正文',
                    )

                    request_mock.assert_called_once()
                    self.assertFalse(request_mock.call_args.kwargs['allow_redirects'])
                    self.assertFalse(result['success'])
                    self.assertTrue(result['submission_unknown'])
                    self.assertEqual(result['error']['code'], 'GRAPH_SEND_RESULT_UNKNOWN')
                    self.assertEqual(result['error']['status'], status_code)

    def test_send_helper_treats_ambiguous_responses_as_submission_unknown(self):
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(web_outlook_app.requests, 'request') as request_mock:
            for status_code in (408, 502, 504):
                with self.subTest(status_code=status_code):
                    request_mock.reset_mock()
                    request_mock.return_value = FakeResponse(
                        status_code,
                        {
                            'error': {
                                'code': 'GatewayError',
                                'message': (
                                    'Mail.Send backend unavailable'
                                    if status_code == 502 else 'Gateway response'
                                ),
                            },
                        },
                    )

                    result = web_outlook_app.send_graph_mail_result(
                        'client-id',
                        'refresh-token',
                        ['recipient@example.com'],
                        '主题',
                        '正文',
                    )

                    request_mock.assert_called_once()
                    self.assertFalse(result['success'])
                    self.assertTrue(result['submission_unknown'])
                    self.assertFalse(result['retryable'])
                    self.assertEqual(result['error']['code'], 'GRAPH_SEND_RESULT_UNKNOWN')
                    self.assertEqual(result['error']['status'], status_code)

    def test_send_helper_does_not_retry_when_network_result_is_unknown(self):
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(
            web_outlook_app.requests,
            'request',
            side_effect=web_outlook_app.requests.exceptions.Timeout('network timeout'),
        ) as request_mock:
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['recipient@example.com'],
                '主题',
                '正文',
                proxy_url='http://primary-proxy:8080',
            )

        request_mock.assert_called_once()
        self.assertFalse(result['success'])
        self.assertTrue(result['submission_unknown'])
        self.assertFalse(result['retryable'])
        self.assertEqual(result['error']['code'], 'GRAPH_SEND_RESULT_UNKNOWN')

    def test_send_helper_maps_permission_failure_to_reauthorization(self):
        graph_response = FakeResponse(403, {
            'error': {
                'code': 'ErrorAccessDenied',
                'message': 'Access is denied. Check credentials and try again.',
            },
        })
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(web_outlook_app.requests, 'request', return_value=graph_response):
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['recipient@example.com'],
                '主题',
                '正文',
            )

        self.assertFalse(result['success'])
        self.assertFalse(result['submitted'])
        self.assertEqual(result['error']['code'], 'GRAPH_SEND_REAUTH_REQUIRED')
        self.assertEqual(result['error']['status'], 403)

    def test_send_helper_exposes_throttling_wait_suggestion(self):
        graph_response = FakeResponse(
            429,
            {'error': {'code': 'TooManyRequests', 'message': 'Please retry later'}},
            headers={'Retry-After': '12', 'content-type': 'application/json'},
        )
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(web_outlook_app.requests, 'request', return_value=graph_response):
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['recipient@example.com'],
                '主题',
                '正文',
            )

        self.assertFalse(result['success'])
        self.assertTrue(result['retryable'])
        self.assertEqual(result['retry_after'], 12)
        self.assertEqual(result['error']['code'], 'GRAPH_SEND_THROTTLED')

    def test_send_helper_reports_known_graph_rejection_without_automatic_retry(self):
        graph_response = FakeResponse(400, {
            'error': {
                'code': 'ErrorInvalidRecipients',
                'message': 'One or more recipients are not valid.',
            },
        })
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': True, 'access_token': 'access-token'},
        ), patch.object(web_outlook_app.requests, 'request', return_value=graph_response) as request_mock:
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['recipient@example.com'],
                '主题',
                '正文',
            )

        request_mock.assert_called_once()
        self.assertFalse(result['success'])
        self.assertFalse(result['submitted'])
        self.assertFalse(result['submission_unknown'])
        self.assertEqual(result['error']['code'], 'GRAPH_SEND_FAILED')
        self.assertEqual(result['error']['status'], 400)

    def test_send_helper_maps_invalid_grant_to_reauthorization_without_submitting_mail(self):
        token_error = web_outlook_app.build_error_payload(
            'GRAPH_TOKEN_FAILED',
            '获取访问令牌失败',
            'GraphAPIError',
            400,
            {'error': 'invalid_grant'},
        )
        with patch.object(
            web_outlook_app,
            'get_access_token_graph_result',
            return_value={'success': False, 'error': token_error},
        ), patch.object(web_outlook_app.requests, 'request') as request_mock:
            result = web_outlook_app.send_graph_mail_result(
                'client-id',
                'refresh-token',
                ['recipient@example.com'],
                '主题',
                '正文',
            )

        request_mock.assert_not_called()
        self.assertEqual(result['error']['code'], 'GRAPH_SEND_REAUTH_REQUIRED')
        self.assertEqual(result['error']['status'], 403)

    def test_route_uses_account_id_and_returns_graph_submission_result(self):
        account_id = self._add_outlook_account()
        with patch.object(
            web_outlook_app,
            'send_graph_mail_result',
            return_value={'success': True, 'submitted': True, 'message': '邮件已提交发送'},
        ) as send_mock:
            response = self._post_send(account_id)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()['message'], '邮件已提交发送')
        send_mock.assert_called_once_with(
            'client-id',
            'refresh-token',
            ['recipient@example.com'],
            '测试主题',
            '测试正文',
            proxy_url='',
            fallback_proxy_urls=['', ''],
        )

    def test_route_rejects_unsupported_account_and_spoofed_sender_without_calling_graph(self):
        imap_channel_account_id = self._add_outlook_account('imap-channel@outlook.com', authorization_type='imap')
        standard_imap_account_id = self._add_standard_imap_account()
        with patch.object(web_outlook_app, 'send_graph_mail_result') as send_mock:
            imap_channel_response = self._post_send(imap_channel_account_id)
            standard_imap_response = self._post_send(standard_imap_account_id)
            spoofed_response = self._post_send(
                imap_channel_account_id,
                **{'from': 'other@example.com'},
            )

        self.assertEqual(imap_channel_response.status_code, 403)
        self.assertEqual(imap_channel_response.get_json()['error']['code'], 'GRAPH_SEND_REAUTH_REQUIRED')
        self.assertEqual(standard_imap_response.status_code, 400)
        self.assertEqual(standard_imap_response.get_json()['error']['code'], 'GRAPH_SEND_UNSUPPORTED_ACCOUNT')
        self.assertEqual(spoofed_response.status_code, 400)
        self.assertEqual(spoofed_response.get_json()['error']['code'], 'GRAPH_SEND_UNSUPPORTED_FIELD')
        send_mock.assert_not_called()

    def test_route_rejects_invalid_recipient_without_requesting_token(self):
        account_id = self._add_outlook_account()
        with patch.object(web_outlook_app, 'get_access_token_graph_result') as token_mock:
            response = self._post_send(account_id, recipients=['not-an-email'])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error']['code'], 'GRAPH_SEND_INVALID_REQUEST')
        token_mock.assert_not_called()

    def test_route_requires_login(self):
        account_id = self._add_outlook_account()
        with self.client.session_transaction() as session:
            session.clear()
        with patch.object(web_outlook_app, 'send_graph_mail_result') as send_mock:
            response = self._post_send(account_id)

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.get_json()['need_login'])
        send_mock.assert_not_called()

    @unittest.skipUnless(getattr(web_outlook_app, 'CSRF_AVAILABLE', False), 'Flask-WTF not installed')
    def test_route_requires_csrf_when_protection_is_enabled(self):
        account_id = self._add_outlook_account()
        original_enabled = self.app.config.get('WTF_CSRF_ENABLED')
        original_check_default = self.app.config.get('WTF_CSRF_CHECK_DEFAULT')
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = True
        try:
            with patch.object(web_outlook_app, 'send_graph_mail_result') as send_mock:
                response = self._post_send(account_id)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = original_enabled
            if original_check_default is None:
                self.app.config.pop('WTF_CSRF_CHECK_DEFAULT', None)
            else:
                self.app.config['WTF_CSRF_CHECK_DEFAULT'] = original_check_default

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json().get('csrf_error'))
        send_mock.assert_not_called()
