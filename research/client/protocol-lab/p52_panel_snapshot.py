#!/usr/bin/env python3
"""One-shot, read-only field/control comparison. Does not call game functions."""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p52_shadow_ui import FIELDS, SANPK_SHA, display_scale


def snapshot(read, core, view):
    def u32(a): return struct.unpack('<I', read(a, 4))[0]
    def i32(a): return struct.unpack('<i', read(a, 4))[0]
    if u32(core) != 0x5053c0:
        raise ValueError('GameCore type mismatch')
    slot = i32(core+0x6c0)
    force = i32(core+0x4a+slot*0x87) if 0 <= slot < 8 else None
    result = {'schema': 'p52-panel-snapshot-1', 'wall': time.time(), 'readonly': True,
              'core': hex(core), 'view': hex(view) if view else None,
              'slot': slot, 'force_id': force, 'lord': None, 'source_values': None,
              'controls': [], 'coherent': False,
              'clock_raw': {'year_4d0': struct.unpack('<h', read(core+0x4d0, 2))[0],
                            'season_4d6': struct.unpack('<h', read(core+0x4d6, 2))[0]}}
    head = u32(core+0x4f8); seen = set(); lord_raw = None; lord_addr = None
    while head:
        if head in seen or len(seen) >= 128:
            raise ValueError('invalid force list')
        seen.add(head); obj = u32(head+8)
        if u32(obj) != 0x506660:
            raise ValueError('force type mismatch')
        if struct.unpack('<h', read(obj+8, 2))[0] == force:
            lord_addr = obj; lord_raw = read(obj, 0x111)
            if result['lord'] is not None:
                raise ValueError('duplicate force identity')
            result['lord'] = hex(obj)
            values = [lord_raw[0x17], None]+[struct.unpack_from('<I', lord_raw, o)[0] for o in (0x1c, 0x18, 0x20, 0x26, 0x2c)]
            result['source_values'] = [dict(f, current=v,
                bar_scale=list(display_scale(v, f['max'])) if v is not None else None) for f, v in zip(FIELDS, values)]
            result['territory_ratio'] = {'status': 'not_invoked', 'source': '0x46814a(lord); native weighted city ratio'}
            result['hand_slots_raw'] = list(lord_raw[0x5e:0x63])
        head = u32(head)
    if view:
        if u32(view+0x3c)+0x912 != core:
            raise ValueError('view and core binding differ')
        owner = u32(view+0x7ea)
        result['panel_container'] = hex(owner)
        if owner:
            if u32(owner) != 0x50a4e0:
                raise ValueError('panel container type mismatch')
            node = u32(owner+4); seen = set()
            while node:
                if node in seen or len(seen) >= 64:
                    raise ValueError('invalid UI child list')
                seen.add(node); obj = u32(node+8); vt = u32(obj)
                row = {'address': hex(obj), 'vtable': hex(vt), 'id': u32(obj+0x30)}
                if vt == 0x50a3a8:
                    row.update(current=i32(obj+0x3c), maximum=i32(obj+0x40))
                elif vt == 0x50a468:
                    count = u32(obj+0x40); data = u32(obj+0x3c)
                    if count > 5 or (count and not data):
                        raise ValueError('invalid card icon array')
                    row.update(icon_ids=[u32(data+4*i) for i in range(count)])
                result['controls'].append(row); node = u32(node)
    result['coherent'] = (i32(core+0x6c0) == slot and
                          (force is None or i32(core+0x4a+slot*0x87) == force) and
                          (lord_addr is None or read(lord_addr, len(lord_raw)) == lord_raw))
    if not result['coherent']:
        result['source_values'] = None
    result['consistency_limit'] = 'double-read context/force; not an atomic whole-world/UI snapshot'
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', required=True)
    args = ap.parse_args()
    if Path(os.environ.get('WINEPREFIX', '').rstrip('/\\')).name != 'prefix-fengye-shadow':
        raise SystemExit('explicit shadow prefix required')
    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector
    from p51_shadow_inject import find_process
    targets = find_process('SANPK.exe')
    if len(targets) != 1:
        raise SystemExit('need one shadow SANPK process')
    col = Collector(targets[0][0])
    try:
        col.bind()
        if col.sha != SANPK_SHA:
            raise SystemExit('SANPK SHA mismatch')
        view = struct.unpack('<I', col.m.read(0x53b930, 4))[0]
        result = snapshot(col.m.read, col.core, view)
        result.update(identity=col.m.identity, build_sha256=col.sha)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        col.close()


if __name__ == '__main__':
    main()
