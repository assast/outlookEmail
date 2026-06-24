        /* global ACCOUNT_LIST_DEFAULT_PAGE_SIZE, ACCOUNT_LIST_MAX_PAGE_SIZE, accountListPageSize, accountListRequestSeq, accountPaginationState, accountSelectionMode, accountsCache, closeAllModals, currentAccount, currentAccountListSource, currentEmailDetail, currentEmailId, currentEmails, currentGroupId, currentSkip, currentSortBy, currentSortOrder, deleteAccount, editingGroupId, escapeHtml, formatAbsoluteDateTime, generateTempEmail, groups, handleAccountRowSelectionClick, handleAccountSelectionCheckboxClick, handleApiError, hasMoreEmails, hideModal, isMobileLayout, isTempEmailGroup, loadCloudflareChannelsForImport, loadTempEmails, localStorage, matchesSelectedTagFilters, normalizeTagFilterSelectionValue, openMobilePanel, renderEmptyStateMarkup, renderTempEmailList, resetSelectedAccountView, selectedColor, selectedTagFilters, setModalVisible, shouldShowAccountCreatedAt, shouldShowAccountSortOrder, showAddAccountModal, showGetRefreshTokenModal, showModal, showRefreshError, showTagManagementModal, showToast, suppressGroupClickUntil, tempEmailGroupId, toggleAccountSelectionMode, updateCurrentGroupHeader, updateMobileContext */

        // ==================== 分组相关 ====================

        const ACCOUNT_SEARCH_MAX_TERMS = 200;
        const GROUP_COLLAPSED_STORAGE_PREFIX = 'outlook_group_collapsed_';
        let groupTree = [];

        function normalizeGroupLevel(group) {
            const level = Number(group?.level || 1);
            return Math.max(1, Math.min(3, Number.isFinite(level) ? level : 1));
        }

        function normalizeGroupParentId(value) {
            const parentId = Number(value);
            return Number.isFinite(parentId) && parentId > 0 ? parentId : null;
        }

        function isSystemGroup(group) {
            return !!(group && (group.is_system === 1 || group.name === '临时邮箱'));
        }

        function getGroupById(groupId) {
            return groups.find(group => Number(group.id) === Number(groupId)) || null;
        }

        function sortGroupsForTree(left, right) {
            if (left.name === '临时邮箱' && right.name !== '临时邮箱') return -1;
            if (right.name === '临时邮箱' && left.name !== '临时邮箱') return 1;
            const leftOrder = Number(left.sort_order || 0);
            const rightOrder = Number(right.sort_order || 0);
            if (leftOrder !== rightOrder) return leftOrder - rightOrder;
            return Number(left.id) - Number(right.id);
        }

        function buildGroupTree(flatGroups) {
            const nodeMap = new Map();
            (flatGroups || []).forEach(group => {
                nodeMap.set(Number(group.id), { ...group, children: [] });
            });

            const roots = [];
            nodeMap.forEach(node => {
                const parentId = normalizeGroupParentId(node.parent_id);
                const parent = parentId ? nodeMap.get(parentId) : null;
                if (parent) {
                    parent.children.push(node);
                } else {
                    roots.push(node);
                }
            });

            function sortNodeChildren(nodes) {
                nodes.sort(sortGroupsForTree);
                nodes.forEach(node => sortNodeChildren(node.children));
            }

            sortNodeChildren(roots);
            return roots;
        }

        function flattenGroupTree(nodes = groupTree) {
            const result = [];
            function visit(nodeList) {
                nodeList.forEach(node => {
                    result.push(node);
                    if (node.children?.length) {
                        visit(node.children);
                    }
                });
            }
            visit(nodes || []);
            return result;
        }

        function getGroupChildren(groupId) {
            return groups
                .filter(group => normalizeGroupParentId(group.parent_id) === Number(groupId))
                .sort(sortGroupsForTree);
        }

        function getGroupDescendantIds(groupId) {
            const result = [];
            function visit(currentId) {
                getGroupChildren(currentId).forEach(child => {
                    result.push(Number(child.id));
                    visit(Number(child.id));
                });
            }
            visit(Number(groupId));
            return result;
        }

        function getGroupSubtreeDepth(groupId) {
            const children = getGroupChildren(groupId);
            if (!children.length) {
                return 1;
            }
            return 1 + Math.max(...children.map(child => getGroupSubtreeDepth(Number(child.id))));
        }

        function isGroupCollapsed(groupId) {
            return localStorage.getItem(`${GROUP_COLLAPSED_STORAGE_PREFIX}${groupId}`) === '1';
        }

        function setGroupCollapsed(groupId, collapsed) {
            const key = `${GROUP_COLLAPSED_STORAGE_PREFIX}${groupId}`;
            if (collapsed) {
                localStorage.setItem(key, '1');
            } else {
                localStorage.removeItem(key);
            }
        }

        function expandAncestors(groupId) {
            let changed = false;
            let current = getGroupById(groupId);
            const visited = new Set();
            while (current && normalizeGroupParentId(current.parent_id) && !visited.has(Number(current.id))) {
                visited.add(Number(current.id));
                const parentId = normalizeGroupParentId(current.parent_id);
                if (isGroupCollapsed(parentId)) {
                    setGroupCollapsed(parentId, false);
                    changed = true;
                }
                current = getGroupById(parentId);
            }
            return changed;
        }

        function toggleGroupCollapsed(event, groupId) {
            event.stopPropagation();
            setGroupCollapsed(groupId, !isGroupCollapsed(groupId));
            renderGroupList(groups);
        }

        function canMoveGroupToParent(groupId, targetParentId) {
            const source = getGroupById(groupId);
            if (!source || isSystemGroup(source) || Number(source.id) === 1) {
                return false;
            }
            const normalizedTargetParentId = normalizeGroupParentId(targetParentId);
            if (!normalizedTargetParentId) {
                return true;
            }
            if (Number(groupId) === normalizedTargetParentId) {
                return false;
            }
            const targetParent = getGroupById(normalizedTargetParentId);
            if (!targetParent || isSystemGroup(targetParent) || normalizeGroupLevel(targetParent) >= 3) {
                return false;
            }
            if (getGroupDescendantIds(groupId).includes(normalizedTargetParentId)) {
                return false;
            }
            return normalizeGroupLevel(targetParent) + getGroupSubtreeDepth(groupId) <= 3;
        }

        function getSiblingGroupIds(parentId, excludeGroupId = null) {
            const normalizedParentId = normalizeGroupParentId(parentId);
            return groups
                .filter(group => {
                    if (isSystemGroup(group)) return false;
                    if (Number(group.id) === 1) return false;
                    if (excludeGroupId !== null && Number(group.id) === Number(excludeGroupId)) return false;
                    return normalizeGroupParentId(group.parent_id) === normalizedParentId;
                })
                .sort(sortGroupsForTree)
                .map(group => Number(group.id));
        }

        function isLastChild(group) {
            const parentId = normalizeGroupParentId(group.parent_id);
            const siblings = groups
                .filter(g => !isSystemGroup(g) && Number(g.id) !== 1 && normalizeGroupParentId(g.parent_id) === parentId)
                .sort(sortGroupsForTree);
            if (siblings.length === 0) return true;
            return Number(siblings[siblings.length - 1].id) === Number(group.id);
        }

        function getGroupOptionLabel(group) {
            if (isSystemGroup(group) || Number(group.id) === 1) {
                return normalizeGroupName(group.name);
            }

            const level = normalizeGroupLevel(group);
            if (level === 1) {
                return normalizeGroupName(group.name);
            }

            let prefix = '';
            if (level === 3) {
                const parent = getGroupById(group.parent_id);
                if (parent) {
                    if (isLastChild(parent)) {
                        prefix += '\u00A0\u00A0\u00A0';
                    } else {
                        prefix += '│\u00A0\u00A0';
                    }
                }
            }

            if (isLastChild(group)) {
                prefix += '└─\u00A0';
            } else {
                prefix += '├─\u00A0';
            }

            return `${prefix}${normalizeGroupName(group.name)}`;
        }

        function renderGroupOptions({ includeTemp = true, placeholder = '' } = {}) {
            const optionGroups = flattenGroupTree(groupTree).filter(group => includeTemp || !isSystemGroup(group));
            const options = optionGroups.map(group =>
                `<option value="${group.id}">${escapeHtml(getGroupOptionLabel(group))}</option>`
            );
            if (placeholder) {
                options.unshift(`<option value="">${escapeHtml(placeholder)}</option>`);
            }
            return options.join('');
        }

        // 加载分组列表
        async function loadGroups() {
            const container = document.getElementById('groupList');
            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch('/api/groups');
                const data = await response.json();

                if (data.success) {
                    groups = data.groups;
                    groupTree = buildGroupTree(groups);

                    // 找到临时邮箱分组
                    const tempGroup = groups.find(g => g.name === '临时邮箱');
                    if (tempGroup) {
                        tempEmailGroupId = tempGroup.id;
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

                    if (currentGroupId) {
                        expandAncestors(currentGroupId);
                    }

                    renderGroupList(data.groups);
                    updateGroupSelects();
                    if (document.getElementById('addGroupModal').classList.contains('show')) {
                        const currentSortValue = parseInt(document.getElementById('groupSortPosition')?.value || '');
                        const parentId = normalizeGroupParentId(document.getElementById('groupParentSelect')?.value);
                        updateParentGroupSelect(parentId, editingGroupId);
                        updateGroupSortPositionOptions(editingGroupId, Number.isNaN(currentSortValue) ? null : currentSortValue, parentId);
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
        function renderGroupList(flatGroups) {
            const container = document.getElementById('groupList');
            const sourceGroups = Array.isArray(flatGroups) ? flatGroups : groups;

            groupTree = buildGroupTree(sourceGroups);
            if (!sourceGroups.length) {
                container.innerHTML = renderEmptyStateMarkup('📁', '暂无分组', {
                    onAction: 'loadGroups()',
                    actionTitle: '刷新分组列表'
                });
                return;
            }

            container.innerHTML = renderGroupTree(groupTree);
        }

        function renderGroupTree(nodes) {
            return nodes.map(group => {
                const isSystem = isSystemGroup(group);
                const isTempGroup = group.name === '临时邮箱';
                const isDefault = group.id === 1;
                const isMovable = !isSystem && !isDefault;
                const isDragging = groupDragState.isDragging && groupDragState.groupId === group.id;
                const level = normalizeGroupLevel(group);
                const hasChildren = Array.isArray(group.children) && group.children.length > 0;
                const collapsed = hasChildren && isGroupCollapsed(group.id);
                const groupName = normalizeGroupName(group.name);
                const groupIdBadgeText = formatGroupIdBadgeText(group.id);
                const count = group.descendant_account_count ?? group.account_count ?? 0;

                return `
                    <div class="group-item level-${level} ${currentGroupId === group.id ? 'active' : ''} ${isTempGroup ? 'temp-email-group' : ''} ${isMovable ? 'draggable' : ''} ${isDragging ? 'dragging' : ''}"
                          data-group-id="${group.id}"
                          data-parent-id="${normalizeGroupParentId(group.parent_id) || ''}"
                          data-level="${level}"
                          ${isMovable ? `onpointerdown="handleGroupPointerDown(event, ${group.id})"` : ''}
                          onclick="handleGroupClick(event, ${group.id})">
                        <div class="group-row-1">
                            ${hasChildren && !isTempGroup ? `<button type="button" class="group-toggle ${collapsed ? 'collapsed' : ''}" onclick="toggleGroupCollapsed(event, ${group.id})" title="${collapsed ? '展开' : '折叠'}">▾</button>` : '<span class="group-toggle-spacer"></span>'}
                            <div class="group-color" style="background-color: ${group.color || '#666'}"></div>
                            <span class="group-name">${escapeHtml(groupName)}${isTempGroup ? ' ⚡' : ''}</span>
                            <span class="group-count">${count || 0}</span>
                            <div class="group-actions">
                                ${!isSystem ? `<button class="group-action-btn" onclick="event.stopPropagation(); editGroup(${group.id})" title="编辑">✏️</button>` : ''}
                                ${!isDefault && !isSystem ? `<button class="group-action-btn" onclick="event.stopPropagation(); deleteGroup(${group.id})" title="删除">🗑️</button>` : ''}
                            </div>
                        </div>
                        ${groupIdBadgeText ? `
                        <div class="group-row-2">
                            <div class="group-meta">
                                <span class="group-id-badge">${escapeHtml(groupIdBadgeText)}</span>
                            </div>
                        </div>
                        ` : ''}
                    </div>
                    ${hasChildren && !collapsed ? renderGroupTree(group.children) : ''}
                `;
            }).join('');
        }

        function getMovableGroups() {
            return groups.filter(group => !isSystemGroup(group) && Number(group.id) !== 1);
        }

        function reorderGroupData(orderIds, parentId = null) {
            const orderMap = new Map(orderIds.map((id, index) => [Number(id), index + 1]));
            groups = groups.map(group => {
                if (normalizeGroupParentId(group.parent_id) !== normalizeGroupParentId(parentId) || !orderMap.has(Number(group.id))) {
                    return group;
                }
                return { ...group, sort_order: orderMap.get(Number(group.id)) };
            });
            groupTree = buildGroupTree(groups);
        }

        function getGroupSortPositionCount(editingId = null, parentId = null) {
            const normalizedParentId = normalizeGroupParentId(parentId);
            const movableGroups = groups.filter(group =>
                !isSystemGroup(group)
                && Number(group.id) !== 1
                && Number(group.id) !== Number(editingId)
                && normalizeGroupParentId(group.parent_id) === normalizedParentId
            );
            return movableGroups.length + 1;
        }

        function updateGroupSortPositionOptions(editingId = null, selectedPosition = null, parentId = null) {
            const select = document.getElementById('groupSortPosition');
            if (!select) {
                return;
            }

            const optionCount = getGroupSortPositionCount(editingId, parentId);
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

            document.querySelectorAll('.group-item.drop-target, .group-item.drop-rejected').forEach(item => {
                item.classList.remove('drop-target', 'drop-rejected');
            });

            document.body.style.userSelect = '';
            groupDragState = createGroupDragState();
        }

        function getDragTargetItem(clientY) {
            const container = document.getElementById('groupList');
            const sourceEl = groupDragState.sourceEl;
            if (!container || !sourceEl) {
                return null;
            }
            return Array.from(container.querySelectorAll('.group-item.draggable'))
                .filter(item => item !== sourceEl);
        }

        function findClosestGroupItem(clientY) {
            const items = getDragTargetItem(clientY);
            if (!items?.length) {
                return null;
            }
            return items.find(item => {
                const rect = item.getBoundingClientRect();
                return clientY >= rect.top && clientY <= rect.bottom;
            }) || items.find(item => {
                const rect = item.getBoundingClientRect();
                return clientY < rect.top + (rect.height / 2);
            }) || items[items.length - 1];
        }

        function moveGroupPlaceholder(clientY) {
            const container = document.getElementById('groupList');
            const sourceEl = groupDragState.sourceEl;
            const placeholderEl = groupDragState.placeholderEl;
            if (!container || !sourceEl || !placeholderEl) {
                return;
            }

            document.querySelectorAll('.group-item.drop-target, .group-item.drop-rejected').forEach(item => {
                item.classList.remove('drop-target', 'drop-rejected');
            });

            const targetItem = findClosestGroupItem(clientY);
            if (!targetItem) {
                return;
            }

            const targetGroupId = Number(targetItem.dataset.groupId);
            const targetGroup = getGroupById(targetGroupId);
            const rect = targetItem.getBoundingClientRect();

            const relativeY = clientY - rect.top;
            const height = rect.height;
            const canNest = canMoveGroupToParent(groupDragState.groupId, targetGroupId);

            let isNestZone = false;
            let insertAfter = false;

            if (canNest) {
                if (relativeY >= height * 0.2 && relativeY <= height * 0.8) {
                    isNestZone = true;
                } else {
                    insertAfter = relativeY > height * 0.5;
                }
            } else {
                insertAfter = relativeY > height * 0.5;
            }

            if (isNestZone) {
                targetItem.classList.add('drop-target');
                placeholderEl.style.display = 'none';
                groupDragState.targetMode = 'move';
                groupDragState.targetGroupId = targetGroupId;
                groupDragState.targetParentId = targetGroupId;
                groupDragState.dropAllowed = true;
                return;
            }

            const targetParentId = normalizeGroupParentId(targetGroup?.parent_id);
            const sourceParentId = normalizeGroupParentId(getGroupById(groupDragState.groupId)?.parent_id);
            if (sourceParentId !== targetParentId) {
                targetItem.classList.add('drop-rejected');
                placeholderEl.style.display = 'none';
                groupDragState.targetMode = 'sort';
                groupDragState.targetGroupId = targetGroupId;
                groupDragState.targetParentId = targetParentId;
                groupDragState.dropAllowed = false;
                return;
            }

            placeholderEl.style.display = '';
            if (insertAfter) {
                targetItem.parentNode.insertBefore(placeholderEl, targetItem.nextSibling);
            } else {
                targetItem.parentNode.insertBefore(placeholderEl, targetItem);
            }

            groupDragState.targetMode = 'sort';
            groupDragState.targetGroupId = targetGroupId;
            groupDragState.targetParentId = targetParentId;
            groupDragState.insertAfter = insertAfter;
            groupDragState.dropAllowed = true;
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
            if (event.target.closest('.group-action-btn, .group-toggle')) {
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
            if (!groupDragState.sourceEl) {
                resetGroupDragState();
                return;
            }

            const sourceGroupId = Number(groupDragState.groupId);
            const targetMode = groupDragState.targetMode;
            const targetGroupId = Number(groupDragState.targetGroupId);
            const targetParentId = normalizeGroupParentId(groupDragState.targetParentId);
            const insertAfter = !!groupDragState.insertAfter;
            const dropAllowed = groupDragState.dropAllowed !== false;

            resetGroupDragState();

            if (!dropAllowed) {
                showToast(targetMode === 'move' ? '移动后层级深度将超过 3 级' : '只能在同父级内排序', 'error');
                return;
            }

            if (targetMode === 'move') {
                await persistGroupMove(sourceGroupId, targetGroupId);
                return;
            }

            if (targetMode !== 'sort' || !targetGroupId) {
                return;
            }

            const newOrder = getSiblingGroupIds(targetParentId, sourceGroupId);
            const targetIndex = newOrder.indexOf(targetGroupId);
            if (targetIndex === -1) {
                return;
            }
            newOrder.splice(targetIndex + (insertAfter ? 1 : 0), 0, sourceGroupId);

            const previousOrder = getSiblingGroupIds(targetParentId);
            if (JSON.stringify(newOrder) === JSON.stringify(previousOrder)) {
                return;
            }

            reorderGroupData(newOrder, targetParentId);
            await persistGroupOrder(newOrder, targetParentId);
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

        async function persistGroupOrder(groupIds, parentId = null) {
            try {
                const response = await fetch('/api/groups/reorder', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        group_ids: groupIds,
                        parent_id: parentId
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

        async function persistGroupMove(groupId, parentId) {
            const group = getGroupById(groupId);
            if (!group) {
                return;
            }

            try {
                const response = await fetch(`/api/groups/${groupId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: group.name,
                        description: group.description || '',
                        color: group.color || '#1a1a1a',
                        proxy_url: group.proxy_url || '',
                        fallback_proxy_url_1: group.fallback_proxy_url_1 || '',
                        fallback_proxy_url_2: group.fallback_proxy_url_2 || '',
                        parent_id: parentId,
                        sort_position: null
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showToast(data.message || '分组已移动', 'success');
                } else {
                    handleApiError(data, '移动分组失败');
                }
                await loadGroups();
            } catch (error) {
                showToast('移动分组失败', 'error');
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

            const expandedAncestors = expandAncestors(groupId);

            // 更新分组列表 UI
            if (expandedAncestors) {
                renderGroupList(groups);
            } else {
                document.querySelectorAll('.group-item').forEach(item => {
                    item.classList.toggle('active', parseInt(item.dataset.groupId) === groupId);
                });
            }

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
        function renderAccountSelectionModeButton() {
            const activeClass = accountSelectionMode ? ' active' : '';
            const title = accountSelectionMode ? '退出批量选择' : '批量选择';
            return `
                <button class="panel-action-btn account-selection-mode-btn${activeClass}" id="accountSelectionModeBtn"
                        onclick="toggleAccountSelectionMode()" title="${title}" aria-pressed="${accountSelectionMode ? 'true' : 'false'}">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="2" width="12" height="12" rx="2"></rect>
                        <path d="M5 8l2 2 4-4"></path>
                    </svg>
                </button>
            `;
        }

        function renderAccountMinimalModeButton() {
            const isMinimal = localStorage.getItem('outlook_account_list_minimal') === 'true';
            const activeClass = isMinimal ? ' active' : '';
            const title = isMinimal ? '切换详细展示' : '切换极简展示';
            return `
                <button class="panel-action-btn${activeClass}" id="accountMinimalBtn" onclick="toggleAccountMinimalMode()" title="${title}" aria-pressed="${isMinimal ? 'true' : 'false'}">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="2.5" width="12" height="2.5" rx="0.5"></rect>
                        <rect x="2" y="6.75" width="12" height="2.5" rx="0.5"></rect>
                        <rect x="2" y="11" width="12" height="2.5" rx="0.5"></rect>
                    </svg>
                </button>
            `;
        }

        function updateAccountPanelActions() {
            const actions = document.querySelector('.account-panel-header-actions');
            const searchInput = document.getElementById('globalSearch');
            if (!actions) return;
            if (isTempEmailGroup) {
                actions.innerHTML = `
                    ${renderAccountSelectionModeButton()}
                    <button class="panel-action-btn" onclick="showTagManagementModal()" title="管理标签">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M7 1.5h6v6L6.5 14 2 9.5 7 1.5z"></path>
                            <circle cx="9.5" cy="5" r="1.2" fill="currentColor"></circle>
                        </svg>
                    </button>
                    ${renderAccountMinimalModeButton()}
                    <button class="panel-action-btn panel-action-btn-accent" onclick="generateTempEmail()" title="生成临时邮箱">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <polygon points="9 1 2 9 8 9 7 15 14 7 8 7 9 1"></polygon>
                        </svg>
                    </button>
                    <button class="panel-action-btn panel-action-btn-primary" onclick="showAddAccountModal()" title="导入邮箱账号">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                            <path fill-rule="evenodd"
                                d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
                        </svg>
                    </button>
                `;
                // 显示渠道筛选、隐藏排序
                document.getElementById('tempEmailProviderFilter').style.display = 'flex';
                document.querySelector('.sort-control').style.display = 'none';
                document.getElementById('accountPageSizeContainer').style.display = 'none';
                syncAccountSearchScopeVisibility();
                updateTagFilter();
                // 同步筛选按钮样式
                const currentFilter = localStorage.getItem('outlook_temp_email_filter') || 'all';
                document.querySelectorAll('.provider-filter-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.provider === currentFilter);
                });
                if (searchInput) {
                    searchInput.placeholder = '搜索临时邮箱地址或标签...';
                }
            } else {
                actions.innerHTML = `
                    ${renderAccountSelectionModeButton()}
                    <button class="panel-action-btn" onclick="showTagManagementModal()" title="管理标签">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M7 1.5h6v6L6.5 14 2 9.5 7 1.5z"></path>
                            <circle cx="9.5" cy="5" r="1.2" fill="currentColor"></circle>
                        </svg>
                    </button>
                    ${renderAccountMinimalModeButton()}
                    <button class="panel-action-btn panel-action-btn-accent" onclick="showGetRefreshTokenModal()" title="授权并保存 Outlook 账号">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="5.5" cy="10.5" r="3.5"></circle>
                            <path d="M8 8l5-5M13 3h2v2M11 5h2v2"></path>
                        </svg>
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
                document.getElementById('accountPageSizeContainer').style.display = 'flex';
                syncAccountSearchScopeVisibility();
                syncAccountPageSizeSelect();
                updateTagFilter();
                if (searchInput) {
                    searchInput.placeholder = '邮箱|别名|备注|标签';
                }
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

        function getAccountTagFilterParams() {
            const values = Array.from(selectedTagFilters || []);
            const tagIds = values
                .filter(value => !isUntaggedTagFilterValue(value))
                .map(value => normalizeTagFilterSelectionValue(value))
                .filter(value => Number.isFinite(value) && value > 0);
            const includeUntagged = values.some(value => isUntaggedTagFilterValue(value));
            return { tagIds, includeUntagged };
        }

        function hasAccountServerSideFilters() {
            const filters = getAccountTagFilterParams();
            return filters.tagIds.length > 0 || filters.includeUntagged;
        }

        function normalizeAccountPageSize(value) {
            const parsed = parseInt(value, 10);
            if (!Number.isFinite(parsed)) {
                return ACCOUNT_LIST_DEFAULT_PAGE_SIZE;
            }
            return Math.max(1, Math.min(parsed, ACCOUNT_LIST_MAX_PAGE_SIZE));
        }

        function getAccountPageSize() {
            accountListPageSize = normalizeAccountPageSize(accountListPageSize);
            return accountListPageSize;
        }

        function syncAccountPageSizeSelect() {
            const select = document.getElementById('accountPageSizeSelect');
            if (select) {
                const hasMatchingOption = Array.from(select.options)
                    .some(option => option.value === String(getAccountPageSize()));
                if (!hasMatchingOption) {
                    accountListPageSize = ACCOUNT_LIST_DEFAULT_PAGE_SIZE;
                    localStorage.setItem('outlook_account_page_size', String(accountListPageSize));
                }
                select.value = String(getAccountPageSize());
            }
        }

        function initAccountPageSizeSelect() {
            accountListPageSize = normalizeAccountPageSize(
                localStorage.getItem('outlook_account_page_size') || ACCOUNT_LIST_DEFAULT_PAGE_SIZE
            );
            syncAccountPageSizeSelect();
        }

        function getAccountSearchScope() {
            const select = document.getElementById('accountSearchScopeSelect');
            return select?.value === 'group' ? 'group' : 'all';
        }

        function getAccountSearchScopeKey() {
            return getAccountSearchScope() === 'group' && currentGroupId
                ? `group:${currentGroupId}`
                : 'all';
        }

        function initAccountSearchScopeSelect() {
            const select = document.getElementById('accountSearchScopeSelect');
            if (!select) {
                return;
            }
            const savedScope = localStorage.getItem('outlook_account_search_scope');
            select.value = savedScope === 'group' ? 'group' : 'all';
        }

        function syncAccountSearchScopeVisibility() {
            const container = document.querySelector('.search-container');
            const wrap = document.getElementById('accountSearchScopeWrap');
            const select = document.getElementById('accountSearchScopeSelect');
            const hidden = !!isTempEmailGroup;

            if (container) {
                container.classList.toggle('search-container--single', hidden);
            }
            if (wrap) {
                wrap.hidden = hidden;
            }
            if (select) {
                select.disabled = hidden;
            }
        }

        function handleAccountSearchScopeChange(value) {
            const normalizedScope = value === 'group' ? 'group' : 'all';
            localStorage.setItem('outlook_account_search_scope', normalizedScope);
            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery && !isTempEmailGroup) {
                searchAccounts(searchQuery, true);
            }
        }

        function handleAccountPageSizeChange(value) {
            accountListPageSize = normalizeAccountPageSize(value);
            localStorage.setItem('outlook_account_page_size', String(accountListPageSize));
            syncAccountPageSizeSelect();
            invalidateAccountCaches();
            if (!isTempEmailGroup) {
                refreshVisibleAccountList(true);
            }
        }

        function appendAccountListParams(params) {
            params.set('limit', String(getAccountPageSize()));
            params.set('sort_by', currentSortBy || 'created_at');
            params.set('sort_order', currentSortOrder || 'desc');

            const filters = getAccountTagFilterParams();
            if (filters.tagIds.length) {
                params.set('tag_ids', filters.tagIds.join(','));
            }
            if (filters.includeUntagged) {
                params.set('include_untagged', '1');
            }
            return params;
        }

        function updateAccountPaginationState(mode, key, data, loadedCount, loading = false) {
            accountPaginationState = {
                mode,
                key,
                total: Number.isFinite(Number(data?.total)) ? Number(data.total) : loadedCount,
                loaded: loadedCount,
                hasMore: data?.has_more === true,
                loading
            };
        }

        function setAccountPaginationLoading(loading) {
            accountPaginationState.loading = loading;
            const footer = document.getElementById('accountPaginationFooter');
            if (footer) {
                footer.classList.toggle('is-loading', loading);
                const text = footer.querySelector('.account-pagination-text');
                if (text) {
                    if (loading) {
                        text.textContent = '加载中...';
                    } else {
                        const total = Number(accountPaginationState.total) || 0;
                        const loaded = Math.min(Number(accountPaginationState.loaded) || 0, total || Number(accountPaginationState.loaded) || 0);
                        text.textContent = accountPaginationState.hasMore
                            ? `已加载 ${loaded} / ${total} 个邮箱`
                            : `已加载全部 ${total} 个邮箱`;
                    }
                }
            }
        }

        function renderAccountPaginationFooter(visibleCount) {
            if (!accountPaginationState.total && !accountPaginationState.hasMore) {
                return '';
            }

            const total = Math.max(Number(accountPaginationState.total) || 0, visibleCount);
            const loaded = Math.max(Number(accountPaginationState.loaded) || visibleCount, visibleCount);
            if (!accountPaginationState.hasMore && total <= getAccountPageSize()) {
                return '';
            }

            const text = accountPaginationState.hasMore
                ? `已加载 ${Math.min(loaded, total)} / ${total} 个邮箱`
                : `已加载全部 ${total} 个邮箱`;
            const action = accountPaginationState.hasMore
                ? '<button class="account-pagination-btn" type="button" onclick="loadMoreAccounts()">加载更多</button>'
                : '';

            return `
                <div class="account-pagination-footer ${accountPaginationState.loading ? 'is-loading' : ''}" id="accountPaginationFooter">
                    <span class="account-pagination-text">${escapeHtml(accountPaginationState.loading ? '加载中...' : text)}</span>
                    ${action}
                </div>
            `;
        }

        function maybeLoadMoreAccounts() {
            const container = document.getElementById('accountList');
            if (!container || accountPaginationState.loading || !accountPaginationState.hasMore) {
                return;
            }
            const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
            if (distanceToBottom < 180) {
                loadMoreAccounts();
            }
        }

        function initAccountListScroll() {
            const accountList = document.getElementById('accountList');
            if (!accountList || accountList.dataset.boundPaging) return;
            accountList.dataset.boundPaging = 'true';
            accountList.addEventListener('scroll', maybeLoadMoreAccounts, { passive: true });
        }

        async function loadMoreAccounts() {
            if (accountPaginationState.loading || !accountPaginationState.hasMore) {
                return;
            }

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery) {
                await searchAccounts(searchQuery, false, true);
            } else if (currentGroupId && !isTempEmailGroup) {
                await loadAccountsByGroup(currentGroupId, false, true);
            }
        }

        // 加载分组下的账号
        async function loadAccountsByGroup(groupId, forceRefresh = false, append = false) {
            const container = document.getElementById('accountList');
            const cacheAllowed = !hasAccountServerSideFilters();

            // 如果有缓存且不强制刷新，直接使用缓存
            if (!append && !forceRefresh && cacheAllowed && accountsCache[groupId]) {
                updateAccountPaginationState('group', String(groupId), {
                    total: accountsCache[groupId].length,
                    has_more: false
                }, accountsCache[groupId].length);
                renderFilteredAccountList(accountsCache[groupId]);
                return;
            }

            const offset = append ? currentAccountListSource.length : 0;
            if (append) {
                setAccountPaginationLoading(true);
            } else {
                container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';
            }

            const params = appendAccountListParams(new URLSearchParams({
                group_id: String(groupId),
                offset: String(offset)
            }));
            const requestId = ++accountListRequestSeq;

            try {
                const response = await fetch(`/api/accounts?${params.toString()}`);
                const data = await response.json();
                if (requestId !== accountListRequestSeq) {
                    return;
                }

                if (data.success) {
                    const nextAccounts = append
                        ? currentAccountListSource.concat(data.accounts || [])
                        : (data.accounts || []);
                    if (cacheAllowed && !data.has_more && nextAccounts.length <= getAccountPageSize()) {
                        accountsCache[groupId] = nextAccounts;
                    } else if (!append) {
                        delete accountsCache[groupId];
                    } else if (nextAccounts.length > getAccountPageSize()) {
                        delete accountsCache[groupId];
                    }
                    updateAccountPaginationState('group', String(groupId), data, nextAccounts.length);
                    renderFilteredAccountList(nextAccounts);
                } else {
                    container.innerHTML = renderEmptyStateMarkup('⚠️', data.error || '加载失败', {
                        onAction: `loadAccountsByGroup(${Number(groupId)}, true)`,
                        actionTitle: '刷新账号列表'
                    });
                }
            } catch (error) {
                if (append) {
                    showToast('加载更多账号失败', 'error');
                } else {
                    container.innerHTML = renderEmptyStateMarkup('⚠️', '加载失败', {
                        onAction: `loadAccountsByGroup(${Number(groupId)}, true)`,
                        actionTitle: '刷新账号列表'
                    });
                }
            } finally {
                if (requestId === accountListRequestSeq) {
                    setAccountPaginationLoading(false);
                }
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
            if (accountSelectionMode || event?.shiftKey) {
                handleAccountRowSelectionClick(event);
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
            const showSearchGroupInfo = isSearchMode && getAccountSearchScope() === 'all';
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

            const checkedAccountIds = new Set(
                Array.from(container.querySelectorAll('.account-select-checkbox:checked'))
                    .map(checkbox => String(checkbox.value))
            );
            container.innerHTML = accounts.map(acc => `
                <div class="account-item ${currentAccount === acc.email ? 'active' : ''} ${acc.status === 'inactive' ? 'inactive' : ''}"
                     data-account-id="${acc.id}"
                     onclick="handleAccountItemClick(event, '${escapeJs(acc.email)}')">
                    <input type="checkbox" class="account-select-checkbox" value="${acc.id}" 
                           data-account-email="${escapeHtml(acc.email)}"
                           data-account-type="${escapeHtml(acc.account_type || 'outlook')}"
                           data-refreshable="${acc.account_type !== 'imap' ? 'true' : 'false'}"
                           data-forward-enabled="${acc.forward_enabled ? 'true' : 'false'}"
                           onclick="handleAccountSelectionCheckboxClick(event)">
                    <div class="account-body">
                        <div class="account-title-row">
                            <div class="account-email-wrap">
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
                        ${renderAccountGroupSummary(acc, showSearchGroupInfo)}
                        ${renderAccountAliasSummary(acc.aliases)}
                        ${acc.remark && acc.remark.trim() ? `<div class="account-remark" title="${escapeHtml(acc.remark)}">${escapeHtml(acc.remark)}</div>` : ''}
                        ${(acc.tags || []).length ? `<div class="account-tags">${renderAccountTagSummary(acc.tags)}</div>` : ''}
                        ${renderAccountFooter(acc)}
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
            `).join('') + renderAccountPaginationFooter(accounts.length);
            if (checkedAccountIds.size) {
                container.querySelectorAll('.account-select-checkbox').forEach(checkbox => {
                    checkbox.checked = checkedAccountIds.has(String(checkbox.value));
                });
            }
            updateBatchActionBar();
            maybeLoadMoreAccounts();
        }

        // 排序相关变量
        const ACCOUNT_SORT_DEFAULT_ORDERS = {
            sort_order: 'asc',
            created_at: 'desc',
            email: 'asc'
        };
        let currentSortBy = 'sort_order';
        let currentSortOrder = ACCOUNT_SORT_DEFAULT_ORDERS[currentSortBy];
        let suppressGroupClickUntil = 0;
        function createGroupDragState() {
            return {
                groupId: null,
                pointerId: null,
                pointerType: 'mouse',
                sourceEl: null,
                placeholderEl: null,
                targetMode: null,
                targetGroupId: null,
                targetParentId: null,
                insertAfter: false,
                dropAllowed: true,
                pressTimer: null,
                isDragging: false,
                startX: 0,
                startY: 0,
                offsetY: 0,
                fixedLeft: 0
            };
        }
        let groupDragState = createGroupDragState();

        function renderAccountFooter(acc) {
            const footerParts = [];
            const sortOrder = getAccountSortOrderValue(acc);
            if (shouldShowAccountSortOrder() && sortOrder !== null) {
                footerParts.push(`<span class="account-sort-order">排序值 ${escapeHtml(String(sortOrder))}</span>`);
            }
            if (shouldShowAccountCreatedAt() && acc.created_at) {
                footerParts.push(`<span class="account-created-at" title="${escapeHtml(acc.created_at || '')}">${escapeHtml(formatAbsoluteDateTime(acc.created_at))}</span>`);
            }
            if (acc.last_refresh_status === 'failed') {
                footerParts.push('<button class="account-error-btn" onclick="event.stopPropagation(); showRefreshError(' + acc.id + ', \'' + escapeJs(acc.last_refresh_error || '未知错误') + '\', \'' + escapeJs(acc.email) + '\', \'' + escapeJs(acc.account_type || 'outlook') + '\')">查看错误</button>');
            }
            if (!footerParts.length) {
                return '';
            }
            return `<div class="account-refresh-row">${footerParts.join('')}</div>`;
        }

        function getAccountSortOrderValue(account) {
            const value = parseInt(account?.sort_order, 10);
            return Number.isFinite(value) && value > 0 ? value : null;
        }

        function getAccountCreatedAtValue(account) {
            const value = Date.parse(account?.created_at || '');
            return Number.isNaN(value) ? 0 : value;
        }

        function compareAccountsByCreatedAt(a, b, order = 'desc') {
            const createdA = getAccountCreatedAtValue(a);
            const createdB = getAccountCreatedAtValue(b);
            return order === 'asc' ? createdA - createdB : createdB - createdA;
        }

        function compareAccountsByEmail(a, b, order = 'asc') {
            const emailA = String(a?.email || '').toLowerCase();
            const emailB = String(b?.email || '').toLowerCase();
            return order === 'asc'
                ? emailA.localeCompare(emailB)
                : emailB.localeCompare(emailA);
        }

        // 排序账号列表
        function sortAccounts(sortBy) {
            // 如果点击同一个排序按钮，切换排序顺序
            if (currentSortBy === sortBy) {
                currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                currentSortBy = sortBy;
                currentSortOrder = ACCOUNT_SORT_DEFAULT_ORDERS[sortBy] || 'asc';
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

            invalidateAccountCaches();
            if (isTempEmailGroup) {
                if (currentAccountListSource.length) {
                    renderTempEmailList(currentAccountListSource);
                }
                return;
            }

            refreshVisibleAccountList(true);
        }

        function renderFilteredAccountList(accounts) {
            currentAccountListSource = Array.isArray(accounts) ? [...accounts] : [];
            const filteredAccounts = applyFiltersAndSort(currentAccountListSource);
            renderAccountList(filteredAccounts);

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery) {
                const total = Number(accountPaginationState.total) || filteredAccounts.length;
                if (getAccountSearchScope() === 'group') {
                    const currentGroup = groups.find(group => group.id === currentGroupId);
                    const groupName = currentGroup ? normalizeGroupName(currentGroup.name) : '当前分组';
                    updateCurrentGroupHeader(currentGroup || null, `${groupName} 搜索 (${filteredAccounts.length}/${total})`);
                } else {
                    updateCurrentGroupHeader(null, `搜索结果 (${filteredAccounts.length}/${total})`);
                }
            } else {
                const currentGroup = groups.find(group => group.id === currentGroupId);
                if (currentGroup && Number(accountPaginationState.total) > 0) {
                    updateCurrentGroupHeader(currentGroup, `${normalizeGroupName(currentGroup.name)} (${filteredAccounts.length}/${accountPaginationState.total})`);
                }
            }
        }

        function refreshVisibleAccountList(forceRefresh = false) {
            if (currentGroupId && isTempEmailGroup) {
                return loadTempEmails(forceRefresh);
            }

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();
            if (searchQuery) {
                return searchAccounts(searchQuery, forceRefresh);
            }
            if (currentGroupId) {
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

        function getAccountSearchTerms(query) {
            const normalizedQuery = String(query || '').trim().toLowerCase();
            if (!normalizedQuery) {
                return [];
            }

            const splitTerms = normalizedQuery.split(/\s+/).filter(Boolean);
            return Array.from(new Set(splitTerms));
        }

        function matchesAccountSearchTerms(fields, query) {
            const terms = getAccountSearchTerms(query);
            if (!terms.length) {
                return true;
            }

            const normalizedFields = fields.map(value => String(value || '').toLowerCase());
            return terms.some(term => normalizedFields.some(value => value.includes(term)));
        }

        // 应用筛选和排序
        function applyFiltersAndSort(accounts) {
            let result = [...accounts];

            const searchQuery = (document.getElementById('globalSearch')?.value || '').trim();

            if (searchQuery) {
                result = result.filter(acc => {
                    const aliasText = Array.isArray(acc.aliases) ? acc.aliases.join('\n') : '';
                    const tagText = Array.isArray(acc.tags) ? acc.tags.map(tag => String(tag.name || '')).join('\n') : '';
                    return matchesAccountSearchTerms([
                        acc.email,
                        aliasText,
                        acc.remark,
                        tagText
                    ], searchQuery);
                });
            }

            // 1. Tag 筛选
            if (selectedTagFilters.size > 0) {
                result = result.filter(acc => matchesSelectedTagFilters(acc.tags));
            }

            // 2. 排序
            return result.sort((a, b) => {
                if (currentSortBy === 'sort_order') {
                    const sortA = getAccountSortOrderValue(a);
                    const sortB = getAccountSortOrderValue(b);
                    const hasSortA = sortA !== null;
                    const hasSortB = sortB !== null;

                    if (hasSortA !== hasSortB) {
                        return hasSortA ? -1 : 1;
                    }

                    if (hasSortA && hasSortB && sortA !== sortB) {
                        return currentSortOrder === 'asc' ? sortA - sortB : sortB - sortA;
                    }

                    const createdCompare = compareAccountsByCreatedAt(a, b, 'desc');
                    if (createdCompare !== 0) {
                        return createdCompare;
                    }
                    return compareAccountsByEmail(a, b, 'asc');
                }

                if (currentSortBy === 'created_at') {
                    const createdCompare = compareAccountsByCreatedAt(a, b, currentSortOrder);
                    if (createdCompare !== 0) {
                        return createdCompare;
                    }
                    return compareAccountsByEmail(a, b, 'asc');
                }

                const emailCompare = compareAccountsByEmail(a, b, currentSortOrder);
                if (emailCompare !== 0) {
                    return emailCompare;
                }
                return compareAccountsByCreatedAt(a, b, 'desc');
            });
        }

        // Tag Filter Change Handler
        function handleTagFilterChange() {
            const selected = document.querySelectorAll('.tag-filter-checkbox:checked');
            selectedTagFilters = new Set(
                Array.from(selected)
                    .map(cb => normalizeTagFilterSelectionValue(cb.value))
                    .filter(value => value !== null)
            );
            document.querySelectorAll('.tag-filter-option').forEach(option => {
                const checkbox = option.querySelector('.tag-filter-checkbox');
                option.classList.toggle('is-checked', !!checkbox?.checked);
            });
            updateTagFilterSummary();
            invalidateAccountCaches();
            if (isTempEmailGroup) {
                if (currentAccountListSource.length) {
                    renderTempEmailList(currentAccountListSource);
                }
                return;
            } else if (currentGroupId) {
                refreshVisibleAccountList(true);
                return;
            }

            if (currentAccountListSource.length) {
                renderFilteredAccountList(currentAccountListSource);
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
        async function searchAccounts(query, forceRefresh = false, append = false) {
            const container = document.getElementById('accountList');

            if (!query.trim()) {
                const currentGroup = groups.find(group => group.id === currentGroupId);
                updateCurrentGroupHeader(currentGroup);
                currentAccountListSource = [];
                accountPaginationState = {
                    mode: '',
                    key: '',
                    total: 0,
                    loaded: 0,
                    hasMore: false,
                    loading: false
                };
                if (isTempEmailGroup) {
                    loadTempEmails();
                } else {
                    loadAccountsByGroup(currentGroupId, forceRefresh);
                }
                return;
            }

            if (getAccountSearchTerms(query).length > ACCOUNT_SEARCH_MAX_TERMS) {
                const message = '搜索关键词最多支持 200 个';
                if (append) {
                    showToast(message, 'warning');
                } else {
                    container.innerHTML = `<div class="empty-state"><div class="empty-state-text">${escapeHtml(message)}</div></div>`;
                }
                return;
            }

            if (isTempEmailGroup) {
                if (accountsCache['temp']) {
                    renderTempEmailList(accountsCache['temp']);
                } else {
                    await loadTempEmails();
                }
                return;
            }

            const offset = append ? currentAccountListSource.length : 0;
            if (append) {
                setAccountPaginationLoading(true);
            } else {
                container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';
            }

            const params = appendAccountListParams(new URLSearchParams({
                q: query,
                offset: String(offset)
            }));
            if (getAccountSearchScope() === 'group' && currentGroupId) {
                params.set('group_id', String(currentGroupId));
            }
            const requestId = ++accountListRequestSeq;

            try {
                const response = await fetch(`/api/accounts/search?${params.toString()}`);
                const data = await response.json();
                if (requestId !== accountListRequestSeq) {
                    return;
                }

                if (data.success) {
                    const nextAccounts = append
                        ? currentAccountListSource.concat(data.accounts || [])
                        : (data.accounts || []);
                    updateAccountPaginationState('search', `${getAccountSearchScopeKey()}:${query}`, data, nextAccounts.length);
                    renderFilteredAccountList(nextAccounts);
                } else {
                    const message = data.error || '搜索失败';
                    container.innerHTML = `<div class="empty-state"><div class="empty-state-text">${escapeHtml(message)}</div></div>`;
                }
            } catch (error) {
                console.error('搜索失败:', error);
                if (append) {
                    showToast('加载更多搜索结果失败', 'error');
                } else {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-text">搜索失败，请重试</div></div>';
                }
            } finally {
                if (requestId === accountListRequestSeq) {
                    setAccountPaginationLoading(false);
                }
            }
        }

        // 更新分组下拉选择框
        function updateGroupSelects() {
            const selects = ['importGroupSelect', 'editGroupSelect', 'tokenSaveGroupSelect'];
            selects.forEach(selectId => {
                const select = document.getElementById(selectId);
                if (select) {
                    const currentValue = select.value;
                    const includeTemp = !(selectId === 'editGroupSelect' || selectId === 'tokenSaveGroupSelect');
                    const filteredGroups = includeTemp ? groups : groups.filter(g => !isSystemGroup(g));

                    select.innerHTML = renderGroupOptions({ includeTemp });
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

        function getAvailableParentGroups(editingId = null) {
            const editingGroupIdValue = editingId === null ? null : Number(editingId);
            const excludedIds = editingGroupIdValue
                ? new Set([editingGroupIdValue, ...getGroupDescendantIds(editingGroupIdValue)])
                : new Set();
            return flattenGroupTree(groupTree).filter(group =>
                !isSystemGroup(group)
                && normalizeGroupLevel(group) < 3
                && !excludedIds.has(Number(group.id))
            );
        }

        function updateParentGroupSelect(selectedParentId = null, editingId = null) {
            const select = document.getElementById('groupParentSelect');
            if (!select) {
                return;
            }

            const normalizedSelectedParentId = normalizeGroupParentId(selectedParentId);
            const options = ['<option value="">无（一级分组）</option>'];
            getAvailableParentGroups(editingId).forEach(group => {
                options.push(`<option value="${group.id}">${escapeHtml(getGroupOptionLabel(group))}</option>`);
            });
            select.innerHTML = options.join('');
            select.value = normalizedSelectedParentId && getAvailableParentGroups(editingId).some(group => Number(group.id) === normalizedSelectedParentId)
                ? String(normalizedSelectedParentId)
                : '';
        }

        function handleGroupParentChange() {
            const parentId = normalizeGroupParentId(document.getElementById('groupParentSelect')?.value);
            updateGroupSortPositionOptions(editingGroupId, null, parentId);
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
            const reauthorizeGroup = document.getElementById('editReauthorizeGroup');

            if (passwordGroup) passwordGroup.style.display = isOutlook ? '' : 'none';
            if (clientIdGroup) clientIdGroup.style.display = isOutlook ? '' : 'none';
            if (refreshTokenGroup) refreshTokenGroup.style.display = isOutlook ? '' : 'none';
            if (imapFields) imapFields.style.display = isOutlook ? 'none' : '';
            if (customImapFields) customImapFields.style.display = provider === 'custom' ? '' : 'none';
            if (reauthorizeGroup) reauthorizeGroup.style.display = isOutlook ? '' : 'none';
        }

        function updateImportHint() {
            const hintEl = document.getElementById('importFormatHint');
            const inputEl = document.getElementById('accountInput');
            const channelGroup = document.getElementById('importChannelGroup');
            const channelSelect = document.getElementById('importChannelSelect');
            const cloudflareChannelGroup = document.getElementById('importCloudflareChannelGroup');
            const cloudflareModeGroup = document.getElementById('importCloudflareModeGroup');
            const cloudflareModeSelect = document.getElementById('importCloudflareImportMode');
            const providerGroup = document.getElementById('importProviderGroup');
            const providerSelect = document.getElementById('importProviderSelect');
            const exampleEl = document.getElementById('importFormatExample');
            const importSource = document.querySelector('#addAccountModal .import-account-source');
            const customImapSettings = document.getElementById('customImapSettings');
            const customHost = document.getElementById('importImapHost');
            const customPort = document.getElementById('importImapPort');
            const accountDefaultFields = document.querySelectorAll('#addAccountModal .import-account-default-field');
            if (!hintEl || !inputEl) return;

            const isTempGroup = isTempImportGroup();
            if (channelGroup) channelGroup.style.display = isTempGroup ? '' : 'none';
            if (providerGroup) providerGroup.style.display = isTempGroup ? 'none' : '';
            if (!isTempGroup) {
                if (cloudflareChannelGroup) cloudflareChannelGroup.style.display = 'none';
                if (cloudflareModeGroup) cloudflareModeGroup.style.display = 'none';
                if (importSource) importSource.style.display = '';
            }
            accountDefaultFields.forEach(field => {
                const isTagField = !!field.querySelector('#importTagDropdown');
                field.style.display = isTempGroup ? (isTagField ? '' : 'none') : '';
            });

            if (isTempGroup) {
                if (customImapSettings) customImapSettings.style.display = 'none';
                const channel = channelSelect ? channelSelect.value : 'gptmail';
                const isCloudflare = channel === 'cloudflare';
                const cloudflareMode = cloudflareModeSelect ? cloudflareModeSelect.value : 'auto';
                if (cloudflareChannelGroup) cloudflareChannelGroup.style.display = isCloudflare ? '' : 'none';
                if (cloudflareModeGroup) cloudflareModeGroup.style.display = isCloudflare ? '' : 'none';
                if (importSource) importSource.style.display = isCloudflare && cloudflareMode === 'auto' ? 'none' : '';
                if (isCloudflare && typeof loadCloudflareChannelsForImport === 'function') {
                    loadCloudflareChannelsForImport();
                }
                if (channel === 'duckmail') {
                    hintEl.textContent = '格式：邮箱----密码，每行一个。';
                    inputEl.placeholder = '邮箱----密码';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\nuser@duck.com----mypassword\nuser2@duck.com----password2';
                    }
                    return;
                }
                if (channel === 'cloudflare') {
                    if (cloudflareMode === 'auto') {
                        hintEl.textContent = '自动从所选 Cloudflare 渠道拉取邮箱地址并导入，不拉取 JWT。';
                        inputEl.placeholder = '';
                        if (exampleEl) {
                            exampleEl.style.display = 'none';
                            exampleEl.textContent = '';
                        }
                        return;
                    }
                    hintEl.textContent = '格式：每行一个邮箱地址。手动导入不再支持 邮箱----JWT。';
                    inputEl.placeholder = 'user@example.com\nuser2@example.com';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\nuser@example.com\nuser2@example.com';
                    }
                    return;
                }
                hintEl.textContent = '格式：每行一个邮箱地址。';
                inputEl.placeholder = '每行一个邮箱地址';
                if (exampleEl) {
                    exampleEl.style.display = '';
                    exampleEl.textContent = '示例：\nuser1@gptmail.com\nuser2@gptmail.com';
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
                    exampleEl.textContent = '示例：\nuser@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA...\nuser@outlook.com----password123----0.AXEA...----24d9a0ed-8787-4584-883c-2fd79308940a';
                }
                return;
            }

            if (provider === 'custom') {
                hintEl.textContent = '格式：邮箱----IMAP密码。也支持兼容格式：邮箱----IMAP密码----imap_host----imap_port。';
                inputEl.placeholder = '邮箱----IMAP密码';
                if (exampleEl) {
                    const host = customHost?.value?.trim() || 'imap.example.com';
                    const port = customPort?.value?.trim() || '993';
                    exampleEl.textContent = `示例：\nuser@example.com----app-password\nuser@example.com----app-password----${host}----${port}`;
                }
                return;
            }

            hintEl.textContent = `格式：邮箱----IMAP授权码/应用密码，每行一个。当前类型：${getProviderLabel(provider)}。`;
            inputEl.placeholder = '邮箱----IMAP授权码/应用密码';
            if (exampleEl) {
                exampleEl.textContent = '示例：\nuser@gmail.com----app-password\nuser2@qq.com----imap-auth-code';
            }
        }

        function showAddGroupModal() {
            closeAllModals();
            editingGroupId = null;
            document.getElementById('groupModalTitle').textContent = '添加分组';
            document.getElementById('groupName').value = '';
            document.getElementById('groupDescription').value = '';
            const currentGroup = getGroupById(currentGroupId);
            const defaultParentId = currentGroup && !isSystemGroup(currentGroup) && normalizeGroupLevel(currentGroup) < 3
                ? currentGroup.id
                : null;
            updateParentGroupSelect(defaultParentId, null);
            updateGroupSortPositionOptions(null, null, defaultParentId);
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
                    updateParentGroupSelect(data.group.parent_id, groupId);
                    updateGroupSortPositionOptions(groupId, data.group.sort_position, data.group.parent_id);
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
            const sortPositionRaw = document.getElementById('groupSortPosition').value;
            const sortPosition = sortPositionRaw ? parseInt(sortPositionRaw, 10) : null;
            const parentId = normalizeGroupParentId(document.getElementById('groupParentSelect')?.value);

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
                        sort_position: sortPosition,
                        parent_id: parentId
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
            const childCount = getGroupDescendantIds(groupId).length;
            const message = childCount > 0
                ? `该分组下有 ${childCount} 个子分组，删除后子分组将一并删除，所有邮箱将移至默认分组`
                : '确定要删除该分组吗？分组下的邮箱将移至默认分组。';
            if (!(await showConfirmModal(message, { title: '删除分组', confirmText: '确认删除' }))) {
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
