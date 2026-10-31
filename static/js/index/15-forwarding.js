const sourceForwardingState = {channels: [], accounts: [], groups: [], workers: [], policies: [], selectedPolicyIds: new Set(), editingPolicyIds: [], editingId: null, tab: 'policies', offset: 0};
const notificationTypeLabels = {smtp: 'SMTP 邮件', telegram: 'Telegram', wecom: '企业微信', feishu: '飞书'};
const notificationFieldDefinitions = {
    smtp: [['recipient', '转发到邮箱'], ['host', 'SMTP 主机'], ['port', '端口', 'number'], ['username', '用户名'], ['password', '密码', 'password'], ['from_email', '发件地址'], ['use_tls', '使用 STARTTLS', 'checkbox'], ['use_ssl', '使用 SSL', 'checkbox']],
    telegram: [['bot_token', 'Bot Token', 'password'], ['chat_id', 'Chat ID'], ['topic_id', '话题 ID（可选）'], ['proxy_url', '代理地址（可选）']],
    wecom: [['webhook_url', '机器人 Webhook', 'password']],
    feishu: [['webhook_url', '机器人 Webhook', 'password'], ['sign_secret', '签名密钥（可选）', 'password']],
};
const forwardingScopeLabels = {normal_default: '普通邮箱默认', group: '分组', account: '邮箱', cloudflare_worker: 'Worker 默认', cloudflare_domain: 'CF 域名', cloudflare_address: 'CF 邮箱'};
const forwardingModeLabels = {inherit: '自动使用上层配置', custom: '指定渠道', off: '关闭通知'};
const forwardingRuleFilterFields = {q: 'forwardRuleSearch', scope: 'forwardRuleScopeFilter', channel: 'forwardRuleChannelFilter', mode: 'forwardRuleModeFilter'};

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

function isDedicatedForwardingUI() {
    return document.getElementById('forwardingManagementView')?.dataset.forwardingWorkspace === 'true';
}

