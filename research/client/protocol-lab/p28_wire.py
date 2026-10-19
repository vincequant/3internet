"""Bounded, offline first-object inspection. Preserve unknown derived bytes.

Source: disasm/sanpk-wire-serialize.md and sim/m6_wire.py. This is NOT a
complete snapshot decoder and never decides that a game is ready to start.
"""
import hashlib
import struct

KNOWN_BASE = {b'CSanInetCmdObject', b'CSanInetGetInitCmdData',
              b'CSanInetInitGameData', b'CSanInetPlayerNotifyData'}


def inspect_object(data):
    result = {'sha256': hashlib.sha256(data).hexdigest(), 'length': len(data)}
    pos = 0

    def take(n):
        nonlocal pos
        if n < 0 or n > len(data) - pos:
            raise ValueError('truncated_at_%d' % pos)
        v = data[pos:pos+n]
        pos += n
        return v

    def count():
        n = take(1)[0]
        if n != 255:
            return n
        n = struct.unpack('<H', take(2))[0]
        return struct.unpack('<I', take(4))[0] if n == 65535 else n

    try:
        if take(2) != b'\xff\xff':
            raise ValueError('first_object_not_fresh_class')
        schema, size = struct.unpack('<HH', take(4))
        if not 0 < size < 64:
            raise ValueError('class_name_bound')
        name = take(size)
        result.update(class_name=name.decode('ascii', 'replace'), schema=schema)
        if schema != 1 or name not in KNOWN_BASE:
            raise ValueError('unimplemented_class_or_schema')
        cmd, a, b = struct.unpack('<III', take(12))
        result.update(cmd=cmd, a=a, b=b)
        size = count()
        wide = size == 65534
        if wide:
            size = count()
            if size == 65534:
                raise ValueError('repeated_unicode_marker')
        text = take(size * (2 if wide else 1))
        result.update(text_hex=text.hex(), text_wide=wide,
                      base_end=pos, derived_tail_length=len(data)-pos,
                      interpretation='base_fields_only')
    except ValueError as exc:
        result['parse_unknown'] = str(exc)
    return result


def inspect_packet(raw, packet_type):
    if len(raw) < 12:
        raise ValueError('short_notification_header')
    sender, target, size = struct.unpack_from('<III', raw)
    cap = 0x1800 if packet_type == 4 else 128
    if packet_type not in (3, 4) or size > cap or len(raw) != 12 + size:
        raise ValueError('notification_length_or_type')
    payload = raw[12:]
    result = {'sender': sender, 'target': target, 'length': size,
              'raw_hex': payload.hex(), 'sha256': hashlib.sha256(payload).hexdigest()}
    if packet_type == 4:
        result['object'] = inspect_object(payload)
        obj = result['object']
        if obj.get('class_name') == 'CSanInetInitGameData' and 'base_end' in obj:
            try:
                result['snapshot'] = decode_snapshot(payload, obj['base_end'])
            except ValueError as exc:
                result['snapshot_unknown'] = str(exc)
    return result


def decode_snapshot(data, offset):
    """435f21/42bbd9/4725ab Serialize order; field offsets are native names.

    All eight rows + 68 setting bytes must be present. Native transient fields
    +16..41/+7f..86 are not serialized and are never invented here.
    """
    pos = offset

    def take(n):
        nonlocal pos
        if n < 0 or n > len(data)-pos:
            raise ValueError('snapshot_truncated_at_%d' % pos)
        value = data[pos:pos+n]
        pos += n
        return value

    def uint(size):
        return int.from_bytes(take(size), 'little')

    def text():
        size = uint(1)
        if size == 255:
            size = uint(2)
            if size == 65534:
                raise ValueError('snapshot_unicode_unimplemented')
            if size == 65535:
                size = uint(4)
        value = take(size)
        return {'raw_hex': value.hex(), 'gbk_display': value.decode('gbk', 'replace')}

    header = {'d14': uint(4), 'w18': uint(2), 'w1a': uint(2),
              'bytes1c_hex': take(8).hex(), 'd24': uint(4), 'd28': uint(4)}
    rows = []
    for i in range(8):
        begin = pos
        row = {'index': i, 'w4': uint(2), 'id': uint(4),
               'text_a': text(), 'name_e': text(), 'd12': uint(4)}
        version = uint(1)
        if version != 1:
            raise ValueError('row_version_%d_at_%d' % (version, pos-1))
        row.update(state42=uint(4), binding46=uint(4), w4a=uint(2),
                   text4c=text(), d50=uint(4), b54=uint(1), b55=uint(1),
                   dwords56=[uint(4) for _ in range(9)], text7a=text(), b7e=uint(1))
        row['wire_start'], row['wire_length'] = begin, pos-begin
        rows.append(row)
    settings = take(68)
    if pos != len(data):
        raise ValueError('snapshot_unconsumed_tail_%d' % (len(data)-pos))
    return {'header': header, 'rows': rows, 'settings_hex': settings.hex(),
            'consumed': pos, 'interpretation': 'serialized_state_fields; business_labels_unknown'}
