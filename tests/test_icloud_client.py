import copy
import hashlib
import json
from pathlib import Path

import pytest
import requests

from outlook_web.icloud_client import ICloudClient
from outlook_web.icloud_fingerprint import account_fingerprint
from outlook_web.icloud_protocol import AppleProtocolError, SessionSnapshot
from dataclasses import asdict


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/icloud/protocol.json').read_text())


def test_account_fingerprint_matches_pinned_go_vector():
    vector = FIXTURE['account_fingerprint']
    assert account_fingerprint(vector['timestamp']) == vector['expected']


def test_web_login_http_200_still_requires_mfa_when_setup_is_not_trusted():
    body = {'dsInfo': {'dsid': '12345', 'appleId': 'test@example.com', 'countryCode': 'US', 'hsaVersion': 2},
            'hsaChallengeRequired': False, 'hsaTrustedBrowser': False, 'webservices': {}}
    http = ScriptedHTTP([
        ('GET', '/authorize/signin', 200, b'<html>widget</html>', {}),
        ('POST', '/federate', 200, {}, {}),
        ('POST', '/signin/init', 200, FIXTURE['challenge'], {}),
        ('POST', '/signin/complete', 200, {}, {'X-Apple-Session-Token': 'pending-token'}),
        ('POST', '/accountLogin', 200, body, {}),
        ('PUT', '/verify/trusteddevice/securitycode', 204, {}, {}),
    ])
    client = ICloudClient('test@example.com', 'global', 'web', http_factory=lambda: http)
    assert client.login('password')['state'] == 'verification_required'
    assert not http.script


class ScriptedHTTP(requests.Session):
    def __init__(self, script):
        super().__init__()
        self.script, self.calls = list(script), []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs['allow_redirects'] is False
        assert kwargs['stream'] is True
        assert 0 < kwargs['timeout'] <= 15
        assert self.trust_env is False
        expected_method, expected_path, status, body, headers = self.script.pop(0)
        assert method == expected_method
        assert expected_path in url
        if isinstance(body, Exception):
            raise body
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response._content = json.dumps(body).encode() if not isinstance(body, bytes) else body
        response._content_consumed = True
        return response


@pytest.mark.parametrize('region', ['global', 'cn'])
def test_native_account_login_and_code_use_global_management_and_isolated_widget(region):
    http = ScriptedHTTP([
        ('GET', '/account/manage/section/privacy', 200, b'<html>portal</html>', {}),
        ('GET', '/bootstrap/portal', 200, {'timeOutInterval': 15}, {}),
        ('GET', '/gs/ws/token', 401, {}, {'scnt': 'bootstrap-scnt'}),
        ('GET', '/authorize/signin', 200, b'<html>widget</html>', {'X-Apple-HC-Bits': '8', 'X-Apple-HC-Challenge': 'fixture'}),
        ('POST', '/verify/device/key/challenge', 200, {}, {}),
        ('POST', '/federate', 200, {}, {}),
        ('POST', '/signin/init', 200, FIXTURE['challenge'], {}),
        ('POST', '/signin/complete', 409, {}, {'scnt': 'account-scnt'}),
        ('GET', '/appleauth/auth', 200, b'<html>code requested</html>', {}),
        ('POST', '/verify/trusteddevice/securitycode', 200, {}, {'scnt': 'verified'}),
        ('GET', '/2sv/trust', 200, {}, {}),
        ('GET', '/gs/ws/token', 200, {'timeOutInterval': 15}, {'scnt': 'renewed'}),
        ('GET', '/account/manage', 200, {'apiKey': 'management-key'}, {}),
        ('GET', '/forwardemail', 200, {}, {}),
    ])
    client = ICloudClient('test@example.com', region, 'account', http_factory=lambda: http)
    assert client.login(' password ')['state'] == 'verification_required'
    assert client.verify('123456')['state'] == 'connected'
    assert 'X-Apple-HC' in http.calls[7][2]['headers']
    assert http.calls[9][2]['headers']['X-Apple-App-Id']
    assert 'X-Requested-With' not in http.calls[9][2]['headers']
    assert client.snapshot()['values']['api_key'] == 'management-key'
    assert all('icloud.com' not in url for _, url, _ in http.calls)
    assert not http.script