function setForwardingLocation(tab, replace = true) {
    if (!isDedicatedForwardingUI() || typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.pathname = '/forwarding';
    url.searchParams.set('forwarding_tab', tab);
    window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}

async function showForwardingManagement(tab = 'policies', updateLocation = true) {
    closeAllModals();
    if (typeof closeNavbarActionsMenu === 'function') closeNavbarActionsMenu();
    if (typeof closeMobilePanels === 'function') closeMobilePanels();
    document.getElementById('forwardingManagementView').hidden = false;
    document.documentElement.classList.add('forwarding-workspace-open');
    if (updateLocation) setForwardingLocation(tab, window.location.pathname === '/forwarding');
    sourceForwardingState.tab = 'policies';
    await refreshForwardingManagement();
    const ruleParams = new URL(window.location.href).searchParams;
    for (const [key, id] of Object.entries(forwardingRuleFilterFields)) document.getElementById(id).value = ruleParams.get('forwarding_rule_' + key) || '';
    changeForwardingPolicyFilters(false);
    if (tab === 'history') {
        const params = new URL(window.location.href).searchParams;
        for (const [key, id] of [['source_type', 'forwardHistorySource'], ['channel_id', 'forwardHistoryChannel'], ['email_address', 'forwardHistoryAddress'], ['status', 'forwardHistoryState']]) {
            document.getElementById(id).value = params.get('forwarding_' + key) || '';
        }
        sourceForwardingState.offset = Math.max(0, parseInt(params.get('forwarding_offset'), 10) || 0);
    }
    showForwardingTab(tab, false);
}

async function refreshForwardingManagement() {
    await Promise.all([loadSourceForwarding(), loadForwardingRuntimeSettings()]);
}

function hideForwardingManagement(updateLocation = true) {
    document.getElementById('forwardingManagementView').hidden = true;
    document.documentElement.classList.remove('forwarding-workspace-open');
    if (updateLocation) {
        const url = new URL(window.location.href);
        url.pathname = '/';
        [...url.searchParams.keys()].filter(key => key.startsWith('forwarding_')).forEach(key => url.searchParams.delete(key));
        window.history.pushState({}, '', url);
    }
}

function showForwardingTab(tab, updateLocation = true) {
    if (!['channels', 'policies', 'history', 'runtime'].includes(tab)) tab = 'policies';
    sourceForwardingState.tab = tab;
    document.querySelectorAll('#sourceForwardingConsole [data-forward-panel]').forEach(panel => { panel.hidden = panel.dataset.forwardPanel !== tab; });
    document.querySelectorAll('#sourceForwardingConsole [data-forward-tab]').forEach(button => {
        const active = button.dataset.forwardTab === tab;
        button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
    });
    if (updateLocation) setForwardingLocation(tab);
    if (tab === 'history') loadForwardingHistory(sourceForwardingState.offset);
}

function showForwardingPolicyEditor() {
    setForwardingPolicyEditing([]);
    document.getElementById('forwardPolicyMode').value = 'custom';
    document.getElementById('forwardPolicyKeywords').value = '';
    document.getElementById('forwardPolicySenders').value = '';
    renderForwardingTargets();
    const editor = document.getElementById('forwardPolicyEditor');
    editor.hidden = false;
    editor.scrollIntoView({block: 'start'});
    document.getElementById('forwardPolicyScope').focus({preventScroll: true});
    changeForwardingScope();
}


function setForwardingPolicyEditing(ids) {
    sourceForwardingState.editingPolicyIds = ids;
    const editing = ids.length > 0;
    const bulk = ids.length > 1;
    document.getElementById('forwardPolicyEditorTitle').textContent = bulk ? `批量编辑 ${ids.length} 条规则` : editing ? '编辑转发规则' : '新增来源关联';
    document.getElementById('saveForwardingPolicyBtn').textContent = editing ? '保存修改' : '新增关联';
    document.getElementById('forwardPolicyBulkFields').hidden = !bulk;
    document.getElementById('forwardPolicyEditingSources').hidden = !editing;
    document.getElementById('forwardPolicyScope').disabled = editing;
    const scope = document.getElementById('forwardPolicyScope').value;
    document.getElementById('forwardPolicySourceField').hidden = editing || scope === 'normal_default';
    document.getElementById('forwardPolicyMatchField').hidden = editing || !['cloudflare_domain', 'cloudflare_address'].includes(scope);
    for (const field of ['Notification', 'Keywords', 'Senders']) document.getElementById('forwardPolicyApply' + field).checked = !bulk;
}

function closeForwardingPolicyEditor() {
    setForwardingPolicyEditing([]);
    document.getElementById('forwardPolicyEditor').hidden = true;
}

function forwardingSourcesForScope(scope) {
    return scope === 'group' ? sourceForwardingState.groups : scope === 'account' ? sourceForwardingState.accounts : scope.startsWith('cloudflare_') ? sourceForwardingState.workers : [];
}

function editForwardingPolicies(ids) {
    ids = [...new Set(ids)].sort((a, b) => a - b);
    const policies = ids.map(id => sourceForwardingState.policies.find(p => p.id === id && p.mode !== 'inherit'));
    if (!ids.length || policies.some(p => !p)) return showToast('部分转发规则已不存在，请刷新后重试', 'error');
    if (new Set(policies.map(p => p.scope_type)).size !== 1) return showToast('批量编辑仅支持同一来源范围的转发规则', 'error');
    const first = policies[0];
    const shared = key => policies.every(p => JSON.stringify(p[key]) === JSON.stringify(first[key]));
    const scope = first.scope_type;
    document.getElementById('forwardPolicyScope').value = scope;
    document.getElementById('forwardPolicySource').innerHTML = sourceForwardingOptions(forwardingSourcesForScope(scope), policies.map(p => p.scope_id));
    document.getElementById('forwardPolicyMatch').value = ids.length === 1 ? first.match_value || '' : '';
    document.getElementById('forwardPolicyMode').value = shared('mode') ? first.mode : 'custom';
    for (const [key, id] of [['keywords', 'forwardPolicyKeywords'], ['senders', 'forwardPolicySenders']]) {
        document.getElementById(id).value = shared(key) ? first[key] || '' : '';
    }
    setForwardingPolicyEditing(ids);
    renderForwardingTargets(shared('channel_ids') ? first.channel_ids : []);
    document.getElementById('forwardPolicyEditingSources').textContent = `${forwardingScopeLabels[scope]}：` + policies.map(p => forwardingPolicyLabel(p) + (p.match_value ? `（${forwardingPolicySource(p)?.name || 'Worker'}）` : '')).join('、');
    document.getElementById('forwardPolicyConfigurationHint').textContent = ids.length > 1 ? '仅保存勾选的字段；未勾选字段各自保留原值。勾选条件后留空表示清除，关闭通知的规则不使用邮件条件。' : '修改通知方式、渠道或邮件条件，邮件来源保持不变。';
    document.getElementById('forwardPolicyPreview').textContent = '';
    const isCf = scope.startsWith('cloudflare_');
    document.getElementById('forwardPreviewAccountField').hidden = isCf;
    document.getElementById('forwardPreviewWorkerField').hidden = !isCf;
    document.getElementById('forwardPreviewAddressField').hidden = !isCf;
    updateForwardingPreviewSources();
    const editor = document.getElementById('forwardPolicyEditor');
    editor.hidden = false;
    editor.scrollIntoView({block: 'start'});
    document.getElementById(ids.length > 1 ? 'forwardPolicyApplyNotification' : 'forwardPolicyMode').focus({preventScroll: true});
}

function editSelectedForwardingPolicies() {
    editForwardingPolicies(Array.from(sourceForwardingState.selectedPolicyIds));
}
function forwardingEmptyRow(columns, message) {
    return `<tr><td colspan="${columns}" class="forwarding-empty">${message}</td></tr>`;
}

function forwardingCellLabel(value) {
    const text = escapeHtml(value);
    return text.includes('@') ? text.replace('@', '@<wbr>') : text.replace('.', '<wbr>.');
}

function forwardingLoadingRows(columns) {
    return Array.from({length: 3}, () => `<tr aria-hidden="true">${'<td><span class="forwarding-skeleton"></span></td>'.repeat(columns)}</tr>`).join('');
}

function sourceForwardingOptions(rows, selected) {
    const ids = new Set((Array.isArray(selected) ? selected : [selected]).map(Number));
    return rows.map(row => `<option value="${Number(row.id)}"${ids.has(Number(row.id)) ? ' selected' : ''}>${escapeHtml(row.email || row.name)}${row.enabled === 0 ? '（已停用）' : ''}</option>`).join('');
}

async function loadSourceForwarding() {
    if (!usesNamedForwardingSettings()) return;
    const status = document.getElementById('sourceForwardingStatus');
    status.textContent = '正在加载通知配置…';
    document.getElementById('notificationChannelList').innerHTML = forwardingLoadingRows(4);
    document.getElementById('forwardPolicyList').innerHTML = forwardingLoadingRows(5);
    try {
        const [channels, sources, policies] = await Promise.all([
            forwardingRequest('/api/notification-channels'), forwardingRequest('/api/forwarding/sources'), forwardingRequest('/api/forwarding/policies'),
        ]);
        Object.assign(sourceForwardingState, {channels: channels.channels, accounts: sources.accounts, groups: sources.groups, workers: sources.workers, policies: policies.policies});
        renderNotificationChannels();
        const historyChannel = document.getElementById('forwardHistoryChannel');
        historyChannel.innerHTML = '<option value="">全部渠道</option>' + sourceForwardingOptions(channels.channels, historyChannel.value);
        const ruleChannel = document.getElementById('forwardRuleChannelFilter');
        ruleChannel.innerHTML = '<option value="">全部渠道</option>' + sourceForwardingOptions(channels.channels, ruleChannel.value);
        renderForwardingPolicies();
        if (!sourceForwardingState.editingPolicyIds.length) await changeForwardingScope(true);
        status.textContent = `${channels.channels.length} 个通知渠道，${policies.policies.filter(p => p.mode !== 'inherit').length} 条转发规则`;
        if (sourceForwardingState.tab === 'history') await loadForwardingHistory(sourceForwardingState.offset);
    } catch (error) {
        status.textContent = error.message || '加载失败，请刷新重试';
        for (const [id, columns] of [['notificationChannelList', 4], ['forwardPolicyList', 5]]) document.getElementById(id).innerHTML = forwardingEmptyRow(columns, '加载失败，请点击页面右上角的刷新重试。');
    }
}

function renderNotificationChannels() {
    document.getElementById('notificationChannelList').innerHTML = sourceForwardingState.channels.map(channel => `
        <tr><td><strong>${escapeHtml(channel.name)}</strong><span class="forwarding-cell-detail">${escapeHtml(notificationTypeLabels[channel.type])}</span></td>
        <td><span class="forwarding-state${channel.enabled ? '' : ' is-muted'}">${channel.enabled ? '已启用' : '已停用'}</span></td>
        <td class="forwarding-numeric">${Number(channel.reference_count)} 个关联<span class="forwarding-cell-detail">${Number(channel.pending_count)} 项待处理</span></td>
        <td><div class="forwarding-row-actions"><button class="btn btn-secondary" type="button" data-channel-action="edit" data-channel-id="${Number(channel.id)}">编辑</button>
        <button class="btn btn-secondary" type="button" data-channel-action="toggle" data-channel-id="${Number(channel.id)}">${channel.enabled ? '停用' : '启用'}</button>
        <button class="btn btn-secondary forwarding-danger" type="button" data-channel-action="delete" data-channel-id="${Number(channel.id)}">删除</button></div></td></tr>`).join('') || forwardingEmptyRow(4, '还没有通知渠道。点击“新增渠道”配置第一个通知目标。');
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
        await loadSourceForwarding();
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
        if (action === 'delete' && !(await showConfirmModal('删除此通知渠道？仍有关联或未完成投递时无法删除。', {title: '删除通知渠道', confirmText: '删除渠道'}))) return;
        await forwardingRequest('/api/notification-channels/' + id, action === 'delete' ? {method: 'DELETE'} : {method: 'PUT', body: JSON.stringify({enabled: !row.enabled})});
        await loadSourceForwarding();
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

function forwardingSourceName() {
    const scope = document.getElementById('forwardPolicyScope').value;
    return scope === 'account' ? '邮箱' : scope === 'group' ? '分组' : scope.startsWith('cloudflare_') ? 'Worker' : '来源';
}

function updateForwardingSourceSelection() {
    const options = Array.from(document.getElementById('forwardPolicySource').options);
    const selected = options.filter(option => option.selected);
    const ids = new Set(selected.map(option => option.value));
    document.getElementById('forwardPolicySourceSummary').textContent = selected.length
        ? `已选 ${selected.length} 项：${selected.slice(0, 2).map(option => option.textContent).join('、')}${selected.length > 2 ? '…' : ''}`
        : forwardingSourceName() === 'Worker' ? '请选择 Worker' : '请选择' + forwardingSourceName();
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
        keywords: document.getElementById('forwardPolicyKeywords').value,
        senders: document.getElementById('forwardPolicySenders').value,
        channel_ids: Array.from(document.querySelectorAll('#forwardPolicyTargets input:checked')).map(input => Number(input.value))};
}

async function changeForwardingScope(preserve = false) {
    const scope = document.getElementById('forwardPolicyScope').value;
    const source = document.getElementById('forwardPolicySource');
    const selected = preserve ? selectedForwardingSources() : [];
    const isCf = scope.startsWith('cloudflare_');
    const sourceName = forwardingSourceName();
    document.getElementById('forwardPolicySourceLabel').textContent = `${sourceName}（可多选）`;
    document.getElementById('forwardPolicySourceFilter').placeholder = {邮箱: '输入邮箱地址筛选', 分组: '输入分组名称筛选', Worker: '输入 Worker 名称筛选', 来源: '输入关键词筛选'}[sourceName];
    const rows = forwardingSourcesForScope(scope);
    source.innerHTML = sourceForwardingOptions(rows, selected);
    if (!preserve) {
        document.getElementById('forwardPolicySourceFilter').value = '';
        document.getElementById('forwardPolicySourcePicker').open = false;
    }
    renderForwardingSourcePicker();
    document.getElementById('forwardPolicyMode').value = 'custom';
    renderForwardingTargets();
    document.getElementById('forwardPolicySourceField').hidden = scope === 'normal_default';
    const matchNeeded = scope === 'cloudflare_domain' || scope === 'cloudflare_address';
    document.getElementById('forwardPolicyMatchField').hidden = !matchNeeded;
    document.getElementById('forwardPolicyMatchLabel').textContent = scope === 'cloudflare_address' ? '完整收件邮箱地址' : '完整收件域名';
    document.getElementById('forwardPolicyMatch').placeholder = scope === 'cloudflare_address' ? 'user@example.com（无需导入）' : 'example.com';
    if (!preserve) {
        document.getElementById('forwardPolicyMatch').value = '';
        document.getElementById('forwardPolicyKeywords').value = '';
        document.getElementById('forwardPolicySenders').value = '';
    }
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

function syncForwardingPolicyMode() {
    const bulk = sourceForwardingState.editingPolicyIds.length > 1;
    const applyNotification = !bulk || document.getElementById('forwardPolicyApplyNotification').checked;
    const hidden = applyNotification && document.getElementById('forwardPolicyMode').value !== 'custom';
    document.getElementById('forwardPolicyMode').disabled = !applyNotification;
    document.getElementById('forwardPolicyTargets').hidden = hidden;
    document.querySelectorAll('#forwardPolicyTargets input').forEach(input => { input.disabled = !applyNotification; });
    document.getElementById('forwardPolicyFilters').hidden = hidden;
    document.getElementById('forwardPolicyKeywords').disabled = hidden || bulk && !document.getElementById('forwardPolicyApplyKeywords').checked;
    document.getElementById('forwardPolicySenders').disabled = hidden || bulk && !document.getElementById('forwardPolicyApplySenders').checked;
}

async function loadForwardingPolicy() {
    updateForwardingPreviewSources();
    if (sourceForwardingState.editingPolicyIds.length) return;
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
        if (sourceForwardingState.editingPolicyIds.length) return;
        const current = forwardingPolicyDraft();
        if (key !== JSON.stringify([current.scope_type, current.scope_ids, current.match_value])) return;
        const policies = data.policies || [data.policy];
        const existing = policies.filter(policy => policy.id !== null && policy.mode !== 'inherit');
        hint.textContent = existing.length ? `所选来源中有 ${existing.length} 项已有转发规则，可在列表编辑；新增关联不会覆盖已有规则。`
            : '当前未设置独立规则，自动使用上层配置；可为所选来源新增转发规则。';
    } catch (error) { document.getElementById('forwardPolicyPreview').textContent = error.message; }
}

async function saveForwardingPolicy(button) {
    await forwardingAction(button, async () => {
        const draft = forwardingPolicyDraft();
        const ids = sourceForwardingState.editingPolicyIds;
        if (ids.length) {
            const bulk = ids.length > 1;
            const changes = {};
            if (!bulk || document.getElementById('forwardPolicyApplyNotification').checked) Object.assign(changes, {mode: draft.mode, channel_ids: draft.channel_ids});
            if (!bulk || document.getElementById('forwardPolicyApplyKeywords').checked) changes.keywords = draft.keywords;
            if (!bulk || document.getElementById('forwardPolicyApplySenders').checked) changes.senders = draft.senders;
            if (!Object.keys(changes).length) throw new Error('请勾选至少一个需要修改的字段');
            await forwardingRequest('/api/forwarding/policies', {method: 'PATCH', body: JSON.stringify({policy_ids: ids, changes})});
        } else {
            if (!draft.scope_ids.length) throw new Error('请至少选择一个来源');
            await forwardingRequest('/api/forwarding/policies', {method: 'POST', body: JSON.stringify(draft)});
        }
        closeForwardingPolicyEditor();
        await loadSourceForwarding();
    });
}

function forwardingPolicySource(policy) {
    return policy.scope_type === 'account' ? sourceForwardingState.accounts.find(a => a.id === policy.scope_id)
        : policy.scope_type === 'group' ? sourceForwardingState.groups.find(g => g.id === policy.scope_id)
        : sourceForwardingState.workers.find(w => w.id === policy.scope_id);
}

function forwardingPolicyLabel(policy) {
    const source = forwardingPolicySource(policy);
    return policy.match_value || source?.email || source?.name || forwardingScopeLabels[policy.scope_type];
}

function filteredForwardingPolicies() {
    const filters = Object.fromEntries(Object.entries(forwardingRuleFilterFields).map(([key, id]) => [key, document.getElementById(id).value.trim()]));
    const query = filters.q.toLocaleLowerCase();
    return sourceForwardingState.policies.filter(policy => {
        if (policy.mode === 'inherit' || filters.scope && policy.scope_type !== filters.scope || filters.mode && policy.mode !== filters.mode) return false;
        if (filters.channel && !policy.channel_ids.includes(Number(filters.channel))) return false;
        if (!query) return true;
        const source = forwardingPolicySource(policy);
        const targets = policy.channel_ids.map(id => sourceForwardingState.channels.find(channel => channel.id === id)?.name || '');
        return [source?.email, source?.name, policy.match_value, policy.keywords, policy.senders, forwardingScopeLabels[policy.scope_type], ...targets].join(' ').toLocaleLowerCase().includes(query);
    });
}

function changeForwardingPolicyFilters(updateLocation = true) {
    sourceForwardingState.selectedPolicyIds.clear();
    renderForwardingPolicies();
    if (updateLocation && isDedicatedForwardingUI() && typeof window !== 'undefined') {
        const url = new URL(window.location.href);
        for (const [key, id] of Object.entries(forwardingRuleFilterFields)) {
            const value = document.getElementById(id).value.trim();
            if (value) url.searchParams.set('forwarding_rule_' + key, value);
            else url.searchParams.delete('forwarding_rule_' + key);
        }
        window.history.replaceState({}, '', url);
    }
}

function resetForwardingPolicyFilters() {
    Object.values(forwardingRuleFilterFields).forEach(id => { document.getElementById(id).value = ''; });
    changeForwardingPolicyFilters();
}

function updateForwardingPolicySelection(visible = filteredForwardingPolicies()) {
    const count = visible.filter(policy => sourceForwardingState.selectedPolicyIds.has(policy.id)).length;
    const checkbox = document.getElementById('forwardRuleSelectAll');
    checkbox.checked = visible.length > 0 && count === visible.length;
    checkbox.indeterminate = count > 0 && count < visible.length;
    checkbox.disabled = !visible.length;
    document.querySelectorAll('#forwardPolicyList input[data-policy-id]').forEach(input => { input.checked = sourceForwardingState.selectedPolicyIds.has(Number(input.value)); });
    document.getElementById('deleteSelectedForwardingPoliciesBtn').disabled = !count;
    const selected = visible.filter(policy => sourceForwardingState.selectedPolicyIds.has(policy.id));
    const mixed = new Set(selected.map(policy => policy.scope_type)).size > 1;
    document.getElementById('editSelectedForwardingPoliciesBtn').disabled = !count || mixed;
    document.getElementById('editSelectedForwardingPoliciesBtn').title = mixed ? '请选择同一来源范围的规则' : '批量修改所选规则';
    const total = sourceForwardingState.policies.filter(policy => policy.mode !== 'inherit').length;
    document.getElementById('forwardRuleSelectionStatus').textContent = `显示 ${visible.length} / ${total} 条规则，已选 ${count} 条${mixed ? '；同一来源范围可批量编辑' : ''}`;
}

function selectForwardingPolicyRows(selected) {
    const visible = filteredForwardingPolicies();
    visible.forEach(policy => selected ? sourceForwardingState.selectedPolicyIds.add(policy.id) : sourceForwardingState.selectedPolicyIds.delete(policy.id));
    updateForwardingPolicySelection(visible);
}

function toggleForwardingPolicyRow(id, selected) {
    id = Number(id);
    if (filteredForwardingPolicies().some(policy => policy.id === id)) {
        if (selected) sourceForwardingState.selectedPolicyIds.add(id);
        else sourceForwardingState.selectedPolicyIds.delete(id);
    }
    updateForwardingPolicySelection();
}

function renderForwardingPolicies() {
    const visible = filteredForwardingPolicies();
    const visibleIds = new Set(visible.map(policy => policy.id));
    sourceForwardingState.selectedPolicyIds.forEach(id => { if (!visibleIds.has(id)) sourceForwardingState.selectedPolicyIds.delete(id); });
    document.getElementById('forwardPolicyList').innerHTML = visible.map(policy => {
        const targets = policy.channel_ids.map(id => sourceForwardingState.channels.find(c => c.id === id)?.name || '已删除渠道');
        const worker = policy.match_value ? sourceForwardingState.workers.find(w => w.id === policy.scope_id) : null;
        const detail = forwardingScopeLabels[policy.scope_type] + (worker ? '，' + worker.name : '');
        return `<tr><td class="forwarding-selection-cell"><label class="forwarding-selection-control"><input type="checkbox" data-policy-id="${Number(policy.id)}" value="${Number(policy.id)}" aria-label="选择规则：${escapeHtml(forwardingPolicyLabel(policy))}" onchange="toggleForwardingPolicyRow(this.value, this.checked)"></label></td>
            <td><strong>${forwardingCellLabel(forwardingPolicyLabel(policy))}</strong><span class="forwarding-cell-detail">${escapeHtml(detail)}</span></td>
            <td>${policy.mode === 'off' ? '<span class="forwarding-state is-muted">关闭通知</span>' : targets.map(name => `<span class="forwarding-target-name">${escapeHtml(name)}</span>`).join('')}</td>
            <td class="forwarding-rule-conditions">${policy.mode === 'off' ? '—' : `<span>关键词：${escapeHtml(policy.keywords || '不限')}</span><span class="forwarding-cell-detail">发件人：${escapeHtml(policy.senders || '不限')}</span>`}</td>
            <td>${forwardingPolicyActions(policy.id)}</td></tr>`;
    }).join('') || forwardingEmptyRow(5, sourceForwardingState.policies.some(policy => policy.mode !== 'inherit') ? '没有符合条件的规则，请调整或清除筛选。' : '还没有转发规则。先添加通知渠道，再新增来源关联。');
    updateForwardingPolicySelection(visible);
}


function forwardingPolicyActions(id) {
    return '<div class="forwarding-row-actions">' + [
        ['edit', '编辑转发规则', '<path d="m16 3 5 5-12 12H4v-5Z"/><path d="m13 6 5 5"/>'],
        ['remove', '删除转发规则', '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>'],
    ].map(([action, label, paths]) => `<button class="btn btn-secondary forwarding-icon-button${action === 'remove' ? ' forwarding-danger' : ''}" type="button" data-policy-${action}="${Number(id)}" aria-label="${label}" title="${label}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg></button>`).join('') + '</div>';
}
async function deleteForwardingPolicies(ids, button) {
    if (button?.disabled) return;
    ids = [...new Set(ids)].sort((a, b) => a - b);
    await forwardingAction(button, async () => {
        if (!ids.length) throw new Error('请至少选择一条转发规则');
        if (!(await showConfirmModal(`确定删除选中的 ${ids.length} 条转发规则？\n\n只删除所选规则，来源将使用上层配置；删除默认规则后默认不通知。`, {title: '删除转发规则', confirmText: `删除 ${ids.length} 条规则`}))) return;
        await forwardingRequest('/api/forwarding/policies', {method: 'DELETE', body: JSON.stringify({policy_ids: ids})});
        ids.forEach(id => sourceForwardingState.selectedPolicyIds.delete(id));
        await loadSourceForwarding();
    });
    updateForwardingPolicySelection();
}

function deleteSelectedForwardingPolicies(button) {
    return deleteForwardingPolicies(Array.from(sourceForwardingState.selectedPolicyIds), button);
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
        document.getElementById('forwardPolicyPreview').textContent = `${preview.email_address}\n${path}\n${preview.eligible ? (targets ? '通知目标：' + targets : '不发送通知') : preview.reason}\n邮件关键词：${preview.keywords || '不限'}\n来信发件人：${preview.senders || '不限'}`;
    });
}

