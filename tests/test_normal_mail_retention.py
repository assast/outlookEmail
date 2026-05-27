import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-retention-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class NormalMailRetentionTests(unittest.TestCase):
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
            added = web_outlook_app.add_account(
                'retained@example.com',
                'password',
                'client-id',
                'refresh-token',
                group_id=1,
                account_type='outlook',
                provider='outlook',
            )
            self.assertTrue(added)
            self.account = web_outlook_app.get_account_by_email('retained@example.com')

    def _remote_list_result(self):
        return {
            'success': True,
            'emails': [
                {
                    'id': 'graph-message-1',
                    'id_mode': 'graph',
                    'subject': 'Graph subject',
                    'from': 'sender@example.com',
                    'to': 'one@example.com, two@example.com',
                    'date': '2026-05-27T04:00:00Z',
                    'is_read': False,
                    'has_attachments': True,
                    'body_preview': 'Graph preview',
                    'folder': 'junkemail',
                },
                {
                    'id': 'uid-200',
                    'id_mode': 'uid',
                    'subject': 'Inbox subject',
                    'sender': 'imap-sender@example.com',
                    'recipients': ['target@example.com'],
                    'received_at': '2026-05-26T03:00:00Z',
                    'is_read': True,
                    'has_attachments': False,
                    'body_preview': 'Inbox preview',
                },
            ],
            'method': 'Graph API / IMAP',
            'has_more': False,
        }

    def _retained_rows_for_account(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = db.execute(
                '''
                SELECT account_id, folder, provider_message_id, id_mode,
                       subject, sender, recipients, received_at,
                       is_read, has_attachments, body_preview,
                       list_cached, list_cached_at, last_synced_at, updated_at
                FROM retained_normal_mail_messages
                WHERE account_id = ?
                ORDER BY provider_message_id
                ''',
                (self.account['id'],)
            ).fetchall()
        return [dict(row) for row in rows]

    def _assert_graph_retained_row(self, row):
        self.assertEqual(row['folder'], 'junkemail')
        self.assertEqual(row['provider_message_id'], 'graph-message-1')
        self.assertEqual(row['id_mode'], 'graph')
        self.assertEqual(row['subject'], 'Graph subject')
        self.assertEqual(row['sender'], 'sender@example.com')
        self.assertEqual(row['recipients'], 'one@example.com, two@example.com')
        self.assertEqual(row['received_at'], '2026-05-27T04:00:00Z')
        self.assertEqual(row['is_read'], 0)
        self.assertEqual(row['has_attachments'], 1)
        self.assertEqual(row['body_preview'], 'Graph preview')
        self.assertEqual(row['list_cached'], 1)
        self.assertIsNotNone(row['list_cached_at'])
        self.assertIsNotNone(row['last_synced_at'])
        self.assertIsNotNone(row['updated_at'])

    def _assert_imap_retained_row(self, row):
        self.assertEqual(row['folder'], 'all')
        self.assertEqual(row['provider_message_id'], 'uid-200')
        self.assertEqual(row['id_mode'], 'uid')
        self.assertEqual(row['subject'], 'Inbox subject')
        self.assertEqual(row['sender'], 'imap-sender@example.com')
        self.assertEqual(row['recipients'], 'target@example.com')
        self.assertEqual(row['received_at'], '2026-05-26T03:00:00Z')
        self.assertEqual(row['is_read'], 1)
        self.assertEqual(row['has_attachments'], 0)
        self.assertEqual(row['body_preview'], 'Inbox preview')
        self.assertEqual(row['list_cached'], 1)

    def test_get_emails_persists_successful_remote_list_rows(self):
        remote_result = self._remote_list_result()

        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=remote_result) as fetch_mock:
            response = self.client.get('/api/emails/retained@example.com?folder=all')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['emails'], remote_result['emails'])
        fetch_mock.assert_called_once()

        rows = self._retained_rows_for_account()
        self.assertEqual(len(rows), 2)
        self._assert_graph_retained_row(rows[0])
        self._assert_imap_retained_row(rows[1])

    def test_get_emails_reports_new_remote_rows_before_retention_upsert(self):
        old_row = {
            'id': 'old-uid-1',
            'id_mode': 'uid',
            'subject': 'Already retained',
            'from': 'old@example.com',
            'to': 'reader@example.com',
            'date': '2026-05-26T02:00:00Z',
            'is_read': True,
            'has_attachments': False,
            'body_preview': 'Old preview',
        }
        new_row = {
            'id': 'new-uid-2',
            'id_mode': 'uid',
            'subject': 'Fresh remote',
            'from': 'new@example.com',
            'to': 'reader@example.com',
            'date': '2026-05-27T02:00:00Z',
            'is_read': False,
            'has_attachments': False,
            'body_preview': 'New preview',
        }
        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(
                self.account, 'inbox', [old_row]
            )

        remote_result = {
            'success': True,
            'emails': [old_row, new_row],
            'method': 'IMAP',
            'has_more': False,
        }
        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=remote_result):
            response = self.client.get(
                '/api/emails/retained@example.com?folder=inbox&skip=0&top=20'
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['new_count'], 1)
        self.assertEqual(
            payload['new_message_ids'],
            [{'id': 'new-uid-2', 'folder': 'inbox', 'id_mode': 'uid'}]
        )

        rows = self._retained_rows_for_account()
        self.assertEqual(len(rows), 2)
        retained_ids = {row['provider_message_id'] for row in rows}
        self.assertEqual(retained_ids, {'old-uid-1', 'new-uid-2'})

    def test_get_emails_can_return_local_retention_list_with_pagination(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = [
                ('inbox', 'inbox-old', 'uid', 'Older inbox', 'old@example.com',
                 'reader@example.com', '2026-05-25T10:00:00Z', 1, 0, 'Old preview'),
                ('junkemail', 'junk-new', 'graph', 'Newest junk', 'junk@example.com',
                 'reader@example.com', '2026-05-27T12:00:00Z', 0, 1, 'Junk preview'),
                ('inbox', 'inbox-mid', 'uid', 'Middle inbox', 'mid@example.com',
                 'reader@example.com', '2026-05-26T09:00:00Z', 0, 0, 'Middle preview'),
            ]
            db.executemany(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at,
                    is_read, has_attachments, body_preview, list_cached
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ''',
                [(self.account['id'], *row) for row in rows]
            )
            db.commit()

        with patch.object(web_outlook_app, 'fetch_account_emails') as fetch_mock:
            response = self.client.get(
                '/api/emails/retained@example.com?source=local&folder=all&skip=1&top=1'
            )

        self.assertEqual(response.status_code, 200)
        fetch_mock.assert_not_called()
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['method'], 'Local Retention')
        self.assertEqual(payload['source'], 'local_retention')
        self.assertEqual(payload['request_method'], 'local')
        self.assertTrue(payload['local_retention'])
        self.assertNotIn('new_count', payload)
        self.assertNotIn('new_message_ids', payload)
        self.assertEqual(payload['count'], 3)
        self.assertTrue(payload['has_more'])
        self.assertEqual(len(payload['emails']), 1)

        item = payload['emails'][0]
        self.assertEqual(item['id'], 'inbox-mid')
        self.assertEqual(item['subject'], 'Middle inbox')
        self.assertEqual(item['from'], 'mid@example.com')
        self.assertEqual(item['to'], 'reader@example.com')
        self.assertEqual(item['date'], '2026-05-26T09:00:00Z')
        self.assertFalse(item['is_read'])
        self.assertFalse(item['has_attachments'])
        self.assertEqual(item['body_preview'], 'Middle preview')
        self.assertEqual(item['folder'], 'inbox')
        self.assertEqual(item['id_mode'], 'uid')

        inbox_response = self.client.get(
            '/api/emails/retained@example.com?source=local&folder=inbox&skip=0&top=5'
        )
        inbox_payload = inbox_response.get_json()
        self.assertEqual(inbox_payload['count'], 2)
        self.assertFalse(inbox_payload['has_more'])
        self.assertEqual(
            [item['id'] for item in inbox_payload['emails']],
            ['inbox-mid', 'inbox-old']
        )


if __name__ == '__main__':
    unittest.main()
