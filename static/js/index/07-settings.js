        /* global accountsCache, closeAllModals, currentGroupId, currentGroupName, deleteCurrentAccount, ensureForwardingSettingsUI, getSelectedForwardChannels, groups, handleApiError, hideEditAccountModal, hideModal, hideSettingsModal, isTempEmailGroup, isTempImportGroup, loadAccountsByGroup, loadGroups, loadTempEmails, normalizeSmtpForwardProvider, refreshVisibleAccountList, setAppTimeZone, setModalVisible, setSelectedForwardChannels, setShowAccountCreatedAt, showModal, showToast, syncSmtpProviderUI, toggleRefreshStrategy, updateEditAccountFields, updateImportHint */

        // ==================== 设置相关 ====================
        let settingsScrollSyncBound = false;
        let settingsScrollSyncFrame = 0;

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
            updateImportHint();
        }

        async function addAccount() {
            const input = document.getElementById('accountInput').value.trim();
            const groupId = parseInt(document.getElementById('importGroupSelect').value);
            const provider = document.getElementById('importProviderSelect')?.value || 'outlook';
            const imapHost = document.getElementById('importImapHost')?.value.trim() || '';
            const imapPort = parseInt(document.getElementById('importImapPort')?.value || '993', 10);
            const forwardEnabled = !!document.getElementById('importForwardEnabled')?.checked;

            if (!input) {
                showToast('请输入账号信息', 'error');
                return;
            }

            const isTempGroup = isTempImportGroup();
            if (!isTempGroup && provider === 'custom' && !imapHost) {
                showToast('自定义 IMAP 必须填写服务器地址', 'error');
                return;
            }

            try {
                let response;
                if (isTempGroup) {
                    const tempProvider = document.getElementById('importChannelSelect').value || 'gptmail';
                    response = await fetch('/api/temp-emails/import', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ account_string: input, provider: tempProvider })
                    });
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
                            forward_enabled: forwardEnabled
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
                    document.getElementById('editAccountId').value = acc.id;
                    document.getElementById('editEmail').value = acc.email || '';
                    document.getElementById('editPassword').value = acc.password || '';
                    document.getElementById('editClientId').value = acc.client_id || '';
                    document.getElementById('editRefreshToken').value = acc.refresh_token || '';
                    document.getElementById('editImapPassword').value = acc.imap_password || '';
                    document.getElementById('editImapHost').value = acc.imap_host || '';
                    document.getElementById('editImapPort').value = acc.imap_port || 993;
                    document.getElementById('editGroupSelect').value = acc.group_id || 1;
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

            const data = {
                email: document.getElementById('editEmail').value.trim(),
                password: document.getElementById('editPassword').value,
                client_id: document.getElementById('editClientId').value.trim(),
                refresh_token: document.getElementById('editRefreshToken').value.trim(),
                account_type: isOutlook ? 'outlook' : 'imap',
                provider,
                imap_host: document.getElementById('editImapHost')?.value.trim() || '',
                imap_port: Number.isFinite(imapPort) ? imapPort : 993,
                imap_password: document.getElementById('editImapPassword')?.value || '',
                group_id: newGroupId,
                sort_order: Number.isFinite(sortOrder) ? Math.max(0, sortOrder) : 0,
                remark: document.getElementById('editRemark').value.trim(),
                aliases: document.getElementById('editAliases')?.value
                    .split('\n')
                    .map(item => item.trim())
                    .filter(Boolean),
                status: document.getElementById('editStatus').value,
                forward_enabled: !!document.getElementById('editForwardEnabled')?.checked
            };

            if (isOutlook) {
                if (!data.email || !data.client_id || !data.refresh_token) {
                    showToast('邮箱、Client ID 和 Refresh Token 不能为空', 'error');
                    return;
                }
            } else {
                if (!data.email || !data.imap_password) {
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
                    document.getElementById('settingsCloudflareWorkerDomain').value = data.settings.cloudflare_worker_domain || '';
                    document.getElementById('settingsCloudflareEmailDomains').value = data.settings.cloudflare_email_domains || '';
                    document.getElementById('settingsCloudflareAdminPassword').value = data.settings.cloudflare_admin_password || '';
                    document.getElementById('settingsAppTimezone').value = appTimeZone;
                    document.getElementById('settingsPassword').value = '';

                    document.getElementById('refreshIntervalDays').value = data.settings.refresh_interval_days || '30';
                    document.getElementById('refreshDelaySeconds').value = data.settings.refresh_delay_seconds || '5';
                    document.getElementById('refreshCron').value = data.settings.refresh_cron || '0 2 * * *';
                    document.getElementById('enableScheduledRefresh').checked = data.settings.enable_scheduled_refresh !== 'false';
                    document.getElementById('settingsShowAccountCreatedAt').checked = String(data.settings.show_account_created_at) !== 'false';
                    document.getElementById('forwardCheckIntervalMinutes').value = data.settings.forward_check_interval_minutes || '5';
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
                    setSelectedForwardChannels(data.settings.forward_channels || []);

                    const useCron = data.settings.use_cron_schedule === 'true';
                    document.querySelector('input[name="refreshStrategy"][value="' + (useCron ? 'cron' : 'days') + '"]').checked = true;
                    toggleRefreshStrategy();
                    syncSmtpProviderUI(false);
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
            const settings = {};
            const forwardChannels = getSelectedForwardChannels();

            if (password) {
                settings.login_password = password;
            }

            settings.gptmail_api_key = apiKey;
            settings.external_api_key = externalApiKey;
            settings.duckmail_base_url = document.getElementById('settingsDuckmailBaseUrl').value.trim();
            settings.duckmail_api_key = document.getElementById('settingsDuckmailApiKey').value.trim();
            settings.cloudflare_worker_domain = document.getElementById('settingsCloudflareWorkerDomain').value.trim();
            settings.cloudflare_email_domains = document.getElementById('settingsCloudflareEmailDomains').value.trim();
            settings.cloudflare_admin_password = document.getElementById('settingsCloudflareAdminPassword').value.trim();

            const days = parseInt(refreshDays, 10);
            const delay = parseInt(refreshDelay, 10);
            const forwardMinutes = parseInt(document.getElementById('forwardCheckIntervalMinutes').value || '5', 10);
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
            if (Number.isNaN(forwardMinutes) || forwardMinutes < 1 || forwardMinutes > 60) {
                showToast('转发轮询间隔必须在 1-60 分钟之间', 'error');
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

            settings.refresh_interval_days = days;
            settings.refresh_delay_seconds = delay;
            settings.use_cron_schedule = strategy === 'cron';
            settings.enable_scheduled_refresh = enableScheduled;
            settings.app_timezone = appTimeZone;
            settings.show_account_created_at = showAccountCreatedAt;
            settings.forward_channels = forwardChannels;
            settings.forward_check_interval_minutes = forwardMinutes;
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

            if (strategy === 'cron') {
                if (!refreshCron) {
                    showToast('请输入 Cron 表达式', 'error');
                    return;
                }
                settings.refresh_cron = refreshCron;
            }

            try {
                const response = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });

                const data = await response.json();
                if (data.success) {
                    setAppTimeZone(appTimeZone);
                    setShowAccountCreatedAt(showAccountCreatedAt);
                    await loadGroups();
                    await refreshVisibleAccountList(false);
                    showToast('时间展示已生效，定时任务重启后生效', 'success');
                    hideSettingsModal();
                } else {
                    handleApiError(data, '保存设置失败');
                }
            } catch (error) {
                showToast('保存设置失败', 'error');
            }
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
