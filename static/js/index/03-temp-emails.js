        /* global accountsCache, allTags, closeMobilePanels, currentAccount, currentAccountListSource, currentEmailDetail, currentEmailId, currentEmails, currentGroupId, currentMethod, currentSkip, escapeHtml, escapeJs, formatDate, groups, handleAccountSelectionCheckboxClick, handleApiError, hasMoreEmails, isLoadingMore, loadGroups, loadTags, loadTempEmails, matchesSelectedTagFilters, refreshEmails, renderAccountTagSummary, renderEmailDetail, renderEmailList, renderEmptyStateMarkup, scheduleEmailListLoadCheck, selectedTagFilters, showEmailList, showMobileEmailDetail, showToast, updateBatchActionBar, updateMobileContext, updateCurrentGroupHeader */

        // ==================== 临时邮箱相关 ====================

        const CLOUDFLARE_GLOBAL_ACCOUNT_KEY = '__cloudflare_global_messages__';
        const CLOUDFLARE_GLOBAL_ACCOUNT_PREFIX = `${CLOUDFLARE_GLOBAL_ACCOUNT_KEY}:`;
        const CLOUDFLARE_GLOBAL_PAGE_SIZE = 50;
        let currentCloudflareGlobalChannelId = null;
        let currentCloudflareGlobalChannelName = '';

        // 加载临时邮箱列表
        async function loadTempEmails(forceRefresh = false) {
            const container = document.getElementById('accountList');

            if (!forceRefresh && accountsCache['temp']) {
                renderTempEmailList(accountsCache['temp']);
                return;
            }

            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch('/api/temp-emails');
                const data = await response.json();

                if (data.success) {
                    await loadCloudflareChannelsForTempEmails(forceRefresh);
                    accountsCache['temp'] = data.emails;
                    renderTempEmailList(data.emails);

                    const group = groups.find(g => g.name === '临时邮箱');
                    if (group) {
                        group.account_count = data.emails.length;
                        renderGroupList(groups);
                    }
                } else {
                    container.innerHTML = renderEmptyStateMarkup('⚠️', data.error || '加载失败', {
                        onAction: 'loadTempEmails(true)',
                        actionTitle: '刷新临时邮箱列表'
                    });
                }
            } catch (error) {
                container.innerHTML = renderEmptyStateMarkup('⚠️', '加载失败', {
                    onAction: 'loadTempEmails(true)',
                    actionTitle: '刷新临时邮箱列表'
                });
            }
        }

        async function loadCloudflareChannelsForTempEmails(forceRefresh = false) {
            if (!forceRefresh && Array.isArray(accountsCache.cloudflareChannels)) {
                return accountsCache.cloudflareChannels;
            }
            try {
                const response = await fetch('/api/cloudflare/channels');
                const data = await response.json();
                accountsCache.cloudflareChannels = data.success && Array.isArray(data.channels)
                    ? data.channels
                    : [];
            } catch (error) {
                accountsCache.cloudflareChannels = [];
            }
            return accountsCache.cloudflareChannels;
        }

        // 渲染临时邮箱列表
        function renderTempEmailList(emails) {
            const container = document.getElementById('accountList');
            currentAccountListSource = Array.isArray(emails) ? [...emails] : [];
            const cloudflareChannels = Array.isArray(accountsCache.cloudflareChannels)
                ? accountsCache.cloudflareChannels.filter(channel => channel.enabled)
                : [];

            // 渠道筛选
            const filter = localStorage.getItem('outlook_temp_email_filter') || 'all';
            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            const normalizedSearchQuery = searchQuery.toLowerCase();
            let filtered = filter === 'all'
                ? [...currentAccountListSource]
                : currentAccountListSource.filter(e => e.provider === filter);

            if (searchQuery) {
                filtered = filtered.filter(email => {
                    const tagText = Array.isArray(email.tags)
                        ? email.tags.map(tag => String(tag.name || '')).join('\n')
                        : '';
                    return matchesAccountSearchTerms([email.email, tagText], searchQuery);
                });
            }

            if (selectedTagFilters.size > 0) {
                filtered = filtered.filter(email => matchesSelectedTagFilters(email.tags));
            }

            const currentGroup = groups.find(group => group.id === currentGroupId);
            if (searchQuery) {
                updateCurrentGroupHeader(null, `搜索结果 (${filtered.length})`);
            } else if (currentGroup) {
                updateCurrentGroupHeader(currentGroup);
            }

            const cloudflareGlobalEntries = (filter === 'all' || filter === 'cloudflare')
                ? cloudflareChannels.filter(channel => {
                    const label = `Cloudflare所有邮件 · ${channel.name || channel.id}`;
                    return !searchQuery || label.toLowerCase().includes(normalizedSearchQuery);
                })
                : [];

            if (filtered.length === 0 && cloudflareGlobalEntries.length === 0) {
                const providerName = filter === 'duckmail' ? 'DuckMail' : (filter === 'cloudflare' ? 'Cloudflare' : 'GPTMail');
                const hasAdvancedFilters = !!searchQuery || selectedTagFilters.size > 0;
                const hint = hasAdvancedFilters
                    ? '未找到匹配的临时邮箱'
                    : (filter === 'all' ? '暂无临时邮箱<br>点击下方按钮生成' : `暂无 ${providerName} 邮箱`);
                container.innerHTML = renderEmptyStateMarkup('⚡', hint, {
                    allowHtml: !hasAdvancedFilters,
                    onAction: 'loadTempEmails(true)',
                    actionTitle: '刷新临时邮箱列表'
                });
                updateBatchActionBar();
                return;
            }

            const cloudflareGlobalEntry = cloudflareGlobalEntries.map(channel => {
                const channelId = Number(channel.id);
                const channelName = channel.name || `#${channelId}`;
                const label = `Cloudflare所有邮件 · ${channelName}`;
                const active = currentMethod === 'cloudflare-admin' && Number(currentCloudflareGlobalChannelId) === channelId;
                return `
                <div class="account-item cloudflare-global-account-item ${active ? 'active' : ''}"
                     onclick="selectCloudflareGlobalMessages(event, ${channelId}, '${escapeJs(channelName)}')">
                    <div class="account-body">
                        <div class="account-title-row">
                            <div class="account-email-wrap">
                                <div class="account-email cloudflare-global-account-title" title="${escapeHtml(label)}">${escapeHtml(label)}</div>
                            </div>
                        </div>
                        <div class="account-meta-row">
                            <span class="account-status-pill provider" style="--pill-accent: #f48120">Cloudflare</span>
                        </div>
                    </div>
                </div>
            `;
            }).join('');

            container.innerHTML = cloudflareGlobalEntry + filtered.map(email => `
                <div class="account-item ${currentAccount === email.email ? 'active' : ''}"
                     data-account-id="${email.id}"
                     onclick="handleAccountItemClick(event, '${escapeJs(email.email)}', true)">
                    <input type="checkbox" class="account-select-checkbox" value="${email.id}"
                           data-account-email="${escapeHtml(email.email)}"
                           data-account-type="temp-email"
                           data-refreshable="false"
                           data-forward-enabled="false"
                           onclick="handleAccountSelectionCheckboxClick(event)">
                    <div class="account-body">
                        <div class="account-title-row">
                            <div class="account-email-wrap">
                                <div class="account-email" title="${escapeHtml(email.email)}">${escapeHtml(email.email)}</div>
                            </div>
                        </div>
                        <div class="account-meta-row">
                            <span class="account-status-pill provider"
                                style="--pill-accent: ${email.provider === 'duckmail' ? '#ff9800' : (email.provider === 'cloudflare' ? '#f48120' : '#00bcf2')}">
                                ${escapeHtml(email.provider === 'duckmail' ? 'DuckMail' : (email.provider === 'cloudflare' ? 'Cloudflare' : 'GPTMail'))}
                            </span>
                            <span class="account-status-pill muted">临时邮箱</span>
                            ${email.provider === 'cloudflare' && email.cloudflare_channel_name ? `<span class="account-status-pill muted">${escapeHtml(email.cloudflare_channel_name)}</span>` : ''}
                        </div>
                        ${(email.tags || []).length ? `<div class="account-tags">${renderAccountTagSummary(email.tags)}</div>` : ''}
                    </div>
                    <div class="account-menu-wrap">
                        <button class="account-menu-trigger" type="button" data-account-menu-toggle="true" title="更多操作">⋯</button>
                        <div class="account-menu-panel">
                            <button class="account-action-btn" type="button" onclick="event.stopPropagation(); closeAccountActionMenus(); copyEmail('${escapeJs(email.email)}')">复制邮箱</button>
                            <button class="account-action-btn delete" type="button" onclick="event.stopPropagation(); closeAccountActionMenus(); deleteTempEmail('${escapeJs(email.email)}')">删除邮箱</button>
                        </div>
                    </div>
                </div>
            `).join('');
            updateBatchActionBar();
        }

        // 生成临时邮箱（显示提供商选择弹窗）
        async function generateTempEmail() {
            // 显示提供商选择弹窗
            showTempEmailProviderModal();
        }

        function hideTempEmailProviderModal() {
            hideModal('tempEmailProviderModal');
        }

        // 切换 Duckmail 密码可见性
        function toggleDuckmailPasswordVisibility() {
            const input = document.getElementById('duckmailPassword');
            const svg = document.getElementById('duckmailPasswordEyeIcon');
            if (!input || !svg) return;

            if (input.type === 'password') {
                input.type = 'text';
                svg.innerHTML = `
                    <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>
                    <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>
                    <path d="M6.61 6.61A13.52 13.52 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>
                    <line x1="2" y1="2" x2="22" y2="22"/>
                `;
            } else {
                input.type = 'password';
                svg.innerHTML = `
                    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
                    <circle cx="12" cy="12" r="3"/>
                `;
            }
        }

        // 切换 Cloudflare 用户名生成方式
        function toggleCloudflareUsernameMode(mode) {
            const btnRandom = document.getElementById('usernameModeRandom');
            const btnCustom = document.getElementById('usernameModeCustom');
            const groupUsername = document.getElementById('cloudflareUsernameGroup');
            const textarea = document.getElementById('cloudflareUsername');

            if (mode === 'random') {
                btnRandom?.classList.add('active');
                btnCustom?.classList.remove('active');
                if (groupUsername) groupUsername.style.display = 'none';
                if (textarea) textarea.value = '';
            } else {
                btnRandom?.classList.remove('active');
                btnCustom?.classList.add('active');
                if (groupUsername) groupUsername.style.display = 'block';
            }
        }

        // 显示提供商选择弹窗
        function showTempEmailProviderModal() {
            closeAllModals();
            // 动态创建弹窗
            let modal = document.getElementById('tempEmailProviderModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'tempEmailProviderModal';
                modal.className = 'modal';
                modal.onmousedown = function (e) { if (e.target === modal) hideTempEmailProviderModal(); };
                modal.innerHTML = `
                    <div class="modal-content temp-email-provider-modal-content">
                        <div class="modal-header">
                            <h3>生成临时邮箱</h3>
                            <button class="modal-close" onclick="hideTempEmailProviderModal()">&times;</button>
                        </div>
                        <div class="modal-body temp-email-provider-modal-body">
                            <div class="form-group">
                                <label class="form-label">选择提供商</label>
                                <div class="provider-tabs">
                                    <div class="provider-tab-item">
                                        <input type="radio" id="providerCloudflare" name="tempEmailProvider" value="cloudflare" checked onchange="toggleTempEmailProvider('cloudflare')">
                                        <label class="provider-tab-label" for="providerCloudflare" id="providerLabelCloudflare">
                                            <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
                                                <path d="M17.5 19A3.5 3.5 0 0 0 21 15.5c0-2.79-2.54-4.5-5-4.5-.48 0-.96.06-1.41.17A5.98 5.98 0 0 0 9 8c-3.12 0-5.67 2.43-5.96 5.5A4.5 4.5 0 0 0 7.5 19h10z"/>
                                            </svg>
                                            <span>Cloudflare</span>
                                        </label>
                                    </div>
                                    <div class="provider-tab-item">
                                        <input type="radio" id="providerGptmail" name="tempEmailProvider" value="gptmail" onchange="toggleTempEmailProvider('gptmail')">
                                        <label class="provider-tab-label" for="providerGptmail" id="providerLabelGptmail">
                                            <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
                                                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275Z"/>
                                                <path d="m5 3 1 2.5L8.5 6 6 7 5 9.5 4 7 1.5 6 4 5.5Z"/>
                                                <path d="m19 17 1 2.5 2.5.5-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1Z"/>
                                            </svg>
                                            <span>GPTMail</span>
                                        </label>
                                    </div>
                                    <div class="provider-tab-item">
                                        <input type="radio" id="providerDuckmail" name="tempEmailProvider" value="duckmail" onchange="toggleTempEmailProvider('duckmail')">
                                        <label class="provider-tab-label" for="providerDuckmail" id="providerLabelDuckmail">
                                            <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
                                                <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
                                                <path d="M7.5 10.5c.828 0 1.5-.672 1.5-1.5s-.672-1.5-1.5-1.5-1.5.672-1.5 1.5.672 1.5 1.5 1.5z"/>
                                                <path d="M11.5 11.5c.828 0 1.5-.672 1.5-1.5s-.672-1.5-1.5-1.5-1.5.672-1.5 1.5.672 1.5 1.5 1.5z"/>
                                                <path d="M16 14c0 1.657-2.686 3-6 3s-6-1.343-6-3"/>
                                            </svg>
                                            <span>DuckMail</span>
                                        </label>
                                    </div>
                                </div>
                            </div>
                            <div id="gptmailFields">
                                <div class="form-hint" style="margin-bottom: 12px; text-align: center; padding: 20px 0; color: #64748b;">
                                    点击下方按钮即可一键生成 GPTMail 临时邮箱
                                </div>
                            </div>
                            <div id="duckmailFields" style="display: none;">
                                <div class="form-group">
                                    <label class="form-label">域名</label>
                                    <select class="form-input" id="duckmailDomain" style="width: 100%;">
                                        <option value="">加载中...</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">用户名</label>
                                    <input type="text" class="form-input" id="duckmailUsername" placeholder="请输入用户名（至少 3 个字符）">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">密码</label>
                                    <div class="password-wrapper">
                                        <input type="password" class="form-input" id="duckmailPassword" placeholder="请输入登录密码（至少 6 个字符）">
                                        <button type="button" class="password-toggle-btn" onclick="toggleDuckmailPasswordVisibility()" title="显示/隐藏密码">
                                            <svg id="duckmailPasswordEyeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
                                                <circle cx="12" cy="12" r="3"/>
                                            </svg>
                                        </button>
                                    </div>
                                    <div class="form-hint">用于登录邮箱，请务必牢记密码。邮件保存 3 天，账号不会自动删除</div>
                                </div>
                            </div>
                            <div id="cloudflareFields" style="display: none;">
                                <div class="form-grid-2">
                                    <div class="form-group">
                                        <label class="form-label">渠道</label>
                                        <select class="form-input" id="cloudflareChannel" style="width: 100%;" onchange="loadCloudflareDomains()">
                                            <option value="">加载中...</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label class="form-label">域名</label>
                                        <select class="form-input" id="cloudflareDomain" style="width: 100%;">
                                            <option value="">加载中...</option>
                                        </select>
                                    </div>
                                </div>
                                <div class="form-grid-2">
                                    <div class="form-group">
                                        <label class="form-label">数量</label>
                                        <input type="number" class="form-input" id="cloudflareGenerateCount" min="1" max="50" value="1" style="width: 100%;">
                                    </div>
                                    <div class="form-group">
                                        <label class="form-label">生成方式</label>
                                        <div class="username-mode-selector">
                                            <button type="button" class="btn btn-secondary" id="usernameModeRandom" onclick="toggleCloudflareUsernameMode('random')">🎲 随机</button>
                                            <button type="button" class="btn btn-secondary active" id="usernameModeCustom" onclick="toggleCloudflareUsernameMode('custom')">✍️ 自定义</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="form-group" id="cloudflareUsernameGroup" style="display: block;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
                                        <label class="form-label" style="margin-bottom: 0;">用户名列表</label>
                                        <button class="btn btn-secondary btn-ai-wand" type="button" id="cloudflareAiGenerateBtn" onclick="generateCloudflareAiUsernames()">
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                <path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72Z"/>
                                                <path d="m14 7 3 3"/>
                                                <path d="M5 6v4"/>
                                                <path d="M19 14v4"/>
                                                <path d="M10 2v2"/>
                                                <path d="M7 8H3"/>
                                                <path d="M21 16h-4"/>
                                                <path d="M11 3H9"/>
                                            </svg>
                                            AI 智能生成
                                        </button>
                                    </div>
                                    <textarea class="form-input" id="cloudflareUsername" rows="2" placeholder="一行一个用户名（留空则按数量随机生成）" style="width: 100%; min-height: 48px; resize: vertical;"></textarea>
                                </div>
                                <div class="form-group" style="margin-bottom: 4px;">
                                    <label class="form-label">绑定标签</label>
                                    <div class="tag-cloud" id="cloudflareGenerateTagOptions">
                                        <div class="tag-cloud-empty">暂无标签</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn btn-secondary" onclick="hideTempEmailProviderModal()">取消</button>
                            <button class="btn btn-primary" id="createTempEmailBtn" onclick="doGenerateTempEmail()">创建邮箱</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            // 重置表单，使用上次保存的渠道
            const defaultProvider = localStorage.getItem('outlook_temp_email_generate') || 'cloudflare';
            const radio = modal.querySelector(`input[value="${defaultProvider}"]`);
            if (radio) radio.checked = true;
            toggleTempEmailProvider(defaultProvider);
            toggleCloudflareUsernameMode('custom');
            setModalVisible('tempEmailProviderModal', true);
        }

        // 切换提供商显示
        function toggleTempEmailProvider(provider) {
            // 记录用户选择
            localStorage.setItem('outlook_temp_email_generate', provider);

            const gptmailFields = document.getElementById('gptmailFields');
            const duckmailFields = document.getElementById('duckmailFields');
            const cloudflareFields = document.getElementById('cloudflareFields');
            const labelGpt = document.getElementById('providerLabelGptmail');
            const labelDuck = document.getElementById('providerLabelDuckmail');
            const labelCloudflare = document.getElementById('providerLabelCloudflare');

            labelGpt?.classList.toggle('active', provider === 'gptmail');
            labelDuck?.classList.toggle('active', provider === 'duckmail');
            labelCloudflare?.classList.toggle('active', provider === 'cloudflare');

            if (provider === 'duckmail') {
                gptmailFields.style.display = 'none';
                duckmailFields.style.display = 'block';
                cloudflareFields.style.display = 'none';
                loadDuckmailDomains();
            } else if (provider === 'cloudflare') {
                gptmailFields.style.display = 'none';
                duckmailFields.style.display = 'none';
                cloudflareFields.style.display = 'block';
                loadCloudflareChannelsForGenerate();
                ensureCloudflareGenerateTagsLoaded();
            } else {
                gptmailFields.style.display = 'block';
                duckmailFields.style.display = 'none';
                cloudflareFields.style.display = 'none';
            }
        }

        // 加载 DuckMail 域名列表
        async function loadDuckmailDomains() {
            const select = document.getElementById('duckmailDomain');
            select.innerHTML = '<option value="">加载中...</option>';
            try {
                const response = await fetch('/api/duckmail/domains');
                const data = await response.json();
                if (data.success && data.domains && data.domains.length > 0) {
                    select.innerHTML = data.domains.map(d =>
                        `<option value="${escapeHtml(d.domain)}">${escapeHtml(d.domain)}</option>`
                    ).join('');
                } else if (data.error) {
                    select.innerHTML = `<option value="">加载失败: ${escapeHtml(data.error)}</option>`;
                } else {
                    select.innerHTML = '<option value="">无可用域名</option>';
                }
            } catch (error) {
                select.innerHTML = `<option value="">加载失败: ${escapeHtml(error.message)}</option>`;
            }
        }

        async function loadCloudflareDomains() {
            const channelSelect = document.getElementById('cloudflareChannel');
            const select = document.getElementById('cloudflareDomain');
            const channelId = channelSelect?.value || '';
            if (!channelId) {
                select.innerHTML = '<option value="">请先选择渠道</option>';
                return;
            }
            select.innerHTML = '<option value="">加载中...</option>';
            try {
                const response = await fetch(`/api/cloudflare/domains?channel_id=${encodeURIComponent(channelId)}`);
                const data = await response.json();
                if (data.success && data.domains && data.domains.length > 0) {
                    select.innerHTML = data.domains.map(d =>
                        `<option value="${escapeHtml(d.domain)}">${escapeHtml(d.domain)}</option>`
                    ).join('');
                } else if (data.error) {
                    select.innerHTML = `<option value="">加载失败: ${escapeHtml(data.error)}</option>`;
                } else {
                    select.innerHTML = '<option value="">无可用域名</option>';
                }
            } catch (error) {
                select.innerHTML = `<option value="">加载失败: ${escapeHtml(error.message)}</option>`;
            }
        }

        async function loadCloudflareChannelsForGenerate() {
            const channelSelect = document.getElementById('cloudflareChannel');
            const domainSelect = document.getElementById('cloudflareDomain');
            if (!channelSelect || !domainSelect) return;

            channelSelect.innerHTML = '<option value="">加载中...</option>';
            domainSelect.innerHTML = '<option value="">请先选择渠道</option>';
            const channels = await loadCloudflareChannelsForTempEmails(true);
            const enabledChannels = channels.filter(channel => channel.enabled);
            if (enabledChannels.length === 0) {
                channelSelect.innerHTML = '<option value="">无可用渠道</option>';
                return;
            }

            channelSelect.innerHTML = enabledChannels.map(channel =>
                `<option value="${escapeHtml(String(channel.id))}">${escapeHtml(channel.name || `#${channel.id}`)}</option>`
            ).join('');
            const defaultChannel = enabledChannels.find(channel => channel.is_default) || enabledChannels[0];
            channelSelect.value = String(defaultChannel.id);
            await loadCloudflareDomains();
        }

        async function ensureCloudflareGenerateTagsLoaded() {
            const tags = typeof allTags === 'undefined' || !Array.isArray(allTags) ? [] : allTags;
            if (typeof loadTags === 'function' && tags.length === 0) {
                await loadTags();
            }
            renderCloudflareGenerateTagOptions();
        }

        function renderCloudflareGenerateTagOptions() {
            const container = document.getElementById('cloudflareGenerateTagOptions');
            if (!container) return;

            const tags = typeof allTags === 'undefined' || !Array.isArray(allTags) ? [] : allTags;
            if (!tags.length) {
                container.innerHTML = '<div class="tag-cloud-empty">暂无标签</div>';
                return;
            }

            container.innerHTML = tags.map(tag => {
                const color = tag.color || '#9ca3af';
                let bgStyle = '';
                if (color.startsWith('#')) {
                    bgStyle = `--dot-color: ${color}; --tag-bg: ${color}15; --tag-color: ${color}; --tag-border: ${color}40;`;
                } else {
                    bgStyle = `--dot-color: ${color}; --tag-bg: rgba(156, 163, 175, 0.1); --tag-color: #374151; --tag-border: #e2e8f0;`;
                }
                return `
                    <label class="tag-badge-item" style="${bgStyle}">
                        <input type="checkbox" class="cloudflare-generate-tag-checkbox" value="${escapeHtml(String(tag.id))}">
                        <span class="tag-badge-label">
                            <span class="tag-badge-dot"></span>
                            <span>${escapeHtml(tag.name || '')}</span>
                        </span>
                    </label>
                `;
            }).join('');
        }

        function getCloudflareGenerateSelectedTagIds() {
            return Array.from(document.querySelectorAll('.cloudflare-generate-tag-checkbox:checked'))
                .map(checkbox => parseInt(checkbox.value, 10))
                .filter(Number.isFinite);
        }

        function getCloudflareUsernameLines() {
            const textarea = document.getElementById('cloudflareUsername');
            return (textarea?.value || '')
                .split(/\r?\n/)
                .map(line => line.trim())
                .filter(Boolean);
        }

        async function generateCloudflareAiUsernames() {
            const btn = document.getElementById('cloudflareAiGenerateBtn');
            const textarea = document.getElementById('cloudflareUsername');
            const count = parseInt(document.getElementById('cloudflareGenerateCount')?.value || '1', 10);
            if (Number.isNaN(count) || count < 1 || count > 50) {
                showToast('数量必须在 1-50 之间', 'error');
                return;
            }
            if (!btn || !textarea) return;

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '生成中...';
            try {
                const response = await fetch('/api/cloudflare/ai-usernames/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ count })
                });
                const data = await response.json();
                if (data.success && Array.isArray(data.usernames)) {
                    textarea.value = data.usernames.join('\n');
                    showToast(`已生成 ${data.usernames.length} 个用户名`, 'success');
                } else {
                    handleApiError(data, 'AI 生成用户名失败');
                }
            } catch (error) {
                showToast('AI 生成用户名失败', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        function formatCloudflareBatchFailureSummary(failures) {
            const items = Array.isArray(failures) ? failures.slice(0, 3) : [];
            return items.map(failure => {
                const index = Number(failure.index);
                const target = Number.isFinite(index) ? `第 ${index} 个` : (failure.email || failure.username || '邮箱');
                return `${target}: ${failure.error || '创建失败'}`;
            }).join('；');
        }

        // 执行创建临时邮箱
        async function doGenerateTempEmail() {
            const provider = document.querySelector('input[name="tempEmailProvider"]:checked').value;
            const btn = document.getElementById('createTempEmailBtn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '⏳ 创建中...';

            try {
                let body = { provider };

                if (provider === 'duckmail') {
                    body.domain = document.getElementById('duckmailDomain').value;
                    body.username = document.getElementById('duckmailUsername').value.trim();
                    body.password = document.getElementById('duckmailPassword').value;

                    if (!body.domain) {
                        showToast('请选择域名', 'error');
                        return;
                    }
                    if (!body.username || body.username.length < 3) {
                        showToast('用户名至少 3 个字符', 'error');
                        return;
                    }
                    if (!body.password || body.password.length < 6) {
                        showToast('密码至少 6 个字符', 'error');
                        return;
                    }
                } else if (provider === 'cloudflare') {
                    body.channel_id = document.getElementById('cloudflareChannel').value;
                    body.domain = document.getElementById('cloudflareDomain').value;
                    body.count = parseInt(document.getElementById('cloudflareGenerateCount')?.value || '1', 10);
                    body.tag_ids = getCloudflareGenerateSelectedTagIds();
                    const usernameLines = getCloudflareUsernameLines();
                    if (usernameLines.length > 0) {
                        body.usernames = usernameLines;
                    }

                    if (!body.channel_id) {
                        showToast('请选择渠道', 'error');
                        return;
                    }
                    if (!body.domain) {
                        showToast('请选择域名', 'error');
                        return;
                    }
                    if (Number.isNaN(body.count) || body.count < 1 || body.count > 50) {
                        showToast('数量必须在 1-50 之间', 'error');
                        return;
                    }
                    if (usernameLines.length > 0 && usernameLines.length !== body.count) {
                        showToast('用户名数量必须与创建数量一致', 'error');
                        return;
                    }
                }

                const useCloudflareBatch = provider === 'cloudflare';
                const response = await fetch(useCloudflareBatch ? '/api/temp-emails/generate-batch' : '/api/temp-emails/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });

                const data = await response.json();

                if (data.success) {
                    if (useCloudflareBatch) {
                        const failedText = data.failed_count ? `，失败 ${data.failed_count} 个` : '';
                        const failureSummary = formatCloudflareBatchFailureSummary(data.failures);
                        const failureSummaryText = failureSummary ? `：${failureSummary}` : '';
                        showToast(
                            `已生成 ${data.created_count || 0} 个临时邮箱${failedText}${failureSummaryText}`,
                            data.failed_count ? 'warning' : 'success'
                        );
                    } else {
                        showToast(`临时邮箱已生成: ${data.email}`, 'success');
                    }
                    hideModal('tempEmailProviderModal');
                    delete accountsCache['temp'];
                    loadTempEmails(true);
                    loadGroups();
                } else {
                    handleApiError(data, '生成临时邮箱失败');
                }
            } catch (error) {
                showToast('生成临时邮箱失败', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        // 选择临时邮箱
        function selectTempEmail(email) {
            currentAccount = email;
            currentCloudflareGlobalChannelId = null;
            currentCloudflareGlobalChannelName = '';
            isTempEmailGroup = true;
            currentMethod = 'gptmail';
            currentEmailId = null;
            currentEmailDetail = null;
            currentSkip = 0;
            hasMoreEmails = false;

            document.getElementById('currentAccount').classList.add('show');
            document.getElementById('currentAccountEmail').textContent = email + ' (临时)';
            showEmailList();
            closeMobilePanels();
            updateMobileContext();

            document.querySelectorAll('.account-item').forEach(item => {
                item.classList.remove('active');
                const emailEl = item.querySelector('.account-email');
                if (emailEl && emailEl.textContent.includes(email)) {
                    item.classList.add('active');
                }
            });

            // 隐藏文件夹切换按钮（临时邮箱不支持文件夹）
            const folderTabs = document.getElementById('folderTabs');
            if (folderTabs) {
                folderTabs.style.display = 'none';
            }

            document.getElementById('emailList').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📬</div>
                    <div class="empty-state-text">点击"获取邮件"按钮获取邮件</div>
                </div>
            `;

            document.getElementById('emailDetail').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">选择一封邮件查看详情</div>
                </div>
            `;
            document.getElementById('emailDetailToolbar').style.display = 'none';
            document.getElementById('emailCount').textContent = '';
            document.getElementById('methodTag').style.display = 'none';
        }

        function getCloudflareGlobalAddressFilter() {
            return (localStorage.getItem(getCloudflareGlobalFilterStorageKey()) || '').trim();
        }

        function getCloudflareGlobalFilterStorageKey() {
            return `outlook_cloudflare_global_address_filter_${currentCloudflareGlobalChannelId || 'default'}`;
        }

        function renderCloudflareGlobalFilterBar() {
            const value = getCloudflareGlobalAddressFilter();
            return `
                <div class="cloudflare-global-filter">
                    <input type="text" class="cloudflare-global-filter-input" id="cloudflareGlobalAddressFilter"
                           placeholder="按收件地址过滤，例如 user@gmail.com"
                           value="${escapeHtml(value)}"
                           onkeydown="if(event.key === 'Enter') applyCloudflareGlobalFilter()">
                    <button class="cloudflare-global-filter-btn" type="button" onclick="applyCloudflareGlobalFilter()">查询</button>
                    <button class="cloudflare-global-filter-btn secondary" type="button" onclick="clearCloudflareGlobalFilter()">全部</button>
                </div>
            `;
        }

        function selectCloudflareGlobalMessages(event, channelId, channelName) {
            if (event) event.stopPropagation();
            currentCloudflareGlobalChannelId = Number(channelId) || null;
            currentCloudflareGlobalChannelName = channelName || '';
            currentAccount = `${CLOUDFLARE_GLOBAL_ACCOUNT_PREFIX}${currentCloudflareGlobalChannelId}`;
            currentMethod = 'cloudflare-admin';
            currentEmailId = null;
            currentEmailDetail = null;
            currentEmails = [];
            isTempEmailGroup = true;
            currentSkip = 0;
            hasMoreEmails = true;

            document.getElementById('currentAccount').classList.add('show');
            document.getElementById('currentAccountEmail').textContent = `Cloudflare所有邮件 · ${currentCloudflareGlobalChannelName || currentCloudflareGlobalChannelId}`;
            showEmailList();
            closeMobilePanels();
            updateMobileContext();

            document.querySelectorAll('.account-item').forEach(item => item.classList.remove('active'));
            const targetItem = event?.currentTarget;
            if (targetItem) targetItem.classList.add('active');

            const folderTabs = document.getElementById('folderTabs');
            if (folderTabs) {
                folderTabs.style.display = 'none';
            }

            document.getElementById('emailList').innerHTML = `
                ${renderCloudflareGlobalFilterBar()}
                    <div class="empty-state">
                        <div class="empty-state-icon">📬</div>
                        <div class="empty-state-text">点击"获取邮件"按钮获取当前渠道邮件</div>
                    </div>
            `;
            document.getElementById('emailDetail').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">选择一封邮件查看详情</div>
                </div>
            `;
            document.getElementById('emailDetailToolbar').style.display = 'none';
            document.getElementById('emailCount').textContent = '';
            const methodTag = document.getElementById('methodTag');
            methodTag.textContent = `Cloudflare 全部 · ${currentCloudflareGlobalChannelName || currentCloudflareGlobalChannelId}`;
            methodTag.style.display = 'inline';
            methodTag.style.backgroundColor = '#f48120';
            methodTag.style.color = 'white';
        }

        function applyCloudflareGlobalFilter() {
            const input = document.getElementById('cloudflareGlobalAddressFilter');
            localStorage.setItem(getCloudflareGlobalFilterStorageKey(), (input?.value || '').trim());
            loadCloudflareGlobalMessages();
        }

        function clearCloudflareGlobalFilter() {
            localStorage.removeItem(getCloudflareGlobalFilterStorageKey());
            const input = document.getElementById('cloudflareGlobalAddressFilter');
            if (input) input.value = '';
            loadCloudflareGlobalMessages();
        }

        function buildCloudflareGlobalMessagesParams(offset = 0) {
            const address = getCloudflareGlobalAddressFilter();
            const params = new URLSearchParams({
                channel_id: String(currentCloudflareGlobalChannelId || ''),
                limit: String(CLOUDFLARE_GLOBAL_PAGE_SIZE),
                offset: String(Math.max(0, Number(offset) || 0))
            });
            if (address) params.set('address', address);
            return params;
        }

        function updateCloudflareGlobalMethodTag(data) {
            const methodTag = document.getElementById('methodTag');
            const channelLabel = data?.channel_name || currentCloudflareGlobalChannelName || currentCloudflareGlobalChannelId || '';
            const fallbackLabel = data?.fallback_used && data?.queried_email
                ? `Cloudflare 全部 · ${channelLabel} · ${data.queried_email}`
                : `Cloudflare 全部 · ${channelLabel}`;
            methodTag.textContent = fallbackLabel;
            methodTag.style.display = 'inline';
            methodTag.style.backgroundColor = '#f48120';
            methodTag.style.color = 'white';
        }

        async function fetchCloudflareGlobalMessagesPage(offset = 0) {
            if (!currentCloudflareGlobalChannelId) {
                return { success: false, error: '请先选择 Cloudflare 渠道' };
            }
            const params = buildCloudflareGlobalMessagesParams(offset);
            const response = await fetch(`/api/cloudflare/messages?${params.toString()}`);
            return response.json();
        }

        function getCloudflareGlobalNextOffset(data, fallbackOffset = 0) {
            const responseOffset = Number(data?.offset);
            const responseLimit = Number(data?.limit);
            if (Number.isFinite(responseOffset) && Number.isFinite(responseLimit) && responseLimit > 0) {
                return responseOffset + responseLimit;
            }
            return Math.max(0, Number(fallbackOffset) || 0) + CLOUDFLARE_GLOBAL_PAGE_SIZE;
        }

        async function loadCloudflareGlobalMessages() {
            const container = document.getElementById('emailList');
            container.innerHTML = `${renderCloudflareGlobalFilterBar()}<div class="loading"><div class="loading-spinner"></div></div>`;
            currentEmailId = null;
            currentEmailDetail = null;
            currentEmails = [];
            currentMethod = 'cloudflare-admin';
            currentSkip = 0;
            hasMoreEmails = true;

            const refreshBtn = document.querySelector('.refresh-btn');
            if (refreshBtn) {
                refreshBtn.disabled = true;
                refreshBtn.textContent = '获取中...';
            }

            try {
                const data = await fetchCloudflareGlobalMessagesPage(0);

                if (data.success) {
                    currentEmails = data.emails || [];
                    hasMoreEmails = data.has_more === true;
                    currentSkip = hasMoreEmails ? getCloudflareGlobalNextOffset(data, 0) : currentEmails.length;
                    document.getElementById('emailCount').textContent = `(${currentEmails.length})`;
                    updateCloudflareGlobalMethodTag(data);

                    renderEmailList(currentEmails);
                    scheduleEmailListLoadCheck(80);
                } else {
                    hasMoreEmails = false;
                    handleApiError(data, '加载 Cloudflare所有邮件失败');
                    container.innerHTML = `${renderCloudflareGlobalFilterBar()}${renderEmptyStateMarkup('⚠️', data.error || '加载失败', {
                        onAction: 'loadCloudflareGlobalMessages()',
                        actionTitle: '刷新邮件列表'
                    })}`;
                }
            } catch (error) {
                hasMoreEmails = false;
                container.innerHTML = `${renderCloudflareGlobalFilterBar()}${renderEmptyStateMarkup('⚠️', '网络错误，请重试', {
                    onAction: 'loadCloudflareGlobalMessages()',
                    actionTitle: '刷新邮件列表'
                })}`;
            } finally {
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = '获取邮件';
                }
            }
        }

        async function loadMoreCloudflareGlobalMessages() {
            if (isLoadingMore || !hasMoreEmails) return;

            isLoadingMore = true;
            const nextOffset = Math.max(Number(currentSkip) || 0, Array.isArray(currentEmails) ? currentEmails.length : 0);
            currentSkip = nextOffset;

            const emailList = document.getElementById('emailList');
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'loading loading-small';
            loadingDiv.id = 'loadingMore';
            loadingDiv.innerHTML = '<div class="loading-spinner"></div>';
            emailList.appendChild(loadingDiv);

            const refreshBtn = document.querySelector('.refresh-btn');
            if (refreshBtn) {
                refreshBtn.disabled = true;
            }

            try {
                const data = await fetchCloudflareGlobalMessagesPage(nextOffset);

                if (!data.success) {
                    hasMoreEmails = false;
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) loadingEl.remove();
                    handleApiError(data, '加载 Cloudflare所有邮件失败');
                    return;
                }

                if (Array.isArray(data.emails) && data.emails.length > 0) {
                    currentEmails = currentEmails.concat(data.emails);
                    hasMoreEmails = data.has_more === true;
                    currentSkip = hasMoreEmails ? getCloudflareGlobalNextOffset(data, nextOffset) : currentEmails.length;

                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) loadingEl.remove();

                    document.getElementById('emailCount').textContent = `(${currentEmails.length})`;
                    updateCloudflareGlobalMethodTag(data);
                    renderEmailList(currentEmails);
                    scheduleEmailListLoadCheck(80);
                } else {
                    hasMoreEmails = false;
                    currentSkip = getCloudflareGlobalNextOffset(data, nextOffset);
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) {
                        loadingEl.innerHTML = '<div style="text-align:center;padding:20px;color:#999;font-size:13px;">没有更多邮件了</div>';
                    }
                }
            } catch (error) {
                const loadingEl = document.getElementById('loadingMore');
                if (loadingEl) loadingEl.remove();
                showToast('加载 Cloudflare所有邮件失败', 'error');
            } finally {
                isLoadingMore = false;
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                }
            }
        }

        function getCloudflareGlobalMessageDetail(messageId, index) {
            currentEmailId = messageId;
            document.querySelectorAll('.email-item').forEach((item, i) => {
                item.classList.toggle('active', i === index);
            });

            document.getElementById('emailDetailToolbar').style.display = 'flex';
            const deleteBtn = document.querySelector('#emailDetailToolbar .batch-btn.danger');
            if (deleteBtn) deleteBtn.style.display = 'none';
            showMobileEmailDetail();

            const email = currentEmails[index];
            if (!email) {
                document.getElementById('emailDetail').innerHTML = renderEmptyStateMarkup('⚠️', '邮件不存在');
                return;
            }
            currentEmailDetail = email;
            renderEmailDetail(email);
        }

        // 清空临时邮箱的所有邮件
        async function clearTempEmailMessages(email) {
            if (!(await showConfirmModal(`确定要清空临时邮箱 ${email} 的所有邮件吗？`, { title: '清空邮件', confirmText: '确认清空' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/temp-emails/${encodeURIComponent(email)}/clear`, {
                    method: 'DELETE'
                });

                const data = await response.json();

                if (data.success) {
                    showToast('邮件已清空', 'success');

                    // 如果当前选中的就是这个邮箱，清空邮件列表
                    if (currentAccount === email) {
                        currentEmails = [];
                        document.getElementById('emailCount').textContent = '(0)';
                        document.getElementById('emailList').innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">📭</div>
                                <div class="empty-state-text">收件箱为空</div>
                            </div>
                        `;
                        document.getElementById('emailDetail').innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">📄</div>
                                <div class="empty-state-text">选择一封邮件查看详情</div>
                            </div>
                        `;
                        document.getElementById('emailDetailToolbar').style.display = 'none';
                    }
                } else {
                    handleApiError(data, '清空临时邮箱失败');
                }
            } catch (error) {
                showToast('清空失败', 'error');
            }
        }

        // 删除临时邮箱
        async function deleteTempEmail(email) {
            if (!(await showConfirmModal(`确定要删除临时邮箱 ${email} 吗？\n该邮箱的所有邮件也将被删除。`, { title: '删除临时邮箱', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/temp-emails/${encodeURIComponent(email)}`, {
                    method: 'DELETE'
                });

                const data = await response.json();

                if (data.success) {
                    showToast('临时邮箱已删除', 'success');
                    delete accountsCache['temp'];

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

                    loadTempEmails(true);
                    loadGroups();
                } else {
                    handleApiError(data, '删除临时邮箱失败');
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }

        // 加载临时邮箱的邮件
        async function loadTempEmailMessages(email) {
            if (currentMethod === 'cloudflare-admin' || email === CLOUDFLARE_GLOBAL_ACCOUNT_KEY) {
                loadCloudflareGlobalMessages();
                return;
            }

            const container = document.getElementById('emailList');
            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';
            currentEmailId = null;
            currentEmailDetail = null;

            // 禁用按钮
            const refreshBtn = document.querySelector('.refresh-btn');
            if (refreshBtn) {
                refreshBtn.disabled = true;
                refreshBtn.textContent = '获取中...';
            }

            try {
                const response = await fetch(`/api/temp-emails/${encodeURIComponent(email)}/messages`);
                const data = await response.json();

                if (data.success) {
                    currentEmails = data.emails;
                    currentMethod = data.method === 'DuckMail'
                        ? 'duckmail'
                        : (data.method === 'Cloudflare' ? 'cloudflare' : 'gptmail');

                    const methodTag = document.getElementById('methodTag');
                    methodTag.textContent = data.method || 'GPTMail';
                    methodTag.style.display = 'inline';
                    methodTag.style.backgroundColor = data.method === 'DuckMail'
                        ? '#ff9800'
                        : (data.method === 'Cloudflare' ? '#f48120' : '#00bcf2');
                    methodTag.style.color = 'white';

                    document.getElementById('emailCount').textContent = `(${data.count})`;

                    renderEmailList(data.emails);
                } else {
                    handleApiError(data, '加载临时邮件失败');
                    container.innerHTML = renderEmptyStateMarkup('⚠️', data.error && data.error.message ? data.error.message : '加载失败', {
                        onAction: 'refreshEmails()',
                        actionTitle: '刷新邮件列表'
                    });
                }
            } catch (error) {
                container.innerHTML = renderEmptyStateMarkup('⚠️', '网络错误，请重试', {
                    onAction: 'refreshEmails()',
                    actionTitle: '刷新邮件列表'
                });
            } finally {
                // 启用按钮
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = '获取邮件';
                }
            }
        }

        // 获取临时邮件详情
        async function getTempEmailDetail(messageId, index) {
            if (currentMethod === 'cloudflare-admin') {
                getCloudflareGlobalMessageDetail(messageId, index);
                return;
            }

            currentEmailId = messageId;
            document.querySelectorAll('.email-item').forEach((item, i) => {
                item.classList.toggle('active', i === index);
            });

            document.getElementById('emailDetailToolbar').style.display = 'flex';
            const deleteBtn = document.querySelector('#emailDetailToolbar .batch-btn.danger');
            if (deleteBtn) deleteBtn.style.display = 'none';
            showMobileEmailDetail();

            const container = document.getElementById('emailDetail');
            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/temp-emails/${encodeURIComponent(currentAccount)}/messages/${encodeURIComponent(messageId)}`);
                const data = await response.json();

                if (data.success) {
                    renderEmailDetail(data.email);
                } else {
                    handleApiError(data, '加载邮件详情失败');
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">⚠️</div>
                            <div class="empty-state-text">${data.error && data.error.message ? data.error.message : '加载失败'}</div>
                        </div>
                    `;
                }
            } catch (error) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">⚠️</div>
                        <div class="empty-state-text">网络错误，请重试</div>
                    </div>
                `;
            }
        }
