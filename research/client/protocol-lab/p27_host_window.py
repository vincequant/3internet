"""Bounded, read-only host sampling during one start experiment.

This samples a last-message slot, not a lossless packet capture. It does not
run indefinitely, send frames, or write target process memory.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import time
# Embedded python312._pth excludes the script directory in this Wine runtime.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p4_host_watch import Memory, module_base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pid', type=int)
    ap.add_argument('--duration', type=float, default=30)
    ap.add_argument('--out', required=True, help='Explicit JSONL output; Wine stdout may be unavailable')
    args = ap.parse_args()
    if not 0 < args.duration <= 60:
        ap.error('duration must be within (0, 60] seconds')
    m = Memory(args.pid)
    output = Path(args.out).open('w', encoding='utf-8', buffering=1)
    def emit(value):
        output.write(json.dumps(value, ensure_ascii=False) + '\n')
    try:
        base = module_base(m.h, 'koeinm.dll')
        if not base:
            raise RuntimeError('host koeinm.dll not found')
        obj = base + 0x12170
        emit({'ev': 'capture_started', 'wall': time.time(),
                          'identity': m.identity, 'readonly': True,
                          'sampling_interval_s': 0.1,
                          'limitation': 'last-message-slot sampling; frames may be missed'})
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            raw = m.read(obj, 0x8468)
            if raw is None:
                raise RuntimeError('netobj read failed')
            u32 = lambda off: struct.unpack_from('<I', raw, off)[0]
            length = struct.unpack_from('<i', raw, 0x414c)[0]
            count, table = u32(0x43bc), u32(0x43b8)
            members = []
            if table:
                for i in range(min(count, 8)):
                    row = m.read(table + i * 0x164, 0x50)
                    if row:
                        r32 = lambda off: struct.unpack_from('<I', row, off)[0]
                        members.append({'id': r32(0),
                                        'name': row[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                                        'sA': r32(0x24), 'sB': r32(0x28),
                                        'reconnecting': r32(0x34), 'failed': r32(0x38),
                                        'active': r32(0x4c)})
            emit({'ev': 'sample', 'wall': time.time(),
                              'last_len': length, 'sender': u32(0x4150),
                              'last_msg': raw[0x14c:0x14c + min(max(length, 0), 512)].hex(),
                              'truncated': length > 512, 'join': u32(0x8414),
                              'members': members})
            time.sleep(0.1)
        emit({'ev': 'capture_ended', 'wall': time.time()})
    finally:
        m.close()
        output.close()


if __name__ == '__main__':
    main()
