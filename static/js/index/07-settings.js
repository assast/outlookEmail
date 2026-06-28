        /* global accountsCache, allTags, closeAllModals, closeMobilePanels, closeNavbarActionsMenu, currentGroupId, currentGroupName, deleteCurrentAccount, ensureForwardingSettingsUI, escapeHtml, formatAbsoluteDateTime, getSelectedForwardChannels, groups, handleApiError, hideEditAccountModal, hideModal, hideSettingsModal, invalidateNormalMailRetentionCaches, isTempEmailGroup, isTempImportGroup, loadAccountsByGroup, loadCloudflareChannelsForTempEmails, loadGroups, loadTempEmails, normalizeSmtpForwardProvider, refreshVisibleAccountList, setAppTimeZone, setModalVisible, setSelectedForwardChannels, setShowAccountCreatedAt, setShowAccountSortOrder, setShowGroupId, setNormalMailLocalRetentionEnabled, showConfirmModal, showModal, showToast, syncSmtpProviderUI, toggleRefreshStrategy, updateEditAccountFields, updateImportHint */

        // ==================== 设置相关 ====================
        let settingsScrollSyncBound = false;
        let settingsScrollSyncFrame = 0;
        let lastLoadedWebdavBackupSettings = null;
        let cloudflareSettingsChannels = [];
        let lastNormalMailRetentionStatus = null;
        let lastLoadedSkinSettings = null;
        let normalMailRetentionStatusPollTimer = null;
        let normalMailRetentionStatusPollDelayMs = 0;
        const NORMAL_MAIL_RETENTION_STATUS_INITIAL_POLL_MS = 2000;
        const NORMAL_MAIL_RETENTION_STATUS_MAX_POLL_MS = 10000;
        const LOCKED_ACCOUNT_SECRET_PLACEHOLDER = '已保存，验证后显示';
        let editAccountSecretState = {
            accountId: '',
            pendingField: ''
        };

        function parseSettingsBoolean(value) {
            return String(value).toLowerCase() === 'true';
        }

        function syncForwardExecutionModeUI() {
            const modeEl = document.getElementById('forwardExecutionMode');
            const workersEl = document.getElementById('forwardParallelWorkers');
            const delayEl = document.getElementById('forwardAccountDelaySeconds');
            if (!modeEl || !workersEl) return;
            const isParallel = modeEl.value === 'parallel';
            workersEl.disabled = !isParallel;
            if (delayEl) {
                delayEl.disabled = isParallel;
                if (isParallel) {
                    delayEl.value = '0';
                }
            }
        }

        function formatStorageBytes(bytes) {
            const value = Number(bytes) || 0;
            if (value < 1024) return `${value} B`;
            if (value < 1024 * 1024) return `${(value / 1024).toFixed(1).replace(/\.0$/, '')} KB`;
            if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1).replace(/\.0$/, '')} MB`;
            return `${(value / 1024 / 1024 / 1024).toFixed(1).replace(/\.0$/, '')} GB`;
        }

        function resetEditSecretInput(inputId, buttonId, hasSavedValue, emptyPlaceholder = '') {
            const input = document.getElementById(inputId);
            const button = document.getElementById(buttonId);
            if (!input) return;

            input.value = '';
            input.placeholder = hasSavedValue ? LOCKED_ACCOUNT_SECRET_PLACEHOLDER : emptyPlaceholder;
            input.dataset.secretHasSaved = hasSavedValue ? 'true' : 'false';
            input.dataset.secretLoaded = hasSavedValue ? 'false' : 'true';
            if (button) {
                button.style.display = hasSavedValue ? '' : 'none';
            }
        }

        function setEditSecretInputValue(inputId, buttonId, value, emptyPlaceholder = '') {
            const input = document.getElementById(inputId);
            const button = document.getElementById(buttonId);
            if (!input) return;

            input.value = value || '';
            input.placeholder = emptyPlaceholder;
            input.dataset.secretHasSaved = input.value ? 'true' : 'false';
            input.dataset.secretLoaded = 'true';
            if (button) {
                button.style.display = 'none';
            }
        }

        function clearEditAccountSecrets() {
            resetEditSecretInput('editPassword', 'revealEditPasswordBtn', false, '可选');
            resetEditSecretInput('editImapPassword', 'revealEditImapPasswordBtn', false, '');
            const verifyInput = document.getElementById('accountSecretVerifyPassword');
            if (verifyInput) {
                verifyInput.value = '';
            }
            editAccountSecretState = {
                accountId: '',
                pendingField: ''
            };
        }

        function shouldSubmitSecretInput(input) {
            return !!input && (input.dataset.secretLoaded === 'true' || !!input.value);
        }

        function showAccountSecretVerifyModal(fieldName) {
            const accountId = document.getElementById('editAccountId')?.value || '';
            if (!accountId) {
                showToast('请先打开账号编辑窗口', 'error');
                return;
            }

            editAccountSecretState.accountId = accountId;
            editAccountSecretState.pendingField = fieldName || '';
            closeNavbarActionsMenu();
            closeMobilePanels();
            setModalVisible('accountSecretVerifyModal', true);

            const verifyInput = document.getElementById('accountSecretVerifyPassword');
            if (verifyInput) {
                verifyInput.value = '';
                verifyInput.focus();
            }
        }

        function hideAccountSecretVerifyModal() {
            hideModal('accountSecretVerifyModal');
            const verifyInput = document.getElementById('accountSecretVerifyPassword');
            if (verifyInput) {
                verifyInput.value = '';
            }
        }

        async function confirmAccountSecretVerify() {
            const accountId = editAccountSecretState.accountId || document.getElementById('editAccountId')?.value || '';
            const verifyInput = document.getElementById('accountSecretVerifyPassword');
            const password = verifyInput?.value || '';

            if (!accountId) {
                showToast('请先打开账号编辑窗口', 'error');
                return;
            }
            if (!password) {
                showToast('请输入登录密码', 'error');
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}/secrets`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        password,
                        field: editAccountSecretState.pendingField || ''
                    })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '验证失败');
                    return;
                }

                const secrets = data.secrets || {};
                if (Object.prototype.hasOwnProperty.call(secrets, 'password')) {
                    setEditSecretInputValue('editPassword', 'revealEditPasswordBtn', secrets.password || '', '可选');
                }
                if (Object.prototype.hasOwnProperty.call(secrets, 'imap_password')) {
                    setEditSecretInputValue('editImapPassword', 'revealEditImapPasswordBtn', secrets.imap_password || '', '');
                }
                hideAccountSecretVerifyModal();
                showToast('验证通过，已显示账号密码', 'success');
            } catch (error) {
                showToast('验证失败', 'error');
            }
        }

        function updateNormalMailRetentionStats(status = {}) {
            lastNormalMailRetentionStatus = status || {};
            const savedCount = Number(status.saved_message_count || 0);
            const cachedBodyCount = Number(status.cached_body_count || 0);
            const clearStatus = status.clear_status || {};

            const savedEl = document.getElementById('normalMailRetentionSavedCount');
            const cachedEl = document.getElementById('normalMailRetentionCachedBodyCount');
            const estimatedEl = document.getElementById('normalMailRetentionEstimatedBytes');
            const dbEl = document.getElementById('normalMailRetentionDbBytes');
            const clearEl = document.getElementById('normalMailRetentionClearStatus');
            const errorEl = document.getElementById('normalMailRetentionStatsError');

            if (savedEl) savedEl.textContent = String(savedCount);
            if (cachedEl) cachedEl.textContent = String(cachedBodyCount);
            if (estimatedEl) estimatedEl.textContent = formatStorageBytes(status.estimated_retained_bytes);
            if (dbEl) dbEl.textContent = formatStorageBytes(status.db_file_bytes);
            if (clearEl) clearEl.textContent = `清理状态：${clearStatus.message || clearStatus.state || '普通邮箱本地缓存清理空闲'}`;
            if (errorEl) {
                errorEl.style.display = 'none';
                errorEl.textContent = '';
            }

            if (clearStatus.state === 'running') {
                scheduleNormalMailRetentionStatusPoll();
            } else {
                stopNormalMailRetentionStatusPoll();
            }
        }

        function renderNormalMailRetentionStatusError(message) {
            const errorEl = document.getElementById('normalMailRetentionStatsError');
            if (!errorEl) return;
            errorEl.textContent = message || '加载普通邮箱本地保留统计失败';
            errorEl.style.display = 'block';
        }

        function stopNormalMailRetentionStatusPoll() {
            if (normalMailRetentionStatusPollTimer) {
                window.clearTimeout(normalMailRetentionStatusPollTimer);
                normalMailRetentionStatusPollTimer = null;
            }
            normalMailRetentionStatusPollDelayMs = 0;
        }

        function resetNormalMailRetentionStatusPollDelay() {
            normalMailRetentionStatusPollDelayMs = NORMAL_MAIL_RETENTION_STATUS_INITIAL_POLL_MS;
        }

        function nextNormalMailRetentionStatusPollDelay() {
            if (!normalMailRetentionStatusPollDelayMs) {
                resetNormalMailRetentionStatusPollDelay();
                return normalMailRetentionStatusPollDelayMs;
            }
            const delay = normalMailRetentionStatusPollDelayMs;
            normalMailRetentionStatusPollDelayMs = Math.min(
                NORMAL_MAIL_RETENTION_STATUS_MAX_POLL_MS,
                normalMailRetentionStatusPollDelayMs * 1.5
            );
            return delay;
        }

        function scheduleNormalMailRetentionStatusPoll() {
            if (normalMailRetentionStatusPollTimer) return;
            normalMailRetentionStatusPollTimer = window.setTimeout(async () => {
                normalMailRetentionStatusPollTimer = null;
                await loadNormalMailRetentionStatus({ silent: true });
            }, nextNormalMailRetentionStatusPollDelay());
        }

        async function loadNormalMailRetentionStatus(options = {}) {
            try {
                const response = await fetch('/api/settings/normal-mail-retention/status', { cache: 'no-store' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '加载普通邮箱本地保留统计失败');
                }
                updateNormalMailRetentionStats(data.status || {});
                return data.status || {};
            } catch (error) {
                if (!options.silent) {
                    renderNormalMailRetentionStatusError(error.message || '加载普通邮箱本地保留统计失败');
                }
                return null;
            }
        }

        async function clearNormalMailRetentionCache() {
            const confirmed = await showConfirmModal(
                '确定要清理普通邮箱本地缓存吗？这只会删除本机 SQLite 中保留的普通邮箱列表和正文缓存，不会关闭本地保留开关。',
                { title: '清理普通邮箱本地缓存', confirmText: '确认清理' }
            );
            if (!confirmed) return false;
            try {
                const response = await fetch('/api/settings/normal-mail-retention/clear', { method: 'POST' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '启动普通邮箱本地缓存清理失败');
                }
                if (typeof invalidateNormalMailRetentionCaches === 'function') {
                    invalidateNormalMailRetentionCaches({ resetCurrentView: true });
                }
                resetNormalMailRetentionStatusPollDelay();
                updateNormalMailRetentionStats({
                    ...(lastNormalMailRetentionStatus || {}),
                    clear_status: data.status || { state: 'running', message: '正在清理普通邮箱本地缓存…' }
                });
                showToast(data.already_running ? '普通邮箱本地缓存正在清理中' : '已开始清理普通邮箱本地缓存', 'success');
                scheduleNormalMailRetentionStatusPoll();
                return true;
            } catch (error) {
                renderNormalMailRetentionStatusError(error.message || '启动普通邮箱本地缓存清理失败');
                showToast('启动普通邮箱本地缓存清理失败', 'error');
                return false;
            }
        }


        function getSettingsScrollContainer() {
            return document.querySelector('#settingsModal .settings-modal-body')
                || document.querySelector('#settingsModal .settings-modal-content');
        }

        function populateTimeZoneOptions(selectedTimeZone = getAppTimeZone()) {
            const select = document.getElementById('settingsAppTimezone');
            if (!select) {
                return;
            }

            const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const normalizedTimeZone = isValidAppTimeZone(selectedTimeZone)
                ? selectedTimeZone
                : getAppTimeZone();
            const availableTimeZones = getAvailableAppTimeZones();
            if (!availableTimeZones.includes(normalizedTimeZone)) {
                availableTimeZones.unshift(normalizedTimeZone);
            }

            select.innerHTML = '';
            availableTimeZones.forEach(timeZone => {
                const option = document.createElement('option');
                option.value = timeZone;
                option.textContent = timeZone === browserTimeZone
                    ? `${timeZone} (System)`
                    : timeZone;
                option.selected = timeZone === normalizedTimeZone;
                select.appendChild(option);
            });
        }

        // 显示设置模态框
        async function showSettingsModal() {
            ensureSettingsScrollSync();
            showModal('settingsModal');
            scrollSettingsSection('settingsGeneralSection');
            populateTimeZoneOptions(getAppTimeZone());
            await loadSettings();
            await loadSkinSettings();
            scheduleSettingsSidebarSync();
        }

        // 隐藏设置模态框
        function hideSettingsModal() {
            hideModal('settingsModal');
            // 清空密码输入框
            const passwordInput = document.getElementById('settingsPassword');
            if (passwordInput) {
                passwordInput.value = '';
            }
            const backupVerifyInput = document.getElementById('webdavBackupVerifyPassword');
            if (backupVerifyInput) {
                backupVerifyInput.value = '';
            }
        }

        function setSkinSettingsStatus(message, type = '') {
            const statusEl = document.getElementById('settingsSkinStatus');
            if (!statusEl) return;
            statusEl.textContent = message || '';
            statusEl.style.display = message ? 'block' : 'none';
            statusEl.dataset.type = type || '';
        }

        function refreshActiveSkinStylesheet(assetHash) {
            const link = document.getElementById('activeSkinStylesheet');
            if (!link) return;
            const version = encodeURIComponent(assetHash || String(Date.now()));
            link.href = `/assets/active-skin.css?v=${version}`;
        }

        function formatSkinSourceLabel(sourceType) {
            if (sourceType === 'builtin') return '内置';
            if (sourceType === 'upload') return '上传';
            if (sourceType === 'git') return 'Git';
            return sourceType || '未知';
        }

        function renderSkinList(payload = {}) {
            lastLoadedSkinSettings = payload || {};
            const listEl = document.getElementById('settingsSkinList');
            const summaryEl = document.getElementById('settingsSkinActiveSummary');
            if (!listEl || !summaryEl) return;

            const activeSkin = payload.active_skin || {};
            const activeName = activeSkin.name || activeSkin.id || 'classic';
            summaryEl.textContent = `${activeName}（${activeSkin.id || 'classic'}）`;

            const skins = Array.isArray(payload.skins) ? payload.skins : [];
            if (!skins.length) {
                listEl.innerHTML = '<div class="settings-note">没有可用皮肤。</div>';
                return;
            }

            listEl.innerHTML = skins.map(skin => {
                const skinId = String(skin.id || '').trim();
                const isActive = !!skin.active;
                const isInvalid = skin.status && skin.status !== 'ok';
                const sourceType = String(skin.source_type || '');
                const escapedId = escapeHtml(skinId);
                const name = escapeHtml(skin.name || skinId);
                const version = escapeHtml(skin.version || '-');
                const sourceLabel = escapeHtml(formatSkinSourceLabel(sourceType));
                const description = escapeHtml(skin.description || '');
                const error = escapeHtml(skin.last_error || '');
                const gitMeta = sourceType === 'git' && skin.git_url
                    ? `<span>${escapeHtml(skin.git_url)}${skin.git_ref ? ` @ ${escapeHtml(skin.git_ref)}` : ''}</span>`
                    : '';
                const activePill = isActive ? '<span class="skin-pill skin-pill--active">当前</span>' : '';
                const invalidPill = isInvalid ? '<span class="skin-pill skin-pill--invalid">不可用</span>' : '';
                const activateButton = isActive || isInvalid
                    ? ''
                    : `<button class="btn btn-sm btn-secondary" type="button" onclick="activateSkin('${skinId}')">启用</button>`;
                const updateButton = sourceType === 'git'
                    ? `<button class="btn btn-sm btn-secondary" type="button" onclick="updateGitSkin('${skinId}')">更新</button>`
                    : '';
                const deleteButton = !skin.builtin && !isActive
                    ? `<button class="btn btn-sm btn-danger" type="button" onclick="deleteSkin('${skinId}')">删除</button>`
                    : '';

                return `
                    <article class="skin-card ${isActive ? 'is-active' : ''} ${isInvalid ? 'is-invalid' : ''}">
                        <div>
                            <div class="skin-card__title">
                                <span>${name}</span>
                                ${activePill}
                                ${invalidPill}
                            </div>
                            <div class="skin-card__meta">
                                <span>ID：${escapedId}</span>
                                <span>版本：${version}</span>
                                <span>来源：${sourceLabel}</span>
                                ${description ? `<span>${description}</span>` : ''}
                                ${gitMeta}
                            </div>
                            ${error ? `<div class="skin-card__error">${error}</div>` : ''}
                        </div>
                        <div class="skin-card__actions">
                            ${activateButton}
                            ${updateButton}
                            ${deleteButton}
                        </div>
                    </article>
                `;
            }).join('');
        }

        async function loadSkinSettings() {
            const listEl = document.getElementById('settingsSkinList');
            if (listEl) {
                listEl.innerHTML = '<div class="settings-note">正在加载皮肤列表...</div>';
            }
            try {
                const response = await fetch('/api/skins', { cache: 'no-store' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '加载皮肤列表失败');
                }
                renderSkinList(data);
                setSkinSettingsStatus('');
                return data;
            } catch (error) {
                setSkinSettingsStatus(error.message || '加载皮肤列表失败', 'error');
                if (listEl) {
                    listEl.innerHTML = '<div class="settings-note">皮肤列表加载失败。</div>';
                }
                return null;
            }
        }

        async function activateSkin(skinId) {
            const normalizedId = String(skinId || '').trim();
            if (!normalizedId) {
                showToast('皮肤 ID 无效', 'error');
                return;
            }
            try {
                const response = await fetch(`/api/skins/${encodeURIComponent(normalizedId)}/activate`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '启用皮肤失败');
                }
                refreshActiveSkinStylesheet(data.asset_hash);
                showToast('皮肤已启用', 'success');
                await loadSkinSettings();
            } catch (error) {
                showToast(error.message || '启用皮肤失败', 'error');
                setSkinSettingsStatus(error.message || '启用皮肤失败', 'error');
            }
        }

        async function uploadSkinPackage() {
            const input = document.getElementById('settingsSkinUploadFile');
            const file = input?.files?.[0];
            if (!file) {
                showToast('请选择 zip 皮肤包', 'error');
                return;
            }
            const formData = new FormData();
            formData.append('skin', file);
            setSkinSettingsStatus('正在安装上传皮肤...', 'pending');
            try {
                const response = await fetch('/api/skins/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '安装上传皮肤失败');
                }
                if (input) input.value = '';
                showToast('皮肤已安装', 'success');
                setSkinSettingsStatus('');
                await loadSkinSettings();
            } catch (error) {
                showToast(error.message || '安装上传皮肤失败', 'error');
                setSkinSettingsStatus(error.message || '安装上传皮肤失败', 'error');
            }
        }

        async function installGitSkin() {
            const gitUrl = document.getElementById('settingsSkinGitUrl')?.value.trim() || '';
            const gitRef = document.getElementById('settingsSkinGitRef')?.value.trim() || '';
            if (!gitUrl) {
                showToast('请输入 Git 仓库地址', 'error');
                return;
            }
            setSkinSettingsStatus('正在安装 Git 皮肤...', 'pending');
            try {
                const response = await fetch('/api/skins/git/install', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ git_url: gitUrl, git_ref: gitRef })
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '安装 Git 皮肤失败');
                }
                showToast('Git 皮肤已安装', 'success');
                setSkinSettingsStatus('');
                await loadSkinSettings();
            } catch (error) {
                showToast(error.message || '安装 Git 皮肤失败', 'error');
                setSkinSettingsStatus(error.message || '安装 Git 皮肤失败', 'error');
            }
        }

        async function updateGitSkin(skinId) {
            const normalizedId = String(skinId || '').trim();
            if (!normalizedId) return;
            setSkinSettingsStatus('正在更新 Git 皮肤...', 'pending');
            try {
                const response = await fetch(`/api/skins/${encodeURIComponent(normalizedId)}/git/update`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '更新 Git 皮肤失败');
                }
                if (lastLoadedSkinSettings?.active_skin_id === normalizedId) {
                    refreshActiveSkinStylesheet(data.skin?.asset_hash);
                }
                showToast('Git 皮肤已更新', 'success');
                setSkinSettingsStatus('');
                await loadSkinSettings();
            } catch (error) {
                showToast(error.message || '更新 Git 皮肤失败', 'error');
                setSkinSettingsStatus(error.message || '更新 Git 皮肤失败', 'error');
            }
        }

        async function deleteSkin(skinId) {
            const normalizedId = String(skinId || '').trim();
            if (!normalizedId) return;
            const confirmed = await showConfirmModal(
                '确定要删除这个自定义皮肤吗？',
                { title: '删除皮肤', confirmText: '确认删除' }
            );
            if (!confirmed) return;
            try {
                const response = await fetch(`/api/skins/${encodeURIComponent(normalizedId)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || '删除皮肤失败');
                }
                showToast('皮肤已删除', 'success');
                await loadSkinSettings();
            } catch (error) {
                showToast(error.message || '删除皮肤失败', 'error');
                setSkinSettingsStatus(error.message || '删除皮肤失败', 'error');
            }
        }

        function updateSettingsSidebarActive(sectionId) {
            document.querySelectorAll('#settingsModal .settings-sidebar-link').forEach(link => {
                link.classList.toggle('is-active', link.dataset.target === sectionId);
            });
        }

        function getSettingsSidebarSectionIds() {
            return Array.from(document.querySelectorAll('#settingsModal .settings-sidebar-link'))
                .map(link => link.dataset.target)
                .filter(Boolean);
        }

        function syncSettingsSidebarActiveByScroll() {
            const scrollContainer = getSettingsScrollContainer();
            if (!scrollContainer) {
                return;
            }

            const sectionIds = getSettingsSidebarSectionIds();
            if (!sectionIds.length) {
                return;
            }

            const modalContent = document.querySelector('#settingsModal .settings-modal-content');
            const header = modalContent?.querySelector('.modal-header');
            const headerHeight = scrollContainer === modalContent && header ? header.offsetHeight : 0;
            const anchorTop = scrollContainer.getBoundingClientRect().top + headerHeight + 28;
            let activeSectionId = sectionIds[0];
            let closestAboveId = '';
            let closestAboveOffset = Number.NEGATIVE_INFINITY;
            let closestBelowId = '';
            let closestBelowOffset = Number.POSITIVE_INFINITY;

            sectionIds.forEach(sectionId => {
                const section = document.getElementById(sectionId);
                if (!section) {
                    return;
                }

                const offset = section.getBoundingClientRect().top - anchorTop;
                if (offset <= 0 && offset > closestAboveOffset) {
                    closestAboveOffset = offset;
                    closestAboveId = sectionId;
                }
                if (offset > 0 && offset < closestBelowOffset) {
                    closestBelowOffset = offset;
                    closestBelowId = sectionId;
                }
            });

            if (closestAboveId) {
                activeSectionId = closestAboveId;
            } else if (closestBelowId) {
                activeSectionId = closestBelowId;
            }

            updateSettingsSidebarActive(activeSectionId);
        }

        function scheduleSettingsSidebarSync() {
            if (settingsScrollSyncFrame) {
                return;
            }

            settingsScrollSyncFrame = window.requestAnimationFrame(() => {
                settingsScrollSyncFrame = 0;
                syncSettingsSidebarActiveByScroll();
            });
        }

        function ensureSettingsScrollSync() {
            if (settingsScrollSyncBound) {
                return;
            }

            const scrollContainer = getSettingsScrollContainer();
            if (!scrollContainer) {
                return;
            }

            scrollContainer.addEventListener('scroll', scheduleSettingsSidebarSync, { passive: true });
            window.addEventListener('resize', scheduleSettingsSidebarSync);
            settingsScrollSyncBound = true;
        }

        function scrollSettingsSection(sectionId, triggerEl = null) {
            const scrollContainer = getSettingsScrollContainer();
            const section = document.getElementById(sectionId);
            if (!scrollContainer || !section) {
                return;
            }

            const modalContent = document.querySelector('#settingsModal .settings-modal-content');
            const header = modalContent.querySelector('.modal-header');
            const headerHeight = scrollContainer === modalContent && header ? header.offsetHeight : 0;
            const sectionTop = section.getBoundingClientRect().top - scrollContainer.getBoundingClientRect().top + scrollContainer.scrollTop;
            const targetTop = Math.max(sectionTop - headerHeight - 18, 0);

            scrollContainer.scrollTo({
                top: targetTop,
                behavior: 'smooth'
            });

            if (triggerEl?.dataset?.target) {
                updateSettingsSidebarActive(triggerEl.dataset.target);
            } else {
                updateSettingsSidebarActive(sectionId);
            }
        }

        // 生成随机对外 API Key
        function generateExternalApiKey() {
            const array = new Uint8Array(16);
            crypto.getRandomValues(array);
            const key = Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
            document.getElementById('settingsExternalApiKey').value = key;
            showToast('已生成随机 API Key，请保存设置', 'success');
        }

        // 切换刷新策略
        function toggleRefreshStrategy() {
            const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
            document.getElementById('daysStrategyContainer').style.display = strategy === 'days' ? 'block' : 'none';
            document.getElementById('cronStrategyContainer').style.display = strategy === 'cron' ? 'block' : 'none';
        }

        // 选择 Cron 样例
        async function selectCronExample(cronExpr) {
            document.getElementById('refreshCron').value = cronExpr;
            await validateCronExpression();
        }

        // 验证 Cron 表达式
        async function validateCronExpression() {
            const cronExpr = document.getElementById('refreshCron').value.trim();
            const resultEl = document.getElementById('cronValidationResult');

            if (!cronExpr) {
                resultEl.innerHTML = '';
                resultEl.style.display = 'none';
                return;
            }

            const selectedTimeZone = document.getElementById('settingsAppTimezone')?.value || getAppTimeZone();
            if (!isValidAppTimeZone(selectedTimeZone)) {
                resultEl.style.display = 'block';
                resultEl.innerHTML = `
                    <div style="color: #dc3545;">
                        Invalid time zone
                    </div>
                `;
                return;
            }

            try {
                const response = await fetch('/api/settings/validate-cron', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cron_expression: cronExpr,
                        time_zone: selectedTimeZone
                    })
                });

                const data = await response.json();

                if (data.success && data.valid) {
                    const previewTimeZone = data.time_zone || selectedTimeZone;
                    const nextRun = new Date(data.next_run).toLocaleString('zh-CN', {
                        timeZone: previewTimeZone,
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #28a745;">
                            ✓ 表达式有效<br>
                            下次执行: ${nextRun}
                        </div>
                    `;
                } else {
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #dc3545;">
                            ✗ ${data.error && data.error.message ? data.error.message : (data.error || '表达式无效')}
                        </div>
                    `;
                }
            } catch (error) {
                resultEl.style.display = 'block';
                resultEl.innerHTML = `
                    <div style="color: #dc3545;">
                        ✗ 验证失败: ${error.message}
                    </div>
                `;
            }
        }

        function normalizeWebdavBackupSettings(settings) {
            return {
                webdav_backup_enabled: String(settings?.webdav_backup_enabled) === 'true' || settings?.webdav_backup_enabled === true ? 'true' : 'false',
                webdav_backup_url: String(settings?.webdav_backup_url || '').trim(),
                webdav_backup_username: String(settings?.webdav_backup_username || '').trim(),
                webdav_backup_password: String(settings?.webdav_backup_password || '').trim(),
                webdav_backup_cron: String(settings?.webdav_backup_cron || '').trim()
            };
        }

        function getWebdavBackupFormSettings() {
            return normalizeWebdavBackupSettings({
                webdav_backup_enabled: !!document.getElementById('webdavBackupEnabled')?.checked,
                webdav_backup_url: document.getElementById('webdavBackupUrl')?.value || '',
                webdav_backup_username: document.getElementById('webdavBackupUsername')?.value || '',
                webdav_backup_password: document.getElementById('webdavBackupPassword')?.value || '',
                webdav_backup_cron: document.getElementById('webdavBackupCron')?.value || ''
            });
        }

        function hasWebdavBackupSettingsChanged(currentSettings) {
            if (!lastLoadedWebdavBackupSettings) {
                return Object.values(currentSettings).some(value => value !== '' && value !== 'false');
            }
            return Object.keys(currentSettings).some(key => currentSettings[key] !== lastLoadedWebdavBackupSettings[key]);
        }

        function buildWebdavBackupDraftConfig() {
            return {
                url: document.getElementById('webdavBackupUrl')?.value.trim() || '',
                username: document.getElementById('webdavBackupUsername')?.value.trim() || '',
                password: document.getElementById('webdavBackupPassword')?.value || ''
            };
        }

        function renderWebdavBackupStatus(settings) {
            const statusEl = document.getElementById('webdavBackupStatus');
            if (!statusEl) return;

            const lines = [];
            if (settings.webdav_backup_next_run) {
                lines.push(`下次执行：${formatAbsoluteDateTime(settings.webdav_backup_next_run)}（${settings.app_timezone || getAppTimeZone()}）`);
            }
            if (settings.webdav_backup_last_run_at) {
                const statusText = settings.webdav_backup_last_status === 'success' ? '成功' : (settings.webdav_backup_last_status || '未知');
                lines.push(`上次执行：${formatAbsoluteDateTime(settings.webdav_backup_last_run_at)}，状态：${statusText}`);
            }
            if (settings.webdav_backup_last_filename) {
                lines.push(`最近文件：${settings.webdav_backup_last_filename}`);
            }
            if (settings.webdav_backup_last_message) {
                lines.push(settings.webdav_backup_last_message);
            }

            statusEl.style.display = 'block';
            statusEl.textContent = lines.length ? lines.join('\n') : '尚未执行备份。保存设置后，调度器重启时会加载新的 Cron 计划。';
        }

        async function selectWebdavBackupCronExample(cronExpr) {
            const input = document.getElementById('webdavBackupCron');
            if (input) {
                input.value = cronExpr;
            }
            await validateWebdavBackupCronExpression();
        }

        async function validateWebdavBackupCronExpression() {
            const cronExpr = document.getElementById('webdavBackupCron')?.value.trim() || '';
            const resultEl = document.getElementById('webdavBackupCronValidationResult');
            if (!resultEl) return;

            if (!cronExpr) {
                resultEl.innerHTML = '';
                resultEl.style.display = 'none';
                return;
            }

            const selectedTimeZone = document.getElementById('settingsAppTimezone')?.value || getAppTimeZone();
            if (!isValidAppTimeZone(selectedTimeZone)) {
                resultEl.style.display = 'block';
                resultEl.innerHTML = '<div style="color: #dc3545;">Invalid time zone</div>';
                return;
            }

            try {
                const response = await fetch('/api/settings/validate-cron', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cron_expression: cronExpr,
                        time_zone: selectedTimeZone,
                        expected_fields: 5
                    })
                });
                const data = await response.json();
                if (data.success && data.valid) {
                    const previewTimeZone = data.time_zone || selectedTimeZone;
                    const nextRun = new Date(data.next_run).toLocaleString('zh-CN', {
                        timeZone: previewTimeZone,
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #28a745;">
                            ✓ 表达式有效<br>
                            下次执行: ${nextRun}
                        </div>
                    `;
                } else {
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #dc3545;">
                            ✗ ${data.error && data.error.message ? data.error.message : (data.error || '表达式无效')}
                        </div>
                    `;
                }
            } catch (error) {
                resultEl.style.display = 'block';
                resultEl.innerHTML = `
                    <div style="color: #dc3545;">
                        ✗ 验证失败: ${error.message}
                    </div>
                `;
            }
        }

        async function testWebdavBackup() {
            const btn = document.getElementById('testWebdavBackupBtn');
            const resultEl = document.getElementById('webdavBackupTestResult');
            if (!btn || btn.disabled) return;

            const draft = buildWebdavBackupDraftConfig();

            if (!draft.url) {
                showToast('请先填写 WebDAV 目录 URL', 'error');
                return;
            }
            try {
                const backupUrl = new URL(draft.url);
                if (!['http:', 'https:'].includes(backupUrl.protocol)) {
                    showToast('WebDAV 目录 URL 必须是 http(s) 地址', 'error');
                    return;
                }
            } catch (error) {
                showToast('WebDAV 目录 URL 无效', 'error');
                return;
            }

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '测试中...';
            if (resultEl) {
                resultEl.style.display = 'block';
                resultEl.style.color = '';
                resultEl.textContent = '正在上传测试文件...';
            }

            try {
                const response = await fetch('/api/settings/test-webdav-backup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config: draft
                    })
                });
                const data = await response.json();
                if (data.success) {
                    const message = data.message || 'WebDAV 测试成功';
                    showToast(message, 'success');
                    if (resultEl) {
                        resultEl.style.display = 'block';
                        resultEl.style.color = '#28a745';
                        resultEl.textContent = `✓ ${message}`;
                    }
                } else {
                    const message = data.error && data.error.message ? data.error.message : (data.error || 'WebDAV 测试失败');
                    handleApiError(data, 'WebDAV 测试失败');
                    if (resultEl) {
                        resultEl.style.display = 'block';
                        resultEl.style.color = '#dc3545';
                        resultEl.textContent = `✗ ${message}`;
                    }
                }
            } catch (error) {
                showToast('WebDAV 测试失败', 'error');
                if (resultEl) {
                    resultEl.style.display = 'block';
                    resultEl.style.color = '#dc3545';
                    resultEl.textContent = `✗ WebDAV 测试失败: ${error.message}`;
                }
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        async function uploadWebdavBackupNow() {
            const btn = document.getElementById('uploadWebdavBackupBtn');
            const resultEl = document.getElementById('webdavBackupTestResult');
            if (!btn || btn.disabled) return;

            const draft = buildWebdavBackupDraftConfig();
            const loginPassword = document.getElementById('webdavBackupVerifyPassword')?.value || '';

            if (!draft.url) {
                showToast('请先填写 WebDAV 目录 URL', 'error');
                return;
            }
            try {
                const backupUrl = new URL(draft.url);
                if (!['http:', 'https:'].includes(backupUrl.protocol)) {
                    showToast('WebDAV 目录 URL 必须是 http(s) 地址', 'error');
                    return;
                }
            } catch (error) {
                showToast('WebDAV 目录 URL 无效', 'error');
                return;
            }
            if (!loginPassword) {
                showToast('手动上传备份需要输入登录密码', 'error');
                return;
            }

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '上传中...';
            if (resultEl) {
                resultEl.style.display = 'block';
                resultEl.style.color = '';
                resultEl.textContent = '正在上传真实备份文件...';
            }

            try {
                const response = await fetch('/api/settings/upload-webdav-backup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config: draft,
                        login_password: loginPassword
                    })
                });
                const data = await response.json();
                if (data.success) {
                    const message = data.message || 'WebDAV 备份已上传';
                    showToast(message, 'success');
                    if (resultEl) {
                        resultEl.style.display = 'block';
                        resultEl.style.color = '#28a745';
                        resultEl.textContent = `✓ ${message}`;
                    }
                    await loadSettings();
                } else {
                    const message = data.error && data.error.message ? data.error.message : (data.error || 'WebDAV 备份上传失败');
                    handleApiError(data, '手动上传失败');
                    if (resultEl) {
                        resultEl.style.display = 'block';
                        resultEl.style.color = '#dc3545';
                        resultEl.textContent = `✗ ${message}`;
                    }
                }
            } catch (error) {
                showToast('手动上传失败', 'error');
                if (resultEl) {
                    resultEl.style.display = 'block';
                    resultEl.style.color = '#dc3545';
                    resultEl.textContent = `✗ 手动上传失败: ${error.message}`;
                }
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        function ensureEditForwardToggle() {
            if (document.getElementById('editForwardEnabled')) return;
            const statusGroup = document.getElementById('editStatus')?.closest('.form-group');
            if (!statusGroup) return;
            statusGroup.insertAdjacentHTML('afterend', `
                <div class="form-group">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="editForwardEnabled">
                        <span class="form-label" style="margin: 0;">启用邮件转发</span>
                    </label>
                    <div class="form-hint">开启后会按系统设置转发到邮箱或 Telegram。</div>
                </div>
            `);
        }

        function renderImportTagOptions() {
            const container = document.getElementById('importTagOptions');
            if (!container) return;

            const tags = typeof allTags !== 'undefined' && Array.isArray(allTags) ? allTags : [];
            if (!tags.length) {
                container.innerHTML = '<div class="import-tag-empty">暂无标签</div>';
                updateImportTagSummary();
                return;
            }

            container.innerHTML = tags.map(tag => `
                <label class="import-tag-option">
                    <input type="checkbox" class="import-tag-checkbox" value="${tag.id}" onchange="updateImportTagSummary()">
                    <span class="import-tag-dot" style="background-color: ${escapeHtml(tag.color || '#9ca3af')};"></span>
                    <span>${escapeHtml(tag.name || '')}</span>
                </label>
            `).join('');
            updateImportTagSummary();
        }

        function updateImportTagSummary() {
            const summaryEl = document.getElementById('importTagSummary');
            const countEl = document.getElementById('importTagCount');
            if (!summaryEl || !countEl) return;

            const selected = Array.from(document.querySelectorAll('.import-tag-checkbox:checked'))
                .map(checkbox => {
                    const label = checkbox.closest('.import-tag-option');
                    return label ? label.textContent.trim() : '';
                })
                .filter(Boolean);

            if (!selected.length) {
                summaryEl.textContent = '未选择标签';
                countEl.style.display = 'none';
                countEl.textContent = '';
                return;
            }

            summaryEl.textContent = selected.length <= 2 ? selected.join('、') : `已选 ${selected.length} 个标签`;
            countEl.style.display = 'inline-flex';
            countEl.textContent = String(selected.length);
        }

        function toggleImportTagDropdown(event) {
            event?.stopPropagation();
            const dropdown = document.getElementById('importTagDropdown');
            if (!dropdown) return;
            dropdown.classList.toggle('open');
        }

        function resetImportDefaults() {
            const remarkInput = document.getElementById('importRemark');
            const statusSelect = document.getElementById('importStatus');
            const forwardInput = document.getElementById('importForwardEnabled');
            const tagDropdown = document.getElementById('importTagDropdown');

            if (remarkInput) remarkInput.value = '';
            if (statusSelect) statusSelect.value = 'active';
            if (forwardInput) forwardInput.checked = false;
            tagDropdown?.classList.remove('open');
            renderImportTagOptions();
        }

        function getImportSelectedTagIds() {
            return Array.from(document.querySelectorAll('.import-tag-checkbox:checked'))
                .map(checkbox => parseInt(checkbox.value, 10))
                .filter(Number.isFinite);
        }

        async function loadCloudflareChannelsForImport(forceRefresh = false) {
            const select = document.getElementById('importCloudflareChannelSelect');
            if (!select) return [];
            const channels = typeof loadCloudflareChannelsForTempEmails === 'function'
                ? await loadCloudflareChannelsForTempEmails(forceRefresh)
                : [];
            const enabledChannels = (Array.isArray(channels) ? channels : []).filter(channel => channel.enabled);
            if (!enabledChannels.length) {
                select.innerHTML = '<option value="">请先在设置中配置 Cloudflare 渠道</option>';
                return [];
            }
            const currentValue = select.value;
            select.innerHTML = enabledChannels.map(channel => (
                `<option value="${Number(channel.id)}">${escapeHtml(channel.name || `#${channel.id}`)}</option>`
            )).join('');
            const defaultChannel = enabledChannels.find(channel => channel.is_default) || enabledChannels[0];
            select.value = enabledChannels.some(channel => String(channel.id) === currentValue)
                ? currentValue
                : String(defaultChannel.id);
            return enabledChannels;
        }

        function showAddAccountModal() {
            showModal('addAccountModal');
            document.getElementById('accountInput').value = '';
            if (document.getElementById('importProviderSelect')) {
                document.getElementById('importProviderSelect').value = 'outlook';
            }
            if (document.getElementById('importImapHost')) {
                document.getElementById('importImapHost').value = '';
            }
            if (document.getElementById('importImapPort')) {
                document.getElementById('importImapPort').value = '993';
            }
            if (currentGroupId) {
                document.getElementById('importGroupSelect').value = currentGroupId;
            }
            const cloudflareMode = document.getElementById('importCloudflareImportMode');
            if (cloudflareMode) {
                cloudflareMode.value = 'auto';
            }
            resetImportDefaults();
            updateImportHint();
            loadCloudflareChannelsForImport();
        }

        async function addAccount() {
            const input = document.getElementById('accountInput').value.trim();
            const groupId = parseInt(document.getElementById('importGroupSelect').value);
            const provider = document.getElementById('importProviderSelect')?.value || 'outlook';
            const isTempGroup = isTempImportGroup();
            const tempProvider = isTempGroup ? (document.getElementById('importChannelSelect').value || 'gptmail') : '';
            const cloudflareMode = document.getElementById('importCloudflareImportMode')?.value || 'auto';
            const isCloudflareAutoImport = isTempGroup && tempProvider === 'cloudflare' && cloudflareMode === 'auto';
            const cloudflareChannelId = document.getElementById('importCloudflareChannelSelect')?.value || '';
            const imapHost = document.getElementById('importImapHost')?.value.trim() || '';
            const imapPort = parseInt(document.getElementById('importImapPort')?.value || '993', 10);
            const forwardEnabled = !!document.getElementById('importForwardEnabled')?.checked;
            const remark = document.getElementById('importRemark')?.value.trim() || '';
            const status = document.getElementById('importStatus')?.value || 'active';
            const tagIds = getImportSelectedTagIds();
            const importButton = document.querySelector('#addAccountModal .btn.btn-primary');

            if (!input && !isCloudflareAutoImport) {
                showToast('请输入账号信息', 'error');
                return;
            }

            if (!isTempGroup && provider === 'custom' && !imapHost) {
                showToast('自定义 IMAP 必须填写服务器地址', 'error');
                return;
            }
            if (isTempGroup && tempProvider === 'cloudflare' && !cloudflareChannelId) {
                showToast('请选择 Cloudflare 渠道', 'error');
                return;
            }

            try {
                if (importButton) {
                    importButton.disabled = true;
                    importButton.textContent = '导入中...';
                }
                let response;
                if (isTempGroup) {
                    const endpoint = isCloudflareAutoImport
                        ? '/api/temp-emails/import-cloudflare-addresses'
                        : '/api/temp-emails/import';
                    const payload = {
                        provider: tempProvider,
                        tag_ids: tagIds
                    };
                    if (!isCloudflareAutoImport) {
                        payload.account_string = input;
                    }
                    if (tempProvider === 'cloudflare') {
                        payload.cloudflare_channel_id = cloudflareChannelId;
                    }

                    // 自动导入支持流式进度
                    if (isCloudflareAutoImport) {
                        payload.stream = true;
                        const progressHint = document.getElementById('importFormatExample');
                        if (progressHint) {
                            progressHint.style.display = '';
                            progressHint.textContent = '正在拉取地址列表...';
                        }

                        response = await fetch(endpoint, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });

                        // 处理 Server-Sent Events 流
                        if (response.headers.get('content-type')?.includes('text/event-stream')) {
                            const reader = response.body.getReader();
                            const decoder = new TextDecoder();
                            let buffer = '';
                            let lastData = null;

                            while (true) {
                                const { done, value } = await reader.read();
                                if (done) break;

                                buffer += decoder.decode(value, { stream: true });
                                const lines = buffer.split('\n\n');
                                buffer = lines.pop() || '';

                                for (const line of lines) {
                                    if (line.startsWith('data: ')) {
                                        try {
                                            const eventData = JSON.parse(line.substring(6));
                                            lastData = eventData;

                                            if (eventData.type === 'progress' && progressHint) {
                                                const percent = eventData.total > 0
                                                    ? Math.round((eventData.imported / eventData.total) * 100)
                                                    : 0;
                                                progressHint.textContent = `导入进度: ${eventData.imported}/${eventData.total} (${percent}%) - 新增 ${eventData.added}，更新 ${eventData.updated}`;
                                            } else if (eventData.type === 'complete') {
                                                if (progressHint) {
                                                    progressHint.textContent = eventData.success
                                                        ? `✅ ${eventData.message || '导入完成'}`
                                                        : `❌ ${eventData.error || '导入失败'}`;
                                                }
                                            }
                                        } catch (e) {
                                            console.error('Parse SSE error:', e);
                                        }
                                    }
                                }
                            }

                            // 使用最后收到的完整数据
                            if (lastData && lastData.type === 'complete') {
                                if (lastData.success) {
                                    showToast(lastData.message, 'success');
                                    hideAddAccountModal();
                                    delete accountsCache[groupId];
                                    await loadGroups();
                                    if (currentGroupId === groupId) await loadAccountsByGroup(groupId);
                                } else {
                                    handleApiError(lastData, '导入临时邮箱失败');
                                }
                                return;
                            }
                        }
                    } else {
                        response = await fetch(endpoint, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                    }
                } else {
                    response = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            account_string: input,
                            group_id: groupId,
                            provider,
                            imap_host: imapHost,
                            imap_port: Number.isFinite(imapPort) ? imapPort : 993,
                            forward_enabled: forwardEnabled,
                            remark,
                            status,
                            tag_ids: tagIds
                        })
                    });
                }

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideAddAccountModal();
                    delete accountsCache[groupId];
                    await loadGroups();
                    if (isTempGroup) {
                        await loadTempEmails(true);
                    } else {
                        await loadAccountsByGroup(groupId, true);
                    }
                } else {
                    handleApiError(data, '导入失败');
                }
            } catch (error) {
                showToast('导入失败', 'error');
            } finally {
                if (importButton) {
                    importButton.disabled = false;
                    importButton.textContent = '导入';
                }
            }
        }

        async function showEditAccountModal(accountId) {
            try {
                ensureEditForwardToggle();
                const response = await fetch(`/api/accounts/${accountId}`);
                const data = await response.json();

                if (data.success) {
                    closeAllModals();
                    const acc = data.account;
                    editAccountSecretState.accountId = String(acc.id || '');
                    editAccountSecretState.pendingField = '';
                    document.getElementById('editAccountId').value = acc.id;
                    document.getElementById('editEmail').value = acc.email || '';
                    resetEditSecretInput('editPassword', 'revealEditPasswordBtn', !!acc.has_password, '可选');
                    document.getElementById('editClientId').value = acc.client_id || '';
                    document.getElementById('editRefreshToken').value = acc.refresh_token || '';
                    resetEditSecretInput('editImapPassword', 'revealEditImapPasswordBtn', !!acc.has_imap_password, '');
                    document.getElementById('editImapHost').value = acc.imap_host || '';
                    document.getElementById('editImapPort').value = acc.imap_port || 993;
                    document.getElementById('editGroupSelect').value = acc.group_id || 1;
                    document.getElementById('editProxyUrl').value = acc.proxy_url || '';
                    document.getElementById('editFallbackProxyUrl1').value = acc.fallback_proxy_url_1 || '';
                    document.getElementById('editFallbackProxyUrl2').value = acc.fallback_proxy_url_2 || '';
                    document.getElementById('editSortOrder').value = Number(acc.sort_order || 0);
                    document.getElementById('editRemark').value = acc.remark || '';
                    document.getElementById('editAliases').value = Array.isArray(acc.aliases) ? acc.aliases.join('\n') : '';
                    document.getElementById('editStatus').value = acc.status || 'active';
                    if (document.getElementById('editForwardEnabled')) {
                        document.getElementById('editForwardEnabled').checked = !!acc.forward_enabled;
                    }
                    if (document.getElementById('editProviderSelect')) {
                        document.getElementById('editProviderSelect').value = acc.provider || (acc.account_type === 'imap' ? 'custom' : 'outlook');
                    }
                    updateEditAccountFields();
                    setModalVisible('editAccountModal', true);
                }
            } catch (error) {
                showToast('加载账号信息失败', 'error');
            }
        }

        async function updateAccount() {
            const accountId = document.getElementById('editAccountId').value;
            const oldGroupId = currentGroupId;
            const newGroupId = parseInt(document.getElementById('editGroupSelect').value);
            const provider = document.getElementById('editProviderSelect')?.value || 'outlook';
            const isOutlook = provider === 'outlook';
            const imapPort = parseInt(document.getElementById('editImapPort')?.value || '993', 10);
            const sortOrder = parseInt(document.getElementById('editSortOrder')?.value || '0', 10);
            const passwordInput = document.getElementById('editPassword');
            const imapPasswordInput = document.getElementById('editImapPassword');
            const imapPasswordValue = imapPasswordInput?.value || '';
            const imapPasswordLockedWithSavedValue = (
                imapPasswordInput?.dataset.secretHasSaved === 'true'
                && imapPasswordInput?.dataset.secretLoaded !== 'true'
            );

            const data = {
                email: document.getElementById('editEmail').value.trim(),
                client_id: document.getElementById('editClientId').value.trim(),
                refresh_token: document.getElementById('editRefreshToken').value.trim(),
                account_type: isOutlook ? 'outlook' : 'imap',
                provider,
                imap_host: document.getElementById('editImapHost')?.value.trim() || '',
                imap_port: Number.isFinite(imapPort) ? imapPort : 993,
                group_id: newGroupId,
                proxy_url: document.getElementById('editProxyUrl')?.value.trim() || '',
                fallback_proxy_url_1: document.getElementById('editFallbackProxyUrl1')?.value.trim() || '',
                fallback_proxy_url_2: document.getElementById('editFallbackProxyUrl2')?.value.trim() || '',
                sort_order: Number.isFinite(sortOrder) ? Math.max(0, sortOrder) : 0,
                remark: document.getElementById('editRemark').value.trim(),
                aliases: document.getElementById('editAliases')?.value
                    .split('\n')
                    .map(item => item.trim())
                    .filter(Boolean),
                status: document.getElementById('editStatus').value,
                forward_enabled: !!document.getElementById('editForwardEnabled')?.checked
            };
            if (shouldSubmitSecretInput(passwordInput)) {
                data.password = passwordInput.value;
            }
            if (shouldSubmitSecretInput(imapPasswordInput)) {
                data.imap_password = imapPasswordValue;
            }

            if (isOutlook) {
                if (!data.email || !data.client_id || !data.refresh_token) {
                    showToast('邮箱、Client ID 和 Refresh Token 不能为空', 'error');
                    return;
                }
            } else {
                if (!data.email || (!imapPasswordValue && !imapPasswordLockedWithSavedValue)) {
                    showToast('邮箱和 IMAP 密码不能为空', 'error');
                    return;
                }
                if (provider === 'custom' && !data.imap_host) {
                    showToast('自定义 IMAP 必须填写服务器地址', 'error');
                    return;
                }
            }
            if (!Number.isFinite(sortOrder) || sortOrder < 0) {
                showToast('排序值不能小于 0', 'error');
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                if (result.success) {
                    showToast(result.message, 'success');
                    hideEditAccountModal();
                    delete accountsCache[oldGroupId];
                    if (oldGroupId !== newGroupId) {
                        delete accountsCache[newGroupId];
                    }
                    loadGroups();
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    handleApiError(result, '更新失败');
                }
            } catch (error) {
                showToast('更新失败', 'error');
            }
        }

        function setCloudflareChannelFormMode(isEditing) {
            const saveBtn = document.getElementById('saveCloudflareChannelBtn');
            const resetBtn = document.getElementById('resetCloudflareChannelBtn');
            const deleteBtn = document.getElementById('deleteCloudflareChannelBtn');
            const testBtn = document.getElementById('testCloudflareChannelBtn');
            const testResult = document.getElementById('cloudflareChannelTestResult');
            if (saveBtn) saveBtn.textContent = isEditing ? '保存渠道' : '创建渠道';
            if (resetBtn) resetBtn.textContent = isEditing ? '新建渠道' : '清空表单';
            if (deleteBtn) deleteBtn.style.display = isEditing ? '' : 'none';
            if (testBtn) testBtn.style.display = isEditing ? '' : 'none';
            if (testResult) testResult.style.display = 'none';
        }

        function resetCloudflareChannelForm() {
            const idInput = document.getElementById('settingsCloudflareChannelId');
            if (!idInput) return;
            idInput.value = '';
            document.getElementById('settingsCloudflareChannelName').value = '';
            document.getElementById('settingsCloudflareWorkerDomain').value = '';
            document.getElementById('settingsCloudflareEmailDomains').value = '';
            document.getElementById('settingsCloudflareAdminPassword').value = '';
            document.getElementById('settingsCloudflareAdminPassword').placeholder = '对应 Cloudflare Temp Email 的 ADMIN_PASSWORD';
            document.getElementById('settingsCloudflareEnabled').checked = true;
            document.getElementById('settingsCloudflareDefault').checked = cloudflareSettingsChannels.length === 0;
            setCloudflareChannelFormMode(false);
        }

        function renderCloudflareChannelsForSettings() {
            const list = document.getElementById('settingsCloudflareChannelList');
            if (!list) return;
            if (!cloudflareSettingsChannels.length) {
                list.innerHTML = '<div class="form-hint">暂无 Cloudflare 渠道</div>';
                return;
            }
            list.innerHTML = cloudflareSettingsChannels.map(channel => `
                <div class="cloudflare-channel-row">
                    <div>
                        <div class="cloudflare-channel-row-title">${escapeHtml(channel.name || `#${channel.id}`)}</div>
                        <div class="cloudflare-channel-row-meta">
                            <span class="cloudflare-channel-pill">${escapeHtml(channel.worker_domain || '未配置 Worker')}</span>
                            <span class="cloudflare-channel-pill">${escapeHtml((channel.email_domains || []).join(', ') || '未配置域名')}</span>
                            <span class="cloudflare-channel-pill">${channel.enabled ? '启用' : '停用'}</span>
                            ${channel.is_default ? '<span class="cloudflare-channel-pill">默认</span>' : ''}
                            <span class="cloudflare-channel-pill">${Number(channel.reference_count || 0)} 个邮箱</span>
                        </div>
                    </div>
                    <button class="btn btn-secondary" type="button" onclick="editCloudflareChannel(${Number(channel.id)})">编辑</button>
                </div>
            `).join('');
        }

        async function loadCloudflareChannelsForSettings() {
            const list = document.getElementById('settingsCloudflareChannelList');
            if (list) list.innerHTML = '<div class="form-hint">加载中...</div>';
            try {
                const response = await fetch('/api/cloudflare/channels');
                const data = await response.json();
                cloudflareSettingsChannels = data.success && Array.isArray(data.channels) ? data.channels : [];
                renderCloudflareChannelsForSettings();
                resetCloudflareChannelForm();
            } catch (error) {
                cloudflareSettingsChannels = [];
                if (list) list.innerHTML = '<div class="form-hint">加载失败</div>';
            }
        }

        function editCloudflareChannel(channelId) {
            const channel = cloudflareSettingsChannels.find(item => Number(item.id) === Number(channelId));
            if (!channel) return;
            document.getElementById('settingsCloudflareChannelId').value = String(channel.id);
            document.getElementById('settingsCloudflareChannelName').value = channel.name || '';
            document.getElementById('settingsCloudflareWorkerDomain').value = channel.worker_domain || '';
            document.getElementById('settingsCloudflareEmailDomains').value = (channel.email_domains || []).join(', ');
            document.getElementById('settingsCloudflareAdminPassword').value = '';
            document.getElementById('settingsCloudflareAdminPassword').placeholder = channel.admin_password_configured ? '已保存，留空不修改' : '对应 Cloudflare Temp Email 的 ADMIN_PASSWORD';
            document.getElementById('settingsCloudflareEnabled').checked = !!channel.enabled;
            document.getElementById('settingsCloudflareDefault').checked = !!channel.is_default;
            setCloudflareChannelFormMode(true);
        }

        async function testCloudflareChannelConnection() {
            const channelId = document.getElementById('settingsCloudflareChannelId')?.value || '';
            if (!channelId) {
                showToast('请先选择要测试的渠道', 'error');
                return;
            }

            const btn = document.getElementById('testCloudflareChannelBtn');
            const resultContainer = document.getElementById('cloudflareChannelTestResult');
            const resultText = document.getElementById('cloudflareChannelTestResultText');
            const originalText = btn?.textContent || '';

            if (btn) {
                btn.disabled = true;
                btn.textContent = '测试中...';
            }
            if (resultContainer) {
                resultContainer.style.display = '';
            }
            if (resultText) {
                resultText.textContent = '正在测试 Cloudflare 管理员 API 连接...';
                resultText.className = 'form-hint';
            }

            try {
                const response = await fetch(`/api/cloudflare/channels/${encodeURIComponent(channelId)}/test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();

                if (resultText) {
                    let html = `<strong>${escapeHtml(data.message || '测试完成')}</strong><br><br>`;
                    if (data.tests && Array.isArray(data.tests)) {
                        html += '<ul style="margin: 0; padding-left: 20px;">';
                        for (const test of data.tests) {
                            const icon = test.success ? '✅' : '❌';
                            html += `<li>${icon} ${escapeHtml(test.test)}`;
                            if (test.success) {
                                if (test.domains) {
                                    html += `: ${test.domains.length} 个域名`;
                                    if (test.domains.length > 0) {
                                        html += ` (${test.domains.slice(0, 3).map(d => escapeHtml(d)).join(', ')}${test.domains.length > 3 ? '...' : ''})`;
                                    }
                                } else if (test.count !== undefined) {
                                    html += `: 总计 ${test.count} 条记录`;
                                }
                            } else if (test.error) {
                                html += `: ${escapeHtml(test.error)}`;
                            }
                            html += '</li>';
                        }
                        html += '</ul>';
                    }
                    resultText.innerHTML = html;
                    resultText.className = data.success ? 'form-hint success-text' : 'form-hint error-text';
                }

                if (data.success) {
                    showToast('连接测试通过', 'success');
                } else {
                    showToast(data.message || '连接测试失败', 'error');
                }
            } catch (error) {
                if (resultText) {
                    resultText.textContent = `测试失败: ${error.message}`;
                    resultText.className = 'form-hint error-text';
                }
                showToast('测试连接失败', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            }
        }

        async function saveCloudflareChannel() {
            const channelId = document.getElementById('settingsCloudflareChannelId')?.value || '';
            const payload = {
                name: document.getElementById('settingsCloudflareChannelName')?.value.trim() || '',
                worker_domain: document.getElementById('settingsCloudflareWorkerDomain')?.value.trim() || '',
                email_domains: document.getElementById('settingsCloudflareEmailDomains')?.value.trim() || '',
                admin_password: document.getElementById('settingsCloudflareAdminPassword')?.value.trim() || '',
                enabled: !!document.getElementById('settingsCloudflareEnabled')?.checked,
                is_default: !!document.getElementById('settingsCloudflareDefault')?.checked
            };
            if (!payload.name || !payload.worker_domain) {
                showToast('请填写渠道名称和 Worker 域名', 'error');
                return;
            }
            if (!channelId && !payload.admin_password) {
                showToast('新建渠道必须填写管理员密码', 'error');
                return;
            }
            try {
                const response = await fetch(channelId ? `/api/cloudflare/channels/${encodeURIComponent(channelId)}` : '/api/cloudflare/channels', {
                    method: channelId ? 'PUT' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '保存 Cloudflare 渠道失败');
                    return;
                }
                showToast(data.message || 'Cloudflare 渠道已保存', 'success');
                delete accountsCache.cloudflareChannels;
                delete accountsCache.temp;
                await loadCloudflareChannelsForSettings();
                if (currentGroupId) loadTempEmails(true);
            } catch (error) {
                showToast('保存 Cloudflare 渠道失败', 'error');
            }
        }

        async function deleteCloudflareChannel() {
            const channelId = document.getElementById('settingsCloudflareChannelId')?.value || '';
            if (!channelId) return;
            if (!(await showConfirmModal('确定要删除这个 Cloudflare 渠道吗？', { title: '删除渠道', confirmText: '确认删除' }))) {
                return;
            }
            try {
                const response = await fetch(`/api/cloudflare/channels/${encodeURIComponent(channelId)}`, { method: 'DELETE' });
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '删除 Cloudflare 渠道失败');
                    return;
                }
                showToast(data.message || 'Cloudflare 渠道已删除', 'success');
                delete accountsCache.cloudflareChannels;
                delete accountsCache.temp;
                await loadCloudflareChannelsForSettings();
                if (currentGroupId) loadTempEmails(true);
            } catch (error) {
                showToast('删除 Cloudflare 渠道失败', 'error');
            }
        }

        async function testCloudflareAiUsernames() {
            const resultEl = document.getElementById('settingsCloudflareAiTestResult');
            const btn = document.getElementById('testCloudflareAiBtn');
            const originalText = btn?.textContent || '';
            const apiKey = document.getElementById('settingsCloudflareAiApiKey')?.value.trim() || '';
            const count = parseInt(document.getElementById('settingsCloudflareAiTestCount')?.value || '5', 10);
            const body = {
                api_url: document.getElementById('settingsCloudflareAiApiUrl')?.value.trim() || '',
                model: document.getElementById('settingsCloudflareAiModel')?.value.trim() || '',
                prompt: document.getElementById('settingsCloudflareAiPrompt')?.value.trim() || '',
                count: Number.isNaN(count) ? 5 : count
            };
            if (apiKey) {
                body.api_key = apiKey;
            }

            if (btn) {
                btn.disabled = true;
                btn.textContent = '测试中...';
            }
            if (resultEl) {
                resultEl.textContent = '测试中...';
            }

            try {
                const response = await fetch('/api/cloudflare/ai-usernames/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, 'AI 用户名测试失败');
                    if (resultEl) resultEl.textContent = data.error || '测试失败';
                    return;
                }
                const usernames = Array.isArray(data.usernames) ? data.usernames : [];
                if (resultEl) {
                    resultEl.textContent = usernames.length ? usernames.join(', ') : '未返回可用用户名';
                }
                showToast('AI 用户名测试完成', 'success');
            } catch (error) {
                showToast('AI 用户名测试失败', 'error');
                if (resultEl) resultEl.textContent = '测试失败';
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            }
        }

        async function loadSettings() {
            ensureForwardingSettingsUI();
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();

                if (data.success) {
                    const appTimeZone = data.settings.app_timezone || getAppTimeZone();
                    setAppTimeZone(appTimeZone);
                    populateTimeZoneOptions(appTimeZone);
                    document.getElementById('settingsApiKey').value = data.settings.gptmail_api_key || '';
                    document.getElementById('settingsExternalApiKey').value = data.settings.external_api_key || '';
                    document.getElementById('settingsDuckmailBaseUrl').value = data.settings.duckmail_base_url || '';
                    document.getElementById('settingsDuckmailApiKey').value = data.settings.duckmail_api_key || '';
                    document.getElementById('settingsCloudflareAiEnabled').checked = String(data.settings.cloudflare_ai_username_enabled) === 'true';
                    document.getElementById('settingsCloudflareAiApiUrl').value = data.settings.cloudflare_ai_username_api_url || '';
                    document.getElementById('settingsCloudflareAiModel').value = data.settings.cloudflare_ai_username_model || '';
                    document.getElementById('settingsCloudflareAiApiKey').value = '';
                    document.getElementById('settingsCloudflareAiApiKey').placeholder = data.settings.cloudflare_ai_username_api_key_configured ? '已保存，留空不修改' : '输入 AI API Key';
                    document.getElementById('settingsCloudflareAiApiKeyHint').textContent = data.settings.cloudflare_ai_username_api_key_configured ? '已配置' : '未配置';
                    document.getElementById('settingsCloudflareAiClearApiKey').checked = false;
                    document.getElementById('settingsCloudflareAiPrompt').value = data.settings.cloudflare_ai_username_prompt || '';
                    document.getElementById('settingsCloudflareAiTestResult').textContent = '未测试';
                    document.getElementById('settingsAppTimezone').value = appTimeZone;
                    document.getElementById('settingsPassword').value = '';

                    document.getElementById('refreshIntervalDays').value = data.settings.refresh_interval_days || '30';
                    document.getElementById('refreshDelaySeconds').value = data.settings.refresh_delay_seconds || '5';
                    document.getElementById('refreshCron').value = data.settings.refresh_cron || '0 2 * * *';
                    document.getElementById('enableScheduledRefresh').checked = data.settings.enable_scheduled_refresh !== 'false';
                    document.getElementById('settingsShowAccountCreatedAt').checked = String(data.settings.show_account_created_at) !== 'false';
                    document.getElementById('settingsShowAccountSortOrder').checked = String(data.settings.show_account_sort_order) === 'true';
                    document.getElementById('settingsShowGroupId').checked = String(data.settings.show_group_id) !== 'false';
                    const retentionEnabled = parseSettingsBoolean(data.settings.normal_mail_local_retention_enabled);
                    document.getElementById('normalMailLocalRetentionEnabled').checked = retentionEnabled;
                    setNormalMailLocalRetentionEnabled(retentionEnabled);
                    const fallbackForwardSeconds = String((parseInt(data.settings.forward_check_interval_minutes || '5', 10) || 5) * 60);
                    document.getElementById('forwardCheckIntervalSeconds').value = data.settings.forward_check_interval_seconds || fallbackForwardSeconds;
                    document.getElementById('forwardExecutionMode').value = data.settings.forward_execution_mode === 'parallel' ? 'parallel' : 'serial';
                    document.getElementById('forwardParallelWorkers').value = data.settings.forward_parallel_workers || '4';
                    document.getElementById('forwardAccountDelaySeconds').value = data.settings.forward_account_delay_seconds || '0';
                    document.getElementById('forwardEmailWindowMinutes').value = data.settings.forward_email_window_minutes || '0';
                    document.getElementById('forwardIncludeJunkemail').checked = String(data.settings.forward_include_junkemail) === 'true';
                    document.getElementById('settingsEmailForwardRecipient').value = data.settings.email_forward_recipient || '';
                    document.getElementById('settingsSmtpHost').value = data.settings.smtp_host || '';
                    document.getElementById('settingsSmtpPort').value = data.settings.smtp_port || '465';
                    document.getElementById('settingsSmtpUsername').value = data.settings.smtp_username || '';
                    document.getElementById('settingsSmtpPassword').value = data.settings.smtp_password || '';
                    document.getElementById('settingsSmtpProvider').value = normalizeSmtpForwardProvider(data.settings.smtp_provider || 'custom');
                    document.getElementById('settingsSmtpFromEmail').value = data.settings.smtp_from_email || '';
                    document.getElementById('settingsSmtpUseTls').checked = String(data.settings.smtp_use_tls) === 'true';
                    document.getElementById('settingsSmtpUseSsl').checked = String(data.settings.smtp_use_ssl) !== 'false';
                    document.getElementById('settingsTelegramBotToken').value = data.settings.telegram_bot_token || '';
                    document.getElementById('settingsTelegramChatId').value = data.settings.telegram_chat_id || '';
                    document.getElementById('settingsTelegramProxyUrl').value = data.settings.telegram_proxy_url || '';
                    document.getElementById('settingsWecomWebhookUrl').value = data.settings.wecom_webhook_url || '';
                    document.getElementById('webdavBackupEnabled').checked = String(data.settings.webdav_backup_enabled) === 'true';
                    document.getElementById('webdavBackupUrl').value = data.settings.webdav_backup_url || '';
                    document.getElementById('webdavBackupUsername').value = data.settings.webdav_backup_username || '';
                    document.getElementById('webdavBackupPassword').value = data.settings.webdav_backup_password || '';
                    document.getElementById('webdavBackupCron').value = data.settings.webdav_backup_cron || '0 3 * * *';
                    document.getElementById('webdavBackupVerifyPassword').value = '';
                    lastLoadedWebdavBackupSettings = normalizeWebdavBackupSettings(data.settings);
                    renderWebdavBackupStatus(data.settings);
                    setSelectedForwardChannels(data.settings.forward_channels || []);

                    const useCron = data.settings.use_cron_schedule === 'true';
                    document.querySelector('input[name="refreshStrategy"][value="' + (useCron ? 'cron' : 'days') + '"]').checked = true;
                    toggleRefreshStrategy();
                    syncSmtpProviderUI(false);
                    syncForwardExecutionModeUI();
                    await loadCloudflareChannelsForSettings();
                    await loadNormalMailRetentionStatus();
                }
            } catch (error) {
                showToast('加载设置失败', 'error');
            }
        }

        async function saveSettings() {
            ensureForwardingSettingsUI();
            const password = document.getElementById('settingsPassword').value;
            const apiKey = document.getElementById('settingsApiKey').value.trim();
            const externalApiKey = document.getElementById('settingsExternalApiKey').value.trim();
            const refreshDays = document.getElementById('refreshIntervalDays').value;
            const refreshDelay = document.getElementById('refreshDelaySeconds').value;
            const refreshCron = document.getElementById('refreshCron').value.trim();
            const appTimeZone = document.getElementById('settingsAppTimezone').value.trim();
            const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
            const enableScheduled = document.getElementById('enableScheduledRefresh').checked;
            const showAccountCreatedAt = !!document.getElementById('settingsShowAccountCreatedAt')?.checked;
            const showAccountSortOrder = !!document.getElementById('settingsShowAccountSortOrder')?.checked;
            const showGroupId = !!document.getElementById('settingsShowGroupId')?.checked;
            const normalMailLocalRetentionEnabled = !!document.getElementById('normalMailLocalRetentionEnabled')?.checked;
            const settings = {};
            const forwardChannels = getSelectedForwardChannels();

            if (password) {
                settings.login_password = password;
            }

            settings.gptmail_api_key = apiKey;
            settings.external_api_key = externalApiKey;
            settings.duckmail_base_url = document.getElementById('settingsDuckmailBaseUrl').value.trim();
            settings.duckmail_api_key = document.getElementById('settingsDuckmailApiKey').value.trim();
            settings.cloudflare_ai_username_enabled = !!document.getElementById('settingsCloudflareAiEnabled')?.checked;
            settings.cloudflare_ai_username_api_url = document.getElementById('settingsCloudflareAiApiUrl')?.value.trim() || '';
            settings.cloudflare_ai_username_model = document.getElementById('settingsCloudflareAiModel')?.value.trim() || '';
            settings.cloudflare_ai_username_prompt = document.getElementById('settingsCloudflareAiPrompt')?.value.trim() || '';
            const cloudflareAiApiKey = document.getElementById('settingsCloudflareAiApiKey')?.value.trim() || '';
            if (cloudflareAiApiKey) {
                settings.cloudflare_ai_username_api_key = cloudflareAiApiKey;
            }
            if (document.getElementById('settingsCloudflareAiClearApiKey')?.checked) {
                settings.cloudflare_ai_username_clear_api_key = true;
            }

            const days = parseInt(refreshDays, 10);
            const delay = parseInt(refreshDelay, 10);
            const forwardSeconds = parseInt(document.getElementById('forwardCheckIntervalSeconds').value || '300', 10);
            const forwardExecutionMode = document.getElementById('forwardExecutionMode')?.value === 'parallel' ? 'parallel' : 'serial';
            const forwardParallelWorkers = parseInt(document.getElementById('forwardParallelWorkers').value || '4', 10);
            const forwardAccountDelaySeconds = forwardExecutionMode === 'parallel'
                ? 0
                : parseInt(document.getElementById('forwardAccountDelaySeconds').value || '0', 10);
            const forwardWindowMinutes = parseInt(document.getElementById('forwardEmailWindowMinutes').value || '0', 10);
            const forwardIncludeJunkemail = !!document.getElementById('forwardIncludeJunkemail')?.checked;
            const smtpPortValue = document.getElementById('settingsSmtpPort').value.trim();
            const smtpPort = parseInt(smtpPortValue || '465', 10);
            const smtpRecipient = document.getElementById('settingsEmailForwardRecipient').value.trim();
            const smtpHost = document.getElementById('settingsSmtpHost').value.trim();
            const smtpProvider = normalizeSmtpForwardProvider(document.getElementById('settingsSmtpProvider')?.value || 'custom');
            const smtpFromEmail = document.getElementById('settingsSmtpFromEmail').value.trim();
            const smtpUsername = document.getElementById('settingsSmtpUsername').value.trim();
            const telegramBotToken = document.getElementById('settingsTelegramBotToken').value.trim();
            const telegramChatId = document.getElementById('settingsTelegramChatId').value.trim();
            const telegramProxyUrl = document.getElementById('settingsTelegramProxyUrl').value.trim();
            const wecomWebhookUrl = document.getElementById('settingsWecomWebhookUrl').value.trim();
            const webdavBackupSettings = getWebdavBackupFormSettings();
            const webdavBackupChanged = hasWebdavBackupSettingsChanged(webdavBackupSettings);
            const webdavBackupVerifyPassword = document.getElementById('webdavBackupVerifyPassword')?.value || '';

            if (Number.isNaN(days) || days < 1 || days > 90) {
                showToast('刷新周期必须在 1-90 天之间', 'error');
                return;
            }
            if (Number.isNaN(delay) || delay < 0 || delay > 60) {
                showToast('刷新间隔必须在 0-60 秒之间', 'error');
                return;
            }
            if (!isValidAppTimeZone(appTimeZone)) {
                showToast('Invalid time zone', 'error');
                return;
            }
            if (Number.isNaN(forwardSeconds) || forwardSeconds < 20 || forwardSeconds > 3600) {
                showToast('转发轮询间隔必须在 20-3600 秒之间', 'error');
                return;
            }
            if (!['serial', 'parallel'].includes(forwardExecutionMode)) {
                showToast('转发执行模式无效', 'error');
                return;
            }
            if (Number.isNaN(forwardParallelWorkers) || forwardParallelWorkers < 1 || forwardParallelWorkers > 10) {
                showToast('转发并行 worker 数必须在 1-10 之间', 'error');
                return;
            }
            if (Number.isNaN(forwardAccountDelaySeconds) || forwardAccountDelaySeconds < 0 || forwardAccountDelaySeconds > 60) {
                showToast('账号间拉取间隔必须在 0-60 秒之间', 'error');
                return;
            }
            if (Number.isNaN(forwardWindowMinutes) || forwardWindowMinutes < 0 || forwardWindowMinutes > 10080) {
                showToast('转发邮件时间范围必须在 0-10080 分钟之间', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpRecipient) {
                showToast('启用 SMTP 转发时必须填写转发到邮箱', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpHost) {
                showToast('启用 SMTP 转发时必须填写 SMTP 主机', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpUsername && !smtpFromEmail) {
                showToast('至少需要填写 SMTP 用户名或发件人邮箱之一', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && (Number.isNaN(smtpPort) || smtpPort < 1 || smtpPort > 65535)) {
                showToast('SMTP 端口无效', 'error');
                return;
            }
            if (forwardChannels.includes('telegram') && !telegramBotToken) {
                showToast('启用 TG 转发时必须填写 Telegram Bot Token', 'error');
                return;
            }
            if (forwardChannels.includes('telegram') && !telegramChatId) {
                showToast('启用 TG 转发时必须填写 Telegram Chat ID', 'error');
                return;
            }
            if (forwardChannels.includes('wecom') && !wecomWebhookUrl) {
                showToast('启用企业微信转发时必须填写 Webhook 地址', 'error');
                return;
            }
            if (webdavBackupChanged) {
                if (!webdavBackupVerifyPassword) {
                    showToast('修改 WebDAV 备份设置需要输入登录密码', 'error');
                    return;
                }
                if (webdavBackupSettings.webdav_backup_enabled === 'true' && !webdavBackupSettings.webdav_backup_url) {
                    showToast('启用 WebDAV 备份时必须填写 WebDAV 目录 URL', 'error');
                    return;
                }
                if (webdavBackupSettings.webdav_backup_enabled === 'true') {
                    try {
                        const backupUrl = new URL(webdavBackupSettings.webdav_backup_url);
                        if (!['http:', 'https:'].includes(backupUrl.protocol)) {
                            showToast('WebDAV 目录 URL 必须是 http(s) 地址', 'error');
                            return;
                        }
                    } catch (error) {
                        showToast('WebDAV 目录 URL 无效', 'error');
                        return;
                    }
                }
                if (webdavBackupSettings.webdav_backup_enabled === 'true' && !webdavBackupSettings.webdav_backup_cron) {
                    showToast('请输入 WebDAV 备份 Cron 表达式', 'error');
                    return;
                }
            }

            settings.refresh_interval_days = days;
            settings.refresh_delay_seconds = delay;
            settings.use_cron_schedule = strategy === 'cron';
            settings.enable_scheduled_refresh = enableScheduled;
            settings.app_timezone = appTimeZone;
            settings.show_account_created_at = showAccountCreatedAt;
            settings.show_account_sort_order = showAccountSortOrder;
            settings.show_group_id = showGroupId;
            settings.normal_mail_local_retention_enabled = normalMailLocalRetentionEnabled;
            settings.forward_channels = forwardChannels;
            settings.forward_check_interval_seconds = forwardSeconds;
            settings.forward_check_interval_minutes = Math.max(1, Math.min(60, Math.ceil(forwardSeconds / 60)));
            settings.forward_execution_mode = forwardExecutionMode;
            settings.forward_parallel_workers = forwardParallelWorkers;
            settings.forward_account_delay_seconds = forwardAccountDelaySeconds;
            settings.forward_email_window_minutes = forwardWindowMinutes;
            settings.forward_include_junkemail = forwardIncludeJunkemail;
            settings.email_forward_recipient = smtpRecipient;
            settings.smtp_host = smtpHost;
            settings.smtp_port = Number.isNaN(smtpPort) ? 465 : smtpPort;
            settings.smtp_username = smtpUsername;
            settings.smtp_password = document.getElementById('settingsSmtpPassword').value;
            settings.smtp_provider = smtpProvider;
            settings.smtp_from_email = smtpFromEmail;
            settings.smtp_use_tls = document.getElementById('settingsSmtpUseTls').checked;
            settings.smtp_use_ssl = document.getElementById('settingsSmtpUseSsl').checked;
            settings.telegram_bot_token = telegramBotToken;
            settings.telegram_chat_id = telegramChatId;
            settings.telegram_proxy_url = telegramProxyUrl;
            settings.wecom_webhook_url = wecomWebhookUrl;

            if (webdavBackupChanged) {
                Object.assign(settings, webdavBackupSettings);
                settings.webdav_backup_verify_password = webdavBackupVerifyPassword;
            }

            if (strategy === 'cron') {
                if (!refreshCron) {
                    showToast('请输入 Cron 表达式', 'error');
                    return;
                }
                settings.refresh_cron = refreshCron;
            }

            const savedMessageCount = Number(lastNormalMailRetentionStatus?.saved_message_count || 0);
            const wasRetentionEnabled = isNormalMailLocalRetentionEnabled();
            let shouldClearNormalMailRetentionCache = false;
            if (wasRetentionEnabled && !normalMailLocalRetentionEnabled && savedMessageCount > 0) {
                const confirmed = await showConfirmModal(
                    '关闭普通邮箱本地保留将清理已保存的普通邮箱本地缓存数据。此操作不可恢复，是否继续？',
                    { title: '关闭普通邮箱本地保留', confirmText: '确认关闭并清理' }
                );
                if (!confirmed) {
                    const switchEl = document.getElementById('normalMailLocalRetentionEnabled');
                    if (switchEl) switchEl.checked = true;
                    return;
                }
                shouldClearNormalMailRetentionCache = true;
            }

            let data;
            try {
                const response = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });

                data = await response.json();
            } catch (error) {
                showToast('保存设置失败', 'error');
                return;
            }

            if (!data.success) {
                handleApiError(data, '保存设置失败');
                return;
            }

            setAppTimeZone(appTimeZone);
            setShowAccountCreatedAt(showAccountCreatedAt);
            setShowAccountSortOrder(showAccountSortOrder);
            setShowGroupId(showGroupId);
            setNormalMailLocalRetentionEnabled(normalMailLocalRetentionEnabled);
            if (wasRetentionEnabled && !normalMailLocalRetentionEnabled
                && typeof invalidateNormalMailRetentionCaches === 'function') {
                invalidateNormalMailRetentionCaches({ resetCurrentView: true });
            }
            if (shouldClearNormalMailRetentionCache) {
                try {
                    const clearResponse = await fetch('/api/settings/normal-mail-retention/clear', { method: 'POST' });
                    const clearData = await clearResponse.json();
                    if (!clearResponse.ok || !clearData.success) {
                        throw new Error(clearData.error || '启动普通邮箱本地缓存清理失败');
                    }
                    if (typeof invalidateNormalMailRetentionCaches === 'function') {
                        invalidateNormalMailRetentionCaches({ resetCurrentView: true });
                    }
                    resetNormalMailRetentionStatusPollDelay();
                    updateNormalMailRetentionStats({
                        ...(lastNormalMailRetentionStatus || {}),
                        clear_status: clearData.status || { state: 'running', message: '正在清理普通邮箱本地缓存…' }
                    });
                    scheduleNormalMailRetentionStatusPoll();
                } catch (error) {
                    showToast('设置已保存，但启动普通邮箱本地缓存清理失败', 'warning');
                }
            } else {
                await loadNormalMailRetentionStatus({ silent: true });
            }
            try {
                await loadGroups();
                await refreshVisibleAccountList(false);
            } catch (error) {
                showToast('设置已保存，但列表刷新失败，请刷新页面', 'warning');
                hideSettingsModal();
                return;
            }

            showToast('时间展示已生效，定时任务重启后生效', 'success');
            hideSettingsModal();
        }

        function buildForwardingDraftConfig() {
            const smtpPortValue = document.getElementById('settingsSmtpPort').value.trim();
            const smtpPort = parseInt(smtpPortValue || '465', 10);
            return {
                smtp: {
                    provider: document.getElementById('settingsSmtpProvider')?.value || 'custom',
                    recipient: document.getElementById('settingsEmailForwardRecipient').value.trim(),
                    host: document.getElementById('settingsSmtpHost').value.trim(),
                    port: Number.isNaN(smtpPort) ? null : smtpPort,
                    username: document.getElementById('settingsSmtpUsername').value.trim(),
                    password: document.getElementById('settingsSmtpPassword').value,
                    from_email: document.getElementById('settingsSmtpFromEmail').value.trim(),
                    use_tls: !!document.getElementById('settingsSmtpUseTls')?.checked,
                    use_ssl: !!document.getElementById('settingsSmtpUseSsl')?.checked,
                },
                telegram: {
                    bot_token: document.getElementById('settingsTelegramBotToken').value.trim(),
                    chat_id: document.getElementById('settingsTelegramChatId').value.trim(),
                    proxy_url: document.getElementById('settingsTelegramProxyUrl').value.trim(),
                },
                wecom: {
                    webhook_url: document.getElementById('settingsWecomWebhookUrl').value.trim(),
                }
            };
        }

        async function testForwardChannel(channel) {
            const btn = document.getElementById(
                channel === 'smtp'
                    ? 'testSmtpBtn'
                    : (channel === 'telegram' ? 'testTelegramBtn' : 'testWecomBtn')
            );
            if (!btn || btn.disabled) return;

            const draft = buildForwardingDraftConfig();
            if (channel === 'smtp') {
                if (!draft.smtp.recipient) {
                    showToast('请先填写 SMTP 转发到邮箱', 'error');
                    return;
                }
                if (!draft.smtp.host) {
                    showToast('请先填写 SMTP 主机', 'error');
                    return;
                }
                if (!draft.smtp.username && !draft.smtp.from_email) {
                    showToast('请至少填写 SMTP 用户名或发件人邮箱', 'error');
                    return;
                }
                if (!draft.smtp.port || draft.smtp.port < 1 || draft.smtp.port > 65535) {
                    showToast('SMTP 端口无效', 'error');
                    return;
                }
            } else if (channel === 'telegram') {
                if (!draft.telegram.bot_token) {
                    showToast('请先填写 Telegram Bot Token', 'error');
                    return;
                }
                if (!draft.telegram.chat_id) {
                    showToast('请先填写 Telegram Chat ID', 'error');
                    return;
                }
            } else if (channel === 'wecom') {
                if (!draft.wecom.webhook_url) {
                    showToast('请先填写企业微信 Webhook 地址', 'error');
                    return;
                }
            } else {
                showToast('未知转发渠道', 'error');
                return;
            }

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '发送中...';

            try {
                const response = await fetch('/api/settings/test-forward-channel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        channel,
                        config: draft
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showToast(data.message || '测试成功', 'success');
                } else {
                    handleApiError(data, '测试失败');
                }
            } catch (error) {
                showToast('测试失败', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        function formatRelativeTime(timestamp) {
            if (!timestamp) return '从未刷新';

            const now = new Date();
            let dateStr = timestamp;
            if (typeof dateStr === 'string' && !dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                dateStr = dateStr + 'Z';
            }
            const past = new Date(dateStr);
            const diffMs = now - past;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return '刚刚';
            if (diffMins < 60) return `${diffMins} 分钟前`;
            if (diffHours < 24) return `${diffHours} 小时前`;
            if (diffDays < 30) return `${diffDays} 天前`;
            return `${Math.floor(diffDays / 30)} 月前`;
        }
