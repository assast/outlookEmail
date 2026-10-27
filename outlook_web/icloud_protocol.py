"""Offline Apple protocol contracts; HTTP orchestration is not implemented here.

Protocol source: t508708/icloud-mail internal/apple/, commit
a2b952c2b50992c15f0f54dff23a15a234189a50 (MIT).
Copyright (c) 2026 t508708. See third_party/icloud-mail-LICENSE.txt.
"""

import base64
import binascii
import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from outlook_web.icloud_srp import N


AUTH_ROOT = 'https://idmsa.apple.com/appleauth/auth'
ACCOUNT_ROOT = 'https://appleid.apple.com'
ACCOUNT_PORTAL = 'https://account.apple.com'
WEB_WIDGET = 'd39ba9916b7251055b22c7f910e2ea796ee65e98b2ddecea8f5dde8d9d1a815d'
ACCOUNT_WIDGET = 'af1139274f266b22b68c2a3e7ad932cb3c0bbe854e13a79af78dcc73136882c3'
_STEPS = {'sign_in', 'verify_code', 'web_validate', 'account_renew', 'directory', 'protocol'}


class AppleProtocolError(Exception):
    """Only safe metadata. Retryable never authorizes replaying a mutation."""

    def __init__(self, kind, step='protocol', status=0, retry_after=0):
        if step not in _STEPS:
            raise ValueError('Invalid Apple protocol step')
        self.kind = kind
        self.step = step
        self.status = status
        self.retry_after = retry_after
        self.retryable = kind in {'temporary_failure', 'rate_limited'}
        super().__init__(f'Apple {step}: {kind} (HTTP {status})')


def _invalid():
    return AppleProtocolError('invalid_response')


def _scope(region, channel):
    if region not in {'global', 'cn'} or channel not in {'web', 'account'}:
        raise AppleProtocolError('invalid_configuration')


def _identity(region, channel, apple_id):
    _scope(region, channel)
    if not isinstance(apple_id, str) or not apple_id.strip():
        raise AppleProtocolError('invalid_configuration')
    return apple_id.strip().lower()


def endpoints(region: str) -> dict:
    _scope(region, 'web')
    suffix = 'icloud.com.cn' if region == 'cn' else 'icloud.com'
    return {
        'auth': AUTH_ROOT,
        'home': f'https://www.{suffix}',
        'setup': f'https://setup.{suffix}/setup/ws/1',
        'account': ACCOUNT_ROOT,
        'portal': ACCOUNT_PORTAL,
    }


def validate_service_url(raw: str, region: str, channel: str) -> str:
    """Validate before any request, including a redirect or discovered service."""
    _scope(region, channel)
    try:
        if not isinstance(raw, str) or re.search(r'[\s\\]', raw):
            raise ValueError
        parsed = urlsplit(raw)
        if (parsed.scheme != 'https' or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or (':' in parsed.netloc and (channel != 'web' or not parsed.netloc.endswith(':443')))
                or parsed.fragment):
            raise ValueError
        host = parsed.hostname
        auth = host == 'idmsa.apple.com'
        if channel == 'account':
            allowed = host in {'idmsa.apple.com', 'account.apple.com', 'appleid.apple.com'}
        else:
            suffix = 'icloud.com.cn' if region == 'cn' else 'icloud.com'
            allowed = auth or host == suffix or bool(host and host.endswith('.' + suffix))
        if not allowed:
            raise ValueError
    except (TypeError, ValueError):
        raise AppleProtocolError('invalid_target') from None
    return raw