async function openForwardingSource(scope, id, match = '') {
    await showForwardingManagement('policies');
    const policy = sourceForwardingState.policies.find(p => p.scope_type === scope && p.scope_id === id && p.match_value === match && p.mode !== 'inherit');
    if (policy) return editForwardingPolicies([policy.id]);
    showForwardingPolicyEditor();
    document.getElementById('forwardPolicyScope').value = scope;
    await changeForwardingScope();
    document.getElementById('forwardPolicySource').value = String(id);
    renderForwardingSourcePicker();
    document.getElementById('forwardPolicyMatch').value = match;
    await loadForwardingPolicy();
    document.getElementById('forwardPolicyEditor').scrollIntoView({block: 'start'});
}

async function loadForwardingHistory(offset = 0) {
    const container = document.getElementById('sourceForwardingHistory');
    container.innerHTML = forwardingLoadingRows(4);
    try {
        const params = new URLSearchParams({limit: 50, offset: Math.max(0, offset)});
        for (const [key, id] of [['source_type', 'forwardHistorySource'], ['channel_id', 'forwardHistoryChannel'], ['email_address', 'forwardHistoryAddress'], ['status', 'forwardHistoryState']]) {
            const value = document.getElementById(id).value.trim(); if (value) params.set(key, value);
        }
        if (isDedicatedForwardingUI() && typeof window !== 'undefined') {
            const url = new URL(window.location.href);
            for (const key of ['source_type', 'channel_id', 'email_address', 'status', 'offset']) {
                const value = params.get(key);
                if (value && value !== '0') url.searchParams.set('forwarding_' + key, value);
                else url.searchParams.delete('forwarding_' + key);
            }
            window.history.replaceState({}, '', url);
        }
        const data = await forwardingRequest('/api/forwarding/history?' + params);
        sourceForwardingState.offset = Math.max(0, offset);
        const labels = {succeeded: '成功', success: '成功', failed: '失败', pending: '待发送', blocked: '已阻塞', cancelled: '已取消'};
        const rows = data.history;
        container.innerHTML = rows.map(row => `<tr><td class="forwarding-numeric">${escapeHtml(formatDateTime(new Date(row.updated_at * 1000).toISOString()))}</td>
            <td><strong>${forwardingCellLabel(row.email_address)}</strong><span class="forwarding-cell-detail">${row.source_type === 'cloudflare' ? 'CF / ' + escapeHtml(row.source_name) : '普通邮箱'}</span></td>
            <td>${escapeHtml(row.channel_name)}<span class="forwarding-cell-detail">${escapeHtml(notificationTypeLabels[row.channel_type] || row.channel_type)}</span></td>
            <td><span class="forwarding-state${row.status === 'failed' ? ' is-error' : ''}">${escapeHtml(labels[row.status] || row.status)}</span>${row.error_message ? '<span class="forwarding-cell-detail">' + escapeHtml(row.error_message) + '</span>' : ''}</td></tr>`).join('') || forwardingEmptyRow(4, '没有符合条件的投递记录。可调整筛选条件，或等待新邮件投递。');
        document.getElementById('forwardHistoryPrevious').disabled = sourceForwardingState.offset === 0;
        document.getElementById('forwardHistoryNext').disabled = rows.length < 50;
        document.getElementById('forwardScanStatus').textContent = data.scans.filter(s => s.error_message).map(s => s.worker_name + '：' + s.error_message).join('\n');
    } catch (error) { container.innerHTML = forwardingEmptyRow(4, escapeHtml(error.message || '加载失败，请点击查询重试')); }
}

