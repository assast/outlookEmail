"""Feishu protocol, settings and forwarding integration contracts."""

import base64
import hashlib
import hmac
import importlib
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest


_import_directory = tempfile.TemporaryDirectory(prefix='outlookEmail-feishu-import-')
with patch.dict(os.environ, {
    'SECRET_KEY': os.environ.get('SECRET_KEY', 'test-secret-key'),
    'DATABASE_PATH': os.path.join(_import_directory.name, 'import.db'),
    'WERKZEUG_RUN_MAIN': 'false',
}):
    web = importlib.import_module('web_outlook_app')

WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/test-webhook-token'
SECRET = 'test-signing-secret'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setattr(web, 'DATABASE', str(tmp_path / 'feishu.db'))
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', False)
    monkeypatch.setattr(web, 'FEISHU_RATE_STATE', {}, raising=False)
    with web.app.app_context():
        web.init_db()
        yield_client = web.app.test_client()
        with yield_client.session_transaction() as session:
            session['logged_in'] = True
        yield yield_client


def response(payload=None, status=200, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=payload))


def send(config=None, text='邮件转发\n账号: primary@example.com\n测试邮件'):
    return web.send_forward_feishu_with_config(config or {'webhook_url': WEBHOOK}, text)


def test_settings_encrypt_hide_preserve_and_clear_credentials(client):
    result = client.put('/api/settings', json={
        'forward_channels': ['feishu'], 'feishu_webhook_url': WEBHOOK,
        'feishu_sign_secret': SECRET,
    }).get_json()
    assert result['success']
    assert web.get_setting('feishu_webhook_url').startswith('enc:')
    assert web.get_setting('feishu_sign_secret').startswith('enc:')
    settings = client.get('/api/settings').get_json()['settings']
    assert settings['forward_channels'] == ['feishu']
    assert settings['feishu_webhook_url_configured'] is True
    assert settings['feishu_sign_secret_configured'] is True
    assert 'feishu_webhook_url' not in settings
    assert 'feishu_sign_secret' not in settings
    assert WEBHOOK not in json.dumps(settings) and SECRET not in json.dumps(settings)
    assert client.put('/api/settings', json={
        'feishu_webhook_url': '', 'feishu_sign_secret': '',
    }).get_json()['success']
    assert web.get_setting_decrypted('feishu_webhook_url') == WEBHOOK
    assert web.get_setting_decrypted('feishu_sign_secret') == SECRET
    assert client.put('/api/settings', json={'feishu_clear_sign_secret': True}).get_json()['success']
    assert web.get_setting_decrypted('feishu_sign_secret') == ''


@pytest.mark.parametrize('payload', [
    {'code': 19021}, {'code': 19024}, {'code': 11232}, {}, [],
    {'code': None}, {'code': False}, {'code': '0'}, {'code': 1, 'StatusCode': 0},
])
def test_http_200_business_failures_never_succeed(client, payload):
    with patch.object(web.requests, 'request', return_value=response(payload)) as request:
        with pytest.raises(ValueError, match='飞书'):
            send()
    assert request.call_count == 1


@pytest.mark.parametrize('payload', [{'code': 0}, {'StatusCode': 0}])
def test_signed_and_unsigned_protocol(client, payload):
    with patch.object(web.requests, 'request', return_value=response(payload)) as request:
        assert send() is True
        sent = json.loads(request.call_args.kwargs['data'])
        assert sent['msg_type'] == 'text'
        assert 'timestamp' not in sent and 'sign' not in sent
        assert request.call_args.args == ('post', WEBHOOK)
        assert request.call_args.kwargs['allow_redirects'] is False
    with patch.object(web.time, 'time', return_value=1599360473), patch.object(
        web.requests, 'request', return_value=response(payload),
    ) as request:
        assert send({'webhook_url': WEBHOOK, 'sign_secret': SECRET}) is True
        sent = json.loads(request.call_args.kwargs['data'])
        expected = base64.b64encode(hmac.new(
            f'1599360473\n{SECRET}'.encode(), b'', hashlib.sha256,
        ).digest()).decode()
        assert sent['timestamp'] == '1599360473' and sent['sign'] == expected


