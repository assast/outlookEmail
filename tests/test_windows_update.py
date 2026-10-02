import atexit
import importlib
import json
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
temp_dir = ROOT_DIR / '.tmp' / f'windows-update-tests-{os.getpid()}'
temp_dir.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_PATH'] = str(temp_dir / 'test.db')

windows_update = importlib.import_module('outlook_web.windows_update')
web_outlook_app = importlib.import_module('web_outlook_app')
atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))


class FakeDownloadResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.headers = {'Content-Length': str(sum(len(chunk) for chunk in self.chunks))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        return None


class FakeProcess:
    _next_pid = 9000

    def __init__(self, *args, **kwargs):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid

    def poll(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


class WindowsUpdateModuleTests(unittest.TestCase):
    def setUp(self):
        windows_update.register_shutdown_callback(None)
        windows_update._cancel_event.clear()
        windows_update._result_loaded_for = None
        with windows_update._state_lock:
            windows_update._state.clear()
            windows_update._state.update(windows_update.DEFAULT_STATE)
        self.workspace = pathlib.Path(tempfile.mkdtemp(dir=temp_dir))

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def _paths(self, executable_name='Renamed Mail.exe'):
        target = self.workspace / executable_name
        target.write_bytes(b'old-executable')
        return windows_update.build_update_paths(target)

    def test_build_update_paths_preserves_current_executable_name(self):
        paths = self._paths()

        self.assertEqual(paths.target.name, 'Renamed Mail.exe')
        self.assertEqual(paths.archive.name, 'Renamed Mail.update.zip')
        self.assertEqual(paths.replacement.name, 'Renamed Mail.new.exe')
        self.assertEqual(paths.runner.name, 'Renamed Mail.updater.exe')
        self.assertEqual(paths.backup.name, 'Renamed Mail.old.exe')

    def test_directory_probe_does_not_leave_files_behind(self):
        paths = self._paths()

        windows_update.check_update_directory(paths)

        self.assertEqual([item.name for item in self.workspace.iterdir()], [paths.target.name])

    def test_select_release_asset_requires_existing_zip_name(self):
        payload = {
            'assets': [
                {
                    'name': 'OutlookEmail-windows-x64-3.1.0.zip',
                    'browser_download_url': 'https://example.com/windows.zip',
                    'size': 123,
                },
            ],
        }

        asset = windows_update.select_release_asset(payload, 'v3.1.0')

        self.assertEqual(asset['download_url'], 'https://example.com/windows.zip')
        self.assertEqual(asset['size'], 123)

    def test_select_release_asset_reports_package_not_published(self):
        with self.assertRaisesRegex(windows_update.WindowsUpdateError, '尚未发布'):
            windows_update.select_release_asset({'assets': []}, 'v3.1.0')

    def test_download_tracks_exact_bytes_and_percentage(self):
        paths = self._paths()
        response = FakeDownloadResponse([b'abc', b'defg'])

        with patch.object(windows_update.requests, 'get', return_value=response):
            windows_update._download_release_asset(
                {'download_url': 'https://example.com/update.zip', 'size': 7},
                paths,
            )

        state = windows_update.get_windows_update_state(paths.target)
        self.assertEqual(paths.archive.read_bytes(), b'abcdefg')
        self.assertEqual(state['downloaded_bytes'], 7)
        self.assertEqual(state['total_bytes'], 7)
        self.assertEqual(state['percent'], 100.0)
        self.assertFalse(state['cancelable'])

    def test_extract_release_executable_uses_exact_packaged_member(self):
        paths = self._paths()
        with zipfile.ZipFile(paths.archive, 'w') as archive:
            archive.writestr('OutlookEmail.exe', b'new-executable')
            archive.writestr('README.md', b'readme')

        windows_update.extract_release_executable(paths.archive, paths.replacement)

        self.assertEqual(paths.replacement.read_bytes(), b'new-executable')

    def test_parse_restart_context_keeps_runner_and_health_arguments(self):
        context = windows_update.parse_update_startup_context([
            'OutlookEmail.exe',
            windows_update.UPDATE_RESTART_FLAG,
            windows_update.UPDATE_HEALTH_FILE_FLAG,
            'health.json',
            windows_update.UPDATE_HEALTH_TOKEN_FLAG,
            'token-1',
            windows_update.UPDATE_RUNNER_FLAG,
            'updater.exe',
            windows_update.UPDATE_RUNNER_PID_FLAG,
            '123',
            windows_update.UPDATE_TARGET_VERSION_FLAG,
            'v3.1.0',
        ])

        self.assertTrue(context['restarted'])
        self.assertEqual(context['health_file'], 'health.json')
        self.assertEqual(context['health_token'], 'token-1')
        self.assertEqual(context['runner'], 'updater.exe')
        self.assertEqual(context['runner_pid'], 123)
        self.assertEqual(context['target_version'], 'v3.1.0')

    def test_helper_command_passes_configured_health_port(self):
        paths = self._paths()

        with patch.dict(os.environ, {'PORT': '51234'}):
            command = windows_update._helper_command(
                paths,
                target_version='v3.1.0',
                health_token='health-token',
                parent_pid=321,
            )

        health_port_index = command.index('--health-port')
        self.assertEqual(command[health_port_index + 1], '51234')

    def test_wait_for_health_accepts_matching_version(self):
        paths = self._paths()
        paths.health.write_text(json.dumps({
            'ready': True,
            'token': 'health-token',
            'version': 'v3.1.0',
        }), encoding='utf-8')

        result = windows_update._wait_for_health(
            paths.health,
            'health-token',
            FakeProcess(),
            30,
            target=paths.target,
            target_version='v3.1.0',
            health_port=5000,
        )

        self.assertTrue(result)

    def test_wait_for_health_requires_matching_version(self):
        paths = self._paths()
        paths.health.write_text(json.dumps({
            'ready': True,
            'token': 'health-token',
            'version': 'v3.0.9',
        }), encoding='utf-8')

        result = windows_update._wait_for_health(
            paths.health,
            'health-token',
            FakeProcess(),
            30,
            target=paths.target,
            target_version='v3.1.0',
            health_port=5000,
        )

        self.assertFalse(result)

    def test_wait_for_health_accepts_stable_target_listener_as_compatibility_fallback(self):
        paths = self._paths()

        with patch.object(
            windows_update.time,
            'monotonic',
            side_effect=[0.0, 0.0, 1.1],
        ), patch.object(windows_update.time, 'sleep'), patch.object(
            windows_update,
            '_target_listener_pids',
            return_value={1234},
        ):
            result = windows_update._wait_for_health(
                paths.health,
                'health-token',
                FakeProcess(),
                30,
                target=paths.target,
                target_version='v3.1.0',
                health_port=5000,
                compatibility_ready_seconds=1.0,
            )

        self.assertTrue(result)

    def test_target_listener_pids_only_accepts_the_replacement_executable(self):
        paths = self._paths()
        other_executable = self.workspace / 'Other.exe'

        with patch.object(
            windows_update,
            '_windows_tcp_listener_pids',
            return_value={101, 202},
        ), patch.object(
            windows_update,
            '_windows_process_image_path',
            side_effect=lambda process_id: paths.target if process_id == 101 else other_executable,
        ):
            result = windows_update._target_listener_pids(paths.target, 5000)

        self.assertEqual(result, {101})

    def test_terminate_process_stops_bootloader_and_listening_child(self):
        paths = self._paths()
        process = FakeProcess()

        with patch.object(windows_update.os, 'name', 'nt'), patch.object(
            windows_update,
            '_target_listener_pids',
            return_value={4321},
        ), patch.object(windows_update, '_terminate_windows_process_tree') as terminate_tree:
            windows_update._terminate_process(process, target=paths.target, health_port=5000)

        self.assertEqual(
            {call.args[0] for call in terminate_tree.call_args_list},
            {process.pid, 4321},
        )

    def test_update_job_runs_from_copy_of_current_executable(self):
        paths = self._paths()
        shutdown_calls = []
        windows_update.register_shutdown_callback(lambda: shutdown_calls.append(True))

        def fake_download(asset, update_paths, request_headers=None):
            update_paths.archive.write_bytes(b'archive')

        def fake_extract(archive_path, destination):
            destination.write_bytes(b'new-executable')

        with patch.object(
            windows_update,
            'resolve_release_asset',
            return_value={'download_url': 'https://example.com/update.zip', 'size': 7},
        ), patch.object(
            windows_update,
            '_download_release_asset',
            side_effect=fake_download,
        ), patch.object(
            windows_update,
            'extract_release_executable',
            side_effect=fake_extract,
        ), patch.object(windows_update.subprocess, 'Popen', FakeProcess), patch.object(
            windows_update.time,
            'sleep',
        ):
            windows_update._run_update_job(
                paths,
                repository_owner='assast',
                repository_name='outlookEmail',
                target_version='v3.1.0',
                request_headers=None,
            )

        self.assertEqual(paths.runner.read_bytes(), b'old-executable')
        self.assertEqual(paths.replacement.read_bytes(), b'new-executable')
        self.assertEqual(shutdown_calls, [True])

    def test_helper_replaces_target_and_removes_backup_after_health(self):
        paths = self._paths()
        paths.replacement.write_bytes(b'new-executable')
        paths.archive.write_bytes(b'archive')
        paths.runner.write_bytes(b'runner')
        args = self._helper_args(paths)

        with patch.object(windows_update, '_wait_for_process_exit', return_value=True), patch.object(
            windows_update,
            'replace_file_windows',
            side_effect=self._fake_replace_file,
        ), patch.object(windows_update.subprocess, 'Popen', FakeProcess), patch.object(
            windows_update,
            '_wait_for_health',
            return_value=True,
        ):
            result = windows_update._run_helper(args)

        self.assertEqual(result, 0)
        self.assertEqual(paths.target.read_bytes(), b'new-executable')
        self.assertFalse(paths.backup.exists())
        self.assertFalse(paths.archive.exists())
        update_result = json.loads(paths.result.read_text(encoding='utf-8'))
        self.assertTrue(update_result['success'])

    def test_helper_restores_old_executable_when_health_check_fails(self):
        paths = self._paths()
        paths.replacement.write_bytes(b'new-executable')
        paths.archive.write_bytes(b'archive')
        paths.runner.write_bytes(b'runner')
        args = self._helper_args(paths)

        with patch.object(windows_update, '_wait_for_process_exit', return_value=True), patch.object(
            windows_update,
            'replace_file_windows',
            side_effect=self._fake_replace_file,
        ), patch.object(windows_update.subprocess, 'Popen', FakeProcess), patch.object(
            windows_update,
            '_wait_for_health',
            return_value=False,
        ), patch.object(windows_update, '_terminate_process'):
            result = windows_update._run_helper(args)

        self.assertEqual(result, 1)
        self.assertEqual(paths.target.read_bytes(), b'old-executable')
        update_result = json.loads(paths.result.read_text(encoding='utf-8'))
        self.assertFalse(update_result['success'])
        self.assertIn('已恢复旧版本', update_result['message'])

    def _helper_args(self, paths):
        return SimpleNamespace(
            target=str(paths.target),
            replacement=str(paths.replacement),
            backup=str(paths.backup),
            archive=str(paths.archive),
            health_file=str(paths.health),
            result_file=str(paths.result),
            health_token='health-token',
            target_version='v3.1.0',
            parent_pid=321,
            health_timeout=30,
            health_port=5000,
        )

    @staticmethod
    def _fake_replace_file(target, replacement, backup):
        target = pathlib.Path(target)
        replacement = pathlib.Path(replacement)
        if backup is not None:
            shutil.copy2(target, pathlib.Path(backup))
        os.replace(replacement, target)


class WindowsUpdateRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['login_session_version'] = web_outlook_app.DEFAULT_LOGIN_SESSION_VERSION

    def test_status_reports_platform_configuration_and_state(self):
        with patch.object(
            windows_update,
            'get_windows_update_config',
            return_value={'enabled': True, 'available': True, 'reason': '', 'executable_name': 'OutlookEmail.exe'},
        ), patch.object(
            windows_update,
            'get_windows_update_state',
            return_value={'running': False, 'stage': 'idle'},
        ):
            response = self.client.get('/api/windows-update/status')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()['windows_update']
        self.assertTrue(payload['available'])
        self.assertEqual(payload['state']['stage'], 'idle')

    def test_start_reuses_existing_version_status_target(self):
        version_status = {
            'status': 'update_available',
            'latest_version': 'v3.1.0',
        }
        config = {'enabled': True, 'available': True, 'reason': '', 'executable_name': 'OutlookEmail.exe'}
        with patch.object(windows_update, 'get_windows_update_config', return_value=config), patch.object(
            windows_update,
            'get_windows_update_state',
            return_value={'running': True, 'stage': 'queued'},
        ), patch.object(
            web_outlook_app,
            'get_version_status_payload',
            return_value=version_status,
        ), patch.object(
            windows_update,
            'start_windows_update',
            return_value=(True, 'started'),
        ) as start_update:
            response = self.client.post('/api/windows-update', json={})

        self.assertEqual(response.status_code, 202)
        self.assertEqual(start_update.call_args.kwargs['target_version'], 'v3.1.0')
        self.assertEqual(start_update.call_args.kwargs['repository_owner'], web_outlook_app.REPOSITORY_OWNER)
        self.assertEqual(start_update.call_args.kwargs['repository_name'], web_outlook_app.REPOSITORY_NAME)

    def test_start_rejects_when_existing_version_status_has_no_update(self):
        config = {'enabled': True, 'available': True, 'reason': '', 'executable_name': 'OutlookEmail.exe'}
        with patch.object(windows_update, 'get_windows_update_config', return_value=config), patch.object(
            web_outlook_app,
            'get_version_status_payload',
            return_value={'status': 'up_to_date', 'latest_version': 'v3.0.9'},
        ), patch.object(windows_update, 'start_windows_update') as start_update:
            response = self.client.post('/api/windows-update', json={})

        self.assertEqual(response.status_code, 409)
        start_update.assert_not_called()

    def test_cancel_delegates_to_windows_update_module(self):
        config = {'enabled': True, 'available': True, 'reason': '', 'executable_name': 'OutlookEmail.exe'}
        with patch.object(windows_update, 'cancel_windows_update', return_value=(True, 'cancelling')), patch.object(
            windows_update,
            'get_windows_update_config',
            return_value=config,
        ), patch.object(
            windows_update,
            'get_windows_update_state',
            return_value={'running': True, 'stage': 'downloading', 'cancelable': False},
        ):
            response = self.client.post('/api/windows-update/cancel', json={})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
