const sourceForwardingState = {channels: [], accounts: [], groups: [], workers: [], policies: [], editingId: null, tab: 'channels', offset: 0};
const notificationTypeLabels = {smtp: 'SMTP 邮件', telegram: 'Telegram', wecom: '企业微信', feishu: '飞书'};
const notificationFieldDefinitions = {
    smtp: [['recipient', '转发到邮箱'], ['host', 'SMTP 主机'], ['port', '端口', 'number'], ['username', '用户名'], ['password', '密码', 'password'], ['from_email', '发件地址'], ['use_tls', '使用 STARTTLS', 'checkbox'], ['use_ssl', '使用 SSL', 'checkbox']],
    telegram: [['bot_token', 'Bot Token', 'password'], ['chat_id', 'Chat ID'], ['topic_id', '话题 ID（可选）'], ['proxy_url', '代理地址（可选）']],
    wecom: [['webhook_url', '机器人 Webhook', 'password']],
    feishu: [['webhook_url', '机器人 Webhook', 'password'], ['sign_secret', '签名密钥（可选）', 'password']],
};
const forwardingScopeLabels = {normal_default: '普通邮箱默认', group: '分组', account: '邮箱', cloudflare_worker: 'Worker 默认', cloudflare_domain: 'CF 域名', cloudflare_address: 'CF 邮箱'};
const forwardingModeLabels = {inherit: '自动使用上层配置', custom: '指定渠道', off: '关闭通知'};

function usesNamedForwardingSettings() { return !!document.getElementById('sourceForwardingConsole'); }

