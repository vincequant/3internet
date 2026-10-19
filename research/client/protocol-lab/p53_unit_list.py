#!/usr/bin/env python3
"""Read-only unit lister for the shadow client (research helper).

Uses the P53 unit model container contract (core+0x534 doubly linked list) and
decode_unit; prints each unit's address, id, owner, type and the editable
fields (soldiers/rice/morale/training) so a specific unit can be targeted.

Usage (wine py32): p53_unit_list.py --bridge 'Z:\\...\\shadow\\bridge' [--limit 4096]
"""
import argparse
import ctypes as c
import json
import os
import struct
import sys

from ctypes import wintypes as w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--limit', type=int, default=4096)
    ap.add_argument('--raw', action='store_true')
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    import p53_unit_model as M
    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe'}))
        return 1
    col = Collector(pid)
    try:
        col.bind()
        core = int(col.core)
    finally:
        col.close()
    h = k.OpenProcess(0x0010, False, pid)

    def rd(addr, n):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    try:
        units, guards = M.walk(rd, core, 0x534, args.limit)
    except Exception as error:
        print(json.dumps({'error': 'walk_failed', 'detail': str(error), 'core': hex(core)}))
        return 1
    rows = []
    for addr in units:
        raw = rd(addr, M.UNIT_SIZE)
        if raw is None:
            rows.append({'address': hex(addr), 'error': 'unreadable'})
            continue
        try:
            row = M.decode_unit(addr, raw)
        except Exception as error:
            rows.append({'address': hex(addr), 'error': str(error)})
            continue
        vals = {}
        for key, spec in M.FIELDS.items():
            off, fmt = spec[1], spec[2]
            vals[key] = struct.unpack_from(fmt, raw, off)[0]
        row['editable'] = vals
        if args.raw:
            row['raw_hex'] = raw.hex()
        rows.append(row)
    print(json.dumps({'core': hex(core), 'count': len(rows), 'units': rows}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
