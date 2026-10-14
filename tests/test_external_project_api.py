import importlib
import os
import pathlib
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _test_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.test_tmp')
    os.makedirs(_test_root, exist_ok=True)
    _temp_dir = os.path.join(_test_root, 'external_project')
    os.makedirs(_temp_dir, exist_ok=True)
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]

READ_ENDPOINTS = (
    'api_external_get_projects',
    'api_external_get_project',
    'api_external_get_project_accounts',
)
WRITE_ENDPOINTS = (
    'api_external_start_project',
    'api_external_claim_project_account',
    'api_external_complete_project_success',
    'api_external_complete_project_failed',
    'api_external_release_project_account',
    'api_external_reset_project_failed',
    'api_external_remove_project_account',
    'api_external_restore_project_account',
    'api_external_archive_project',
    'api_external_restore_project',
    'api_external_delete_project',
)


def clear_external_project_fixtures(db):
    db.execute('DELETE FROM project_account_events')
    db.execute('DELETE FROM project_accounts')
    db.execute('DELETE FROM project_group_scopes')
    db.execute('DELETE FROM projects')
    db.execute('DELETE FROM audit_logs')
    db.execute('DELETE FROM account_aliases')
    db.execute('DELETE FROM account_tags')
    db.execute('DELETE FROM accounts')
    db.execute("DELETE FROM groups WHERE name NOT IN ('默认分组', '临时邮箱')")
    db.commit()


class ExternalProjectTestBase(unittest.TestCase):
    API_KEY = 'test-external-project-key'

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            clear_external_project_fixtures(db)
            self.assertTrue(web_outlook_app.set_setting('external_api_key', self.API_KEY))

    def _headers(self):
        return {'X-API-Key': self.API_KEY}

    def _set_permission(self, value):
        with self.app.app_context():
            if value is None:
                db = web_outlook_app.get_db()
                db.execute("DELETE FROM settings WHERE key = 'external_api_key_permission'")
                db.commit()
            else:
                self.assertTrue(web_outlook_app.set_setting('external_api_key_permission', value))

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

    def _delete_account(self, email_addr):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM accounts WHERE email = ?', (email_addr,))
            db.commit()

    def _start_project_via_api(self, project_key, **payload):
        body = {'project_key': project_key}
        body.update(payload)
        return self.client.post(
            '/api/external/projects/start',
            headers=self._headers(),
            json=body,
        )

    def _claim_via_api(self, project_key, caller_id='worker-1', task_id='task-1', lease_seconds=600):
        return self.client.post(
            f'/api/external/projects/{project_key}/claim-random',
            headers=self._headers(),
            json={
                'caller_id': caller_id,
                'task_id': task_id,
                'lease_seconds': lease_seconds,
            },
        )

    def _post_project_action(self, project_key, action, body):
        return self.client.post(
            f'/api/external/projects/{project_key}/{action}',
            headers=self._headers(),
            json=body,
        )

    def _project_account_status(self, project_key, account_id):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            row = db.execute(
                '''
                SELECT pa.status
                FROM project_accounts pa
                JOIN projects p ON p.id = pa.project_id
                WHERE p.project_key = ? AND pa.account_id = ?
                ''',
                (project_key, account_id)
            ).fetchone()
            return row['status'] if row else None

    def _last_audit_row(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            return db.execute(
                'SELECT action, resource_type, resource_id, details FROM audit_logs ORDER BY id DESC LIMIT 1'
            ).fetchone()


class ExternalProjectAuthTests(ExternalProjectTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readonly')
        self._insert_account('peek@outlook.com')
        with self.app.app_context():
            web_outlook_app.start_project('readonly-peek')

    def test_readonly_can_query_project_endpoints(self):
        for path in ('/api/external/projects', '/api/external/projects/readonly-peek'):
            response = self.client.get(path, headers=self._headers())
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.get_json()['success'], path)

        response = self.client.get(
            '/api/external/projects/readonly-peek/accounts',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['data']['accounts'][0]['project_status'], 'toClaim')

    def test_missing_api_key_returns_401_before_permission_check(self):
        response = self.client.post(
            '/api/external/projects/readonly-peek/claim-random',
            json={'caller_id': 'w', 'task_id': 't'},
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['success'])

    def test_invalid_api_key_returns_401(self):
        response = self.client.get('/api/external/projects', headers={'X-API-Key': 'wrong-key'})
        self.assertEqual(response.status_code, 401)

    def test_readonly_permission_rejects_all_write_actions_with_403(self):
        cases = [
            ('/api/external/projects/start', {'project_key': 'blocked'}),
            ('/api/external/projects/readonly-peek/claim-random', {'caller_id': 'w', 'task_id': 't'}),
            ('/api/external/projects/readonly-peek/complete-success', {'account_id': 1, 'claim_token': 'x'}),
            ('/api/external/projects/readonly-peek/complete-failed', {'account_id': 1, 'claim_token': 'x'}),
            ('/api/external/projects/readonly-peek/release', {'account_id': 1, 'claim_token': 'x'}),
            ('/api/external/projects/readonly-peek/reset-failed', {'account_id': 1}),
            ('/api/external/projects/readonly-peek/remove-account', {'account_id': 1}),
            ('/api/external/projects/readonly-peek/restore-account', {'account_id': 1}),
            ('/api/external/projects/readonly-peek/archive', {}),
            ('/api/external/projects/readonly-peek/restore', {}),
        ]
        for path, body in cases:
            response = self.client.post(path, headers=self._headers(), json=body)
            self.assertEqual(response.status_code, 403, path)
            payload = response.get_json()
            self.assertFalse(payload['success'], path)
            self.assertIn('readonly', payload['error'])
            self.assertIn('readwrite', payload['error'])

        response = self.client.delete(
            '/api/external/projects/readonly-peek',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()['success'])

    def test_unset_permission_defaults_to_readonly(self):
        self._set_permission(None)
        response = self._claim_via_api('readonly-peek')
        self.assertEqual(response.status_code, 403)

    def test_routes_marked_with_decorators(self):
        for endpoint in READ_ENDPOINTS:
            view = self.app.view_functions[endpoint]
            self.assertTrue(getattr(view, '_requires_api_key', False), endpoint)
            self.assertFalse(getattr(view, '_requires_api_key_write', False), endpoint)
        for endpoint in WRITE_ENDPOINTS:
            view = self.app.view_functions[endpoint]
            self.assertTrue(getattr(view, '_requires_api_key', False), endpoint)
            self.assertTrue(getattr(view, '_requires_api_key_write', False), endpoint)

    def test_web_project_routes_still_require_login(self):
        response = self.client.get('/api/projects')
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            '/api/projects/readonly-peek/claim-random',
            json={'caller_id': 'w', 'task_id': 't'},
        )
        self.assertEqual(response.status_code, 401)


