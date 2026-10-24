"""Forwarding must not hold SQLite write transactions across network calls."""

import importlib
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch


# The assembled module initializes its database and scheduler at import time.
# Isolate that initialization too, even when DATABASE_PATH is set externally.
_import_directory = tempfile.TemporaryDirectory(prefix='outlookEmail-transactions-import-')
with patch.dict(os.environ, {
    'SECRET_KEY': os.environ.get('SECRET_KEY', 'test-secret-key'),
    'DATABASE_PATH': os.path.join(_import_directory.name, 'import.db'),
    'WERKZEUG_RUN_MAIN': 'false',
}):
    web_outlook_app = importlib.import_module('web_outlook_app')


class ForwardingTransactionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='outlookEmail-transactions-')
        self.addCleanup(directory.cleanup)
        self.database = os.path.join(directory.name, 'test.db')
        self.start_patch('DATABASE', self.database)
        config_patch = patch.dict(web_outlook_app.app.config, TESTING=True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        with web_outlook_app.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            cursor = db.execute(
                "INSERT INTO accounts (email, account_type, forward_enabled) VALUES (?, 'imap', 1)",
                ('transactions@example.com',),
            )
            db.commit()
            self.account = dict(db.execute(
                'SELECT * FROM accounts WHERE id = ?', (cursor.lastrowid,),
            ).fetchone())

        # Only the connection factory is replaced: every query, commit and
        # rollback still uses real SQLite, with no long busy-timeout stalls.
        self.start_patch('open_forwarding_db_connection', side_effect=self.connect)
        self.candidates = self.start_patch(
            'fetch_forward_candidates', return_value={'success': True, 'emails': []},
        )
        self.details = self.start_patch(
            'fetch_forward_detail', side_effect=lambda _account, message_id, _folder: self.detail(message_id),
        )
        self.smtp = self.start_patch('send_forward_email', return_value=True)
        self.telegram = self.start_patch('send_forward_telegram', return_value=True)
        self.wecom = self.start_patch('send_forward_wecom', return_value=True)
        self.feishu = self.start_patch('send_forward_feishu', return_value=True)
        self.config = {
            'email_enabled': True, 'telegram_enabled': False, 'wecom_enabled': False,
            'include_junkemail': False, 'keywords': [], 'forward_window_start': None,
        }

    def start_patch(self, name, *args, **kwargs):
        patcher = patch.object(web_outlook_app, name, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def connect(self):
        conn = sqlite3.connect(self.database, timeout=0.01)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def item(message_id):
        return {'id': message_id, 'folder': 'inbox', 'date': '2026-04-15T07:00:00Z'}

    @staticmethod
    def detail(message_id):
        return {'id': message_id, 'subject': 'Transaction test', 'body': 'Synthetic body'}

    def snapshot(self, conn):
        # Read both tables in one independent snapshot, not through the worker.
        conn.execute('BEGIN')
        dedup = [tuple(row) for row in conn.execute(
            'SELECT message_id, channel FROM forward_logs WHERE account_id = ? ORDER BY id',
            (self.account['id'],),
        )]
        audit = [tuple(row) for row in conn.execute(
            'SELECT message_id, channel, status, error_message FROM forwarding_logs '
            'WHERE account_id = ? ORDER BY id', (self.account['id'],),
        )]
        conn.rollback()
        return dedup, audit

    def probe(self):
        """Capture evidence without assertions that worker exception handlers swallow."""
        conn = self.connect()
        try:
            dedup, audit = self.snapshot(conn)
            write_error = None
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('transaction_probe', 'written')",
                )
                conn.commit()
            except sqlite3.OperationalError as exc:
                write_error = str(exc)
                conn.rollback()
            return dedup, audit, write_error
        finally:
            conn.close()

    def assert_probe(self, evidence, dedup, audit):
        self.assertIsNone(evidence[2], f'independent writer blocked: {evidence[2]}')
        self.assertEqual(evidence[0], dedup)
        self.assertEqual(evidence[1], audit)

    def process(self, items=None, **config):
        if items is not None:
            self.candidates.return_value = {'success': True, 'emails': items}
        result = web_outlook_app.process_forwarding_account(self.account, {**self.config, **config})
        # A callback error must never silently turn a regression into a pass.
        self.assertEqual(result['error'], '')
        return result

    def test_failed_folder_audit_committed_before_next_folder_fetch(self):
        evidence = []

        def fetch(_account, _top, folder):
            if folder == 'inbox':
                return {'success': False, 'error': 'synthetic folder failure'}
            evidence.append(self.probe())
            return {'success': True, 'emails': []}

        self.candidates.side_effect = fetch
        result = self.process(include_junkemail=True)
        self.assertTrue(result['had_processing_failure'])
        self.assertEqual(self.candidates.call_count, 2)
        self.assertEqual(len(evidence), 1)
        self.assert_probe(evidence[0], [], [(
            'folder:inbox', 'fetch_candidates', 'failed',
            'inbox 候选邮件拉取失败: synthetic folder failure',
        )])
        self.smtp.assert_not_called()

    def test_failed_detail_audit_committed_before_next_detail_fetch(self):
        evidence = []

        def fetch(_account, message_id, _folder):
            if message_id == 'missing':
                return None
            evidence.append(self.probe())
            return self.detail(message_id)

        self.details.side_effect = fetch
        result = self.process([self.item('missing'), self.item('next')])
        self.assertTrue(result['had_processing_failure'])
        self.assertEqual(self.details.call_count, 2)
        self.assertEqual(len(evidence), 1)
        self.assert_probe(evidence[0], [], [
            ('missing', 'detail', 'failed', '获取邮件详情失败'),
        ])

    def test_success_committed_before_next_channel_and_next_email_network(self):
        evidence = []
        self.telegram.side_effect = lambda *_args: evidence.append(self.probe()) or True

        def fetch(_account, message_id, _folder):
            if message_id == 'second':
                evidence.append(self.probe())
            return self.detail(message_id)

        self.details.side_effect = fetch
        result = self.process([self.item('first'), self.item('second')], telegram_enabled=True)
        self.assertFalse(result['had_processing_failure'])
        self.assertEqual(result['email_success_count'], 2)
        self.assertEqual(result['telegram_success_count'], 2)
        self.assertEqual(len(evidence), 3)
        pairs = [('first', 'email'), ('first', 'telegram'), ('second', 'email')]
        for index, observed in enumerate(evidence, 1):
            with self.subTest(network_boundary=index):
                expected = pairs[:index]
                self.assert_probe(observed, expected, [
                    (message_id, channel, 'success', None) for message_id, channel in expected
                ])

    def test_feishu_network_does_not_hold_writer_and_success_deduplicates(self):
        evidence = []
        self.feishu.side_effect = lambda *_args: evidence.append(self.probe()) or True
        items = [self.item('first'), self.item('second')]
        result = self.process(items, feishu_enabled=True)
        self.assertFalse(result['had_processing_failure'])
        self.assertEqual(result['feishu_success_count'], 2)
        self.assertEqual(len(evidence), 2)
        self.assert_probe(evidence[0], [('first', 'email')], [('first', 'email', 'success', None)])
        pairs = [('first', 'email'), ('first', 'feishu'), ('second', 'email')]
        self.assert_probe(evidence[1], pairs, [(message, channel, 'success', None) for message, channel in pairs])
        result = self.process(items, feishu_enabled=True)
        self.assertEqual(self.feishu.call_count, 2)
        self.assertEqual(result['feishu_success_count'], 0)

    def test_feishu_failure_preserves_cursor_and_other_channel_success_for_retry(self):
        self.feishu.side_effect = ValueError('飞书关键词验证失败')
        result = self.process([self.item('retry')], feishu_enabled=True)
        self.assertTrue(result['had_processing_failure'])
        self.assertFalse(result['cursor_updated'])
        self.assertEqual(result['feishu_success_count'], 0)
        self.assert_probe(self.probe(), [('retry', 'email')], [
            ('retry', 'email', 'success', None), ('retry', 'feishu', 'failed', '飞书关键词验证失败'),
        ])
        self.feishu.side_effect = None
        result = self.process([self.item('retry')], feishu_enabled=True)
        self.assertFalse(result['had_processing_failure'])
        self.assertTrue(result['cursor_updated'])
        self.assertEqual(result['feishu_success_count'], 1)
        self.smtp.assert_called_once()
        self.assertEqual(self.feishu.call_count, 2)

    def test_failed_send_commits_audit_and_releases_writer_before_return(self):
        for outcome in ('false', 'exception'):
            with self.subTest(outcome=outcome):
                conn = self.connect()
                sender = Mock(return_value=False)
                error = 'SMTP 转发返回失败'
                if outcome == 'exception':
                    error = 'synthetic send failure'
                    sender.side_effect = RuntimeError(error)
                result = web_outlook_app.send_forward_channel(
                    conn, self.account, self.detail(outcome), 'email', sender,
                )
                evidence = self.probe()  # worker connection is still open
                active_transaction = conn.in_transaction
                conn.close()
                self.assertEqual((result[0], result[1], result[3]), (False, True, False))
                sender.assert_called_once_with()
                expected = [('false', 'email', 'failed', 'SMTP 转发返回失败')]
                if outcome == 'exception':
                    expected.append(('exception', 'email', 'failed', error))
                self.assert_probe(evidence, [], expected)
                self.assertFalse(active_transaction)

    def test_success_is_visible_to_second_connection_and_deduplicates_without_resend(self):
        first = self.connect()
        second = self.connect()
        sender = Mock(return_value=True)
        sent = web_outlook_app.send_forward_channel(
            first, self.account, self.detail('same'), 'email', sender,
        )
        evidence = self.probe()
        # Probe before retrying so the original code fails promptly, rather than
        # waiting for the second connection to attempt an insert under its lock.
        self.assert_probe(evidence, [('same', 'email')], [('same', 'email', 'success', None)])
        retried = web_outlook_app.send_forward_channel(
            second, self.account, self.detail('same'), 'email', sender,
        )
        self.assertEqual((sent[0], sent[1], sent[3]), (True, False, True))
        self.assertEqual(retried, (True, False, 0.0, False))
        sender.assert_called_once_with()
        self.assert_probe(self.probe(), [('same', 'email')], [('same', 'email', 'success', None)])

    def test_exception_after_dedup_insert_rolls_back_partial_success(self):
        conn = self.connect()
        evidence = []
        real_log = web_outlook_app.log_forwarding_result

        def log_result(*args, **kwargs):
            if args[4] == 'success':
                evidence.append(self.probe())
                raise RuntimeError('synthetic audit failure')
            return real_log(*args, **kwargs)

        with patch.object(web_outlook_app, 'log_forwarding_result', side_effect=log_result):
            result = web_outlook_app.send_forward_channel(
                conn, self.account, self.detail('partial'), 'email', Mock(return_value=True),
            )
        # Before the audit, the dedup insert must not already be committed.
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0][:2], ([], []))
        self.assertEqual((result[0], result[1], result[3]), (False, True, False))
        self.assert_probe(self.probe(), [], [
            ('partial', 'email', 'failed', 'synthetic audit failure'),
        ])
        self.assertFalse(conn.in_transaction)

    def test_success_survives_later_account_processing_rollback(self):
        def fetch(_account, message_id, _folder):
            if message_id == 'later':
                raise RuntimeError('synthetic later account failure')
            return self.detail(message_id)

        self.candidates.return_value = {
            'success': True, 'emails': [self.item('sent'), self.item('later')],
        }
        self.details.side_effect = fetch
        result = web_outlook_app.process_forwarding_account(self.account, self.config)
        self.assertTrue(result['had_processing_failure'])
        self.assertEqual(result['error'], 'synthetic later account failure')
        self.assertEqual(result['email_success_count'], 1)
        self.smtp.assert_called_once()
        self.assert_probe(self.probe(), [('sent', 'email')], [('sent', 'email', 'success', None)])
        conn = self.connect()
        self.assertIsNone(conn.execute(
            'SELECT forward_last_checked_at FROM accounts WHERE id = ?', (self.account['id'],),
        ).fetchone()[0])


if __name__ == '__main__':
    unittest.main()
