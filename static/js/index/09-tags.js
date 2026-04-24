        /* global UNTAGGED_TAG_FILTER_KEY, accountsCache, currentAccountListSource, currentGroupId, handleApiError, hideModal, isTempEmailGroup, isUntaggedTagFilterValue, loadAccountsByGroup, loadTempEmails, normalizeTagFilterSelectionValue, refreshVisibleAccountList, renderFilteredAccountList, renderTempEmailList, selectedTagFilters, showModal, showToast, updateBatchTagTagOptions, updateCurrentGroupHeader */

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
                    selectedTagFilters = new Set(
                        Array.from(selectedTagFilters).filter(tagId => {
                            if (isUntaggedTagFilterValue(tagId)) {
                                return true;
                            }
                            return allTags.some(tag => tag.id === normalizeTagFilterSelectionValue(tagId));
                        })
                    );
                    renderTagList();
                    updateTagFilter();
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
            if (!triggerText || !countBadge) return;

            const selectedCount = selectedTagFilters.size;
            triggerText.textContent = getTagFilterSummaryText();
            countBadge.style.display = selectedCount > 0 ? 'inline-flex' : 'none';
            countBadge.textContent = String(selectedCount);
        }

        function filterTagOptions(keyword = '') {
            tagFilterKeyword = keyword.trim().toLowerCase();
            let visibleCount = 0;
            document.querySelectorAll('.tag-filter-option').forEach(option => {
                const tagName = (option.dataset.tagName || '').toLowerCase();
                const isVisible = !tagFilterKeyword || tagName.includes(tagFilterKeyword);
                option.classList.toggle('hidden', !isVisible);
                if (isVisible) visibleCount += 1;
            });

            const emptyState = document.getElementById('tagFilterEmptyState');
            if (emptyState) {
                emptyState.style.display = visibleCount === 0 ? 'block' : 'none';
            }
        }

        function toggleTagFilterDropdown(event) {
            event?.stopPropagation();
            const dropdown = document.getElementById('tagFilterDropdown');
            if (!dropdown) return;

            const willOpen = !dropdown.classList.contains('open');
            dropdown.classList.toggle('open', willOpen);

            if (willOpen) {
                const searchInput = document.getElementById('tagFilterSearchInput');
                if (searchInput) {
                    searchInput.value = tagFilterKeyword;
                    filterTagOptions(searchInput.value);
                    window.requestAnimationFrame(() => searchInput.focus());
                }
            }
        }

        function clearTagFilterSelection(event) {
            event?.stopPropagation();
            selectedTagFilters = new Set();
            document.querySelectorAll('.tag-filter-checkbox').forEach(checkbox => {
                checkbox.checked = false;
            });
            document.querySelectorAll('.tag-filter-option').forEach(option => {
                option.classList.remove('is-checked');
            });
            updateTagFilterSummary();
            if (currentAccountListSource.length) {
                if (isTempEmailGroup) {
                    renderTempEmailList(currentAccountListSource);
                } else {
                    renderFilteredAccountList(currentAccountListSource);
                }
            } else if (currentGroupId) {
                if (isTempEmailGroup) {
                    loadTempEmails();
                } else {
                    loadAccountsByGroup(currentGroupId);
                }
            }
        }

        // 更新标签筛选下拉框
        function updateTagFilter() {
            const container = document.getElementById('tagFilterContainer');
            if (!container) return;

            container.style.display = 'flex';

            const optionsHtml = getTagFilterOptionItems().map(tag => `
                <label class="tag-filter-option ${selectedTagFilters.has(tag.id) ? 'is-checked' : ''}" data-tag-name="${escapeHtml(tag.name)}">
                    <input type="checkbox" class="tag-filter-checkbox" value="${tag.id}"
                        ${selectedTagFilters.has(tag.id) ? 'checked' : ''}
                        onchange="handleTagFilterChange()">
                    <span class="tag-filter-dot" style="background-color: ${tag.color};"></span>
                    <span class="tag-filter-name">${escapeHtml(tag.name)}</span>
                </label>
            `).join('');

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
