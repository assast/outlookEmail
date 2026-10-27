"""Apple SRP-6a primitives (Python 3.9+, no additional dependencies).

Adapted from t508708/icloud-mail internal/apple/srp.go at
a2b952c2b50992c15f0f54dff23a15a234189a50 (MIT).
Copyright (c) 2026 t508708. See third_party/icloud-mail-LICENSE.txt.
"""

import hashlib
import secrets
from dataclasses import dataclass, field


N = int(
    'AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050'
    'A37329CBB4A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50'
    'E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B8'
    '55F97993EC975EEAA80D740ADBF4FF747359D041D5C33EA71D281E446B14773B'
    'CA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87748'
    '544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6'
    'AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB6'
    '94B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73',
    16,
)
G = 2
SIZE = 256


def _hash(*parts: bytes) -> bytes:
    return hashlib.sha256(b''.join(parts)).digest()


def _pad(value: int) -> bytes:
    return value.to_bytes(SIZE, 'big')


def derive_password(password: str, salt: bytes, iterations: int, protocol: str) -> bytes:
    """Derive Apple's password key without trimming the original password."""
    if (not isinstance(password, str) or not isinstance(salt, bytes)
            or not 1 <= len(salt) <= 1024
            or type(iterations) is not int or not 1 <= iterations <= 10_000_000):
        raise ValueError('Invalid Apple SRP parameters')
    digest = _hash(password.encode('utf-8'))
    if protocol == 's2k':
        material = digest
    elif protocol == 's2k_fo':
        material = digest.hex().encode('ascii')
    else:
        raise ValueError('Unsupported Apple SRP protocol')
    return hashlib.pbkdf2_hmac('sha256', material, salt, iterations, dklen=32)


@dataclass(repr=False)
class AppleSRP:
    """One short-lived SRP attempt. Never serialize or log this object."""

    _secret: int = field(repr=False)

    @classmethod
    def generate(cls):
        return cls.from_private_bytes(secrets.token_bytes(32))

    @classmethod
    def from_private_bytes(cls, private: bytes):
        """Deterministic input is provided for protocol-vector tests only."""
        if not isinstance(private, bytes) or len(private) != 32 or not any(private):
            raise ValueError('Invalid Apple SRP private value')
        return cls(int.from_bytes(private, 'big'))

    def __post_init__(self):
        if type(self._secret) is not int or not 0 < self._secret < (1 << 256):
            raise ValueError('Invalid Apple SRP private value')

    @property
    def public_key(self) -> bytes:
        return _pad(pow(G, self._secret, N))

    def proofs(self, apple_id: str, password: str, salt: bytes,
               server_public: bytes, iterations: int, protocol: str) -> tuple[bytes, bytes]:
        """Return m1 and m2 for Apple's signin/complete request."""
        if (not isinstance(apple_id, str) or not apple_id
                or not isinstance(server_public, bytes)
                or not 1 <= len(server_public) <= SIZE):
            raise ValueError('Invalid Apple SRP challenge')
        b = int.from_bytes(server_public, 'big')
        if not 0 < b < N:
            raise ValueError('Invalid Apple SRP server public value')
        password_key = derive_password(password, salt, iterations, protocol)
        x = int.from_bytes(_hash(salt, _hash(b':', password_key)), 'big')
        a_bytes = self.public_key
        b_bytes = _pad(b)
        u = int.from_bytes(_hash(a_bytes, b_bytes), 'big')
        k = int.from_bytes(_hash(_pad(N), _pad(G)), 'big')
        base = (b - k * pow(G, x, N)) % N
        if not u or not base:
            raise ValueError('Invalid Apple SRP challenge')
        shared = pow(base, self._secret + u * x, N)
        key = _hash(_pad(shared))
        group_hash = bytes(a ^ b for a, b in zip(_hash(_pad(N)), _hash(_pad(G))))
        m1 = _hash(group_hash, _hash(apple_id.encode('utf-8')), salt, a_bytes, b_bytes, key)
        m2 = _hash(a_bytes, m1, key)
        return m1, m2
