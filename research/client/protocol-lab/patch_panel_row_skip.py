#!/usr/bin/env python3
"""Skip the panel-row update when the element list has no matching element.

Replaces the earlier "synthesise a dummy element" approach (2026-10-19 19:29).
That version kept the client alive but still produced a burst of five handled
access violations per training click (EIP 0x7BFA4376, chain
0x4A3EC6 -> 0x485570 -> 0x485431 -> 0x485477): the synthetic element was fed
into the game's notify path, which expects a real panel row.

New behaviour: nothing synthetic is ever created. If the shared look-up
(0x4195A9) returns NULL for the row id, jump straight to the enclosing
function's own epilogue. Nothing to notify, nothing to crash.

Sites and their clean landing points (all verified in sanpk-full.objdump.asm):
  0x4A3E15  row 0x12E  -> 0x4A409F   (mov ecx,[ebp-0xc]; pop/pop; fs:0; leave; ret 4)
  0x48F06C  row 0x12C  -> 0x48F088   (orl $-1,-4(ebp); lea/pop; fs:0; leave; ret 4)
  0x48F215  row 0x12C  -> 0x48F231   (same shape)

Cave per site (19 bytes):
  e8 <walk>    call 0x4195A9      ; args are already on the stack; the walker is
                                  ; stdcall (ret 8) and eats them plus our return
  85 c0        test eax,eax
  74 05        jz  skip
  e9 <site+5>  jmp back           ; normal path, exactly like the original call
skip:
  e9 <epilogue> jmp epilogue      ; leave the function without dereferencing NULL

Note: jumping to the epilogue skips the compiler's local-object cleanup for that
frame, so each skipped call leaks the objects allocated before the look-up
(0x44 bytes each). That is a deliberate, bounded trade (one click = one leak)
in exchange for never handing a fake object to the notify path.

Usage (wine py32 inside the target prefix):
  patch_panel_row_skip.py <pid>
  patch_panel_row_skip.py <pid> --revert
  patch_panel_row_skip.py <pid> --dry-run
  patch_panel_row_skip.py --selftest
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

WALKER = 0x4195A9

# (name, call site va, original 5 bytes: call 0x4195A9, epilogue va)
SITES = (
    ('panel-row-12e', 0x4A3E15, bytes.fromhex('e88f57f7ff'), 0x4A409F),
    ('panel-row-12c-a', 0x48F06C, bytes.fromhex('e838a5f8ff'), 0x48F088),
    ('panel-row-12c-b', 0x48F215, bytes.fromhex('e88fa3f8ff'), 0x48F231),
)
CAVE_STRIDE = 0x40
CAVE_SIZE = 0x1000
PAGE_RWX = 0x40
MEM_COMMIT_RESERVE = 0x3000
ACCESS = 0x0010 | 0x0020 | 0x0008 | 0x0400


def build_cave(cave: int, site: int, epilogue: int) -> bytes:
    # NOTE: the hook is a `jmp`, so the stack at cave entry holds only the two
    # pushed arguments. A plain `call WALKER` gives the callee exactly the
    # argument layout it expects; its `ret 8` consumes them plus our return.
    b = bytearray()
    b += b'\xe8' + struct.pack('<i', WALKER - (cave + 5))      # call walker
    b += b'\x85\xc0'                                           # test eax,eax
    b += b'\x74\x05'                                           # jz skip  (0x09+5=0x0E)
    b += b'\xe9' + struct.pack('<i', (site + 5) - (cave + 0x0E))    # jmp site+5
    b += b'\xe9' + struct.pack('<i', epilogue - (cave + 0x13))      # jmp epilogue
    assert len(b) == 0x13, hex(len(b))
    return bytes(b)


def site_hook(site: int, cave: int) -> bytes:
    return b'\xe9' + struct.pack('<i', cave - (site + 5))


def _k32():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAllocEx.restype = c.c_void_p
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    k.VirtualProtectEx.restype = w.BOOL
    k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.WriteProcessMemory.restype = w.BOOL
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]
    k.CloseHandle.argtypes = [w.HANDLE]
    return k


def read_at(k, h, addr, n):
    buf = c.create_string_buffer(n)
    got = c.c_size_t()
    ok = k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got))
    if not ok or got.value != n:
        return None
    return buf.raw


def write_at(k, h, addr, data):
    old = w.DWORD(0)
    prot = bool(k.VirtualProtectEx(h, c.c_void_p(addr), len(data), PAGE_RWX, c.byref(old)))
    got = c.c_size_t()
    raw = c.create_string_buffer(data, len(data))
    ok = bool(k.WriteProcessMemory(h, c.c_void_p(addr), raw, len(data), c.byref(got)) and got.value == len(data))
    if prot:
        tmp = w.DWORD(0)
        k.VirtualProtectEx(h, c.c_void_p(addr), len(data), old.value, c.byref(tmp))
    k.FlushInstructionCache(h, c.c_void_p(addr), len(data))
    back = read_at(k, h, addr, len(data))
    return back == data, back.hex() if back else None


def find_sanpk_pid():
    k32 = c.WinDLL('kernel32', use_last_error=True)
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(c.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                    ("th32DefaultHeapID", c.POINTER(c.c_ulong)), ("th32ModuleID", w.DWORD),
                    ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                    ("pcPriClassBase", c.c_long), ("dwFlags", w.DWORD),
                    ("szExeFile", c.c_char * 260)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    e = PROCESSENTRY32()
    e.dwSize = c.sizeof(PROCESSENTRY32)
    out = []
    ok = k32.Process32First(snap, c.byref(e))
    while ok:
        if e.szExeFile.decode('gbk', 'replace').lower().startswith('sanpk'):
            out.append(e.th32ProcessID)
        ok = k32.Process32Next(snap, c.byref(e))
    k32.CloseHandle(snap)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pid', type=int, nargs='?')
    ap.add_argument('--revert', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        cave = 0x10000000
        for i, (name, site, orig, epi) in enumerate(SITES):
            base = cave + i * CAVE_STRIDE
            b = build_cave(base, site, epi)
            assert b[0] == 0xE8
            assert (base + 5 + struct.unpack_from('<i', b, 1)[0]) & 0xFFFFFFFF == WALKER
            assert b[5:7] == b'\x85\xc0'
            assert b[7] == 0x74 and 0x09 + b[8] == 0x0E
            assert b[9] == 0xE9
            assert (base + 0x0E + struct.unpack_from('<i', b, 10)[0]) & 0xFFFFFFFF == site + 5
            assert b[0x0E] == 0xE9
            assert (base + 0x13 + struct.unpack_from('<i', b, 0x0F)[0]) & 0xFFFFFFFF == epi
            assert len(b) == 0x13
            hook = site_hook(site, base)
            assert hook[0] == 0xE9
            assert (site + 5 + struct.unpack_from('<i', hook, 1)[0]) & 0xFFFFFFFF == base
            assert len(orig) == 5
        print(json.dumps({'selftest': True, 'sites': len(SITES), 'cave_bytes': 0x13}))
        return 0

    pid = args.pid
    if pid is None:
        pids = find_sanpk_pid()
        if len(pids) != 1:
            print(json.dumps({'error': 'pid required', 'sanpk_pids': pids}))
            return 1
        pid = pids[0]

    k = _k32()
    h = k.OpenProcess(ACCESS, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess', 'pid': pid, 'err': c.get_last_error()}))
        return 1
    try:
        current = {}
        for name, site, orig, _epi in SITES:
            got = read_at(k, h, site, 5)
            if got is None:
                print(json.dumps({'error': 'read failed', 'pid': pid, 'site': name}))
                return 1
            current[name] = got

        if args.revert:
            out = {'pid': pid, 'mode': 'revert', 'sites': []}
            for name, site, orig, _epi in SITES:
                if current[name] == orig:
                    out['sites'].append({'site': name, 'action': 'already-original'})
                    continue
                ok, back = write_at(k, h, site, orig)
                out['sites'].append({'site': name, 'ok': ok, 'back': back})
                if not ok:
                    out['ok'] = False
                    print(json.dumps(out))
                    return 1
            out['ok'] = True
            print(json.dumps(out))
            return 0

        todo = []
        for name, site, orig, epi in SITES:
            cur = current[name]
            if cur[0] == 0xE9:
                continue
            if cur != orig:
                print(json.dumps({'error': 'unexpected site bytes', 'pid': pid,
                                  'site': name, 'hex': cur.hex()}))
                return 1
            todo.append((name, site, epi))
        if not todo:
            print(json.dumps({'pid': pid, 'mode': 'panel-row-skip', 'ok': True, 'already': True}))
            return 0
        if args.dry_run:
            print(json.dumps({'pid': pid, 'mode': 'panel-row-skip', 'ok': True,
                              'dry_run': True, 'would_patch': [t[0] for t in todo]}))
            return 0

        cave = k.VirtualAllocEx(h, None, CAVE_SIZE, MEM_COMMIT_RESERVE, PAGE_RWX)
        if not cave:
            print(json.dumps({'error': 'VirtualAllocEx', 'err': c.get_last_error()}))
            return 1
        cave = int(cave)
        patched = []
        names = [s[0] for s in SITES]
        for name, site, epi in todo:
            i = names.index(name)
            base = cave + i * CAVE_STRIDE
            blob = build_cave(base, site, epi)
            ok, back = write_at(k, h, base, blob)
            if not ok:
                print(json.dumps({'error': 'cave write mismatch', 'site': name, 'back': back}))
                return 1
            ok2, back2 = write_at(k, h, site, site_hook(site, base))
            patched.append({'site': name, 'va': hex(site), 'epilogue': hex(epi),
                            'ok': bool(ok2), 'back': back2})
            if not ok2:
                print(json.dumps({'pid': pid, 'cave': hex(cave), 'patched': patched, 'ok': False}))
                return 1
        print(json.dumps({'pid': pid, 'cave': hex(cave), 'patched': patched,
                          'mode': 'panel-row-skip', 'ok': True}))
        return 0
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    sys.exit(main())
