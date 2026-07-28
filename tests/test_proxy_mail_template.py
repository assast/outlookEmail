import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-proxy-mail-template-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

web_outlook_app = importlib.import_module('web_outlook_app')


class ProxyMailTemplateTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.execute(
                "UPDATE groups SET parent_id = NULL, level = 1, "
                "proxy_url = '', fallback_proxy_url_1 = '', fallback_proxy_url_2 = '' "
                "WHERE name IN ('默认分组', '临时邮箱')"
            )
            db.commit()

    def test_resolve_log_level_from_env_name(self):
        self.assertEqual(web_outlook_app.resolve_log_level('DEBUG'), 10)
        self.assertEqual(web_outlook_app.resolve_log_level('warning'), 30)
        self.assertEqual(web_outlook_app.resolve_log_level('not-a-level'), 20)

    def test_format_proxy_for_log_redacts_password_keeps_username(self):
        format_log = web_outlook_app.format_proxy_for_log
        self.assertEqual(format_log(''), '直连(未配置应用代理)')
        self.assertEqual(format_log('direct'), 'direct')
        self.assertEqual(
            format_log('socks5h://outlook.alicebob:secret@127.0.0.1:2260'),
            'socks5h://outlook.alicebob:***@127.0.0.1:2260',
        )
        self.assertEqual(
            format_log('socks5h://outlook.alicebob@127.0.0.1:2260'),
            'socks5h://outlook.alicebob@127.0.0.1:2260',
        )

    def test_socks_empty_password_forces_userpass_for_pysocks(self):
        """空密码时 PySocks 会跳过 UserPass；传输层必须补占位密码。"""
        prepare = web_outlook_app.prepare_proxy_url_for_transport
        resolve = web_outlook_app.resolve_socks_proxy_auth

        self.assertEqual(
            resolve('test.user', None),
            ('test.user', web_outlook_app.SOCKS_EMPTY_PASSWORD_PLACEHOLDER),
        )
        self.assertEqual(
            resolve('test.user', ''),
            ('test.user', web_outlook_app.SOCKS_EMPTY_PASSWORD_PLACEHOLDER),
        )
        self.assertEqual(resolve('test.user', 'secret'), ('test.user', 'secret'))
        self.assertEqual(resolve(None, None), (None, None))

        for raw in (
            'socks5h://test.abbottiwanow436178437@10.144.144.10:2260',
            'socks5h://test.abbottiwanow436178437:@10.144.144.10:2260',
        ):
            prepared = prepare(raw)
            self.assertIn('@10.144.144.10:2260', prepared)
            self.assertIn(':', prepared.split('@', 1)[0])  # user:pass present
            from urllib.parse import urlparse, unquote
            parsed = urlparse(prepared)
            self.assertEqual(unquote(parsed.username), 'test.abbottiwanow436178437')
            self.assertTrue(unquote(parsed.password))  # truthy for PySocks

        unchanged = 'socks5h://test.user:secret@10.144.144.10:2260'
        self.assertEqual(prepare(unchanged), unchanged)
        self.assertEqual(prepare('http://test.user@10.144.144.10:2260'), 'http://test.user@10.144.144.10:2260')

    def test_expand_proxy_url_template_rules(self):
        expand = web_outlook_app.expand_proxy_url_template
        template = 'socks5h://outlook.{mail}:123@127.0.0.1:2260'

        self.assertEqual(
            expand(template, 'Alice.Bob+tag@outlook.com'),
            'socks5h://outlook.alicebobtag:123@127.0.0.1:2260',
        )
        self.assertEqual(
            expand('socks5h://user:pass@127.0.0.1:1080', 'a@b.com'),
            'socks5h://user:pass@127.0.0.1:1080',
        )
        self.assertEqual(expand(template, None), template)
        self.assertEqual(expand(template, ''), template)
        self.assertEqual(
            expand('socks5h://outlook.{mail}:@127.0.0.1:2260', '中文用户@x.com'),
            'socks5h://outlook.:@127.0.0.1:2260',
        )
        self.assertEqual(
            expand('http://outlook.{mail}@127.0.0.1:2260', 'User_Name@x.com'),
            'http://outlook.username@127.0.0.1:2260',
        )

    def test_get_account_resolved_expands_primary_and_fallbacks(self):
        with self.app.app_context():
            group_id = web_outlook_app.add_group(
                'Resin组',
                proxy_url='socks5h://outlook.{mail}:tok@127.0.0.1:2260',
                fallback_proxy_url_1='socks5h://backup.{mail}:tok@127.0.0.1:2260',
                fallback_proxy_url_2='direct',
            )
            db = web_outlook_app.get_db()
            db.execute(
                '''INSERT INTO accounts (email, password, client_id, refresh_token, account_type, provider, group_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                ('Alice.Bob@example.com', 'p', 'cid', 'rt', 'outlook', 'outlook', group_id),
            )
            db.commit()
            account = web_outlook_app.get_account_by_email('Alice.Bob@example.com')

            stored = web_outlook_app.get_account_proxy_config(account)
            self.assertEqual(stored['proxy_url'], 'socks5h://outlook.{mail}:tok@127.0.0.1:2260')
            self.assertEqual(stored['fallback_proxy_url_1'], 'socks5h://backup.{mail}:tok@127.0.0.1:2260')

            resolved = web_outlook_app.get_account_resolved_proxy_config(account)
            self.assertEqual(resolved['proxy_url'], 'socks5h://outlook.alicebob:tok@127.0.0.1:2260')
            self.assertEqual(resolved['fallback_proxy_url_1'], 'socks5h://backup.alicebob:tok@127.0.0.1:2260')
            self.assertEqual(resolved['fallback_proxy_url_2'], 'direct')
            self.assertEqual(
                web_outlook_app.get_account_proxy_url(account),
                'socks5h://outlook.alicebob:tok@127.0.0.1:2260',
            )
            self.assertEqual(
                web_outlook_app.get_account_proxy_failover_urls(account),
                ['socks5h://backup.alicebob:tok@127.0.0.1:2260', 'direct'],
            )

    def test_account_override_beats_group_template(self):
        with self.app.app_context():
            group_id = web_outlook_app.add_group(
                '组代理',
                proxy_url='socks5h://group.{mail}:g@127.0.0.1:2260',
            )
            db = web_outlook_app.get_db()
            db.execute(
                '''INSERT INTO accounts
                   (email, password, client_id, refresh_token, account_type, provider, group_id, proxy_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    'user@example.com', 'p', 'cid', 'rt', 'outlook', 'outlook', group_id,
                    'socks5h://acct.{mail}:a@127.0.0.1:2260',
                ),
            )
            db.commit()
            account = web_outlook_app.get_account_by_email('user@example.com')
            self.assertEqual(
                web_outlook_app.get_account_proxy_url(account),
                'socks5h://acct.user:a@127.0.0.1:2260',
            )

    def test_upload_account_proxy_own_then_group_inheritance(self):
        with self.app.app_context():
            group_id = web_outlook_app.add_group(
                '上传继承组',
                proxy_url='socks5h://outlook.{mail}:g@127.0.0.1:2260',
                fallback_proxy_url_1='socks5h://fb.{mail}:g@127.0.0.1:2260',
            )
            own = web_outlook_app.get_upload_account_resolved_proxy_config({
                'email': 'Own.User@example.com',
                'proxy_url': 'socks5h://outlook.{mail}:own@127.0.0.1:2260',
                'group_id': group_id,
            })
            self.assertEqual(own['proxy_url'], 'socks5h://outlook.ownuser:own@127.0.0.1:2260')
            self.assertEqual(own['fallback_proxy_url_1'], '')

            inherited = web_outlook_app.get_upload_account_resolved_proxy_config({
                'email': 'Bob+1@example.com',
                'proxy_url': '',
                'group_id': group_id,
            })
            self.assertEqual(inherited['proxy_url'], 'socks5h://outlook.bob1:g@127.0.0.1:2260')
            self.assertEqual(inherited['fallback_proxy_url_1'], 'socks5h://fb.bob1:g@127.0.0.1:2260')

            empty = web_outlook_app.get_upload_account_resolved_proxy_config({
                'email': 'x@y.com',
                'proxy_url': '',
                'group_id': None,
            })
            self.assertEqual(empty, web_outlook_app.get_empty_proxy_config())

    def test_refresh_outlook_account_token_uses_resolved_account_proxy(self):
        with self.app.app_context():
            group_id = web_outlook_app.add_group(
                '刷新组',
                proxy_url='socks5h://group.{mail}:g@127.0.0.1:2260',
            )
            db = web_outlook_app.get_db()
            encrypted = web_outlook_app.encrypt_data('refresh-token-value')
            cursor = db.execute(
                '''INSERT INTO accounts
                   (email, password, client_id, refresh_token, account_type, provider, group_id, proxy_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    'Refresh.User@example.com', 'p', 'client-id', encrypted,
                    'outlook', 'outlook', group_id,
                    'socks5h://acct.{mail}:a@127.0.0.1:2260',
                ),
            )
            db.commit()
            account = db.execute('SELECT * FROM accounts WHERE id = ?', (cursor.lastrowid,)).fetchone()

            with patch.object(
                web_outlook_app,
                'test_refresh_token',
                return_value=(True, None, ''),
            ) as token_mock:
                result = web_outlook_app.refresh_outlook_account_token(account, 'manual', db_conn=db)

            self.assertTrue(result['success'])
            token_mock.assert_called_once()
            args = token_mock.call_args[0]
            self.assertEqual(args[2], 'socks5h://acct.refreshuser:a@127.0.0.1:2260')


class ExtractGraphProxySessionTests(unittest.TestCase):
    def _make_session(self):
        class RecordingSession:
            def __init__(self):
                self.headers = {}
                self.trust_env = True
                self.proxies = {}
                self.get_calls = []
                self.post_calls = []

            def get(self, url, **kwargs):
                self.get_calls.append((url, kwargs))
                return type('R', (), {
                    'url': url,
                    'text': '<input name="PPFT" value="flow"><script>"urlPost":"https://post"</script>',
                    'status_code': 200,
                    'headers': {},
                })()

            def post(self, url, data=None, **kwargs):
                self.post_calls.append((url, data or {}, kwargs))
                if 'token' in url or 'oauth2' in url:
                    return type('R', (), {
                        'url': url,
                        'text': '',
                        'status_code': 200,
                        'headers': {},
                        'json': lambda self=None: {
                            'access_token': 'a',
                            'refresh_token': 'r',
                        },
                    })()
                return type('R', (), {
                    'url': 'http://localhost?code=c',
                    'text': '',
                    'status_code': 200,
                    'headers': {},
                })()

        return RecordingSession()

    def test_extract_sets_session_proxy_and_disables_trust_env(self):
        session = self._make_session()
        result = web_outlook_app.extract_graph_refresh_token(
            'user@example.com',
            'password',
            session_factory=lambda: session,
            proxy_url='socks5h://outlook.user:tok@127.0.0.1:2260',
        )
        self.assertTrue(result['success'])
        self.assertFalse(session.trust_env)
        self.assertEqual(
            session.proxies.get('https'),
            'socks5h://outlook.user:tok@127.0.0.1:2260',
        )

    def test_extract_without_proxy_keeps_trust_env(self):
        session = self._make_session()
        session.trust_env = False
        result = web_outlook_app.extract_graph_refresh_token(
            'user@example.com',
            'password',
            session_factory=lambda: session,
        )
        self.assertTrue(result['success'])
        self.assertTrue(session.trust_env)
        self.assertEqual(session.proxies, {})


if __name__ == '__main__':
    unittest.main()
