import json
from pathlib import Path
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'layout.html'
DIALOGS_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-primary.html'
CORE_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '01-core.js'
GROUPS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '02-groups.js'
TEMP_EMAILS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '03-temp-emails.js'
ACCOUNTS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '04-accounts.js'
EMAILS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '05-emails.js'
EMAIL_CONTENT_CSS_PATH = ROOT_DIR / 'static' / 'css' / 'index' / '05-email-content.css'
MODALS_CSS_PATH = ROOT_DIR / 'static' / 'css' / 'index' / '06-modals-toast.css'


class OutlookGraphSendMailFrontendTests(unittest.TestCase):
    def setUp(self):
        self.layout = LAYOUT_PATH.read_text(encoding='utf-8')
        self.dialogs = DIALOGS_PATH.read_text(encoding='utf-8')
        self.core_js = CORE_JS_PATH.read_text(encoding='utf-8')
        self.groups_js = GROUPS_JS_PATH.read_text(encoding='utf-8')
        self.temp_emails_js = TEMP_EMAILS_JS_PATH.read_text(encoding='utf-8')
        self.accounts_js = ACCOUNTS_JS_PATH.read_text(encoding='utf-8')
        self.emails_js = EMAILS_JS_PATH.read_text(encoding='utf-8')

    def test_compose_entry_and_basic_text_only_modal_are_present(self):
        self.assertIn('id="composeGraphMailBtn"', self.layout)
        self.assertIn('onclick="openGraphSendMailModal()"', self.layout)
        self.assertIn('id="graphSendMailModal"', self.dialogs)
        self.assertIn('id="graphSendMailAccountId"', self.dialogs)
        self.assertIn('id="graphSendMailRecipients"', self.dialogs)
        self.assertIn('id="graphSendMailSubject"', self.dialogs)
        self.assertIn('id="graphSendMailBody"', self.dialogs)
        self.assertIn('onsubmit="event.preventDefault(); sendGraphMail();"', self.dialogs)
        self.assertNotIn('graphSendMailFrom', self.dialogs)
        self.assertNotIn('graphSendMailAttachment', self.dialogs)
        self.assertNotIn('graphSendMailHtml', self.dialogs)

    def test_account_selection_preserves_server_account_id_metadata(self):
        self.assertIn('let currentAccountSummary = null;', self.core_js)
        self.assertIn('function buildCurrentAccountSummary(email, accountId)', self.accounts_js)
        self.assertIn('selectAccount(email, accountId = 0)', self.accounts_js)
        self.assertIn('handleAccountItemClick(event, email, isTemp = false, accountId = 0)', self.groups_js)
        self.assertIn("selectAccount(email, accountId);", self.groups_js)
        self.assertIn("onclick=\"handleAccountItemClick(event, '${escapeJs(acc.email)}', false, ${Number(acc.id) || 0})\"", self.groups_js)

    def test_compose_visibility_excludes_temp_imap_and_inactive_accounts(self):
        candidate_start = self.emails_js.index('function getGraphSendMailCandidate()')
        candidate_end = self.emails_js.index('function updateGraphSendMailAvailability()', candidate_start)
        candidate_source = self.emails_js[candidate_start:candidate_end]
        self.assertIn('isTempEmailGroup', candidate_source)
        self.assertIn("account_type || '').toLowerCase() !== 'outlook'", candidate_source)
        self.assertIn("provider || '').toLowerCase() !== 'outlook'", candidate_source)
        self.assertIn("authorization_type || '').toLowerCase() === 'imap'", candidate_source)
        self.assertIn("status || '').toLowerCase() !== 'active'", candidate_source)
        self.assertIn('currentAccountSummary = null;', self.temp_emails_js)
        self.assertIn('updateGraphSendMailAvailability();', self.temp_emails_js)

    def test_frontend_posts_only_whitelisted_graph_send_payload_and_prevents_duplicates(self):
        send_start = self.emails_js.index('async function sendGraphMail()')
        send_end = self.emails_js.index('function cleanupIframeResizeResources', send_start)
        send_source = self.emails_js[send_start:send_end]
        self.assertIn('if (isGraphSendMailSubmitting)', send_source)
        self.assertIn('setGraphSendMailSubmitting(true);', send_source)
        self.assertIn('setGraphSendMailSubmitting(false);', send_source)
        self.assertIn("fetchWithTimeout('/api/outlook/send-mail'", send_source)
        self.assertIn('account_id: graphSendMailAccountSnapshot.id', send_source)
        self.assertIn('recipients: recipientResult.recipients', send_source)
        self.assertIn('subject,', send_source)
        self.assertIn('body,', send_source)
        self.assertNotIn('from:', send_source)
        self.assertNotIn('sender:', send_source)
        self.assertNotIn('attachments:', send_source)
        self.assertNotIn('html:', send_source)

    def test_success_reauthorization_throttle_and_unknown_result_feedback_are_explicit(self):
        self.assertIn("showGraphSendMailFeedback('邮件已提交发送', 'success');", self.emails_js)
        self.assertIn("showToast('邮件已提交发送', 'success');", self.emails_js)
        self.assertIn("code === 'GRAPH_SEND_REAUTH_REQUIRED'", self.emails_js)
        self.assertIn('reauthorizationRequired: true', self.emails_js)
        self.assertIn("code === 'GRAPH_SEND_THROTTLED'", self.emails_js)
        self.assertIn('retry_after', self.emails_js)
        self.assertIn("code === 'GRAPH_SEND_RESULT_UNKNOWN'", self.emails_js)
        self.assertIn('邮件提交结果不确定，请确认后再决定是否重新发送', self.emails_js)

    def test_recipient_parser_accepts_multiple_addresses_and_rejects_invalid_values(self):
        start = self.emails_js.index('const GRAPH_SEND_MAIL_RECIPIENT_PATTERN')
        end = self.emails_js.index('function setGraphSendMailValidation', start)
        source = self.emails_js[start:end]
        script = f"""
const GRAPH_SEND_MAIL_RECIPIENT_PATTERN = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
{source[source.index('function parseGraphSendMailRecipients'):]}
const valid = parseGraphSendMailRecipients('A@example.com; b@example.com\\nA@example.com');
const invalid = parseGraphSendMailRecipients('not-an-email');
const empty = parseGraphSendMailRecipients('');
console.log(JSON.stringify({{ valid, invalid, empty }}));
"""
        result = subprocess.run(['node', '-e', script], check=True, text=True, capture_output=True)
        values = json.loads(result.stdout)
        self.assertEqual(values['valid']['recipients'], ['a@example.com', 'b@example.com'])
        self.assertEqual(values['valid']['error'], '')
        self.assertEqual(values['invalid']['recipients'], [])
        self.assertTrue(values['invalid']['error'])
        self.assertEqual(values['empty']['recipients'], [])
        self.assertTrue(values['empty']['error'])

    def test_compose_styles_use_existing_assets(self):
        email_css = EMAIL_CONTENT_CSS_PATH.read_text(encoding='utf-8')
        modal_css = MODALS_CSS_PATH.read_text(encoding='utf-8')
        self.assertIn('.email-list-header-actions', email_css)
        self.assertIn('.compose-mail-btn', email_css)
        self.assertIn('.graph-send-mail-modal-content', modal_css)
        self.assertIn('.graph-send-mail-status.warning', modal_css)


if __name__ == '__main__':
    unittest.main()
