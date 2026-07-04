import importlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
_test_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.test_tmp')
os.makedirs(_test_root, exist_ok=True)
_temp_dir = os.path.join(_test_root, 'graph_oauth')
os.makedirs(_temp_dir, exist_ok=True)
os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class FakeResponse:
    def __init__(self, url='', text='', status_code=200, headers=None, payload=None):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError('No JSON payload')
        return self._payload


class FakeSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.headers = {}
        self.trust_env = False
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if not self.get_responses:
            raise AssertionError(f'Unexpected GET {url}')
        return self.get_responses.pop(0)

    def post(self, url, data=None, **kwargs):
        self.post_calls.append((url, data or {}, kwargs))
        if not self.post_responses:
            raise AssertionError(f'Unexpected POST {url}')
        return self.post_responses.pop(0)


class GraphTokenExtractorTests(unittest.TestCase):
    def test_extracts_ppft_from_hidden_input_and_exchanges_code(self):
        auth_html = '''
            <html>
              <input type="hidden" name="PPFT" value="flow-token-hidden">
              <script>"urlPost":"https://login.live.com/post.srf","sCtx":"ctx-value"</script>
            </html>
        '''
        session = FakeSession(
            get_responses=[FakeResponse(url='https://login.microsoftonline.com/auth', text=auth_html)],
            post_responses=[
                FakeResponse(url='http://localhost?code=auth-code', text=''),
                FakeResponse(
                    url='https://login.microsoftonline.com/token',
                    payload={'access_token': 'access-token', 'refresh_token': 'refresh-token-value'},
                ),
            ],
        )
        logs = []

        result = web_outlook_app.extract_graph_refresh_token(
            'user@example.com',
            'secret-password',
            log=logs.append,
            session_factory=lambda: session,
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['refresh_token'], 'refresh-token-value')
        self.assertEqual(result['client_id'], web_outlook_app.OAUTH_CLIENT_ID)
        self.assertEqual(session.post_calls[0][0], 'https://login.live.com/post.srf')
        self.assertFalse(session.post_calls[0][2]['allow_redirects'])
        self.assertEqual(session.post_calls[0][1]['PPFT'], 'flow-token-hidden')
        self.assertEqual(session.post_calls[0][1]['ctx'], 'ctx-value')
        self.assertEqual(session.post_calls[1][1]['code'], 'auth-code')
        self.assertNotIn('secret-password', '\n'.join(logs))
        self.assertNotIn('refresh-token-value', '\n'.join(logs))

    def test_login_redirect_to_localhost_is_captured_without_following(self):
        auth_html = '<input name="PPFT" value="flow"><script>"urlPost":"https://post"</script>'
        session = FakeSession(
            get_responses=[FakeResponse(url='https://auth', text=auth_html)],
            post_responses=[
                FakeResponse(status_code=302, headers={'Location': 'http://localhost?code=redirect-code'}),
                FakeResponse(payload={'access_token': 'access-token', 'refresh_token': 'redirect-refresh'}),
            ],
        )

        result = web_outlook_app.extract_graph_refresh_token(
            'redirect@example.com',
            'password',
            session_factory=lambda: session,
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['refresh_token'], 'redirect-refresh')
        self.assertEqual(session.post_calls[1][1]['code'], 'redirect-code')
        self.assertFalse(session.post_calls[0][2]['allow_redirects'])
        self.assertEqual(len(session.get_calls), 1)

    def test_handles_js_autosubmit_consent_proofs_and_sftag(self):
        server_data = {
            'sClientId': 'client-from-server',
            'sRawInputScopes': 'offline_access Mail.Read',
            'sRawInputGrantedScopes': 'offline_access',
            'sCanary': 'canary-value',
        }
        auth_html = '''
            <script>
              var x = {"urlPost":"https://login.live.com/post.srf","sCtx":"ctx-from-sftag"};
              var sFTTag = '<input type="hidden" name="PPFT" value=\\"flow-from-sftag\\">';
            </script>
        '''
        auto_submit_html = '''
            <html onload="DoSubmit()">
              <form id="fmHF" action="https://login.live.com/continue">
                <input type="hidden" name="h1" value="v1">
              </form>
            </html>
        '''
        consent_html = f'''
            <script>var ServerData = {json.dumps(server_data)};</script>
        '''
        proofs_html = '''
            <form action="/proofs/Add">
              <input type="hidden" name="canary" value="proof-canary">
            </form>
        '''
        session = FakeSession(
            get_responses=[
                FakeResponse(url='https://login.microsoftonline.com/auth', text=auth_html),
            ],
            post_responses=[
                FakeResponse(url='https://login.live.com/autosubmit', text=auto_submit_html),
                FakeResponse(url='https://account.live.com/Consent/Update', text=consent_html),
                FakeResponse(url='https://account.live.com/proofs/Add', text=proofs_html),
                FakeResponse(status_code=302, headers={'Location': 'http://localhost?code=final-code'}),
                FakeResponse(payload={'access_token': 'access-token', 'refresh_token': 'rt-after-proofs'}),
            ],
        )

        result = web_outlook_app.extract_graph_refresh_token(
            'flow@example.com',
            'password',
            session_factory=lambda: session,
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['refresh_token'], 'rt-after-proofs')
        self.assertEqual(session.post_calls[0][1]['PPFT'], 'flow-from-sftag')
        self.assertEqual(session.post_calls[1][0], 'https://login.live.com/continue')
        self.assertEqual(session.post_calls[1][1], {'h1': 'v1'})
        self.assertEqual(session.post_calls[2][1]['ucaction'], 'Yes')
        self.assertEqual(session.post_calls[2][1]['canary'], 'canary-value')
        self.assertEqual(session.post_calls[3][0], 'https://account.live.com/proofs/Add')
        self.assertEqual(session.post_calls[3][1]['action'], 'Skip')

    def test_oauth_error_redirect_returns_sanitized_failure(self):
        auth_html = '<input name="PPFT" value="flow"><script>"urlPost":"https://post"</script>'
        session = FakeSession(
            get_responses=[FakeResponse(url='https://auth', text=auth_html)],
            post_responses=[
                FakeResponse(url='http://localhost?error=access_denied&error_description=password%3Dsecret'),
            ],
        )

        result = web_outlook_app.extract_graph_refresh_token(
            'error@example.com',
            'secret',
            session_factory=lambda: session,
        )

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'OAuth 错误')
        self.assertNotIn('secret', result['details'])

    def test_token_endpoint_without_refresh_token_fails(self):
        auth_html = '<input name="PPFT" value="flow"><script>"urlPost":"https://post"</script>'
        session = FakeSession(
            get_responses=[FakeResponse(url='https://auth', text=auth_html)],
            post_responses=[
                FakeResponse(url='http://localhost?code=code-only'),
                FakeResponse(payload={'access_token': 'access-token'}),
            ],
        )

        result = web_outlook_app.extract_graph_refresh_token(
            'missing@example.com',
            'password',
            session_factory=lambda: session,
        )

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], '未获取到 refresh_token')


