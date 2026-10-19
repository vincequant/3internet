# -*- coding: utf-8 -*-
"""P39c2 channel-2 wire builders: non-member endpoint -> host uplink.

Pure functions, no I/O. Every layout is byte-anchored to REAL captures so
that no cross-toolkit endianness convention leaks in:

- Game-level envelope (p38 domain A):
    BE32(5 + len(inner)) || 0x06 || BE32(label_id) || inner
  Anchors: p37-chat-20261015/wire-frames.txt fy-d1 frame
    "00000020 06 0a9028aa <inner 27B>" (len field 0x20 == 5 + 27);
  p36-e1-reconstruct c4 both directions; p38-frame-surface section 2.

- Inner frame header: [cmd 1B][seq BE32][stamp 4B][...] (p38 section 3.3).

- Loader 1000 instruction "game -> loader" (single-shot variant flag5=0),
  byte-anchored on the real c4 capture:
    "e8030000 00 00 0ae85a82 f5ac 0a78483a 1e61 0400 0001338b"
    = LE u32 1000 || flag4 || flag5 || BE u32 addr1 || BE u16 port1
      || BE u32 addr2 || BE u16 port2 || LE u16 plen || payload
  Field semantics (loader dispatcher-B + P36-E2 bed, both static and live):
    addr1/port1 = source imprint copied verbatim into the emitted '!' frame
                  [8..11]/[12..13];
    addr2       = target member id; copied verbatim into '!' [2..5]
                  (observed: E2 -> [2..5]=addr2 wire bytes; referenced by the
                  loader table lookup);
    port2       = target game delivery port; wire bytes copied verbatim into
                  '!' [6..7]. Receiving loader delivers payload to
                  127.0.0.1:<BE16 of those bytes>.
  Real-frame double check (p36-e1 c4, 2026-10-16):
    instruction #1 port2 "1e61" -> '!' deliver_port BE 0x1e61 == 7777;
    instruction #2 port2 "f5ac" -> '!' deliver_port BE 0xf5ac == 62892
    (the dynamic-port peer).

- Step-1 harmless payload: inner = [0x0a][00 00 00 00][marker b"P9C2"].
  cmd 0x0a host route FUN_10007ab0 '\n' case == plain return (no state);
  the receive stage FUN_10009520 case 6 writes +0x14c/+0x414c/+0x4150
  unconditionally BEFORE routing, so the host-side watch still records
  sender / length / raw bytes. Both claims re-checked on this machine's
  Koeinm.dll 28476038... with REA on 2026-10-16 (procedure_pseudo_code
  0x10009520 / 0x10007ab0).

- Relay-fed loader table entry (17B, real a3/a8/aa wire):
    BE32 id || ip_a 4B || BE16 port_a || ip_b 4B || BE16 port_b || flag
  (E1 c4 roster decode cross-checked against relay packets; memory rows use
  the same byte order as the wire, id read BE.)
"""

import hashlib
import struct

HARMLESS_CMD = 0x0A
MARKER = b'P9C2'
MAX_ENVELOPE_INNER = 0x1800

# golden real-frame vectors (byte-anchored, do not edit)
GOLDEN_C4_INSTRUCTION = (
    'e803000000000ae85a82f5ac0a78483a1e6104000001338b')
GOLDEN_C4_FRAME_B = (
    '0a78483a53475a574c4200000000000000000000000000000000000000000000'
    '000000b7e7d4c600000000000000000000000000000000000000000000000000'
    '0000000000080000000100000000')
GOLDEN_P37_FY_D1 = (
    '00000020060a9028aa460000000000000000000000060a9028aaffffffff66792d'
    '643100')


def sha256_hex(blob):
    return hashlib.sha256(blob).hexdigest()


def ip_to_id(text):
    """'10.x.y.z' -> the u32 whose big-endian bytes are the dotted quad."""
    parts = [int(p) for p in text.split('.')]
    if len(parts) != 4 or any(not 0 <= p <= 255 for p in parts):
        raise ValueError('bad_ip:' + text)
    return int.from_bytes(bytes(parts), 'big')


