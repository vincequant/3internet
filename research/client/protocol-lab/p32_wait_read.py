"""One-shot read-only native sync roster; no thread suspension or API sends."""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p4_host_watch import Memory, module_base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pid', type=int)
    ap.add_argument('--expected-id', type=int, required=True)
    ap.add_argument('--expected-exe', default=r'C:\sgi\run-3.5\3I\SANPK.exe')
    args = ap.parse_args()
    os.environ['SGI_GAME_EXE'] = args.expected_exe  # retain exact instance-path guard
    m = Memory(args.pid)
    try:
        base = module_base(m.h, 'koeinm.dll')
        if not base:
            raise ValueError('module_not_found')
        netobj = base+0x12170
        raw = m.read(netobj, 0x84ec)
        if not raw or len(raw) != 0x84ec:
            raise ValueError('short_netobj_read')
        u32 = lambda off: struct.unpack_from('<I', raw, off)[0]
        if u32(0) != args.expected_id:
            raise ValueError('source_id_mismatch')
        fields = {hex(off): u32(off) for off in (0, 0x118, 0x138, 0x148, 0x43bc,
                  0x8440, 0x8444, 0x849c, 0x84a0, 0x84a4, 0x84a8, 0x84ac,
                  0x84b0, 0x84b4, 0x84b8, 0x84bc, 0x84c0, 0x84c4, 0x84c8,
                  0x84cc, 0x84d0, 0x84d4, 0x84d8)}
        ptr, count = u32(0x84c4), u32(0x84c8)
        sync_rows = None
        if 0 < count <= 8 and ptr:
            buf = m.read(ptr, count*8)
            if buf and len(buf) == count*8:
                sync_rows = [{'index': i, 'id': struct.unpack_from('<I', buf, i*8)[0],
                              'ready_flag': struct.unpack_from('<I', buf, i*8+4)[0]}
                             for i in range(count)]
        members = []
        count, ptr = u32(0x43bc), u32(0x43b8)
        if 0 < count <= 8 and ptr:
            buf = m.read(ptr, count*0x164)
            if buf and len(buf) == count*0x164:
                for i in range(count):
                    row = buf[i*0x164:(i+1)*0x164]
                    members.append({'id': struct.unpack_from('<I', row)[0],
                                    'name': row[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                                    'active_4c': struct.unpack_from('<I', row, 0x4c)[0],
                                    'raw_first60_hex': row[:0x60].hex()})
        print(json.dumps({'wall': time.time(), 'pid': args.pid, 'readonly': True,
                          'netobj_base': hex(netobj), 'fields': fields, 'sync_rows': sync_rows,
                          'members': members, 'raw_8490_84ec': raw[0x8490:0x84ec].hex()},
                         ensure_ascii=False))
    finally:
        m.close()


if __name__ == '__main__':
    main()