class GraphOauthRouteTests(unittest.TestCase):
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
            db.execute('DELETE FROM outlook_upload_accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

    def _add_upload_account(self, email='upload@example.com', password='mail-password'):
        with self.app.app_context():
            result = web_outlook_app.add_upload_account(email, password, 'upload note')
            web_outlook_app.get_db().commit()
            return result['id']

    def _start_graph_task(self, account_id):
        response = self.client.post('/api/oauth/graph-extract-token', json={'account_id': account_id})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertIn('stream_url', payload)
        return payload['stream_url']

    def _consume_stream(self, stream_url):
        response = self.client.get(stream_url)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        events = []
        for block in body.strip().split('\n\n'):
            if not block.startswith('data: '):
                continue
            events.append(json.loads(block[len('data: '):]))
        return body, events

    def test_post_requires_existing_upload_account_id(self):
        response = self.client.post('/api/oauth/graph-extract-token', json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

        response = self.client.post('/api/oauth/graph-extract-token', json={'account_id': 9999})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])

    def test_stream_success_creates_formal_account_and_marks_upload_authorized(self):
        account_id = self._add_upload_account()

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': True,
            'refresh_token': 'fresh-refresh-token',
            'client_id': 'graph-client-id',
        }) as extract_mock, \
             patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, 'rotated-refresh-token')):
            body, events = self._consume_stream(self._start_graph_task(account_id))

        extract_mock.assert_called_once()
        self.assertEqual(extract_mock.call_args.args[1], 'mail-password')
        self.assertTrue(any(event['type'] == 'success' for event in events))
        self.assertTrue(events[-1]['success'])
        self.assertNotIn('mail-password', body)
        self.assertNotIn('fresh-refresh-token', body)
        self.assertNotIn('rotated-refresh-token', body)

        with self.app.app_context():
            formal = web_outlook_app.get_account_by_email('upload@example.com')
            upload = web_outlook_app.get_db().execute(
                'SELECT is_authorized, password FROM outlook_upload_accounts WHERE id = ?',
                (account_id,),
            ).fetchone()

        self.assertIsNotNone(formal)
        self.assertEqual(formal['email'], 'upload@example.com')
        self.assertEqual(formal['password'], 'mail-password')
        self.assertEqual(formal['client_id'], 'graph-client-id')
        self.assertEqual(formal['refresh_token'], 'rotated-refresh-token')
        self.assertEqual(formal['provider'], 'outlook')
        self.assertEqual(formal['account_type'], 'outlook')
        self.assertEqual(upload['is_authorized'], 1)
        self.assertEqual(upload['password'], '')

    def test_stream_success_updates_existing_formal_account(self):
        account_id = self._add_upload_account(email='exists@example.com', password='new-password')
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                'exists@example.com',
                'old-password',
                'old-client',
                'old-refresh',
                group_id=1,
                remark='keep existing remark',
            ))
            existing_id = web_outlook_app.get_account_by_email('exists@example.com')['id']
            db = web_outlook_app.get_db()
            db.execute(
                '''
                UPDATE accounts
                SET last_refresh_status = 'failed', last_refresh_error = 'old failure'
                WHERE id = ?
                ''',
                (existing_id,),
            )
            db.commit()

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': True,
            'refresh_token': 'updated-refresh',
            'client_id': 'updated-client',
        }), patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, '')):
            _, events = self._consume_stream(self._start_graph_task(account_id))

        self.assertTrue(events[-1]['success'])
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('exists@example.com')
            rows = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS total FROM accounts WHERE email = ?',
                ('exists@example.com',),
            ).fetchone()

        self.assertEqual(rows['total'], 1)
        self.assertEqual(account['id'], existing_id)
        self.assertEqual(account['password'], 'new-password')
        self.assertEqual(account['client_id'], 'updated-client')
        self.assertEqual(account['refresh_token'], 'updated-refresh')
        self.assertEqual(account['remark'], 'keep existing remark')
        self.assertEqual(account['last_refresh_status'], 'never')
        self.assertIsNone(account['last_refresh_error'])

    def test_stream_validation_failure_does_not_write_or_mark_authorized(self):
        account_id = self._add_upload_account(email='invalid-token@example.com')

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': True,
            'refresh_token': 'bad-refresh-token',
            'client_id': 'graph-client-id',
        }), patch.object(web_outlook_app, 'test_refresh_token', return_value=(False, 'Graph failed for token=bad-refresh-token', '')):
            body, events = self._consume_stream(self._start_graph_task(account_id))

        self.assertFalse(events[-1]['success'])
        self.assertIn('Graph failed', body)
        self.assertNotIn('bad-refresh-token', body)
        with self.app.app_context():
            formal = web_outlook_app.get_account_by_email('invalid-token@example.com')
            upload = web_outlook_app.get_db().execute(
                'SELECT is_authorized, password FROM outlook_upload_accounts WHERE id = ?',
                (account_id,),
            ).fetchone()

        self.assertIsNone(formal)
        self.assertEqual(upload['is_authorized'], 0)
        self.assertEqual(web_outlook_app.decrypt_data(upload['password']), 'mail-password')

    # --- Task 3.1: Successful auth overwrites formal account credentials ---

    def test_3_1_successful_auth_keeps_single_account_and_overwrites_credentials(self):
        """同邮箱自动化授权成功后只保留一个正式账号，覆盖密码/client_id/refresh_token/授权时间。"""
        account_id = self._add_upload_account(
            email='overwrite@example.com', password='new-mail-password'
        )
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                'overwrite@example.com',
                'old-password',
                'old-client-id',
                'old-refresh-token',
                group_id=1,
                remark='keep remark',
            ))
            existing = web_outlook_app.get_account_by_email('overwrite@example.com')
            existing_id = existing['id']
            db = web_outlook_app.get_db()
            db.execute(
                "UPDATE accounts SET last_refresh_status = 'failed', "
                "last_refresh_error = 'old failure' WHERE id = ?",
                (existing_id,),
            )
            db.commit()

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': True,
            'refresh_token': 'new-refresh-token',
            'client_id': 'new-client-id',
        }), patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, 'rotated-token')):
            _, events = self._consume_stream(self._start_graph_task(account_id))

        self.assertTrue(events[-1]['success'])
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('overwrite@example.com')
            raw = web_outlook_app.get_db().execute(
                "SELECT COUNT(*) AS total FROM accounts WHERE email = ?",
                ('overwrite@example.com',),
            ).fetchone()
            raw_fields = web_outlook_app.get_db().execute(
                "SELECT password, client_id, refresh_token, refresh_token_updated_at, "
                "last_refresh_status, last_refresh_error FROM accounts WHERE id = ?",
                (account['id'],),
            ).fetchone()

        # Only one formal account
        self.assertEqual(raw['total'], 1)
        # Same account ID (not recreated)
        self.assertEqual(account['id'], existing_id)
        # Credentials overwritten
        self.assertEqual(account['password'], 'new-mail-password')
        self.assertEqual(account['client_id'], 'new-client-id')
        self.assertEqual(account['refresh_token'], 'rotated-token')
        self.assertIsNotNone(raw_fields['refresh_token_updated_at'])
        self.assertEqual(raw_fields['last_refresh_status'], 'never')
        self.assertIsNone(raw_fields['last_refresh_error'])

    # --- Task 3.2: Successful auth preserves business metadata ---

    def test_3_2_successful_auth_preserves_business_metadata(self):
        """重复自动化授权成功后保留正式账号分组/备注/别名/标签/代理/转发/排序/启停。"""
        account_id = self._add_upload_account(
            email='preserve@example.com', password='refresh-pwd'
        )
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                'preserve@example.com',
                'old-pwd',
                'old-client',
                'old-refresh',
                group_id=1,
                remark='business remark',
                account_type='outlook',
                provider='outlook',
                forward_enabled=True,
                sort_order=7,
                status='active',
                proxy_url='socks5://primary:1080',
                fallback_proxy_url_1='http://fallback:7890',
                fallback_proxy_url_2='direct',
            ))
            account = web_outlook_app.get_account_by_email('preserve@example.com')
            web_outlook_app.replace_account_aliases(
                account['id'], 'preserve@example.com', ['alias@example.com']
            )
            tag_id = web_outlook_app.add_tag('业务标签', '#abc')
            db = web_outlook_app.get_db()
            db.execute(
                'INSERT INTO account_tags (account_id, tag_id) VALUES (?, ?)',
                (account['id'], tag_id),
            )
            db.commit()

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': True,
            'refresh_token': 'new-refresh',
            'client_id': 'new-client',
        }), patch.object(web_outlook_app, 'test_refresh_token', return_value=(True, None, '')):
            _, events = self._consume_stream(self._start_graph_task(account_id))

        self.assertTrue(events[-1]['success'])
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('preserve@example.com')
            aliases = web_outlook_app.get_account_aliases(account['id'])
            tags = [t['name'] for t in web_outlook_app.get_account_tags(account['id'])]

        # Authorization fields overwritten
        self.assertEqual(account['password'], 'refresh-pwd')
        self.assertEqual(account['client_id'], 'new-client')
        self.assertEqual(account['refresh_token'], 'new-refresh')
        # Business metadata preserved
        self.assertEqual(account['group_id'], 1)
        self.assertEqual(account['remark'], 'business remark')
        self.assertEqual(account['status'], 'active')
        self.assertTrue(account['forward_enabled'])
        self.assertEqual(account['sort_order'], 7)
        self.assertEqual(account['proxy_url'], 'socks5://primary:1080')
        self.assertEqual(account['fallback_proxy_url_1'], 'http://fallback:7890')
        self.assertEqual(account['fallback_proxy_url_2'], 'direct')
        self.assertEqual(aliases, ['alias@example.com'])
        self.assertEqual(tags, ['业务标签'])

    # --- Task 3.3: Token extraction failure does not overwrite ---

    def test_3_3_extraction_failure_does_not_overwrite_existing_formal_account(self):
        """Graph token 提取失败时不覆盖已有正式账号数据，暂存记录保持未授权。"""
        account_id = self._add_upload_account(
            email='extract-fail@example.com', password='upload-pwd'
        )
        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_account(
                'extract-fail@example.com',
                'original-pwd',
                'original-client',
                'original-refresh',
                group_id=1,
                remark='original remark',
            ))
            db = web_outlook_app.get_db()
            db.execute(
                "UPDATE accounts SET last_refresh_status = 'success' WHERE id = ?",
                (web_outlook_app.get_account_by_email('extract-fail@example.com')['id'],),
            )
            db.commit()

        with patch.object(web_outlook_app, 'extract_graph_refresh_token', return_value={
            'success': False,
            'error': 'OAuth 错误',
            'details': 'access_denied',
        }):
            _, events = self._consume_stream(self._start_graph_task(account_id))

        self.assertFalse(events[-1]['success'])
        with self.app.app_context():
            account = web_outlook_app.get_account_by_email('extract-fail@example.com')
            upload = web_outlook_app.get_db().execute(
                'SELECT is_authorized, password FROM outlook_upload_accounts WHERE id = ?',
                (account_id,),
            ).fetchone()

        # Formal account unchanged
        self.assertEqual(account['password'], 'original-pwd')
        self.assertEqual(account['client_id'], 'original-client')
        self.assertEqual(account['refresh_token'], 'original-refresh')
        self.assertEqual(account['remark'], 'original remark')
        # Upload row stays unauthorized with password
        self.assertEqual(upload['is_authorized'], 0)
        self.assertEqual(web_outlook_app.decrypt_data(upload['password']), 'upload-pwd')