@pytest.mark.parametrize('region', FIXTURE['regions'], ids=lambda item: item['region'])
def test_native_web_login_code_exchange_and_directory(region):
    account = {'dsInfo': {'dsid': '12345', 'appleId': 'test@example.com', 'countryCode': region['country']},
               'webservices': {'premiummailsettings': {'url': region['premium']}}}
    http = ScriptedHTTP([
        ('GET', '/authorize/signin', 200, b'<html>login widget</html>', {}),
        ('POST', '/federate', 200, {}, {}),
        ('POST', '/signin/init', 200, FIXTURE['challenge'], {}),
        ('POST', '/signin/complete', 409, {}, {'scnt': 'web-scnt', 'X-Apple-ID-Session-Id': 'web-session'}),
        ('PUT', '/verify/trusteddevice/securitycode', 405, {}, {}),
        ('POST', '/verify/trusteddevice/securitycode', 204, {}, {'X-Apple-Session-Token': 'web-token'}),
        ('GET', '/2sv/trust', 200, {}, {'X-Apple-TwoSV-Trust-Token': 'web-trust'}),
        ('POST', '/accountLogin', 200, account, {'scnt': 'web-rotated'}),
        ('GET', '/v2/hme/list', 200, FIXTURE['web_directory'], {}),
    ])
    client = ICloudClient('test@example.com', region['region'], 'web', http_factory=lambda: http)
    assert client.login(' password ')['state'] == 'verification_required'
    assert client.verify('123456')['state'] == 'connected'
    assert client.snapshot()['values']['scnt'] == 'web-rotated'
    assert client.directory().authoritative
    exchange = http.calls[-2]
    assert exchange[1].startswith(region['setup'])
    assert exchange[2]['json']['extended_login'] is True
    assert 'api_key' not in client.snapshot()['values']
    assert not http.script
    assert all(' password ' not in json.dumps(call[2]['json']) for call in http.calls)


@pytest.mark.parametrize('region', FIXTURE['regions'], ids=lambda item: item['region'])
def test_web_verification_accepts_409_with_token_and_discovers_https_port(region):
    snapshot = asdict(SessionSnapshot(region['region'], 'web', 'test@example.com', 'verification_required',
                                     {'session_token': 'old-token'}))
    account = {'dsInfo': {'dsid': '12345', 'appleId': 'test@example.com', 'countryCode': region['country']},
               'webservices': {'premiummailsettings': {'url': region['premium'] + ':443'}}}
    http = ScriptedHTTP([
        ('POST', '/verify/trusteddevice/securitycode', 409, {}, {'X-Apple-Session-Token': 'accepted-token'}),
        ('GET', '/2sv/trust', 204, {}, {'X-Apple-TwoSV-Trust-Token': 'accepted-trust'}),
        ('POST', '/accountLogin', 200, account, {}),
        ('GET', '/v2/hme/list', 200, FIXTURE['web_directory'], {}),
    ])
    client = ICloudClient('test@example.com', region['region'], 'web', snapshot=snapshot, http_factory=lambda: http)
    try:
        assert client.verify('123456')['state'] == 'connected'
        assert http.calls[2][2]['json']['dsWebAuthToken'] == 'accepted-token'
        assert http.calls[2][2]['json']['trustToken'] == 'accepted-trust'
        assert client.directory().authoritative
        assert http.calls[-1][1].startswith(region['premium'] + ':443/')
        assert not http.script
    finally:
        client.close()


@pytest.mark.parametrize('channel,token', [('web', None), ('web', ''), ('account', 'accepted-token')])
def test_verification_rejects_409_without_web_session_token(channel, token):
    snapshot = asdict(SessionSnapshot('global', channel, 'test@example.com', 'verification_required',
                                     {'scnt': 'old-scnt', 'session_token': 'old-token'}))
    headers = {'scnt': 'rejected-scnt'}
    if token is not None:
        headers['X-Apple-Session-Token'] = token
    http = ScriptedHTTP([('POST', '/verify/trusteddevice/securitycode', 409, {}, headers)])
    client = ICloudClient('test@example.com', 'global', channel, snapshot=snapshot, http_factory=lambda: http)
    try:
        with pytest.raises(AppleProtocolError, match='invalid_code'):
            client.verify('123456')
        assert len(http.calls) == 1
        assert client.snapshot()['values']['session_token'] == 'old-token'
        assert client.snapshot()['values']['scnt'] == 'old-scnt'
    finally:
        client.close()


@pytest.mark.parametrize('body,kind', [
    ({'errorCode': -41015}, 'rate_limited'),
    ({'termsUpdateNeeded': True}, 'account_action_required'),
])
def test_verification_token_does_not_override_rate_limit_or_account_action(body, kind):
    snapshot = asdict(SessionSnapshot('global', 'web', 'test@example.com', 'verification_required'))
    http = ScriptedHTTP([('POST', '/verify/trusteddevice/securitycode', 409, body,
                         {'X-Apple-Session-Token': 'unaccepted-token'})])
    client = ICloudClient('test@example.com', 'global', 'web', snapshot=snapshot, http_factory=lambda: http)
    try:
        with pytest.raises(AppleProtocolError) as caught:
            client.verify('123456')
        assert caught.value.kind == kind
        assert len(http.calls) == 1 and 'session_token' not in client.snapshot()['values']
    finally:
        client.close()


