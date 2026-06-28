import importlib
import io
import json
import os
import shutil
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-skin-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class SystemSkinManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['logged_in'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            skin_root = web_outlook_app.get_skin_data_root()
            shutil.rmtree(skin_root, ignore_errors=True)
            skin_root.mkdir(parents=True, exist_ok=True)
            web_outlook_app.set_setting('active_skin_id', web_outlook_app.SKIN_CLASSIC_ID)
            web_outlook_app.set_setting('skin_last_error', '')

    def make_skin_zip(self, files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for filename, content in files.items():
                archive.writestr(filename, content)
        buffer.seek(0)
        return buffer

    def make_valid_skin_zip(self, skin_id='uploaded-skin', css=':root { --skin-primary: #38bdf8; }'):
        return self.make_skin_zip({
            'skin.json': json.dumps({
                'id': skin_id,
                'name': 'Uploaded Skin',
                'version': '1.0.0',
                'entry': 'theme.css',
            }),
            'theme.css': css,
        })

    def install_git_skin_fixture(self):
        with tempfile.TemporaryDirectory(prefix='outlook-skin-fixture-') as temp_dir:
            package_dir = Path(temp_dir)
            (package_dir / 'skin.json').write_text(json.dumps({
                'id': 'git-skin',
                'name': 'Git Skin',
                'version': '1.0.0',
                'entry': 'theme.css',
            }), encoding='utf-8')
            (package_dir / 'theme.css').write_text(':root { --skin-primary: #0ea5e9; }', encoding='utf-8')
            return web_outlook_app.install_skin_from_directory(
                package_dir,
                web_outlook_app.SKIN_SOURCE_GIT,
                source_config={'git_url': 'https://example.invalid/skin.git', 'git_ref': 'main'},
            )

    def test_settings_default_to_classic_when_active_skin_missing(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute("DELETE FROM settings WHERE key = 'active_skin_id'")
            db.commit()

        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['settings']['active_skin_id'], 'classic')
        self.assertEqual(payload['settings']['active_skin']['source_type'], 'builtin')

    def test_settings_reject_invalid_active_skin(self):
        response = self.client.put('/api/settings', json={'active_skin_id': 'missing-skin'})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('皮肤不存在', payload['error'])
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_configured_active_skin_id(), 'classic')

    def test_manifest_validation_requires_manifest_and_safe_css_entry(self):
        with tempfile.TemporaryDirectory(prefix='outlook-skin-invalid-') as temp_dir:
            package_dir = Path(temp_dir)
            with self.assertRaises(web_outlook_app.SkinValidationError):
                web_outlook_app.validate_skin_package_directory(package_dir)

            (package_dir / 'skin.json').write_text(json.dumps({
                'id': 'bad-skin',
                'name': 'Bad Skin',
                'version': '1.0.0',
                'entry': '../theme.css',
            }), encoding='utf-8')
            with self.assertRaises(web_outlook_app.SkinValidationError):
                web_outlook_app.validate_skin_package_directory(package_dir)

    def test_manifest_validation_rejects_oversized_css(self):
        with tempfile.TemporaryDirectory(prefix='outlook-skin-large-') as temp_dir:
            package_dir = Path(temp_dir)
            (package_dir / 'skin.json').write_text(json.dumps({
                'id': 'large-skin',
                'name': 'Large Skin',
                'version': '1.0.0',
                'entry': 'theme.css',
            }), encoding='utf-8')
            (package_dir / 'theme.css').write_text('a' * (web_outlook_app.SKIN_MAX_CSS_BYTES + 1), encoding='utf-8')
            with self.assertRaises(web_outlook_app.SkinValidationError):
                web_outlook_app.validate_skin_package_directory(package_dir)

    def test_manifest_validation_rejects_script_files(self):
        with tempfile.TemporaryDirectory(prefix='outlook-skin-script-') as temp_dir:
            package_dir = Path(temp_dir)
            (package_dir / 'skin.json').write_text(json.dumps({
                'id': 'script-skin',
                'name': 'Script Skin',
                'version': '1.0.0',
                'entry': 'theme.css',
            }), encoding='utf-8')
            (package_dir / 'theme.css').write_text(':root {}', encoding='utf-8')
            (package_dir / 'install.sh').write_text('echo unsafe', encoding='utf-8')
            with self.assertRaises(web_outlook_app.SkinValidationError):
                web_outlook_app.validate_skin_package_directory(package_dir)

    def test_upload_skin_zip_installs_skin(self):
        response = self.client.post(
            '/api/skins/upload',
            data={'skin': (self.make_valid_skin_zip(), 'skin.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['skin']['id'], 'uploaded-skin')

        list_response = self.client.get('/api/skins')
        skin_ids = [skin['id'] for skin in list_response.get_json()['skins']]
        self.assertIn('uploaded-skin', skin_ids)

    def test_upload_rejects_zip_path_traversal(self):
        response = self.client.post(
            '/api/skins/upload',
            data={'skin': (self.make_skin_zip({
                '../evil.css': 'body{}',
                'skin.json': '{}',
            }), 'skin.zip')},
            content_type='multipart/form-data',
        )
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('路径', payload['error'])

    def test_git_install_failure_keeps_current_skin(self):
        with patch.object(web_outlook_app.shutil, 'which', return_value='/usr/bin/git'), \
                patch.object(
                    web_outlook_app.subprocess,
                    'run',
                    return_value=types.SimpleNamespace(returncode=1, stdout='', stderr='network failed'),
                ):
            response = self.client.post('/api/skins/git/install', json={
                'git_url': 'https://example.invalid/skin.git',
                'git_ref': 'main',
            })

        payload = response.get_json()
        self.assertFalse(payload['success'])
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_configured_active_skin_id(), 'classic')

    def test_git_update_failure_keeps_existing_skin_files(self):
        self.install_git_skin_fixture()
        skin_dir = web_outlook_app.get_skin_source_root(web_outlook_app.SKIN_SOURCE_GIT) / 'git-skin'
        before_css = (skin_dir / 'theme.css').read_text(encoding='utf-8')

        with patch.object(web_outlook_app.shutil, 'which', return_value='/usr/bin/git'), \
                patch.object(
                    web_outlook_app.subprocess,
                    'run',
                    return_value=types.SimpleNamespace(returncode=1, stdout='', stderr='network failed'),
                ):
            response = self.client.post('/api/skins/git-skin/git/update')

        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual((skin_dir / 'theme.css').read_text(encoding='utf-8'), before_css)

    def test_active_skin_css_returns_custom_or_classic_fallback(self):
        upload_response = self.client.post(
            '/api/skins/upload',
            data={'skin': (self.make_valid_skin_zip(css=':root { --skin-primary: #abcdef; }'), 'skin.zip')},
            content_type='multipart/form-data',
        )
        self.assertTrue(upload_response.get_json()['success'])
        activate_response = self.client.post('/api/skins/uploaded-skin/activate')
        self.assertTrue(activate_response.get_json()['success'])

        css_response = self.client.get('/assets/active-skin.css')
        self.assertEqual(css_response.status_code, 200)
        self.assertIn('--skin-primary: #abcdef', css_response.get_data(as_text=True))

        with self.app.app_context():
            web_outlook_app.set_setting('active_skin_id', 'missing-skin')
        fallback_response = self.client.get('/assets/active-skin.css')
        self.assertIn('classic', fallback_response.get_data(as_text=True))

    def test_settings_page_contains_skin_management_ui(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="activeSkinStylesheet"', html)
        self.assertIn('id="settingsSkinSection"', html)
        self.assertIn('settingsSkinUploadFile', html)


if __name__ == '__main__':
    unittest.main()