function changeForwardingHistoryPage(direction) { return loadForwardingHistory(sourceForwardingState.offset + direction * 50); }

const forwardingRuntimeFields = {
    forward_check_interval_seconds: ['forwardCheckIntervalSeconds', 300],
    forward_parallel_workers: ['forwardParallelWorkers', 4],
    forward_account_delay_seconds: ['forwardAccountDelaySeconds', 0],
    forward_email_window_minutes: ['forwardEmailWindowMinutes', 0],
};

async function loadForwardingRuntimeSettings() {
    const status = document.getElementById('forwardingRuntimeStatus');
    status.textContent = '正在加载运行设置…';
    try {
        const {settings} = await forwardingRequest('/api/settings');
        for (const [key, [id, fallback]] of Object.entries(forwardingRuntimeFields)) document.getElementById(id).value = settings[key] ?? fallback;
        document.getElementById('forwardExecutionMode').value = settings.forward_execution_mode === 'parallel' ? 'parallel' : 'serial';
        document.getElementById('forwardIncludeJunkemail').checked = String(settings.forward_include_junkemail) === 'true';
        syncForwardExecutionModeUI();
        status.textContent = '';
    } catch (error) { status.textContent = error.message || '运行设置加载失败，请重新打开页面重试'; }
}

async function saveForwardingRuntimeSettings(button) {
    const form = document.getElementById('forwardingRuntimeForm');
    if (!form.reportValidity()) return;
    await forwardingAction(button, async () => {
        const settings = {};
        for (const [key, [id, fallback]] of Object.entries(forwardingRuntimeFields)) settings[key] = parseInt(document.getElementById(id).value || fallback, 10);
        settings.forward_execution_mode = document.getElementById('forwardExecutionMode').value;
        if (settings.forward_execution_mode === 'parallel') settings.forward_account_delay_seconds = 0;
        settings.forward_include_junkemail = document.getElementById('forwardIncludeJunkemail').checked;
        await forwardingRequest('/api/settings', {method: 'PUT', body: JSON.stringify(settings)});
        document.getElementById('forwardingRuntimeStatus').textContent = '运行设置已保存。';
    });
}

