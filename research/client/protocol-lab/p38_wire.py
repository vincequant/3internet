"""P38 wire codec — offline construction/inspection of Koeinm frames.

Sources (all same binary SHA 28476038..., see p38-frame-surface-20261016):
  - disasm/message-flow.md (M1): outer envelope / 46 / export ABI.
  - P38 map: inner-frame table, gates, record layout.
  - p33_wire.py: DLL control-domain bodies (D1/D2/D3/D5/D8) + inner63.

Strictly offline: builds and parses bytes only. No sockets, no native calls.
All integers on the wire are big-endian (BE). Synthetic stamp bytes are 0.
Bounds are enforced on construction; rejection is explicit, never truncated.
"""
import struct

from p33_wire import be, inner63 as ctrl_inner63, decode_control, uint  # noqa: F401

OUTER_TAG = 0x06
CMD_JOIN = 0x01
CMD_RECORD = (0x02, 0x04, 0x05, 0x07, 0x08, 0x0B)   # member-event records
CMD_EXIT = 0x06
CMD_HEARTBEAT = 0x09
CMD_NOOP = 0x0A
CMD_TEXT = 0x46                                      # 'F' text/relay frame
CMD_PROBE = (0x54, 0x55, 0x56, 0x57)                 # reconnect notices (id@+1)
CMD_ACK = 0x58
CMD_DATA = 0x63                                      # inner63

APP_DATA_CAP = 0x1800      # SendData/SendDataTo bound (23a0)
TEXT_CAP = 127             # local reception contract (60b0 checks len<0x81)
RECORD_LEN = 0x2F          # member-event record total length


# ---------------------------------------------------------------- outer layer

def outer(inner, label):
    """Koeinm outer envelope: BE32(5+len(inner)) | 06 | BE32(label) | inner."""
    label = uint(label)
    if not isinstance(inner, (bytes, bytearray)) or len(inner) == 0:
        raise ValueError('inner_required')
    if len(inner) > 0x4000:
        raise ValueError('inner_too_large')
    return be(5 + len(inner)) + bytes([OUTER_TAG]) + be(label) + bytes(inner)


def parse_outer(raw):
    raw = bytes(raw)
    if len(raw) < 9:
        raise ValueError('outer_short')
    total, tag, label = struct.unpack_from('>IBI', raw, 0)
    if tag != OUTER_TAG:
        raise ValueError('outer_tag_mismatch')
    if total != len(raw) - 4:
        raise ValueError('outer_length_mismatch')
    return {'total_field': total, 'label': label, 'inner': raw[9:]}


# ---------------------------------------------------------------- inner layer

def inner(cmd, seq, payload, stamp=b'\x00\x00\x00\x00'):
    """Inner frame: cmd(1) | seq BE32 | stamp(4) | payload."""
    if not 0 <= cmd <= 0xFF:
        raise ValueError('cmd_range')
    seq = uint(seq)
    if len(stamp) != 4:
        raise ValueError('stamp_len')
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError('payload_bytes')
    return bytes([cmd]) + be(seq) + bytes(stamp) + bytes(payload)


def parse_inner(raw):
    raw = bytes(raw)
    if len(raw) < 9:
        raise ValueError('inner_short')
    cmd = raw[0]
    seq = struct.unpack_from('>I', raw, 1)[0]
    return {'cmd': cmd, 'seq': seq, 'stamp_hex': raw[5:9].hex(), 'rest': raw[9:]}


# ------------------------------------------------------- concrete inner frames

def frame_text(sender, target, text_bytes):
    """0x46 'F' text frame: +9 len(incl NUL) | +0d sender | +11 target | +15 text.

    text_bytes must be the on-wire encoding (GBK for this game); NUL appended.
    Reception contract: len <= 127 (60b0 checks < 0x81).
    """
    sender, target = uint(sender), uint(target)
    text_bytes = bytes(text_bytes)
    n = len(text_bytes) + 1
    if n > TEXT_CAP + 1 or n - 1 > 128:
        raise ValueError('text_over_local_contract')
    body = be(n) + be(sender) + be(target) + text_bytes + b'\x00'
    return inner(CMD_TEXT, 0, body)


