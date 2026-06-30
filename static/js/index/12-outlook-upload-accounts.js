        /* global escapeHtml, handleApiError, hideModal, showConfirmModal, showModal, showToast */

        // ==================== Outlook 上传账号 ====================

        const uploadAccountsState = {
            page: 1,
            pageSize: 20,
            keyword: '',
            total: 0,
            totalPages: 1,
            loading: false,
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
            // 返回明文密码
            return escapeHtml(item.password || '');
        }

        function renderUploadAccountsRows(items) {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (!tbody) return;

            if (!Array.isArray(items) || items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="upload-accounts-empty">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = items.map(item => {
                const authBtnLabel = item.is_authorized ? '重新授权' : '去授权';
                const authBtn = `<button class="btn btn-sm btn-primary" type="button" style="width: 80px;" data-graph-auth-account-id="${escapeHtml(String(item.id ?? ''))}" data-graph-auth-email="${escapeHtml(item.email || '')}" data-graph-auth-password-length="${escapeHtml(String(item.password_length || 0))}">${authBtnLabel}</button>`;
                const editBtn = `<button class="btn btn-sm btn-secondary" type="button" data-edit-account-id="${escapeHtml(String(item.id ?? ''))}" data-edit-account-email="${escapeHtml(item.email || '')}" data-edit-account-remark="${escapeHtml(item.remark || '')}">修改</button>`;
                const deleteBtn = `<button class="btn btn-sm btn-danger" type="button" data-delete-account-id="${escapeHtml(String(item.id ?? ''))}" data-delete-account-email="${escapeHtml(item.email || '')}">删除</button>`;
                return `
                    <tr>
                        <td>${escapeHtml(String(item.id ?? ''))}</td>
                        <td class="upload-accounts-cell-mono">${escapeHtml(item.email || '')}</td>
                        <td class="upload-accounts-cell-mono">${escapeHtml(formatUploadAccountPassword(item))}</td>
                        <td>${formatUploadAccountAuthorized(item.is_authorized)}</td>
                        <td>${escapeHtml(item.status || '')}</td>
                        <td>${escapeHtml(item.remark || '')}</td>
                        <td>${escapeHtml(item.created_at || '')}</td>
                        <td>${authBtn}${editBtn}${deleteBtn}</td>
                    </tr>
                `;
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
            const pageSizeSelect = document.getElementById('uploadAccountsPageSize');
            if (pageSizeSelect) {
                pageSizeSelect.value = String(uploadAccountsState.pageSize);
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
                    renderUploadAccountsRows(data.items);
                } else {
                    renderUploadAccountsRows([]);
                    handleApiError(data, '加载 Outlook 上传账号失败');
                }
            } catch (error) {
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

        function changeUploadAccountsPageSize(value) {
            const parsed = parseInt(value, 10);
            uploadAccountsState.pageSize = Number.isFinite(parsed) ? parsed : 20;
            uploadAccountsState.page = 1;
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

        function showAddUploadAccountModal() {
            document.getElementById('addUploadAccountEmailPrefix').value = '';
            document.getElementById('addUploadAccountEmailDomain').value = '@outlook.com';
            document.getElementById('addUploadAccountPassword').value = '';
            document.getElementById('addUploadAccountRemark').value = '';
            showModal('addUploadAccountModal');
        }

        function hideAddUploadAccountModal() {
            hideModal('addUploadAccountModal');
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
                    hideAddUploadAccountModal();
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

        function showEditUploadAccountModal(accountId, email, remark) {
            document.getElementById('editUploadAccountId').value = String(accountId ?? '');
            document.getElementById('editUploadAccountEmail').value = email || '';
            document.getElementById('editUploadAccountPassword').value = '';
            document.getElementById('editUploadAccountRemark').value = remark || '';
            showModal('editUploadAccountModal');
        }

        function hideEditUploadAccountModal() {
            hideModal('editUploadAccountModal');
        }

        async function submitEditUploadAccount() {
            const accountId = document.getElementById('editUploadAccountId').value.trim();
            const email = document.getElementById('editUploadAccountEmail').value.trim();
            const password = document.getElementById('editUploadAccountPassword').value;
            const remark = document.getElementById('editUploadAccountRemark').value.trim();

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

            const btn = document.getElementById('submitEditUploadAccountBtn');
            if (btn) btn.disabled = true;

            try {
                const response = await fetch(`/api/outlook-upload-accounts/${encodeURIComponent(accountId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (data.success) {
                    showToast('修改成功', 'success');
                    hideEditUploadAccountModal();
                    reloadUploadAccounts();
                } else {
                    handleApiError(data, '修改失败');
                }
            } catch (error) {
                showToast('修改失败: ' + error.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-edit-account-id]');
            if (!button) return;
            showEditUploadAccountModal(
                Number(button.dataset.editAccountId),
                button.dataset.editAccountEmail || '',
                button.dataset.editAccountRemark || ''
            );
        });

        // ==================== Graph OAuth 授权 ====================

        const GRAPH_AUTH_LOG_PLACEHOLDER = '点击账号「去授权 / 重新授权」后，授权日志会显示在这里。';

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

            setUploadAuthButtonsDisabled(true);
            setGraphAuthStatus('running', '授权中');

            const logEl = document.getElementById('graphAuthLog');
            if (logEl) logEl.textContent = '开始 Graph OAuth 授权流程...';
            const startTime = Date.now();

            const finishAuth = (state, statusText) => {
                graphAuthState.running = false;
                setUploadAuthButtonsDisabled(false);
                setGraphAuthStatus(state, statusText);
            };

            try {
                appendGraphAuthLog('邮箱: ' + email);
                appendGraphAuthLog('密码: ' + '*'.repeat(Math.max(6, graphAuthState.secretLength)));
                appendGraphAuthLog('');
                appendGraphAuthLog('正在创建授权任务...');
                appendGraphAuthLog('');

                const response = await fetch('/api/oauth/graph-extract-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        account_id: accountId
                    })
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.stream_url) {
                    appendGraphAuthLog('创建授权任务失败: ' + (data.error || '未知错误'));
                    showToast('Graph 授权失败: ' + (data.error || '未知错误'), 'error');
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
                        showToast('Graph 授权成功，已保存到正式账号', 'success');
                    } else if (payload.type === 'error') {
                        appendGraphAuthLog('');
                        appendGraphAuthLog('授权失败: ' + (payload.message || '未知错误'));
                        if (payload.details) {
                            appendGraphAuthLog(payload.details);
                        }
                        showToast('Graph 授权失败: ' + (payload.message || '未知错误'), 'error');
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
