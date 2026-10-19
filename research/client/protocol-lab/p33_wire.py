"""Offline DLL control-domain codec. These are NOT MFC game commands.

Source: Koeinm 24f0/2530/2580/26d0/2750 and 3cd0 dispatch table.
Constructed vectors are synthetic, never captured input or foreign replay.
"""
import struct


def uint(v):
    if type(v) is not int or not 0 <= v <= 0xffffffff:
        raise ValueError('uint32_required')
    return v


def be(v):
    return struct.pack('>I', uint(v))


def start_ready():
    return be(1)


def end_ready(processing_ms):
    return be(2)+be(processing_ms)


def command_batch(records):
    if len(records) > 120:
        raise ValueError('native_command_count_bound')
    out = be(5)+be(len(records))
    for sender, raw in records:
        if not uint(sender) or not isinstance(raw, bytes) or len(raw) > 0x800:
            raise ValueError('sender_or_command_bound')
        out += be(sender)+be(len(raw))+raw
    return out


def timing_batch(records):
    if len(records) > 8:
        raise ValueError('member_count_bound')
    return be(3)+be(len(records))+b''.join(be(i)+be(t)+be(ms) for i, t, ms in records)


def own_sync_withdrawal(own_id):
    """Offline candidate B only. No sender/API implementation is provided."""
    if not uint(own_id):
        raise ValueError('own_id_nonzero')
    return be(8)+be(own_id)


def decode_control(raw):
    pos = 0
    def take(n):
        nonlocal pos
        if n < 0 or pos+n > len(raw):
            raise ValueError('truncated_control_at_%d' % pos)
        b = raw[pos:pos+n]
        pos += n
        return b
    def word():
        return struct.unpack('>I', take(4))[0]
    cmd = word()
    result = {'domain': 'DLL_control', 'control_cmd': cmd}
    if cmd == 1:
        pass
    elif cmd == 2:
        result['processing_ms'] = word()
    elif cmd == 8:
        result['declared_departing_id'] = word()
    elif cmd in (3, 5):
        count = word()
        if count > (8 if cmd == 3 else 120):
            raise ValueError('control_record_count_bound')
        result['records'] = []
        for _ in range(count):
            sender = word()
            if cmd == 3:
                result['records'].append({'id': sender, 'sync_ms': word(), 'processing_ms': word()})
            else:
                size = word()
                if size > 0x800:
                    raise ValueError('command_length_bound')
                result['records'].append({'sender': sender, 'raw_hex': take(size).hex(), 'length': size})
    else:
        raise ValueError('unimplemented_DLL_control_%d' % cmd)
    if pos != len(raw):
        raise ValueError('unconsumed_control_tail')
    return result


def inner63(control, seq, sender, target, stamp):
    if not uint(seq) or not uint(sender) or not uint(target) or len(stamp) != 4:
        raise ValueError('explicit_nonzero_native_sequence_identity_and_stamp_required')
    return b'\x63'+be(seq)+stamp+be(len(control))+be(sender)+be(target)+control


def inspect_inner(raw):
    if len(raw) < 21 or raw[0] != 0x63:
        raise ValueError('not_inner63')
    seq, size, sender, target = (struct.unpack_from('>I', raw, i)[0] for i in (1, 9, 13, 17))
    if len(raw) != 21+size:
        raise ValueError('inner63_length_mismatch')
    return {'seq': seq, 'stamp_hex': raw[5:9].hex(), 'sender': sender,
            'target': target, 'control': decode_control(raw[21:])}


def elapsed_native(before, after):
    """SANPK 4ae79b: DWORD elapsed, including its wraparound decrement."""
    uint(before)
    uint(after)
    return (after-before-(1 if after < before else 0)) & 0xffffffff
