import os
import queue
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-authorization-channel-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

import web_outlook_app


class _TokenResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ''

    def json(self):
        return dict(self._payload)


class OutlookAuthorizationChannelTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM outlook_upload_accounts")
            db.commit()
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['login_session_version'] = web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION

    def _add_outlook_account(self, email='channel@example.com'):
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(email, 'password', 'client', 'refresh'))
            return int(web_outlook_app.get_account_by_email(email)['id'])

    def test_authorization_type_normalization(self):
        self.assertEqual(web_outlook_app.normalize_outlook_authorization_type(' GRAPH '), 'graph')
        self.assertEqual(web_outlook_app.normalize_outlook_authorization_type('IMAP'), 'imap')
        self.assertEqual(web_outlook_app.normalize_outlook_authorization_type('unknown'), '')
        self.assertEqual(web_outlook_app.normalize_outlook_authorization_type('invalid'), '')
        with self.assertRaises(ValueError):
            web_outlook_app.normalize_outlook_authorization_type('invalid', strict=True)

    def test_edit_can_set_clear_and_preserve_authorization_type(self):
        account_id = self._add_outlook_account()
        base = {
            'email': 'channel@example.com',
            'client_id': 'client',
            'refresh_token': 'refresh',
            'account_type': 'outlook',
            'provider': 'outlook',
            'group_id': 1,
            'status': 'active',
        }

        response = self.client.put(f'/api/accounts/{account_id}', json={**base, 'authorization_type': 'imap'})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_account_by_id(account_id)['authorization_type'], 'imap')

        response = self.client.put(f'/api/accounts/{account_id}', json=base)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_account_by_id(account_id)['authorization_type'], 'imap')

        response = self.client.put(f'/api/accounts/{account_id}', json={**base, 'authorization_type': ''})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_account_by_id(account_id)['authorization_type'], '')

    def test_editing_as_generic_imap_clears_outlook_authorization_type(self):
        account_id = self._add_outlook_account('generic@example.com')
        with self.app.app_context():
            self.assertTrue(web_outlook_app.update_account_authorization_type(account_id, 'graph'))

        response = self.client.put(f'/api/accounts/{account_id}', json={
            'email': 'generic@example.com',
            'account_type': 'imap',
            'provider': 'gmail',
            'imap_password': 'imap-password',
            'imap_host': 'imap.gmail.com',
            'imap_port': 993,
            'group_id': 1,
            'status': 'active',
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            account = web_outlook_app.get_account_by_id(account_id)
            self.assertEqual(account['account_type'], 'imap')
            self.assertEqual(account['authorization_type'], '')

    def test_graph_preference_falls_back_to_imap_and_records_actual_channel(self):
        account = {
            'id': 1,
            'email': 'channel@example.com',
            'account_type': 'outlook',
            'client_id': 'client',
            'refresh_token': 'refresh',
            'authorization_type': 'graph',
        }
        calls = []

        def graph(*_args, **_kwargs):
            calls.append('graph')
            return {'success': False, 'error': {'message': 'graph unavailable'}}

        def imap(*args, **_kwargs):
            calls.append(f'imap:{args[6]}')
            return {'success': True, 'emails': [], 'has_more': False}

        with patch.object(web_outlook_app, 'get_emails_graph', side_effect=graph), \
             patch.object(web_outlook_app, 'get_emails_imap_with_server', side_effect=imap), \
             patch.object(web_outlook_app, 'record_account_authorization_type') as record:
            result = web_outlook_app.fetch_account_folder_emails(account, 'inbox', 0, 20)

        self.assertTrue(result['success'])
        self.assertEqual(calls, ['graph', f'imap:{web_outlook_app.IMAP_SERVER_NEW}'])
        record.assert_called_once_with(account, 'imap')

    def test_imap_preference_falls_back_to_graph_and_records_actual_channel(self):
        account = {
            'id': 1,
            'email': 'channel@example.com',
            'account_type': 'outlook',
            'client_id': 'client',
            'refresh_token': 'refresh',
            'authorization_type': 'imap',
        }
        calls = []

        def graph(*_args, **_kwargs):
            calls.append('graph')
            return {'success': True, 'emails': []}

        def imap(*args, **_kwargs):
            calls.append(f'imap:{args[6]}')
            return {'success': False, 'error': {'message': 'imap unavailable'}}

        with patch.object(web_outlook_app, 'get_emails_graph', side_effect=graph), \
             patch.object(web_outlook_app, 'get_emails_imap_with_server', side_effect=imap), \
             patch.object(web_outlook_app, 'record_account_authorization_type') as record:
            result = web_outlook_app.fetch_account_folder_emails(account, 'inbox', 0, 20)

        self.assertTrue(result['success'])
        self.assertEqual(calls, [
            f'imap:{web_outlook_app.IMAP_SERVER_NEW}',
            f'imap:{web_outlook_app.IMAP_SERVER_OLD}',
            'graph',
        ])
        record.assert_called_once_with(account, 'graph')

    def test_folder_all_only_records_when_both_folders_use_same_channel(self):
        account = {
            'id': 1,
            'email': 'channel@example.com',
            'account_type': 'outlook',
            'authorization_type': '',
        }

        def same_channel(_account, folder, *_args):
            return {
                'success': True,
                'emails': [{'id': folder, 'date': '2026-01-01T00:00:00Z'}],
                'method': 'Graph API',
                'request_method': 'graph',
                'has_more': False,
            }

        with patch.object(web_outlook_app, 'get_account_proxy_url', return_value=''), \
             patch.object(web_outlook_app, 'get_account_proxy_failover_urls', return_value=[]), \
             patch.object(web_outlook_app, 'fetch_account_folder_emails', side_effect=same_channel), \
             patch.object(web_outlook_app, 'record_account_authorization_type') as record:
            result = web_outlook_app.fetch_account_emails(account, 'all', 0, 20)

        self.assertTrue(result['success'])
        record.assert_called_once_with(account, 'graph')

    def test_detail_uses_recorded_preference_and_falls_back(self):
        account = {
            'id': 1,
            'email': 'channel@example.com',
            'account_type': 'outlook',
            'client_id': 'client',
            'refresh_token': 'refresh',
            'authorization_type': 'graph',
        }
        with patch.object(
            web_outlook_app,
            'fetch_graph_detail_response',
            return_value={'success': False, 'error': {'message': 'graph detail failed'}},
        ) as graph, patch.object(
            web_outlook_app,
            'fetch_oauth_imap_detail_response',
            return_value={'success': True, 'email': {'subject': 'imap detail'}},
        ) as imap, patch.object(
            web_outlook_app,
            'record_account_authorization_type',
        ) as record:
            result = web_outlook_app.fetch_email_detail_for_account(
                account,
                'message-id',
                method='graph',
                folder='inbox',
            )

        self.assertTrue(result['success'])
        graph.assert_called_once()
        imap.assert_called_once()
        record.assert_called_once_with(account, 'imap')

    def test_token_refresh_order_and_actual_channel(self):
        calls = []

        def graph(*_args, **_kwargs):
            calls.append('graph')
            return _TokenResponse(401, {'error_description': 'graph failed'})

        def imap(*_args, **_kwargs):
            calls.append('imap')
            return _TokenResponse(200, {'refresh_token': 'rotated'})

        with patch.object(web_outlook_app, 'request_graph_token_response', side_effect=graph), \
             patch.object(web_outlook_app, 'request_imap_token_response', side_effect=imap):
            result = web_outlook_app.test_refresh_token(
                'client', 'refresh', authorization_type='graph'
            )

        self.assertEqual(calls, ['graph', 'imap'])
        self.assertEqual(result, (True, None, 'rotated', 'imap'))

    def test_internal_authorization_saves_actual_validation_channel(self):
        with self.app.app_context():
            upload = web_outlook_app.add_upload_account(
                'oauth@example.com', 'password', remark='keep me'
            )
            web_outlook_app.get_db().commit()
            output = queue.Queue()
            with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
                'success': True,
                'refresh_token': 'new-refresh',
                'client_id': 'new-client',
            }), patch.object(
                web_outlook_app,
                'test_refresh_token',
                return_value=(True, None, '', 'imap'),
            ):
                web_outlook_app.run_graph_oauth_task(upload['id'], output, mode='graph')

            events = []
            while True:
                item = output.get_nowait()
                if item is web_outlook_app.GRAPH_OAUTH_DONE:
                    break
                events.append(item)
            account = web_outlook_app.get_account_by_email('oauth@example.com')

        self.assertTrue(any(event.get('type') == 'success' for event in events))
        self.assertEqual(account['authorization_type'], 'imap')
        self.assertEqual(account['client_id'], 'new-client')

    def test_frontend_exposes_authorization_type_edit_control(self):
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'templates', 'partials', 'index', 'dialogs-primary.html'
        )
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'static', 'js', 'index', '07-settings.js'
        )
        with open(template_path, encoding='utf-8') as handle:
            template = handle.read()
        with open(script_path, encoding='utf-8') as handle:
            script = handle.read()
        self.assertIn('id="editAuthorizationType"', template)
        self.assertIn('authorization_type:', script)
        self.assertIn('acc.authorization_type', script)


if __name__ == '__main__':
    unittest.main()