def id_to_ip(value):
    return '.'.join(str(b) for b in (value & 0xFFFFFFFF).to_bytes(4, 'big'))


def envelope(label_id, inner):
    """Game-level outer envelope, wire-exact."""
    if not 1 <= len(inner) <= MAX_ENVELOPE_INNER:
        raise ValueError('inner_len_out_of_range')
    return (struct.pack('>I', 5 + len(inner)) + b'\x06'
            + struct.pack('>I', label_id & 0xFFFFFFFF) + inner)


def harmless_inner(stamp=MARKER):
    """[0x0a][seq=0][stamp] - ignored by the host route, slot-visible."""
    if len(stamp) != 4:
        raise ValueError('stamp_must_be_4_bytes')
    return bytes([HARMLESS_CMD]) + struct.pack('>I', 0) + stamp


def step1_frame(label_id, stamp=MARKER):
    """The single Step-1 uplink frame (18 bytes)."""
    return envelope(label_id, harmless_inner(stamp))


def instr1000(addr1, port1, addr2, port2, payload, flag4=0, flag5=0):
    """Loader 1000 instruction, wire-exact (see module docstring)."""
    if not 0 < len(payload) <= 0x4000:
        raise ValueError('payload_len_out_of_range')
    if flag4 not in (0, 1) or flag5 not in (0, 1):
        raise ValueError('flag_range')
    return (struct.pack('<I', 1000) + bytes([flag4, flag5])
            + struct.pack('>I', addr1 & 0xFFFFFFFF) + struct.pack('>H', port1 & 0xFFFF)
            + struct.pack('>I', addr2 & 0xFFFFFFFF) + struct.pack('>H', port2 & 0xFFFF)
            + struct.pack('<H', len(payload)) + payload)


def entry17(entry_id, ip_a='0.0.0.0', port_a=0,
            ip_b='0.0.0.0', port_b=0, flag=1):
    """Relay-fed 17B table entry (a3/a8/aa payload part), wire-exact."""
    def ip4(text):
        parts = [int(p) for p in text.split('.')]
        if len(parts) != 4 or any(not 0 <= p <= 255 for p in parts):
            raise ValueError('bad_ip:' + text)
        return bytes(parts)
    return (struct.pack('>I', entry_id & 0xFFFFFFFF) + ip4(ip_a)
            + struct.pack('>H', port_a & 0xFFFF) + ip4(ip_b)
            + struct.pack('>H', port_b & 0xFFFF) + bytes([flag & 0xFF]))


def _key4(key):
    return struct.pack('<I', key & 0xFFFFFFFF)


def msg_a8(entry_id, ip_a, port_a, ip_b, port_b, flag=1, key=1):
    """Registration receipt (real wire: len byte 0x10, then the 17B entry)."""
    return (b'\xa8' + _key4(key) + b'\x00\x00\x00\x00' + b'\x10\x00'
            + entry17(entry_id, ip_a, port_a, ip_b, port_b, flag))


def msg_a3(entries, key=2):
    """User-list add. entries: list of (id, ip_a, port_a, ip_b, port_b, flag).
    Real wire: [a3][key4][00000000][17*n byte][00][count LE2][entries...]."""
    body = b''.join(entry17(*e) for e in entries)
    if not 0 < len(entries) <= 8:
        raise ValueError('entry_count')
    return (b'\xa3' + _key4(key) + b'\x00\x00\x00\x00' + bytes([17 * len(entries)])
            + b'\x00' + struct.pack('<H', len(entries)) + body)


def msg_aa(entry_id, ip_a, port_a, ip_b, port_b, flag=1, key=3):
    """User update (real wire: len byte 0x11, then the 17B entry)."""
    return (b'\xaa' + _key4(key) + b'\x00\x00\x00\x00' + b'\x11\x00'
            + entry17(entry_id, ip_a, port_a, ip_b, port_b, flag))


def msg_2(entry_id, value=0):
    """'2' status update: [32][00][id BE4][value BE4] (P36-E2 form + E1
    decoder id@+2; value semantic not established, kept numeric)."""
    return (b'\x32' + b'\x00' + struct.pack('>I', entry_id & 0xFFFFFFFF)
            + struct.pack('>I', value & 0xFFFFFFFF))


