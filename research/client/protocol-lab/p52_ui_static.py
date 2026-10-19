#!/usr/bin/env python3
"""Reproducible, execution-free P52 evidence from the supplied PE files.

Only the selected output directory is written. The game images are read-only.
Requires capstone in the analysis environment, never in the Wine injector.
"""
import argparse
import hashlib
import json
from pathlib import Path

from pe_static import PE

SANPK_SHA = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
RANGES = {
    'panel-create': (0x484F35, 0x485204),
    'panel-refresh': (0x499E09, 0x49A590),
    'panel-value-render': (0x484385, 0x4843F4),
    'panel-value-set': (0x4842D4, 0x484385),
    'panel-item-init': (0x484101, 0x48411F),
    'panel-item-config': (0x4852A6, 0x4852C6),
    'panel-callsite': (0x487060, 0x487121),
    'panel-icon-copy': (0x484C5D, 0x484C98),
    'panel-hand-enum': (0x467BFC, 0x467CFE),
    'panel-territory-ratio': (0x46814A, 0x4681D3),
    'strict-element-lookup': (0x4195A9, 0x4195E1),
    'projection-setters': (0x444D95, 0x444F96),
    'chat-send': (0x42B8CF, 0x42B9ED),
    'chat-api-wrappers': (0x42ACCB, 0x42AD0B),
    'chat-allied-list': (0x499505, 0x4995DF),
    'chat-receive': (0x4993E2, 0x499505),
    'chat-relation': (0x4682D8, 0x468381),
    'visibility-source': (0x468662, 0x468768),
    'visibility-allocation': (0x466C5C, 0x466CA8),
    'visibility-recompute': (0x466CA8, 0x467016),
    'visibility-unit': (0x476BFC, 0x476D19),
    'visibility-overview': (0x432F20, 0x433442),
    'visibility-building': (0x4340DD, 0x434140),
    'visibility-trap': (0x4742D8, 0x47431B),
    'visibility-detail': (0x47DCD3, 0x47DD39),
    'visibility-marker': (0x483859, 0x4838A8),
    'render-unit-gate': (0x47E750, 0x47E760),
    'render-city-gate': (0x47FF27, 0x47FF36),
    'render-city-skin-gate': (0x480558, 0x480565),
    'render-site-gate': (0x48179E, 0x4817B5),
    'render-marker-gate': (0x4820E6, 0x4820FD),
    'native-repaint-api': (0x499E09, 0x499E48),
    'native-calendar-setters': (0x47126C, 0x471299),
    'native-card-ids': (0x43F5DA, 0x43F69A),
}
DLL_RANGES = {
    'chat-dll-send': (0x10004BA0, 0x10004C0D),
    'chat-dll-distribute': (0x10005C80, 0x10005EA0),
}


def emit(binary, ranges, directory):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    pe = PE(binary)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    rows = []
    for name, (start, end) in ranges.items():
        raw = pe.read(start, end-start)
        instructions = list(md.disasm(raw, start))
        covered = sum(i.size for i in instructions)
        path = directory / (name + '.asm')
        path.write_text(''.join('%08x  %-30s %s %s\n' %
                               (i.address, i.bytes.hex(), i.mnemonic, i.op_str)
                               for i in instructions), encoding='utf-8')
        rows.append({'name': name, 'start_va': hex(start), 'end_exclusive_va': hex(end),
                     'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
                     'decoded_bytes': covered, 'fully_decoded': covered == len(raw),
                     'evidence': path.name})
    return {'path': str(Path(binary).resolve()), 'sha256': hashlib.sha256(pe.data).hexdigest(),
            'image_base': hex(pe.base), 'ranges': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sanpk', required=True)
    ap.add_argument('--koeinm', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    if hashlib.sha256(Path(args.sanpk).read_bytes()).hexdigest() != SANPK_SHA:
        raise SystemExit('unsupported SANPK SHA')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {'schema': 'p52-ui-static-1', 'execution': False,
              'sanpk': emit(args.sanpk, RANGES, out),
              'koeinm': emit(args.koeinm, DLL_RANGES, out)}
    (out/'manifest.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'out': str(out), 'ranges': len(RANGES)+len(DLL_RANGES),
                      'sanpk_sha256': result['sanpk']['sha256']}))


if __name__ == '__main__':
    main()
