#!/usr/bin/env python3
"""Read-only verification of the two observer-side element-fallback caves.

Checks, in the live SANPK process:
  * 0x4195C4 holds a 5-byte jmp; the cave it points at starts with
    `call 0x4D3214` and ends with `jmp 0x4195C9`;
  * 0x4A3E15 / 0x48F06C / 0x48F215 hold 5-byte jmps; each cave starts with
    `call 0x4195A9` and its trailing `jmp` lands on site+5;
  * 0x4195AF still holds the original `33 FF` (xor edi,edi = NULL seed).

Never writes. Usage: verify_shadow_caves.py <pid>
"""
from __future__ import annotations

import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

ELEMENT_SITE = 0x4195C4
ELEMENT_RET = 0x4195C9
CAST_FN = 0x4D3214
SEED_VA = 0x4195AF
PANEL_SITES = (0x4A3E15, 0x48F06C, 0x48F215)
WALKER = 0x4195A9
ACCESS = 0x0010 | 0x0008


def k32():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    return k


def read_at(k, h, addr, n):
    buf = c.create_string_buffer(n)
    got = c.c_size_t()
    ok = k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got))
    if not ok or got.value != n:
        return None
    return buf.raw


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'usage: verify_shadow_caves.py <pid>'}))
        return 2
    pid = int(sys.argv[1])
    k = k32()
    h = k.OpenProcess(ACCESS, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess', 'err': c.get_last_error()}))
        return 1
    out = {'pid': pid}
    try:
        seed = read_at(k, h, SEED_VA, 2)
        out['seed_4195af'] = seed.hex() if seed else None
        out['seed_ok'] = seed == bytes.fromhex('33ff')

        site = read_at(k, h, ELEMENT_SITE, 5)
        info = {'site': hex(ELEMENT_SITE), 'bytes': site.hex() if site else None}
        if site and site[0] == 0xE9:
            cave = (ELEMENT_SITE + 5 + struct.unpack_from('<i', site, 1)[0]) & 0xFFFFFFFF
            info['cave'] = hex(cave)
            blob = read_at(k, h, cave, 0x16)
            if blob:
                info['cave_hex'] = blob.hex()
                info['calls_cast'] = (blob[0] == 0xE8 and
                                      ((cave + 5 + struct.unpack_from('<i', blob, 1)[0]) & 0xFFFFFFFF) == CAST_FN)
                info['jumps_back'] = (blob[0x11] == 0xE9 and
                                      ((cave + 0x16 + struct.unpack_from('<i', blob, 0x12)[0]) & 0xFFFFFFFF) == ELEMENT_RET)
        out['element'] = info

        panels = []
        for s in PANEL_SITES:
            site = read_at(k, h, s, 5)
            e = {'site': hex(s), 'bytes': site.hex() if site else None}
            if site and site[0] == 0xE9:
                cave = (s + 5 + struct.unpack_from('<i', site, 1)[0]) & 0xFFFFFFFF
                e['cave'] = hex(cave)
                blob = read_at(k, h, cave, 0x2F)
                if blob:
                    e['cave_hex'] = blob.hex()
                    e['calls_walker'] = (blob[0] == 0xE8 and
                                         ((cave + 5 + struct.unpack_from('<i', blob, 1)[0]) & 0xFFFFFFFF) == WALKER)
                    e['jumps_back'] = (blob[0x2A] == 0xE9 and
                                       ((cave + 0x2F + struct.unpack_from('<i', blob, 0x2B)[0]) & 0xFFFFFFFF) == s + 5)
            panels.append(e)
        out['panel_rows'] = panels
        out['ok'] = bool(out['seed_ok'] and out['element'].get('calls_cast') and
                         out['element'].get('jumps_back') and
                         all(p.get('calls_walker') and p.get('jumps_back') for p in panels))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out['ok'] else 1
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    sys.exit(main())
