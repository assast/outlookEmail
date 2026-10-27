"""Offline contracts only: these fixtures do not demonstrate live Apple support."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from outlook_web.icloud_protocol import (
    ACCOUNT_ROOT, AUTH_ROOT, AppleProtocolError, SessionSnapshot, decode_directory,
    decode_account_api_key, decode_account_token, decode_srp_challenge, decode_web_account, endpoints, login_checkpoint,
    response_error, retry_after_seconds, security_code_payload, validate_service_url,
)


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/icloud/protocol.json').read_text())
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


@pytest.fixture(params=FIXTURE['regions'], ids=lambda item: item['region'])
def region(request):
    return request.param


@pytest.fixture(params=['web', 'account'])
def channel(request):
    return request.param


def web_account(region):
    return {
        'dsInfo': {'dsid': '12345', 'appleId': 'test@example.com', 'countryCode': region['country']},
        'webservices': {'premiummailsettings': {'url': region['premium']}},
        'hsaChallengeRequired': False,
    }


def test_region_endpoint_contract(region):
    actual = endpoints(region['region'])
    assert actual['auth'] == AUTH_ROOT
    assert actual['home'] == region['home']
    assert actual['setup'] == region['setup']
    assert actual['account'] == ACCOUNT_ROOT
    assert validate_service_url(actual['auth'], region['region'], 'web')
    assert validate_service_url(actual['setup'], region['region'], 'web')
    assert validate_service_url(region['premium'] + '/v2/hme/list?dsid=12345', region['region'], 'web')


def test_web_service_discovery_accepts_standard_https_port(region):
    premium = region['premium'] + ':443'
    assert validate_service_url(premium, region['region'], 'web') == premium
    assert validate_service_url(AUTH_ROOT.replace('apple.com', 'apple.com:443'), region['region'], 'web')
    payload = web_account(region)
    payload['webservices']['premiummailsettings']['url'] = premium
    values = decode_web_account(payload, region['region'], 'test@example.com')
    assert SessionSnapshot(region['region'], 'web', 'test@example.com', 'connected', values).values['premium_url'] == premium


def test_account_channel_rejects_explicit_https_port(region):
    for host in ('idmsa.apple.com', 'account.apple.com', 'appleid.apple.com'):
        with pytest.raises(AppleProtocolError, match='invalid_target'):
            validate_service_url('https://' + host + ':443/', region['region'], 'account')


def test_srp_and_verification_checkpoints_are_not_connected(region, channel):
    original = SessionSnapshot(region['region'], channel, 'test@example.com', 'signed_out')
    challenge = decode_srp_challenge(FIXTURE['challenge'])
    assert challenge.protocol == 's2k_fo'
    assert len(challenge.server_public) == 256
    pending = login_checkpoint(original, 409, {}, {'scnt': 'synthetic-scnt', 'X-Apple-ID-Session-Id': 'synthetic-session'})
    assert pending.state == 'verification_required'
    assert pending.values['scnt'] == 'synthetic-scnt'
    assert original.state == 'signed_out'
    assert original.values == {}
    assert security_code_payload('123456') == {'securityCode': {'code': '123456'}}
    accepted = login_checkpoint(pending, 200, {}, {'scnt': 'synthetic-rotated-scnt'})
    assert accepted.state == 'service_pending'
    assert accepted.values['scnt'] != pending.values['scnt']
    assert 'synthetic-scnt' not in repr(pending)
    assert 'synthetic-session' not in repr(pending)


def test_snapshot_rejects_cross_identity_and_channel(region, channel):
    snapshot = SessionSnapshot(region['region'], channel, 'test@example.com', 'connected')
    snapshot.require_identity(region['region'], channel, ' TEST@example.com ')
    for scope in [
        (region['region'], 'account' if channel == 'web' else 'web', 'test@example.com'),
        ('cn' if region['region'] == 'global' else 'global', channel, 'test@example.com'),
        (region['region'], channel, 'other@example.com'),
    ]:
        with pytest.raises(AppleProtocolError, match='session_identity_mismatch'):
            snapshot.require_identity(*scope)


def test_snapshot_rejects_other_channel_fields_and_cookies(region, channel):
    field = 'api_key' if channel == 'web' else 'dsid'
    with pytest.raises(AppleProtocolError, match='invalid_session'):
        SessionSnapshot(region['region'], channel, 'test@example.com', 'connected', {field: 'secret'})
    for domain in ['localhost', 'evil.example', 'apple.com.evil.example']:
        with pytest.raises(AppleProtocolError, match='invalid_session'):
            SessionSnapshot(region['region'], channel, 'test@example.com', 'connected', cookies=(
                {'domain': domain, 'name': 'cookie', 'value': 'secret'},
            ))
    other_channel_cookie = 'appleid.apple.com' if channel == 'web' else 'icloud.com'
    with pytest.raises(AppleProtocolError, match='invalid_session'):
        SessionSnapshot(region['region'], channel, 'test@example.com', 'connected', cookies=(
            {'domain': other_channel_cookie, 'name': 'cookie', 'value': 'secret'},
        ))


def test_snapshot_copies_caller_containers():
    values = {'scnt': 'old'}
    cookies = [{'domain': 'idmsa.apple.com', 'name': 'session', 'value': 'old'}]
    session = SessionSnapshot('global', 'web', 'test@example.com', 'service_pending', values, cookies)
    values['scnt'] = 'new'
    cookies[0]['value'] = 'new'
    assert session.values['scnt'] == 'old'
    assert session.cookies[0]['value'] == 'old'


def test_web_recovery_validates_identity_and_service_region(region):
    result = decode_web_account(web_account(region), region['region'], 'test@example.com', '12345')
    assert result == {'dsid': '12345', 'country_code': region['country'], 'premium_url': region['premium']}
    for change in [{'dsid': '54321'}, {'appleId': 'other@example.com'}]:
        payload = web_account(region)
        payload['dsInfo'].update(change)
        with pytest.raises(AppleProtocolError, match='session_identity_mismatch'):
            decode_web_account(payload, region['region'], 'test@example.com', '12345')
    payload = web_account(region)
    payload['hsaChallengeRequired'] = True
    with pytest.raises(AppleProtocolError, match='verification_required'):
        decode_web_account(payload, region['region'], 'test@example.com')
    payload = web_account(region)
    other_region = FIXTURE['regions'][1 if region['region'] == 'global' else 0]
    payload['webservices']['premiummailsettings']['url'] = other_region['premium']
    with pytest.raises(AppleProtocolError, match='invalid_target'):
        decode_web_account(payload, region['region'], 'test@example.com')


def test_account_recovery_keeps_its_key_and_ttl_separate_from_web(region):
    expires = decode_account_token({'timeOutInterval': 15}, NOW)
    assert (expires - NOW).total_seconds() == 900
    key = decode_account_api_key({'apiKey': 'synthetic-api-key'})
    account = SessionSnapshot(region['region'], 'account', 'test@example.com', 'connected', {'api_key': key})
    web = SessionSnapshot(region['region'], 'web', 'test@example.com', 'connected', decode_web_account(
        web_account(region), region['region'], 'test@example.com',
    ))
    assert 'api_key' not in web.values
    assert 'premium_url' not in account.values
    assert 'synthetic-api-key' not in repr(account)
    assert response_error(401, {}, 'account_renew').kind == 'session_expired'
    assert web.state == 'connected'
    assert response_error(503, {}, 'account_renew').retryable
    assert account.values['api_key'] == key


@pytest.mark.parametrize('payload', [{}, {'timeOutInterval': 0}, {'timeOutInterval': 1441},
                                     {'timeOutInterval': True}, {'timeOutInterval': '15'}, None])
def test_account_token_rejects_invalid_ttl(payload):
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_account_token(payload, NOW)


@pytest.mark.parametrize('payload', [{}, {'apiKey': ''}, {'apiKey': None}, {'apiKey': 123}, None])
def test_account_recovery_cannot_reuse_web_service_response(payload):
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_account_api_key(payload)


@pytest.mark.parametrize('url', [
    'http://idmsa.apple.com/appleauth/auth', 'https://idmsa.apple.com.evil.example/',
    'https://user:secret@idmsa.apple.com/', 'https://idmsa.apple.com:8443/',
    'https://idmsa.apple.com:80/', 'https://idmsa.apple.com:0/', 'https://idmsa.apple.com:/',
    'https://127.0.0.1/', 'https://[::1]/', 'https://icloud.com.evil.example/',
    'https://appleid.apple.com:invalid/', 'https://idmsa.apple.com/#secret',
    'https://idmsa.apple.com\n.evil.example/', 'https://idmsa.apple.com\\@evil.example/',
])
def test_rejects_unsafe_targets_before_transport(region, channel, url):
    with pytest.raises(AppleProtocolError, match='invalid_target'):
        validate_service_url(url, region['region'], channel)


@pytest.mark.parametrize('status,payload,step,kind,retryable', [
    (0, {}, 'web_validate', 'temporary_failure', True),
    (503, {}, 'account_renew', 'temporary_failure', True),
    (429, {}, 'account_renew', 'rate_limited', True),
    (200, {'success': False, 'errorCode': -41015}, 'directory', 'rate_limited', True),
    (412, {'ineligibilityReason': 'rate_limit_exceeded'}, 'directory', 'rate_limited', True),
    (401, {}, 'sign_in', 'authentication_failed', False),
    (401, {}, 'web_validate', 'session_expired', False),
    (419, {}, 'account_renew', 'session_expired', False),
    (403, {}, 'directory', 'directory_authentication', False),
    (422, {}, 'verify_code', 'invalid_code', False),
    (412, {}, 'sign_in', 'account_action_required', False),
    (200, {'termsUpdateNeeded': True}, 'web_validate', 'account_action_required', False),
    (421, {}, 'web_validate', 'web_token_exchange_required', False),
    (302, {}, 'account_renew', 'redirect_rejected', False),
    (200, {'success': False}, 'directory', 'service_error', False),
])
def test_error_classification_preserves_safe_retry_hint(status, payload, step, kind, retryable):
    body = dict(payload, errorMessage='secret-token', raw_url='https://code.example/?password=secret')
    failure = response_error(status, body, step, '7200', NOW)
    assert failure.kind == kind
    assert failure.retryable == retryable
    assert failure.retry_after == 7200
    assert 'secret' not in str(failure)
    assert 'secret' not in repr(failure)


def test_rejected_login_does_not_rotate_the_checkpoint(region, channel):
    original = SessionSnapshot(region['region'], channel, 'test@example.com', 'verification_required', {'scnt': 'old'})
    with pytest.raises(AppleProtocolError, match='authentication_failed'):
        login_checkpoint(original, 401, {}, {'scnt': 'rejected'})
    assert original.values == {'scnt': 'old'}


@pytest.mark.parametrize('raw,seconds', [
    ('120', 120), ('Sat, 24 Oct 2026 13:00:00 GMT', 3600),
    ('Sat, 24 Oct 2026 11:00:00 GMT', 0), ('-1', 0), ('120x', 0), ('', 0),
])
def test_retry_after(raw, seconds):
    assert retry_after_seconds(raw, NOW) == seconds


def test_retry_after_does_not_shorten_long_server_deadlines():
    assert retry_after_seconds('10000000000000', NOW) >= 10**13


@pytest.mark.parametrize('change', [
    {'salt': '!not-base64!'}, {'salt': ''}, {'b': ''}, {'b': 'AA=='},
    {'iteration': 0}, {'iteration': True}, {'iteration': 10_000_001},
    {'iteration': '1000'}, {'protocol': 'unknown'}, {'c': ''}, {'c': None},
])
def test_invalid_challenges_have_safe_errors(change):
    payload = dict(FIXTURE['challenge'], **change)
    with pytest.raises(AppleProtocolError, match='invalid_response') as caught:
        decode_srp_challenge(payload)
    assert 'fixture-challenge' not in str(caught.value)


@pytest.mark.parametrize('code', ['12345', '1234567', '１２３４５６', ' 123456 ', '', None])
def test_invalid_code_never_becomes_a_request(code):
    with pytest.raises(AppleProtocolError, match='invalid_code'):
        security_code_payload(code)


def test_both_directory_protocols_and_authority_boundary(region):
    web = decode_directory(copy.deepcopy(FIXTURE['web_directory']), 'web')
    account = decode_directory(copy.deepcopy(FIXTURE['account_directory']), 'account')
    assert web.authoritative is True
    assert account.authoritative is False
    assert [item.address for item in web.aliases] == [item.address for item in account.aliases]
    assert [item.active for item in web.aliases] == [True, False]
    assert web.aliases[0].remote_id != account.aliases[0].remote_id
    assert web.aliases[0].forward_to == 'receiver@example.com'
    assert web.aliases[0].label == '测试标签'


def test_explicit_empty_directory_is_distinct_from_missing():
    web = decode_directory({'success': True, 'result': {'hmeEmails': []}}, 'web')
    account = decode_directory({'forwardToEmailAddress': 'receiver@example.com', 'privateEmailList': [], 'inactivePrivateEmailList': []}, 'account')
    assert web.authoritative and web.aliases == ()
    assert not account.authoritative and account.aliases == ()
    for payload in [{}, {'success': True}, {'success': True, 'result': {}},
                    {'success': True, 'result': {'hmeEmails': None}}]:
        with pytest.raises(AppleProtocolError):
            decode_directory(payload, 'web')


@pytest.mark.parametrize('change', [
    {'hme': ''}, {'hme': 'display <synthetic@icloud.com>'}, {'isActive': 1},
    {'anonymousId': ''}, {'anonymousId': None}, {'forwardToEmail': ''},
    {'label': None}, {'note': {}},
])
def test_invalid_web_rows_cannot_be_authoritative(change):
    payload = copy.deepcopy(FIXTURE['web_directory'])
    payload['result']['hmeEmails'][0].update(change)
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, 'web')


@pytest.mark.parametrize('channel', ['web', 'account'])
def test_pagination_and_duplicate_rows_are_rejected(channel):
    payload = copy.deepcopy(FIXTURE[channel + '_directory'])
    payload['metadata'] = {'nextCursor': None}
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, channel)
    payload = copy.deepcopy(FIXTURE[channel + '_directory'])
    if channel == 'web':
        payload['result'].pop('total')
        rows = payload['result']['hmeEmails']
    else:
        rows = payload['privateEmailList']
    rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, channel)


@pytest.mark.parametrize('count', [0, 3, True, '2', None])
def test_web_total_must_prove_completeness(count):
    payload = copy.deepcopy(FIXTURE['web_directory'])
    payload['result']['total'] = count
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, 'web')


def test_account_directory_only_skips_exact_relay_domain():
    payload = copy.deepcopy(FIXTURE['account_directory'])
    payload['privateEmailList'][1]['emailAddress'] = 'relay@privaterelay.appleid.com.evil.example'
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, 'account')


@pytest.mark.parametrize('forward', [None, 0, False, {}, []])
def test_account_per_alias_forwarding_must_be_a_string(forward):
    payload = copy.deepcopy(FIXTURE['account_directory'])
    payload['privateEmailList'][0]['forwardToEmail'] = forward
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, 'account')


def test_account_active_flag_must_match_its_directory_group():
    payload = copy.deepcopy(FIXTURE['account_directory'])
    payload['inactivePrivateEmailList'][0]['active'] = True
    with pytest.raises(AppleProtocolError, match='invalid_response'):
        decode_directory(payload, 'account')
