import importlib
import os
import tempfile
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _test_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.test_tmp')
    os.makedirs(_test_root, exist_ok=True)
    _temp_dir = os.path.join(_test_root, 'outlook_upload')
    os.makedirs(_temp_dir, exist_ok=True)
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class OutlookUploadSchemaTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()

    def test_table_exists_with_expected_columns_and_defaults(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            columns = {row[1]: row for row in db.execute(
                'PRAGMA table_info(outlook_upload_accounts)'
            ).fetchall()}

        for name in ['id', 'email', 'password', 'is_authorized',
                     'status', 'remark', 'source', 'created_at', 'updated_at']:
            self.assertIn(name, columns)

    def test_is_authorized_defaults_to_zero(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                ('default@outlook.com', 'pwd'),
            )
            db.commit()
            row = db.execute(
                "SELECT is_authorized, status, source FROM outlook_upload_accounts WHERE email = ?",
                ('default@outlook.com',),
            ).fetchone()

        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['source'], 'external_api')

    def test_email_is_unique(self):
        import sqlite3
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                ('dup@outlook.com', 'p1'),
            )
            db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                    ('dup@outlook.com', 'p2'),
                )
                db.commit()


class OutlookUploadDataLayerTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()

    def test_add_single_account_normalizes_and_persists_encrypted_password(self):
        with self.app.app_context():
            result = web_outlook_app.add_upload_account('  USER@Outlook.com ', 'secret', 'note')
            web_outlook_app.get_db().commit()
            self.assertEqual(result['status'], 'added')
            self.assertEqual(result['email'], 'user@outlook.com')
            self.assertIsInstance(result['id'], int)

            row = web_outlook_app.get_db().execute(
                "SELECT email, password, is_authorized, remark FROM outlook_upload_accounts WHERE id = ?",
                (result['id'],),
            ).fetchone()
        self.assertEqual(row['email'], 'user@outlook.com')
        self.assertNotEqual(row['password'], 'secret')
        self.assertTrue(row['password'].startswith('enc:'))
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'secret')
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['remark'], 'note')

    def test_add_duplicate_email_returns_duplicate(self):
        with self.app.app_context():
            web_outlook_app.add_upload_account('dupe@outlook.com', 'p1')
            web_outlook_app.get_db().commit()
            result = web_outlook_app.add_upload_account('dupe@outlook.com', 'p2')
            web_outlook_app.get_db().commit()
            self.assertEqual(result['status'], 'duplicate')
            row = web_outlook_app.get_db().execute(
                "SELECT password FROM outlook_upload_accounts WHERE email = ?",
                ('dupe@outlook.com',),
            ).fetchone()
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'p1')   # 原值未被覆盖

    def test_add_invalid_email_or_empty_password_returns_invalid(self):
        with self.app.app_context():
            r1 = web_outlook_app.add_upload_account('not-an-email', 'p')
            r2 = web_outlook_app.add_upload_account('ok@outlook.com', '')
            web_outlook_app.get_db().commit()
        self.assertEqual(r1['status'], 'invalid')
        self.assertEqual(r2['status'], 'invalid')

    def test_bulk_add_reports_counts_and_preserves_order(self):
        with self.app.app_context():
            web_outlook_app.add_upload_account('exists@outlook.com', 'old')
            web_outlook_app.get_db().commit()
            summary = web_outlook_app.add_upload_accounts_bulk([
                {'email': 'new1@outlook.com', 'password': 'p1'},
                {'email': 'exists@outlook.com', 'password': 'p2'},
                {'email': 'bad', 'password': 'p3'},
            ])
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['added'], 1)
        self.assertEqual(summary['duplicate'], 1)
        self.assertEqual(summary['invalid'], 1)
        self.assertEqual([r['status'] for r in summary['results']],
                         ['added', 'duplicate', 'invalid'])
        self.assertEqual([r['email'] for r in summary['results']],
                         ['new1@outlook.com', 'exists@outlook.com', 'bad'])


class OutlookUploadRouteTests(unittest.TestCase):
    API_KEY = 'test-external-key'

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()
            self.assertTrue(web_outlook_app.set_setting('external_api_key', self.API_KEY))

    def _headers(self):
        return {'X-API-Key': self.API_KEY}

    def test_requires_api_key(self):
        response = self.client.post('/api/external/outlook/upload',
                                    json={'email': 'a@outlook.com', 'password': 'p'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['success'])

    def test_single_upload_succeeds_and_hides_password(self):
        response = self.client.post(
            '/api/external/outlook/upload',
            headers=self._headers(),
            json={'email': 'single@outlook.com', 'password': 'secret', 'remark': 'n'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['added'], 1)
        self.assertEqual(payload['results'][0]['status'], 'added')
        # 响应不回显 password
        self.assertNotIn('password', payload['results'][0])
        self.assertNotIn('secret', response.get_data(as_text=True))

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT is_authorized, password FROM outlook_upload_accounts WHERE email = ?",
                ('single@outlook.com',),
            ).fetchone()
        self.assertEqual(row['is_authorized'], 0)
        self.assertNotEqual(row['password'], 'secret')
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'secret')

    def test_list_upload_accounts_masks_password(self):
        with self.app.app_context():
            web_outlook_app.add_upload_account('list@outlook.com', 'secret', 'n')
            web_outlook_app.get_db().commit()
        with self.client.session_transaction() as session:
            session['logged_in'] = True

        response = self.client.get('/api/outlook-upload-accounts')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        item = next(item for item in payload['items'] if item['email'] == 'list@outlook.com')
        self.assertNotIn('password', item)
        self.assertTrue(item['has_password'])
        self.assertEqual(item['password_length'], len('secret'))

    def test_list_upload_accounts_tolerates_corrupted_encrypted_password(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            web_outlook_app.add_upload_account('good@outlook.com', 'secret', 'n')
            db.execute(
                "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                ('bad@outlook.com', 'enc:not-a-valid-token'),
            )
            db.commit()
        with self.client.session_transaction() as session:
            session['logged_in'] = True

        response = self.client.get('/api/outlook-upload-accounts')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        items = {item['email']: item for item in payload['items']}
        self.assertTrue(items['good@outlook.com']['has_password'])
        self.assertFalse(items['bad@outlook.com']['has_password'])
        self.assertEqual(items['bad@outlook.com']['password_length'], 0)

    def test_bulk_upload_reports_counts(self):
        response = self.client.post(
            '/api/external/outlook/upload',
            headers=self._headers(),
            json={'accounts': [
                {'email': 'b1@outlook.com', 'password': 'p1'},
                {'email': 'b1@outlook.com', 'password': 'p2'},
                {'email': 'bad', 'password': 'p3'},
            ]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 3)
        self.assertEqual(payload['added'], 1)
        self.assertEqual(payload['duplicate'], 1)
        self.assertEqual(payload['invalid'], 1)

    def test_empty_body_returns_400(self):
        response = self.client.post('/api/external/outlook/upload',
                                    headers=self._headers(), json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_route_is_marked_api_key_required(self):
        view = self.app.view_functions['api_external_upload_outlook']
        self.assertTrue(getattr(view, '_requires_api_key', False))


if __name__ == '__main__':
    unittest.main()