def test_invalid_json_and_network_errors_do_not_leak_credentials(client):
    invalid = response()
    invalid.json.side_effect = ValueError(WEBHOOK + SECRET)
    for outcome in (invalid, web.requests.ConnectionError(WEBHOOK + SECRET)):
        with patch.object(web.requests, 'request', side_effect=[outcome]) as request:
            with pytest.raises(ValueError) as error:
                send({'webhook_url': WEBHOOK, 'sign_secret': SECRET})
        assert request.call_count == 1
        assert WEBHOOK not in str(error.value) and SECRET not in str(error.value)


def test_draft_test_uses_saved_values_but_does_not_save_or_deduplicate(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    web.set_setting_encrypted('feishu_sign_secret', SECRET)
    draft_webhook = WEBHOOK + '-draft'
    with patch.object(web.requests, 'request', return_value=response({'code': 0})) as request:
        result = client.post('/api/settings/test-forward-channel', json={
            'channel': 'feishu', 'config': {'feishu': {
                'webhook_url': draft_webhook, 'sign_secret': '', 'clear_sign_secret': True,
            }},
        }).get_json()
    assert result['success']
    assert request.call_args.args == ('post', draft_webhook)
    sent = json.loads(request.call_args.kwargs['data'])
    assert '邮件转发' in sent['content']['text'] and 'sign' not in sent
    assert web.get_setting_decrypted('feishu_webhook_url') == WEBHOOK
    assert web.get_setting_decrypted('feishu_sign_secret') == SECRET
    assert web.get_db().execute('SELECT COUNT(*) FROM forward_logs').fetchone()[0] == 0


@pytest.mark.parametrize('invalid', [
    'http://open.feishu.cn/open-apis/bot/v2/hook/token',
    'https://example.com/open-apis/bot/v2/hook/token',
    'https://open.feishu.cn@127.0.0.1/open-apis/bot/v2/hook/token',
    'https://open.feishu.cn:444/open-apis/bot/v2/hook/token',
    'https://open.feishu.cn/open-apis/bot/v2/hook/token#fragment',
    'https://open.feishu.cn/other', None, [],
])
def test_invalid_settings_rejected_before_any_settings_write(client, invalid):
    web.set_setting('forward_channels', 'none')
    result = client.put('/api/settings', json={
        'forward_channels': ['feishu'], 'feishu_webhook_url': invalid,
    }).get_json()
    assert result['success'] is False
    assert web.get_setting('forward_channels') == 'none'
    assert web.get_setting('feishu_webhook_url', '') == ''


def test_settings_auto_none_and_explicit_channels(client):
    assert 'feishu' not in web.get_forward_channels()
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    assert 'feishu' in web.get_forward_channels()
    web.set_setting('forward_channels', 'none')
    assert web.get_forward_channels() == []
    web.set_setting('forward_channels', 'smtp,feishu,feishu,wecom')
    assert web.get_forward_channels() == ['smtp', 'feishu', 'wecom']


@pytest.mark.parametrize('status', [302, 400, 500])
def test_http_errors_and_redirects_do_not_succeed_or_retry(client, status):
    with patch.object(web.requests, 'request', return_value=response({'code': 0}, status)) as request:
        with pytest.raises(ValueError, match=f'HTTP {status}'):
            send()
    request.assert_called_once()
    assert request.call_args.kwargs['allow_redirects'] is False


def test_payload_byte_limit_preserves_source_for_long_chinese_content(client):
    text = '邮件转发\n账号: primary@example.com\n发件人: sender@example.com\n主题: 通知\n\n' + '中文😀"' * 15000
    with patch.object(web.requests, 'request', return_value=response({'code': 0})) as request:
        assert send({'webhook_url': WEBHOOK, 'sign_secret': SECRET}, text)
    encoded = request.call_args.kwargs['data']
    assert len(encoded) <= 20 * 1024
    sent = json.loads(encoded)
    assert sent['content']['text'].startswith('邮件转发\n账号: primary@example.com\n发件人: sender@example.com')
    assert '内容已截断' in sent['content']['text']
    assert 'sign' in sent


def test_long_subject_uses_existing_summary_and_keeps_recipient_identity(client):
    _, _, _, text = web.build_forward_payload({'email': 'primary@example.com'}, {
        'subject': '长主题😀' * 10000, 'from': 'sender@example.com',
        'to': 'actual@example.com', 'cc': 'team@example.com', 'body': '长正文' * 10000,
    })
    with patch.object(web.requests, 'request', return_value=response({'code': 0})) as request:
        assert send(text=text)
    encoded = request.call_args.kwargs['data']
    assert len(encoded) <= 20 * 1024
    sent = json.loads(encoded)['content']['text']
    assert '账号: primary@example.com' in sent
    assert '收件人: actual@example.com' in sent and '抄送: team@example.com' in sent


class Clock:
    def __init__(self):
        self.value = 1000.0

    def now(self):
        return self.value

    def sleep(self, delay):
        self.value += delay


def test_saved_and_draft_sends_share_second_and_minute_rate_limits(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    clock = Clock()
    sent_at = []

    def request(*_args, **_kwargs):
        sent_at.append(clock.now())
        return response({'code': 0})

    with patch.object(web.time, 'monotonic', side_effect=clock.now), patch.object(
        web.time, 'sleep', side_effect=clock.sleep,
    ), patch.object(web.requests, 'request', side_effect=request):
        for index in range(101):
            assert web.send_forward_feishu('邮件转发') if index % 2 else send()
    for moment in sent_at:
        assert sum(moment <= sent < moment + 1 for sent in sent_at) <= 5
        assert sum(moment <= sent < moment + 60 for sent in sent_at) <= 100
    assert sent_at[-1] - sent_at[0] >= 60


def test_parallel_accounts_share_one_rate_limit(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    sent_at = []
    started = threading.Barrier(6)

    def request(*_args, **_kwargs):
        sent_at.append(time.monotonic())
        return response({'code': 0})

    def worker(_index):
        with web.app.app_context():
            started.wait(timeout=5)
            return web.send_forward_feishu('邮件转发')

    with patch.object(web.requests, 'request', side_effect=request), ThreadPoolExecutor(max_workers=6) as pool:
        assert all(pool.map(worker, range(6)))
    assert len(sent_at) == 6
    assert max(sent_at) - min(sent_at) >= 0.95


def test_equivalent_webhook_urls_use_canonical_endpoint_and_share_cooldown(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    equivalent = WEBHOOK.replace('https://open.feishu.cn', 'HTTPS://OPEN.FEISHU.CN:443')
    with patch.object(web.requests, 'request', return_value=response({}, 429, {'Retry-After': '120'})) as request:
        with pytest.raises(ValueError, match='限流'):
            send({'webhook_url': equivalent})
        with pytest.raises(ValueError, match='限流'):
            web.send_forward_feishu('邮件转发')
    request.assert_called_once()
    assert request.call_args.args == ('post', WEBHOOK)


@pytest.mark.parametrize('status,payload', [(429, {}), (200, {'code': 11232})])
def test_retry_after_cools_down_saved_and_draft_sends(client, status, payload):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    clock = Clock()
    with patch.object(web.time, 'monotonic', side_effect=clock.now), patch.object(
        web.requests, 'request', side_effect=[
            response(payload, status, {'Retry-After': '120'}), response({'code': 0}),
        ],
    ) as request:
        with pytest.raises(ValueError, match='限流'):
            send()
        with pytest.raises(ValueError, match='限流'):
            web.send_forward_feishu('邮件转发')
        assert request.call_count == 1
        clock.value += 120
        assert web.send_forward_feishu('邮件转发')
        assert request.call_count == 2


def test_permissions_and_csrf_prevent_any_send(client, monkeypatch):
    anonymous = web.app.test_client()
    with patch.object(web.requests, 'request') as request:
        assert anonymous.get('/api/settings').status_code == 401
        assert anonymous.put('/api/settings', json={'forward_channels': ['feishu']}).status_code == 401
        assert anonymous.post('/api/settings/test-forward-channel', json={'channel': 'feishu'}).status_code == 401
        if web.CSRF_AVAILABLE:
            monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', True)
            assert client.put('/api/settings', json={'feishu_webhook_url': WEBHOOK}).status_code == 400
            assert client.post('/api/settings/test-forward-channel', json={'channel': 'feishu'}).status_code == 400
        request.assert_not_called()


def test_reinitialization_preserves_saved_credentials_and_disabled_channel(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    web.set_setting_encrypted('feishu_sign_secret', SECRET)
    web.set_setting('forward_channels', 'none')
    encrypted = web.get_setting('feishu_sign_secret')
    web.init_db()
    assert web.get_setting('feishu_sign_secret') == encrypted
    assert web.get_forward_channels() == []
    with patch.object(web.requests, 'request') as request:
        result = web.process_forwarding_job()
    assert result['skipped'] and result['reason'] == 'no_active_channels'
    request.assert_not_called()


def test_draft_uses_saved_signature_and_failure_does_not_modify_settings(client):
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    web.set_setting_encrypted('feishu_sign_secret', SECRET)
    with patch.object(web.requests, 'request', return_value=response({'code': 19024, 'msg': WEBHOOK + SECRET})) as request:
        result = client.post('/api/settings/test-forward-channel', json={
            'channel': 'feishu', 'config': {'feishu': {'webhook_url': '', 'sign_secret': ''}},
        }).get_json()
    assert result['success'] is False and '关键词' in result['error']
    assert 'sign' in json.loads(request.call_args.kwargs['data'])
    assert WEBHOOK not in json.dumps(result) and SECRET not in json.dumps(result)
    assert web.get_setting_decrypted('feishu_webhook_url') == WEBHOOK
    assert web.get_setting_decrypted('feishu_sign_secret') == SECRET


def test_feishu_only_job_honors_keywords_and_reports_success(client):
    web.set_setting('forward_channels', 'feishu')
    web.set_setting('forward_keywords', 'notice')
    web.set_setting('forward_email_window_minutes', '0')
    web.set_setting_encrypted('feishu_webhook_url', WEBHOOK)
    db = web.get_db()
    cursor = db.execute(
        "INSERT INTO accounts (email, account_type, forward_enabled) VALUES ('feishu@example.com', 'imap', 1)",
    )
    db.commit()
    items = [
        {'id': 'match', 'folder': 'inbox', 'date': '2026-10-24T01:00:00Z'},
        {'id': 'filtered', 'folder': 'inbox', 'date': '2026-10-24T02:00:00Z'},
    ]
    with patch.object(web, 'fetch_forward_candidates', return_value={'success': True, 'emails': items}), patch.object(
        web, 'fetch_forward_detail', side_effect=lambda _account, message_id, _folder: {
            'id': message_id, 'subject': 'NOTICE' if message_id == 'match' else 'newsletter',
            'to': 'recipient@example.com', 'cc': 'team@example.com', 'body': 'hello',
        },
    ), patch.object(web.requests, 'request', return_value=response({'code': 0})) as request:
        result = web.process_forwarding_job()
        assert result['success'] and result['feishu_success_count'] == 1
        assert result['email_success_count'] == result['telegram_success_count'] == result['wecom_success_count'] == 0
        result = web.process_forwarding_job()
    assert request.call_count == 1
    text = json.loads(request.call_args.kwargs['data'])['content']['text']
    assert '邮件转发' in text and '收件人: recipient@example.com' in text and '抄送: team@example.com' in text
    assert result['feishu_success_count'] == 0
    logs = db.execute('SELECT channel, status FROM forwarding_logs WHERE account_id = ?', (cursor.lastrowid,)).fetchall()
    assert [tuple(log) for log in logs] == [('feishu', 'success')]
