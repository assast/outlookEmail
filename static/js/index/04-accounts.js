        /* global accountsCache, applyEmailListCache, closeMobilePanels, currentAccount, currentEmailDetail, currentEmailId, currentEmails, currentFolder, currentGroupId, currentMethod, currentSkip, emailListCache, getEmailListCacheEntry, getNextEmailSkipFromCache, handleApiError, hasMoreEmails, hideModal, isTempEmailGroup, loadAccountsByGroup, loadEmails, loadGroups, renderEmailList, scheduleEmailListLoadCheck, showEmailList, showToast, updateMobileContext */

        // ==================== 账号相关 ====================

        // 选择账号
        function selectAccount(email) {
            currentAccount = email;
            isTempEmailGroup = false;
            currentFolder = 'all'; // 重置为全部邮件
            currentEmailId = null;
            currentEmailDetail = null;

            document.getElementById('currentAccount').classList.add('show');
            document.getElementById('currentAccountEmail').textContent = email;
            showEmailList({ scheduleLoadCheck: false });
            closeMobilePanels();
            updateMobileContext();

            document.querySelectorAll('.account-item').forEach(item => {
                item.classList.remove('active');
                const emailEl = item.querySelector('.account-email');
                if (emailEl && emailEl.textContent.includes(email)) {
                    item.classList.add('active');
                }
            });

            // 显示文件夹切换按钮
            const folderTabs = document.getElementById('folderTabs');
            if (folderTabs) {
                folderTabs.style.display = 'flex';
                // 重置为全部邮件
                document.querySelectorAll('.folder-tab').forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.folder === 'all');
                });
            }

            const cache = getEmailListCacheEntry(email, 'all');

            // 检查缓存
            if (cache) {
                applyEmailListCache(cache, { scheduleLoadCheck: false });
            } else {
                document.getElementById('emailList').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📬</div>
                        <div class="empty-state-text">正在自动刷新全部邮件...</div>
                    </div>
                `;
                document.getElementById('emailCount').textContent = '';
                document.getElementById('methodTag').style.display = 'none';
                currentEmails = [];
            }

            document.getElementById('emailDetail').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">选择一封邮件查看详情</div>
                </div>
            `;
            document.getElementById('emailDetailToolbar').style.display = 'none';

            // 首次进入未命中缓存时才自动加载
            if (!cache) {
                loadEmails(email);
            }
        }

        // 隐藏添加账号模态框
        function hideAddAccountModal() {
            hideModal('addAccountModal');
        }

        // 隐藏编辑账号模态框
        function hideEditAccountModal() {
            if (typeof clearEditAccountSecrets === 'function') {
                clearEditAccountSecrets();
            }
            document.getElementById('editTagFilterDropdown')?.classList.remove('open');
            hideModal('editAccountModal');
        }

        // 删除当前编辑的账号
        async function deleteCurrentAccount() {
            const accountId = document.getElementById('editAccountId').value;
            const email = document.getElementById('editEmail').value;
            const groupId = parseInt(document.getElementById('editGroupSelect').value);

            if (!(await showConfirmModal(`确定要删除账号 ${email} 吗？`, { title: '删除账号', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');
                    hideEditAccountModal();

                    // 清除缓存
                    delete accountsCache[groupId];

                    if (currentAccount === email) {
                        currentAccount = null;
                        document.getElementById('currentAccount').classList.remove('show');
                        document.getElementById('emailList').innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">📬</div>
                                <div class="empty-state-text">请从左侧选择一个邮箱账号</div>
                            </div>
                        `;
                        document.getElementById('emailDetail').innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">📄</div>
                                <div class="empty-state-text">选择一封邮件查看详情</div>
                            </div>
                        `;
                        showEmailList();
                        updateMobileContext();
                    }

                    // 刷新分组列表
                    loadGroups();

                    // 刷新当前分组的邮箱列表
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }

        // 切换账号状态（启用/停用）
        async function toggleAccountStatus(accountId, currentStatus) {
            const newStatus = currentStatus === 'inactive' ? 'active' : 'inactive';
            const action = newStatus === 'inactive' ? '停用' : '启用';

            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: newStatus })
                });

                const data = await response.json();

                if (data.success) {
                    showToast(`${action}成功`, 'success');

                    // 清除当前分组的缓存
                    if (currentGroupId) {
                        delete accountsCache[currentGroupId];
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    handleApiError(data, `${action}账号失败`);
                }
            } catch (error) {
                showToast(`${action}失败`, 'error');
            }
        }

        // 删除账号（快捷方式）
        async function deleteAccount(accountId, email) {
            if (!(await showConfirmModal(`确定要删除账号 ${email} 吗？`, { title: '删除账号', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');
                    invalidateAccountCaches();
                    resetSelectedAccountViewIfDeleted([email]);
                    loadGroups();
                    await refreshVisibleAccountList(true);
                } else {
                    handleApiError(data, '删除账号失败');
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }

        // 显示导出邮箱模态框
        async function showExportModal() {
            showModal('exportModal');
            await loadExportGroupList();
        }

        // 隐藏导出邮箱模态框
        function hideExportModal() {
            hideModal('exportModal');
        }

        // 加载导出分组列表
        async function loadExportGroupList() {
            const container = document.getElementById('exportGroupList');
            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                // 使用已加载的分组数据
                if (groups.length === 0) {
                    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #999;">暂无分组</div>';
                } else {
                    const sortedGroups = typeof flattenGroupTree === 'function' && typeof buildGroupTree === 'function'
                        ? flattenGroupTree(buildGroupTree(groups))
                        : groups;

                    container.innerHTML = sortedGroups.map(group => {
                        const level = typeof normalizeGroupLevel === 'function' ? normalizeGroupLevel(group) : 1;
                        const paddingLeft = 12 + (level - 1) * 16;
                        const count = group.descendant_account_count ?? group.account_count ?? 0;
                        return `
                            <label style="display: flex; align-items: center; gap: 10px; padding: 10px 12px; padding-left: ${paddingLeft}px; cursor: pointer; border-radius: 6px; transition: background-color 0.15s, opacity 0.15s;"
                                   onmouseover="this.style.backgroundColor='#f5f5f5'"
                                   onmouseout="this.style.backgroundColor='transparent'">
                                <input type="checkbox" class="export-group-checkbox" value="${group.id}" style="width: 16px; height: 16px;">
                                <span style="display: flex; align-items: center; gap: 8px; flex: 1;">
                                    <span style="width: 12px; height: 12px; border-radius: 3px; background-color: ${group.color || '#666'}"></span>
                                    <span style="display: inline-flex; align-items: center; gap: 8px; min-width: 0; flex: 1;">
                                        <span style="font-size: 14px; color: #1a1a1a; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(normalizeGroupName(group.name))}</span>
                                        ${formatGroupIdBadgeText(group.id) ? `<span class="group-id-badge">${escapeHtml(formatGroupIdBadgeText(group.id))}</span>` : ''}
                                    </span>
                                </span>
                                <span style="font-size: 12px; color: #999; background-color: #f0f0f0; padding: 2px 8px; border-radius: 10px;">${count || 0}</span>
                            </label>
                        `;
                    }).join('');

                    // 绑定复选框变化事件
                    document.querySelectorAll('.export-group-checkbox').forEach(cb => {
                        cb.addEventListener('change', handleExportCheckboxChange);
                    });
                    syncExportGroupCheckboxStates();
                }
            } catch (error) {
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: #dc3545;">加载失败</div>';
            }

            // 重置全选复选框
            document.getElementById('selectAllGroups').checked = false;
        }

        // 获取下级分组的 ID 列表
        function getDescendantGroupIds(groupId) {
            const descendants = [];
            const queue = [Number(groupId)];
            while (queue.length > 0) {
                const currentId = queue.shift();
                groups.forEach(g => {
                    if (g.parent_id && Number(g.parent_id) === currentId) {
                        descendants.push(g.id);
                        queue.push(g.id);
                    }
                });
            }
            return descendants;
        }

        function hasSelectedAncestorGroup(groupId, selectedGroupIds) {
            let current = groups.find(g => Number(g.id) === Number(groupId));
            while (current && current.parent_id) {
                const parentId = Number(current.parent_id);
                if (selectedGroupIds.has(parentId)) {
                    return true;
                }
                current = groups.find(g => Number(g.id) === parentId);
            }
            return false;
        }

        function syncExportGroupCheckboxStates() {
            const checkboxes = Array.from(document.querySelectorAll('.export-group-checkbox'));
            const selectedGroupIds = new Set(checkboxes
                .filter(cb => cb.checked)
                .map(cb => Number(cb.value)));

            checkboxes.forEach(cb => {
                const coveredByParent = hasSelectedAncestorGroup(Number(cb.value), selectedGroupIds);
                cb.disabled = coveredByParent;
                if (coveredByParent) {
                    cb.checked = true;
                }
                const row = cb.closest('label');
                if (row) {
                    row.style.opacity = coveredByParent ? '0.45' : '';
                    row.style.cursor = coveredByParent ? 'default' : 'pointer';
                }
            });
        }

        // 处理导出复选框变化
        function handleExportCheckboxChange(event) {
            const cb = event.target;
            if (!cb) return;
            const groupId = Number(cb.value);
            const isChecked = cb.checked;

            const descendants = getDescendantGroupIds(groupId);
            descendants.forEach(descId => {
                const descCb = document.querySelector(`.export-group-checkbox[value="${descId}"]`);
                if (descCb) {
                    descCb.checked = isChecked;
                }
            });
            syncExportGroupCheckboxStates();
        }

        // 全选/取消全选分组
        function toggleSelectAllGroups() {
            const selectAll = document.getElementById('selectAllGroups').checked;
            document.querySelectorAll('.export-group-checkbox').forEach(cb => {
                cb.checked = selectAll;
            });
            syncExportGroupCheckboxStates();
        }

        // 存储待导出的分组或账号 ID
        let pendingExportGroupIds = [];
        let pendingExportAccountIds = [];

        // 导出选中的分组
        async function exportSelectedGroups() {
            const checkboxes = Array.from(document.querySelectorAll('.export-group-checkbox:checked'));
            const selectedGroupIds = checkboxes.map(cb => parseInt(cb.value));

            // 过滤掉其父分组也同时被选中的子分组，避免重复导出
            const groupIds = selectedGroupIds.filter(groupId => {
                let current = groups.find(g => Number(g.id) === Number(groupId));
                while (current && current.parent_id) {
                    if (selectedGroupIds.includes(Number(current.parent_id))) {
                        return false;
                    }
                    current = groups.find(g => Number(g.id) === Number(current.parent_id));
                }
                return true;
            });

            if (groupIds.length === 0) {
                showToast('请选择要导出的分组', 'error');
                return;
            }

            pendingExportGroupIds = groupIds;
            pendingExportAccountIds = [];

            // 显示密码确认对话框
            hideExportModal();
            showExportVerifyModal();
        }

        function startSelectedAccountExport(accountIds) {
            const normalizedIds = Array.from(new Set((accountIds || [])
                .map(accountId => parseInt(accountId, 10))
                .filter(Number.isFinite)));

            if (!normalizedIds.length) {
                showToast('请先选择要导出的邮箱', 'error');
                return;
            }

            pendingExportGroupIds = [];
            pendingExportAccountIds = normalizedIds;
            showExportVerifyModal();
        }

        // 显示导出密码确认对话框
        function showExportVerifyModal() {
            showModal('exportVerifyModal');
            const passwordInput = document.getElementById('exportVerifyPassword');
            if (passwordInput) {
                passwordInput.value = '';
                passwordInput.focus();
            }
        }

        // 隐藏导出密码确认对话框
        function hideExportVerifyModal() {
            hideModal('exportVerifyModal');
            const passwordInput = document.getElementById('exportVerifyPassword');
            if (passwordInput) {
                passwordInput.value = '';
            }
        }

        // 确认导出验证
        async function confirmExportVerify() {
            const password = document.getElementById('exportVerifyPassword').value;

            if (!password) {
                showToast('请输入密码', 'error');
                return;
            }

            try {
                // 获取验证token
                const verifyResponse = await fetch('/api/export/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });

                const verifyData = await verifyResponse.json();

                if (!verifyData.success) {
                    showToast(verifyData.error || '密码错误', 'error');
                    return;
                }

                const verifyToken = verifyData.verify_token;

                const exportPayload = {
                    verify_token: verifyToken
                };
                if (pendingExportAccountIds.length > 0) {
                    exportPayload.account_ids = pendingExportAccountIds;
                } else {
                    exportPayload.group_ids = pendingExportGroupIds;
                }

                // 执行导出
                const response = await fetch('/api/accounts/export-selected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(exportPayload)
                });

                const contentType = response.headers.get('content-type') || '';
                if (response.ok && !contentType.includes('application/json')) {
                    // 获取文件名
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = 'accounts.txt';
                    if (contentDisposition) {
                        const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?([^;\n]+)/i);
                        if (match) {
                            filename = decodeURIComponent(match[1]);
                        }
                    }

                    // 下载文件
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);

                    showToast('导出成功', 'success');
                    hideExportVerifyModal();
                } else {
                    const data = await response.json();
                    handleApiError(data, '导出失败');
                }
            } catch (error) {
                showToast('导出失败', 'error');
            }
        }
