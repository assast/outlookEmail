        /* global escapeHtml, handleApiError, hideModal, showConfirmModal, showModal, showToast */

        // ==================== Outlook 上传账号 ====================

        const uploadAccountsState = {
            page: 1,
            pageSize: 10,
            keyword: '',
            total: 0,
            totalPages: 1,
            loading: false,
            editingRowId: null,
            currentData: [],
        };

        function formatUploadAccountAuthorized(isAuthorized) {
            return isAuthorized
                ? '<span class="upload-accounts-badge upload-accounts-badge--yes">已授权</span>'
                : '<span class="upload-accounts-badge upload-accounts-badge--no">未授权</span>';
        }

        function formatUploadAccountPassword(item) {
            if (!item || !item.has_password) {
                return '-';
            }
            return '已保存';
        }

        function renderUploadAccountsRows(items) {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (!tbody) return;

            if (!Array.isArray(items) || items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="upload-accounts-empty">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = items.map(item => {
                const itemId = item.id ?? '';
                const itemEmail = item.email || '';
                const itemRemark = item.remark || '';
                const itemCreatedAt = item.created_at || '';
                const isEditing = uploadAccountsState.editingRowId === itemId;

                if (isEditing) {
                    // 编辑状态
                    return `
                        <tr class="upload-accounts-row--editing" data-editing-id="${escapeHtml(String(itemId))}">
                            <td>${escapeHtml(String(itemId))}</td>
                            <td class="upload-accounts-cell-mono">
                                <input type="text" class="upload-accounts-edit-input"
                                    id="edit-email-${escapeHtml(String(itemId))}"
                                    value="${escapeHtml(itemEmail)}"
                                    placeholder="邮箱" autocomplete="off">
                            </td>
                            <td>
                                <input type="password" class="upload-accounts-edit-input"
                                    id="edit-password-${escapeHtml(String(itemId))}"
                                    placeholder="留空不改" autocomplete="off">
                            </td>
                            <td class="upload-accounts-edit-disabled">-</td>
                            <td>
                                <input type="text" class="upload-accounts-edit-input"
                                    id="edit-remark-${escapeHtml(String(itemId))}"
                                    value="${escapeHtml(itemRemark)}"
                                    placeholder="备注" autocomplete="off">
                            </td>
                            <td class="upload-accounts-edit-disabled">-</td>
                            <td>
                                <button class="btn btn-sm btn-primary" type="button" onclick="saveRowEdit(${escapeHtml(String(itemId))})">保存修改</button>
                                <button class="btn btn-sm btn-secondary" type="button" onclick="cancelRowEdit()">取消</button>
                            </td>
                        </tr>
                    `;
                } else {
                    // 正常显示状态
                    const authBtnLabel = item.is_authorized ? '重新授权' : '去授权';
                    const editDisabled = uploadAccountsState.editingRowId !== null;
                    const authBtn = `<button class="btn btn-sm btn-primary" type="button" style="width: 80px;" ${editDisabled ? 'disabled' : ''} data-graph-auth-account-id="${escapeHtml(String(itemId))}" data-graph-auth-email="${escapeHtml(itemEmail)}" data-graph-auth-password-length="${escapeHtml(String(item.password_length || 0))}">${authBtnLabel}</button>`;
                    const editBtn = `<button class="btn btn-sm btn-secondary" type="button" ${editDisabled ? 'disabled' : ''} onclick="enterRowEditMode(${escapeHtml(String(itemId))}, '${escapeHtml(itemEmail)}', '${escapeHtml(itemRemark)}')">修改</button>`;
                    const deleteBtn = `<button class="btn btn-sm btn-danger" type="button" ${editDisabled ? 'disabled' : ''} data-delete-account-id="${escapeHtml(String(itemId))}" data-delete-account-email="${escapeHtml(itemEmail)}">删除</button>`;
                    return `
                        <tr>
                            <td>${escapeHtml(String(itemId))}</td>
                            <td class="upload-accounts-cell-mono">${escapeHtml(itemEmail)}</td>
                            <td class="upload-accounts-cell-mono">${escapeHtml(formatUploadAccountPassword(item))}</td>
                            <td>${formatUploadAccountAuthorized(item.is_authorized)}</td>
                            <td>${escapeHtml(itemRemark)}</td>
                            <td>${escapeHtml(itemCreatedAt)}</td>
                            <td>${authBtn}${editBtn}${deleteBtn}</td>
                        </tr>
                    `;
                }
            }).join('');
        }

        function syncUploadAccountsPagination() {
            const info = document.getElementById('uploadAccountsPageInfo');
            if (info) {
                info.textContent = `共 ${uploadAccountsState.total} 条`;
            }
            const pageText = document.getElementById('uploadAccountsPageText');
            if (pageText) {
                pageText.textContent = `第 ${uploadAccountsState.page} / ${uploadAccountsState.totalPages} 页`;
            }
            const prevBtn = document.getElementById('uploadAccountsPrevBtn');
            const nextBtn = document.getElementById('uploadAccountsNextBtn');
            if (prevBtn) {
                prevBtn.disabled = uploadAccountsState.loading || uploadAccountsState.page <= 1;
            }
            if (nextBtn) {
                nextBtn.disabled = uploadAccountsState.loading
                    || uploadAccountsState.page >= uploadAccountsState.totalPages;
            }
        }

        async function loadUploadAccounts() {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="8" class="upload-accounts-empty">正在加载...</td></tr>';
            }
            uploadAccountsState.loading = true;
            syncUploadAccountsPagination();

            try {
                const params = new URLSearchParams({
                    page: String(uploadAccountsState.page),
                    page_size: String(uploadAccountsState.pageSize),
                });
                if (uploadAccountsState.keyword) {
                    params.set('keyword', uploadAccountsState.keyword);
                }
                const response = await fetch(`/api/outlook-upload-accounts?${params.toString()}`);
                const data = await response.json();
                if (data.success) {
                    uploadAccountsState.total = Number(data.total) || 0;
                    uploadAccountsState.totalPages = Math.max(1, Number(data.total_pages) || 1);
                    uploadAccountsState.page = Math.max(1, Number(data.page) || 1);
                    uploadAccountsState.pageSize = Number(data.page_size) || uploadAccountsState.pageSize;
                    uploadAccountsState.currentData = data.items || [];
                    renderUploadAccountsRows(uploadAccountsState.currentData);
                } else {
                    uploadAccountsState.currentData = [];
                    renderUploadAccountsRows([]);
                    handleApiError(data, '加载 Outlook 上传账号失败');
                }
            } catch (error) {
                uploadAccountsState.currentData = [];
                renderUploadAccountsRows([]);
                showToast('加载 Outlook 上传账号失败: ' + error.message, 'error');
            } finally {
                uploadAccountsState.loading = false;
                syncUploadAccountsPagination();
            }
        }

        function changeUploadAccountsPage(delta) {
            if (uploadAccountsState.loading) return;
            const target = uploadAccountsState.page + delta;
            if (target < 1 || target > uploadAccountsState.totalPages) return;
            uploadAccountsState.page = target;
            loadUploadAccounts();
        }

        function searchUploadAccounts() {
            const input = document.getElementById('uploadAccountsSearch');
            uploadAccountsState.keyword = input ? input.value.trim() : '';
            uploadAccountsState.page = 1;
            loadUploadAccounts();
        }

        function reloadUploadAccounts() {
            loadUploadAccounts();
        }

        function showOutlookUploadAccountsModal() {
            uploadAccountsState.page = 1;
            uploadAccountsState.keyword = '';
            const input = document.getElementById('uploadAccountsSearch');
            if (input) input.value = '';
            resetGraphAuthPanel();
            clearAddAccountForm();
            showModal('outlookUploadAccountsModal');
            loadUploadAccounts();
        }

        function hideOutlookUploadAccountsModal() {
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            graphAuthState.running = false;
            hideModal('outlookUploadAccountsModal');
        }

        // ==================== 添加上传账号 ====================

        function toggleAddAccountPanel() {
            const container = document.getElementById('addAccountFormContainer');
            const icon = document.getElementById('toggleAddPanelIcon');
            if (!container || !icon) return;

            const isCollapsed = container.classList.toggle('is-collapsed');
            icon.textContent = isCollapsed ? '▶' : '▼';
        }

        function clearAddAccountForm() {
            document.getElementById('addUploadAccountEmailPrefix').value = '';
            document.getElementById('addUploadAccountEmailDomain').value = '@outlook.com';
            document.getElementById('addUploadAccountPassword').value = '';
            document.getElementById('addUploadAccountRemark').value = '';
        }

        async function submitAddUploadAccount() {
            const emailPrefix = document.getElementById('addUploadAccountEmailPrefix').value.trim();
            const emailDomain = document.getElementById('addUploadAccountEmailDomain').value;
            const password = document.getElementById('addUploadAccountPassword').value.trim();
            const remark = document.getElementById('addUploadAccountRemark').value.trim();

            if (!emailPrefix) {
                showToast('请输入邮箱前缀', 'error');
                return;
            }
            if (!password) {
                showToast('请输入密码', 'error');
                return;
            }

            const email = emailPrefix + emailDomain;

            const btn = document.getElementById('submitAddUploadAccountBtn');
            if (btn) btn.disabled = true;

            try {
                const response = await fetch('/api/outlook-upload-accounts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password, remark })
                });
                const data = await response.json();
                if (data.success) {
                    showToast('添加成功', 'success');
                    clearAddAccountForm();
                    reloadUploadAccounts();
                } else {
                    handleApiError(data, '添加失败');
                }
            } catch (error) {
                showToast('添加失败: ' + error.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        // ==================== 修改上传账号 ====================

        function enterRowEditMode(accountId, email, remark) {
            if (uploadAccountsState.editingRowId !== null) {
                showToast('请先完成当前编辑', 'warning');
                return;
            }
            uploadAccountsState.editingRowId = accountId;
            renderUploadAccountsRows(uploadAccountsState.currentData);

            // 聚焦到备注输入框
            setTimeout(() => {
                const remarkInput = document.getElementById(`edit-remark-${accountId}`);
                if (remarkInput) remarkInput.focus();
            }, 50);
        }

        function cancelRowEdit() {
            uploadAccountsState.editingRowId = null;
            renderUploadAccountsRows(uploadAccountsState.currentData);
        }

        async function saveRowEdit(accountId) {
            const email = document.getElementById(`edit-email-${accountId}`)?.value.trim();
            const password = document.getElementById(`edit-password-${accountId}`)?.value.trim();
            const remark = document.getElementById(`edit-remark-${accountId}`)?.value.trim();

            if (!accountId) {
                showToast('未选中账号，无法修改', 'error');
                return;
            }
            if (!email) {
                showToast('请输入邮箱', 'error');
                return;
            }

            const payload = { email, remark };
            // 密码留空表示保持原密码，不下发该字段
            if (password !== '') {
                payload.password = password;
            }

            // 禁用保存按钮
            const saveBtn = document.querySelector(`[onclick="saveRowEdit(${accountId})"]`);
            if (saveBtn) saveBtn.disabled = true;

            try {
                const response = await fetch(`/api/outlook-upload-accounts/${encodeURIComponent(accountId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (data.success) {
                    showToast('修改成功', 'success');
                    uploadAccountsState.editingRowId = null;
                    reloadUploadAccounts();
                } else {
                    handleApiError(data, '修改失败');
                }
            } catch (error) {
                showToast('修改失败: ' + error.message, 'error');
            } finally {
                if (saveBtn) saveBtn.disabled = false;
            }
        }

        // ==================== Outlook IMAP OAuth 授权 ====================

        const GRAPH_AUTH_LOG_PLACEHOLDER = '点击账号「去授权 / 重新授权」后，授权日志会显示在这里。';
        const GRAPH_AUTH_MODE_LABELS = {
            imap: 'Outlook IMAP',
            graph: 'Graph-only（不含 IMAP 权限）',
        };

        let graphAuthState = {
            accountId: null,
            email: '',
            secretLength: 0,
            eventSource: null,
            running: false,
        };

        function setGraphAuthStatus(state, text) {
            const statusEl = document.getElementById('graphAuthStatus');
            if (!statusEl) return;
            statusEl.dataset.state = state;
            statusEl.textContent = text;
        }

        function resetGraphAuthPanel() {
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            graphAuthState.accountId = null;
            graphAuthState.email = '';
            graphAuthState.secretLength = 0;
            graphAuthState.running = false;
            const logEl = document.getElementById('graphAuthLog');
            if (logEl) logEl.textContent = GRAPH_AUTH_LOG_PLACEHOLDER;
            setGraphAuthStatus('idle', '空闲');
        }

        function setUploadAuthButtonsDisabled(disabled) {
            document.querySelectorAll('#uploadAccountsTableBody [data-graph-auth-account-id]').forEach(btn => {
                btn.disabled = disabled;
            });
        }

        function appendGraphAuthLog(message) {
            const logEl = document.getElementById('graphAuthLog');
            if (!logEl) return;

            const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
            logEl.textContent += `\n[${timestamp}] ${message}`;
            logEl.scrollTop = logEl.scrollHeight;
        }

        function getGraphAuthMode() {
            const checked = document.querySelector('input[name="graphAuthMode"]:checked');
            return checked && checked.value === 'graph' ? 'graph' : 'imap';
        }

        function getGraphAuthModeLabel(mode) {
            return GRAPH_AUTH_MODE_LABELS[mode] || GRAPH_AUTH_MODE_LABELS.imap;
        }

        async function startGraphAuthForAccount(accountId, email, passwordLength) {
            if (graphAuthState.running) {
                showToast('正在授权中，请等待当前任务完成', 'warning');
                return;
            }
            if (!accountId) {
                showToast('请选择要授权的账号', 'error');
                return;
            }

            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }

            graphAuthState.accountId = accountId;
            graphAuthState.email = email;
            graphAuthState.secretLength = Number(passwordLength) || 0;
            graphAuthState.running = true;
            const authMode = getGraphAuthMode();
            const authModeLabel = getGraphAuthModeLabel(authMode);

            setUploadAuthButtonsDisabled(true);
            setGraphAuthStatus('running', '授权中');

            const logEl = document.getElementById('graphAuthLog');
            if (logEl) logEl.textContent = `开始 ${authModeLabel} OAuth 授权流程...`;
            const startTime = Date.now();

            const finishAuth = (state, statusText) => {
                graphAuthState.running = false;
                setUploadAuthButtonsDisabled(false);
                setGraphAuthStatus(state, statusText);
            };

            try {
                appendGraphAuthLog('邮箱: ' + email);
                appendGraphAuthLog('密码: ' + '*'.repeat(Math.max(6, graphAuthState.secretLength)));
                appendGraphAuthLog('授权模式: ' + authModeLabel);
                appendGraphAuthLog('');
                appendGraphAuthLog('正在创建授权任务...');
                appendGraphAuthLog('');

                const response = await fetch('/api/oauth/graph-extract-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        account_id: accountId,
                        mode: authMode
                    })
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.stream_url) {
                    appendGraphAuthLog('创建授权任务失败: ' + (data.error || '未知错误'));
                    showToast(authModeLabel + ' 授权失败: ' + (data.error || '未知错误'), 'error');
                    finishAuth('error', '失败');
                    return;
                }

                appendGraphAuthLog('授权任务已创建，等待后端日志...');
                graphAuthState.eventSource = new EventSource(data.stream_url);
                graphAuthState.eventSource.onmessage = (event) => {
                    let payload;
                    try {
                        payload = JSON.parse(event.data);
                    } catch (parseError) {
                        appendGraphAuthLog(event.data);
                        return;
                    }

                    if (payload.type === 'start' && payload.message) {
                        appendGraphAuthLog(payload.message);
                    } else if (payload.type === 'log') {
                        appendGraphAuthLog(payload.message || '');
                    } else if (payload.type === 'success') {
                        appendGraphAuthLog('');
                        appendGraphAuthLog('授权成功，已保存到正式账号');
                        appendGraphAuthLog('Client ID: ' + (payload.client_id || '-'));
                        appendGraphAuthLog(payload.created ? '保存方式: 新增正式账号' : '保存方式: 更新已有正式账号');
                        showToast(getGraphAuthModeLabel(payload.mode || authMode) + ' 授权成功，已保存到正式账号', 'success');
                    } else if (payload.type === 'error') {
                        appendGraphAuthLog('');
                        appendGraphAuthLog('授权失败: ' + (payload.message || '未知错误'));
                        if (payload.details) {
                            appendGraphAuthLog(payload.details);
                        }
                        showToast(getGraphAuthModeLabel(payload.mode || authMode) + ' 授权失败: ' + (payload.message || '未知错误'), 'error');
                    } else if (payload.type === 'complete') {
                        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                        appendGraphAuthLog('');
                        appendGraphAuthLog('耗时: ' + elapsed + ' 秒');
                        if (graphAuthState.eventSource) {
                            graphAuthState.eventSource.close();
                            graphAuthState.eventSource = null;
                        }
                        finishAuth(payload.success ? 'success' : 'error', payload.success ? '成功' : '失败');
                        if (payload.success) {
                            setTimeout(() => {
                                loadUploadAccounts();
                            }, 1000);
                        }
                    }
                };
                graphAuthState.eventSource.onerror = () => {
                    appendGraphAuthLog('授权日志连接中断');
                    if (graphAuthState.eventSource) {
                        graphAuthState.eventSource.close();
                        graphAuthState.eventSource = null;
                    }
                    finishAuth('error', '连接中断');
                };
            } catch (error) {
                appendGraphAuthLog('');
                appendGraphAuthLog('异常信息: ' + error.message);

                showToast('授权请求失败: ' + error.message, 'error');
                finishAuth('error', '失败');
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-graph-auth-account-id]');
            if (!button) return;
            startGraphAuthForAccount(
                Number(button.dataset.graphAuthAccountId),
                button.dataset.graphAuthEmail || '',
                Number(button.dataset.graphAuthPasswordLength) || 0
            );
        });

        async function deleteUploadAccount(accountId, email) {
            if (!(await showConfirmModal(`确定要删除账号 ${email || ''} 吗？此操作不可恢复。`, { title: '删除上传账号', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/outlook-upload-accounts/${encodeURIComponent(accountId)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (data.success) {
                    showToast('删除成功', 'success');
                    loadUploadAccounts();
                } else {
                    handleApiError(data, '删除失败');
                }
            } catch (error) {
                showToast('删除失败: ' + error.message, 'error');
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-delete-account-id]');
            if (!button) return;
            deleteUploadAccount(
                Number(button.dataset.deleteAccountId),
                button.dataset.deleteAccountEmail || ''
            );
        });

        // ==================== 从正式账号加入自动授权 ====================

        async function queueAccountForOutlookAutoAuth(accountId, email) {
            if (!Number.isFinite(accountId) || accountId <= 0) {
                showToast('账号信息无效，无法加入自动授权', 'error');
                return;
            }
            try {
                const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/outlook-auto-auth`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const data = await response.json();
                if (data.success) {
                    const msg = data.status === 'updated'
                        ? `已重新加入自动授权：${data.email || email || ''}`
                        : `已加入自动授权：${data.email || email || ''}`;
                    showToast(msg, 'success');
                    const modal = document.getElementById('outlookUploadAccountsModal');
                    if (modal && modal.classList.contains('show')) {
                        loadUploadAccounts();
                    }
                } else {
                    handleApiError(data, '加入自动授权失败');
                }
            } catch (error) {
                showToast('加入自动授权失败: ' + error.message, 'error');
            }
        }

        window.queueAccountForOutlookAutoAuth = queueAccountForOutlookAutoAuth;
