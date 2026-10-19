#!/usr/bin/env python3
"""Build a typed replacement for ONE bitmap-paint call, never its hit test.

The immutable entries implement independent masks without any writable
configuration in the game. World objects, fog, and rule predicates are read only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

GROUPS = {
    'map-trap-fire': (1, (0x50a0f0,)),
    'map-trap-rock': (2, (0x50a1a8,)),
    'map-trap-pit': (4, (0x50a260,)),
    'map-unit-sprites': (8, (0x508678, 0x508878, 0x508a60, 0x508c48,
        0x508e30, 0x509018, 0x509200, 0x5093e8, 0x5095d0, 0x5097b8,
        0x5099d0, 0x50bdb8)),
    'map-site-sprites': (16, (0x507e10, 0x507ee8, 0x507fc0)),
}
SITE = 0x4afc5c
ORIGINAL = bytes.fromhex('ff506085c0')


def assembly():
    code = ['.intel_syntax noprefix', '.text']
    for mask in range(1 << len(GROUPS)):
        code += ['.globl hidden_%d' % mask, 'hidden_%d:' % mask,
                 'push edx', 'mov edx, %d' % mask, 'jmp hidden_common']
    code += ['hidden_common:', 'push ebx', 'push esi', 'mov ebx, edx',
             'mov esi, ecx', 'test esi, esi', 'jz hidden_false',
             # Only the entity-backed bitmap wrapper; unrelated widgets run
             # their original virtual method, including any side effects.
             'cmp dword ptr [eax+0x60], 0x4490d2', 'je hidden_typed',
             'cmp dword ptr [eax+0x60], 0x4491e5', 'jne hidden_original',
             'hidden_typed:',
             'mov edx, [esi+0x1c]', 'test edx, edx', 'jz hidden_false',
             'mov edx, [edx]']
    for index, (_, (bit, vtables)) in enumerate(GROUPS.items()):
        for vt in vtables:
            code += ['cmp edx, 0x%x' % vt, 'je hidden_group_%d' % index]
    code += ['jmp hidden_original']
    for index, (_, (bit, _)) in enumerate(GROUPS.items()):
        code += ['hidden_group_%d:' % index, 'test ebx, %d' % bit,
                 'jz hidden_original', 'jmp hidden_base_flags']
    code += ['hidden_base_flags:',
             # Exact read-only equivalent of 4b0012 -> 4afb44. Keep native
             # disabled/not-displayed flags and all preceding image/clip gates.
             'xor eax, eax', 'test dword ptr [esi+0x20], 0xa0000000',
             'sete al', 'jmp hidden_done',
             'hidden_original:', 'mov ecx, esi', 'call dword ptr [eax+0x60]',
             'jmp hidden_done', 'hidden_false:', 'xor eax, eax',
             'hidden_done:', 'pop esi', 'pop ebx', 'pop edx',
             'test eax, eax', 'ret']
    return '\n'.join(code) + '\n'


def main():
    from p51_shadow_agent_build import assemble, disassemble
    from p51_shadow_resident_build import symbols
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)
    source = assembly()
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        raw = assemble(source, 'hidden_draw', temp)
        entries = symbols(temp/'hidden_draw.obj')
    (out/'hidden_draw.bin').write_bytes(raw)
    (out/'hidden_draw.s').write_text(source, encoding='utf-8')
    (out/'hidden_draw.disasm.txt').write_text('\n'.join(
        '%04x %-8s %s' % (a, op, arg) for a, op, arg, _ in disassemble(raw))+'\n')
    meta = dict(schema='p53-hidden-draw-1', size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                entries={n: v for n, v in entries.items() if n.startswith('hidden_') and n[7:].isdigit()},
                groups=GROUPS, site=hex(SITE), before=ORIGINAL.hex(),
                activation=False, writes='code cave and one bitmap paint CALL only')
    (out/'hidden_draw.json').write_text(json.dumps(meta, indent=2)+'\n')
    print(json.dumps(dict(size=len(raw), sha256=meta['sha256'], entries=len(meta['entries']))))


if __name__ == '__main__':
    main()
