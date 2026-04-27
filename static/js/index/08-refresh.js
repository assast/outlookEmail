        /* global closeAccountActionMenus, closeFullscreenEmail, closeMobilePanels, closeNavbarActionsMenu, closeTagFilterDropdown, escapeHtml, formatDate, handleApiError, hideModal, showEditAccountModal, showModal, showToast, updateModalBodyState */

        // ==================== Token 刷新管理 ====================

        const refreshModalState = {
            query: '',
            status: 'all',
            page: 1,
            pageSize: 200,
            total: 0,
            items: [],
            stats: null,
            currentRefreshingAccountId: null,
            searchTimer: 0,
        };

        function getRefreshStatusMeta(status) {
            switch (String(status || '').toLowerCase()) {
                case 'running':
                    return { label: '刷新中', className: 'running' };
                case 'success':
                    return { label: '成功', className: 'success' };
                case 'failed':
                    return { label: '失败', className: 'failed' };
                case 'partial_failed':
                    return { label: '部分失败', className: 'partial-failed' };
                case 'never':
                    return { label: '从未刷新', className: 'never' };
                default:
                    return { label: '未执行', className: 'never' };
            }
        }

        function renderRefreshStatusBadge(status, isRunning = false) {
            const meta = isRunning ? getRefreshStatusMeta('running') : getRefreshStatusMeta(status);
            return `<span class="refresh-status-pill ${meta.className}">${meta.label}</span>`;
        }

        function setRefreshProgressBanner(visible, title = '正在刷新', text = '请稍候') {
            const banner = document.getElementById('refreshProgressBanner');
            const titleEl = banner?.querySelector('.refresh-progress-banner__title');
            const textEl = document.getElementById('refreshProgressText');
            if (!banner || !titleEl || !textEl) {
                return;
            }
            banner.hidden = !visible;
            titleEl.textContent = title;
            textEl.innerHTML = text;
        }

        function resetRefreshModalRuntime() {
            if (refreshModalState.searchTimer) {
                window.clearTimeout(refreshModalState.searchTimer);
                refreshModalState.searchTimer = 0;
            }
            refreshModalState.currentRefreshingAccountId = null;
            setRefreshProgressBanner(false);

            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = false;
                refreshAllBtn.textContent = '全量刷新';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = false;
                retryFailedBtn.textContent = '重试失败';
            }
        }

        function updateRefreshStatusFilterButtons() {
            document.querySelectorAll('#refreshModal .refresh-filter-chip').forEach(btn => {
                btn.classList.toggle('is-active', btn.dataset.status === refreshModalState.status);
            });
        }

        function renderRefreshStats(stats) {
            refreshModalState.stats = stats || null;
            const snapshotMeta = getRefreshStatusMeta(stats?.last_refresh_status);

            document.getElementById('lastRefreshTime').textContent = stats?.last_refresh_time
                ? formatDateTime(stats.last_refresh_time)
                : '-';
            document.getElementById('totalRefreshCount').textContent = String(stats?.total ?? 0);
            document.getElementById('successRefreshCount').textContent = String(stats?.success_count ?? 0);
            document.getElementById('failedRefreshCount').textContent = String(stats?.failed_count ?? 0);
            document.getElementById('refreshFilterCountAll').textContent = String(stats?.total ?? 0);
            document.getElementById('refreshFilterCountSuccess').textContent = String(stats?.success_count ?? 0);
            document.getElementById('refreshFilterCountFailed').textContent = String(stats?.failed_count ?? 0);
            document.getElementById('refreshFilterCountNever').textContent = String(stats?.never_count ?? 0);

            const statusEl = document.getElementById('lastRefreshStatusLabel');
            if (statusEl) {
                statusEl.className = `refresh-status-pill ${snapshotMeta.className}`;
                statusEl.textContent = snapshotMeta.label;
            }
        }

        function renderRefreshAccountList(items, total) {
            const container = document.getElementById('refreshAccountList');
            const summaryEl = document.getElementById('refreshListSummary');
            if (!container || !summaryEl) {
                return;
            }

            refreshModalState.items = Array.isArray(items) ? items : [];
            refreshModalState.total = Number(total || 0);
            summaryEl.textContent = `当前 ${refreshModalState.items.length} / 共 ${refreshModalState.total} 项`;

            if (!refreshModalState.items.length) {
                container.innerHTML = '<div class="refresh-account-empty">当前筛选条件下暂无邮箱</div>';
                return;
            }

            const rowsHtml = refreshModalState.items.map(item => {
                const isRunning = refreshModalState.currentRefreshingAccountId === item.id;
                const canRetry = item.last_refresh_status === 'failed' && !isRunning;
                const groupText = item.group_name || '默认分组';
                const refreshTime = item.last_refresh_at ? formatDateTime(item.last_refresh_at) : '-';
                const remarkHtml = item.remark
                    ? `<div class="refresh-account-remark">${escapeHtml(item.remark)}</div>`
                    : '';
                const errorHtml = item.last_refresh_status === 'failed' && item.last_refresh_error
                    ? `<div class="refresh-account-error">${escapeHtml(item.last_refresh_error)}</div>`
                    : '';

                return `
                    <tr class="refresh-account-row ${isRunning ? 'is-refreshing' : ''}">
                        <td class="refresh-account-main">
                            <div class="refresh-account-email" title="${escapeHtml(item.email)}">${escapeHtml(item.email)}</div>
                            ${remarkHtml}
                            ${errorHtml}
                        </td>
                        <td class="refresh-account-group" title="${escapeHtml(groupText)}">${escapeHtml(groupText)}</td>
                        <td class="refresh-account-time">${escapeHtml(refreshTime)}</td>
                        <td class="refresh-account-status-cell">${renderRefreshStatusBadge(item.last_refresh_status, isRunning)}</td>
                        <td class="refresh-account-action">
                            ${canRetry
                                ? `<button class="btn btn-sm btn-primary" type="button" onclick="retrySingleAccount(${item.id}, '${escapeJs(item.email)}')">重试</button>`
                                : '<span class="refresh-account-time">-</span>'}
                        </td>
                    </tr>
                `;
            }).join('');

            container.innerHTML = `
                <table class="refresh-account-table">
                    <thead>
                        <tr>
                            <th>邮箱</th>
                            <th>分组</th>
                            <th>最近刷新</th>
                            <th>状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            `;
        }

        async function loadRefreshStats() {
            try {
                const response = await fetch('/api/accounts/refresh-stats');
                const data = await response.json();
                if (data.success) {
                    renderRefreshStats(data.stats || {});
                }
            } catch (error) {
                console.error('加载刷新统计失败:', error);
            }
        }

        async function loadRefreshStatusList() {
            const params = new URLSearchParams({
                q: refreshModalState.query,
                status: refreshModalState.status,
                page: String(refreshModalState.page),
                page_size: String(refreshModalState.pageSize),
            });

            try {
                const response = await fetch(`/api/accounts/refresh-status-list?${params.toString()}`);
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '加载 Token 刷新状态失败');
                    return;
                }
                renderRefreshStats(data.stats || {});
                renderRefreshAccountList(data.items || [], data.total || 0);
                updateRefreshStatusFilterButtons();
            } catch (error) {
                showToast('加载 Token 刷新状态失败', 'error');
            }
        }

        async function showRefreshModal(resetFilters = false) {
            if (resetFilters) {
                refreshModalState.query = '';
                refreshModalState.status = 'all';
                refreshModalState.page = 1;
            }

            showModal('refreshModal');
            updateRefreshStatusFilterButtons();

            const searchInput = document.getElementById('refreshSearchInput');
            if (searchInput) {
                searchInput.value = refreshModalState.query;
            }

            await loadRefreshStatusList();
        }

        async function openRefreshModalWithStatus(status = 'all') {
            refreshModalState.query = '';
            refreshModalState.status = String(status || 'all').toLowerCase();
            refreshModalState.page = 1;
            await showRefreshModal();
        }

        function hideRefreshModal() {
            hideModal('refreshModal');
            resetRefreshModalRuntime();
        }

        function handleRefreshSearchInput(value) {
            refreshModalState.query = String(value || '').trim();
            refreshModalState.page = 1;
            if (refreshModalState.searchTimer) {
                window.clearTimeout(refreshModalState.searchTimer);
            }
            refreshModalState.searchTimer = window.setTimeout(() => {
                refreshModalState.searchTimer = 0;
                loadRefreshStatusList();
            }, 180);
        }

        function setRefreshStatusFilter(status, triggerEl = null) {
            refreshModalState.status = String(status || 'all').toLowerCase();
            refreshModalState.page = 1;
            if (triggerEl?.dataset?.status) {
                document.querySelectorAll('#refreshModal .refresh-filter-chip').forEach(btn => {
                    btn.classList.toggle('is-active', btn === triggerEl);
                });
            } else {
                updateRefreshStatusFilterButtons();
            }
            loadRefreshStatusList();
        }

        // 全量刷新所有账号
        async function refreshAllAccounts() {
            const btn = document.getElementById('refreshAllBtn');

            if (btn.disabled) return;

            if (!(await showConfirmModal('确定要刷新所有账号的 Token 吗？', { title: '刷新 Token', confirmText: '确认刷新', danger: false }))) {
                return;
            }

            btn.disabled = true;
            btn.textContent = '刷新中...';
            setRefreshProgressBanner(true, '正在刷新', '正在初始化...');

            try {
                const eventSource = new EventSource('/api/accounts/trigger-scheduled-refresh?force=true');
                let totalCount = 0;
                let successCount = 0;
                let failedCount = 0;

                eventSource.onmessage = async function (event) {
                    try {
                        const data = JSON.parse(event.data);

                        if (data.type === 'start') {
                            totalCount = data.total;
                            const delayInfo = data.delay_seconds > 0 ? `（间隔 ${data.delay_seconds} 秒）` : '';
                            setRefreshProgressBanner(true, '正在刷新', `总共 <strong>${totalCount}</strong> 个账号${delayInfo}，准备开始刷新...`);
                            document.getElementById('totalRefreshCount').textContent = totalCount;
                            document.getElementById('successRefreshCount').textContent = '0';
                            document.getElementById('failedRefreshCount').textContent = '0';
                        } else if (data.type === 'progress') {
                            successCount = data.success_count;
                            failedCount = data.failed_count;
                            refreshModalState.currentRefreshingAccountId = data.account_id || null;
                            document.getElementById('successRefreshCount').textContent = successCount;
                            document.getElementById('failedRefreshCount').textContent = failedCount;
                            setRefreshProgressBanner(true, '正在刷新', `
                                正在处理：<strong>${escapeHtml(data.email || '-')}</strong><br>
                                进度：<strong>${data.current}/${data.total}</strong> |
                                成功：<strong style="color:#15803d;">${successCount}</strong> |
                                失败：<strong style="color:#b42318;">${failedCount}</strong>
                            `);
                            renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
                        } else if (data.type === 'delay') {
                            setRefreshProgressBanner(true, '正在刷新', `
                                已处理 <strong>${successCount + failedCount}</strong> 个账号<br>
                                <span style="color:#64748b;">等待 ${data.seconds} 秒后继续...</span>
                            `);
                        } else if (data.type === 'complete') {
                            eventSource.close();
                            refreshModalState.currentRefreshingAccountId = null;
                            setRefreshProgressBanner(false);
                            btn.disabled = false;
                            btn.textContent = '全量刷新';

                            showToast(`刷新完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                                data.failed_count > 0 ? 'warning' : 'success');

                            await loadRefreshStatusList();
                            if (currentGroupId) {
                                loadAccountsByGroup(currentGroupId, true);
                            }
                        } else if (data.type === 'conflict') {
                            eventSource.close();
                            refreshModalState.currentRefreshingAccountId = null;
                            setRefreshProgressBanner(false);
                            btn.disabled = false;
                            btn.textContent = '全量刷新';
                            showToast(data.message || '已有刷新任务在执行', 'warning');
                            await loadRefreshStatusList();
                        } else if (data.type === 'error') {
                            eventSource.close();
                            refreshModalState.currentRefreshingAccountId = null;
                            setRefreshProgressBanner(false);
                            btn.disabled = false;
                            btn.textContent = '全量刷新';
                            showToast(data.message || '刷新过程中出现错误', 'error');
                            await loadRefreshStatusList();
                        }
                    } catch (e) {
                        console.error('解析进度数据失败:', e);
                    }
                };

                eventSource.onerror = function (error) {
                    console.error('EventSource 错误:', error);
                    eventSource.close();
                    refreshModalState.currentRefreshingAccountId = null;
                    setRefreshProgressBanner(false);
                    btn.disabled = false;
                    btn.textContent = '全量刷新';
                    showToast('刷新过程中出现错误', 'error');
                };

            } catch (error) {
                refreshModalState.currentRefreshingAccountId = null;
                setRefreshProgressBanner(false);
                btn.disabled = false;
                btn.textContent = '全量刷新';
                showToast('刷新请求失败', 'error');
            }
        }

        // 重试失败的账号
        async function retryFailedAccounts() {
            const btn = document.getElementById('retryFailedBtn');

            if (btn.disabled) return;

            btn.disabled = true;
            btn.textContent = '重试中...';
            setRefreshProgressBanner(true, '正在重试', '正在重试失败状态的账号...');

            try {
                const response = await fetch('/api/accounts/refresh-failed', {
                    method: 'POST'
                });
                const data = await response.json();

                setRefreshProgressBanner(false);
                btn.disabled = false;
                btn.textContent = '重试失败';

                if (data.success) {
                    if (data.total === 0) {
                        showToast('没有需要重试的失败账号', 'info');
                    } else {
                        showToast(`重试完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                            data.failed_count > 0 ? 'warning' : 'success');
                        await loadRefreshStatusList();
                    }
                } else {
                    handleApiError(data, '重试失败');
                }
            } catch (error) {
                setRefreshProgressBanner(false);
                btn.disabled = false;
                btn.textContent = '重试失败';
                showToast('重试请求失败', 'error');
            }
        }

        // 单个账号重试
        async function retrySingleAccount(accountId, accountEmail) {
            try {
                refreshModalState.currentRefreshingAccountId = accountId;
                renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
                setRefreshProgressBanner(true, '正在重试', `正在重试 <strong>${escapeHtml(accountEmail)}</strong>`);
                const response = await fetch(`/api/accounts/${accountId}/retry-refresh`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    showToast(`${accountEmail} 刷新成功`, 'success');
                    await loadRefreshStatusList();
                } else {
                    handleApiError(data, `${accountEmail} 刷新失败`);
                }
            } catch (error) {
                handleApiError({ success: false, error: { message: '刷新请求失败', details: error.message, code: 'NETWORK_ERROR', type: 'Frontend' } });
            } finally {
                refreshModalState.currentRefreshingAccountId = null;
                setRefreshProgressBanner(false);
                renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
            }
        }

        async function loadForwardingLogs() {
            const drawer = document.getElementById('forwardingLogsDrawer');
            const container = document.getElementById('forwardingLogsContainer');
            const listEl = document.getElementById('forwardingLogsList');
            hideFailedForwardingLogs();

            try {
                const response = await fetch('/api/accounts/forwarding-logs?limit=100');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无转发历史</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                            const statusText = log.status === 'success' ? '成功' : '失败';
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #e5e5e5;">
                                    <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                                        <div style="font-weight: 600;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: ${statusColor}; font-weight: 600;">${statusText}</div>
                                    </div>
                                    <div style="font-size: 12px; color: #666; line-height: 1.7;">
                                        <div>渠道：${escapeHtml(log.channel || '-')}</div>
                                        <div>邮件 ID：${escapeHtml(log.message_id || '-')}</div>
                                        <div>时间：${formatDateTime(log.created_at)}</div>
                                    </div>
                                    ${log.error_message ? `<div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message)}</div>` : ''}
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    if (container) {
                        container.hidden = false;
                    }
                    if (drawer) {
                        drawer.classList.add('is-open');
                    }
                    const toggleBtn = document.getElementById('forwardingLogsToggleBtn');
                    if (toggleBtn) {
                        toggleBtn.textContent = '收起历史';
                    }
                }
            } catch (error) {
                showToast('加载转发历史失败', 'error');
            }
        }

        async function loadFailedForwardingLogs() {
            const drawer = document.getElementById('failedForwardingLogsDrawer');
            const container = document.getElementById('failedForwardingLogsContainer');
            const listEl = document.getElementById('failedForwardingLogsList');
            hideForwardingLogs();

            try {
                const response = await fetch('/api/accounts/forwarding-logs/failed?limit=100');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无转发失败记录</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #f3d6d6;">
                                    <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                                        <div style="font-weight: 600;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: #dc3545; font-weight: 600;">失败</div>
                                    </div>
                                    <div style="font-size: 12px; color: #666; line-height: 1.7;">
                                        <div>渠道：${escapeHtml(log.channel || '-')}</div>
                                        <div>邮件 ID：${escapeHtml(log.message_id || '-')}</div>
                                        <div>时间：${formatDateTime(log.created_at)}</div>
                                    </div>
                                    <div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message || '未知错误')}</div>
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    if (container) {
                        container.hidden = false;
                    }
                    if (drawer) {
                        drawer.classList.add('is-open');
                    }
                    const toggleBtn = document.getElementById('failedForwardingLogsToggleBtn');
                    if (toggleBtn) {
                        toggleBtn.textContent = '收起失败';
                    }
                }
            } catch (error) {
                showToast('加载转发失败记录失败', 'error');
            }
        }

        function toggleForwardingLogsDrawer() {
            const container = document.getElementById('forwardingLogsContainer');
            if (container?.hidden) {
                loadForwardingLogs();
                return;
            }
            hideForwardingLogs();
        }

        function toggleFailedForwardingLogsDrawer() {
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container?.hidden) {
                loadFailedForwardingLogs();
                return;
            }
            hideFailedForwardingLogs();
        }

        function hideForwardingLogs() {
            const drawer = document.getElementById('forwardingLogsDrawer');
            const container = document.getElementById('forwardingLogsContainer');
            if (container) {
                container.hidden = true;
            }
            if (drawer) {
                drawer.classList.remove('is-open');
            }
            const toggleBtn = document.getElementById('forwardingLogsToggleBtn');
            if (toggleBtn) {
                toggleBtn.textContent = '查看历史';
            }
        }

        function hideFailedForwardingLogs() {
            const drawer = document.getElementById('failedForwardingLogsDrawer');
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container) {
                container.hidden = true;
            }
            if (drawer) {
                drawer.classList.remove('is-open');
            }
            const toggleBtn = document.getElementById('failedForwardingLogsToggleBtn');
            if (toggleBtn) {
                toggleBtn.textContent = '查看失败';
            }
        }

        // 格式化日期时间
        function formatDateTime(dateStr) {
            if (!dateStr) return '-';

            let date;
            if (dateStr instanceof Date) {
                date = dateStr;
            } else if (typeof dateStr === 'number' || /^\d+$/.test(String(dateStr))) {
                const timestamp = Number(dateStr);
                date = new Date(timestamp < 1000000000000 ? timestamp * 1000 : timestamp);
            } else {
                // 如果字符串不包含时区信息，假定为 UTC 时间
                if (!dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                    dateStr = dateStr + 'Z';
                }
                date = new Date(dateStr);
            }

            const now = new Date();
            const diff = now - date;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);

            if (minutes < 1) return '刚刚';
            if (minutes < 60) return `${minutes}分钟前`;
            if (hours < 24) return `${hours}小时前`;
            if (days < 7) return `${days}天前`;

            return date.toLocaleString('zh-CN', {
                timeZone: getAppTimeZone(),
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        // 统一关闭所有模态框的函数 (修复 bug：防止模态框意外残留)
        function closeAllModals() {
            document.querySelectorAll('.modal').forEach(modal => {
                modal.classList.remove('show');
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
            });

            const settingsPassword = document.getElementById('settingsPassword');
            if (settingsPassword) {
                settingsPassword.value = '';
            }

            const exportVerifyPassword = document.getElementById('exportVerifyPassword');
            if (exportVerifyPassword) {
                exportVerifyPassword.value = '';
            }

            resetRefreshModalRuntime();
            hideForwardingLogs();
            hideFailedForwardingLogs();

            closeFullscreenEmail();
            updateModalBodyState();
        }

        // 键盘快捷键
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeNavbarActionsMenu();
                closeMobilePanels();
                closeAccountActionMenus();
                closeTagFilterDropdown();
                closeAllModals();
            }
        });
