        /* global escapeHtml, handleApiError, hideModal, showModal, showToast */

        // ==================== Outlook 上传账号 ====================

        const uploadAccountsState = {
            page: 1,
            pageSize: 20,
            keyword: '',
            total: 0,
            totalPages: 1,
            loading: false,
        };

        function formatUploadAccountAuthorized(isAuthorized) {
            return isAuthorized
                ? '<span class="upload-accounts-badge upload-accounts-badge--yes">已授权</span>'
                : '<span class="upload-accounts-badge upload-accounts-badge--no">未授权</span>';
        }

        function renderUploadAccountsRows(items) {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (!tbody) return;

            if (!Array.isArray(items) || items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="upload-accounts-empty">暂无数据</td></tr>';
                return;
            }

            tbody.innerHTML = items.map(item => `
                <tr>
                    <td>${escapeHtml(String(item.id ?? ''))}</td>
                    <td class="upload-accounts-cell-mono">${escapeHtml(item.email || '')}</td>
                    <td class="upload-accounts-cell-mono">${escapeHtml(item.password || '')}</td>
                    <td>${formatUploadAccountAuthorized(item.is_authorized)}</td>
                    <td>${escapeHtml(item.status || '')}</td>
                    <td>${escapeHtml(item.remark || '')}</td>
                    <td>${escapeHtml(item.created_at || '')}</td>
                </tr>
            `).join('');
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
            const pageSizeSelect = document.getElementById('uploadAccountsPageSize');
            if (pageSizeSelect) {
                pageSizeSelect.value = String(uploadAccountsState.pageSize);
            }
        }

        async function loadUploadAccounts() {
            const tbody = document.getElementById('uploadAccountsTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="7" class="upload-accounts-empty">正在加载...</td></tr>';
            }
            uploadAccountsState.loading = true;
            syncUploadAccountsPagination();

            try {
                const params = new URLSearchParams({
                    page: String(uploadAccountsState.page),
                    page_size: String(uploadAccountsState.pageSize),
                });
                if (uploadAccountsState.keyword) {
                    params.set('keyword', uploadAccountsState.keyword);
                }
                const response = await fetch(`/api/outlook-upload-accounts?${params.toString()}`);
                const data = await response.json();
                if (data.success) {
                    uploadAccountsState.total = Number(data.total) || 0;
                    uploadAccountsState.totalPages = Math.max(1, Number(data.total_pages) || 1);
                    uploadAccountsState.page = Math.max(1, Number(data.page) || 1);
                    uploadAccountsState.pageSize = Number(data.page_size) || uploadAccountsState.pageSize;
                    renderUploadAccountsRows(data.items);
                } else {
                    renderUploadAccountsRows([]);
                    handleApiError(data, '加载 Outlook 上传账号失败');
                }
            } catch (error) {
                renderUploadAccountsRows([]);
                showToast('加载 Outlook 上传账号失败: ' + error.message, 'error');
            } finally {
                uploadAccountsState.loading = false;
                syncUploadAccountsPagination();
            }
        }

        function changeUploadAccountsPage(delta) {
            if (uploadAccountsState.loading) return;
            const target = uploadAccountsState.page + delta;
            if (target < 1 || target > uploadAccountsState.totalPages) return;
            uploadAccountsState.page = target;
            loadUploadAccounts();
        }

        function changeUploadAccountsPageSize(value) {
            const parsed = parseInt(value, 10);
            uploadAccountsState.pageSize = Number.isFinite(parsed) ? parsed : 20;
            uploadAccountsState.page = 1;
            loadUploadAccounts();
        }

        function searchUploadAccounts() {
            const input = document.getElementById('uploadAccountsSearch');
            uploadAccountsState.keyword = input ? input.value.trim() : '';
            uploadAccountsState.page = 1;
            loadUploadAccounts();
        }

        function reloadUploadAccounts() {
            loadUploadAccounts();
        }

        function showOutlookUploadAccountsModal() {
            uploadAccountsState.page = 1;
            uploadAccountsState.keyword = '';
            const input = document.getElementById('uploadAccountsSearch');
            if (input) input.value = '';
            showModal('outlookUploadAccountsModal');
            loadUploadAccounts();
        }

        function hideOutlookUploadAccountsModal() {
            hideModal('outlookUploadAccountsModal');
        }
