#!/usr/bin/env python3
"""Reproduce D-only bounded static evidence; never execute a game file."""
import argparse
import hashlib
import json
from pathlib import Path
from p52_ui_static import emit, SANPK_SHA

RANGES = {
    'map-message-map-getter': (0x485f08, 0x485f14),
    'map-left-down-before-orders': (0x498811, 0x498a5d),
    'map-left-up': (0x498a89, 0x498b04),
    'ui-hit-button-class-filter': (0x419619, 0x4196a7),
    'ui-runtime-downcast': (0x4d3214, 0x4d3241),
    'map-native-diamond-hit': (0x498591, 0x498694),
    'map-coarse-and-forward-projection': (0x498694, 0x498721),
    'unit-serialization': (0x4768be, 0x476c8d),
    'unit-soldiers-setter': (0x477444, 0x47746d),
    'unit-morale-setters': (0x47750e, 0x477628),
    'unit-unknowns-training-setters': (0x477665, 0x4776ce),
    'unit-movement-rice': (0x477983, 0x477a5e),
    'unit-morale-and-size-consumers': (0x477cf0, 0x477d48),
    'unit-infantry-coefficient': (0x47a9b7, 0x47aa51),
    'unit-cavalry-coefficient': (0x47b1b1, 0x47b235),
    'unit-default-morale-limits': (0x4764dd, 0x4764e9),
    'unit-transport-morale-limit': (0x47c102, 0x47c109),
    'unit-current-movement-consumer': (0x430328, 0x4303ae),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sanpk', required=True); ap.add_argument('--out', required=True)
    args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    if hashlib.sha256(Path(args.sanpk).read_bytes()).hexdigest()!=SANPK_SHA:
        raise SystemExit('unsupported image')
    result=emit(args.sanpk,RANGES,out)
    from pe_static import PE
    p=PE(args.sanpk)
    result['message_map']={'va':'0x50a6e0','raw_48b':p.read(0x50a6e0,48).hex(),
        'WM_LBUTTONDOWN':'0x498811','WM_LBUTTONUP':'0x498a89',
        'no_dedicated_doubleclick_entry_in_view_map':True}
    result['training_clamp_bypass']={'va':'0x4776b3','bytes':p.read(0x4776b3,2).hex(),
        'observation':'current image jumps directly to byte store at 0x4776cb; 0..100 is calculation domain, not an enforced byte invariant'}
    result['ui_hit_filter']={'accepts_class':'CVisualButtonObject@0x50cf50',
        'unit_visual_classes':['CDynamicObjectVO@0x504f20','CDirectionalDynamicObjectVO@0x504f38'],
        'observation':'419660 casts only to the button class; unit visual inheritance does not contain it'}
    result['runtime_classes']=[]
    for address in (0x504f20,0x504f38,0x50cf50,0x50d070,0x50d088,0x50e318):
        raw=p.read(address,24)
        result['runtime_classes'].append(dict(va=hex(address),raw=raw.hex(),sha256=hashlib.sha256(raw).hexdigest()))
    from p53_unit_model import UNIT_TYPES
    result['morale_vtable_limits']=[dict(vtable=hex(vt),kind=name,function=hex(p.u32(vt+0x9c)),
        raw=p.read(p.u32(vt+0x9c),4).hex()) for vt,name in UNIT_TYPES.items()]
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(ranges=len(RANGES),sha256=result['sha256'],execution=False)))


if __name__=='__main__':main()
