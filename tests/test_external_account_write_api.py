import importlib
import os
import pathlib
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _test_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.test_tmp')
    os.makedirs(_test_root, exist_ok=True)
    _temp_dir = os.path.join(_test_root, 'external_account_write')
    os.makedirs(_temp_dir, exist_ok=True)
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]

CLIENT_ID = '3f2504e0-4f89-11d3-9a0c-0305e82c3301'


def clear_external_write_fixtures(db):
    db.execute('DELETE FROM account_tags')
    db.execute('DELETE FROM account_aliases')
    db.execute('DELETE FROM account_refresh_logs')
    db.execute('DELETE FROM accounts')
    db.execute('DELETE FROM tags')
    db.execute('DELETE FROM audit_logs')
    db.execute("DELETE FROM groups WHERE name = '外部写入测试分组'")
    db.commit()


class ExternalAccountWriteTestBase(unittest.TestCase):
    API_KEY = 'test-external-key'

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            clear_external_write_fixtures(db)
            self.assertTrue(web_outlook_app.set_setting('external_api_key', self.API_KEY))

    def _headers(self):
        return {'X-API-Key': self.API_KEY}

    def _set_permission(self, value):
        with self.app.app_context():
            if value is None:
                db = web_outlook_app.get_db()
                db.execute("DELETE FROM settings WHERE key = 'external_api_key_permission'")
                db.commit()
            else:
                self.assertTrue(web_outlook_app.set_setting('external_api_key_permission', value))

    def _get_permission(self):
        with self.app.app_context():
            return web_outlook_app.get_external_api_key_permission()

    def _login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def _import_lines(self, lines, **payload):
        body = {'accounts': lines}
        body.update(payload)
        return self.client.post(
            '/api/external/accounts',
            headers=self._headers(),
            json=body,
        )

    def _outlook_line(self, email, password='pass-word', client_id=CLIENT_ID, token='rt-token-value'):
        return f'{email}----{password}----{client_id}----{token}'

    def _fetch_account_row(self, email):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            return db.execute(
                'SELECT * FROM accounts WHERE LOWER(email) = ?',
                (email.lower(),),
            ).fetchone()

    def _last_audit_row(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            return db.execute(
                'SELECT action, resource_type, resource_id, details FROM audit_logs ORDER BY id DESC LIMIT 1'
            ).fetchone()


class ExternalAccountWriteAuthTests(ExternalAccountWriteTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readonly')

    def test_missing_api_key_returns_401_before_permission_check(self):
        response = self.client.post(
            '/api/external/accounts',
            json={'accounts': [self._outlook_line('a@outlook.com')]},
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['success'])

    def test_invalid_api_key_returns_401(self):
        response = self.client.post(
            '/api/external/accounts',
            headers={'X-API-Key': 'wrong-key'},
            json={'accounts': [self._outlook_line('a@outlook.com')]},
        )
        self.assertEqual(response.status_code, 401)

    def test_readonly_permission_rejects_import_with_403(self):
        response = self._import_lines([self._outlook_line('a@outlook.com')])
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('readonly', payload['error'])
        self.assertIn('readwrite', payload['error'])

    def test_readonly_permission_rejects_delete_with_403(self):
        response = self.client.delete(
            '/api/external/accounts/email/a@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()['success'])

    def test_unset_permission_defaults_to_readonly(self):
        self._set_permission(None)
        response = self._import_lines([self._outlook_line('a@outlook.com')])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._get_permission(), 'readonly')

    def test_invalid_stored_permission_falls_back_to_readonly(self):
        with self.app.app_context():
            self.assertTrue(
                web_outlook_app.set_setting('external_api_key_permission', 'bogus')
            )
        self.assertEqual(self._get_permission(), 'readonly')
        response = self._import_lines([self._outlook_line('a@outlook.com')])
        self.assertEqual(response.status_code, 403)

    def test_existing_readonly_endpoints_still_work(self):
        response = self.client.get('/api/external/accounts', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])

    def test_routes_marked_with_decorators(self):
        for endpoint in ('api_external_import_accounts', 'api_external_delete_account_by_email'):
            view = self.app.view_functions[endpoint]
            self.assertTrue(getattr(view, '_requires_api_key', False), endpoint)
            self.assertTrue(getattr(view, '_requires_api_key_write', False), endpoint)


class ExternalAccountImportRouteTests(ExternalAccountWriteTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readwrite')

    def test_import_multiline_string(self):
        payload_text = self._outlook_line('one@outlook.com') + '\n' + self._outlook_line('two@outlook.com')
        response = self._import_lines(payload_text)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['added_count'], 2)
        self.assertEqual(payload['skipped_count'], 0)
        self.assertEqual(payload['invalid_count'], 0)
        self.assertEqual(payload['tagged_count'], 0)

        row = self._fetch_account_row('one@outlook.com')
        self.assertIsNotNone(row)
        self.assertEqual(row['group_id'], 1)
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'pass-word')
        self.assertEqual(row['client_id'], CLIENT_ID)
        self.assertEqual(web_outlook_app.decrypt_data(row['refresh_token']), 'rt-token-value')

    def test_import_string_array(self):
        response = self._import_lines([
            self._outlook_line('arr1@outlook.com'),
            '  ',
            self._outlook_line('arr2@outlook.com'),
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['added_count'], 2)

    def test_duplicate_lines_within_request(self):
        line = self._outlook_line('dup@outlook.com')
        response = self._import_lines([line, line])
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['added_count'], 1)
        self.assertEqual(payload['skipped_count'], 1)

    def test_import_existing_email_all_skipped_returns_400(self):
        first = self._import_lines([self._outlook_line('exist@outlook.com')])
        self.assertEqual(first.status_code, 200)

        second = self._import_lines([self._outlook_line('exist@outlook.com')])
        self.assertEqual(second.status_code, 400)
        payload = second.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['added_count'], 0)
        self.assertEqual(payload['skipped_count'], 1)
        self.assertEqual(payload['invalid_count'], 0)

    def test_invalid_lines_counted(self):
        response = self._import_lines([
            self._outlook_line('valid@outlook.com'),
            'no-separator-line',
        ])
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['added_count'], 1)
        self.assertEqual(payload['invalid_count'], 1)

    def test_refresh_token_client_id_format(self):
        token = 'token-first-value'
        response = self._import_lines(
            [f'token-first@outlook.com----pass----{token}----{CLIENT_ID}'],
            account_format='refresh_token_client_id',
        )
        self.assertEqual(response.status_code, 200)
        row = self._fetch_account_row('token-first@outlook.com')
        self.assertEqual(row['client_id'], CLIENT_ID)
        self.assertEqual(web_outlook_app.decrypt_data(row['refresh_token']), token)

    def test_tag_ids_applied(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                "INSERT INTO tags (name, color) VALUES ('外部写入标签', '#1a1a1a')"
            )
            tag_id = cursor.lastrowid
            db.commit()

        response = self._import_lines(
            [self._outlook_line('tagged@outlook.com')],
            tag_ids=[tag_id],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['tagged_count'], 1)

        row = self._fetch_account_row('tagged@outlook.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            binding = db.execute(
                'SELECT tag_id FROM account_tags WHERE account_id = ?', (row['id'],)
            ).fetchone()
        self.assertEqual(binding['tag_id'], tag_id)

    def test_nonexistent_tag_ids_filtered(self):
        response = self._import_lines(
            [self._outlook_line('untagged@outlook.com')],
            tag_ids=[99999],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['tagged_count'], 0)

    def test_group_not_found_returns_404(self):
        response = self._import_lines(
            [self._outlook_line('grouped@outlook.com')],
            group_id=99999,
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])
        self.assertIsNone(self._fetch_account_row('grouped@outlook.com'))

    def test_import_into_custom_group(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                "INSERT INTO groups (name, description) VALUES ('外部写入测试分组', 'n')"
            )
            group_id = cursor.lastrowid
            db.commit()

        response = self._import_lines(
            [self._outlook_line('custom-group@outlook.com')],
            group_id=group_id,
        )
        self.assertEqual(response.status_code, 200)
        row = self._fetch_account_row('custom-group@outlook.com')
        self.assertEqual(row['group_id'], group_id)

    def test_invalid_account_format_returns_400(self):
        response = self._import_lines(
            [self._outlook_line('fmt@outlook.com')],
            account_format='email_password',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('account_format', response.get_json()['error'])

    def test_invalid_imap_port_returns_400(self):
        response = self._import_lines(
            [self._outlook_line('port@outlook.com')],
            imap_port='not-a-port',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_or_empty_accounts_returns_400(self):
        for body in ({}, {'accounts': ''}, {'accounts': []}, {'accounts': 123}):
            response = self.client.post(
                '/api/external/accounts', headers=self._headers(), json=body
            )
            self.assertEqual(response.status_code, 400, body)

        response = self.client.post(
            '/api/external/accounts',
            headers=self._headers(),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_imap_provider_import(self):
        response = self._import_lines(
            ['imap-user@example.com----imap-secret'],
            provider='custom',
            imap_host='imap.example.com',
            imap_port=993,
        )
        self.assertEqual(response.status_code, 200)
        row = self._fetch_account_row('imap-user@example.com')
        self.assertEqual(row['account_type'], 'imap')
        self.assertEqual(row['imap_host'], 'imap.example.com')
        self.assertEqual(web_outlook_app.decrypt_data(row['imap_password']), 'imap-secret')

    def test_remark_persisted(self):
        response = self._import_lines(
            [self._outlook_line('remark@outlook.com')],
            remark='来自外部系统',
        )
        self.assertEqual(response.status_code, 200)
        row = self._fetch_account_row('remark@outlook.com')
        self.assertEqual(row['remark'], '来自外部系统')

    def test_import_writes_audit_log(self):
        self._import_lines([self._outlook_line('audit@outlook.com')])
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'import')
        self.assertEqual(audit['resource_type'], 'accounts')
        self.assertIn('对外 API', audit['details'])
        self.assertIn('新增 1', audit['details'])


class ExternalAccountDeleteRouteTests(ExternalAccountWriteTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readwrite')

    def _seed_account(self, email):
        response = self._import_lines([self._outlook_line(email)])
        self.assertEqual(response.status_code, 200)

    def test_delete_existing_account(self):
        self._seed_account('delete-me@outlook.com')
        response = self.client.delete(
            '/api/external/accounts/email/delete-me@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['deleted_email'], 'delete-me@outlook.com')
        self.assertIsNone(self._fetch_account_row('delete-me@outlook.com'))

    def test_delete_nonexistent_returns_404(self):
        response = self.client.delete(
            '/api/external/accounts/email/ghost@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])

    def test_delete_url_encoded_email(self):
        self._seed_account('encoded@outlook.com')
        response = self.client.delete(
            '/api/external/accounts/email/encoded%40outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._fetch_account_row('encoded@outlook.com'))

    def test_delete_plus_addressed_email(self):
        self._seed_account('plus+tag@outlook.com')
        response = self.client.delete(
            '/api/external/accounts/email/plus+tag@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._fetch_account_row('plus+tag@outlook.com'))

    def test_delete_case_insensitive_returns_canonical_email(self):
        self._seed_account('User@Outlook.com')
        response = self.client.delete(
            '/api/external/accounts/email/user@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['deleted_email'], 'User@Outlook.com')
        self.assertIsNone(self._fetch_account_row('user@outlook.com'))

    def test_delete_via_alias_deletes_owner_account(self):
        self._seed_account('owner@outlook.com')
        row = self._fetch_account_row('owner@outlook.com')
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                'INSERT INTO account_aliases (account_id, alias_email) VALUES (?, ?)',
                (row['id'], 'alias@outlook.com'),
            )
            db.commit()

        response = self.client.delete(
            '/api/external/accounts/email/alias@outlook.com',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['deleted_email'], 'owner@outlook.com')
        self.assertIsNone(self._fetch_account_row('owner@outlook.com'))

    def test_delete_failure_returns_500(self):
        self._seed_account('fail@outlook.com')
        with patch.object(web_outlook_app, 'delete_account_by_email', return_value=False):
            response = self.client.delete(
                '/api/external/accounts/email/fail@outlook.com',
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()['success'])

    def test_delete_writes_audit_log(self):
        self._seed_account('audit-del@outlook.com')
        self.client.delete(
            '/api/external/accounts/email/audit-del@outlook.com',
            headers=self._headers(),
        )
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'delete')
        self.assertEqual(audit['resource_type'], 'account')
        self.assertEqual(audit['resource_id'], 'audit-del@outlook.com')
        self.assertIn('对外 API', audit['details'])


class ExternalApiKeyPermissionSettingsTests(ExternalAccountWriteTestBase):
    def test_get_settings_echoes_default_readonly(self):
        self._set_permission(None)
        self._login()
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['settings']['external_api_key_permission'], 'readonly')

    def test_put_settings_updates_permission_and_unlocks_write(self):
        self._set_permission('readonly')
        blocked = self._import_lines([self._outlook_line('unlock@outlook.com')])
        self.assertEqual(blocked.status_code, 403)

        self._login()
        response = self.client.put(
            '/api/settings',
            json={'external_api_key_permission': 'readwrite'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])

        allowed = self._import_lines([self._outlook_line('unlock@outlook.com')])
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()['added_count'], 1)

    def test_put_settings_normalizes_case(self):
        self._login()
        response = self.client.put(
            '/api/settings',
            json={'external_api_key_permission': 'READWRITE'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._get_permission(), 'readwrite')

    def test_put_settings_invalid_value_returns_400_and_keeps_old(self):
        self._set_permission('readwrite')
        self._login()
        response = self.client.put(
            '/api/settings',
            json={'external_api_key_permission': 'admin'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])
        self.assertEqual(self._get_permission(), 'readwrite')

    def test_put_without_field_keeps_permission(self):
        self._set_permission('readwrite')
        self._login()
        response = self.client.put(
            '/api/settings',
            json={'external_api_key': 'brand-new-key'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._get_permission(), 'readwrite')


class ExternalAccountWriteFrontendStructureTests(unittest.TestCase):
    def test_settings_dialog_contains_permission_select(self):
        html = (ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-management.html').read_text(
            encoding='utf-8'
        )
        self.assertIn('id="settingsExternalApiKeyPermission"', html)
        self.assertIn('value="readonly"', html)
        self.assertIn('value="readwrite"', html)

    def test_settings_js_loads_and_saves_permission(self):
        js = (ROOT_DIR / 'static' / 'js' / 'index' / '07-settings.js').read_text(encoding='utf-8')
        self.assertIn('external_api_key_permission', js)
        self.assertIn('settingsExternalApiKeyPermission', js)


if __name__ == '__main__':
    unittest.main()
