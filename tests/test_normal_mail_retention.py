import importlib
import json
import os
import sqlite3
import time
import threading
import sys
import tempfile
import unittest

import pytest
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
            if hasattr(web_outlook_app, 'set_normal_mail_retention_clear_status'):
                web_outlook_app.set_normal_mail_retention_clear_status('idle', '普通邮箱本地缓存清理空闲')

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
                       subject, sender, recipients, received_at, received_at_sort,
                       is_read, has_attachments, body_preview,
                       list_cached, list_cached_at, last_synced_at, updated_at
                FROM retained_normal_mail_messages
                WHERE account_id = ?
                ORDER BY provider_message_id
                ''',
                (self.account['id'],)
            ).fetchall()
        return [dict(row) for row in rows]

    def _seed_retention_switch_retained_row(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at, list_cached
                )
                VALUES (?, 'inbox', 'settings-switch-kept-1', 'graph',
                        'Keep cached row', 'sender@example.com',
                        'reader@example.com', '2026-05-27T07:00:00Z', 1)
                ''',
                (self.account['id'],)
            )
            db.commit()

    def _retention_switch_retained_row_exists(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            row = db.execute(
                '''
                SELECT id
                FROM retained_normal_mail_messages
                WHERE account_id = ? AND folder = 'inbox'
                  AND provider_message_id = 'settings-switch-kept-1'
                  AND id_mode = 'graph'
                ''',
                (self.account['id'],)
            ).fetchone()
        return row is not None

    def test_get_settings_fresh_db_returns_default_disabled_retention_switch(self):
        with tempfile.TemporaryDirectory(prefix='outlookEmail-fresh-settings-') as temp_dir:
            fresh_db_path = os.path.join(temp_dir, 'fresh.db')
            with patch.object(web_outlook_app, 'DATABASE', fresh_db_path):
                web_outlook_app.init_db()
                with sqlite3.connect(fresh_db_path) as db:
                    row = db.execute(
                        '''
                        SELECT value FROM settings
                        WHERE key = 'normal_mail_local_retention_enabled'
                        '''
                    ).fetchone()

                response = self.client.get('/api/settings')

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'false')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(
            payload['settings']['normal_mail_local_retention_enabled'],
            'false',
        )

    def test_update_settings_retention_switch_does_not_clear_retained_rows(self):
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))
        self._seed_retention_switch_retained_row()

        response = self.client.put(
            '/api/settings',
            json={'normal_mail_local_retention_enabled': False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        with self.app.app_context():
            saved_value = web_outlook_app.get_setting(
                'normal_mail_local_retention_enabled',
                'true',
            )
        self.assertEqual(saved_value, 'false')
        self.assertTrue(self._retention_switch_retained_row_exists())

    def _seed_retention_status_rows(self):
        db = web_outlook_app.get_db()
        self.assertTrue(web_outlook_app.set_setting(
            'normal_mail_local_retention_enabled',
            'true',
        ))
        added = web_outlook_app.add_account(
            'status-retained@example.com',
            'password',
            'client-id',
            'refresh-token',
            group_id=1,
            account_type='outlook',
            provider='outlook',
        )
        self.assertTrue(added)
        account = web_outlook_app.get_account_by_email('status-retained@example.com')
        self._insert_retention_status_rows(db, account['id'])
        db.commit()

    def _insert_retention_status_rows(self, db, account_id):
        db.executemany(
            '''
            INSERT INTO retained_normal_mail_messages (
                account_id, folder, provider_message_id, id_mode,
                subject, sender, recipients, received_at,
                body_preview, body, body_type, attachments_json,
                list_cached, body_cached, body_cached_at
            )
            VALUES (?, 'inbox', ?, 'graph', ?,
                    'sender@example.com', 'reader@example.com',
                    '2026-05-27T07:00:00Z', ?, ?, 'html', '[]',
                    1, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
            ''',
            [
                (account_id, 'status-with-body', 'Cached status row',
                 'cached preview', '<p>cached body</p>', 1, 1),
                (account_id, 'status-without-body', 'Metadata only status row',
                 'metadata preview', None, 0, 0),
            ]
        )

    def test_retention_status_api_reports_seeded_storage_statistics(self):
        with tempfile.TemporaryDirectory(prefix='outlookEmail-retention-status-') as temp_dir:
            status_db_path = os.path.join(temp_dir, 'status.db')
            with patch.object(web_outlook_app, 'DATABASE', status_db_path):
                web_outlook_app.init_db()
                with self.app.app_context():
                    self._seed_retention_status_rows()

                response = self.client.get('/api/settings/normal-mail-retention/status')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        status = payload['status']
        self.assertTrue(status['enabled'])
        self.assertEqual(status['saved_message_count'], 2)
        self.assertEqual(status['cached_body_count'], 1)
        self.assertIsInstance(status['estimated_retained_bytes'], int)
        self.assertGreaterEqual(status['estimated_retained_bytes'], 0)
        self.assertIsInstance(status['db_file_bytes'], int)
        self.assertGreaterEqual(status['db_file_bytes'], 0)
        self.assertEqual(status['clear_status']['state'], 'idle')
        self.assertIn('message', status['clear_status'])

    def _retained_message_count(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            row = db.execute(
                'SELECT COUNT(*) AS count FROM retained_normal_mail_messages'
            ).fetchone()
        return int(row['count'])

    def _wait_for_clear_status(self, expected_state='succeeded', attempts=20):
        last_status = None
        for _ in range(attempts):
            response = self.client.get('/api/settings/normal-mail-retention/status')
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload['success'])
            last_status = payload['status']['clear_status']
            if last_status['state'] == expected_state:
                return payload['status']
            time.sleep(0.05)
        self.fail(f'clear status did not become {expected_state}: {last_status}')

    def test_clear_retention_cache_api_deletes_rows_without_disabling_switch(self):
        with self.app.app_context():
            self._seed_retention_status_rows()

        response = self.client.post('/api/settings/normal-mail-retention/clear')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['status']['state'], 'running')

        status = self._wait_for_clear_status()
        self.assertEqual(status['saved_message_count'], 0)
        self.assertEqual(status['cached_body_count'], 0)
        self.assertEqual(self._retained_message_count(), 0)
        with self.app.app_context():
            saved_value = web_outlook_app.get_setting(
                'normal_mail_local_retention_enabled',
                'false',
            )
        self.assertEqual(saved_value, 'true')

    def test_clear_retention_cache_reports_running_and_rejects_duplicate_job(self):
        original_clear = web_outlook_app.clear_retained_normal_mail_cache_rows
        release_clear = threading.Event()
        clear_started = threading.Event()
        clear_calls = []

        def slow_clear():
            clear_calls.append('called')
            clear_started.set()
            self.assertTrue(release_clear.wait(timeout=2))
            return original_clear()

        with self.app.app_context():
            self._seed_retention_status_rows()

        with patch.object(web_outlook_app, 'clear_retained_normal_mail_cache_rows', side_effect=slow_clear):
            first_response = self.client.post('/api/settings/normal-mail-retention/clear')
            self.assertTrue(clear_started.wait(timeout=2))
            running_status = self.client.get('/api/settings/normal-mail-retention/status')
            second_response = self.client.post('/api/settings/normal-mail-retention/clear')
            release_clear.set()

        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.get_json()
        self.assertTrue(first_payload['success'])
        self.assertFalse(first_payload['already_running'])
        self.assertEqual(first_payload['status']['state'], 'running')
        self.assertTrue(first_payload['status']['message'])

        self.assertEqual(running_status.status_code, 200)
        running_payload = running_status.get_json()
        self.assertEqual(running_payload['status']['clear_status']['state'], 'running')
        self.assertTrue(running_payload['status']['clear_status']['message'])

        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.get_json()
        self.assertTrue(second_payload['success'])
        self.assertTrue(second_payload['already_running'])
        self.assertEqual(second_payload['status']['state'], 'running')
        self.assertTrue(second_payload['status']['message'])
        self.assertEqual(clear_calls, ['called'])

        status = self._wait_for_clear_status()
        self.assertEqual(status['clear_status']['state'], 'succeeded')

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

    def _seed_delete_graph_retained_rows(self):
        rows = [
            ('delete-graph-1', 'Delete me'),
            ('delete-graph-2', 'Keep me'),
        ]
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.executemany(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at, list_cached
                )
                VALUES (?, 'inbox', ?, 'graph', ?,
                        'sender@example.com', 'reader@example.com',
                        '2026-05-27T07:00:00Z', 1)
                ''',
                [(self.account['id'], message_id, subject) for message_id, subject in rows]
            )
            db.commit()

    def _retained_graph_ids(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            rows = db.execute(
                '''
                SELECT provider_message_id
                FROM retained_normal_mail_messages
                WHERE account_id = ? AND folder = 'inbox' AND id_mode = 'graph'
                ORDER BY provider_message_id
                ''',
                (self.account['id'],)
            ).fetchall()
        return [row['provider_message_id'] for row in rows]

    def test_get_emails_persists_successful_remote_list_rows(self):
        remote_result = self._remote_list_result()

        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))
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

    def test_get_emails_disabled_retention_returns_remote_list_without_persisting_rows(self):
        remote_result = self._remote_list_result()

        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'false',
            ))
        with patch.object(web_outlook_app, 'fetch_account_emails', return_value=remote_result) as fetch_mock:
            response = self.client.get('/api/emails/retained@example.com?folder=all')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['emails'], remote_result['emails'])
        self.assertEqual(payload['method'], remote_result['method'])
        self.assertEqual(payload['has_more'], remote_result['has_more'])
        fetch_mock.assert_called_once()

        rows = self._retained_rows_for_account()
        self.assertEqual(rows, [])

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

    def test_delete_emails_removes_successful_retained_graph_row(self):
        self._seed_delete_graph_retained_rows()
        remote_result = {
            'success': True,
            'success_count': 1,
            'failed_count': 0,
            'errors': [],
        }

        with patch.object(web_outlook_app, 'delete_emails_graph', return_value=remote_result) as delete_mock:
            response = self.client.post(
                '/api/emails/delete',
                json={
                    'email': 'retained@example.com',
                    'ids': ['delete-graph-1'],
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        delete_mock.assert_called_once()
        self.assertEqual(self._retained_graph_ids(), ['delete-graph-2'])

    def test_delete_emails_remote_failure_keeps_retained_graph_rows(self):
        self._seed_delete_graph_retained_rows()
        remote_result = {
            'success': False,
            'success_count': 0,
            'failed_count': 1,
            'errors': ['remote failed'],
            'error': 'remote failed',
        }

        with patch.object(web_outlook_app, 'delete_emails_graph', return_value=remote_result), \
             patch.object(web_outlook_app, 'delete_emails_imap', return_value=remote_result):
            response = self.client.post(
                '/api/emails/delete',
                json={
                    'email': 'retained@example.com',
                    'ids': ['delete-graph-1'],
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(self._retained_graph_ids(), ['delete-graph-1', 'delete-graph-2'])

    def test_delete_emails_imap_uses_imap_oauth_token_and_remains_unsupported(self):
        with patch.object(web_outlook_app, 'get_access_token_graph') as graph_token_mock, \
             patch.object(web_outlook_app, 'get_access_token_imap', return_value='imap-token') as imap_token_mock, \
             patch.object(web_outlook_app.imaplib, 'IMAP4_SSL') as imap_mock:
            graph_token_mock.side_effect = AssertionError('Graph token helper should not be used for IMAP delete')
            connection = imap_mock.return_value
            connection.authenticate.return_value = ('OK', [b'Authenticated'])
            connection.select.return_value = ('OK', [b'1'])

            result = web_outlook_app.delete_emails_imap(
                'retained@example.com',
                'client-id',
                'refresh-token',
                ['uid-1'],
                'imap.example.com',
                'socks5://proxy.example:1080',
                ['socks5://fallback.example:1080'],
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'IMAP 删除暂不支持 (ID 格式不兼容)')
        graph_token_mock.assert_not_called()
        imap_token_mock.assert_called_once_with(
            'client-id',
            'refresh-token',
            'socks5://proxy.example:1080',
            ['socks5://fallback.example:1080'],
        )
        imap_mock.assert_called_once_with(
            'imap.example.com',
            web_outlook_app.IMAP_PORT,
            timeout=web_outlook_app.IMAP_TIMEOUT,
        )
        connection.authenticate.assert_called_once()
        connection.select.assert_called_once_with('INBOX')

    def test_retained_action_row_counts_are_cumulative(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            for message_id in ('count-1', 'count-2'):
                self._seed_unread_graph_retained_row(message_id)
            updated_count = web_outlook_app.mark_retained_normal_mail_rows_read(
                self.account,
                [
                    {'id': 'count-1', 'folder': 'inbox', 'id_mode': 'graph'},
                    {'id': 'count-2', 'folder': 'inbox', 'id_mode': 'graph'},
                ],
                {'updated_ids': ['count-1', 'count-2']},
                db=db,
            )
            deleted_count = web_outlook_app.delete_retained_normal_mail_rows(
                self.account,
                ['count-1', 'count-2'],
                {
                    'success': True,
                    'deleted_ids': ['count-1', 'count-2'],
                    'success_count': 2,
                    'failed_count': 0,
                },
                fallback_id_mode='graph',
                db=db,
            )

        self.assertEqual(updated_count, 2)
        self.assertEqual(deleted_count, 2)

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

    def test_local_retention_list_disabled_hides_seeded_rows_until_enabled(self):
        items = [{
            'id': 'disabled-local-row',
            'folder': 'inbox',
            'id_mode': 'graph',
            'subject': 'Hidden local row',
            'from': 'sender@example.com',
            'to': 'reader@example.com',
            'date': '2026-05-27T08:00:00Z',
            'is_read': True,
            'has_attachments': False,
            'body_preview': 'hidden',
        }]
        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'inbox', items)
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'false',
            ))

        disabled_response = self.client.get(
            '/api/emails/retained@example.com?source=local&folder=inbox&skip=0&top=20'
        )

        self.assertEqual(disabled_response.status_code, 200)
        disabled_payload = disabled_response.get_json()
        self.assertTrue(disabled_payload['success'])
        self.assertFalse(disabled_payload['local_retention_enabled'])
        self.assertFalse(disabled_payload['local_retention'])
        self.assertEqual(disabled_payload['emails'], [])
        self.assertEqual(disabled_payload['count'], 0)
        self.assertEqual(disabled_payload['message'], '本地存储未启用')

        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))

        enabled_response = self.client.get(
            '/api/emails/retained@example.com?source=local&folder=inbox&skip=0&top=20'
        )
        enabled_payload = enabled_response.get_json()
        self.assertTrue(enabled_payload['success'])
        self.assertTrue(enabled_payload['local_retention'])
        self.assertEqual([item['id'] for item in enabled_payload['emails']], ['disabled-local-row'])

    def test_get_emails_can_return_local_retention_list_with_pagination(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            items = [
                {
                    'id': 'inbox-old',
                    'folder': 'inbox',
                    'id_mode': 'uid',
                    'subject': 'Older inbox',
                    'from': 'old@example.com',
                    'to': 'reader@example.com',
                    'date': '2026-05-25T10:00:00Z',
                    'is_read': True,
                    'has_attachments': False,
                    'body_preview': 'Old preview',
                },
                {
                    'id': 'junk-new',
                    'folder': 'junkemail',
                    'id_mode': 'graph',
                    'subject': 'Newest junk',
                    'from': 'junk@example.com',
                    'to': 'reader@example.com',
                    'date': '2026-05-27T12:00:00Z',
                    'is_read': False,
                    'has_attachments': True,
                    'body_preview': 'Junk preview',
                },
                {
                    'id': 'inbox-mid',
                    'folder': 'inbox',
                    'id_mode': 'uid',
                    'subject': 'Middle inbox',
                    'from': 'mid@example.com',
                    'to': 'reader@example.com',
                    'date': '2026-05-26T09:00:00Z',
                    'is_read': False,
                    'has_attachments': False,
                    'body_preview': 'Middle preview',
                },
            ]
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'all', items)
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

    def test_local_retention_list_dedupes_mixed_id_modes_for_same_provider_id(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.executemany(
                '''
                INSERT INTO retained_normal_mail_messages (
                    account_id, folder, provider_message_id, id_mode,
                    subject, sender, recipients, received_at,
                    received_at_sort, is_read, list_cached, body_cached
                )
                VALUES (?, 'inbox', 'mixed-provider-1', ?, ?,
                        'sender@example.com', 'reader@example.com',
                        '2026-05-27T09:00:00Z', ?, 1, 1, ?)
                ''',
                [
                    (self.account['id'], 'uid', 'UID retained copy', 100.0, 0),
                    (self.account['id'], 'graph', 'Graph retained copy', 101.0, 1),
                ]
            )
            db.commit()

        with patch.object(web_outlook_app, 'fetch_account_emails') as fetch_mock:
            response = self.client.get(
                '/api/emails/retained@example.com?source=local&folder=inbox&skip=0&top=20'
            )

        self.assertEqual(response.status_code, 200)
        fetch_mock.assert_not_called()
        payload = response.get_json()
        self.assertTrue(payload['success'])
        visible_provider_ids = [item['id'] for item in payload['emails']]
        self.assertEqual(visible_provider_ids.count('mixed-provider-1'), 1)
        self.assertEqual(payload['count'], 1)

    def test_local_retention_list_can_page_beyond_first_twenty_rows(self):
        items = []
        for index in range(25):
            items.append({
                'id': f'bulk-{index:02d}',
                'folder': 'inbox',
                'id_mode': 'uid',
                'subject': f'Bulk {index:02d}',
                'from': 'sender@example.com',
                'to': 'reader@example.com',
                'date': f'2026-05-{27 - (index // 24):02d}T{23 - (index % 24):02d}:00:00Z',
                'is_read': True,
                'has_attachments': False,
                'body_preview': f'preview {index:02d}',
            })

        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'inbox', items)

        with patch.object(web_outlook_app, 'fetch_account_emails') as fetch_mock:
            first_response = self.client.get(
                '/api/emails/retained@example.com?source=local&folder=inbox&skip=0&top=20'
            )
            next_response = self.client.get(
                '/api/emails/retained@example.com?source=local&folder=inbox&skip=20&top=20'
            )

        fetch_mock.assert_not_called()
        first_payload = first_response.get_json()
        next_payload = next_response.get_json()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(next_response.status_code, 200)
        self.assertTrue(first_payload['success'])
        self.assertTrue(first_payload['has_more'])
        self.assertEqual(len(first_payload['emails']), 20)
        self.assertTrue(next_payload['success'])
        self.assertFalse(next_payload['has_more'])
        self.assertEqual(next_payload['count'], 25)
        self.assertEqual(len(next_payload['emails']), 5)
        self.assertEqual([item['id'] for item in next_payload['emails']], [
            'bulk-20', 'bulk-21', 'bulk-22', 'bulk-23', 'bulk-24'
        ])

    def test_local_retention_list_sorts_mixed_date_formats_before_pagination(self):
        items = [
            {
                'id': 'rfc-older',
                'id_mode': 'uid',
                'subject': 'RFC older',
                'from': 'older@example.com',
                'to': 'reader@example.com',
                'date': 'Tue, 26 May 2026 10:00:00 +0000',
                'is_read': True,
                'has_attachments': False,
                'body_preview': 'older',
            },
            {
                'id': 'internal-newer',
                'id_mode': 'uid',
                'subject': 'Internal newer',
                'from': 'newer@example.com',
                'to': 'reader@example.com',
                'date': '27-May-2026 09:00:00 +0000',
                'is_read': True,
                'has_attachments': False,
                'body_preview': 'newer',
            },
            {
                'id': 'iso-middle',
                'id_mode': 'graph',
                'subject': 'ISO middle',
                'from': 'middle@example.com',
                'to': 'reader@example.com',
                'date': '2026-05-26T12:00:00Z',
                'is_read': False,
                'has_attachments': False,
                'body_preview': 'middle',
            },
        ]
        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'inbox', items)

        response = self.client.get(
            '/api/emails/retained@example.com?source=local&folder=inbox&skip=1&top=1'
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['count'], 3)
        self.assertTrue(payload['has_more'])
        self.assertEqual([item['id'] for item in payload['emails']], ['iso-middle'])

    def test_local_retention_keyword_search_checks_cached_body(self):
        with self.app.app_context():
            web_outlook_app.upsert_retained_normal_mail_list_items(
                self.account,
                'inbox',
                [{
                    'id': 'body-keyword-1',
                    'id_mode': 'graph',
                    'subject': 'Routine subject',
                    'from': 'sender@example.com',
                    'to': 'reader@example.com',
                    'date': '2026-05-27T08:00:00Z',
                    'is_read': True,
                    'has_attachments': False,
                    'body_preview': 'No target here',
                }]
            )
            web_outlook_app.upsert_retained_normal_mail_detail(
                self.account,
                'inbox',
                'body-keyword-1',
                {
                    'id': 'body-keyword-1',
                    'subject': 'Routine subject',
                    'from': 'sender@example.com',
                    'to': 'reader@example.com',
                    'date': '2026-05-27T08:00:00Z',
                    'body': '<p>Cached SecretNeedle body</p>',
                    'body_type': 'html',
                    'attachments': [],
                },
                'graph',
                'graph',
                'graph',
            )

        response = self.client.get(
            '/api/emails/retained@example.com?source=local&folder=inbox&keyword=secretneedle'
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual([item['id'] for item in payload['emails']], ['body-keyword-1'])

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

    def test_get_email_detail_disabled_retention_returns_detail_without_caching_body(self):
        self._seed_graph_detail_retained_row()
        graph_detail = self._graph_detail_payload()
        attachments = self._graph_attachment_payload()
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'false',
            ))

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
        self.assertEqual(rows[0]['provider_message_id'], 'graph-detail-1')
        self.assertEqual(rows[0]['body_cached'], 0)
        self.assertIsNone(rows[0]['body'])

    def test_get_email_detail_persists_successful_graph_body(self):
        self._seed_graph_detail_retained_row()
        graph_detail = self._graph_detail_payload()
        attachments = self._graph_attachment_payload()
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))

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

    def test_prefer_local_detail_disabled_does_not_return_cached_body(self):
        self._seed_cached_detail_retained_row()
        graph_detail = self._graph_detail_payload()
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'false',
            ))

        with patch.object(web_outlook_app, 'get_email_detail_graph', return_value=graph_detail) as detail_mock, \
             patch.object(web_outlook_app, 'get_email_attachments_graph', return_value=[]) as attachments_mock:
            response = self.client.get(
                '/api/email/retained@example.com/cached-detail-1'
                '?prefer_local=1&method=graph&folder=inbox&id_mode=graph'
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertNotEqual(payload.get('source'), 'local_retention')
        self.assertFalse(payload.get('local_retention', False))
        self.assertEqual(payload['email']['body'], '<p>Persist me</p>')
        detail_mock.assert_called_once()
        attachments_mock.assert_called_once()

    def test_get_email_detail_returns_cached_body_without_remote_fetch(self):
        attachments = self._seed_cached_detail_retained_row()
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))

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

    def test_retain_bodies_api_rejects_disabled_retention_without_fetching_detail(self):
        items = [
            {'id': 'retain-disabled-1', 'folder': 'inbox', 'id_mode': 'graph', 'method': 'graph'},
        ]
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'false',
            ))
            web_outlook_app.upsert_retained_normal_mail_list_items(self.account, 'inbox', items)

        with patch.object(web_outlook_app, 'get_email_detail_graph') as detail_mock, \
             patch.object(web_outlook_app, 'get_email_attachments_graph') as attachments_mock:
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
        self.assertFalse(payload['success'])
        self.assertFalse(payload['local_retention_enabled'])
        self.assertIn('本地保留未启用', payload['error'])
        detail_mock.assert_not_called()
        attachments_mock.assert_not_called()

        rows = self._retained_detail_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['provider_message_id'], 'retain-disabled-1')
        self.assertEqual(rows[0]['body_cached'], 0)

    def test_retain_bodies_api_fetches_and_persists_uncached_graph_bodies(self):
        items = [
            {'id': 'retain-body-1', 'folder': 'inbox', 'id_mode': 'graph', 'method': 'graph'},
            {'id': 'retain-body-2', 'folder': 'inbox', 'id_mode': 'graph', 'method': 'graph'},
        ]
        with self.app.app_context():
            self.assertTrue(web_outlook_app.set_setting(
                'normal_mail_local_retention_enabled',
                'true',
            ))
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