def crc32_bang(data):
    """'!' frame checksum: CRC32(seed=0xFFFFFFFF) low byte (loader variant)."""
    import zlib
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFF


def bang_parse(buf):
    """Parse a wire '!' frame into a dict (for bed/live receipts)."""
    if len(buf) < 16 or buf[0] != 0x21:
        return {'ok': False, 'reason': 'not_a_bang'}
    plen = struct.unpack_from('<H', buf, 14)[0]
    payload = buf[16:16 + plen]
    return {
        'ok': True,
        'crc_ok': crc32_bang(buf[2:]) == buf[1],
        'vip_id_hex': buf[2:6].hex(),
        'deliver_port': struct.unpack_from('>H', buf, 6)[0],
        'src_id': int.from_bytes(buf[8:12], 'big'),
        'src_port': struct.unpack_from('>H', buf, 12)[0],
        'plen': plen,
        'payload_hex': payload.hex(),
        'payload_sha256': sha256_hex(payload),
        'trailer_hex': buf[16 + plen:].hex(),
    }


def validate_authorization(auth, target_id, own_id, b_port, table_rows):
    """Single-shot gate validation shared by the orchestrator and tests.

    Returns None when the authorization may be executed, else a reason code.
    """
    if not isinstance(auth, dict):
        return 'authorization_not_dict'
    if auth.get('authorized') is not True:
        return 'authorized_flag_not_true'
    if not isinstance(auth.get('target_id'), int) or auth['target_id'] != target_id:
        return 'target_id_mismatch'
    if not isinstance(auth.get('target_port'), int) \
            or not 1 <= auth['target_port'] <= 65535:
        return 'target_port_invalid'
    if own_id is None or auth.get('own_id') != own_id:
        return 'own_id_mismatch'
    if not isinstance(b_port, int) or not 1 <= b_port <= 65535:
        return 'b_port_unavailable'
    if not any(isinstance(r, dict) and r.get('id') == target_id
               for r in (table_rows or [])):
        return 'target_not_in_relay_table'
    return None


def _self_check():
    # 1) real c4 instruction, byte-exact
    got = instr1000(182999682, 62892, 175654970, 7777,
                    bytes.fromhex('0001338b'))
    assert got.hex() == GOLDEN_C4_INSTRUCTION, got.hex()
    # 2) step-1 frame shape
    frame = step1_frame(0x0A112233)
    assert len(frame) == 18
    assert frame.hex() == '0000000e060a1122330a0000000050394332'
    # 3) P37 fy-d1 envelope reconstruction
    inner = bytes.fromhex('460000000000000000000000060a9028aaffffffff66792d643100')
    assert len(inner) == 27
    assert envelope(0x0A9028AA, inner).hex() == GOLDEN_P37_FY_D1
    # 4) a3 roster entry from the real E1 roster (丁满 row)
    a3 = msg_a3([(0x0A5CC286, '223.74.148.129', 0x2023, '192.168.188.129', 0x11E0, 1)], key=7)
    assert a3[:5] == b'\xa3' + struct.pack('<I', 7)
    assert a3[13:].hex() == '0a5cc286df4a94812023c0a8bc8111e001'
    # 5) bang round trip
    payload = step1_frame(0x0A112233)
    head = (bytes([0x21, 0x00]) + b'\x02\x00\x00\x00'
            + struct.pack('>H', 7777) + bytes([10, 9, 9, 9])
            + struct.pack('>H', 7777) + struct.pack('<H', len(payload)))
    body = head[2:] + payload
    frame_b = bytes([0x21, crc32_bang(body)]) + body
    parsed = bang_parse(frame_b)
    assert parsed['ok'] and parsed['crc_ok'] and parsed['deliver_port'] == 7777
    assert parsed['src_id'] == ip_to_id('10.9.9.9')
    assert parsed['payload_hex'] == payload.hex()
    # 6) id helpers
    assert ip_to_id('10.92.194.134') == 0x0A5CC286
    assert id_to_ip(0x0A5CC286) == '10.92.194.134'
    print('p39c2_frame self-check OK')


if __name__ == '__main__':
    _self_check()