def retry_after_seconds(value: str, now: datetime) -> float:
    value = str(value or '').strip()
    if re.fullmatch(r'[0-9]+', value):
        return float(value)
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return max(0, (deadline - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0


def response_error(status: int, payload, step: str, retry_after='', now=None):
    """Classify without retaining upstream messages, URLs, or response bodies."""
    if step not in _STEPS:
        raise ValueError('Invalid Apple protocol step')
    now = now or datetime.now(timezone.utc)
    body = payload if isinstance(payload, dict) else {}
    errors = body.get('serviceErrors')
    codes = [body.get('errorCode'), body.get('code')]
    if isinstance(errors, list):
        codes += [item.get('code') for item in errors if isinstance(item, dict)]
    if (status == 429 or any(str(code) == '-41015' for code in codes)
            or body.get('ineligibilityReason') == 'rate_limit_exceeded'):
        kind = 'rate_limited'
    elif status == 0 or 500 <= status <= 599:
        kind = 'temporary_failure'
    elif status == 412 or body.get('termsUpdateNeeded') is True or body.get('isRepairNeeded') is True:
        kind = 'account_action_required'
    elif step == 'verify_code' and status in {400, 401, 403, 409, 422}:
        kind = 'invalid_code'
    elif status in {401, 403, 419, 450}:
        if step == 'sign_in':
            kind = 'authentication_failed'
        elif step == 'directory':
            kind = 'directory_authentication'
        else:
            kind = 'session_expired'
    elif step == 'web_validate' and status == 421:
        kind = 'web_token_exchange_required'
    elif 300 <= status <= 399:
        kind = 'redirect_rejected'
    elif (200 <= status <= 299 or step == 'sign_in' and status == 409):
        if body.get('success') is False or errors or any(code not in (None, '', 0, '0') for code in codes):
            kind = 'service_error'
        else:
            return None
    else:
        kind = 'service_error'
    return AppleProtocolError(kind, step, status, retry_after_seconds(retry_after, now))


@dataclass(frozen=True)
class SRPChallenge:
    salt: bytes = field(repr=False)
    server_public: bytes = field(repr=False)
    challenge: str = field(repr=False)
    iterations: int
    protocol: str


def decode_srp_challenge(payload) -> SRPChallenge:
    try:
        if not isinstance(payload, dict):
            raise ValueError
        salt = base64.b64decode(payload['salt'], validate=True)
        server = base64.b64decode(payload['b'], validate=True)
        iteration, protocol, challenge = payload['iteration'], payload['protocol'], payload['c']
        if (not 1 <= len(salt) <= 1024 or not 1 <= len(server) <= 256
                or not 0 < int.from_bytes(server, 'big') < N
                or type(iteration) is not int or not 1 <= iteration <= 10_000_000
                or protocol not in {'s2k', 's2k_fo'}
                or not isinstance(challenge, str) or not 1 <= len(challenge) <= 4096):
            raise ValueError
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise _invalid() from None
    return SRPChallenge(salt, server, challenge, iteration, protocol)


def security_code_payload(code: str) -> dict:
    if not isinstance(code, str) or re.fullmatch(r'[0-9]{6}', code) is None:
        raise AppleProtocolError('invalid_code', 'verify_code')
    return {'securityCode': {'code': code}}


def decode_account_token(payload, now: datetime) -> datetime:
    """Account token TTL is in minutes; it says nothing about Web trust."""
    if not isinstance(payload, dict):
        raise _invalid()
    minutes = payload.get('timeOutInterval')
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise _invalid()
    return now + timedelta(minutes=minutes)


def decode_account_api_key(payload) -> str:
    if not isinstance(payload, dict):
        raise _invalid()
    key = payload.get('apiKey')
    if not isinstance(key, str) or not key.strip():
        raise _invalid()
    return key


_COMMON_FIELDS = {'scnt', 'session_id', 'session_token', 'trust_token', 'frame_id', 'auth_attributes'}
_CHANNEL_FIELDS = {
    'web': _COMMON_FIELDS | {'dsid', 'country_code', 'premium_url', 'client_id'},
    'account': _COMMON_FIELDS | {'api_key'},
}


@dataclass(frozen=True)
class SessionSnapshot:
    """Tagged protocol snapshot; callers must encrypt before persistence."""

    region: str
    channel: str
    apple_id: str
    state: str
    values: dict = field(default_factory=dict, repr=False)
    cookies: tuple = field(default_factory=tuple, repr=False)

    def __post_init__(self):
        normalized = _identity(self.region, self.channel, self.apple_id)
        if normalized != self.apple_id or self.state not in {
                'signed_out', 'verification_required', 'service_pending', 'connected'}:
            raise AppleProtocolError('invalid_session')
        if not isinstance(self.values, dict) or set(self.values) - _CHANNEL_FIELDS[self.channel]:
            raise AppleProtocolError('invalid_session')
        if any(not isinstance(value, str) for value in self.values.values()):
            raise AppleProtocolError('invalid_session')
        if self.channel == 'web' and self.values.get('premium_url'):
            validate_service_url(self.values['premium_url'], self.region, self.channel)
        for cookie in self.cookies:
            if not isinstance(cookie, dict) or not isinstance(cookie.get('domain'), str):
                raise AppleProtocolError('invalid_session')
            domain = cookie['domain'].lstrip('.')
            suffix = 'icloud.com.cn' if self.region == 'cn' else 'icloud.com'
            common = domain in {'apple.com', 'idmsa.apple.com'}
            if self.channel == 'account':
                allowed = common or domain in {'account.apple.com', 'appleid.apple.com'}
            else:
                allowed = common or domain == suffix or domain.endswith('.' + suffix)
            if not allowed or not cookie.get('name') or not isinstance(cookie.get('value'), str):
                raise AppleProtocolError('invalid_session')
        # Do not retain mutable containers supplied by the caller.
        object.__setattr__(self, 'values', copy.deepcopy(self.values))
        object.__setattr__(self, 'cookies', tuple(copy.deepcopy(self.cookies)))

    def require_identity(self, region, channel, apple_id):
        normalized = _identity(region, channel, apple_id)
        if (self.region, self.channel, self.apple_id) != (region, channel, normalized):
            raise AppleProtocolError('session_identity_mismatch')


def login_checkpoint(session: SessionSnapshot, status: int, payload, headers: dict) -> SessionSnapshot:
    """SRP acceptance alone never means the management channel is connected."""
    failure = response_error(status, payload, 'sign_in')
    if failure:
        raise failure
    if status not in {200, 409}:
        raise _invalid()
    names = {
        'scnt': 'scnt', 'x-apple-id-session-id': 'session_id',
        'x-apple-session-token': 'session_token', 'x-apple-twosv-trust-token': 'trust_token',
        'x-apple-auth-attributes': 'auth_attributes',
    }
    values = dict(session.values)
    for name, value in headers.items():
        target = names.get(name.lower())
        if target and isinstance(value, str) and value:
            values[target] = value
    state = 'verification_required' if status == 409 else 'service_pending'
    return SessionSnapshot(session.region, session.channel, session.apple_id, state, values, session.cookies)


def decode_web_account(payload, region: str, expected_apple_id: str, expected_dsid='') -> dict:
    """Validate the Web service exchange before replacing a saved checkpoint."""
    expected_apple_id = _identity(region, 'web', expected_apple_id)
    if not isinstance(payload, dict):
        raise _invalid()
    failure = response_error(200, payload, 'web_validate')
    if failure:
        raise failure
    info = payload.get('dsInfo')
    if not isinstance(info, dict):
        raise _invalid()
    dsid = info.get('dsid')
    if type(dsid) not in {str, int} or not re.fullmatch(r'[0-9]+', str(dsid)):
        raise _invalid()
    if ((expected_dsid and str(dsid) != expected_dsid)
            or str(info.get('appleId', '')).strip().lower() != expected_apple_id
            or region == 'global' and str(info.get('countryCode', '')).upper() == 'CN'):
        raise AppleProtocolError('session_identity_mismatch')
    hsa_version = info.get('hsaVersion', 0)
    if type(hsa_version) is not int or any(key in payload and type(payload[key]) is not bool for key in ('hsaChallengeRequired', 'hsaTrustedBrowser')):
        raise _invalid()
    if payload.get('hsaChallengeRequired') is True or hsa_version >= 1 and not payload.get('hsaTrustedBrowser', False):
        raise AppleProtocolError('verification_required')
    services = payload.get('webservices')
    if not isinstance(services, dict):
        raise _invalid()
    premium = services.get('premiummailsettings', {})
    if not isinstance(premium, dict):
        raise _invalid()
    url = premium.get('url', '')
    if url:
        validate_service_url(url, region, 'web')
        if urlsplit(url).hostname == 'idmsa.apple.com':
            raise AppleProtocolError('invalid_target')
    return {'dsid': str(dsid), 'premium_url': url, 'country_code': str(info.get('countryCode', ''))}


@dataclass(frozen=True)
class HiddenAddress:
    remote_id: str
    address: str
    forward_to: str
    active: bool
    label: str = ''
    note: str = ''


@dataclass(frozen=True)
class DirectorySnapshot:
    channel: str
    aliases: tuple[HiddenAddress, ...]
    authoritative: bool


def _address(value):
    if (not isinstance(value, str) or value != value.strip()
            or not re.fullmatch(r'[^\s<>,;"()@]+@[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', value)):
        raise _invalid()
    return value.lower()


def _complete(value, count=None):
    pagination = {
        'next', 'cursor', 'page', 'pagination', 'paging', 'hasmore', 'has_more',
        'hasnext', 'has_next', 'offset', 'continuationtoken', 'continuation_token',
        'nexttoken', 'next_token', 'nextpage', 'next_page', 'nextcursor', 'next_cursor',
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in pagination:
                raise _invalid()
            if count is not None and key.lower() in {'total', 'totalcount', 'total_count'}:
                if type(child) is not int or child != count:
                    raise _invalid()
            _complete(child, count)
    elif isinstance(value, list):
        for child in value:
            _complete(child, count)


def _hidden_address(row, channel, forward='', active=None):
    if not isinstance(row, dict):
        raise _invalid()
    identity = row.get('anonymousId' if channel == 'web' else 'id')
    if not isinstance(identity, str) or not 1 <= len(identity) <= 1024 or identity.strip() != identity:
        raise _invalid()
    address = _address(row.get('hme' if channel == 'web' else 'emailAddress'))
    if address.rsplit('@', 1)[1] != 'icloud.com':
        raise _invalid()
    target = row.get('forwardToEmail', forward)
    if not isinstance(target, str):
        raise _invalid()
    forward = _address(target or forward)
    state_key = 'isActive' if channel == 'web' else 'active'
    state = row.get(state_key, active)
    if type(state) is not bool or active is not None and state != active:
        raise _invalid()
    label, note = row.get('label', ''), row.get('note', '')
    if not isinstance(label, str) or not isinstance(note, str):
        raise _invalid()
    return HiddenAddress(identity, address, forward, state, label, note)


def decode_directory(payload, channel: str) -> DirectorySnapshot:
    """Account directory success never makes its omissions authoritative."""
    if channel not in {'web', 'account'} or not isinstance(payload, dict):
        raise _invalid()
    failure = response_error(200, payload, 'directory')
    if failure:
        raise failure
    _complete(payload)
    result = []
    if channel == 'web':
        if payload.get('success') is not True or not isinstance(payload.get('result'), dict):
            raise _invalid()
        rows = payload['result'].get('hmeEmails')
        if not isinstance(rows, list):
            raise _invalid()
        _complete(payload, len(rows))
        result = [_hidden_address(row, channel) for row in rows]
    else:
        forward = _address(payload.get('forwardToEmailAddress'))
        for key, active in [('privateEmailList', True), ('inactivePrivateEmailList', False)]:
            rows = payload.get(key)
            if not isinstance(rows, list):
                raise _invalid()
            for row in rows:
                if not isinstance(row, dict):
                    raise _invalid()
                address = _address(row.get('emailAddress'))
                if address.rsplit('@', 1)[1] == 'privaterelay.appleid.com':
                    continue
                result.append(_hidden_address(row, channel, forward, active))
    if (len({item.address for item in result}) != len(result)
            or len({item.remote_id for item in result}) != len(result)):
        raise _invalid()
    return DirectorySnapshot(channel, tuple(result), channel == 'web')
