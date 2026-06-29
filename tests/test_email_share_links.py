import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import timedelta
from urllib.parse import urlparse
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-share-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class EmailShareLinkTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM email_share_links')
            db.execute('DELETE FROM accounts')
            db.commit()

    def _insert_account(self, email_addr='shared@example.com'):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', 'client-id', 'refresh-token', 1, '', 'active',
                        'outlook', 'outlook', '', 993, '', 0)
                ''',
                (email_addr,)
            )
            db.commit()
            return int(cursor.lastrowid)

    def _create_share(self, account_id, **payload):
        data = {'account_id': account_id, 'duration_minutes': 60}
        data.update(payload)
        response = self.client.post('/api/email-shares', json=data)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        return body['share']

    def _token_from_share_url(self, share_url):
        return urlparse(share_url).path.rstrip('/').split('/')[-1]

    def test_create_timed_and_never_expiring_shares_and_list_copy_urls(self):
        account_id = self._insert_account()

        timed_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'duration_minutes': 60}
        )
        self.assertEqual(timed_response.status_code, 200)
        timed_share = timed_response.get_json()['share']
        self.assertFalse(timed_share['never_expires'])
        self.assertTrue(timed_share['expires_at'])
        self.assertIn('/share/email/', timed_share['share_url'])

        never_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': True, 'duration_minutes': -1}
        )
        self.assertEqual(never_response.status_code, 200)
        never_share = never_response.get_json()['share']
        self.assertTrue(never_share['never_expires'])
        self.assertIsNone(never_share['expires_at'])
        self.assertIn('/share/email/', never_share['share_url'])

        missing_response = self.client.post(
            '/api/email-shares',
            json={'email': 'missing@example.com', 'duration_minutes': 60}
        )
        self.assertEqual(missing_response.status_code, 404)

        invalid_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'duration_minutes': 0}
        )
        self.assertEqual(invalid_response.status_code, 400)

        list_response = self.client.get('/api/email-shares')
        self.assertEqual(list_response.status_code, 200)
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 2)
        self.assertTrue(all(share['share_url'] for share in shares))

    def test_create_share_strictly_parses_never_expires(self):
        account_id = self._insert_account()

        string_false_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': 'false', 'duration_minutes': 30}
        )
        self.assertEqual(string_false_response.status_code, 200)
        string_false_share = string_false_response.get_json()['share']
        self.assertFalse(string_false_share['never_expires'])
        self.assertTrue(string_false_share['expires_at'])

        invalid_bool_response = self.client.post(
            '/api/email-shares',
            json={'account_id': account_id, 'never_expires': 'maybe', 'duration_minutes': 30}
        )
        self.assertEqual(invalid_bool_response.status_code, 400)

    def test_list_shares_filters_by_positive_account_id_only(self):
        account_id = self._insert_account('shared@example.com')
        other_account_id = self._insert_account('other@example.com')
        self._create_share(account_id)
        self._create_share(other_account_id)

        filtered_response = self.client.get(f'/api/email-shares?account_id={account_id}')
        self.assertEqual(filtered_response.status_code, 200)
        filtered_shares = filtered_response.get_json()['shares']
        self.assertEqual(len(filtered_shares), 1)
        self.assertEqual(filtered_shares[0]['account_id'], account_id)

        zero_response = self.client.get('/api/email-shares?account_id=0')
        self.assertEqual(zero_response.status_code, 400)

        invalid_response = self.client.get('/api/email-shares?account_id=not-a-number')
        self.assertEqual(invalid_response.status_code, 400)

    def test_cancel_expired_never_expiring_and_invalid_token_status(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        cancel_response = self.client.post(f"/api/email-shares/{share['id']}/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.get_json()['share']['status'], 'revoked')

        repeat_cancel_response = self.client.post(f"/api/email-shares/{share['id']}/cancel")
        self.assertEqual(repeat_cancel_response.status_code, 200)
        self.assertEqual(repeat_cancel_response.get_json()['share']['status'], 'revoked')

        revoked_status = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(revoked_status.status_code, 404)
        self.assertEqual(revoked_status.get_json()['status'], 'revoked')

        expired_token = 'expired-token'
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO email_share_links (
                    account_id, token_hash, token_encrypted, expires_at, never_expires
                )
                VALUES (?, ?, ?, '2000-01-01 00:00:00', 0)
                ''',
                (
                    account_id,
                    web_outlook_app.hash_email_share_token(expired_token),
                    web_outlook_app.encrypt_data(expired_token),
                )
            )
            db.commit()

        expired_status = self.client.get(f'/api/share/email/{expired_token}/status')
        self.assertEqual(expired_status.status_code, 404)
        self.assertEqual(expired_status.get_json()['status'], 'expired')

        never_share = self._create_share(account_id, never_expires=True, duration_minutes=-1)
        never_token = self._token_from_share_url(never_share['share_url'])
        never_status = self.client.get(f'/api/share/email/{never_token}/status')
        self.assertEqual(never_status.status_code, 200)
        self.assertTrue(never_status.get_json()['never_expires'])

        invalid_status = self.client.get('/api/share/email/not-a-real-token/status')
        self.assertEqual(invalid_status.status_code, 404)
        self.assertEqual(invalid_status.get_json()['status'], 'invalid')

    def test_anonymous_share_list_and_detail_are_bound_to_shared_account(self):
        account_id = self._insert_account('shared@example.com')
        self._insert_account('other@example.com')
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value={
            'success': True,
            'emails': [{'id': 'msg-1', 'subject': 'Shared Mail', 'folder': 'inbox'}],
            'method': 'Graph API',
            'has_more': False,
        }) as list_mock:
            list_response = self.client.get(f'/api/share/email/{token}/emails?folder=inbox')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()['emails'][0]['subject'], 'Shared Mail')
        self.assertEqual(list_mock.call_args.args[0]['email'], 'shared@example.com')

        forbidden_response = self.client.get(
            f'/api/share/email/{token}/emails?email=other@example.com'
        )
        self.assertEqual(forbidden_response.status_code, 403)

        with patch.object(web_outlook_app, 'fetch_email_detail_for_account', return_value={
            'success': True,
            'email': {'id': 'msg-1', 'subject': 'Detail'}
        }) as detail_mock:
            detail_response = self.client.get(f'/api/share/email/{token}/email/msg-1?folder=inbox')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.get_json()['email']['subject'], 'Detail')
        self.assertEqual(detail_mock.call_args.args[0]['email'], 'shared@example.com')

    def test_anonymous_share_rejects_unlisted_folders(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        with patch.object(web_outlook_app, 'fetch_account_emails') as list_mock:
            deleted_response = self.client.get(f'/api/share/email/{token}/emails?folder=deleteditems')
            all_response = self.client.get(f'/api/share/email/{token}/emails?folder=all')
        self.assertEqual(deleted_response.status_code, 400)
        self.assertEqual(all_response.status_code, 400)
        list_mock.assert_not_called()

        with patch.object(web_outlook_app, 'fetch_email_detail_for_account') as detail_mock:
            detail_response = self.client.get(
                f'/api/share/email/{token}/email/msg-1?folder=deleteditems'
            )
        self.assertEqual(detail_response.status_code, 400)
        detail_mock.assert_not_called()

    def test_share_access_timestamp_is_throttled(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        first_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(first_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            first_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            recent_timestamp = first_row['last_accessed_at']

        second_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(second_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            second_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            self.assertEqual(second_row['last_accessed_at'], recent_timestamp)

            stale_timestamp = (
                web_outlook_app.utc_now_naive()
                - timedelta(seconds=web_outlook_app.EMAIL_SHARE_ACCESS_TOUCH_MIN_SECONDS + 30)
            ).strftime('%Y-%m-%d %H:%M:%S')
            db.execute(
                'UPDATE email_share_links SET last_accessed_at = ? WHERE id = ?',
                (stale_timestamp, share['id'])
            )
            db.commit()

        third_response = self.client.get(f'/api/share/email/{token}/status')
        self.assertEqual(third_response.status_code, 200)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            third_row = db.execute(
                'SELECT last_accessed_at FROM email_share_links WHERE id = ?',
                (share['id'],)
            ).fetchone()
            self.assertNotEqual(third_row['last_accessed_at'], stale_timestamp)

    def test_share_access_does_not_grant_management_or_write_permissions(self):
        account_id = self._insert_account()
        share = self._create_share(account_id)
        token = self._token_from_share_url(share['share_url'])

        anonymous = self.app.test_client()
        management_response = anonymous.get('/api/email-shares')
        self.assertEqual(management_response.status_code, 401)

        write_response = anonymous.post(f'/api/share/email/{token}/emails')
        self.assertEqual(write_response.status_code, 405)

        admin_write_response = anonymous.post('/api/emails/delete', json={
            'email': 'shared@example.com',
            'ids': ['msg-1'],
        })
        self.assertEqual(admin_write_response.status_code, 401)

    def test_delete_and_batch_operations_on_shares(self):
        account_id = self._insert_account()
        share1 = self._create_share(account_id)
        share2 = self._create_share(account_id)
        share3 = self._create_share(account_id)

        # test single delete
        delete_response = self.client.delete(f'/api/email-shares/{share1["id"]}')
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.get_json()['success'])

        # verify deleted
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 2)
        self.assertNotIn(share1['id'], [s['id'] for s in shares])

        # test batch cancel
        batch_cancel_response = self.client.post('/api/email-shares/batch-cancel', json={
            'share_ids': [share2['id'], share3['id']]
        })
        self.assertEqual(batch_cancel_response.status_code, 200)
        self.assertTrue(batch_cancel_response.get_json()['success'])

        # verify cancelled
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        for s in shares:
            if s['id'] in [share2['id'], share3['id']]:
                self.assertEqual(s['status'], 'revoked')

        # test batch delete
        batch_delete_response = self.client.post('/api/email-shares/batch-delete', json={
            'share_ids': [share2['id'], share3['id']]
        })
        self.assertEqual(batch_delete_response.status_code, 200)
        self.assertTrue(batch_delete_response.get_json()['success'])

        # verify deleted
        list_response = self.client.get('/api/email-shares')
        shares = list_response.get_json()['shares']
        self.assertEqual(len(shares), 0)


class EmailShareFrontendContractTests(unittest.TestCase):
    def test_admin_ui_contains_share_entry_points(self):
        layout = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'layout.html').read_text(encoding='utf-8')
        dialogs = pathlib.Path(ROOT_DIR, 'templates', 'partials', 'index', 'dialogs-primary.html').read_text(encoding='utf-8')
        groups_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '02-groups.js').read_text(encoding='utf-8')
        shares_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'index', '11-email-shares.js').read_text(encoding='utf-8')

        self.assertIn('emailShareManagementBtn', layout)
        self.assertIn('createEmailShareModal', dialogs)
        self.assertIn('emailShareManagementModal', dialogs)
        self.assertIn('data-account-action="share"', groups_js)
        self.assertIn('function createEmailShare()', shares_js)
        self.assertIn('function cancelEmailShare', shares_js)

    def test_share_page_contains_read_only_shell(self):
        template = pathlib.Path(ROOT_DIR, 'templates', 'email_share.html').read_text(encoding='utf-8')
        share_js = pathlib.Path(ROOT_DIR, 'static', 'js', 'email-share.js').read_text(encoding='utf-8')
        share_css = pathlib.Path(ROOT_DIR, 'static', 'css', 'email-share.css').read_text(encoding='utf-8')

        self.assertIn('shareEmailList', template)
        self.assertIn('shareEmailDetail', template)
        self.assertIn('/api/share/email/', share_js)
        self.assertIn('.overlay-screen[hidden]', share_css)
        self.assertNotIn("shareStatusAttr !== 'active'", share_js)
        self.assertNotIn('/api/emails/delete', share_js)
        self.assertNotIn('/api/email-shares', share_js)


if __name__ == '__main__':
    unittest.main()
