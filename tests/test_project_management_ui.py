import importlib
import os
import pathlib
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _test_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.test_tmp')
    os.makedirs(_test_root, exist_ok=True)
    _temp_dir = os.path.join(_test_root, 'project_management_ui')
    os.makedirs(_temp_dir, exist_ok=True)
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


class ProjectManagementUiTestBase(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            web_outlook_app.init_db()
            web_outlook_app.set_setting(
                web_outlook_app.LOGIN_SESSION_VERSION_SETTING_KEY,
                web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION,
            )
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM settings WHERE key = ?', ('show_project_management',))
            db.execute('DELETE FROM project_account_events')
            db.execute('DELETE FROM project_accounts')
            db.execute('DELETE FROM project_group_scopes')
            db.execute('DELETE FROM projects')
            db.execute('DELETE FROM audit_logs')
            db.execute('DELETE FROM account_aliases')
            db.execute('DELETE FROM accounts')
            db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
            db.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['login_session_version'] = web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION

    def _insert_account(self, email_addr, group_id=1, status='active'):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', '', '', ?, '', ?, 'outlook', 'outlook', '', 993, '', 0)
                ''',
                (email_addr, group_id, status)
            )
            db.commit()
            return int(cursor.lastrowid)


class ProjectManagementSettingsTests(ProjectManagementUiTestBase):
    def tearDown(self):
        # 测试文件共用同一进程内数据库，清理本类写入的设置行，
        # 避免影响其他文件对默认值的断言
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                'DELETE FROM settings WHERE key IN (?, ?)',
                ('show_project_management', 'show_account_sort_order'),
            )
            db.commit()

    def test_settings_require_login(self):
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertTrue(payload['need_login'])

    def test_show_project_management_defaults_to_false(self):
        self._login()
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['show_project_management'], 'false')

    def test_show_project_management_roundtrips_true(self):
        self._login()
        update = self.client.put('/api/settings', json={'show_project_management': True})
        self.assertEqual(update.status_code, 200)
        self.assertTrue(update.get_json()['success'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('show_project_management'), 'true')

        refreshed = self.client.get('/api/settings')
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.get_json()['settings']['show_project_management'], 'true')

    def test_show_project_management_roundtrips_false(self):
        self._login()
        self.assertTrue(self.client.put('/api/settings', json={'show_project_management': True}).get_json()['success'])
        update = self.client.put('/api/settings', json={'show_project_management': False})
        self.assertEqual(update.status_code, 200)
        self.assertTrue(update.get_json()['success'])
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('show_project_management'), 'false')

    def test_show_project_management_rejects_invalid_value(self):
        self._login()
        self.assertTrue(self.client.put('/api/settings', json={'show_project_management': True}).get_json()['success'])

        update = self.client.put('/api/settings', json={'show_project_management': 'bogus'})
        self.assertEqual(update.status_code, 200)
        payload = update.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('项目管理入口展示必须是 true 或 false', payload['error'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('show_project_management'), 'true')

    def test_show_project_management_untouched_when_field_absent(self):
        self._login()
        self.assertTrue(self.client.put('/api/settings', json={'show_project_management': True}).get_json()['success'])

        update = self.client.put('/api/settings', json={'show_account_sort_order': True})
        self.assertEqual(update.status_code, 200)
        self.assertTrue(update.get_json()['success'])

        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting('show_project_management'), 'true')


class ProjectManagementFrontendStructureTests(unittest.TestCase):
    def _read(self, *parts):
        return pathlib.Path(ROOT_DIR, *parts).read_text(encoding='utf-8')

    def test_nav_entries_exist_and_default_hidden(self):
        layout_html = self._read('templates', 'partials', 'index', 'layout.html')

        self.assertIn('id="projectManagementBtn"', layout_html)
        self.assertIn('id="desktopProjectManagementBtn"', layout_html)
        self.assertIn('showProjectManagementModal()', layout_html)

        for element_id in ('projectManagementBtn', 'desktopProjectManagementBtn'):
            element_line = next(
                line for line in layout_html.splitlines() if f'id="{element_id}"' in line
            )
            self.assertIn('style="display: none;"', element_line)

    def test_settings_toggle_defaults_off(self):
        settings_html = self._read('templates', 'partials', 'index', 'dialogs-management.html')

        toggle_line = next(
            line for line in settings_html.splitlines() if 'id="settingsShowProjectManagement"' in line
        )
        self.assertIn('<input type="checkbox"', toggle_line)
        self.assertNotIn('checked', toggle_line)
        self.assertIn('项目管理入口', settings_html)

    def test_project_management_modal_structure(self):
        settings_html = self._read('templates', 'partials', 'index', 'dialogs-management.html')
        modal_markup = settings_html.split('id="projectManagementModal"', 1)[1].split('</div>\n    </div>', 1)[0]

        for element_id in (
            'projectSearchInput',
            'projectCreateForm',
            'projectKeyInput',
            'projectNameInput',
            'projectDescriptionInput',
            'projectGroupCheckboxList',
            'projectUseAliasEmail',
            'projectsTableBody',
        ):
            self.assertIn(f'id="{element_id}"', modal_markup)

        self.assertIn('project-mgmt-table', modal_markup)
        self.assertIn('.project-mgmt-badge--active', settings_html)
        self.assertIn('.project-mgmt-badge--archived', settings_html)

    def test_projects_js_registered_in_template_and_bootstrap(self):
        index_html = self._read('templates', 'index.html')
        bootstrap_py = self._read('outlook_web', 'segments', '01_bootstrap.py')

        self.assertIn("filename='js/index/13-projects.js'", index_html)
        self.assertIn("'js/index/13-projects.js',", bootstrap_py)

    def test_visibility_chain_wired_in_core_js(self):
        core_js = self._read('static', 'js', 'index', '01-core.js')

        self.assertIn('let showProjectManagement = false;', core_js)
        self.assertIn('function setShowProjectManagement(enabled)', core_js)
        self.assertIn('function shouldShowProjectManagement()', core_js)
        self.assertIn('applyProjectManagementVisibility();', core_js)
        self.assertIn(
            "setShowProjectManagement(String(data?.settings?.show_project_management) === 'true');",
            core_js,
        )

    def test_settings_js_loads_and_saves_toggle(self):
        settings_js = self._read('static', 'js', 'index', '07-settings.js')

        self.assertIn(
            "document.getElementById('settingsShowProjectManagement').checked = String(data.settings.show_project_management) === 'true';",
            settings_js,
        )
        self.assertIn(
            "const showProjectManagement = !!document.getElementById('settingsShowProjectManagement')?.checked;",
            settings_js,
        )
        self.assertIn('settings.show_project_management = showProjectManagement;', settings_js)
        self.assertIn('setShowProjectManagement(showProjectManagement);', settings_js)

    def test_projects_js_escapes_user_controlled_values(self):
        projects_js = self._read('static', 'js', 'index', '13-projects.js')

        self.assertIn('const pmState =', projects_js)
        self.assertIn('function applyProjectManagementVisibility()', projects_js)
        self.assertIn("typeof shouldShowProjectManagement === 'function'", projects_js)
        self.assertIn('escapeHtml(key)', projects_js)
        self.assertIn('data-key="${escapeHtml(key)}"', projects_js)
        self.assertIn('encodeURIComponent(projectKey)', projects_js)
        self.assertIn('showConfirmModal(', projects_js)
        self.assertIn("fetch('/api/projects')", projects_js)
        self.assertIn("fetch('/api/projects/start'", projects_js)
        self.assertIn('}/archive', projects_js)
        self.assertIn('}/restore', projects_js)
        self.assertIn("method: 'DELETE'", projects_js)


class WebProjectLifecycleTests(ProjectManagementUiTestBase):
    def test_project_routes_require_login(self):
        cases = (
            ('get', '/api/projects', None),
            ('post', '/api/projects/start', {'project_key': 'pm-auth'}),
            ('post', '/api/projects/pm-auth/archive', None),
            ('post', '/api/projects/pm-auth/restore', None),
            ('delete', '/api/projects/pm-auth', None),
        )
        for method, url, body in cases:
            response = getattr(self.client, method)(url, json=body)
            self.assertEqual(response.status_code, 401, f'{method.upper()} {url}')
            self.assertFalse(response.get_json()['success'])

    def test_web_project_lifecycle_flow(self):
        self._login()
        first_id = self._insert_account('pm-flow-1@example.com')
        self._insert_account('pm-flow-2@example.com')

        start = self.client.post(
            '/api/projects/start',
            json={'project_key': 'pm-flow', 'name': '流程项目', 'description': 'Web 界面冒烟'},
        )
        self.assertEqual(start.status_code, 200)
        self.assertTrue(start.get_json()['success'])

        listing = self.client.get('/api/projects')
        self.assertEqual(listing.status_code, 200)
        projects = listing.get_json()['data']['projects']
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project['project_key'], 'pm-flow')
        self.assertEqual(project['status'], 'active')
        self.assertEqual(project['total_count'], 2)
        self.assertEqual(project['to_claim_count'], 2)
        self.assertEqual(project['claiming_count'], 0)
        self.assertEqual(project['done_count'], 0)
        self.assertEqual(project['failed_count'], 0)

        archive = self.client.post('/api/projects/pm-flow/archive')
        self.assertEqual(archive.status_code, 200)
        self.assertTrue(archive.get_json()['success'])
        self.assertEqual(archive.get_json()['data']['project']['status'], 'archived')

        claim_blocked = self.client.post(
            '/api/projects/pm-flow/claim-random',
            json={'caller_id': 'web-ui-test', 'task_id': 'web-ui-task'},
        )
        self.assertEqual(claim_blocked.status_code, 400)
        self.assertIn('项目已停用', claim_blocked.get_json()['error'])

        restore = self.client.post('/api/projects/pm-flow/restore')
        self.assertEqual(restore.status_code, 200)
        self.assertTrue(restore.get_json()['success'])
        self.assertEqual(restore.get_json()['data']['project']['status'], 'active')

        claim = self.client.post(
            '/api/projects/pm-flow/claim-random',
            json={'caller_id': 'web-ui-test', 'task_id': 'web-ui-task'},
        )
        self.assertEqual(claim.status_code, 200)
        claimed = claim.get_json()['data']
        self.assertTrue(claimed['claim_token'].startswith('pclm_'))

        listing = self.client.get('/api/projects')
        project = listing.get_json()['data']['projects'][0]
        self.assertEqual(project['to_claim_count'], 1)
        self.assertEqual(project['claiming_count'], 1)

        delete_blocked = self.client.delete('/api/projects/pm-flow')
        self.assertEqual(delete_blocked.status_code, 400)
        self.assertIn('正在领取中', delete_blocked.get_json()['error'])

        release = self.client.post(
            '/api/projects/pm-flow/release',
            json={'account_id': claimed['account_id'], 'claim_token': claimed['claim_token']},
        )
        self.assertEqual(release.status_code, 200)
        self.assertTrue(release.get_json()['success'])

        delete = self.client.delete('/api/projects/pm-flow')
        self.assertEqual(delete.status_code, 200)
        payload = delete.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['deleted_project']['project_key'], 'pm-flow')

        listing = self.client.get('/api/projects')
        self.assertEqual(listing.get_json()['data']['projects'], [])

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) AS count FROM accounts WHERE id IN (?, ?)',
                (first_id, first_id + 1),
            ).fetchone()
            self.assertEqual(int(row['count']), 2)

    def test_web_project_operations_log_audit(self):
        self._login()
        self._insert_account('pm-audit@example.com')

        self.assertTrue(self.client.post('/api/projects/start', json={'project_key': 'pm-audit'}).get_json()['success'])
        self.assertTrue(self.client.post('/api/projects/pm-audit/archive').get_json()['success'])
        self.assertTrue(self.client.post('/api/projects/pm-audit/restore').get_json()['success'])
        self.assertTrue(self.client.delete('/api/projects/pm-audit').get_json()['success'])

        with self.app.app_context():
            rows = web_outlook_app.get_db().execute(
                "SELECT action, details FROM audit_logs WHERE resource_type = 'project' AND resource_id = 'pm-audit' ORDER BY id ASC"
            ).fetchall()

        actions = [row['action'] for row in rows]
        self.assertEqual(actions, ['start', 'archive', 'restore', 'delete'])
        self.assertIn('Web 端停用项目', rows[1]['details'])
        self.assertIn('Web 端恢复项目', rows[2]['details'])
        self.assertIn('Web 端删除项目', rows[3]['details'])


if __name__ == '__main__':
    unittest.main()
