#!/usr/bin/env python3
"""P60 builder: generic interface-free faction-command sender (any CSanInet*Cmd).

Same trust path as P59 (game's own constructor + game's own 0x42A7D4 send), but
the object layout is described by a small table in the injected blob, so any
command class / subtype can be sent without rebuilding the agent:

    blob: ctor, send, send_this, obj_size, nfields, table_off, flag/receipt paths,
          then N pairs of (object_offset, value) — applied after the ctor runs.

Verified class layouts (SANPK 3.5, 2026-10-19):

  CSanInetDomesticCmd   vtable 0x5039F8  ctor 0x4369F6  size 0x24
      +0x04 kind 18, +0x08 subtype (0 train / 2 alms / 3 rice / 4 build / 5 raze /
      8 scout), +0x0C action operand (packed XY for 4/5/8), +0x14 actor,
      +0x18 parameter, +0x1C value, +0x20 extra
  CSanInetPersonnelCmd  vtable 0x503A28  ctor 0x436CD3  size 0x1C
      +0x04 kind 20, +0x08 subtype (0 hire / 1 accept / 2 dismiss / 5 add),
      +0x14 actor, +0x18 target
  CSanInetPhaseEndCmd   vtable 0x503A40  ctor 0x436DDA  size 0x14
      +0x04 kind 21 only
  CSanInetDiplomacyCmd  vtable 0x503A10  ctor 0x436B2E  size 0x33
      +0x14..0x18 flags, +0x19/+0x1D/+0x21/+0x25 ints, +0x29.. five u16 cards
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

MAGIC = 0x36474853          # 'SHG6'
MAGIC2 = 0x53365243         # 'S6RC' little-endian
BLOB_SIZE = 0x200
FLAG_OFF = 0x48
RECEIPT_OFF = 0xC8
RECEIPT_SIZE = 64
TABLE_OFF = 0x148
MAX_FIELDS = 16

BASE_PREFERRED = 0x400000
RVA_CORE_GLOBAL = 0x13BB30
RVA_SEND = 0x42A7D4 - BASE_PREFERRED
RVA_SEND_THIS = 0x13B672
RVA_VTABLE = 0x5039F8 - BASE_PREFERRED
RVA_CLASS = 0x5334B0 - BASE_PREFERRED
RVA_NAME = 0x533554 - BASE_PREFERRED
RVA_FACTORY = 0x4369A9 - BASE_PREFERRED
RVA_SERIALIZE = 0x436A6F - BASE_PREFERRED
RVA_GETRUNTIMECLASS = 0x4369DB - BASE_PREFERRED
A_SIZE = 0x24
A_SCHEMA = 1

# class registry: name -> (ctor VA, object size, kind, vtable VA)
CLASSES = {
    'domestic': (0x4369F6, 0x24, 18, 0x5039F8),
    'personnel': (0x436CD3, 0x1C, 20, 0x503A28),
    'phaseend': (0x436DDA, 0x14, 21, 0x503A40),
    'diplomacy': (0x436B2E, 0x33, 19, 0x503A10),
}

BLOB_LAYOUT = (
    ('magic', 0x00), ('sent', 0x04),
    ('GetFileAttributesA', 0x08), ('CreateFileA', 0x0C), ('WriteFileA', 0x10),
    ('CloseHandle', 0x14), ('Sleep', 0x18), ('GetTickCount', 0x1C),
    ('is_connected', 0x20), ('get_ip', 0x24), ('core_global', 0x28),
    ('ctor', 0x2C), ('send', 0x30), ('send_this', 0x34),
    ('obj_size', 0x38), ('nfields', 0x3C), ('table_off', 0x40), ('class_tag', 0x44),
)
POINTER_NAMES = tuple(name for name, _ in BLOB_LAYOUT[2:11])

AGENT_ASM = r"""
.intel_syntax noprefix
.text
.globl agent_start
agent_start:
    push esi
    push ebx
    push edi
    sub esp, 0x160
    mov esi, [esp+0x170]            ; blob ptr (0x160 + 3 pushes + ret)
    cmp dword ptr [esi], 0x36474853 ; 'SHG6'
    jne g_spin
