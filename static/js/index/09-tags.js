        /* global UNTAGGED_TAG_FILTER_KEY, accountsCache, currentAccountListSource, currentGroupId, handleApiError, hideModal, invalidateAccountCaches, isTempEmailGroup, isUntaggedTagFilterValue, loadAccountTagFilterPreference, loadAccountsByGroup, loadTempEmails, normalizeTagFilterSelectionValue, refreshVisibleAccountList, renderFilteredAccountList, renderImportTagOptions, renderTempEmailList, saveAccountTagFilterPreference, selectedTagFilters, showModal, showToast, updateBatchTagTagOptions, updateCurrentGroupHeader */

        // ==================== 标签管理 ====================

        let allTags = [];
        const UNTAGGED_TAG_FILTER_ITEM = {
            id: UNTAGGED_TAG_FILTER_KEY,
            name: '无标签',
            color: '#9ca3af',
        };

        function getTagFilterOptionItems() {
            return [UNTAGGED_TAG_FILTER_ITEM, ...allTags];
        }

        // ==================== 通用标签下拉组件函数 ====================
        // 供邮箱列表筛选条件、导入模态框、编辑模态框共用

        /**
         * 生成 tag-filter-option checkbox 列表 HTML
         * @param {Array} tags - 标签列表 [{id, name, color}, ...]
         * @param {Array|Set} selectedIds - 已选中的标签 ID 集合
         * @param {string} onchangeFn - onchange 调用的函数名（不含括号）
         * @param {boolean} includeUntagged - 是否包含"无标签"选项（仅筛选条件用）
         */
        function buildTagFilterOptionsHtml(tags, selectedIds, onchangeFn, includeUntagged) {
            const selectedSet = selectedIds instanceof Set ? selectedIds : new Set(selectedIds);
            let items = includeUntagged ? [UNTAGGED_TAG_FILTER_ITEM, ...tags] : (tags || []);
            if (!items.length) {
                return '<div class="tag-filter-empty" style="display: block;">暂无标签</div>';
            }
            return items.map(tag => `
                <label class="tag-filter-option ${selectedSet.has(tag.id) ? 'is-checked' : ''}" data-tag-name="${escapeHtml(tag.name)}">
                    <input type="checkbox" class="tag-filter-checkbox" value="${tag.id}"
                        ${selectedSet.has(tag.id) ? 'checked' : ''}
                        ${onchangeFn ? `onchange="${onchangeFn}()"` : ''}>
                    <span class="tag-filter-dot" style="background-color: ${tag.color};"></span>
                    <span class="tag-filter-name">${escapeHtml(tag.name)}</span>
                </label>
            `).join('');
        }

        /**
         * 在指定 options 容器内按关键字过滤标签选项
         */
        function filterTagFilterOptions(keyword, optionsContainer) {
            if (!optionsContainer) return;
            const kw = (keyword || '').trim().toLowerCase();
            let visibleCount = 0;
            optionsContainer.querySelectorAll('.tag-filter-option').forEach(option => {
                const tagName = (option.dataset.tagName || '').toLowerCase();
                const isVisible = !kw || tagName.includes(kw);
                option.classList.toggle('hidden', !isVisible);
                if (isVisible) visibleCount += 1;
            });
            const emptyState = optionsContainer.querySelector('.tag-filter-empty');
            if (emptyState) {
                const hasOptions = optionsContainer.querySelectorAll('.tag-filter-option').length > 0;
                emptyState.style.display = (visibleCount === 0 && (kw || !hasOptions)) ? 'block' : 'none';
                if (kw && visibleCount === 0) {
                    emptyState.textContent = '没有匹配的标签';
                } else if (!hasOptions) {
                    emptyState.textContent = '暂无标签';
                }
            }
        }

        /**
         * 从指定 options 容器获取已选中标签 ID 数组
         */
        function getTagFilterSelectedIds(optionsContainer) {
            if (!optionsContainer) return [];
            return Array.from(optionsContainer.querySelectorAll('.tag-filter-checkbox:checked'))
                .map(checkbox => parseInt(checkbox.value, 10))
                .filter(Number.isFinite);
        }

        /**
         * 更新标签下拉触发器的汇总文本和计数徽章
         * @param {HTMLElement} triggerTextEl - 汇总文本元素
         * @param {HTMLElement} countEl - 计数徽章元素
         * @param {Array} selectedItems - 已选标签对象数组 [{id, name, color}, ...]
         * @param {string} defaultText - 无选中时的默认文本
         */
        function updateTagFilterSummaryText(triggerTextEl, countEl, selectedItems, defaultText) {
            if (!triggerTextEl || !countEl) return;
            const count = selectedItems.length;
            if (!count) {
                triggerTextEl.textContent = defaultText || '未选择标签';
                countEl.style.display = 'none';
                countEl.textContent = '';
                return;
            }
            triggerTextEl.textContent = count <= 2
                ? selectedItems.map(t => t.name).join('、')
                : `已选 ${count} 个标签`;
            countEl.style.display = 'inline-flex';
            countEl.textContent = String(count);
        }

        /**
         * 切换标签下拉面板的开关状态，打开时聚焦搜索框
         */
        function toggleTagFilterDropdownState(dropdownEl, searchInputEl, keyword) {
            if (!dropdownEl) return;
            const willOpen = !dropdownEl.classList.contains('open');
            dropdownEl.classList.toggle('open', willOpen);
            if (willOpen && searchInputEl) {
                searchInputEl.value = keyword || '';
                const optionsContainer = dropdownEl.querySelector('.tag-filter-options');
                filterTagFilterOptions(searchInputEl.value, optionsContainer);
                window.requestAnimationFrame(() => searchInputEl.focus());
            }
        }

        /**
         * 清空标签下拉中所有选中状态（仅 UI 层面）
         */
        function clearTagFilterCheckboxes(dropdownEl) {
            if (!dropdownEl) return;
            dropdownEl.querySelectorAll('.tag-filter-checkbox').forEach(checkbox => {
                checkbox.checked = false;
            });
            dropdownEl.querySelectorAll('.tag-filter-option').forEach(option => {
                option.classList.remove('is-checked');
            });
        }

        // 显示标签管理模态框
        async function showTagManagementModal() {
            showModal('tagManagementModal');
            await loadTags();
        }

        // 隐藏标签管理模态框
        function hideTagManagementModal() {
            hideModal('tagManagementModal');
        }

        // 加载标签列表
        async function loadTags() {
            try {
                const response = await fetch('/api/tags');
                const data = await response.json();
                if (data.success) {
                    allTags = data.tags;
                    const selectedBeforePrune = Array.from(selectedTagFilters)
                        .map(tagId => normalizeTagFilterSelectionValue(tagId))
                        .filter(tagId => tagId !== null)
                        .join(',');
                    const savedTagFilters = typeof loadAccountTagFilterPreference === 'function'
                        ? loadAccountTagFilterPreference()
                        : selectedTagFilters;
                    selectedTagFilters = new Set(
                        Array.from(savedTagFilters).filter(tagId => {
                            if (isUntaggedTagFilterValue(tagId)) {
                                return true;
                            }
                            return allTags.some(tag => tag.id === normalizeTagFilterSelectionValue(tagId));
                        })
                    );
                    saveAccountTagFilterPreference();
                    const selectedAfterPrune = Array.from(selectedTagFilters)
                        .map(tagId => normalizeTagFilterSelectionValue(tagId))
                        .filter(tagId => tagId !== null)
                        .join(',');
                    renderTagList();
                    updateTagFilter();
                    if (typeof renderImportTagOptions === 'function') {
                        renderImportTagOptions();
                    }
                    if (selectedBeforePrune !== selectedAfterPrune && currentGroupId) {
                        refreshVisibleAccountList(true);
                    }
                }
            } catch (error) {
                showToast('加载标签失败', 'error');
            }
        }

        function getSelectedTagFilterItems() {
            return getTagFilterOptionItems().filter(tag => selectedTagFilters.has(tag.id));
        }

        function getTagFilterSummaryText() {
            const selected = getSelectedTagFilterItems();
            if (!selected.length) return '全部标签';
            if (selected.length <= 2) {
                return selected.map(tag => tag.name).join('、');
            }
            return `已选 ${selected.length} 个标签`;
        }

        function updateTagFilterSummary() {
            const triggerText = document.getElementById('tagFilterTriggerText');
            const countBadge = document.getElementById('tagFilterTriggerCount');
            updateTagFilterSummaryText(triggerText, countBadge, getSelectedTagFilterItems(), '全部标签');
        }

        function filterTagOptions(keyword = '') {
            tagFilterKeyword = keyword.trim().toLowerCase();
            const dropdown = document.getElementById('tagFilterDropdown');
            const optionsContainer = dropdown?.querySelector('.tag-filter-options');
            filterTagFilterOptions(tagFilterKeyword, optionsContainer);
        }

        function toggleTagFilterDropdown(event) {
            event?.stopPropagation();
            const dropdown = document.getElementById('tagFilterDropdown');
            const searchInput = document.getElementById('tagFilterSearchInput');
            toggleTagFilterDropdownState(dropdown, searchInput, tagFilterKeyword);
        }

        function clearTagFilterSelection(event) {
            event?.stopPropagation();
            selectedTagFilters = new Set();
            saveAccountTagFilterPreference();
            const dropdown = document.getElementById('tagFilterDropdown');
            clearTagFilterCheckboxes(dropdown);
            updateTagFilterSummary();
            if (isTempEmailGroup) {
                if (currentAccountListSource.length) {
                    renderTempEmailList(currentAccountListSource);
                }
                return;
            }

            invalidateAccountCaches();
            refreshVisibleAccountList(true);
        }

        // 更新标签筛选下拉框
        function updateTagFilter() {
            const container = document.getElementById('tagFilterContainer');
            if (!container) return;

            container.style.display = 'flex';

            const optionsHtml = buildTagFilterOptionsHtml(
                allTags, selectedTagFilters, 'handleTagFilterChange', true
            );

            container.innerHTML = `
                <span class="toolbar-label">标签</span>
                <div class="tag-filter-dropdown" id="tagFilterDropdown">
                    <button class="tag-filter-trigger" type="button" onclick="toggleTagFilterDropdown(event)">
                        <span class="tag-filter-trigger-text" id="tagFilterTriggerText">${escapeHtml(getTagFilterSummaryText())}</span>
                        <span class="tag-filter-trigger-count" id="tagFilterTriggerCount" style="display: none;"></span>
                        <span class="tag-filter-trigger-caret">▾</span>
                    </button>
                    <div class="tag-filter-panel">
                        <div class="tag-filter-panel-header">
                            <input
                                type="text"
                                id="tagFilterSearchInput"
                                class="tag-filter-search-input"
                                placeholder="搜索标签..."
                                oninput="filterTagOptions(this.value)"
                            >
                            <button class="tag-filter-clear-btn" type="button" onclick="clearTagFilterSelection(event)">清空</button>
                        </div>
                        <div class="tag-filter-options" id="tagFilterOptions">
                            ${optionsHtml}
                            <div class="tag-filter-empty" id="tagFilterEmptyState" style="display: none;">没有匹配的标签</div>
                        </div>
                    </div>
                </div>
            `;

            updateTagFilterSummary();
            filterTagOptions(tagFilterKeyword);
        }

        // 渲染标签列表
        function renderTagList() {
            const listEl = document.getElementById('tagList');
            if (!allTags.length) {
                listEl.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">暂无标签</div>';
                return;
            }

            let html = '';
            allTags.forEach(tag => {
                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px; border-bottom: 1px solid #f0f0f0;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="tag-badge" style="background-color: ${tag.color};">${escapeHtml(tag.name)}</span>
                        </div>
                        <button class="btn btn-sm btn-danger" onclick="deleteTag(${tag.id})">删除</button>
                    </div>
                `;
            });
            listEl.innerHTML = html;
        }

        // 创建标签
        async function createTag() {
            const nameInput = document.getElementById('newTagName');
            const colorInput = document.getElementById('newTagColor');
            const name = nameInput.value.trim();
            const color = colorInput.value;

            if (!name) {
                showToast('请输入标签名称', 'error');
                return;
            }

            try {
                const response = await fetch('/api/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, color })
                });
                const data = await response.json();

                if (data.success) {
                    nameInput.value = '';
                    showToast('标签创建成功', 'success');
                    await loadTags();
                    // 刷新账号列表以重新加载标签（如果是在查看列表时添加标签，可能不需要立即刷新列表，但为了保持一致性可以刷新）
                    // 但通常添加标签不影响当前列表显示，除非是给账号打标
                } else {
                    showToast(data.error || '创建失败', 'error');
                }
            } catch (error) {
                showToast('创建标签失败', 'error');
            }
        }

        // 删除标签
        async function deleteTag(id) {
            if (!(await showConfirmModal('确定要删除这个标签吗？', { title: '删除标签', confirmText: '确认删除' }))) return;

            try {
                const response = await fetch(`/api/tags/${id}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('标签已删除', 'success');
                    await loadTags();
                    await refreshVisibleAccountList(true);
                } else {
                    showToast(data.error || '删除失败', 'error');
                }
            } catch (error) {
                showToast('删除标签失败', 'error');
            }
        }
