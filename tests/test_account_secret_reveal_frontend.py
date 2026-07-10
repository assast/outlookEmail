from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '07-settings.js'
DIALOGS_PRIMARY_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-primary.html'


class AccountSecretRevealFrontendTests(unittest.TestCase):
    def test_verify_modal_removed_from_html(self):
        html = DIALOGS_PRIMARY_PATH.read_text(encoding='utf-8')

        self.assertNotIn('accountSecretVerifyModal', html)
        self.assertNotIn('showAccountSecretVerifyModal', html)
        self.assertNotIn('confirmAccountSecretVerify', html)

    def test_eye_icon_buttons_use_toggle_instead_of_verify(self):
        html = DIALOGS_PRIMARY_PATH.read_text(encoding='utf-8')

        self.assertIn("toggleEditSecretVisibility('editPassword'", html)
        self.assertIn("toggleEditSecretVisibility('editImapPassword'", html)
        self.assertIn('aria-label="显示密码"', html)
        self.assertIn('aria-label="显示 IMAP 密码"', html)
        self.assertNotIn('aria-label="验证显示密码"', html)
        self.assertNotIn('aria-label="验证显示 IMAP 密码"', html)

    def test_reset_edit_secret_input_stores_secret_and_mask(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn('input.dataset.secretValue', source)
        self.assertIn('input.dataset.secretRevealed', source)
        self.assertIn('input.dataset.secretMask', source)
        self.assertIn('getSecretMask', source)

    def test_toggle_function_exists_and_no_verify_functions(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn('function toggleEditSecretVisibility', source)
        self.assertNotIn('function showAccountSecretVerifyModal', source)
        self.assertNotIn('function hideAccountSecretVerifyModal', source)
        self.assertNotIn('function confirmAccountSecretVerify', source)
        self.assertNotIn('editAccountSecretState.pendingField', source)

    def test_open_edit_account_passes_password_to_reset(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn(
            "resetEditSecretInput('editPassword', 'revealEditPasswordBtn', !!acc.has_password, acc.password || '', '可选')",
            source,
        )
        self.assertIn(
            "resetEditSecretInput('editImapPassword', 'revealEditImapPasswordBtn', !!acc.has_imap_password, acc.imap_password || '', '')",
            source,
        )

    def test_should_submit_skips_mask_value(self):
        source = SETTINGS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn('input.dataset.secretMask', source)
        self.assertNotIn('LOCKED_ACCOUNT_SECRET_PLACEHOLDER', source)


if __name__ == '__main__':
    unittest.main()
