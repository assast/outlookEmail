import importlib
import os
import tempfile
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-upload-tests-')
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

    def test_add_single_account_normalizes_and_persists_plaintext(self):
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
        self.assertEqual(row['password'], 'secret')   # 明文，未加密
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
        self.assertEqual(row['password'], 'p1')   # 原值未被覆盖

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


if __name__ == '__main__':
    unittest.main()
