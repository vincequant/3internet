#!/usr/bin/env python3
"""P59 builder: interface-free CSanInetDomesticCmd (kind 18) sender.

The agent is a position-independent x86 (32-bit) stub injected into a shadow
client's SANPK.exe by p59_domestic_inject.py. On operator trigger it builds ONE
`CSanInetDomesticCmd` **with the game's own constructor** and hands it to the
game's own network send path — no UI, no view switch, no hand-rolled frame.

Static anchors (all re-verified 2026-10-19 against SANPK 3.5, whole-file SHA
df9b52251ff1d7bb…, .text identical in the archived research copy):

  CRuntimeClass       0x5334b0  { name=0x533554 "CSanInetDomesticCmd",
                                  size=0x24, schema=1, factory=0x4369a9 }
  vtable              0x5039f8  [0]=GetRuntimeClass 0x4369db
                                [1]=scalar deleting dtor 0x436a22
                                [2]=Serialize 0x436a6f
                                [3]=AssertValid 0x401094
                                [4]=Dump 0x4023ac
  ctor                0x4369f6  base ctor 0x4359e7(18, 0, 0, "")
                                +0x14=-1 +0x18=0 +0x1c=0 +0x20=0
  Serialize           0x436a6f  0x435a44 base (12B ints + 1B empty string)
                                then +0x14/+0x18/+0x1c/+0x20 as i32

  UI training path    0x4a3ba8  builds the object on the stack, then
                                `mov ecx,G; push &obj; call 0x446482`
  the hand-off        0x446482  G+0x80 (match gate) = 0 -> send -> = 1;
                                this = G = core-0x912
  send object         0x42a7d4  CArchive(0x400) << obj  -> SendCmd(buf,len)
                                this = 0x53b672 (static CSanInet member)
  SendCmd             0x42a7ac  -> Koeinm _NetMsg_SendCmd@8 (IAT 0x4fb460)

The agent deliberately calls 0x42a7d4 directly (not 0x446482): identical bytes
on the wire, but it leaves the match gate G+0x80 untouched. The gate value is
recorded before/after in the receipt so a live run can prove that.

Outputs (--outdir): agent_domestic.s / .bin / .listing.txt / manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MAGIC = 0x35474853          # 'SHG5' blob marker
MAGIC2 = 0x43523553         # 'S5RC' receipt marker
BLOB_SIZE = 0x160
FLAG_OFF = 0x50
RECEIPT_OFF = 0xD0
RECEIPT_SIZE = 48

# blob contract (agent assembly reads these absolute byte offsets)
BLOB_LAYOUT = (
    ('magic', 0x00),
    ('sent', 0x04),
    ('GetFileAttributesA', 0x08),
    ('CreateFileA', 0x0C),
    ('WriteFileA', 0x10),
    ('CloseHandle', 0x14),
    ('Sleep', 0x18),
    ('GetTickCount', 0x1C),
    ('is_connected', 0x20),
    ('get_ip', 0x24),
    ('core_global', 0x28),
    ('ctor', 0x2C),
    ('send', 0x30),
    ('send_this', 0x34),
    ('actor', 0x38),
    ('parameter', 0x3C),
    ('value', 0x40),
    ('extra', 0x44),
    ('sanpk_base', 0x48),
)
POINTER_NAMES = tuple(name for name, _ in BLOB_LAYOUT[2:11])

# SANPK 3.5 RVAs that the injector turns into absolute addresses.
# Everything here is a true RVA (VA - preferred image base 0x400000).
BASE_PREFERRED = 0x400000
RVA_CORE_GLOBAL = 0x13BB30      # [0x53bb30] = core
RVA_CTOR = 0x4369F6 - BASE_PREFERRED
RVA_SEND = 0x42A7D4 - BASE_PREFERRED
RVA_SEND_THIS = 0x13B672        # 0x53b540 + 0x132 (static CSanInet member)
RVA_G_FROM_CORE = 0x912         # G = core - 0x912

CLASS_NAME = 'CSanInetDomesticCmd'
CLASS_HEADER = struct.pack('<3H', 0xFFFF, 1, len(CLASS_NAME)) + CLASS_NAME.encode('ascii')

# static anchors, true RVAs (SANPK 3.5)
RVA_VTABLE = 0x5039F8 - BASE_PREFERRED
RVA_CLASS = 0x5334B0 - BASE_PREFERRED
RVA_NAME = 0x533554 - BASE_PREFERRED
RVA_FACTORY = 0x4369A9 - BASE_PREFERRED
RVA_SERIALIZE = 0x436A6F - BASE_PREFERRED
RVA_GETRUNTIMECLASS = 0x4369DB - BASE_PREFERRED
A_SIZE = 0x24
A_SCHEMA = 1


def pe_image(data):
    """Minimal PE32 reader good enough for anchor checks (no execution)."""
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('not a PE')
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    optsz = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    image_base = struct.unpack_from('<I', data, opt + 28)[0]
    secs = []
    for i in range(nsec):
        off = opt + optsz + i * 40
        vsize, va, rawsize, rawptr = struct.unpack_from('<IIII', data, off + 8)
        secs.append((va, max(vsize, rawsize), rawptr, rawsize))

    def read(va, n):
        rva = va - image_base
        for sva, ssize, rawptr, rawsize in secs:
            if sva <= rva < sva + ssize:
                start = rawptr + (rva - sva)
                return data[start:start + n]
        raise ValueError('unmapped VA 0x%x' % va)

    return image_base, read


def static_preflight(data):
    """Verify the four kind-18 anchors in an on-disk SANPK.exe image."""
    image_base, read = pe_image(data)
    checks = {
        'image_base': image_base,
        'vtable_getruntimeclass': struct.unpack('<I', read(image_base + RVA_VTABLE, 4))[0] - image_base,
        'vtable_serialize': struct.unpack('<I', read(image_base + RVA_VTABLE + 8, 4))[0] - image_base,
        'class_name_ptr': struct.unpack('<I', read(image_base + RVA_CLASS, 4))[0] - image_base,
        'class_size': struct.unpack('<I', read(image_base + RVA_CLASS + 4, 4))[0],
        'class_schema': struct.unpack('<I', read(image_base + RVA_CLASS + 8, 4))[0],
        'class_factory': struct.unpack('<I', read(image_base + RVA_CLASS + 0x0C, 4))[0] - image_base,
        'class_name': read(image_base + RVA_NAME, len(CLASS_NAME)).decode('latin1'),
        'ctor_prologue': read(image_base + RVA_CTOR, 8).hex(),
    }
    problems = []
    if checks['vtable_getruntimeclass'] != RVA_GETRUNTIMECLASS:
        problems.append('vtable[0]')
    if checks['vtable_serialize'] != RVA_SERIALIZE:
        problems.append('vtable[2]')
    if checks['class_name_ptr'] != RVA_NAME:
        problems.append('CRuntimeClass::name')
    if checks['class_size'] != A_SIZE:
        problems.append('CRuntimeClass::size')
    if checks['class_schema'] != A_SCHEMA:
        problems.append('CRuntimeClass::schema')
    if checks['class_factory'] != RVA_FACTORY:
        problems.append('CRuntimeClass::factory')
    if checks['class_name'] != CLASS_NAME:
        problems.append('class name string')
    if checks['ctor_prologue'][:10] != '565733ff68':
        problems.append('ctor prologue')
    checks['problems'] = problems
    checks['ok'] = not problems
    return checks

AGENT_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 112
    mov esi, [esp+128]             ; blob ptr (entry [esp0+4])
    cmp dword ptr [esi], 0x35474853 ; 'SHG5'; bad -> inert spin
    jne d_spin
d_loop:
    cmp dword ptr [esi+4], 0       ; once-only sent flag
    jne d_sleep_long
    lea eax, [esi+0x50]
    push eax
    call dword ptr [esi+8]         ; GetFileAttributesA(flag) stdcall
    cmp eax, -1
    je d_sleep_short
    call dword ptr [esi+0x20]      ; _NetMsg_IsConnected@0
    test eax, eax
    jz d_sleep_short
    mov eax, [esi+0x28]            ; &core
    test eax, eax
    jz d_sleep_short
    mov ebx, [eax]                 ; core
    test ebx, ebx
    jz d_sleep_short
    mov ecx, [ebx+0x6c0]           ; my_slot must be sane
    cmp ecx, 7
    ja d_sleep_short
    cmp dword ptr [esi+0x38], 32   ; actor 0..31
    jae d_sleep_short
    cmp dword ptr [esi+0x3c], 3    ; parameter 0..2
    jae d_sleep_short
    mov dword ptr [esp+0x58], 0
    lea eax, [esp+0x58]
    push eax
    call dword ptr [esi+0x24]      ; _NetMsg_GetIPAddress@4(&ptr)
    mov eax, [esp+0x58]
    test eax, eax
    jz d_sleep_short
    mov edi, [eax]                 ; own id
    test edi, edi
    jz d_sleep_short
    mov [esp+0x24], ebx            ; save core
    mov eax, ebx
    sub eax, 0x912                 ; G
    mov eax, [eax+0x80]            ; match gate before
    mov [esp+0x5c], eax
    lea ecx, [esp]                 ; &obj
    call dword ptr [esi+0x2c]      ; CSanInetDomesticCmd::ctor
    mov eax, [esi+0x38]
    mov [esp+0x14], eax            ; actor
    mov eax, [esi+0x3c]
    mov [esp+0x18], eax            ; parameter (0/1/2)
    mov eax, [esi+0x40]
    mov [esp+0x1c], eax            ; value
    mov eax, [esi+0x44]
    mov [esp+0x20], eax            ; extra
    mov ecx, [esi+0x34]            ; CSanInet member (static)
    lea eax, [esp]
    push eax
    call dword ptr [esi+0x30]      ; 0x42a7d4 SendObject(this, &obj), ret 4
    mov dword ptr [esi+4], 1       ; once-only, before any I/O
    ; ---- receipt (48 bytes at esp+0x28) ----
    mov dword ptr [esp+0x28], 0x43523553
    mov [esp+0x2c], eax            ; rc (1 = SendCmd accepted, 0 = error)
    mov ecx, [esp+0x24]
    mov [esp+0x30], ecx            ; core
    mov ecx, [esi+0x38]
    mov [esp+0x34], ecx            ; actor
    mov ecx, [esi+0x3c]
    mov [esp+0x38], ecx            ; parameter
    mov ecx, [esi+0x40]
    mov [esp+0x3c], ecx            ; value
    mov ecx, [esi+0x44]
    mov [esp+0x40], ecx            ; extra
    mov ecx, [esp+0x5c]
    mov [esp+0x48], ecx            ; gate before
    mov ecx, [esp+0x24]
    sub ecx, 0x912
    mov ecx, [ecx+0x80]
    mov [esp+0x4c], ecx            ; gate after
    mov ecx, [esp+0x24]
    movzx ecx, word ptr [ecx+0x4d8]
    mov [esp+0x50], ecx            ; phase/season step
    mov [esp+0x54], edi            ; own id
    call dword ptr [esi+0x1c]      ; GetTickCount
    mov [esp+0x44], eax            ; tick
    lea eax, [esi+0xD0]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+0x0C]      ; CreateFileA receipt, stdcall ret 28
    cmp eax, -1
    je d_after_receipt
    mov [esp+0x60], eax            ; handle
    push 0                         ; lpOverlapped
    lea eax, [esp+0x6C]            ; &written  (= E+0x68)
    push eax
    push 48                        ; nBytes
    lea eax, [esp+0x34]            ; buffer    (= E+0x28)
    push eax
    mov eax, [esp+0x70]            ; handle    (= E+0x60)
    push eax
    call dword ptr [esi+0x10]      ; WriteFileA, stdcall ret 20
    push dword ptr [esp+0x60]
    call dword ptr [esi+0x14]      ; CloseHandle, stdcall ret 4
d_after_receipt:
    push 1000
    call dword ptr [esi+0x18]      ; Sleep
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
"""


