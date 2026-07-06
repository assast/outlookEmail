import importlib
import os
import pathlib
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
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


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


class OutlookUploadRequeueTests(unittest.TestCase):
    """Tests for upsert_upload_account_for_auto_auth (tasks 1.1 – 1.3, 1.5)."""

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()

    def test_1_1_new_email_creates_record_with_encrypted_password(self):
        """正式邮箱加入自动授权时新增记录，密码加密且响应不回显明文。"""
        with self.app.app_context():
            result = web_outlook_app.upsert_upload_account_for_auto_auth(
                '  New@Outlook.com ', 'secret-pwd', 'from-formal-account'
            )
            web_outlook_app.get_db().commit()

            self.assertEqual(result['status'], 'added')
            self.assertEqual(result['email'], 'new@outlook.com')
            self.assertIsInstance(result['id'], int)

            row = web_outlook_app.get_db().execute(
                "SELECT email, password, is_authorized, status, remark, source "
                "FROM outlook_upload_accounts WHERE id = ?",
                (result['id'],),
            ).fetchone()

        self.assertEqual(row['email'], 'new@outlook.com')
        self.assertNotEqual(row['password'], 'secret-pwd')
        self.assertTrue(row['password'].startswith('enc:'))
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'secret-pwd')
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['source'], 'auto_auth')
        self.assertEqual(row['remark'], 'from-formal-account')
        # 返回值不包含密码
        self.assertNotIn('password', result)

    def test_1_2_requeue_authorized_row_overwrites_and_resets(self):
        """同邮箱已授权暂存记录重新入队时覆盖密码、重置 is_authorized=0、status=active。"""
        with self.app.app_context():
            # 先用 add_upload_account 添加一条，再模拟已授权
            add_result = web_outlook_app.add_upload_account(
                'queue@outlook.com', 'old-password', 'old remark'
            )
            web_outlook_app.get_db().commit()
            upload_id = add_result['id']

            db = web_outlook_app.get_db()
            db.execute(
                "UPDATE outlook_upload_accounts SET is_authorized = 1, password = '', "
                "status = 'done', remark = 'authorized' WHERE id = ?",
                (upload_id,),
            )
            db.commit()

            # 重新入队
            result = web_outlook_app.upsert_upload_account_for_auto_auth(
                'queue@outlook.com', 'new-password', 'requeued'
            )
            web_outlook_app.get_db().commit()

            self.assertEqual(result['status'], 'updated')
            self.assertEqual(result['id'], upload_id)

            row = db.execute(
                "SELECT email, password, is_authorized, status, remark, source, "
                "COUNT(*) OVER () AS total_rows "
                "FROM outlook_upload_accounts WHERE email = ?",
                ('queue@outlook.com',),
            ).fetchone()

        self.assertEqual(row['email'], 'queue@outlook.com')
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'new-password')
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['remark'], 'requeued')
        self.assertEqual(row['source'], 'auto_auth')
        # 不创建重复记录
        self.assertEqual(row['total_rows'], 1)

    def test_1_3_requeue_unauthorized_row_overwrites_metadata(self):
        """同邮箱未授权暂存记录重新入队时覆盖密码和备注/来源，保持单行。"""
        with self.app.app_context():
            add_result = web_outlook_app.add_upload_account(
                'pending@outlook.com', 'first-pwd', 'first note'
            )
            web_outlook_app.get_db().commit()
            upload_id = add_result['id']

            result = web_outlook_app.upsert_upload_account_for_auto_auth(
                'pending@outlook.com', 'second-pwd', 'second note'
            )
            web_outlook_app.get_db().commit()

            self.assertEqual(result['status'], 'updated')
            self.assertEqual(result['id'], upload_id)

            row = web_outlook_app.get_db().execute(
                "SELECT password, is_authorized, status, remark, source, "
                "COUNT(*) OVER () AS total_rows "
                "FROM outlook_upload_accounts WHERE email = ?",
                ('pending@outlook.com',),
            ).fetchone()

        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'second-pwd')
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['remark'], 'second note')
        self.assertEqual(row['source'], 'auto_auth')
        self.assertEqual(row['total_rows'], 1)

    def test_1_5_external_upload_duplicate_still_returns_duplicate(self):
        """未走显式重新入队路径时重复邮箱仍返回 duplicate 且不覆盖旧密码。"""
        with self.app.app_context():
            web_outlook_app.add_upload_account('ext@outlook.com', 'original')
            web_outlook_app.get_db().commit()
            result = web_outlook_app.add_upload_account('ext@outlook.com', 'overwrite')
            web_outlook_app.get_db().commit()

            self.assertEqual(result['status'], 'duplicate')

            row = web_outlook_app.get_db().execute(
                "SELECT password FROM outlook_upload_accounts WHERE email = ?",
                ('ext@outlook.com',),
            ).fetchone()

        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'original')


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

    def test_list_upload_accounts_returns_password_for_inline_edit(self):
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
        self.assertEqual(item['password'], 'secret')
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


