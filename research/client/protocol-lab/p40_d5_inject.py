"""P40 offline D5 (member command upload) constructor and once-only gate.

Implements the P38 static lead: the host-side batch collection appends member
uploads without sender validation (Koeinm 0x10001130..). This module only
CONSTRUCTS and VERIFIES bytes offline; sending is the probe's explicit action
under a separate live authorization file (never from this module). All vectors
are rebuilt from retained evidence or synthesized fields, never invented game
results.

Wire references:
- record layout: SANPK serializer 0x435a44, decoded by the local viewer's
  native_command_evidence (kind 18 = CSanInetDomesticCmd, 29-byte body).
- D5 body: control cmd 5 via p33_wire.command_batch (sender, raw) records.
"""
import struct

from p33_wire import command_batch, decode_control

CLASS_NAME = 'CSanInetDomesticCmd'
DOMESTIC_KIND = 18
DOMESTIC_BODY_LEN = 29
RECORD_LEN = 54
D5_MAX_RECORDS = 1

GOLDEN_RECORDS = (
    'ffff010013004353616e496e6574446f6d6573746963436d641200000000000000000000000011000000000000004f00000001000000',
    'ffff010013004353616e496e6574446f6d6573746963436d641200000000000000000000000011000000010000005600000001000000',
    'ffff010013004353616e496e6574446f6d6573746963436d641200000000000000000000000011000000000000004900000001000000',
)


def _int32(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or not -2**31 <= value < 2**31:
        raise ValueError('%s_int32_required' % name)
    return value


def domestic_record(actor, parameter=0, value=0, extra=1, subtype=0, operand=0):
    """Build one 54-byte CSanInetDomesticCmd serialization (schema 1, no text).

    Bounds are rejected, never clamped. Field order follows the serializer:
    body = kind, subtype, operand | text_len=0 | actor, parameter, value, extra.
    """
    if not isinstance(actor, int) or isinstance(actor, bool) or not 0 <= actor < 32:
        raise ValueError('actor_force_bounds')
    if not isinstance(subtype, int) or isinstance(subtype, bool) or not 0 <= subtype <= 255:
        raise ValueError('subtype_bounds')
    _int32('parameter', parameter)
    _int32('value', value)
    _int32('extra', extra)
    _int32('operand', operand)
    body = (struct.pack('<3i', DOMESTIC_KIND, subtype, operand) + b'\x00'
            + struct.pack('<4i', actor, parameter, value, extra))
    if len(body) != DOMESTIC_BODY_LEN:
        raise ValueError('domestic_body_length')
    raw = (b'\xff\xff' + struct.pack('<H', 1) + struct.pack('<H', len(CLASS_NAME))
           + CLASS_NAME.encode('ascii') + body)
    if len(raw) != RECORD_LEN:
        raise ValueError('domestic_record_length')
    return raw


def verify_record(raw):
    """Strict structural check anchored on the retained golden layout.

    The bounded p28 decoder only knows registration classes, so verification
    here is the record's own header/body contract plus a byte-stable rebuild
    through the constructor (bounded fields, never clamped).
    """
    if not isinstance(raw, bytes) or len(raw) != RECORD_LEN:
        raise ValueError('record_length')
    if (raw[0:2] != b'\xff\xff' or struct.unpack_from('<H', raw, 2)[0] != 1
            or struct.unpack_from('<H', raw, 4)[0] != len(CLASS_NAME)
            or raw[6:6 + len(CLASS_NAME)] != CLASS_NAME.encode('ascii')):
        raise ValueError('record_header')
    kind = struct.unpack_from('<i', raw, 25)[0]
    if kind != DOMESTIC_KIND or raw[37] != 0:
        raise ValueError('record_body')
    fields = parse_golden(raw)
    if domestic_record(**fields) != raw:
        raise ValueError('domestic_roundtrip_failed')
    return fields


def parse_golden(raw):
    """Strictly parse a retained golden record into constructor fields."""
    if not isinstance(raw, bytes) or len(raw) != RECORD_LEN:
        raise ValueError('golden_length')
    if raw[0:2] != b'\xff\xff' or struct.unpack_from('<H', raw, 2)[0] != 1 \
            or raw[6:6 + len(CLASS_NAME)] != CLASS_NAME.encode('ascii'):
        raise ValueError('not_golden_domestic_record')
    kind, subtype, operand = struct.unpack_from('<3i', raw, 25)
    if kind != DOMESTIC_KIND or raw[37] != 0:
        raise ValueError('unsupported_golden_layout')
    actor, parameter, value, extra = struct.unpack_from('<4i', raw, 38)
    return {'actor': actor, 'parameter': parameter, 'value': value,
            'extra': extra, 'subtype': subtype, 'operand': operand}


def modify_golden(raw, **changes):
    """Rebuild a retained record with selected fields replaced (byte-stable)."""
    fields = dict(parse_golden(raw))
    unknown = set(changes) - set(fields)
    if unknown:
        raise ValueError('unknown_fields_%s' % ','.join(sorted(unknown)))
    fields.update(changes)
    return domestic_record(**fields)


def d5_body(own_id, record_raw):
    """Wrap one command record as a single-record D5 upload bound to own_id."""
    if not isinstance(own_id, int) or isinstance(own_id, bool) or not 0 < own_id <= 0xffffffff:
        raise ValueError('own_id_bounds')
    verify_record(record_raw)
    body = command_batch([(own_id, record_raw)])
    decoded = decode_control(body)
    if decoded.get('control_cmd') != 5 or len(decoded.get('records', [])) != 1:
        raise ValueError('d5_roundtrip_failed')
    row = decoded['records'][0]
    if row.get('sender') != own_id or row.get('raw_hex') != record_raw.hex():
        raise ValueError('d5_payload_mismatch')
    return body


class D5Gate:
    """Once-only reservation; every failure ends the sequence, never retries."""

    def __init__(self):
        self.phase = 'idle'
        self.body = None
        self.raw_rc = None

    def reserve(self, own_id, record_raw):
        if self.phase != 'idle':
            raise ValueError('d5_already_reserved_or_wrong_phase')
        body = d5_body(own_id, record_raw)
        self.body = body
        self.phase = 'reserved'
        return body

    def mark_sent(self, raw_rc):
        if self.phase != 'reserved':
            raise ValueError('d5_not_reserved')
        _int32('raw_rc', raw_rc)
        self.raw_rc = raw_rc
        self.phase = 'sent'


def d5_authorized(receipt, own_id, host_id, now):
    """Live arming receipt; written by the operator only for a test game."""
    if not isinstance(receipt, dict):
        return False
    return (receipt.get('contract') == 'P40'
            and receipt.get('enable_d5') is True
            and receipt.get('test_game_confirmed') is True
            and receipt.get('own_id') == own_id
            and receipt.get('host_id') == host_id
            and isinstance(receipt.get('observed_wall'), (int, float))
            and 0 <= now-receipt['observed_wall'] <= 600)
