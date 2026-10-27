import json
import socket

import pytest

from outlook_web import icloud_codes as codes


@pytest.mark.parametrize('url', ['http://127.0.0.1/code', 'https://[::1]/', 'http://169.254.169.254/',
    'https://10.1.1.1/', 'http://224.0.0.1/', 'https://localhost/', 'file:///tmp/code',
    'https://user:password@code.example/', 'https://code.example:0/'])
def test_unsafe_code_urls_are_rejected(url):
    with pytest.raises(ValueError):
        codes.validate_code_url(url)


def test_dns_and_actual_peer_are_public_and_pinned(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: answers)
    class FakeSocket:
        def settimeout(self, value): pass
        def connect(self, target): self.target = target
        def getpeername(self): return ('8.8.8.8', 443)
        def close(self): pass
    connection = FakeSocket()
    monkeypatch.setattr(socket, 'socket', lambda *_: connection)
    assert codes._public_connect('code.example', 443, 5) is connection
    assert connection.target == ('8.8.8.8', 443)
    connection.getpeername = lambda: ('127.0.0.1', 443)
    with pytest.raises(ValueError):
        codes._public_connect('code.example', 443, 5)
    answers.append((socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.1', 443)))
    with pytest.raises(ValueError, match='不是公网'):
        codes._public_connect('code.example', 443, 5)


def test_code_http_is_cookie_free_direct_and_rejects_redirects_and_large_bodies(monkeypatch):
    calls = []
    class Socket:
        def settimeout(self, _): pass
    class Connection:
        def __init__(self, host, port, timeout): self.sock = Socket()
        def request(self, method, path, headers): calls.append((method, path, headers))
        def getresponse(self): return response
        def close(self): pass
    class Response:
        status = 200
        chunks = ['AppleID 验证码:123456'.encode(), b'']
        def read1(self, limit): return self.chunks.pop(0)
        def getheader(self, name, default=''): return '3600' if name == 'Retry-After' else default
    response = Response()
    monkeypatch.setattr(codes.http.client, 'HTTPSConnection', Connection)
    assert codes.fetch_code_response('https://code.example:8443/code?secret=private').endswith('123456')
    assert calls == [('GET', '/code?secret=private', {'Accept': 'application/json, text/plain'})]
    response.status = 302
    with pytest.raises(ValueError) as caught:
        codes.fetch_code_response('https://code.example/code?secret=private')
    assert 'private' not in str(caught.value)
    assert caught.value.retry_after == 3600
    response.status, response.chunks = 200, [b'x' * 20]
    with pytest.raises(ValueError):
        codes.fetch_code_response('https://code.example/code', limit=10)


@pytest.mark.parametrize('body', ['123456', 'status:200', '<html>验证码123456</html>',
    '验证码:123456，验证码:654321', '{"code":"123456"}', '{"otp":"123456","smsCode":"654321"}'])
def test_ambiguous_and_untrusted_code_responses_are_not_submitted(body):
    assert codes.parse_code_response(body) is None


def test_code_freshness_and_semantic_json_plaintext():
    assert codes.fresh_code('AppleID 登录验证码:123456', 'AppleID 登录验证码:123456', 1000, 1010) is None
    assert codes.fresh_code('{"otp":"654321"}', '{"otp":"123456"}', 1000, 1010) == '654321'
    assert codes.fresh_code('{"smsCode":"654321","received_at":1005}', '', 1000, 1010) == '654321'
    assert codes.fresh_code('{"smsCode":"654321","received_at":900}', '', 1000, 1010) is None
    assert codes.fresh_code('{"smsCode":"654321","received_at":2000}', '', 1000, 1010) is None
    assert codes.fresh_code('验证码:654321', '', 1000, 1010) == '654321'
