        /* global accountsCache, closeAllModals, currentAccount, currentAccountListSource, currentEmailDetail, currentEmailId, currentEmails, currentGroupId, currentSkip, currentSortBy, currentSortOrder, deleteAccount, editingGroupId, escapeHtml, formatRelativeTime, generateTempEmail, groups, handleApiError, hasMoreEmails, hideModal, isMobileLayout, isTempEmailGroup, loadTempEmails, localStorage, openMobilePanel, renderEmptyStateMarkup, resetSelectedAccountView, selectedColor, selectedTagFilters, setModalVisible, showAddAccountModal, showGetRefreshTokenModal, showModal, showRefreshError, showTagManagementModal, showToast, suppressGroupClickUntil, tempEmailGroupId, updateCurrentGroupHeader, updateMobileContext */

        // ==================== 分组相关 ====================

        // 加载分组列表
        async function loadGroups() {
            const container = document.getElementById('groupList');
            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch('/api/groups');
                const data = await response.json();

                if (data.success) {
                    groups = data.groups;

                    // 找到临时邮箱分组
                    const tempGroup = groups.find(g => g.name === '临时邮箱');
                    if (tempGroup) {
                        tempEmailGroupId = tempGroup.id;
                    }

                    renderGroupList(data.groups);
                    updateGroupSelects();
                    if (document.getElementById('addGroupModal').classList.contains('show')) {
                        const currentSortValue = parseInt(document.getElementById('groupSortPosition')?.value || '');
                        updateGroupSortPositionOptions(editingGroupId, Number.isNaN(currentSortValue) ? null : currentSortValue);
                    }

                    // 获取本地缓存的分组 ID（如果有的话）
                    if (!currentGroupId) {
                        const savedGroupId = localStorage.getItem('outlook_last_group_id');
                        if (savedGroupId) {
                            currentGroupId = parseInt(savedGroupId);
                        } else if (groups.length > 0) {
                            // 如果没有缓存，默认选中"临时邮箱"或者首个分组
                            const tempMatch = groups.find(g => g.name === '临时邮箱');
                            currentGroupId = tempMatch ? tempMatch.id : groups[0].id;
                        }
                    }

                    // 如果有了选中的分组，高亮分组并刷新邮箱面板
                    if (currentGroupId) {
                        let group = groups.find(g => g.id === currentGroupId);
                        // 兜底：如果缓存的组已经被删了，回退到第一个组
                        if (!group && groups.length > 0) {
                            currentGroupId = groups[0].id;
                            group = groups[0];
                        }

                        if (group) {
                            selectGroup(currentGroupId);
                        }
                    }

                    updateMobileContext();
                } else {
                    container.innerHTML = renderEmptyStateMarkup('⚠️', data.error || '加载失败', {
                        onAction: 'loadGroups()',
                        actionTitle: '刷新分组列表'
                    });
                }
            } catch (error) {
                container.innerHTML = renderEmptyStateMarkup('⚠️', '加载失败', {
                    onAction: 'loadGroups()',
                    actionTitle: '刷新分组列表'
                });
                showToast('加载分组失败', 'error');
            }
        }

        // 渲染分组列表
        function renderGroupList(groups) {
            const container = document.getElementById('groupList');

            if (groups.length === 0) {
                container.innerHTML = renderEmptyStateMarkup('📁', '暂无分组', {
                    onAction: 'loadGroups()',
                    actionTitle: '刷新分组列表'
                });
                return;
            }

            container.innerHTML = groups.map(group => {
                const isSystem = group.is_system === 1 || group.name === '临时邮箱';
                const isTempGroup = group.name === '临时邮箱';
                const isDefault = group.id === 1;
                const isDragging = groupDragState.isDragging && groupDragState.groupId === group.id;
                const groupName = normalizeGroupName(group.name);
                const groupIdBadgeText = formatGroupIdBadgeText(group.id);

                return `
                    <div class="group-item ${currentGroupId === group.id ? 'active' : ''} ${isTempGroup ? 'temp-email-group' : ''} ${!isTempGroup ? 'draggable' : ''} ${isDragging ? 'dragging' : ''}"
                         data-group-id="${group.id}"
                         ${!isTempGroup ? `onpointerdown="handleGroupPointerDown(event, ${group.id})"` : ''}
                         onclick="handleGroupClick(event, ${group.id})">
                        <div class="group-row-1">
                            <div class="group-color" style="background-color: ${group.color || '#666'}"></div>
                            <span class="group-name">${escapeHtml(groupName)}${isTempGroup ? ' ⚡' : ''}</span>
                        </div>
                        <div class="group-row-2">
                            <div class="group-meta">
                                ${groupIdBadgeText ? `<span class="group-id-badge">${escapeHtml(groupIdBadgeText)}</span>` : ''}
                                <span class="group-count">${group.account_count || 0} 个邮箱</span>
                            </div>
                            <div class="group-actions">
                                ${!isSystem ? `<button class="group-action-btn" onclick="event.stopPropagation(); editGroup(${group.id})" title="编辑">✏️</button>` : ''}
                                ${!isDefault && !isSystem ? `<button class="group-action-btn" onclick="event.stopPropagation(); deleteGroup(${group.id})" title="删除">🗑️</button>` : ''}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function getMovableGroups() {
            return groups.filter(group => group.name !== '临时邮箱');
        }

        function reorderGroupData(orderIds) {
            const tempGroups = groups.filter(group => group.name === '临时邮箱');
            const movableMap = new Map(getMovableGroups().map(group => [group.id, group]));
            groups = [...tempGroups, ...orderIds.map(id => movableMap.get(id)).filter(Boolean)];
        }

        function getGroupSortPositionCount(editingId = null) {
            const movableGroups = groups.filter(group => group.name !== '临时邮箱' && group.id !== editingId);
            return movableGroups.length + 1;
        }

        function updateGroupSortPositionOptions(editingId = null, selectedPosition = null) {
            const select = document.getElementById('groupSortPosition');
            if (!select) {
                return;
            }

            const optionCount = getGroupSortPositionCount(editingId);
            let html = '';
            for (let position = 1; position <= optionCount; position += 1) {
                let label = `第 ${position} 位`;
                if (position === 1) {
                    label += '（最前）';
                } else if (position === optionCount) {
                    label += '（最后）';
                }
                html += `<option value="${position}">${label}</option>`;
            }
            select.innerHTML = html;
            select.value = String(selectedPosition || optionCount);
        }

        function handleGroupClick(event, groupId) {
            if (Date.now() < suppressGroupClickUntil || groupDragState.isDragging) {
                event.preventDefault();
                return;
            }
            selectGroup(groupId);
        }

        function resetGroupDragState() {
            if (groupDragState.pressTimer) {
                clearTimeout(groupDragState.pressTimer);
            }

            if (groupDragState.placeholderEl && groupDragState.placeholderEl.parentNode) {
                groupDragState.placeholderEl.parentNode.removeChild(groupDragState.placeholderEl);
            }

            if (groupDragState.sourceEl) {
                groupDragState.sourceEl.classList.remove('dragging');
                groupDragState.sourceEl.style.position = '';
                groupDragState.sourceEl.style.left = '';
                groupDragState.sourceEl.style.top = '';
                groupDragState.sourceEl.style.width = '';
                groupDragState.sourceEl.style.zIndex = '';
                groupDragState.sourceEl.style.pointerEvents = '';
            }

            document.body.style.userSelect = '';
            groupDragState = createGroupDragState();
        }

        function moveGroupPlaceholder(clientY) {
            const container = document.getElementById('groupList');
            const sourceEl = groupDragState.sourceEl;
            const placeholderEl = groupDragState.placeholderEl;
            if (!container || !sourceEl || !placeholderEl) {
                return;
            }

            const movableItems = Array.from(container.querySelectorAll('.group-item.draggable'))
                .filter(item => item !== sourceEl);

            const nextItem = movableItems.find(item => {
                const rect = item.getBoundingClientRect();
                return clientY < rect.top + (rect.height / 2);
            });

            if (nextItem) {
                container.insertBefore(placeholderEl, nextItem);
            } else {
                container.appendChild(placeholderEl);
            }
        }

        function autoScrollGroupList(clientY) {
            const container = document.getElementById('groupList');
            if (!container) {
                return;
            }

            const rect = container.getBoundingClientRect();
            const edgeSize = 40;
            if (clientY < rect.top + edgeSize) {
                container.scrollTop -= 12;
            } else if (clientY > rect.bottom - edgeSize) {
                container.scrollTop += 12;
            }
        }

        function startGroupDrag(clientX, clientY) {
            const sourceEl = groupDragState.sourceEl;
            if (!sourceEl || groupDragState.isDragging) {
                return;
            }

            const rect = sourceEl.getBoundingClientRect();
            const placeholderEl = document.createElement('div');
            placeholderEl.className = 'group-placeholder';
            placeholderEl.style.height = `${rect.height}px`;

            sourceEl.parentNode.insertBefore(placeholderEl, sourceEl.nextSibling);
            sourceEl.classList.add('dragging');
            sourceEl.style.position = 'fixed';
            sourceEl.style.left = `${rect.left}px`;
            sourceEl.style.top = `${rect.top}px`;
            sourceEl.style.width = `${rect.width}px`;
            sourceEl.style.zIndex = '1200';
            sourceEl.style.pointerEvents = 'none';

            groupDragState.isDragging = true;
            groupDragState.placeholderEl = placeholderEl;
            groupDragState.offsetY = clientY - rect.top;
            groupDragState.fixedLeft = rect.left;
            suppressGroupClickUntil = Date.now() + 400;
            document.body.style.userSelect = 'none';

            moveGroupPlaceholder(clientY);
        }

        function handleGroupPointerDown(event, groupId) {
            if (event.button !== undefined && event.button !== 0) {
                return;
            }
            if (event.target.closest('.group-action-btn')) {
                return;
            }

            const sourceEl = event.currentTarget;
            groupDragState = createGroupDragState();
            groupDragState.groupId = groupId;
            groupDragState.pointerId = event.pointerId;
            groupDragState.pointerType = event.pointerType || 'mouse';
            groupDragState.sourceEl = sourceEl;
            groupDragState.startX = event.clientX;
            groupDragState.startY = event.clientY;

            if (groupDragState.pointerType === 'touch') {
                groupDragState.pressTimer = window.setTimeout(() => {
                    startGroupDrag(groupDragState.startX, groupDragState.startY);
                }, 280);
            }
        }

        function handleGlobalGroupPointerMove(event) {
            if (!groupDragState.sourceEl || event.pointerId !== groupDragState.pointerId) {
                return;
            }

            const deltaX = event.clientX - groupDragState.startX;
            const deltaY = event.clientY - groupDragState.startY;
            const distance = Math.hypot(deltaX, deltaY);

            if (!groupDragState.isDragging) {
                if (groupDragState.pointerType === 'touch') {
                    if (distance > 8) {
                        resetGroupDragState();
                    }
                    return;
                }

                if (distance > 4) {
                    startGroupDrag(event.clientX, event.clientY);
                }
                return;
            }

            event.preventDefault();
            groupDragState.sourceEl.style.left = `${groupDragState.fixedLeft}px`;
            groupDragState.sourceEl.style.top = `${event.clientY - groupDragState.offsetY}px`;
            autoScrollGroupList(event.clientY);
            moveGroupPlaceholder(event.clientY);
        }

        async function finishGroupDrag() {
            const container = document.getElementById('groupList');
            const sourceEl = groupDragState.sourceEl;
            const placeholderEl = groupDragState.placeholderEl;

            if (!container || !sourceEl || !placeholderEl) {
                resetGroupDragState();
                return;
            }

            container.insertBefore(sourceEl, placeholderEl);

            const newOrder = Array.from(container.querySelectorAll('.group-item.draggable'))
                .map(item => parseInt(item.dataset.groupId));
            const previousOrder = getMovableGroups().map(group => group.id);

            resetGroupDragState();

            if (JSON.stringify(newOrder) === JSON.stringify(previousOrder)) {
                return;
            }

            reorderGroupData(newOrder);
            await persistGroupOrder(newOrder);
        }

        async function handleGlobalGroupPointerUp(event) {
            if (!groupDragState.sourceEl || event.pointerId !== groupDragState.pointerId) {
                return;
            }

            if (!groupDragState.isDragging) {
                resetGroupDragState();
                return;
            }

            suppressGroupClickUntil = Date.now() + 250;
            await finishGroupDrag();
        }

        async function persistGroupOrder(groupIds) {
            try {
                const response = await fetch('/api/groups/reorder', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        group_ids: groupIds
                    })
                });
                const data = await response.json();

                if (data.success) {
                    showToast(data.message, 'success');
                    await loadGroups();
                } else {
                    handleApiError(data, '更新分组排序失败');
                    await loadGroups();
                }
            } catch (error) {
                showToast('更新分组排序失败', 'error');
                await loadGroups();
            }
        }

        // 选择分组
        async function selectGroup(groupId) {
            if (Date.now() < suppressGroupClickUntil) {
                return;
            }

            currentGroupId = groupId;
            localStorage.setItem('outlook_last_group_id', groupId);

            // 清空搜索框
            const searchInput = document.getElementById('globalSearch');
            if (searchInput) {
                searchInput.value = '';
            }

            // 检查是否是临时邮箱分组
            const group = groups.find(g => g.id === groupId);
            isTempEmailGroup = group && group.name === '临时邮箱';

            // 更新分组列表 UI
            document.querySelectorAll('.group-item').forEach(item => {
                item.classList.toggle('active', parseInt(item.dataset.groupId) === groupId);
            });

            // 更新邮箱面板标题
            if (group) {
                updateCurrentGroupHeader(group);
                document.getElementById('currentGroupColor').style.backgroundColor = group.color || '#666';

                // 更新导入邮箱时的默认分组
                const importSelect = document.getElementById('importGroupSelect');
                if (importSelect) {
                    importSelect.value = groupId;
                }
            }
            // 临时邮箱：先应用上次保存的筛选渠道，再更新面板（按钮样式依赖 filter 值）
            if (isTempEmailGroup) {
                // 读取缓存，如果没有或者无效（被设为all），则给默认值 gptmail 
                let storedFilter = localStorage.getItem('outlook_temp_email_filter');
                if (!storedFilter || storedFilter === 'all') {
                    storedFilter = 'gptmail';
                }
                window.tempEmailProviderFilter = storedFilter;
                localStorage.setItem('outlook_temp_email_filter', storedFilter);
            }
            // 更新账号面板头部动作
            updateAccountPanelActions();
            const shouldAdvanceToAccounts = isMobileLayout()
                && document.getElementById('groupPanel')?.classList.contains('show');

            // 加载该分组的邮箱
            if (isTempEmailGroup) {
                await loadTempEmails();
            } else {
                await loadAccountsByGroup(groupId);
            }

            if (shouldAdvanceToAccounts) {
                openMobilePanel('account');
            }
            updateMobileContext();
        }

        // 更新账号面板头部动作按钮
        function updateAccountPanelActions() {
            const actions = document.querySelector('.account-panel-header-actions');
            if (!actions) return;
            if (isTempEmailGroup) {
                actions.innerHTML = `
                    <button class="panel-action-btn panel-action-btn-accent" onclick="generateTempEmail()" title="生成临时邮箱">
                        ⚡
                    </button>
                    <button class="panel-action-btn panel-action-btn-primary" onclick="showAddAccountModal()" title="导入邮箱账号">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                            <path fill-rule="evenodd"
                                d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
                        </svg>
                    </button>
                `;
                // 显示渠道筛选、隐藏排序和标签
                document.getElementById('tempEmailProviderFilter').style.display = 'flex';
                document.querySelector('.sort-control').style.display = 'none';
                document.getElementById('tagFilterContainer').style.display = 'none';
                // 同步筛选按钮样式
                const currentFilter = localStorage.getItem('outlook_temp_email_filter') || 'all';
                document.querySelectorAll('.provider-filter-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.provider === currentFilter);
                });
            } else {
                actions.innerHTML = `
                    <button class="panel-action-btn" onclick="showTagManagementModal()" title="管理标签">
                        🏷️
                    </button>
                    <button class="panel-action-btn panel-action-btn-accent" onclick="showGetRefreshTokenModal()" title="授权并保存 Outlook 账号">
                        🔑
                    </button>
                    <button class="panel-action-btn panel-action-btn-primary" onclick="showAddAccountModal()" title="导入邮箱账号">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                            <path fill-rule="evenodd"
                                d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
                        </svg>
                    </button>
                `;
                // 隐藏渠道筛选、显示排序、恢复标签筛选
                document.getElementById('tempEmailProviderFilter').style.display = 'none';
                document.querySelector('.sort-control').style.display = 'flex';
                updateTagFilter();
            }
        }

        // 筛选临时邮箱渠道（点击已激活的按钮取消筛选）
        function filterTempEmailByProvider(provider) {
            if (provider === 'all') {
                localStorage.setItem('outlook_temp_email_filter', 'all');
            } else if (localStorage.getItem('outlook_temp_email_filter') === provider) {
                // 点击已激活的按钮取消筛选（显示全部）
                localStorage.setItem('outlook_temp_email_filter', 'all');
            } else {
                localStorage.setItem('outlook_temp_email_filter', provider);
            }

            // 更新按钮样式
            const currentFilter = localStorage.getItem('outlook_temp_email_filter') || 'all';
            document.querySelectorAll('.provider-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.provider === currentFilter);
            });
            if (accountsCache['temp']) {
                renderTempEmailList(accountsCache['temp']);
            }
        }

        // 加载分组下的账号
        async function loadAccountsByGroup(groupId, forceRefresh = false) {
            const container = document.getElementById('accountList');

            // 如果有缓存且不强制刷新，直接使用缓存
            if (!forceRefresh && accountsCache[groupId]) {
                renderFilteredAccountList(accountsCache[groupId]);
                return;
            }

            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/accounts?group_id=${groupId}`);
                const data = await response.json();

                if (data.success) {
                    // 缓存数据
                    accountsCache[groupId] = data.accounts;
                    renderFilteredAccountList(data.accounts);
                } else {
                    container.innerHTML = renderEmptyStateMarkup('⚠️', data.error || '加载失败', {
                        onAction: `loadAccountsByGroup(${Number(groupId)}, true)`,
                        actionTitle: '刷新账号列表'
                    });
                }
            } catch (error) {
                container.innerHTML = renderEmptyStateMarkup('⚠️', '加载失败', {
                    onAction: `loadAccountsByGroup(${Number(groupId)}, true)`,
                    actionTitle: '刷新账号列表'
                });
            }
        }

        function showForwardStatusLabel(enabled) {
            return enabled
                ? '<span class="account-status-pill success" title="已开启转发">转</span>'
                : '';
        }

        function renderAccountTagSummary(tags) {
            const safeTags = Array.isArray(tags) ? tags : [];
            const visibleTags = safeTags.slice(0, 2);
            const hiddenCount = Math.max(0, safeTags.length - visibleTags.length);

            let html = visibleTags.map(tag => `
                <span class="account-status-pill tag" style="--pill-accent: ${tag.color}">
                    ${escapeHtml(tag.name)}
                </span>
            `).join('');

            if (hiddenCount > 0) {
                html += `<span class="account-status-pill outline">+${hiddenCount}</span>`;
            }

            return html;
        }

        function renderAccountAliasSummary(aliases) {
            const safeAliases = Array.isArray(aliases) ? aliases.filter(Boolean) : [];
            if (!safeAliases.length) return '';

            const visibleAliases = safeAliases.slice(0, 2);
            const hiddenCount = Math.max(0, safeAliases.length - visibleAliases.length);
            const aliasText = visibleAliases.join(' / ');
            const suffix = hiddenCount > 0 ? ` +${hiddenCount}` : '';
            return `<div class="account-aliases" title="${escapeHtml(safeAliases.join('\n'))}">别名: ${escapeHtml(aliasText)}${suffix}</div>`;
        }

        function renderAccountGroupSummary(account, showGroupInfo = false) {
            if (!showGroupInfo) return '';

            const groupColor = account.group_color || '#666666';
            const groupName = normalizeGroupName(account.group_name, '默认分组');
            const groupIdBadgeText = formatGroupIdBadgeText(account.group_id);
            return `
                <div class="account-group-summary" title="所属分组: ${escapeHtml(groupName)}">
                    <span class="account-group-dot" style="background-color: ${escapeHtml(groupColor)}"></span>
                    <span class="account-group-name">${escapeHtml(groupName)}</span>
                    ${groupIdBadgeText ? `<span class="group-id-badge account-group-id-badge">${escapeHtml(groupIdBadgeText)}</span>` : ''}
                </div>
            `;
        }

        function isAccountRowInteractiveTarget(target) {
            if (!target || typeof target.closest !== 'function') {
                return false;
            }
            return !!target.closest(
                '.account-menu-wrap, .account-action-btn, .account-menu-trigger, .account-menu-panel, .account-select-checkbox, .account-error-btn, button, input, a'
            );
        }

        function handleAccountItemClick(event, email, isTemp = false) {
            if (isAccountRowInteractiveTarget(event?.target)) {
                return;
            }
            if (isTemp) {
                selectTempEmail(email);
            } else {
                selectAccount(email);
            }
        }

        // 渲染邮箱列表
        function renderAccountList(accounts) {
            const container = document.getElementById('accountList');
            const isSearchMode = !!(document.getElementById('globalSearch')?.value || '').trim();
            const normalizedGroupId = Number(currentGroupId);
            const refreshAction = Number.isFinite(normalizedGroupId) && normalizedGroupId > 0
                ? `loadAccountsByGroup(${normalizedGroupId}, true)`
                : '';

            if (accounts.length === 0) {
                container.innerHTML = isSearchMode
                    ? renderEmptyStateMarkup('📭', '未找到匹配邮箱')
                    : renderEmptyStateMarkup('📭', '该分组暂无邮箱', {
                        onAction: refreshAction,
                        actionTitle: '刷新账号列表'
                    });
                updateBatchActionBar();
                return;
            }

            container.innerHTML = accounts.map((acc, index) => `
                <div class="account-item ${currentAccount === acc.email ? 'active' : ''} ${acc.status === 'inactive' ? 'inactive' : ''}"
                     onclick="handleAccountItemClick(event, '${escapeJs(acc.email)}')">
                    <input type="checkbox" class="account-select-checkbox" value="${acc.id}" 
                           data-account-email="${escapeHtml(acc.email)}"
                           data-account-type="${escapeHtml(acc.account_type || 'outlook')}"
                           data-refreshable="${acc.account_type !== 'imap' ? 'true' : 'false'}"
                           data-forward-enabled="${acc.forward_enabled ? 'true' : 'false'}"
                           onclick="event.stopPropagation(); updateBatchActionBar()">
                    <div class="account-body">
                        <div class="account-title-row">
                            <div class="account-email-wrap">
                                <span class="account-email-index">${index + 1}.</span>
                                <div class="account-email" title="${escapeHtml(acc.email)}" style="${acc.last_refresh_status === 'failed' ? 'color: #b42318;' : ''}">
                                    ${escapeHtml(acc.email)}
                                </div>
                            </div>
                        </div>
                        <div class="account-meta-row">
                            <span class="account-status-pill provider"
                                style="--pill-accent: ${acc.account_type === 'imap' ? '#0ea5e9' : '#2563eb'}">
                                ${escapeHtml(getProviderLabel(acc.provider || (acc.account_type === 'imap' ? 'custom' : 'outlook')))}
                            </span>
                            ${showForwardStatusLabel(!!acc.forward_enabled)}
                            ${acc.status === 'inactive' ? '<span class="account-status-pill muted">已停用</span>' : ''}
                            ${acc.last_refresh_status === 'failed' ? '<span class="account-status-pill danger">刷新失败</span>' : ''}
                        </div>
                        ${renderAccountGroupSummary(acc, isSearchMode)}
                        ${renderAccountAliasSummary(acc.aliases)}
                        ${acc.remark && acc.remark.trim() ? `<div class="account-remark" title="${escapeHtml(acc.remark)}">${escapeHtml(acc.remark)}</div>` : ''}
                        ${(acc.tags || []).length ? `<div class="account-tags">${renderAccountTagSummary(acc.tags)}</div>` : ''}
                        <div class="account-refresh-row">
                            <span class="account-refresh-meta ${acc.last_refresh_status === 'failed' ? 'failed' : ''}">
                                ${formatRelativeTime(acc.last_refresh_at)}
                            </span>
                            ${acc.last_refresh_status === 'failed' ? '<button class="account-error-btn" onclick="event.stopPropagation(); showRefreshError(' + acc.id + ', \'' + escapeJs(acc.last_refresh_error || '未知错误') + '\', \'' + escapeJs(acc.email) + '\')">查看错误</button>' : ''}
                        </div>
                    </div>
                    <div class="account-menu-wrap">
                        <button class="account-menu-trigger" type="button" data-account-menu-toggle="true" title="更多操作">⋯</button>
                        <div class="account-menu-panel">
                            <button class="account-action-btn" type="button" data-account-action="copy" data-account-email="${escapeHtml(acc.email)}">复制邮箱</button>
                            <button class="account-action-btn" type="button" data-account-action="forwardingLogs" data-account-id="${acc.id}" data-account-email="${escapeHtml(acc.email)}">转发日志</button>
                            <button class="account-action-btn" type="button" data-account-action="toggleStatus" data-account-id="${acc.id}" data-account-status="${escapeHtml(acc.status || 'active')}">${acc.status === 'inactive' ? '启用账号' : '停用账号'}</button>
                            <button class="account-action-btn" type="button" data-account-action="edit" data-account-id="${acc.id}">编辑账号</button>
                            <button class="account-action-btn delete" type="button" data-account-action="delete" data-account-id="${acc.id}" data-account-email="${escapeHtml(acc.email)}">删除账号</button>
                        </div>
                    </div>
                </div>
            `).join('');
            updateBatchActionBar();
        }

        // 排序相关变量
        let currentSortBy = 'refresh_time';
        let currentSortOrder = 'asc';
        let suppressGroupClickUntil = 0;
        function createGroupDragState() {
            return {
                groupId: null,
                pointerId: null,
                pointerType: 'mouse',
                sourceEl: null,
                placeholderEl: null,
                pressTimer: null,
                isDragging: false,
                startX: 0,
                startY: 0,
                offsetY: 0,
                fixedLeft: 0
            };
        }
        let groupDragState = createGroupDragState();

        // 排序账号列表
        function sortAccounts(sortBy) {
            // 如果点击同一个排序按钮，切换排序顺序
            if (currentSortBy === sortBy) {
                currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                currentSortBy = sortBy;
                currentSortOrder = sortBy === 'refresh_time' ? 'asc' : 'asc';
            }

            // 更新按钮状态
            document.querySelectorAll('.sort-btn').forEach(btn => {
                btn.classList.remove('active');
                btn.style.backgroundColor = '#ffffff';
                btn.style.color = '#666';
                btn.style.borderColor = '#e5e5e5';
            });

            const activeBtn = document.querySelector(`[data-sort="${sortBy}"]`);
            if (activeBtn) {
                activeBtn.classList.add('active');
                activeBtn.style.backgroundColor = '#1a1a1a';
                activeBtn.style.color = '#ffffff';
                activeBtn.style.borderColor = '#1a1a1a';
            }

            // 重新加载并排序账号列表
            if (currentAccountListSource.length) {
                renderFilteredAccountList(currentAccountListSource);
            }
        }

        function renderFilteredAccountList(accounts) {
            currentAccountListSource = Array.isArray(accounts) ? [...accounts] : [];
            const filteredAccounts = applyFiltersAndSort(currentAccountListSource);
            renderAccountList(filteredAccounts);

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery) {
                updateCurrentGroupHeader(null, `搜索结果 (${filteredAccounts.length})`);
            }
        }

        function refreshVisibleAccountList(forceRefresh = false) {
            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery) {
                return searchAccounts(searchQuery);
            }
            if (currentGroupId && !isTempEmailGroup) {
                return loadAccountsByGroup(currentGroupId, forceRefresh);
            }
            return Promise.resolve();
        }

        function invalidateAccountCaches() {
            Object.keys(accountsCache).forEach(key => {
                if (key !== 'temp') {
                    delete accountsCache[key];
                }
            });
        }

        function resetSelectedAccountView() {
            currentAccount = null;
            currentEmailId = null;
            currentEmailDetail = null;
            currentEmails = [];
            currentSkip = 0;
            hasMoreEmails = true;

            document.getElementById('currentAccount').classList.remove('show');
            document.getElementById('currentAccountEmail').textContent = '';
            document.getElementById('emailCount').textContent = '';
            document.getElementById('methodTag').style.display = 'none';
            document.getElementById('folderTabs').style.display = 'none';
            document.getElementById('emailDetailToolbar').style.display = 'none';
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

        function resetSelectedAccountViewIfDeleted(deletedEmails) {
            const emailSet = new Set((deletedEmails || []).map(email => String(email || '').toLowerCase()));
            if (currentAccount && emailSet.has(String(currentAccount).toLowerCase())) {
                resetSelectedAccountView();
            }
        }

        // 应用筛选和排序
        function applyFiltersAndSort(accounts) {
            let result = [...accounts];

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim().toLowerCase();

            if (searchQuery) {
                result = result.filter(acc => {
                    const aliasText = Array.isArray(acc.aliases) ? acc.aliases.join('\n').toLowerCase() : '';
                    const tagText = Array.isArray(acc.tags) ? acc.tags.map(tag => String(tag.name || '')).join('\n').toLowerCase() : '';
                    const remarkText = String(acc.remark || '').toLowerCase();
                    const emailText = String(acc.email || '').toLowerCase();
                    return emailText.includes(searchQuery)
                        || aliasText.includes(searchQuery)
                        || remarkText.includes(searchQuery)
                        || tagText.includes(searchQuery);
                });
            }

            // 1. Tag 筛选
            const selectedTagIds = Array.from(selectedTagFilters);
            if (selectedTagIds.length > 0) {
                result = result.filter(acc => {
                    if (!acc.tags) return false;
                    return acc.tags.some(t => selectedTagIds.includes(t.id));
                });
            }

            // 2. 排序
            return result.sort((a, b) => {
                if (currentSortBy === 'refresh_time') {
                    const timeA = a.last_refresh_at ? new Date(a.last_refresh_at) : new Date(0);
                    const timeB = b.last_refresh_at ? new Date(b.last_refresh_at) : new Date(0);
                    return currentSortOrder === 'asc' ? timeA - timeB : timeB - timeA;
                } else {
                    const emailA = a.email.toLowerCase();
                    const emailB = b.email.toLowerCase();
                    return currentSortOrder === 'asc'
                        ? emailA.localeCompare(emailB)
                        : emailB.localeCompare(emailA);
                }
            });
        }

        // Tag Filter Change Handler
        function handleTagFilterChange() {
            const selected = document.querySelectorAll('.tag-filter-checkbox:checked');
            selectedTagFilters = new Set(
                Array.from(selected)
                    .map(cb => parseInt(cb.value, 10))
                    .filter(Number.isFinite)
            );
            document.querySelectorAll('.tag-filter-option').forEach(option => {
                const checkbox = option.querySelector('.tag-filter-checkbox');
                option.classList.toggle('is-checked', !!checkbox?.checked);
            });
            updateTagFilterSummary();
            if (currentAccountListSource.length) {
                renderFilteredAccountList(currentAccountListSource);
            } else if (currentGroupId && !isTempEmailGroup) {
                loadAccountsByGroup(currentGroupId);
            }
        }

        // 防抖函数
        function debounce(func, wait) {
            let timeout;
            return function (...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        }

        // 全局搜索函数
        async function searchAccounts(query) {
            const container = document.getElementById('accountList');

            if (!query.trim()) {
                const currentGroup = groups.find(group => group.id === currentGroupId);
                updateCurrentGroupHeader(currentGroup);
                currentAccountListSource = [];
                if (isTempEmailGroup) {
                    loadTempEmails();
                } else {
                    loadAccountsByGroup(currentGroupId);
                }
                return;
            }

            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/accounts/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();

                if (data.success) {
                    renderFilteredAccountList(data.accounts);
                } else {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-text">搜索失败</div></div>';
                }
            } catch (error) {
                console.error('搜索失败:', error);
                container.innerHTML = '<div class="empty-state"><div class="empty-state-text">搜索失败，请重试</div></div>';
            }
        }

        // 更新分组下拉选择框
        function updateGroupSelects() {
            const selects = ['importGroupSelect', 'editGroupSelect', 'tokenSaveGroupSelect'];
            selects.forEach(selectId => {
                const select = document.getElementById(selectId);
                if (select) {
                    const currentValue = select.value;
                    // editGroupSelect 和 tokenSaveGroupSelect 过滤掉临时邮箱分组
                    const filteredGroups = (selectId === 'editGroupSelect' || selectId === 'tokenSaveGroupSelect')
                        ? groups.filter(g => g.name !== '临时邮箱')
                        : groups;

                    select.innerHTML = filteredGroups.map(g =>
                        `<option value="${g.id}">${escapeHtml(normalizeGroupName(g.name))}</option>`
                    ).join('');
                    // 恢复之前的选择
                    if (currentValue && filteredGroups.find(g => g.id === parseInt(currentValue))) {
                        select.value = currentValue;
                    } else if (selectId === 'tokenSaveGroupSelect') {
                        const preferredGroupId = (!isTempEmailGroup && currentGroupId && filteredGroups.find(g => g.id === currentGroupId))
                            ? currentGroupId
                            : (filteredGroups[0]?.id || '');
                        if (preferredGroupId) {
                            select.value = preferredGroupId;
                        }
                    } else if (currentGroupId && filteredGroups.find(g => g.id === currentGroupId)) {
                        select.value = currentGroupId;
                    }
                }
            });

            // 绑定导入分组切换事件，动态更新提示
            const importSelect = document.getElementById('importGroupSelect');
            if (importSelect) {
                importSelect.onchange = function () {
                    updateImportHint();
                };
            }
        }

        // 显示添加分组模态框
        const MAIL_PROVIDER_LABELS = {
            outlook: 'Outlook',
            gmail: 'Gmail',
            qq: 'QQ',
            '163': '163',
            '126': '126',
            yahoo: 'Yahoo',
            aliyun: 'Aliyun',
            '2925': '2925邮箱',
            custom: 'Custom IMAP'
        };

        function getProviderLabel(provider) {
            return MAIL_PROVIDER_LABELS[provider] || (provider || 'Outlook');
        }

        function isTempImportGroup() {
            const importSelect = document.getElementById('importGroupSelect');
            const selectedGroup = groups.find(g => g.id === parseInt(importSelect?.value || '0'));
            return !!(selectedGroup && selectedGroup.name === '临时邮箱');
        }

        function normalizeForwardChannels(rawChannels) {
            const aliases = {
                email: 'smtp',
                smtp: 'smtp',
                tg: 'telegram',
                telegram: 'telegram',
                wecom: 'wecom',
                wechatwork: 'wecom',
                qywx: 'wecom'
            };
            const values = Array.isArray(rawChannels)
                ? rawChannels
                : String(rawChannels || '').split(',');

            return [...new Set(
                values
                    .map(channel => aliases[String(channel || '').trim().toLowerCase()])
                    .filter(Boolean)
            )];
        }

        function getSelectedForwardChannels() {
            const checkboxMap = {
                smtp: 'forwardChannelSmtp',
                telegram: 'forwardChannelTelegram',
                wecom: 'forwardChannelWecom',
            };
            return Object.keys(checkboxMap).filter(channel =>
                document.getElementById(checkboxMap[channel])?.checked
            );
        }

        function setSelectedForwardChannels(rawChannels) {
            const channels = normalizeForwardChannels(rawChannels);
            const smtpCheckbox = document.getElementById('forwardChannelSmtp');
            const telegramCheckbox = document.getElementById('forwardChannelTelegram');
            const wecomCheckbox = document.getElementById('forwardChannelWecom');
            if (smtpCheckbox) smtpCheckbox.checked = channels.includes('smtp');
            if (telegramCheckbox) telegramCheckbox.checked = channels.includes('telegram');
            if (wecomCheckbox) wecomCheckbox.checked = channels.includes('wecom');
            syncForwardChannelUI();
        }

        function syncForwardChannelUI() {
            const selectedChannels = new Set(getSelectedForwardChannels());

            document.querySelectorAll('#forwardChannelPicker .forward-channel-option').forEach(option => {
                const input = option.querySelector('input');
                option.classList.toggle('is-selected', !!input?.checked);
            });

            document.querySelectorAll('#forwardChannelPanels .forward-channel-panel').forEach(panel => {
                const channel = panel.dataset.channel;
                panel.hidden = !selectedChannels.has(channel);
            });

            const emptyState = document.getElementById('forwardChannelEmptyState');
            if (emptyState) {
                emptyState.hidden = selectedChannels.size > 0;
            }
        }

        const SMTP_FORWARD_PROVIDER_OPTIONS = ['outlook', 'qq', '163', '126', 'yahoo', 'aliyun', 'custom'];

        function normalizeSmtpForwardProvider(value) {
            const provider = String(value || '').trim().toLowerCase();
            return SMTP_FORWARD_PROVIDER_OPTIONS.includes(provider) ? provider : 'custom';
        }

        const SMTP_PROVIDER_PRESETS = {
            outlook: { host: 'smtp-mail.outlook.com', port: '587', useTls: true, useSsl: false, hint: 'Outlook 推荐使用 SMTP + STARTTLS（587）。' },
            qq: { host: 'smtp.qq.com', port: '465', useTls: false, useSsl: true, hint: 'QQ 邮箱通常使用 SMTP 授权码，默认 SSL 465。' },
            '163': { host: 'smtp.163.com', port: '465', useTls: false, useSsl: true, hint: '163 邮箱通常使用 SMTP 授权码，默认 SSL 465。' },
            '126': { host: 'smtp.126.com', port: '465', useTls: false, useSsl: true, hint: '126 邮箱通常使用 SMTP 授权码，默认 SSL 465。' },
            yahoo: { host: 'smtp.mail.yahoo.com', port: '465', useTls: false, useSsl: true, hint: 'Yahoo 默认 SSL 465。' },
            aliyun: { host: 'smtp.aliyun.com', port: '465', useTls: false, useSsl: true, hint: '阿里邮箱默认 SSL 465。' },
            custom: { host: '', port: '465', useTls: false, useSsl: true, hint: '自定义模式下，请手动填写 SMTP 主机、端口和连接方式。' }
        };

        function ensureForwardingSettingsUI() {
            if (!document.getElementById('forwardingSettingsSection')) return;
            syncForwardChannelUI();
            syncSmtpProviderUI(false);
        }

        function syncSmtpProviderUI(applyPreset = false) {
            const providerSelect = document.getElementById('settingsSmtpProvider');
            const hostInput = document.getElementById('settingsSmtpHost');
            const portInput = document.getElementById('settingsSmtpPort');
            const useTlsInput = document.getElementById('settingsSmtpUseTls');
            const useSslInput = document.getElementById('settingsSmtpUseSsl');
            const providerHint = document.getElementById('settingsSmtpProviderHint');
            const fromHint = document.getElementById('settingsSmtpFromEmailHint');
            if (!providerSelect || !hostInput || !portInput || !useTlsInput || !useSslInput || !providerHint || !fromHint) return;

            const provider = normalizeSmtpForwardProvider(providerSelect.value || 'custom');
            providerSelect.value = provider;
            const preset = SMTP_PROVIDER_PRESETS[provider] || SMTP_PROVIDER_PRESETS.custom;

            if (applyPreset) {
                hostInput.value = preset.host;
                portInput.value = preset.port;
                useTlsInput.checked = !!preset.useTls;
                useSslInput.checked = !!preset.useSsl;
            }

            providerHint.textContent = preset.hint;
            fromHint.textContent = '可选。留空时默认使用 SMTP 用户名作为发件人邮箱。';
        }

        function updateEditAccountFields() {
            const provider = document.getElementById('editProviderSelect')?.value || 'outlook';
            const isOutlook = provider === 'outlook';
            const passwordGroup = document.getElementById('editPassword')?.closest('.form-group');
            const clientIdGroup = document.getElementById('editClientId')?.closest('.form-group');
            const refreshTokenGroup = document.getElementById('editRefreshToken')?.closest('.form-group');
            const imapFields = document.getElementById('editImapFields');
            const customImapFields = document.getElementById('editCustomImapFields');

            if (passwordGroup) passwordGroup.style.display = isOutlook ? '' : 'none';
            if (clientIdGroup) clientIdGroup.style.display = isOutlook ? '' : 'none';
            if (refreshTokenGroup) refreshTokenGroup.style.display = isOutlook ? '' : 'none';
            if (imapFields) imapFields.style.display = isOutlook ? 'none' : '';
            if (customImapFields) customImapFields.style.display = provider === 'custom' ? '' : 'none';
        }

        function updateImportHint() {
            const hintEl = document.getElementById('importFormatHint');
            const inputEl = document.getElementById('accountInput');
            const channelGroup = document.getElementById('importChannelGroup');
            const channelSelect = document.getElementById('importChannelSelect');
            const providerGroup = document.getElementById('importProviderGroup');
            const providerSelect = document.getElementById('importProviderSelect');
            const exampleEl = document.getElementById('importFormatExample');
            const customImapSettings = document.getElementById('customImapSettings');
            const customHost = document.getElementById('importImapHost');
            const customPort = document.getElementById('importImapPort');
            if (!hintEl || !inputEl) return;

            const isTempGroup = isTempImportGroup();
            if (channelGroup) channelGroup.style.display = isTempGroup ? '' : 'none';
            if (providerGroup) providerGroup.style.display = isTempGroup ? 'none' : '';

            if (isTempGroup) {
                if (customImapSettings) customImapSettings.style.display = 'none';
                const channel = channelSelect ? channelSelect.value : 'gptmail';
                if (channel === 'duckmail') {
                    hintEl.textContent = '格式：邮箱----密码，每行一个。';
                    inputEl.placeholder = '邮箱----密码';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\\nuser@duck.com----mypassword\\nuser2@duck.com----password2';
                    }
                    return;
                }
                if (channel === 'cloudflare') {
                    hintEl.textContent = '格式：邮箱----JWT，每行一个。';
                    inputEl.placeholder = '邮箱----JWT';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\\nuser@example.com----eyJhbGciOi...';
                    }
                    return;
                }
                hintEl.textContent = '格式：每行一个邮箱地址。';
                inputEl.placeholder = '每行一个邮箱地址';
                if (exampleEl) {
                    exampleEl.style.display = '';
                    exampleEl.textContent = '示例：\\nuser1@gptmail.com\\nuser2@gptmail.com';
                }
                return;
            }

            const provider = providerSelect ? providerSelect.value : 'outlook';
            const isOutlook = provider === 'outlook';
            if (customImapSettings) customImapSettings.style.display = provider === 'custom' ? '' : 'none';
            if (exampleEl) exampleEl.style.display = '';

            if (isOutlook) {
                hintEl.textContent = 'Outlook 支持两种格式并自动识别：邮箱----密码----client_id----refresh_token 或 邮箱----密码----refresh_token----client_id。';
                inputEl.placeholder = '邮箱----密码----client_id----refresh_token';
                if (exampleEl) {
                    exampleEl.textContent = '示例：\\nuser@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA...\\nuser@outlook.com----password123----0.AXEA...----24d9a0ed-8787-4584-883c-2fd79308940a';
                }
                return;
            }

            if (provider === 'custom') {
                hintEl.textContent = '格式：邮箱----IMAP密码。也支持兼容格式：邮箱----IMAP密码----imap_host----imap_port。';
                inputEl.placeholder = '邮箱----IMAP密码';
                if (exampleEl) {
                    const host = customHost?.value?.trim() || 'imap.example.com';
                    const port = customPort?.value?.trim() || '993';
                    exampleEl.textContent = `示例：\\nuser@example.com----app-password\\nuser@example.com----app-password----${host}----${port}`;
                }
                return;
            }

            hintEl.textContent = `格式：邮箱----IMAP授权码/应用密码，每行一个。当前类型：${getProviderLabel(provider)}。`;
            inputEl.placeholder = '邮箱----IMAP授权码/应用密码';
            if (exampleEl) {
                exampleEl.textContent = '示例：\\nuser@gmail.com----app-password\\nuser2@qq.com----imap-auth-code';
            }
        }

        function showAddGroupModal() {
            closeAllModals();
            editingGroupId = null;
            document.getElementById('groupModalTitle').textContent = '添加分组';
            document.getElementById('groupName').value = '';
            document.getElementById('groupDescription').value = '';
            updateGroupSortPositionOptions();
            selectedColor = '#1a1a1a';
            document.querySelectorAll('.color-option').forEach(o => {
                o.classList.toggle('selected', o.dataset.color === selectedColor);
            });
            document.getElementById('customColorInput').value = selectedColor;
            document.getElementById('customColorHex').value = selectedColor;
            document.getElementById('groupProxyUrl').value = '';
            document.getElementById('groupFallbackProxyUrl1').value = '';
            document.getElementById('groupFallbackProxyUrl2').value = '';
            setModalVisible('addGroupModal', true);
        }

        // 隐藏添加分组模态框
        function hideAddGroupModal() {
            hideModal('addGroupModal');
        }

        // 编辑分组
        async function editGroup(groupId) {
            try {
                const response = await fetch(`/api/groups/${groupId}`);
                const data = await response.json();

                if (data.success) {
                    editingGroupId = groupId;
                    document.getElementById('groupModalTitle').textContent = '编辑分组';
                    document.getElementById('groupName').value = data.group.name;
                    document.getElementById('groupDescription').value = data.group.description || '';
                    updateGroupSortPositionOptions(groupId, data.group.sort_position);
                    selectedColor = data.group.color || '#1a1a1a';

                    // 检查是否是预设颜色
                    let isPresetColor = false;
                    document.querySelectorAll('.color-option').forEach(o => {
                        if (o.dataset.color === selectedColor) {
                            o.classList.add('selected');
                            isPresetColor = true;
                        } else {
                            o.classList.remove('selected');
                        }
                    });

                    // 更新自定义颜色输入框
                    document.getElementById('customColorInput').value = selectedColor;
                    document.getElementById('customColorHex').value = selectedColor;

                    // 填充代理设置
                    document.getElementById('groupProxyUrl').value = data.group.proxy_url || '';
                    document.getElementById('groupFallbackProxyUrl1').value = data.group.fallback_proxy_url_1 || '';
                    document.getElementById('groupFallbackProxyUrl2').value = data.group.fallback_proxy_url_2 || '';

                    showModal('addGroupModal');
                }
            } catch (error) {
                showToast('加载分组信息失败', 'error');
            }
        }

        // 保存分组
        async function saveGroup() {
            const name = document.getElementById('groupName').value.trim();
            const description = document.getElementById('groupDescription').value.trim();
            const sortPosition = parseInt(document.getElementById('groupSortPosition').value);

            if (!name) {
                showToast('请输入分组名称', 'error');
                return;
            }

            try {
                const url = editingGroupId ? `/api/groups/${editingGroupId}` : '/api/groups';
                const method = editingGroupId ? 'PUT' : 'POST';

                const response = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        description,
                        color: selectedColor,
                        proxy_url: document.getElementById('groupProxyUrl').value.trim(),
                        fallback_proxy_url_1: document.getElementById('groupFallbackProxyUrl1').value.trim(),
                        fallback_proxy_url_2: document.getElementById('groupFallbackProxyUrl2').value.trim(),
                        sort_position: sortPosition
                    })
                });

                const data = await response.json();

                if (data.success) {
                    showToast(data.message, 'success');
                    hideAddGroupModal();
                    loadGroups();
                } else {
                    handleApiError(data, '保存分组失败');
                }
            } catch (error) {
                showToast('保存失败', 'error');
            }
        }

        // 删除分组
        async function deleteGroup(groupId) {
            if (!(await showConfirmModal('确定要删除该分组吗？分组下的邮箱将移至默认分组。', { title: '删除分组', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast(data.message, 'success');
                    // 清除缓存
                    delete accountsCache[groupId];
                    // 如果删除的是当前选中的分组，切换到默认分组
                    if (currentGroupId === groupId) {
                        currentGroupId = 1;
                        localStorage.setItem('outlook_last_group_id', 1);
                    }
                    loadGroups();
                } else {
                    handleApiError(data, '删除分组失败');
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }
