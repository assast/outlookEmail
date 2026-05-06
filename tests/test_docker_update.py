import importlib
import json
import os
import pathlib
import shutil
import unittest
from unittest.mock import patch


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
temp_dir = ROOT_DIR / '.tmp' / f'docker-update-tests-{os.getpid()}'
temp_dir.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_PATH'] = str(temp_dir / 'test.db')
os.environ['DOCKER_UPDATE_STATE_FILE'] = str(temp_dir / 'docker_update_state.json')

web_outlook_app = importlib.import_module('web_outlook_app')


def tearDownModule():
    shutil.rmtree(temp_dir, ignore_errors=True)


class DockerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.state_file = temp_dir / 'docker_update_state.json'
        if self.state_file.exists():
            self.state_file.unlink()
        with web_outlook_app.DOCKER_UPDATE_STATE_LOCK:
            web_outlook_app.DOCKER_UPDATE_STATE.clear()
            web_outlook_app.DOCKER_UPDATE_STATE.update(web_outlook_app.DEFAULT_DOCKER_UPDATE_STATE)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    def test_status_is_disabled_by_default(self):
        with patch.dict(os.environ, {'DOCKER_UPDATE_ENABLED': 'false'}, clear=False):
            response = self.client.get('/api/docker-update/status')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertFalse(payload['docker_update']['enabled'])
        self.assertFalse(payload['docker_update']['available'])

    def test_start_requires_enabled_flag(self):
        with patch.dict(os.environ, {'DOCKER_UPDATE_ENABLED': 'false'}, clear=False):
            response = self.client.post('/api/docker-update', json={})

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertFalse(payload['success'])

    def test_start_rejects_missing_docker_socket(self):
        with patch.dict(
            os.environ,
            {
                'DOCKER_UPDATE_ENABLED': 'true',
                'DOCKER_UPDATE_SOCKET': str(ROOT_DIR / '.tmp' / 'missing-docker.sock'),
                'DOCKER_UPDATE_CONTAINER': 'outlook-mail-reader',
            },
            clear=False,
        ):
            response = self.client.post('/api/docker-update', json={})

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertRegex(payload['error'], r'Docker socket|Unix docker socket')

    def test_watchtower_payload_targets_configured_container_only(self):
        payload = web_outlook_app.build_watchtower_create_payload(
            container_name='outlook-mail-reader',
            socket_path='/var/run/docker.sock',
            watchtower_image='containrrr/watchtower:latest',
        )

        self.assertEqual(payload['Image'], 'containrrr/watchtower:latest')
        self.assertEqual(payload['Cmd'], ['--run-once', '--cleanup', 'outlook-mail-reader'])
        self.assertTrue(payload['Tty'])
        self.assertEqual(payload['Env'], ['DOCKER_HOST=unix:///var/run/docker.sock'])
        self.assertEqual(payload['HostConfig']['Binds'], ['/var/run/docker.sock:/var/run/docker.sock'])
        self.assertTrue(payload['HostConfig']['AutoRemove'])

    def test_watchtower_payload_uses_custom_socket_for_docker_host(self):
        payload = web_outlook_app.build_watchtower_create_payload(
            container_name='outlook-mail-reader',
            socket_path='/custom/docker.sock',
            watchtower_image='containrrr/watchtower:latest',
        )

        self.assertEqual(payload['Env'], ['DOCKER_HOST=unix:///custom/docker.sock'])
        self.assertEqual(payload['HostConfig']['Binds'], ['/custom/docker.sock:/custom/docker.sock'])

    def test_docker_api_body_reads_full_stream(self):
        class FakeResponse:
            def read(self):
                return ('{"status":"pulling"}\n' + ('x' * 70000)).encode('utf-8')

        body = web_outlook_app._read_docker_api_body(FakeResponse())

        self.assertIn('{"status":"pulling"}', body)
        self.assertEqual(body.count('x'), 70000)
        self.assertNotIn('truncated', body)

    def test_ensure_watchtower_image_detects_stream_error(self):
        config = {
            'watchtower_image': 'containrrr/watchtower:latest',
            'socket_path': '/var/run/docker.sock',
            'api_version': 'v1.41',
            'timeout_seconds': 30,
        }
        stream_body = (
            '{"status":"Pulling from containrrr/watchtower"}\n'
            '{"errorDetail":{"message":"pull access denied"},"error":"pull access denied"}\n'
        )

        with patch.object(web_outlook_app, '_docker_api_request', return_value=(200, stream_body)):
            with self.assertRaisesRegex(RuntimeError, 'pull access denied'):
                web_outlook_app._ensure_watchtower_image(config)

    def test_classify_watchtower_logs_reports_no_new_image(self):
        success, message = web_outlook_app._classify_watchtower_logs(
            'time="2026-05-06T10:00:00Z" level=info msg="No new images found for /outlook-mail-reader"',
            'ghcr.io/assast/outlookemail:latest',
        )

        self.assertFalse(success)
        self.assertIn('No new image found for the current tag', message)

    def test_update_state_persists_latest_snapshot_to_file(self):
        web_outlook_app._update_docker_update_state(message='first', success=None)
        web_outlook_app._update_docker_update_state(
            running=False,
            success=True,
            message='second',
            log_excerpt='final log line',
        )

        persisted = json.loads(self.state_file.read_text(encoding='utf-8'))
        self.assertEqual(persisted['message'], 'second')
        self.assertTrue(persisted['success'])
        self.assertEqual(persisted['log_excerpt'], 'final log line')

    def test_load_persisted_running_state_converts_to_unknown_final_state(self):
        self.state_file.write_text(json.dumps({
            'running': True,
            'started_at': '2026-05-06T10:00:00+00:00',
            'finished_at': None,
            'success': None,
            'message': 'watching logs',
            'error': '',
            'container_id': 'abc',
            'log_excerpt': 'tail',
        }), encoding='utf-8')

        restored = web_outlook_app._load_persisted_docker_update_state()

        self.assertFalse(restored['running'])
        self.assertIsNone(restored['success'])
        self.assertIn('service may have restarted', restored['message'].lower())
        self.assertEqual(restored['log_excerpt'], 'tail')

    def test_docker_update_config_rejects_pinned_release_tag(self):
        with patch.dict(
            os.environ,
            {
                'DOCKER_UPDATE_ENABLED': 'true',
                'DOCKER_UPDATE_SOCKET': '/var/run/docker.sock',
                'DOCKER_UPDATE_CONTAINER': 'outlook-mail-reader',
            },
            clear=False,
        ), patch.object(web_outlook_app.socket, 'AF_UNIX', new=object(), create=True), patch.object(
            web_outlook_app.os.path,
            'exists',
            return_value=True,
        ), patch.object(
            web_outlook_app,
            '_inspect_docker_container',
            return_value={
                'Name': '/outlook-mail-reader',
                'Config': {'Image': 'ghcr.io/assast/outlookemail:v2.0.39'},
            },
        ):
            config = web_outlook_app.get_docker_update_config()

        self.assertTrue(config['enabled'])
        self.assertFalse(config['available'])
        self.assertEqual(config['container'], 'outlook-mail-reader')
        self.assertEqual(config['current_image'], 'ghcr.io/assast/outlookemail:v2.0.39')
        self.assertIn('mutable image tag like latest/main/dev', config['reason'])

    def test_docker_update_config_resolves_current_container_name_from_hostname(self):
        with patch.dict(
            os.environ,
            {
                'DOCKER_UPDATE_ENABLED': 'true',
                'DOCKER_UPDATE_SOCKET': '/var/run/docker.sock',
                'DOCKER_UPDATE_CONTAINER': '',
                'HOSTNAME': '3d4c5b6a7f8e',
            },
            clear=False,
        ), patch.object(web_outlook_app.socket, 'AF_UNIX', new=object(), create=True), patch.object(
            web_outlook_app.os.path,
            'exists',
            return_value=True,
        ), patch.object(
            web_outlook_app,
            '_inspect_docker_container',
            return_value={
                'Name': '/outlook-mail-reader',
                'Config': {'Image': 'ghcr.io/assast/outlookemail:latest'},
            },
        ):
            config = web_outlook_app.get_docker_update_config()

        self.assertTrue(config['enabled'])
        self.assertTrue(config['available'])
        self.assertEqual(config['container'], 'outlook-mail-reader')
        self.assertEqual(config['current_image'], 'ghcr.io/assast/outlookemail:latest')

    def test_docker_update_config_uses_dedicated_status_timeout_for_inspect(self):
        captured = {}

        def fake_inspect(config, container_ref):
            captured['timeout_seconds'] = config['timeout_seconds']
            return {
                'Name': '/outlook-mail-reader',
                'Config': {'Image': 'ghcr.io/assast/outlookemail:latest'},
            }

        with patch.dict(
            os.environ,
            {
                'DOCKER_UPDATE_ENABLED': 'true',
                'DOCKER_UPDATE_SOCKET': '/var/run/docker.sock',
                'DOCKER_UPDATE_CONTAINER': 'outlook-mail-reader',
                'DOCKER_UPDATE_TIMEOUT': '300',
                'DOCKER_UPDATE_STATUS_TIMEOUT': '7',
            },
            clear=False,
        ), patch.object(web_outlook_app.socket, 'AF_UNIX', new=object(), create=True), patch.object(
            web_outlook_app.os.path,
            'exists',
            return_value=True,
        ), patch.object(web_outlook_app, '_inspect_docker_container', side_effect=fake_inspect):
            config = web_outlook_app.get_docker_update_config()

        self.assertTrue(config['available'])
        self.assertEqual(captured['timeout_seconds'], 7)

    def test_frontend_monitor_handles_unknown_final_state(self):
        core_js = (ROOT_DIR / 'static' / 'js' / 'index' / '01-core.js').read_text(encoding='utf-8')

        self.assertIn('state.success === null || typeof state.success === \'undefined\'', core_js)
        self.assertIn('服务可能已重启，请刷新并核对当前版本/镜像', core_js)


if __name__ == '__main__':
    unittest.main()