class ExternalProjectReadRouteTests(ExternalProjectTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readonly')
        self.account_one = self._insert_account('one@outlook.com')
        self.account_two = self._insert_account('two@outlook.com')
        with self.app.app_context():
            web_outlook_app.start_project('read-channel', name='读取渠道')

    def test_list_projects_returns_counts(self):
        response = self.client.get('/api/external/projects', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        project = payload['data']['projects'][0]
        self.assertEqual(project['project_key'], 'read-channel')
        self.assertEqual(project['total_count'], 2)
        self.assertEqual(project['to_claim_count'], 2)
        self.assertEqual(project['name'], '读取渠道')

    def test_project_detail_and_missing(self):
        response = self.client.get('/api/external/projects/read-channel', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['project']['project_key'], 'read-channel')

        response = self.client.get('/api/external/projects/no-such', headers=self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])

    def test_project_accounts_with_status_filter(self):
        response = self.client.get(
            '/api/external/projects/read-channel/accounts?status=toClaim',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['total'], 2)
        emails = {item['email'] for item in payload['data']['accounts']}
        self.assertEqual(emails, {'one@outlook.com', 'two@outlook.com'})

        response = self.client.get(
            '/api/external/projects/read-channel/accounts?status=done',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 0)

    def test_project_accounts_with_keyword_filter(self):
        response = self.client.get(
            '/api/external/projects/read-channel/accounts?keyword=one@',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['data']['accounts'][0]['email'], 'one@outlook.com')

    def test_project_accounts_missing_project_returns_404(self):
        response = self.client.get(
            '/api/external/projects/no-such/accounts',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])


