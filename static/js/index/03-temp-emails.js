        /* global accountsCache, closeMobilePanels, currentAccount, currentEmailDetail, currentEmailId, currentEmails, currentMethod, currentGroupId, escapeHtml, formatDate, groups, handleApiError, loadGroups, loadTempEmails, renderEmailDetail, renderEmailList, showEmailList, showMobileEmailDetail, showToast, updateMobileContext, updateCurrentGroupHeader */

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
            currentAccountListSource = [];

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
            showEmailList();
            closeMobilePanels();
            updateMobileContext();

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
                        showEmailList();
                        updateMobileContext();
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
            showMobileEmailDetail();

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
