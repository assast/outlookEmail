        /* global adjustIframeHeight, closeMobilePanels, closeNavbarActionsMenu, copyCurrentEmail, currentAccount, currentEmailDetail, currentEmailId, currentEmails, currentFolder, currentMethod, emailListCache, escapeHtml, formatDate, getFolderDisplayName, handleApiError, isTempEmailGroup, showMobileEmailDetail, showToast, updateMobileContext, updateModalBodyState */

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

        function getRecipientDisplayLabel(emailItem) {
            if (isTempEmailGroup) {
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
            if (isTempEmailGroup || currentFolder !== 'all' || !emailItem?.folder) {
                return '';
            }
            return getFolderDisplayName(emailItem?.folder);
        }

        function renderEmailList(emails) {
            const container = document.getElementById('emailList');

            if (emails.length === 0) {
                const emptyStateText = isTempEmailGroup
                    ? '暂无邮件'
                    : `${getFolderDisplayName(currentFolder)}为空`;
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📭</div>
                        <div class="empty-state-text">${emptyStateText}</div>
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
                const recipientDisplayLabel = getRecipientDisplayLabel(email);
                const sourceLabel = getEmailSourceLabel(email);
                return `
                <div class="email-item ${email.is_read === false ? 'unread' : ''} ${isActive ? 'active' : ''}"
                     onclick="${clickHandler}('${email.id}', ${index})">
                    <div class="email-checkbox-wrapper" onclick="event.stopPropagation(); toggleEmailSelection('${email.id}')">
                        <input type="checkbox" class="email-checkbox" ${isChecked ? 'checked' : ''} style="pointer-events: none;">
                    </div>
                    <div class="email-body">
                        <div class="email-top-row">
                            <div class="email-top-main">
                                <div class="email-sender-block">
                                    <div class="email-from" title="${escapeHtml(email.from || '未知发件人')}">${escapeHtml(email.from || '未知发件人')}</div>
                                    ${recipientDisplayLabel ? `<div class="email-recipient" title="${escapeHtml(recipientDisplayLabel)}">${escapeHtml(recipientDisplayLabel)}</div>` : ''}
                                </div>
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
            const panel = document.getElementById('emailListPanel');
            if (isTempEmailGroup) {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
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
            } else {
                bar.style.display = 'none';
                panel?.classList.remove('batch-toolbar-active');
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
                const response = await fetch(`/api/email/${encodeURIComponent(currentAccount)}/${encodeURIComponent(messageId)}?method=${currentMethod}&folder=${requestFolder}`);
                const data = await response.json();

                if (data.success) {
                    currentEmailDetail = { ...data.email, folder: requestFolder };
                    renderEmailDetail(currentEmailDetail);
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

            closeMobilePanels();
            closeNavbarActionsMenu();
            updateMobileContext();
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
            closeMobilePanels();
            closeNavbarActionsMenu();
            updateMobileContext();
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
        async function logout() {
            if (await showConfirmModal('确定要退出登录吗？', { title: '退出登录', confirmText: '确认退出', danger: false })) {
                window.location.href = '/logout';
            }
        }
