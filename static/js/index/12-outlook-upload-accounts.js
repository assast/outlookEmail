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
            const length = Number(item.password_length) || 0;
            return '*'.repeat(Math.max(6, length));
        }

        function renderUploadAccountsRows(items) {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (!tbody) return;

            if (!Array.isArray(items) || items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="upload-accounts-empty">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = items.map(item => {
                const authBtn = !item.is_authorized
                    ? `<button class="btn btn-sm btn-primary" type="button" data-graph-auth-account-id="${escapeHtml(String(item.id ?? ''))}" data-graph-auth-email="${escapeHtml(item.email || '')}" data-graph-auth-password-length="${escapeHtml(String(item.password_length || 0))}">去授权</button>`
                    : '';
                const deleteBtn = `<button class="btn btn-sm btn-danger" type="button" data-delete-account-id="${escapeHtml(String(item.id ?? ''))}" data-delete-account-email="${escapeHtml(item.email || '')}" style="margin-left: 4px;">删除</button>`;
                return `
                    <tr>
                        <td>${escapeHtml(String(item.id ?? ''))}</td>
                        <td class="upload-accounts-cell-mono">${escapeHtml(item.email || '')}</td>
                        <td class="upload-accounts-cell-mono">${escapeHtml(formatUploadAccountPassword(item))}</td>
                        <td>${formatUploadAccountAuthorized(item.is_authorized)}</td>
                        <td>${escapeHtml(item.status || '')}</td>
                        <td>${escapeHtml(item.remark || '')}</td>
                        <td>${escapeHtml(item.created_at || '')}</td>
                        <td>${authBtn}${deleteBtn}</td>
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
            showModal('outlookUploadAccountsModal');
            loadUploadAccounts();
        }

        function hideOutlookUploadAccountsModal() {
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

        // ==================== Graph OAuth 授权 ====================

        let graphAuthState = {
            accountId: null,
            email: '',
            secretLength: 0,
            eventSource: null
        };

        function showGraphAuthModal(accountId, email, passwordLength) {
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            graphAuthState.accountId = accountId;
            graphAuthState.email = email;
            graphAuthState.secretLength = Number(passwordLength) || 0;

            document.getElementById('graphAuthEmail').textContent = email;
            document.getElementById('graphAuthPasswordMasked').textContent = '*'.repeat(Math.max(6, graphAuthState.secretLength));
            document.getElementById('graphAuthLog').textContent = '准备就绪，点击"授权"按钮开始...';
            document.getElementById('startGraphAuthBtn').disabled = false;

            showModal('graphAuthModal');
        }

        function hideGraphAuthModal() {
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            hideModal('graphAuthModal');
        }

        function appendGraphAuthLog(message) {
            const logEl = document.getElementById('graphAuthLog');
            if (!logEl) return;

            const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
            logEl.textContent += `\n[${timestamp}] ${message}`;
            logEl.scrollTop = logEl.scrollHeight;
        }

        async function startGraphAuth() {
            const btn = document.getElementById('startGraphAuthBtn');
            if (!btn) return;
            if (!graphAuthState.accountId) {
                showToast('请选择要授权的账号', 'error');
                return;
            }

            btn.disabled = true;
            btn.textContent = '授权中...';

            const logEl = document.getElementById('graphAuthLog');
            logEl.textContent = '开始 Graph OAuth 授权流程...\n';
            const startTime = Date.now();

            try {
                appendGraphAuthLog('邮箱: ' + graphAuthState.email);
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
                        account_id: graphAuthState.accountId
                    })
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.stream_url) {
                    appendGraphAuthLog('创建授权任务失败: ' + (data.error || '未知错误'));
                    showToast('Graph 授权失败: ' + (data.error || '未知错误'), 'error');
                    btn.disabled = false;
                    btn.textContent = '授权';
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
                        btn.disabled = false;
                        btn.textContent = '授权';
                        if (payload.success) {
                            setTimeout(() => {
                                hideGraphAuthModal();
                                loadUploadAccounts();
                            }, 1200);
                        }
                    }
                };
                graphAuthState.eventSource.onerror = () => {
                    appendGraphAuthLog('授权日志连接中断');
                    if (graphAuthState.eventSource) {
                        graphAuthState.eventSource.close();
                        graphAuthState.eventSource = null;
                    }
                    btn.disabled = false;
                    btn.textContent = '授权';
                };
            } catch (error) {
                appendGraphAuthLog('');
                appendGraphAuthLog('异常信息: ' + error.message);

                showToast('授权请求失败: ' + error.message, 'error');
                btn.disabled = false;
                btn.textContent = '授权';
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-graph-auth-account-id]');
            if (!button) return;
            showGraphAuthModal(
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