def record(code, seq, name_bytes, member_id, port=0):
    """Member-event record (0x2f): code@0 | seq@1 | stamp@5 | name@9 | id@0x28.

    code in {2,4,5,7,8,0x0b}; name NUL-padded into [9,0x28). port BE16 @0x2c.
    """
    if code not in CMD_RECORD and code != CMD_EXIT:
        raise ValueError('record_code')
    seq = uint(seq)
    member_id = uint(member_id)
    name_bytes = bytes(name_bytes)
    if b'\x00' in name_bytes or len(name_bytes) > 0x28 - 9 - 1:
        raise ValueError('name_bytes')
    buf = bytearray(RECORD_LEN)
    buf[0] = code
    struct.pack_into('>I', buf, 1, seq)
    buf[9:9 + len(name_bytes)] = name_bytes
    struct.pack_into('>I', buf, 0x28, member_id)
    if port:
        struct.pack_into('>H', buf, 0x2C, port & 0xFFFF)
    return bytes(buf)


def exit_frame(seq, name_bytes=b''):
    """0x06 member-exit frame, 47B record-shaped (name@+9 read by host 6ce0)."""
    return record(CMD_EXIT, seq, name_bytes, member_id=0)


def probe_frame(cmd, member_id):
    """0x54..0x57 reconnect notice: id taken from the seq slot (+1). 9B minimal."""
    if cmd not in CMD_PROBE:
        raise ValueError('probe_cmd')
    return inner(cmd, member_id, b'')


def ack58(seq):
    return bytes([CMD_ACK]) + be(uint(seq)) + b'\x00\x00\x00\x00'


def heartbeat09():
    return bytes([CMD_HEARTBEAT]) + b'\x00\x00\x00\x00' + b'\x00\x00\x00\x00'


# --------------------------------------------------- application carriers (D)

def d4(data):
    """SendCmd member body: BE32(4) | BE32(len) | data."""
    data = bytes(data)
    if len(data) > 0x800:
        raise ValueError('d4_command_bound')
    return be(4) + be(len(data)) + data


def d7(target, data):
    """SendData/SendDataTo body: BE32(7) | BE32(target) | BE32(len) | data.

    Live observation (run-123126): broadcast sends use target field 0 while the
    outer inner63 target is 0xFFFFFFFF.
    """
    data = bytes(data)
    if len(data) > APP_DATA_CAP:
        raise ValueError('d7_data_bound')
    return be(7) + be(uint(target)) + be(len(data)) + data


def wrap_data(body, seq, sender, target):
    """inner63 carrying an application/control body (member uplink shape)."""
    return ctrl_inner63(body, seq, sender, target, b'\x00\x00\x00\x00')


# ------------------------------------------------------------------ decoding

def inspect(raw):
    """Best-effort structural decode of one inner frame (no guessing beyond bytes)."""
    raw = bytes(raw)
    base = parse_inner(raw)
    cmd = base['cmd']
    out = {'cmd': cmd, 'seq': base['seq'], 'stamp_hex': base['stamp_hex'], 'len': len(raw)}
    r = base['rest']
    if cmd == CMD_DATA and len(r) >= 12:
        blen, sender, target = struct.unpack_from('>III', r, 0)
        body = r[12:]
        out.update(body_len=blen, sender=sender, target=target,
                   body_hex=body[:64].hex(), body_actual=len(body))
        if len(body) >= 4:
            ctl = struct.unpack_from('>I', body, 0)[0]
            out['control'] = ctl
            if ctl == 7 and len(body) >= 12:
                out['d7_target'] = struct.unpack_from('>I', body, 4)[0]
                out['d7_len'] = struct.unpack_from('>I', body, 8)[0]
            elif ctl == 4 and len(body) >= 8:
                out['d4_len'] = struct.unpack_from('>I', body, 4)[0]
    elif cmd == CMD_TEXT and len(r) >= 12:
        n, sender, target = struct.unpack_from('>III', r, 0)
        out.update(text_len=n, sender=sender, target=target, text=r[12:12 + max(0, n - 1)])
    elif cmd in CMD_RECORD:
        name = r[:0x28 - 9].split(b'\x00')[0].decode('latin1')
        member_id = struct.unpack_from('>I', r, 0x28 - 9)[0] if len(r) >= 0x24 else None
        out.update(name=name, member_id=member_id)
    elif cmd == CMD_EXIT:
        name = r[:0x28 - 9].split(b'\x00')[0].decode('latin1')
        out.update(name=name)
    elif cmd in CMD_PROBE:
        out['member_id'] = base['seq']
    elif cmd == CMD_ACK:
        out['ack_seq'] = base['seq']
    return out