class GraphOauthFrontendContractTests(unittest.TestCase):
    def test_upload_accounts_frontend_does_not_inline_password_in_onclick(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static/js/index/12-outlook-upload-accounts.js'),
            encoding='utf-8',
        ) as handle:
            js = handle.read()

        self.assertNotIn("showGraphAuthModal(${item.id}, '${escapeHtml(item.email)}', '${escapeHtml(item.password)}')", js)
        self.assertNotIn('item.password ||', js)
        self.assertNotIn('graphAuthState.password', js)
        self.assertIn('data-graph-auth-account-id', js)

    def test_graph_auth_modal_does_not_render_plain_password_container(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates/partials/index/dialogs-management.html'),
            encoding='utf-8',
        ) as handle:
            html = handle.read()

        self.assertNotIn('id="graphAuthPassword"', html)
        self.assertIn('id="graphAuthPasswordMasked"', html)

    def test_4_1_outlook_account_menu_has_auto_auth_imap_does_not(self):
        """Outlook 账号菜单包含"加入自动授权"，IMAP 账号不包含该入口。"""
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static/js/index/02-groups.js'),
            encoding='utf-8',
        ) as handle:
            js = handle.read()

        # The menu button is conditionally rendered for non-IMAP accounts
        self.assertIn("data-account-action=\"outlookAutoAuth\"", js)
        self.assertIn("(acc.account_type || 'outlook') !== 'imap'", js)

    def test_4_5_frontend_does_not_pass_or_render_plain_password(self):
        """前端不传递、不记录、不渲染明文密码。"""
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static/js/index/12-outlook-upload-accounts.js'),
            encoding='utf-8',
        ) as handle:
            js = handle.read()

        # The queueAccountForOutlookAutoAuth function exists and does not send password
        self.assertIn('queueAccountForOutlookAutoAuth', js)
        self.assertIn('/outlook-auto-auth', js)
        # The request body does not include a password field
        self.assertNotIn('password:', js.split('queueAccountForOutlookAutoAuth')[1].split('window.queueAccountForOutlookAutoAuth')[0])


if __name__ == '__main__':
    unittest.main()
