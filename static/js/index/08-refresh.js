        /* global closeAccountActionMenus, closeFullscreenEmail, closeMobilePanels, closeNavbarActionsMenu, closeTagFilterDropdown, escapeHtml, formatDate, handleApiError, hideModal, showEditAccountModal, showModal, showToast, updateModalBodyState */

        // ==================== Token 刷新管理 ====================

        // 显示刷新模态框
        async function showRefreshModal(autoLoadFailedList = true) {
            showModal('refreshModal');
            // 加载统计数据
            await loadRefreshStats();
            // 自动加载失败列表（如果有失败记录）
            if (autoLoadFailedList) {
                await autoLoadFailedListIfNeeded();
            }
        }

        // 自动加载失败列表（如果有失败记录）
        async function autoLoadFailedListIfNeeded() {
            try {
                const response = await fetch('/api/accounts/refresh-logs/failed');
                const data = await response.json();

                if (data.success && data.logs && data.logs.length > 0) {
                    // 有失败记录，自动显示失败列表
                    showFailedListFromData(data.logs.map(log => ({
                        id: log.account_id,
                        email: log.account_email,
                        error: log.error_message
                    })));
                }
            } catch (error) {
                console.error('自动加载失败列表失败:', error);
            }
        }

        // 隐藏刷新模态框
        function hideRefreshModal() {
            hideModal('refreshModal');

            // 确保所有内容都被隐藏，防止残留
            const progress = document.getElementById('refreshProgress');
            if (progress) {
                progress.style.display = 'none';
            }
            const failedList = document.getElementById('failedListContainer');
            if (failedList) {
                failedList.style.display = 'none';
            }
            const logsContainer = document.getElementById('refreshLogsContainer');
            if (logsContainer) {
                logsContainer.style.display = 'none';
            }

            // 重置按钮状态
            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = false;
                refreshAllBtn.textContent = '🔄 全量刷新';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = false;
                retryFailedBtn.textContent = '🔁 重试失败';
            }
        }

        // 加载刷新统计
        async function loadRefreshStats() {
            try {
                const response = await fetch('/api/accounts/refresh-stats');
                const data = await response.json();

                console.log('刷新统计数据:', data);

                if (data.success) {
                    const stats = data.stats;

                    // 优先使用保存的本地刷新时间
                    if (window.lastRefreshTime && window.lastRefreshTime instanceof Date) {
                        document.getElementById('lastRefreshTime').textContent = formatDateTime(window.lastRefreshTime.toISOString());
                    } else if (stats.last_refresh_time) {
                        document.getElementById('lastRefreshTime').textContent = formatDateTime(stats.last_refresh_time);
                    } else {
                        document.getElementById('lastRefreshTime').textContent = '-';
                    }

                    document.getElementById('totalRefreshCount').textContent = stats.total;
                    document.getElementById('successRefreshCount').textContent = stats.success_count;
                    document.getElementById('failedRefreshCount').textContent = stats.failed_count;

                    console.log('统计数据已更新到页面');
                }
            } catch (error) {
                console.error('加载刷新统计失败:', error);
            }
        }

        // 全量刷新所有账号
        async function refreshAllAccounts() {
            const btn = document.getElementById('refreshAllBtn');
            const progress = document.getElementById('refreshProgress');
            const progressText = document.getElementById('refreshProgressText');

            if (btn.disabled) return;

            if (!(await showConfirmModal('确定要刷新所有账号的 Token 吗？', { title: '刷新 Token', confirmText: '确认刷新', danger: false }))) {
                return;
            }

            btn.disabled = true;
            btn.textContent = '刷新中...';
            progress.style.display = 'block';
            progressText.innerHTML = '正在初始化...';

            try {
                const eventSource = new EventSource('/api/accounts/trigger-scheduled-refresh?force=true');
                let totalCount = 0;
                let successCount = 0;
                let failedCount = 0;

                eventSource.onmessage = function (event) {
                    try {
                        const data = JSON.parse(event.data);

                        if (data.type === 'start') {
                            totalCount = data.total;
                            const delayInfo = data.delay_seconds > 0 ? `（间隔 ${data.delay_seconds} 秒）` : '';
                            progressText.innerHTML = `总共 <strong>${totalCount}</strong> 个账号${delayInfo}，准备开始刷新...`;
                            // 初始化统计
                            document.getElementById('totalRefreshCount').textContent = totalCount;
                            document.getElementById('successRefreshCount').textContent = '0';
                            document.getElementById('failedRefreshCount').textContent = '0';
                        } else if (data.type === 'progress') {
                            successCount = data.success_count;
                            failedCount = data.failed_count;
                            // 实时更新统计
                            document.getElementById('successRefreshCount').textContent = successCount;
                            document.getElementById('failedRefreshCount').textContent = failedCount;
                            progressText.innerHTML = `
                                正在处理: <strong>${data.email}</strong><br>
                                进度: <strong>${data.current}/${data.total}</strong> |
                                成功: <strong style="color: #28a745;">${successCount}</strong> |
                                失败: <strong style="color: #dc3545;">${failedCount}</strong>
                            `;
                        } else if (data.type === 'delay') {
                            progressText.innerHTML += `<br><span style="color: #999;">等待 ${data.seconds} 秒后继续...</span>`;
                        } else if (data.type === 'complete') {
                            eventSource.close();
                            progress.style.display = 'none';
                            btn.disabled = false;
                            btn.textContent = '🔄 全量刷新';

                            // 直接更新统计数据，使用本地时间
                            const now = new Date();
                            window.lastRefreshTime = now; // 保存刷新时间
                            document.getElementById('lastRefreshTime').textContent = '刚刚';
                            document.getElementById('totalRefreshCount').textContent = data.total;
                            document.getElementById('successRefreshCount').textContent = data.success_count;
                            document.getElementById('failedRefreshCount').textContent = data.failed_count;

                            showToast(`刷新完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                                data.failed_count > 0 ? 'warning' : 'success');

                            // 如果有失败的，显示失败列表
                            if (data.failed_count > 0) {
                                showFailedListFromData(data.failed_list);
                            }

                            // 刷新账号列表以更新刷新时间
                            if (currentGroupId) {
                                loadAccountsByGroup(currentGroupId, true);
                            }
                        }
                    } catch (e) {
                        console.error('解析进度数据失败:', e);
                    }
                };

                eventSource.onerror = function (error) {
                    console.error('EventSource 错误:', error);
                    eventSource.close();
                    progress.style.display = 'none';
                    btn.disabled = false;
                    btn.textContent = '🔄 全量刷新';
                    showToast('刷新过程中出现错误', 'error');
                };

            } catch (error) {
                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔄 全量刷新';
                showToast('刷新请求失败', 'error');
            }
        }

        // 重试失败的账号
        async function retryFailedAccounts() {
            const btn = document.getElementById('retryFailedBtn');
            const progress = document.getElementById('refreshProgress');
            const progressText = document.getElementById('refreshProgressText');

            if (btn.disabled) return;

            btn.disabled = true;
            btn.textContent = '重试中...';
            progress.style.display = 'block';
            progressText.textContent = '正在重试失败的账号...';

            try {
                const response = await fetch('/api/accounts/refresh-failed', {
                    method: 'POST'
                });
                const data = await response.json();

                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔁 重试失败';

                if (data.success) {
                    if (data.total === 0) {
                        showToast('没有需要重试的失败账号', 'info');
                    } else {
                        showToast(`重试完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                            data.failed_count > 0 ? 'warning' : 'success');

                        // 刷新统计
                        loadRefreshStats();

                        // 如果还有失败的，显示失败列表
                        if (data.failed_count > 0) {
                            showFailedListFromData(data.failed_list);
                        } else {
                            hideFailedList();
                        }
                    }
                } else {
                    handleApiError(data, '重试失败');
                }
            } catch (error) {
                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔁 重试失败';
                showToast('重试请求失败', 'error');
            }
        }

        // 单个账号重试
        async function retrySingleAccount(accountId, accountEmail) {
            try {
                const response = await fetch(`/api/accounts/${accountId}/retry-refresh`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    showToast(`${accountEmail} 刷新成功`, 'success');
                    loadRefreshStats();

                    // 刷新失败列表
                    loadFailedLogs();
                } else {
                    handleApiError(data, `${accountEmail} 刷新失败`);
                }
            } catch (error) {
                handleApiError({ success: false, error: { message: '刷新请求失败', details: error.message, code: 'NETWORK_ERROR', type: 'Frontend' } });
            }
        }

        // 显示失败列表（从数据）
        function showFailedListFromData(failedList) {
            const container = document.getElementById('failedListContainer');
            const listEl = document.getElementById('failedList');

            // 隐藏其他列表
            hideRefreshLogs();

            if (!failedList || failedList.length === 0) {
                container.style.display = 'none';
                return;
            }

            let html = '';
            failedList.forEach(item => {
                html += `
                    <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: start;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(item.email)}</div>
                            <div style="font-size: 12px; color: #dc3545;">${escapeHtml(item.error || '未知错误')}</div>
                        </div>
                        <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${item.id}, '${escapeHtml(item.email)}')">
                            重试
                        </button>
                    </div>
                `;
            });

            listEl.innerHTML = html;
            container.style.display = 'block';
        }

        // 隐藏失败列表
        function hideFailedList() {
            const container = document.getElementById('failedListContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        // 加载失败日志
        async function loadFailedLogs() {
            const container = document.getElementById('failedListContainer');
            const listEl = document.getElementById('failedList');

            hideRefreshLogs();

            try {
                const response = await fetch('/api/accounts/refresh-logs/failed');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无失败状态的邮箱</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: center;">
                                    <div style="flex: 1;">
                                        <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: #dc3545;">${escapeHtml(log.error_message || '未知错误')}</div>
                                        <div style="font-size: 11px; color: #999; margin-top: 4px;">最后刷新: ${formatDateTime(log.created_at)}</div>
                                    </div>
                                    <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${log.account_id}, '${escapeJs(log.account_email)}')">
                                        重试
                                    </button>
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载失败邮箱列表失败', 'error');
            }
        }

        // 加载刷新历史
        async function loadRefreshLogs() {
            const container = document.getElementById('refreshLogsContainer');
            const listEl = document.getElementById('refreshLogsList');

            try {
                const response = await fetch('/api/accounts/refresh-logs?limit=1000');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无刷新历史</div>';
                    } else {
                        listEl.innerHTML = `<div style="padding: 12px; background-color: #f8f9fa; border-bottom: 1px solid #e5e5e5; font-size: 13px; color: #666;">近半年刷新历史（共 ${data.logs.length} 条）</div>`;
                        let html = '';
                        data.logs.forEach(log => {
                            const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                            const statusText = log.status === 'success' ? '成功' : '失败';
                            const typeText = log.refresh_type === 'manual' ? '手动' : '自动';
                            const typeColor = log.refresh_type === 'manual' ? '#007bff' : '#28a745';
                            const typeBgColor = log.refresh_type === 'manual' ? '#e7f3ff' : '#e8f5e9';

                            html += `
                                <div style="padding: 14px; border-bottom: 1px solid #e5e5e5; transition: background-color 0.2s;"
                                     onmouseover="this.style.backgroundColor='#f8f9fa'"
                                     onmouseout="this.style.backgroundColor='transparent'">
                                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
                                        <div style="font-weight: 600; font-size: 14px;">${escapeHtml(log.account_email)}</div>
                                        <div style="display: flex; gap: 8px; align-items: center;">
                                            <span style="font-size: 11px; padding: 3px 8px; background-color: ${typeBgColor}; color: ${typeColor}; border-radius: 4px; font-weight: 500;">${typeText}</span>
                                            <span style="font-size: 13px; color: ${statusColor}; font-weight: 600;">${statusText}</span>
                                        </div>
                                    </div>
                                    <div style="font-size: 12px; color: #888;">${formatDateTime(log.created_at)}</div>
                                    ${log.error_message ? `<div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message)}</div>` : ''}
                                </div>
                            `;
                        });
                        listEl.innerHTML += html;
                    }
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载刷新历史失败', 'error');
            }
        }

        async function loadForwardingLogs() {
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
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载转发历史失败', 'error');
            }
        }

        async function loadFailedForwardingLogs() {
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
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载转发失败记录失败', 'error');
            }
        }

        // 隐藏刷新历史
        function hideRefreshLogs() {
            const container = document.getElementById('refreshLogsContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        function hideForwardingLogs() {
            const container = document.getElementById('forwardingLogsContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        function hideFailedForwardingLogs() {
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container) {
                container.style.display = 'none';
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
                timeZone: 'Asia/Shanghai',
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

            hideFailedList();
            hideRefreshLogs();
            hideForwardingLogs();
            hideFailedForwardingLogs();

            const progress = document.getElementById('refreshProgress');
            if (progress) {
                progress.style.display = 'none';
            }

            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = false;
                refreshAllBtn.textContent = '🔄 全量刷新';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = false;
                retryFailedBtn.textContent = '🔁 重试失败';
            }

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
