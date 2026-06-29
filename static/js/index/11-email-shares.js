        /* global copyTextToClipboard, escapeHtml, handleApiError, hideModal, showConfirmModal, showModal, showToast */

        // ==================== 邮箱分享 ====================

        function formatEmailShareStatus(status) {
            if (status === 'active') return '有效';
            if (status === 'expired') return '已过期';
            if (status === 'revoked') return '已取消';
            return '无效';
        }

        function formatEmailShareExpiry(share) {
            if (share.never_expires) {
                return '永不过期';
            }
            return share.expires_at || '未设置';
        }

        function hideCreateEmailShareModal() {
            hideModal('createEmailShareModal');
        }

        function hideEmailShareManagementModal() {
            hideModal('emailShareManagementModal');
        }

        function resetEmailShareCreateForm() {
            const result = document.getElementById('emailShareCreateResult');
            if (result) {
                result.hidden = true;
                result.replaceChildren();
            }
            const preset = document.getElementById('emailShareDurationPreset');
            if (preset) preset.value = '1440';
            const custom = document.getElementById('emailShareCustomDuration');
            if (custom) custom.value = '1440';
            const never = document.getElementById('emailShareNeverExpires');
            if (never) never.checked = false;
            syncEmailShareDurationPreset();
            toggleEmailShareNeverExpires();
        }

        function showCreateEmailShareModal(accountId, email) {
            resetEmailShareCreateForm();
            document.getElementById('emailShareAccountId').value = String(accountId || '');
            document.getElementById('emailShareAccountEmail').value = email || '';
            showModal('createEmailShareModal');
        }

        function syncEmailShareDurationPreset() {
            const preset = document.getElementById('emailShareDurationPreset');
            const customGroup = document.getElementById('emailShareCustomDurationGroup');
            if (!preset || !customGroup) return;
            customGroup.style.display = preset.value === 'custom' ? 'block' : 'none';
        }

        function toggleEmailShareNeverExpires() {
            const never = document.getElementById('emailShareNeverExpires')?.checked;
            const preset = document.getElementById('emailShareDurationPreset');
            const custom = document.getElementById('emailShareCustomDuration');
            if (preset) preset.disabled = !!never;
            if (custom) custom.disabled = !!never;
            syncEmailShareDurationPreset();
        }

        function getEmailShareDurationMinutes() {
            const preset = document.getElementById('emailShareDurationPreset')?.value || '1440';
            const rawValue = preset === 'custom'
                ? document.getElementById('emailShareCustomDuration')?.value
                : preset;
            const value = parseInt(rawValue || '0', 10);
            return Number.isFinite(value) ? value : 0;
        }

        function renderEmailShareCreateResult(share) {
            const result = document.getElementById('emailShareCreateResult');
            if (!result) return;
            result.hidden = false;
            result.innerHTML = `
                <div class="share-result__label">分享链接</div>
                <div class="share-result__row">
                    <input type="text" class="form-input" readonly value="${escapeHtml(share.share_url || '')}">
                    <button class="btn btn-secondary" type="button" onclick="copyEmailShareUrl('${escapeHtml(share.share_url || '')}')">复制</button>
                </div>
                <div class="form-hint">有效期：${escapeHtml(formatEmailShareExpiry(share))}</div>
            `;
        }

        async function createEmailShare() {
            const accountId = parseInt(document.getElementById('emailShareAccountId')?.value || '0', 10);
            const neverExpires = !!document.getElementById('emailShareNeverExpires')?.checked;
            const durationMinutes = getEmailShareDurationMinutes();
            if (!accountId) {
                showToast('缺少邮箱账号', 'error');
                return;
            }
            if (!neverExpires && durationMinutes <= 0) {
                showToast('分享时长无效', 'error');
                return;
            }

            const button = document.getElementById('createEmailShareBtn');
            if (button) button.disabled = true;
            try {
                const response = await fetch('/api/email-shares', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: accountId,
                        duration_minutes: durationMinutes,
                        never_expires: neverExpires
                    })
                });
                const data = await response.json();
                if (data.success) {
                    renderEmailShareCreateResult(data.share);
                    showToast('分享链接已创建', 'success');
                    loadEmailShares();
                } else {
                    handleApiError(data, '创建分享失败');
                }
            } catch (error) {
                showToast('创建分享失败: ' + error.message, 'error');
            } finally {
                if (button) button.disabled = false;
            }
        }
        function copyEmailShareUrl(url) {
            if (!url) {
                showToast('分享链接不可用', 'error');
                return;
            }
            copyTextToClipboard(url, '分享链接已复制');
        }

        let allEmailShares = [];

        function renderEmailShareTable(shares) {
            const tbody = document.getElementById('emailShareTableBody');
            if (!tbody) return;

            // Reset Select All checkbox
            const allCheckbox = document.getElementById('shareSelectAllCheckbox');
            if (allCheckbox) {
                allCheckbox.checked = false;
            }

            if (!Array.isArray(shares) || shares.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" class="share-empty">暂无分享记录</td>
                    </tr>
                `;
                updateBatchActionButtons();
                return;
            }

            tbody.innerHTML = shares.map(share => {
                const statusStr = formatEmailShareStatus(share.status);
                let badgeClass = 'share-badge--invalid';
                if (share.status === 'active') badgeClass = 'share-badge--active';
                else if (share.status === 'expired') badgeClass = 'share-badge--expired';
                else if (share.status === 'revoked') badgeClass = 'share-badge--revoked';

                const expiryStr = formatEmailShareExpiry(share);

                return `
                    <tr data-share-id="${share.id}">
                        <td>
                            <div class="share-select-all">
                                <input type="checkbox" class="share-checkbox share-item-checkbox" data-share-id="${share.id}" onchange="updateBatchActionButtons()">
                            </div>
                        </td>
                        <td style="font-weight: 500; color: var(--text-primary, #111827);">${escapeHtml(share.email || '')}</td>
                        <td>
                            <span class="share-badge ${badgeClass}">${escapeHtml(statusStr)}</span>
                        </td>
                        <td class="share-cell-mono">${escapeHtml(expiryStr)}</td>
                        <td class="share-cell-mono">${escapeHtml(share.created_at || '')}</td>
                        <td>
                            <div class="share-url-container">
                                <input type="text" class="form-input share-url-input" readonly value="${escapeHtml(share.share_url || '')}">
                                <button class="btn btn-secondary btn-sm-action" type="button" onclick="copyEmailShareUrl('${escapeHtml(share.share_url || '')}')">复制</button>
                            </div>
                        </td>
                        <td style="text-align: right;">
                            <div style="display: flex; gap: 6px; justify-content: flex-end;">
                                <button class="btn btn-secondary btn-sm-action" type="button" onclick="cancelEmailShare(${Number(share.id)})" ${share.status === 'revoked' ? 'disabled' : ''}>取消</button>
                                <button class="btn btn-danger btn-sm-action" type="button" onclick="deleteEmailShare(${Number(share.id)})">删除</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            updateBatchActionButtons();
        }

        async function loadEmailShares() {
            const tbody = document.getElementById('emailShareTableBody');
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" class="share-empty">正在加载分享记录...</td>
                    </tr>
                `;
            }

            // Disable batch buttons and uncheck Select All during load
            const allCheckbox = document.getElementById('shareSelectAllCheckbox');
            if (allCheckbox) allCheckbox.checked = false;
            updateBatchActionButtons();

            try {
                const response = await fetch('/api/email-shares');
                const data = await response.json();
                if (data.success) {
                    allEmailShares = data.shares || [];
                    applyShareFilters();
                } else {
                    handleApiError(data, '加载分享记录失败');
                }
            } catch (error) {
                showToast('加载分享记录失败: ' + error.message, 'error');
            }
        }

        let currentSortCol = 'created_at';
        let currentSortDir = 'desc';

        function handleHeaderSort(colName) {
            if (currentSortCol === colName) {
                currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                currentSortCol = colName;
                if (colName === 'email') {
                    currentSortDir = 'asc';
                } else {
                    currentSortDir = 'desc';
                }
            }
            applyShareFilters();
        }

        function updateSortHeadersUI() {
            const headers = document.querySelectorAll('.sortable-header');
            headers.forEach(th => {
                const col = th.getAttribute('data-sort-col');
                const indicator = th.querySelector('.sort-indicator');
                if (!indicator) return;

                if (col === currentSortCol) {
                    indicator.textContent = currentSortDir === 'asc' ? ' ▲' : ' ▼';
                    indicator.style.color = 'var(--text-primary, #111827)';
                } else {
                    indicator.textContent = ' ↕';
                    indicator.style.color = 'var(--text-muted, #9ca3af)';
                }
            });
        }

        function applyShareFilters() {
            const searchEmail = document.getElementById('shareFilterEmail')?.value.toLowerCase().trim() || '';
            const filterStatus = document.getElementById('shareFilterStatus')?.value || 'all';

            let filtered = [...allEmailShares];

            // 筛选邮箱
            if (searchEmail) {
                filtered = filtered.filter(share => (share.email || '').toLowerCase().includes(searchEmail));
            }

            // 筛选状态
            if (filterStatus !== 'all') {
                filtered = filtered.filter(share => share.status === filterStatus);
            }

            // 排序
            filtered.sort((a, b) => {
                let valA, valB;

                if (currentSortCol === 'email') {
                    valA = (a.email || '').toLowerCase();
                    valB = (b.email || '').toLowerCase();
                } else if (currentSortCol === 'status') {
                    valA = (a.status || '');
                    valB = (b.status || '');
                } else if (currentSortCol === 'expires_at') {
                    const getExpiryTime = (s) => {
                        if (s.never_expires) {
                            return currentSortDir === 'asc' ? Infinity : -Infinity;
                        }
                        return s.expires_at ? new Date(s.expires_at).getTime() : 0;
                    };
                    valA = getExpiryTime(a);
                    valB = getExpiryTime(b);

                    if (valA === valB) return 0;
                    if (valA === Infinity || valB === -Infinity) return currentSortDir === 'asc' ? 1 : -1;
                    if (valB === Infinity || valA === -Infinity) return currentSortDir === 'asc' ? -1 : 1;
                    return currentSortDir === 'asc' ? valA - valB : valB - valA;
                } else if (currentSortCol === 'created_at') {
                    valA = new Date(a.created_at || 0).getTime();
                    valB = new Date(b.created_at || 0).getTime();
                } else {
                    return 0;
                }

                if (currentSortCol !== 'expires_at') {
                    if (valA < valB) return currentSortDir === 'asc' ? -1 : 1;
                    if (valA > valB) return currentSortDir === 'asc' ? 1 : -1;
                    return 0;
                }
            });

            updateSortHeadersUI();
            renderEmailShareTable(filtered);
        }

        function toggleSelectAllShares(allCheckbox) {
            const checkboxes = document.querySelectorAll('.share-item-checkbox');
            checkboxes.forEach(cb => {
                cb.checked = allCheckbox.checked;
            });
            updateBatchActionButtons();
        }

        function updateBatchActionButtons() {
            const checkboxes = document.querySelectorAll('.share-item-checkbox');
            const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;

            const cancelBtn = document.getElementById('batchCancelShareBtn');
            const deleteBtn = document.getElementById('batchDeleteShareBtn');
            const allCheckbox = document.getElementById('shareSelectAllCheckbox');

            if (cancelBtn) cancelBtn.disabled = checkedCount === 0;
            if (deleteBtn) deleteBtn.disabled = checkedCount === 0;

            if (allCheckbox) {
                allCheckbox.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
            }
        }

        function showEmailShareManagementModal() {
            // Reset filter controls
            const filterEmail = document.getElementById('shareFilterEmail');
            if (filterEmail) filterEmail.value = '';
            const filterStatus = document.getElementById('shareFilterStatus');
            if (filterStatus) filterStatus.value = 'all';

            // Reset sorting parameters
            currentSortCol = 'created_at';
            currentSortDir = 'desc';

            showModal('emailShareManagementModal');
            loadEmailShares();
        }

        async function cancelEmailShare(shareId) {
            if (!(await showConfirmModal('确定要取消这个分享链接吗？', { title: '取消分享', confirmText: '确认取消' }))) {
                return;
            }
            try {
                const response = await fetch(`/api/email-shares/${encodeURIComponent(shareId)}/cancel`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (data.success) {
                    showToast('分享已取消', 'success');
                    loadEmailShares();
                } else {
                    handleApiError(data, '取消分享失败');
                }
            } catch (error) {
                showToast('取消分享失败: ' + error.message, 'error');
            }
        }

        async function deleteEmailShare(shareId) {
            if (!(await showConfirmModal('确定要删除这个分享链接吗？删除后链接将永久失效且不可恢复。', { title: '删除分享', confirmText: '确认删除', danger: true }))) {
                return;
            }
            try {
                const response = await fetch(`/api/email-shares/${encodeURIComponent(shareId)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (data.success) {
                    showToast('分享已删除', 'success');
                    loadEmailShares();
                } else {
                    handleApiError(data, '删除分享失败');
                }
            } catch (error) {
                showToast('删除分享失败: ' + error.message, 'error');
            }
        }

        async function batchCancelShares() {
            const checkboxes = document.querySelectorAll('.share-item-checkbox:checked');
            const ids = Array.from(checkboxes).map(cb => parseInt(cb.getAttribute('data-share-id'), 10));
            if (ids.length === 0) return;

            if (!(await showConfirmModal(`确定要取消选中的 ${ids.length} 个分享链接吗？`, { title: '批量取消分享', confirmText: '确认取消' }))) {
                return;
            }

            try {
                const response = await fetch('/api/email-shares/batch-cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ share_ids: ids })
                });
                const data = await response.json();
                if (data.success) {
                    showToast('所选分享已取消', 'success');
                    loadEmailShares();
                } else {
                    handleApiError(data, '批量取消失败');
                }
            } catch (error) {
                showToast('批量取消失败: ' + error.message, 'error');
            }
        }

        async function batchDeleteShares() {
            const checkboxes = document.querySelectorAll('.share-item-checkbox:checked');
            const ids = Array.from(checkboxes).map(cb => parseInt(cb.getAttribute('data-share-id'), 10));
            if (ids.length === 0) return;

            if (!(await showConfirmModal(`确定要删除选中的 ${ids.length} 个分享链接吗？删除后链接将永久失效且不可恢复。`, { title: '批量删除分享', confirmText: '确认删除', danger: true }))) {
                return;
            }

            try {
                const response = await fetch('/api/email-shares/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ share_ids: ids })
                });
                const data = await response.json();
                if (data.success) {
                    showToast('所选分享已删除', 'success');
                    loadEmailShares();
                } else {
                    handleApiError(data, '批量删除失败');
                }
            } catch (error) {
                showToast('批量删除失败: ' + error.message, 'error');
            }
        }
