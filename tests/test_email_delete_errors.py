import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-delete-errors-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = text
        self.headers = {'content-type': 'application/json'}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _batch_item(index, status, body=None):
    item = {'id': str(index), 'status': status}
    if body is not None:
        item['body'] = body
    return item


def _access_denied_body():
    return {
        'error': {
            'code': 'ErrorAccessDenied',
            'message': 'Access is denied. Check credentials and try again.',
        }
    }


class GraphDeleteErrorTests(unittest.TestCase):
    """delete_emails_graph 的批量删除错误信息处理（issue #89）。"""

    def _delete(self, message_ids, batch_response):
        with patch.object(web_outlook_app, 'get_access_token_graph', return_value='token'), \
             patch.object(web_outlook_app, 'request_with_proxy_failover', return_value=batch_response):
            return web_outlook_app.delete_emails_graph('client-id', 'refresh-token', message_ids)

    def test_access_denied_403_returns_reauthorization_hint(self):
        response = FakeResponse(200, payload={'responses': [_batch_item(0, 403, _access_denied_body())]})

        result = self._delete(['msg-1'], response)

        self.assertFalse(result['success'])
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failed_count'], 1)
        error = result['errors'][0]['error']
        self.assertEqual(error['code'], 'EMAIL_DELETE_REAUTH_REQUIRED')
        self.assertIn('重新授权', error['message'])
        self.assertIn('Mail.ReadWrite', error['message'])
        self.assertIn('ErrorAccessDenied', error['details'])

    def test_non_auth_failure_keeps_graph_error_details(self):
        body = {
            'error': {
                'code': 'MessageNotFound',
                'message': 'The specified object was not found in the store.',
            }
        }
        response = FakeResponse(200, payload={'responses': [_batch_item(0, 404, body)]})

        result = self._delete(['msg-1'], response)

        self.assertFalse(result['success'])
        error = result['errors'][0]['error']
        self.assertEqual(error['code'], 'EMAIL_DELETE_FAILED')
        self.assertEqual(error['message'], '删除邮件失败')
        self.assertIn('MessageNotFound', error['details'])

    def test_mixed_batch_counts_partial_success(self):
        response = FakeResponse(200, payload={'responses': [
            _batch_item(0, 204),
            _batch_item(1, 403, _access_denied_body()),
        ]})

        result = self._delete(['msg-ok', 'msg-deny'], response)

        self.assertFalse(result['success'])
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(result['deleted_ids'], ['msg-ok'])
        self.assertEqual(result['errors'][0]['id'], 'msg-deny')

    def test_successful_delete_returns_ids(self):
        response = FakeResponse(200, payload={'responses': [
            _batch_item(0, 204),
            _batch_item(1, 200),
        ]})

        result = self._delete(['msg-1', 'msg-2'], response)

        self.assertTrue(result['success'])
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['deleted_ids'], ['msg-1', 'msg-2'])
        self.assertEqual(result['errors'], [])

    def test_batch_level_failure_reports_each_message(self):
        response = FakeResponse(500, payload={'error': {'code': 'ServerError'}})

        result = self._delete(['msg-1', 'msg-2'], response)

        self.assertFalse(result['success'])
        self.assertEqual(result['failed_count'], 2)
        self.assertEqual(len(result['errors']), 2)
        for item in result['errors']:
            self.assertEqual(item['error']['code'], 'EMAIL_DELETE_FAILED')

    def test_network_error_reports_each_message(self):
        with patch.object(web_outlook_app, 'get_access_token_graph', return_value='token'), \
             patch.object(web_outlook_app, 'request_with_proxy_failover', side_effect=RuntimeError('boom')):
            result = web_outlook_app.delete_emails_graph('client-id', 'refresh-token', ['msg-1', 'msg-2'])

        self.assertFalse(result['success'])
        self.assertEqual(result['failed_count'], 2)
        self.assertEqual(len(result['errors']), 2)
        self.assertIn('boom', result['errors'][0]['error']['details'])

    def test_is_graph_delete_reauthorization_error_markers(self):
        func = web_outlook_app.is_graph_delete_reauthorization_error
        self.assertTrue(func(403, ''))
        self.assertTrue(func(401, None))
        self.assertTrue(func(400, {'error': {'message': 'Missing scope Mail.ReadWrite for the request'}}))
        self.assertFalse(func(404, {'error': {'code': 'MessageNotFound'}}))
        self.assertFalse(func(204, ''))
        self.assertFalse(func(None, None))

    def test_merge_email_action_results_unwraps_error_entry(self):
        wrapped = {'id': 'msg-1', 'error': build_error_payload_dict()}
        merged = web_outlook_app.merge_email_action_results([{
            'success': False,
            'success_count': 0,
            'failed_count': 1,
            'updated_ids': [],
            'deleted_ids': [],
            'errors': [wrapped],
        }])

        self.assertEqual(merged['error']['message'], '删除邮件失败')
        self.assertEqual(merged['errors'], [wrapped])

    def test_merge_email_action_results_keeps_plain_string_error(self):
        merged = web_outlook_app.merge_email_action_results([{
            'success': False,
            'success_count': 0,
            'failed_count': 1,
            'updated_ids': [],
            'deleted_ids': [],
            'errors': ['remote failed'],
        }])

        self.assertEqual(merged['error'], 'remote failed')


def build_error_payload_dict():
    return {
        'code': 'EMAIL_DELETE_FAILED',
        'message': '删除邮件失败',
        'type': 'GraphAPIError',
        'status': 403,
        'details': '',
        'trace_id': 'test-trace-id',
    }


class DeleteEmailsRouteErrorTests(unittest.TestCase):
    """删除接口把结构化错误传递给前端（issue #89 的用户可见表现）。"""

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
            db.execute('DELETE FROM retained_normal_mail_messages')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()
            self.assertTrue(web_outlook_app.add_account(
                'delete-error@example.com',
                'password',
                'client-id',
                'refresh-token',
                group_id=1,
                account_type='outlook',
                provider='outlook',
            ))

    def test_route_surfaces_reauthorization_error_message(self):
        response = FakeResponse(200, payload={'responses': [
            _batch_item(0, 403, _access_denied_body()),
        ]})
        with patch.object(web_outlook_app, 'get_access_token_graph', return_value='token'), \
             patch.object(web_outlook_app, 'request_with_proxy_failover', return_value=response):
            api_response = self.client.post('/api/emails/delete', json={
                'email': 'delete-error@example.com',
                'method': 'graph',
                'items': [{'id': 'msg-1', 'folder': 'inbox', 'id_mode': 'graph'}],
            })

        self.assertEqual(api_response.status_code, 200)
        payload = api_response.get_json()
        self.assertFalse(payload['success'])
        self.assertIsInstance(payload['error'], dict)
        self.assertEqual(payload['error']['code'], 'EMAIL_DELETE_REAUTH_REQUIRED')
        self.assertIn('重新授权', payload['error']['message'])


if __name__ == '__main__':
    unittest.main()
