import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(tempfile.mkdtemp(prefix="outlookemail-tests-"), "test.db"),
)

import web_outlook_app as app_module


ACTIVE_ACCOUNT = {
    "id": 1,
    "email": "user@outlook.com",
    "status": "active",
}


def mock_read_account_messages(account, folder="inbox", **kwargs):
    messages = {
        "inbox": {
            "id": "msg-inbox",
            "date": "2026-04-10T09:00:00+00:00",
            "subject": "Inbox verification code",
        },
        "junkemail": {
            "id": "msg-junk",
            "date": "2026-04-10T10:00:00+00:00",
            "subject": "Junk verification code",
        },
    }
    return {
        "success": True,
        "method": "mock",
        "emails": [messages[folder]],
    }


def mock_read_account_message_detail(account, message_id, folder="inbox"):
    details = {
        "msg-inbox": {
            "id": "msg-inbox",
            "subject": "Inbox verification code",
            "content": "Your verification code is 111111.",
            "html_content": "",
            "from_address": "sender@example.com",
            "timestamp": "2026-04-10T09:00:00+00:00",
            "method": "mock",
        },
        "msg-junk": {
            "id": "msg-junk",
            "subject": "Junk verification code",
            "content": "Your verification code is 654321.",
            "html_content": "",
            "from_address": "sender@example.com",
            "timestamp": "2026-04-10T10:00:00+00:00",
            "method": "mock",
        },
    }
    return {
        "success": True,
        "email": details[message_id],
    }


class LatestVerificationCodeTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    @patch.object(app_module, "get_account_by_id", return_value=ACTIVE_ACCOUNT)
    @patch.object(app_module, "read_account_messages", side_effect=mock_read_account_messages)
    @patch.object(app_module, "read_account_message_detail", side_effect=mock_read_account_message_detail)
    def test_internal_route_prefers_newer_junk_message(
        self,
        _mock_detail,
        _mock_messages,
        _mock_account,
    ):
        with self.client.session_transaction() as session:
            session["logged_in"] = True

        response = self.client.get("/api/accounts/1/latest-verification-code")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["code"], "654321")
        self.assertEqual(payload["data"]["selected_folder"], "junkemail")
        self.assertEqual(payload["data"]["candidates"][0]["folder"], "junkemail")

    def test_external_verification_code_uses_same_latest_message_logic_without_default_lookback(self):
        since_minutes_seen = []

        def tracking_messages(account, folder="inbox", **kwargs):
            since_minutes_seen.append((folder, kwargs.get("since_minutes")))
            return mock_read_account_messages(account, folder=folder, **kwargs)

        with patch.object(app_module, "get_external_api_key", return_value="test-key"), \
             patch.object(app_module, "get_account_by_email", return_value=ACTIVE_ACCOUNT), \
             patch.object(app_module, "read_account_messages", side_effect=tracking_messages), \
             patch.object(app_module, "read_account_message_detail", side_effect=mock_read_account_message_detail):
            response = self.client.get(
                "/api/external/verification-code?email=user@outlook.com",
                headers={"X-API-Key": "test-key"},
            )

        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["code"], "654321")
        self.assertEqual(payload["data"]["selected_folder"], "junkemail")
        self.assertEqual(since_minutes_seen, [("inbox", None), ("junkemail", None)])


if __name__ == "__main__":
    unittest.main()
