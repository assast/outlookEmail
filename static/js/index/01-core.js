        /* global closeAllModals, debounce, ensureForwardingSettingsUI, handleGlobalGroupPointerMove, handleGlobalGroupPointerUp, initColorPicker, initEmailListScroll, loadGroups, loadTags, searchAccounts */

        // 全局状态
        let csrfToken = null;
        let currentAccount = null;
        let currentGroupId = null;
        let currentEmails = [];
        let currentMethod = 'graph';
        let currentFolder = 'all'; // 当前文件夹：all / inbox / junkemail / deleteditems
        let isListVisible = true;
        let groups = [];
        let accountsCache = {}; // 缓存各分组的邮箱列表
        let currentAccountListSource = []; // 当前账号列表的原始数据源（分组或搜索结果）
        let currentForwardingLogAccountId = null;
        let currentForwardingLogAccountEmail = '';
        let editingGroupId = null;
        let selectedColor = '#1a1a1a';
        let isTempEmailGroup = false; // 是否是临时邮箱分组
        let tempEmailGroupId = null; // 临时邮箱分组 ID
        let isLoadingMore = false; // 是否正在加载更多邮件
        let hasMoreEmails = true; // 是否还有更多邮件
        let currentSkip = 0; // 当前分页偏移量

        // 缓存与信任模式
        let emailListCache = {}; // 结构: { "account_folder": { emails: [], hasMore: bool, skip: int, method: str, count: int } }
        let currentEmailId = null; // 当前选中的邮件 ID
        let currentEmailDetail = null; // 当前查看的邮件详细数据
        let isTrustedMode = false; // 是否处于信任模式（不过滤 HTML）
        let oauthPreviewAccount = null;
        let selectedTagFilters = new Set();
        let tagFilterKeyword = '';
        let responsiveUiResizeTimer = null;
        const EMAIL_LIST_REQUEST_TIMEOUT_MS = 70000;
        const EMAIL_DETAIL_REQUEST_TIMEOUT_MS = 45000;
        const TOKEN_REFRESH_REQUEST_TIMEOUT_MS = 70000;
        const BULK_REFRESH_BASE_TIMEOUT_MS = 30000;
        const BULK_REFRESH_PER_ACCOUNT_TIMEOUT_MS = 35000;
        const BULK_REFRESH_MAX_TIMEOUT_MS = 180000;
        const REFRESH_STREAM_STALL_TIMEOUT_MS = 70000;

        function isMobileLayout() {
            return window.matchMedia('(max-width: 768px)').matches;
        }

        function isTimeoutAbortError(error) {
            return error?.name === 'AbortError';
        }

        function fetchWithTimeout(url, options = {}) {
            const fetchOptions = { ...(options || {}) };
            const timeoutMs = Number(fetchOptions.timeoutMs || 0);
            const timeoutMessage = fetchOptions.timeoutMessage || '请求超时，请稍后重试';
            delete fetchOptions.timeoutMs;
            delete fetchOptions.timeoutMessage;

            if (!timeoutMs || timeoutMs <= 0) {
                return window.fetch(url, fetchOptions);
            }

            const controller = new AbortController();
            const originalSignal = fetchOptions.signal;
            const timer = window.setTimeout(() => {
                controller.abort(new DOMException(timeoutMessage, 'AbortError'));
            }, timeoutMs);

            if (originalSignal) {
                if (originalSignal.aborted) {
                    controller.abort(originalSignal.reason);
                } else {
                    originalSignal.addEventListener('abort', () => controller.abort(originalSignal.reason), { once: true });
                }
            }

            fetchOptions.signal = controller.signal;
            return window.fetch(url, fetchOptions).finally(() => {
                window.clearTimeout(timer);
            });
        }

        function createEventSourceWatchdog(eventSource, timeoutMs, onTimeout) {
            let timer = null;

            function stop() {
                if (timer) {
                    window.clearTimeout(timer);
                    timer = null;
                }
            }

            function reset() {
                stop();
                timer = window.setTimeout(() => {
                    try {
                        eventSource.close();
                    } catch (error) {
                        console.warn('关闭超时 EventSource 失败:', error);
                    }
                    if (typeof onTimeout === 'function') {
                        onTimeout();
                    }
                }, timeoutMs);
            }

            reset();
            return { reset, stop };
        }

        function getFolderDisplayName(folder) {
            const names = {
                all: '全部邮件',
                inbox: '收件箱',
                junkemail: '垃圾邮件',
                deleteditems: '已删除邮件'
            };
            return names[String(folder || '').trim().toLowerCase()] || '邮件';
        }

        function normalizeGroupName(groupName, fallbackName = '未命名分组') {
            const normalizedName = String(groupName || '').trim();
            return normalizedName || fallbackName;
        }

        function formatGroupIdBadgeText(groupId) {
            const normalizedId = Number.parseInt(String(groupId ?? ''), 10);
            return Number.isFinite(normalizedId) ? String(normalizedId) : '';
        }

        function updateMobileQuickbarState() {
            const groupBtn = document.getElementById('mobileGroupBtn');
            const accountBtn = document.getElementById('mobileAccountBtn');
            const listBtn = document.getElementById('mobileListBtn');
            const groupOpen = document.getElementById('groupPanel')?.classList.contains('show');
            const accountOpen = document.getElementById('accountPanel')?.classList.contains('show');
            const listHidden = document.getElementById('emailListPanel')?.classList.contains('hidden');

            groupBtn?.classList.toggle('is-active', !!groupOpen);
            accountBtn?.classList.toggle('is-active', !!accountOpen);
            listBtn?.classList.toggle('is-active', !groupOpen && !accountOpen && !listHidden);
        }

        function updateMobileContext() {
            const groupText = document.getElementById('mobileCurrentGroup');
            const accountText = document.getElementById('mobileCurrentAccount');
            const listText = document.getElementById('mobileListButtonHint');
            const listHidden = document.getElementById('emailListPanel')?.classList.contains('hidden');
            const currentGroup = Array.isArray(groups) ? groups.find(group => group.id === currentGroupId) : null;
            const mobileActive = isMobileLayout();

            if (groupText) {
                groupText.textContent = currentGroup
                    ? normalizeGroupName(currentGroup.name)
                    : '未选择';
            }

            if (accountText) {
                accountText.textContent = currentAccount
                    ? `${currentAccount}${isTempEmailGroup ? ' (临时)' : ''}`
                    : '未选择';
            }

            if (listText) {
                listText.textContent = listHidden ? '返回列表' : '当前列表';
            }

            document.body.classList.toggle('mobile-email-detail-open', !!mobileActive && !!listHidden);
            document.body.classList.toggle('mobile-has-current-account', !!mobileActive && !!currentAccount);
            updateMobileQuickbarState();
        }

        function syncMobilePanels() {
            const scrim = document.getElementById('mobilePanelScrim');
            const hasOpenPanel = isMobileLayout()
                && !!document.querySelector('#groupPanel.show, #accountPanel.show');

            scrim?.classList.toggle('show', hasOpenPanel);
            document.body.classList.toggle('mobile-panels-open', hasOpenPanel);
            updateMobileQuickbarState();
        }

        function closeMobilePanels() {
            document.getElementById('groupPanel')?.classList.remove('show');
            document.getElementById('accountPanel')?.classList.remove('show');
            syncMobilePanels();
        }

        function openMobilePanel(panelName) {
            if (!isMobileLayout()) return;

            const targetPanel = document.getElementById(panelName === 'account' ? 'accountPanel' : 'groupPanel');
            const otherPanel = document.getElementById(panelName === 'account' ? 'groupPanel' : 'accountPanel');
            if (!targetPanel) return;

            closeNavbarActionsMenu();
            otherPanel?.classList.remove('show');
            targetPanel.classList.add('show');
            syncMobilePanels();
        }

        function toggleMobilePanel(panelName) {
            if (!isMobileLayout()) return;

            const targetPanel = document.getElementById(panelName === 'account' ? 'accountPanel' : 'groupPanel');
            if (!targetPanel) return;

            if (targetPanel.classList.contains('show')) {
                closeMobilePanels();
                return;
            }

            openMobilePanel(panelName);
        }

        function closeNavbarActionsMenu() {
            const container = document.querySelector('.navbar-actions');
            if (!container) return;

            container.classList.remove('is-open');
            document.getElementById('mobileNavMenuBtn')?.setAttribute('aria-expanded', 'false');
        }

        function toggleNavbarActionsMenu() {
            if (!isMobileLayout()) return;

            const container = document.querySelector('.navbar-actions');
            if (!container) return;

            const willOpen = !container.classList.contains('is-open');
            closeMobilePanels();
            container.classList.toggle('is-open', willOpen);
            document.getElementById('mobileNavMenuBtn')?.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        }

        function handleGlobalChromeClick(event) {
            if (!event.target.closest('.navbar-actions')) {
                closeNavbarActionsMenu();
            }
        }

        function showMobileEmailDetail() {
            if (!isMobileLayout()) return;

            const panel = document.getElementById('emailListPanel');
            if (!panel) return;

            panel.classList.add('hidden');
            isListVisible = false;
            const toggleText = document.getElementById('toggleListText');
            if (toggleText) {
                toggleText.textContent = '显示列表';
            }
            closeMobilePanels();
            closeNavbarActionsMenu();
            updateMobileContext();
        }

        function syncResponsiveUI() {
            if (!isMobileLayout()) {
                closeMobilePanels();
                closeNavbarActionsMenu();

                const listPanel = document.getElementById('emailListPanel');
                if (listPanel) {
                    listPanel.classList.remove('hidden');
                }
                isListVisible = true;
                const toggleText = document.getElementById('toggleListText');
                if (toggleText) {
                    toggleText.textContent = '隐藏列表';
                }
            }

            updateMobileContext();
        }

        // ==================== CSRF 防护 ====================

        // 初始化 CSRF Token
        async function initCSRFToken() {
            try {
                const response = await fetch('/api/csrf-token');
                const data = await response.json();
                csrfToken = data.csrf_token;
                if (data.csrf_disabled) {
                    console.warn('CSRF protection is disabled. Install flask-wtf for better security.');
                }
            } catch (error) {
                console.error('Failed to initialize CSRF token:', error);
            }
        }

        // 包装 fetch 请求，自动添加 CSRF Token
        const originalFetch = window.fetch;
        window.fetch = function (url, options = {}) {
            // 只对非 GET 请求添加 CSRF Token
            if (options.method && options.method.toUpperCase() !== 'GET' && csrfToken) {
                if (options.headers instanceof Headers) {
                    options.headers.set('X-CSRFToken', csrfToken);
                } else {
                    options.headers = {
                        ...(options.headers || {}),
                        'X-CSRFToken': csrfToken
                    };
                }
            }
            return originalFetch(url, options);
        };

        // 初始化
        document.addEventListener('DOMContentLoaded', async function () {
            // 初始化 CSRF Token
            await initCSRFToken();
            ensureForwardingSettingsUI();
            bindPersistentButtonHandlers();
            document.addEventListener('click', closeAccountActionMenus);
            document.addEventListener('click', handleGlobalChromeClick);
            document.addEventListener('click', handleGlobalTagFilterClick);
            document.getElementById('importImapHost')?.addEventListener('input', updateImportHint);
            document.getElementById('importImapPort')?.addEventListener('input', updateImportHint);
            document.getElementById('oauthEmailInput')?.addEventListener('input', invalidateRefreshTokenPreview);
            document.getElementById('oauthPasswordInput')?.addEventListener('input', invalidateRefreshTokenPreview);
            document.getElementById('redirectUrlInput')?.addEventListener('input', invalidateRefreshTokenPreview);
            document.getElementById('navbarActionsMenu')?.addEventListener('click', function (event) {
                if (event.target.closest('.navbar-btn')) {
                    closeNavbarActionsMenu();
                }
            });
            document.getElementById('mobileNavMenuBtn')?.addEventListener('click', function () {
                toggleNavbarActionsMenu();
            });
            document.getElementById('mobileGroupBtn')?.addEventListener('click', function () {
                toggleMobilePanel('group');
            });
            document.getElementById('mobileAccountBtn')?.addEventListener('click', function () {
                toggleMobilePanel('account');
            });
            document.getElementById('mobileListBtn')?.addEventListener('click', function () {
                showEmailList();
            });
            document.getElementById('mobilePanelScrim')?.addEventListener('click', function () {
                closeMobilePanels();
            });
            window.addEventListener('resize', function () {
                clearTimeout(responsiveUiResizeTimer);
                responsiveUiResizeTimer = window.setTimeout(syncResponsiveUI, 120);
            });

            closeAllModals(); // 修复：应用启动时关闭所有模态框，防止浏览器缓存导致残留的模态框背景层
            loadGroups();
            if (typeof loadTags === 'function') {
                loadTags();
            }
            initColorPicker();
            initColorPicker();
            initEmailListScroll();
            window.addEventListener('pointermove', handleGlobalGroupPointerMove, { passive: false });
            window.addEventListener('pointerup', handleGlobalGroupPointerUp);
            window.addEventListener('pointercancel', handleGlobalGroupPointerUp);

            // 绑定搜索框事件
            const searchInput = document.getElementById('globalSearch');
            if (searchInput) {
                const debouncedSearch = debounce((e) => {
                    searchAccounts(e.target.value);
                }, 300);
                searchInput.addEventListener('input', debouncedSearch);
            }

            syncResponsiveUI();
        });

        function closeAccountActionMenus() {
            document.querySelectorAll('.account-item.menu-open').forEach(item => {
                item.classList.remove('menu-open');
            });
        }

        function closeTagFilterDropdown() {
            document.getElementById('tagFilterDropdown')?.classList.remove('open');
        }

        function handleGlobalTagFilterClick(event) {
            if (!event.target.closest('#tagFilterDropdown')) {
                closeTagFilterDropdown();
            }
        }

        function toggleAccountActionMenu(toggleBtn) {
            const accountItem = toggleBtn?.closest('.account-item');
            if (!accountItem) return;

            const shouldOpen = !accountItem.classList.contains('menu-open');
            closeAccountActionMenus();
            if (shouldOpen) {
                accountItem.classList.add('menu-open');
            }
        }

        function bindPersistentButtonHandlers() {
            const accountList = document.getElementById('accountList');
            if (accountList && !accountList.dataset.boundActions) {
                accountList.dataset.boundActions = 'true';
                accountList.addEventListener('click', function (event) {
                    const menuToggle = event.target.closest('[data-account-menu-toggle]');
                    if (menuToggle) {
                        event.preventDefault();
                        event.stopPropagation();
                        toggleAccountActionMenu(menuToggle);
                        return;
                    }

                    const actionBtn = event.target.closest('[data-account-action]');
                    if (!actionBtn) return;

                    event.preventDefault();
                    event.stopPropagation();
                    closeAccountActionMenus();

                    const action = actionBtn.dataset.accountAction;
                    const accountId = parseInt(actionBtn.dataset.accountId || '0', 10);
                    const accountEmail = actionBtn.dataset.accountEmail || '';
                    const accountStatus = actionBtn.dataset.accountStatus || 'active';

                    if (action === 'copy') {
                        copyEmail(accountEmail);
                    } else if (action === 'forwardingLogs') {
                        showAccountForwardingLogs(accountId, accountEmail);
                    } else if (action === 'toggleStatus') {
                        toggleAccountStatus(accountId, accountStatus);
                    } else if (action === 'edit') {
                        showEditAccountModal(accountId);
                    } else if (action === 'delete') {
                        deleteAccount(accountId, accountEmail);
                    }
                });
            }
        }

        // 初始化颜色选择器
        function initColorPicker() {
            document.querySelectorAll('.color-option').forEach(option => {
                option.addEventListener('click', function () {
                    document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
                    this.classList.add('selected');
                    selectedColor = this.dataset.color;
                    // 同步更新自定义颜色输入框
                    document.getElementById('customColorInput').value = selectedColor;
                    document.getElementById('customColorHex').value = selectedColor;
                });
            });
        }

        // 初始化邮件列表滚动监听
        function initEmailListScroll() {
            const emailList = document.getElementById('emailList');
            emailList.addEventListener('scroll', function () {
                // 检查是否滚动到底部
                if (emailList.scrollHeight - emailList.scrollTop <= emailList.clientHeight + 50) {
                    if (!isLoadingMore && hasMoreEmails && currentAccount && !isTempEmailGroup) {
                        loadMoreEmails();
                    }
                }
            });
        }

        // 加载更多邮件
        async function loadMoreEmails() {
            if (isLoadingMore || !hasMoreEmails) return;

            isLoadingMore = true;
            currentSkip += 20; // 每页20封

            // 在列表底部显示加载状态
            const emailList = document.getElementById('emailList');
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'loading loading-small';
            loadingDiv.id = 'loadingMore';
            loadingDiv.innerHTML = '<div class="loading-spinner"></div>';
            emailList.appendChild(loadingDiv);

            // 禁用按钮
            const refreshBtn = document.querySelector('.refresh-btn');
            const folderTabs = document.querySelectorAll('.folder-tab');
            if (refreshBtn) {
                refreshBtn.disabled = true;
            }
            folderTabs.forEach(tab => tab.disabled = true);

            try {
                const response = await fetchWithTimeout(
                    `/api/emails/${encodeURIComponent(currentAccount)}?method=${currentMethod}&folder=${currentFolder}&skip=${currentSkip}&top=20`,
                    {
                        timeoutMs: EMAIL_LIST_REQUEST_TIMEOUT_MS,
                        timeoutMessage: '加载更多邮件超时，请稍后重试'
                    }
                );
                const data = await response.json();

                if (data.success && data.emails.length > 0) {
                    // 追加新邮件到列表
                    currentEmails = currentEmails.concat(data.emails);
                    hasMoreEmails = data.has_more;

                    // 移除加载状态
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) loadingEl.remove();

                    // 重新渲染邮件列表
                    renderEmailList(currentEmails);

                    // 更新邮件数量
                    document.getElementById('emailCount').textContent = `(${currentEmails.length})`;

                    // 更新缓存
                    if (currentAccount && !isTempEmailGroup) {
                        const cacheKey = `${currentAccount}_${currentFolder}`;
                        if (emailListCache[cacheKey]) {
                            emailListCache[cacheKey].emails = currentEmails;
                            emailListCache[cacheKey].has_more = hasMoreEmails;
                            emailListCache[cacheKey].skip = currentSkip;
                        }
                    }
                } else {
                    hasMoreEmails = false;
                    // 显示"没有更多邮件"
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) {
                        loadingEl.innerHTML = '<div style="text-align:center;padding:20px;color:#999;font-size:13px;">没有更多邮件了</div>';
                    }
                }
            } catch (error) {
                const loadingEl = document.getElementById('loadingMore');
                if (loadingEl) loadingEl.remove();
                showToast(isTimeoutAbortError(error) ? '加载更多邮件超时' : '加载失败', 'error');
            } finally {
                isLoadingMore = false;
                // 启用按钮
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                }
                folderTabs.forEach(tab => tab.disabled = false);
            }
        }

        // 切换文件夹（自动触发查询）
        function switchFolder(folder) {
            if (currentFolder === folder) return;

            currentFolder = folder;
            currentEmailId = null;
            currentEmailDetail = null;

            // 更新按钮状态
            document.querySelectorAll('.folder-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.folder === folder);
            });

            const cacheKey = `${currentAccount}_${folder}`;

            // 检查是否有缓存
            if (emailListCache[cacheKey]) {
                const cache = emailListCache[cacheKey];
                currentEmails = cache.emails;
                hasMoreEmails = cache.has_more;
                currentSkip = cache.skip;
                currentMethod = cache.method || 'graph';

                // 恢复 UI
                const methodTag = document.getElementById('methodTag');
                methodTag.textContent = currentMethod;
                methodTag.style.display = 'inline';
                document.getElementById('emailCount').textContent = `(${currentEmails.length})`;

                renderEmailList(currentEmails);
            } else {
                // 清空邮件列表，显示提示
                document.getElementById('emailList').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📬</div>
                        <div class="empty-state-text">正在自动刷新${getFolderDisplayName(folder)}...</div>
                    </div>
                `;
                document.getElementById('emailCount').textContent = '';
                document.getElementById('methodTag').style.display = 'none';

                // 重置分页状态
                currentEmails = [];
                currentSkip = 0;
                hasMoreEmails = true;
            }

            document.getElementById('emailDetail').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">选择一封邮件查看详情</div>
                </div>
            `;
            document.getElementById('emailDetailToolbar').style.display = 'none';

            // 切换文件夹后自动刷新对应列表
            if (currentAccount && !isTempEmailGroup) {
                loadEmails(currentAccount, true);
            }
        }

        // 选择自定义颜色（颜色选择器）
        function selectCustomColor(color) {
            selectedColor = color;
            document.getElementById('customColorHex').value = color;
            // 取消预设颜色的选中状态
            document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
        }

        // 选择自定义颜色（十六进制输入）
        function selectCustomColorHex(value) {
            // 验证十六进制颜色格式
            const hexPattern = /^#[0-9A-Fa-f]{6}$/;
            if (hexPattern.test(value)) {
                selectedColor = value;
                document.getElementById('customColorInput').value = value;
                // 取消预设颜色的选中状态
                document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
            } else {
                showToast('请输入有效的十六进制颜色（如 #FF5500）', 'error');
            }
        }

        // 显示消息提示
        function showToast(message, type = 'info', errorDetail = null) {
            const toast = document.getElementById('toast');
            toast.innerHTML = '';

            // Message span
            const messageSpan = document.createElement('span');
            messageSpan.textContent = message;
            toast.appendChild(messageSpan);

            if (errorDetail && type === 'error') {
                const detailLink = document.createElement('a');
                detailLink.href = 'javascript:void(0)';
                detailLink.textContent = ' [详情]';
                detailLink.style.color = '#ffdddd';
                detailLink.style.textDecoration = 'underline';
                detailLink.style.marginLeft = '8px';
                detailLink.onclick = function (e) {
                    e.stopPropagation();
                    showErrorDetailModal(errorDetail);
                };
                toast.appendChild(detailLink);

                // Ensure the toast remains visible long enough for the user to click the link
                clearTimeout(toast.timer);
                toast.timer = setTimeout(() => {
                    toast.className = 'toast';
                }, 8000); // 8 seconds for errors with details
            } else {
                clearTimeout(toast.timer);
                toast.timer = setTimeout(() => {
                    toast.className = 'toast';
                }, 3000); // 3 seconds for regular messages
            }
            toast.className = 'toast show ' + type;
        }

        function updateModalBodyState() {
            const hasVisibleModal = !!document.querySelector('.modal.show, .fullscreen-email-modal.show');
            document.body.style.overflow = hasVisibleModal ? 'hidden' : '';
        }

        function setModalVisible(modalId, visible) {
            const modal = document.getElementById(modalId);
            if (!modal) return null;
            modal.classList.toggle('show', visible);
            modal.style.display = visible ? 'flex' : 'none';
            modal.setAttribute('aria-hidden', visible ? 'false' : 'true');
            updateModalBodyState();
            return modal;
        }

        function hideModal(modalId) {
            return setModalVisible(modalId, false);
        }

        // 通用确认模态框 - 替代原生 confirm()
        let _genericConfirmResolve = null;

        function showConfirmModal(message, { title = "确认操作", confirmText = "确认", danger = true } = {}) {
            return new Promise((resolve) => {
                _genericConfirmResolve = resolve;
                document.getElementById('genericConfirmTitle').textContent = title;
                document.getElementById('genericConfirmMsg').textContent = message;
                const btn = document.getElementById('genericConfirmBtn');
                btn.textContent = confirmText;
                btn.className = danger ? 'btn btn-danger' : 'btn btn-primary';
                showModal('genericConfirmModal');
            });
        }

        function resolveGenericConfirm() {
            hideModal('genericConfirmModal');
            if (_genericConfirmResolve) {
                _genericConfirmResolve(true);
                _genericConfirmResolve = null;
            }
        }

        function hideGenericConfirmModal() {
            hideModal('genericConfirmModal');
            if (_genericConfirmResolve) {
                _genericConfirmResolve(false);
                _genericConfirmResolve = null;
            }
        }
        function showModal(modalId) {
            closeNavbarActionsMenu();
            closeMobilePanels();
            closeAllModals();
            return setModalVisible(modalId, true);
        }

        // 显示刷新错误信息
        function showRefreshError(accountId, errorMessage, accountEmail) {
            showModal('refreshErrorModal');
            document.getElementById('refreshErrorEmail').textContent = `账号：${accountEmail || '未知'}`;
            document.getElementById('refreshErrorMessage').textContent = errorMessage;
            document.getElementById('editAccountFromErrorBtn').onclick = function () {
                hideRefreshErrorModal();
                showEditAccountModal(accountId);
            };
        }

        async function triggerForwardingCheck() {
            const triggerBtn = document.getElementById('triggerForwardingCheckBtn');
            if (!triggerBtn || triggerBtn.disabled) return;

            const originalText = triggerBtn.textContent;
            triggerBtn.disabled = true;
            triggerBtn.textContent = '触发中...';

            try {
                if (!csrfToken) {
                    await initCSRFToken();
                }

                const response = await fetch('/api/accounts/trigger-forwarding-check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await response.json();

                if (data.success) {
                    showToast(data.message || '已触发一次转发检查', 'success');
                    loadForwardingLogs();
                    loadFailedForwardingLogs();
                } else {
                    showToast(data.error || data.message || '触发转发检查失败', 'error');
                }
            } catch (error) {
                showToast('触发转发检查失败', 'error');
            } finally {
                triggerBtn.disabled = false;
                triggerBtn.textContent = originalText;
            }
        }

        async function showAccountForwardingLogs(accountId, accountEmail) {
            currentForwardingLogAccountId = accountId;
            currentForwardingLogAccountEmail = accountEmail || '';
            const title = document.getElementById('accountForwardingLogsTitle');
            title.textContent = `${accountEmail || '该账号'} 的转发日志`;
            showModal('accountForwardingLogsModal');
            await loadAccountForwardingLogs();
        }

        async function loadAccountForwardingLogs() {
            const listEl = document.getElementById('accountForwardingLogsList');
            const failedOnly = !!document.getElementById('accountForwardingLogsFailedOnly')?.checked;
            const cursorValueEl = document.getElementById('accountForwardingCursorValue');
            const cursorHintEl = document.getElementById('accountForwardingCursorHint');
            if (!currentForwardingLogAccountId) {
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">未选择账号</div>';
                if (cursorValueEl) {
                    cursorValueEl.textContent = '-';
                }
                return;
            }

            listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">加载中...</div>';

            try {
                const suffix = failedOnly ? '&failed_only=1' : '';
                const response = await fetch(`/api/accounts/${currentForwardingLogAccountId}/forwarding-logs?limit=100${suffix}`);
                const data = await response.json();
                if (!data.success || !Array.isArray(data.logs)) {
                    throw new Error('加载失败');
                }
                let account = data.account || {};
                if (!Object.keys(account).length) {
                    try {
                        const accountResp = await fetch(`/api/accounts/${currentForwardingLogAccountId}`);
                        const accountData = await accountResp.json();
                        if (accountData.success && accountData.account) {
                            account = accountData.account;
                        }
                    } catch (fallbackError) {
                        console.warn('加载账号转发元信息失败:', fallbackError);
                    }
                }
                if (cursorValueEl) {
                    cursorValueEl.textContent = account.forward_last_checked_at
                        ? formatDateTime(account.forward_last_checked_at)
                        : '未设置';
                }
                if (cursorHintEl) {
                    cursorHintEl.textContent = account.forward_enabled
                        ? '回退游标后，会按当前转发时间范围重新扫描最近邮件；已成功转发过的邮件仍会被去重。'
                        : '该账号当前未开启转发，回退游标后仍需先开启账号转发。';
                }
                if (data.logs.length === 0) {
                    listEl.innerHTML = `<div style="padding: 20px; text-align: center; color: #666;">${failedOnly ? '该账号暂无失败转发日志' : '该账号暂无转发日志'}</div>`;
                    return;
                }

                let html = '';
                data.logs.forEach(log => {
                    const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                    const statusText = log.status === 'success' ? '成功' : '失败';
                    html += `
                        <div style="padding: 12px; border-bottom: 1px solid #e5e5e5;">
                            <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                                <div style="font-weight: 600;">${escapeHtml(log.account_email || currentForwardingLogAccountEmail || '-')}</div>
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
            } catch (error) {
                if (cursorValueEl) {
                    cursorValueEl.textContent = '加载失败';
                }
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #dc3545;">加载账号转发日志失败</div>';
            }
        }

        async function resetAccountForwardCursor() {
            if (!currentForwardingLogAccountId) return;

            const btn = document.getElementById('resetAccountForwardingCursorBtn');
            const originalText = btn?.textContent || '回退游标并重扫';

            if (!(await showConfirmModal(`确定要回退 ${currentForwardingLogAccountEmail || '该账号'} 的转发游标，并立即重扫最近邮件吗？\n\n已成功转发过的邮件仍会因为去重记录被跳过。`, { title: '回退转发游标', confirmText: '确认回退' }))) {
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.textContent = '处理中...';
            }

            try {
                if (!csrfToken) {
                    await initCSRFToken();
                }

                const response = await fetch(`/api/accounts/${currentForwardingLogAccountId}/forwarding/reset-cursor`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mode: 'window',
                        trigger_check: true
                    })
                });
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || '重置转发游标失败');
                }

                showToast(data.message || '已回退转发游标并触发检查', 'success');
                await loadAccountForwardingLogs();
                loadForwardingLogs();
                loadFailedForwardingLogs();
            } catch (error) {
                showToast(error.message || '重置转发游标失败', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            }
        }

        function toggleAccountForwardingLogFilter() {
            if (!currentForwardingLogAccountId) return;
            loadAccountForwardingLogs();
        }

        function hideAccountForwardingLogs() {
            hideModal('accountForwardingLogsModal');
        }

        // 隐藏刷新错误模态框
        function hideRefreshErrorModal() {
            hideModal('refreshErrorModal');
        }

        // ==================== 统一错误处理相关 ====================

        function escapeHtml(value) {
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function renderEmptyStateMarkup(icon, text, options = {}) {
            const {
                allowHtml = false,
                actionLabel = '刷新',
                actionTitle = '刷新列表',
                onAction = ''
            } = options;

            const content = allowHtml ? String(text || '') : escapeHtml(text || '');
            const hasAction = typeof onAction === 'string' && onAction.trim() !== '';

            return `
                <div class="empty-state">
                    <div class="empty-state-icon">${icon}</div>
                    <div class="empty-state-text">${content}</div>
                    ${hasAction ? `
                        <button
                            class="empty-state-refresh-btn"
                            type="button"
                            onclick="${onAction}"
                            title="${escapeHtml(actionTitle)}"
                            aria-label="${escapeHtml(actionTitle)}"
                        >
                            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                                <path d="M13.5 3.5v3h-3"></path>
                                <path d="M2.5 12.5v-3h3"></path>
                                <path d="M4 6.25A4.75 4.75 0 0 1 12.05 4"></path>
                                <path d="M12 9.75A4.75 4.75 0 0 1 3.95 12"></path>
                            </svg>
                            <span>${escapeHtml(actionLabel)}</span>
                        </button>
                    ` : ''}
                </div>
            `;
        }

        function parseJsonLike(value) {
            if (typeof value !== 'string') return value;
            const text = value.trim();
            if (!text || (!text.startsWith('{') && !text.startsWith('['))) return value;
            try {
                return JSON.parse(text);
            } catch (err) {
                return value;
            }
        }

        function formatFetchErrorDetails(value) {
            const normalized = parseJsonLike(value);
            if (normalized === undefined || normalized === null || normalized === '') return '';
            if (typeof normalized === 'string') return normalized;
            try {
                return JSON.stringify(normalized, null, 2);
            } catch (err) {
                return String(normalized);
            }
        }

        function normalizeMethodError(err) {
            if (err && typeof err === 'object' && err.error && typeof err.error === 'object') {
                return err.error;
            }
            return err;
        }

        // 显示统一错误详情模态框
        function showErrorDetailModal(error) {
            showModal('errorDetailModal');
            document.getElementById('errorModalUserMessage').textContent = error.message || '发生未知错误';
            document.getElementById('errorModalCode').textContent = error.code || '-';
            document.getElementById('errorModalType').textContent = error.type || '-';
            document.getElementById('errorModalStatus').textContent = error.status || '-';
            document.getElementById('errorModalTraceId').textContent = error.trace_id || '-';

            const detailsEl = document.getElementById('errorModalDetails');
            const detailsContainer = document.getElementById('errorModalDetailsContainer');
            const toggleBtn = document.getElementById('toggleTraceBtn');

            detailsEl.textContent = formatFetchErrorDetails(error && error.details) || '暂无详细技术堆栈信息';

            // 重置堆栈显示状态
            detailsContainer.style.display = 'none';
            toggleBtn.textContent = '显示堆栈/细节';
        }

        // 隐藏统一错误详情模态框
        function hideErrorDetailModal() {
            hideModal('errorDetailModal');
        }

        // 邮件获取失败详情弹框
        function showEmailFetchErrorModal(details) {
            if (!details) return;

            const methodNames = {
                'graph': 'Graph API',
                'imap_new': 'IMAP（新服务器）',
                'imap_old': 'IMAP（旧服务器）',
                'imap_generic': '标准 IMAP',
                'inbox': '收件箱',
                'junkemail': '垃圾邮件',
                'deleteditems': '已删除邮件',
                'all': '全部邮件'
            };

            function translateError(err) {
                if (!err) return '未知错误';
                // err 可能是 string 或 object
                if (typeof err === 'string') return err;

                const code = err.code || '';
                const details = formatFetchErrorDetails(err.details);
                const msg = err.message || '';

                // 翻译常见错误
                if (code === 'GRAPH_TOKEN_EXCEPTION' && details.includes('ProxyError')) {
                    return '代理连接失败：无法连接到代理服务器，请检查代理地址是否正确以及代理是否在运行';
                }
                if (code === 'GRAPH_TOKEN_FAILED' || code === 'IMAP_TOKEN_FAILED') {
                    if (details.includes('invalid_grant')) {
                        return 'Token 已失效或权限不足：请重新授权登录或更换 refresh_token';
                    }
                    if (details.includes('invalid_client')) {
                        return 'Client ID 无效：请检查 client_id 配置是否正确';
                    }
                    return `令牌获取失败：${msg}`;
                }
                if (code === 'EMAIL_FETCH_FAILED') {
                    return `获取邮件失败：${msg}`;
                }
                if (code === 'IMAP_CONNECTION_FAILED') {
                    return 'IMAP 连接失败：无法连接到邮件服务器';
                }
                if (code === 'IMAP_FOLDER_NOT_FOUND') {
                    return `IMAP 文件夹不存在或无权访问：${msg || '请检查邮箱服务端的实际文件夹名称'}`;
                }
                if (code === 'IMAP_AUTH_FAILED') {
                    return `IMAP 认证失败：${msg || '请检查邮箱密码或授权码'}`;
                }
                if (code === 'IMAP_UNSAFE_LOGIN_BLOCKED') {
                    return msg || '邮箱服务商拦截了当前 IMAP 登录（Unsafe Login），请检查 IMAP 开关、授权码和当前网络环境';
                }
                if (code === 'IMAP_CONNECT_FAILED') {
                    return `IMAP 连接失败：${msg || '请检查 IMAP 主机、端口和网络连通性'}`;
                }
                return msg || details || '未知错误';
            }

            const detailEntries = (typeof details === 'object' && !Array.isArray(details) && !(details.message && details.code))
                ? details
                : { error: details };
            const preferredOrder = ['graph', 'imap_new', 'imap_old', 'imap_generic', 'inbox', 'junkemail', 'deleteditems', 'all', 'error'];
            const methods = [
                ...preferredOrder.filter(method => detailEntries[method] !== undefined),
                ...Object.keys(detailEntries).filter(method => !preferredOrder.includes(method))
            ];

            const summaryEl = document.getElementById('emailFetchErrorSummary');
            if (summaryEl) {
                summaryEl.textContent = methods.length > 1
                    ? '所有获取方式均失败，以下是各方式的详细错误信息：'
                    : '获取邮件失败，以下是详细错误信息：';
            }

            let html = '';
            methods.forEach(method => {
                const err = normalizeMethodError(detailEntries[method]);
                if (err !== undefined) {
                    const name = methodNames[method] || method;
                    const reason = translateError(err);
                    const codeText = (err && typeof err === 'object') ? (err.code || '-') : '-';
                    const typeText = (err && typeof err === 'object') ? (err.type || '-') : '-';
                    const statusText = (err && typeof err === 'object') ? (err.status || '-') : '-';
                    const traceIdText = (err && typeof err === 'object') ? (err.trace_id || '-') : '-';
                    const detailText = (err && typeof err === 'object')
                        ? formatFetchErrorDetails(err.details)
                        : formatFetchErrorDetails(detailEntries[method]);
                    html += `
                        <div style="background: #fff5f5; border: 1px solid #fde2e2; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
                            <div style="font-weight: 600; color: #dc3545; margin-bottom: 6px; font-size: 14px;">${name}</div>
                            <div style="color: #333; font-size: 13px; line-height: 1.6;">${reason}</div>
                            <div style="color: #999; font-size: 12px; margin-top: 6px; line-height: 1.6;">
                                错误代码: ${escapeHtml(codeText)}<br>
                                类型: ${escapeHtml(typeText)}<br>
                                状态码: ${escapeHtml(statusText)}<br>
                                Trace ID: ${escapeHtml(traceIdText)}
                            </div>
                            ${detailText ? `<pre style="margin-top:10px; padding:10px 12px; background:#fff; border:1px solid #f3caca; border-radius:6px; color:#444; font-size:12px; line-height:1.5; white-space:pre-wrap; word-break:break-word; max-height:240px; overflow:auto;">${escapeHtml(detailText)}</pre>` : ''}
                        </div>
                    `;
                }
            });

            if (!html) {
                html = '<div style="color:#666;">无详细错误信息</div>';
            }

            document.getElementById('emailFetchErrorContent').innerHTML = html;
            showModal('emailFetchErrorModal');
        }

        function hideEmailFetchErrorModal() {
            hideModal('emailFetchErrorModal');
        }

        // 切换堆栈信息的显示/隐藏
        function toggleStackTrace() {
            const container = document.getElementById('errorModalDetailsContainer');
            const btn = document.getElementById('toggleTraceBtn');

            if (container.style.display === 'none') {
                container.style.display = 'block';
                btn.textContent = '隐藏堆栈/细节';
            } else {
                container.style.display = 'none';
                btn.textContent = '显示堆栈/细节';
            }
        }

        // 复制错误详情到剪贴板
        function copyErrorDetails() {
            const userMessage = document.getElementById('errorModalUserMessage').textContent;
            const details = document.getElementById('errorModalDetails').textContent;
            const code = document.getElementById('errorModalCode').textContent;
            const type = document.getElementById('errorModalType').textContent;
            const status = document.getElementById('errorModalStatus').textContent;
            const traceId = document.getElementById('errorModalTraceId').textContent;

            const fullErrorText = `
【用户错误信息】
${userMessage}

【错误详情】
Code: ${code}
Type: ${type}
Status: ${status}
Trace ID: ${traceId}

【技术堆栈/细节】
${details}
            `.trim();

            navigator.clipboard.writeText(fullErrorText).then(() => {
                showToast('错误详情已复制', 'success');
            }).catch(() => {
                // 降级方案
                const textarea = document.createElement('textarea');
                textarea.value = fullErrorText;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                showToast('错误详情已复制', 'success');
            });
        }

        // 统一处理 API 响应错误
        function handleApiError(data, defaultMessage = '请求失败') {
            if (!data.success) {
                // 检查是否是统一错误格式
                if (data.error && data.error.message) {
                    const error = data.error;
                    // 使用后端提供的 message 作为用户友好信息
                    const userMessage = error.message;

                    // 调用 showToast 携带完整的错误对象
                    showToast(userMessage, 'error', error);
                } else {
                    // 兼容旧的或非标准错误格式
                    const errorMessage = data.error || defaultMessage;
                    showToast(errorMessage, 'error');
                }
                return true;
            }
            return false;
        }

        function escapeJs(str) {
            if (!str) return '';
            return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r');
        }

        function updateCurrentGroupHeader(group = null, titleOverride = '') {
            const nameEl = document.getElementById('currentGroupName');
            const idBadgeEl = document.getElementById('currentGroupIdBadge');
            if (!nameEl || !idBadgeEl) {
                return;
            }

            if (titleOverride) {
                nameEl.textContent = titleOverride;
                idBadgeEl.textContent = '';
                idBadgeEl.style.display = 'none';
                return;
            }

            if (!group) {
                nameEl.textContent = '选择分组';
                idBadgeEl.textContent = '';
                idBadgeEl.style.display = 'none';
                return;
            }

            const badgeText = formatGroupIdBadgeText(group.id);
            nameEl.textContent = normalizeGroupName(group.name);
            idBadgeEl.textContent = badgeText;
            idBadgeEl.style.display = badgeText ? 'inline-flex' : 'none';
        }
