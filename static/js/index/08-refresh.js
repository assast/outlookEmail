        /* global closeAccountActionMenus, closeFullscreenEmail, closeMobilePanels, closeNavbarActionsMenu, closeTagFilterDropdown, currentGroupId, escapeHtml, formatDate, handleApiError, hideModal, invalidateAccountCaches, loadGroups, loadAccountsByGroup, markCurrentReleaseNoticeSeen, refreshVisibleAccountList, resetSelectedAccountViewIfDeleted, showEditAccountModal, showModal, showToast, updateModalBodyState */

        // ==================== Token 刷新管理 ====================

        const refreshModalState = {
            query: '',
            status: 'all',
            page: 1,
            pageSize: 200,
            total: 0,
            items: [],
            stats: null,
            currentRefreshingAccountId: null,
            searchTimer: 0,
            eventSource: null,
            isRunning: false,
            stopRequested: false,
            runtimeLogs: [],
            selectedAccountIds: new Set(),
            selectionMode: false,
            selectionAnchorId: null,
            selectionDragState: null,
            selectionSuppressClickUntil: 0,
        };
        const REFRESH_PAGE_SIZE_STORAGE_KEY = 'outlook_refresh_page_size';
        const REFRESH_PAGE_SIZE_DEFAULT = 200;
        const REFRESH_PAGE_SIZE_MAX = 10000;

        function getRefreshStatusMeta(status) {
            switch (String(status || '').toLowerCase()) {
                case 'running':
                    return { label: '刷新中', className: 'running' };
                case 'success':
                    return { label: '成功', className: 'success' };
                case 'failed':
                    return { label: '失败', className: 'failed' };
                case 'partial_failed':
                    return { label: '部分失败', className: 'partial-failed' };
                case 'never':
                    return { label: '从未刷新', className: 'never' };
                default:
                    return { label: '未执行', className: 'never' };
            }
        }

        function renderRefreshStatusBadge(status, isRunning = false) {
            const meta = isRunning ? getRefreshStatusMeta('running') : getRefreshStatusMeta(status);
            return `<span class="refresh-status-pill ${meta.className}">${meta.label}</span>`;
        }

        function closeRefreshEventSource(source = refreshModalState.eventSource) {
            if (!source) {
                return;
            }
            try {
                source.close();
            } catch (error) {
                console.warn('关闭 Token 刷新 EventSource 失败:', error);
            }
            if (refreshModalState.eventSource === source) {
                refreshModalState.eventSource = null;
            }
        }

        function setRefreshSnapshotCounts(total = 0, success = 0, failed = 0) {
            const totalEl = document.getElementById('totalRefreshCount');
            const successEl = document.getElementById('successRefreshCount');
            const failedEl = document.getElementById('failedRefreshCount');

            if (totalEl) {
                totalEl.textContent = String(Math.max(0, Number(total || 0)));
            }
            if (successEl) {
                successEl.textContent = String(Math.max(0, Number(success || 0)));
            }
            if (failedEl) {
                failedEl.textContent = String(Math.max(0, Number(failed || 0)));
            }
        }

        function syncRefreshActionButtons() {
            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = refreshModalState.isRunning;
                refreshAllBtn.textContent = refreshModalState.isRunning
                    ? (refreshModalState.stopRequested ? '停止中...' : '刷新中...')
                    : '全量刷新';
            }

            const stopRefreshBtn = document.getElementById('stopRefreshBtn');
            if (stopRefreshBtn) {
                stopRefreshBtn.hidden = !refreshModalState.isRunning;
                stopRefreshBtn.disabled = !refreshModalState.isRunning || refreshModalState.stopRequested;
                stopRefreshBtn.textContent = refreshModalState.stopRequested ? '停止中...' : '停止任务';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = refreshModalState.isRunning;
                retryFailedBtn.textContent = '重试失败';
            }

            syncRefreshBatchControls();
            syncRefreshPaginationControls();
        }

        function updateRefreshLogSummary(text = '暂无任务日志') {
            const summaryEl = document.getElementById('refreshLogsSummary');
            if (summaryEl) {
                summaryEl.textContent = text;
            }
        }

        function renderRefreshRuntimeLogs() {
            const container = document.getElementById('refreshLogsList');
            if (!container) {
                return;
            }
            if (!refreshModalState.runtimeLogs.length) {
                container.innerHTML = '<div class="refresh-log-empty">暂无任务日志</div>';
                return;
            }

            container.innerHTML = refreshModalState.runtimeLogs.map(log => `
                <article class="refresh-log-item refresh-log-item--${escapeHtml(log.level || 'info')}">
                    <div class="refresh-log-item__head">
                        <strong class="refresh-log-item__title">${escapeHtml(log.title || '-')}</strong>
                        <span class="refresh-log-item__time">${escapeHtml(log.time || '-')}</span>
                    </div>
                    ${log.detail ? `<div class="refresh-log-item__detail">${escapeHtml(log.detail)}</div>` : ''}
                </article>
            `).join('');
        }

        function appendRefreshRuntimeLog(level, title, detail = '') {
            refreshModalState.runtimeLogs.unshift({
                level: String(level || 'info').toLowerCase(),
                title: String(title || '').trim() || '任务更新',
                detail: String(detail || '').trim(),
                time: new Date().toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                }),
            });
            if (refreshModalState.runtimeLogs.length > 300) {
                refreshModalState.runtimeLogs.length = 300;
            }
            renderRefreshRuntimeLogs();
        }

        function resetRefreshModalRuntime(force = false) {
            if (refreshModalState.searchTimer) {
                window.clearTimeout(refreshModalState.searchTimer);
                refreshModalState.searchTimer = 0;
            }
            if (refreshModalState.isRunning && !force) {
                syncRefreshActionButtons();
                renderRefreshRuntimeLogs();
                return;
            }
            closeRefreshEventSource();
            refreshModalState.currentRefreshingAccountId = null;
            refreshModalState.isRunning = false;
            refreshModalState.stopRequested = false;
            syncRefreshActionButtons();
        }

        function updateRefreshStatusFilterButtons() {
            document.querySelectorAll('#refreshModal .refresh-filter-chip').forEach(btn => {
                btn.classList.toggle('is-active', btn.dataset.status === refreshModalState.status);
            });
        }

        function normalizeRefreshPageSize(value) {
            const parsed = parseInt(value, 10);
            if (!Number.isFinite(parsed)) {
                return REFRESH_PAGE_SIZE_DEFAULT;
            }
            return Math.max(1, Math.min(parsed, REFRESH_PAGE_SIZE_MAX));
        }

        function getRefreshTotalPages() {
            const pageSize = normalizeRefreshPageSize(refreshModalState.pageSize);
            const total = Math.max(0, Number(refreshModalState.total || 0));
            return Math.max(1, Math.ceil(total / pageSize));
        }

        function getRefreshPaginationMarkup() {
            return `
                <div class="refresh-pagination" aria-label="Token 刷新管理分页">
                    <select id="refreshPageSizeSelect" class="refresh-pagination__select"
                        onchange="handleRefreshPageSizeChange(this.value)">
                        <option value="100">每页 100</option>
                        <option value="200" selected>每页 200</option>
                        <option value="500">每页 500</option>
                        <option value="1000">每页 1000</option>
                        <option value="2000">每页 2000</option>
                        <option value="5000">每页 5000</option>
                        <option value="10000">每页 10000</option>
                    </select>
                    <div class="refresh-pagination__controls">
                        <button class="refresh-pagination__btn" type="button" id="refreshPrevPageBtn"
                            onclick="changeRefreshPage(-1)">上一页</button>
                        <label class="refresh-pagination__page" for="refreshPageInput">
                            <span>第</span>
                            <input type="number" id="refreshPageInput" min="1" value="1"
                                onchange="goToRefreshPage(this.value)"
                                onkeydown="handleRefreshPageInputKeydown(event)">
                            <span id="refreshTotalPagesText">/ 1 页</span>
                        </label>
                        <button class="refresh-pagination__btn" type="button" id="refreshNextPageBtn"
                            onclick="changeRefreshPage(1)">下一页</button>
                    </div>
                </div>
            `;
        }

        function ensureRefreshPaginationControls() {
            if (document.getElementById('refreshPageSizeSelect')) {
                return;
            }

            const listActions = document.querySelector('#refreshModal .refresh-list-panel__actions');
            const mount = document.getElementById('refreshPaginationMount');
            if (mount && listActions?.contains(mount)) {
                mount.innerHTML = getRefreshPaginationMarkup();
                return;
            }
            if (listActions) {
                listActions.insertAdjacentHTML('afterbegin', getRefreshPaginationMarkup());
                return;
            }

            if (mount) {
                mount.innerHTML = getRefreshPaginationMarkup();
                return;
            }

            const toolbarActions = document.querySelector('#refreshModal .refresh-toolbar__actions');
            if (toolbarActions) {
                toolbarActions.insertAdjacentHTML('beforebegin', getRefreshPaginationMarkup());
            }
        }

        function syncRefreshPageSizeSelect() {
            const select = document.getElementById('refreshPageSizeSelect');
            if (!select) {
                return;
            }
            const pageSize = normalizeRefreshPageSize(refreshModalState.pageSize);
            const hasMatchingOption = Array.from(select.options)
                .some(option => option.value === String(pageSize));
            if (!hasMatchingOption) {
                refreshModalState.pageSize = REFRESH_PAGE_SIZE_DEFAULT;
            }
            select.value = String(normalizeRefreshPageSize(refreshModalState.pageSize));
        }

        function syncRefreshPaginationControls() {
            refreshModalState.page = Math.max(1, parseInt(refreshModalState.page, 10) || 1);
            refreshModalState.pageSize = normalizeRefreshPageSize(refreshModalState.pageSize);
            syncRefreshPageSizeSelect();

            const totalPages = getRefreshTotalPages();
            const visiblePage = Math.min(refreshModalState.page, totalPages);
            const pageInput = document.getElementById('refreshPageInput');
            if (pageInput) {
                pageInput.value = String(visiblePage);
                pageInput.max = String(totalPages);
                pageInput.disabled = refreshModalState.isRunning;
            }

            const totalPagesText = document.getElementById('refreshTotalPagesText');
            if (totalPagesText) {
                totalPagesText.textContent = `/ ${totalPages} 页`;
            }

            const prevBtn = document.getElementById('refreshPrevPageBtn');
            const nextBtn = document.getElementById('refreshNextPageBtn');
            if (prevBtn) {
                prevBtn.disabled = refreshModalState.isRunning || refreshModalState.page <= 1;
            }
            if (nextBtn) {
                nextBtn.disabled = refreshModalState.isRunning || refreshModalState.page >= totalPages || refreshModalState.total <= 0;
            }

            const pageSizeSelect = document.getElementById('refreshPageSizeSelect');
            if (pageSizeSelect) {
                pageSizeSelect.disabled = refreshModalState.isRunning;
            }
        }

        function initRefreshPaginationSettings() {
            ensureRefreshPaginationControls();
            refreshModalState.pageSize = normalizeRefreshPageSize(
                localStorage.getItem(REFRESH_PAGE_SIZE_STORAGE_KEY) || refreshModalState.pageSize
            );
            syncRefreshPaginationControls();
        }

        function renderRefreshStats(stats) {
            refreshModalState.stats = stats || null;
            setRefreshSnapshotCounts(stats?.total ?? 0, stats?.success_count ?? 0, stats?.failed_count ?? 0);
            document.getElementById('refreshFilterCountAll').textContent = String(stats?.total ?? 0);
            document.getElementById('refreshFilterCountSuccess').textContent = String(stats?.success_count ?? 0);
            document.getElementById('refreshFilterCountFailed').textContent = String(stats?.failed_count ?? 0);
            document.getElementById('refreshFilterCountNever').textContent = String(stats?.never_count ?? 0);
        }

        function getVisibleRefreshAccountIds() {
            return refreshModalState.items
                .map(item => Number(item.id))
                .filter(Number.isFinite);
        }

        function getSelectedRefreshAccountIds() {
            return Array.from(refreshModalState.selectedAccountIds)
                .map(accountId => Number(accountId))
                .filter(Number.isFinite);
        }

        function getSelectedRefreshAccounts() {
            const selectedIds = new Set(getSelectedRefreshAccountIds());
            if (!selectedIds.size) {
                return [];
            }
            return refreshModalState.items.filter(item => selectedIds.has(Number(item.id)));
        }

        function getRefreshAccountBatchContext() {
            const selectedAccounts = getSelectedRefreshAccounts();
            return {
                source: 'refresh-management',
                isTempContext: false,
                selectedAccounts,
                selectedIds: getSelectedRefreshAccountIds(),
                selectedEmails: selectedAccounts.map(account => account.email).filter(Boolean),
                selectedCheckboxes: Array.from(document.querySelectorAll('#refreshAccountList .refresh-account-select-checkbox:checked')),
                buttons: {
                    copy: document.getElementById('refreshCopySelectedBtn'),
                    export: document.getElementById('refreshExportSelectedBtn'),
                    refresh: document.getElementById('refreshSelectedBtn'),
                    enableForwarding: document.getElementById('refreshEnableForwardingBtn'),
                    disableForwarding: document.getElementById('refreshDisableForwardingBtn'),
                    proxy: document.getElementById('refreshProxyBtn'),
                    delete: document.getElementById('refreshDeleteSelectedBtn'),
                },
                clearSelection: clearRefreshSelection,
                updateControls: syncRefreshBatchControls,
                afterMutation: async function afterRefreshBatchMutation(options = {}) {
                    if (typeof invalidateAccountCaches === 'function') {
                        invalidateAccountCaches();
                    }
                    if (Array.isArray(options.deletedEmails) && options.deletedEmails.length && typeof resetSelectedAccountViewIfDeleted === 'function') {
                        resetSelectedAccountViewIfDeleted(options.deletedEmails);
                    }
                    if (typeof loadGroups === 'function') {
                        await loadGroups();
                    }
                    clearRefreshSelection();
                    await reloadRefreshWorkbenchData();
                }
            };
        }

        function withRefreshAccountBatchContext(callback) {
            if (typeof withAccountBatchSelectionContext !== 'function') {
                showToast('批量操作模块尚未加载，请刷新页面后重试', 'error');
                return undefined;
            }
            return withAccountBatchSelectionContext(getRefreshAccountBatchContext(), callback);
        }

        function setRefreshSelectionMode(enabled) {
            refreshModalState.selectionMode = !!enabled;
            document.getElementById('refreshModal')?.classList.toggle('refresh-selection-mode', refreshModalState.selectionMode);
            document.querySelectorAll('.refresh-selection-mode-btn').forEach(button => {
                button.classList.toggle('active', refreshModalState.selectionMode);
                button.setAttribute('aria-pressed', refreshModalState.selectionMode ? 'true' : 'false');
                button.title = refreshModalState.selectionMode ? '退出批量选择' : '批量选择';
            });
            if (!refreshModalState.selectionMode) {
                refreshModalState.selectionDragState = null;
            }
        }

        function toggleRefreshSelectionMode() {
            setRefreshSelectionMode(!refreshModalState.selectionMode);
        }

        function getRefreshSelectionCheckboxes() {
            return Array.from(document.querySelectorAll('#refreshAccountList .refresh-account-select-checkbox'));
        }

        function getRefreshSelectionCheckboxById(accountId) {
            return getRefreshSelectionCheckboxes()
                .find(checkbox => String(checkbox.value) === String(accountId));
        }

        function setRefreshSelectionAnchor(accountId) {
            const normalizedId = Number(accountId);
            refreshModalState.selectionAnchorId = Number.isFinite(normalizedId) ? normalizedId : null;
        }

        function setRefreshSelectionRange(fromId, toId, selected) {
            const checkboxes = getRefreshSelectionCheckboxes();
            const fromIndex = checkboxes.findIndex(checkbox => String(checkbox.value) === String(fromId));
            const toIndex = checkboxes.findIndex(checkbox => String(checkbox.value) === String(toId));
            if (fromIndex === -1 || toIndex === -1) {
                return false;
            }
            const start = Math.min(fromIndex, toIndex);
            const end = Math.max(fromIndex, toIndex);
            for (let index = start; index <= end; index += 1) {
                setRefreshAccountSelected(checkboxes[index].value, selected, { sync: false });
            }
            return true;
        }

        function applyRefreshSelectionFromCheckbox(checkbox, event = null) {
            if (!checkbox || refreshModalState.isRunning) {
                syncRefreshBatchControls();
                return;
            }
            const accountId = Number(checkbox.value);
            if (!Number.isFinite(accountId)) {
                syncRefreshBatchControls();
                return;
            }
            const selected = !!checkbox.checked;
            if (event?.shiftKey && refreshModalState.selectionAnchorId !== null) {
                if (setRefreshSelectionRange(refreshModalState.selectionAnchorId, accountId, selected)) {
                    event.preventDefault?.();
                } else {
                    setRefreshAccountSelected(accountId, selected, { sync: false });
                }
            } else {
                setRefreshAccountSelected(accountId, selected, { sync: false });
            }
            setRefreshSelectionAnchor(accountId);
            syncRefreshBatchControls();
        }

        function handleRefreshSelectionCheckboxClick(event) {
            event.stopPropagation();
            if (refreshModalState.selectionMode && Date.now() < refreshModalState.selectionSuppressClickUntil) {
                event.preventDefault();
                return;
            }
            applyRefreshSelectionFromCheckbox(event.currentTarget, event);
        }

        function isRefreshRowInteractiveTarget(target) {
            return !!target?.closest?.('button, input, a, .refresh-account-action');
        }

        function handleRefreshAccountRowClick(event) {
            if (Date.now() < refreshModalState.selectionSuppressClickUntil) {
                event?.preventDefault?.();
                return;
            }
            if (refreshModalState.isRunning || isRefreshRowInteractiveTarget(event?.target)) {
                return;
            }
            if (!refreshModalState.selectionMode && !event?.shiftKey) {
                return;
            }

            const checkbox = event.currentTarget?.querySelector?.('.refresh-account-select-checkbox');
            if (!checkbox) {
                return;
            }

            event?.preventDefault?.();
            if (event?.shiftKey && refreshModalState.selectionAnchorId !== null) {
                checkbox.checked = true;
                applyRefreshSelectionFromCheckbox(checkbox, event);
            } else {
                checkbox.checked = !checkbox.checked;
                applyRefreshSelectionFromCheckbox(checkbox, event);
            }
        }

        function setRefreshDragSelection(checkbox) {
            if (!refreshModalState.selectionDragState || !checkbox) {
                return;
            }
            const accountId = String(checkbox.value);
            if (refreshModalState.selectionDragState.visitedIds.has(accountId)) {
                return;
            }
            refreshModalState.selectionDragState.visitedIds.add(accountId);
            checkbox.checked = refreshModalState.selectionDragState.targetChecked;
            setRefreshAccountSelected(checkbox.value, refreshModalState.selectionDragState.targetChecked, { sync: false });
            setRefreshSelectionAnchor(checkbox.value);
            syncRefreshBatchControls();
        }

        function handleRefreshSelectionPointerDown(event) {
            if (!refreshModalState.selectionMode || refreshModalState.isRunning || event.button !== 0) {
                return;
            }
            const startedOnCheckbox = !!event.target.closest('.refresh-account-select-checkbox');
            if (!startedOnCheckbox && isRefreshRowInteractiveTarget(event.target)) {
                return;
            }

            const row = event.target.closest('.refresh-account-row');
            const checkbox = row?.querySelector?.('.refresh-account-select-checkbox');
            if (!checkbox) {
                return;
            }

            event.preventDefault();
            refreshModalState.selectionSuppressClickUntil = Date.now() + 350;
            refreshModalState.selectionDragState = {
                pointerId: event.pointerId,
                targetChecked: !checkbox.checked,
                visitedIds: new Set()
            };
            document.getElementById('refreshAccountList')?.setPointerCapture?.(event.pointerId);
            setRefreshDragSelection(checkbox);
        }

        function handleRefreshSelectionPointerMove(event) {
            const dragState = refreshModalState.selectionDragState;
            if (!dragState || event.pointerId !== dragState.pointerId) {
                return;
            }
            event.preventDefault();
            const element = document.elementFromPoint(event.clientX, event.clientY);
            const row = element?.closest?.('#refreshAccountList .refresh-account-row');
            const checkbox = row?.querySelector?.('.refresh-account-select-checkbox');
            setRefreshDragSelection(checkbox);
        }

        function handleRefreshSelectionPointerEnd(event) {
            const dragState = refreshModalState.selectionDragState;
            if (!dragState || event.pointerId !== dragState.pointerId) {
                return;
            }
            document.getElementById('refreshAccountList')?.releasePointerCapture?.(event.pointerId);
            refreshModalState.selectionDragState = null;
        }

        function initRefreshSelectionGestures() {
            const refreshAccountList = document.getElementById('refreshAccountList');
            if (!refreshAccountList || refreshAccountList.dataset.boundSelectionGestures) {
                return;
            }
            refreshAccountList.dataset.boundSelectionGestures = 'true';
            refreshAccountList.addEventListener('pointerdown', handleRefreshSelectionPointerDown);
            refreshAccountList.addEventListener('pointermove', handleRefreshSelectionPointerMove);
            refreshAccountList.addEventListener('pointerup', handleRefreshSelectionPointerEnd);
            refreshAccountList.addEventListener('pointercancel', handleRefreshSelectionPointerEnd);
        }

        function syncRefreshBatchControls() {
            const selectedIds = getSelectedRefreshAccountIds();
            const visibleIds = getVisibleRefreshAccountIds();
            const visibleSelectedCount = visibleIds.filter(accountId => refreshModalState.selectedAccountIds.has(accountId)).length;
            const hiddenSelectedCount = Math.max(0, selectedIds.length - visibleSelectedCount);
            const hasVisibleItems = visibleIds.length > 0;
            const hasSelection = selectedIds.length > 0;
            const allVisibleSelected = hasVisibleItems && visibleSelectedCount === visibleIds.length;
            const selectedAccounts = getSelectedRefreshAccounts();
            const enableForwardingCount = selectedAccounts.filter(account => !account.forward_enabled).length;
            const disableForwardingCount = selectedAccounts.filter(account => !!account.forward_enabled).length;

            const modalEl = document.getElementById('refreshModal');
            modalEl?.classList.toggle('refresh-selection-mode', refreshModalState.selectionMode);

            const batchActions = document.getElementById('refreshBatchActions');
            if (batchActions) {
                batchActions.classList.toggle('is-active', hasSelection);
            }

            document.querySelectorAll('.refresh-selection-mode-btn').forEach(button => {
                button.classList.toggle('active', refreshModalState.selectionMode);
                button.setAttribute('aria-pressed', refreshModalState.selectionMode ? 'true' : 'false');
                button.title = refreshModalState.selectionMode ? '退出批量选择' : '批量选择';
            });

            const summaryEl = document.getElementById('refreshSelectedSummary');
            if (summaryEl) {
                summaryEl.textContent = hasSelection
                    ? (hiddenSelectedCount > 0 ? `已选 ${selectedIds.length} 项，当前筛选外 ${hiddenSelectedCount} 项` : `已选 ${selectedIds.length} 项`)
                    : '未选择账号';
            }

            const selectVisibleBtn = document.getElementById('refreshSelectVisibleBtn');
            if (selectVisibleBtn) {
                selectVisibleBtn.disabled = !hasVisibleItems || refreshModalState.isRunning;
                selectVisibleBtn.textContent = allVisibleSelected ? '取消当前列表' : '全选当前列表';
            }

            const clearSelectionBtn = document.getElementById('refreshClearSelectionBtn');
            if (clearSelectionBtn) {
                clearSelectionBtn.disabled = !hasSelection || refreshModalState.isRunning;
            }

            const refreshSelectedBtn = document.getElementById('refreshSelectedBtn');
            if (refreshSelectedBtn) {
                refreshSelectedBtn.disabled = !hasSelection || refreshModalState.isRunning;
                refreshSelectedBtn.textContent = hasSelection ? `刷新已选 (${selectedIds.length})` : '刷新已选';
            }

            const copySelectedBtn = document.getElementById('refreshCopySelectedBtn');
            if (copySelectedBtn) {
                const isCopying = copySelectedBtn.dataset.loading === 'true';
                copySelectedBtn.disabled = !hasSelection || refreshModalState.isRunning || isCopying;
                if (!isCopying) {
                    copySelectedBtn.textContent = hasSelection ? `复制邮箱+别名 (${selectedIds.length})` : '复制邮箱+别名';
                }
            }

            const exportSelectedBtn = document.getElementById('refreshExportSelectedBtn');
            if (exportSelectedBtn) {
                exportSelectedBtn.disabled = !hasSelection || refreshModalState.isRunning;
                exportSelectedBtn.textContent = hasSelection ? `导出 (${selectedIds.length})` : '导出';
            }

            const enableForwardingBtn = document.getElementById('refreshEnableForwardingBtn');
            const disableForwardingBtn = document.getElementById('refreshDisableForwardingBtn');
            const isForwardingUpdating = enableForwardingBtn?.dataset.loading === 'true'
                || disableForwardingBtn?.dataset.loading === 'true';
            if (enableForwardingBtn) {
                enableForwardingBtn.disabled = !hasSelection || enableForwardingCount === 0 || refreshModalState.isRunning || isForwardingUpdating;
                enableForwardingBtn.title = hasSelection && enableForwardingCount === 0 ? '所选账号已全部开启转发' : '';
                if (enableForwardingBtn.dataset.loading !== 'true') {
                    enableForwardingBtn.textContent = enableForwardingCount > 0 && enableForwardingCount !== selectedIds.length
                        ? `开启转发 (${enableForwardingCount})`
                        : '开启转发';
                }
            }
            if (disableForwardingBtn) {
                disableForwardingBtn.disabled = !hasSelection || disableForwardingCount === 0 || refreshModalState.isRunning || isForwardingUpdating;
                disableForwardingBtn.title = hasSelection && disableForwardingCount === 0 ? '所选账号已全部取消转发' : '';
                if (disableForwardingBtn.dataset.loading !== 'true') {
                    disableForwardingBtn.textContent = disableForwardingCount > 0 && disableForwardingCount !== selectedIds.length
                        ? `取消转发 (${disableForwardingCount})`
                        : '取消转发';
                }
            }

            const proxyBtn = document.getElementById('refreshProxyBtn');
            if (proxyBtn) {
                const isUpdatingProxy = proxyBtn.dataset.loading === 'true';
                proxyBtn.disabled = !hasSelection || refreshModalState.isRunning || isUpdatingProxy;
                if (!isUpdatingProxy) {
                    proxyBtn.textContent = hasSelection ? `代理 (${selectedIds.length})` : '代理';
                }
            }

            const addTagBtn = document.getElementById('refreshAddTagBtn');
            if (addTagBtn) {
                addTagBtn.disabled = !hasSelection || refreshModalState.isRunning;
            }

            const removeTagBtn = document.getElementById('refreshRemoveTagBtn');
            if (removeTagBtn) {
                removeTagBtn.disabled = !hasSelection || refreshModalState.isRunning;
            }

            const moveGroupBtn = document.getElementById('refreshMoveGroupBtn');
            if (moveGroupBtn) {
                moveGroupBtn.disabled = !hasSelection || refreshModalState.isRunning;
            }

            const deleteSelectedBtn = document.getElementById('refreshDeleteSelectedBtn');
            if (deleteSelectedBtn) {
                const isDeleting = deleteSelectedBtn.dataset.loading === 'true';
                deleteSelectedBtn.disabled = !hasSelection || refreshModalState.isRunning || isDeleting;
                if (!isDeleting) {
                    deleteSelectedBtn.textContent = hasSelection ? `删除 (${selectedIds.length})` : '删除';
                }
            }

            const selectVisibleCheckbox = document.getElementById('refreshSelectVisibleCheckbox');
            if (selectVisibleCheckbox) {
                selectVisibleCheckbox.disabled = !hasVisibleItems || refreshModalState.isRunning;
                selectVisibleCheckbox.checked = allVisibleSelected;
                selectVisibleCheckbox.indeterminate = hasVisibleItems && visibleSelectedCount > 0 && !allVisibleSelected;
            }

            document.querySelectorAll('#refreshAccountList .refresh-account-select-checkbox').forEach(checkbox => {
                const accountId = Number(checkbox.value);
                checkbox.checked = refreshModalState.selectedAccountIds.has(accountId);
                checkbox.disabled = refreshModalState.isRunning;
            });
        }

        function setRefreshAccountSelected(accountId, selected, options = {}) {
            const normalizedId = Number(accountId);
            if (!Number.isFinite(normalizedId) || refreshModalState.isRunning) {
                syncRefreshBatchControls();
                return;
            }
            if (selected) {
                refreshModalState.selectedAccountIds.add(normalizedId);
            } else {
                refreshModalState.selectedAccountIds.delete(normalizedId);
            }
            if (options.sync !== false) {
                syncRefreshBatchControls();
            }
        }

        function toggleRefreshVisibleSelection() {
            if (refreshModalState.isRunning) {
                return;
            }
            const visibleIds = getVisibleRefreshAccountIds();
            if (!visibleIds.length) {
                return;
            }
            const shouldClear = visibleIds.every(accountId => refreshModalState.selectedAccountIds.has(accountId));
            visibleIds.forEach(accountId => {
                if (shouldClear) {
                    refreshModalState.selectedAccountIds.delete(accountId);
                } else {
                    refreshModalState.selectedAccountIds.add(accountId);
                }
            });
            syncRefreshBatchControls();
        }

        function clearRefreshSelection() {
            if (refreshModalState.isRunning) {
                return;
            }
            refreshModalState.selectedAccountIds.clear();
            refreshModalState.selectionAnchorId = null;
            syncRefreshBatchControls();
        }

        function clearRefreshSelectionForScopeChange() {
            refreshModalState.selectionAnchorId = null;
            if (!refreshModalState.selectedAccountIds.size) {
                return;
            }
            refreshModalState.selectedAccountIds.clear();
            syncRefreshBatchControls();
        }

        function renderRefreshAccountList(items, total) {
            const container = document.getElementById('refreshAccountList');
            const summaryEl = document.getElementById('refreshListSummary');
            if (!container || !summaryEl) {
                return;
            }

            refreshModalState.items = Array.isArray(items) ? items : [];
            refreshModalState.total = Number(total || 0);
            const pageSize = normalizeRefreshPageSize(refreshModalState.pageSize);
            const page = Math.max(1, parseInt(refreshModalState.page, 10) || 1);
            const startItem = refreshModalState.items.length
                ? ((page - 1) * pageSize) + 1
                : 0;
            const endItem = refreshModalState.items.length
                ? Math.min(refreshModalState.total, startItem + refreshModalState.items.length - 1)
                : 0;
            summaryEl.textContent = refreshModalState.total > 0
                ? `第 ${startItem}-${endItem} 项 / 共 ${refreshModalState.total} 项`
                : '共 0 项';
            syncRefreshPaginationControls();

            if (!refreshModalState.items.length) {
                container.innerHTML = '<div class="refresh-account-empty">当前筛选条件下暂无邮箱</div>';
                syncRefreshBatchControls();
                return;
            }

            const rowsHtml = refreshModalState.items.map(item => {
                const accountId = Number(item.id);
                const isRunning = refreshModalState.currentRefreshingAccountId === item.id;
                const isSelected = refreshModalState.selectedAccountIds.has(accountId);
                const canRetry = item.last_refresh_status === 'failed' && !isRunning;
                const groupText = item.group_name || '默认分组';
                const refreshTime = item.last_refresh_at ? formatDateTime(item.last_refresh_at) : '-';
                const remarkHtml = item.remark
                    ? `<div class="refresh-account-remark">${escapeHtml(item.remark)}</div>`
                    : '';
                const errorHtml = item.last_refresh_status === 'failed' && item.last_refresh_error
                    ? `<div class="refresh-account-error">${escapeHtml(item.last_refresh_error)}</div>`
                    : '';
                const rowClassNames = [
                    isRunning ? 'is-refreshing' : '',
                    isSelected ? 'is-selected' : '',
                    refreshModalState.isRunning ? 'is-disabled' : '',
                ].filter(Boolean);

                return `
                    <tr class="refresh-account-row ${rowClassNames.join(' ')}" data-refresh-account-id="${accountId}" onclick="handleRefreshAccountRowClick(event)">
                        <td class="refresh-account-select-cell">
                            <input type="checkbox" class="refresh-account-select-checkbox" value="${item.id}"
                                ${isSelected ? 'checked' : ''}
                                onclick="handleRefreshSelectionCheckboxClick(event)">
                        </td>
                        <td class="refresh-account-main">
                            <div class="refresh-account-email" title="${escapeHtml(item.email)}">${escapeHtml(item.email)}</div>
                            ${remarkHtml}
                            ${errorHtml}
                        </td>
                        <td class="refresh-account-group" title="${escapeHtml(groupText)}">${escapeHtml(groupText)}</td>
                        <td class="refresh-account-time">${escapeHtml(refreshTime)}</td>
                        <td class="refresh-account-status-cell">${renderRefreshStatusBadge(item.last_refresh_status, isRunning)}</td>
                        <td class="refresh-account-action">
                            ${canRetry
                                ? `<button class="btn btn-sm btn-primary" type="button" onclick="retrySingleAccount(${item.id}, '${escapeJs(item.email)}')">重试</button>`
                                : '<span class="refresh-account-time">-</span>'}
                        </td>
                    </tr>
                `;
            }).join('');

            container.innerHTML = `
                <table class="refresh-account-table">
                    <thead>
                        <tr>
                            <th class="refresh-account-select-head">
                                <input type="checkbox" id="refreshSelectVisibleCheckbox" onclick="toggleRefreshVisibleSelection()">
                            </th>
                            <th>邮箱</th>
                            <th>分组</th>
                            <th>最近刷新</th>
                            <th>状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            `;
            syncRefreshBatchControls();
        }

        async function loadRefreshStats() {
            try {
                const response = await fetch('/api/accounts/refresh-stats');
                const data = await response.json();
                if (data.success) {
                    renderRefreshStats(data.stats || {});
                }
            } catch (error) {
                console.error('加载刷新统计失败:', error);
            }
        }

        async function loadRefreshStatusList() {
            const params = new URLSearchParams({
                q: refreshModalState.query,
                status: refreshModalState.status,
                page: String(refreshModalState.page),
                page_size: String(refreshModalState.pageSize),
            });

            try {
                const response = await fetch(`/api/accounts/refresh-status-list?${params.toString()}`);
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '加载 Token 刷新状态失败');
                    return;
                }
                refreshModalState.page = Math.max(1, parseInt(data.page, 10) || refreshModalState.page);
                refreshModalState.pageSize = normalizeRefreshPageSize(data.page_size || refreshModalState.pageSize);
                refreshModalState.total = Math.max(0, Number(data.total || 0));
                const totalPages = getRefreshTotalPages();
                if (refreshModalState.total > 0 && refreshModalState.page > totalPages) {
                    refreshModalState.page = totalPages;
                    await loadRefreshStatusList();
                    return;
                }
                renderRefreshStats(data.stats || {});
                renderRefreshAccountList(data.items || [], data.total || 0);
                updateRefreshStatusFilterButtons();
            } catch (error) {
                showToast('加载 Token 刷新状态失败', 'error');
            }
        }

        function handleRefreshPageSizeChange(value) {
            if (refreshModalState.isRunning) {
                syncRefreshPaginationControls();
                return;
            }
            const nextPageSize = normalizeRefreshPageSize(value);
            if (nextPageSize === refreshModalState.pageSize) {
                syncRefreshPaginationControls();
                return;
            }
            clearRefreshSelectionForScopeChange();
            refreshModalState.pageSize = nextPageSize;
            refreshModalState.page = 1;
            localStorage.setItem(REFRESH_PAGE_SIZE_STORAGE_KEY, String(nextPageSize));
            syncRefreshPaginationControls();
            loadRefreshStatusList();
        }

        function goToRefreshPage(value) {
            if (refreshModalState.isRunning) {
                syncRefreshPaginationControls();
                return;
            }
            const totalPages = getRefreshTotalPages();
            const nextPage = Math.min(
                totalPages,
                Math.max(1, parseInt(value, 10) || 1)
            );
            if (nextPage === refreshModalState.page) {
                syncRefreshPaginationControls();
                return;
            }
            clearRefreshSelectionForScopeChange();
            refreshModalState.page = nextPage;
            syncRefreshPaginationControls();
            loadRefreshStatusList();
        }

        function changeRefreshPage(delta) {
            goToRefreshPage(refreshModalState.page + (parseInt(delta, 10) || 0));
        }

        function handleRefreshPageInputKeydown(event) {
            if (event.key !== 'Enter') {
                return;
            }
            event.preventDefault();
            goToRefreshPage(event.currentTarget.value);
            event.currentTarget.blur();
        }

        async function showRefreshModal(resetFilters = false) {
            if (resetFilters) {
                refreshModalState.query = '';
                refreshModalState.status = 'all';
                refreshModalState.page = 1;
                refreshModalState.selectedAccountIds.clear();
                refreshModalState.selectionAnchorId = null;
                setRefreshSelectionMode(false);
            }

            showModal('refreshModal');
            initRefreshSelectionGestures();
            initRefreshPaginationSettings();
            updateRefreshStatusFilterButtons();
            syncRefreshActionButtons();
            renderRefreshRuntimeLogs();
            if (!refreshModalState.runtimeLogs.length) {
                updateRefreshLogSummary(refreshModalState.isRunning ? '正在执行全量刷新任务' : '暂无任务日志');
            }

            const searchInput = document.getElementById('refreshSearchInput');
            if (searchInput) {
                searchInput.value = refreshModalState.query;
            }

            await loadRefreshStatusList();
        }

        async function openRefreshModalWithStatus(status = 'all') {
            refreshModalState.query = '';
            refreshModalState.status = String(status || 'all').toLowerCase();
            refreshModalState.page = 1;
            refreshModalState.selectedAccountIds.clear();
            refreshModalState.selectionAnchorId = null;
            setRefreshSelectionMode(false);
            await showRefreshModal();
        }

        function hideRefreshModal() {
            hideModal('refreshModal');
            if (!refreshModalState.isRunning) {
                setRefreshSelectionMode(false);
                resetRefreshModalRuntime();
            }
        }

        function handleRefreshSearchInput(value) {
            const nextQuery = String(value || '').trim();
            if (nextQuery !== refreshModalState.query) {
                clearRefreshSelectionForScopeChange();
            }
            refreshModalState.query = nextQuery;
            refreshModalState.page = 1;
            if (refreshModalState.searchTimer) {
                window.clearTimeout(refreshModalState.searchTimer);
            }
            refreshModalState.searchTimer = window.setTimeout(() => {
                refreshModalState.searchTimer = 0;
                loadRefreshStatusList();
            }, 180);
        }

        function setRefreshStatusFilter(status, triggerEl = null) {
            const nextStatus = String(status || 'all').toLowerCase();
            if (nextStatus !== refreshModalState.status) {
                clearRefreshSelectionForScopeChange();
            }
            refreshModalState.status = nextStatus;
            refreshModalState.page = 1;
            if (triggerEl?.dataset?.status) {
                document.querySelectorAll('#refreshModal .refresh-filter-chip').forEach(btn => {
                    btn.classList.toggle('is-active', btn === triggerEl);
                });
            } else {
                updateRefreshStatusFilterButtons();
            }
            loadRefreshStatusList();
        }

        function applyRefreshResultToListItem(data) {
            const targetItem = refreshModalState.items.find(item => item.id === data.account_id);
            if (!targetItem) {
                return;
            }
            targetItem.last_refresh_status = data.status;
            targetItem.last_refresh_error = data.error_message || null;
            targetItem.last_refresh_at = new Date().toISOString();
        }

        function beginRefreshTaskRuntime(summary, title, detail) {
            closeRefreshEventSource();
            refreshModalState.runtimeLogs = [];
            refreshModalState.isRunning = true;
            refreshModalState.stopRequested = false;
            refreshModalState.currentRefreshingAccountId = null;
            updateRefreshLogSummary(summary);
            appendRefreshRuntimeLog('info', title, detail);
            syncRefreshActionButtons();
            renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
        }

        function finishRefreshTaskRuntime(source = refreshModalState.eventSource) {
            closeRefreshEventSource(source);
            refreshModalState.isRunning = false;
            refreshModalState.stopRequested = false;
            refreshModalState.currentRefreshingAccountId = null;
            syncRefreshActionButtons();
            renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
        }

        async function reloadRefreshWorkbenchData() {
            await loadRefreshStatusList();
            if (typeof refreshVisibleAccountList === 'function') {
                await refreshVisibleAccountList(true);
            } else if (currentGroupId && typeof loadAccountsByGroup === 'function') {
                await loadAccountsByGroup(currentGroupId, true);
            }
        }

        async function startRefreshEventStream(url, options = {}) {
            if (refreshModalState.isRunning) {
                return;
            }

            const taskLabel = options.taskLabel || '刷新';
            const startSummary = options.startSummary || `正在准备${taskLabel}任务`;
            const startLogTitle = options.startLogTitle || `已提交${taskLabel}任务`;
            const startLogDetail = options.startLogDetail || '正在建立刷新连接';
            const requestErrorToast = options.requestErrorToast || `${taskLabel}请求失败`;
            const emptyToast = options.emptyToast || '没有需要处理的账号';
            const clearSelectionOnComplete = options.clearSelectionOnComplete === true;

            beginRefreshTaskRuntime(startSummary, startLogTitle, startLogDetail);

            try {
                const eventSource = new EventSource(url);
                refreshModalState.eventSource = eventSource;

                let totalCount = 0;
                let successCount = 0;
                let failedCount = 0;
                let finished = false;

                async function finalizeRefreshTask(callback) {
                    if (finished || refreshModalState.eventSource !== eventSource) {
                        return;
                    }
                    finished = true;
                    await callback();
                }

                eventSource.onmessage = async function (event) {
                    if (refreshModalState.eventSource !== eventSource || finished) {
                        return;
                    }

                    let data = null;
                    try {
                        data = JSON.parse(event.data);
                    } catch (error) {
                        console.error('解析刷新日志失败:', error);
                        return;
                    }

                    if (data.type === 'start') {
                        totalCount = Math.max(0, Number(data.total || 0));
                        successCount = Math.max(0, Number(data.success_count || 0));
                        failedCount = Math.max(0, Number(data.failed_count || 0));
                        setRefreshSnapshotCounts(totalCount, successCount, failedCount);

                        const delayText = Number(data.delay_seconds || 0) > 0 ? `，刷新间隔 ${data.delay_seconds} 秒` : '';
                        updateRefreshLogSummary(totalCount > 0 ? `任务运行中：0 / ${totalCount}` : '本次没有需要处理的账号');
                        appendRefreshRuntimeLog('info', '任务开始', `本次共需处理 ${totalCount} 个账号${delayText}`);
                        return;
                    }

                    if (data.type === 'progress') {
                        totalCount = Math.max(totalCount, Number(data.total || 0));
                        successCount = Math.max(0, Number(data.success_count || successCount));
                        failedCount = Math.max(0, Number(data.failed_count || failedCount));
                        refreshModalState.currentRefreshingAccountId = data.account_id || null;
                        setRefreshSnapshotCounts(totalCount, successCount, failedCount);
                        updateRefreshLogSummary(`任务运行中：${Math.max(0, Number(data.current || 0) - 1)} / ${Math.max(totalCount, Number(data.total || 0))}`);
                        appendRefreshRuntimeLog('info', `开始刷新 ${data.email || '-'}`, `进度 ${data.current || 0}/${data.total || totalCount}`);
                        renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
                        return;
                    }

                    if (data.type === 'account_result') {
                        totalCount = Math.max(totalCount, Number(data.total || 0));
                        successCount = Math.max(0, Number(data.success_count || successCount));
                        failedCount = Math.max(0, Number(data.failed_count || failedCount));
                        refreshModalState.currentRefreshingAccountId = null;
                        setRefreshSnapshotCounts(totalCount, successCount, failedCount);
                        updateRefreshLogSummary(`任务运行中：${successCount + failedCount} / ${Math.max(totalCount, Number(data.total || 0))}`);
                        applyRefreshResultToListItem(data);
                        appendRefreshRuntimeLog(
                            data.status === 'failed' ? 'error' : 'success',
                            `${data.email || '-'} ${data.status === 'failed' ? '刷新失败' : '刷新成功'}`,
                            data.error_message || `累计成功 ${successCount}，失败 ${failedCount}`
                        );
                        renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
                        return;
                    }

                    if (data.type === 'delay') {
                        const waitSeconds = Math.max(0, Number(data.seconds || 0));
                        const processedCount = successCount + failedCount;
                        updateRefreshLogSummary(`任务运行中：${processedCount} / ${totalCount}，等待 ${waitSeconds} 秒`);
                        appendRefreshRuntimeLog('warn', '等待下一轮刷新', `等待 ${waitSeconds} 秒后继续`);
                        return;
                    }

                    if (data.type === 'stopped') {
                        await finalizeRefreshTask(async () => {
                            totalCount = Math.max(totalCount, Number(data.total || 0));
                            successCount = Math.max(0, Number(data.success_count || successCount));
                            failedCount = Math.max(0, Number(data.failed_count || failedCount));
                            setRefreshSnapshotCounts(totalCount, successCount, failedCount);
                            finishRefreshTaskRuntime(eventSource);
                            updateRefreshLogSummary(`任务已停止：已处理 ${data.processed_count || (successCount + failedCount)} / ${totalCount}`);
                            appendRefreshRuntimeLog('warn', '任务已停止', data.message || `已停止${taskLabel}任务`);
                            showToast(data.message || `已停止${taskLabel}任务`, 'warning');
                            await reloadRefreshWorkbenchData();
                        });
                        return;
                    }

                    if (data.type === 'complete') {
                        await finalizeRefreshTask(async () => {
                            totalCount = Math.max(totalCount, Number(data.total || 0));
                            successCount = Math.max(0, Number(data.success_count || successCount));
                            failedCount = Math.max(0, Number(data.failed_count || failedCount));
                            setRefreshSnapshotCounts(totalCount, successCount, failedCount);
                            finishRefreshTaskRuntime(eventSource);
                            if (clearSelectionOnComplete) {
                                refreshModalState.selectedAccountIds.clear();
                                refreshModalState.selectionAnchorId = null;
                                syncRefreshBatchControls();
                            }

                            if (totalCount <= 0) {
                                updateRefreshLogSummary('本次没有需要处理的账号');
                                appendRefreshRuntimeLog('info', '任务完成', '本次没有需要处理的账号');
                                showToast(emptyToast, 'info');
                            } else {
                                updateRefreshLogSummary(`任务已完成：${successCount + failedCount} / ${totalCount}`);
                                appendRefreshRuntimeLog(
                                    failedCount > 0 ? 'warn' : 'success',
                                    '任务完成',
                                    `成功 ${successCount}，失败 ${failedCount}`
                                );
                                showToast(
                                    `${taskLabel}完成：成功 ${successCount}，失败 ${failedCount}`,
                                    failedCount > 0 ? 'warning' : 'success'
                                );
                            }

                            await reloadRefreshWorkbenchData();
                        });
                        return;
                    }

                    if (data.type === 'conflict') {
                        await finalizeRefreshTask(async () => {
                            finishRefreshTaskRuntime(eventSource);
                            updateRefreshLogSummary('已有任务在执行');
                            appendRefreshRuntimeLog('warn', '任务未启动', data.message || '已有刷新任务在执行');
                            showToast(data.message || '已有刷新任务在执行', 'warning');
                            await reloadRefreshWorkbenchData();
                        });
                        return;
                    }

                    if (data.type === 'error') {
                        await finalizeRefreshTask(async () => {
                            totalCount = Math.max(totalCount, Number(data.total || 0));
                            successCount = Math.max(0, Number(data.success_count || successCount));
                            failedCount = Math.max(0, Number(data.failed_count || failedCount));
                            if (totalCount > 0 || successCount > 0 || failedCount > 0) {
                                setRefreshSnapshotCounts(totalCount, successCount, failedCount);
                            }
                            finishRefreshTaskRuntime(eventSource);
                            updateRefreshLogSummary('任务执行失败');
                            appendRefreshRuntimeLog('error', '任务执行失败', data.message || `${taskLabel}过程中出现错误`);
                            showToast(data.message || `${taskLabel}过程中出现错误`, 'error');
                            await reloadRefreshWorkbenchData();
                        });
                    }
                };

                eventSource.onerror = function (error) {
                    console.error('Token 刷新 EventSource 错误:', error);
                    if (refreshModalState.eventSource !== eventSource || finished) {
                        return;
                    }

                    finished = true;
                    const wasStopping = refreshModalState.stopRequested;
                    finishRefreshTaskRuntime(eventSource);

                    if (!wasStopping) {
                        updateRefreshLogSummary('连接已中断');
                        appendRefreshRuntimeLog('error', '连接中断', `${taskLabel}日志连接异常断开`);
                        showToast(`${taskLabel}过程中出现错误`, 'error');
                    }

                    reloadRefreshWorkbenchData();
                };
            } catch (error) {
                finishRefreshTaskRuntime();
                updateRefreshLogSummary('任务启动失败');
                appendRefreshRuntimeLog('error', '任务启动失败', error.message || requestErrorToast);
                showToast(requestErrorToast, 'error');
            }
        }

        // 全量刷新所有账号
        async function refreshAllAccounts() {
            const btn = document.getElementById('refreshAllBtn');
            if (btn?.disabled) {
                return;
            }

            if (!(await showConfirmModal('确定要刷新所有账号的 Token 吗？', { title: '刷新 Token', confirmText: '确认刷新', danger: false }))) {
                return;
            }

            await startRefreshEventStream('/api/accounts/trigger-scheduled-refresh?force=true', {
                taskLabel: '全量刷新',
                startSummary: '正在准备全量刷新任务',
                startLogTitle: '已提交全量刷新任务',
                startLogDetail: '正在建立刷新连接',
                requestErrorToast: '刷新请求失败',
                emptyToast: '没有可刷新的账号',
            });
        }

        async function stopFullRefresh() {
            if (!refreshModalState.isRunning || refreshModalState.stopRequested) {
                return;
            }

            const stopBtn = document.getElementById('stopRefreshBtn');
            refreshModalState.stopRequested = true;
            syncRefreshActionButtons();
            updateRefreshLogSummary('正在请求停止任务');
            appendRefreshRuntimeLog('warn', '已发送停止请求', '当前账号处理完成后会结束任务');

            try {
                const response = await fetch('/api/accounts/stop-full-refresh', {
                    method: 'POST',
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    refreshModalState.stopRequested = false;
                    syncRefreshActionButtons();
                    updateRefreshLogSummary('停止请求失败');
                    appendRefreshRuntimeLog('error', '停止请求失败', data.message || '停止任务失败');
                    showToast(data.message || '停止任务失败', 'error');
                    return;
                }
                if (stopBtn) {
                    stopBtn.blur();
                }
                showToast(data.message || '已请求停止刷新任务', 'warning');
            } catch (error) {
                refreshModalState.stopRequested = false;
                syncRefreshActionButtons();
                updateRefreshLogSummary('停止请求失败');
                appendRefreshRuntimeLog('error', '停止请求失败', error.message || '停止请求异常');
                showToast('停止任务失败', 'error');
            }
        }

        async function retryFailedAccounts() {
            const btn = document.getElementById('retryFailedBtn');
            if (btn?.disabled) {
                return;
            }

            await startRefreshEventStream('/api/accounts/refresh-failed-stream', {
                taskLabel: '失败重试',
                startSummary: '正在准备失败重试任务',
                startLogTitle: '已提交失败重试任务',
                startLogDetail: '正在建立刷新连接',
                requestErrorToast: '重试请求失败',
                emptyToast: '没有需要重试的失败账号',
            });
        }

        async function copySelectedRefreshAccountsWithAliases() {
            return withRefreshAccountBatchContext(() => copySelectedAccountsWithAliases());
        }

        function exportSelectedRefreshAccounts() {
            return withRefreshAccountBatchContext(() => exportSelectedAccounts());
        }

        async function enableForwardingForSelectedRefreshAccounts() {
            return withRefreshAccountBatchContext(() => updateForwardingForSelectedAccounts(true));
        }

        async function disableForwardingForSelectedRefreshAccounts() {
            return withRefreshAccountBatchContext(() => updateForwardingForSelectedAccounts(false));
        }

        function showRefreshBatchProxyModal() {
            return withRefreshAccountBatchContext(() => showBatchProxyModal());
        }

        function showRefreshBatchTagModal(type) {
            return withRefreshAccountBatchContext(() => showBatchTagModal(type));
        }

        function showRefreshBatchMoveGroupModal() {
            return withRefreshAccountBatchContext(() => showBatchMoveGroupModal());
        }

        async function refreshSelectedRefreshAccounts() {
            const btn = document.getElementById('refreshSelectedBtn');
            if (btn?.disabled || refreshModalState.isRunning) {
                return;
            }

            const accountIds = getSelectedRefreshAccountIds();
            if (!accountIds.length) {
                showToast('请先选择要刷新的账号', 'error');
                return;
            }
            if (!(await showConfirmModal(`确定要刷新选中的 ${accountIds.length} 个账号 Token 吗？`, { title: '刷新已选 Token', confirmText: '确认刷新', danger: false }))) {
                return;
            }

            let data = null;
            try {
                const response = await fetch('/api/accounts/refresh-selected-stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds })
                });
                data = await response.json();

                if (!response.ok || !data.success || !data.stream_url) {
                    handleApiError(data, '批量刷新任务初始化失败');
                    return;
                }
            } catch (error) {
                handleApiError({
                    success: false,
                    error: {
                        message: '批量刷新任务初始化失败',
                        details: error.message,
                        code: 'NETWORK_ERROR',
                        type: 'Frontend'
                    }
                });
                return;
            }

            await startRefreshEventStream(data.stream_url, {
                taskLabel: '批量刷新',
                startSummary: '正在准备批量刷新任务',
                startLogTitle: '已提交批量刷新任务',
                startLogDetail: `已选择 ${accountIds.length} 个账号`,
                requestErrorToast: '批量刷新请求失败',
                emptyToast: '没有可刷新的选中账号',
                clearSelectionOnComplete: true,
            });
        }

        async function deleteSelectedRefreshAccounts() {
            const btn = document.getElementById('refreshDeleteSelectedBtn');
            if (btn?.disabled || refreshModalState.isRunning) {
                return;
            }

            const accountIds = getSelectedRefreshAccountIds();
            if (!accountIds.length) {
                showToast('请先选择要删除的账号', 'error');
                return;
            }
            if (!(await showConfirmModal(`确定要删除选中的 ${accountIds.length} 个账号吗？此操作不可恢复。`, { title: '删除已选账号', confirmText: '确认删除' }))) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '删除中...';

            try {
                const response = await fetch('/api/accounts/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '批量删除失败');
                    return;
                }

                const deletedAccounts = Array.isArray(data.deleted_accounts) ? data.deleted_accounts : [];
                const deletedEmails = deletedAccounts.map(account => account.email).filter(Boolean);
                accountIds.forEach(accountId => refreshModalState.selectedAccountIds.delete(accountId));
                if (!refreshModalState.selectedAccountIds.size) {
                    refreshModalState.selectionAnchorId = null;
                }
                updateRefreshLogSummary(data.message || `已删除 ${deletedAccounts.length} 个账号`);
                appendRefreshRuntimeLog('warn', '批量删除账号', data.message || `已删除 ${deletedAccounts.length} 个账号`);
                showToast(data.message || `已删除 ${deletedAccounts.length} 个账号`, 'success');

                if (typeof invalidateAccountCaches === 'function') {
                    invalidateAccountCaches();
                }
                if (typeof resetSelectedAccountViewIfDeleted === 'function') {
                    resetSelectedAccountViewIfDeleted(deletedEmails);
                }
                if (typeof loadGroups === 'function') {
                    await loadGroups();
                }
                await reloadRefreshWorkbenchData();
            } catch (error) {
                showToast('批量删除失败', 'error');
            } finally {
                btn.dataset.loading = 'false';
                syncRefreshBatchControls();
            }
        }

        // 单个账号重试
        async function retrySingleAccount(accountId, accountEmail) {
            try {
                refreshModalState.currentRefreshingAccountId = accountId;
                updateRefreshLogSummary(`正在重试 ${accountEmail}`);
                appendRefreshRuntimeLog('info', `开始重试 ${accountEmail}`, '单账号重试任务');
                renderRefreshAccountList(refreshModalState.items, refreshModalState.total);

                const response = await fetch(`/api/accounts/${accountId}/retry-refresh`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    appendRefreshRuntimeLog('success', `${accountEmail} 刷新成功`, '单账号重试完成');
                    updateRefreshLogSummary(`${accountEmail} 重试完成`);
                    showToast(`${accountEmail} 刷新成功`, 'success');
                    await reloadRefreshWorkbenchData();
                } else {
                    const errorMessage = data?.error?.message || data?.error || data?.message || '刷新失败';
                    appendRefreshRuntimeLog('error', `${accountEmail} 刷新失败`, errorMessage);
                    updateRefreshLogSummary(`${accountEmail} 重试失败`);
                    handleApiError(data, `${accountEmail} 刷新失败`);
                }
            } catch (error) {
                appendRefreshRuntimeLog('error', `${accountEmail} 刷新失败`, error.message || '刷新请求失败');
                updateRefreshLogSummary(`${accountEmail} 重试失败`);
                handleApiError({ success: false, error: { message: '刷新请求失败', details: error.message, code: 'NETWORK_ERROR', type: 'Frontend' } });
            } finally {
                refreshModalState.currentRefreshingAccountId = null;
                renderRefreshAccountList(refreshModalState.items, refreshModalState.total);
            }
        }

        async function loadForwardingLogs() {
            const drawer = document.getElementById('forwardingLogsDrawer');
            const container = document.getElementById('forwardingLogsContainer');
            const listEl = document.getElementById('forwardingLogsList');
            hideFailedForwardingLogs();

            try {
                const response = await fetch('/api/accounts/forwarding-logs?limit=100');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无转发历史</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                            const statusText = log.status === 'success' ? '成功' : '失败';
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #e5e5e5;">
                                    <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                                        <div style="font-weight: 600;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: ${statusColor}; font-weight: 600;">${statusText}</div>
                                    </div>
                                    <div style="font-size: 12px; color: #666; line-height: 1.7;">
                                        <div>渠道：${escapeHtml(log.channel || '-')}</div>
                                        <div>邮件 ID：${escapeHtml(log.message_id || '-')}</div>
                                        <div>时间：${formatDateTime(log.created_at)}</div>
                                    </div>
                                    ${log.error_message ? `<div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message)}</div>` : ''}
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    if (container) {
                        container.hidden = false;
                    }
                    if (drawer) {
                        drawer.classList.add('is-open');
                    }
                    const toggleBtn = document.getElementById('forwardingLogsToggleBtn');
                    if (toggleBtn) {
                        toggleBtn.textContent = '收起历史';
                    }
                }
            } catch (error) {
                showToast('加载转发历史失败', 'error');
            }
        }

        async function loadFailedForwardingLogs() {
            const drawer = document.getElementById('failedForwardingLogsDrawer');
            const container = document.getElementById('failedForwardingLogsContainer');
            const listEl = document.getElementById('failedForwardingLogsList');
            hideForwardingLogs();

            try {
                const response = await fetch('/api/accounts/forwarding-logs/failed?limit=100');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无转发失败记录</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #f3d6d6;">
                                    <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                                        <div style="font-weight: 600;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: #dc3545; font-weight: 600;">失败</div>
                                    </div>
                                    <div style="font-size: 12px; color: #666; line-height: 1.7;">
                                        <div>渠道：${escapeHtml(log.channel || '-')}</div>
                                        <div>邮件 ID：${escapeHtml(log.message_id || '-')}</div>
                                        <div>时间：${formatDateTime(log.created_at)}</div>
                                    </div>
                                    <div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message || '未知错误')}</div>
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    if (container) {
                        container.hidden = false;
                    }
                    if (drawer) {
                        drawer.classList.add('is-open');
                    }
                    const toggleBtn = document.getElementById('failedForwardingLogsToggleBtn');
                    if (toggleBtn) {
                        toggleBtn.textContent = '收起失败';
                    }
                }
            } catch (error) {
                showToast('加载转发失败记录失败', 'error');
            }
        }

        function toggleForwardingLogsDrawer() {
            const container = document.getElementById('forwardingLogsContainer');
            if (container?.hidden) {
                loadForwardingLogs();
                return;
            }
            hideForwardingLogs();
        }

        function toggleFailedForwardingLogsDrawer() {
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container?.hidden) {
                loadFailedForwardingLogs();
                return;
            }
            hideFailedForwardingLogs();
        }

        function hideForwardingLogs() {
            const drawer = document.getElementById('forwardingLogsDrawer');
            const container = document.getElementById('forwardingLogsContainer');
            if (container) {
                container.hidden = true;
            }
            if (drawer) {
                drawer.classList.remove('is-open');
            }
            const toggleBtn = document.getElementById('forwardingLogsToggleBtn');
            if (toggleBtn) {
                toggleBtn.textContent = '查看历史';
            }
        }

        function hideFailedForwardingLogs() {
            const drawer = document.getElementById('failedForwardingLogsDrawer');
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container) {
                container.hidden = true;
            }
            if (drawer) {
                drawer.classList.remove('is-open');
            }
            const toggleBtn = document.getElementById('failedForwardingLogsToggleBtn');
            if (toggleBtn) {
                toggleBtn.textContent = '查看失败';
            }
        }

        // 格式化日期时间
        function formatDateTime(dateStr) {
            if (!dateStr) return '-';

            let date;
            if (dateStr instanceof Date) {
                date = dateStr;
            } else if (typeof dateStr === 'number' || /^\d+$/.test(String(dateStr))) {
                const timestamp = Number(dateStr);
                date = new Date(timestamp < 1000000000000 ? timestamp * 1000 : timestamp);
            } else {
                // 如果字符串不包含时区信息，假定为 UTC 时间
                if (!dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                    dateStr = dateStr + 'Z';
                }
                date = new Date(dateStr);
            }

            const now = new Date();
            const diff = now - date;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);

            if (minutes < 1) return '刚刚';
            if (minutes < 60) return `${minutes}分钟前`;
            if (hours < 24) return `${hours}小时前`;
            if (days < 7) return `${days}天前`;

            return date.toLocaleString('zh-CN', {
                timeZone: getAppTimeZone(),
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        // 统一关闭所有模态框的函数 (修复 bug：防止模态框意外残留)
        function closeAllModals() {
            const releaseNoticeModal = document.getElementById('releaseNoticeModal');
            if (releaseNoticeModal?.classList.contains('show') && typeof markCurrentReleaseNoticeSeen === 'function') {
                markCurrentReleaseNoticeSeen();
            }

            document.querySelectorAll('.modal').forEach(modal => {
                modal.classList.remove('show');
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
            });

            const settingsPassword = document.getElementById('settingsPassword');
            if (settingsPassword) {
                settingsPassword.value = '';
            }
            const settingsCurrentPassword = document.getElementById('settingsCurrentPassword');
            if (settingsCurrentPassword) {
                settingsCurrentPassword.value = '';
            }

            const exportVerifyPassword = document.getElementById('exportVerifyPassword');
            if (exportVerifyPassword) {
                exportVerifyPassword.value = '';
            }

            if (typeof clearEditAccountSecrets === 'function') {
                clearEditAccountSecrets();
            }

            setRefreshSelectionMode(false);
            resetRefreshModalRuntime();
            hideForwardingLogs();
            hideFailedForwardingLogs();

            closeFullscreenEmail();
            updateModalBodyState();
        }

        // 键盘快捷键
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeNavbarActionsMenu();
                closeMobilePanels();
                closeAccountActionMenus();
                closeTagFilterDropdown();
                closeAllModals();
            }
        });