@pytest.mark.parametrize('region', ['global', 'cn'])
def test_account_management_renewal_rotates_its_own_state_and_reads_resource(region):
    snapshot = asdict(SessionSnapshot(region, 'account', 'test@example.com', 'connected', {'scnt': 'old', 'api_key': 'old-key'}))
    http = ScriptedHTTP([
        ('GET', '/gs/ws/token', 200, {'timeOutInterval': 2}, {'scnt': 'rotated'}),
        ('GET', '/account/manage', 200, {'apiKey': 'new-key'}, {}),
        ('GET', '/forwardemail', 200, {}, {}),
    ])
    client = ICloudClient('test@example.com', region, 'account', snapshot=snapshot, clock=lambda: 1700000000, http_factory=lambda: http)
    result = client.renew()
    assert result['values']['scnt'] == 'rotated'
    assert result['values']['api_key'] == 'new-key'
    assert client.expires_at == 1700000120
    assert http.calls[0][2]['headers'].get('X-Apple-Api-Key') is None
    assert http.calls[-1][2]['headers']['X-Apple-Api-Key'] == 'new-key'
    assert all('icloud.com' not in call[1] for call in http.calls)


def test_temporary_renewal_failure_does_not_replay_login_or_lose_accepted_rotation():
    snapshot = asdict(SessionSnapshot('global', 'account', 'test@example.com', 'connected', {'scnt': 'old'}))
    http = ScriptedHTTP([
        ('GET', '/gs/ws/token', 200, {'timeOutInterval': 15}, {'scnt': 'accepted'}),
        ('GET', '/account/manage', 503, b'<html>upstream unavailable</html>', {'scnt': 'rejected', 'Retry-After': '3600'}),
    ])
    client = ICloudClient('test@example.com', 'global', 'account', snapshot=snapshot, http_factory=lambda: http)
    with pytest.raises(AppleProtocolError) as caught:
        client.renew()
    assert caught.value.kind == 'temporary_failure' and caught.value.retry_after == 3600
    assert client.snapshot()['values']['scnt'] == 'accepted'
    assert not http.script and len(http.calls) == 2


def test_web_421_exchanges_token_once_and_checks_identity():
    snapshot = asdict(SessionSnapshot('cn', 'web', 'test@example.com', 'connected', {'dsid': '12345', 'session_token': 'saved', 'trust_token': 'trusted'}))
    body = {'dsInfo': {'dsid': '99999', 'appleId': 'test@example.com', 'countryCode': 'CN'}, 'webservices': {}}
    http = ScriptedHTTP([('POST', '/validate', 421, {}, {}), ('POST', '/accountLogin', 200, body, {})])
    client = ICloudClient('test@example.com', 'cn', 'web', snapshot=snapshot, http_factory=lambda: http)
    with pytest.raises(AppleProtocolError, match='session_identity_mismatch'):
        client.renew()
    assert len(http.calls) == 2


def test_redirect_and_transport_errors_are_safe_and_never_replayed():
    for status, body, kind in [(302, {}, 'redirect_rejected'), (500, requests.Timeout('https://secret/?password=hidden'), 'temporary_failure')]:
        http = ScriptedHTTP([('GET', '/authorize/signin', status, body, {'Location': 'https://evil.example/'})])
        client = ICloudClient('test@example.com', 'global', 'web', http_factory=lambda: http)
        with pytest.raises(AppleProtocolError) as caught:
            client.login('secret-password')
        assert caught.value.kind == kind and 'hidden' not in str(caught.value)
        assert len(http.calls) == 1


def test_mutation_timeout_is_sent_once_and_cancellation_prevents_any_request():
    snapshot = asdict(SessionSnapshot('global', 'web', 'test@example.com', 'connected', {'dsid': '123', 'premium_url': 'https://p01-maildomainws.icloud.com'}))
    http = ScriptedHTTP([('POST', '/reserve', 500, requests.Timeout('private body'), {})])
    client = ICloudClient('test@example.com', 'global', 'web', snapshot=snapshot, http_factory=lambda: http)
    with pytest.raises(AppleProtocolError, match='temporary_failure'):
        client.mutate('reserve', {'hme': 'a@icloud.com'})
    assert len(http.calls) == 1
    http = ScriptedHTTP([])
    client = ICloudClient('test@example.com', 'global', 'web', cancelled=lambda: True, http_factory=lambda: http)
    with pytest.raises(AppleProtocolError, match='cancelled'):
        client.login('password')
    assert not http.calls


def test_hashcash_is_bounded_and_matches_apple_sha1_proof_shape():
    client = ICloudClient('test@example.com', 'global', 'account', clock=lambda: 1700000000)
    proof = client.hashcash('8', 'synthetic-challenge')
    assert proof.startswith('1:8:20231114221320:synthetic-challenge::')
    assert hashlib.sha1(proof.encode()).digest()[0] == 0
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        client.hashcash('25', 'synthetic-challenge')