g_loop:
    cmp dword ptr [esi+4], 0
    jne g_sleep_long
    lea eax, [esi+0x48]
    push eax
    call dword ptr [esi+8]          ; GetFileAttributesA(flag)
    cmp eax, -1
    je g_sleep_short
    call dword ptr [esi+0x20]       ; IsConnected
    test eax, eax
    jz g_sleep_short
    mov eax, [esi+0x28]             ; &core
    test eax, eax
    jz g_sleep_short
    mov ebx, [eax]                  ; core
    test ebx, ebx
    jz g_sleep_short
    mov ecx, [ebx+0x6c0]            ; my_slot
    cmp ecx, 7
    ja g_sleep_short
    mov dword ptr [esp+0x108], 0
    lea eax, [esp+0x108]
    push eax
    call dword ptr [esi+0x24]       ; GetIPAddress(&ptr)
    mov eax, [esp+0x108]
    test eax, eax
    jz g_sleep_short
    mov eax, [eax]
    test eax, eax
    jz g_sleep_short
    mov [esp+0x10C], eax            ; own id
    mov [esp+0x100], ebx            ; core
    mov eax, ebx
    sub eax, 0x912
    mov eax, [eax+0x80]
    mov [esp+0x104], eax            ; gate before
    lea ecx, [esp]
    call dword ptr [esi+0x2C]       ; the game's own ctor
    mov ecx, [esi+0x3C]
    test ecx, ecx
    jz g_fields_done
    mov edi, [esi+0x40]
    add edi, esi
g_floop:
    mov eax, [edi]
    mov edx, [edi+4]
    mov [esp+eax], edx
    add edi, 8
    dec ecx
    jnz g_floop
g_fields_done:
    mov ecx, [esi+0x34]
    lea eax, [esp]
    push eax
    call dword ptr [esi+0x30]       ; 0x42a7d4 SendObject(this,&obj), ret 4
    mov dword ptr [esi+4], 1
    mov dword ptr [esp+0x110], 0x53365243
    mov [esp+0x114], eax            ; rc
    mov ecx, [esp+0x100]
    mov [esp+0x118], ecx            ; core
    mov ecx, [esp+0x10C]
    mov [esp+0x11C], ecx            ; own
    mov ecx, [esp+0x104]
    mov [esp+0x120], ecx            ; gate before
    mov ecx, [esp+0x100]
    sub ecx, 0x912
    mov ecx, [ecx+0x80]
    mov [esp+0x124], ecx            ; gate after
    mov ecx, [esp+0x100]
    movzx ecx, word ptr [ecx+0x4d8]
    mov [esp+0x128], ecx            ; phase
    call dword ptr [esi+0x1C]       ; GetTickCount
    mov [esp+0x12C], eax            ; tick
    mov eax, [esp+0x00]
    mov [esp+0x130], eax
    mov eax, [esp+0x04]
    mov [esp+0x134], eax
    mov eax, [esp+0x08]
    mov [esp+0x138], eax
    mov eax, [esp+0x0C]
    mov [esp+0x13C], eax
    mov eax, [esp+0x14]
    mov [esp+0x140], eax
    mov eax, [esp+0x18]
    mov [esp+0x144], eax
    mov eax, [esp+0x1C]
    mov [esp+0x148], eax
    mov eax, [esp+0x20]
    mov [esp+0x14C], eax
    lea eax, [esi+0xC8]
    push 0
    push 128
    push 2
    push 0
    push 3
    push 0x40000000
    push eax
    call dword ptr [esi+0x0C]       ; CreateFileA receipt
    cmp eax, -1
    je g_after_receipt
    mov [esp+0x150], eax
    push 0
    lea eax, [esp+0x158]
    push eax
    push 64
    lea eax, [esp+0x11C]
    push eax
    mov eax, [esp+0x160]
    push eax
    call dword ptr [esi+0x10]       ; WriteFileA
    push dword ptr [esp+0x150]
    call dword ptr [esi+0x14]       ; CloseHandle
