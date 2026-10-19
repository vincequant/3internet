#!/usr/bin/env python3
"""Build optional shadow UI replacements; does not open a game process.

Keep the sealed functions' bodies intact: P51 already uses them as caves.
Every entry is called by the original UI caller, never a new worker thread.
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
.globl ui_panel_create, ui_stat_12c, ui_stat_12d, ui_stat_12e, ui_stat_12f
.globl ui_stat_130, ui_stat_131, ui_stat_132, ui_cards_init, ui_cards_update
.globl ui_visible_xy, ui_visible_test

// this=the real 0x50a4e0 panel container; argument=GameCore.
// Seven numeric widgets + the original hand-card widget; no message pump.
ui_panel_create:
    push ebp
    mov ebp, esp
    push ebx
    push esi
    push edi
    sub esp, 0x14
    mov edi, ecx
    test edi, edi
    jz create_done
    cmp dword ptr [edi], 0x50a4e0
    jne create_done
    cmp dword ptr [edi+0xc], 0
    jne create_done
    mov esi, [ebp+8]
    test esi, esi
    jz create_done
    cmp dword ptr [esi], 0x5053c0
    jne create_done
    mov eax, [esi+0x6c0]
    cmp eax, 7
    ja create_done
    mov [ebp-0x10], eax
    mov ecx, esi
    mov eax, 0x44b83b
    call eax
    cmp eax, -1
    je create_done
    push eax
    mov ecx, esi
    mov eax, 0x44ff48
    call eax
    test eax, eax
    jz create_done
    cmp dword ptr [eax], 0x506660
    jne create_done
    mov edx, [ebp-0x10]
    cmp [esi+0x6c0], edx
    jne create_done
    mov esi, eax
    movzx eax, byte ptr [esi+0x17]
    push 0
    push 200
    push eax
    push 0x12c
    mov ecx, edi
    call create_number
    mov ecx, esi
    mov eax, 0x46814a
    call eax
    push 0x18
    push 100
    push eax
    push 0x12d
    mov ecx, edi
    call create_number
    push 0x34
    push 10000000
    push dword ptr [esi+0x1c]
    push 0x12e
    mov ecx, edi
    call create_number
    push 0x4c
    push 10000000
    push dword ptr [esi+0x18]
    push 0x12f
    mov ecx, edi
    call create_number
    push 0x68
    push 2000000
    push dword ptr [esi+0x20]
    push 0x130
    mov ecx, edi
    call create_number
    push 0x80
    push 2000000
    push dword ptr [esi+0x26]
    push 0x131
    mov ecx, edi
    call create_number
    push 0x98
    push 2000000
    push dword ptr [esi+0x2c]
    push 0x132
    mov ecx, edi
    call create_number
    push 0x4c
    mov eax, 0x4d1d22
    call eax
    add esp, 4
    test eax, eax
    jz create_done
    mov ecx, eax
    mov eax, 0x484ad8
    call eax
    test eax, eax
    jz create_done
    mov ebx, eax
    push 0
    push 0xb4
    push 0
    mov ecx, ebx
    mov eax, 0x4b0071
    call eax
    push ebx
    mov ecx, edi
    mov eax, 0x4b08b4
    call eax
    // Build the native card/treasure icon ids from the selected force.
    // The original constructor leaves this empty until a later refresh.
    lea eax, [ebp-0x20]
    push 1
    push eax
    mov ecx, esi
    mov eax, 0x467c52
    call eax
    cmp eax, 5
    ja create_done
    mov edi, eax
    xor esi, esi
create_card_loop:
    cmp esi, edi
    jae create_card_copy
    mov eax, [ebp+esi*4-0x20]
    push eax
    mov eax, 0x43f5da
    call eax
    add esp, 4
    mov [ebp+esi*4-0x20], eax
    inc esi
    jmp create_card_loop
create_card_copy:
    // Use a native CArray<int>, not a guessed array layout or shallow alias.
    sub esp, 0x14
    mov esi, esp
    mov ecx, esi
    mov eax, 0x4cce14
    call eax
    push -1
    push edi
    mov ecx, esi
    mov eax, 0x4cd117
    call eax
    xor ecx, ecx
create_card_fill:
    cmp ecx, edi
    jae create_card_set
    mov eax, [ebp+ecx*4-0x20]
    mov edx, [esi+4]
    mov [edx+ecx*4], eax
    inc ecx
    jmp create_card_fill
create_card_set:
    push esi
    mov ecx, ebx
    call ui_cards_update
    mov ecx, esi
    mov eax, 0x4cce47
    call eax
    add esp, 0x14
create_done:
    add esp, 0x14
    pop edi
    pop esi
    pop ebx
    pop ebp
    xor eax, eax
    ret 4

// Native ctor/config/layout/ownership, bounded to one widget. Limits/layout
// are the original constants, not sampled resource values from a screenshot.
create_number:
    push ebp
    mov ebp, esp
    push ebx
    push esi
    mov esi, ecx
    push 0x44
    mov eax, 0x4d1d22
    call eax
    add esp, 4
    test eax, eax
    jz number_done
    mov ecx, eax
    mov eax, 0x484101
    call eax
    test eax, eax
    jz number_done
    mov ebx, eax
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov ecx, ebx
    mov eax, 0x4852a6
    call eax
    push dword ptr [ebp+0x14]
    push 0
    mov ecx, ebx
    mov eax, 0x4b0071
    call eax
    push 0
    push ebx
    mov ecx, esi
    mov eax, 0x4b08b4
    call eax
number_done:
    pop esi
    pop ebx
    pop ebp
    ret 0x10

// Each entry preserves thiscall + one callee-cleaned argument. A direct
// field update replaces the entire old animate/pump/retry loop.
ui_stat_12c:
    mov edx, 0x12c
    jmp stat_common
ui_stat_12d:
    mov edx, 0x12d
    jmp stat_common
ui_stat_12e:
    mov edx, 0x12e
    jmp stat_common
ui_stat_12f:
    mov edx, 0x12f
    jmp stat_common
ui_stat_130:
    mov edx, 0x130
    jmp stat_common
ui_stat_131:
    mov edx, 0x131
    jmp stat_common
ui_stat_132:
    mov edx, 0x132
stat_common:
    push ebx
    push esi
    push edi
    push ebp
    mov ebp, ecx
    test ecx, ecx
    jz stat_done
    mov eax, [ecx+0x7ea]
    test eax, eax
    jz stat_done
    cmp dword ptr [eax], 0x50a4e0
    jne stat_done
    mov esi, [eax+4]
    mov ebx, 64
stat_find:
    test esi, esi
    jz stat_done
    dec ebx
    js stat_done
    mov edi, [esi+8]
    test edi, edi
    jz stat_next
    cmp dword ptr [edi], 0x50a3a8
    jne stat_next
    cmp [edi+0x30], edx
    jne stat_next
    mov eax, [esp+0x14]
    mov [edi+0x3c], eax
    // Queue a normal repaint; never dispatch/pump messages synchronously.
    mov eax, [ebp+0x1c]
    test eax, eax
    jz stat_done
    push 0
    push 0
    push eax
    call dword ptr [0x4fb754]
    jmp stat_done
stat_next:
    mov esi, [esi]
    jmp stat_find
stat_done:
    pop ebp
    pop edi
    pop esi
    pop ebx
    xor eax, eax
    ret 4

ui_cards_init:
    xor edx, edx
    jmp cards_common
ui_cards_update:
    mov edx, 1
cards_common:
    push ebx
    push esi
    mov esi, ecx
    test esi, esi
    jz cards_done
    cmp dword ptr [esi], 0x50a468
    jne cards_done
    mov ebx, [esp+0xc]
    test ebx, ebx
    jnz cards_copy
    test edx, edx
    jnz cards_done
    jmp cards_notify
cards_copy:
    cmp dword ptr [ebx+8], 5
    ja cards_done
    cmp dword ptr [ebx+8], 0
    je cards_copy_valid
    cmp dword ptr [ebx+4], 0
    je cards_done
cards_copy_valid:
    push ebx
    lea ecx, [esi+0x38]
    mov eax, 0x4cce7e
    call eax
cards_notify:
    mov ecx, esi
    mov eax, [esi]
    call dword ptr [eax+0x74]
cards_done:
    pop esi
    pop ebx
    xor eax, eax
    ret 4

// Only used at individually listed renderer call sites, never at the shared
// 468662/4686c7 predicates. No world data, vision bitmap, RNG, network or
// synchronization event is written. Null draw context still means invisible.
ui_visible_xy:
    xor eax, eax
    test ecx, ecx
    setne al
    test eax, eax
    ret 8
ui_visible_test:
    xor eax, eax
    test ecx, ecx
    setne al
    test eax, eax
    ret
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        code = assemble(ASM, 'shadow_ui', temp)
        entries = symbols(temp/'shadow_ui.obj')
    (out/'shadow_ui.bin').write_bytes(code)
    (out/'shadow_ui.s').write_text(ASM, encoding='utf-8')
    (out/'shadow_ui.disasm.txt').write_text('\n'.join(
        '%04x %-8s %s' % (va, op, arg) for va, op, arg, size in disassemble(code))+'\n')
    meta = {'schema': 'p52-shadow-ui-1', 'sha256': hashlib.sha256(code).hexdigest(),
            'size': len(code), 'entries': {n: v for n, v in entries.items() if n.startswith('ui_')},
            'activation': 'optional_per_element; NOT enabled by arm_now.sh'}
    (out/'shadow_ui.json').write_text(json.dumps(meta, indent=2)+'\n')
    print(json.dumps(meta))


if __name__ == '__main__':
    main()
