"""SGI TCP codec recovered from SANGUO SHA256 4029e2a4….

Vendored from research/client/protocol-lab/login_protocol.py for the Hub
main-account path. No networking or credential access on import.
Never log plaintext packet bodies.
"""
import hashlib
import struct
import zlib

MAX_BODY = 1024 * 1024
SUBSTITUTION = bytes.fromhex(
    '702f405f448e6e457eab2c1fb4ac9d910d369b0bd4c43974bf23161406eb043e125c'
    '8bbc6163f6a5e165d8f55a07f013f2206b4a24598964d7426a5e3d0a77e08027b8c5'
    '8c0efa8ad52956576c536741e8001ace8683b022284d3f26464f6f2b723af18d979549'
    '84e5e3798f5110a882c6ddfffce4cfb3095dea9c34f9179fda87f815053cd3a4852e'
    'fbee473bef377f93af690c7131de2175a0aaba7c3802b78101fde71dcccdbd1b7a2a'
    'ad66be553303db88b21e4eb9e6c2f7cb7dc962c3a6dca750b54b94c0924c115b78d9'
    'b1ed19e9a11cb63299a3769e7b6d9a30d6a925c7ae9635d0bbd2c8a208f3d173f448'
    '2d90cae258c11852fedf689854ec60430f')
INVERSE = bytes(SUBSTITUTION.index(i) for i in range(256))


def wrap(packet):
    # Outer transport: total length, additive checksum, marker, main/sub command.
    plain = struct.pack('<HH', 101, 1) + packet
    if len(plain)+4 > 0x808:
        raise ValueError('Transport frame exceeds original client limit')
    return struct.pack('<HBB', len(plain)+4, -sum(plain) & 255, 0x44) + plain.translate(SUBSTITUTION)


class Transport:
    def __init__(self):
        self.pending = bytearray()

    def feed(self, data):
        self.pending.extend(data)
        result = []
        while len(self.pending) >= 4:
            n, check, marker = struct.unpack_from('<HBB', self.pending)
            if not 8 <= n <= 0x808 or marker != 0x44:
                raise ValueError('Invalid transport header')
            if len(self.pending) < n:
                break
            plain = bytes(self.pending[4:n]).translate(INVERSE)
            if (check + sum(plain)) & 255:
                raise ValueError('Transport checksum mismatch')
            del self.pending[:n]
            main, sub = struct.unpack_from('<HH', plain)
            result.append((main, sub, plain[4:]))
        return result


def transform(data, decrypt=False):
    out = bytearray(data)
    n = len(out)
    if n <= 1:
        return bytes(out)
    if decrypt and n % 2:
        out[n // 2] ^= out[0]
    for i in range(n // 2):
        j = n - i - 1
        a, b = out[i], out[j]
        if decrypt:
            out[i], out[j] = (2*b-a) & 255, (a-b) & 255
        else:
            out[i], out[j] = (a+2*b) & 255, (a+b) & 255
    if not decrypt and n % 2:
        out[n // 2] ^= out[0]
    return bytes(out)


def pack_string(value):
    raw = value.encode('gbk') if isinstance(value, str) else value
    if len(raw) > 65535:
        raise ValueError('String exceeds protocol limit')
    return struct.pack('<H', len(raw)) + raw


def login_body(username, password, version=(6 << 16) | 2):
    user = username.encode('gbk')
    if not 1 <= len(user) <= 16:
        raise ValueError('Username exceeds client limit')
    digest = hashlib.md5(password.encode('gbk')).hexdigest().upper()
    # Force login is deliberately disabled. Initial login, no previous user ID.
    return pack_string(user) + pack_string(digest) + struct.pack(
        '<BIIIBI', 0, version, 6, 3, 0, 0xffffffff)


def encode(command, sequence, body=b''):
    if len(body) > MAX_BODY:
        raise ValueError('Body exceeds limit')
    head = struct.pack('<III', command, sequence, len(body))
    return head + struct.pack('<II', zlib.crc32(head), zlib.crc32(body)) + transform(body)


class Frames:
    def __init__(self):
        self.pending = bytearray()

    def feed(self, data):
        self.pending.extend(data)
        result = []
        while len(self.pending) >= 20:
            cmd, seq, n, hc, bc = struct.unpack_from('<IIIII', self.pending)
            if zlib.crc32(self.pending[:12]) != hc:
                raise ValueError('Header CRC mismatch')
            if n > MAX_BODY:
                raise ValueError('Body exceeds limit')
            if len(self.pending) < 20+n:
                break
            body = transform(self.pending[20:20+n], decrypt=True)
            if zlib.crc32(body) != bc:
                raise ValueError('Body CRC mismatch')
            del self.pending[:20+n]
            result.append((cmd, seq, body))
        return result


class Reader:
    def __init__(self, body):
        self.body, self.pos = body, 0

    def take(self, n):
        if n < 0 or self.pos+n > len(self.body):
            raise ValueError('Truncated payload')
        out = self.body[self.pos:self.pos+n]
        self.pos += n
        return out

    def number(self, fmt='I'):
        return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))[0]

    def string(self):
        return self.take(self.number('H')).decode('gbk', errors='replace')


def room_directory(body):
    r = Reader(body)
    out = {'game_id': r.number(), 'id': r.number(), 'name': r.string(),
           'flags': r.number('B'), 'field10': r.number(), 'field14': r.number(),
           'field18': r.number(), 'field1c': r.number(),
           'server': r.string(), 'port': r.number('H')}
    # These strings may be transport configuration; keep out of public results.
    private = (r.string(), r.string(), r.number())
    if r.pos != len(body):
        raise ValueError('Unexpected room directory trailing data')
    return out, private


def game_directory(body):
    r = Reader(body)
    out = {'id': r.number(), 'name': r.string()}
    private = [r.string(), r.string(), r.number('B'), r.number('B'),
               r.string(), r.string(), r.string()]
    if r.pos != len(body):
        raise ValueError('Unexpected game directory trailing data')
    return out, private


def user_record(r):
    # Field names not yet fully identified. Keep the entire record in memory only.
    out = {'id': r.number(), 'name': r.string(), 's08': r.string(),
           'i0c': r.number(), 's10': r.string()}
    out.update({f'i{x:02x}': r.number() for x in range(0x14, 0x2c, 4)})
    out.update(s2c=r.string(), b30=r.number('B'))
    return out


def member_directory(body):
    # S2C 0x2004 after client 0x200f. Layout from protocol-lab/native_login_probe.py.
    r = Reader(body)
    room_id, count = r.number(), r.number()
    if count > 200:
        raise ValueError('Unexpected user count')
    users = [user_record(r) for _ in range(count)]
    flag = r.number('B')
    if r.pos != len(body):
        raise ValueError('Unexpected user-list trailing bytes')
    return {'room_id': room_id, 'count': count, 'users': users, 'flag': flag}
