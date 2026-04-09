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

        function invalidateRefreshTokenPreview() {
            oauthPreviewAccount = null;
            const resultEl = document.getElementById('refreshTokenResult');
            if (resultEl) {
                resultEl.style.display = 'none';
            }
        }

        function renderRefreshTokenPreview() {
            if (!oauthPreviewAccount) {
                invalidateRefreshTokenPreview();
                return;
            }
            const resultEl = document.getElementById('refreshTokenResult');
            const saveBtn = document.getElementById('saveTokenAccountBtn');
            const group = groups.find(item => item.id === oauthPreviewAccount.group_id);
            document.getElementById('oauthPreviewEmail').value = oauthPreviewAccount.email || '';
            document.getElementById('oauthPreviewPassword').value = oauthPreviewAccount.password || '';
            document.getElementById('oauthPreviewClientId').value = oauthPreviewAccount.client_id || '';
            document.getElementById('oauthPreviewGroup').value = group?.name || `分组 #${oauthPreviewAccount.group_id}`;
            document.getElementById('oauthPreviewRefreshToken').value = oauthPreviewAccount.refresh_token || '';
            if (resultEl) {
                resultEl.style.display = 'block';
            }
        }

        // 显示获取 Refresh Token 模态框
        async function showGetRefreshTokenModal() {
            showModal('getRefreshTokenModal');

            // 重置表单
            document.getElementById('oauthEmailInput').value = '';
            document.getElementById('oauthPasswordInput').value = '';
            document.getElementById('redirectUrlInput').value = '';
            document.getElementById('oauthForwardEnabled').checked = false;
            invalidateRefreshTokenPreview();

            // 重置按钮状态
            const btn = document.getElementById('exchangeTokenBtn');
            btn.disabled = false;
            btn.textContent = '换取并预览';
            btn.style.display = '';
            const saveBtn = document.getElementById('saveTokenAccountBtn');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = '直接保存（自动换取）';
            }

            const groupSelect = document.getElementById('tokenSaveGroupSelect');
            if (groupSelect) {
                const nonTempGroups = groups.filter(group => group.name !== '临时邮箱');
                const fallbackGroupId = (!isTempEmailGroup && currentGroupId && nonTempGroups.find(group => group.id === currentGroupId))
                    ? currentGroupId
                    : (nonTempGroups[0]?.id || '');
                if (fallbackGroupId) {
                    groupSelect.value = fallbackGroupId;
                }
            }

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
        async function exchangeToken(options = {}) {
            const { silentSuccess = false, keepSavingState = false } = options;
            const email = document.getElementById('oauthEmailInput').value.trim();
            const password = document.getElementById('oauthPasswordInput').value;
            const redirectUrl = document.getElementById('redirectUrlInput').value.trim();
            const groupId = parseInt(document.getElementById('tokenSaveGroupSelect')?.value || '0', 10);
            const forwardEnabled = !!document.getElementById('oauthForwardEnabled')?.checked;

            if (!email || !password) {
                showToast('请先输入邮箱账号和密码', 'error');
                return;
            }

            if (!redirectUrl) {
                showToast('请先粘贴授权后的完整 URL', 'error');
                return;
            }

            if (!groupId) {
                showToast('请选择目标分组', 'error');
                return;
            }

            const btn = document.getElementById('exchangeTokenBtn');
            const saveBtn = document.getElementById('saveTokenAccountBtn');
            btn.disabled = true;
            if (!keepSavingState && saveBtn) {
                saveBtn.disabled = true;
            }
            btn.textContent = '⏳ 预览中...';

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
                    oauthPreviewAccount = {
                        email,
                        password,
                        client_id: data.client_id,
                        refresh_token: data.refresh_token,
                        group_id: groupId,
                        forward_enabled: forwardEnabled
                    };
                    renderRefreshTokenPreview();

                    if (!silentSuccess) {
                        showToast('✅ Refresh Token 获取成功！', 'success');
                    }

                    // 重置按钮状态（不隐藏，允许重复使用）
                    btn.disabled = false;
                    if (!keepSavingState && saveBtn) {
                        saveBtn.disabled = false;
                    }
                    btn.textContent = '换取并预览';
                    return true;
                } else {
                    handleApiError(data, '换取 Token 失败');
                    btn.disabled = false;
                    if (!keepSavingState && saveBtn) {
                        saveBtn.disabled = false;
                    }
                    btn.textContent = '换取并预览';
                    return false;
                }
            } catch (error) {
                showToast('换取 Token 失败: ' + error.message, 'error');
                btn.disabled = false;
                if (!keepSavingState && saveBtn) {
                    saveBtn.disabled = false;
                }
                btn.textContent = '换取并预览';
                return false;
            }
        }

        async function saveTokenAccount() {
            if (!oauthPreviewAccount) {
                const exchanged = await exchangeToken({ silentSuccess: true, keepSavingState: true });
                if (!exchanged || !oauthPreviewAccount) {
                    return;
                }
            }

            const saveBtn = document.getElementById('saveTokenAccountBtn');
            const exchangeBtn = document.getElementById('exchangeTokenBtn');
            saveBtn.disabled = true;
            exchangeBtn.disabled = true;
            saveBtn.textContent = '保存中...';

            try {
                const accountString = [
                    oauthPreviewAccount.email,
                    oauthPreviewAccount.password,
                    oauthPreviewAccount.client_id,
                    oauthPreviewAccount.refresh_token
                ].join('----');

                const response = await fetch('/api/accounts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_string: accountString,
                        group_id: oauthPreviewAccount.group_id,
                        provider: 'outlook',
                        forward_enabled: !!oauthPreviewAccount.forward_enabled
                    })
                });

                const data = await response.json();
                if (data.success) {
                    showToast(data.message || '账号已保存', 'success');
                    currentGroupId = oauthPreviewAccount.group_id;
                    await loadGroups();
                    hideGetRefreshTokenModal();
                } else {
                    handleApiError(data, '保存账号失败');
                }
            } catch (error) {
                showToast('保存账号失败', 'error');
            } finally {
                exchangeBtn.disabled = false;
                saveBtn.disabled = false;
                saveBtn.textContent = '直接保存（自动换取）';
            }
        }

