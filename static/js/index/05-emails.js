        /* global EMAIL_DETAIL_REQUEST_TIMEOUT_MS, EMAIL_LIST_REQUEST_TIMEOUT_MS, adjustIframeHeight, applyEmailListCache, closeMobilePanels, closeNavbarActionsMenu, copyCurrentEmail, currentAccount, currentEmailDetail, currentEmailId, currentEmails, currentFolder, currentMethod, currentSkip, emailListCache, escapeHtml, fetchWithTimeout, formatDate, getEmailListCacheEntry, getFolderDisplayName, getNextEmailSkipFromCache, handleApiError, hasMoreEmails, invalidateEmailListCache, isNormalMailLocalRetentionEnabled, isTempEmailGroup, isTimeoutAbortError, loadCloudflareGlobalMessages, mergeFolderSummaries, normalizeFolderSummaries, renderCloudflareGlobalFilterBar, renderEmptyStateMarkup, scheduleEmailListLoadCheck, showMobileEmailDetail, showToast, updateMobileContext, updateModalBodyState */

        // ==================== 邮件相关 ====================

        function isNormalMailboxListRequest() {
            return !isTempEmailGroup && currentMethod !== 'cloudflare-admin';
        }

        const backgroundMailboxSyncs = new Map();
        const pendingNewMailSyncs = new Map();
        const normalDetailIframeResizeResources = { timers: [], observer: null };
        const fullscreenIframeResizeResources = { timers: [], observer: null };
        const NEW_EMAIL_HIGHLIGHT_CLEAR_DELAY_MS = 3500;

        function cleanupIframeResizeResources(resources) {
            (resources.timers || []).forEach(timerId => window.clearTimeout(timerId));
            resources.timers = [];
            if (resources.observer) {
                resources.observer.disconnect();
                resources.observer = null;
            }
        }

        function cleanupNormalDetailIframeResizeResources() {
            cleanupIframeResizeResources(normalDetailIframeResizeResources);
        }

        function cleanupFullscreenIframeResizeResources() {
            cleanupIframeResizeResources(fullscreenIframeResizeResources);
        }

        function getNormalMailboxRemoteMethod() {
            const cacheMethod = getEmailListCacheEntry(currentAccount, currentFolder)?.remote_method;
            return cacheMethod || currentMethod;
        }

        function getRemoteMailboxMethodFallback() {
            const method = String(getNormalMailboxRemoteMethod() || '').trim().toLowerCase();
            return ['graph', 'imap'].includes(method) ? method : 'graph';
        }

        function getCurrentEmailRemoteActionMethod(emailItem = {}) {
            const idMode = String(emailItem?.id_mode || emailItem?.idMode || '').trim().toLowerCase();
            if (idMode === 'graph') {
                return 'graph';
            }
            if (idMode === 'uid' || idMode === 'sequence') {
                return 'imap';
            }
            return getRemoteMailboxMethodFallback();
        }

        function buildEmailListRequestUrl(email, params = {}) {
            const query = new URLSearchParams(params);
            return `/api/emails/${encodeURIComponent(email)}?${query.toString()}`;
        }

        function setEmailListLoadingState(isLoading, options = {}) {
            const refreshBtn = document.querySelector('.refresh-btn');
            const folderTabs = document.querySelectorAll('.folder-tab');
            const isBackgroundSync = options.background === true;

            if (refreshBtn) {
                refreshBtn.disabled = isLoading && !isBackgroundSync;
                refreshBtn.textContent = isLoading
                    ? (isBackgroundSync ? '同步中...' : '获取中...')
                    : '获取邮件';
                refreshBtn.title = isLoading && isBackgroundSync
                    ? '本地保留邮件已显示，正在后台同步远程邮件'
                    : '';
                refreshBtn.toggleAttribute('aria-busy', isLoading);
            }
            folderTabs.forEach(tab => {
                tab.disabled = isLoading && !isBackgroundSync;
                tab.title = isLoading && isBackgroundSync
                    ? '本地保留邮件已显示，后台同步进行中'
                    : '';
            });
        }

        function isCurrentMailboxContext(context) {
            return currentAccount === context.account && currentFolder === context.folder;
        }

        function updateEmailListHeader(methodLabel, emailCount) {
            const methodTag = document.getElementById('methodTag');
            if (methodTag) {
                methodTag.textContent = methodLabel;
                methodTag.style.display = 'inline';
            }

            const emailCountEl = document.getElementById('emailCount');
            if (emailCountEl) {
                emailCountEl.textContent = `(${emailCount})`;
            }
        }

        function setMailSyncStatus(message = '') {
            const status = document.getElementById('mailSyncStatus');
            if (!status) {
                return;
            }

            status.textContent = message;
            status.hidden = !message;
        }

        function getEmailListMethodMetadata(data, options = {}) {
            const requestMethod = String(data.request_method || '').trim().toLowerCase();
            const optionMethod = String(options.method || '').trim().toLowerCase();
            const method = requestMethod || optionMethod || (data.method === 'Graph API' ? 'graph' : 'imap');
            return {
                method,
                remoteMethod: method === 'local' ? getRemoteMailboxMethodFallback() : method,
                methodLabel: options.methodLabel || data.method || method,
                disableLoadMore: options.disableLoadMore === true
            };
        }

        function getEmailMessageStableKey(emailItem, fallbackFolder = currentFolder) {
            const id = String(emailItem?.id || '').trim();
            if (!id) {
                return '';
            }

            const folder = String(emailItem?.folder || fallbackFolder || '').trim().toLowerCase();
            const idMode = String(emailItem?.id_mode || emailItem?.idMode || '').trim().toLowerCase();
            return `${folder}::${idMode}::${id}`;
        }

        function getEmailListTimestamp(emailItem) {
            const timestamp = Date.parse(emailItem?.date || emailItem?.received_at || '');
            return Number.isNaN(timestamp) ? 0 : timestamp;
        }

        function mergeEmailListByStableKey(existingEmails, incomingEmails, fallbackFolder = currentFolder) {
            const mergedEmails = [];
            const indexByKey = new Map();
            const newEmails = [];

            (existingEmails || []).forEach(emailItem => {
                const key = getEmailMessageStableKey(emailItem, fallbackFolder);
                if (key) {
                    indexByKey.set(key, mergedEmails.length);
                }
                mergedEmails.push(emailItem);
            });

            (incomingEmails || []).forEach(emailItem => {
                const key = getEmailMessageStableKey(emailItem, fallbackFolder);
                if (key && indexByKey.has(key)) {
                    const index = indexByKey.get(key);
                    mergedEmails[index] = { ...mergedEmails[index], ...emailItem };
                    return;
                }

                if (key) {
                    indexByKey.set(key, mergedEmails.length);
                }
                mergedEmails.push(emailItem);
                newEmails.push(emailItem);
            });

            mergedEmails.sort((left, right) => getEmailListTimestamp(right) - getEmailListTimestamp(left));
            return { emails: mergedEmails, newEmails };
        }

        function cacheEmailListResponse(cacheKey, data, method, methodLabel, options = {}) {
            const emails = Array.isArray(data.emails) ? data.emails : [];
            const disableLoadMore = options.disableLoadMore === true;
            const folderSummaries = options.folderSummaries || data.folder_summaries;
            emailListCache[cacheKey] = {
                emails,
                has_more: disableLoadMore ? false : data.has_more === true,
                skip: emails.length,
                method,
                method_label: methodLabel,
                derived_from: null,
                local_retention: data.local_retention === true,
                local_retention_count: Number(data.count) || emails.length,
                folder_summaries: currentFolder === 'all'
                    ? normalizeFolderSummaries(folderSummaries)
                    : undefined
            };

            if (options.remoteMethod) {
                emailListCache[cacheKey].remote_method = options.remoteMethod;
            }
        }

        function applyEmailListResponse(cacheKey, data, options = {}) {
            const emails = Array.isArray(data.emails) ? data.emails : [];
            const { method, remoteMethod, methodLabel, disableLoadMore } = getEmailListMethodMetadata(data, options);

            currentEmails = emails;
            currentMethod = method;
            hasMoreEmails = disableLoadMore ? false : data.has_more === true;
            currentSkip = currentEmails.length;

            cacheEmailListResponse(cacheKey, data, method, methodLabel, {
                disableLoadMore,
                remoteMethod
            });
            updateEmailListHeader(methodLabel, currentEmails.length);
            renderEmailList(currentEmails);
            scheduleEmailListLoadCheck(80);
        }

        function getPendingNewMailSyncKey(account = currentAccount, folder = currentFolder) {
            return `${account || ''}_${folder || 'all'}`;
        }

        function hasPendingNewMailSync(account = currentAccount, folder = currentFolder) {
            return pendingNewMailSyncs.has(getPendingNewMailSyncKey(account, folder));
        }

        function updateEmailListCacheRemoteMetadata(cacheKey, data, options = {}) {
            const existingCache = emailListCache[cacheKey];
            if (!existingCache) {
                return;
            }

            const { method, remoteMethod } = getEmailListMethodMetadata(data, options);
            existingCache.remote_method = remoteMethod || method;
            if (currentFolder === 'all' && data.folder_summaries) {
                existingCache.folder_summaries = mergeFolderSummaries(
                    existingCache.folder_summaries,
                    data.folder_summaries
                );
            }
        }

        function queuePendingNewMailSync(syncKey, cacheKey, data, options = {}) {
            const existingEmails = Array.isArray(currentEmails) ? currentEmails : [];
            const incomingEmails = Array.isArray(data.emails) ? data.emails : [];
            const mergedResult = mergeEmailListByStableKey(existingEmails, incomingEmails, options.folder);
            const newlySyncedRows = collectNewlySyncedEmailRows(data, mergedResult, options.folder);

            updateEmailListCacheRemoteMetadata(cacheKey, data, options);
            pendingNewMailSyncs.set(syncKey, {
                cacheKey,
                data,
                options: { ...options },
                newlySyncedRows
            });
            announceNewlySyncedEmailRows(data, newlySyncedRows, options.folder, syncKey);
            return mergedResult;
        }


        function applyPendingNewMailSync(syncKey = getPendingNewMailSyncKey()) {
            const pending = pendingNewMailSyncs.get(syncKey);
            if (!pending) {
                hideNewMailNotice();
                return false;
            }

            const listElement = document.getElementById('emailList');
            const previousScrollTop = listElement ? listElement.scrollTop : null;
            const mergeResult = mergeEmailListByStableKey(
                Array.isArray(currentEmails) ? currentEmails : [],
                pending.data.emails,
                pending.options.folder
            );
            const newlySyncedRows = collectNewlySyncedEmailRows(
                pending.data,
                mergeResult,
                pending.options.folder
            );
            const { method, remoteMethod, methodLabel } = getEmailListMethodMetadata(
                pending.data,
                pending.options
            );
            markNewlySyncedEmailRows(newlySyncedRows, pending.options.folder);
            currentEmails = mergeResult.emails;
            currentMethod = method;
            hasMoreEmails = pending.data.has_more === true;
            currentSkip = currentEmails.length;

            cacheEmailListResponse(pending.cacheKey, { ...pending.data, emails: currentEmails }, method, methodLabel, {
                remoteMethod
            });
            updateEmailListHeader(methodLabel, currentEmails.length);
            renderEmailList(currentEmails);
            if (previousScrollTop !== null) {
                const currentListElement = document.getElementById('emailList');
                if (currentListElement) {
                    currentListElement.scrollTop = previousScrollTop;
                }
            }
            scheduleEmailListLoadCheck(80);
            requestBodyRetentionForNewRows(newlySyncedRows, pending.options.folder);
            if (newlySyncedRows.length > 0) {
                scheduleNewEmailHighlightClear();
            }
            pendingNewMailSyncs.delete(syncKey);
            hideNewMailNotice();
            return true;
        }


        function applyMergedRemoteEmailSync(cacheKey, data, options = {}) {
            const syncKey = getPendingNewMailSyncKey(options.context?.account, options.context?.folder);
            if (options.announceNewRows === true && Number(data.new_count || 0) > 0) {
                return queuePendingNewMailSync(syncKey, cacheKey, data, options);
            }

            pendingNewMailSyncs.delete(syncKey);
            hideNewMailNotice();
            const mergedResult = mergeEmailListByStableKey(currentEmails, data.emails, options.folder);
            const { method, remoteMethod, methodLabel } = getEmailListMethodMetadata(data, options);
            currentEmails = mergedResult.emails;
            currentMethod = method;
            hasMoreEmails = data.has_more === true;
            currentSkip = currentEmails.length;
            cacheEmailListResponse(cacheKey, { ...data, emails: currentEmails }, method, methodLabel, { remoteMethod });
            updateEmailListHeader(methodLabel, currentEmails.length);
            renderEmailList(currentEmails);
            scheduleEmailListLoadCheck(80);
            return mergedResult;
        }

        async function tryRenderLocalRetainedEmails(email, cacheKey) {
            if (!isNormalMailLocalRetentionEnabled()) {
                setMailSyncStatus('本地存储未启用');
                return false;
            }
            try {
                const response = await fetchWithTimeout(
                    buildEmailListRequestUrl(email, {
                        source: 'local',
                        folder: currentFolder,
                        skip: 0,
                        top: 20
                    }),
                    {
                        timeoutMs: EMAIL_LIST_REQUEST_TIMEOUT_MS,
                        timeoutMessage: '读取本地保留邮件超时'
                    }
                );
                const data = await response.json();
                const retainedEmails = Array.isArray(data.emails) ? data.emails : [];
                if (!data.success || retainedEmails.length === 0) {
                    return false;
                }

                applyEmailListResponse(cacheKey, data, {
                    method: 'local',
                    methodLabel: data.method || 'Local Retention'
                });
                return true;
            } catch (error) {
                return false;
            }
        }

        async function fetchRemoteEmails(email, cacheKey, options = {}) {
            const requestFolder = options.folder || currentFolder;
            const requestMethod = options.method || getRemoteMailboxMethodFallback();
            const response = await fetchWithTimeout(
                buildEmailListRequestUrl(email, {
                    method: requestMethod,
                    folder: requestFolder,
                    skip: 0,
                    top: 20
                }),
                {
                    timeoutMs: EMAIL_LIST_REQUEST_TIMEOUT_MS,
                    timeoutMessage: '获取邮件超时，请检查网络、代理或账号配置后重试'
                }
            );
            const data = await response.json();

            if (data.success) {
                if (!options.context || isCurrentMailboxContext(options.context)) {
                    setMailSyncStatus('');
                    if (options.mergeWithCurrentList === true) {
                        applyMergedRemoteEmailSync(cacheKey, data, options);
                    } else {
                        applyEmailListResponse(cacheKey, data, options);
                    }
                }
                return data;
            }

            const fetchErrorDetails = data.details || (data.error ? { error: data.error } : {});
            if (options.preserveCurrentListOnError === true) {
                window._lastFetchErrorDetails = fetchErrorDetails;
                if (!options.context || isCurrentMailboxContext(options.context)) {
                    setMailSyncStatus('后台同步失败，当前显示的是本地保留邮件');
                    showToast('后台同步失败，已保留本地邮件列表', 'error');
                }
                return false;
            }

            if (Object.keys(fetchErrorDetails).length > 0) {
                showEmailFetchErrorModal(fetchErrorDetails);
            } else {
                handleApiError(data, '获取邮件失败');
            }
            document.getElementById('emailList').innerHTML = renderEmptyStateMarkup(
                '⚠️',
                '获取邮件失败，<a href="javascript:void(0)" onclick="showEmailFetchErrorModal(window._lastFetchErrorDetails)" style="color:#409eff;text-decoration:underline;">点击查看详情</a>',
                {
                    allowHtml: true,
                    onAction: 'refreshEmails()',
                    actionTitle: '刷新邮件列表'
                }
            );
            window._lastFetchErrorDetails = fetchErrorDetails;
            return false;
        }

        function startBackgroundRemoteMailboxSync(email, cacheKey) {
            const context = {
                account: email,
                folder: currentFolder
            };
            const syncKey = `${context.account}_${context.folder}`;
            if (backgroundMailboxSyncs.has(syncKey)) {
                return;
            }

            setEmailListLoadingState(true, { background: true });
            const syncPromise = fetchRemoteEmails(email, cacheKey, {
                folder: context.folder,
                method: getRemoteMailboxMethodFallback(),
                context,
                mergeWithCurrentList: true,
                announceNewRows: true,
                preserveCurrentListOnError: true
            }).catch(error => {
                if (isCurrentMailboxContext(context)) {
                    setMailSyncStatus('后台同步失败，当前显示的是本地保留邮件');
                    showToast(isTimeoutAbortError(error) ? '后台同步超时' : '后台同步失败', 'error');
                }
            }).finally(() => {
                backgroundMailboxSyncs.delete(syncKey);
                if (isCurrentMailboxContext(context)) {
                    setEmailListLoadingState(false);
                }
            });
            backgroundMailboxSyncs.set(syncKey, syncPromise);
        }

        // 加载邮件列表
        async function loadEmails(email, forceRefresh = false) {
            const container = document.getElementById('emailList');

            // 切换账号/刷新时清除选中状态
            selectedEmailIds.clear();
            updateEmailBatchActionBar();
            hideNewMailNotice();
            pendingNewMailSyncs.delete(getPendingNewMailSyncKey(email, currentFolder));
            setMailSyncStatus('');

            const cacheKey = `${email}_${currentFolder}`;
            const cache = !forceRefresh ? getEmailListCacheEntry(email, currentFolder) : null;
            if (cache) {
                applyEmailListCache(cache, { scheduleLoadCheck: false });
                return;
            }

            setEmailListLoadingState(true);
            currentSkip = 0;
            hasMoreEmails = true;
            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';
            let startedBackgroundSync = false;

            try {
                if (isNormalMailboxListRequest() && await tryRenderLocalRetainedEmails(email, cacheKey)) {
                    startBackgroundRemoteMailboxSync(email, cacheKey);
                    startedBackgroundSync = true;
                    return;
                }
                await fetchRemoteEmails(email, cacheKey);
            } catch (error) {
                const errorMessage = isTimeoutAbortError(error)
                    ? '获取邮件超时，请重试'
                    : '网络错误，请重试';
                setMailSyncStatus('');
                container.innerHTML = renderEmptyStateMarkup('⚠️', errorMessage, {
                    onAction: 'refreshEmails()',
                    actionTitle: '刷新邮件列表'
                });
            } finally {
                if (!startedBackgroundSync) {
                    setEmailListLoadingState(false);
                }
            }
        }

        // 渲染邮件列表
        // Selected email IDs
        let selectedEmailIds = new Set();
        let pendingReadEmailIds = new Set();
        let isBatchSelectMode = false;
        let highlightedNewEmailKeys = new Set();
        const requestedBodyRetentionKeys = new Set();
        const BODY_RETENTION_REQUEST_LIMIT = 5;

        function hideNewMailNotice() {
            const notice = document.getElementById('newMailNotice');
            if (!notice) {
                return;
            }

            notice.hidden = true;
            notice.innerHTML = '';
            notice.dataset.syncKey = '';
            notice.removeAttribute('role');
            notice.removeAttribute('tabindex');
            notice.onclick = null;
            notice.onkeydown = null;
        }

        function getNewMessageIdKeys(newMessageIds, fallbackFolder = currentFolder) {
            return new Set(
                (newMessageIds || [])
                    .map(item => getEmailMessageStableKey(item, fallbackFolder))
                    .filter(Boolean)
            );
        }

        function collectNewlySyncedEmailRows(data, mergeResult, fallbackFolder = currentFolder) {
            const newMessageKeys = getNewMessageIdKeys(data.new_message_ids, fallbackFolder);
            const candidateRows = Array.isArray(data.emails) ? data.emails : [];
            const rows = candidateRows.filter(emailItem => {
                const key = getEmailMessageStableKey(emailItem, fallbackFolder);
                return key && newMessageKeys.has(key);
            });

            if (rows.length > 0) {
                return rows;
            }
            return Number(data.new_count || 0) > 0 ? mergeResult.newEmails : [];
        }

        function showNewMailNotice(newCount, syncKey = getPendingNewMailSyncKey()) {
            const notice = document.getElementById('newMailNotice');
            if (!notice || newCount <= 0) {
                hideNewMailNotice();
                return;
            }

            const acceptPendingSync = () => applyPendingNewMailSync(syncKey);
            notice.hidden = false;
            notice.setAttribute('role', 'button');
            notice.setAttribute('tabindex', '0');
            notice.dataset.syncKey = syncKey;
            notice.onclick = acceptPendingSync;
            notice.onkeydown = event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    acceptPendingSync();
                }
            };
            notice.replaceChildren();
            const message = document.createElement('span');
            message.textContent = `有 ${Number(newCount)} 封新邮件已同步`;
            const hint = document.createElement('span');
            hint.className = 'new-mail-notice__hint';
            hint.textContent = '点击显示';
            notice.append(message, hint);
        }


        function markNewlySyncedEmailRows(rows, fallbackFolder = currentFolder) {
            highlightedNewEmailKeys = new Set();
            rows.forEach(emailItem => {
                const key = getEmailMessageStableKey(emailItem, fallbackFolder);
                if (key) {
                    highlightedNewEmailKeys.add(key);
                }
            });
        }

        function scheduleNewEmailHighlightClear() {
            window.setTimeout(() => {
                highlightedNewEmailKeys = new Set();
                document.querySelectorAll('.email-item.newly-synced').forEach(item => {
                    item.classList.remove('newly-synced');
                });
            }, NEW_EMAIL_HIGHLIGHT_CLEAR_DELAY_MS);
        }

        function announceNewlySyncedEmailRows(data, rows, fallbackFolder = currentFolder, syncKey = getPendingNewMailSyncKey()) {
            const reportedCount = Number(data.new_count || 0);
            const visibleCount = reportedCount > 0 ? reportedCount : rows.length;
            if (visibleCount <= 0) {
                hideNewMailNotice();
                return;
            }

            showNewMailNotice(visibleCount, syncKey);
        }

        function buildBodyRetentionItems(rows, fallbackFolder = currentFolder) {
            const method = getRemoteMailboxMethodFallback();
            return (rows || [])
                .map(emailItem => ({
                    id: String(emailItem?.id || '').trim(),
                    folder: String(emailItem?.folder || fallbackFolder || 'inbox'),
                    id_mode: String(emailItem?.id_mode || '').trim(),
                    method
                }))
                .filter(item => item.id);
        }

        function getUnrequestedBodyRetentionItems(rows, fallbackFolder = currentFolder) {
            const items = buildBodyRetentionItems(rows, fallbackFolder);
            const unrequestedItems = items.filter(item => {
                const key = getEmailMessageStableKey(item, fallbackFolder);
                return key && !requestedBodyRetentionKeys.has(key);
            });
            return unrequestedItems.slice(0, BODY_RETENTION_REQUEST_LIMIT);
        }

        function requestBodyRetentionForNewRows(rows, fallbackFolder = currentFolder) {
            const items = getUnrequestedBodyRetentionItems(rows, fallbackFolder);
            if (!items.length || !currentAccount || isTempEmailGroup || !isNormalMailLocalRetentionEnabled()) {
                return;
            }

            const requestedKeys = items
                .map(item => getEmailMessageStableKey(item, fallbackFolder))
                .filter(Boolean);
            requestedKeys.forEach(key => requestedBodyRetentionKeys.add(key));

            fetch('/api/emails/retain-bodies', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: currentAccount,
                    folder: fallbackFolder,
                    method: getRemoteMailboxMethodFallback(),
                    items
                })
            }).then(response => {
                if (!response.ok) {
                    throw new Error(`Retained body request failed with status ${response.status}`);
                }
                return response.json().catch(() => ({ success: true }));
            }).then(data => {
                if (data && data.success === false) {
                    throw new Error(data.error || 'Retained body request failed');
                }
            }).catch(error => {
                requestedKeys.forEach(key => requestedBodyRetentionKeys.delete(key));
                console.warn('Retained mail body background fetch failed:', error);
            });
        }

        function buildEmailDetailRequestUrl(messageId, folder, selectedEmail = {}) {
            const query = new URLSearchParams({
                method: getCurrentEmailRemoteActionMethod(selectedEmail),
                folder
            });
            if (isNormalMailboxListRequest() && isNormalMailLocalRetentionEnabled()) {
                query.set('prefer_local', '1');
                if (selectedEmail.id_mode) {
                    query.set('id_mode', selectedEmail.id_mode);
                }
            }
            return `/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(messageId)}?${query.toString()}`;
        }

        function getRecipientDisplayLabel(emailItem) {
            if (isTempEmailGroup && currentMethod !== 'cloudflare-admin') {
                return '';
            }

            const normalizedCurrentAccount = String(currentAccount || '').trim().toLowerCase();
            const toValue = String(emailItem?.to || '').trim();
            if (!normalizedCurrentAccount || !toValue) {
                return '';
            }

            const recipientCandidates = toValue.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || [];
            const recipients = recipientCandidates.length > 0
                ? recipientCandidates.map(recipient => recipient.trim().toLowerCase())
                : [toValue.toLowerCase()];

            if (recipients.includes(normalizedCurrentAccount)) {
                return '';
            }

            return `to: ${toValue}`;
        }

        function getEmailSourceLabel(emailItem) {
            if (currentMethod === 'cloudflare-admin') {
                return 'Cloudflare';
            }
            if (isTempEmailGroup || currentFolder !== 'all' || !emailItem?.folder) {
                return '';
            }
            return getFolderDisplayName(emailItem?.folder);
        }

        function formatAttachmentSize(size) {
            const numericSize = Number(size) || 0;
            if (numericSize < 1024) {
                return `${numericSize} B`;
            }
            if (numericSize < 1024 * 1024) {
                return `${(numericSize / 1024).toFixed(1).replace(/\.0$/, '')} KB`;
            }
            return `${(numericSize / (1024 * 1024)).toFixed(1).replace(/\.0$/, '')} MB`;
        }

        function appendEmailIdModeParam(query, email) {
            const idMode = String(email?.id_mode || email?.idMode || '').trim().toLowerCase();
            if (idMode) {
                query.set('id_mode', idMode);
            }
        }

        function buildAttachmentDownloadUrl(email, attachment) {
            const query = new URLSearchParams();
            query.set('method', getCurrentEmailRemoteActionMethod(email));
            query.set('folder', email?.folder || currentFolder || 'inbox');
            appendEmailIdModeParam(query, email);
            return `/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(email.id)}/attachments/${encodeURIComponent(attachment.id)}?${query.toString()}`;
        }

        function buildAllAttachmentsDownloadUrl(email) {
            const query = new URLSearchParams();
            query.set('method', getCurrentEmailRemoteActionMethod(email));
            query.set('folder', email?.folder || currentFolder || 'inbox');
            appendEmailIdModeParam(query, email);
            return `/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(email.id)}/attachments/download-all?${query.toString()}`;
        }

        function parseDownloadFilename(response, fallbackFilename) {
            const disposition = response.headers.get('content-disposition') || '';
            const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (encodedMatch) {
                try {
                    return decodeURIComponent(encodedMatch[1].trim().replace(/^"|"$/g, '')) || fallbackFilename;
                } catch (error) {
                    return fallbackFilename;
                }
            }

            const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
            return filenameMatch ? filenameMatch[1] : fallbackFilename;
        }

        function triggerAttachmentDownload(blob, filename) {
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename || 'attachment';
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
        }

        function setAttachmentDownloadState(link, isDownloading) {
            link.dataset.downloading = isDownloading ? 'true' : 'false';
            link.classList.toggle('is-downloading', isDownloading);
            link.setAttribute('aria-busy', isDownloading ? 'true' : 'false');

            if (link.classList.contains('email-attachments__download-all')) {
                if (!link.dataset.defaultLabel) {
                    link.dataset.defaultLabel = link.textContent.trim() || '全部下载';
                }
                link.textContent = isDownloading ? '打包中...' : link.dataset.defaultLabel;
                return;
            }

            const action = link.querySelector('.email-attachment-item__action');
            if (action) {
                action.textContent = isDownloading ? '下载中...' : '下载';
            }
        }

        async function downloadEmailAttachmentFile(event, link) {
            event.preventDefault();
            if (!link || link.dataset.downloading === 'true') {
                return;
            }

            const isDownloadAll = link.classList.contains('email-attachments__download-all');
            const fallbackFilename = link.getAttribute('download') || (isDownloadAll ? 'attachments.zip' : 'attachment');
            const pendingMessage = isDownloadAll ? '正在打包附件...' : '正在下载附件...';
            const failureMessage = isDownloadAll ? '全部附件下载失败' : '附件下载失败';
            const successMessage = isDownloadAll ? '附件已打包，下载已开始' : '附件下载已开始';

            setAttachmentDownloadState(link, true);
            showToast(pendingMessage, 'info');

            try {
                const response = await fetch(link.href, {
                    method: 'GET',
                    cache: 'no-store',
                    credentials: 'same-origin'
                });
                const contentType = response.headers.get('content-type') || '';
                const disposition = response.headers.get('content-disposition') || '';
                const isFileResponse = /attachment/i.test(disposition);

                if (!response.ok || (!isFileResponse && contentType.includes('application/json'))) {
                    const data = contentType.includes('application/json')
                        ? await response.json().catch(() => null)
                        : null;
                    if (data) {
                        handleApiError(data, failureMessage);
                    } else {
                        showToast(`${failureMessage}（HTTP ${response.status}）`, 'error');
                    }
                    return;
                }

                const blob = await response.blob();
                triggerAttachmentDownload(blob, parseDownloadFilename(response, fallbackFilename));
                showToast(successMessage, 'success');
            } catch (error) {
                showToast(`${failureMessage}，请检查网络后重试`, 'error');
            } finally {
                setAttachmentDownloadState(link, false);
            }
        }

        function renderAttachmentSection(email) {
            const attachments = Array.isArray(email?.attachments) ? email.attachments : [];
            if (attachments.length === 0) {
                return '';
            }

            return `
                <section class="email-attachments" aria-label="邮件附件">
                    <div class="email-attachments__header">
                        <div class="email-attachments__summary">
                            <div class="email-attachments__title">附件</div>
                            <div class="email-attachments__count">${attachments.length} 个</div>
                        </div>
                        ${attachments.length > 1 ? `
                            <a class="email-attachments__download-all"
                               href="${buildAllAttachmentsDownloadUrl(email)}"
                               download="attachments.zip"
                               onclick="downloadEmailAttachmentFile(event, this)">全部下载</a>
                        ` : ''}
                    </div>
                    <div class="email-attachments__list">
                        ${attachments.map(attachment => `
                            <a class="email-attachment-item"
                               href="${buildAttachmentDownloadUrl(email, attachment)}"
                               download="${escapeHtml(attachment.name || 'attachment')}"
                               onclick="downloadEmailAttachmentFile(event, this)">
                                <span class="email-attachment-item__icon" aria-hidden="true">📎</span>
                                <span class="email-attachment-item__content">
                                    <span class="email-attachment-item__name">${escapeHtml(attachment.name || 'attachment')}</span>
                                    <span class="email-attachment-item__meta">
                                        ${attachment.is_inline ? '<span class="email-attachment-item__badge">内联</span>' : ''}
                                        <span>${formatAttachmentSize(attachment.size)}</span>
                                        <span>${escapeHtml(attachment.content_type || 'application/octet-stream')}</span>
                                    </span>
                                </span>
                                <span class="email-attachment-item__action">下载</span>
                            </a>
                        `).join('')}
                    </div>
                </section>
            `;
        }

        function renderEmailList(emails) {
            const container = document.getElementById('emailList');

            if (emails.length === 0) {
                const emptyStateText = isTempEmailGroup
                    ? '暂无邮件'
                    : `${getFolderDisplayName(currentFolder)}为空`;
                const emptyPrefix = currentMethod === 'cloudflare-admin' && typeof renderCloudflareGlobalFilterBar === 'function'
                    ? renderCloudflareGlobalFilterBar()
                    : '';
                container.innerHTML = emptyPrefix + renderEmptyStateMarkup('📭', emptyStateText, {
                    onAction: 'refreshEmails()',
                    actionTitle: '刷新邮件列表'
                });
                // Reset selection
                selectedEmailIds.clear();
                currentEmailId = null;
                updateEmailBatchActionBar();
                return;
            }

            bindEmailListDelegatedEvents();
            const listPrefix = currentMethod === 'cloudflare-admin' && typeof renderCloudflareGlobalFilterBar === 'function'
                ? renderCloudflareGlobalFilterBar()
                : '';

            container.innerHTML = listPrefix + emails.map((email, index) => {
                const isChecked = selectedEmailIds.has(email.id);
                const isActive = currentEmailId === email.id;
                const recipientDisplayLabel = getRecipientDisplayLabel(email);
                const sourceLabel = getEmailSourceLabel(email);
                const hasAttachments = Boolean(email.has_attachments);
                const isNewlySynced = highlightedNewEmailKeys.has(getEmailMessageStableKey(email));
                return `
                <div class="email-item ${email.is_read === false ? 'unread' : ''} ${isActive ? 'active' : ''} ${isNewlySynced ? 'newly-synced' : ''}"
                     data-email-id="${escapeHtml(String(email.id || ''))}"
                     data-email-index="${index}">
                    <div class="email-checkbox-wrapper" data-email-id="${escapeHtml(String(email.id || ''))}">
                        <input type="checkbox" class="email-checkbox" ${isChecked ? 'checked' : ''} style="pointer-events: none;">
                    </div>
                    <div class="email-body">
                        <div class="email-top-row">
                            <div class="email-top-main">
                                ${email.is_read === false ? '<span class="email-unread-dot" title="未读" aria-label="未读"></span>' : ''}
                                <div class="email-sender-block">
                                    <div class="email-from" title="${escapeHtml(email.from || '未知发件人')}">${escapeHtml(email.from || '未知发件人')}</div>
                                    ${recipientDisplayLabel ? `<div class="email-recipient" title="${escapeHtml(recipientDisplayLabel)}">${escapeHtml(recipientDisplayLabel)}</div>` : ''}
                                </div>
                                ${hasAttachments ? '<span class="email-attachment-indicator" title="含附件" aria-label="含附件">📎</span>' : ''}
                                ${sourceLabel ? `<span class="email-folder-badge email-folder-badge--${escapeHtml(String(email.folder || '').toLowerCase())}">${escapeHtml(sourceLabel)}</span>` : ''}
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

        function handleEmailListClick(event) {
            const checkboxWrapper = event.target.closest('.email-checkbox-wrapper[data-email-id]');
            if (checkboxWrapper) {
                event.stopPropagation();
                toggleEmailSelection(checkboxWrapper.dataset.emailId);
                return;
            }

            const emailItem = event.target.closest('.email-item[data-email-id]');
            if (!emailItem || !emailItem.parentElement?.contains(event.target)) {
                return;
            }

            const emailId = emailItem.dataset.emailId || '';
            const emailIndex = Number(emailItem.dataset.emailIndex || 0);
            if (currentMethod === 'cloudflare-admin') {
                getCloudflareGlobalMessageDetail(emailId, emailIndex);
            } else if (isTempEmailGroup) {
                getTempEmailDetail(emailId, emailIndex);
            } else {
                selectEmail(emailId, emailIndex);
            }
        }

        function bindEmailListDelegatedEvents() {
            const container = document.getElementById('emailList');
            if (!container || container.dataset.emailListClickBound === 'true') {
                return;
            }
            container.dataset.emailListClickBound = 'true';
            container.addEventListener('click', handleEmailListClick);
        }

        function getSelectedEmailItems() {
            const selectedIds = new Set(Array.from(selectedEmailIds).map(id => String(id)));
            if (!selectedIds.size) {
                return [];
            }

            return currentEmails.filter(email => selectedIds.has(String(email.id)));
        }

        function applyEmailReadState(updatedIds, isRead = true) {
            const normalizedIds = new Set((updatedIds || []).map(id => String(id)).filter(Boolean));
            if (!normalizedIds.size) {
                return;
            }

            const applyToEmailList = (emails) => {
                if (!Array.isArray(emails)) {
                    return;
                }

                emails.forEach(email => {
                    if (normalizedIds.has(String(email.id))) {
                        email.is_read = isRead;
                    }
                });
            };

            applyToEmailList(currentEmails);

            const cachePrefix = `${currentAccount || ''}_`;
            Object.entries(emailListCache).forEach(([cacheKey, cacheValue]) => {
                if (!cacheKey.startsWith(cachePrefix)) {
                    return;
                }
                applyToEmailList(cacheValue?.emails);
            });

            if (currentEmailDetail && normalizedIds.has(String(currentEmailDetail.id))) {
                currentEmailDetail.is_read = isRead;
            }
        }

        async function requestMarkEmailsAsRead(items, { silent = false } = {}) {
            const normalizedItems = (items || [])
                .map(item => {
                    if (!item?.id) {
                        return null;
                    }
                    return {
                        id: String(item.id),
                        folder: String(item.folder || currentFolder || 'inbox'),
                        id_mode: String(item.id_mode || '')
                    };
                })
                .filter(Boolean)
                .filter(item => !pendingReadEmailIds.has(item.id));

            if (!normalizedItems.length) {
                return {
                    success: true,
                    success_count: 0,
                    failed_count: 0,
                    updated_ids: [],
                    errors: []
                };
            }

            normalizedItems.forEach(item => pendingReadEmailIds.add(item.id));

            try {
                const response = await fetch('/api/emails/mark-read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: currentAccount,
                        method: getRemoteMailboxMethodFallback(),
                        folder: currentFolder,
                        items: normalizedItems
                    })
                });
                const result = await response.json();
                const updatedIds = Array.isArray(result.updated_ids) ? result.updated_ids : [];

                if (updatedIds.length > 0) {
                    applyEmailReadState(updatedIds, true);
                    renderEmailList(currentEmails);
                }

                if (!silent) {
                    if (result.success_count > 0 && result.failed_count === 0) {
                        showToast(`已将 ${result.success_count} 封邮件设为已读`);
                    } else if (result.success_count > 0) {
                        showToast(`已设为已读 ${result.success_count} 封，失败 ${result.failed_count} 封`, 'warning');
                    } else {
                        handleApiError(result, '设为已读失败');
                    }
                }

                if (result.failed_count > 0 && Array.isArray(result.errors) && result.errors.length > 0) {
                    console.warn('Mark read errors:', result.errors);
                }

                return result;
            } catch (error) {
                if (!silent) {
                    showToast('设为已读失败，请检查网络后重试', 'error');
                }
                return {
                    success: false,
                    success_count: 0,
                    failed_count: normalizedItems.length,
                    updated_ids: [],
                    errors: [error]
                };
            } finally {
                normalizedItems.forEach(item => pendingReadEmailIds.delete(item.id));
            }
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
            const markReadBtn = document.getElementById('batchMarkReadBtn');
            const panel = document.getElementById('emailListPanel');
            const selectedEmails = getSelectedEmailItems();
            const unreadSelectedCount = selectedEmails.filter(email => email.is_read === false).length;
            if (isTempEmailGroup) {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
                if (markReadBtn) {
                    markReadBtn.disabled = false;
                    markReadBtn.dataset.loading = 'false';
                    markReadBtn.textContent = '设为已读';
                    markReadBtn.title = '';
                }
                return;
            }
            if (selectedEmailIds.size > 0) {
                bar.style.display = 'flex';
                panel?.classList.add('batch-toolbar-active');
                document.getElementById('emailSelectedCount').textContent = `已选 ${selectedEmailIds.size} 项`;
                if (selectAllBtn) {
                    selectAllBtn.textContent = currentEmails.length > 0 && selectedEmailIds.size === currentEmails.length
                        ? '取消全选'
                        : '全选';
                }
                if (markReadBtn) {
                    const isMarking = markReadBtn.dataset.loading === 'true';
                    markReadBtn.disabled = unreadSelectedCount === 0 || isMarking;
                    markReadBtn.title = unreadSelectedCount === 0 ? '所选邮件已全部为已读' : '';
                    if (!isMarking) {
                        markReadBtn.textContent = unreadSelectedCount > 0
                            ? `设为已读${unreadSelectedCount !== selectedEmails.length ? ` (${unreadSelectedCount})` : ''}`
                            : '设为已读';
                    }
                }
            } else {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
                if (markReadBtn) {
                    markReadBtn.disabled = false;
                    markReadBtn.dataset.loading = 'false';
                    markReadBtn.textContent = '设为已读';
                    markReadBtn.title = '';
                }
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

        async function markSelectedEmailsAsRead() {
            const btn = document.getElementById('batchMarkReadBtn');
            if (!btn || btn.disabled) return;

            const unreadItems = getSelectedEmailItems()
                .filter(email => email.is_read === false)
                .map(email => ({
                    id: email.id,
                    folder: email.folder || currentFolder || 'inbox',
                    id_mode: email.id_mode || ''
                }));

            if (!unreadItems.length) {
                showToast('所选邮件已全部为已读');
                return;
            }

            btn.disabled = true;
            btn.dataset.loading = 'true';
            btn.textContent = '设置中...';

            try {
                await requestMarkEmailsAsRead(unreadItems);
            } finally {
                btn.dataset.loading = 'false';
                updateEmailBatchActionBar();
            }
        }

        async function confirmBatchDeleteEmails() {
            if (selectedEmailIds.size === 0) return;

            if (!(await showConfirmModal(`确定要永久删除选中的 ${selectedEmailIds.size} 封邮件吗？此操作不可恢复！`, { title: '批量删除邮件', confirmText: '确认删除' }))) {
                return;
            }

            await deleteEmails(Array.from(selectedEmailIds));
        }

        async function confirmDeleteCurrentEmail() {
            if (isTempEmailGroup) return;
            if (!currentEmailDetail || !currentEmailDetail.id) return;

            if (!(await showConfirmModal('确定要永久删除这封邮件吗？此操作不可恢复！', { title: '删除邮件', confirmText: '确认删除' }))) {
                return;
            }

            await deleteEmails([currentEmailDetail.id]);
        }

        function removeDeletedEmailsFromCachedLists(deletedIds, account = currentAccount) {
            const normalizedIds = new Set(Array.from(deletedIds || []).map(id => String(id)));
            if (!normalizedIds.size) {
                return;
            }

            const cachePrefix = `${account || ''}_`;
            Object.entries(emailListCache).forEach(([cacheKey, cacheValue]) => {
                if (!cacheKey.startsWith(cachePrefix) || !Array.isArray(cacheValue?.emails)) {
                    return;
                }
                cacheValue.emails = cacheValue.emails.filter(email => !normalizedIds.has(String(email.id)));
                cacheValue.skip = cacheValue.emails.length;
                if (typeof cacheValue.local_retention_count === 'number') {
                    cacheValue.local_retention_count = Math.max(0, cacheValue.local_retention_count - normalizedIds.size);
                }
            });
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

                    const deletedIds = new Set(ids.map(id => String(id)));
                    currentEmails = currentEmails.filter(e => !deletedIds.has(String(e.id)));
                    removeDeletedEmailsFromCachedLists(deletedIds);
                    selectedEmailIds.clear();
                    if (currentEmailId && deletedIds.has(String(currentEmailId))) {
                        currentEmailId = null;
                    }

                    renderEmailList(currentEmails);

                    // If current viewed email was deleted, clear view
                    if (currentEmailDetail && deletedIds.has(String(currentEmailDetail.id))) {
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
            const selectedEmail = currentEmails.find(email => email.id === messageId);
            const requestFolder = currentFolder === 'all'
                ? (selectedEmail?.folder || 'inbox')
                : currentFolder;
            // 更新 UI
            document.querySelectorAll('.email-item').forEach((item, i) => {
                item.classList.toggle('active', i === index);
            });

            // 这里不重置 currentEmailDetail，等到 fetch 成功后再设置

            // 重置信任模式
            const trustCheckbox = document.getElementById('trustEmailCheckbox');
            trustCheckbox.checked = false;
            isTrustedMode = false;
            updateTrustToggleState(trustCheckbox);

            // 显示工具栏
            document.getElementById('emailDetailToolbar').style.display = 'flex';
            const deleteBtn = document.querySelector('#emailDetailToolbar .batch-btn.danger');
            if (deleteBtn) deleteBtn.style.display = '';
            showMobileEmailDetail();

            // 加载邮件详情
            const container = document.getElementById('emailDetail');
            container.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';

            try {
                const response = await fetchWithTimeout(
                    buildEmailDetailRequestUrl(messageId, requestFolder, selectedEmail),
                    {
                        timeoutMs: EMAIL_DETAIL_REQUEST_TIMEOUT_MS,
                        timeoutMessage: '加载邮件详情超时，请稍后重试'
                    }
                );
                const data = await response.json();

                if (data.success) {
                    currentEmailDetail = {
                        ...data.email,
                        folder: requestFolder,
                        id_mode: data.email?.id_mode || selectedEmail?.id_mode || ''
                    };
                    renderEmailDetail(currentEmailDetail);
                    if (selectedEmail?.is_read === false) {
                        void requestMarkEmailsAsRead([{
                            id: messageId,
                            folder: requestFolder,
                            id_mode: selectedEmail.id_mode || ''
                        }], { silent: true });
                    }
                } else {
                    handleApiError(data, '加载邮件详情失败');
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">⚠️</div>
                            <div class="empty-state-text"></div>
                        </div>
                    `;
                    const errorText = container.querySelector('.empty-state-text');
                    if (errorText) {
                        errorText.textContent = data.error && data.error.message ? data.error.message : '加载失败';
                    }
                }
            } catch (error) {
                const errorMessage = isTimeoutAbortError(error)
                    ? '加载邮件详情超时，请重试'
                    : '网络错误，请重试';
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">⚠️</div>
                        <div class="empty-state-text">${errorMessage}</div>
                    </div>
                `;
            }
        }

        // 渲染邮件详情
        function renderEmailDetail(email) {
            cleanupNormalDetailIframeResizeResources();
            const container = document.getElementById('emailDetail');
            const compactMobileMeta = typeof isMobileLayout === 'function' && isMobileLayout();

            const isHtml = email.body_type === 'html' ||
                (email.body && (email.body.includes('<html') || email.body.includes('<div') || email.body.includes('<p>')));

            const bodyContent = isHtml
                ? `<iframe id="emailBodyFrame" sandbox="allow-same-origin" onload="adjustIframeHeight(this)"></iframe>`
                : `<div class="email-body-text">${escapeHtml(email.body)}</div>`;

            const detailMetaRows = `
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
            `;

            const detailHeader = compactMobileMeta
                ? `
                <div class="email-detail-header email-detail-header--compact">
                    <div class="email-detail-subject">${escapeHtml(email.subject || '无主题')}</div>
                    <div class="email-detail-meta-inline">
                        <span class="email-detail-meta-inline__from">${escapeHtml(email.from || '未知发件人')}</span>
                        <span class="email-detail-meta-inline__dot"></span>
                        <span class="email-detail-meta-inline__time">${formatDate(email.date)}</span>
                    </div>
                    <details class="email-detail-meta-collapsible">
                        <summary class="email-detail-meta-collapsible__summary">查看邮件信息</summary>
                        <div class="email-detail-meta email-detail-meta--compact">
                            ${detailMetaRows}
                        </div>
                    </details>
                </div>
                `
                : `
                <div class="email-detail-header">
                    <div class="email-detail-subject">${escapeHtml(email.subject || '无主题')}</div>
                    <div class="email-detail-meta">
                        ${detailMetaRows}
                    </div>
                </div>
                `;

            container.innerHTML = `
                ${detailHeader}
                <div class="email-detail-body">
                    ${renderAttachmentSection(email)}
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
            cleanupNormalDetailIframeResizeResources();
            try {
                const adjustHeight = () => {
                    if (!iframe.isConnected) {
                        return;
                    }
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
                        iframe.style.height = Math.max(height + 100, 600) + 'px';
                    }
                };

                adjustHeight();
                [100, 300, 500, 1000, 2000].forEach(delay => {
                    normalDetailIframeResizeResources.timers.push(window.setTimeout(adjustHeight, delay));
                });

                if (iframe.contentDocument) {
                    normalDetailIframeResizeResources.observer = new MutationObserver(adjustHeight);
                    normalDetailIframeResizeResources.observer.observe(iframe.contentDocument.body, {
                        childList: true,
                        subtree: true,
                        attributes: true
                    });

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

        // 全屏查看邮件
        let currentFullscreenEmail = null;
        let currentRawEmailSource = '';
        let currentRawEmailFilename = 'message.eml';

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
                cleanupFullscreenIframeResizeResources();
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
        function updateTrustToggleState(checkbox) {
            checkbox?.closest('.email-trust-toggle')?.classList.toggle('is-active', !!checkbox?.checked);
        }

        async function toggleTrustMode(checkbox) {
            updateTrustToggleState(checkbox);
            if (checkbox.checked) {
                if (await showConfirmModal('⚠️ 警告：启用信任模式将直接显示邮件原始内容，不进行任何安全过滤。\n\n这可能包含恶意脚本或不安全的内容。您确定要继续吗？', { title: '启用信任模式', confirmText: '确认启用' })) {
                    isTrustedMode = true;
                    if (currentEmailDetail) {
                        renderEmailDetail(currentEmailDetail);
                    }
                } else {
                    checkbox.checked = false;
                    updateTrustToggleState(checkbox);
                }
            } else {
                isTrustedMode = false;
                if (currentEmailDetail) {
                    renderEmailDetail(currentEmailDetail);
                }
            }
        }

        function closeFullscreenEmail() {
            cleanupFullscreenIframeResizeResources();
            const modal = document.getElementById('fullscreenEmailModal');
            if (!modal) return;
            modal.classList.remove('show');
            updateModalBodyState();
        }

        async function openRawEmailModal() {
            if (!currentEmailDetail || !currentEmailDetail.id || !currentAccount) {
                showToast('请先选择一封邮件', 'warning');
                return;
            }

            const modal = document.getElementById('rawEmailModal');
            const content = document.getElementById('rawEmailContent');
            const title = document.getElementById('rawEmailTitle');
            const warning = document.getElementById('rawEmailWarning');
            if (!modal || !content) return;

            currentRawEmailSource = '';
            currentRawEmailFilename = `${currentEmailDetail.id || 'message'}.eml`;
            title.textContent = currentEmailDetail.subject ? `原始邮件：${currentEmailDetail.subject}` : '原始邮件';
            warning.textContent = '原始邮件包含完整邮件头和路由信息，请谨慎分享。';
            content.textContent = '正在加载原始邮件源码...';
            modal.classList.add('show');
            updateModalBodyState();

            const folder = encodeURIComponent(currentEmailDetail.folder || currentFolder || 'inbox');
            const method = encodeURIComponent(getCurrentEmailRemoteActionMethod(currentEmailDetail));
            try {
                const response = await fetchWithTimeout(
                    `/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(currentEmailDetail.id)}/raw?method=${method}&folder=${folder}`,
                    {
                        timeoutMs: EMAIL_DETAIL_REQUEST_TIMEOUT_MS,
                        timeoutMessage: '加载原始邮件超时，请稍后重试'
                    }
                );
                const data = await response.json();
                if (!data.success) {
                    handleApiError(data, '加载原始邮件失败');
                    content.textContent = data.error && data.error.message ? data.error.message : (data.error || '加载原始邮件失败');
                    return;
                }
                currentRawEmailSource = data.raw || '';
                currentRawEmailFilename = data.filename || currentRawEmailFilename;
                if (data.warning) {
                    warning.textContent = data.warning;
                }
                content.textContent = currentRawEmailSource || '原始邮件为空';
            } catch (error) {
                const errorMessage = isTimeoutAbortError(error)
                    ? '加载原始邮件超时，请重试'
                    : '网络错误，请重试';
                content.textContent = errorMessage;
                showToast(errorMessage, 'error');
            }
        }

        function closeRawEmailModal() {
            const modal = document.getElementById('rawEmailModal');
            if (!modal) return;
            modal.classList.remove('show');
            updateModalBodyState();
        }

        function closeRawEmailOnBackdrop(event) {
            if (event.target.id === 'rawEmailModal') {
                closeRawEmailModal();
            }
        }

        async function copyRawEmailSource() {
            if (!currentRawEmailSource) {
                showToast('暂无可复制的原始邮件内容', 'warning');
                return;
            }
            try {
                await navigator.clipboard.writeText(currentRawEmailSource);
                showToast('原始邮件已复制');
            } catch (error) {
                showToast('复制失败，请手动选择复制', 'error');
            }
        }

        function downloadRawEmailSource() {
            if (!currentRawEmailSource) {
                showToast('暂无可下载的原始邮件内容', 'warning');
                return;
            }
            const blob = new Blob([currentRawEmailSource], { type: 'message/rfc822;charset=utf-8' });
            triggerAttachmentDownload(blob, currentRawEmailFilename || 'message.eml');
            showToast('原始邮件下载已开始');
        }

        function closeFullscreenEmailOnBackdrop(event) {
            // 只有点击背景时才关闭，点击内容区域不关闭
            if (event.target.id === 'fullscreenEmailModal') {
                closeFullscreenEmail();
            }
        }

        function adjustFullscreenIframeHeight(iframe) {
            cleanupFullscreenIframeResizeResources();
            try {
                const adjustHeight = () => {
                    if (!iframe.isConnected) {
                        return;
                    }
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
                        iframe.style.height = (height + 100) + 'px';
                    }
                };

                adjustHeight();
                [100, 300, 500, 1000].forEach(delay => {
                    fullscreenIframeResizeResources.timers.push(window.setTimeout(adjustHeight, delay));
                });

                if (iframe.contentDocument) {
                    fullscreenIframeResizeResources.observer = new MutationObserver(adjustHeight);
                    fullscreenIframeResizeResources.observer.observe(iframe.contentDocument.body, {
                        childList: true,
                        subtree: true,
                        attributes: true
                    });

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
        function showEmailList({ scheduleLoadCheck = true } = {}) {
            document.getElementById('emailListPanel').classList.remove('hidden');
            isListVisible = true;
            document.getElementById('toggleListText').textContent = '隐藏列表';
            closeMobilePanels();
            closeNavbarActionsMenu();
            updateMobileContext();
            if (scheduleLoadCheck) {
                scheduleEmailListLoadCheck(0);
            }
        }

        // 刷新邮件
        function refreshEmails() {
            if (currentAccount) {
                if (isTempEmailGroup) {
                    if (currentMethod === 'cloudflare-admin') {
                        loadCloudflareGlobalMessages();
                    } else {
                        loadTempEmailMessages(currentAccount);
                    }
                } else {
                    // 清除当前缓存并强制刷新
                    invalidateEmailListCache(currentAccount, currentFolder);
                    loadEmails(currentAccount, true);
                }
            } else {
                showToast('请先选择一个邮箱账号', 'error');
            }
        }

        function copyTextToClipboard(text, successMessage = '内容已复制') {
            const fallbackCopy = () => {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                showToast(successMessage, 'success');
            };

            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                return navigator.clipboard.writeText(text).then(() => {
                    showToast(successMessage, 'success');
                }).catch(() => {
                    fallbackCopy();
                });
            }

            fallbackCopy();
            return Promise.resolve();
        }

        // 复制邮箱地址
        function copyEmail(email) {
            copyTextToClipboard(email, '邮箱地址已复制');
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
        async function logout() {
            if (await showConfirmModal('确定要退出登录吗？', { title: '退出登录', confirmText: '确认退出', danger: false })) {
                window.location.href = '/logout';
            }
        }
