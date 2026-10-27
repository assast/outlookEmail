/* global escapeHtml, showModal, hideModal, showConfirmModal */

const icloudUI = {accounts: [], mailboxes: [], selected: null, busy: false};
const icElement = id => document.getElementById(id);
const icTime = value => value ? new Date(value * 1000).toLocaleString() : '—';
const icStateLabel = state => ({connected: '管理连接可用', verification_required: '等待验证码',
    signed_out: '未登录', expired: '会话失效', retry: '等待重试', manual_required: '需要人工处理',
    service_pending: '正在建立管理连接', active: '有效', inactive: '已停用', removed: '远端移除', pending: '待核对'}[state] || state);

function icMessage(message, error = false) {
    icElement('icloudMessage').textContent = message;
    icElement('icloudMessage').dataset.error = String(error);
}

async function icRequest(path, method = 'GET', body) {
    const response = await fetch('/api/icloud/accounts' + path, {
        method, headers: {'Content-Type': 'application/json'},
        ...(body === undefined ? {} : {body: JSON.stringify(body)}),
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || 'iCloud 操作失败');
    return data;
}

async function icRun(work) {
    if (icloudUI.busy) return;
    icloudUI.busy = true;
    const buttons = [...icElement('icloudManagementModal').querySelectorAll('button:not(.modal-close)')];
    buttons.forEach(button => {button.disabled = true;});
    icMessage('处理中…');
    try {
        await work();
    } catch (error) {
        icMessage(error.message || '请求失败，请稍后重试', true);
    } finally {
        icloudUI.busy = false;
        icElement('icloudManagementModal').querySelectorAll('button').forEach(button => {button.disabled = false;});
    }
}

function renderICloudState() {
    const e = escapeHtml;
    icElement('icloudAccountList').innerHTML = icloudUI.accounts.length ? icloudUI.accounts.map(account => `
        <button type="button" class="icloud-account" data-ic-action="select" data-id="${account.id}"
            aria-current="${account.id === icloudUI.selected}">${e(account.apple_id)}<br>
            <small>${account.region === 'cn' ? '中国大陆' : '国际区'} · ${account.enabled ? '启用' : '停用'}</small></button>`).join('')
        : '<p class="form-hint">先新增 Apple 主号，再人工登录并同步隐藏地址。收信账号可稍后绑定。</p>';
    const selected = icloudUI.accounts.find(account => account.id === icloudUI.selected);
    icElement('icloudConnectedPanel').hidden = !selected;
    if (!selected) return;
    const mailbox = icloudUI.mailboxes.find(item => item.id === selected.mailbox_account_id);
    icElement('icMailboxState').textContent = selected.binding_lost ? '原收信账号已删除，请重新绑定或显式解除绑定。'
        : mailbox ? `收信绑定：${mailbox.email}（${mailbox.status === 'active' ? '账号启用' : '账号停用'}）。IMAP 是否可收信需在邮箱列表单独验证。`
        : '收信未绑定：可管理 Apple 地址，暂不可在本项目取信。';
    icElement('icloudSessions').innerHTML = selected.sessions.map(row => `<div class="icloud-session">
        <strong>${row.channel === 'web' ? 'iCloud Web' : 'Apple Account'} · ${e(icStateLabel(row.state))}</strong>
        <small>最近成功 ${e(icTime(row.last_success))} · 下次尝试 ${e(icTime(row.next_attempt))}</small>
        <small>最近尝试 ${e(icTime(row.last_attempt))} · 失败次数 ${row.failures} · ${e(row.last_error || '无错误')}</small>
        </div>`).join('');
    icElement('icloudAliases').innerHTML = selected.aliases.map(alias => `<tr>
        <td>${e(alias.address)}<br>${e(alias.label)}<br>${e(alias.note)}</td><td>${e(alias.forward_to || '—')}</td>
        <td>${e(icStateLabel(alias.state))}<br>${e(alias.conflict)}</td><td>
        ${alias.state === 'active' ? `<button class="btn btn-secondary" type="button" data-ic-action="deactivate" data-id="${alias.id}">停用</button>` : ''}
        ${alias.state === 'inactive' ? `<button class="btn btn-secondary" type="button" data-ic-action="delete" data-id="${alias.id}">永久删除</button>` : ''}
        </td></tr>`).join('') || '<tr><td colspan="4">尚无目录。Web 管理连接可用后，点击“同步”。</td></tr>';
}

function editICloudAccount(id) {
    icloudUI.selected = id || null;
    const account = icloudUI.accounts.find(item => item.id === id);
    icElement('icAppleId').value = account?.apple_id || '';
    icElement('icRegion').value = account?.region || 'global';
    icElement('icMailbox').value = account?.mailbox_account_id || '';
    icElement('icRemark').value = account?.remark || '';
    icElement('icEnabled').checked = account ? !!account.enabled : true;
    icElement('icAutoLogin').checked = !!account?.auto_login;
    ['icPassword', 'icCodeUrl', 'icLoginPassword', 'icCode'].forEach(field => {icElement(field).value = '';});
    ['icClearPassword', 'icClearCodeUrl'].forEach(field => {icElement(field).checked = false;});
    icElement('icCredentialFlags').textContent = `密码${account?.password_configured ? '已配置' : '未配置'} · 接码 URL ${account?.code_url_configured ? '已配置' : '未配置'}`;
    renderICloudState();
}

async function loadICloudState() {
    const data = await icRequest('');
    icloudUI.accounts = data.accounts;
    icloudUI.mailboxes = data.mailboxes;
    const binding = icElement('icMailbox').value;
    icElement('icMailbox').innerHTML = '<option value="">不绑定，独立管理</option>' + data.mailboxes.map(item =>
        `<option value="${item.id}">${escapeHtml(item.email)}${item.status === 'active' ? '' : '（停用）'}</option>`).join('');
    icElement('icMailbox').value = binding;
    renderICloudState();
}

async function showICloudManagement() {
    showModal('icloudManagementModal');
    await icRun(async () => {
        await loadICloudState();
        editICloudAccount(icloudUI.selected || icloudUI.accounts[0]?.id);
        icMessage('当前展示本地保存状态。');
    });
}

async function saveICloudAccount(event) {
    event.preventDefault();
    await icRun(async () => {
        const id = icloudUI.selected;
        const data = await icRequest(id ? `/${id}` : '', id ? 'PUT' : 'POST', {
            apple_id: icElement('icAppleId').value, region: icElement('icRegion').value,
            mailbox_account_id: Number(icElement('icMailbox').value) || null,
            remark: icElement('icRemark').value, enabled: icElement('icEnabled').checked,
            auto_login: icElement('icAutoLogin').checked, password: icElement('icPassword').value,
            code_url: icElement('icCodeUrl').value, clear_password: icElement('icClearPassword').checked,
            clear_code_url: icElement('icClearCodeUrl').checked,
        });
        await loadICloudState();
        editICloudAccount(data.account.id);
        icMessage('主号已保存。管理连接与收信状态分别维护。');
    });
}

async function icAction(action, id) {
    if (icloudUI.busy) return;
    if (action === 'select' || action === 'new') {editICloudAccount(action === 'new' ? null : id); return;}
    await icRun(async () => {
        if (action === 'refresh') {await loadICloudState(); icMessage('本地状态已刷新。'); return;}
        const accountId = icloudUI.selected;
        const account = icloudUI.accounts.find(item => item.id === accountId);
        if (!account) throw new Error('请先保存或选择主号');
        if (action === 'delete-main') {
            if (!await showConfirmModal('确认删除本地主号？仅清理本地凭据和托管映射，Apple 地址与收信账号保留。', {title: '删除本地主号'})) return;
            await icRequest(`/${accountId}`, 'DELETE', {confirm: true});
            await loadICloudState(); editICloudAccount(null); icMessage('本地主号已删除。'); return;
        }
        if (['login', 'verify', 'logout'].includes(action)) {
            if (action === 'logout' && !await showConfirmModal(account.auto_login
                ? '自动重登仍开启，退出后将重新登录。确认退出当前会话？' : '确认退出 Apple 会话？', {title: '退出 Apple 会话'})) return;
            const result = await icRequest(`/${accountId}/${action}`, 'POST', {
                channel: icElement('icChannel').value, password: icElement('icLoginPassword').value, code: icElement('icCode').value,
            });
            icElement('icLoginPassword').value = ''; icElement('icCode').value = '';
            await loadICloudState();
            icMessage(result.message || (result.state === 'verification_required' ? 'Apple 要求双重验证，请输入本次验证码。' : '管理连接状态已更新。'));
            return;
        }
        if (action === 'delete' && !await showConfirmModal('永久删除后无法恢复。确认从 Apple 永久删除该已停用地址？', {title: '永久删除隐藏地址'})) return;
        await icRequest(`/${accountId}/aliases`, 'POST', {action, alias_id: id,
            label: icElement('icAliasLabel').value, note: icElement('icAliasNote').value, confirm: action === 'delete'});
        await loadICloudState();
        icMessage('隐藏地址状态已更新。');
    });
}

document.addEventListener('DOMContentLoaded', () => {
    icElement('icloudManagementModal').addEventListener('click', event => {
        const button = event.target.closest('[data-ic-action]');
        if (button) icAction(button.dataset.icAction, Number(button.dataset.id) || null);
    });
});