class OutlookUploadUpdateRouteTests(unittest.TestCase):
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
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def _seed(self, email='edit@outlook.com', password='oldpw', remark='old'):
        with self.app.app_context():
            result = web_outlook_app.add_upload_account(email, password, remark)
            web_outlook_app.get_db().commit()
        return result['id']

    def test_update_changes_email_password_and_remark(self):
        account_id = self._seed()
        response = self.client.put(
            f'/api/outlook-upload-accounts/{account_id}',
            json={'email': 'new@outlook.com', 'password': 'newpw', 'remark': 'updated'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT email, password, remark FROM outlook_upload_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        self.assertEqual(row['email'], 'new@outlook.com')
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'newpw')
        self.assertEqual(row['remark'], 'updated')

    def test_update_keeps_password_when_omitted_or_empty(self):
        account_id = self._seed(password='keepme')
        response = self.client.put(
            f'/api/outlook-upload-accounts/{account_id}',
            json={'email': 'edit@outlook.com', 'remark': 'r'},
        )
        self.assertEqual(response.status_code, 200)
        response2 = self.client.put(
            f'/api/outlook-upload-accounts/{account_id}',
            json={'email': 'edit@outlook.com', 'password': '', 'remark': 'r'},
        )
        self.assertEqual(response2.status_code, 200)
        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT password FROM outlook_upload_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        self.assertEqual(web_outlook_app.decrypt_data(row['password']), 'keepme')

    def test_update_duplicate_email_returns_400(self):
        self._seed(email='a@outlook.com')
        account_id_b = self._seed(email='b@outlook.com')
        response = self.client.put(
            f'/api/outlook-upload-accounts/{account_id_b}',
            json={'email': 'a@outlook.com'},
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertFalse(body['success'])
        self.assertIn('已存在', body['error'])

    def test_update_invalid_email_returns_400(self):
        account_id = self._seed()
        response = self.client.put(
            f'/api/outlook-upload-accounts/{account_id}',
            json={'email': 'no-at-sign'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_update_not_found_returns_404(self):
        response = self.client.put(
            '/api/outlook-upload-accounts/99999',
            json={'email': 'x@outlook.com'},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])


class OutlookUploadFrontendStructureTests(unittest.TestCase):
    def test_add_account_form_is_inline_above_table(self):
        html = (ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-management.html').read_text(encoding='utf-8')
        js = (ROOT_DIR / 'static' / 'js' / 'index' / '12-outlook-upload-accounts.js').read_text(encoding='utf-8')

        add_panel_index = html.index('class="upload-accounts-add-panel"')
        table_index = html.index('class="upload-accounts-table-wrap"')
        self.assertLess(add_panel_index, table_index)
        self.assertNotIn('id="toggleAddPanelBtn"', html)
        self.assertNotIn('upload-accounts-add-panel__form is-collapsed', html)
        self.assertNotIn('toggleAddAccountPanel', js)

    def test_add_account_password_is_visible(self):
        html = (ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-management.html').read_text(encoding='utf-8')

        self.assertIn('type="text" id="addUploadAccountPassword"', html)
        self.assertNotIn('type="password" id="addUploadAccountPassword"', html)

    def test_edit_row_prefills_visible_password(self):
        js = (ROOT_DIR / 'static' / 'js' / 'index' / '12-outlook-upload-accounts.js').read_text(encoding='utf-8')

        self.assertIn("const itemPassword = item.password || '';", js)
        self.assertIn('id="edit-password-${escapeHtml(String(itemId))}"', js)
        self.assertIn('value="${escapeHtml(itemPassword)}"', js)
        self.assertNotIn('input type="password" class="upload-accounts-edit-input"', js)
        self.assertNotIn('placeholder="留空不改"', js)

    def test_passwords_are_visible_without_reveal_controls(self):
        html = (ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-management.html').read_text(encoding='utf-8')
        js = (ROOT_DIR / 'static' / 'js' / 'index' / '12-outlook-upload-accounts.js').read_text(encoding='utf-8')

        self.assertIn("return item.password || '';", js)
        self.assertIn('<td class="upload-accounts-cell-mono">${escapeHtml(formatUploadAccountPassword(item))}</td>', js)
        self.assertNotIn("return escapeHtml(item.password || '')", js)
        self.assertNotIn('id="addUploadAccountPassword" type="password"', html)
        self.assertNotIn('password-toggle', html)
        self.assertNotIn('secret-reveal', html)
        self.assertNotIn('password-toggle', js)
        self.assertNotIn('secret-reveal', js)


if __name__ == '__main__':
    unittest.main()
