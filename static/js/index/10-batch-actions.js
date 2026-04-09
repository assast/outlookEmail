        // ==================== 批量操作 ====================

        // 更新批量操作栏状态
        function updateBatchActionBar() {
            const checked = Array.from(document.querySelectorAll('.account-select-checkbox:checked'));
            const allCheckboxes = document.querySelectorAll('#accountList .account-select-checkbox');
            const bar = document.getElementById('batchActionBar');
            const countSpan = document.getElementById('selectedCount');
            const selectAllBtn = document.getElementById('accountSelectAllBtn');
            const batchRefreshBtn = document.getElementById('batchRefreshTokensBtn');
            const batchEnableForwardingBtn = document.getElementById('batchEnableForwardingBtn');
            const batchDisableForwardingBtn = document.getElementById('batchDisableForwardingBtn');
            const batchDeleteBtn = document.getElementById('batchDeleteAccountsBtn');
            const panel = document.getElementById('accountPanel');
            const refreshableChecked = checked.filter(cb => cb.dataset.refreshable === 'true');
            const enableForwardingChecked = checked.filter(cb => cb.dataset.forwardEnabled !== 'true');
            const disableForwardingChecked = checked.filter(cb => cb.dataset.forwardEnabled === 'true');
            const isForwardingUpdating = batchEnableForwardingBtn?.dataset.loading === 'true'
                || batchDisableForwardingBtn?.dataset.loading === 'true';

            if (checked.length > 0) {
                bar.style.display = 'flex';
                panel?.classList.add('batch-toolbar-active');
                countSpan.textContent = refreshableChecked.length > 0 && refreshableChecked.length !== checked.length
                    ? `已选 ${checked.length} 项，可刷新 ${refreshableChecked.length} 项`
                    : `已选 ${checked.length} 项`;
                if (selectAllBtn) {
                    selectAllBtn.textContent = allCheckboxes.length > 0 && checked.length === allCheckboxes.length
                        ? '取消全选'
                        : '全选';
                }
                if (batchRefreshBtn) {
                    const isRefreshing = batchRefreshBtn.dataset.loading === 'true';
                    batchRefreshBtn.disabled = refreshableChecked.length === 0 || isRefreshing;
                    batchRefreshBtn.title = refreshableChecked.length === 0
                        ? '所选账号中没有可刷新的 Outlook 账号'
                        : '';
                    if (!isRefreshing) {
                        batchRefreshBtn.textContent = refreshableChecked.length > 0
                            ? `刷新 Token${refreshableChecked.length !== checked.length ? ` (${refreshableChecked.length})` : ''}`
                            : '刷新 Token';
                    }
                }
                if (batchEnableForwardingBtn) {
                    batchEnableForwardingBtn.disabled = enableForwardingChecked.length === 0 || isForwardingUpdating;
                    batchEnableForwardingBtn.title = enableForwardingChecked.length === 0
                        ? '所选账号已全部开启转发'
                        : '';
                    if (batchEnableForwardingBtn.dataset.loading !== 'true') {
                        batchEnableForwardingBtn.textContent = enableForwardingChecked.length > 0
                            ? `开启转发${enableForwardingChecked.length !== checked.length ? ` (${enableForwardingChecked.length})` : ''}`
                            : '开启转发';
                    }
                }
                if (batchDisableForwardingBtn) {
                    batchDisableForwardingBtn.disabled = disableForwardingChecked.length === 0 || isForwardingUpdating;
                    batchDisableForwardingBtn.title = disableForwardingChecked.length === 0
                        ? '所选账号已全部取消转发'
                        : '';
                    if (batchDisableForwardingBtn.dataset.loading !== 'true') {
                        batchDisableForwardingBtn.textContent = disableForwardingChecked.length > 0
                            ? `取消转发${disableForwardingChecked.length !== checked.length ? ` (${disableForwardingChecked.length})` : ''}`
                            : '取消转发';
                    }
                }
                if (batchDeleteBtn) {
                    const isDeleting = batchDeleteBtn.dataset.loading === 'true';
                    batchDeleteBtn.disabled = isDeleting;
                    if (!isDeleting) {
                        batchDeleteBtn.textContent = checked.length > 1 ? `删除 (${checked.length})` : '删除';
                    }
                }
            } else {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
                if (batchRefreshBtn) {
                    batchRefreshBtn.disabled = false;
                    batchRefreshBtn.dataset.loading = 'false';
                    batchRefreshBtn.textContent = '刷新 Token';
                    batchRefreshBtn.title = '';
                }
                if (batchEnableForwardingBtn) {
                    batchEnableForwardingBtn.disabled = false;
                    batchEnableForwardingBtn.dataset.loading = 'false';
                    batchEnableForwardingBtn.textContent = '开启转发';
                    batchEnableForwardingBtn.title = '';
                }
                if (batchDisableForwardingBtn) {
                    batchDisableForwardingBtn.disabled = false;
                    batchDisableForwardingBtn.dataset.loading = 'false';
                    batchDisableForwardingBtn.textContent = '取消转发';
                    batchDisableForwardingBtn.title = '';
                }
                if (batchDeleteBtn) {
                    batchDeleteBtn.disabled = false;
                    batchDeleteBtn.dataset.loading = 'false';
                    batchDeleteBtn.textContent = '删除';
                }
            }
        }

        function toggleSelectAllAccounts() {
            const checkboxes = Array.from(document.querySelectorAll('#accountList .account-select-checkbox'));
            if (!checkboxes.length) return;

            const shouldClear = checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => {
                cb.checked = !shouldClear;
            });
            updateBatchActionBar();
        }

        function clearAccountSelection() {
            document.querySelectorAll('#accountList .account-select-checkbox').forEach(cb => {
                cb.checked = false;
            });
            updateBatchActionBar();
        }

        async function refreshSelectedAccounts() {
            const btn = document.getElementById('batchRefreshTokensBtn');
            if (!btn || btn.disabled) return;

            const checked = Array.from(document.querySelectorAll('#accountList .account-select-checkbox:checked'));
            const accountIds = checked
                .map(cb => parseInt(cb.value, 10))
                .filter(Number.isFinite);
            const refreshableCount = checked.filter(cb => cb.dataset.refreshable === 'true').length;

            if (!accountIds.length) {
                showToast('请先选择要刷新的邮箱', 'error');
                return;
            }
            if (!refreshableCount) {
                showToast('所选账号中没有可刷新的 Outlook 账号', 'error');
                return;
            }
            if (!confirm(`确定要刷新所选 ${accountIds.length} 个邮箱的 Token 吗？`)) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '刷新中...';

            try {
                const response = await fetch('/api/accounts/refresh-selected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '批量刷新失败');
                    return;
                }

                const toastType = data.failed_count > 0 || data.skipped_count > 0 ? 'warning' : 'success';
                showToast(
                    `批量刷新完成：成功 ${data.success_count}，失败 ${data.failed_count}，跳过 ${data.skipped_count}`,
                    toastType
                );

                if (data.failed_count > 0) {
                    await showRefreshModal(false);
                    showFailedListFromData(data.failed_list || []);
                } else {
                    loadRefreshStats();
                }

                clearAccountSelection();
                await refreshVisibleAccountList(true);
            } catch (error) {
                showToast('批量刷新请求失败', 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateBatchActionBar();
            }
        }

        async function updateForwardingForSelectedAccounts(targetEnabled) {
            const btn = document.getElementById(targetEnabled ? 'batchEnableForwardingBtn' : 'batchDisableForwardingBtn');
            if (!btn || btn.disabled) return;

            const checked = Array.from(document.querySelectorAll('#accountList .account-select-checkbox:checked'));
            const accountIds = checked
                .map(cb => parseInt(cb.value, 10))
                .filter(Number.isFinite);
            const eligibleCount = checked.filter(cb => (cb.dataset.forwardEnabled === 'true') !== targetEnabled).length;
            const actionLabel = targetEnabled ? '开启转发' : '取消转发';
            const loadingLabel = targetEnabled ? '开启中...' : '取消中...';
            const finishedLabel = targetEnabled ? '已全部开启转发' : '已全部取消转发';
            const skippedLabel = targetEnabled ? '已开启' : '已取消';

            if (!accountIds.length) {
                showToast(`请先选择要${actionLabel}的邮箱`, 'error');
                return;
            }
            if (!eligibleCount) {
                showToast(`所选账号${finishedLabel}`, 'error');
                return;
            }

            const skippedCount = accountIds.length - eligibleCount;
            const confirmMessage = skippedCount > 0
                ? `确定要为所选 ${accountIds.length} 个邮箱${actionLabel}吗？其中 ${skippedCount} 个${skippedLabel}账号会自动跳过。`
                : `确定要为所选 ${accountIds.length} 个邮箱${actionLabel}吗？`;
            if (!confirm(confirmMessage)) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = loadingLabel;

            try {
                const response = await fetch('/api/accounts/batch-update-forwarding', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        forward_enabled: targetEnabled
                    })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, `批量${actionLabel}失败`);
                    return;
                }

                showToast(data.message || `已为 ${eligibleCount} 个账号${actionLabel}`, 'success');
                invalidateAccountCaches();
                clearAccountSelection();
                await refreshVisibleAccountList(true);
            } catch (error) {
                showToast(`批量${actionLabel}失败`, 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateBatchActionBar();
            }
        }

        async function enableForwardingForSelectedAccounts() {
            await updateForwardingForSelectedAccounts(true);
        }

        async function disableForwardingForSelectedAccounts() {
            await updateForwardingForSelectedAccounts(false);
        }

        async function deleteSelectedAccounts() {
            const btn = document.getElementById('batchDeleteAccountsBtn');
            if (!btn || btn.disabled) return;

            const checked = Array.from(document.querySelectorAll('#accountList .account-select-checkbox:checked'));
            const accountIds = checked
                .map(cb => parseInt(cb.value, 10))
                .filter(Number.isFinite);
            const accountEmails = checked
                .map(cb => cb.dataset.accountEmail || '')
                .filter(Boolean);

            if (!accountIds.length) {
                showToast('请先选择要删除的邮箱', 'error');
                return;
            }

            if (!confirm(`确定要删除所选 ${accountIds.length} 个邮箱吗？此操作不可恢复。`)) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '删除中...';

            try {
                const response = await fetch('/api/accounts/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '批量删除失败');
                    return;
                }

                const deletedEmails = Array.isArray(data.deleted_accounts)
                    ? data.deleted_accounts.map(item => item.email).filter(Boolean)
                    : accountEmails;

                showToast(data.message || `已删除 ${deletedEmails.length} 个账号`, 'success');
                invalidateAccountCaches();
                resetSelectedAccountViewIfDeleted(deletedEmails);
                clearAccountSelection();
                loadGroups();
                await refreshVisibleAccountList(true);
            } catch (error) {
                showToast('批量删除失败', 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateBatchActionBar();
            }
        }

        let batchActionType = ''; // 'add' or 'remove'

        // 显示批量打标模态框
        async function showBatchTagModal(type) {
            batchActionType = type;
            document.getElementById('batchTagTitle').textContent = type === 'add' ? '批量添加标签' : '批量移除标签';
            showModal('batchTagModal');

            // 加载标签选项
            await loadTagsForSelect();
        }

        function hideBatchTagModal() {
            hideModal('batchTagModal');
        }

        // 加载标签到下拉框
        async function loadTagsForSelect() {
            const select = document.getElementById('batchTagSelect');
            select.innerHTML = '<option value="">加载中...</option>';

            try {
                const response = await fetch('/api/tags');
                const data = await response.json();
                if (data.success) {
                    let html = '<option value="">请选择标签...</option>';
                    data.tags.forEach(tag => {
                        html += `<option value="${tag.id}">${escapeHtml(tag.name)}</option>`;
                    });
                    select.innerHTML = html;
                }
            } catch (error) {
                select.innerHTML = '<option value="">加载失败</option>';
            }
        }

        // 确认批量打标
        async function confirmBatchTag() {
            const tagId = document.getElementById('batchTagSelect').value;
            if (!tagId) {
                showToast('请选择标签', 'error');
                return;
            }

            const checked = document.querySelectorAll('.account-select-checkbox:checked');
            const accountIds = Array.from(checked).map(cb => parseInt(cb.value));

            if (accountIds.length === 0) return;

            try {
                const response = await fetch('/api/accounts/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        tag_id: parseInt(tagId),
                        action: batchActionType
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchTagModal();
                    await refreshVisibleAccountList(true);
                    // 隐藏操作栏
                    document.querySelectorAll('.account-select-checkbox').forEach(cb => cb.checked = false);
                    updateBatchActionBar();
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            }
        }

        // ==================== 批量移动分组 ====================

        // 显示批量移动分组模态框
        async function showBatchMoveGroupModal() {
            showModal('batchMoveGroupModal');
            await loadGroupsForBatchMove();
        }

        function hideBatchMoveGroupModal() {
            hideModal('batchMoveGroupModal');
        }

        // 加载分组到下拉框
        async function loadGroupsForBatchMove() {
            const select = document.getElementById('batchMoveGroupSelect');
            select.innerHTML = '<option value="">加载中...</option>';

            try {
                const response = await fetch('/api/groups');
                const data = await response.json();
                if (data.success) {
                    let html = '<option value="">请选择分组...</option>';
                    data.groups.filter(g => !g.is_system).forEach(group => {
                        html += `<option value="${group.id}">${escapeHtml(group.name)}</option>`;
                    });
                    select.innerHTML = html;
                }
            } catch (error) {
                select.innerHTML = '<option value="">加载失败</option>';
            }
        }

        // 确认批量移动分组
        async function confirmBatchMoveGroup() {
            const groupId = document.getElementById('batchMoveGroupSelect').value;
            if (!groupId) {
                showToast('请选择目标分组', 'error');
                return;
            }

            const checked = document.querySelectorAll('.account-select-checkbox:checked');
            const accountIds = Array.from(checked).map(cb => parseInt(cb.value));

            if (accountIds.length === 0) return;

            try {
                const response = await fetch('/api/accounts/batch-update-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        group_id: parseInt(groupId)
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchMoveGroupModal();
                    // 刷新分组列表
                    loadGroups();
                    if (currentGroupId) {
                        delete accountsCache[currentGroupId];
                    }
                    await refreshVisibleAccountList(true);
                    // 清除选择
                    document.querySelectorAll('.account-select-checkbox').forEach(cb => cb.checked = false);
                    updateBatchActionBar();
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            }
        }
