"""Named notifications keep drafts, scope identity and external text safe."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_frontend(scenario):
    script = r'''
const fs = require('fs'), vm = require('vm');
const elements = new Map(), requests = [], toasts = [];
function node(tag = 'div') {
    return {tag, value: '', checked: false, disabled: false, hidden: false, textContent: '',
        innerHTML: '', dataset: {}, style: {}, children: [],
        set id(value) {this._id = value; elements.set(value, this);}, get id() {return this._id;},
        get selectedOptions() {return this.selection || (this.options.length ? this.options.filter(o=>o.selected) : (this.value ? [{value:this.value}] : []));},
        set selectedOptions(value) {this.selection = value;}, options: [],
        append(...items) {this.children.push(...items);}, replaceChildren() {this.children = [];},
        setAttribute() {}, addEventListener() {}, closest() {return this;}};
}
function element(id) {if (!elements.has(id)) {const n = node(); n.id = id;} return elements.get(id);}
const sandbox = {console, Set, Map, Date, JSON, Number, String, Object, Array, URLSearchParams,
    requests, toasts, element, fail: false, historyRows: [], previewResult: {}, policyResults: [], confirmResult:true,
    document: {getElementById: element, createElement: node, createTextNode: text => ({textContent: text}),
        addEventListener() {}, querySelector: () => node(), querySelectorAll: () => []},
    escapeHtml: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    showToast: (...args) => toasts.push(args), formatDateTime: value => value,
    showConfirmModal: async () => sandbox.confirmResult,
    fetch: async (url, options = {}) => {
        requests.push({url, body: options.body && JSON.parse(options.body), method: options.method});
        return {json: async () => sandbox.fail ? {success: false, error: '模拟失败'} :
            url.startsWith('/api/forwarding/preview') ? {success: true, preview: sandbox.previewResult} :
            url.startsWith('/api/forwarding/history') ? {success: true, history: sandbox.historyRows, scans: []} : {success: true, message: '测试已发送'}};
    }};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/index/15-forwarding.js', 'utf8'), sandbox);
(async () => {console.log(JSON.stringify(await vm.runInContext(SCENARIO, sandbox)));})()
    .catch(error => {console.error(error); process.exitCode = 1;});
'''.replace('SCENARIO', json.dumps(scenario))
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_edit_secret_flags_never_fill_credentials_and_draft_keeps_identity():
    result = run_frontend('''(() => {
        sourceForwardingState.channels = [{id: 7, name: '地址飞书', type: 'feishu', config: {
            webhook_url_configured: true, sign_secret_configured: true}}];
        editNotificationChannel(7);
        return {draft: notificationChannelDraft(), placeholder: element('notificationField_webhook_url').placeholder,
            fixedType: element('notificationChannelType').disabled};
    })()''')
    assert result['draft']['id'] == 7 and result['fixedType']
    assert result['draft']['config'] == {'webhook_url': '', 'sign_secret': '', 'clear_sign_secret': False}
    assert '留空保留' in result['placeholder']


def test_failed_save_restores_button_and_keeps_unsaved_draft():
    result = run_frontend('''(async () => {
        editNotificationChannel();
        element('notificationChannelName').value = '未保存';
        element('notificationField_webhook_url').value = 'draft-webhook';
        fail = true;
        const button = element('save'); await saveNotificationChannel(button);
        return {disabled: button.disabled, hidden: element('notificationChannelEditor').hidden,
            draft: notificationChannelDraft(), toasts};
    })()''')
    assert not result['disabled'] and not result['hidden']
    assert result['draft']['config']['webhook_url'] == 'draft-webhook'
    assert result['toasts'][0][1] == 'error'


def test_test_button_sends_draft_once_and_does_not_save():
    result = run_frontend('''(async () => {
        editNotificationChannel(); element('notificationChannelName').value = '测试';
        element('notificationField_webhook_url').value = 'draft-hook';
        const button = element('test'); await testNotificationChannel(button);
        return {requests, disabled: button.disabled, editorHidden: element('notificationChannelEditor').hidden};
    })()''')
    assert not result['disabled'] and not result['editorHidden']
    assert len(result['requests']) == 1
    assert result['requests'][0]['url'] == '/api/notification-channels/test'
    assert result['requests'][0]['body']['config']['webhook_url'] == 'draft-hook'


def test_address_preview_uses_worker_and_complete_address_and_plain_text():
    result = run_frontend('''(async () => {
        element('forwardPolicyScope').value = 'cloudflare_address'; element('forwardPolicySource').value = '12';
        element('forwardPreviewAddress').value = 'special@example.com';
        element('forwardPreviewWorker').value = '12';
        previewResult = {email_address: 'special@example.com', eligible: true,
            path: [{scope_type: 'cloudflare_address', mode: 'custom'}], channels: [{name: '<img onerror=bad>', enabled: true}]};
        await previewForwardingPolicy(element('preview'));
        return {requests, text: element('forwardPolicyPreview').textContent, html: element('forwardPolicyPreview').innerHTML};
    })()''')
    assert 'worker_id=12' in result['requests'][0]['url']
    assert 'address=special%40example.com' in result['requests'][0]['url']
    assert 'CF 邮箱（指定渠道）' in result['text'] and result['html'] == ''


def test_history_escapes_text_and_keeps_address_and_channel_filters():
    result = run_frontend('''(async () => {
        element('forwardHistoryAddress').value = 'special@example.com'; element('forwardHistoryChannel').value = '7';
        historyRows = [{email_address: '<img src=x>', channel_name: '<script>bad</script>', channel_type: 'feishu',
            source_type: 'cloudflare', source_name: '<worker>', status: 'failed', updated_at: 1, error_message: '<svg onload=bad>'}];
        await loadForwardingHistory(0);
        return {requests, html: element('sourceForwardingHistory').innerHTML, previousDisabled: element('forwardHistoryPrevious').disabled};
    })()''')
    assert 'channel_id=7' in result['requests'][0]['url']
    assert 'email_address=special%40example.com' in result['requests'][0]['url']
    assert '<img' not in result['html'] and '<script>' not in result['html'] and '&lt;svg' in result['html']
    assert result['previousDisabled']


def test_main_settings_omit_legacy_credentials_but_keep_poll_and_filter_options():
    result = run_frontend('''(() => {
        const settings = {forward_channels: ['feishu'], smtp_host: 'old', smtp_provider: 'custom',
            telegram_bot_token: 'old', feishu_webhook_url: 'old', feishu_clear_sign_secret: false,
            forward_keywords: 'normal only', forward_check_interval_seconds: 60, app_timezone: 'Asia/Shanghai'};
        omitLegacyForwardingFields(settings); return settings;
    })()''')
    assert result == {'forward_keywords': 'normal only', 'forward_check_interval_seconds': 60, 'app_timezone': 'Asia/Shanghai'}


def test_dedicated_workspace_omits_forwarding_fields_from_system_settings_save():
    result = run_frontend('''(() => {
        element('forwardingManagementView').dataset.forwardingWorkspace = 'true';
        const settings = {forward_keywords:'draft', forward_check_interval_seconds:60,
            forward_execution_mode:'parallel', forward_channels:['feishu'], app_timezone:'Asia/Shanghai'};
        omitLegacyForwardingFields(settings); return settings;
    })()''')
    assert result == {'app_timezone': 'Asia/Shanghai'}


def test_runtime_settings_save_only_submits_forwarding_fields():
    result = run_frontend('''(async () => {
        element('forwardingRuntimeForm').reportValidity = () => true;
        element('forwardExecutionMode').value = 'parallel';
        element('forwardAccountDelaySeconds').value = '20';
        element('forwardCheckIntervalSeconds').value = '60';
        element('forwardKeywords').value = 'important';
        await saveForwardingRuntimeSettings(element('save'));
        return {requests,status:element('forwardingRuntimeStatus').textContent};
    })()''')
    assert len(result['requests']) == 1
    request = result['requests'][0]
    assert request['url'] == '/api/settings' and request['method'] == 'PUT'
    assert request['body']['forward_account_delay_seconds'] == 0
    assert request['body']['forward_check_interval_seconds'] == 60
    assert all(key.startswith('forward_') for key in request['body'])
    assert result['status'] == '运行设置已保存。'


def test_bulk_save_submits_every_selected_source_once_without_account_switch():
    result = run_frontend('''(async () => {
        element('forwardPolicyScope').value = 'account';
        element('forwardPolicySource').selectedOptions = [{value:'3'},{value:'7'}];
        element('forwardPolicyMode').value = 'custom';
        document.querySelectorAll = () => [{value:'11'}];
        loadSourceForwarding = async () => {};
        await saveForwardingPolicy(element('save'));
        return {requests, disabled: element('save').disabled};
    })()''')
    assert not result['disabled']
    assert len(result['requests']) == 1
    assert result['requests'][0]['method'] == 'POST'
    body = result['requests'][0]['body']
    assert body['scope_ids'] == [3, 7] and body['channel_ids'] == [11]
    assert 'forward_enabled' not in body


def test_source_picker_filters_case_insensitively_and_selects_only_matching_rows():
    result = run_frontend('''(async () => {
        element('forwardPolicyScope').value = 'account';
        const options = [
            {value:'3', textContent:'Alice@Example.com', selected:false},
            {value:'7', textContent:'bob@other.com', selected:true},
            {value:'9', textContent:'Carol@example.com', selected:false}];
        element('forwardPolicySource').options = options;
        element('forwardPolicySourceFilter').value = ' EXAMPLE.COM ';
        loadForwardingPolicy = async () => {};
        renderForwardingSourcePicker();
        const filtered = element('forwardPolicySourceOptions').innerHTML;
        await selectForwardingSources(true);
        return {filtered, selected:options.filter(o=>o.selected).map(o=>o.value),
            status:element('forwardPolicySourceStatus').textContent};
    })()''')
    assert 'Alice@Example.com' in result['filtered'] and 'Carol@example.com' in result['filtered']
    assert 'bob@other.com' not in result['filtered']
    assert result['selected'] == ['3', '7', '9']
    assert '2 / 3' in result['status'] and '已选 3' in result['status']


def test_source_picker_keeps_hidden_selections_and_clears_all_even_under_filter():
    result = run_frontend('''(async () => {
        element('forwardPolicyScope').value = 'group';
        const options = [
            {value:'4', textContent:'工作分组', selected:false},
            {value:'8', textContent:'个人分组', selected:true}];
        element('forwardPolicySource').options = options;
        loadForwardingPolicy = async () => {};
        element('forwardPolicySourceFilter').value = '工作';
        await toggleForwardingSource('4', true);
        element('forwardPolicySourceFilter').value = '不存在';
        renderForwardingSourcePicker();
        const empty = element('forwardPolicySourceOptions').textContent || element('forwardPolicySourceOptions').innerHTML;
        const before = options.filter(o=>o.selected).map(o=>o.value);
        await selectForwardingSources(false);
        return {before, empty, after:options.filter(o=>o.selected).map(o=>o.value)};
    })()''')
    assert result['before'] == ['4', '8']
    assert '没有匹配' in result['empty']
    assert result['after'] == []


def test_source_picker_escapes_labels_for_all_source_types():
    result = run_frontend('''(() => {
        element('forwardPolicyScope').value = 'cloudflare_worker';
        element('forwardPolicySource').options = [{value:'12', textContent:'<img src=x onerror=bad>', selected:true}];
        renderForwardingSourcePicker();
        return {html:element('forwardPolicySourceOptions').innerHTML,
            summary:element('forwardPolicySourceSummary').textContent};
    })()''')
    assert '<img' not in result['html'] and '&lt;img' in result['html']
    assert '已选 1' in result['summary']


def test_source_picker_saves_selections_across_different_searches():
    result = run_frontend('''(async () => {
        element('forwardPolicyScope').value = 'cloudflare_worker';
        element('forwardPolicySource').options = [
            {value:'12', textContent:'Worker A', selected:false},
            {value:'15', textContent:'Worker B', selected:false}];
        loadForwardingPolicy = async () => {};
        loadSourceForwarding = async () => {};
        element('forwardPolicySourceFilter').value = 'A';
        await toggleForwardingSource('12', true);
        element('forwardPolicySourceFilter').value = 'B';
        await selectForwardingSources(true);
        element('forwardPolicyMode').value = 'off';
        await saveForwardingPolicy(element('save'));
        return requests;
    })()''')
    assert len(result) == 1
    assert result[0]['body']['scope_ids'] == [12, 15]


def test_rule_filters_combine_keyword_scope_channel_and_mode():
    result = run_frontend('''(() => {
        sourceForwardingState.channels = [{id:11,name:'工作通知'},{id:12,name:'注册提醒'}];
        sourceForwardingState.accounts = [{id:3,email:'one@example.com'}];
        sourceForwardingState.groups = [{id:4,name:'工作组'}];
        sourceForwardingState.workers = [{id:5,name:'Edge Worker'}];
        sourceForwardingState.policies = [
            {id:101,scope_type:'account',scope_id:3,match_value:'',mode:'custom',channel_ids:[11]},
            {id:102,scope_type:'group',scope_id:4,match_value:'',mode:'custom',channel_ids:[12]},
            {id:103,scope_type:'cloudflare_address',scope_id:5,match_value:'special@example.com',mode:'custom',channel_ids:[11]},
            {id:104,scope_type:'cloudflare_worker',scope_id:5,match_value:'',mode:'off',channel_ids:[]}];
        element('forwardRuleSearch').value = ' EDGE ';
        element('forwardRuleScopeFilter').value = 'cloudflare_address';
        element('forwardRuleChannelFilter').value = '11';
        element('forwardRuleModeFilter').value = 'custom';
        return filteredForwardingPolicies().map(p=>p.id);
    })()''')
    assert result == [103]


def test_rule_selection_only_selects_filtered_rows_and_clears_on_filter_change():
    result = run_frontend('''(() => {
        sourceForwardingState.policies = [
            {id:101,scope_type:'account',scope_id:3,mode:'off',channel_ids:[]},
            {id:102,scope_type:'group',scope_id:4,mode:'off',channel_ids:[]}];
        element('forwardRuleScopeFilter').value = 'account';
        selectForwardingPolicyRows(true);
        const first = Array.from(sourceForwardingState.selectedPolicyIds);
        element('forwardRuleScopeFilter').value = 'group';
        changeForwardingPolicyFilters();
        return {first,after:Array.from(sourceForwardingState.selectedPolicyIds),disabled:element('deleteSelectedForwardingPoliciesBtn').disabled};
    })()''')
    assert result['first'] == [101] and result['after'] == []
    assert result['disabled']


def test_batch_rule_delete_submits_stable_ids_once_and_clears_successful_selection():
    result = run_frontend('''(async () => {
        sourceForwardingState.policies = [
            {id:40,scope_type:'group',scope_id:2,mode:'off',channel_ids:[]},
            {id:18,scope_type:'account',scope_id:1,mode:'off',channel_ids:[]}];
        sourceForwardingState.selectedPolicyIds = new Set([40,18]);
        loadSourceForwarding = async () => {};
        await deleteSelectedForwardingPolicies(element('deleteSelectedForwardingPoliciesBtn'));
        return {requests,selected:Array.from(sourceForwardingState.selectedPolicyIds),disabled:element('deleteSelectedForwardingPoliciesBtn').disabled};
    })()''')
    assert len(result['requests']) == 1
    assert result['requests'][0]['method'] == 'DELETE'
    assert result['requests'][0]['body'] == {'policy_ids': [18, 40]}
    assert result['selected'] == [] and result['disabled']


def test_batch_rule_delete_cancel_and_failure_keep_selection():
    for cancelled in (True, False):
        result = run_frontend('''(async () => {
            sourceForwardingState.policies = [{id:18,scope_type:'account',scope_id:1,mode:'off',channel_ids:[]}];
            sourceForwardingState.selectedPolicyIds = new Set([18]);
            confirmResult = CANCELLED ? false : true;
            fail = true;
            await deleteSelectedForwardingPolicies(element('deleteSelectedForwardingPoliciesBtn'));
            return {requests,selected:Array.from(sourceForwardingState.selectedPolicyIds),disabled:element('deleteSelectedForwardingPoliciesBtn').disabled};
        })()'''.replace('CANCELLED', 'true' if cancelled else 'false'))
        assert len(result['requests']) == (0 if cancelled else 1)
        assert result['selected'] == [18] and not result['disabled']