# ------------------------------------------------------------------ pure logic

def expected_wire(actor, parameter, value, extra):
    """Exact 54-byte payload the game serializes for one training command.

    Golden-checked against a real control5 record captured 2026-10-17
    (actor=7, parameter=0, value=95, extra=1).
    """
    for name, val, lo, hi in (('actor', actor, 0, 31), ('parameter', parameter, 0, 2)):
        if not isinstance(val, int) or not lo <= val <= hi:
            raise ValueError('%s out of range' % name)
    for name, val in (('value', value), ('extra', extra)):
        if not isinstance(val, int) or not -2 ** 31 <= val < 2 ** 31:
            raise ValueError('%s out of i32 range' % name)
    body = struct.pack('<3i', 18, 0, 0) + b'\x00' + struct.pack('<4i', actor, parameter, value, extra)
    return CLASS_HEADER + body


def build_blob(pointers, *, actor, parameter, value, extra, sanpk_base, flag_path, receipt_path,
               ctor_addr=None, send_addr=None, send_this_addr=None):
    blob = bytearray(BLOB_SIZE)

    def put32(off, val):
        struct.pack_into('<I', blob, off, val & 0xFFFFFFFF)

    def put_path(off, text, limit=128):
        raw = text.encode('utf-8')
        if len(raw) >= limit:
            raise ValueError('path too long')
        blob[off:off + len(raw)] = raw

    put32(0x00, MAGIC)
    put32(0x04, 0)
    for name, off in BLOB_LAYOUT[2:11]:
        if name not in pointers:
            raise ValueError('missing pointer: ' + name)
        put32(off, pointers[name])
    put32(0x2C, sanpk_base + RVA_CTOR if ctor_addr is None else ctor_addr)
    put32(0x30, sanpk_base + RVA_SEND if send_addr is None else send_addr)
    put32(0x34, sanpk_base + RVA_SEND_THIS if send_this_addr is None else send_this_addr)
    if not 0 <= actor < 32:
        raise ValueError('actor out of range')
    if not 0 <= parameter < 3:
        raise ValueError('parameter out of range')
    put32(0x38, actor)
    put32(0x3C, parameter)
    put32(0x40, value)
    put32(0x44, extra)
    put32(0x48, sanpk_base)
    put_path(FLAG_OFF, flag_path)
    put_path(RECEIPT_OFF, receipt_path)
    return bytes(blob)


