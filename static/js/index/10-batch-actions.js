        /* global accountPaginationState, accountsCache, clearEmailSelection, closeModal, copyTextToClipboard, currentAccount, currentAccountListSource, currentEmailDetail, currentGroupId, deleteAccount, getSelectedForwardChannels, handleApiError, hideModal, invalidateAccountCaches, isTempEmailGroup, loadAccountsByGroup, loadGroups, loadTags, refreshVisibleAccountList, renderEmailList, selectedEmailIds, setModalVisible, showModal, showToast, startSelectedAccountExport, updateBatchActionBar */

        // ==================== 批量操作 ====================

        let accountSelectionMode = false;
        let accountSelectionAnchorId = null;
        let accountSelectionDragState = null;
        let accountSelectionSuppressClickUntil = 0;

        function getAccountSelectionCheckboxes() {
            return Array.from(document.querySelectorAll('#accountList .account-select-checkbox'));
        }

        function getAccountSelectionCheckboxById(accountId) {
            return getAccountSelectionCheckboxes()
                .find(checkbox => String(checkbox.value) === String(accountId));
        }

        function setAccountSelectionMode(enabled) {
            accountSelectionMode = !!enabled;
            document.getElementById('accountPanel')?.classList.toggle('account-selection-mode', accountSelectionMode);
            document.querySelectorAll('.account-selection-mode-btn').forEach(button => {
                button.classList.toggle('active', accountSelectionMode);
                button.setAttribute('aria-pressed', accountSelectionMode ? 'true' : 'false');
                button.title = accountSelectionMode ? '退出批量选择' : '批量选择';
            });
            if (!accountSelectionMode) {
                accountSelectionDragState = null;
            }
        }

        function toggleAccountSelectionMode() {
            setAccountSelectionMode(!accountSelectionMode);
        }

        function setAccountSelectionAnchor(checkbox) {
            if (checkbox) {
                accountSelectionAnchorId = String(checkbox.value);
            }
        }

        function setAccountSelectionRange(fromCheckbox, toCheckbox, checked) {
            const checkboxes = getAccountSelectionCheckboxes();
            const fromIndex = checkboxes.indexOf(fromCheckbox);
            const toIndex = checkboxes.indexOf(toCheckbox);
            if (fromIndex === -1 || toIndex === -1) {
                return false;
            }

            const start = Math.min(fromIndex, toIndex);
            const end = Math.max(fromIndex, toIndex);
            for (let index = start; index <= end; index += 1) {
                checkboxes[index].checked = checked;
            }
            return true;
        }

        function applyAccountSelectionFromCheckbox(checkbox, event = null) {
            if (!checkbox) {
                return;
            }

            if (event?.shiftKey && accountSelectionAnchorId) {
                const anchor = getAccountSelectionCheckboxById(accountSelectionAnchorId);
                if (anchor && setAccountSelectionRange(anchor, checkbox, checkbox.checked)) {
                    event.preventDefault?.();
                }
            }
            setAccountSelectionAnchor(checkbox);
            updateBatchActionBar();
        }

        function handleAccountSelectionCheckboxClick(event) {
            event.stopPropagation();
            if (accountSelectionMode && Date.now() < accountSelectionSuppressClickUntil) {
                event.preventDefault();
                return;
            }
            applyAccountSelectionFromCheckbox(event.currentTarget, event);
        }

        function handleAccountRowSelectionClick(event) {
            if (Date.now() < accountSelectionSuppressClickUntil) {
                event?.preventDefault?.();
                return;
            }
            if (event?.target?.closest?.('.account-menu-wrap, .account-action-btn, .account-menu-trigger, .account-menu-panel, .account-error-btn, button, input, a')) {
                return;
            }

            const item = event.currentTarget;
            const checkbox = item?.querySelector?.('.account-select-checkbox');
            if (!checkbox) {
                return;
            }

            event?.preventDefault?.();
            if (event?.shiftKey && accountSelectionAnchorId) {
                checkbox.checked = true;
                applyAccountSelectionFromCheckbox(checkbox, event);
            } else {
                checkbox.checked = !checkbox.checked;
                applyAccountSelectionFromCheckbox(checkbox, event);
            }
        }

        function setAccountDragSelection(checkbox) {
            if (!accountSelectionDragState || !checkbox) {
                return;
            }
            const accountId = String(checkbox.value);
            if (accountSelectionDragState.visitedIds.has(accountId)) {
                return;
            }
            accountSelectionDragState.visitedIds.add(accountId);
            checkbox.checked = accountSelectionDragState.targetChecked;
            setAccountSelectionAnchor(checkbox);
            updateBatchActionBar();
        }

        function handleAccountSelectionPointerDown(event) {
            if (!accountSelectionMode || event.button !== 0) {
                return;
            }
            const startedOnCheckbox = !!event.target.closest('.account-select-checkbox');
            if (!startedOnCheckbox && event.target.closest('.account-menu-wrap, .account-action-btn, .account-menu-trigger, .account-menu-panel, .account-error-btn, button, input, a')) {
                return;
            }

            const item = event.target.closest('.account-item');
            const checkbox = item?.querySelector?.('.account-select-checkbox');
            if (!checkbox) {
                return;
            }

            event.preventDefault();
            accountSelectionSuppressClickUntil = Date.now() + 350;
            accountSelectionDragState = {
                pointerId: event.pointerId,
                targetChecked: !checkbox.checked,
                visitedIds: new Set()
            };
            document.getElementById('accountList')?.setPointerCapture?.(event.pointerId);
            setAccountDragSelection(checkbox);
        }

        function handleAccountSelectionPointerMove(event) {
            if (!accountSelectionDragState || event.pointerId !== accountSelectionDragState.pointerId) {
                return;
            }
            event.preventDefault();
            const element = document.elementFromPoint(event.clientX, event.clientY);
            const item = element?.closest?.('#accountList .account-item');
            const checkbox = item?.querySelector?.('.account-select-checkbox');
            setAccountDragSelection(checkbox);
        }

        function handleAccountSelectionPointerEnd(event) {
            if (!accountSelectionDragState || event.pointerId !== accountSelectionDragState.pointerId) {
                return;
            }
            document.getElementById('accountList')?.releasePointerCapture?.(event.pointerId);
            accountSelectionDragState = null;
        }

        function initAccountSelectionGestures() {
            const accountList = document.getElementById('accountList');
            if (!accountList || accountList.dataset.boundSelectionGestures) {
                return;
            }
            accountList.dataset.boundSelectionGestures = 'true';
            accountList.addEventListener('pointerdown', handleAccountSelectionPointerDown);
            accountList.addEventListener('pointermove', handleAccountSelectionPointerMove);
            accountList.addEventListener('pointerup', handleAccountSelectionPointerEnd);
            accountList.addEventListener('pointercancel', handleAccountSelectionPointerEnd);
            accountList.addEventListener('scroll', positionAccountBatchActionBar, { passive: true });
            window.addEventListener('resize', positionAccountBatchActionBar);
        }

        function resetAccountBatchActionBarPosition() {
            const bar = document.getElementById('batchActionBar');
            if (!bar) return;
            bar.style.removeProperty('--batch-action-top');
            bar.style.removeProperty('--batch-action-max-width');
        }

        function positionAccountBatchActionBar() {
            const bar = document.getElementById('batchActionBar');
            const panel = document.getElementById('accountPanel');
            const firstChecked = document.querySelector('#accountList .account-select-checkbox:checked');
            const firstSelectedItem = firstChecked?.closest('.account-item');

            if (!bar || !panel || !firstSelectedItem || !window.matchMedia('(min-width: 769px)').matches) {
                resetAccountBatchActionBarPosition();
                return;
            }

            const panelRect = panel.getBoundingClientRect();
            const itemRect = firstSelectedItem.getBoundingClientRect();
            const availableWidth = Math.max(260, window.innerWidth - panelRect.right - 16);
            bar.style.setProperty('--batch-action-max-width', `${Math.min(560, Math.round(availableWidth))}px`);

            const barHeight = bar.offsetHeight || 0;
            const minTop = 8;
            const maxTop = Math.max(minTop, panelRect.height - barHeight - 12);
            const selectedTop = itemRect.top - panelRect.top;
            const top = Math.min(Math.max(selectedTop, minTop), maxTop);

            bar.style.setProperty('--batch-action-top', `${Math.round(top)}px`);
        }

        // 更新批量操作栏状态
        function updateBatchActionBar() {
            const checked = Array.from(document.querySelectorAll('.account-select-checkbox:checked'));
            const allCheckboxes = document.querySelectorAll('#accountList .account-select-checkbox');
            const bar = document.getElementById('batchActionBar');
            const countSpan = document.getElementById('selectedCount');
            const selectAllBtn = document.getElementById('accountSelectAllBtn');
            const batchRefreshBtn = document.getElementById('batchRefreshTokensBtn');
            const batchCopyBtn = document.getElementById('batchCopyEmailsBtn');
            const batchExportBtn = document.getElementById('batchExportAccountsBtn');
            const batchEnableForwardingBtn = document.getElementById('batchEnableForwardingBtn');
            const batchDisableForwardingBtn = document.getElementById('batchDisableForwardingBtn');
            const batchProxyBtn = document.getElementById('batchProxyBtn');
            const batchAddTagBtn = document.getElementById('batchAddTagBtn');
            const batchRemoveTagBtn = document.getElementById('batchRemoveTagBtn');
            const batchMoveGroupBtn = document.getElementById('batchMoveGroupBtn');
            const batchDeleteBtn = document.getElementById('batchDeleteAccountsBtn');
            const panel = document.getElementById('accountPanel');
            const refreshableChecked = checked.filter(cb => cb.dataset.refreshable === 'true');
            const enableForwardingChecked = checked.filter(cb => cb.dataset.forwardEnabled !== 'true');
            const disableForwardingChecked = checked.filter(cb => cb.dataset.forwardEnabled === 'true');
            const isForwardingUpdating = batchEnableForwardingBtn?.dataset.loading === 'true'
                || batchDisableForwardingBtn?.dataset.loading === 'true';
            const isTempContext = !!isTempEmailGroup;
            const loadedAccountCount = allCheckboxes.length;
            const totalAccountCount = Number(accountPaginationState?.total) || loadedAccountCount;
            const isPartialPageLoaded = !isTempContext && totalAccountCount > loadedAccountCount;
            const loadedScopeSuffix = isPartialPageLoaded
                ? `（已加载 ${loadedAccountCount}/${totalAccountCount}）`
                : '';

            if (batchRefreshBtn) batchRefreshBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchExportBtn) batchExportBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchEnableForwardingBtn) batchEnableForwardingBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchDisableForwardingBtn) batchDisableForwardingBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchProxyBtn) batchProxyBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchMoveGroupBtn) batchMoveGroupBtn.style.display = isTempContext ? 'none' : 'inline-flex';
            if (batchAddTagBtn) batchAddTagBtn.style.display = 'inline-flex';
            if (batchRemoveTagBtn) batchRemoveTagBtn.style.display = 'inline-flex';
            if (batchDeleteBtn) batchDeleteBtn.style.display = 'inline-flex';
            if (selectAllBtn) {
                const allLoadedChecked = loadedAccountCount > 0 && checked.length === loadedAccountCount;
                const scopeLabel = isPartialPageLoaded ? '已加载' : '';
                selectAllBtn.textContent = allLoadedChecked
                    ? `取消全选${scopeLabel}`
                    : `全选${scopeLabel}`;
            }

            if (checked.length > 0) {
                bar.style.display = 'flex';
                panel?.classList.add('batch-toolbar-active');
                countSpan.textContent = isTempContext
                    ? `已选 ${checked.length} 项`
                    : (refreshableChecked.length > 0 && refreshableChecked.length !== checked.length
                    ? `已选 ${checked.length} 项，可刷新 ${refreshableChecked.length} 项${loadedScopeSuffix}`
                    : `已选 ${checked.length} 项${loadedScopeSuffix}`);
                if (batchRefreshBtn) {
                    const isRefreshing = batchRefreshBtn.dataset.loading === 'true';
                    batchRefreshBtn.disabled = refreshableChecked.length === 0 || isRefreshing;
                    batchRefreshBtn.title = refreshableChecked.length === 0
                        ? '所选账号中没有可刷新的 Outlook 账号'
                        : '';
                    if (!isRefreshing) {
                        batchRefreshBtn.textContent = refreshableChecked.length > 0
                            ? `刷新 Token${refreshableChecked.length !== checked.length ? ` (${refreshableChecked.length})` : ''}`
                            : '刷新 Token';
                    }
                }
                if (batchCopyBtn) {
                    const isCopying = batchCopyBtn.dataset.loading === 'true';
                    batchCopyBtn.disabled = checked.length === 0 || isCopying;
                    if (!isCopying) {
                        batchCopyBtn.textContent = isTempContext
                            ? (checked.length > 1 ? `复制邮箱 (${checked.length})` : '复制邮箱')
                            : (checked.length > 1 ? `复制邮箱+别名 (${checked.length})` : '复制邮箱+别名');
                    }
                }
                if (batchExportBtn) {
                    batchExportBtn.disabled = checked.length === 0;
                    batchExportBtn.textContent = checked.length > 1 ? `导出 (${checked.length})` : '导出';
                }
                if (batchProxyBtn) {
                    const isUpdatingProxy = batchProxyBtn.dataset.loading === 'true';
                    batchProxyBtn.disabled = checked.length === 0 || isUpdatingProxy;
                    if (!isUpdatingProxy) {
                        batchProxyBtn.textContent = checked.length > 1 ? `代理 (${checked.length})` : '代理';
                    }
                }
                if (batchEnableForwardingBtn) {
                    batchEnableForwardingBtn.disabled = enableForwardingChecked.length === 0 || isForwardingUpdating;
                    batchEnableForwardingBtn.title = enableForwardingChecked.length === 0
                        ? '所选账号已全部开启转发'
                        : '';
                    if (batchEnableForwardingBtn.dataset.loading !== 'true') {
                        batchEnableForwardingBtn.textContent = enableForwardingChecked.length > 0
                            ? `开启转发${enableForwardingChecked.length !== checked.length ? ` (${enableForwardingChecked.length})` : ''}`
                            : '开启转发';
                    }
                }
                if (batchDisableForwardingBtn) {
                    batchDisableForwardingBtn.disabled = disableForwardingChecked.length === 0 || isForwardingUpdating;
                    batchDisableForwardingBtn.title = disableForwardingChecked.length === 0
                        ? '所选账号已全部取消转发'
                        : '';
                    if (batchDisableForwardingBtn.dataset.loading !== 'true') {
                        batchDisableForwardingBtn.textContent = disableForwardingChecked.length > 0
                            ? `取消转发${disableForwardingChecked.length !== checked.length ? ` (${disableForwardingChecked.length})` : ''}`
                            : '取消转发';
                    }
                }
                if (batchDeleteBtn) {
                    const isDeleting = batchDeleteBtn.dataset.loading === 'true';
                    batchDeleteBtn.disabled = isDeleting;
                    if (!isDeleting) {
                        batchDeleteBtn.textContent = checked.length > 1 ? `删除 (${checked.length})` : '删除';
                    }
                }
                positionAccountBatchActionBar();
            } else {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
                resetAccountBatchActionBarPosition();
                if (batchRefreshBtn) {
                    batchRefreshBtn.disabled = false;
                    batchRefreshBtn.dataset.loading = 'false';
                    batchRefreshBtn.textContent = '刷新 Token';
                    batchRefreshBtn.title = '';
                }
                if (batchCopyBtn) {
                    batchCopyBtn.disabled = false;
                    batchCopyBtn.dataset.loading = 'false';
                    batchCopyBtn.textContent = isTempContext ? '复制邮箱' : '复制邮箱+别名';
                    batchCopyBtn.title = '';
                }
                if (batchExportBtn) {
                    batchExportBtn.disabled = false;
                    batchExportBtn.textContent = '导出';
                    batchExportBtn.title = '';
                }
                if (batchProxyBtn) {
                    batchProxyBtn.disabled = false;
                    batchProxyBtn.dataset.loading = 'false';
                    batchProxyBtn.textContent = '代理';
                    batchProxyBtn.title = '';
                }
                if (batchEnableForwardingBtn) {
                    batchEnableForwardingBtn.disabled = false;
                    batchEnableForwardingBtn.dataset.loading = 'false';
                    batchEnableForwardingBtn.textContent = '开启转发';
                    batchEnableForwardingBtn.title = '';
                }
                if (batchDisableForwardingBtn) {
                    batchDisableForwardingBtn.disabled = false;
                    batchDisableForwardingBtn.dataset.loading = 'false';
                    batchDisableForwardingBtn.textContent = '取消转发';
                    batchDisableForwardingBtn.title = '';
                }
                if (batchDeleteBtn) {
                    batchDeleteBtn.disabled = false;
                    batchDeleteBtn.dataset.loading = 'false';
                    batchDeleteBtn.textContent = '删除';
                }
            }
        }

        let activeAccountBatchSelectionContext = null;
        let pendingAccountBatchModalContext = null;
        let batchActionType = ''; // 'add' or 'remove'

        function normalizeAccountBatchId(value) {
            const normalized = parseInt(value, 10);
            return Number.isFinite(normalized) ? normalized : null;
        }

        function getMainAccountBatchSelectionCheckboxes() {
            return Array.from(document.querySelectorAll('#accountList .account-select-checkbox:checked'));
        }

        function buildAccountBatchSelectionFromCheckboxes(checkboxes, sourceAccounts = currentAccountListSource) {
            const accountById = new Map();
            (Array.isArray(sourceAccounts) ? sourceAccounts : []).forEach(account => {
                const accountId = normalizeAccountBatchId(account?.id);
                if (accountId !== null) {
                    accountById.set(accountId, account);
                }
            });

            return checkboxes
                .map(checkbox => {
                    const accountId = normalizeAccountBatchId(checkbox.value);
                    if (accountId === null) {
                        return null;
                    }
                    const sourceAccount = accountById.get(accountId) || {};
                    return {
                        ...sourceAccount,
                        id: accountId,
                        email: sourceAccount.email || checkbox.dataset.accountEmail || '',
                        aliases: Array.isArray(sourceAccount.aliases) ? sourceAccount.aliases : [],
                        account_type: sourceAccount.account_type || checkbox.dataset.accountType || 'outlook',
                        provider: sourceAccount.provider || 'outlook',
                        forward_enabled: typeof sourceAccount.forward_enabled === 'boolean'
                            ? sourceAccount.forward_enabled
                            : checkbox.dataset.forwardEnabled === 'true',
                    };
                })
                .filter(Boolean);
        }

        function getMainAccountBatchSelectionContext() {
            const selectedCheckboxes = getMainAccountBatchSelectionCheckboxes();
            const selectedAccounts = buildAccountBatchSelectionFromCheckboxes(selectedCheckboxes);
            const selectedIds = selectedAccounts.map(account => normalizeAccountBatchId(account.id)).filter(Number.isFinite);
            const context = {
                source: 'main-account-list',
                isTempContext: !!isTempEmailGroup,
                selectedCheckboxes,
                selectedAccounts,
                selectedIds,
                selectedEmails: selectedAccounts.map(account => account.email).filter(Boolean),
                buttons: {
                    copy: document.getElementById('batchCopyEmailsBtn'),
                    export: document.getElementById('batchExportAccountsBtn'),
                    refresh: document.getElementById('batchRefreshTokensBtn'),
                    enableForwarding: document.getElementById('batchEnableForwardingBtn'),
                    disableForwarding: document.getElementById('batchDisableForwardingBtn'),
                    proxy: document.getElementById('batchProxyBtn'),
                    delete: document.getElementById('batchDeleteAccountsBtn'),
                },
                clearSelection: clearAccountSelection,
                updateControls: updateBatchActionBar,
            };
            context.afterMutation = async function afterMainAccountMutation(options = {}) {
                if (context.isTempContext) {
                    delete accountsCache.temp;
                } else if (typeof invalidateAccountCaches === 'function') {
                    invalidateAccountCaches();
                }
                if (Array.isArray(options.deletedEmails) && options.deletedEmails.length && typeof resetSelectedAccountViewIfDeleted === 'function') {
                    resetSelectedAccountViewIfDeleted(options.deletedEmails);
                }
                if (typeof loadGroups === 'function') {
                    await loadGroups();
                }
                if (options.clearSelection !== false && typeof context.clearSelection === 'function') {
                    context.clearSelection();
                }
                if (typeof refreshVisibleAccountList === 'function') {
                    await refreshVisibleAccountList(true);
                }
            };
            return context;
        }

        function snapshotAccountBatchSelectionContext(context) {
            const safeContext = context || getMainAccountBatchSelectionContext();
            return {
                ...safeContext,
                selectedCheckboxes: Array.isArray(safeContext.selectedCheckboxes) ? [...safeContext.selectedCheckboxes] : [],
                selectedIds: Array.isArray(safeContext.selectedIds)
                    ? safeContext.selectedIds.map(normalizeAccountBatchId).filter(Number.isFinite)
                    : [],
                selectedEmails: Array.isArray(safeContext.selectedEmails) ? [...safeContext.selectedEmails] : [],
                selectedAccounts: Array.isArray(safeContext.selectedAccounts)
                    ? safeContext.selectedAccounts.map(account => ({
                        ...account,
                        aliases: Array.isArray(account.aliases) ? [...account.aliases] : [],
                        tags: Array.isArray(account.tags) ? [...account.tags] : [],
                    }))
                    : [],
                buttons: safeContext.buttons || {},
            };
        }

        function withAccountBatchSelectionContext(context, callback) {
            const previousContext = activeAccountBatchSelectionContext;
            activeAccountBatchSelectionContext = snapshotAccountBatchSelectionContext(context);
            try {
                const result = callback();
                if (result && typeof result.then === 'function') {
                    return result.finally(() => {
                        activeAccountBatchSelectionContext = previousContext;
                    });
                }
                activeAccountBatchSelectionContext = previousContext;
                return result;
            } catch (error) {
                activeAccountBatchSelectionContext = previousContext;
                throw error;
            }
        }

        function getCurrentAccountBatchSelectionContext() {
            return activeAccountBatchSelectionContext || getMainAccountBatchSelectionContext();
        }

        function getAccountBatchSelectedIds(context = getCurrentAccountBatchSelectionContext()) {
            return Array.from(new Set((context.selectedIds || [])
                .map(normalizeAccountBatchId)
                .filter(Number.isFinite)));
        }

        function getAccountBatchSelectedAccounts(context = getCurrentAccountBatchSelectionContext()) {
            return Array.isArray(context.selectedAccounts) ? context.selectedAccounts : [];
        }

        function getAccountBatchSelectedEmails(context = getCurrentAccountBatchSelectionContext()) {
            const emailSet = new Set();
            getAccountBatchSelectedAccounts(context)
                .map(account => String(account.email || '').trim())
                .filter(Boolean)
                .forEach(email => emailSet.add(email));
            (context.selectedEmails || [])
                .map(email => String(email || '').trim())
                .filter(Boolean)
                .forEach(email => emailSet.add(email));
            return Array.from(emailSet);
        }

        function getAccountBatchButton(context, name) {
            return context?.buttons?.[name] || null;
        }

        function updateAccountBatchControls(context = getCurrentAccountBatchSelectionContext()) {
            if (typeof context.updateControls === 'function') {
                context.updateControls();
            }
        }

        async function afterSuccessfulAccountBatchMutation(context, options = {}) {
            if (typeof context.afterMutation === 'function') {
                await context.afterMutation(options);
                return;
            }
            if (typeof invalidateAccountCaches === 'function') {
                invalidateAccountCaches();
            }
            if (typeof loadGroups === 'function') {
                await loadGroups();
            }
            if (options.clearSelection !== false && typeof context.clearSelection === 'function') {
                context.clearSelection();
            }
            if (typeof refreshVisibleAccountList === 'function') {
                await refreshVisibleAccountList(true);
            }
        }

        function setPendingAccountBatchModalContext(context = getCurrentAccountBatchSelectionContext()) {
            pendingAccountBatchModalContext = snapshotAccountBatchSelectionContext(context);
            return pendingAccountBatchModalContext;
        }

        function getPendingAccountBatchModalContext() {
            return pendingAccountBatchModalContext || getCurrentAccountBatchSelectionContext();
        }

        function clearPendingAccountBatchModalContext() {
            pendingAccountBatchModalContext = null;
        }

        function toggleSelectAllAccounts() {
            const checkboxes = Array.from(document.querySelectorAll('#accountList .account-select-checkbox'));
            if (!checkboxes.length) return;

            const shouldClear = checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => {
                cb.checked = !shouldClear;
            });
            updateBatchActionBar();
        }

        function clearAccountSelection() {
            document.querySelectorAll('#accountList .account-select-checkbox').forEach(cb => {
                cb.checked = false;
            });
            accountSelectionAnchorId = null;
            updateBatchActionBar();
        }

        function getSelectedAccountIds() {
            return getAccountBatchSelectedIds();
        }

        function getSelectedAccounts() {
            return getAccountBatchSelectedAccounts();
        }

        async function copySelectedAccountsWithAliases() {
            const context = getCurrentAccountBatchSelectionContext();
            const btn = getAccountBatchButton(context, 'copy');
            if (!btn || btn.disabled) return;

            const selectedAccounts = getAccountBatchSelectedAccounts(context);
            if (!selectedAccounts.length) {
                showToast('请先选择要复制的邮箱', 'error');
                return;
            }

            const emailSet = new Set();
            selectedAccounts.forEach(account => {
                const candidates = [account.email].concat(Array.isArray(account.aliases) ? account.aliases : []);
                candidates
                    .map(value => String(value || '').trim())
                    .filter(Boolean)
                    .forEach(email => emailSet.add(email));
            });

            const emailList = Array.from(emailSet);
            if (!emailList.length) {
                showToast('所选账号没有可复制的邮箱', 'error');
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '复制中...';

            try {
                await copyTextToClipboard(emailList.join('\n'), `已复制 ${emailList.length} 个邮箱地址`);
            } finally {
                btn.dataset.loading = 'false';
                updateAccountBatchControls(context);
            }
        }

        function exportSelectedAccounts() {
            const context = getCurrentAccountBatchSelectionContext();
            if (context.isTempContext) {
                showToast('临时邮箱暂不支持选中导出', 'error');
                return;
            }

            const accountIds = getAccountBatchSelectedIds(context);
            if (!accountIds.length) {
                showToast('请先选择要导出的邮箱', 'error');
                return;
            }

            startSelectedAccountExport(accountIds);
        }

        async function refreshSelectedAccounts() {
            const context = getCurrentAccountBatchSelectionContext();
            const btn = getAccountBatchButton(context, 'refresh');
            if (!btn || btn.disabled) return;

            const accountIds = getAccountBatchSelectedIds(context);
            const refreshableCount = getAccountBatchSelectedAccounts(context)
                .filter(account => String(account.account_type || 'outlook').toLowerCase() !== 'imap')
                .length;

            if (!accountIds.length) {
                showToast('请先选择要刷新的邮箱', 'error');
                return;
            }
            if (!refreshableCount) {
                showToast('所选账号中没有可刷新的 Outlook 账号', 'error');
                return;
            }
            if (!(await showConfirmModal(`确定要刷新所选 ${accountIds.length} 个邮箱的 Token 吗？`, { title: '批量刷新 Token', confirmText: '确认刷新', danger: false }))) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '刷新中...';

            try {
                const response = await fetch('/api/accounts/refresh-selected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_ids: accountIds })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '批量刷新失败');
                    return;
                }

                const toastType = data.failed_count > 0 || data.skipped_count > 0 ? 'warning' : 'success';
                showToast(
                    `批量刷新完成：成功 ${data.success_count}，失败 ${data.failed_count}，跳过 ${data.skipped_count}`,
                    toastType
                );

                if (data.failed_count > 0) {
                    await openRefreshModalWithStatus('failed');
                } else {
                    loadRefreshStats();
                }

                if (typeof context.clearSelection === 'function') {
                    context.clearSelection();
                }
                if (typeof refreshVisibleAccountList === 'function') {
                    await refreshVisibleAccountList(true);
                }
            } catch (error) {
                showToast('批量刷新请求失败', 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateAccountBatchControls(context);
            }
        }

        async function updateForwardingForSelectedAccounts(targetEnabled) {
            const context = getCurrentAccountBatchSelectionContext();
            const btn = getAccountBatchButton(context, targetEnabled ? 'enableForwarding' : 'disableForwarding');
            if (!btn || btn.disabled) return;

            const selectedAccounts = getAccountBatchSelectedAccounts(context);
            const accountIds = getAccountBatchSelectedIds(context);
            const eligibleCount = selectedAccounts.filter(account => !!account.forward_enabled !== targetEnabled).length;
            const actionLabel = targetEnabled ? '开启转发' : '取消转发';
            const loadingLabel = targetEnabled ? '开启中...' : '取消中...';
            const finishedLabel = targetEnabled ? '已全部开启转发' : '已全部取消转发';
            const skippedLabel = targetEnabled ? '已开启' : '已取消';

            if (!accountIds.length) {
                showToast(`请先选择要${actionLabel}的邮箱`, 'error');
                return;
            }
            if (!eligibleCount) {
                showToast(`所选账号${finishedLabel}`, 'error');
                return;
            }

            const skippedCount = accountIds.length - eligibleCount;
            const confirmMessage = skippedCount > 0
                ? `确定要为所选 ${accountIds.length} 个邮箱${actionLabel}吗？其中 ${skippedCount} 个${skippedLabel}账号会自动跳过。`
                : `确定要为所选 ${accountIds.length} 个邮箱${actionLabel}吗？`;
            if (!(await showConfirmModal(confirmMessage, { title: actionLabel, confirmText: '确认', danger: false }))) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = loadingLabel;

            try {
                const response = await fetch('/api/accounts/batch-update-forwarding', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        forward_enabled: targetEnabled
                    })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, `批量${actionLabel}失败`);
                    return;
                }

                showToast(data.message || `已为 ${eligibleCount} 个账号${actionLabel}`, 'success');
                await afterSuccessfulAccountBatchMutation(context);
            } catch (error) {
                showToast(`批量${actionLabel}失败`, 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateAccountBatchControls(context);
            }
        }

        async function enableForwardingForSelectedAccounts() {
            await updateForwardingForSelectedAccounts(true);
        }

        async function disableForwardingForSelectedAccounts() {
            await updateForwardingForSelectedAccounts(false);
        }

        async function deleteSelectedAccounts() {
            const context = getCurrentAccountBatchSelectionContext();
            const btn = getAccountBatchButton(context, 'delete');
            if (!btn || btn.disabled) return;

            const accountIds = getAccountBatchSelectedIds(context);
            const accountEmails = getAccountBatchSelectedEmails(context);
            const isTempContext = !!context.isTempContext;

            if (!accountIds.length) {
                showToast(isTempContext ? '请先选择要删除的临时邮箱' : '请先选择要删除的邮箱', 'error');
                return;
            }

            const resourceLabel = isTempContext ? '临时邮箱' : '邮箱';
            if (!(await showConfirmModal(`确定要删除所选 ${accountIds.length} 个${resourceLabel}吗？此操作不可恢复。`, { title: `批量删除${resourceLabel}`, confirmText: '确认删除' }))) {
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '删除中...';

            try {
                const response = await fetch(isTempContext ? '/api/temp-emails/batch-delete' : '/api/accounts/batch-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(isTempContext
                        ? { temp_email_ids: accountIds }
                        : { account_ids: accountIds })
                });
                const data = await response.json();

                if (!data.success) {
                    handleApiError(data, '批量删除失败');
                    return;
                }

                const deletedEmails = Array.isArray(isTempContext ? data.deleted_emails : data.deleted_accounts)
                    ? (isTempContext ? data.deleted_emails : data.deleted_accounts).map(item => item.email).filter(Boolean)
                    : accountEmails;

                showToast(data.message || `已删除 ${deletedEmails.length} 个${resourceLabel}`, 'success');
                await afterSuccessfulAccountBatchMutation(context, { deletedEmails });
            } catch (error) {
                showToast('批量删除失败', 'error');
            } finally {
                btn.dataset.loading = 'false';
                updateAccountBatchControls(context);
            }
        }

        // 显示批量打标模态框
        async function showBatchTagModal(type) {
            const context = setPendingAccountBatchModalContext();
            const accountIds = getAccountBatchSelectedIds(context);
            if (!accountIds.length) {
                showToast('请先选择要操作的账号', 'error');
                clearPendingAccountBatchModalContext();
                return;
            }
            batchActionType = type;
            const resourceLabel = context.isTempContext ? '临时邮箱' : '账号';
            document.getElementById('batchTagTitle').textContent = type === 'add'
                ? `批量给${resourceLabel}添加标签`
                : `批量移除${resourceLabel}标签`;
            showModal('batchTagModal');

            // 加载标签选项
            await loadTagsForSelect();
        }

        function hideBatchTagModal() {
            clearPendingAccountBatchModalContext();
            hideModal('batchTagModal');
        }

        // 加载标签到下拉框
        async function loadTagsForSelect() {
            const select = document.getElementById('batchTagSelect');
            select.innerHTML = '<option value="">加载中...</option>';

            try {
                const response = await fetch('/api/tags');
                const data = await response.json();
                if (data.success) {
                    let html = '<option value="">请选择标签...</option>';
                    data.tags.forEach(tag => {
                        html += `<option value="${tag.id}">${escapeHtml(tag.name)}</option>`;
                    });
                    select.innerHTML = html;
                }
            } catch (error) {
                select.innerHTML = '<option value="">加载失败</option>';
            }
        }

        // 确认批量打标
        async function confirmBatchTag() {
            const context = getPendingAccountBatchModalContext();
            const tagId = document.getElementById('batchTagSelect').value;
            if (!tagId) {
                showToast('请选择标签', 'error');
                return;
            }

            const accountIds = getAccountBatchSelectedIds(context);
            if (accountIds.length === 0) return;

            try {
                const isTempContext = !!context.isTempContext;
                const response = await fetch(isTempContext ? '/api/temp-emails/tags' : '/api/accounts/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(isTempContext
                        ? {
                            temp_email_ids: accountIds,
                            tag_id: parseInt(tagId, 10),
                            action: batchActionType
                        }
                        : {
                            account_ids: accountIds,
                            tag_id: parseInt(tagId, 10),
                            action: batchActionType
                        })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchTagModal();
                    await afterSuccessfulAccountBatchMutation(context);
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            } finally {
                updateAccountBatchControls(context);
            }
        }

        // ==================== 批量代理设置 ====================

        function showBatchProxyModal() {
            const context = setPendingAccountBatchModalContext();
            if (context.isTempContext) {
                showToast('临时邮箱不支持账号代理设置', 'error');
                clearPendingAccountBatchModalContext();
                return;
            }
            const accountIds = getAccountBatchSelectedIds(context);
            if (!accountIds.length) {
                showToast('请先选择要设置代理的邮箱', 'error');
                clearPendingAccountBatchModalContext();
                return;
            }
            document.getElementById('batchProxyUrl').value = '';
            document.getElementById('batchFallbackProxyUrl1').value = '';
            document.getElementById('batchFallbackProxyUrl2').value = '';
            showModal('batchProxyModal');
        }

        function hideBatchProxyModal() {
            clearPendingAccountBatchModalContext();
            hideModal('batchProxyModal');
        }

        async function confirmBatchProxy() {
            const context = getPendingAccountBatchModalContext();
            const btn = getAccountBatchButton(context, 'proxy');
            const accountIds = getAccountBatchSelectedIds(context);
            if (!accountIds.length) {
                showToast('请先选择要设置代理的邮箱', 'error');
                return;
            }

            const proxyUrl = document.getElementById('batchProxyUrl').value.trim();
            const fallbackProxyUrl1 = document.getElementById('batchFallbackProxyUrl1').value.trim();
            const fallbackProxyUrl2 = document.getElementById('batchFallbackProxyUrl2').value.trim();
            const isClearing = !proxyUrl && !fallbackProxyUrl1 && !fallbackProxyUrl2;
            const confirmMessage = isClearing
                ? `确定要清空所选 ${accountIds.length} 个邮箱的账号代理，并改为继承分组代理吗？`
                : `确定要为所选 ${accountIds.length} 个邮箱设置账号代理吗？`;

            if (!(await showConfirmModal(confirmMessage, { title: '设置账号代理', confirmText: '确认', danger: false }))) {
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.dataset.loading = 'true';
                btn.textContent = '设置中...';
            }

            try {
                const response = await fetch('/api/accounts/batch-update-proxy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        proxy_url: proxyUrl,
                        fallback_proxy_url_1: fallbackProxyUrl1,
                        fallback_proxy_url_2: fallbackProxyUrl2
                    })
                });
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '批量设置代理失败');
                    return;
                }

                showToast(data.message || '账号代理已更新', 'success');
                hideBatchProxyModal();
                await afterSuccessfulAccountBatchMutation(context);
            } catch (error) {
                showToast('批量设置代理失败', 'error');
            } finally {
                if (btn) {
                    btn.dataset.loading = 'false';
                }
                updateAccountBatchControls(context);
            }
        }

        // ==================== 批量移动分组 ====================

        // 显示批量移动分组模态框
        async function showBatchMoveGroupModal() {
            const context = setPendingAccountBatchModalContext();
            if (context.isTempContext) {
                showToast('临时邮箱不支持移动分组', 'error');
                clearPendingAccountBatchModalContext();
                return;
            }
            const accountIds = getAccountBatchSelectedIds(context);
            if (!accountIds.length) {
                showToast('请先选择要移动的邮箱', 'error');
                clearPendingAccountBatchModalContext();
                return;
            }
            showModal('batchMoveGroupModal');
            await loadGroupsForBatchMove();
        }

        function hideBatchMoveGroupModal() {
            clearPendingAccountBatchModalContext();
            hideModal('batchMoveGroupModal');
        }

        // 加载分组到下拉框
        async function loadGroupsForBatchMove() {
            const select = document.getElementById('batchMoveGroupSelect');
            select.innerHTML = '<option value="">加载中...</option>';

            try {
                const response = await fetch('/api/groups');
                const data = await response.json();
                if (data.success) {
                    let html = '<option value="">请选择分组...</option>';
                    data.groups.filter(g => !g.is_system).forEach(group => {
                        html += `<option value="${group.id}">${escapeHtml(normalizeGroupName(group.name))}</option>`;
                    });
                    select.innerHTML = html;
                }
            } catch (error) {
                select.innerHTML = '<option value="">加载失败</option>';
            }
        }

        // 确认批量移动分组
        async function confirmBatchMoveGroup() {
            const context = getPendingAccountBatchModalContext();
            const groupId = document.getElementById('batchMoveGroupSelect').value;
            if (!groupId) {
                showToast('请选择目标分组', 'error');
                return;
            }

            const accountIds = getAccountBatchSelectedIds(context);
            if (accountIds.length === 0) return;

            try {
                const response = await fetch('/api/accounts/batch-update-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        group_id: parseInt(groupId, 10)
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchMoveGroupModal();
                    await afterSuccessfulAccountBatchMutation(context);
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            } finally {
                updateAccountBatchControls(context);
            }
        }
