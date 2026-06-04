from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '07-settings.js'
DIALOGS_PRIMARY_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-primary.html'


class AccountSecretRevealFrontendTests(unittest.TestCase):
    def test_account_secret_verify_posts_requested_field(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn("field: editAccountSecretState.pendingField || ''", source)
        self.assertIn("hasOwnProperty.call(secrets, 'password')", source)
        self.assertIn("hasOwnProperty.call(secrets, 'imap_password')", source)

    def test_account_secret_verify_keeps_edit_modal_open(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')
        function_start = source.index('function showAccountSecretVerifyModal')
        function_end = source.index('function hideAccountSecretVerifyModal', function_start)
        function_source = source[function_start:function_end]

        self.assertIn("setModalVisible('accountSecretVerifyModal', true)", function_source)
        self.assertNotIn("showModal('accountSecretVerifyModal')", function_source)

    def test_account_secret_reveal_uses_eye_icon_buttons(self):
        html = DIALOGS_PRIMARY_PATH.read_text(encoding='utf-8')

        self.assertIn('class="secret-reveal-btn"', html)
        self.assertIn('aria-label="验证显示密码"', html)
        self.assertIn('aria-label="验证显示 IMAP 密码"', html)
        self.assertNotIn('>验证显示</button>', html)


if __name__ == '__main__':
    unittest.main()
