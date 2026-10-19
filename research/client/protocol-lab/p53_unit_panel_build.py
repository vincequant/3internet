#!/usr/bin/env python3
"""Build the optional P53 map-click mailbox; no world/UI/network calls.

The hook runs after original widget hit-testing, before the map order switch.
Only GetTickCount is called. All writes target the private mailbox allocation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from p51_shadow_agent_build import assemble, disassemble
from p51_shadow_resident_build import symbols

ASM = r"""
.intel_syntax noprefix
.text
.globl unit_click, unit_click_blob
unit_click:
    pushfd
    pushad
    call click_pc
click_pc:
    pop ebp
    .set pc_delta, click_pc-unit_click
    sub ebp, offset pc_delta
    add ebp, 0x1000
    cmp dword ptr [ebp], 0x33505553
    jne click_passthrough
    cmp dword ptr [ebp+4], 1
    jne click_passthrough
    call dword ptr [0x4fb2f8]
    sub eax, [ebp+8]
    jns click_passthrough
    cmp esi, [0x53b930]
    jne click_passthrough
    cmp dword ptr [esi], 0x50b730
    jne click_passthrough
    cmp dword ptr [esi+0x210], 0
    jne click_passthrough
    cmp dword ptr [esi+0x7e2], 0
    jne click_passthrough
    cmp dword ptr [esi+0x8da], 0
    jne click_passthrough
    mov edx, [esi+0x3c]
    test edx, edx
    jz click_passthrough
    lea eax, [edx+0x912]
    cmp eax, [0x53bb30]
    jne click_passthrough
    cmp dword ptr [eax], 0x5053c0
    jne click_passthrough
    // One UI writer. Odd/even publication prevents torn cross-process reads.
    inc dword ptr [ebp+0xc]
    mov [ebp+0x10], esi
    mov [ebp+0x14], edx
    mov [ebp+0x18], eax
    mov ecx, [esi+0x1c]
    mov [ebp+0x1c], ecx
    mov [ebp+0x20], edi
    mov [ebp+0x24], ebx
    mov ecx, [esi+0x54]
    mov [ebp+0x28], ecx
    mov ecx, [esi+0x58]
    mov [ebp+0x2c], ecx
    mov ecx, [edx+0xf22]
    mov [ebp+0x30], ecx
    mov ecx, [edx+0xf26]
    mov [ebp+0x34], ecx
    mov ecx, [edx+0xf2a]
    mov [ebp+0x38], ecx
    mov ecx, [edx+0xf2e]
    mov [ebp+0x3c], ecx
    mov ecx, [eax+0x4d0]
    mov [ebp+0x40], ecx
    mov ecx, [eax+0x4d4]
    mov [ebp+0x44], ecx
    mov ecx, [eax+0x4d8]
    mov [ebp+0x48], ecx
    call dword ptr [0x4fb2f8]
    mov [ebp+0x4c], eax
    inc dword ptr [ebp+0xc]
    popad
    popfd
    // Original down-handler epilogue; no selection/order branch executed.
    push 0x498a56
    ret
click_passthrough:
    popad
    popfd
    cmp [esi+0x8da], ecx
    push 0x4988e9
    ret
unit_click_blob:
"""


def build(directory):
    out = Path(directory); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        code = assemble(ASM, 'unit_click', temporary)
        entries = symbols(temporary/'unit_click.obj')
    if len(code) >= 0x1000:
        raise ValueError('mailbox overlaps code')
    meta = dict(schema='p53-unit-click-build-1', size=len(code),
                sha256=hashlib.sha256(code).hexdigest(), entries=entries,
                mailbox_offset=0x1000, mailbox_size=0x80,
                site=0x4988e3, before='398eda080000', default_enabled=False,
                target_calls=['KERNEL32.GetTickCount via original IAT 0x4fb2f8'])
    (out/'unit_click.s').write_text(ASM, encoding='utf-8')
    (out/'unit_click.bin').write_bytes(code)
    (out/'unit_click.disasm.txt').write_text('\n'.join(
        '%04x %-8s %s' % (va, op, arg) for va, op, arg, size in disassemble(code))+'\n', encoding='utf-8')
    (out/'unit_click.json').write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    return meta


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--outdir', default=str(Path(__file__).resolve().parent/'unit-panel-build'))
    print(json.dumps(build(ap.parse_args().outdir)))
