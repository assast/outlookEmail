"""Cross-language vectors from the pinned MIT reference; no real credentials."""

import hashlib
import json
from pathlib import Path

import pytest

from outlook_web.icloud_srp import AppleSRP, G, N, SIZE, derive_password


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/icloud/protocol.json').read_text())


def test_reference_node_fixed_vector():
    vector = FIXTURE['vector']
    salt = bytes.fromhex(vector['salt'])
    srp = AppleSRP.from_private_bytes(bytes.fromhex(vector['private']))
    challenge = FIXTURE['challenge']
    derived = derive_password(vector['password'], salt, challenge['iteration'], challenge['protocol'])
    proofs = srp.proofs(vector['apple_id'], vector['password'], salt,
                        bytes.fromhex(vector['wantB']), challenge['iteration'], challenge['protocol'])

    assert derived.hex() == vector['wantDerived']
    assert srp.public_key.hex() == vector['wantA']
    assert proofs[0].hex() == vector['wantM1']
    assert proofs[1].hex() == vector['wantM2']


@pytest.mark.parametrize('protocol', ['s2k', 's2k_fo'])
@pytest.mark.parametrize('password', ['password', ' password ', '密碼 🔑'])
def test_proofs_match_independent_server_calculation(protocol, password):
    # Calculate the server side, rather than repeating the client's base/exponent.
    pad = lambda value: value.to_bytes(SIZE, 'big')
    digest = lambda *parts: hashlib.sha256(b''.join(parts)).digest()
    salt = b'fixture-salt'
    key_material = hashlib.sha256(password.encode()).digest()
    if protocol == 's2k_fo':
        key_material = key_material.hex().encode()
    password_key = hashlib.pbkdf2_hmac('sha256', key_material, salt, 100, dklen=32)
    x = int.from_bytes(digest(salt, digest(b':', password_key)), 'big')
    verifier = pow(G, x, N)
    k = int.from_bytes(digest(pad(N), pad(G)), 'big')
    server_secret = int.from_bytes(bytes(range(33, 65)), 'big')
    b_public = (k * verifier + pow(G, server_secret, N)) % N
    srp = AppleSRP.from_private_bytes(bytes(range(1, 33)))
    a_public = int.from_bytes(srp.public_key, 'big')
    u = int.from_bytes(digest(pad(a_public), pad(b_public)), 'big')
    shared = pow(a_public * pow(verifier, u, N) % N, server_secret, N)
    key = digest(pad(shared))
    group = bytes(a ^ b for a, b in zip(digest(pad(N)), digest(pad(G))))
    expected_m1 = digest(group, digest(b'test@example.com'), salt, pad(a_public), pad(b_public), key)
    expected_m2 = digest(pad(a_public), expected_m1, key)

    assert srp.proofs('test@example.com', password, salt, pad(b_public), 100, protocol) == (
        expected_m1, expected_m2,
    )


def test_password_whitespace_is_not_removed():
    for protocol in ('s2k', 's2k_fo'):
        assert derive_password(' secret ', b'salt', 1, protocol) != derive_password('secret', b'salt', 1, protocol)


@pytest.mark.parametrize('iterations', [0, -1, 10_000_001, True, 1.0, '1000', None])
def test_rejects_invalid_iterations(iterations):
    with pytest.raises(ValueError, match='Invalid Apple SRP parameters'):
        derive_password('secret', b'salt', iterations, 's2k')


@pytest.mark.parametrize('protocol', ['', 's2k_foo', None])
def test_rejects_unknown_protocol(protocol):
    with pytest.raises(ValueError, match='Unsupported Apple SRP protocol'):
        derive_password('secret', b'salt', 1, protocol)


@pytest.mark.parametrize('salt', [b'', b'x' * 1025, 'salt', None])
def test_rejects_invalid_salt(salt):
    with pytest.raises(ValueError):
        derive_password('secret', salt, 1, 's2k')


@pytest.mark.parametrize('private', [b'\0' * 32, b'', b'1' * 31, b'1' * 33, None])
def test_rejects_invalid_private_values(private):
    with pytest.raises(ValueError):
        AppleSRP.from_private_bytes(private)


@pytest.mark.parametrize('server', [b'', b'\0', N.to_bytes(SIZE, 'big'), b'x' * 257])
def test_rejects_invalid_server_public_values(server):
    with pytest.raises(ValueError):
        AppleSRP.from_private_bytes(b'1' * 32).proofs('test@example.com', 'secret', b'salt', server, 1, 's2k')


def test_random_attempts_are_independent_and_repr_omits_private_value():
    first, second = AppleSRP.generate(), AppleSRP.generate()
    assert first.public_key != second.public_key
    assert str(first._secret) not in repr(first)
