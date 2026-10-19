#!/usr/bin/env python3
"""Read-only discovery of the phase/screen object used by the phase-end sender 0x49b181.

The sender is __thiscall EndPhase(phase_obj); it needs [phase_obj+0x3c] == G
(G = core - 0x912) and [phase_obj+0x8a6] == 0 (not already ended this round).
We scan the target process for the dword G; every hit at address A gives a
candidate phase_obj = A - 0x3c. Candidates are validated and printed with
nearby fields so the real one can be told apart.

Usage (wine py32): phase_obj_probe.py --bridge 'Z:\\...\\shadow\\bridge'
"""
import argparse
import json
import os
import struct
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--limit', type=int, default=200)
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector
    from probe import Memory

    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no snp.exe in this bottle'}))
        return 1
    col = Collector(pid)
    try:
        core = int(col.core)
    finally:
        col.close()
    G = core - 0x912
    m = Memory(pid)
    t0 = time.time()
    m.load()
    hits = m.find(struct.pack('<I', G), limit=args.limit)
    out = {'pid': pid, 'core': hex(core), 'G': hex(G), 'hits': len(hits),
           'scan_s': round(time.time() - t0, 2), 'candidates': []}
    seen = set()
    for a in hits:
        obj = a - 0x3c
        if obj in seen:
            continue
        seen.add(obj)
        raw = m.read(obj, 0x8c0)
        if raw is None or len(raw) < 0x8b0:
            continue
        vtable = struct.unpack_from('<I', raw, 0)[0]
        back = struct.unpack_from('<I', raw, 0x3c)[0]
        ended = struct.unpack_from('<I', raw, 0x8a6)[0]
        hwnd = struct.unpack_from('<I', raw, 0x1c)[0]
        cand = {'obj': hex(obj), 'vtable': hex(vtable), 'obj_3c': hex(back),
                'obj_8a6': ended, 'obj_1c': hex(hwnd),
                'vtable_in_image': 0x400000 <= vtable < 0x540000}
        if back == G:
            out['candidates'].append(cand)
    out['validated'] = len(out['candidates'])
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
