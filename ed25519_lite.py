"""Ed25519 signatures in plain Python (0.5.95), after the reference code of RFC 8032, section 6.

The Python standard library has no public-key signatures and MediathekAtlas ships without
third-party packages (old Macs, NAS). The receipts of ``archive_receipts`` need a signature that
another system can check without knowing a secret, so this is the reference algorithm, unchanged
in its arithmetic. It is slow (some milliseconds per signature) and not constant-time: fine for a
few receipts per download between the user's own systems, not meant for anything else.
Checked against the test vectors of RFC 8032 in ``tests/test_v0595_archive_receipts.py``.
"""
import hashlib

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)


def _h(data):
    return int.from_bytes(hashlib.sha512(data).digest(), 'little') % Q


def _add(a, b):
    x = (a[1] - a[0]) * (b[1] - b[0]) % P
    y = (a[1] + a[0]) * (b[1] + b[0]) % P
    c, d = 2 * a[3] * b[3] * D % P, 2 * a[2] * b[2] % P
    e, f, g, h = y - x, d - c, d + c, y + x
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, point):
    out = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            out = _add(out, point)
        point = _add(point, point)
        s >>= 1
    return out


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * _SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    return P - x if (x & 1) != sign else x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(point):
    z = pow(point[2], P - 2, P)
    x, y = point[0] * z % P, point[1] * z % P
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def _decompress(raw):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, 'little')
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError('Schlüssel muss 32 Byte lang sein')
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], 'little')
    return (a & ((1 << 254) - 8)) | (1 << 254), h[32:]


def public_key(secret):
    return _compress(_mul(_expand(secret)[0], G))


def sign(secret, message):
    a, prefix = _expand(secret)
    public = _compress(_mul(a, G))
    r = _h(prefix + message)
    rs = _compress(_mul(r, G))
    s = (r + _h(rs + public + message) * a) % Q
    return rs + s.to_bytes(32, 'little')


def verify(public, message, signature):
    """True only for a signature of ``message`` by the owner of ``public``. Never raises on bad input."""
    if not isinstance(public, bytes) or not isinstance(signature, bytes) or len(public) != 32 or len(signature) != 64:
        return False
    a, r = _decompress(public), _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], 'little')
    if s >= Q:
        return False
    left, right = _mul(s, G), _add(r, _mul(_h(signature[:32] + public + message), a))
    return (left[0] * right[2] - right[0] * left[2]) % P == 0 and (left[1] * right[2] - right[1] * left[2]) % P == 0
