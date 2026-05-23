(function () {
  const Storage = window.ExtensionStorage;
  const Api = window.OutlookExtensionApi;

  let currentView = 'mail';
  let busy = false;

  const mailState = {
    groups: [],
    tags: [],
    selectedGroupId: '',
    accountOffset: 0,
    accountLimit: 50,
    accounts: [],
    tempEmails: [],
    currentAccountEmail: '',
    currentEmails: [],
    currentTempEmail: '',
    currentTempMessages: [],
    cloudflareFilter: '',
    cloudflareOffset: 0,
    cloudflareHasMore: false,
    cloudflareEmails: [],
    oauthPreview: null,
  };

  const viewTitles = {
    mail: '邮箱',
    import: '导入',
    refresh: '刷新',
    token: 'Token',
    export: '导出',
    tags: '标签',
    settings: '设置',
  };

  const normalProviders = [
    ['outlook', 'Outlook / Hotmail'],
    ['gmail', 'Gmail'],
    ['qq', 'QQ'],
    ['163', '163'],
    ['126', '126'],
    ['yahoo', 'Yahoo'],
    ['aliyun', '阿里邮箱'],
    ['custom', '自定义 IMAP'],
  ];

  const tempProviders = [
    ['gptmail', 'GPTMail'],
    ['duckmail', 'DuckMail'],
    ['cloudflare', 'Cloudflare'],
  ];

  function getEl(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function valueOf(id) {
    return (getEl(id)?.value ?? '').trim();
  }

  function checked(id) {
    return getEl(id)?.checked === true;
  }

  function toInt(value, fallback = 0) {
    const parsed = Number.parseInt(String(value ?? ''), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function boolSetting(value, fallback = false) {
    if (typeof value === 'boolean') return value;
    const text = String(value ?? '').trim().toLowerCase();
    if (!text) return fallback;
    return ['1', 'true', 'yes', 'on'].includes(text);
  }

  function queryString(params) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && String(value) !== '') {
        query.set(key, String(value));
      }
    });
    return query.toString();
  }

  function pathWithQuery(path, params) {
    const query = queryString(params);
    return query ? `${path}?${query}` : path;
  }

  function encodePath(value) {
    return encodeURIComponent(String(value ?? ''));
  }

  function formatDate(value) {
    if (value === undefined || value === null || value === '') return '';
    try {
      let normalized = value;
      if (typeof value === 'number' || /^\d+$/.test(String(value))) {
        const numeric = Number(value);
        normalized = numeric < 1000000000000 ? numeric * 1000 : numeric;
      }
      const date = new Date(normalized);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString('zh-CN', { hour12: false });
    } catch {
      return String(value);
    }
  }

  function formatBytes(value) {
    const size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return '';
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  function providerLabel(provider) {
    const hit = [...normalProviders, ...tempProviders].find(([key]) => key === provider);
    if (hit) return hit[1];
    return provider || '';
  }

  function renderOptions(options, selectedValue) {
    return options.map(([value, label]) => {
      const selected = String(value) === String(selectedValue) ? ' selected' : '';
      return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
    }).join('');
  }

  function renderTagPills(tags) {
    if (!Array.isArray(tags) || !tags.length) return '';
    return `<div class="tag-line">${tags.map((tag) => `
      <span class="tag-pill" style="--tag-color:${escapeHtml(tag.color || '#64748b')}">${escapeHtml(tag.name || '')}</span>
    `).join('')}</div>`;
  }

  function renderResult(payload) {
    return `<div class="card result-box">${escapeHtml(JSON.stringify(payload, null, 2))}</div>`;
  }

  function readConfig() {
    return {
      serverUrl: Api.trimUrl(getEl('serverUrl').value),
      password: getEl('password').value,
      rememberPassword: getEl('rememberPassword').checked,
    };
  }

  async function saveConfig() {
    const config = readConfig();
    await Storage.setConfig(config);
    return config;
  }

  function showMessage(message, type) {
    const el = getEl('message');
    el.textContent = message || '';
    el.classList.toggle('error', type === 'error');
  }

  function setBusy(isBusy) {
    busy = isBusy;
    getEl('btnLogin').disabled = isBusy;
    getEl('btnReload').disabled = isBusy;
    getEl('btnConfig').disabled = isBusy;
    document.querySelectorAll('.quick-bar button').forEach((button) => {
      button.disabled = isBusy;
    });
  }

  function setContent(html) {
    getEl('viewContent').innerHTML = html;
  }

  function setActiveView(view) {
    currentView = view;
    getEl('viewTitle').textContent = viewTitles[view] || view;
    document.querySelectorAll('.quick-bar button').forEach((button) => {
      button.classList.toggle('active', button.dataset.view === view);
    });
  }

  async function withSession(task, loadingText = '正在登录...') {
    setBusy(true);
    getEl('panelStatus').textContent = loadingText;
    showMessage(loadingText);
    try {
      const config = await saveConfig();
      await Api.ensureSession(config);
      getEl('configPanel').classList.add('collapsed');
      getEl('panelStatus').textContent = config.serverUrl;
      showMessage('');
      return await task(config);
    } catch (error) {
      getEl('panelStatus').textContent = '操作失败';
      showMessage(Api.friendlyError(error), 'error');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function runAction(config, task, loadingText = '正在处理...') {
    setBusy(true);
    getEl('panelStatus').textContent = loadingText;
    showMessage(loadingText);
    try {
      await Api.ensureSession(config);
      const result = await task();
      getEl('panelStatus').textContent = config.serverUrl;
      showMessage('');
      return result;
    } catch (error) {
      getEl('panelStatus').textContent = '操作失败';
      showMessage(Api.friendlyError(error), 'error');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(String(text || ''));
      showMessage('已复制');
    } catch {
      showMessage('复制失败', 'error');
    }
  }

  async function loadGroups(config) {
    const payload = await Api.apiRequest(config, '/api/groups');
    mailState.groups = Array.isArray(payload.groups) ? payload.groups : [];
    return mailState.groups;
  }

  async function loadTags(config) {
    const payload = await Api.apiRequest(config, '/api/tags');
    mailState.tags = Array.isArray(payload.tags) ? payload.tags : [];
    return mailState.tags;
  }

  function groupOptions(groups, selectedId, includeTemp = true) {
    return (groups || [])
      .filter((group) => includeTemp || !isTempEmailGroup(group))
      .map((group) => {
        const selected = String(group.id) === String(selectedId) ? ' selected' : '';
        const count = group.account_count ?? 0;
        return `<option value="${escapeHtml(group.id)}"${selected}>${escapeHtml(group.name)} (${escapeHtml(count)})</option>`;
      }).join('');
  }

  function tagCheckboxes(tags, selectedIds = [], name = 'tagIds') {
    const selected = new Set((selectedIds || []).map((item) => String(item)));
    if (!Array.isArray(tags) || !tags.length) {
      return '<div class="item-meta">暂无标签。</div>';
    }
    return tags.map((tag) => `
      <label class="check-row inline-check">
        <input type="checkbox" name="${escapeHtml(name)}" value="${escapeHtml(tag.id)}" ${selected.has(String(tag.id)) ? 'checked' : ''}>
        <span><span class="tag-dot" style="--tag-color:${escapeHtml(tag.color || '#64748b')}"></span>${escapeHtml(tag.name)}</span>
      </label>
    `).join('');
  }

  async function renderView(view = currentView) {
    setActiveView(view);
    if (view === 'mail') return renderMailView();
    if (view === 'import') return renderImportView();
    if (view === 'refresh') return renderRefreshView();
    if (view === 'token') return renderTokenView();
    if (view === 'export') return renderExportView();
    if (view === 'tags') return renderTagsView();
    if (view === 'settings') return renderSettingsView();
    return null;
  }

  function getSelectedMailGroup(groups = mailState.groups) {
    const groupId = getEl('mailGroupSelect')?.value || mailState.selectedGroupId || '';
    return (groups || []).find((group) => String(group.id) === String(groupId)) || null;
  }

  function isTempEmailGroup(group) {
    return String(group?.name || '').trim() === '临时邮箱';
  }

  function revealMailPanel() {
    getEl('mailEmails')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function revealAccountsPanel() {
    getEl('mailAccounts')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function closeMailActionPanel() {
    const target = getEl('mailEmails');
    if (target) {
      target.innerHTML = '<div class="card muted">选择邮箱后，邮件会显示在这里。</div>';
    }
    revealAccountsPanel();
  }

  async function renderMailView() {
    setContent('<div class="card muted">正在加载分组...</div>');
    await withSession(async (config) => {
      const groups = await loadGroups(config);
      const storedGroupId = await Storage.getSelectedMailGroupId();
      const preferredGroupId = mailState.selectedGroupId || storedGroupId;
      if (preferredGroupId && groups.some((group) => String(group.id) === String(preferredGroupId))) {
        mailState.selectedGroupId = String(preferredGroupId);
      } else {
        mailState.selectedGroupId = String(groups[0]?.id || '');
        await Storage.setSelectedMailGroupId(mailState.selectedGroupId);
      }
      setContent(`
        <div class="card">
          <label><span>分组</span><select id="mailGroupSelect">${groupOptions(groups, mailState.selectedGroupId)}</select></label>
          <label><span>搜索</span><input id="accountSearch" placeholder="邮箱、备注、标签或别名"></label>
          <div class="toolbar wrap">
            <button id="btnAccountSearch" class="secondary-btn" type="button">搜索</button>
            <button id="btnNewGroup" class="secondary-btn" type="button">新增分组</button>
            <button id="btnEditGroup" class="secondary-btn" type="button">编辑分组</button>
            <button id="btnDeleteGroup" class="danger-btn" type="button">删除分组</button>
            <button id="btnGroupUp" class="small-btn" type="button">上移</button>
            <button id="btnGroupDown" class="small-btn" type="button">下移</button>
          </div>
        </div>
        <div id="mailEmails" class="mail-result-panel">
          <div class="card muted">选择邮箱后，邮件会显示在这里。</div>
        </div>
        <div id="mailAccounts" class="list"></div>
      `);
      getEl('mailGroupSelect').addEventListener('change', async () => {
        mailState.selectedGroupId = getEl('mailGroupSelect').value;
        mailState.accountOffset = 0;
        await Storage.setSelectedMailGroupId(mailState.selectedGroupId);
        runAction(config, () => loadMailAccounts(config, groups), '正在加载账号...');
      });
      getEl('btnAccountSearch').addEventListener('click', () => {
        mailState.accountOffset = 0;
        runAction(config, () => loadMailAccounts(config, groups), '正在搜索账号...');
      });
      getEl('accountSearch').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          mailState.accountOffset = 0;
          runAction(config, () => loadMailAccounts(config, groups), '正在搜索账号...');
        }
      });
      getEl('btnNewGroup').addEventListener('click', () => showGroupEditor(config));
      getEl('btnEditGroup').addEventListener('click', () => showGroupEditor(config, getSelectedMailGroup(groups)));
      getEl('btnDeleteGroup').addEventListener('click', () => deleteSelectedGroup(config));
      getEl('btnGroupUp').addEventListener('click', () => moveSelectedGroup(config, -1));
      getEl('btnGroupDown').addEventListener('click', () => moveSelectedGroup(config, 1));
      await loadMailAccounts(config, groups);
    }, '正在加载邮箱...');
  }

  async function showGroupEditor(config, group = null) {
    const target = getEl('mailEmails');
    if (group && isTempEmailGroup(group)) {
      target.innerHTML = '<div class="card muted">临时邮箱是系统分组，不能编辑。</div>';
      return;
    }
    const isEdit = !!group;
    target.innerHTML = `
      <div class="card">
        <div class="item-title">${isEdit ? '编辑分组' : '新增分组'}</div>
        <label><span>名称</span><input id="groupName" value="${escapeHtml(group?.name || '')}"></label>
        <label><span>说明</span><textarea id="groupDescription">${escapeHtml(group?.description || '')}</textarea></label>
        <div class="row">
          <label><span>颜色</span><input id="groupColor" type="color" value="${escapeHtml(group?.color || '#1a1a1a')}"></label>
          <label><span>排序位置</span><input id="groupSortPosition" type="number" min="1" value="${escapeHtml(group?.sort_position || '')}"></label>
        </div>
        <label><span>代理地址</span><input id="groupProxyUrl" value="${escapeHtml(group?.proxy_url || '')}"></label>
        <label><span>备用代理 1</span><input id="groupFallbackProxy1" value="${escapeHtml(group?.fallback_proxy_url_1 || '')}"></label>
        <label><span>备用代理 2</span><input id="groupFallbackProxy2" value="${escapeHtml(group?.fallback_proxy_url_2 || '')}"></label>
        <div class="toolbar">
          <button id="btnSaveGroup" class="primary-btn" type="button">保存分组</button>
          <button id="btnCancelGroup" class="secondary-btn" type="button">取消</button>
        </div>
      </div>
      <div id="groupEditorResult"></div>
    `;
    revealMailPanel();
    getEl('btnCancelGroup').addEventListener('click', closeMailActionPanel);
    getEl('btnSaveGroup').addEventListener('click', () => runAction(config, async () => {
      const body = {
        name: valueOf('groupName'),
        description: valueOf('groupDescription'),
        color: valueOf('groupColor') || '#1a1a1a',
        proxy_url: valueOf('groupProxyUrl'),
        fallback_proxy_url_1: valueOf('groupFallbackProxy1'),
        fallback_proxy_url_2: valueOf('groupFallbackProxy2'),
        sort_position: valueOf('groupSortPosition'),
      };
      const payload = await Api.apiRequest(config, isEdit ? `/api/groups/${group.id}` : '/api/groups', {
        method: isEdit ? 'PUT' : 'POST',
        body,
      });
      getEl('groupEditorResult').innerHTML = renderResult(payload);
      await loadGroups(config);
      renderMailView();
    }, '正在保存分组...'));
  }

  async function deleteSelectedGroup(config) {
    const group = getSelectedMailGroup();
    if (!group) return;
    if (isTempEmailGroup(group)) {
      getEl('mailEmails').innerHTML = '<div class="card muted">临时邮箱是系统分组，不能删除。</div>';
      return;
    }
    if (!window.confirm(`确定删除分组「${group.name}」吗？账号会移到默认分组。`)) return;
    await runAction(config, async () => {
      await Api.apiRequest(config, `/api/groups/${group.id}`, { method: 'DELETE' });
      mailState.selectedGroupId = '';
      renderMailView();
    }, '正在删除分组...');
  }

  async function moveSelectedGroup(config, delta) {
    const group = getSelectedMailGroup();
    if (!group || isTempEmailGroup(group)) return;
    const movable = mailState.groups.filter((item) => !isTempEmailGroup(item));
    const index = movable.findIndex((item) => String(item.id) === String(group.id));
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= movable.length) return;
    const ids = movable.map((item) => item.id);
    [ids[index], ids[nextIndex]] = [ids[nextIndex], ids[index]];
    await runAction(config, async () => {
      await Api.apiRequest(config, '/api/groups/reorder', {
        method: 'PUT',
        body: { group_ids: ids.map((item) => Number(item)) },
      });
      await renderMailView();
    }, '正在调整分组...');
  }

  async function loadMailAccounts(config, groups) {
    const selectedGroup = getSelectedMailGroup(groups);
    const target = getEl('mailAccounts');
    const emailTarget = getEl('mailEmails');
    if (emailTarget) {
      emailTarget.innerHTML = '<div class="card muted">选择邮箱后，邮件会显示在这里。</div>';
    }
    target.innerHTML = '<div class="card muted">正在加载账号...</div>';

    if (isTempEmailGroup(selectedGroup)) {
      await loadTempEmailAccounts(config, target);
      return;
    }

    const q = valueOf('accountSearch');
    const endpoint = q
      ? pathWithQuery('/api/accounts/search', {
        q,
        group_id: selectedGroup?.id || '',
        limit: mailState.accountLimit,
        offset: mailState.accountOffset,
      })
      : pathWithQuery('/api/accounts', {
        group_id: selectedGroup?.id || '',
        limit: mailState.accountLimit,
        offset: mailState.accountOffset,
      });
    const payload = await Api.apiRequest(config, endpoint);
    const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
    mailState.accounts = accounts;
    if (!accounts.length) {
      target.innerHTML = '<div class="card muted">该分组暂无账号。</div>';
      return;
    }
    const pager = `
      <div class="toolbar wrap">
        <button id="btnPrevAccounts" class="small-btn" type="button" ${mailState.accountOffset <= 0 ? 'disabled' : ''}>上一页</button>
        <button id="btnNextAccounts" class="small-btn" type="button" ${payload.has_more ? '' : 'disabled'}>下一页</button>
        <span class="item-meta">共 ${escapeHtml(payload.total ?? accounts.length)} 个，当前 ${escapeHtml(mailState.accountOffset + 1)}-${escapeHtml(mailState.accountOffset + accounts.length)}</span>
      </div>
    `;
    target.innerHTML = `${pager}${accounts.map((account, index) => {
      const forwardLabel = account.forward_enabled ? '关闭转发' : '开启转发';
      const aliases = Array.isArray(account.aliases) && account.aliases.length ? ` · 别名 ${account.aliases.length}` : '';
      const refreshStatus = account.last_refresh_status ? ` · Token ${account.last_refresh_status}` : '';
      const remark = account.remark ? ` · ${account.remark}` : '';
      return `
        <div class="item" data-account-index="${escapeHtml(index)}">
          <div class="item-title">${escapeHtml(account.email)}</div>
          <div class="item-meta">ID ${escapeHtml(account.id)} · ${escapeHtml(providerLabel(account.provider || account.account_type))} · ${escapeHtml(account.status || '')}${escapeHtml(aliases)}${escapeHtml(refreshStatus)}${escapeHtml(remark)}</div>
          ${renderTagPills(account.tags)}
          <div class="item-actions account-actions">
            <button class="small-btn" type="button" data-action="view-mails" data-email="${escapeHtml(account.email)}">邮件</button>
            <select class="account-action-select" data-account-menu data-account-id="${escapeHtml(account.id)}" data-email="${escapeHtml(account.email)}" data-label="${escapeHtml(account.email)}" data-forward="${account.forward_enabled ? '1' : '0'}" aria-label="${escapeHtml(account.email)} 更多操作">
              <option value="">更多操作</option>
              <option value="edit-account">编辑</option>
              <option value="tag-account">标签</option>
              <option value="toggle-forward">${escapeHtml(forwardLabel)}</option>
              <option value="refresh-account">刷新 Token</option>
              <option value="copy">复制</option>
              <option value="delete-account">删除</option>
            </select>
          </div>
        </div>
      `;
    }).join('')}`;
    getEl('btnPrevAccounts')?.addEventListener('click', () => {
      mailState.accountOffset = Math.max(0, mailState.accountOffset - mailState.accountLimit);
      runAction(config, () => loadMailAccounts(config, groups), '正在加载上一页...');
    });
    getEl('btnNextAccounts')?.addEventListener('click', () => {
      mailState.accountOffset += mailState.accountLimit;
      runAction(config, () => loadMailAccounts(config, groups), '正在加载下一页...');
    });
    target.querySelectorAll('[data-action]').forEach((button) => {
      button.addEventListener('click', () => handleAccountAction(config, button));
    });
    target.querySelectorAll('[data-account-menu]').forEach((select) => {
      select.addEventListener('change', () => handleAccountMenuChange(config, select));
    });
  }

  async function handleAccountMenuChange(config, select) {
    const selectedAction = select?.value || '';
    select.value = '';
    if (!selectedAction) {
      showMessage('');
      return null;
    }
    return handleAccountAction(config, {
      dataset: {
        action: selectedAction,
        accountId: select.dataset.accountId,
        email: select.dataset.email,
        label: select.dataset.label,
        forward: select.dataset.forward,
        copy: select.dataset.email,
      },
    });
  }

  async function handleAccountAction(config, button) {
    const action = button.dataset.action;
    if (action === 'copy') return copyText(button.dataset.copy || '');
    if (action === 'view-mails') {
      return runAction(config, () => loadAccountEmails(config, button.dataset.email), '正在加载邮件...');
    }
    if (action === 'edit-account') return showAccountEditor(config, button.dataset.accountId);
    if (action === 'tag-account') return showTagAssignment(config, 'account', button.dataset.accountId, button.dataset.label || '');
    if (action === 'toggle-forward') {
      const enable = button.dataset.forward !== '1';
      return runAction(config, async () => {
        await Api.apiRequest(config, '/api/accounts/batch-update-forwarding', {
          method: 'POST',
          body: { account_ids: [Number(button.dataset.accountId)], forward_enabled: enable },
        });
        await loadMailAccounts(config, mailState.groups);
      }, '正在更新转发状态...');
    }
    if (action === 'refresh-account') {
      return runAction(config, async () => {
        const payload = await Api.apiRequest(config, `/api/accounts/${button.dataset.accountId}/refresh`, {
          method: 'POST',
          timeoutMs: 70000,
        });
        getEl('mailEmails').innerHTML = renderResult(payload);
        revealMailPanel();
        await loadMailAccounts(config, mailState.groups);
      }, '正在刷新 Token...');
    }
    if (action === 'delete-account') {
      if (!window.confirm(`确定删除账号 ${button.dataset.label || ''} 吗？`)) return null;
      return runAction(config, async () => {
        await Api.apiRequest(config, `/api/accounts/${button.dataset.accountId}`, { method: 'DELETE' });
        await loadMailAccounts(config, mailState.groups);
      }, '正在删除账号...');
    }
    return null;
  }

  async function showAccountEditor(config, accountId) {
    await runAction(config, async () => {
      const [accountPayload, groups] = await Promise.all([
        Api.apiRequest(config, `/api/accounts/${accountId}`),
        loadGroups(config),
      ]);
      const account = accountPayload.account || {};
      const provider = account.provider || account.account_type || 'outlook';
      const aliases = Array.isArray(account.aliases) ? account.aliases.join('\n') : '';
      getEl('mailEmails').innerHTML = `
        <div class="card">
          <div class="item-title">编辑账号</div>
          <label><span>邮箱</span><input id="editEmail" value="${escapeHtml(account.email || '')}"></label>
          <label><span>账号密码</span><input id="editPassword" value="${escapeHtml(account.password || '')}"></label>
          <div class="row">
            <label><span>类型</span><select id="editProvider">${renderOptions(normalProviders, provider)}</select></label>
            <label><span>分组</span><select id="editGroup">${groupOptions(groups, account.group_id, false)}</select></label>
          </div>
          <label><span>Client ID</span><input id="editClientId" value="${escapeHtml(account.client_id || '')}"></label>
          <label><span>Refresh Token</span><textarea id="editRefreshToken">${escapeHtml(account.refresh_token || '')}</textarea></label>
          <div id="editImapFields">
            <div class="row">
              <label><span>IMAP 主机</span><input id="editImapHost" value="${escapeHtml(account.imap_host || '')}"></label>
              <label><span>IMAP 端口</span><input id="editImapPort" type="number" value="${escapeHtml(account.imap_port || 993)}"></label>
            </div>
            <label><span>IMAP 密码</span><input id="editImapPassword" value="${escapeHtml(account.imap_password || '')}"></label>
          </div>
          <div class="row">
            <label><span>状态</span><select id="editStatus">${renderOptions([['active', 'active'], ['inactive', 'inactive']], account.status || 'active')}</select></label>
            <label><span>排序值</span><input id="editSortOrder" type="number" value="${escapeHtml(account.sort_order ?? '')}"></label>
          </div>
          <label><span>备注</span><input id="editRemark" value="${escapeHtml(account.remark || '')}"></label>
          <label><span>别名</span><textarea id="editAliases" placeholder="每行一个别名">${escapeHtml(aliases)}</textarea></label>
          <label class="check-row"><input id="editForwardEnabled" type="checkbox" ${account.forward_enabled ? 'checked' : ''}><span>开启转发</span></label>
          <div class="toolbar wrap">
            <button id="btnSaveAccount" class="primary-btn" type="button">保存账号</button>
            <button id="btnOnlyStatusActive" class="secondary-btn" type="button">设为 active</button>
            <button id="btnOnlyStatusInactive" class="secondary-btn" type="button">设为 inactive</button>
            <button id="btnCancelAccountEditor" class="secondary-btn" type="button">取消</button>
          </div>
        </div>
        <div id="accountEditorResult"></div>
      `;
      revealMailPanel();
      function updateImapVisibility() {
        const selectedProvider = valueOf('editProvider');
        getEl('editImapFields').classList.toggle('hidden', selectedProvider === 'outlook');
      }
      getEl('editProvider').addEventListener('change', updateImapVisibility);
      updateImapVisibility();
      getEl('btnSaveAccount').addEventListener('click', () => runAction(config, async () => {
        const selectedProvider = valueOf('editProvider');
        const isOutlook = selectedProvider === 'outlook';
        const body = {
          email: valueOf('editEmail'),
          password: valueOf('editPassword'),
          client_id: valueOf('editClientId'),
          refresh_token: valueOf('editRefreshToken'),
          account_type: isOutlook ? 'outlook' : 'imap',
          provider: selectedProvider,
          imap_host: valueOf('editImapHost'),
          imap_port: toInt(valueOf('editImapPort'), 993),
          imap_password: valueOf('editImapPassword'),
          group_id: Number(valueOf('editGroup')),
          sort_order: valueOf('editSortOrder'),
          remark: valueOf('editRemark'),
          status: valueOf('editStatus') || 'active',
          forward_enabled: checked('editForwardEnabled'),
          aliases: valueOf('editAliases').split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean),
        };
        const payload = await Api.apiRequest(config, `/api/accounts/${accountId}`, {
          method: 'PUT',
          body,
        });
        getEl('accountEditorResult').innerHTML = renderResult(payload);
        await loadMailAccounts(config, mailState.groups);
      }, '正在保存账号...'));
      getEl('btnOnlyStatusActive').addEventListener('click', () => updateAccountStatus(config, accountId, 'active'));
      getEl('btnOnlyStatusInactive').addEventListener('click', () => updateAccountStatus(config, accountId, 'inactive'));
      getEl('btnCancelAccountEditor').addEventListener('click', closeMailActionPanel);
    }, '正在加载账号详情...');
  }

  async function updateAccountStatus(config, accountId, status) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, `/api/accounts/${accountId}`, {
        method: 'PUT',
        body: { status },
      });
      getEl('accountEditorResult').innerHTML = renderResult(payload);
      await loadMailAccounts(config, mailState.groups);
    }, '正在更新状态...');
  }

  async function showTagAssignment(config, type, id, label) {
    await runAction(config, async () => {
      const tags = await loadTags(config);
      const endpoint = type === 'temp' ? '/api/temp-emails/tags' : '/api/accounts/tags';
      const idKey = type === 'temp' ? 'temp_email_ids' : 'account_ids';
      getEl('mailEmails').innerHTML = `
        <div class="card">
          <div class="item-title">标签：${escapeHtml(label)}</div>
          <label><span>标签</span><select id="assignTagId">${tags.map((tag) => `<option value="${escapeHtml(tag.id)}">${escapeHtml(tag.name)}</option>`).join('')}</select></label>
          <div class="toolbar wrap">
            <button id="btnAddAssignedTag" class="primary-btn" type="button">添加标签</button>
            <button id="btnRemoveAssignedTag" class="secondary-btn" type="button">移除标签</button>
            <button id="btnCancelTagAssignment" class="secondary-btn" type="button">取消</button>
          </div>
        </div>
        <div id="tagAssignResult"></div>
      `;
      revealMailPanel();
      async function submit(action) {
        await runAction(config, async () => {
          const payload = await Api.apiRequest(config, endpoint, {
            method: 'POST',
            body: { [idKey]: [Number(id)], tag_id: Number(valueOf('assignTagId')), action },
          });
          getEl('tagAssignResult').innerHTML = renderResult(payload);
          await loadMailAccounts(config, mailState.groups);
        }, '正在更新标签...');
      }
      getEl('btnAddAssignedTag').addEventListener('click', () => submit('add'));
      getEl('btnRemoveAssignedTag').addEventListener('click', () => submit('remove'));
      getEl('btnCancelTagAssignment').addEventListener('click', closeMailActionPanel);
    }, '正在加载标签...');
  }

  async function loadTempEmailAccounts(config, target) {
    target.innerHTML = '<div class="card muted">正在加载临时邮箱...</div>';
    const payload = await Api.apiRequest(config, '/api/temp-emails');
    const emails = Array.isArray(payload.emails) ? payload.emails : [];
    mailState.tempEmails = emails;
    const filter = getEl('tempProviderFilter')?.value || 'all';
    const search = (getEl('tempEmailSearch')?.value || '').trim().toLowerCase();
    const filtered = emails.filter((item) => {
      const providerOk = filter === 'all' || item.provider === filter;
      const haystack = [
        item.email,
        item.provider,
        ...(Array.isArray(item.tags) ? item.tags.map((tag) => tag.name) : []),
      ].join('\n').toLowerCase();
      return providerOk && (!search || haystack.includes(search));
    });
    const showCloudflareGlobal = (filter === 'all' || filter === 'cloudflare')
      && (!search || 'cloudflare所有邮件'.includes(search) || 'cloudflare all messages'.includes(search));

    target.innerHTML = `
      <div class="card">
        <div class="row">
          <label><span>渠道</span><select id="tempProviderFilter">${renderOptions([['all', '全部'], ...tempProviders], filter)}</select></label>
          <label><span>搜索</span><input id="tempEmailSearch" value="${escapeHtml(search)}" placeholder="临时邮箱或标签"></label>
        </div>
        <div class="toolbar wrap">
          <button id="btnFilterTempEmails" class="secondary-btn" type="button">筛选</button>
          <button id="btnGoTempImport" class="secondary-btn" type="button">导入/生成</button>
        </div>
      </div>
      ${showCloudflareGlobal ? `
        <div class="item cloudflare-entry">
          <div class="item-title">Cloudflare所有邮件</div>
          <div class="item-meta">查看当前 Worker 中的全部邮件，可按收件地址过滤。</div>
          <div class="item-actions">
            <button class="small-btn" type="button" data-temp-action="cloudflare-global">查看全部</button>
          </div>
        </div>
      ` : ''}
      ${filtered.length ? filtered.map((item) => {
        const provider = providerLabel(item.provider || 'gptmail');
        return `
          <div class="item">
            <div class="item-title">${escapeHtml(item.email)}</div>
            <div class="item-meta">ID ${escapeHtml(item.id)} · ${escapeHtml(provider)} · 临时邮箱</div>
            ${renderTagPills(item.tags)}
            <div class="item-actions wrap">
              <button class="small-btn" type="button" data-temp-action="view" data-id="${escapeHtml(item.id)}" data-email="${escapeHtml(item.email)}">邮件</button>
              <button class="small-btn" type="button" data-temp-action="refresh" data-email="${escapeHtml(item.email)}">刷新</button>
              <button class="small-btn" type="button" data-temp-action="tag" data-id="${escapeHtml(item.id)}" data-email="${escapeHtml(item.email)}">标签</button>
              <button class="small-btn" type="button" data-temp-action="copy" data-copy="${escapeHtml(item.email)}">复制</button>
              <button class="danger-btn" type="button" data-temp-action="delete" data-id="${escapeHtml(item.id)}" data-email="${escapeHtml(item.email)}">删除</button>
            </div>
          </div>
        `;
      }).join('') : (!showCloudflareGlobal ? '<div class="card muted">暂无临时邮箱。</div>' : '')}
    `;
    getEl('tempProviderFilter').addEventListener('change', () => {
      runAction(config, () => loadTempEmailAccounts(config, target), '正在筛选临时邮箱...');
    });
    getEl('btnFilterTempEmails').addEventListener('click', () => {
      runAction(config, () => loadTempEmailAccounts(config, target), '正在筛选临时邮箱...');
    });
    getEl('tempEmailSearch').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        runAction(config, () => loadTempEmailAccounts(config, target), '正在搜索临时邮箱...');
      }
    });
    getEl('btnGoTempImport').addEventListener('click', () => renderView('import'));
    target.querySelectorAll('[data-temp-action]').forEach((button) => {
      button.addEventListener('click', () => handleTempEmailAction(config, button));
    });
  }

  async function handleTempEmailAction(config, button) {
    const action = button.dataset.tempAction;
    if (action === 'copy') return copyText(button.dataset.copy || '');
    if (action === 'cloudflare-global') {
      return runAction(config, () => loadCloudflareGlobalMessages(config, false), '正在加载 Cloudflare 所有邮件...');
    }
    if (action === 'view') {
      return runAction(config, () => loadTempEmailMessages(config, button.dataset.email), '正在加载临时邮箱邮件...');
    }
    if (action === 'refresh') {
      return runAction(config, async () => {
        const payload = await Api.apiRequest(config, `/api/temp-emails/${encodePath(button.dataset.email)}/refresh`, {
          method: 'POST',
          timeoutMs: 70000,
        });
        getEl('mailEmails').innerHTML = renderResult(payload);
        revealMailPanel();
      }, '正在刷新临时邮箱...');
    }
    if (action === 'tag') return showTagAssignment(config, 'temp', button.dataset.id, button.dataset.email || '');
    if (action === 'delete') {
      if (!window.confirm(`确定删除临时邮箱 ${button.dataset.email || ''} 吗？`)) return null;
      return runAction(config, async () => {
        await Api.apiRequest(config, `/api/temp-emails/${encodePath(button.dataset.email)}`, { method: 'DELETE' });
        await loadTempEmailAccounts(config, getEl('mailAccounts'));
      }, '正在删除临时邮箱...');
    }
    return null;
  }

  async function loadAccountEmails(config, email) {
    mailState.currentAccountEmail = email;
    const target = getEl('mailEmails');
    const folder = getEl('mailFolder')?.value || 'all';
    const keyword = valueOf('mailKeyword');
    const subject = valueOf('mailSubject');
    const from = valueOf('mailFrom');
    target.innerHTML = `<div class="card muted">正在加载 ${escapeHtml(email)} 的邮件...</div>`;
    revealMailPanel();
    const payload = await Api.apiRequest(config, pathWithQuery(`/api/emails/${encodePath(email)}`, {
      folder,
      top: 30,
      skip: 0,
      keyword,
      subject_contains: subject,
      from_contains: from,
    }), { timeoutMs: 70000 });
    const emails = Array.isArray(payload.emails) ? payload.emails : [];
    mailState.currentEmails = emails;
    target.innerHTML = `
      <div class="card">
        <div class="item-title">${escapeHtml(email)}</div>
        <div class="item-meta">${escapeHtml(payload.method || '')} · 最近 ${emails.length} 封邮件${payload.matched_alias ? ` · 命中别名 ${escapeHtml(payload.matched_alias)}` : ''}</div>
        <div class="row">
          <label><span>文件夹</span><select id="mailFolder">${renderOptions([
        ['all', '全部'],
        ['inbox', '收件箱'],
        ['junkemail', '垃圾邮件'],
        ['deleteditems', '已删除'],
      ], folder)}</select></label>
          <label><span>关键词</span><input id="mailKeyword" value="${escapeHtml(keyword)}"></label>
        </div>
        <div class="row">
          <label><span>主题包含</span><input id="mailSubject" value="${escapeHtml(subject)}"></label>
          <label><span>发件人包含</span><input id="mailFrom" value="${escapeHtml(from)}"></label>
        </div>
        <div class="toolbar">
          <button id="btnReloadMails" class="secondary-btn" type="button">刷新邮件</button>
          <button id="btnBackToAccounts" class="secondary-btn" type="button">返回账号列表</button>
        </div>
      </div>
      <div class="list">
        ${emails.length ? emails.map((item, index) => `
          <div class="item ${item.is_read === false ? 'unread' : ''}">
            <div class="item-title">${escapeHtml(item.subject || '无主题')}</div>
            <div class="item-meta">${escapeHtml(item.from || '')} · ${escapeHtml(formatDate(item.date))} · ${escapeHtml(item.folder || folder)}${item.has_attachments ? ' · 有附件' : ''}</div>
            <div class="item-meta">${escapeHtml(item.body_preview || '')}</div>
            <div class="item-actions wrap">
              <button class="small-btn" type="button" data-mail-action="detail" data-index="${escapeHtml(index)}">详情</button>
              <button class="small-btn" type="button" data-mail-action="mark-read" data-index="${escapeHtml(index)}">已读</button>
              <button class="danger-btn" type="button" data-mail-action="delete" data-index="${escapeHtml(index)}">删除</button>
            </div>
          </div>
        `).join('') : '<div class="card muted">没有邮件。</div>'}
      </div>
      <div id="mailDetail"></div>
    `;
    getEl('btnReloadMails').addEventListener('click', () => {
      runAction(config, () => loadAccountEmails(config, email), '正在刷新邮件...');
    });
    getEl('btnBackToAccounts').addEventListener('click', revealAccountsPanel);
    target.querySelectorAll('[data-mail-action]').forEach((button) => {
      button.addEventListener('click', () => handleMailAction(config, button));
    });
  }

  function getMailActionItem(button) {
    const index = toInt(button.dataset.index, -1);
    return mailState.currentEmails[index] || null;
  }

  function getMailItemMethod(item) {
    const idMode = String(item?.id_mode || '').toLowerCase();
    if (idMode && idMode !== 'graph') return 'imap';
    return item?.method || 'graph';
  }

  async function handleMailAction(config, button) {
    const item = getMailActionItem(button);
    if (!item) return null;
    const action = button.dataset.mailAction;
    const email = mailState.currentAccountEmail;
    const folder = item.folder || getEl('mailFolder')?.value || 'inbox';
    if (action === 'detail') {
      return runAction(config, async () => {
        const payload = await Api.apiRequest(config, pathWithQuery(`/api/email/${encodePath(email)}/${encodePath(item.id)}`, {
          folder,
          method: getMailItemMethod(item),
        }), { timeoutMs: 70000 });
        renderEmailDetail(config, 'mailDetail', {
          type: 'normal',
          email,
          item,
          folder,
          method: getMailItemMethod(item),
        }, payload.email || {});
      }, '正在加载邮件详情...');
    }
    if (action === 'mark-read') {
      return markNormalMailRead(config, email, item, folder);
    }
    if (action === 'delete') {
      return deleteNormalMail(config, email, item);
    }
    return null;
  }

  async function markNormalMailRead(config, email, item, folder) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/emails/mark-read', {
        method: 'POST',
        body: {
          email,
          method: getMailItemMethod(item),
          folder,
          items: [{
            id: item.id,
            folder,
            id_mode: item.id_mode || (getMailItemMethod(item) === 'imap' ? 'uid' : 'graph'),
          }],
        },
        timeoutMs: 70000,
      });
      getEl('mailDetail').innerHTML = renderResult(payload);
    }, '正在标记已读...');
  }

  async function deleteNormalMail(config, email, item) {
    if (!window.confirm('确定删除这封邮件吗？')) return;
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/emails/delete', {
        method: 'POST',
        body: { email, ids: [item.id] },
        timeoutMs: 70000,
      });
      getEl('mailDetail').innerHTML = renderResult(payload);
      await loadAccountEmails(config, email);
    }, '正在删除邮件...');
  }

  async function loadTempEmailMessages(config, email) {
    mailState.currentTempEmail = email;
    const target = getEl('mailEmails');
    target.innerHTML = `<div class="card muted">正在加载 ${escapeHtml(email)} 的临时邮件...</div>`;
    revealMailPanel();
    const payload = await Api.apiRequest(config, `/api/temp-emails/${encodePath(email)}/messages`, { timeoutMs: 70000 });
    const emails = Array.isArray(payload.emails) ? payload.emails : [];
    mailState.currentTempMessages = emails;
    target.innerHTML = `
      <div class="card">
        <div class="item-title">${escapeHtml(email)}</div>
        <div class="item-meta">${escapeHtml(payload.method || '临时邮箱')} · 最近 ${emails.length} 封邮件</div>
        <div class="toolbar wrap">
          <button id="btnRefreshTempMessages" class="secondary-btn" type="button">刷新邮件</button>
          <button id="btnBackToAccounts" class="secondary-btn" type="button">返回账号列表</button>
        </div>
      </div>
      <div class="list">
        ${emails.length ? emails.map((item, index) => `
          <div class="item">
            <div class="item-title">${escapeHtml(item.subject || '无主题')}</div>
            <div class="item-meta">${escapeHtml(item.from || '')} · ${escapeHtml(formatDate(item.date || item.timestamp))}</div>
            <div class="item-meta">${escapeHtml(item.body_preview || '')}</div>
            <div class="item-actions">
              <button class="small-btn" type="button" data-temp-mail-detail="${escapeHtml(index)}">详情</button>
            </div>
          </div>
        `).join('') : '<div class="card muted">没有邮件。</div>'}
      </div>
      <div id="tempMailDetail"></div>
    `;
    getEl('btnRefreshTempMessages').addEventListener('click', () => runAction(config, async () => {
      await Api.apiRequest(config, `/api/temp-emails/${encodePath(email)}/refresh`, { method: 'POST', timeoutMs: 70000 });
      await loadTempEmailMessages(config, email);
    }, '正在刷新临时邮件...'));
    getEl('btnBackToAccounts').addEventListener('click', revealAccountsPanel);
    target.querySelectorAll('[data-temp-mail-detail]').forEach((button) => {
      button.addEventListener('click', () => loadTempEmailDetail(config, email, toInt(button.dataset.tempMailDetail, -1)));
    });
  }

  async function loadTempEmailDetail(config, email, index) {
    const item = mailState.currentTempMessages[index];
    if (!item) return;
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, `/api/temp-emails/${encodePath(email)}/messages/${encodePath(item.id)}`, {
        timeoutMs: 70000,
      });
      renderEmailDetail(config, 'tempMailDetail', { type: 'temp', email, item }, payload.email || {});
    }, '正在加载临时邮件详情...');
  }

  async function loadCloudflareGlobalMessages(config, append) {
    const target = getEl('mailEmails');
    if (!append) {
      mailState.cloudflareFilter = valueOf('cloudflareAddressFilter') || mailState.cloudflareFilter || '';
      mailState.cloudflareOffset = 0;
      mailState.cloudflareHasMore = false;
      mailState.cloudflareEmails = [];
      target.innerHTML = '<div class="card muted">正在加载 Cloudflare 所有邮件...</div>';
      revealMailPanel();
    }

    const payload = await Api.apiRequest(config, pathWithQuery('/api/cloudflare/messages', {
      limit: 50,
      offset: mailState.cloudflareOffset,
      address: mailState.cloudflareFilter,
    }), { timeoutMs: 70000 });

    const emails = Array.isArray(payload.emails) ? payload.emails : [];
    mailState.cloudflareEmails = append ? mailState.cloudflareEmails.concat(emails) : emails;
    mailState.cloudflareHasMore = payload.has_more === true;
    mailState.cloudflareOffset = Number(payload.offset || 0) + Number(payload.limit || 50);
    renderCloudflareGlobalPanel(config, payload);
  }

  function renderCloudflareGlobalPanel(config, payload = {}) {
    const target = getEl('mailEmails');
    const emails = mailState.cloudflareEmails;
    const queried = payload.queried_email && payload.fallback_used ? ` · 实际查询 ${payload.queried_email}` : '';
    target.innerHTML = `
      <div class="card">
        <div class="item-title">Cloudflare所有邮件</div>
        <div class="item-meta">已加载 ${escapeHtml(emails.length)} / ${escapeHtml(payload.total_count ?? emails.length)}${escapeHtml(queried)}</div>
        <label><span>收件地址过滤</span><input id="cloudflareAddressFilter" value="${escapeHtml(mailState.cloudflareFilter)}" placeholder="user@example.com"></label>
        <div class="toolbar wrap">
          <button id="btnApplyCloudflareFilter" class="secondary-btn" type="button">查询</button>
          <button id="btnClearCloudflareFilter" class="secondary-btn" type="button">全部</button>
          <button id="btnMoreCloudflareMessages" class="secondary-btn" type="button" ${mailState.cloudflareHasMore ? '' : 'disabled'}>加载更多</button>
          <button id="btnBackToAccounts" class="secondary-btn" type="button">返回账号列表</button>
        </div>
      </div>
      <div class="list">
        ${emails.length ? emails.map((item, index) => `
          <div class="item">
            <div class="item-title">${escapeHtml(item.subject || '无主题')}</div>
            <div class="item-meta">${escapeHtml(item.from || '')} → ${escapeHtml(item.to || '')} · ${escapeHtml(formatDate(item.date || item.timestamp))}</div>
            <div class="item-meta">${escapeHtml(item.body_preview || '')}</div>
            <div class="item-actions">
              <button class="small-btn" type="button" data-cf-detail="${escapeHtml(index)}">详情</button>
              <button class="small-btn" type="button" data-cf-copy="${escapeHtml(item.to || '')}">复制收件人</button>
            </div>
          </div>
        `).join('') : '<div class="card muted">没有邮件。</div>'}
      </div>
      <div id="cloudflareMailDetail"></div>
    `;
    getEl('btnApplyCloudflareFilter').addEventListener('click', () => {
      mailState.cloudflareFilter = valueOf('cloudflareAddressFilter');
      runAction(config, () => loadCloudflareGlobalMessages(config, false), '正在加载 Cloudflare 所有邮件...');
    });
    getEl('btnClearCloudflareFilter').addEventListener('click', () => {
      mailState.cloudflareFilter = '';
      runAction(config, () => loadCloudflareGlobalMessages(config, false), '正在加载 Cloudflare 所有邮件...');
    });
    getEl('btnMoreCloudflareMessages').addEventListener('click', () => {
      runAction(config, () => loadCloudflareGlobalMessages(config, true), '正在加载更多 Cloudflare 邮件...');
    });
    getEl('btnBackToAccounts').addEventListener('click', revealAccountsPanel);
    target.querySelectorAll('[data-cf-detail]').forEach((button) => {
      button.addEventListener('click', () => {
        const item = mailState.cloudflareEmails[toInt(button.dataset.cfDetail, -1)];
        if (!item) return;
        renderEmailDetail(config, 'cloudflareMailDetail', { type: 'cloudflare', item }, item);
      });
    });
    target.querySelectorAll('[data-cf-copy]').forEach((button) => {
      button.addEventListener('click', () => copyText(button.dataset.cfCopy || ''));
    });
  }

  function renderEmailDetail(config, targetId, context, email) {
    const target = getEl(targetId);
    const attachmentLinks = Array.isArray(email.attachments) && email.attachments.length
      ? email.attachments.map((attachment) => {
        const folder = context.folder || 'inbox';
        const method = context.method || 'graph';
        const href = `${Api.trimUrl(config.serverUrl)}/api/email/${encodePath(context.email)}/${encodePath(email.id || context.item?.id)}/attachments/${encodePath(attachment.id)}?${queryString({ folder, method })}`;
        return `<a class="small-btn attachment-link" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(attachment.name || '附件')} ${escapeHtml(formatBytes(attachment.size))}</a>`;
      }).join('')
      : '';
    const normalActions = context.type === 'normal' ? `
      <div class="toolbar wrap">
        <button id="${targetId}MarkRead" class="secondary-btn" type="button">标记已读</button>
        <button id="${targetId}Raw" class="secondary-btn" type="button">源码</button>
        <button id="${targetId}Delete" class="danger-btn" type="button">删除邮件</button>
      </div>
    ` : '';
    target.innerHTML = `
      <div class="card detail-card">
        <div class="item-title">${escapeHtml(email.subject || '无主题')}</div>
        <div class="item-meta">From: ${escapeHtml(email.from || '')}</div>
        <div class="item-meta">To: ${escapeHtml(email.to || context.email || '')}</div>
        ${email.cc ? `<div class="item-meta">Cc: ${escapeHtml(email.cc)}</div>` : ''}
        <div class="item-meta">${escapeHtml(formatDate(email.date || email.timestamp))}</div>
        ${normalActions}
        ${attachmentLinks ? `<div class="attachment-list">${attachmentLinks}</div>` : ''}
        <div id="${targetId}Body" class="mail-body"></div>
      </div>
    `;
    renderBodyContent(`${targetId}Body`, email.body || '', email.body_type || (email.has_html ? 'html' : 'text'));
    if (context.type === 'normal') {
      getEl(`${targetId}MarkRead`).addEventListener('click', () => markNormalMailRead(config, context.email, context.item, context.folder || 'inbox'));
      getEl(`${targetId}Delete`).addEventListener('click', () => deleteNormalMail(config, context.email, context.item));
      getEl(`${targetId}Raw`).addEventListener('click', () => loadRawEmail(config, targetId, context));
    }
  }

  function renderBodyContent(targetId, body, bodyType) {
    const target = getEl(targetId);
    if (!target) return;
    target.textContent = '';
    if (String(bodyType || '').toLowerCase() === 'html') {
      const iframe = document.createElement('iframe');
      iframe.className = 'mail-frame';
      iframe.setAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox');
      iframe.srcdoc = `<!doctype html><meta charset="utf-8"><base target="_blank"><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;line-height:1.5;color:#172033;margin:12px;overflow-wrap:anywhere}img{max-width:100%;height:auto}</style>${body || ''}`;
      target.appendChild(iframe);
      return;
    }
    const pre = document.createElement('pre');
    pre.className = 'text-mail-body';
    pre.textContent = body || '';
    target.appendChild(pre);
  }

  async function loadRawEmail(config, targetId, context) {
    await runAction(config, async () => {
      const text = await Api.apiTextRequest(config, pathWithQuery(`/api/email/${encodePath(context.email)}/${encodePath(context.item.id)}/raw`, {
        folder: context.folder || 'inbox',
        method: context.method || 'graph',
      }), { timeoutMs: 70000 });
      renderBodyContent(`${targetId}Body`, text, 'text');
    }, '正在加载源码...');
  }

  async function renderImportView() {
    setContent('<div class="card muted">正在加载导入工具...</div>');
    await withSession(async (config) => {
      const [groups, tags] = await Promise.all([loadGroups(config), loadTags(config)]);
      const defaultGroupId = groups.find((group) => !isTempEmailGroup(group))?.id || groups[0]?.id || '';
      setContent(`
        <div class="card">
          <label><span>导入对象</span><select id="importMode">${renderOptions([['normal', '普通邮箱'], ['temp', '临时邮箱']], 'normal')}</select></label>
          <div id="normalImportFields">
            <label><span>目标分组</span><select id="importGroup">${groupOptions(groups, defaultGroupId, false)}</select></label>
            <div class="row">
              <label><span>邮箱类型</span><select id="importProvider">${renderOptions(normalProviders, 'outlook')}</select></label>
              <label><span>Outlook 格式</span><select id="importFormat">${renderOptions([
        ['client_id_refresh_token', 'ClientID 在前'],
        ['refresh_token_client_id', 'RefreshToken 在前'],
      ], 'client_id_refresh_token')}</select></label>
            </div>
            <div id="customImapImportFields" class="hidden">
              <div class="row">
                <label><span>IMAP 主机</span><input id="importImapHost"></label>
                <label><span>IMAP 端口</span><input id="importImapPort" type="number" value="993"></label>
              </div>
            </div>
            <div class="row">
              <label><span>统一备注</span><input id="importRemark"></label>
              <label><span>状态</span><select id="importStatus">${renderOptions([['active', 'active'], ['inactive', 'inactive']], 'active')}</select></label>
            </div>
            <label class="check-row"><input id="importForward" type="checkbox"><span>导入后开启转发</span></label>
            <div class="compact-box">
              <div class="item-meta">导入时绑定标签</div>
              ${tagCheckboxes(tags, [], 'importTagIds')}
            </div>
          </div>
          <div id="tempImportFields" class="hidden">
            <label><span>临时邮箱渠道</span><select id="tempImportProvider">${renderOptions(tempProviders, 'gptmail')}</select></label>
          </div>
          <label><span>账号内容</span><textarea id="importText" placeholder="每行一个账号"></textarea></label>
          <button id="btnImportSubmit" class="primary-btn" type="button">导入</button>
        </div>
        <div class="card">
          <div class="item-title">生成临时邮箱</div>
          <div class="row">
            <label><span>渠道</span><select id="generateProvider">${renderOptions(tempProviders, 'gptmail')}</select></label>
            <label><span>域名</span><select id="generateDomain"></select></label>
          </div>
          <div class="row">
            <label><span>用户名 / 前缀</span><input id="generateUsername"></label>
            <label><span>密码</span><input id="generatePassword" type="password"></label>
          </div>
          <div class="toolbar">
            <button id="btnLoadTempDomains" class="secondary-btn" type="button">刷新域名</button>
            <button id="btnGenerateTempEmail" class="primary-btn" type="button">生成</button>
          </div>
        </div>
        <div id="importResult"></div>
      `);
      function updateImportMode() {
        const mode = valueOf('importMode');
        getEl('normalImportFields').classList.toggle('hidden', mode !== 'normal');
        getEl('tempImportFields').classList.toggle('hidden', mode !== 'temp');
      }
      function updateProviderFields() {
        getEl('customImapImportFields').classList.toggle('hidden', valueOf('importProvider') !== 'custom');
      }
      getEl('importMode').addEventListener('change', updateImportMode);
      getEl('importProvider').addEventListener('change', updateProviderFields);
      updateImportMode();
      updateProviderFields();
      getEl('btnImportSubmit').addEventListener('click', () => submitImport(config));
      getEl('generateProvider').addEventListener('change', () => loadTempDomains(config));
      getEl('btnLoadTempDomains').addEventListener('click', () => loadTempDomains(config));
      getEl('btnGenerateTempEmail').addEventListener('click', () => generateTempEmail(config));
      await loadTempDomains(config);
    }, '正在加载导入...');
  }

  async function submitImport(config) {
    await runAction(config, async () => {
      const mode = valueOf('importMode');
      const result = getEl('importResult');
      result.innerHTML = '<div class="card muted">正在导入...</div>';
      if (mode === 'temp') {
        const payload = await Api.apiRequest(config, '/api/temp-emails/import', {
          method: 'POST',
          body: {
            provider: valueOf('tempImportProvider'),
            account_string: valueOf('importText'),
          },
          timeoutMs: 70000,
        });
        result.innerHTML = renderResult(payload);
        return;
      }
      const tagIds = Array.from(document.querySelectorAll('[name="importTagIds"]:checked')).map((item) => Number(item.value));
      const payload = await Api.apiRequest(config, '/api/accounts', {
        method: 'POST',
        body: {
          group_id: Number(valueOf('importGroup')),
          provider: valueOf('importProvider'),
          account_format: valueOf('importFormat'),
          account_string: valueOf('importText'),
          imap_host: valueOf('importImapHost'),
          imap_port: toInt(valueOf('importImapPort'), 993),
          forward_enabled: checked('importForward'),
          remark: valueOf('importRemark'),
          status: valueOf('importStatus') || 'active',
          tag_ids: tagIds,
        },
        timeoutMs: 70000,
      });
      result.innerHTML = renderResult(payload);
    }, '正在导入账号...');
  }

  async function loadTempDomains(config) {
    const provider = valueOf('generateProvider') || 'gptmail';
    const select = getEl('generateDomain');
    if (!select) return;
    select.innerHTML = '<option value="">默认</option>';
    if (provider === 'gptmail') return;
    await runAction(config, async () => {
      const endpoint = provider === 'duckmail' ? '/api/duckmail/domains' : '/api/cloudflare/domains';
      const payload = await Api.apiRequest(config, endpoint, { timeoutMs: 70000 });
      const domains = Array.isArray(payload.domains) ? payload.domains : [];
      select.innerHTML = '<option value="">默认</option>' + domains.map((item) => {
        const domain = item.domain || item;
        return `<option value="${escapeHtml(domain)}">${escapeHtml(domain)}</option>`;
      }).join('');
    }, '正在加载域名...');
  }

  async function generateTempEmail(config) {
    await runAction(config, async () => {
      const provider = valueOf('generateProvider') || 'gptmail';
      const body = { provider };
      const username = valueOf('generateUsername');
      const domain = valueOf('generateDomain');
      if (provider === 'gptmail') {
        body.prefix = username;
        body.domain = domain;
      } else if (provider === 'duckmail') {
        body.username = username;
        body.domain = domain;
        body.password = valueOf('generatePassword');
      } else if (provider === 'cloudflare') {
        body.username = username;
        body.domain = domain;
      }
      const payload = await Api.apiRequest(config, '/api/temp-emails/generate', {
        method: 'POST',
        body,
        timeoutMs: 70000,
      });
      getEl('importResult').innerHTML = renderResult(payload);
    }, '正在生成临时邮箱...');
  }

  async function renderRefreshView() {
    setContent('<div class="card muted">正在加载刷新状态...</div>');
    await withSession(async (config) => {
      const status = getEl('refreshStatusFilter')?.value || 'all';
      const q = valueOf('refreshSearch');
      const payload = await Api.apiRequest(config, pathWithQuery('/api/accounts/refresh-status-list', {
        q,
        status,
        page: 1,
        page_size: 80,
      }));
      const accounts = Array.isArray(payload.items) ? payload.items : (Array.isArray(payload.accounts) ? payload.accounts : []);
      const stats = payload.stats || {};
      setContent(`
        <div class="card">
          <div class="item-title">刷新统计</div>
          <div class="item-meta">总数 ${escapeHtml(stats.total ?? payload.total ?? 0)} · 成功 ${escapeHtml(stats.success_count ?? 0)} · 失败 ${escapeHtml(stats.failed_count ?? 0)} · 从不 ${escapeHtml(stats.never_count ?? 0)} · 状态 ${escapeHtml(stats.last_refresh_status || 'idle')}</div>
          <div class="row">
            <label><span>状态</span><select id="refreshStatusFilter">${renderOptions([['all', '全部'], ['success', '成功'], ['failed', '失败'], ['never', '从未刷新']], status)}</select></label>
            <label><span>搜索</span><input id="refreshSearch" value="${escapeHtml(q)}"></label>
          </div>
          <div class="toolbar wrap">
            <button id="btnFilterRefresh" class="secondary-btn" type="button">筛选</button>
            <button id="btnRefreshAll" class="primary-btn" type="button">全量刷新</button>
            <button id="btnRefreshFailedStream" class="secondary-btn" type="button">流式重试失败</button>
            <button id="btnRefreshFailed" class="secondary-btn" type="button">快速重试失败</button>
            <button id="btnStopRefresh" class="danger-btn" type="button">停止全量刷新</button>
            <button id="btnLoadRefreshLogs" class="secondary-btn" type="button">刷新日志</button>
            <button id="btnLoadFailedRefreshLogs" class="secondary-btn" type="button">失败列表</button>
          </div>
        </div>
        <div id="refreshStreamLog" class="card result-box"></div>
        <div id="refreshList" class="list">
          ${accounts.map((account) => `
            <div class="item">
              <div class="item-title">${escapeHtml(account.email)}</div>
              <div class="item-meta">ID ${escapeHtml(account.id)} · 状态 ${escapeHtml(account.last_refresh_status || 'never')} · ${escapeHtml(formatDate(account.last_refresh_at))}</div>
              ${account.last_refresh_error ? `<div class="item-meta status-bad">${escapeHtml(account.last_refresh_error)}</div>` : ''}
              <div class="item-actions wrap">
                <button class="small-btn" type="button" data-refresh-action="refresh" data-id="${escapeHtml(account.id)}">刷新此账号</button>
                <button class="small-btn" type="button" data-refresh-action="retry" data-id="${escapeHtml(account.id)}">重试</button>
                <button class="small-btn" type="button" data-refresh-action="logs" data-id="${escapeHtml(account.id)}">日志</button>
              </div>
            </div>
          `).join('') || '<div class="card muted">没有可刷新的账号。</div>'}
        </div>
      `);
      getEl('btnFilterRefresh').addEventListener('click', () => renderRefreshView());
      getEl('refreshStatusFilter').addEventListener('change', () => renderRefreshView());
      getEl('refreshSearch').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') renderRefreshView();
      });
      getEl('btnRefreshAll').addEventListener('click', () => startRefreshStream(config, '/api/accounts/refresh-all'));
      getEl('btnRefreshFailedStream').addEventListener('click', () => startRefreshStream(config, '/api/accounts/refresh-failed-stream'));
      getEl('btnRefreshFailed').addEventListener('click', () => runAction(config, async () => {
        const result = await Api.apiRequest(config, '/api/accounts/refresh-failed', { method: 'POST', timeoutMs: 10 * 60 * 1000 });
        getEl('refreshStreamLog').textContent = JSON.stringify(result, null, 2);
        await renderRefreshView();
      }, '正在重试失败账号...'));
      getEl('btnStopRefresh').addEventListener('click', () => runAction(config, async () => {
        const result = await Api.apiRequest(config, '/api/accounts/stop-full-refresh', { method: 'POST' });
        getEl('refreshStreamLog').textContent = JSON.stringify(result, null, 2);
      }, '正在停止刷新...'));
      getEl('btnLoadRefreshLogs').addEventListener('click', () => loadRefreshLogs(config, false));
      getEl('btnLoadFailedRefreshLogs').addEventListener('click', () => loadRefreshLogs(config, true));
      getEl('refreshList').querySelectorAll('[data-refresh-action]').forEach((button) => {
        button.addEventListener('click', () => handleRefreshAccountAction(config, button));
      });
    }, '正在加载刷新...');
  }

  async function startRefreshStream(config, path) {
    await runAction(config, async () => {
      const log = getEl('refreshStreamLog');
      log.textContent = '';
      await Api.apiStreamRequest(config, path, (event) => {
        const type = event.type || 'message';
        const line = `[${type}] ${event.email || event.message || ''} ${event.current ? `${event.current}/${event.total}` : ''} 成功:${event.success_count ?? ''} 失败:${event.failed_count ?? ''}`;
        log.textContent += `${line}\n`;
        log.scrollTop = log.scrollHeight;
      }, { timeoutMs: 30 * 60 * 1000 });
      await renderRefreshView();
    }, '正在执行刷新...');
  }

  async function handleRefreshAccountAction(config, button) {
    const accountId = button.dataset.id;
    const action = button.dataset.refreshAction;
    if (action === 'logs') return loadRefreshLogs(config, false, accountId);
    const endpoint = action === 'retry' ? `/api/accounts/${accountId}/retry-refresh` : `/api/accounts/${accountId}/refresh`;
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, endpoint, { method: 'POST', timeoutMs: 70000 });
      getEl('refreshStreamLog').textContent = JSON.stringify(payload, null, 2);
      await renderRefreshView();
    }, '正在刷新账号...');
  }

  async function loadRefreshLogs(config, failedOnly, accountId = '') {
    await runAction(config, async () => {
      const endpoint = accountId
        ? `/api/accounts/${accountId}/refresh-logs?limit=30`
        : (failedOnly ? '/api/accounts/refresh-logs/failed' : '/api/accounts/refresh-logs?limit=50');
      const payload = await Api.apiRequest(config, endpoint);
      const logs = Array.isArray(payload.logs) ? payload.logs : [];
      getEl('refreshStreamLog').textContent = logs.map((log) => {
        return `${log.created_at || ''} ${log.account_email || ''} ${log.status || ''} ${log.error_message || ''}`;
      }).join('\n') || '暂无日志';
    }, '正在加载刷新日志...');
  }

  async function renderTokenView() {
    setContent('<div class="card muted">正在加载 Token 工具...</div>');
    await withSession(async (config) => {
      const [authPayload, groups] = await Promise.all([
        Api.apiRequest(config, '/api/oauth/auth-url'),
        loadGroups(config),
      ]);
      const defaultGroup = groups.find((group) => !isTempEmailGroup(group))?.id || '';
      mailState.oauthPreview = null;
      setContent(`
        <div class="card">
          <div class="item-title">OAuth 授权链接</div>
          <div class="item-meta">Client ID: ${escapeHtml(authPayload.client_id || '')}</div>
          <textarea id="authUrlText" readonly>${escapeHtml(authPayload.auth_url || '')}</textarea>
          <div class="toolbar">
            <button id="btnCopyAuthUrl" class="secondary-btn" type="button">复制授权链接</button>
          </div>
        </div>
        <div class="card">
          <div class="row">
            <label><span>邮箱</span><input id="oauthEmailInput"></label>
            <label><span>账号密码</span><input id="oauthPasswordInput" type="password"></label>
          </div>
          <label><span>保存到分组</span><select id="tokenSaveGroup">${groupOptions(groups, defaultGroup, false)}</select></label>
          <label class="check-row"><input id="oauthForwardEnabled" type="checkbox"><span>保存后开启转发</span></label>
          <label><span>授权后完整回调 URL</span><textarea id="redirectedUrl" placeholder="粘贴浏览器地址栏中的完整 URL"></textarea></label>
          <div class="toolbar wrap">
            <button id="btnExchangeToken" class="secondary-btn" type="button">换取并预览</button>
            <button id="btnSaveTokenAccount" class="primary-btn" type="button">保存账号</button>
          </div>
        </div>
        <div id="tokenResult"></div>
      `);
      getEl('btnCopyAuthUrl').addEventListener('click', () => copyText(getEl('authUrlText').value));
      getEl('btnExchangeToken').addEventListener('click', () => exchangeToken(config));
      getEl('btnSaveTokenAccount').addEventListener('click', () => saveTokenAccount(config));
      ['oauthEmailInput', 'oauthPasswordInput', 'tokenSaveGroup', 'oauthForwardEnabled', 'redirectedUrl'].forEach((id) => {
        const el = getEl(id);
        el?.addEventListener('input', () => { mailState.oauthPreview = null; });
        el?.addEventListener('change', () => { mailState.oauthPreview = null; });
      });
    }, '正在加载 Token...');
  }

  async function exchangeToken(config) {
    return runAction(config, async () => {
      return exchangeTokenPayload(config);
    }, '正在换取 Token...');
  }

  async function exchangeTokenPayload(config) {
    const tokenPayload = await Api.apiRequest(config, '/api/oauth/exchange-token', {
      method: 'POST',
      body: { redirected_url: valueOf('redirectedUrl') },
      timeoutMs: 70000,
    });
    if (tokenPayload.success) {
      mailState.oauthPreview = {
        email: valueOf('oauthEmailInput'),
        password: valueOf('oauthPasswordInput'),
        client_id: tokenPayload.client_id,
        refresh_token: tokenPayload.refresh_token,
        group_id: Number(valueOf('tokenSaveGroup')),
        forward_enabled: checked('oauthForwardEnabled'),
      };
    }
    getEl('tokenResult').innerHTML = renderResult(tokenPayload);
    return tokenPayload;
  }

  async function saveTokenAccount(config) {
    await runAction(config, async () => {
      if (!mailState.oauthPreview) {
        await exchangeTokenPayload(config);
      }
      const preview = mailState.oauthPreview;
      if (!preview || !preview.email || !preview.password || !preview.client_id || !preview.refresh_token) {
        throw new Error('保存账号前需要填写邮箱、密码并成功换取 Token');
      }
      const accountString = [preview.email, preview.password, preview.client_id, preview.refresh_token].join('----');
      const payload = await Api.apiRequest(config, '/api/accounts', {
        method: 'POST',
        body: {
          account_string: accountString,
          group_id: preview.group_id,
          provider: 'outlook',
          forward_enabled: preview.forward_enabled,
        },
        timeoutMs: 70000,
      });
      getEl('tokenResult').innerHTML = renderResult(payload);
    }, '正在保存账号...');
  }

  async function renderExportView() {
    setContent('<div class="card muted">正在加载导出...</div>');
    await withSession(async (config) => {
      const groups = await loadGroups(config);
      setContent(`
        <div class="card">
          <label><span>二次验证密码</span><input id="exportPassword" type="password" placeholder="输入 Web 登录密码"></label>
          <div class="toolbar wrap">
            <button id="btnCheckAllExportGroups" class="secondary-btn" type="button">全选分组</button>
            <button id="btnClearExportGroups" class="secondary-btn" type="button">清空</button>
          </div>
          <div class="list">
            ${groups.map((group) => `
              <label class="check-row">
                <input type="checkbox" name="exportGroup" value="${escapeHtml(group.id)}">
                <span>${escapeHtml(group.name)} (${escapeHtml(group.account_count ?? 0)})</span>
              </label>
            `).join('')}
          </div>
          <div class="toolbar wrap">
            <button id="btnExportAll" class="primary-btn" type="button">导出全部</button>
            <button id="btnExportSelected" class="secondary-btn" type="button">导出选中</button>
            <button id="btnCopyExportResult" class="secondary-btn" type="button">复制结果</button>
          </div>
        </div>
        <textarea id="exportResult" class="result-box" readonly placeholder="导出内容会显示在这里"></textarea>
      `);
      async function getVerifyToken() {
        const verify = await Api.apiRequest(config, '/api/export/verify', {
          method: 'POST',
          body: { password: valueOf('exportPassword') },
        });
        return verify.verify_token;
      }
      getEl('btnCheckAllExportGroups').addEventListener('click', () => {
        document.querySelectorAll('[name="exportGroup"]').forEach((item) => { item.checked = true; });
      });
      getEl('btnClearExportGroups').addEventListener('click', () => {
        document.querySelectorAll('[name="exportGroup"]').forEach((item) => { item.checked = false; });
      });
      getEl('btnExportAll').addEventListener('click', () => runAction(config, async () => {
        const token = await getVerifyToken();
        getEl('exportResult').value = await Api.apiTextRequest(config, `/api/accounts/export?verify_token=${encodeURIComponent(token)}`, {
          timeoutMs: 70000,
        });
      }, '正在导出全部...'));
      getEl('btnExportSelected').addEventListener('click', () => runAction(config, async () => {
        const token = await getVerifyToken();
        const groupIds = Array.from(document.querySelectorAll('[name="exportGroup"]:checked')).map((item) => Number(item.value));
        getEl('exportResult').value = await Api.apiTextRequest(config, '/api/accounts/export-selected', {
          method: 'POST',
          body: { group_ids: groupIds, verify_token: token },
          timeoutMs: 70000,
        });
      }, '正在导出选中分组...'));
      getEl('btnCopyExportResult').addEventListener('click', () => copyText(getEl('exportResult').value));
    }, '正在加载导出...');
  }

  async function renderTagsView() {
    setContent('<div class="card muted">正在加载标签...</div>');
    await withSession(async (config) => {
      const tags = await loadTags(config);
      setContent(`
        <div class="card row">
          <input id="tagName" placeholder="标签名">
          <input id="tagColor" type="color" value="#1a1a1a">
          <button id="btnAddTag" class="primary-btn" type="button">新增</button>
        </div>
        <div class="card">
          <div class="item-title">批量绑定</div>
          <div class="row">
            <label><span>对象</span><select id="batchTagTarget">${renderOptions([['account', '普通账号'], ['temp', '临时邮箱']], 'account')}</select></label>
            <label><span>标签</span><select id="batchTagId">${tags.map((tag) => `<option value="${escapeHtml(tag.id)}">${escapeHtml(tag.name)}</option>`).join('')}</select></label>
          </div>
          <label><span>ID 列表</span><textarea id="batchTagIds" placeholder="多个 ID 用逗号或换行分隔"></textarea></label>
          <div class="toolbar">
            <button id="btnBatchAddTag" class="secondary-btn" type="button">添加</button>
            <button id="btnBatchRemoveTag" class="secondary-btn" type="button">移除</button>
          </div>
        </div>
        <div id="tagList" class="list">
          ${tags.map((tag) => `
            <div class="item">
              <div class="item-title"><span class="tag-dot" style="--tag-color:${escapeHtml(tag.color || '#1a1a1a')}"></span> ${escapeHtml(tag.name)}</div>
              <div class="item-meta">ID ${escapeHtml(tag.id)}</div>
              <div class="item-actions">
                <button class="danger-btn" type="button" data-tag-id="${escapeHtml(tag.id)}">删除</button>
              </div>
            </div>
          `).join('') || '<div class="card muted">暂无标签。</div>'}
        </div>
        <div id="tagsResult"></div>
      `);
      getEl('btnAddTag').addEventListener('click', () => runAction(config, async () => {
        await Api.apiRequest(config, '/api/tags', {
          method: 'POST',
          body: { name: valueOf('tagName'), color: valueOf('tagColor') },
        });
        renderTagsView();
      }, '正在新增标签...'));
      async function batchTag(action) {
        await runAction(config, async () => {
          const ids = valueOf('batchTagIds').split(/[\s,，]+/).map((item) => Number(item)).filter(Boolean);
          const type = valueOf('batchTagTarget');
          const endpoint = type === 'temp' ? '/api/temp-emails/tags' : '/api/accounts/tags';
          const idKey = type === 'temp' ? 'temp_email_ids' : 'account_ids';
          const payload = await Api.apiRequest(config, endpoint, {
            method: 'POST',
            body: { [idKey]: ids, tag_id: Number(valueOf('batchTagId')), action },
          });
          getEl('tagsResult').innerHTML = renderResult(payload);
        }, '正在批量更新标签...');
      }
      getEl('btnBatchAddTag').addEventListener('click', () => batchTag('add'));
      getEl('btnBatchRemoveTag').addEventListener('click', () => batchTag('remove'));
      getEl('tagList').querySelectorAll('[data-tag-id]').forEach((button) => {
        button.addEventListener('click', () => runAction(config, async () => {
          await Api.apiRequest(config, `/api/tags/${button.dataset.tagId}`, { method: 'DELETE' });
          renderTagsView();
        }, '正在删除标签...'));
      });
    }, '正在加载标签...');
  }

  async function renderSettingsView() {
    setContent('<div class="card muted">正在加载设置...</div>');
    await withSession(async (config) => {
      const payload = await Api.apiRequest(config, '/api/settings');
      const settings = payload.settings || {};
      setContent(`
        <div class="card">
          <div class="item-title">基础与刷新</div>
          <div class="row">
            <label><span>应用时区</span><input id="settingTimezone" value="${escapeHtml(settings.app_timezone || 'Asia/Shanghai')}"></label>
            <label><span>刷新周期（天）</span><input id="settingRefreshDays" type="number" min="1" max="90" value="${escapeHtml(settings.refresh_interval_days || '30')}"></label>
          </div>
          <div class="row">
            <label><span>刷新间隔（秒）</span><input id="settingRefreshDelay" type="number" min="0" max="60" value="${escapeHtml(settings.refresh_delay_seconds || '0')}"></label>
            <label><span>Cron</span><input id="settingRefreshCron" value="${escapeHtml(settings.refresh_cron || '0 0 */15 * *')}"></label>
          </div>
          <label class="check-row"><input id="settingUseCron" type="checkbox" ${boolSetting(settings.use_cron_schedule) ? 'checked' : ''}><span>使用 Cron 调度</span></label>
          <label class="check-row"><input id="settingScheduledRefresh" type="checkbox" ${boolSetting(settings.enable_scheduled_refresh) ? 'checked' : ''}><span>开启定时刷新</span></label>
          <label class="check-row"><input id="settingShowCreated" type="checkbox" ${boolSetting(settings.show_account_created_at, true) ? 'checked' : ''}><span>显示账号创建时间</span></label>
          <label class="check-row"><input id="settingShowSort" type="checkbox" ${boolSetting(settings.show_account_sort_order) ? 'checked' : ''}><span>显示账号排序值</span></label>
          <label class="check-row"><input id="settingShowGroupId" type="checkbox" ${boolSetting(settings.show_group_id, true) ? 'checked' : ''}><span>显示分组 ID</span></label>
        </div>
        <div class="card">
          <div class="item-title">临时邮箱服务</div>
          <label><span>GPTMail API Key</span><input id="settingGptmailKey" value="${escapeHtml(settings.gptmail_api_key || '')}"></label>
          <label><span>DuckMail API 地址</span><input id="settingDuckmailBaseUrl" value="${escapeHtml(settings.duckmail_base_url || '')}"></label>
          <label><span>DuckMail API Key</span><input id="settingDuckmailApiKey" value="${escapeHtml(settings.duckmail_api_key || '')}"></label>
          <label><span>Cloudflare Worker 域名</span><input id="settingCloudflareWorkerDomain" value="${escapeHtml(settings.cloudflare_worker_domain || '')}"></label>
          <label><span>Cloudflare 邮箱域名</span><input id="settingCloudflareEmailDomains" value="${escapeHtml(settings.cloudflare_email_domains || '')}"></label>
          <label><span>Cloudflare 管理密码</span><input id="settingCloudflareAdminPassword" type="password" value="${escapeHtml(settings.cloudflare_admin_password || '')}"></label>
        </div>
        <div class="card">
          <div class="item-title">转发</div>
          <div class="inline-checks">
            <label class="check-row"><input name="settingForwardChannel" value="smtp" type="checkbox" ${Array.isArray(settings.forward_channels) && settings.forward_channels.includes('smtp') ? 'checked' : ''}><span>SMTP</span></label>
            <label class="check-row"><input name="settingForwardChannel" value="telegram" type="checkbox" ${Array.isArray(settings.forward_channels) && settings.forward_channels.includes('telegram') ? 'checked' : ''}><span>Telegram</span></label>
            <label class="check-row"><input name="settingForwardChannel" value="wecom" type="checkbox" ${Array.isArray(settings.forward_channels) && settings.forward_channels.includes('wecom') ? 'checked' : ''}><span>企业微信</span></label>
          </div>
          <div class="row">
            <label><span>检查间隔（分钟）</span><input id="settingForwardCheckInterval" type="number" value="${escapeHtml(settings.forward_check_interval_minutes || '5')}"></label>
            <label><span>账号间隔（秒）</span><input id="settingForwardAccountDelay" type="number" value="${escapeHtml(settings.forward_account_delay_seconds || '0')}"></label>
          </div>
          <div class="row">
            <label><span>邮件时间窗口（分钟）</span><input id="settingForwardWindow" type="number" value="${escapeHtml(settings.forward_email_window_minutes || '0')}"></label>
            <label><span>SMTP 类型</span><select id="settingSmtpProvider">${renderOptions(normalProviders.filter(([key]) => key !== 'gmail'), settings.smtp_provider || 'custom')}</select></label>
          </div>
          <label class="check-row"><input id="settingForwardJunk" type="checkbox" ${boolSetting(settings.forward_include_junkemail) ? 'checked' : ''}><span>转发垃圾箱邮件</span></label>
          <label><span>SMTP 收件人</span><input id="settingForwardRecipient" value="${escapeHtml(settings.email_forward_recipient || '')}"></label>
          <div class="row">
            <label><span>SMTP 主机</span><input id="settingSmtpHost" value="${escapeHtml(settings.smtp_host || '')}"></label>
            <label><span>SMTP 端口</span><input id="settingSmtpPort" type="number" value="${escapeHtml(settings.smtp_port || '465')}"></label>
          </div>
          <label><span>SMTP 用户名</span><input id="settingSmtpUsername" value="${escapeHtml(settings.smtp_username || '')}"></label>
          <label><span>SMTP 密码</span><input id="settingSmtpPassword" type="password" value="${escapeHtml(settings.smtp_password || '')}"></label>
          <label><span>SMTP 发件人</span><input id="settingSmtpFromEmail" value="${escapeHtml(settings.smtp_from_email || '')}"></label>
          <label class="check-row"><input id="settingSmtpTls" type="checkbox" ${boolSetting(settings.smtp_use_tls) ? 'checked' : ''}><span>SMTP TLS</span></label>
          <label class="check-row"><input id="settingSmtpSsl" type="checkbox" ${boolSetting(settings.smtp_use_ssl, true) ? 'checked' : ''}><span>SMTP SSL</span></label>
          <label><span>Telegram Bot Token</span><input id="settingTelegramBotToken" type="password" value="${escapeHtml(settings.telegram_bot_token || '')}"></label>
          <label><span>Telegram Chat ID</span><input id="settingTelegramChatId" value="${escapeHtml(settings.telegram_chat_id || '')}"></label>
          <label><span>Telegram 代理</span><input id="settingTelegramProxyUrl" value="${escapeHtml(settings.telegram_proxy_url || '')}"></label>
          <label><span>企业微信 Webhook</span><input id="settingWecomWebhookUrl" type="password" value="${escapeHtml(settings.wecom_webhook_url || '')}"></label>
        </div>
        <div class="card">
          <div class="item-title">WebDAV 备份</div>
          <label class="check-row"><input id="settingWebdavEnabled" type="checkbox" ${boolSetting(settings.webdav_backup_enabled) ? 'checked' : ''}><span>启用 WebDAV 备份</span></label>
          <label><span>WebDAV 目录 URL</span><input id="settingWebdavUrl" value="${escapeHtml(settings.webdav_backup_url || '')}"></label>
          <label><span>WebDAV 用户名</span><input id="settingWebdavUsername" value="${escapeHtml(settings.webdav_backup_username || '')}"></label>
          <label><span>WebDAV 密码</span><input id="settingWebdavPassword" type="password" value="${escapeHtml(settings.webdav_backup_password || '')}"></label>
          <label><span>WebDAV Cron</span><input id="settingWebdavCron" value="${escapeHtml(settings.webdav_backup_cron || '0 3 * * *')}"></label>
          <label><span>修改/上传验证密码</span><input id="settingWebdavVerifyPassword" type="password"></label>
          <div class="item-meta">上次：${escapeHtml(settings.webdav_backup_last_status || '')} ${escapeHtml(settings.webdav_backup_last_message || '')}</div>
        </div>
        <div class="card">
          <label><span>对外 API Key</span><input id="settingExternalKey" value="${escapeHtml(settings.external_api_key || '')}"></label>
          <div class="toolbar wrap">
            <button id="btnSaveSettings" class="primary-btn" type="button">保存设置</button>
            <button id="btnValidateRefreshCron" class="secondary-btn" type="button">校验刷新 Cron</button>
            <button id="btnTestSmtp" class="secondary-btn" type="button">测试 SMTP</button>
            <button id="btnTestTelegram" class="secondary-btn" type="button">测试 Telegram</button>
            <button id="btnTestWecom" class="secondary-btn" type="button">测试企业微信</button>
            <button id="btnTestWebdav" class="secondary-btn" type="button">测试 WebDAV</button>
            <button id="btnUploadWebdav" class="secondary-btn" type="button">上传 WebDAV 备份</button>
          </div>
        </div>
        <div id="settingsResult"></div>
      `);
      getEl('btnSaveSettings').addEventListener('click', () => saveSettings(config));
      getEl('btnValidateRefreshCron').addEventListener('click', () => validateCron(config, valueOf('settingRefreshCron'), 5));
      getEl('btnTestSmtp').addEventListener('click', () => testForwardChannel(config, 'smtp'));
      getEl('btnTestTelegram').addEventListener('click', () => testForwardChannel(config, 'telegram'));
      getEl('btnTestWecom').addEventListener('click', () => testForwardChannel(config, 'wecom'));
      getEl('btnTestWebdav').addEventListener('click', () => testWebdav(config));
      getEl('btnUploadWebdav').addEventListener('click', () => uploadWebdav(config));
    }, '正在加载设置...');
  }

  function collectSettingsPayload() {
    return {
      gptmail_api_key: valueOf('settingGptmailKey'),
      app_timezone: valueOf('settingTimezone'),
      refresh_interval_days: valueOf('settingRefreshDays'),
      refresh_delay_seconds: valueOf('settingRefreshDelay'),
      refresh_cron: valueOf('settingRefreshCron'),
      use_cron_schedule: checked('settingUseCron'),
      enable_scheduled_refresh: checked('settingScheduledRefresh'),
      show_account_created_at: checked('settingShowCreated'),
      show_account_sort_order: checked('settingShowSort'),
      show_group_id: checked('settingShowGroupId'),
      external_api_key: valueOf('settingExternalKey'),
      duckmail_base_url: valueOf('settingDuckmailBaseUrl'),
      duckmail_api_key: valueOf('settingDuckmailApiKey'),
      cloudflare_worker_domain: valueOf('settingCloudflareWorkerDomain'),
      cloudflare_email_domains: valueOf('settingCloudflareEmailDomains'),
      cloudflare_admin_password: valueOf('settingCloudflareAdminPassword'),
      forward_channels: Array.from(document.querySelectorAll('[name="settingForwardChannel"]:checked')).map((item) => item.value),
      forward_check_interval_minutes: valueOf('settingForwardCheckInterval'),
      forward_account_delay_seconds: valueOf('settingForwardAccountDelay'),
      forward_email_window_minutes: valueOf('settingForwardWindow'),
      forward_include_junkemail: checked('settingForwardJunk'),
      email_forward_recipient: valueOf('settingForwardRecipient'),
      smtp_host: valueOf('settingSmtpHost'),
      smtp_port: valueOf('settingSmtpPort'),
      smtp_username: valueOf('settingSmtpUsername'),
      smtp_password: valueOf('settingSmtpPassword'),
      smtp_from_email: valueOf('settingSmtpFromEmail'),
      smtp_provider: valueOf('settingSmtpProvider'),
      smtp_use_tls: checked('settingSmtpTls'),
      smtp_use_ssl: checked('settingSmtpSsl'),
      telegram_bot_token: valueOf('settingTelegramBotToken'),
      telegram_chat_id: valueOf('settingTelegramChatId'),
      telegram_proxy_url: valueOf('settingTelegramProxyUrl'),
      wecom_webhook_url: valueOf('settingWecomWebhookUrl'),
      webdav_backup_enabled: checked('settingWebdavEnabled'),
      webdav_backup_url: valueOf('settingWebdavUrl'),
      webdav_backup_username: valueOf('settingWebdavUsername'),
      webdav_backup_password: valueOf('settingWebdavPassword'),
      webdav_backup_cron: valueOf('settingWebdavCron'),
      webdav_backup_verify_password: valueOf('settingWebdavVerifyPassword'),
    };
  }

  async function saveSettings(config) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/settings', {
        method: 'PUT',
        body: collectSettingsPayload(),
        timeoutMs: 70000,
      });
      getEl('settingsResult').innerHTML = renderResult(payload);
    }, '正在保存设置...');
  }

  async function validateCron(config, cronExpression, expectedFields) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/settings/validate-cron', {
        method: 'POST',
        body: {
          cron_expression: cronExpression,
          time_zone: valueOf('settingTimezone'),
          expected_fields: expectedFields,
        },
      });
      getEl('settingsResult').innerHTML = renderResult(payload);
    }, '正在校验 Cron...');
  }

  function forwardTestConfig() {
    return {
      smtp: {
        host: valueOf('settingSmtpHost'),
        port: toInt(valueOf('settingSmtpPort'), 465),
        username: valueOf('settingSmtpUsername'),
        password: valueOf('settingSmtpPassword'),
        from_email: valueOf('settingSmtpFromEmail'),
        recipient: valueOf('settingForwardRecipient'),
        provider: valueOf('settingSmtpProvider'),
        use_tls: checked('settingSmtpTls'),
        use_ssl: checked('settingSmtpSsl'),
      },
      telegram: {
        bot_token: valueOf('settingTelegramBotToken'),
        chat_id: valueOf('settingTelegramChatId'),
        proxy_url: valueOf('settingTelegramProxyUrl'),
      },
      wecom: {
        webhook_url: valueOf('settingWecomWebhookUrl'),
      },
    };
  }

  async function testForwardChannel(config, channel) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/settings/test-forward-channel', {
        method: 'POST',
        body: { channel, config: forwardTestConfig() },
        timeoutMs: 70000,
      });
      getEl('settingsResult').innerHTML = renderResult(payload);
    }, `正在测试 ${channel}...`);
  }

  function webdavConfig() {
    return {
      url: valueOf('settingWebdavUrl'),
      username: valueOf('settingWebdavUsername'),
      password: valueOf('settingWebdavPassword'),
    };
  }

  async function testWebdav(config) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/settings/test-webdav-backup', {
        method: 'POST',
        body: { config: webdavConfig() },
        timeoutMs: 70000,
      });
      getEl('settingsResult').innerHTML = renderResult(payload);
    }, '正在测试 WebDAV...');
  }

  async function uploadWebdav(config) {
    await runAction(config, async () => {
      const payload = await Api.apiRequest(config, '/api/settings/upload-webdav-backup', {
        method: 'POST',
        body: {
          login_password: valueOf('settingWebdavVerifyPassword'),
          config: webdavConfig(),
        },
        timeoutMs: 10 * 60 * 1000,
      });
      getEl('settingsResult').innerHTML = renderResult(payload);
    }, '正在上传 WebDAV 备份...');
  }

  function toggleConfigPanel() {
    getEl('configPanel').classList.toggle('collapsed');
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const config = await Storage.getConfig();
    getEl('serverUrl').value = config.serverUrl || '';
    getEl('password').value = config.password || '';
    getEl('rememberPassword').checked = config.rememberPassword === true;

    getEl('btnConfig').addEventListener('click', toggleConfigPanel);
    getEl('btnLogin').addEventListener('click', async () => {
      await saveConfig();
      await renderView(currentView);
    });
    getEl('btnReload').addEventListener('click', () => renderView(currentView));

    document.querySelectorAll('.quick-bar button').forEach((button) => {
      button.addEventListener('click', () => renderView(button.dataset.view || 'mail'));
    });

    setActiveView(currentView);
    if (config.serverUrl && config.password) {
      getEl('configPanel').classList.add('collapsed');
      await renderView(currentView);
    } else {
      setContent('<div class="card muted">填写服务地址和 Web 登录密码后，直接点击上方功能即可在侧边栏内操作。</div>');
    }
  });
})();
