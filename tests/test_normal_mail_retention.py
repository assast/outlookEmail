import importlib
import json
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

    def _seed_unread_graph_retained_row(self, message_id='mark-read-graph-1'):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at, is_read, list_cached
                )
                VALUES (?, 'inbox', ?, 'graph',
                        'Unread subject', 'sender@example.com',
                        'reader@example.com', '2026-05-27T07:00:00Z', 0, 1)
                ''',
                (self.account['id'], message_id)
            )
            db.commit()

    def _retained_read_state(self, message_id):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            row = db.execute(
                '''
                SELECT is_read, updated_at
                FROM retained_normal_mail_messages
                WHERE account_id = ? AND folder = 'inbox'
                  AND provider_message_id = ? AND id_mode = 'graph'
                ''',
                (self.account['id'], message_id)
            ).fetchone()
        return dict(row)

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

    def test_mark_read_updates_successful_retained_graph_row(self):
        self._seed_unread_graph_retained_row()
        remote_result = {
            'success': True,
            'success_count': 1,
            'failed_count': 0,
            'updated_ids': ['mark-read-graph-1'],
            'errors': [],
        }

        with patch.object(web_outlook_app, 'mark_emails_read_graph_result', return_value=remote_result) as mark_mock:
            response = self.client.post(
                '/api/emails/mark-read',
                json={
                    'email': 'retained@example.com',
                    'method': 'graph',
                    'folder': 'inbox',
                    'items': [{
                        'id': 'mark-read-graph-1',
                        'folder': 'inbox',
                        'id_mode': 'graph',
                    }],
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['updated_ids'], ['mark-read-graph-1'])
        mark_mock.assert_called_once()

        state = self._retained_read_state('mark-read-graph-1')
        self.assertEqual(state['is_read'], 1)
        self.assertIsNotNone(state['updated_at'])

    def test_mark_read_remote_failure_does_not_update_retained_graph_row(self):
        self._seed_unread_graph_retained_row('mark-read-failed-graph-1')
        remote_result = {
            'success': False,
            'success_count': 0,
            'failed_count': 1,
            'updated_ids': [],
            'errors': ['remote failed'],
        }

        with patch.object(web_outlook_app, 'mark_emails_read_graph_result', return_value=remote_result):
            response = self.client.post(
                '/api/emails/mark-read',
                json={
                    'email': 'retained@example.com',
                    'method': 'graph',
                    'folder': 'inbox',
                    'items': [{
                        'id': 'mark-read-failed-graph-1',
                        'folder': 'inbox',
                        'id_mode': 'graph',
                    }],
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], 'remote failed')

        state = self._retained_read_state('mark-read-failed-graph-1')
        self.assertEqual(state['is_read'], 0)

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

    def _seed_graph_detail_retained_row(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at,
                    has_attachments, body_cached
                )
                VALUES (?, 'inbox', 'graph-detail-1', 'graph',
                        'List subject', 'list@example.com',
                        'reader@example.com', '2026-05-26T01:00:00Z', 0, 0)
                ''',
                (self.account['id'],)
            )
            db.commit()

    def _seed_cached_detail_retained_row(self):
        attachments = [{
            'id': 'cached-att-1',
            'name': 'cached.txt',
            'content_type': 'text/plain',
            'size': 42,
            'is_inline': False,
            'content_id': '',
        }]
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, cc, received_at,
                    has_attachments, body, body_type, attachments_json,
                    body_cached, body_cached_at
                )
                VALUES (?, 'inbox', 'cached-detail-1', 'graph',
                        'Cached subject', 'cached-sender@example.com',
                        'reader@example.com', 'copy@example.com',
                        '2026-05-27T08:00:00Z', 1,
                        '<p>Cached body</p>', 'html', ?, 1, CURRENT_TIMESTAMP)
                ''',
                (self.account['id'], json.dumps(attachments))
            )
            db.commit()
        return attachments

    def _graph_detail_payload(self):
        return {
            'id': 'graph-detail-1',
            'subject': 'Detail subject',
            'from': {'emailAddress': {'address': 'sender@example.com'}},
            'toRecipients': [{'emailAddress': {'address': 'reader@example.com'}}],
            'ccRecipients': [{'emailAddress': {'address': 'copy@example.com'}}],
            'receivedDateTime': '2026-05-27T05:00:00Z',
            'hasAttachments': True,
            'body': {'contentType': 'html', 'content': '<p>Persist me</p>'},
        }

    def _graph_attachment_payload(self):
        return [{
            'id': 'att-1',
            'name': 'report.pdf',
            'content_type': 'application/pdf',
            'size': 1234,
            'is_inline': False,
            'content_id': '',
        }]

    def _retained_detail_rows(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = db.execute(
                '''
                SELECT folder, provider_message_id, id_mode, subject, sender,
                       recipients, cc, received_at, body, body_type,
                       attachments_json, has_attachments, body_cached,
                       body_cached_at, last_synced_at, updated_at
                FROM retained_normal_mail_messages
                WHERE account_id = ?
                ''',
                (self.account['id'],)
            ).fetchall()
        return [dict(row) for row in rows]

    def _assert_graph_detail_retained(self, row, attachments):
        self.assertEqual(row['folder'], 'inbox')
        self.assertEqual(row['provider_message_id'], 'graph-detail-1')
        self.assertEqual(row['id_mode'], 'graph')
        self.assertEqual(row['subject'], 'Detail subject')
        self.assertEqual(row['sender'], 'sender@example.com')
        self.assertEqual(row['recipients'], 'reader@example.com')
        self.assertEqual(row['cc'], 'copy@example.com')
        self.assertEqual(row['received_at'], '2026-05-27T05:00:00Z')
        self.assertEqual(row['body'], '<p>Persist me</p>')
        self.assertEqual(row['body_type'], 'html')
        self.assertEqual(row['has_attachments'], 1)
        self.assertEqual(row['body_cached'], 1)
        self.assertIsNotNone(row['body_cached_at'])
        self.assertIsNotNone(row['last_synced_at'])
        self.assertIsNotNone(row['updated_at'])
        self.assertEqual(json.loads(row['attachments_json']), attachments)

    def test_get_email_detail_persists_successful_graph_body(self):
        self._seed_graph_detail_retained_row()
        graph_detail = self._graph_detail_payload()
        attachments = self._graph_attachment_payload()

        with patch.object(web_outlook_app, 'get_email_detail_graph', return_value=graph_detail) as detail_mock, \
             patch.object(web_outlook_app, 'get_email_attachments_graph', return_value=attachments) as attachments_mock:
            response = self.client.get(
                '/api/email/retained@example.com/graph-detail-1?method=graph&folder=inbox&id_mode=graph'
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['email']['subject'], 'Detail subject')
        self.assertEqual(payload['email']['body'], '<p>Persist me</p>')
        detail_mock.assert_called_once()
        attachments_mock.assert_called_once()

        rows = self._retained_detail_rows()
        self.assertEqual(len(rows), 1)
        self._assert_graph_detail_retained(rows[0], attachments)

    def test_prefer_local_detail_falls_back_and_fills_missing_body(self):
        self._seed_graph_detail_retained_row()
        graph_detail = self._graph_detail_payload()
        attachments = self._graph_attachment_payload()

        with patch.object(web_outlook_app, 'get_email_detail_graph', return_value=graph_detail) as detail_mock, \
             patch.object(web_outlook_app, 'get_email_attachments_graph', return_value=attachments) as attachments_mock:
            response = self.client.get(
                '/api/email/retained@example.com/graph-detail-1'
                '?prefer_local=1&method=graph&folder=inbox&id_mode=graph'
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['email']['subject'], 'Detail subject')
        self.assertEqual(payload['email']['body'], '<p>Persist me</p>')
        self.assertNotEqual(payload.get('source'), 'local_retention')
        self.assertFalse(payload.get('local_retention', False))
        detail_mock.assert_called_once()
        attachments_mock.assert_called_once()

        rows = self._retained_detail_rows()
        self.assertEqual(len(rows), 1)
        self._assert_graph_detail_retained(rows[0], attachments)

    def test_get_email_detail_returns_cached_body_without_remote_fetch(self):
        attachments = self._seed_cached_detail_retained_row()

        with patch.object(web_outlook_app, 'get_email_detail_graph') as graph_mock, \
             patch.object(web_outlook_app, 'get_email_detail_imap') as oauth_imap_mock, \
             patch.object(web_outlook_app, 'get_email_detail_imap_generic_result') as generic_imap_mock:
            graph_mock.side_effect = AssertionError('Graph detail helper should not be called')
            oauth_imap_mock.side_effect = AssertionError('OAuth IMAP detail helper should not be called')
            generic_imap_mock.side_effect = AssertionError('Generic IMAP detail helper should not be called')
            response = self.client.get(
                '/api/email/retained@example.com/cached-detail-1'
                '?prefer_local=1&folder=inbox&id_mode=graph'
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['source'], 'local_retention')
        self.assertTrue(payload['local_retention'])
        self.assertEqual(payload['request_method'], 'local')
        self.assertEqual(payload['method'], 'Local Retention')
        self.assertEqual(payload['email']['id'], 'cached-detail-1')
        self.assertEqual(payload['email']['subject'], 'Cached subject')
        self.assertEqual(payload['email']['from'], 'cached-sender@example.com')
        self.assertEqual(payload['email']['to'], 'reader@example.com')
        self.assertEqual(payload['email']['cc'], 'copy@example.com')
        self.assertEqual(payload['email']['body'], '<p>Cached body</p>')
        self.assertEqual(payload['email']['body_type'], 'html')
        self.assertEqual(payload['email']['attachments'], attachments)
        self.assertTrue(payload['email']['has_attachments'])
        graph_mock.assert_not_called()
        oauth_imap_mock.assert_not_called()
        generic_imap_mock.assert_not_called()

    def test_retain_bodies_api_fetches_and_persists_uncached_graph_bodies(self):
        items = [
            {'id': 'retain-body-1', 'folder': 'inbox', 'id_mode': 'graph', 'method': 'graph'},
            {'id': 'retain-body-2', 'folder': 'inbox', 'id_mode': 'graph', 'method': 'graph'},
        ]
        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'inbox', items)

        def graph_detail(client_id, refresh_token, message_id, proxy_url, fallback_proxy_urls):
            return {
                'id': message_id,
                'subject': f'Detail {message_id}',
                'from': {'emailAddress': {'address': f'{message_id}@example.com'}},
                'toRecipients': [{'emailAddress': {'address': 'reader@example.com'}}],
                'ccRecipients': [],
                'receivedDateTime': '2026-05-27T05:00:00Z',
                'hasAttachments': False,
                'body': {'contentType': 'html', 'content': f'<p>Body {message_id}</p>'},
            }

        with patch.object(web_outlook_app, 'get_email_detail_graph', side_effect=graph_detail) as detail_mock, \
             patch.object(web_outlook_app, 'get_email_attachments_graph', return_value=[]) as attachments_mock:
            response = self.client.post(
                '/api/emails/retain-bodies',
                json={
                    'email': 'retained@example.com',
                    'folder': 'inbox',
                    'items': items,
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['cached_count'], 2)
        self.assertEqual(payload['skipped_count'], 0)
        self.assertEqual(payload['failed_count'], 0)
        self.assertEqual(detail_mock.call_count, 2)
        attachments_mock.assert_not_called()

        rows = sorted(self._retained_detail_rows(), key=lambda row: row['provider_message_id'])
        self.assertEqual([row['provider_message_id'] for row in rows], ['retain-body-1', 'retain-body-2'])
        self.assertEqual([row['body_cached'] for row in rows], [1, 1])
        self.assertEqual(rows[0]['body'], '<p>Body retain-body-1</p>')
        self.assertEqual(rows[1]['body'], '<p>Body retain-body-2</p>')


if __name__ == '__main__':
    unittest.main()