def parse_receipt(data):
    if len(data) != RECEIPT_SIZE:
        raise ValueError('receipt must be %d bytes, got %d' % (RECEIPT_SIZE, len(data)))
    keys = ('magic2', 'rc', 'core', 'actor', 'parameter', 'value', 'extra', 'tick',
            'gate_before', 'gate_after', 'phase', 'own')
    return dict(zip(keys, struct.unpack('<12I', data)))


def assemble(asm_text, name, workdir):
    src = workdir / (name + '.s')
    obj = workdir / (name + '.obj')
    src.write_text(asm_text.replace('; ', '// '), encoding='utf-8')
    clang = shutil.which('clang')
    if clang is None:
        raise SystemExit('clang not found')
    subprocess.run([clang, '--target=i386-pc-windows-msvc', '-x', 'assembler',
                    '-c', str(src), '-o', str(obj)], check=True)
    data = obj.read_bytes()
    machine, nsec = struct.unpack_from('<HH', data, 0)
    if machine != 0x14C:
        raise SystemExit('unexpected COFF machine %x' % machine)
    text = None
    for i in range(nsec):
        off = 20 + i * 40
        name_b = data[off:off + 8].rstrip(b'\0')
        vsize, va, rawsize, rawptr = struct.unpack_from('<IIII', data, off + 8)
        nreloc = struct.unpack_from('<H', data, off + 32)[0]
        if name_b == b'.text':
            if nreloc:
                raise SystemExit('%s .text has %d relocations (must be none)' % (name, nreloc))
            text = data[rawptr:rawptr + rawsize]
    if not text:
        raise SystemExit('%s: .text not found' % name)
    return text


