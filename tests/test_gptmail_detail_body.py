import os
import tempfile
import unittest
from unittest.mock import patch


if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-gptmail-detail-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
if 'SECRET_KEY' not in os.environ:
    os.environ['SECRET_KEY'] = 'test-secret-key'

import web_outlook_app


EMAIL = 'gpt-user@example.com'


class GptMailDetailBodyTestCase(unittest.TestCase):
    """回归测试: issue #115 GPTMail 邮件正文显示空白

    GPTMail 列表接口契约: has_html=True 但 html_content 恒为空串,
    完整 HTML 正文只在详情接口返回。详情接口需回源补全, 且 body 需有纯文本兜底。
    """

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM temp_email_messages')
            db.execute('DELETE FROM temp_email_tags')
            db.execute('DELETE FROM temp_emails')
            db.commit()
            self.assertTrue(web_outlook_app.add_temp_email(EMAIL, 'gptmail'))

    def seed_message(self, message_id, content, html_content='', has_html=True):
        with self.app.app_context():
            web_outlook_app.save_temp_email_messages(EMAIL, [{
                'id': message_id,
                'from_address': 'sender@example.com',
                'subject': '测试主题',
                'content': content,
                'html_content': html_content,
                'has_html': has_html,
                'timestamp': 1730000000,
            }])

    def fetch_detail(self, message_id):
        return self.client.get(f'/api/temp-emails/{EMAIL}/messages/{message_id}')

    def test_incomplete_cache_refetches_detail_and_returns_html_body(self):
        self.seed_message('m1', '纯文本正文', html_content='', has_html=True)

        detail = {
            'id': 'm1',
            'from_address': 'sender@example.com',
            'subject': '测试主题',
            'content': '纯文本正文',
            'html_content': '<p>HTML 正文</p>',
            'has_html': True,
            'timestamp': 1730000000,
        }
        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=detail) as api:
            resp = self.fetch_detail('m1')

        api.assert_called_once_with('m1', EMAIL)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '<p>HTML 正文</p>')
        self.assertEqual(data['email']['body_type'], 'html')

        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=None) as api:
            resp = self.fetch_detail('m1')
        api.assert_not_called()
        self.assertEqual(resp.get_json()['email']['body'], '<p>HTML 正文</p>')

    def test_complete_html_cache_skips_upstream(self):
        self.seed_message('m2', '纯文本正文', html_content='<p>已缓存 HTML</p>', has_html=True)

        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=None) as api:
            resp = self.fetch_detail('m2')

        api.assert_not_called()
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '<p>已缓存 HTML</p>')
        self.assertEqual(data['email']['body_type'], 'html')

    def test_plain_text_cache_skips_upstream(self):
        self.seed_message('m3', '纯文本正文', html_content='', has_html=False)

        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=None) as api:
            resp = self.fetch_detail('m3')

        api.assert_not_called()
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '纯文本正文')
        self.assertEqual(data['email']['body_type'], 'text')

    def test_upstream_failure_falls_back_to_text_content(self):
        self.seed_message('m4', '纯文本正文', html_content='', has_html=True)

        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=None):
            resp = self.fetch_detail('m4')

        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '纯文本正文')
        self.assertEqual(data['email']['body_type'], 'text')

    def test_upstream_detail_without_html_updates_cache_and_falls_back(self):
        self.seed_message('m5', '纯文本正文', html_content='', has_html=True)

        detail = {
            'id': 'm5',
            'from_address': 'sender@example.com',
            'subject': '测试主题',
            'content': '纯文本正文',
            'html_content': '',
            'has_html': True,
            'timestamp': 1730000000,
        }
        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=detail) as api:
            resp = self.fetch_detail('m5')

        api.assert_called_once()
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '纯文本正文')
        self.assertEqual(data['email']['body_type'], 'text')

        # html_content 为空时缓存标记 has_html=0, 不再重复回源
        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=detail) as api:
            resp = self.fetch_detail('m5')
        api.assert_not_called()

    def test_missing_local_record_saves_upstream_detail(self):
        detail = {
            'id': 'm6',
            'from_address': 'sender@example.com',
            'subject': '测试主题',
            'content': '纯文本正文',
            'html_content': '<p>HTML 正文</p>',
            'has_html': True,
            'timestamp': 1730000000,
        }
        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=detail):
            resp = self.fetch_detail('m6')

        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['email']['body'], '<p>HTML 正文</p>')
        self.assertEqual(data['email']['body_type'], 'html')

    def test_unknown_message_returns_error(self):
        with patch('web_outlook_app.get_temp_email_detail_from_api', return_value=None):
            resp = self.fetch_detail('missing-id')

        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertIn('不存在', data['error'])


if __name__ == '__main__':
    unittest.main()