"""Native Apple login and HME transport. Private protocol; live validation required.

Adapted from t508708/icloud-mail@a2b952c2b50992c15f0f54dff23a15a234189a50,
internal/apple/ (MIT). Copyright (c) 2026 t508708.
See third_party/icloud-mail-LICENSE.txt.
"""

import base64
import copy
import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from outlook_web.icloud_protocol import (
    ACCOUNT_PORTAL, ACCOUNT_ROOT, ACCOUNT_WIDGET, AUTH_ROOT, WEB_WIDGET,
    AppleProtocolError, SessionSnapshot, decode_account_api_key, decode_account_token,
    decode_directory, decode_srp_challenge, decode_web_account, endpoints,
    response_error, security_code_payload, validate_service_url,
)
from outlook_web.icloud_srp import AppleSRP
from outlook_web.icloud_fingerprint import account_fingerprint


USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'


class ICloudClient:
    def __init__(self, apple_id, region, channel, snapshot=None, proxy='', cancelled=lambda: False,
                 http_factory=requests.Session, clock=time.time):
        self.apple_id, self.region, self.channel = apple_id.strip().lower(), region, channel
        if snapshot:
            self.session = SessionSnapshot(**snapshot)
            self.session.require_identity(region, channel, apple_id)
        else:
            self.session = SessionSnapshot(region, channel, self.apple_id, 'signed_out')
        self.values = dict(self.session.values)
        self.values.setdefault('frame_id', str(uuid.uuid4()))
        if channel == 'web':
            self.values.setdefault('client_id', str(uuid.uuid4()))
        self.http = http_factory()
        self.http.trust_env = False
        self.http.proxies = {'https': proxy, 'http': proxy} if proxy else {}
        for cookie in self.session.cookies:
            self.http.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie.get('path', '/'),
                                  secure=cookie.get('secure', True), expires=cookie.get('expires'))
        self.clock, self.cancelled = clock, cancelled
        self.deadline = time.monotonic() + 30
        self.expires_at = None

    def close(self):
        self.http.close()

    def check(self):
        if self.cancelled():
            raise AppleProtocolError('cancelled')
        if time.monotonic() >= self.deadline:
            raise AppleProtocolError('temporary_failure')

    def snapshot(self):
        cookies = tuple({'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path,
                         'secure': c.secure, 'expires': c.expires} for c in self.http.cookies)
        result = SessionSnapshot(self.region, self.channel, self.apple_id, self.session.state, self.values, cookies)
        return asdict(result)

    def headers(self, auth=False):
        portal = endpoints(self.region)['home'] if self.channel == 'web' else ACCOUNT_PORTAL
        headers = {'Accept': 'application/json, text/plain, */*', 'Content-Type': 'application/json',
                   'User-Agent': USER_AGENT, 'Origin': portal, 'Referer': portal + '/', 'Accept-Language': 'zh,en;q=0.9'}
        if self.values.get('scnt'):
            headers['scnt'] = self.values['scnt']
        if auth:
            widget = WEB_WIDGET if self.channel == 'web' else ACCOUNT_WIDGET
            frame = 'auth-' + self.values['frame_id']
            headers.update({
                'Origin': 'https://idmsa.apple.com', 'Referer': 'https://idmsa.apple.com/',
                'X-Apple-Widget-Key': widget, 'X-Apple-Domain-Id': '3' if self.channel == 'web' else '11',
                'X-Apple-OAuth-Client-Id': widget, 'X-Apple-OAuth-Client-Type': 'firstPartyAuth',
                'X-Apple-OAuth-Redirect-URI': portal, 'X-Apple-OAuth-Response-Mode': 'web_message',
                'X-Apple-OAuth-Response-Type': 'code', 'X-Apple-OAuth-State': frame,
                'X-Apple-Frame-Id': frame, 'X-Requested-With': 'XMLHttpRequest',
                'X-Apple-Privacy-Consent': 'true', 'X-Apple-Privacy-Consent-Accepted': 'true',
                'X-Apple-I-FD-Client-Info': json.dumps({'U': USER_AGENT, 'L': 'zh' if self.channel == 'account' else 'en-US',
                    'Z': 'GMT+08:00' if self.channel == 'account' else 'GMT+00:00', 'V': '1.1',
                    'F': account_fingerprint(self.clock()) if self.channel == 'account' else ''}),
            })
            if self.channel == 'web':
                headers.update({'X-Apple-OAuth-Require-Grant-Code': 'true', 'X-Apple-Mandate-Security-Upgrade': '0', 'X-Apple-I-Require-UE': 'true'})
            for key, header in [('session_id', 'X-Apple-ID-Session-Id'), ('session_token', 'X-Apple-Session-Token'), ('auth_attributes', 'X-Apple-Auth-Attributes')]:
                if self.values.get(key):
                    headers[header] = self.values[key]
        elif self.channel == 'account':
            headers.update({'X-Apple-I-Request-Context': 'ca', 'X-Apple-I-TimeZone': 'Asia/Shanghai'})
            if self.values.get('api_key'):
                headers['X-Apple-Api-Key'] = self.values['api_key']
        return headers

    def request(self, method, url, payload=None, *, auth=False, step='protocol', allow=(200, 204), document=False, headers=None):
        self.check()
        validate_service_url(url, self.region, self.channel)
        checkpoint = copy.deepcopy(self.http.cookies)
        outgoing = self.headers(auth)
        outgoing.update(headers or {})
        outgoing = {key: value for key, value in outgoing.items() if value is not None}
        response = None
        try:
            response = self.http.request(method, url, json=payload, headers=outgoing,
                                         allow_redirects=False, stream=True, timeout=max(.1, min(15, self.deadline - time.monotonic())))
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                self.check()
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise AppleProtocolError('invalid_response', step)
                chunks.append(chunk)
            raw = b''.join(chunks)
            try:
                body = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                if document or response.status_code >= 300:
                    body = {}
                else:
                    raise AppleProtocolError('invalid_response', step) from None
            failure = response_error(response.status_code, body, step, response.headers.get('Retry-After', ''), datetime.fromtimestamp(self.clock(), timezone.utc))
            if failure and response.status_code not in allow:
                raise failure
            accepted_verification = (self.channel == 'web' and step == 'verify_code' and response.status_code == 409
                                     and response.headers.get('X-Apple-Session-Token')
                                     and failure is not None and failure.kind == 'invalid_code')
            explicitly_allowed = response.status_code in allow and (response.status_code in {401, 405} or accepted_verification)
            if failure and not explicitly_allowed:
                raise failure
            if response.status_code not in allow:
                raise AppleProtocolError('invalid_response', step, response.status_code)
            for header, key in {'scnt': 'scnt', 'X-Apple-ID-Session-Id': 'session_id', 'X-Apple-Session-Token': 'session_token',
                                'X-Apple-TwoSV-Trust-Token': 'trust_token', 'X-Apple-Auth-Attributes': 'auth_attributes'}.items():
                if response.headers.get(header):
                    self.values[key] = response.headers[header]
            if self.channel == 'web' and response.headers.get('X-Apple-ID-Account-Country'):
                self.values['country_code'] = response.headers['X-Apple-ID-Account-Country']
            self.check()
            return response.status_code, body, dict(response.headers)
        except AppleProtocolError:
            self.http.cookies = checkpoint
            raise
        except requests.RequestException:
            self.http.cookies = checkpoint
            raise AppleProtocolError('temporary_failure', step) from None
        finally:
            if response is not None:
                response.close()

    def _set_state(self, state):
        self.session = SessionSnapshot(self.region, self.channel, self.apple_id, state, self.values)

    def login(self, password):
        if not isinstance(password, str) or not password:
            raise AppleProtocolError('authentication_failed', 'sign_in')
        self.values['frame_id'] = str(uuid.uuid4())
        portal = endpoints(self.region)['home'] if self.channel == 'web' else ACCOUNT_PORTAL
        widget = WEB_WIDGET if self.channel == 'web' else ACCOUNT_WIDGET
        if self.channel == 'account':
            self._warm_portal()
            self.request('GET', ACCOUNT_ROOT + '/account/manage/gs/ws/token', step='sign_in', allow=(200, 401),
                         headers={'scnt': None, 'X-Apple-Api-Key': None})
        frame = 'auth-' + self.values['frame_id']
        params = {'frame_id': frame, 'iframeId': frame, 'skVersion': '7', 'client_id': widget,
                  'redirect_uri': portal, 'response_type': 'code', 'response_mode': 'web_message',
                  'state': frame, 'authVersion': 'latest' if self.channel == 'web' else '8.0.2'}
        _, _, authorize_headers = self.request('GET', AUTH_ROOT + '/authorize/signin?' + urlencode(params), auth=True, step='sign_in', document=True)
        if self.channel == 'account':
            self.request('POST', AUTH_ROOT + '/verify/device/key/challenge', {'passkeyAutofill': False}, auth=True, step='sign_in', headers={'scnt': None, 'X-Apple-ID-Session-Id': None})
        self.request('POST', AUTH_ROOT + '/federate?isRememberMeEnabled=true', {'accountName': self.apple_id, 'rememberMe': True}, auth=True, step='sign_in')
        srp = AppleSRP.generate()
        _, challenge_body, challenge_headers = self.request('POST', AUTH_ROOT + '/signin/init',
            {'a': base64.b64encode(srp.public_key).decode(), 'accountName': self.apple_id, 'protocols': ['s2k', 's2k_fo']}, auth=True, step='sign_in')
        challenge = decode_srp_challenge(challenge_body)
        m1, m2 = srp.proofs(self.apple_id, password, challenge.salt, challenge.server_public, challenge.iterations, challenge.protocol)
        headers = {}
        if self.channel == 'account':
            hints = requests.structures.CaseInsensitiveDict(authorize_headers)
            if not hints.get('X-Apple-HC-Bits'):
                hints.update(challenge_headers)
            headers['X-Apple-HC'] = self.hashcash(hints.get('X-Apple-HC-Bits'), hints.get('X-Apple-HC-Challenge'))
        status, _, _ = self.request('POST', AUTH_ROOT + '/signin/complete?isRememberMeEnabled=true', {
            'accountName': self.apple_id, 'c': challenge.challenge, 'm1': base64.b64encode(m1).decode(),
            'm2': base64.b64encode(m2).decode(), 'rememberMe': True,
            'trustTokens': [self.values['trust_token']] if self.values.get('trust_token') else [],
        }, auth=True, step='sign_in', allow=(200, 409), headers=headers)
        if status == 409:
            return self._pending_verification()
        self._set_state('service_pending')
        try:
            return self.renew()
        except AppleProtocolError as error:
            if error.kind != 'verification_required':
                raise
            return self._pending_verification()

    def _pending_verification(self):
        self._set_state('verification_required')
        if self.channel == 'web':
            self.request('PUT', AUTH_ROOT + '/verify/trusteddevice/securitycode', auth=True, step='sign_in', allow=(200, 204, 405))
        else:
            self.request('GET', AUTH_ROOT, auth=True, step='sign_in', document=True)
        return self.snapshot()

    def verify(self, code):
        if self.session.state != 'verification_required':
            raise AppleProtocolError('invalid_session', 'verify_code')
        payload = security_code_payload(code)
        self.check()
        headers = {'X-Apple-App-Id': ACCOUNT_WIDGET, 'X-Requested-With': None} if self.channel == 'account' else {}
        allow = (200, 204, 409) if self.channel == 'web' else (200, 204)
        self.request('POST', AUTH_ROOT + '/verify/trusteddevice/securitycode', payload, auth=True, step='verify_code', allow=allow, headers=headers)
        self.request('GET', AUTH_ROOT + '/2sv/trust', auth=True, step='verify_code')
        try:
            return self.renew()
        except AppleProtocolError as error:
            if error.kind != 'verification_required':
                raise
            raise AppleProtocolError('invalid_code', 'verify_code') from None

    def _web_exchange(self):
        if not self.values.get('session_token'):
            raise AppleProtocolError('session_expired', 'web_validate')
        _, body, _ = self.request('POST', endpoints(self.region)['setup'] + '/accountLogin', {
            'dsWebAuthToken': self.values['session_token'], 'trustToken': self.values.get('trust_token', ''),
            'extended_login': True, 'accountCountryCode': self.values.get('country_code', 'CN' if self.region == 'cn' else ''),
        }, step='web_validate')
        return body

    def _warm_portal(self):
        self.request('GET', ACCOUNT_PORTAL + '/account/manage/section/privacy', document=True,
                     headers={'Content-Type': None, 'Accept': 'text/html,application/xhtml+xml', 'scnt': None, 'X-Apple-Api-Key': None})
        self.request('GET', ACCOUNT_PORTAL + '/bootstrap/portal', headers={'X-Apple-Api-Key': None})

    def renew(self):
        if self.channel == 'web':
            if self.session.state != 'connected':
                body = self._web_exchange()
            else:
                try:
                    _, body, _ = self.request('POST', endpoints(self.region)['setup'] + '/validate', step='web_validate')
                except AppleProtocolError as error:
                    if error.kind != 'web_token_exchange_required':
                        raise
                    body = self._web_exchange()
            values = decode_web_account(body, self.region, self.apple_id, self.values.get('dsid', ''))
            self.values.update(values)
            self.expires_at = None  # Web validate does not expose a verified management TTL.
        else:
            def refresh(without_scnt=False):
                _, body, _ = self.request('GET', ACCOUNT_ROOT + '/account/manage/gs/ws/token', step='account_renew',
                    headers={'X-Apple-Api-Key': None, **({'scnt': None} if without_scnt else {})})
                if not self.values.get('scnt'):
                    raise AppleProtocolError('session_expired', 'account_renew')
                self.expires_at = decode_account_token(body, datetime.fromtimestamp(self.clock(), timezone.utc)).timestamp()
                _, body, _ = self.request('GET', ACCOUNT_ROOT + '/account/manage', step='account_renew', headers={'X-Apple-Api-Key': None})
                self.values['api_key'] = decode_account_api_key(body)
                self.request('GET', ACCOUNT_ROOT + '/account/manage/forwardemail', step='account_renew')
            try:
                refresh()
            except AppleProtocolError as error:
                if error.kind != 'session_expired':
                    raise
                self._warm_portal()
                try:
                    refresh(True)
                except AppleProtocolError as recovery:
                    if recovery.kind != 'session_expired':
                        raise
                    refresh()
        self._set_state('connected')
        return self.snapshot()

    def hashcash(self, bits, challenge):
        try:
            bits = int(bits)
        except (ValueError, TypeError):
            raise AppleProtocolError('invalid_response', 'sign_in') from None
        if not 1 <= bits <= 24 or not isinstance(challenge, str) or not 1 <= len(challenge) <= 1024:
            raise AppleProtocolError('invalid_response', 'sign_in')
        prefix = '1:%d:%s:%s::' % (bits, datetime.fromtimestamp(self.clock(), timezone.utc).strftime('%Y%m%d%H%M%S'), challenge)
        for counter in range(1 << 27):
            if counter % 4096 == 0:
                self.check()
            number, digits = counter, ''
            while number:
                number, digit = divmod(number, 36)
                digits = '0123456789abcdefghijklmnopqrstuvwxyz'[digit] + digits
            proof = prefix + (digits or '0')
            if int.from_bytes(hashlib.sha1(proof.encode()).digest(), 'big') >> (160 - bits) == 0:
                return proof
        raise AppleProtocolError('temporary_failure', 'sign_in')

    def _hme_url(self, path):
        if self.channel != 'web' or self.session.state != 'connected' or not self.values.get('dsid') or not self.values.get('premium_url'):
            raise AppleProtocolError('hme_unavailable', 'directory')
        return self.values['premium_url'].rstrip('/') + path + '?' + urlencode({
            'dsid': self.values['dsid'], 'clientBuildNumber': '2534Project66', 'clientMasteringNumber': '2534B22',
            'clientId': self.values['client_id'],
        })

    def directory(self):
        if self.channel == 'web':
            _, body, _ = self.request('GET', self._hme_url('/v2/hme/list'), step='directory', headers={'Content-Type': 'text/plain'})
        else:
            _, body, _ = self.request('GET', ACCOUNT_ROOT + '/account/manage/email/private', step='directory')
        return decode_directory(body, self.channel)

    def generate(self):
        _, body, _ = self.request('POST', self._hme_url('/v1/hme/generate'), {'langCode': 'zh-cn' if self.region == 'cn' else 'en-us'}, step='directory')
        if not isinstance(body, dict) or body.get('success') is not True or not isinstance(body.get('result'), dict):
            raise AppleProtocolError('invalid_response', 'directory')
        candidate = body['result'].get('hme')
        if isinstance(candidate, dict):
            candidate = candidate.get('hme')
        if not isinstance(candidate, str) or not re.fullmatch(r'[^\s<>@]+@icloud\.com', candidate):
            raise AppleProtocolError('invalid_response', 'directory')
        return candidate.lower()

    def mutate(self, action, payload):
        if action not in {'reserve', 'deactivate', 'delete'}:
            raise ValueError('隐藏地址操作无效')
        _, body, _ = self.request('POST', self._hme_url('/v1/hme/' + action), payload, step='directory')
        if not isinstance(body, dict) or body.get('success') is not True:
            raise AppleProtocolError('invalid_response', 'directory')
        return body.get('result', {})
