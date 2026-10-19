"""P36 wire codec: NetHook loader-level frames and control messages.

Everything here is derived from static REA analysis of NetHookLoader.dll
(2026-10-15) unless marked TODO(empirical). Runs on the Mac side (python3).

Wire facts (receiver-verified, FUN_10009530):
  '!' datagram (what a peer loader delivers into the local game):
    [0]     0x21
    [1]     CRC32 low byte over bytes[2:]
    [2..5]  4 bytes, sender writes 02 00 00 00 (exact meaning unknown)
    [6..7]  u16 BE  local delivery port (loader sends to 127.0.0.1:this)
    [8..11] u32     source ip as stored by inet_addr (raw address bytes)
    [12..13]u16 BE  source port (trailer port)
    [14..15]u16 LE  payload length (offset)
    [16..]  payload (the game application frame)

Control messages (loader protocol, first byte):
  0xa8 registration ack: dwords @0x0b,0x0f,0x13,0x17; flag byte @0x1b
  0xa3 user-list add: count u16 @0x0b, entries @0x0d, 17 bytes each
  0xa9 user remove:   id u32 @0x0b
  0xaa user replace:  id u32 @0x0b; fields @0x0f,0x13,0x17
  0x23 '#' update:    id u32 @0x02; flag @0x06; value u32 @0x07
  0x32 '2' update:    id u32 @0x02; value u32 @0x06
  1000 instruction (hook->loader / relay->loader): dword 1000; flag @4; @5==1;
       addr1 u32 @6, port1 u16 @0x0a, addr2 u32 @0x0c, port2 u16 @0x10,
       len u16 @0x12, payload @0x14
  1001 query: dword 0x3e9; user id u32 @0x14   (reply 1002 to source)
"""

import struct
import zlib


def crc32_low(data: bytes) -> int:
    """Low byte of the standard CRC-32 (table-driven in FUN_100010f0)."""
    return zlib.crc32(data) & 0xFF


def crc32_low_loader(data: bytes) -> int:
    """Loader variant: FUN_100010f0(.., seed=0xffffffff) == zlib(seed=0xffffffff)."""
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFF


# ---------------------------------------------------------------- '!' frames

def bang_encode(payload: bytes, src_ip: str, src_port: int, deliver_port: int,
                crc_mode: str = 'loader') -> bytes:
    ip_bytes = bytes(int(p) & 0xFF for p in src_ip.split('.'))
    head = bytes([0x21, 0x00, 0x02, 0x00, 0x00, 0x00])
    head += struct.pack('>H', deliver_port & 0xFFFF)      # [6..7]  BE
    head += ip_bytes                                       # [8..11]
    head += struct.pack('>H', src_port & 0xFFFF)          # [12..13] BE
    head += struct.pack('<H', len(payload))               # [14..15] LE
    body = head + payload
    crc = crc32_low(body[2:]) if crc_mode == 'default' else crc32_low_loader(body[2:])
    return bytes([0x21, crc]) + body[2:]


def bang_decode(buf: bytes) -> dict:
    if len(buf) < 16 or buf[0] != 0x21:
        return {'ok': False, 'reason': 'not_a_bang'}
    crc_ok = (crc32_low_loader(buf[2:]) == buf[1])
    off = struct.unpack_from('<H', buf, 14)[0]
    return {
        'ok': True, 'crc_ok': crc_ok,
        'deliver_port': struct.unpack_from('>H', buf, 6)[0],
        'src_ip': '.'.join(str(b) for b in buf[8:12]),
        'src_port': struct.unpack_from('>H', buf, 12)[0],
        'length': off,
        'payload': buf[16:16 + off],
        'tail': buf[16 + off:],
    }


# ------------------------------------------------------------ control msgs

def _put_key(buf: bytearray, key: int) -> None:
    """Dedupe key at unaligned offset 1 (CDupChecker reads u32 LE at buf+1)."""
    struct.pack_into('<I', buf, 1, key & 0xFFFFFFFF)


def msg_a8(d0: int, d1: int, d2: int, d3: int, flag: int = 1, key: int = 1) -> bytes:
    buf = bytearray(0x1c)
    buf[0] = 0xA8
    _put_key(buf, key)
    struct.pack_into('<IIII', buf, 0x0B, d0 & 0xFFFFFFFF, d1 & 0xFFFFFFFF,
                     d2 & 0xFFFFFFFF, d3 & 0xFFFFFFFF)
    buf[0x1B] = flag & 0xFF
    return bytes(buf)


def msg_a3(entries, key: int = 2) -> bytes:
    """entries: list of (id, f1, f2, f3, f4) with f4 a byte."""
    count = len(entries)
    buf = bytearray(0x0D + 17 * count)
    buf[0] = 0xA3
    _put_key(buf, key)
    struct.pack_into('<H', buf, 0x0B, count)
    off = 0x0D
    for (eid, f1, f2, f3, f4) in entries:
        struct.pack_into('<IIII', buf, off, eid & 0xFFFFFFFF, f1 & 0xFFFFFFFF,
                         f2 & 0xFFFFFFFF, f3 & 0xFFFFFFFF)
        buf[off + 16] = f4 & 0xFF
        off += 17
    return bytes(buf)


