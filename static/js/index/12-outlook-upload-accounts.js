        /* global escapeHtml, handleApiError, hideModal, showAddAccountModal, showConfirmModal, showGetRefreshTokenModal, showModal, showToast */

        // ==================== Outlook 上传账号 ====================

        const UPLOAD_ACCOUNTS_PAGE_SIZE_DEFAULT = 200;
        const UPLOAD_ACCOUNTS_PAGE_SIZE_OPTIONS = [100, 200, 500, 1000];
        const UPLOAD_ACCOUNTS_PAGE_SIZE_STORAGE_KEY = 'outlook_upload_account_page_size';
        const UPLOAD_ACCOUNTS_AUTH_STATUS_OPTIONS = ['all', 'authorized', 'unauthorized'];

        const uploadAccountsState = {
            page: 1,
            pageSize: UPLOAD_ACCOUNTS_PAGE_SIZE_DEFAULT,
            keyword: '',
            authStatus: 'all',
            total: 0,
            totalPages: 1,
            loading: false,
            requestSequence: 0,
            editingRowId: null,
            currentData: [],
            selectedIds: new Set(),
            batchAuthQueue: [],
            batchAuthRunning: false,
        };

        let graphAuthState = {
            accountId: null,
            email: '',
            secretLength: 0,
            eventSource: null,
            running: false,
        };

        function normalizeUploadAccountsPageSize(value) {
            const parsed = parseInt(value, 10);
            if (UPLOAD_ACCOUNTS_PAGE_SIZE_OPTIONS.includes(parsed)) {
                return parsed;
            }
            return UPLOAD_ACCOUNTS_PAGE_SIZE_DEFAULT;
        }

        function syncUploadAccountsPageSizeSelect() {
            const select = document.getElementById('uploadAccountsPageSizeSelect');
            if (select) {
                select.value = String(normalizeUploadAccountsPageSize(uploadAccountsState.pageSize));
            }
        }

        function initializeUploadAccountsPageSize() {
            const storedValue = localStorage.getItem(UPLOAD_ACCOUNTS_PAGE_SIZE_STORAGE_KEY);
            const normalizedValue = normalizeUploadAccountsPageSize(
                storedValue === null ? UPLOAD_ACCOUNTS_PAGE_SIZE_DEFAULT : storedValue
            );
            uploadAccountsState.pageSize = normalizedValue;
            if (storedValue !== null && String(normalizedValue) !== storedValue) {
                localStorage.setItem(
                    UPLOAD_ACCOUNTS_PAGE_SIZE_STORAGE_KEY,
                    String(normalizedValue),
                );
            }
            syncUploadAccountsPageSizeSelect();
        }

        function normalizeUploadAccountsAuthStatus(value) {
            const normalized = String(value || '').trim().toLowerCase();
            return UPLOAD_ACCOUNTS_AUTH_STATUS_OPTIONS.includes(normalized)
                ? normalized
                : 'all';
        }

        function syncUploadAccountsAuthStatusFilter() {
            const select = document.getElementById('uploadAccountsAuthStatusFilter');
            if (select) {
                select.value = normalizeUploadAccountsAuthStatus(uploadAccountsState.authStatus);
            }
        }

        function normalizeUploadAccountId(value) {
            const id = Number(value);
            return Number.isFinite(id) && id > 0 ? id : null;
        }

        function getSelectedUploadAccountIds() {
            return Array.from(uploadAccountsState.selectedIds)
                .map(normalizeUploadAccountId)
                .filter(Boolean);
        }

        function syncUploadAccountSelectionUi() {
            const selectedIds = getSelectedUploadAccountIds();
            const bar = document.getElementById('uploadAccountsBatchBar');
            const summary = document.getElementById('uploadAccountsSelectedSummary');
            const selectAll = document.getElementById('uploadAccountsSelectAllVisible');
            const authorizeBtn = document.getElementById('batchAuthorizeUploadAccountsBtn');
            const deleteBtn = document.getElementById('batchDeleteUploadAccountsBtn');
            const visibleCheckboxes = Array.from(
                document.querySelectorAll('#uploadAccountsTableBody .upload-account-select-checkbox')
            );
            const visibleIds = visibleCheckboxes
                .map(cb => normalizeUploadAccountId(cb.value))
                .filter(Boolean);
            const visibleSelectedCount = visibleIds.filter(id => uploadAccountsState.selectedIds.has(id)).length;

            if (bar) {
                bar.style.display = selectedIds.length > 0 || visibleIds.length > 0 ? 'flex' : 'none';
            }
            if (summary) {
                summary.textContent = selectedIds.length
                    ? `已选 ${selectedIds.length} 项`
                    : '未选择账号';
            }
            if (selectAll) {
                selectAll.checked = visibleIds.length > 0 && visibleSelectedCount === visibleIds.length;
                selectAll.indeterminate = visibleSelectedCount > 0 && visibleSelectedCount < visibleIds.length;
            }
            if (authorizeBtn && authorizeBtn.dataset.loading !== 'true') {
                authorizeBtn.disabled = selectedIds.length === 0 || graphAuthState.running || uploadAccountsState.batchAuthRunning;
                authorizeBtn.textContent = selectedIds.length > 1
                    ? `批量授权 (${selectedIds.length})`
                    : '批量授权';
            }
            if (deleteBtn && deleteBtn.dataset.loading !== 'true') {
                deleteBtn.disabled = selectedIds.length === 0 || graphAuthState.running || uploadAccountsState.batchAuthRunning;
                deleteBtn.textContent = selectedIds.length > 1
                    ? `批量删除 (${selectedIds.length})`
                    : '批量删除';
            }

            visibleCheckboxes.forEach(cb => {
                const id = normalizeUploadAccountId(cb.value);
                cb.checked = id ? uploadAccountsState.selectedIds.has(id) : false;
                cb.disabled = uploadAccountsState.editingRowId !== null
                    || graphAuthState.running
                    || uploadAccountsState.batchAuthRunning;
            });
        }

        function setUploadAccountSelected(accountId, selected) {
            const id = normalizeUploadAccountId(accountId);
            if (!id) return;
            if (selected) {
                uploadAccountsState.selectedIds.add(id);
            } else {
                uploadAccountsState.selectedIds.delete(id);
            }
            syncUploadAccountSelectionUi();
        }

        function toggleSelectVisibleUploadAccounts(forceChecked) {
            const checkboxes = Array.from(
                document.querySelectorAll('#uploadAccountsTableBody .upload-account-select-checkbox')
            );
            if (!checkboxes.length) return;
            const shouldSelect = typeof forceChecked === 'boolean'
                ? forceChecked
                : !checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => {
                const id = normalizeUploadAccountId(cb.value);
                if (!id) return;
                if (shouldSelect) {
                    uploadAccountsState.selectedIds.add(id);
                } else {
                    uploadAccountsState.selectedIds.delete(id);
                }
            });
            syncUploadAccountSelectionUi();
        }

        function clearUploadAccountSelection() {
            uploadAccountsState.selectedIds.clear();
            syncUploadAccountSelectionUi();
        }

        function renderAddUploadAccountTagOptions(selectedIds = []) {
            const container = document.getElementById('addUploadAccountTagOptions');
            if (!container || typeof buildTagFilterOptionsHtml !== 'function') return;
            const tags = typeof allTags !== 'undefined' && Array.isArray(allTags) ? allTags : [];
            container.innerHTML = buildTagFilterOptionsHtml(
                tags,
                selectedIds,
                'updateAddUploadAccountTagSummary'
            );
            updateAddUploadAccountTagSummary();
        }

        function updateAddUploadAccountTagSummary() {
            const summaryEl = document.getElementById('addUploadAccountTagTriggerText');
            const countEl = document.getElementById('addUploadAccountTagTriggerCount');
            if (!summaryEl || !countEl) return;
            const container = document.getElementById('addUploadAccountTagOptions');
            const selectedIds = typeof getTagFilterSelectedIds === 'function'
                ? getTagFilterSelectedIds(container)
                : [];
            const tags = typeof allTags !== 'undefined' && Array.isArray(allTags) ? allTags : [];
            const selectedItems = selectedIds.map(id => tags.find(t => t.id === id)).filter(Boolean);
            if (typeof updateTagFilterSummaryText === 'function') {
                updateTagFilterSummaryText(summaryEl, countEl, selectedItems, '未选择标签');
            }
        }

        function toggleAddUploadAccountTagDropdown(event) {
            event?.stopPropagation();
            const dropdown = document.getElementById('addUploadAccountTagDropdown');
            const searchInput = document.getElementById('addUploadAccountTagSearchInput');
            if (typeof toggleTagFilterDropdownState === 'function') {
                toggleTagFilterDropdownState(dropdown, searchInput, '');
            }
        }

        function filterAddUploadAccountTagOptions(keyword) {
            const container = document.getElementById('addUploadAccountTagOptions');
            if (typeof filterTagFilterOptions === 'function') {
                filterTagFilterOptions(keyword, container);
            }
        }

        function clearAddUploadAccountTagSelection(event) {
            event?.stopPropagation();
            const dropdown = document.getElementById('addUploadAccountTagDropdown');
            if (typeof clearTagFilterCheckboxes === 'function') {
                clearTagFilterCheckboxes(dropdown);
            }
            updateAddUploadAccountTagSummary();
        }

        function getAddUploadAccountSelectedTagIds() {
            const container = document.getElementById('addUploadAccountTagOptions');
            return typeof getTagFilterSelectedIds === 'function'
                ? getTagFilterSelectedIds(container)
                : [];
        }

        function prepareAddUploadAccountFormOptions() {
            if (typeof updateGroupSelects === 'function') {
                updateGroupSelects();
            }
            if (typeof loadTags === 'function' && (!Array.isArray(allTags) || !allTags.length)) {
                loadTags().then(() => renderAddUploadAccountTagOptions()).catch(() => {
                    renderAddUploadAccountTagOptions();
                });
            } else {
                renderAddUploadAccountTagOptions();
            }
        }

        function formatUploadAccountAuthorized(isAuthorized) {
            return isAuthorized
                ? '<span class="upload-accounts-badge upload-accounts-badge--yes">已授权</span>'
                : '<span class="upload-accounts-badge upload-accounts-badge--no">未授权</span>';
        }

        function formatUploadAccountTags(tags) {
            const safeTags = Array.isArray(tags) ? tags : [];
            if (!safeTags.length) {
                return '-';
            }

            const visibleTags = safeTags.slice(0, 2);
            const hiddenCount = Math.max(0, safeTags.length - visibleTags.length);
            const title = safeTags
                .map(tag => tag && tag.name ? String(tag.name) : '')
                .filter(Boolean)
                .join('、');
            const tagHtml = visibleTags.map(tag => {
                const tagName = tag && tag.name ? String(tag.name) : '';
                const tagColor = tag && tag.color ? String(tag.color) : '#64748b';
                return `
                    <span class="account-status-pill tag upload-accounts-tag-pill"
                        style="--pill-accent: ${escapeHtml(tagColor)}"
                        title="${escapeHtml(tagName)}">${escapeHtml(tagName)}</span>
                `;
            }).join('');
            const moreHtml = hiddenCount > 0
                ? `<span class="account-status-pill outline">+${hiddenCount}</span>`
                : '';

            return `<div class="upload-accounts-tags" title="${escapeHtml(title)}">${tagHtml}${moreHtml}</div>`;
        }

        function getUploadAccountPasswordMask(length) {
            return '*'.repeat(Math.max(6, Number(length) || 0));
        }

        function getUploadAccountEyeIcon(hidden) {
            if (!hidden) {
                return `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M3 3l18 18"></path>
                        <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"></path>
                        <path d="M9.5 5.5A10.5 10.5 0 0 1 12 5c6 0 9.5 7 9.5 7a17.6 17.6 0 0 1-2.1 3"></path>
                        <path d="M6.5 6.5C3.8 8.3 2.5 12 2.5 12s3.5 7 9.5 7a10 10 0 0 0 4.5-1.1"></path>
                    </svg>
                `;
            }
            return `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                </svg>
            `;
        }

        function formatUploadAccountPassword(item) {
            if (!item || !item.has_password) {
                return '-';
            }
            const plainPassword = typeof item.password === 'string' ? item.password : '';
            const maskedPassword = getUploadAccountPasswordMask(item.password_length || plainPassword.length);
            return `
                <span class="upload-accounts-password" data-password-visible="false">
                    <span class="upload-accounts-password-text upload-accounts-password-mask">${escapeHtml(maskedPassword)}</span>
                    <button class="upload-accounts-password-toggle" type="button"
                        data-upload-account-password="${escapeHtml(plainPassword)}"
                        aria-label="显示密码" title="显示密码">
                        ${getUploadAccountEyeIcon(true)}
                    </button>
                </span>
            `;
        }

        function getUploadAccountProxyDisplay(proxyUrl) {
            const normalizedProxy = String(proxyUrl || '').trim();
            if (!normalizedProxy) return '';
            try {
                const parsedProxy = new URL(normalizedProxy);
                if (!parsedProxy.host) return '已配置代理';
                parsedProxy.username = '';
                parsedProxy.password = '';
                return `${parsedProxy.protocol}//${parsedProxy.host}`;
            } catch (error) {
                return '已配置代理';
            }
        }

        function formatUploadAccountProxy(proxyUrl) {
            const displayProxy = getUploadAccountProxyDisplay(proxyUrl);
            if (!displayProxy) return '-';
            const escapedProxy = escapeHtml(displayProxy);
            return `<span class="upload-accounts-proxy" title="${escapedProxy}">${escapedProxy}</span>`;
        }

        function renderUploadAccountsRows(items) {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (!tbody) return;

            if (!Array.isArray(items) || items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" class="upload-accounts-empty">暂无数据</td></tr>';
                syncUploadAccountSelectionUi();
                return;
            }

            tbody.innerHTML = items.map(item => {
                const itemId = item.id ?? '';
                const itemEmail = item.email || '';
                const itemRemark = item.remark || '';
                const itemCreatedAt = item.created_at || '';
                const isEditing = uploadAccountsState.editingRowId === itemId;
                const selectDisabled = uploadAccountsState.editingRowId !== null
                    || graphAuthState.running
                    || uploadAccountsState.batchAuthRunning;
                const checkboxCell = `
                    <td>
                        <input type="checkbox"
                            class="upload-account-select-checkbox"
                            value="${escapeHtml(String(itemId))}"
                            ${selectDisabled ? 'disabled' : ''}
                            onchange="setUploadAccountSelected(${escapeHtml(String(itemId))}, this.checked)"
                            aria-label="选择 ${escapeHtml(itemEmail)}">
                    </td>
                `;

                if (isEditing) {
                    // 编辑状态
                    return `
                        <tr class="upload-accounts-row--editing" data-editing-id="${escapeHtml(String(itemId))}">
                            ${checkboxCell}
                            <td class="upload-accounts-cell-mono upload-accounts-cell-right">
                                <input type="text" class="upload-accounts-edit-input"
                                    id="edit-email-${escapeHtml(String(itemId))}"
                                    value="${escapeHtml(itemEmail)}"
                                    placeholder="邮箱" autocomplete="off">
                            </td>
                            <td class="upload-accounts-cell-right">
                                <input type="password" class="upload-accounts-edit-input"
                                    id="edit-password-${escapeHtml(String(itemId))}"
                                    placeholder="留空不改" autocomplete="off">
                            </td>
                            <td class="upload-accounts-edit-disabled">-</td>
                            <td class="upload-accounts-edit-disabled">-</td>
                            <td class="upload-accounts-cell-mono">${formatUploadAccountProxy(item.proxy_url)}</td>
                            <td>
                                <input type="text" class="upload-accounts-edit-input"
                                    id="edit-remark-${escapeHtml(String(itemId))}"
                                    value="${escapeHtml(itemRemark)}"
                                    placeholder="备注" autocomplete="off">
                            </td>
                            <td class="upload-accounts-edit-disabled">-</td>
                            <td>
                                <button class="btn btn-sm btn-primary" type="button" onclick="saveRowEdit(${escapeHtml(String(itemId))})">保存修改</button>
                                <button class="btn btn-sm btn-secondary" type="button" onclick="cancelRowEdit()">取消</button>
                            </td>
                        </tr>
                    `;
                } else {
                    // 正常显示状态
                    const authBtnLabel = item.is_authorized ? '重新授权' : '授权';
                    const editDisabled = uploadAccountsState.editingRowId !== null
                        || graphAuthState.running
                        || uploadAccountsState.batchAuthRunning;
                    const authBtn = `<button class="btn btn-sm btn-primary" type="button" style="width: 80px;" ${editDisabled ? 'disabled' : ''} data-graph-auth-account-id="${escapeHtml(String(itemId))}" data-graph-auth-email="${escapeHtml(itemEmail)}" data-graph-auth-password-length="${escapeHtml(String(item.password_length || 0))}">${authBtnLabel}</button>`;
                    const editBtn = `<button class="btn btn-sm btn-secondary" type="button" ${editDisabled ? 'disabled' : ''} onclick="enterRowEditMode(${escapeHtml(String(itemId))}, '${escapeHtml(itemEmail)}', '${escapeHtml(itemRemark)}')">修改</button>`;
                    const deleteBtn = `<button class="btn btn-sm btn-danger" type="button" ${editDisabled ? 'disabled' : ''} data-delete-account-id="${escapeHtml(String(itemId))}" data-delete-account-email="${escapeHtml(itemEmail)}">删除</button>`;
                    return `
                        <tr>
                            ${checkboxCell}
                            <td class="upload-accounts-cell-mono upload-accounts-cell-right">${escapeHtml(itemEmail)}</td>
                            <td class="upload-accounts-cell-mono upload-accounts-cell-right">${formatUploadAccountPassword(item)}</td>
                            <td>${formatUploadAccountAuthorized(item.is_authorized)}</td>
                            <td>${formatUploadAccountTags(item.tags)}</td>
                            <td class="upload-accounts-cell-mono">${formatUploadAccountProxy(item.proxy_url)}</td>
                            <td>${escapeHtml(itemRemark)}</td>
                            <td>${escapeHtml(itemCreatedAt)}</td>
                            <td>${authBtn}${editBtn}${deleteBtn}</td>
                        </tr>
                    `;
                }
            }).join('');
            syncUploadAccountSelectionUi();
        }

        function syncUploadAccountsPagination() {
            const info = document.getElementById('uploadAccountsPageInfo');
            if (info) {
                info.textContent = `共 ${uploadAccountsState.total} 条`;
            }
            const pageText = document.getElementById('uploadAccountsPageText');
            if (pageText) {
                pageText.textContent = `第 ${uploadAccountsState.page} / ${uploadAccountsState.totalPages} 页`;
            }
            const prevBtn = document.getElementById('uploadAccountsPrevBtn');
            const nextBtn = document.getElementById('uploadAccountsNextBtn');
            if (prevBtn) {
                prevBtn.disabled = uploadAccountsState.loading || uploadAccountsState.page <= 1;
            }
            if (nextBtn) {
                nextBtn.disabled = uploadAccountsState.loading
                    || uploadAccountsState.page >= uploadAccountsState.totalPages;
            }
            syncUploadAccountsPageSizeSelect();
        }

        function toggleUploadAccountPasswordVisibility(button) {
            const wrapper = button.closest('.upload-accounts-password');
            const textEl = wrapper ? wrapper.querySelector('.upload-accounts-password-text') : null;
            if (!wrapper || !textEl) return;

            const isVisible = wrapper.dataset.passwordVisible === 'true';
            const plainPassword = button.dataset.uploadAccountPassword || '';
            const maskedPassword = getUploadAccountPasswordMask(plainPassword.length);

            wrapper.dataset.passwordVisible = isVisible ? 'false' : 'true';
            textEl.textContent = isVisible ? maskedPassword : plainPassword;
            textEl.classList.toggle('upload-accounts-password-mask', isVisible);
            button.setAttribute('aria-label', isVisible ? '显示密码' : '隐藏密码');
            button.setAttribute('title', isVisible ? '显示密码' : '隐藏密码');
            button.innerHTML = getUploadAccountEyeIcon(isVisible);
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-upload-account-password]');
            if (!button) return;
            toggleUploadAccountPasswordVisibility(button);
        });

        async function loadUploadAccounts() {
            const requestSequence = ++uploadAccountsState.requestSequence;
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="9" class="upload-accounts-empty">正在加载...</td></tr>';
            }
            uploadAccountsState.loading = true;
            syncUploadAccountsPagination();

            try {
                const params = new URLSearchParams({
                    page: String(uploadAccountsState.page),
                    page_size: String(uploadAccountsState.pageSize),
                    auth_status: uploadAccountsState.authStatus,
                });
                if (uploadAccountsState.keyword) {
                    params.set('keyword', uploadAccountsState.keyword);
                }
                const response = await fetch(`/api/outlook-upload-accounts?${params.toString()}`);
                const data = await response.json();
                if (requestSequence !== uploadAccountsState.requestSequence) return;
                if (data.success) {
                    uploadAccountsState.total = Number(data.total) || 0;
                    uploadAccountsState.totalPages = Math.max(1, Number(data.total_pages) || 1);
                    uploadAccountsState.page = Math.max(1, Number(data.page) || 1);
                    uploadAccountsState.pageSize = normalizeUploadAccountsPageSize(
                        data.page_size || uploadAccountsState.pageSize
                    );
                    uploadAccountsState.currentData = data.items || [];
                    renderUploadAccountsRows(uploadAccountsState.currentData);
                } else {
                    uploadAccountsState.currentData = [];
                    renderUploadAccountsRows([]);
                    handleApiError(data, '加载 Outlook 上传账号失败');
                }
            } catch (error) {
                if (requestSequence !== uploadAccountsState.requestSequence) return;
                uploadAccountsState.currentData = [];
                renderUploadAccountsRows([]);
                showToast('加载 Outlook 上传账号失败: ' + error.message, 'error');
            } finally {
                if (requestSequence === uploadAccountsState.requestSequence) {
                    uploadAccountsState.loading = false;
                    syncUploadAccountsPagination();
                }
            }
        }

        function changeUploadAccountsPage(delta) {
            if (uploadAccountsState.loading) return;
            const target = uploadAccountsState.page + delta;
            if (target < 1 || target > uploadAccountsState.totalPages) return;
            uploadAccountsState.page = target;
            loadUploadAccounts();
        }

        function handleUploadAccountsAuthStatusChange(value) {
            const nextStatus = normalizeUploadAccountsAuthStatus(value);
            if (nextStatus === uploadAccountsState.authStatus) {
                syncUploadAccountsAuthStatusFilter();
                return;
            }
            uploadAccountsState.authStatus = nextStatus;
            uploadAccountsState.page = 1;
            // 筛选条件变化后清空选择，避免对旧筛选结果做批量操作
            clearUploadAccountSelection();
            syncUploadAccountsAuthStatusFilter();
            loadUploadAccounts();
        }

        function handleUploadAccountsPageSizeChange(value) {
            const nextPageSize = normalizeUploadAccountsPageSize(value);
            if (nextPageSize === uploadAccountsState.pageSize) {
                syncUploadAccountsPageSizeSelect();
                return;
            }
            uploadAccountsState.pageSize = nextPageSize;
            uploadAccountsState.page = 1;
            // 分页粒度变化会改变可见结果集，清空选择避免误操作
            clearUploadAccountSelection();
            localStorage.setItem(
                UPLOAD_ACCOUNTS_PAGE_SIZE_STORAGE_KEY,
                String(nextPageSize),
            );
            syncUploadAccountsPageSizeSelect();
            loadUploadAccounts();
        }

        function searchUploadAccounts() {
            const input = document.getElementById('uploadAccountsSearch');
            const nextKeyword = input ? input.value.trim() : '';
            if (nextKeyword === uploadAccountsState.keyword) {
                uploadAccountsState.page = 1;
                loadUploadAccounts();
                return;
            }
            uploadAccountsState.keyword = nextKeyword;
            uploadAccountsState.page = 1;
            // 搜索条件变化后清空选择，批量操作仅针对当前筛选结果
            clearUploadAccountSelection();
            loadUploadAccounts();
        }

        function reloadUploadAccounts() {
            loadUploadAccounts();
        }

        function showOutlookUploadAccountsModal() {
            uploadAccountsState.page = 1;
            uploadAccountsState.keyword = '';
            uploadAccountsState.authStatus = 'all';
            uploadAccountsState.selectedIds.clear();
            uploadAccountsState.batchAuthQueue = [];
            uploadAccountsState.batchAuthRunning = false;
            const input = document.getElementById('uploadAccountsSearch');
            if (input) input.value = '';
            initializeUploadAccountsPageSize();
            syncUploadAccountsAuthStatusFilter();
            resetGraphAuthPanel();
            clearAddAccountForm();
            prepareAddUploadAccountFormOptions();
            showModal('outlookUploadAccountsModal');
            loadUploadAccounts();
        }

        function hideOutlookUploadAccountsModal() {
            uploadAccountsState.requestSequence += 1;
            uploadAccountsState.loading = false;
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            graphAuthState.running = false;
            uploadAccountsState.batchAuthQueue = [];
            uploadAccountsState.batchAuthRunning = false;
            hideModal('outlookUploadAccountsModal');
        }

        function openBatchImportFromUploadGuide() {
            hideOutlookUploadAccountsModal();
            if (typeof showAddAccountModal === 'function') {
                showAddAccountModal();
            }
        }

        function openOauthSaveFromUploadGuide() {
            hideOutlookUploadAccountsModal();
            if (typeof showGetRefreshTokenModal === 'function') {
                showGetRefreshTokenModal();
            }
        }

        // ==================== 添加上传账号 ====================

        function toggleAddAccountPanel() {
            const container = document.getElementById('addAccountFormContainer');
            const icon = document.getElementById('toggleAddPanelIcon');
            if (!container || !icon) return;

            const isCollapsed = container.classList.toggle('is-collapsed');
            icon.textContent = isCollapsed ? '▶' : '▼';
        }

        function clearAddAccountForm() {
            const prefix = document.getElementById('addUploadAccountEmailPrefix');
            const domain = document.getElementById('addUploadAccountEmailDomain');
            const password = document.getElementById('addUploadAccountPassword');
            const remark = document.getElementById('addUploadAccountRemark');
            const proxy = document.getElementById('addUploadAccountProxyUrl');
            if (prefix) prefix.value = '';
            if (domain) domain.value = '@outlook.com';
            if (password) password.value = '';
            if (remark) remark.value = '';
            if (proxy) proxy.value = '';
            document.getElementById('addUploadAccountTagDropdown')?.classList.remove('open');
            renderAddUploadAccountTagOptions();
            if (typeof updateGroupSelects === 'function') {
                updateGroupSelects();
            }
        }

        async function submitAddUploadAccount() {
            const emailPrefix = document.getElementById('addUploadAccountEmailPrefix').value.trim();
            const emailDomain = document.getElementById('addUploadAccountEmailDomain').value;
            const password = document.getElementById('addUploadAccountPassword').value.trim();
            const remark = document.getElementById('addUploadAccountRemark').value.trim();
            const groupId = parseInt(document.getElementById('addUploadAccountGroupSelect')?.value || '0', 10) || 1;
            const proxyUrl = document.getElementById('addUploadAccountProxyUrl')?.value.trim() || '';
            const tagIds = getAddUploadAccountSelectedTagIds();

            if (!emailPrefix) {
                showToast('请输入邮箱前缀', 'error');
                return;
            }
            if (!password) {
                showToast('请输入密码', 'error');
                return;
            }

            const email = emailPrefix + emailDomain;

            const btn = document.getElementById('submitAddUploadAccountBtn');
            if (btn) btn.disabled = true;

            try {
                const response = await fetch('/api/outlook-upload-accounts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email,
                        password,
                        remark,
                        group_id: groupId,
                        proxy_url: proxyUrl,
                        tag_ids: tagIds,
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showToast('添加成功', 'success');
                    clearAddAccountForm();
                    reloadUploadAccounts();
                } else {
                    handleApiError(data, '添加失败');
                }
            } catch (error) {
                showToast('添加失败: ' + error.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        // ==================== 修改上传账号 ====================

        function enterRowEditMode(accountId, email, remark) {
            if (uploadAccountsState.editingRowId !== null) {
                showToast('请先完成当前编辑', 'warning');
                return;
            }
            uploadAccountsState.editingRowId = accountId;
            renderUploadAccountsRows(uploadAccountsState.currentData);

            // 聚焦到备注输入框
            setTimeout(() => {
                const remarkInput = document.getElementById(`edit-remark-${accountId}`);
                if (remarkInput) remarkInput.focus();
            }, 50);
        }

        function cancelRowEdit() {
            uploadAccountsState.editingRowId = null;
            renderUploadAccountsRows(uploadAccountsState.currentData);
        }

        async function saveRowEdit(accountId) {
            const email = document.getElementById(`edit-email-${accountId}`)?.value.trim();
            const password = document.getElementById(`edit-password-${accountId}`)?.value.trim();
            const remark = document.getElementById(`edit-remark-${accountId}`)?.value.trim();

            if (!accountId) {
                showToast('未选中账号，无法修改', 'error');
                return;
            }
            if (!email) {
                showToast('请输入邮箱', 'error');
                return;
            }

            const payload = { email, remark };
            // 密码留空表示保持原密码，不下发该字段
            if (password !== '') {
                payload.password = password;
            }

            // 禁用保存按钮
            const saveBtn = document.querySelector(`[onclick="saveRowEdit(${accountId})"]`);
            if (saveBtn) saveBtn.disabled = true;

            try {
                const response = await fetch(`/api/outlook-upload-accounts/${encodeURIComponent(accountId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (data.success) {
                    showToast('修改成功', 'success');
                    uploadAccountsState.editingRowId = null;
                    reloadUploadAccounts();
                } else {
                    handleApiError(data, '修改失败');
                }
            } catch (error) {
                showToast('修改失败: ' + error.message, 'error');
            } finally {
                if (saveBtn) saveBtn.disabled = false;
            }
        }

        // ==================== Outlook IMAP OAuth 授权 ====================

        const GRAPH_AUTH_LOG_PLACEHOLDER = '点击账号「授权 / 重新授权」后，授权日志会显示在这里。';
        const GRAPH_AUTH_MODE_LABELS = {
            imap: 'Outlook IMAP',
            graph: 'Graph-only（不含 IMAP 权限）',
        };

        function setGraphAuthStatus(state, text) {
            const statusEl = document.getElementById('graphAuthStatus');
            if (!statusEl) return;
            statusEl.dataset.state = state;
            statusEl.textContent = text;
        }

        function resetGraphAuthPanel() {
            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }
            graphAuthState.accountId = null;
            graphAuthState.email = '';
            graphAuthState.secretLength = 0;
            graphAuthState.running = false;
            const logEl = document.getElementById('graphAuthLog');
            if (logEl) logEl.textContent = GRAPH_AUTH_LOG_PLACEHOLDER;
            setGraphAuthStatus('idle', '空闲');
        }

        function setUploadAuthButtonsDisabled(disabled) {
            document.querySelectorAll('#uploadAccountsTableBody [data-graph-auth-account-id]').forEach(btn => {
                btn.disabled = disabled;
            });
            syncUploadAccountSelectionUi();
        }

        function continueBatchAuthQueue() {
            if (!uploadAccountsState.batchAuthRunning) {
                return;
            }
            const next = uploadAccountsState.batchAuthQueue.shift();
            if (!next) {
                uploadAccountsState.batchAuthRunning = false;
                appendGraphAuthLog('');
                appendGraphAuthLog('批量授权队列已完成');
                setGraphAuthStatus('success', '批量完成');
                const authorizeBtn = document.getElementById('batchAuthorizeUploadAccountsBtn');
                if (authorizeBtn) {
                    authorizeBtn.dataset.loading = 'false';
                }
                setUploadAuthButtonsDisabled(false);
                loadUploadAccounts();
                return;
            }
            const remaining = uploadAccountsState.batchAuthQueue.length;
            appendGraphAuthLog('');
            appendGraphAuthLog(`批量授权：开始处理 ${next.email || next.accountId}（剩余 ${remaining}）`);
            startGraphAuthForAccount(next.accountId, next.email, next.passwordLength, { fromBatch: true });
        }

        function appendGraphAuthLog(message) {
            const logEl = document.getElementById('graphAuthLog');
            if (!logEl) return;

            const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
            logEl.textContent += `\n[${timestamp}] ${message}`;
            logEl.scrollTop = logEl.scrollHeight;
        }

        function getGraphAuthMode() {
            const checked = document.querySelector('input[name="graphAuthMode"]:checked');
            return checked && checked.value === 'graph' ? 'graph' : 'imap';
        }

        function getGraphAuthModeLabel(mode) {
            return GRAPH_AUTH_MODE_LABELS[mode] || GRAPH_AUTH_MODE_LABELS.imap;
        }

        async function startGraphAuthForAccount(accountId, email, passwordLength, options = {}) {
            const fromBatch = !!options.fromBatch;
            if (graphAuthState.running) {
                showToast('正在授权中，请等待当前任务完成', 'warning');
                return;
            }
            if (!accountId) {
                showToast('请选择要授权的账号', 'error');
                return;
            }

            if (graphAuthState.eventSource) {
                graphAuthState.eventSource.close();
                graphAuthState.eventSource = null;
            }

            graphAuthState.accountId = accountId;
            graphAuthState.email = email;
            graphAuthState.secretLength = Number(passwordLength) || 0;
            graphAuthState.running = true;
            const authMode = getGraphAuthMode();
            const authModeLabel = getGraphAuthModeLabel(authMode);

            setUploadAuthButtonsDisabled(true);
            setGraphAuthStatus('running', fromBatch ? '批量授权中' : '授权中');

            const logEl = document.getElementById('graphAuthLog');
            if (logEl && !fromBatch) {
                logEl.textContent = `开始 ${authModeLabel} OAuth 授权流程...`;
            } else if (logEl && fromBatch && !String(logEl.textContent || '').includes('批量授权')) {
                logEl.textContent = `开始批量 ${authModeLabel} OAuth 授权...`;
            }
            const startTime = Date.now();

            const finishAuth = (state, statusText) => {
                graphAuthState.running = false;
                if (fromBatch || uploadAccountsState.batchAuthRunning) {
                    setGraphAuthStatus(state, statusText);
                    // 批量队列继续；按钮状态由队列结束时统一恢复
                    continueBatchAuthQueue();
                    return;
                }
                setUploadAuthButtonsDisabled(false);
                setGraphAuthStatus(state, statusText);
            };

            try {
                appendGraphAuthLog('邮箱: ' + email);
                appendGraphAuthLog('密码: ' + '*'.repeat(Math.max(6, graphAuthState.secretLength)));
                appendGraphAuthLog('授权模式: ' + authModeLabel);
                appendGraphAuthLog('');
                appendGraphAuthLog('正在创建授权任务...');
                appendGraphAuthLog('');

                const response = await fetch('/api/oauth/graph-extract-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        account_id: accountId,
                        mode: authMode
                    })
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.stream_url) {
                    appendGraphAuthLog('创建授权任务失败: ' + (data.error || '未知错误'));
                    showToast(authModeLabel + ' 授权失败: ' + (data.error || '未知错误'), 'error');
                    finishAuth('error', '失败');
                    return;
                }

                appendGraphAuthLog('授权任务已创建，等待后端日志...');
                graphAuthState.eventSource = new EventSource(data.stream_url);
                graphAuthState.eventSource.onmessage = (event) => {
                    let payload;
                    try {
                        payload = JSON.parse(event.data);
                    } catch (parseError) {
                        appendGraphAuthLog(event.data);
                        return;
                    }

                    if (payload.type === 'start' && payload.message) {
                        appendGraphAuthLog(payload.message);
                    } else if (payload.type === 'log') {
                        appendGraphAuthLog(payload.message || '');
                    } else if (payload.type === 'success') {
                        appendGraphAuthLog('');
                        appendGraphAuthLog('授权成功，已保存到正式账号');
                        appendGraphAuthLog('Client ID: ' + (payload.client_id || '-'));
                        appendGraphAuthLog(payload.created ? '保存方式: 新增正式账号' : '保存方式: 更新已有正式账号');
                        showToast(getGraphAuthModeLabel(payload.mode || authMode) + ' 授权成功，已保存到正式账号', 'success');
                    } else if (payload.type === 'error') {
                        appendGraphAuthLog('');
                        appendGraphAuthLog('授权失败: ' + (payload.message || '未知错误'));
                        if (payload.details) {
                            appendGraphAuthLog(payload.details);
                        }
                        showToast(getGraphAuthModeLabel(payload.mode || authMode) + ' 授权失败: ' + (payload.message || '未知错误'), 'error');
                    } else if (payload.type === 'complete') {
                        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                        appendGraphAuthLog('');
                        appendGraphAuthLog('耗时: ' + elapsed + ' 秒');
                        if (graphAuthState.eventSource) {
                            graphAuthState.eventSource.close();
                            graphAuthState.eventSource = null;
                        }
                        finishAuth(payload.success ? 'success' : 'error', payload.success ? '成功' : '失败');
                        if (payload.success && !fromBatch && !uploadAccountsState.batchAuthRunning) {
                            setTimeout(() => {
                                loadUploadAccounts();
                            }, 1000);
                        }
                    }
                };
                graphAuthState.eventSource.onerror = () => {
                    appendGraphAuthLog('授权日志连接中断');
                    if (graphAuthState.eventSource) {
                        graphAuthState.eventSource.close();
                        graphAuthState.eventSource = null;
                    }
                    finishAuth('error', '连接中断');
                };
            } catch (error) {
                appendGraphAuthLog('');
                appendGraphAuthLog('异常信息: ' + error.message);

                showToast('授权请求失败: ' + error.message, 'error');
                finishAuth('error', '失败');
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-graph-auth-account-id]');
            if (!button) return;
            if (uploadAccountsState.batchAuthRunning) {
                showToast('批量授权进行中，请等待完成', 'warning');
                return;
            }
            startGraphAuthForAccount(
                Number(button.dataset.graphAuthAccountId),
                button.dataset.graphAuthEmail || '',
                Number(button.dataset.graphAuthPasswordLength) || 0
            );
        });

        async function authorizeSelectedUploadAccounts() {
            if (graphAuthState.running || uploadAccountsState.batchAuthRunning) {
                showToast('正在授权中，请等待当前任务完成', 'warning');
                return;
            }
            const selectedIds = getSelectedUploadAccountIds();
            if (!selectedIds.length) {
                showToast('请先选择要授权的账号', 'error');
                return;
            }

            const queue = selectedIds.map(accountId => {
                const item = (uploadAccountsState.currentData || []).find(row => Number(row.id) === accountId) || {};
                return {
                    accountId,
                    email: item.email || '',
                    passwordLength: item.password_length || 0,
                };
            });

            if (!(await showConfirmModal(
                `确定按当前授权模式串行授权所选 ${queue.length} 个账号吗？`,
                { title: '批量授权', confirmText: '开始授权', danger: false }
            ))) {
                return;
            }

            uploadAccountsState.batchAuthQueue = queue;
            uploadAccountsState.batchAuthRunning = true;
            const authorizeBtn = document.getElementById('batchAuthorizeUploadAccountsBtn');
            if (authorizeBtn) {
                authorizeBtn.dataset.loading = 'true';
                authorizeBtn.disabled = true;
                authorizeBtn.textContent = '批量授权中...';
            }
            syncUploadAccountSelectionUi();
            const logEl = document.getElementById('graphAuthLog');
            if (logEl) {
                logEl.textContent = `开始批量授权，共 ${queue.length} 个账号（串行）`;
            }
            continueBatchAuthQueue();
        }

        async function deleteUploadAccount(accountId, email) {
            if (!(await showConfirmModal(`确定要删除账号 ${email || ''} 吗？此操作不可恢复。`, { title: '删除上传账号', confirmText: '确认删除' }))) {
                return;
            }

            try {
                const response = await fetch(`/api/outlook-upload-accounts/${encodeURIComponent(accountId)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (data.success) {
                    showToast('删除成功', 'success');
                    uploadAccountsState.selectedIds.delete(normalizeUploadAccountId(accountId));
                    loadUploadAccounts();
                } else {
                    handleApiError(data, '删除失败');
                }
            } catch (error) {
                showToast('删除失败: ' + error.message, 'error');
            }
        }

        async function deleteSelectedUploadAccounts() {
            if (graphAuthState.running || uploadAccountsState.batchAuthRunning) {
                showToast('授权进行中，请稍后再删除', 'warning');
                return;
            }
            const accountIds = getSelectedUploadAccountIds();
            if (!accountIds.length) {
                showToast('请先选择要删除的账号', 'error');
                return;
            }
            if (!(await showConfirmModal(
                `确定要删除所选 ${accountIds.length} 个上传账号吗？此操作不可恢复。`,
                { title: '批量删除上传账号', confirmText: '确认删除' }
            ))) {
                return;
            }

            const deleteBtn = document.getElementById('batchDeleteUploadAccountsBtn');
            if (deleteBtn) {
                deleteBtn.dataset.loading = 'true';
                deleteBtn.disabled = true;
                deleteBtn.textContent = '删除中...';
            }

            try {
                const response = await fetch('/api/outlook-upload-accounts/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds }),
                });
                const data = await response.json();
                if (data.success) {
                    showToast(data.message || `已删除 ${data.deleted || accountIds.length} 个账号`, 'success');
                    accountIds.forEach(id => uploadAccountsState.selectedIds.delete(id));
                    loadUploadAccounts();
                } else {
                    handleApiError(data, '批量删除失败');
                }
            } catch (error) {
                showToast('批量删除失败: ' + error.message, 'error');
            } finally {
                if (deleteBtn) {
                    deleteBtn.dataset.loading = 'false';
                }
                syncUploadAccountSelectionUi();
            }
        }

        document.addEventListener('click', (event) => {
            const button = event.target.closest('[data-delete-account-id]');
            if (!button) return;
            deleteUploadAccount(
                Number(button.dataset.deleteAccountId),
                button.dataset.deleteAccountEmail || ''
            );
        });

        // ==================== 从正式账号加入自动授权 ====================

        async function queueAccountForOutlookAutoAuth(accountId, email) {
            if (!Number.isFinite(accountId) || accountId <= 0) {
                showToast('账号信息无效，无法加入自动授权', 'error');
                return;
            }
            try {
                const response = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/outlook-auto-auth`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const data = await response.json();
                if (data.success) {
                    const msg = data.status === 'updated'
                        ? `已重新加入自动授权：${data.email || email || ''}`
                        : `已加入自动授权：${data.email || email || ''}`;
                    showToast(msg, 'success');
                    const modal = document.getElementById('outlookUploadAccountsModal');
                    if (modal && modal.classList.contains('show')) {
                        loadUploadAccounts();
                    }
                } else {
                    handleApiError(data, '加入自动授权失败');
                }
            } catch (error) {
                showToast('加入自动授权失败: ' + error.message, 'error');
            }
        }

        window.queueAccountForOutlookAutoAuth = queueAccountForOutlookAutoAuth;
        window.setUploadAccountSelected = setUploadAccountSelected;
        window.toggleSelectVisibleUploadAccounts = toggleSelectVisibleUploadAccounts;
        window.clearUploadAccountSelection = clearUploadAccountSelection;
        window.authorizeSelectedUploadAccounts = authorizeSelectedUploadAccounts;
        window.deleteSelectedUploadAccounts = deleteSelectedUploadAccounts;
        window.toggleAddUploadAccountTagDropdown = toggleAddUploadAccountTagDropdown;
        window.filterAddUploadAccountTagOptions = filterAddUploadAccountTagOptions;
        window.clearAddUploadAccountTagSelection = clearAddUploadAccountTagSelection;
        window.updateAddUploadAccountTagSummary = updateAddUploadAccountTagSummary;

        document.addEventListener('click', (event) => {
            if (!event.target.closest('#addUploadAccountTagDropdown')) {
                document.getElementById('addUploadAccountTagDropdown')?.classList.remove('open');
            }
        });
