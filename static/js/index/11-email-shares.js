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

        function renderEmailShareList(shares) {
            const container = document.getElementById('emailShareList');
            if (!container) return;
            if (!Array.isArray(shares) || shares.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-text">暂无分享记录</div>
                    </div>
                `;
                return;
            }

            container.innerHTML = shares.map(share => `
                <div class="share-list-item" data-share-id="${share.id}">
                    <div class="share-list-item__main">
                        <div class="share-list-item__email">${escapeHtml(share.email || '')}</div>
                        <div class="share-list-item__meta">
                            <span>状态：${escapeHtml(formatEmailShareStatus(share.status))}</span>
                            <span>有效期：${escapeHtml(formatEmailShareExpiry(share))}</span>
                            <span>创建：${escapeHtml(share.created_at || '')}</span>
                        </div>
                        <input type="text" class="form-input share-list-item__url" readonly value="${escapeHtml(share.share_url || '')}">
                    </div>
                    <div class="share-list-item__actions">
                        <button class="btn btn-secondary" type="button" onclick="copyEmailShareUrl('${escapeHtml(share.share_url || '')}')">复制</button>
                        <button class="btn btn-danger" type="button" onclick="cancelEmailShare(${Number(share.id)})" ${share.status === 'revoked' ? 'disabled' : ''}>取消</button>
                    </div>
                </div>
            `).join('');
        }

        async function loadEmailShares() {
            const container = document.getElementById('emailShareList');
            if (container) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-text">正在加载分享记录...</div>
                    </div>
                `;
            }
            try {
                const response = await fetch('/api/email-shares');
                const data = await response.json();
                if (data.success) {
                    renderEmailShareList(data.shares);
                } else {
                    handleApiError(data, '加载分享记录失败');
                }
            } catch (error) {
                showToast('加载分享记录失败: ' + error.message, 'error');
            }
        }

        function showEmailShareManagementModal() {
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
