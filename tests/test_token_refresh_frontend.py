import unittest

from tests.test_batch_account_status_frontend import run_frontend


class TokenRefreshFrontendTests(unittest.TestCase):
    def test_single_retry_shows_each_success_message(self):
        result = run_frontend('''(async () => {
            renderRefreshAccountList = () => {};
            renderRefreshRuntimeLogs = () => {};
            for (const token_rotated of [true, false]) {
                const message = token_rotated ? '刷新成功，Token 已更新' : '验证成功，Token 未轮换，继续使用原 Token';
                fetch = async () => ({json: async () => ({success: true, token_rotated, message})});
                await retrySingleAccount(1, 'user@example.com');
            }
            return {events, logs: refreshModalState.runtimeLogs};
        })()''')
        toasts = [event[1] for event in result['events'] if event[0] == 'toast']
        self.assertEqual(toasts, [
            'user@example.com 刷新成功，Token 已更新',
            'user@example.com 验证成功，Token 未轮换，继续使用原 Token',
        ])
        self.assertIn('Token 未轮换', result['logs'][0]['title'])

    def test_stream_displays_success_message_and_updates_rotation(self):
        result = run_frontend('''(async () => {
            beginRefreshTaskRuntime = () => { refreshModalState.runtimeLogs = []; };
            renderRefreshAccountList = () => {};
            renderRefreshRuntimeLogs = () => {};
            setRefreshSnapshotCounts = () => {};
            EventSource = class { close() {} };
            refreshModalState.items = [{id: 1}, {id: 2}];
            await startRefreshEventStream('/mock-stream');
            for (const [account_id, token_rotated] of [[1, true], [2, false]]) {
                const message = token_rotated ? '刷新成功，Token 已更新' : '验证成功，Token 未轮换，继续使用原 Token';
                await refreshModalState.eventSource.onmessage({data: JSON.stringify({
                    type: 'account_result', account_id, email: 'user@example.com',
                    status: 'success', token_rotated, message, total: 2, success_count: account_id,
                })});
            }
            return {items: refreshModalState.items, logs: refreshModalState.runtimeLogs};
        })()''')
        self.assertIs(result['items'][0]['last_refresh_token_rotated'], True)
        self.assertIs(result['items'][1]['last_refresh_token_rotated'], False)
        self.assertIn('Token 未轮换', result['logs'][0]['title'])
        self.assertIn('Token 已更新', result['logs'][1]['title'])

    def test_account_list_distinguishes_persisted_and_unknown_rotation(self):
        html = run_frontend('''(() => {
            escapeHtml = value => String(value ?? '');
            formatDateTime = value => value;
            syncRefreshPaginationControls = () => {};
            refreshModalState.items = [true, false, null].map((rotated, index) => ({
                id: index + 1, email: `user${index}@example.com`, last_refresh_status: 'success',
                last_refresh_token_rotated: rotated,
            }));
            renderRefreshAccountList(refreshModalState.items, 3);
            return document.getElementById('refreshAccountList').innerHTML;
        })()''')
        self.assertIn('Token 已更新', html)
        self.assertIn('Token 未轮换', html)
        self.assertIn('轮换结果未记录', html)

    def test_batch_refresh_toast_includes_rotation_counts(self):
        events = run_frontend('''(async () => {
            fetch = async () => ({json: async () => ({
                success: true, success_count: 2, failed_count: 0, skipped_count: 0,
                rotated_count: 1, unrotated_count: 1,
            })});
            await refreshSelectedAccounts();
            return events;
        })()''')
        self.assertIn(['toast', '批量刷新完成：成功 2（Token 已更新 1，未轮换 1），失败 0，跳过 0', 'success'], events)

    def test_account_list_displays_last_success_and_rotation_times(self):
        html = run_frontend('''(() => {
            escapeHtml = value => String(value ?? '');
            formatDateTime = value => `formatted:${value}`;
            syncRefreshPaginationControls = () => {};
            refreshModalState.items = [{
                id: 1, email: 'user@example.com', last_refresh_status: 'success',
                last_refresh_token_rotated: false,
                last_refresh_at: '2026-10-21 03:00:00',
                last_refresh_success_at: '2026-10-21 03:00:00',
                refresh_token_updated_at: '2026-10-01 03:00:00',
            }, {id: 2, email: 'never@example.com', last_refresh_status: 'never'}];
            renderRefreshAccountList(refreshModalState.items, 2);
            return document.getElementById('refreshAccountList').innerHTML;
        })()''')
        self.assertIn('<th>最近成功刷新</th>', html)
        self.assertIn('<th>最近轮换</th>', html)
        self.assertEqual(html.count('formatted:2026-10-21 03:00:00'), 2)
        self.assertIn('formatted:2026-10-01 03:00:00', html)

    def test_stream_uses_server_times_and_preserves_them_on_failure(self):
        result = run_frontend('''(() => {
            refreshModalState.items = [{id: 1}];
            applyRefreshResultToListItem({
                account_id: 1, status: 'success', token_rotated: true,
                last_refresh_at: '2026-10-01 03:00:00',
                last_refresh_success_at: '2026-10-01 03:00:00',
                refresh_token_updated_at: '2026-10-01 03:00:00',
            });
            applyRefreshResultToListItem({
                account_id: 1, status: 'success', token_rotated: false,
                last_refresh_at: '2026-10-21 03:00:00',
                last_refresh_success_at: '2026-10-21 03:00:00',
                refresh_token_updated_at: '2026-10-01 03:00:00',
            });
            applyRefreshResultToListItem({
                account_id: 1, status: 'failed', error_message: 'refresh failed',
                last_refresh_at: '2026-10-22 03:00:00',
            });
            return refreshModalState.items[0];
        })()''')
        self.assertEqual(result['last_refresh_at'], '2026-10-22 03:00:00')
        self.assertEqual(result['last_refresh_success_at'], '2026-10-21 03:00:00')
        self.assertEqual(result['refresh_token_updated_at'], '2026-10-01 03:00:00')