async function forwardingRequest(url, options = {}) {
    const response = await fetch(url, {...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await response.json();
    if (!data.success) throw new Error(data.error || data.message || '操作失败');
    return data;
}

async function forwardingAction(button, operation) {
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try { await operation(); }
    catch (error) { showToast(error.message || '操作失败，请重试', 'error'); }
    finally { if (button) button.disabled = false; }
}

function showForwardingTab(tab) {
    sourceForwardingState.tab = tab;
    document.querySelectorAll('#sourceForwardingConsole [data-forward-panel]').forEach(panel => { panel.hidden = panel.dataset.forwardPanel !== tab; });
    document.querySelectorAll('#sourceForwardingConsole [data-forward-tab]').forEach(button => { button.setAttribute('aria-selected', String(button.dataset.forwardTab === tab)); });
    if (tab === 'history') loadForwardingHistory(0);
}

function sourceForwardingOptions(rows, selected) {
    const ids = new Set((Array.isArray(selected) ? selected : [selected]).map(Number));
    return rows.map(row => `<option value="${Number(row.id)}"${ids.has(Number(row.id)) ? ' selected' : ''}>${escapeHtml(row.email || row.name)}${row.enabled === 0 ? '（已停用）' : ''}</option>`).join('');
}

async function loadSourceForwarding() {
    if (!usesNamedForwardingSettings()) return;
    const status = document.getElementById('sourceForwardingStatus');
    status.textContent = '正在加载通知配置…';
    try {
        const [channels, sources, policies] = await Promise.all([
            forwardingRequest('/api/notification-channels'), forwardingRequest('/api/forwarding/sources'), forwardingRequest('/api/forwarding/policies'),
        ]);
        Object.assign(sourceForwardingState, {channels: channels.channels, accounts: sources.accounts, groups: sources.groups, workers: sources.workers, policies: policies.policies});
        renderNotificationChannels();
        renderForwardingPolicies();
        document.getElementById('forwardHistoryChannel').innerHTML = '<option value="">全部渠道</option>' + sourceForwardingOptions(channels.channels);
        await changeForwardingScope(true);
        status.textContent = `${channels.channels.length} 个通知渠道 · ${policies.policies.filter(p => p.mode !== 'inherit').length} 项来源配置`;
        if (sourceForwardingState.tab === 'history') await loadForwardingHistory(sourceForwardingState.offset);
    } catch (error) { status.textContent = error.message || '加载失败，请刷新重试'; }
}

function renderNotificationChannels() {
    document.getElementById('notificationChannelList').innerHTML = sourceForwardingState.channels.map(channel => `
        <div class="source-forwarding-row"><strong>${escapeHtml(channel.name)}</strong>
        <div class="form-hint">${escapeHtml(notificationTypeLabels[channel.type])} · ${channel.enabled ? '启用' : '停用'} · ${Number(channel.reference_count)} 个关联 · ${Number(channel.pending_count)} 项未完成</div>
        <div class="settings-action-row"><button class="btn btn-secondary" type="button" data-channel-action="edit" data-channel-id="${Number(channel.id)}">编辑</button>
        <button class="btn btn-secondary" type="button" data-channel-action="toggle" data-channel-id="${Number(channel.id)}">${channel.enabled ? '停用' : '启用'}</button>
        <button class="btn btn-secondary" type="button" data-channel-action="delete" data-channel-id="${Number(channel.id)}">删除</button></div></div>`).join('') || '<p class="form-hint">还没有通知渠道，请先新建。</p>';
}

function editNotificationChannel(id = null) {
    const row = sourceForwardingState.channels.find(c => Number(c.id) === Number(id));
    sourceForwardingState.editingId = row?.id || null;
    document.getElementById('notificationChannelName').value = row?.name || '';
    const type = document.getElementById('notificationChannelType');
    type.value = row?.type || 'feishu';
    type.disabled = !!row;
    renderNotificationFields();
    document.getElementById('notificationChannelEditor').hidden = false;
}

function renderNotificationFields() {
    const kind = document.getElementById('notificationChannelType').value;
    const row = sourceForwardingState.channels.find(c => c.id === sourceForwardingState.editingId);
    const config = row?.config || {};
    const container = document.getElementById('notificationChannelFields');
    container.replaceChildren();
    for (const [key, label, type = 'text'] of notificationFieldDefinitions[kind] || []) {
        const group = document.createElement('div');
        group.className = 'form-group';
        const title = document.createElement('label');
        title.className = 'form-label'; title.htmlFor = 'notificationField_' + key; title.textContent = label;
        const input = document.createElement('input');
        input.id = title.htmlFor; input.type = type; input.className = type === 'checkbox' ? '' : 'form-input'; input.autocomplete = 'off';
        if (type === 'checkbox') input.checked = config[key] ?? (key === 'use_ssl');
        else if (type === 'password') { input.value = ''; input.placeholder = config[key + '_configured'] ? '已配置，留空保留' : label; }
        else input.value = config[key] ?? (key === 'port' ? 465 : '');
        group.append(title, input); container.append(group);
    }
    if (kind === 'feishu') {
        const label = document.createElement('label');
        const clear = document.createElement('input'); clear.id = 'notificationClearSignSecret'; clear.type = 'checkbox';
        label.append(clear, document.createTextNode(' 明确清除已有签名密钥')); container.append(label);
    }
}

function notificationChannelDraft() {
    const type = document.getElementById('notificationChannelType').value;
    const config = {};
    for (const [key, , kind] of notificationFieldDefinitions[type] || []) {
        const input = document.getElementById('notificationField_' + key);
        config[key] = kind === 'checkbox' ? input.checked : kind === 'number' ? Number(input.value) : input.value.trim();
    }
    if (type === 'feishu') config.clear_sign_secret = !!document.getElementById('notificationClearSignSecret')?.checked;
    return {id: sourceForwardingState.editingId, name: document.getElementById('notificationChannelName').value.trim(), type, config};
}

async function saveNotificationChannel(button) {
    await forwardingAction(button, async () => {
        const draft = notificationChannelDraft();
        await forwardingRequest('/api/notification-channels' + (draft.id ? '/' + draft.id : ''), {method: draft.id ? 'PUT' : 'POST', body: JSON.stringify(draft)});
        document.getElementById('notificationChannelEditor').hidden = true;
        await loadSourceForwarding(); showToast('通知渠道已保存', 'success');
    });
}

async function testNotificationChannel(button) {
    await forwardingAction(button, async () => {
        const data = await forwardingRequest('/api/notification-channels/test', {method: 'POST', body: JSON.stringify(notificationChannelDraft())});
        showToast(data.message || '测试消息已发送', 'success');
    });
}

async function notificationChannelAction(action, id, button) {
    if (action === 'edit') { editNotificationChannel(id); return; }
    const row = sourceForwardingState.channels.find(c => c.id === id);
    if (!row) return;
    await forwardingAction(button, async () => {
        await forwardingRequest('/api/notification-channels/' + id, action === 'delete' ? {method: 'DELETE'} : {method: 'PUT', body: JSON.stringify({enabled: !row.enabled})});
        await loadSourceForwarding(); showToast('渠道已更新', 'success');
    });
}

function selectedForwardingSources() {
    if (document.getElementById('forwardPolicyScope').value === 'normal_default') return [0];
    return Array.from(document.getElementById('forwardPolicySource').selectedOptions).map(option => Number(option.value)).sort((a, b) => a - b);
}

function filteredForwardingSourceOptions() {
    const query = document.getElementById('forwardPolicySourceFilter').value.trim().toLocaleLowerCase();
    return Array.from(document.getElementById('forwardPolicySource').options).filter(option => option.textContent.toLocaleLowerCase().includes(query));
}

function updateForwardingSourceSelection() {
    const options = Array.from(document.getElementById('forwardPolicySource').options);
    const selected = options.filter(option => option.selected);
    const ids = new Set(selected.map(option => option.value));
    document.getElementById('forwardPolicySourceSummary').textContent = selected.length
        ? `已选 ${selected.length} 项：${selected.slice(0, 2).map(option => option.textContent).join('、')}${selected.length > 2 ? '…' : ''}` : '请选择来源';
    document.getElementById('forwardPolicySourceStatus').textContent = `显示 ${filteredForwardingSourceOptions().length} / ${options.length} 项 · 已选 ${selected.length} 项`;
    document.querySelectorAll('#forwardPolicySourceOptions input').forEach(input => { input.checked = ids.has(input.value); });
}

function renderForwardingSourcePicker() {
    const options = filteredForwardingSourceOptions();
    document.getElementById('forwardPolicySourceOptions').innerHTML = options.map(option => `
        <label class="forward-source-option"><input type="checkbox" value="${Number(option.value)}"${option.selected ? ' checked' : ''} onchange="toggleForwardingSource(this.value, this.checked)"><span>${escapeHtml(option.textContent)}</span></label>`).join('')
        || '<p class="form-hint">没有匹配的来源，请调整筛选条件。</p>';
    updateForwardingSourceSelection();
}

function toggleForwardingSource(id, selected) {
    const option = Array.from(document.getElementById('forwardPolicySource').options).find(option => option.value === String(id));
    if (option) option.selected = selected;
    updateForwardingSourceSelection();
    return loadForwardingPolicy();
}

function selectForwardingSources(selected) {
    const options = selected ? filteredForwardingSourceOptions() : Array.from(document.getElementById('forwardPolicySource').options);
    options.forEach(option => { option.selected = selected; });
    updateForwardingSourceSelection();
    return loadForwardingPolicy();
}

function forwardingPolicyDraft() {
    const ids = selectedForwardingSources();
    return {scope_type: document.getElementById('forwardPolicyScope').value,
        scope_id: ids[0] || 0, scope_ids: ids,
        match_value: document.getElementById('forwardPolicyMatch').value.trim(),
        mode: document.getElementById('forwardPolicyMode').value,
        channel_ids: Array.from(document.querySelectorAll('#forwardPolicyTargets input:checked')).map(input => Number(input.value))};
}

async function changeForwardingScope(preserve = false) {
    const scope = document.getElementById('forwardPolicyScope').value;
    const source = document.getElementById('forwardPolicySource');
    const selected = preserve ? selectedForwardingSources() : [];
    const isCf = scope.startsWith('cloudflare_');
    const rows = scope === 'group' ? sourceForwardingState.groups : scope === 'account' ? sourceForwardingState.accounts : isCf ? sourceForwardingState.workers : [];
    source.innerHTML = sourceForwardingOptions(rows, selected);
    if (!preserve) {
        document.getElementById('forwardPolicySourceFilter').value = '';
        document.getElementById('forwardPolicySourcePicker').open = false;
    }
    renderForwardingSourcePicker();
    document.getElementById('forwardPolicySourceField').hidden = scope === 'normal_default';
    const matchNeeded = scope === 'cloudflare_domain' || scope === 'cloudflare_address';
    document.getElementById('forwardPolicyMatchField').hidden = !matchNeeded;
    document.getElementById('forwardPolicyMatchLabel').textContent = scope === 'cloudflare_address' ? '完整收件邮箱地址' : '完整收件域名';
    document.getElementById('forwardPolicyMatch').placeholder = scope === 'cloudflare_address' ? 'user@example.com（无需导入）' : 'example.com';
    if (!preserve) document.getElementById('forwardPolicyMatch').value = '';
    document.getElementById('forwardPreviewAccountField').hidden = isCf;
    document.getElementById('forwardPreviewWorkerField').hidden = !isCf;
    document.getElementById('forwardPreviewAddressField').hidden = !isCf;
    await loadForwardingPolicy();
}

function updateForwardingPreviewSources() {
    const draft = forwardingPolicyDraft();
    const groups = sourceForwardingState.groups.filter(g => draft.scope_ids.includes(g.id));
    let accounts = sourceForwardingState.accounts;
    if (draft.scope_type === 'group') accounts = accounts.filter(a => groups.some(g => g.descendant_ids.includes(a.group_id)));
    if (draft.scope_type === 'account') accounts = accounts.filter(a => draft.scope_ids.includes(a.id));
    document.getElementById('forwardPreviewAccount').innerHTML = sourceForwardingOptions(accounts);
    const status = document.getElementById('forwardPolicyAccountStatus');
    if (draft.scope_type === 'group' || draft.scope_type === 'account') status.textContent = `已选 ${draft.scope_ids.length} 个来源，覆盖 ${accounts.length} 个邮箱，其中 ${accounts.filter(a => a.status === 'active').length} 个活跃。通知由来源规则决定。`;
    else status.textContent = '';
    const previewWorker = document.getElementById('forwardPreviewWorker');
    previewWorker.innerHTML = sourceForwardingOptions(sourceForwardingState.workers.filter(w => draft.scope_ids.includes(w.id)), previewWorker.value);
    if (draft.scope_type === 'cloudflare_address') document.getElementById('forwardPreviewAddress').value = draft.match_value;
    else if (draft.scope_type === 'cloudflare_domain' && draft.match_value) document.getElementById('forwardPreviewAddress').value = 'preview@' + draft.match_value.replace(/^@/, '');
}

function renderForwardingTargets(ids = []) {
    document.getElementById('forwardPolicyTargets').innerHTML = sourceForwardingState.channels.map(channel => `
        <label class="forward-checkbox"><input type="checkbox" value="${Number(channel.id)}"${ids.includes(channel.id) ? ' checked' : ''}> ${escapeHtml(channel.name)}${channel.enabled ? '' : '（已停用）'}</label>`).join('') || '<p class="form-hint">请先新建通知渠道。</p>';
    syncForwardingPolicyMode();
}

function syncForwardingPolicyMode() { document.getElementById('forwardPolicyTargets').hidden = document.getElementById('forwardPolicyMode').value !== 'custom'; }

async function loadForwardingPolicy() {
    updateForwardingPreviewSources();
    const draft = forwardingPolicyDraft();
    document.getElementById('forwardPolicyPreview').textContent = '';
    const hint = document.getElementById('forwardPolicyConfigurationHint');
    if (!draft.scope_ids.length || (['cloudflare_domain', 'cloudflare_address'].includes(draft.scope_type) && !draft.match_value)) {
        document.getElementById('forwardPolicyMode').value = 'custom';
        hint.textContent = '请选择来源；未单独配置的账号、子分组和 CF 地址会自动使用上层配置。';
        renderForwardingTargets(); return;
    }
    const key = JSON.stringify([draft.scope_type, draft.scope_ids, draft.match_value]);
    try {
        const params = new URLSearchParams({scope_type: draft.scope_type, scope_ids: draft.scope_ids.join(','), match_value: draft.match_value});
        const data = await forwardingRequest('/api/forwarding/policies?' + params);
        const current = forwardingPolicyDraft();
        if (key !== JSON.stringify([current.scope_type, current.scope_ids, current.match_value])) return;
        const policies = data.policies || [data.policy], first = policies[0];
        const same = policies.every(policy => policy.mode === first.mode && JSON.stringify(policy.channel_ids) === JSON.stringify(first.channel_ids));
        document.getElementById('forwardPolicyMode').value = same && first.mode === 'off' ? 'off' : 'custom';
        hint.textContent = !same ? `已选 ${policies.length} 个来源，现有配置不同；保存后将统一应用所选通知方式和渠道。`
            : first.mode === 'inherit' ? '当前未设置独立配置，已自动使用上层配置；保存渠道后才会覆盖上层。' : `已加载 ${policies.length} 个来源的配置。`;
        renderForwardingTargets(same && first.mode === 'custom' ? first.channel_ids : []);
    } catch (error) { document.getElementById('forwardPolicyPreview').textContent = error.message; }
}

async function saveForwardingPolicy(button) {
    await forwardingAction(button, async () => {
        const draft = forwardingPolicyDraft();
        if (!draft.scope_ids.length) throw new Error('请至少选择一个来源');
        await forwardingRequest('/api/forwarding/policies', {method: 'PUT', body: JSON.stringify(draft)});
        await loadSourceForwarding();
        showToast(`已保存 ${draft.scope_ids.length} 项来源关联，新关联从后续新邮件生效`, 'success');
    });
}

function forwardingPolicyLabel(policy) {
    const source = policy.scope_type === 'account' ? sourceForwardingState.accounts.find(a => a.id === policy.scope_id)
        : policy.scope_type === 'group' ? sourceForwardingState.groups.find(g => g.id === policy.scope_id)
        : sourceForwardingState.workers.find(w => w.id === policy.scope_id);
    return `${forwardingScopeLabels[policy.scope_type]}${source ? ' · ' + (source.email || source.name) : ''}${policy.match_value ? ' · ' + policy.match_value : ''}`;
}

function renderForwardingPolicies() {
    document.getElementById('forwardPolicyList').innerHTML = sourceForwardingState.policies.map((policy, index) => {
        if (policy.mode === 'inherit') return '';
        const names = policy.channel_ids.map(id => sourceForwardingState.channels.find(c => c.id === id)?.name || '已删除渠道');
        return `<div class="source-forwarding-row"><strong>${escapeHtml(forwardingPolicyLabel(policy))}</strong>
            <div class="form-hint">${escapeHtml(forwardingModeLabels[policy.mode])}${names.length ? '：' + names.map(escapeHtml).join('、') : ''}</div>
            <div class="settings-action-row"><button class="btn btn-secondary" type="button" data-policy-index="${index}">编辑关联</button>
            <button class="btn btn-secondary" type="button" data-policy-remove="${index}">删除转发规则</button></div></div>`;
    }).join('') || '<p class="form-hint">还没有来源关联。</p>';
}

async function previewForwardingPolicy(button) {
    await forwardingAction(button, async () => {
        const draft = forwardingPolicyDraft();
        const params = draft.scope_type.startsWith('cloudflare_')
            ? new URLSearchParams({worker_id: document.getElementById('forwardPreviewWorker').value, address: document.getElementById('forwardPreviewAddress').value.trim()})
            : new URLSearchParams({account_id: document.getElementById('forwardPreviewAccount').value});
        const {preview} = await forwardingRequest('/api/forwarding/preview?' + params);
        const path = preview.path.map(p => `${forwardingScopeLabels[p.scope_type]}（${forwardingModeLabels[p.mode]}）`).join(' → ');
        const targets = preview.channels.map(c => c.name + (c.enabled ? '' : '（已停用）')).join('、');
        document.getElementById('forwardPolicyPreview').textContent = `${preview.email_address}\n${path}\n${preview.eligible ? (targets ? '通知目标：' + targets : '不发送通知') : preview.reason}`;
    });
}

async function openForwardingSource(scope, id, match = '') {
    closeAllModals();
    await showSettingsModal();
    showForwardingTab('policies');
    document.getElementById('forwardPolicyScope').value = scope;
    await changeForwardingScope();
    document.getElementById('forwardPolicySource').value = String(id);
    renderForwardingSourcePicker();
    document.getElementById('forwardPolicyMatch').value = match;
    await loadForwardingPolicy();
    scrollSettingsSection('forwardingSettingsSection');
}

async function loadForwardingHistory(offset = 0) {
    const container = document.getElementById('sourceForwardingHistory');
    container.textContent = '正在加载…';
    try {
        const params = new URLSearchParams({limit: 50, offset: Math.max(0, offset)});
        for (const [key, id] of [['source_type', 'forwardHistorySource'], ['channel_id', 'forwardHistoryChannel'], ['email_address', 'forwardHistoryAddress'], ['status', 'forwardHistoryState']]) {
            const value = document.getElementById(id).value.trim(); if (value) params.set(key, value);
        }
        const data = await forwardingRequest('/api/forwarding/history?' + params);
        sourceForwardingState.offset = Math.max(0, offset);
        const labels = {succeeded: '成功', success: '成功', failed: '失败', pending: '待发送', blocked: '已阻塞', cancelled: '已取消'};
        const rows = data.history;
        container.innerHTML = rows.map(row => `<div class="source-forwarding-row"><strong>${escapeHtml(row.email_address)} → ${escapeHtml(row.channel_name)}</strong>
            <div class="form-hint">${row.source_type === 'cloudflare' ? 'CF · ' + escapeHtml(row.source_name) : '普通邮箱'} · ${escapeHtml(notificationTypeLabels[row.channel_type] || row.channel_type)} · ${escapeHtml(labels[row.status] || row.status)} · ${escapeHtml(formatDateTime(new Date(row.updated_at * 1000).toISOString()))}</div>
            ${row.error_message ? '<div>' + escapeHtml(row.error_message) + '</div>' : ''}</div>`).join('') || '<p class="form-hint">没有符合条件的转发记录。</p>';
        document.getElementById('forwardHistoryPrevious').disabled = sourceForwardingState.offset === 0;
        document.getElementById('forwardHistoryNext').disabled = rows.length < 50;
        document.getElementById('forwardScanStatus').textContent = data.scans.filter(s => s.error_message).map(s => s.worker_name + '：' + s.error_message).join('\n');
    } catch (error) { container.textContent = error.message || '加载失败，请重试'; }
}

function changeForwardingHistoryPage(direction) { return loadForwardingHistory(sourceForwardingState.offset + direction * 50); }

function omitLegacyForwardingFields(settings) {
    delete settings.forward_channels; delete settings.smtp_provider; delete settings.feishu_clear_sign_secret;
    for (const [type, definitions] of Object.entries(notificationFieldDefinitions)) {
        for (const [field] of definitions) delete settings[type === 'smtp' && field === 'recipient' ? 'email_forward_recipient' : type + '_' + field];
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const console = document.getElementById('sourceForwardingConsole');
    if (!console) return;
    const sourcePicker = document.getElementById('forwardPolicySourcePicker');
    sourcePicker.addEventListener('toggle', () => {
        if (sourcePicker.open) document.getElementById('forwardPolicySourceFilter').focus();
    });
    sourcePicker.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            sourcePicker.open = false;
            document.getElementById('forwardPolicySourceToggle').focus();
            event.stopPropagation();
        }
    });
    document.addEventListener('click', event => { if (!sourcePicker.contains(event.target)) sourcePicker.open = false; });
    const picker = document.getElementById('forwardChannelPicker');
    if (picker) picker.closest('.forwarding-channel-group').style.display = 'none';
    const panels = document.getElementById('forwardChannelPanels');
    if (panels) panels.style.display = 'none';
    console.addEventListener('click', event => {
        const channel = event.target.closest('[data-channel-action]');
        if (channel) notificationChannelAction(channel.dataset.channelAction, Number(channel.dataset.channelId), channel);
        const policy = event.target.closest('[data-policy-index]');
        if (policy) {
            const row = sourceForwardingState.policies[Number(policy.dataset.policyIndex)];
            if (row) openForwardingSource(row.scope_type, row.scope_id, row.match_value);
        }
        const remove = event.target.closest('[data-policy-remove]');
        if (remove) forwardingAction(remove, async () => {
            const row = sourceForwardingState.policies[Number(remove.dataset.policyRemove)];
            await forwardingRequest('/api/forwarding/policies', {method: 'DELETE', body: JSON.stringify(row)});
            await loadSourceForwarding(); showToast('转发规则已删除', 'success');
        });
    });
    showForwardingTab('channels');
});
