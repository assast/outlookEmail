import pathlib
import unittest


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


class AccountPanelHeaderLayoutTests(unittest.TestCase):
    """邮箱面板头部布局：4 按钮（刷新/授权/导入/⋯）+ 更多操作下拉菜单"""

    def _read(self, *parts):
        return pathlib.Path(ROOT_DIR, *parts).read_text(encoding='utf-8')

    def test_dynamic_render_uses_four_button_layout(self):
        groups_js = self._read('static', 'js', 'index', '02-groups.js')

        # 两个分支（普通分组/临时邮箱）都渲染 [刷新][主操作][导入][⋯]
        self.assertEqual(groups_js.count('${renderAccountMoreDropdown()}'), 2)
        self.assertIn('id="refreshAccountListBtn"', groups_js)

        # 批量选择/管理标签/极简展示不再作为独立头部按钮渲染
        self.assertNotIn('renderAccountSelectionModeButton', groups_js)
        self.assertNotIn('renderAccountMinimalModeButton', groups_js)
        self.assertNotIn('id="accountSelectionModeBtn"', groups_js)
        self.assertNotIn('id="accountMinimalBtn"', groups_js)

    def test_more_dropdown_menu_items(self):
        groups_js = self._read('static', 'js', 'index', '02-groups.js')

        self.assertIn('navbar-dropdown account-more-dropdown', groups_js)
        self.assertIn('id="accountMoreBtn"', groups_js)
        self.assertIn('account-menu-item--selection', groups_js)
        self.assertIn('account-menu-item--tags', groups_js)
        self.assertIn('account-menu-item--minimal', groups_js)
        self.assertIn('toggleAccountSelectionMode(); closeAccountMoreMenu()', groups_js)
        self.assertIn('toggleAccountMinimalMode(); closeAccountMoreMenu()', groups_js)
        self.assertIn('showTagManagementModal(); closeAccountMoreMenu()', groups_js)

    def test_static_template_matches_dynamic_layout(self):
        layout_html = self._read('templates', 'partials', 'index', 'layout.html')

        self.assertIn('id="refreshAccountListBtn"', layout_html)
        self.assertIn('id="accountMoreBtn"', layout_html)
        self.assertIn('account-more-dropdown', layout_html)
        self.assertIn('account-menu-item--selection', layout_html)
        self.assertIn('account-menu-item--minimal', layout_html)
        self.assertIn('account-menu-item--tags', layout_html)

        # 旧的独立按钮与分组包裹已移除
        self.assertNotIn('accountSelectionModeBtn', layout_html)
        self.assertNotIn('accountMinimalBtn', layout_html)
        self.assertNotIn('panel-action-subgroup', layout_html)
        self.assertNotIn('panel-action-separator', layout_html)

    def test_active_state_sync_chain(self):
        core_js = self._read('static', 'js', 'index', '01-core.js')
        batch_js = self._read('static', 'js', 'index', '10-batch-actions.js')

        # 圆点同步函数存在且被状态初始化/切换调用
        self.assertIn('function syncAccountMoreActiveDot()', core_js)
        self.assertIn('has-active', core_js)
        self.assertIn('syncAccountMoreActiveDot();', core_js)

        # 批量选择菜单项同步
        self.assertIn('function syncAccountSelectionMenuItem()', batch_js)
        self.assertIn("querySelectorAll('.account-menu-item--selection')", batch_js)
        self.assertIn('syncAccountMoreActiveDot', batch_js)

        # 极简展示菜单项同步
        self.assertIn("querySelectorAll('.account-menu-item--minimal')", core_js)

        # updateCurrentGroupHeader 不再隐藏刷新按钮（刷新始终可见）
        self.assertNotIn('refreshBtn.style.display', core_js)

    def test_css_dot_and_menu_item_styles(self):
        panel_css = self._read('static', 'css', 'index', '04-account-panel.css')

        self.assertIn('.account-more-btn.has-active::after', panel_css)
        self.assertIn('.account-menu-item.active', panel_css)
        self.assertIn('.account-menu-item-check', panel_css)
        # 点击展开：禁用 hover 展开
        self.assertIn('.account-more-dropdown:hover .navbar-dropdown-menu', panel_css)
        # 旧的独立按钮激活样式与分组包裹样式已删除
        self.assertNotIn('.account-selection-mode-btn.active', panel_css)
        self.assertNotIn('.panel-action-subgroup', panel_css)


if __name__ == '__main__':
    unittest.main()
