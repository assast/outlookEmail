"""Tests for POST /api/accounts/<account_id>/outlook-auto-auth (tasks 2.1 – 2.3)."""

import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-auto-auth-queue-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class OutlookAutoAuthQueueTests(unittest.TestCase):
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

    def _add_outlook_account(self, email='auto@outlook.com', password='formal-pwd'):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                email,
                password,
                'old-client-id',
                'old-refresh-token',
                group_id=1,
                remark='auto auth remark',
                account_type='outlook',
                provider='outlook',
            )
            self.assertTrue(added)
            return web_outlook_app.get_account_by_email(email)['id']

    def _post_queue(self, account_id):
        return self.client.post(f'/api/accounts/{account_id}/outlook-auto-auth')

    # --- Task 2.1 ---

    def test_2_1_queue_outlook_account_returns_id_and_status_no_password(self):
        account_id = self._add_outlook_account('queue@outlook.com', 'secret-pwd')

        response = self._post_queue(account_id)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn(payload['status'], ('added', 'updated'))
        self.assertEqual(payload['email'], 'queue@outlook.com')
        self.assertIsInstance(payload['upload_account_id'], int)

        # Response must not contain password
        self.assertNotIn('password', payload)
        self.assertNotIn('secret-pwd', response.get_data(as_text=True))

        # Upload row created with correct data
        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT email, password, is_authorized, status, source "
                "FROM outlook_upload_accounts WHERE id = ?",
                (payload['upload_account_id'],),
            ).fetchone()

        self.assertEqual(row['email'], 'queue@outlook.com')
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'secret-pwd')
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['source'], 'auto_auth')

    def test_2_1_requeue_existing_upload_row_returns_updated(self):
        account_id = self._add_outlook_account('requeue@outlook.com', 'formal-pwd')
        # First queue
        r1 = self._post_queue(account_id)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.get_json()['status'], 'added')

        # Simulate it was authorized and cleared
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "UPDATE outlook_upload_accounts SET is_authorized = 1, password = '' WHERE email = ?",
                ('requeue@outlook.com',),
            )
            db.commit()

        # Re-queue
        r2 = self._post_queue(account_id)
        self.assertEqual(r2.status_code, 200)
        payload = r2.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['status'], 'updated')

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT is_authorized, status, password FROM outlook_upload_accounts WHERE email = ?",
                ('requeue@outlook.com',),
            ).fetchone()

        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'formal-pwd')

    # --- Task 2.2 ---

    def test_2_2_rejects_missing_account(self):
        response = self._post_queue(99999)
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error']['code'], 'ACCOUNT_NOT_FOUND')

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS cnt FROM outlook_upload_accounts'
            ).fetchone()['cnt']
        self.assertEqual(count, 0)

    def test_2_2_rejects_imap_account(self):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                'imap@outlook.com',
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
            account_id = web_outlook_app.get_account_by_email('imap@outlook.com')['id']

        response = self._post_queue(account_id)
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error']['code'], 'ACCOUNT_AUTO_AUTH_UNSUPPORTED')

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS cnt FROM outlook_upload_accounts WHERE email = ?',
                ('imap@outlook.com',),
            ).fetchone()['cnt']
        self.assertEqual(count, 0)

    def test_2_2_rejects_account_with_empty_password(self):
        with self.app.app_context():
            added = web_outlook_app.add_account(
                'nopass@outlook.com',
                '',
                'client-id',
                'refresh-token',
                group_id=1,
                account_type='outlook',
            )
            self.assertTrue(added)
            account_id = web_outlook_app.get_account_by_email('nopass@outlook.com')['id']

        response = self._post_queue(account_id)
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error']['code'], 'ACCOUNT_PASSWORD_MISSING')

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS cnt FROM outlook_upload_accounts WHERE email = ?',
                ('nopass@outlook.com',),
            ).fetchone()['cnt']
        self.assertEqual(count, 0)

    # --- Task 2.3 ---

    def test_2_3_requires_login(self):
        account_id = self._add_outlook_account('auth@outlook.com', 'pwd')
        # Use a client without login session
        with self.app.test_client() as unauth_client:
            response = unauth_client.post(f'/api/accounts/{account_id}/outlook-auto-auth')
        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload.get('need_login'))

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS cnt FROM outlook_upload_accounts'
            ).fetchone()['cnt']
        self.assertEqual(count, 0)

    @unittest.skipUnless(
        getattr(web_outlook_app, 'CSRF_AVAILABLE', False),
        'Flask-WTF not installed',
    )
    def test_2_3_requires_csrf_when_protection_is_enabled(self):
        account_id = self._add_outlook_account('csrf@outlook.com', 'pwd')
        original_csrf = self.app.config.get('WTF_CSRF_ENABLED')
        original_check_default = self.app.config.get('WTF_CSRF_CHECK_DEFAULT')
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['WTF_CSRF_CHECK_DEFAULT'] = True
        try:
            response = self._post_queue(account_id)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = original_csrf
            if original_check_default is None:
                self.app.config.pop('WTF_CSRF_CHECK_DEFAULT', None)
            else:
                self.app.config['WTF_CSRF_CHECK_DEFAULT'] = original_check_default

        self.assertEqual(response.status_code, 400)

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS cnt FROM outlook_upload_accounts'
            ).fetchone()['cnt']
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
