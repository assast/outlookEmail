(function () {
  const CONFIG_KEY = 'outlookEmailPasswordConfig';
  const SESSION_PASSWORD_KEY = 'outlookEmailSessionPassword';
  const SIDE_PANEL_PATH_KEY = 'outlookEmailSidePanelPath';
  const SELECTED_MAIL_GROUP_KEY = 'outlookEmailSelectedMailGroupId';

  const ExtensionStorage = {
    async getConfig() {
      const data = await chrome.storage.local.get(CONFIG_KEY);
      const config = data[CONFIG_KEY] || {};
      if (!config.password && chrome.storage.session) {
        const sessionData = await chrome.storage.session.get(SESSION_PASSWORD_KEY);
        config.password = sessionData[SESSION_PASSWORD_KEY] || '';
      }
      return config;
    },

    async setConfig(config) {
      await chrome.storage.local.set({
        [CONFIG_KEY]: {
          serverUrl: config.serverUrl || '',
          password: config.rememberPassword ? (config.password || '') : '',
          rememberPassword: config.rememberPassword === true,
        },
      });
      if (chrome.storage.session) {
        if (config.password) {
          await chrome.storage.session.set({ [SESSION_PASSWORD_KEY]: config.password });
        } else {
          await chrome.storage.session.remove(SESSION_PASSWORD_KEY);
        }
      }
    },

    async clearConfig() {
      await chrome.storage.local.remove([CONFIG_KEY, SELECTED_MAIL_GROUP_KEY]);
      if (chrome.storage.session) {
        await chrome.storage.session.remove(SESSION_PASSWORD_KEY);
      }
    },

    async setSidePanelPath(path) {
      await chrome.storage.local.set({ [SIDE_PANEL_PATH_KEY]: path || '/' });
    },

    async getSidePanelPath() {
      const data = await chrome.storage.local.get(SIDE_PANEL_PATH_KEY);
      return data[SIDE_PANEL_PATH_KEY] || '/';
    },

    async setSelectedMailGroupId(groupId) {
      await chrome.storage.local.set({ [SELECTED_MAIL_GROUP_KEY]: String(groupId || '') });
    },

    async getSelectedMailGroupId() {
      const data = await chrome.storage.local.get(SELECTED_MAIL_GROUP_KEY);
      return data[SELECTED_MAIL_GROUP_KEY] || '';
    },
  };

  window.ExtensionStorage = ExtensionStorage;
})();
