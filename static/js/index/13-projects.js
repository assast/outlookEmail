        /* global escapeHtml, flattenGroupTree, getGroupOptionLabel, groupTree, groups, handleApiError, hideModal, showConfirmModal, showModal, showToast */

        // ==================== 项目管理（入口默认隐藏，设置中开启） ====================

        const pmState = {
            projects: [],
            loading: false,
            initialized: false,
            keyword: '',
        };

        function applyProjectManagementVisibility() {
            const visible = typeof shouldShowProjectManagement === 'function' && shouldShowProjectManagement();
            const mobileBtn = document.getElementById('projectManagementBtn');
            const desktopBtn = document.getElementById('desktopProjectManagementBtn');
            if (mobileBtn) {
                mobileBtn.style.display = visible ? '' : 'none';
            }
            if (desktopBtn) {
                desktopBtn.style.display = visible ? '' : 'none';
            }
        }

        function showProjectManagementModal() {
            showModal('projectManagementModal');
            if (!pmState.initialized) {
                loadProjects();
            }
        }

        function hideProjectManagementModal() {
            hideModal('projectManagementModal');
        }

        async function loadProjects() {
            if (pmState.loading) {
                return;
            }
            pmState.loading = true;
            const tbody = document.getElementById('projectsTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="9" class="project-mgmt-empty">加载中...</td></tr>';
            }
            try {
                const response = await fetch('/api/projects');
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '加载项目列表失败');
                    if (tbody) {
                        tbody.innerHTML = '<tr><td colspan="9" class="project-mgmt-empty">加载失败，点击「刷新」重试。</td></tr>';
                    }
                    return;
                }
                pmState.projects = Array.isArray(data?.data?.projects) ? data.data.projects : [];
                pmState.initialized = true;
                pmState.loading = false;
                renderProjects();
            } catch (error) {
                showToast('加载项目列表失败，请稍后重试', 'error');
                if (tbody) {
                    tbody.innerHTML = '<tr><td colspan="9" class="project-mgmt-empty">加载失败，点击「刷新」重试。</td></tr>';
                }
            } finally {
                pmState.loading = false;
            }
        }

        function filterProjects(value) {
            pmState.keyword = String(value || '').trim().toLowerCase();
            renderProjects();
        }

        function renderProjects() {
            const tbody = document.getElementById('projectsTableBody');
            if (!tbody || pmState.loading) {
                return;
            }
            if (!pmState.projects.length) {
                tbody.innerHTML = '<tr><td colspan="9" class="project-mgmt-empty">暂无项目，点击右上角「新建项目」创建。</td></tr>';
                return;
            }
            const keyword = pmState.keyword;
            const matched = pmState.projects.filter(project => {
                if (!keyword) {
                    return true;
                }
                const key = String(project.project_key || '').toLowerCase();
                const name = String(project.name || '').toLowerCase();
                return key.includes(keyword) || name.includes(keyword);
            });
            if (!matched.length) {
                tbody.innerHTML = '<tr><td colspan="9" class="project-mgmt-empty">没有匹配的项目。</td></tr>';
                return;
            }
            tbody.innerHTML = matched.map(project => {
                const key = String(project.project_key || '');
                const isActive = String(project.status || 'active') === 'active';
                const name = String(project.name || '');
                const statusBadge = isActive
                    ? '<span class="project-mgmt-badge project-mgmt-badge--active">已启用</span>'
                    : '<span class="project-mgmt-badge project-mgmt-badge--archived">已停用</span>';
                const statusBtn = isActive
                    ? `<button class="btn btn-secondary btn-sm" type="button" data-key="${escapeHtml(key)}" onclick="archiveProject(this.dataset.key)">停用</button>`
                    : `<button class="btn btn-secondary btn-sm" type="button" data-key="${escapeHtml(key)}" onclick="restoreProject(this.dataset.key)">恢复</button>`;
                const deleteBtn = `<button class="btn btn-danger btn-sm" type="button" data-key="${escapeHtml(key)}" onclick="deleteProject(this.dataset.key)">删除</button>`;
                return `
                    <tr>
                        <td class="project-mgmt-key" title="${escapeHtml(key)}">${escapeHtml(key)}</td>
                        <td title="${escapeHtml(name)}">${name ? escapeHtml(name) : '-'}</td>
                        <td>${statusBadge}</td>
                        <td>${Number(project.total_count || 0)}</td>
                        <td>${Number(project.to_claim_count || 0)}</td>
                        <td>${Number(project.claiming_count || 0)}</td>
                        <td>${Number(project.done_count || 0)}</td>
                        <td>${Number(project.failed_count || 0)}</td>
                        <td>${statusBtn}${deleteBtn}</td>
                    </tr>`;
            }).join('');
        }

        function toggleProjectCreateForm(visible) {
            const form = document.getElementById('projectCreateForm');
            if (!form) {
                return;
            }
            const show = typeof visible === 'boolean' ? visible : form.style.display === 'none';
            form.style.display = show ? '' : 'none';
            const toggleBtn = document.getElementById('projectCreateToggleBtn');
            if (toggleBtn) {
                toggleBtn.textContent = show ? '收起表单' : '新建项目';
            }
            if (show) {
                renderProjectGroupOptions();
            }
        }

        function renderProjectGroupOptions() {
            const container = document.getElementById('projectGroupCheckboxList');
            if (!container) {
                return;
            }
            let options = [];
            if (typeof flattenGroupTree === 'function' && typeof groupTree !== 'undefined') {
                options = flattenGroupTree(groupTree).map(group => ({
                    id: group.id,
                    label: typeof getGroupOptionLabel === 'function' ? getGroupOptionLabel(group) : group.name,
                }));
            } else if (typeof groups !== 'undefined' && Array.isArray(groups)) {
                options = groups.map(group => ({ id: group.id, label: group.name }));
            }
            if (!options.length) {
                container.innerHTML = '<span class="project-mgmt-group-empty">分组尚未加载；留空则项目范围为全部邮箱。</span>';
                return;
            }
            container.innerHTML = options.map(option =>
                `<label class="project-mgmt-group-option">
                    <input type="checkbox" class="project-mgmt-group-checkbox" value="${Number(option.id)}" onchange="syncProjectGroupSelectAll()">
                    <span>${escapeHtml(option.label)}</span>
                </label>`
            ).join('');
            syncProjectGroupSelectAll();
        }

        function toggleProjectGroupSelectAll(checked) {
            document.querySelectorAll('.project-mgmt-group-checkbox').forEach(checkbox => {
                checkbox.checked = !!checked;
            });
        }

        function syncProjectGroupSelectAll() {
            const checkboxes = Array.from(document.querySelectorAll('.project-mgmt-group-checkbox'));
            const selectAll = document.getElementById('projectGroupSelectAll');
            if (!selectAll) {
                return;
            }
            const checkedCount = checkboxes.filter(checkbox => checkbox.checked).length;
            selectAll.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
        }

        function resetProjectCreateForm() {
            ['projectKeyInput', 'projectNameInput', 'projectDescriptionInput'].forEach(id => {
                const input = document.getElementById(id);
                if (input) {
                    input.value = '';
                }
            });
            const useAlias = document.getElementById('projectUseAliasEmail');
            if (useAlias) {
                useAlias.checked = false;
            }
            document.querySelectorAll('.project-mgmt-group-checkbox').forEach(checkbox => {
                checkbox.checked = false;
            });
            syncProjectGroupSelectAll();
        }

        async function submitCreateProject() {
            const keyInput = document.getElementById('projectKeyInput');
            const projectKey = String(keyInput?.value || '').trim();
            if (!projectKey) {
                showToast('请填写项目 Key', 'error');
                return;
            }
            const name = String(document.getElementById('projectNameInput')?.value || '').trim();
            const description = String(document.getElementById('projectDescriptionInput')?.value || '').trim();
            const useAliasEmail = !!document.getElementById('projectUseAliasEmail')?.checked;
            const groupIds = Array.from(document.querySelectorAll('.project-mgmt-group-checkbox:checked'))
                .map(checkbox => Number(checkbox.value))
                .filter(id => Number.isFinite(id) && id > 0);

            const payload = { project_key: projectKey, use_alias_email: useAliasEmail };
            if (name) {
                payload.name = name;
            }
            if (description) {
                payload.description = description;
            }
            if (groupIds.length) {
                payload.group_ids = groupIds;
            }

            const submitBtn = document.getElementById('submitCreateProjectBtn');
            if (submitBtn) {
                submitBtn.disabled = true;
            }
            try {
                const response = await fetch('/api/projects/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '创建项目失败');
                    return;
                }
                const summary = data?.data || {};
                const headline = summary.created ? '创建成功' : '已按最新配置同步邮箱池';
                showToast(`项目「${projectKey}」${headline}：新增 ${Number(summary.added_count || 0)} 个，移除 ${Number(summary.deleted_count || 0)} 个`, 'success');
                toggleProjectCreateForm(false);
                resetProjectCreateForm();
                await loadProjects();
            } catch (error) {
                showToast('创建项目失败，请稍后重试', 'error');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                }
            }
        }

        async function archiveProject(projectKey) {
            if (!projectKey) {
                return;
            }
            try {
                const response = await fetch(`/api/projects/${encodeURIComponent(projectKey)}/archive`, { method: 'POST' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '停用项目失败');
                    return;
                }
                showToast('项目已停用', 'success');
                await loadProjects();
            } catch (error) {
                showToast('停用项目失败，请稍后重试', 'error');
            }
        }

        async function restoreProject(projectKey) {
            if (!projectKey) {
                return;
            }
            try {
                const response = await fetch(`/api/projects/${encodeURIComponent(projectKey)}/restore`, { method: 'POST' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '恢复项目失败');
                    return;
                }
                showToast('项目已恢复', 'success');
                await loadProjects();
            } catch (error) {
                showToast('恢复项目失败，请稍后重试', 'error');
            }
        }

        async function deleteProject(projectKey) {
            if (!projectKey) {
                return;
            }
            const confirmed = await showConfirmModal(
                `确定删除项目「${projectKey}」吗？删除后项目的邮箱池关联将被移除，但不会删除邮箱账号本身；有邮箱正在领取中时无法删除。`,
                { title: '删除项目', confirmText: '删除' }
            );
            if (!confirmed) {
                return;
            }
            try {
                const response = await fetch(`/api/projects/${encodeURIComponent(projectKey)}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '删除项目失败');
                    return;
                }
                showToast(data.message || '项目已删除', 'success');
                await loadProjects();
            } catch (error) {
                showToast('删除项目失败，请稍后重试', 'error');
            }
        }
