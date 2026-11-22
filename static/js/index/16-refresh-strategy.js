const refreshStrategyModeLabels = {expiry: '按到期时间刷新', legacy: '旧周期全量刷新', disabled: '停用自动刷新'};

async function refreshStrategyRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || data.message || '读取刷新策略失败');
    return data;
}

function isDedicatedRefreshStrategyUI() {
    return document.getElementById('refreshStrategyManagementView')?.dataset.refreshStrategyWorkspace === 'true';
}

function setRefreshStrategyLocation(replace = true) {
    if (!isDedicatedRefreshStrategyUI() || typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.pathname = '/refresh-strategy';
    window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}

function getRefreshStrategyMode() {
    return document.querySelector('input[name="refreshStrategyMode"]:checked')?.value || 'expiry';
}

function syncRefreshStrategyModeUI() {
    const mode = getRefreshStrategyMode();
    const expirySettings = document.getElementById('refreshExpirySettings');
    const legacySettings = document.getElementById('refreshLegacySettingsSummary');
    if (expirySettings) expirySettings.hidden = mode !== 'expiry';
    if (legacySettings) legacySettings.hidden = mode !== 'legacy';
}

async function refreshRefreshStrategySettings() {
    try {
        const data = await refreshStrategyRequest('/api/refresh-strategy');
        const strategy = data.strategy;
        document.querySelector(`input[name="refreshStrategyMode"][value="${strategy.mode}"]`).checked = true;
        const legacyModeInput = document.querySelector('input[name="refreshStrategyMode"][value="legacy"]');
        const legacyConfigButton = document.querySelector('#refreshLegacySettingsSummary button');
        const legacyModeDescription = document.getElementById('refreshLegacyModeDescription');
        legacyModeInput.disabled = !strategy.legacy_available;
        legacyConfigButton.disabled = !strategy.legacy_available;
        document.getElementById('refreshStrategyExpiryWindowDays').value = strategy.expiry_window_days;
        document.getElementById('refreshStrategyDefaultLifetimeDays').value = strategy.default_lifetime_days;
        document.getElementById('refreshStrategyIncludeMissingAnchor').checked = strategy.include_missing_anchor;
        const legacyDescription = document.getElementById('refreshLegacySettingsDescription');
        if (!strategy.legacy_available) {
            const explanation = '旧刷新策略已关闭，不能再次选择或启用；旧 Cron 与周期值仍保留。';
            legacyModeDescription.textContent = explanation;
            legacyDescription.textContent = explanation;
        } else if (strategy.legacy_use_cron) {
            legacyModeDescription.textContent = '按通用设置中的旧 Cron 配置刷新全部 Outlook 账号，可能错过微软的轮换窗口。';
            legacyDescription.textContent = `旧版 Cron 当前为“${strategy.legacy_cron}”；每次触发都会全量刷新 Outlook 账号。`;
        } else {
            legacyModeDescription.textContent = '按通用设置中的旧周期配置刷新全部 Outlook 账号，可能错过微软的轮换窗口。';
            legacyDescription.textContent = `旧版全量刷新周期为 ${strategy.legacy_interval_days} 天；其余旧字段和值保持不变。`;
        }
        syncRefreshStrategyModeUI();
        return strategy;
    } catch (error) {
        showToast(error.message || '读取刷新策略失败', 'error');
        return null;
    }
}

async function loadLegacyRefreshStrategyStatus() {
    const status = document.getElementById('legacyRefreshStrategyStatus');
    if (!status) return;
    try {
        const {strategy} = await refreshStrategyRequest('/api/refresh-strategy');
        const modeLabel = refreshStrategyModeLabels[strategy.mode] || '未知';
        status.textContent = strategy.legacy_retired
            ? `当前生效模式：${modeLabel}。旧刷新策略已永久关闭，不能再次开启。`
            : strategy.mode === 'legacy'
            ? `当前生效模式：${modeLabel}。本区旧启停、Cron 和周期配置正在控制自动刷新。`
            : `当前生效模式：${modeLabel}。旧周期字段保留但只读；选择新模式并保存后，旧策略会永久关闭。`;
        const legacyControls = document.querySelectorAll(
            '#settingsRefreshSection #enableScheduledRefresh, '
            + '#settingsRefreshSection input[name="refreshStrategy"], '
            + '#settingsRefreshSection #refreshIntervalDays, '
            + '#settingsRefreshSection #refreshCron, '
            + '#settingsRefreshSection #cronStrategyContainer button'
        );
        legacyControls.forEach(control => {
            control.disabled = strategy.mode !== 'legacy' || !strategy.legacy_available;
        });
    } catch (error) {
        status.textContent = '当前生效模式由独立刷新策略页面管理。';
    }
}

async function saveRefreshStrategySettings(button) {
    if (button?.disabled) return;
    if (button) button.disabled = true;
    const status = document.getElementById('refreshStrategyStatus');
    try {
        const expiryWindow = Number.parseInt(document.getElementById('refreshStrategyExpiryWindowDays').value, 10);
        const defaultLifetime = Number.parseInt(document.getElementById('refreshStrategyDefaultLifetimeDays').value, 10);
        if (!Number.isInteger(expiryWindow) || expiryWindow < 1 || expiryWindow > 3650) {
            throw new Error('提前刷新天数必须在 1-3650 天之间');
        }
        if (!Number.isInteger(defaultLifetime) || defaultLifetime < 1 || defaultLifetime > 3650) {
            throw new Error('默认 RT 寿命必须在 1-3650 天之间');
        }
        await refreshStrategyRequest('/api/refresh-strategy', {
            method: 'PUT',
            body: JSON.stringify({
                mode: getRefreshStrategyMode(),
                expiry_window_days: expiryWindow,
                default_lifetime_days: defaultLifetime,
                include_missing_anchor: document.getElementById('refreshStrategyIncludeMissingAnchor').checked,
            }),
        });
        if (status) status.textContent = '刷新策略已保存并立即生效。';
        await refreshRefreshStrategySettings();
        await loadLegacyRefreshStrategyStatus();
        showToast('刷新策略已保存', 'success');
    } catch (error) {
        if (status) status.textContent = error.message || '保存刷新策略失败';
        showToast(error.message || '保存刷新策略失败', 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

async function showRefreshStrategyManagement(updateLocation = true) {
    closeAllModals();
    if (typeof closeNavbarActionsMenu === 'function') closeNavbarActionsMenu();
    if (typeof closeMobilePanels === 'function') closeMobilePanels();
    if (typeof hideForwardingManagement === 'function') hideForwardingManagement(false);
    document.getElementById('refreshStrategyManagementView').hidden = false;
    document.documentElement.classList.add('refresh-strategy-workspace-open');
    if (updateLocation) setRefreshStrategyLocation(window.location.pathname === '/refresh-strategy');
    await refreshRefreshStrategySettings();
}

function hideRefreshStrategyManagement(updateLocation = true) {
    document.getElementById('refreshStrategyManagementView').hidden = true;
    document.documentElement.classList.remove('refresh-strategy-workspace-open');
    if (updateLocation) {
        const url = new URL(window.location.href);
        url.pathname = '/';
        [...url.searchParams.keys()].filter(key => key.startsWith('refresh_strategy_')).forEach(key => url.searchParams.delete(key));
        window.history.pushState({}, '', url);
    }
}

async function openLegacyRefreshSettings() {
    hideRefreshStrategyManagement();
    await showSettingsModal();
    setTimeout(() => scrollSettingsSection('settingsRefreshSection'), 0);
}

document.addEventListener('DOMContentLoaded', () => {
    const restoreWorkspace = () => {
        if (window.location.pathname === '/refresh-strategy') showRefreshStrategyManagement(false);
        else hideRefreshStrategyManagement(false);
    };
    window.addEventListener('popstate', restoreWorkspace);
    if (window.location.pathname === '/refresh-strategy') restoreWorkspace();
});
