"""Cookie-free, DNS-pinned public code retrieval for optional Apple recovery."""

import http.client
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from outlook_web.icloud_protocol import retry_after_seconds


class CodeFetchError(ValueError):
    def __init__(self, retry_after=0):
        self.retry_after = retry_after
        super().__init__('接码服务暂不可用，请稍后重试')

def is_public_ip(address):
    value = ipaddress.ip_address(address)
    return value.is_global and not value.is_multicast and not value.is_reserved


def validate_code_url(raw):
    try:
        if not isinstance(raw, str) or re.search(r'[\s\\]', raw):
            raise ValueError
        url = urlsplit(raw)
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username is not None
                or url.password is not None or url.fragment or url.port == 0):
            raise ValueError
        if url.hostname.lower() in {'localhost', 'localhost.localdomain'}:
            raise ValueError
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address is not None and not is_public_ip(address):
            raise ValueError
        return url
    except (ValueError, TypeError):
        raise ValueError('接码 URL 必须是公网 HTTP/HTTPS 地址，且不含用户信息或重定向片段') from None


def _public_connect(host, port, timeout):
    deadline = time.monotonic() + timeout
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = {answer[4][0] for answer in answers}
    if not addresses or any(not is_public_ip(address) for address in addresses):
        raise ValueError('接码目标不是公网地址')
    for family, socktype, protocol, _, target in answers:
        connection = socket.socket(family, socktype, protocol)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('接码连接超时')
        connection.settimeout(remaining)
        try:
            connection.connect(target)
            peer = connection.getpeername()[0]
            if peer not in addresses or not is_public_ip(peer):
                raise ValueError('接码连接目标不允许')
            return connection
        except (OSError, ValueError):
            connection.close()
    raise ValueError('接码连接失败') from None


def fetch_code_response(raw, timeout=8, limit=65536):
    url = validate_code_url(raw)
    cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = cls(url.hostname, url.port, timeout=timeout)
    # HTTPSConnection wraps this socket using the original hostname for SNI and
    # certificate validation. DNS is resolved only once and the connected peer is checked.
    connection._create_connection = lambda host_port, timeout, *args: _public_connect(url.hostname, host_port[1], timeout)
    try:
        deadline = time.monotonic() + timeout
        connection.request('GET', (url.path or '/') + ('?' + url.query if url.query else ''), headers={'Accept': 'application/json, text/plain'})
        response = connection.getresponse()
        if response.status != 200:
            delay = retry_after_seconds(response.getheader('Retry-After', ''), datetime.now(timezone.utc))
            raise CodeFetchError(delay)
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('接码读取超时')
            sock = connection.sock or response.fp.raw._sock
            sock.settimeout(remaining)
            chunk = response.read1(min(8192, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('接码响应过大')
            chunks.append(chunk)
        return b''.join(chunks).decode('utf-8')
    except CodeFetchError:
        raise
    except Exception:
        raise ValueError('接码读取失败，请检查公网接口状态') from None
    finally:
        connection.close()


def parse_code_response(body):
    """Return (unambiguous code, optional received timestamp), never persist it."""
    if not isinstance(body, str) or '<' in body or '>' in body:
        return None
    semantic = re.compile(r'验证码|(?:verification|security|login)\s*code|Apple\s*ID.*?code', re.I)
    candidates, timestamps = set(), []

    def text_code(text):
        numbers = re.findall(r'(?<![0-9])[0-9]{6}(?![0-9])', text)
        if semantic.search(text) and len(numbers) == 1:
            candidates.add(numbers[0])

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace('_', '')
                if normalized in {'otp', 'smscode', 'verificationcode', 'securitycode', 'applecode'}:
                    if isinstance(child, str) and re.fullmatch(r'[0-9]{6}', child):
                        candidates.add(child)
                elif normalized in {'message', 'text', 'content'} and isinstance(child, str):
                    text_code(child)
                if normalized in {'receivedat', 'timestamp', 'receivedtime'}:
                    timestamps.append(child)
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        text_code(body)
    else:
        walk(payload)
    if len(candidates) != 1:
        return None
    received = None
    if timestamps:
        try:
            parsed = []
            for value in timestamps:
                if type(value) in (int, float) or isinstance(value, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value):
                    number = float(value)
                    parsed.append(number / 1000 if number > 10**11 else number)
                else:
                    date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                    if date.tzinfo is None:
                        raise ValueError
                    parsed.append(date.timestamp())
            if len(set(parsed)) != 1:
                return None
            received = parsed[0]
        except (ValueError, TypeError, OverflowError):
            return None
    return next(iter(candidates)), received


def fresh_code(current, baseline, started_at, now):
    parsed = parse_code_response(current)
    if not parsed:
        return None
    code, received = parsed
    if received is not None:
        return code if started_at <= received <= now + 30 else None
    previous = parse_code_response(baseline)
    return code if previous and previous[0] != code or not baseline.strip() else None
