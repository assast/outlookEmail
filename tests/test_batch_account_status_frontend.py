import json
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def run_frontend(scenario):
    script = r'''
const fs = require('fs');
const vm = require('vm');
const events = [];
const elements = new Map();
const accounts = [{id: 1, email: 'active@example.com', status: 'active'},
                  {id: 2, email: 'inactive@example.com', status: 'inactive'}];
const checkboxes = accounts.map(account => ({value: String(account.id), dataset: {}, checked: true}));
const sandbox = {
    events, console, Set, Map, URLSearchParams,
    document: {
        addEventListener() {},
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, {
                dataset: {}, style: {}, disabled: false, textContent: '',
                classList: {toggle() {}, remove() {}},
            });
            return elements.get(id);
        },
        querySelectorAll(selector) { return selector.includes('account-select-checkbox') ? checkboxes : []; },
    },
    currentAccountListSource: accounts,
    currentAccountSummary: {id: 1, status: 'active'},
    isTempEmailGroup: false,
    showConfirmModal: async () => true,
    showToast: (...args) => events.push(['toast', ...args]),
    handleApiError: (...args) => events.push(['error', ...args]),
    updateGraphSendMailAvailability: () => events.push(['sendAvailability']),
    invalidateAccountCaches: () => events.push(['invalidate']),
    loadGroups: async () => events.push(['groups']),
    refreshVisibleAccountList: async () => events.push(['mainList']),
    fetch: async (url, options) => {
        events.push(['request', url, JSON.parse(options.body)]);
        return {ok: true, json: async () => ({success: true, updated_count: 1,
            updated_accounts: [{id: 1, email: 'active@example.com'}]})};
    },
};
vm.createContext(sandbox);
for (const file of ['08-refresh.js', '10-batch-actions.js']) {
    vm.runInContext(fs.readFileSync('static/js/index/' + file, 'utf8'), sandbox);
}
vm.runInContext(`
    clearAccountSelection = () => events.push(['clearMain']);
    updateBatchActionBar = () => {
        events.push(['mainControls']);
        syncAccountStatusBatchControls(getMainAccountBatchSelectionContext());
    };
    clearRefreshSelection = () => events.push(['clearRefresh']);
    syncRefreshBatchControls = () => {
        events.push(['refreshControls']);
        syncAccountStatusBatchControls(getRefreshAccountBatchContext(), refreshModalState.isRunning);
    };
    reloadRefreshWorkbenchData = async () => events.push(['reloadRefresh']);
    loadRefreshStats = async () => events.push(['stats']);
`, sandbox);
(async () => {
    const result = await vm.runInContext(SCENARIO, sandbox);
    console.log(JSON.stringify(result));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('SCENARIO', json.dumps(scenario))
    result = subprocess.run(['node', '-e', script], cwd=ROOT_DIR, text=True,
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_main_batch_status_disables_and_restores_with_shared_request_and_updates_view():
    result = run_frontend('''(async () => {
        await updateStatusForSelectedAccounts('inactive');
        const status = currentAccountSummary.status;
        await updateStatusForSelectedAccounts('active');
        return {events, status};
    })()''')
    requests = [event for event in result['events'] if event[0] == 'request']
    assert requests == [
        ['request', '/api/accounts/batch-update-status', {'account_ids': [1, 2], 'status': 'inactive'}],
        ['request', '/api/accounts/batch-update-status', {'account_ids': [1, 2], 'status': 'active'}],
    ]
    assert result['status'] == 'inactive'
    for event in ['invalidate', 'groups', 'clearMain', 'mainList', 'stats', 'sendAvailability']:
        assert [event] in result['events']


def test_refresh_batch_status_uses_refresh_selection_and_reloads_workbench():
    result = run_frontend('''(async () => {
        refreshModalState.items = [{id: 3, email: 'failed@example.com', status: 'active'}];
        refreshModalState.selectedAccountIds = new Set([3]);
        await disableSelectedRefreshAccounts();
        return events;
    })()''')
    assert ['request', '/api/accounts/batch-update-status',
            {'account_ids': [3], 'status': 'inactive'}] in result
    assert ['clearRefresh'] in result
    assert ['reloadRefresh'] in result
    assert ['clearMain'] not in result


def test_batch_status_controls_filter_eligible_accounts_and_hide_for_temp_mail():
    result = run_frontend('''(() => {
        const context = getMainAccountBatchSelectionContext();
        syncAccountStatusBatchControls(context);
        const enabled = [context.buttons.enableAccounts.disabled, context.buttons.disableAccounts.disabled];
        context.selectedAccounts = context.selectedAccounts.filter(account => account.status === 'inactive');
        syncAccountStatusBatchControls(context);
        const inactive = [context.buttons.enableAccounts.disabled, context.buttons.disableAccounts.disabled];
        context.isTempContext = true;
        syncAccountStatusBatchControls(context);
        const hidden = context.buttons.disableAccounts.style.display;
        return {enabled, inactive, hidden};
    })()''')
    assert result == {'enabled': [False, False], 'inactive': [False, True], 'hidden': 'none'}


def test_batch_status_cancel_failure_and_running_refresh_keep_selection():
    result = run_frontend('''(async () => {
        showConfirmModal = async () => false;
        await updateStatusForSelectedAccounts('inactive');
        const canceled = events.length;
        showConfirmModal = async () => true;
        fetch = async () => ({ok: false, json: async () => ({success: false, error: 'failed'})});
        await updateStatusForSelectedAccounts('inactive');
        refreshModalState.isRunning = true;
        await disableSelectedRefreshAccounts();
        return {events, canceled, loading: document.getElementById('batchDisableAccountsBtn').dataset.loading};
    })()''')
    assert result['canceled'] == 0
    assert result['loading'] == 'false'
    assert any(event[0] == 'error' for event in result['events'])
    assert not any(event[0] in ['request', 'clearMain', 'clearRefresh', 'reloadRefresh'] for event in result['events'])
