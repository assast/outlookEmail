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
                            <h3>⚡ 生成临时邮箱</h3>
                            <button class="modal-close" onclick="hideTempEmailProviderModal()">&times;</button>
                        </div>
                        <div class="modal-body temp-email-provider-modal-body">
                            <div class="form-group">
                                <label class="form-label">选择提供商</label>
                                <div style="display: flex; gap: 12px; margin-bottom: 16px;">
                                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 10px 16px; border: 2px solid #e5e5e5; border-radius: 8px; flex: 1; transition: all 0.2s;" id="providerLabelGptmail">
                                        <input type="radio" name="tempEmailProvider" value="gptmail" checked onchange="toggleTempEmailProvider('gptmail')">
                                        <span style="font-weight: 600;">GPTMail</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 10px 16px; border: 2px solid #e5e5e5; border-radius: 8px; flex: 1; transition: all 0.2s;" id="providerLabelDuckmail">
                                        <input type="radio" name="tempEmailProvider" value="duckmail" onchange="toggleTempEmailProvider('duckmail')">
                                        <span style="font-weight: 600;">DuckMail</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 10px 16px; border: 2px solid #e5e5e5; border-radius: 8px; flex: 1; transition: all 0.2s;" id="providerLabelCloudflare">
                                        <input type="radio" name="tempEmailProvider" value="cloudflare" onchange="toggleTempEmailProvider('cloudflare')">
                                        <span style="font-weight: 600;">Cloudflare</span>
                                    </label>
                                </div>
                            </div>
                            <div id="gptmailFields">
                                <div class="form-hint" style="margin-bottom: 12px;">点击下方按钮即可一键生成 GPTMail 临时邮箱</div>
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
                                    <input type="text" class="form-input" id="duckmailUsername" placeholder="至少 3 个字符">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">密码</label>
                                    <input type="password" class="form-input" id="duckmailPassword" placeholder="至少 6 个字符">
                                    <div class="form-hint">用于登录邮箱，请牢记密码。邮件保存 3 天，账号不会自动删除</div>
                                </div>
                            </div>
                            <div id="cloudflareFields" style="display: none;">
                                <div class="form-group">
                                    <label class="form-label">数量</label>
                                    <input type="number" class="form-input" id="cloudflareGenerateCount" min="1" max="50" value="1" style="width: 100%;">
                                </div>
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
                                <div class="form-group">
                                    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
                                        <label class="form-label" style="margin-bottom: 0;">用户名（可选）</label>
                                        <button class="btn btn-secondary" type="button" id="cloudflareAiGenerateBtn" onclick="generateCloudflareAiUsernames()">AI生成</button>
                                    </div>
                                    <textarea class="form-input" id="cloudflareUsername" rows="4" placeholder="留空则随机生成；一行一个用户名" style="width: 100%; min-height: 84px; resize: vertical;"></textarea>
                                    <div class="form-hint">一行一个用户名；留空则按数量随机生成</div>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">标签</label>
                                    <div class="import-tag-options" id="cloudflareGenerateTagOptions" style="max-height: 120px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;">
                                        <div class="import-tag-empty">暂无标签</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn btn-secondary" onclick="hideTempEmailProviderModal()">取消</button>
                            <button class="btn btn-primary" id="createTempEmailBtn" onclick="doGenerateTempEmail()">✨ 创建邮箱</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            // 重置表单，使用上次保存的渠道
            const defaultProvider = localStorage.getItem('outlook_temp_email_generate') || 'gptmail';
            const radio = modal.querySelector(`input[value="${defaultProvider}"]`);
            if (radio) radio.checked = true;
            toggleTempEmailProvider(defaultProvider);
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

            if (provider === 'duckmail') {
                gptmailFields.style.display = 'none';
                duckmailFields.style.display = 'block';
                cloudflareFields.style.display = 'none';
                labelGpt.style.borderColor = '#e5e5e5';
                labelGpt.style.backgroundColor = 'transparent';
                labelDuck.style.borderColor = '#1a1a1a';
                labelDuck.style.backgroundColor = '#f8f8f8';
                labelCloudflare.style.borderColor = '#e5e5e5';
                labelCloudflare.style.backgroundColor = 'transparent';
                // 加载 DuckMail 域名
                loadDuckmailDomains();
            } else if (provider === 'cloudflare') {
                gptmailFields.style.display = 'none';
                duckmailFields.style.display = 'none';
                cloudflareFields.style.display = 'block';
                labelGpt.style.borderColor = '#e5e5e5';
                labelGpt.style.backgroundColor = 'transparent';
                labelDuck.style.borderColor = '#e5e5e5';
                labelDuck.style.backgroundColor = 'transparent';
                labelCloudflare.style.borderColor = '#1a1a1a';
                labelCloudflare.style.backgroundColor = '#f8f8f8';
                loadCloudflareChannelsForGenerate();
                ensureCloudflareGenerateTagsLoaded();
            } else {
                gptmailFields.style.display = 'block';
                duckmailFields.style.display = 'none';
                cloudflareFields.style.display = 'none';
                labelGpt.style.borderColor = '#1a1a1a';
                labelGpt.style.backgroundColor = '#f8f8f8';
                labelDuck.style.borderColor = '#e5e5e5';
                labelDuck.style.backgroundColor = 'transparent';
                labelCloudflare.style.borderColor = '#e5e5e5';
                labelCloudflare.style.backgroundColor = 'transparent';
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
                container.innerHTML = '<div class="import-tag-empty">暂无标签</div>';
                return;
            }

            container.innerHTML = tags.map(tag => `
                <label class="import-tag-option">
                    <input type="checkbox" class="cloudflare-generate-tag-checkbox" value="${escapeHtml(String(tag.id))}">
                    <span class="import-tag-dot" style="background-color: ${escapeHtml(tag.color || '#9ca3af')};"></span>
                    <span>${escapeHtml(tag.name || '')}</span>
                </label>
            `).join('');
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
