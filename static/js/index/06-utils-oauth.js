        /* global accountsCache, currentGroupId, escapeHtml, groups, handleApiError, hideModal, invalidateAccountCaches, invalidateRefreshTokenPreview, isTempEmailGroup, loadAccountsByGroup, loadGroups, loadRefreshStatusList, oauthPreviewAccount, refreshVisibleAccountList, renderRefreshTokenPreview, setModalVisible, showModal, showToast, updateGroupSelects */

        // ==================== 工具函数 ====================

        // 格式化日期
        function formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                let normalizedDate = dateStr;
                if (typeof dateStr === 'number' || /^\d+$/.test(String(dateStr))) {
                    const timestamp = Number(dateStr);
                    normalizedDate = timestamp < 1000000000000 ? timestamp * 1000 : timestamp;
                }

                const date = new Date(normalizedDate);
                if (isNaN(date.getTime())) return dateStr;

                const now = new Date();
                const timeZone = getAppTimeZone();
                const dateKeyFormatter = new Intl.DateTimeFormat('en-CA', {
                    timeZone,
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit'
                });
                const isToday = dateKeyFormatter.format(date) === dateKeyFormatter.format(now);

                if (isToday) {
                    return '今天 ' + date.toLocaleTimeString('zh-CN', {
                        timeZone,
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                } else {
                    return date.toLocaleDateString('zh-CN', {
                        timeZone,
                        year: 'numeric',
                        month: 'long',
                        day: 'numeric'
                    }) + ' ' + date.toLocaleTimeString('zh-CN', {
                        timeZone,
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                }
            } catch (e) {
                return dateStr;
            }
        }

        // ==================== OAuth Refresh Token 相关 ====================

        let oauthReauthorizeAccount = null;

        function isOAuthReauthorizeMode() {
            return !!(oauthReauthorizeAccount && oauthReauthorizeAccount.id);
        }

        function setOAuthElementDisplay(id, visible, displayValue = '') {
            const el = document.getElementById(id);
            if (el) {
                el.style.display = visible ? displayValue : 'none';
            }
        }

        function applyOAuthModalModeUI() {
            const reauthMode = isOAuthReauthorizeMode();
            const titleEl = document.getElementById('oauthModalTitle');
            const sectionTitleEl = document.getElementById('oauthAccountSectionTitle');
            const sectionHintEl = document.getElementById('oauthAccountSectionHint');
            const emailLabelEl = document.getElementById('oauthEmailLabel');
            const emailInput = document.getElementById('oauthEmailInput');
            const passwordLabelEl = document.getElementById('oauthPasswordLabel');
            const passwordInput = document.getElementById('oauthPasswordInput');
            const exchangeBtn = document.getElementById('exchangeTokenBtn');
            const saveBtn = document.getElementById('saveTokenAccountBtn');

            if (titleEl) titleEl.textContent = reauthMode ? '🔑 重新授权 Outlook 账号' : '🔑 授权并保存 Outlook 账号';
            if (sectionTitleEl) sectionTitleEl.textContent = reauthMode ? '当前账号' : '待入库账号';
            if (sectionHintEl) {
                sectionHintEl.textContent = reauthMode
                    ? '请确认当前账号邮箱，并粘贴授权后的回调 URL。系统会保存新授权并自动执行一次 Token 刷新验证。'
                    : '换取并预览只需要粘贴授权后的回调 URL。邮箱、密码和目标分组仅在保存账号时使用，可稍后补充。';
            }
            if (emailLabelEl) emailLabelEl.textContent = reauthMode ? '当前邮箱账号' : '邮箱账号（保存时可选）';
            if (emailInput) {
                emailInput.readOnly = reauthMode;
                emailInput.value = reauthMode ? (oauthReauthorizeAccount.email || '') : '';
                if (reauthMode) {
                    emailInput.style.cursor = 'pointer';
                    emailInput.title = '点击复制';
                    emailInput.onclick = function () { copyOauthField('oauthEmailInput', '邮箱已复制'); };
                } else {
                    emailInput.style.cursor = '';
                    emailInput.title = '';
                    emailInput.onclick = null;
                }
            }

            // 密码字段：重新授权模式下用掩码+小眼睛控制，支持点击复制
            if (passwordLabelEl) passwordLabelEl.textContent = reauthMode ? '密码' : '密码（保存时可选）';
            const revealOauthPasswordBtn = document.getElementById('revealOauthPasswordBtn');
            if (passwordInput) {
                passwordInput.type = 'text';
                passwordInput.readOnly = reauthMode;
                passwordInput.placeholder = reauthMode ? '' : '输入邮箱密码';
                if (reauthMode) {
                    const pw = oauthReauthorizeAccount.password || '';
                    const mask = '*'.repeat(Math.max(6, pw.length));
                    passwordInput.value = mask;
                    passwordInput.dataset.secretValue = pw;
                    passwordInput.dataset.secretRevealed = 'false';
                    passwordInput.style.cursor = 'pointer';
                    passwordInput.title = '点击复制';
                    passwordInput.onclick = function () { copyOauthField('oauthPasswordInput', '密码已复制'); };
                } else {
                    passwordInput.value = '';
                    passwordInput.type = 'password';
                    delete passwordInput.dataset.secretValue;
                    delete passwordInput.dataset.secretRevealed;
                    passwordInput.style.cursor = '';
                    passwordInput.title = '';
                    passwordInput.onclick = null;
                }
            }
            if (revealOauthPasswordBtn) {
                revealOauthPasswordBtn.style.display = reauthMode ? '' : 'none';
                revealOauthPasswordBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
                revealOauthPasswordBtn.title = '显示密码';
                revealOauthPasswordBtn.setAttribute('aria-label', '显示密码');
            }
            setOAuthElementDisplay('copyOauthEmailBtn', reauthMode);

            setOAuthElementDisplay('oauthTargetGroup', !reauthMode);
            setOAuthElementDisplay('oauthForwardGroup', !reauthMode, 'flex');
            setOAuthElementDisplay('oauthPreviewPasswordGroup', !reauthMode);
            setOAuthElementDisplay('oauthPreviewGroupGroup', !reauthMode);

            if (exchangeBtn) {
                exchangeBtn.disabled = false;
                exchangeBtn.textContent = '换取并预览';
                exchangeBtn.style.display = reauthMode ? 'none' : '';
            }
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = reauthMode ? '更新授权并刷新' : '直接保存（自动换取）';
            }
        }

        function copyOauthField(inputId, successMessage) {
            const input = document.getElementById(inputId);
            if (!input) return;
            const text = input.dataset.secretValue || input.value || '';
            if (!text) {
                showToast('内容为空，无法复制', 'error');
                return;
            }
            if (typeof copyTextToClipboard === 'function') {
                copyTextToClipboard(text, successMessage);
            } else {
                input.select();
                document.execCommand('copy');
                showToast(successMessage, 'success');
            }
        }

        function toggleOauthPasswordVisibility() {
            const input = document.getElementById('oauthPasswordInput');
            const button = document.getElementById('revealOauthPasswordBtn');
            if (!input || !button) return;

            const isRevealed = input.dataset.secretRevealed === 'true';
            const secretValue = input.dataset.secretValue || '';
            const mask = '*'.repeat(Math.max(6, secretValue.length));

            if (isRevealed) {
                input.value = mask;
                input.dataset.secretRevealed = 'false';
                button.title = '显示密码';
                button.setAttribute('aria-label', '显示密码');
                button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
            } else {
                input.value = secretValue;
                input.dataset.secretRevealed = 'true';
                button.title = '隐藏密码';
                button.setAttribute('aria-label', '隐藏密码');
                button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"></path><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"></path><path d="M9.5 5.5A10.5 10.5 0 0 1 12 5c6 0 9.5 7 9.5 7a17.6 17.6 0 0 1-2.1 3"></path><path d="M6.5 6.5C3.8 8.3 2.5 12 2.5 12s3.5 7 9.5 7a10 10 0 0 0 4.5-1.1"></path></svg>';
            }
        }

        function invalidateRefreshTokenPreview() {
            oauthPreviewAccount = null;
            const resultEl = document.getElementById('refreshTokenResult');
            if (resultEl) {
                resultEl.style.display = 'none';
            }
        }

        function renderRefreshTokenPreview() {
            if (!oauthPreviewAccount) {
                invalidateRefreshTokenPreview();
                return;
            }
            const resultEl = document.getElementById('refreshTokenResult');
            const saveBtn = document.getElementById('saveTokenAccountBtn');
            if (isOAuthReauthorizeMode()) {
                if (resultEl) {
                    resultEl.style.display = 'none';
                }
                if (saveBtn) {
                    saveBtn.disabled = false;
                }
                return;
            }
            const group = groups.find(item => item.id === oauthPreviewAccount.group_id);
            const fallbackGroupId = Number.parseInt(String(oauthPreviewAccount.group_id ?? ''), 10);
            document.getElementById('oauthPreviewEmail').value = oauthPreviewAccount.email || '';
            document.getElementById('oauthPreviewPassword').value = oauthPreviewAccount.password || '';
            document.getElementById('oauthPreviewClientId').value = oauthPreviewAccount.client_id || '';
            document.getElementById('oauthPreviewGroup').value = group?.name || (Number.isFinite(fallbackGroupId) ? String(fallbackGroupId) : '');
            document.getElementById('oauthPreviewRefreshToken').value = oauthPreviewAccount.refresh_token || '';
            if (resultEl) {
                resultEl.style.display = 'block';
            }
        }

        // 显示获取 Refresh Token 模态框
        async function showGetRefreshTokenModal(options = {}) {
            const reauthorizeAccount = options.reauthorizeAccount || null;
            oauthReauthorizeAccount = reauthorizeAccount && reauthorizeAccount.id
                ? {
                    id: Number(reauthorizeAccount.id),
                    email: String(reauthorizeAccount.email || ''),
                    password: String(reauthorizeAccount.password || '')
                }
                : null;

            showModal('getRefreshTokenModal');

            // 重置表单
            document.getElementById('oauthEmailInput').value = oauthReauthorizeAccount?.email || '';
            document.getElementById('oauthPasswordInput').value = '';
            document.getElementById('redirectUrlInput').value = '';
            document.getElementById('oauthForwardEnabled').checked = false;
            invalidateRefreshTokenPreview();
            applyOAuthModalModeUI();

            // 重置按钮状态
            const btn = document.getElementById('exchangeTokenBtn');
            btn.disabled = false;
            const saveBtn = document.getElementById('saveTokenAccountBtn');

            const groupSelect = document.getElementById('tokenSaveGroupSelect');
            if (groupSelect && !isOAuthReauthorizeMode()) {
                const nonTempGroups = groups.filter(group => group.name !== '临时邮箱');
                const fallbackGroupId = (!isTempEmailGroup && currentGroupId && nonTempGroups.find(group => group.id === currentGroupId))
                    ? currentGroupId
                    : (nonTempGroups[0]?.id || '');
                if (fallbackGroupId) {
                    groupSelect.value = fallbackGroupId;
                }
            }

            // 获取授权 URL
            try {
                const response = await fetch('/api/oauth/auth-url');
                const data = await response.json();

                if (data.success) {
                    document.getElementById('authUrlInput').value = data.auth_url;
                } else {
                    showToast('获取授权链接失败', 'error');
                }
            } catch (error) {
                showToast('获取授权链接失败', 'error');
            }
        }

        // 隐藏获取 Refresh Token 模态框
        function hideGetRefreshTokenModal() {
            oauthReauthorizeAccount = null;
            hideModal('getRefreshTokenModal');
            applyOAuthModalModeUI();
        }

        async function showReauthorizeAccountModal(account) {
            const normalizedAccount = typeof account === 'object'
                ? account
                : { id: account, email: arguments.length > 1 ? arguments[1] : '' };
            const accountId = Number(normalizedAccount.id || 0);
            if (!Number.isFinite(accountId) || accountId <= 0) {
                showToast('账号信息无效，无法重新授权', 'error');
                return;
            }

            let accountPassword = normalizedAccount.password || '';
            if (!accountPassword) {
                try {
                    const response = await fetch(`/api/accounts/${accountId}`);
                    const data = await response.json();
                    if (data.success && data.account) {
                        accountPassword = data.account.password || '';
                        if (!normalizedAccount.email) {
                            normalizedAccount.email = data.account.email || '';
                        }
                    }
                } catch (e) {
                    // 获取密码失败时继续，密码字段将为空
                }
            }

            await showGetRefreshTokenModal({
                reauthorizeAccount: {
                    id: accountId,
                    email: normalizedAccount.email || '',
                    password: accountPassword
                }
            });
        }

        function showReauthorizeAccountModalFromEdit() {
            const accountId = document.getElementById('editAccountId')?.value || '';
            const accountEmail = document.getElementById('editEmail')?.value || '';
            const passwordInput = document.getElementById('editPassword');
            const accountPassword = passwordInput?.dataset.secretValue || '';
            showReauthorizeAccountModal({ id: accountId, email: accountEmail, password: accountPassword });
        }

        // 复制授权 URL
        function copyAuthUrl() {
            const input = document.getElementById('authUrlInput');
            input.select();
            document.execCommand('copy');
            showToast('授权链接已复制到剪贴板', 'success');
        }

        // 打开授权 URL
        function openAuthUrl() {
            const url = document.getElementById('authUrlInput').value;
            if (url) {
                window.open(url, '_blank');
                showToast('已在新窗口打开授权页面', 'info');
            }
        }

        // 换取 Token
        async function exchangeToken(options = {}) {
            if (isOAuthReauthorizeMode()) {
                return reauthorizeExistingAccount();
            }

            const { silentSuccess = false, keepSavingState = false } = options;
            const email = document.getElementById('oauthEmailInput').value.trim();
            const password = document.getElementById('oauthPasswordInput').value;
            const redirectUrl = document.getElementById('redirectUrlInput').value.trim();
            const groupId = parseInt(document.getElementById('tokenSaveGroupSelect')?.value || '0', 10);
            const forwardEnabled = !!document.getElementById('oauthForwardEnabled')?.checked;

            if (!redirectUrl) {
                showToast('请先粘贴授权后的完整 URL', 'error');
                return;
            }

            const btn = document.getElementById('exchangeTokenBtn');
            const saveBtn = document.getElementById('saveTokenAccountBtn');
            btn.disabled = true;
            if (!keepSavingState && saveBtn) {
                saveBtn.disabled = true;
            }
            btn.textContent = '⏳ 预览中...';

            try {
                const response = await fetch('/api/oauth/exchange-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        redirected_url: redirectUrl
                    })
                });

                const data = await response.json();

                if (data.success) {
                    oauthPreviewAccount = {
                        email,
                        password,
                        client_id: data.client_id,
                        refresh_token: data.refresh_token,
                        group_id: groupId,
                        forward_enabled: forwardEnabled
                    };
                    renderRefreshTokenPreview();

                    if (!silentSuccess) {
                        showToast('✅ Refresh Token 获取成功！', 'success');
                    }

                    // 重置按钮状态（不隐藏，允许重复使用）
                    btn.disabled = false;
                    if (!keepSavingState && saveBtn) {
                        saveBtn.disabled = false;
                    }
                    btn.textContent = '换取并预览';
                    return true;
                } else {
                    handleApiError(data, '换取 Token 失败');
                    btn.disabled = false;
                    if (!keepSavingState && saveBtn) {
                        saveBtn.disabled = false;
                    }
                    btn.textContent = '换取并预览';
                    return false;
                }
            } catch (error) {
                showToast('换取 Token 失败: ' + error.message, 'error');
                btn.disabled = false;
                if (!keepSavingState && saveBtn) {
                    saveBtn.disabled = false;
                }
                btn.textContent = '换取并预览';
                return false;
            }
        }

        async function reloadAuthorizationAffectedViews() {
            if (typeof invalidateAccountCaches === 'function') {
                invalidateAccountCaches();
            } else if (currentGroupId) {
                delete accountsCache[currentGroupId];
            }
            if (typeof loadGroups === 'function') {
                await loadGroups();
            }
            if (typeof refreshVisibleAccountList === 'function') {
                await refreshVisibleAccountList(true);
            } else if (currentGroupId && typeof loadAccountsByGroup === 'function') {
                await loadAccountsByGroup(currentGroupId, true);
            }
            if (typeof loadRefreshStatusList === 'function') {
                await loadRefreshStatusList();
            }
        }

        async function reauthorizeExistingAccount() {
            const accountId = Number(oauthReauthorizeAccount?.id || 0);
            const redirectUrl = document.getElementById('redirectUrlInput').value.trim();
            if (!Number.isFinite(accountId) || accountId <= 0) {
                showToast('账号信息无效，无法重新授权', 'error');
                return false;
            }
            if (!redirectUrl) {
                showToast('请先粘贴授权后的完整 URL', 'error');
                return false;
            }

            const saveBtn = document.getElementById('saveTokenAccountBtn');
            const exchangeBtn = document.getElementById('exchangeTokenBtn');
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.textContent = '更新并刷新中...';
            }
            if (exchangeBtn) {
                exchangeBtn.disabled = true;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}/reauthorize`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ redirected_url: redirectUrl })
                });
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '重新授权失败');
                    return false;
                }

                await reloadAuthorizationAffectedViews();
                hideGetRefreshTokenModal();

                const validation = data.validation || {};
                if (validation.success) {
                    showToast(data.message || '重新授权成功，Token 刷新验证通过', 'success');
                } else {
                    showToast(data.message || '重新授权已保存，但自动刷新验证失败', 'error', validation.error);
                }
                return true;
            } catch (error) {
                showToast('重新授权失败: ' + error.message, 'error');
                return false;
            } finally {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = isOAuthReauthorizeMode() ? '更新授权并刷新' : '直接保存（自动换取）';
                }
                if (exchangeBtn) {
                    exchangeBtn.disabled = false;
                }
            }
        }

        async function saveTokenAccount() {
            if (isOAuthReauthorizeMode()) {
                return reauthorizeExistingAccount();
            }

            if (!oauthPreviewAccount) {
                const exchanged = await exchangeToken({ silentSuccess: true, keepSavingState: true });
                if (!exchanged || !oauthPreviewAccount) {
                    return;
                }
            }

            if (!oauthPreviewAccount.email || !oauthPreviewAccount.password) {
                showToast('保存账号前请先填写邮箱账号和密码', 'error');
                return;
            }

            if (!oauthPreviewAccount.group_id) {
                showToast('保存账号前请选择目标分组', 'error');
                return;
            }

            const saveBtn = document.getElementById('saveTokenAccountBtn');
            const exchangeBtn = document.getElementById('exchangeTokenBtn');
            saveBtn.disabled = true;
            exchangeBtn.disabled = true;
            saveBtn.textContent = '保存中...';

            try {
                const accountString = [
                    oauthPreviewAccount.email,
                    oauthPreviewAccount.password,
                    oauthPreviewAccount.client_id,
                    oauthPreviewAccount.refresh_token
                ].join('----');

                const response = await fetch('/api/accounts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_string: accountString,
                        group_id: oauthPreviewAccount.group_id,
                        provider: 'outlook',
                        forward_enabled: !!oauthPreviewAccount.forward_enabled
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message || '账号已保存', 'success');
                    currentGroupId = oauthPreviewAccount.group_id;
                    await reloadAuthorizationAffectedViews();
                    hideGetRefreshTokenModal();
                } else {
                    handleApiError(data, '保存账号失败');
                }
            } catch (error) {
                showToast('保存账号失败', 'error');
            } finally {
                exchangeBtn.disabled = false;
                saveBtn.disabled = false;
                saveBtn.textContent = '直接保存（自动换取）';
            }
        }
