        // 全局状态
        let csrfToken = null;
        let currentAccount = null;
        let currentGroupId = null;
        let currentEmails = [];
        let currentMethod = 'graph';
        let currentFolder = 'inbox'; // 当前文件夹：inbox 或 deleteditems
        let isListVisible = true;
        let groups = [];
        let accountsCache = {}; // 缓存各分组的邮箱列表
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
            document.getElementById('importImapHost')?.addEventListener('input', updateImportHint);
            document.getElementById('importImapPort')?.addEventListener('input', updateImportHint);

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
        });

        function closeAccountActionMenus() {
            document.querySelectorAll('.account-item.menu-open').forEach(item => {
                item.classList.remove('menu-open');
            });
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
                const response = await fetch(
                    `/api/emails/${encodeURIComponent(currentAccount)}?method=${currentMethod}&folder=${currentFolder}&skip=${currentSkip}&top=20`
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
                showToast('加载失败', 'error');
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
                        <div class="empty-state-text">正在自动刷新${folder === 'inbox' ? '收件箱' : '垃圾邮件'}...</div>
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

        function showModal(modalId) {
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
            if (!currentForwardingLogAccountId) {
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">未选择账号</div>';
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
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #dc3545;">加载账号转发日志失败</div>';
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
                }
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-text">加载失败</div></div>';
                showToast('加载分组失败', 'error');
            }
        }

        // 渲染分组列表
        function renderGroupList(groups) {
            const container = document.getElementById('groupList');

            if (groups.length === 0) {
                container.innerHTML = `
                    <div class="empty-state" style="padding: 40px 20px;">
                        <div class="empty-state-text">暂无分组</div>
                    </div>
                `;
                return;
            }

            container.innerHTML = groups.map(group => {
                const isSystem = group.is_system === 1 || group.name === '临时邮箱';
                const isTempGroup = group.name === '临时邮箱';
                const isDefault = group.id === 1;
                const isDragging = groupDragState.isDragging && groupDragState.groupId === group.id;

                return `
                    <div class="group-item ${currentGroupId === group.id ? 'active' : ''} ${isTempGroup ? 'temp-email-group' : ''} ${!isTempGroup ? 'draggable' : ''} ${isDragging ? 'dragging' : ''}"
                         data-group-id="${group.id}"
                         ${!isTempGroup ? `onpointerdown="handleGroupPointerDown(event, ${group.id})"` : ''}
                         onclick="handleGroupClick(event, ${group.id})">
                        <div class="group-row-1">
                            <div class="group-color" style="background-color: ${group.color || '#666'}"></div>
                            <span class="group-name">${escapeHtml(group.name)}${isTempGroup ? ' ⚡' : ''}</span>
                        </div>
                        <div class="group-row-2">
                            <span class="group-count">${group.account_count || 0} 个邮箱</span>
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
                document.getElementById('currentGroupName').textContent = group.name;
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
            // 更新底部按钮
            updateAccountPanelFooter();

            // 加载该分组的邮箱
            if (isTempEmailGroup) {
                await loadTempEmails();
            } else {
                await loadAccountsByGroup(groupId);
            }
        }

        // 更新账号面板底部按钮
        function updateAccountPanelFooter() {
            const footer = document.querySelector('.account-panel-footer');
            if (isTempEmailGroup) {
                footer.innerHTML = `
                    <button class="add-account-btn" onclick="generateTempEmail()" style="margin-bottom: 8px;">+ 生成临时邮箱</button>
                    <button class="add-account-btn" onclick="showAddAccountModal()">+ 导入邮箱</button>
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
                footer.innerHTML = `
                    <button class="add-account-btn" onclick="showGetRefreshTokenModal()" style="background-color: #0078d4; margin-bottom: 8px;">🔑 获取 Refresh Token</button>
                    <button class="add-account-btn" onclick="showAddAccountModal()">+ 导入邮箱</button>
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
                renderAccountList(accountsCache[groupId]);
                return;
            }

            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/accounts?group_id=${groupId}`);
                const data = await response.json();

                if (data.success) {
                    // 缓存数据
                    accountsCache[groupId] = data.accounts;
                    renderAccountList(data.accounts);
                }
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-text">加载失败</div></div>';
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

            if (accounts.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📭</div>
                        <div class="empty-state-text">该分组暂无邮箱</div>
                    </div>
                `;
                return;
            }

            container.innerHTML = accounts.map((acc, index) => `
                <div class="account-item ${currentAccount === acc.email ? 'active' : ''} ${acc.status === 'inactive' ? 'inactive' : ''}"
                     onclick="handleAccountItemClick(event, '${escapeJs(acc.email)}')">
                    <input type="checkbox" class="account-select-checkbox" value="${acc.id}" 
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
            if (accountsCache[currentGroupId]) {
                const sortedAccounts = applyFiltersAndSort(accountsCache[currentGroupId]);
                renderAccountList(sortedAccounts);
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
            // Get checked tags
            const checkedBoxes = document.querySelectorAll('.tag-filter-checkbox:checked');
            const selectedTagIds = Array.from(checkedBoxes).map(cb => parseInt(cb.value));

            if (selectedTagIds.length > 0) {
                result = result.filter(acc => {
                    if (!acc.tags) return false;
                    // Check if account has ANY of the selected tags (OR logic)
                    // If you want AND logic, use every() instead of some()
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
            if (accountsCache[currentGroupId]) {
                const filteredAccounts = applyFiltersAndSort(accountsCache[currentGroupId]);
                renderAccountList(filteredAccounts);
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
            const titleElement = document.getElementById('currentGroupName');

            if (!query.trim()) {
                loadAccountsByGroup(currentGroupId);
                return;
            }

            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/accounts/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();

                if (data.success) {
                    titleElement.textContent = `搜索结果 (${data.accounts.length})`;
                    renderAccountList(data.accounts);
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
            const selects = ['importGroupSelect', 'editGroupSelect'];
            selects.forEach(selectId => {
                const select = document.getElementById(selectId);
                if (select) {
                    const currentValue = select.value;
                    // editGroupSelect 过滤掉临时邮箱分组（不能移动到临时邮箱分组）
                    const filteredGroups = selectId === 'editGroupSelect'
                        ? groups.filter(g => g.name !== '临时邮箱')
                        : groups;

                    select.innerHTML = filteredGroups.map(g =>
                        `<option value="${g.id}">${escapeHtml(g.name)}</option>`
                    ).join('');
                    // 恢复之前的选择
                    if (currentValue && filteredGroups.find(g => g.id === parseInt(currentValue))) {
                        select.value = currentValue;
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

        // 更新导入提示文本和渠道选择器
        function updateImportHint() {
            const importSelect = document.getElementById('importGroupSelect');
            const hintEl = document.getElementById('importFormatHint');
            const inputEl = document.getElementById('accountInput');
            const channelGroup = document.getElementById('importChannelGroup');
            const channelSelect = document.getElementById('importChannelSelect');
            const exampleEl = document.getElementById('importFormatExample');
            if (!importSelect || !hintEl || !inputEl) return;

            const selectedGroup = groups.find(g => g.id === parseInt(importSelect.value));
            const isTempGroup = selectedGroup && selectedGroup.name === '临时邮箱';

            if (isTempGroup) {
                // 显示渠道选择器
                if (channelGroup) channelGroup.style.display = '';

                const channel = channelSelect ? channelSelect.value : 'gptmail';
                if (channel === 'duckmail') {
                    hintEl.textContent = '格式：邮箱----密码，每行一个';
                    inputEl.placeholder = '邮箱----密码';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\nuser@duck.com----mypassword\nuser2@duck.com----password2';
                    }
                } else if (channel === 'cloudflare') {
                    hintEl.textContent = '格式：邮箱----JWT，每行一个';
                    inputEl.placeholder = '邮箱----JWT';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\nuser@example.com----eyJhbGciOi...\nuser2@example.com----eyJ0eXAiOi...';
                    }
                } else {
                    hintEl.textContent = '格式：每行一个邮箱地址';
                    inputEl.placeholder = '每行一个邮箱地址';
                    if (exampleEl) {
                        exampleEl.style.display = '';
                        exampleEl.textContent = '示例：\nuser1@gptmail.com\nuser2@gptmail.com';
                    }
                }
            } else {
                // 隐藏渠道选择器
                if (channelGroup) channelGroup.style.display = 'none';
                if (exampleEl) exampleEl.style.display = '';
                hintEl.textContent = 'Outlook 支持两种格式并自动识别：邮箱----密码----client_id----refresh_token 或 邮箱----密码----refresh_token----client_id';
                inputEl.placeholder = '邮箱----密码----client_id----refresh_token';
                if (exampleEl) {
                    exampleEl.textContent = '示例：\nuser@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA...\nuser@outlook.com----password123----0.AXEA...----24d9a0ed-8787-4584-883c-2fd79308940a';
                }
                return;
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
                telegram: 'telegram'
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
            return ['smtp', 'telegram'].filter(channel =>
                document.getElementById(`forwardChannel${channel === 'smtp' ? 'Smtp' : 'Telegram'}`)?.checked
            );
        }

        function setSelectedForwardChannels(rawChannels) {
            const channels = normalizeForwardChannels(rawChannels);
            const smtpCheckbox = document.getElementById('forwardChannelSmtp');
            const telegramCheckbox = document.getElementById('forwardChannelTelegram');
            if (smtpCheckbox) smtpCheckbox.checked = channels.includes('smtp');
            if (telegramCheckbox) telegramCheckbox.checked = channels.includes('telegram');
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
            if (!confirm('确定要删除该分组吗？分组下的邮箱将移至默认分组。')) {
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

        // ==================== 临时邮箱相关 ====================

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
                    accountsCache['temp'] = data.emails;
                    renderTempEmailList(data.emails);

                    const group = groups.find(g => g.name === '临时邮箱');
                    if (group) {
                        group.account_count = data.emails.length;
                        renderGroupList(groups);
                    }
                }
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-text">加载失败</div></div>';
            }
        }

        // 渲染临时邮箱列表
        function renderTempEmailList(emails) {
            const container = document.getElementById('accountList');

            // 渠道筛选
            const filter = localStorage.getItem('outlook_temp_email_filter') || 'all';
            const filtered = filter === 'all' ? emails : emails.filter(e => e.provider === filter);

            if (filtered.length === 0) {
                const providerName = filter === 'duckmail' ? 'DuckMail' : (filter === 'cloudflare' ? 'Cloudflare' : 'GPTMail');
                const hint = filter === 'all' ? '暂无临时邮箱<br>点击下方按钮生成' : `暂无 ${providerName} 邮箱`;
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">⚡</div>
                        <div class="empty-state-text">${hint}</div>
                    </div>
                `;
                return;
            }

            container.innerHTML = filtered.map(email => `
                <div class="account-item ${currentAccount === email.email ? 'active' : ''}"
                     onclick="handleAccountItemClick(event, '${escapeJs(email.email)}', true)">
                    <div class="account-leading-icon">⚡</div>
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
                        </div>
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
                modal.onclick = function (e) { if (e.target === modal) hideTempEmailProviderModal(); };
                modal.innerHTML = `
                    <div class="modal-content" style="width: 460px;">
                        <div class="modal-header">
                            <h3>⚡ 生成临时邮箱</h3>
                            <button class="modal-close" onclick="hideTempEmailProviderModal()">&times;</button>
                        </div>
                        <div class="modal-body">
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
                                    <label class="form-label">域名</label>
                                    <select class="form-input" id="cloudflareDomain" style="width: 100%;">
                                        <option value="">加载中...</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">用户名（可选）</label>
                                    <input type="text" class="form-input" id="cloudflareUsername" placeholder="留空则随机生成">
                                    <div class="form-hint">如填写，至少 3 个字符；不填则后端自动生成随机前缀</div>
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
                loadCloudflareDomains();
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
            const select = document.getElementById('cloudflareDomain');
            select.innerHTML = '<option value="">加载中...</option>';
            try {
                const response = await fetch('/api/cloudflare/domains');
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
                    body.domain = document.getElementById('cloudflareDomain').value;
                    body.username = document.getElementById('cloudflareUsername').value.trim();

                    if (!body.domain) {
                        showToast('请选择域名', 'error');
                        return;
                    }
                    if (body.username && body.username.length < 3) {
                        showToast('用户名至少 3 个字符，或留空随机生成', 'error');
                        return;
                    }
                }

                const response = await fetch('/api/temp-emails/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });

                const data = await response.json();

                if (data.success) {
                    showToast(`临时邮箱已生成: ${data.email}`, 'success');
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
            isTempEmailGroup = true;
            currentEmailId = null;
            currentEmailDetail = null;

            document.getElementById('currentAccount').classList.add('show');
            document.getElementById('currentAccountEmail').textContent = email + ' (临时)';

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

        // 清空临时邮箱的所有邮件
        async function clearTempEmailMessages(email) {
            if (!confirm(`确定要清空临时邮箱 ${email} 的所有邮件吗？`)) {
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
            if (!confirm(`确定要删除临时邮箱 ${email} 吗？\n该邮箱的所有邮件也将被删除。`)) {
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
            currentEmailId = messageId;
            document.querySelectorAll('.email-item').forEach((item, i) => {
                item.classList.toggle('active', i === index);
            });

            document.getElementById('emailDetailToolbar').style.display = 'flex';
            const deleteBtn = document.querySelector('#emailDetailToolbar .batch-btn.danger');
            if (deleteBtn) deleteBtn.style.display = 'none';

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

        // ==================== 账号相关 ====================

        // 选择账号
        function selectAccount(email) {
            currentAccount = email;
            isTempEmailGroup = false;
            currentFolder = 'inbox'; // 重置为收件箱
            currentEmailId = null;
            currentEmailDetail = null;

            document.getElementById('currentAccount').classList.add('show');
            document.getElementById('currentAccountEmail').textContent = email;

            document.querySelectorAll('.account-item').forEach(item => {
                item.classList.remove('active');
                const emailEl = item.querySelector('.account-email');
                if (emailEl && emailEl.textContent.includes(email)) {
                    item.classList.add('active');
                }
            });

            // 显示文件夹切换按钮
            const folderTabs = document.getElementById('folderTabs');
            if (folderTabs) {
                folderTabs.style.display = 'flex';
                // 重置为收件箱
                document.querySelectorAll('.folder-tab').forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.folder === 'inbox');
                });
            }

            const cacheKey = `${email}_inbox`;

            // 检查缓存
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
                document.getElementById('emailList').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📬</div>
                        <div class="empty-state-text">正在自动刷新收件箱...</div>
                    </div>
                `;
                document.getElementById('emailCount').textContent = '';
                document.getElementById('methodTag').style.display = 'none';
                currentEmails = [];
            }

            document.getElementById('emailDetail').innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📄</div>
                    <div class="empty-state-text">选择一封邮件查看详情</div>
                </div>
            `;
            document.getElementById('emailDetailToolbar').style.display = 'none';

            // 选中账号后自动刷新收件箱
            loadEmails(email, true);
        }

        // 显示添加账号模态框
        function showAddAccountModalLegacy() {
            document.getElementById('accountInput').value = '';
            // 设置默认分组为当前选中的分组
            if (currentGroupId) {
                document.getElementById('importGroupSelect').value = currentGroupId;
            }
            updateImportHint();
            setModalVisible('addAccountModal', true);
        }

        // 隐藏添加账号模态框
        function hideAddAccountModal() {
            hideModal('addAccountModal');
        }

        // 添加账号
        async function addAccountLegacy() {
            const input = document.getElementById('accountInput').value.trim();
            const groupId = parseInt(document.getElementById('importGroupSelect').value);

            if (!input) {
                showToast('请输入账号信息', 'error');
                return;
            }

            // 检查是否是临时邮箱分组
            const selectedGroup = groups.find(g => g.id === groupId);
            const isTempGroup = selectedGroup && selectedGroup.name === '临时邮箱';

            try {
                let response;
                if (isTempGroup) {
                    // 临时邮箱导入使用专用 API，传入选中的渠道
                    const provider = document.getElementById('importChannelSelect').value || 'gptmail';
                    response = await fetch('/api/temp-emails/import', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ account_string: input, provider: provider })
                    });
                } else {
                    response = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ account_string: input, group_id: groupId })
                    });
                }

                const data = await response.json();

                if (data.success) {
                    showToast(data.message, 'success');
                    hideAddAccountModal();

                    // 清除该分组的缓存
                    delete accountsCache[groupId];

                    // 刷新分组列表（更新数量）
                    await loadGroups();

                    // 刷新邮箱列表
                    if (isTempGroup) {
                        await loadTempEmails(true);
                    } else {
                        await loadAccountsByGroup(groupId, true);
                    }
                } else {
                    handleApiError(data, '导入失败');
                }
            } catch (error) {
                showToast('导入失败', 'error');
            }
        }

        // 显示编辑账号模态框
        async function showEditAccountModalLegacy(accountId) {
            try {
                const response = await fetch(`/api/accounts/${accountId}`);
                const data = await response.json();

                if (data.success) {
                    const acc = data.account;
                    document.getElementById('editAccountId').value = acc.id;
                    document.getElementById('editEmail').value = acc.email;
                    document.getElementById('editPassword').value = acc.password || '';
                    document.getElementById('editClientId').value = acc.client_id;
                    document.getElementById('editRefreshToken').value = acc.refresh_token;
                    document.getElementById('editGroupSelect').value = acc.group_id || 1;
                    document.getElementById('editRemark').value = acc.remark || '';
                    document.getElementById('editStatus').value = acc.status || 'active';
                    setModalVisible('editAccountModal', true);
                }
            } catch (error) {
                showToast('加载账号信息失败', 'error');
            }
        }

        // 隐藏编辑账号模态框
        function hideEditAccountModal() {
            hideModal('editAccountModal');
        }

        // 更新账号
        async function updateAccountLegacy() {
            const accountId = document.getElementById('editAccountId').value;
            const oldGroupId = currentGroupId;
            const newGroupId = parseInt(document.getElementById('editGroupSelect').value);

            const data = {
                email: document.getElementById('editEmail').value.trim(),
                password: document.getElementById('editPassword').value,
                client_id: document.getElementById('editClientId').value.trim(),
                refresh_token: document.getElementById('editRefreshToken').value.trim(),
                group_id: newGroupId,
                remark: document.getElementById('editRemark').value.trim(),
                status: document.getElementById('editStatus').value
            };

            if (!data.email || !data.client_id || !data.refresh_token) {
                showToast('邮箱、Client ID 和 Refresh Token 不能为空', 'error');
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (result.success) {
                    showToast(result.message, 'success');
                    hideEditAccountModal();

                    // 清除相关分组的缓存
                    delete accountsCache[oldGroupId];
                    if (oldGroupId !== newGroupId) {
                        delete accountsCache[newGroupId];
                    }

                    // 刷新分组列表
                    loadGroups();

                    // 刷新当前分组的邮箱列表
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    showToast(result.error, 'error');
                }
            } catch (error) {
                showToast('更新失败', 'error');
            }
        }

        // 删除当前编辑的账号
        async function deleteCurrentAccount() {
            const accountId = document.getElementById('editAccountId').value;
            const email = document.getElementById('editEmail').value;
            const groupId = parseInt(document.getElementById('editGroupSelect').value);

            if (!confirm(`确定要删除账号 ${email} 吗？`)) {
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');
                    hideEditAccountModal();

                    // 清除缓存
                    delete accountsCache[groupId];

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
                    }

                    // 刷新分组列表
                    loadGroups();

                    // 刷新当前分组的邮箱列表
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }

        // 切换账号状态（启用/停用）
        async function toggleAccountStatus(accountId, currentStatus) {
            const newStatus = currentStatus === 'inactive' ? 'active' : 'inactive';
            const action = newStatus === 'inactive' ? '停用' : '启用';

            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: newStatus })
                });

                const data = await response.json();

                if (data.success) {
                    showToast(`${action}成功`, 'success');

                    // 清除当前分组的缓存
                    if (currentGroupId) {
                        delete accountsCache[currentGroupId];
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    handleApiError(data, `${action}账号失败`);
                }
            } catch (error) {
                showToast(`${action}失败`, 'error');
            }
        }

        // 删除账号（快捷方式）
        async function deleteAccount(accountId, email) {
            if (!confirm(`确定要删除账号 ${email} 吗？`)) {
                return;
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');

                    // 清除当前分组的缓存
                    if (currentGroupId) {
                        delete accountsCache[currentGroupId];
                    }

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
                    }

                    // 刷新分组列表
                    loadGroups();

                    // 刷新当前分组的邮箱列表
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    handleApiError(data, '删除账号失败');
                }
            } catch (error) {
                showToast('删除失败', 'error');
            }
        }

        // 显示导出邮箱模态框
        async function showExportModal() {
            showModal('exportModal');
            await loadExportGroupList();
        }

        // 隐藏导出邮箱模态框
        function hideExportModal() {
            hideModal('exportModal');
        }

        // 加载导出分组列表
        async function loadExportGroupList() {
            const container = document.getElementById('exportGroupList');
            container.innerHTML = '<div class="loading loading-small"><div class="loading-spinner"></div></div>';

            try {
                // 使用已加载的分组数据
                if (groups.length === 0) {
                    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #999;">暂无分组</div>';
                } else {
                    container.innerHTML = groups.map(group => `
                        <label style="display: flex; align-items: center; gap: 10px; padding: 10px 12px; cursor: pointer; border-radius: 6px; transition: background-color 0.15s;"
                               onmouseover="this.style.backgroundColor='#f5f5f5'"
                               onmouseout="this.style.backgroundColor='transparent'">
                            <input type="checkbox" class="export-group-checkbox" value="${group.id}" style="width: 16px; height: 16px;">
                            <span style="display: flex; align-items: center; gap: 8px; flex: 1;">
                                <span style="width: 12px; height: 12px; border-radius: 3px; background-color: ${group.color || '#666'}"></span>
                                <span style="font-size: 14px; color: #1a1a1a;">${escapeHtml(group.name)}</span>
                            </span>
                            <span style="font-size: 12px; color: #999; background-color: #f0f0f0; padding: 2px 8px; border-radius: 10px;">${group.account_count || 0}</span>
                        </label>
                    `).join('');
                }
            } catch (error) {
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: #dc3545;">加载失败</div>';
            }

            // 重置全选复选框
            document.getElementById('selectAllGroups').checked = false;
        }

        // 全选/取消全选分组
        function toggleSelectAllGroups() {
            const selectAll = document.getElementById('selectAllGroups').checked;
            document.querySelectorAll('.export-group-checkbox').forEach(cb => {
                cb.checked = selectAll;
            });
        }

        // 存储待导出的分组ID
        let pendingExportGroupIds = [];

        // 导出选中的分组
        async function exportSelectedGroups() {
            const checkboxes = document.querySelectorAll('.export-group-checkbox:checked');
            const groupIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

            if (groupIds.length === 0) {
                showToast('请选择要导出的分组', 'error');
                return;
            }

            // 保存待导出的分组ID
            pendingExportGroupIds = groupIds;

            // 显示密码确认对话框
            hideExportModal();
            showExportVerifyModal();
        }

        // 显示导出密码确认对话框
        function showExportVerifyModal() {
            showModal('exportVerifyModal');
            const passwordInput = document.getElementById('exportVerifyPassword');
            if (passwordInput) {
                passwordInput.value = '';
                passwordInput.focus();
            }
        }

        // 隐藏导出密码确认对话框
        function hideExportVerifyModal() {
            hideModal('exportVerifyModal');
            const passwordInput = document.getElementById('exportVerifyPassword');
            if (passwordInput) {
                passwordInput.value = '';
            }
        }

        // 确认导出验证
        async function confirmExportVerify() {
            const password = document.getElementById('exportVerifyPassword').value;

            if (!password) {
                showToast('请输入密码', 'error');
                return;
            }

            try {
                // 获取验证token
                const verifyResponse = await fetch('/api/export/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });

                const verifyData = await verifyResponse.json();

                if (!verifyData.success) {
                    showToast(verifyData.error || '密码错误', 'error');
                    return;
                }

                const verifyToken = verifyData.verify_token;

                // 执行导出
                const response = await fetch('/api/accounts/export-selected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        group_ids: pendingExportGroupIds,
                        verify_token: verifyToken
                    })
                });

                if (response.ok) {
                    // 获取文件名
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = 'accounts.txt';
                    if (contentDisposition) {
                        const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?([^;\n]+)/i);
                        if (match) {
                            filename = decodeURIComponent(match[1]);
                        }
                    }

                    // 下载文件
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);

                    showToast('导出成功', 'success');
                    hideExportVerifyModal();
                } else {
                    const data = await response.json();
                    handleApiError(data, '导出失败');
                }
            } catch (error) {
                showToast('导出失败', 'error');
            }
        }

        // ==================== 邮件相关 ====================

        // 加载邮件列表
        async function loadEmails(email, forceRefresh = false) {
            const container = document.getElementById('emailList');

            // 切换账号/刷新时清除选中状态
            selectedEmailIds.clear();
            updateEmailBatchActionBar();

            // 检查缓存
            const cacheKey = `${email}_${currentFolder}`;
            if (!forceRefresh && emailListCache[cacheKey]) {
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
                return;
            }

            // 禁用按钮
            const refreshBtn = document.querySelector('.refresh-btn');
            const folderTabs = document.querySelectorAll('.folder-tab');
            if (refreshBtn) {
                refreshBtn.disabled = true;
                refreshBtn.textContent = '获取中...';
            }
            folderTabs.forEach(tab => tab.disabled = true);

            // 重置分页状态
            currentSkip = 0;
            hasMoreEmails = true;

            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';

            try {
                // 每次只查询20封邮件
                const response = await fetch(
                    `/api/emails/${encodeURIComponent(email)}?method=${currentMethod}&folder=${currentFolder}&skip=0&top=20`
                );
                const data = await response.json();

                if (data.success) {
                    currentEmails = data.emails;
                    currentMethod = data.method === 'Graph API' ? 'graph' : 'imap';
                    hasMoreEmails = data.has_more;

                    // 保存到缓存
                    emailListCache[cacheKey] = {
                        emails: currentEmails,
                        has_more: hasMoreEmails,
                        skip: currentSkip,
                        method: currentMethod
                    };

                    // 显示使用的方法和邮件数量
                    const methodTag = document.getElementById('methodTag');
                    methodTag.textContent = data.method;
                    methodTag.style.display = 'inline';

                    document.getElementById('emailCount').textContent = `(${data.emails.length})`;

                    renderEmailList(data.emails);
                } else {
                    // 显示详细的多方法失败弹框
                    const fetchErrorDetails = data.details || (data.error ? { error: data.error } : {});
                    if (Object.keys(fetchErrorDetails).length > 0) {
                        showEmailFetchErrorModal(fetchErrorDetails);
                    } else {
                        handleApiError(data, '获取邮件失败');
                    }
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">⚠️</div>
                            <div class="empty-state-text">获取邮件失败，<a href="javascript:void(0)" onclick="showEmailFetchErrorModal(window._lastFetchErrorDetails)" style="color:#409eff;text-decoration:underline;">点击查看详情</a></div>
                        </div>
                    `;
                    window._lastFetchErrorDetails = fetchErrorDetails;
                }
            } catch (error) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">⚠️</div>
                        <div class="empty-state-text">网络错误，请重试</div>
                    </div>
                `;
            } finally {
                // 启用按钮
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = '获取邮件';
                }
                folderTabs.forEach(tab => tab.disabled = false);
            }
        }

        // 渲染邮件列表
        // Selected email IDs
        let selectedEmailIds = new Set();
        let isBatchSelectMode = false;

        function renderEmailList(emails) {
            const container = document.getElementById('emailList');

            if (emails.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📭</div>
                        <div class="empty-state-text">收件箱为空</div>
                    </div>
                `;
                // Reset selection
                selectedEmailIds.clear();
                currentEmailId = null;
                updateEmailBatchActionBar();
                return;
            }

            // 根据是否是临时邮箱选择不同的点击处理函数
            const clickHandler = isTempEmailGroup ? 'getTempEmailDetail' : 'selectEmail';

            container.innerHTML = emails.map((email, index) => {
                const isChecked = selectedEmailIds.has(email.id);
                const isActive = currentEmailId === email.id;
                return `
                <div class="email-item ${email.is_read === false ? 'unread' : ''} ${isActive ? 'active' : ''}"
                     onclick="${clickHandler}('${email.id}', ${index})">
                    <div class="email-checkbox-wrapper" onclick="event.stopPropagation(); toggleEmailSelection('${email.id}')">
                        <input type="checkbox" class="email-checkbox" ${isChecked ? 'checked' : ''} style="pointer-events: none;">
                    </div>
                    <div class="email-body">
                        <div class="email-top-row">
                            <div class="email-top-main">
                                <div class="email-from" title="${escapeHtml(email.from || '未知发件人')}">${escapeHtml(email.from || '未知发件人')}</div>
                            </div>
                            <div class="email-date">${formatDate(email.date)}</div>
                        </div>
                        <div class="email-subject">${escapeHtml(email.subject || '无主题')}</div>
                        <div class="email-preview">${escapeHtml((email.body_preview || '').trim() || '暂无预览内容')}</div>
                    </div>
                </div>
            `}).join('');

            updateEmailBatchActionBar();
        }

        function toggleEmailSelection(emailId) {
            if (selectedEmailIds.has(emailId)) {
                selectedEmailIds.delete(emailId);
            } else {
                selectedEmailIds.add(emailId);
            }

            // Re-render to update checkbox UI (or efficiently update DOM)
            // For simplicity, we just find the checkbox and update it
            // implementation below is cheap
            renderEmailList(currentEmails);
        }

        function updateEmailBatchActionBar() {
            const bar = document.getElementById('emailBatchActionBar');
            const selectAllBtn = document.getElementById('emailSelectAllBtn');
            if (isTempEmailGroup) {
                bar.style.display = 'none';
                return;
            }
            if (selectedEmailIds.size > 0) {
                bar.style.display = 'flex';
                document.getElementById('emailSelectedCount').textContent = `已选 ${selectedEmailIds.size} 项`;
                if (selectAllBtn) {
                    selectAllBtn.textContent = currentEmails.length > 0 && selectedEmailIds.size === currentEmails.length
                        ? '取消全选'
                        : '全选当前列表';
                }
            } else {
                bar.style.display = 'none';
            }
        }

        function toggleSelectAllEmails() {
            if (!currentEmails.length) return;

            const shouldClear = selectedEmailIds.size === currentEmails.length;
            if (shouldClear) {
                selectedEmailIds.clear();
            } else {
                currentEmails.forEach(email => selectedEmailIds.add(email.id));
            }
            renderEmailList(currentEmails);
        }

        function clearEmailSelection() {
            if (selectedEmailIds.size === 0) return;
            selectedEmailIds.clear();
            renderEmailList(currentEmails);
        }

        async function confirmBatchDeleteEmails() {
            if (selectedEmailIds.size === 0) return;

            if (!confirm(`确定要永久删除选中的 ${selectedEmailIds.size} 封邮件吗？此操作不可恢复！`)) {
                return;
            }

            await deleteEmails(Array.from(selectedEmailIds));
        }

        async function confirmDeleteCurrentEmail() {
            if (isTempEmailGroup) return;
            if (!currentEmailDetail || !currentEmailDetail.id) return;

            if (!confirm('确定要永久删除这封邮件吗？此操作不可恢复！')) {
                return;
            }

            await deleteEmails([currentEmailDetail.id]);
        }

        async function deleteEmails(ids) {
            showToast('正在删除...', 'info');

            try {
                const response = await fetch('/api/emails/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: currentAccount,
                        ids: ids
                    })
                });

                const result = await response.json();

                if (result.success) {
                    showToast(`成功删除 ${result.success_count} 封邮件`);

                    // Remove deleted emails from currentEmails
                    const deletedIds = new Set(ids); // Ideally result should return what was deleted
                    currentEmails = currentEmails.filter(e => !deletedIds.has(e.id));
                    selectedEmailIds.clear();
                    if (currentEmailId && deletedIds.has(currentEmailId)) {
                        currentEmailId = null;
                    }

                    renderEmailList(currentEmails);

                    // If current viewed email was deleted, clear view
                    if (currentEmailDetail && deletedIds.has(currentEmailDetail.id)) {
                        currentEmailId = null;
                        currentEmailDetail = null;
                        document.getElementById('emailDetail').innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">🗑️</div>
                                <div class="empty-state-text">邮件已删除</div>
                            </div>
                        `;
                        document.getElementById('emailDetailToolbar').style.display = 'none';
                    }

                    // If errors
                    if (result.failed_count > 0) {
                        console.warn('Deletion errors:', result.errors);
                        showToast(`部分删除失败 (${result.failed_count} 封)`, 'warning');
                    }
                } else {
                    showToast('删除失败: ' + (result.error || '未知错误'), 'error');
                }
            } catch (e) {
                showToast('网络错误', 'error');
                console.error(e);
            }
        }

        // 选择邮件
        async function selectEmail(messageId, index) {
            currentEmailId = messageId;
            // 更新 UI
            document.querySelectorAll('.email-item').forEach((item, i) => {
                item.classList.toggle('active', i === index);
            });

            // 这里不重置 currentEmailDetail，等到 fetch 成功后再设置

            // 重置信任模式
            document.getElementById('trustEmailCheckbox').checked = false;
            isTrustedMode = false;

            // 显示工具栏
            document.getElementById('emailDetailToolbar').style.display = 'flex';
            const deleteBtn = document.querySelector('#emailDetailToolbar .batch-btn.danger');
            if (deleteBtn) deleteBtn.style.display = '';

            // 加载邮件详情
            const container = document.getElementById('emailDetail');
            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetch(`/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(messageId)}?method=${currentMethod}&folder=${currentFolder}`);
                const data = await response.json();

                if (data.success) {
                    currentEmailDetail = data.email;
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

        // 渲染邮件详情
        function renderEmailDetail(email) {
            const container = document.getElementById('emailDetail');

            const isHtml = email.body_type === 'html' ||
                (email.body && (email.body.includes('<html') || email.body.includes('<div') || email.body.includes('<p>')));

            const bodyContent = isHtml
                ? `<iframe id="emailBodyFrame" sandbox="allow-same-origin" onload="adjustIframeHeight(this)"></iframe>`
                : `<div class="email-body-text">${escapeHtml(email.body)}</div>`;

            container.innerHTML = `
                <div class="email-detail-header">
                    <div class="email-detail-subject">${escapeHtml(email.subject || '无主题')}</div>
                    <div class="email-detail-meta">
                        <div class="email-detail-meta-row">
                            <span class="email-detail-meta-label">发件人</span>
                            <span class="email-detail-meta-value">${escapeHtml(email.from)}</span>
                        </div>
                        <div class="email-detail-meta-row">
                            <span class="email-detail-meta-label">收件人</span>
                            <span class="email-detail-meta-value">${escapeHtml(email.to || '-')}</span>
                        </div>
                        ${email.cc ? `
                        <div class="email-detail-meta-row">
                            <span class="email-detail-meta-label">抄送</span>
                            <span class="email-detail-meta-value">${escapeHtml(email.cc)}</span>
                        </div>
                        ` : ''}
                        <div class="email-detail-meta-row">
                            <span class="email-detail-meta-label">时间</span>
                            <span class="email-detail-meta-value">${formatDate(email.date)}</span>
                        </div>
                    </div>
                </div>
                <div class="email-detail-body">
                    ${bodyContent}
                </div>
            `;

            // 如果是 HTML 内容，设置 iframe 内容
            if (isHtml) {
                const iframe = document.getElementById('emailBodyFrame');
                if (iframe) {
                    let sanitizedBody;
                    if (isTrustedMode) {
                        sanitizedBody = email.body; // 信任模式：不过滤
                    } else {
                        // 使用 DOMPurify 净化 HTML 内容，防止 XSS 攻击
                        sanitizedBody = DOMPurify.sanitize(email.body, {
                            ALLOWED_TAGS: ['a', 'b', 'i', 'u', 'strong', 'em', 'p', 'br', 'div', 'span', 'img', 'table', 'tr', 'td', 'th', 'thead', 'tbody', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code'],
                            ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'style', 'class', 'width', 'height', 'align', 'border', 'cellpadding', 'cellspacing'],
                            ALLOW_DATA_ATTR: false,
                            FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button'],
                            FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur']
                        });
                    }

                    const htmlContent = `
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <meta charset="UTF-8">
                            <style>
                                body {
                                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                                    font-size: 15px;
                                    line-height: 1.6;
                                    color: #333;
                                    margin: 0;
                                    padding: 0;
                                    background-color: #ffffff;
                                }
                                img {
                                    max-width: 100%;
                                    height: auto;
                                }
                                a {
                                    color: #0078d4;
                                }
                            </style>
                        </head>
                        <body>${sanitizedBody}</body>
                        </html>
                    `;
                    iframe.srcdoc = htmlContent;
                }
            }
        }

        // 动态调整 iframe 高度
        function adjustIframeHeight(iframe) {
            try {
                // 多次尝试调整高度，确保内容完全加载
                const adjustHeight = () => {
                    if (iframe.contentDocument && iframe.contentDocument.body) {
                        const body = iframe.contentDocument.body;
                        const html = iframe.contentDocument.documentElement;
                        // 获取实际内容高度（取最大值）
                        const height = Math.max(
                            body.scrollHeight,
                            body.offsetHeight,
                            html.clientHeight,
                            html.scrollHeight,
                            html.offsetHeight
                        );
                        // 设置最小高度为 600px，添加 100px 余量确保长邮件能完整显示
                        iframe.style.height = Math.max(height + 100, 600) + 'px';
                    }
                };

                // 立即调整一次
                adjustHeight();
                // 100ms 后再调整（等待图片等资源加载）
                setTimeout(adjustHeight, 100);
                // 300ms 后再调整
                setTimeout(adjustHeight, 300);
                // 500ms 后再调整（确保所有内容都已加载）
                setTimeout(adjustHeight, 500);
                // 1秒后最后调整一次
                setTimeout(adjustHeight, 1000);
                // 2秒后再次调整（处理延迟加载的内容）
                setTimeout(adjustHeight, 2000);

                // 监听 iframe 内容变化
                if (iframe.contentDocument) {
                    const observer = new MutationObserver(adjustHeight);
                    observer.observe(iframe.contentDocument.body, {
                        childList: true,
                        subtree: true,
                        attributes: true
                    });

                    // 监听图片加载完成事件
                    const images = iframe.contentDocument.querySelectorAll('img');
                    images.forEach(img => {
                        img.addEventListener('load', adjustHeight);
                        img.addEventListener('error', adjustHeight);
                    });
                }
            } catch (e) {
                console.log('Cannot adjust iframe height:', e);
            }
        }

        // 切换邮件列表显示
        function toggleEmailList() {
            const panel = document.getElementById('emailListPanel');
            const toggleText = document.getElementById('toggleListText');

            isListVisible = !isListVisible;

            if (isListVisible) {
                panel.classList.remove('hidden');
                toggleText.textContent = '隐藏列表';
            } else {
                panel.classList.add('hidden');
                toggleText.textContent = '显示列表';
            }
        }

        // 全屏查看邮件
        let currentFullscreenEmail = null;

        function openFullscreenEmail() {
            const emailDetail = document.getElementById('emailDetail');
            const modal = document.getElementById('fullscreenEmailModal');
            const content = document.getElementById('fullscreenEmailContent');
            const title = document.getElementById('fullscreenEmailTitle');

            // 获取当前邮件的标题
            const subjectElement = emailDetail.querySelector('.email-detail-subject');
            if (subjectElement) {
                title.textContent = subjectElement.textContent;
            }

            // 克隆邮件内容
            const emailHeader = emailDetail.querySelector('.email-detail-header');
            const emailBody = emailDetail.querySelector('.email-detail-body');

            if (emailHeader && emailBody) {
                // 清空内容
                content.innerHTML = '';

                // 克隆头部信息
                const headerClone = emailHeader.cloneNode(true);
                content.appendChild(headerClone);

                // 处理邮件正文
                const iframe = emailBody.querySelector('iframe');
                const textContent = emailBody.querySelector('.email-body-text');

                if (iframe) {
                    // 如果是 HTML 邮件，创建新的 iframe
                    const newIframe = document.createElement('iframe');
                    newIframe.id = 'fullscreenEmailBodyFrame';
                    newIframe.style.width = '100%';
                    newIframe.style.border = 'none';
                    newIframe.style.backgroundColor = '#ffffff';

                    // 复制原 iframe 的内容
                    if (iframe.contentDocument) {
                        const htmlContent = iframe.contentDocument.documentElement.outerHTML;
                        newIframe.srcdoc = htmlContent;
                    }

                    content.appendChild(newIframe);

                    // 调整 iframe 高度
                    newIframe.onload = function () {
                        adjustFullscreenIframeHeight(newIframe);
                    };
                } else if (textContent) {
                    // 如果是纯文本邮件，直接克隆
                    const textClone = textContent.cloneNode(true);
                    content.appendChild(textClone);
                }

                // 显示模态框
                modal.classList.add('show');
                updateModalBodyState();
            }
        }

        // 切换信任模式
        function toggleTrustMode(checkbox) {
            if (checkbox.checked) {
                if (confirm('⚠️ 警告：启用信任模式将直接显示邮件原始内容，不进行任何安全过滤。\n\n这可能包含恶意脚本或不安全的内容。您确定要继续吗？')) {
                    isTrustedMode = true;
                    if (currentEmailDetail) {
                        renderEmailDetail(currentEmailDetail);
                    }
                } else {
                    checkbox.checked = false;
                }
            } else {
                isTrustedMode = false;
                if (currentEmailDetail) {
                    renderEmailDetail(currentEmailDetail);
                }
            }
        }

        function closeFullscreenEmail() {
            const modal = document.getElementById('fullscreenEmailModal');
            if (!modal) return;
            modal.classList.remove('show');
            updateModalBodyState();
        }

        function closeFullscreenEmailOnBackdrop(event) {
            // 只有点击背景时才关闭，点击内容区域不关闭
            if (event.target.id === 'fullscreenEmailModal') {
                closeFullscreenEmail();
            }
        }

        function adjustFullscreenIframeHeight(iframe) {
            try {
                const adjustHeight = () => {
                    if (iframe.contentDocument && iframe.contentDocument.body) {
                        const body = iframe.contentDocument.body;
                        const html = iframe.contentDocument.documentElement;
                        const height = Math.max(
                            body.scrollHeight,
                            body.offsetHeight,
                            html.clientHeight,
                            html.scrollHeight,
                            html.offsetHeight
                        );
                        // 全屏模式下设置实际高度，添加余量
                        iframe.style.height = (height + 100) + 'px';
                    }
                };

                // 多次调整高度
                adjustHeight();
                setTimeout(adjustHeight, 100);
                setTimeout(adjustHeight, 300);
                setTimeout(adjustHeight, 500);
                setTimeout(adjustHeight, 1000);

                // 监听内容变化
                if (iframe.contentDocument) {
                    const observer = new MutationObserver(adjustHeight);
                    observer.observe(iframe.contentDocument.body, {
                        childList: true,
                        subtree: true,
                        attributes: true
                    });

                    // 监听图片加载
                    const images = iframe.contentDocument.querySelectorAll('img');
                    images.forEach(img => {
                        img.addEventListener('load', adjustHeight);
                        img.addEventListener('error', adjustHeight);
                    });
                }
            } catch (e) {
                console.log('Cannot adjust fullscreen iframe height:', e);
            }
        }

        // 显示邮件列表（移动端）
        function showEmailList() {
            document.getElementById('emailListPanel').classList.remove('hidden');
            isListVisible = true;
            document.getElementById('toggleListText').textContent = '隐藏列表';
        }

        // 刷新邮件
        function refreshEmails() {
            if (currentAccount) {
                if (isTempEmailGroup) {
                    loadTempEmailMessages(currentAccount);
                } else {
                    // 清除当前缓存并强制刷新
                    const cacheKey = `${currentAccount}_${currentFolder}`;
                    delete emailListCache[cacheKey];
                    loadEmails(currentAccount, true);
                }
            } else {
                showToast('请先选择一个邮箱账号', 'error');
            }
        }

        // 复制邮箱地址
        function copyEmail(email) {
            navigator.clipboard.writeText(email).then(() => {
                showToast('邮箱地址已复制', 'success');
            }).catch(() => {
                // 降级方案
                const textarea = document.createElement('textarea');
                textarea.value = email;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                showToast('邮箱地址已复制', 'success');
            });
        }

        // 复制当前邮箱
        function copyCurrentEmail() {
            const emailElement = document.getElementById('currentAccountEmail');
            if (emailElement && emailElement.textContent) {
                const email = emailElement.textContent.replace(' (临时)', '').trim();
                copyEmail(email);
            }
        }

        // 退出登录
        function logout() {
            if (confirm('确定要退出登录吗？')) {
                window.location.href = '/logout';
            }
        }

        // ==================== 工具函数 ====================

        // HTML 转义
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 格式化日期
        function formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                let normalizedDate = dateStr;
                if (typeof dateStr === 'number' || /^\d+$/.test(String(dateStr))) {
                    const timestamp = Number(dateStr);
                    normalizedDate = timestamp < 1000000000000 ? timestamp * 1000 : timestamp;
                }

                const date = new Date(normalizedDate);
                if (isNaN(date.getTime())) return dateStr;

                const now = new Date();
                const isToday = date.toDateString() === now.toDateString();

                if (isToday) {
                    return '今天 ' + date.toLocaleTimeString('zh-CN', {
                        timeZone: 'Asia/Shanghai',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                } else {
                    return date.toLocaleDateString('zh-CN', {
                        timeZone: 'Asia/Shanghai',
                        year: 'numeric',
                        month: 'long',
                        day: 'numeric'
                    }) + ' ' + date.toLocaleTimeString('zh-CN', {
                        timeZone: 'Asia/Shanghai',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                }
            } catch (e) {
                return dateStr;
            }
        }

        // ==================== OAuth Refresh Token 相关 ====================

        // 显示获取 Refresh Token 模态框
        async function showGetRefreshTokenModal() {
            showModal('getRefreshTokenModal');

            // 重置表单
            document.getElementById('redirectUrlInput').value = '';
            document.getElementById('refreshTokenResult').style.display = 'none';
            document.getElementById('refreshTokenOutput').value = '';

            // 重置按钮状态
            const btn = document.getElementById('exchangeTokenBtn');
            btn.disabled = false;
            btn.textContent = '换取 Token';
            btn.style.display = '';

            // 获取授权 URL
            try {
                const response = await fetch('/api/oauth/auth-url');
                const data = await response.json();

                if (data.success) {
                    document.getElementById('authUrlInput').value = data.auth_url;
                } else {
                    showToast('获取授权链接失败', 'error');
                }
            } catch (error) {
                showToast('获取授权链接失败', 'error');
            }
        }

        // 隐藏获取 Refresh Token 模态框
        function hideGetRefreshTokenModal() {
            hideModal('getRefreshTokenModal');
        }

        // 复制授权 URL
        function copyAuthUrl() {
            const input = document.getElementById('authUrlInput');
            input.select();
            document.execCommand('copy');
            showToast('授权链接已复制到剪贴板', 'success');
        }

        // 打开授权 URL
        function openAuthUrl() {
            const url = document.getElementById('authUrlInput').value;
            if (url) {
                window.open(url, '_blank');
                showToast('已在新窗口打开授权页面', 'info');
            }
        }

        // 换取 Token
        async function exchangeToken() {
            const redirectUrl = document.getElementById('redirectUrlInput').value.trim();

            if (!redirectUrl) {
                showToast('请先粘贴授权后的完整 URL', 'error');
                return;
            }

            const btn = document.getElementById('exchangeTokenBtn');
            btn.disabled = true;
            btn.textContent = '⏳ 换取中...';

            try {
                const response = await fetch('/api/oauth/exchange-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        redirected_url: redirectUrl
                    })
                });

                const data = await response.json();

                if (data.success) {
                    // 输出默认推荐导入格式，避免用户复制到与当前导入格式不匹配的备用顺序。
                    const importFormat = `your@outlook.com----yourpassword----${data.client_id}----${data.refresh_token}`;

                    // 显示结果
                    document.getElementById('refreshTokenOutput').value = importFormat;
                    document.getElementById('refreshTokenResult').style.display = 'block';

                    showToast('✅ Refresh Token 获取成功！', 'success');

                    // 重置按钮状态（不隐藏，允许重复使用）
                    btn.disabled = false;
                    btn.textContent = '换取 Token';
                } else {
                    handleApiError(data, '换取 Token 失败');
                    btn.disabled = false;
                    btn.textContent = '换取 Token';
                }
            } catch (error) {
                showToast('换取 Token 失败: ' + error.message, 'error');
                btn.disabled = false;
                btn.textContent = '换取 Token';
            }
        }

        // ==================== 设置相关 ====================

        // 显示设置模态框
        async function showSettingsModal() {
            showModal('settingsModal');
            await loadSettings();
        }

        // 隐藏设置模态框
        function hideSettingsModal() {
            hideModal('settingsModal');
            // 清空密码输入框
            const passwordInput = document.getElementById('settingsPassword');
            if (passwordInput) {
                passwordInput.value = '';
            }
        }

        // 生成随机对外 API Key
        function generateExternalApiKey() {
            const array = new Uint8Array(16);
            crypto.getRandomValues(array);
            const key = Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
            document.getElementById('settingsExternalApiKey').value = key;
            showToast('已生成随机 API Key，请保存设置', 'success');
        }

        // 加载设置
        async function loadSettings() {
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();

                if (data.success) {
                    // 密码不显示，只显示 API Key
                    document.getElementById('settingsApiKey').value = data.settings.gptmail_api_key || '';
                    document.getElementById('settingsExternalApiKey').value = data.settings.external_api_key || '';
                    // DuckMail 设置
                    document.getElementById('settingsDuckmailBaseUrl').value = data.settings.duckmail_base_url || '';
                    document.getElementById('settingsDuckmailApiKey').value = data.settings.duckmail_api_key || '';
                    // Cloudflare 设置
                    document.getElementById('settingsCloudflareWorkerDomain').value = data.settings.cloudflare_worker_domain || '';
                    document.getElementById('settingsCloudflareEmailDomains').value = data.settings.cloudflare_email_domains || '';
                    document.getElementById('settingsCloudflareAdminPassword').value = data.settings.cloudflare_admin_password || '';

                    // 密码框留空
                    document.getElementById('settingsPassword').value = '';

                    // 加载刷新配置
                    document.getElementById('refreshIntervalDays').value = data.settings.refresh_interval_days || '30';
                    document.getElementById('refreshDelaySeconds').value = data.settings.refresh_delay_seconds || '5';
                    document.getElementById('refreshCron').value = data.settings.refresh_cron || '0 2 * * *';

                    // 设置定时刷新开关
                    const enableScheduled = data.settings.enable_scheduled_refresh !== 'false';
                    document.getElementById('enableScheduledRefresh').checked = enableScheduled;

                    // 设置刷新策略单选框
                    const useCron = data.settings.use_cron_schedule === 'true';
                    document.querySelector('input[name="refreshStrategy"][value="' + (useCron ? 'cron' : 'days') + '"]').checked = true;
                    toggleRefreshStrategy();
                }
            } catch (error) {
                showToast('加载设置失败', 'error');
            }
        }

        // 切换刷新策略
        function toggleRefreshStrategy() {
            const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
            document.getElementById('daysStrategyContainer').style.display = strategy === 'days' ? 'block' : 'none';
            document.getElementById('cronStrategyContainer').style.display = strategy === 'cron' ? 'block' : 'none';
        }

        // 选择 Cron 样例
        async function selectCronExample(cronExpr) {
            document.getElementById('refreshCron').value = cronExpr;
            await validateCronExpression();
        }

        // 验证 Cron 表达式
        async function validateCronExpression() {
            const cronExpr = document.getElementById('refreshCron').value.trim();
            const resultEl = document.getElementById('cronValidationResult');

            if (!cronExpr) {
                resultEl.innerHTML = '';
                resultEl.style.display = 'none';
                return;
            }

            try {
                const response = await fetch('/api/settings/validate-cron', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cron_expression: cronExpr })
                });

                const data = await response.json();

                if (data.success && data.valid) {
                    const nextRun = new Date(data.next_run).toLocaleString('zh-CN');
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #28a745;">
                            ✓ 表达式有效<br>
                            下次执行: ${nextRun}
                        </div>
                    `;
                } else {
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <div style="color: #dc3545;">
                            ✗ ${data.error && data.error.message ? data.error.message : (data.error || '表达式无效')}
                        </div>
                    `;
                }
            } catch (error) {
                resultEl.style.display = 'block';
                resultEl.innerHTML = `
                    <div style="color: #dc3545;">
                        ✗ 验证失败: ${error.message}
                    </div>
                `;
            }
        }

        // 保存设置
        async function saveSettings() {
            const password = document.getElementById('settingsPassword').value;
            const apiKey = document.getElementById('settingsApiKey').value.trim();
            const externalApiKey = document.getElementById('settingsExternalApiKey').value.trim();
            const refreshDays = document.getElementById('refreshIntervalDays').value;
            const refreshDelay = document.getElementById('refreshDelaySeconds').value;
            const refreshCron = document.getElementById('refreshCron').value.trim();
            const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
            const enableScheduled = document.getElementById('enableScheduledRefresh').checked;

            const settings = {};

            // 只有输入了密码才更新密码
            if (password) {
                settings.login_password = password;
            }

            // API Key 可以为空（清除）
            settings.gptmail_api_key = apiKey;

            // 对外 API Key
            settings.external_api_key = externalApiKey;

            // DuckMail 设置
            settings.duckmail_base_url = document.getElementById('settingsDuckmailBaseUrl').value.trim();
            settings.duckmail_api_key = document.getElementById('settingsDuckmailApiKey').value.trim();
            settings.cloudflare_worker_domain = document.getElementById('settingsCloudflareWorkerDomain').value.trim();
            settings.cloudflare_email_domains = document.getElementById('settingsCloudflareEmailDomains').value.trim();
            settings.cloudflare_admin_password = document.getElementById('settingsCloudflareAdminPassword').value.trim();

            // 刷新配置
            const days = parseInt(refreshDays);
            const delay = parseInt(refreshDelay);

            if (isNaN(days) || days < 1 || days > 90) {
                showToast('刷新周期必须在 1-90 天之间', 'error');
                return;
            }

            if (isNaN(delay) || delay < 0 || delay > 60) {
                showToast('刷新间隔必须在 0-60 秒之间', 'error');
                return;
            }

            settings.refresh_interval_days = days;
            settings.refresh_delay_seconds = delay;
            settings.use_cron_schedule = strategy === 'cron';
            settings.enable_scheduled_refresh = enableScheduled;

            if (strategy === 'cron') {
                if (!refreshCron) {
                    showToast('请输入 Cron 表达式', 'error');
                    return;
                }
                settings.refresh_cron = refreshCron;
            }

            try {
                const response = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });

                const data = await response.json();

                if (data.success) {
                    showToast('设置已保存，重启应用后生效', 'success');
                    hideSettingsModal();
                } else {
                    handleApiError(data, '保存设置失败');
                }
            } catch (error) {
                showToast('保存设置失败', 'error');
            }
        }

        function ensureEditForwardToggle() {
            if (document.getElementById('editForwardEnabled')) return;
            const statusGroup = document.getElementById('editStatus')?.closest('.form-group');
            if (!statusGroup) return;
            statusGroup.insertAdjacentHTML('afterend', `
                <div class="form-group">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="editForwardEnabled">
                        <span class="form-label" style="margin: 0;">启用邮件转发</span>
                    </label>
                    <div class="form-hint">开启后会按系统设置转发到邮箱或 Telegram。</div>
                </div>
            `);
        }

        function showAddAccountModal() {
            showModal('addAccountModal');
            document.getElementById('accountInput').value = '';
            if (document.getElementById('importProviderSelect')) {
                document.getElementById('importProviderSelect').value = 'outlook';
            }
            if (document.getElementById('importImapHost')) {
                document.getElementById('importImapHost').value = '';
            }
            if (document.getElementById('importImapPort')) {
                document.getElementById('importImapPort').value = '993';
            }
            if (currentGroupId) {
                document.getElementById('importGroupSelect').value = currentGroupId;
            }
            updateImportHint();
        }

        async function addAccount() {
            const input = document.getElementById('accountInput').value.trim();
            const groupId = parseInt(document.getElementById('importGroupSelect').value);
            const provider = document.getElementById('importProviderSelect')?.value || 'outlook';
            const imapHost = document.getElementById('importImapHost')?.value.trim() || '';
            const imapPort = parseInt(document.getElementById('importImapPort')?.value || '993', 10);
            const forwardEnabled = !!document.getElementById('importForwardEnabled')?.checked;

            if (!input) {
                showToast('请输入账号信息', 'error');
                return;
            }

            const isTempGroup = isTempImportGroup();
            if (!isTempGroup && provider === 'custom' && !imapHost) {
                showToast('自定义 IMAP 必须填写服务器地址', 'error');
                return;
            }

            try {
                let response;
                if (isTempGroup) {
                    const tempProvider = document.getElementById('importChannelSelect').value || 'gptmail';
                    response = await fetch('/api/temp-emails/import', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ account_string: input, provider: tempProvider })
                    });
                } else {
                    response = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            account_string: input,
                            group_id: groupId,
                            provider,
                            imap_host: imapHost,
                            imap_port: Number.isFinite(imapPort) ? imapPort : 993,
                            forward_enabled: forwardEnabled
                        })
                    });
                }

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideAddAccountModal();
                    delete accountsCache[groupId];
                    await loadGroups();
                    if (isTempGroup) {
                        await loadTempEmails(true);
                    } else {
                        await loadAccountsByGroup(groupId, true);
                    }
                } else {
                    handleApiError(data, '导入失败');
                }
            } catch (error) {
                showToast('导入失败', 'error');
            }
        }

        async function showEditAccountModal(accountId) {
            try {
                ensureEditForwardToggle();
                const response = await fetch(`/api/accounts/${accountId}`);
                const data = await response.json();

                if (data.success) {
                    closeAllModals();
                    const acc = data.account;
                    document.getElementById('editAccountId').value = acc.id;
                    document.getElementById('editEmail').value = acc.email || '';
                    document.getElementById('editPassword').value = acc.password || '';
                    document.getElementById('editClientId').value = acc.client_id || '';
                    document.getElementById('editRefreshToken').value = acc.refresh_token || '';
                    document.getElementById('editImapPassword').value = acc.imap_password || '';
                    document.getElementById('editImapHost').value = acc.imap_host || '';
                    document.getElementById('editImapPort').value = acc.imap_port || 993;
                    document.getElementById('editGroupSelect').value = acc.group_id || 1;
                    document.getElementById('editRemark').value = acc.remark || '';
                    document.getElementById('editAliases').value = Array.isArray(acc.aliases) ? acc.aliases.join('\n') : '';
                    document.getElementById('editStatus').value = acc.status || 'active';
                    if (document.getElementById('editForwardEnabled')) {
                        document.getElementById('editForwardEnabled').checked = !!acc.forward_enabled;
                    }
                    if (document.getElementById('editProviderSelect')) {
                        document.getElementById('editProviderSelect').value = acc.provider || (acc.account_type === 'imap' ? 'custom' : 'outlook');
                    }
                    updateEditAccountFields();
                    setModalVisible('editAccountModal', true);
                }
            } catch (error) {
                showToast('加载账号信息失败', 'error');
            }
        }

        async function updateAccount() {
            const accountId = document.getElementById('editAccountId').value;
            const oldGroupId = currentGroupId;
            const newGroupId = parseInt(document.getElementById('editGroupSelect').value);
            const provider = document.getElementById('editProviderSelect')?.value || 'outlook';
            const isOutlook = provider === 'outlook';
            const imapPort = parseInt(document.getElementById('editImapPort')?.value || '993', 10);

            const data = {
                email: document.getElementById('editEmail').value.trim(),
                password: document.getElementById('editPassword').value,
                client_id: document.getElementById('editClientId').value.trim(),
                refresh_token: document.getElementById('editRefreshToken').value.trim(),
                account_type: isOutlook ? 'outlook' : 'imap',
                provider,
                imap_host: document.getElementById('editImapHost')?.value.trim() || '',
                imap_port: Number.isFinite(imapPort) ? imapPort : 993,
                imap_password: document.getElementById('editImapPassword')?.value || '',
                group_id: newGroupId,
                remark: document.getElementById('editRemark').value.trim(),
                aliases: document.getElementById('editAliases')?.value
                    .split('\n')
                    .map(item => item.trim())
                    .filter(Boolean),
                status: document.getElementById('editStatus').value,
                forward_enabled: !!document.getElementById('editForwardEnabled')?.checked
            };

            if (isOutlook) {
                if (!data.email || !data.client_id || !data.refresh_token) {
                    showToast('邮箱、Client ID 和 Refresh Token 不能为空', 'error');
                    return;
                }
            } else {
                if (!data.email || !data.imap_password) {
                    showToast('邮箱和 IMAP 密码不能为空', 'error');
                    return;
                }
                if (provider === 'custom' && !data.imap_host) {
                    showToast('自定义 IMAP 必须填写服务器地址', 'error');
                    return;
                }
            }

            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                if (result.success) {
                    showToast(result.message, 'success');
                    hideEditAccountModal();
                    delete accountsCache[oldGroupId];
                    if (oldGroupId !== newGroupId) {
                        delete accountsCache[newGroupId];
                    }
                    loadGroups();
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    handleApiError(result, '更新失败');
                }
            } catch (error) {
                showToast('更新失败', 'error');
            }
        }

        async function loadSettings() {
            ensureForwardingSettingsUI();
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();

                if (data.success) {
                    document.getElementById('settingsApiKey').value = data.settings.gptmail_api_key || '';
                    document.getElementById('settingsExternalApiKey').value = data.settings.external_api_key || '';
                    document.getElementById('settingsDuckmailBaseUrl').value = data.settings.duckmail_base_url || '';
                    document.getElementById('settingsDuckmailApiKey').value = data.settings.duckmail_api_key || '';
                    document.getElementById('settingsCloudflareWorkerDomain').value = data.settings.cloudflare_worker_domain || '';
                    document.getElementById('settingsCloudflareEmailDomains').value = data.settings.cloudflare_email_domains || '';
                    document.getElementById('settingsCloudflareAdminPassword').value = data.settings.cloudflare_admin_password || '';
                    document.getElementById('settingsPassword').value = '';

                    document.getElementById('refreshIntervalDays').value = data.settings.refresh_interval_days || '30';
                    document.getElementById('refreshDelaySeconds').value = data.settings.refresh_delay_seconds || '5';
                    document.getElementById('refreshCron').value = data.settings.refresh_cron || '0 2 * * *';
                    document.getElementById('enableScheduledRefresh').checked = data.settings.enable_scheduled_refresh !== 'false';

                    document.getElementById('forwardCheckIntervalMinutes').value = data.settings.forward_check_interval_minutes || '5';
                    document.getElementById('forwardEmailWindowMinutes').value = data.settings.forward_email_window_minutes || '0';
                    document.getElementById('forwardIncludeJunkemail').checked = String(data.settings.forward_include_junkemail) === 'true';
                    document.getElementById('settingsEmailForwardRecipient').value = data.settings.email_forward_recipient || '';
                    document.getElementById('settingsSmtpHost').value = data.settings.smtp_host || '';
                    document.getElementById('settingsSmtpPort').value = data.settings.smtp_port || '465';
                    document.getElementById('settingsSmtpUsername').value = data.settings.smtp_username || '';
                    document.getElementById('settingsSmtpPassword').value = data.settings.smtp_password || '';
                    document.getElementById('settingsSmtpProvider').value = normalizeSmtpForwardProvider(data.settings.smtp_provider || 'custom');
                    document.getElementById('settingsSmtpFromEmail').value = data.settings.smtp_from_email || '';
                    document.getElementById('settingsSmtpUseTls').checked = String(data.settings.smtp_use_tls) === 'true';
                    document.getElementById('settingsSmtpUseSsl').checked = String(data.settings.smtp_use_ssl) !== 'false';
                    document.getElementById('settingsTelegramBotToken').value = data.settings.telegram_bot_token || '';
                    document.getElementById('settingsTelegramChatId').value = data.settings.telegram_chat_id || '';
                    setSelectedForwardChannels(data.settings.forward_channels || []);

                    const useCron = data.settings.use_cron_schedule === 'true';
                    document.querySelector('input[name="refreshStrategy"][value="' + (useCron ? 'cron' : 'days') + '"]').checked = true;
                    toggleRefreshStrategy();
                    syncSmtpProviderUI(false);
                }
            } catch (error) {
                showToast('加载设置失败', 'error');
            }
        }

        async function saveSettings() {
            ensureForwardingSettingsUI();
            const password = document.getElementById('settingsPassword').value;
            const apiKey = document.getElementById('settingsApiKey').value.trim();
            const externalApiKey = document.getElementById('settingsExternalApiKey').value.trim();
            const refreshDays = document.getElementById('refreshIntervalDays').value;
            const refreshDelay = document.getElementById('refreshDelaySeconds').value;
            const refreshCron = document.getElementById('refreshCron').value.trim();
            const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
            const enableScheduled = document.getElementById('enableScheduledRefresh').checked;
            const settings = {};
            const forwardChannels = getSelectedForwardChannels();

            if (password) {
                settings.login_password = password;
            }

            settings.gptmail_api_key = apiKey;
            settings.external_api_key = externalApiKey;
            settings.duckmail_base_url = document.getElementById('settingsDuckmailBaseUrl').value.trim();
            settings.duckmail_api_key = document.getElementById('settingsDuckmailApiKey').value.trim();
            settings.cloudflare_worker_domain = document.getElementById('settingsCloudflareWorkerDomain').value.trim();
            settings.cloudflare_email_domains = document.getElementById('settingsCloudflareEmailDomains').value.trim();
            settings.cloudflare_admin_password = document.getElementById('settingsCloudflareAdminPassword').value.trim();

            const days = parseInt(refreshDays, 10);
            const delay = parseInt(refreshDelay, 10);
            const forwardMinutes = parseInt(document.getElementById('forwardCheckIntervalMinutes').value || '5', 10);
            const forwardWindowMinutes = parseInt(document.getElementById('forwardEmailWindowMinutes').value || '0', 10);
            const forwardIncludeJunkemail = !!document.getElementById('forwardIncludeJunkemail')?.checked;
            const smtpPortValue = document.getElementById('settingsSmtpPort').value.trim();
            const smtpPort = parseInt(smtpPortValue || '465', 10);
            const smtpRecipient = document.getElementById('settingsEmailForwardRecipient').value.trim();
            const smtpHost = document.getElementById('settingsSmtpHost').value.trim();
            const smtpProvider = normalizeSmtpForwardProvider(document.getElementById('settingsSmtpProvider')?.value || 'custom');
            const smtpFromEmail = document.getElementById('settingsSmtpFromEmail').value.trim();
            const smtpUsername = document.getElementById('settingsSmtpUsername').value.trim();
            const telegramBotToken = document.getElementById('settingsTelegramBotToken').value.trim();
            const telegramChatId = document.getElementById('settingsTelegramChatId').value.trim();

            if (Number.isNaN(days) || days < 1 || days > 90) {
                showToast('刷新周期必须在 1-90 天之间', 'error');
                return;
            }
            if (Number.isNaN(delay) || delay < 0 || delay > 60) {
                showToast('刷新间隔必须在 0-60 秒之间', 'error');
                return;
            }
            if (Number.isNaN(forwardMinutes) || forwardMinutes < 1 || forwardMinutes > 60) {
                showToast('转发轮询间隔必须在 1-60 分钟之间', 'error');
                return;
            }
            if (Number.isNaN(forwardWindowMinutes) || forwardWindowMinutes < 0 || forwardWindowMinutes > 10080) {
                showToast('转发邮件时间范围必须在 0-10080 分钟之间', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpRecipient) {
                showToast('启用 SMTP 转发时必须填写转发到邮箱', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpHost) {
                showToast('启用 SMTP 转发时必须填写 SMTP 主机', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && !smtpUsername && !smtpFromEmail) {
                showToast('至少需要填写 SMTP 用户名或发件人邮箱之一', 'error');
                return;
            }
            if (forwardChannels.includes('smtp') && (Number.isNaN(smtpPort) || smtpPort < 1 || smtpPort > 65535)) {
                showToast('SMTP 端口无效', 'error');
                return;
            }
            if (forwardChannels.includes('telegram') && !telegramBotToken) {
                showToast('启用 TG 转发时必须填写 Telegram Bot Token', 'error');
                return;
            }
            if (forwardChannels.includes('telegram') && !telegramChatId) {
                showToast('启用 TG 转发时必须填写 Telegram Chat ID', 'error');
                return;
            }

            settings.refresh_interval_days = days;
            settings.refresh_delay_seconds = delay;
            settings.use_cron_schedule = strategy === 'cron';
            settings.enable_scheduled_refresh = enableScheduled;
            settings.forward_channels = forwardChannels;
            settings.forward_check_interval_minutes = forwardMinutes;
            settings.forward_email_window_minutes = forwardWindowMinutes;
            settings.forward_include_junkemail = forwardIncludeJunkemail;
            settings.email_forward_recipient = smtpRecipient;
            settings.smtp_host = smtpHost;
            settings.smtp_port = Number.isNaN(smtpPort) ? 465 : smtpPort;
            settings.smtp_username = smtpUsername;
            settings.smtp_password = document.getElementById('settingsSmtpPassword').value;
            settings.smtp_provider = smtpProvider;
            settings.smtp_from_email = smtpFromEmail;
            settings.smtp_use_tls = document.getElementById('settingsSmtpUseTls').checked;
            settings.smtp_use_ssl = document.getElementById('settingsSmtpUseSsl').checked;
            settings.telegram_bot_token = telegramBotToken;
            settings.telegram_chat_id = telegramChatId;

            if (strategy === 'cron') {
                if (!refreshCron) {
                    showToast('请输入 Cron 表达式', 'error');
                    return;
                }
                settings.refresh_cron = refreshCron;
            }

            try {
                const response = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });

                const data = await response.json();
                if (data.success) {
                    showToast('设置已保存，重启应用后生效', 'success');
                    hideSettingsModal();
                } else {
                    handleApiError(data, '保存设置失败');
                }
            } catch (error) {
                showToast('保存设置失败', 'error');
            }
        }

        function buildForwardingDraftConfig() {
            const smtpPortValue = document.getElementById('settingsSmtpPort').value.trim();
            const smtpPort = parseInt(smtpPortValue || '465', 10);
            return {
                smtp: {
                    provider: document.getElementById('settingsSmtpProvider')?.value || 'custom',
                    recipient: document.getElementById('settingsEmailForwardRecipient').value.trim(),
                    host: document.getElementById('settingsSmtpHost').value.trim(),
                    port: Number.isNaN(smtpPort) ? null : smtpPort,
                    username: document.getElementById('settingsSmtpUsername').value.trim(),
                    password: document.getElementById('settingsSmtpPassword').value,
                    from_email: document.getElementById('settingsSmtpFromEmail').value.trim(),
                    use_tls: !!document.getElementById('settingsSmtpUseTls')?.checked,
                    use_ssl: !!document.getElementById('settingsSmtpUseSsl')?.checked,
                },
                telegram: {
                    bot_token: document.getElementById('settingsTelegramBotToken').value.trim(),
                    chat_id: document.getElementById('settingsTelegramChatId').value.trim(),
                }
            };
        }

        async function testForwardChannel(channel) {
            const btn = document.getElementById(channel === 'smtp' ? 'testSmtpBtn' : 'testTelegramBtn');
            if (!btn || btn.disabled) return;

            const draft = buildForwardingDraftConfig();
            if (channel === 'smtp') {
                if (!draft.smtp.recipient) {
                    showToast('请先填写 SMTP 转发到邮箱', 'error');
                    return;
                }
                if (!draft.smtp.host) {
                    showToast('请先填写 SMTP 主机', 'error');
                    return;
                }
                if (!draft.smtp.username && !draft.smtp.from_email) {
                    showToast('请至少填写 SMTP 用户名或发件人邮箱', 'error');
                    return;
                }
                if (!draft.smtp.port || draft.smtp.port < 1 || draft.smtp.port > 65535) {
                    showToast('SMTP 端口无效', 'error');
                    return;
                }
            } else if (channel === 'telegram') {
                if (!draft.telegram.bot_token) {
                    showToast('请先填写 Telegram Bot Token', 'error');
                    return;
                }
                if (!draft.telegram.chat_id) {
                    showToast('请先填写 Telegram Chat ID', 'error');
                    return;
                }
            } else {
                showToast('未知转发渠道', 'error');
                return;
            }

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '发送中...';

            try {
                const response = await fetch('/api/settings/test-forward-channel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        channel,
                        config: draft
                    })
                });
                const data = await response.json();
                if (data.success) {
                    showToast(data.message || '测试成功', 'success');
                } else {
                    handleApiError(data, '测试失败');
                }
            } catch (error) {
                showToast('测试失败', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        function formatRelativeTime(timestamp) {
            if (!timestamp) return '从未刷新';

            const now = new Date();
            let dateStr = timestamp;
            if (typeof dateStr === 'string' && !dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                dateStr = dateStr + 'Z';
            }
            const past = new Date(dateStr);
            const diffMs = now - past;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return '刚刚';
            if (diffMins < 60) return `${diffMins} 分钟前`;
            if (diffHours < 24) return `${diffHours} 小时前`;
            if (diffDays < 30) return `${diffDays} 天前`;
            return `${Math.floor(diffDays / 30)} 月前`;
        }

        // ==================== Token 刷新管理 ====================

        // 显示刷新模态框
        async function showRefreshModal() {
            showModal('refreshModal');
            // 加载统计数据
            await loadRefreshStats();
            // 自动加载失败列表（如果有失败记录）
            await autoLoadFailedListIfNeeded();
        }

        // 自动加载失败列表（如果有失败记录）
        async function autoLoadFailedListIfNeeded() {
            try {
                const response = await fetch('/api/accounts/refresh-logs/failed');
                const data = await response.json();

                if (data.success && data.logs && data.logs.length > 0) {
                    // 有失败记录，自动显示失败列表
                    showFailedListFromData(data.logs.map(log => ({
                        id: log.account_id,
                        email: log.account_email,
                        error: log.error_message
                    })));
                }
            } catch (error) {
                console.error('自动加载失败列表失败:', error);
            }
        }

        // 隐藏刷新模态框
        function hideRefreshModal() {
            hideModal('refreshModal');

            // 确保所有内容都被隐藏，防止残留
            const progress = document.getElementById('refreshProgress');
            if (progress) {
                progress.style.display = 'none';
            }
            const failedList = document.getElementById('failedListContainer');
            if (failedList) {
                failedList.style.display = 'none';
            }
            const logsContainer = document.getElementById('refreshLogsContainer');
            if (logsContainer) {
                logsContainer.style.display = 'none';
            }

            // 重置按钮状态
            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = false;
                refreshAllBtn.textContent = '🔄 全量刷新';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = false;
                retryFailedBtn.textContent = '🔁 重试失败';
            }
        }

        // 加载刷新统计
        async function loadRefreshStats() {
            try {
                const response = await fetch('/api/accounts/refresh-stats');
                const data = await response.json();

                console.log('刷新统计数据:', data);

                if (data.success) {
                    const stats = data.stats;

                    // 优先使用保存的本地刷新时间
                    if (window.lastRefreshTime && window.lastRefreshTime instanceof Date) {
                        document.getElementById('lastRefreshTime').textContent = formatDateTime(window.lastRefreshTime.toISOString());
                    } else if (stats.last_refresh_time) {
                        document.getElementById('lastRefreshTime').textContent = formatDateTime(stats.last_refresh_time);
                    } else {
                        document.getElementById('lastRefreshTime').textContent = '-';
                    }

                    document.getElementById('totalRefreshCount').textContent = stats.total;
                    document.getElementById('successRefreshCount').textContent = stats.success_count;
                    document.getElementById('failedRefreshCount').textContent = stats.failed_count;

                    console.log('统计数据已更新到页面');
                }
            } catch (error) {
                console.error('加载刷新统计失败:', error);
            }
        }

        // 全量刷新所有账号
        async function refreshAllAccounts() {
            const btn = document.getElementById('refreshAllBtn');
            const progress = document.getElementById('refreshProgress');
            const progressText = document.getElementById('refreshProgressText');

            if (btn.disabled) return;

            if (!confirm('确定要刷新所有账号的 Token 吗？')) {
                return;
            }

            btn.disabled = true;
            btn.textContent = '刷新中...';
            progress.style.display = 'block';
            progressText.innerHTML = '正在初始化...';

            try {
                const eventSource = new EventSource('/api/accounts/trigger-scheduled-refresh?force=true');
                let totalCount = 0;
                let successCount = 0;
                let failedCount = 0;

                eventSource.onmessage = function (event) {
                    try {
                        const data = JSON.parse(event.data);

                        if (data.type === 'start') {
                            totalCount = data.total;
                            const delayInfo = data.delay_seconds > 0 ? `（间隔 ${data.delay_seconds} 秒）` : '';
                            progressText.innerHTML = `总共 <strong>${totalCount}</strong> 个账号${delayInfo}，准备开始刷新...`;
                            // 初始化统计
                            document.getElementById('totalRefreshCount').textContent = totalCount;
                            document.getElementById('successRefreshCount').textContent = '0';
                            document.getElementById('failedRefreshCount').textContent = '0';
                        } else if (data.type === 'progress') {
                            successCount = data.success_count;
                            failedCount = data.failed_count;
                            // 实时更新统计
                            document.getElementById('successRefreshCount').textContent = successCount;
                            document.getElementById('failedRefreshCount').textContent = failedCount;
                            progressText.innerHTML = `
                                正在处理: <strong>${data.email}</strong><br>
                                进度: <strong>${data.current}/${data.total}</strong> |
                                成功: <strong style="color: #28a745;">${successCount}</strong> |
                                失败: <strong style="color: #dc3545;">${failedCount}</strong>
                            `;
                        } else if (data.type === 'delay') {
                            progressText.innerHTML += `<br><span style="color: #999;">等待 ${data.seconds} 秒后继续...</span>`;
                        } else if (data.type === 'complete') {
                            eventSource.close();
                            progress.style.display = 'none';
                            btn.disabled = false;
                            btn.textContent = '🔄 全量刷新';

                            // 直接更新统计数据，使用本地时间
                            const now = new Date();
                            window.lastRefreshTime = now; // 保存刷新时间
                            document.getElementById('lastRefreshTime').textContent = '刚刚';
                            document.getElementById('totalRefreshCount').textContent = data.total;
                            document.getElementById('successRefreshCount').textContent = data.success_count;
                            document.getElementById('failedRefreshCount').textContent = data.failed_count;

                            showToast(`刷新完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                                data.failed_count > 0 ? 'warning' : 'success');

                            // 如果有失败的，显示失败列表
                            if (data.failed_count > 0) {
                                showFailedListFromData(data.failed_list);
                            }

                            // 刷新账号列表以更新刷新时间
                            if (currentGroupId) {
                                loadAccountsByGroup(currentGroupId, true);
                            }
                        }
                    } catch (e) {
                        console.error('解析进度数据失败:', e);
                    }
                };

                eventSource.onerror = function (error) {
                    console.error('EventSource 错误:', error);
                    eventSource.close();
                    progress.style.display = 'none';
                    btn.disabled = false;
                    btn.textContent = '🔄 全量刷新';
                    showToast('刷新过程中出现错误', 'error');
                };

            } catch (error) {
                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔄 全量刷新';
                showToast('刷新请求失败', 'error');
            }
        }

        // 重试失败的账号
        async function retryFailedAccounts() {
            const btn = document.getElementById('retryFailedBtn');
            const progress = document.getElementById('refreshProgress');
            const progressText = document.getElementById('refreshProgressText');

            if (btn.disabled) return;

            btn.disabled = true;
            btn.textContent = '重试中...';
            progress.style.display = 'block';
            progressText.textContent = '正在重试失败的账号...';

            try {
                const response = await fetch('/api/accounts/refresh-failed', {
                    method: 'POST'
                });
                const data = await response.json();

                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔁 重试失败';

                if (data.success) {
                    if (data.total === 0) {
                        showToast('没有需要重试的失败账号', 'info');
                    } else {
                        showToast(`重试完成！成功: ${data.success_count}, 失败: ${data.failed_count}`,
                            data.failed_count > 0 ? 'warning' : 'success');

                        // 刷新统计
                        loadRefreshStats();

                        // 如果还有失败的，显示失败列表
                        if (data.failed_count > 0) {
                            showFailedListFromData(data.failed_list);
                        } else {
                            hideFailedList();
                        }
                    }
                } else {
                    handleApiError(data, '重试失败');
                }
            } catch (error) {
                progress.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🔁 重试失败';
                showToast('重试请求失败', 'error');
            }
        }

        // 单个账号重试
        async function retrySingleAccount(accountId, accountEmail) {
            try {
                const response = await fetch(`/api/accounts/${accountId}/retry-refresh`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    showToast(`${accountEmail} 刷新成功`, 'success');
                    loadRefreshStats();

                    // 刷新失败列表
                    loadFailedLogs();
                } else {
                    handleApiError(data, `${accountEmail} 刷新失败`);
                }
            } catch (error) {
                handleApiError({ success: false, error: { message: '刷新请求失败', details: error.message, code: 'NETWORK_ERROR', type: 'Frontend' } });
            }
        }

        // 显示失败列表（从数据）
        function showFailedListFromData(failedList) {
            const container = document.getElementById('failedListContainer');
            const listEl = document.getElementById('failedList');

            // 隐藏其他列表
            hideRefreshLogs();

            if (!failedList || failedList.length === 0) {
                container.style.display = 'none';
                return;
            }

            let html = '';
            failedList.forEach(item => {
                html += `
                    <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: start;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(item.email)}</div>
                            <div style="font-size: 12px; color: #dc3545;">${escapeHtml(item.error || '未知错误')}</div>
                        </div>
                        <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${item.id}, '${escapeHtml(item.email)}')">
                            重试
                        </button>
                    </div>
                `;
            });

            listEl.innerHTML = html;
            container.style.display = 'block';
        }

        // 隐藏失败列表
        function hideFailedList() {
            const container = document.getElementById('failedListContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        // 加载失败日志
        async function loadFailedLogs() {
            const container = document.getElementById('failedListContainer');
            const listEl = document.getElementById('failedList');

            hideRefreshLogs();

            try {
                const response = await fetch('/api/accounts/refresh-logs/failed');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无失败状态的邮箱</div>';
                    } else {
                        let html = '';
                        data.logs.forEach(log => {
                            html += `
                                <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: center;">
                                    <div style="flex: 1;">
                                        <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(log.account_email)}</div>
                                        <div style="font-size: 12px; color: #dc3545;">${escapeHtml(log.error_message || '未知错误')}</div>
                                        <div style="font-size: 11px; color: #999; margin-top: 4px;">最后刷新: ${formatDateTime(log.created_at)}</div>
                                    </div>
                                    <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${log.account_id}, '${escapeJs(log.account_email)}')">
                                        重试
                                    </button>
                                </div>
                            `;
                        });
                        listEl.innerHTML = html;
                    }
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载失败邮箱列表失败', 'error');
            }
        }

        // 加载刷新历史
        async function loadRefreshLogs() {
            const container = document.getElementById('refreshLogsContainer');
            const listEl = document.getElementById('refreshLogsList');

            try {
                const response = await fetch('/api/accounts/refresh-logs?limit=1000');
                const data = await response.json();

                if (data.success) {
                    if (data.logs.length === 0) {
                        listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无全量刷新历史</div>';
                    } else {
                        listEl.innerHTML = `<div style="padding: 12px; background-color: #f8f9fa; border-bottom: 1px solid #e5e5e5; font-size: 13px; color: #666;">近半年刷新历史（共 ${data.logs.length} 条）</div>`;
                        let html = '';
                        data.logs.forEach(log => {
                            const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                            const statusText = log.status === 'success' ? '成功' : '失败';
                            const typeText = log.refresh_type === 'manual' ? '手动' : '自动';
                            const typeColor = log.refresh_type === 'manual' ? '#007bff' : '#28a745';
                            const typeBgColor = log.refresh_type === 'manual' ? '#e7f3ff' : '#e8f5e9';

                            html += `
                                <div style="padding: 14px; border-bottom: 1px solid #e5e5e5; transition: background-color 0.2s;"
                                     onmouseover="this.style.backgroundColor='#f8f9fa'"
                                     onmouseout="this.style.backgroundColor='transparent'">
                                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
                                        <div style="font-weight: 600; font-size: 14px;">${escapeHtml(log.account_email)}</div>
                                        <div style="display: flex; gap: 8px; align-items: center;">
                                            <span style="font-size: 11px; padding: 3px 8px; background-color: ${typeBgColor}; color: ${typeColor}; border-radius: 4px; font-weight: 500;">${typeText}</span>
                                            <span style="font-size: 13px; color: ${statusColor}; font-weight: 600;">${statusText}</span>
                                        </div>
                                    </div>
                                    <div style="font-size: 12px; color: #888;">${formatDateTime(log.created_at)}</div>
                                    ${log.error_message ? `<div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message)}</div>` : ''}
                                </div>
                            `;
                        });
                        listEl.innerHTML += html;
                    }
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载刷新历史失败', 'error');
            }
        }

        async function loadForwardingLogs() {
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
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载转发历史失败', 'error');
            }
        }

        async function loadFailedForwardingLogs() {
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
                    container.style.display = 'block';
                }
            } catch (error) {
                showToast('加载转发失败记录失败', 'error');
            }
        }

        // 隐藏刷新历史
        function hideRefreshLogs() {
            const container = document.getElementById('refreshLogsContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        function hideForwardingLogs() {
            const container = document.getElementById('forwardingLogsContainer');
            if (container) {
                container.style.display = 'none';
            }
        }

        function hideFailedForwardingLogs() {
            const container = document.getElementById('failedForwardingLogsContainer');
            if (container) {
                container.style.display = 'none';
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
                timeZone: 'Asia/Shanghai',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        // 统一关闭所有模态框的函数 (修复 bug：防止模态框意外残留)
        function closeAllModals() {
            document.querySelectorAll('.modal').forEach(modal => {
                modal.classList.remove('show');
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
            });

            const settingsPassword = document.getElementById('settingsPassword');
            if (settingsPassword) {
                settingsPassword.value = '';
            }

            const exportVerifyPassword = document.getElementById('exportVerifyPassword');
            if (exportVerifyPassword) {
                exportVerifyPassword.value = '';
            }

            hideFailedList();
            hideRefreshLogs();
            hideForwardingLogs();
            hideFailedForwardingLogs();

            const progress = document.getElementById('refreshProgress');
            if (progress) {
                progress.style.display = 'none';
            }

            const refreshAllBtn = document.getElementById('refreshAllBtn');
            if (refreshAllBtn) {
                refreshAllBtn.disabled = false;
                refreshAllBtn.textContent = '🔄 全量刷新';
            }

            const retryFailedBtn = document.getElementById('retryFailedBtn');
            if (retryFailedBtn) {
                retryFailedBtn.disabled = false;
                retryFailedBtn.textContent = '🔁 重试失败';
            }

            closeFullscreenEmail();
            updateModalBodyState();
        }

        // HTML 转义
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 键盘快捷键
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeAccountActionMenus();
                closeAllModals();
            }
        });
        // ==================== 标签管理 ====================

        let allTags = [];

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
                    renderTagList();
                    updateTagFilter();  // Update Filter Dropdown
                }
            } catch (error) {
                showToast('加载标签失败', 'error');
            }
        }

        // 更新标签筛选下拉框
        function updateTagFilter() {
            const container = document.getElementById('tagFilterContainer');
            if (!container) return;

            if (allTags.length === 0) {
                container.style.display = 'none';
                return;
            }

            container.style.display = 'flex';

            let html = '';
            allTags.forEach(tag => {
                html += `
                    <label class="tag-filter-label">
                        <input type="checkbox" class="tag-filter-checkbox" value="${tag.id}" onchange="handleTagFilterChange()">
                        <span class="tag-filter-dot" style="background-color: ${tag.color};"></span>
                        ${escapeHtml(tag.name)}
                    </label>
                `;
            });
            container.innerHTML = html;
            /* Old dropdown code removed */


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
            if (!confirm('确定要删除这个标签吗？')) return;

            try {
                const response = await fetch(`/api/tags/${id}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast('标签已删除', 'success');
                    await loadTags();
                    // 刷新账号列表以更新标签显示
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else {
                    showToast(data.error || '删除失败', 'error');
                }
            } catch (error) {
                showToast('删除标签失败', 'error');
            }
        }

        // ==================== 批量操作 ====================

        // 更新批量操作栏状态
        function updateBatchActionBar() {
            const checked = document.querySelectorAll('.account-select-checkbox:checked');
            const allCheckboxes = document.querySelectorAll('#accountList .account-select-checkbox');
            const bar = document.getElementById('batchActionBar');
            const countSpan = document.getElementById('selectedCount');
            const selectAllBtn = document.getElementById('accountSelectAllBtn');

            if (checked.length > 0) {
                bar.style.display = 'flex';
                countSpan.textContent = `已选 ${checked.length} 项`;
                if (selectAllBtn) {
                    selectAllBtn.textContent = allCheckboxes.length > 0 && checked.length === allCheckboxes.length
                        ? '取消全选'
                        : '全选当前列表';
                }
            } else {
                bar.style.display = 'none';
            }
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
            updateBatchActionBar();
        }

        let batchActionType = ''; // 'add' or 'remove'

        // 显示批量打标模态框
        async function showBatchTagModal(type) {
            batchActionType = type;
            document.getElementById('batchTagTitle').textContent = type === 'add' ? '批量添加标签' : '批量移除标签';
            showModal('batchTagModal');

            // 加载标签选项
            await loadTagsForSelect();
        }

        function hideBatchTagModal() {
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
            const tagId = document.getElementById('batchTagSelect').value;
            if (!tagId) {
                showToast('请选择标签', 'error');
                return;
            }

            const checked = document.querySelectorAll('.account-select-checkbox:checked');
            const accountIds = Array.from(checked).map(cb => parseInt(cb.value));

            if (accountIds.length === 0) return;

            try {
                const response = await fetch('/api/accounts/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        tag_id: parseInt(tagId),
                        action: batchActionType
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchTagModal();
                    // 刷新列表
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                    // 隐藏操作栏
                    document.querySelectorAll('.account-select-checkbox').forEach(cb => cb.checked = false);
                    updateBatchActionBar();
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            }
        }

        // ==================== 批量移动分组 ====================

        // 显示批量移动分组模态框
        async function showBatchMoveGroupModal() {
            showModal('batchMoveGroupModal');
            await loadGroupsForBatchMove();
        }

        function hideBatchMoveGroupModal() {
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
                        html += `<option value="${group.id}">${escapeHtml(group.name)}</option>`;
                    });
                    select.innerHTML = html;
                }
            } catch (error) {
                select.innerHTML = '<option value="">加载失败</option>';
            }
        }

        // 确认批量移动分组
        async function confirmBatchMoveGroup() {
            const groupId = document.getElementById('batchMoveGroupSelect').value;
            if (!groupId) {
                showToast('请选择目标分组', 'error');
                return;
            }

            const checked = document.querySelectorAll('.account-select-checkbox:checked');
            const accountIds = Array.from(checked).map(cb => parseInt(cb.value));

            if (accountIds.length === 0) return;

            try {
                const response = await fetch('/api/accounts/batch-update-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_ids: accountIds,
                        group_id: parseInt(groupId)
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    hideBatchMoveGroupModal();
                    // 刷新分组列表
                    loadGroups();
                    // 刷新当前分组的邮箱列表
                    if (currentGroupId) {
                        delete accountsCache[currentGroupId];
                        loadAccountsByGroup(currentGroupId, true);
                    }
                    // 清除选择
                    document.querySelectorAll('.account-select-checkbox').forEach(cb => cb.checked = false);
                    updateBatchActionBar();
                } else {
                    showToast(data.error || '操作失败', 'error');
                }
            } catch (error) {
                showToast('请求失败', 'error');
            }
        }