class ExternalProjectClaimFlowTests(ExternalProjectTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readwrite')
        self.account_one = self._insert_account('flow-one@outlook.com')
        self.account_two = self._insert_account('flow-two@outlook.com')

    def _start(self):
        return self._start_project_via_api('reg-channel')

    def test_full_claim_and_complete_success_flow(self):
        start_response = self._start()
        self.assertEqual(start_response.status_code, 200)
        start_payload = start_response.get_json()
        self.assertTrue(start_payload['success'])
        self.assertEqual(start_payload['message'], '项目已启动')
        self.assertTrue(start_payload['data']['created'])
        self.assertEqual(start_payload['data']['added_count'], 2)
        self.assertEqual(start_payload['data']['total_count'], 2)

        claimed = []
        for index in range(2):
            response = self._claim_via_api('reg-channel', caller_id=f'worker-{index}', task_id=f'task-{index}')
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload['success'])
            account = payload['data']
            self.assertIn(account['email'], {'flow-one@outlook.com', 'flow-two@outlook.com'})
            self.assertNotIn(account['email'], claimed)
            claimed.append(account['email'])

            self.assertTrue(account['claim_token'].startswith('pclm_'))
            self.assertTrue(account['lease_expires_at'])

            complete = self._post_project_action('reg-channel', 'complete-success', {
                'account_id': account['account_id'],
                'claim_token': account['claim_token'],
                'caller_id': f'worker-{index}',
                'detail': '注册成功',
            })
            self.assertEqual(complete.status_code, 200)
            self.assertTrue(complete.get_json()['success'])
            self.assertEqual(
                self._project_account_status('reg-channel', account['account_id']),
                'done',
            )

        exhausted = self._claim_via_api('reg-channel')
        self.assertEqual(exhausted.status_code, 200)
        payload = exhausted.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], '没有可领取的项目邮箱')

    def test_claim_missing_project_returns_404(self):
        response = self._claim_via_api('no-such-project')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()['success'])

    def test_claim_requires_caller_and_task_ids(self):
        self._start()
        response = self.client.post(
            '/api/external/projects/reg-channel/claim-random',
            headers=self._headers(),
            json={'caller_id': '', 'task_id': 'task-1'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('caller_id', response.get_json()['error'])

        response = self.client.post(
            '/api/external/projects/reg-channel/claim-random',
            headers=self._headers(),
            json={'caller_id': 'worker-1', 'task_id': ''},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('task_id', response.get_json()['error'])

    def test_release_returns_account_to_pool(self):
        self._delete_account('flow-two@outlook.com')
        self._start()
        claim = self._claim_via_api('reg-channel').get_json()['data']
        released = self._post_project_action('reg-channel', 'release', {
            'account_id': claim['account_id'],
            'claim_token': claim['claim_token'],
        })
        self.assertEqual(released.status_code, 200)
        self.assertTrue(released.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', claim['account_id']), 'toClaim')

        again = self._claim_via_api('reg-channel').get_json()['data']
        self.assertEqual(again['account_id'], claim['account_id'])

        pool = self.client.get(
            '/api/external/projects/reg-channel/accounts',
            headers=self._headers(),
        ).get_json()['data']['accounts']
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]['claim_count'], 2)

    def test_complete_failed_then_reset_failed(self):
        self._start()
        claim = self._claim_via_api('reg-channel').get_json()['data']
        failed = self._post_project_action('reg-channel', 'complete-failed', {
            'account_id': claim['account_id'],
            'claim_token': claim['claim_token'],
            'detail': '验证码失败',
        })
        self.assertEqual(failed.status_code, 200)
        self.assertTrue(failed.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', claim['account_id']), 'failed')

        reset = self._post_project_action('reg-channel', 'reset-failed', {
            'account_id': claim['account_id'],
        })
        self.assertEqual(reset.status_code, 200)
        self.assertTrue(reset.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', claim['account_id']), 'toClaim')

    def test_complete_with_wrong_claim_token_rejected(self):
        self._start()
        claim = self._claim_via_api('reg-channel').get_json()['data']
        response = self._post_project_action('reg-channel', 'complete-success', {
            'account_id': claim['account_id'],
            'claim_token': 'pclm_wrong-token',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', claim['account_id']), 'claiming')

    def test_complete_with_invalid_account_id_rejected(self):
        self._start()
        claim = self._claim_via_api('reg-channel').get_json()['data']

        response = self._post_project_action('reg-channel', 'complete-success', {
            'claim_token': claim['claim_token'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('缺少', response.get_json()['error'])

        response = self._post_project_action('reg-channel', 'complete-success', {
            'account_id': 'not-a-number',
            'claim_token': claim['claim_token'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('account_id', response.get_json()['error'])

    def test_remove_and_restore_account(self):
        self._start()
        removed = self._post_project_action('reg-channel', 'remove-account', {
            'account_id': self.account_one,
            'detail': '账号被封',
        })
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', self.account_one), 'removed')

        restored = self._post_project_action('reg-channel', 'restore-account', {
            'account_id': self.account_one,
        })
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(restored.get_json()['success'])
        self.assertEqual(self._project_account_status('reg-channel', self.account_one), 'toClaim')

    def test_claim_blocked_while_claiming_in_other_project(self):
        self._delete_account('flow-two@outlook.com')
        self._start_project_via_api('project-a')
        self._start_project_via_api('project-b')

        claim = self._claim_via_api('project-a').get_json()['data']
        other = self._claim_via_api('project-b', caller_id='worker-b', task_id='task-b')
        payload = other.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], '没有可领取的项目邮箱')

        self._post_project_action('project-a', 'release', {
            'account_id': claim['account_id'],
            'claim_token': claim['claim_token'],
        })
        retry = self._claim_via_api('project-b', caller_id='worker-b', task_id='task-b').get_json()['data']
        self.assertEqual(retry['account_id'], claim['account_id'])

    def test_claim_writes_audit_log(self):
        self._start()
        self._claim_via_api('reg-channel', caller_id='auditor', task_id='audit-task')
        audit = self._last_audit_row()
        self.assertIsNotNone(audit)
        self.assertEqual(audit['action'], 'claim')
        self.assertEqual(audit['resource_type'], 'project')
        self.assertEqual(audit['resource_id'], 'reg-channel')
        self.assertIn('对外 API', audit['details'])
        self.assertIn('auditor', audit['details'])

    def test_complete_success_writes_audit_log(self):
        self._start()
        claim = self._claim_via_api('reg-channel').get_json()['data']
        self._post_project_action('reg-channel', 'complete-success', {
            'account_id': claim['account_id'],
            'claim_token': claim['claim_token'],
            'caller_id': 'worker-1',
        })
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'complete')
        self.assertEqual(audit['resource_type'], 'project')
        self.assertIn('对外 API', audit['details'])
        self.assertIn(str(claim['account_id']), audit['details'])


class ExternalProjectStartTests(ExternalProjectTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readwrite')

    def test_restart_syncs_scope_without_recreating(self):
        self._insert_account('sync-one@outlook.com')
        first = self._start_project_via_api('sync-channel')
        self.assertTrue(first.get_json()['data']['created'])

        self._insert_account('sync-two@outlook.com')
        second = self._start_project_via_api('sync-channel')
        payload = second.get_json()
        self.assertTrue(payload['success'])
        self.assertFalse(payload['data']['created'])
        self.assertEqual(payload['data']['added_count'], 1)
        self.assertEqual(payload['data']['total_count'], 2)

    def test_start_with_group_scope_limits_pool(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            cursor = db.execute(
                "INSERT INTO groups (name, description, color, sort_order, is_system) VALUES ('对外项目分组', '', '#123456', 999, 0)"
            )
            db.commit()
            group_id = int(cursor.lastrowid)

        self._insert_account('inside@outlook.com', group_id=group_id)
        self._insert_account('outside@outlook.com', group_id=1)

        response = self._start_project_via_api('scoped-channel', group_ids=[group_id])
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['added_count'], 1)
        self.assertEqual(payload['data']['total_count'], 1)
        self.assertEqual(payload['data']['group_ids'], [group_id])

        accounts = self.client.get(
            '/api/external/projects/scoped-channel/accounts',
            headers=self._headers(),
        ).get_json()['data']['accounts']
        self.assertEqual([item['email'] for item in accounts], ['inside@outlook.com'])

    def test_start_missing_project_key_returns_400(self):
        response = self._start_project_via_api('')
        self.assertEqual(response.status_code, 400)
        self.assertIn('project_key', response.get_json()['error'])

    def test_start_writes_audit_log(self):
        self._insert_account('audit@outlook.com')
        self._start_project_via_api('audit-channel')
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'start')
        self.assertEqual(audit['resource_type'], 'project')
        self.assertEqual(audit['resource_id'], 'audit-channel')
        self.assertIn('对外 API', audit['details'])


class ExternalProjectLifecycleTests(ExternalProjectTestBase):
    def setUp(self):
        super().setUp()
        self._set_permission('readwrite')
        self.account_id = self._insert_account('lifecycle@outlook.com')
        self._start_project_via_api('lifecycle-channel', name='生命周期')

    def _project_status(self, project_key='lifecycle-channel'):
        response = self.client.get(
            f'/api/external/projects/{project_key}',
            headers=self._headers(),
        )
        return response.get_json()['data']['project']['status']

    def test_archive_and_restore_toggle_status(self):
        archive = self._post_project_action('lifecycle-channel', 'archive', {})
        self.assertEqual(archive.status_code, 200)
        payload = archive.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['project']['status'], 'archived')
        self.assertEqual(self._project_status(), 'archived')

        restore = self._post_project_action('lifecycle-channel', 'restore', {})
        self.assertEqual(restore.status_code, 200)
        self.assertEqual(restore.get_json()['data']['project']['status'], 'active')
        self.assertEqual(self._project_status(), 'active')

    def test_archived_project_blocks_claim_with_400(self):
        self._post_project_action('lifecycle-channel', 'archive', {})

        response = self._claim_via_api('lifecycle-channel')
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('停用', payload['error'])

    def test_start_on_archived_project_keeps_archived(self):
        self._post_project_action('lifecycle-channel', 'archive', {})

        response = self._start_project_via_api('lifecycle-channel')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(self._project_status(), 'archived')

    def test_restore_reenables_claim(self):
        self._post_project_action('lifecycle-channel', 'archive', {})
        self._post_project_action('lifecycle-channel', 'restore', {})

        response = self._claim_via_api('lifecycle-channel')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])

    def test_archive_missing_project_returns_404(self):
        response = self._post_project_action('no-such-project', 'archive', {})
        self.assertEqual(response.status_code, 404)
        response = self._post_project_action('no-such-project', 'restore', {})
        self.assertEqual(response.status_code, 404)

    def test_archive_writes_audit_log(self):
        self._post_project_action('lifecycle-channel', 'archive', {})
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'archive')
        self.assertEqual(audit['resource_type'], 'project')
        self.assertEqual(audit['resource_id'], 'lifecycle-channel')
        self.assertIn('对外 API', audit['details'])

    def test_delete_removes_project_and_pool(self):
        response = self.client.delete(
            '/api/external/projects/lifecycle-channel',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['deleted_project']['total_count'], 1)

        detail = self.client.get(
            '/api/external/projects/lifecycle-channel',
            headers=self._headers(),
        )
        self.assertEqual(detail.status_code, 404)

        with self.app.app_context():
            db = web_outlook_app.get_db()
            self.assertIsNone(
                db.execute(
                    'SELECT id FROM projects WHERE project_key = ?', ('lifecycle-channel',)
                ).fetchone()
            )
            self.assertIsNone(
                db.execute(
                    'SELECT id FROM project_accounts WHERE account_id = ?', (self.account_id,)
                ).fetchone()
            )
            self.assertIsNone(
                db.execute(
                    'SELECT id FROM project_account_events WHERE account_id = ?', (self.account_id,)
                ).fetchone()
            )
            # 账号本身不受影响
            account = db.execute(
                'SELECT id FROM accounts WHERE id = ?', (self.account_id,)
            ).fetchone()
            self.assertIsNotNone(account)

    def test_delete_blocked_while_claiming(self):
        claim = self._claim_via_api('lifecycle-channel').get_json()['data']

        response = self.client.delete(
            '/api/external/projects/lifecycle-channel',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('领取中', payload['error'])

        # 释放后可删除
        release = self._post_project_action('lifecycle-channel', 'release', {
            'account_id': claim['account_id'],
            'claim_token': claim['claim_token'],
        })
        self.assertEqual(release.status_code, 200)

        response = self.client.delete(
            '/api/external/projects/lifecycle-channel',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_missing_project_returns_404(self):
        response = self.client.delete(
            '/api/external/projects/no-such-project',
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_writes_audit_log(self):
        self.client.delete(
            '/api/external/projects/lifecycle-channel',
            headers=self._headers(),
        )
        audit = self._last_audit_row()
        self.assertEqual(audit['action'], 'delete')
        self.assertEqual(audit['resource_type'], 'project')
        self.assertEqual(audit['resource_id'], 'lifecycle-channel')
        self.assertIn('对外 API', audit['details'])


if __name__ == '__main__':
    unittest.main()
