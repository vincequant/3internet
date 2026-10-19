#!/usr/bin/env python3
"""Bounded, reproducible P53 static evidence; never executes a game image."""
import argparse
import hashlib
import json
from pathlib import Path
from p52_ui_static import emit, SANPK_SHA
from pe_static import PE
from p53_hidden_draw_build import GROUPS

RANGES = {
    'bitmap-paint-only': (0x4afbad,0x4afce5),
    'bitmap-hit-unchanged': (0x4afd2f,0x4afd9b),
    'entity-bitmap-visible-unchanged': (0x4490d2,0x4490e8),
    'entity-detail-bitmap-visible-unchanged': (0x4491e5,0x4491fb),
    'bitmap-flags-unchanged': (0x4b0012,0x4b002d),
    'trap-owner-and-detection-unchanged': (0x483859,0x4838a8),
    'unit-ambush-and-fog-unchanged': (0x476bfc,0x476d19),
    'native-diamond-hit': (0x498591,0x498694),
    'native-world-to-pixel': (0x4986dd,0x498721),
}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sanpk',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args(); out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    pe=PE(args.sanpk)
    if hashlib.sha256(pe.data).hexdigest()!=SANPK_SHA:raise SystemExit('unsupported image SHA')
    result=emit(args.sanpk,RANGES,out)
    tables=[]
    for name,(_,vts) in GROUPS.items():
        for vt in vts:
            raw=pe.read(vt,0x78)
            tables.append(dict(group=name,vtable=hex(vt),visibility70=hex(pe.u32(vt+0x70)),
                               detail74=hex(pe.u32(vt+0x74)),sha256=hashlib.sha256(raw).hexdigest()))
    result.update(schema='p53-ui-static-1',execution=False,entity_vtables=tables)
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(ranges=len(RANGES),entity_vtables=len(tables),sha256=result['sha256'])))


if __name__=='__main__':main()