g_after_receipt:
    push 1000
    call dword ptr [esi+0x18]
    jmp g_loop
g_sleep_short:
    push 250
    call dword ptr [esi+0x18]
    jmp g_loop
g_sleep_long:
    push 1000
    call dword ptr [esi+0x18]
    jmp g_loop
g_spin:
    push 5000
    call dword ptr [esi+0x18]
    jmp g_spin
"""


# ------------------------------------------------------------------ presets

def fields_train(actor, troop, value, extra):
    return [(0x04, 18), (0x08, 0), (0x0C, 0), (0x14, actor), (0x18, troop),
            (0x1C, value), (0x20, extra)]


def fields_alms(actor, value, extra):
    """kind 18 subtype 2 施捨.  Real capture: parameter=0, value=0, extra=4."""
    return [(0x04, 18), (0x08, 2), (0x0C, 0), (0x14, actor), (0x18, 0),
            (0x1C, value), (0x20, extra)]


def fields_rice(actor, buy, value, extra):
    """kind 18 subtype 3 米交易.  parameter 0=sell rice, 1=buy rice."""
    return [(0x04, 18), (0x08, 3), (0x0C, 0), (0x14, actor), (0x18, buy),
            (0x1C, value), (0x20, extra)]


def fields_build(actor, build_type, x, y, value, extra):
    """kind 18 subtype 4 建設: parameter 4..9, base operand = packed XY."""
    packed = ((x & 0xFFFF) | ((y & 0xFFFF) << 16))
    return [(0x04, 18), (0x08, 4), (0x0C, packed), (0x14, actor), (0x18, build_type),
            (0x1C, value), (0x20, extra)]


def fields_personnel(actor, subtype, target):
    return [(0x04, 20), (0x08, subtype), (0x0C, 0), (0x14, actor), (0x18, target)]


def fields_phaseend():
    return [(0x04, 21), (0x08, 0), (0x0C, 0)]


PRESETS = {
    'train': (fields_train, ('actor', 'troop', 'value', 'extra')),
    'alms': (fields_alms, ('actor', 'value', 'extra')),
    'rice': (fields_rice, ('actor', 'buy', 'value', 'extra')),
    'build': (fields_build, ('actor', 'build_type', 'x', 'y', 'value', 'extra')),
    'personnel': (fields_personnel, ('actor', 'subtype', 'target')),
    'phaseend': (fields_phaseend, ()),
}


def build_blob(pointers, *, cls, fields, sanpk_base, flag_path, receipt_path, class_tag=0):
    if cls not in CLASSES:
        raise ValueError('unknown class: ' + cls)
    ctor_va, size, kind, _vtable = CLASSES[cls]
    if len(fields) > MAX_FIELDS:
        raise ValueError('too many fields')
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
    put32(0x2C, sanpk_base + (ctor_va - BASE_PREFERRED))
    put32(0x30, sanpk_base + RVA_SEND)
    put32(0x34, sanpk_base + RVA_SEND_THIS)
    put32(0x38, size)
    put32(0x3C, len(fields))
    put32(0x40, TABLE_OFF)
    put32(0x44, class_tag if class_tag else kind)
    put_path(FLAG_OFF, flag_path)
    put_path(RECEIPT_OFF, receipt_path)
    for i, (off, val) in enumerate(fields):
        struct.pack_into('<2I', blob, TABLE_OFF + i * 8, off & 0xFFFFFFFF, val & 0xFFFFFFFF)
    return bytes(blob)


def parse_receipt(data):
    if len(data) != RECEIPT_SIZE:
        raise ValueError('receipt must be %d bytes, got %d' % (RECEIPT_SIZE, len(data)))
    keys = ('magic2', 'rc', 'core', 'own', 'gate_before', 'gate_after', 'phase', 'tick',
            'vtable', 'kind', 'subtype', 'operand', 'f14', 'f18', 'f1c', 'f20')
    return dict(zip(keys, struct.unpack('<16I', data)))


# ------------------------------------------------------------- static checks

def pe_image(data):
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
    """Check every registered class ctor + kind in an on-disk SANPK.exe."""
    image_base, read = pe_image(data)
    out = {'image_base': image_base, 'classes': {}, 'problems': []}
    for name, (ctor_va, size, kind, vtable_va) in CLASSES.items():
        rec = {}
        try:
            prologue = read(image_base + (ctor_va - BASE_PREFERRED), 16)
            rec['ctor_prologue'] = prologue.hex()
            # ctor bodies start with push esi (0x56) and push the empty CString
            ok_prologue = prologue[:1] == b'\x56' and prologue[1:3] == b'\x57' or prologue[1:2] == b'\x56'
            # kind immediate inside the ctor: find "6a <kind>" among the first 40 bytes
            body = read(image_base + (ctor_va - BASE_PREFERRED), 40)
            rec['kind_push_found'] = bytes([0x6A, kind & 0xFF]) in body
            vtable = struct.unpack('<I', read(image_base + (vtable_va - BASE_PREFERRED), 4))[0]
            rec['vtable_serialize_rva'] = vtable - image_base
            rec['ok'] = rec['kind_push_found']
        except Exception as exc:  # noqa: BLE001
            rec = {'ok': False, 'error': str(exc)}
        if not rec.get('ok'):
            out['problems'].append(name)
        out['classes'][name] = rec
    # training class anchors (kind 18)
    out['domestic_class_name'] = read(image_base + RVA_NAME, 19).decode('latin1')
    out['domestic_class_size'] = struct.unpack('<I', read(image_base + RVA_CLASS + 4, 4))[0]
    out['domestic_serialize_rva'] = struct.unpack('<I', read(image_base + RVA_VTABLE + 8, 4))[0] - image_base
    if out['domestic_class_name'] != 'CSanInetDomesticCmd':
        out['problems'].append('domestic name')
    if out['domestic_class_size'] != A_SIZE:
        out['problems'].append('domestic size')
    if out['domestic_serialize_rva'] != RVA_SERIALIZE:
        out['problems'].append('domestic serialize')
    out['ok'] = not out['problems']
    return out


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
        sec = data[off:off + 8].rstrip(b'\0')
        vsize, va, rawsize, rawptr = struct.unpack_from('<IIII', data, off + 8)
        nreloc = struct.unpack_from('<H', data, off + 32)[0]
        if sec == b'.text':
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
    manifest = {'schema': 'p60-generic-cmd-1', 'target': 'i386-pc-windows-msvc',
                'blob_layout': {n: o for n, o in BLOB_LAYOUT},
                'blob_size': BLOB_SIZE, 'receipt_size': RECEIPT_SIZE, 'table_off': TABLE_OFF,
                'classes': {n: {'ctor': hex(c[0]), 'size': c[1], 'kind': c[2], 'vtable': hex(c[3])}
                            for n, c in CLASSES.items()},
                'presets': {k: list(v[1]) for k, v in PRESETS.items()}}
    with tempfile.TemporaryDirectory() as tmp:
        code = assemble(AGENT_ASM, 'agent_generic', Path(tmp))
        listing = disassemble(code)
        if not listing or listing[0][1] != 'push':
            raise SystemExit('agent entry does not start with push')
        if len(code) > 800:
            raise SystemExit('agent too large: %d' % len(code))
        (outdir / 'agent_generic.s').write_text(AGENT_ASM.replace('; ', '// '), encoding='utf-8')
        (outdir / 'agent_generic.bin').write_bytes(code)
        (outdir / 'agent_generic.listing.txt').write_text(
            '\n'.join('%04x: %-7s %s' % (a, m, o) for a, m, o, _ in listing) + '\n', encoding='utf-8')
        manifest['agent_generic'] = {'size': len(code),
                                     'sha256': hashlib.sha256(code).hexdigest(),
                                     'instructions': len(listing)}
    (outdir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                          encoding='utf-8')
    print(json.dumps({'ok': True, 'size': manifest['agent_generic']['size'],
                      'sha256': manifest['agent_generic']['sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