def msg_a9(user_id: int, key: int = 3) -> bytes:
    buf = bytearray(0x0F)
    buf[0] = 0xA9
    _put_key(buf, key)
    struct.pack_into('<I', buf, 0x0B, user_id & 0xFFFFFFFF)
    return bytes(buf)


def msg_aa(user_id: int, f1: int, f2: int, f3: int, key: int = 4) -> bytes:
    buf = bytearray(0x1B)
    buf[0] = 0xAA
    _put_key(buf, key)
    struct.pack_into('<IIII', buf, 0x0B, user_id & 0xFFFFFFFF, f1 & 0xFFFFFFFF,
                     f2 & 0xFFFFFFFF, f3 & 0xFFFFFFFF)
    return bytes(buf)


def msg_hash(user_id: int, flag: int, value: int) -> bytes:
    buf = bytearray(0x0B)
    buf[0] = 0x23
    struct.pack_into('<I', buf, 0x02, user_id & 0xFFFFFFFF)
    buf[0x06] = flag & 0xFF
    struct.pack_into('<I', buf, 0x07, value & 0xFFFFFFFF)
    return bytes(buf)


def msg_2(user_id: int, value: int) -> bytes:
    buf = bytearray(0x0A)
    buf[0] = 0x32
    struct.pack_into('<I', buf, 0x02, user_id & 0xFFFFFFFF)
    struct.pack_into('<I', buf, 0x06, value & 0xFFFFFFFF)
    return bytes(buf)


def msg_1000(addr1: int, port1: int, addr2: int, port2: int,
             payload: bytes, flag4: int = 0, flag5: int = 1) -> bytes:
    buf = bytearray(0x14 + len(payload))
    struct.pack_into('<I', buf, 0, 1000)
    buf[4] = flag4 & 0xFF
    buf[5] = flag5 & 0xFF
    struct.pack_into('<I', buf, 6, addr1 & 0xFFFFFFFF)
    struct.pack_into('<H', buf, 0x0A, port1 & 0xFFFF)
    struct.pack_into('<I', buf, 0x0C, addr2 & 0xFFFFFFFF)
    struct.pack_into('<H', buf, 0x10, port2 & 0xFFFF)
    struct.pack_into('<H', buf, 0x12, len(payload))
    buf[0x14:] = payload
    return bytes(buf)


def msg_1001(user_id: int) -> bytes:
    buf = bytearray(0x18)
    struct.pack_into('<I', buf, 0, 0x3E9)
    struct.pack_into('<I', buf, 0x14, user_id & 0xFFFFFFFF)
    return bytes(buf)


# ------------------------------------------------------------- user record

REC_SIZE = 0x3D


def rec_decode(rec: bytes) -> dict:
    """Best-effort 61-byte user record decode (layout from loader reads)."""
    if len(rec) < REC_SIZE:
        return {'ok': False}
    u32 = lambda o: struct.unpack_from('<I', rec, o)[0]
    u16 = lambda o: struct.unpack_from('<H', rec, o)[0]
    return {
        'ok': True,
        'id': u32(0),
        'ip_a': u32(4), 'port_a': u16(8),
        'ip_b': u32(0x0A), 'port_b': u16(0x0E),
        'state': rec[0x10],
        'b11': rec[0x11], 'b16': rec[0x16], 'b17': rec[0x17],
        'ts18': u32(0x18), 'ts1e': u32(0x1E), 'ts22': u32(0x22),
        'raw_hex': rec.hex(),
    }


def ip_to_int(ip: str) -> int:
    """Return the integer as read little-endian from raw address bytes."""
    return struct.unpack('<I', bytes(int(p) & 0xFF for p in ip.split('.')))[0]


def int_to_ip(value: int) -> str:
    return '.'.join(str(b) for b in struct.pack('<I', value & 0xFFFFFFFF))


if __name__ == '__main__':
    # offline self-check
    b = bang_encode(b'hello', '10.1.2.3', 7777, 7777)
    d = bang_decode(b)
    assert d['crc_ok'] and d['payload'] == b'hello'
    assert d['src_ip'] == '10.1.2.3' and d['src_port'] == 7777
    assert d['deliver_port'] == 7777
    a8 = msg_a8(0x0909090A, 1, 2, 3)
    assert a8[0] == 0xA8 and len(a8) == 0x1C
    a3 = msg_a3([(0x0A0B0C0D, 1, 2, 3, 4)])
    assert a3[0] == 0xA3 and len(a3) == 0x0D + 17
    assert int_to_ip(ip_to_int('10.11.12.13')) == '10.11.12.13'
    m = msg_1000(0x0909090A, 7777, 0x0A0B0C0D, 7777, b'XYZ')
    assert struct.unpack_from('<I', m, 0)[0] == 1000
    print('p36_codec self-check OK')
