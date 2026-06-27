(function () {
    const token = document.body.dataset.shareToken || '';
    let currentFolder = 'inbox';
    let currentEmails = [];
    let currentSkip = 0;
    let hasMore = false;
    let isLoading = false;
    let currentMethod = 'graph';
    let selectedEmailId = null;

    // --- Utility Functions ---
    function createLucideIcons() {
        if (typeof lucide !== 'undefined') {
            try {
                lucide.createIcons();
            } catch (e) {
                console.error('Lucide error:', e);
            }
        }
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setStatus(statusText, statusCode) {
        const statusPill = document.getElementById('shareStatusPill');
        const statusSpan = document.getElementById('shareStatusText');
        if (statusSpan) statusSpan.textContent = statusText;
        
        if (statusPill) {
            statusPill.className = 'status-indicator ' + (statusCode || 'invalid');
        }
    }

    function showInvalid(message) {
        const appBody = document.getElementById('appBody');
        if (appBody) appBody.style.display = 'none';
        
        const invalid = document.getElementById('shareInvalidState');
        const title = document.getElementById('shareInvalidTitle');
        if (title) title.textContent = message || '分享链接不可用';
        if (invalid) invalid.hidden = false;
        
        setStatus('链接失效', 'invalid');
        createLucideIcons();
    }

    function showContent() {
        const invalid = document.getElementById('shareInvalidState');
        if (invalid) invalid.hidden = true;
        
        const appBody = document.getElementById('appBody');
        if (appBody) appBody.style.display = 'flex';
        
        setStatus('连接有效', 'active');
    }

    async function requestJson(url) {
        const response = await fetch(url, { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || '请求失败');
        }
        return data;
    }

    // --- Initials and HSL Colors for Avatars ---
    function getAvatarColor(str) {
        let hash = 0;
        const stringVal = String(str || 'U');
        for (let i = 0; i < stringVal.length; i++) {
            hash = stringVal.charCodeAt(i) + ((hash << 5) - hash);
        }
        // Pick an HSL color from 360 range with accessible light/dark settings
        const hue = Math.abs(hash) % 360;
        return `hsl(${hue}, 65%, 40%)`;
    }

    function getInitials(str) {
        const name = String(str || '').trim();
        if (!name) return '?';
        // If it looks like an email address, return the first character
        if (name.includes('@') && !name.includes('<')) {
            return name.charAt(0).toUpperCase();
        }
        // Try to match name part before email if present, e.g. "John Doe <john@example.com>"
        let cleanName = name;
        const emailMatch = name.match(/^(.*?)\s*<.*?>/);
        if (emailMatch && emailMatch[1]) {
            cleanName = emailMatch[1].trim();
        }
        
        cleanName = cleanName.replace(/['"“”]/g, '');
        if (!cleanName) return '?';

        // Check if Chinese name
        if (/^[\u4e00-\u9fa5]+$/.test(cleanName)) {
            return cleanName.length > 2 ? cleanName.slice(-2) : cleanName;
        }

        const parts = cleanName.split(/\s+/).filter(Boolean);
        if (parts.length > 1) {
            return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
        }
        return cleanName.slice(0, 2).toUpperCase();
    }

    function cleanSenderName(str) {
        const name = String(str || '').trim();
        const emailMatch = name.match(/^(.*?)\s*<.*?>/);
        if (emailMatch && emailMatch[1]) {
            return emailMatch[1].replace(/['"“”]/g, '').trim();
        }
        return name;
    }

    // --- Date Formatting ---
    function formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr;
            
            const now = new Date();
            const pad = n => String(n).padStart(2, '0');
            const hours = pad(date.getHours());
            const minutes = pad(date.getMinutes());
            
            // Today
            if (date.toDateString() === now.toDateString()) {
                return `今天 ${hours}:${minutes}`;
            }
            
            // Yesterday
            const yesterday = new Date(now);
            yesterday.setDate(now.getDate() - 1);
            if (date.toDateString() === yesterday.toDateString()) {
                return `昨天 ${hours}:${minutes}`;
            }
            
            // This year
            if (date.getFullYear() === now.getFullYear()) {
                return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hours}:${minutes}`;
            }
            
            return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
        } catch (e) {
            return dateStr;
        }
    }

    function formatBytes(bytes) {
        if (!bytes || isNaN(bytes)) return '0 B';
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function getAttachmentIcon(filename) {
        const ext = String(filename || '').split('.').pop().toLowerCase();
        switch (ext) {
            case 'pdf': return 'file-text';
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'gif':
            case 'webp': return 'image';
            case 'zip':
            case 'rar':
            case '7z':
            case 'tar':
            case 'gz': return 'archive';
            case 'doc':
            case 'docx': return 'file-edit';
            case 'xls':
            case 'xlsx': return 'grid';
            case 'ppt':
            case 'pptx': return 'presentation';
            default: return 'file';
        }
    }

    // --- Search Filtering Helper ---
    function getActiveEmails() {
        const searchInput = document.getElementById('emailSearchInput');
        const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
        if (query) {
            return currentEmails.filter(email => 
                (email.subject || '').toLowerCase().includes(query) ||
                (email.from || '').toLowerCase().includes(query) ||
                (email.body_preview || '').toLowerCase().includes(query)
            );
        }
        return currentEmails;
    }

    // --- View Rendering ---
    function renderListLoading() {
        const list = document.getElementById('shareEmailList');
        if (list) {
            list.innerHTML = `
                <div class="list-skeleton">
                    <div class="skeleton-item"></div>
                    <div class="skeleton-item"></div>
                    <div class="skeleton-item"></div>
                    <div class="skeleton-item"></div>
                </div>
            `;
        }
    }

    function renderListError(message) {
        const list = document.getElementById('shareEmailList');
        if (list) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon-wrapper">
                        <i data-lucide="alert-triangle" style="color: var(--danger)"></i>
                    </div>
                    <h3>加载邮件失败</h3>
                    <p>${escapeHtml(message)}</p>
                </div>
            `;
            createLucideIcons();
        }
    }

    function renderEmailList() {
        const list = document.getElementById('shareEmailList');
        const activeEmails = getActiveEmails();
        const searchInput = document.getElementById('emailSearchInput');
        const isSearching = searchInput && searchInput.value.trim() !== '';

        if (!activeEmails.length) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon-wrapper">
                        <i data-lucide="mail-open"></i>
                    </div>
                    <h3>${isSearching ? '未找到相关邮件' : '暂无邮件'}</h3>
                    <p>${isSearching ? '请尝试修改您的搜索关键词' : '当前文件夹中没有收到任何邮件'}</p>
                </div>
            `;
        } else {
            list.innerHTML = activeEmails.map((email) => {
                const isSelected = selectedEmailId === email.id;
                const initials = getInitials(email.from);
                const color = getAvatarColor(email.from);
                const senderName = cleanSenderName(email.from);
                
                return `
                    <button class="email-item-btn ${email.is_read ? '' : 'unread'} ${isSelected ? 'active' : ''}" 
                            type="button" 
                            data-id="${escapeHtml(email.id)}">
                        <div class="email-item-avatar" style="background-color: ${color}">
                            ${escapeHtml(initials)}
                        </div>
                        <div class="email-item-content">
                            <div class="email-item-header">
                                <span class="email-item-sender">${escapeHtml(senderName)}</span>
                                <span class="email-item-date">${escapeHtml(formatDate(email.date))}</span>
                            </div>
                            <div class="email-item-subject">${escapeHtml(email.subject || '无主题')}</div>
                            <div class="email-item-body">${escapeHtml(email.body_preview || '')}</div>
                            ${email.has_attachments ? `
                                <div class="email-item-meta">
                                    <i data-lucide="paperclip"></i>
                                    <span>包含附件</span>
                                </div>
                            ` : ''}
                        </div>
                    </button>
                `;
            }).join('');
        }
        
        // Hide load more button if searching or if API says there's no more
        const loadMoreBtn = document.getElementById('shareLoadMoreBtn');
        if (loadMoreBtn) {
            loadMoreBtn.hidden = isSearching || !hasMore;
        }

        createLucideIcons();
    }

    async function loadEmails({ append = false } = {}) {
        if (isLoading) return;
        isLoading = true;

        if (!append) {
            currentSkip = 0;
            currentEmails = [];
            renderListLoading();
            
            const detailPanel = document.getElementById('shareEmailDetail');
            if (detailPanel) {
                detailPanel.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon-wrapper">
                            <i data-lucide="mail-open" class="empty-icon"></i>
                        </div>
                        <h3>选择一封邮件</h3>
                        <p>点击左侧列表中的邮件以在此处查看其详细内容和附件。</p>
                    </div>
                `;
            }
            selectedEmailId = null;
            createLucideIcons();
        }

        const loadMoreBtn = document.getElementById('shareLoadMoreBtn');
        if (loadMoreBtn) {
            loadMoreBtn.disabled = true;
            const btnText = loadMoreBtn.querySelector('span');
            if (btnText) {
                btnText.textContent = '加载中...';
            }
            // Show load more button while loading to show feedback
            loadMoreBtn.hidden = false;
        }
        
        const params = new URLSearchParams({
            folder: currentFolder,
            skip: String(currentSkip),
            top: '20'
        });
        
        try {
            const data = await requestJson(`/api/share/email/${encodeURIComponent(token)}/emails?${params.toString()}`);
            const items = Array.isArray(data.emails) ? data.emails : [];
            currentMethod = data.remote_method || data.method || currentMethod;
            currentEmails = append ? currentEmails.concat(items) : items;
            currentSkip += items.length;
            hasMore = !!data.has_more;
            
            const methodTag = document.getElementById('shareMethodTag');
            if (methodTag) {
                methodTag.textContent = data.method ? `读取方式: ${data.method}` : '';
            }
            
            renderEmailList();
        } catch (error) {
            if (append) {
                console.error("加载更多邮件失败:", error);
                if (loadMoreBtn) {
                    const btnText = loadMoreBtn.querySelector('span');
                    if (btnText) {
                        btnText.textContent = '加载失败，点击重试';
                    }
                }
            } else {
                renderListError(error.message);
            }
        } finally {
            isLoading = false;
            if (loadMoreBtn) {
                loadMoreBtn.disabled = false;
                const btnText = loadMoreBtn.querySelector('span');
                if (btnText && btnText.textContent === '加载中...') {
                    btnText.textContent = '加载更多';
                }
                const searchInput = document.getElementById('emailSearchInput');
                const isSearching = searchInput && searchInput.value.trim() !== '';
                loadMoreBtn.hidden = isSearching || !hasMore;
            }
        }
    }

    function buildDetailUrl(email) {
        const params = new URLSearchParams({
            method: email.id_mode === 'graph' ? 'graph' : (currentMethod || 'graph'),
            folder: email.folder || currentFolder
        });
        if (email.id_mode) {
            params.set('id_mode', email.id_mode);
        }
        return `/api/share/email/${encodeURIComponent(token)}/email/${encodeURIComponent(email.id)}?${params.toString()}`;
    }

    function renderAttachments(attachments) {
        if (!Array.isArray(attachments) || attachments.length === 0) {
            return '';
        }
        return `
            <div class="attachments-section">
                <div class="attachments-title">
                    <i data-lucide="paperclip"></i>
                    <span>附件 (${attachments.length})</span>
                </div>
                <div class="attachments-grid">
                    ${attachments.map(att => {
                        const name = att.name || att.filename || '未命名附件';
                        const size = att.size ? formatBytes(att.size) : '';
                        const icon = getAttachmentIcon(name);
                        return `
                            <div class="attachment-card">
                                <div class="attachment-icon-wrapper">
                                    <i data-lucide="${icon}"></i>
                                </div>
                                <div class="attachment-details">
                                    <div class="attachment-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
                                    <div class="attachment-size">${escapeHtml(size)}</div>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }

    function renderBody(email) {
        const body = String(email.body || '');
        const bodyType = String(email.body_type || 'text').toLowerCase();
        if (bodyType === 'html') {
            const safeHtml = window.DOMPurify ? window.DOMPurify.sanitize(body) : escapeHtml(body);
            return `
                <div class="iframe-container">
                    <iframe title="邮件正文" sandbox="allow-popups allow-popups-to-escape-sandbox" srcdoc="${escapeHtml(safeHtml)}"></iframe>
                </div>
            `;
        }
        return `<pre class="plain-text-body">${escapeHtml(body)}</pre>`;
    }

    function renderEmailDetail(email) {
        const initials = getInitials(email.from);
        const color = getAvatarColor(email.from);
        const senderName = cleanSenderName(email.from);
        const rawSender = String(email.from || '');
        const emailAddress = rawSender.includes('<') ? rawSender.substring(rawSender.indexOf('<')) : '';

        const detailPanel = document.getElementById('shareEmailDetail');
        if (detailPanel) {
            detailPanel.innerHTML = `
                <div class="detail-card">
                    <div class="detail-header">
                        <h2 class="detail-subject">${escapeHtml(email.subject || '无主题')}</h2>
                        <div class="detail-meta-row">
                            <div class="detail-meta-avatar" style="background-color: ${color}">
                                ${escapeHtml(initials)}
                            </div>
                            <div class="detail-meta-info">
                                <div class="detail-sender">
                                    ${escapeHtml(senderName)} 
                                    <span class="user-email" style="font-size: 12px; font-weight: normal; margin-left: 4px;">${escapeHtml(emailAddress)}</span>
                                </div>
                                <div class="detail-recipients">
                                    <strong>收件人:</strong> ${escapeHtml(email.to || '')}
                                    ${email.cc ? `<br><strong>抄送:</strong> ${escapeHtml(email.cc)}` : ''}
                                </div>
                            </div>
                            <div class="detail-date">
                                ${escapeHtml(formatDate(email.date))}
                            </div>
                        </div>
                    </div>
                    <div class="detail-body-wrapper">
                        ${renderBody(email)}
                    </div>
                    ${renderAttachments(email.attachments)}
                </div>
            `;
            createLucideIcons();
        }
    }

    async function selectEmail(emailId) {
        if (!emailId) return;
        selectedEmailId = emailId;
        
        // Update list active classes
        document.querySelectorAll('.email-item-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.id === emailId);
        });

        // Show loading state in details
        const detailPanel = document.getElementById('shareEmailDetail');
        if (detailPanel) {
            detailPanel.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon-wrapper">
                        <i data-lucide="loader" class="animate-spin" style="animation: spin 1s linear infinite;"></i>
                    </div>
                    <h3>正在加载邮件详情...</h3>
                    <p>正在拉取完整的邮件内容及附件列表，请稍候。</p>
                </div>
            `;
            createLucideIcons();
        }

        // Add responsive helper class for mobile screens
        const appBody = document.getElementById('appBody');
        if (appBody) {
            appBody.classList.add('show-detail');
        }

        try {
            // Find email object to resolve parameters
            const email = currentEmails.find(e => e.id === emailId);
            if (!email) throw new Error('未找到邮件对象');
            
            const data = await requestJson(buildDetailUrl(email));
            renderEmailDetail(data.email || {});
        } catch (error) {
            if (detailPanel) {
                detailPanel.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon-wrapper">
                            <i data-lucide="alert-triangle" style="color: var(--danger)"></i>
                        </div>
                        <h3>加载邮件详情失败</h3>
                        <p>${escapeHtml(error.message)}</p>
                    </div>
                `;
                createLucideIcons();
            }
        }
    }

    // --- Search Interactions ---
    function setupSearch() {
        const searchInput = document.getElementById('emailSearchInput');
        const clearBtn = document.getElementById('searchClearBtn');
        
        if (!searchInput) return;

        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim();
            if (clearBtn) {
                clearBtn.hidden = query === '';
            }
            renderEmailList();
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                clearBtn.hidden = true;
                renderEmailList();
                searchInput.focus();
            });
        }
    }

    // --- Theme System ---
    function setupTheme() {
        const toggleBtn = document.getElementById('themeToggleBtn');
        if (!toggleBtn) return;

        const savedTheme = localStorage.getItem('theme');
        const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        
        const currentTheme = savedTheme || (systemPrefersDark ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', currentTheme);

        toggleBtn.addEventListener('click', () => {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const newTheme = isDark ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        });
    }

    // --- Scroll Load System ---
    function setupScrollLoad() {
        const emailList = document.getElementById('shareEmailList');
        if (!emailList) return;

        emailList.addEventListener('scroll', () => {
            const searchInput = document.getElementById('emailSearchInput');
            const isSearching = searchInput && searchInput.value.trim() !== '';

            if (isLoading || !hasMore || isSearching) return;

            const threshold = 100; // 100px from bottom
            const remainingScroll = emailList.scrollHeight - emailList.scrollTop - emailList.clientHeight;
            if (remainingScroll <= threshold) {
                loadEmails({ append: true });
            }
        });
    }

    function insertGithubLink() {
        const headerRight = document.querySelector('.header-right');
        if (!headerRight) return;
        
        let githubLink = headerRight.querySelector('.github-link');
        const svgHtml = `
            <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="github-icon">
                <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path>
            </svg>
        `;
        
        if (!githubLink) {
            githubLink = document.createElement('a');
            githubLink.className = 'github-link';
            githubLink.href = 'https://github.com/assast/outlookEmail';
            githubLink.target = '_blank';
            githubLink.rel = 'noopener noreferrer';
            githubLink.setAttribute('aria-label', 'GitHub 仓库');
            githubLink.innerHTML = svgHtml;
            headerRight.appendChild(githubLink);
        } else {
            if (!githubLink.querySelector('svg')) {
                githubLink.innerHTML = svgHtml;
            }
            // Move existing githubLink to the end of the container to keep it on the far right
            headerRight.appendChild(githubLink);
        }
    }

    function showToast(message) {
        let toast = document.getElementById('shareToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'shareToast';
            toast.className = 'toast-notification';
            toast.innerHTML = `
                <i data-lucide="check" class="toast-icon"></i>
                <span class="toast-message"></span>
            `;
            document.body.appendChild(toast);
            createLucideIcons();
        }
        
        toast.querySelector('.toast-message').textContent = message;
        toast.classList.add('show');
        
        if (toast.timeoutId) {
            clearTimeout(toast.timeoutId);
        }
        
        toast.timeoutId = setTimeout(() => {
            toast.classList.remove('show');
        }, 2000);
    }

    function fallbackCopyText(text) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand('copy');
            showToast('已复制邮箱地址到剪贴板');
        } catch (err) {
            console.error('Fallback copy failed', err);
        }
        document.body.removeChild(textArea);
    }

    function setupCopyEmail() {
        const copyEmailPill = document.getElementById('copyEmailPill');
        if (copyEmailPill) {
            copyEmailPill.addEventListener('click', () => {
                const emailTitle = document.getElementById('shareEmailTitle');
                if (!emailTitle) return;
                const emailText = emailTitle.textContent.trim();
                
                if (emailText && emailText.includes('@')) {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(emailText)
                            .then(() => {
                                showToast('已复制邮箱地址到剪贴板');
                            })
                            .catch(err => {
                                console.error('Clipboard copy failed: ', err);
                                fallbackCopyText(emailText);
                            });
                    } else {
                        fallbackCopyText(emailText);
                    }
                }
            });
        }
    }

    // --- Setup Initialization ---
    async function initializeSharePage() {
        insertGithubLink();
        setupTheme();
        setupSearch();
        setupScrollLoad();
        setupCopyEmail();

        if (!token) {
            showInvalid('分享链接不可用');
            return;
        }

        try {
            const status = await requestJson(`/api/share/email/${encodeURIComponent(token)}/status`);
            
            const titleElement = document.getElementById('shareEmailTitle');
            if (titleElement) titleElement.textContent = status.email || '邮箱分享';
            
            const headerAvatar = document.getElementById('headerUserAvatar');
            if (headerAvatar) {
                headerAvatar.textContent = getInitials(status.email);
                headerAvatar.style.backgroundColor = getAvatarColor(status.email);
            }
            
            showContent();
            await loadEmails();
        } catch (error) {
            showInvalid(error.message);
        }
    }

    // --- Global Event Delegation ---
    document.addEventListener('click', (event) => {
        // Folder selection
        const folderBtn = event.target.closest('.folder-btn');
        if (folderBtn) {
            currentFolder = folderBtn.dataset.folder || 'inbox';
            document.querySelectorAll('.folder-btn').forEach(btn => {
                btn.classList.toggle('active', btn === folderBtn);
            });
            loadEmails();
            
            // If on mobile and switching folders, reset view to list
            const appBody = document.getElementById('appBody');
            if (appBody) appBody.classList.remove('show-detail');
            return;
        }

        // Email item selection
        const emailItem = event.target.closest('.email-item-btn');
        if (emailItem) {
            selectEmail(emailItem.dataset.id);
            return;
        }

        // Load more
        if (event.target.closest('#shareLoadMoreBtn')) {
            loadEmails({ append: true });
            return;
        }

        // Mobile back button
        if (event.target.closest('#mobileBackBtn')) {
            const appBody = document.getElementById('appBody');
            if (appBody) {
                appBody.classList.remove('show-detail');
            }
            return;
        }
    });

    // Start
    document.addEventListener('DOMContentLoaded', () => {
        initializeSharePage();
    });
    
    // Safety fallback in case DOMContentLoaded has already fired
    if (document.readyState === 'interactive' || document.readyState === 'complete') {
        initializeSharePage();
    }
})();
