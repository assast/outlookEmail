import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_frontend(scenario):
    script = r'''
const fs = require('fs');
const vm = require('vm');
const elements = new Map();
const events = [];
function element(id) {
    if (!elements.has(id)) elements.set(id, {
        value: '', checked: false, disabled: false, hidden: true,
        dataset: {}, style: {}, innerHTML: '', textContent: '发送测试消息',
        classList: {add() {}, remove() {}, toggle() {}},
    });
    return elements.get(id);
}
const ids = {smtp: 'forwardChannelSmtp', telegram: 'forwardChannelTelegram',
    wecom: 'forwardChannelWecom', feishu: 'forwardChannelFeishu'};
const panels = Object.keys(ids).map(channel => ({dataset: {channel}, hidden: true}));
const sandbox = {
    console, events, elements, panels, element, Set, Map, Date, Intl, URL, URLSearchParams,
    setTimeout, clearTimeout,
    document: {
        addEventListener() {}, getElementById: element,
        querySelector: () => ({value: 'days'}),
        querySelectorAll(selector) {
            if (selector.includes('forward-channel-option')) return Object.values(ids).map(id => ({
                querySelector: () => element(id), classList: {toggle() {}},
            }));
            if (selector.includes('forward-channel-panel')) return panels;
            return [];
        },
    },
    showToast: (...args) => events.push(['toast', ...args]),
    handleApiError: (...args) => events.push(['error', ...args]),
    escapeHtml: value => String(value ?? '').replace(/</g, '&lt;'),
    formatDateTime: value => value,
    isValidAppTimeZone: () => true,
    isNormalMailLocalRetentionEnabled: () => false,
    fetch: async (url, options) => {
        events.push(['request', url, options && JSON.parse(options.body)]);
        return {json: async () => ({success: true})};
    },
};
vm.createContext(sandbox);
for (const name of ['02-groups.js', '07-settings.js', '08-refresh.js']) {
    vm.runInContext(fs.readFileSync('static/js/index/' + name, 'utf8'), sandbox);
}
(async () => {
    const result = await vm.runInContext(SCENARIO, sandbox);
    console.log(JSON.stringify(result));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''.replace('SCENARIO', json.dumps(scenario))
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_selecting_feishu_toggles_its_panel_and_roundtrips_channels():
    result = run_frontend('''(() => {
        setSelectedForwardChannels(['feishu', 'telegram', 'feishu']);
        const selected = getSelectedForwardChannels();
        const visible = panels.filter(panel => !panel.hidden).map(panel => panel.dataset.channel);
        setSelectedForwardChannels([]);
        return {selected, visible, allHidden: panels.every(panel => panel.hidden),
            emptyVisible: !element('forwardChannelEmptyState').hidden};
    })()''')
    assert result == {'selected': ['telegram', 'feishu'], 'visible': ['telegram', 'feishu'],
                      'allHidden': True, 'emptyVisible': True}


def test_loading_flags_does_not_fill_secrets_and_blank_draft_preserves_saved_values():
    result = run_frontend('''(() => {
        element('settingsFeishuWebhookUrl').value = 'old-input';
        element('settingsFeishuSignSecret').value = 'old-secret';
        setFeishuForwardingSettings({feishu_webhook_url_configured: true, feishu_sign_secret_configured: true});
        return {draft: buildForwardingDraftConfig().feishu,
            configured: hasFeishuWebhook(getFeishuForwardingDraftConfig()),
            placeholder: element('settingsFeishuWebhookUrl').placeholder};
    })()''')
    assert result['draft'] == {'webhook_url': '', 'sign_secret': '', 'clear_sign_secret': False}
    assert result['configured'] is True and '留空保留' in result['placeholder']


def test_draft_test_uses_form_and_blocks_duplicate_clicks_until_finished():
    result = run_frontend('''(async () => {
        setFeishuForwardingSettings({feishu_webhook_url_configured: true});
        element('settingsFeishuSignSecret').value = 'new-signature';
        element('settingsFeishuClearSignSecret').checked = true;
        let resolve;
        fetch = async (url, options) => {
            events.push(['request', url, JSON.parse(options.body)]);
            return new Promise(done => {resolve = done;});
        };
        const pending = testForwardChannel('feishu');
        const during = element('testFeishuBtn').disabled;
        await testForwardChannel('feishu');
        resolve({json: async () => ({success: true, message: '已发送'})});
        await pending;
        return {events, during, after: element('testFeishuBtn').disabled,
            value: element('settingsFeishuSignSecret').value, text: element('testFeishuBtn').textContent};
    })()''')
    requests = [event for event in result['events'] if event[0] == 'request']
    assert len(requests) == 1
    assert requests[0][1] == '/api/settings/test-forward-channel'
    assert requests[0][2]['config']['feishu'] == {
        'webhook_url': '', 'sign_secret': 'new-signature', 'clear_sign_secret': True,
    }
    assert result['during'] is True and result['after'] is False
    assert result['value'] == 'new-signature' and result['text'] == '发送测试消息'


def test_failed_test_restores_button_and_preserves_input():
    result = run_frontend('''(async () => {
        element('settingsFeishuWebhookUrl').value = 'draft-webhook';
        fetch = async () => ({json: async () => ({success: false, error: '飞书签名验证失败'})});
        await testForwardChannel('feishu');
        fetch = async () => {throw new Error('network unavailable');};
        await testForwardChannel('feishu');
        return {events, value: element('settingsFeishuWebhookUrl').value,
            disabled: element('testFeishuBtn').disabled};
    })()''')
    assert result['value'] == 'draft-webhook' and result['disabled'] is False
    assert any(event[0] == 'error' for event in result['events'])
    assert any(event[0] == 'toast' and event[1] == '测试失败' for event in result['events'])


def test_missing_webhook_prevents_test_request():
    events = run_frontend('''(async () => {
        await testForwardChannel('feishu');
        return events;
    })()''')
    assert not any(event[0] == 'request' for event in events)
    assert ['toast', '请先填写飞书 Webhook 地址', 'error'] in events


def test_settings_save_preserves_blank_credentials_and_serializes_explicit_clear():
    result = run_frontend('''(async () => {
        element('refreshIntervalDays').value = '30';
        element('refreshDelaySeconds').value = '5';
        element('settingsAppTimezone').value = 'Asia/Shanghai';
        setSelectedForwardChannels(['feishu']);
        setFeishuForwardingSettings({feishu_webhook_url_configured: true, feishu_sign_secret_configured: true});
        element('settingsFeishuClearSignSecret').checked = true;
        hasWebdavBackupSettingsChanged = () => false;
        fetch = async (url, options) => {
            events.push(['request', url, JSON.parse(options.body)]);
            return {json: async () => ({success: false, error: 'stop after inspecting request'})};
        };
        await saveSettings();
        return events;
    })()''')
    requests = [event for event in result if event[0] == 'request']
    assert len(requests) == 1 and requests[0][1] == '/api/settings'
    settings = requests[0][2]
    assert settings['forward_channels'] == ['feishu']
    assert settings['feishu_webhook_url'] == settings['feishu_sign_secret'] == ''
    assert settings['feishu_clear_sign_secret'] is True


def test_success_and_failure_history_display_feishu_label_and_safe_errors():
    result = run_frontend('''(async () => {
        formatDateTime = value => value;
        fetch = async () => ({json: async () => ({success: true, logs: [{
            channel: 'feishu', account_email: 'primary@example.com',
            status: 'failed', error_message: '<unsafe-error>', message_id: 'one', created_at: 'now',
        }]})});
        await loadForwardingLogs();
        const successHistory = element('forwardingLogsList').innerHTML;
        await loadFailedForwardingLogs();
        return [successHistory, element('failedForwardingLogsList').innerHTML];
    })()''')
    for html in result:
        assert '渠道：飞书' in html and '&lt;unsafe-error>' in html
        assert '<unsafe-error>' not in html


def test_feishu_panel_is_inside_the_channel_container():
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.found = False

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            if attributes.get('data-channel') == 'feishu':
                self.found = True
                assert any(item[1] == 'forwardChannelPanels' for item in self.stack)
            if tag not in {'input', 'br', 'hr', 'img', 'meta', 'link'}:
                self.stack.append((tag, attributes.get('id')))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_startendtag(self, tag, attributes):
            pass

    parser = Parser()
    parser.feed((ROOT / 'templates/partials/index/dialogs-management.html').read_text())
    assert parser.found