function omitLegacyForwardingFields(settings) {
    if (isDedicatedForwardingUI()) {
        for (const key of ['forward_check_interval_seconds', 'forward_check_interval_minutes', 'forward_execution_mode', 'forward_parallel_workers', 'forward_account_delay_seconds', 'forward_email_window_minutes', 'forward_include_junkemail', 'forward_keywords']) delete settings[key];
    }
    delete settings.forward_channels; delete settings.smtp_provider; delete settings.feishu_clear_sign_secret;
    delete settings.forward_keywords;
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
        const remove = event.target.closest('[data-policy-remove]');
        if (remove) deleteForwardingPolicies([Number(remove.dataset.policyRemove)], remove);
        const edit = event.target.closest('[data-policy-edit]');
        if (edit) editForwardingPolicies([Number(edit.dataset.policyEdit)]);
    });
    console.querySelector('[role="tablist"]').addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        const tabs = Array.from(console.querySelectorAll('[data-forward-tab]'));
        const current = tabs.indexOf(document.activeElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        event.preventDefault(); tabs[next].focus(); showForwardingTab(tabs[next].dataset.forwardTab);
    });
    showForwardingTab('policies', false);
    const restoreWorkspace = () => {
        if (window.location.pathname === '/forwarding') showForwardingManagement(new URL(window.location.href).searchParams.get('forwarding_tab') || 'policies', false);
        else hideForwardingManagement(false);
    };
    window.addEventListener('popstate', restoreWorkspace);
    if (window.location.pathname === '/forwarding') restoreWorkspace();
});