def disassemble(code):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.address, i.mnemonic, i.op_str, i.size) for i in md.disasm(code, 0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 'p59-domestic-cmd-1', 'target': 'i386-pc-windows-msvc',
                'blob_layout': {name: off for name, off in BLOB_LAYOUT},
                'blob_size': BLOB_SIZE, 'receipt_size': RECEIPT_SIZE,
                'anchors_va': {'CRuntimeClass': 0x5334B0, 'class_name': 0x533554,
                               'vtable': 0x5039F8, 'get_runtime_class': 0x4369DB,
                               'ctor': 0x4369F6, 'factory': 0x4369A9,
                               'serialize': 0x436A6F,
                               'handoff_ui_path': 0x446482, 'send_object': 0x42A7D4,
                               'send_cmd': 0x42A7AC, 'send_this': 0x53B672,
                               'core_global': 0x53BB30},
                'anchors_rva': {'vtable': RVA_VTABLE, 'class': RVA_CLASS, 'name': RVA_NAME,
                                'factory': RVA_FACTORY, 'serialize': RVA_SERIALIZE,
                                'get_runtime_class': RVA_GETRUNTIMECLASS,
                                'ctor': RVA_CTOR, 'send': RVA_SEND,
                                'send_this': RVA_SEND_THIS,
                                'core_global': RVA_CORE_GLOBAL, 'g_from_core': RVA_G_FROM_CORE}}
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        code = assemble(AGENT_ASM, 'agent_domestic', tmpdir)
        listing = disassemble(code)
        if not listing or listing[0][1] != 'push':
            raise SystemExit('agent entry does not start with push')
        if len(code) > 640:
            raise SystemExit('agent too large: %d' % len(code))
        ops = [m for _, m, _, _ in listing]
        for must in ('call', 'movzx', 'jmp'):
            if must not in ops:
                raise SystemExit('agent missing expected op: ' + must)
        (outdir / 'agent_domestic.s').write_text(AGENT_ASM.replace('; ', '// '), encoding='utf-8')
        (outdir / 'agent_domestic.bin').write_bytes(code)
        (outdir / 'agent_domestic.listing.txt').write_text(
            '\n'.join('%04x: %-7s %s' % (a, m, o) for a, m, o, _ in listing) + '\n', encoding='utf-8')
        manifest['agent_domestic'] = {'size': len(code),
                                     'sha256': hashlib.sha256(code).hexdigest(),
                                     'instructions': len(listing)}
        manifest['golden_wire_actor7'] = expected_wire(7, 0, 95, 1).hex()
    (outdir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                          encoding='utf-8')
    print(json.dumps({'ok': True, 'outdir': str(outdir),
                      'size': manifest['agent_domestic']['size'],
                      'sha256': manifest['agent_domestic']['sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
