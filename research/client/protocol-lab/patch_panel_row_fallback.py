#!/usr/bin/env python3
"""Give the panel-row element lookups a real element when the container is empty.

2026-10-19 19:26 crash (observer client, panel/training row update):
    eip=0x4a3e1e  `mov esi,[ebx+0x3c]`  ebx=0  edi=0x49d3230 (valid dialog this)
    0x4a3e15 call 0x4195A9  -> container at [dialog+0x7EA] has NO elements
    -> walker returns NULL (even with the type-safe miss fallback installed)
    -> 0x4a3e1a mov ebx,eax ; 0x4a3e1e reads [0+0x3C] -> AV

The observer client never builds its info-panel element list (no player row ->
no panel), while the UI still runs the periodic "update row 0x12C..0x133"
routines. Those are the only three live call sites that dereference the walker
result immediately; the rest live inside already-stubbed UI refreshers.

Fix (memory only, per process): retarget each call site to a cave that
  1. runs the original walker (stdcall, ret 8),
  2. if it returns NULL, hands back a cached real element created by the game's
     own constructor pair (operator new 0x44 / ctor 0x485256).
That object has the right vtable (0x50A4F8), the right size and zeroed numeric
fields ([+0x38]=-1, [+0x3C]=0, [+0x40]=0 per base ctor 0x484101), so every
later [elem+0x3C] read, comparison and virtual call stays inside a valid object
of the correct class. Nothing is sent; the object is local scratch state.

Cave (55 bytes, one copy per site, own return-address slot each):
  58            pop eax                     ; return address (args are under it)
  a3 <RET_i>    mov [RET_i],eax
  e8 <walk>     call 0x4195A9               ; stdcall ret 8 consumes the two args
  85 c0         test eax,eax
  75 21         jnz have
  a1 <DUMMY>    mov eax,[DUMMY]
  85 c0         test eax,eax
  75 18         jnz have
  6a 44         push 0x44
  e8 <new>      call 0x4D1D22               ; operator new(0x44)
  59            pop ecx
  85 c0         test eax,eax
  74 0c         jz have                     ; allocation failed -> keep NULL
  8b c8         mov ecx,eax
  e8 <ctor>     call 0x485256               ; ecx = this -> eax = object
  a3 <DUMMY>    mov [DUMMY],eax             ; cache it (one object per process)
have:
  ff 35 <RET_i> push dword [RET_i]
  c3            ret

Usage (wine py32 inside the target prefix):
  patch_panel_row_fallback.py <pid>
  patch_panel_row_fallback.py <pid> --revert
  patch_panel_row_fallback.py <pid> --dry-run
  patch_panel_row_fallback.py --selftest
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

WALKER = 0x4195A9
OPNEW = 0x4D1D22
CTOR = 0x485256

# (name, call site va, original 5 bytes: call 0x4195A9)
SITES = (
    ('panel-row-12e', 0x4A3E15, bytes.fromhex('e88f57f7ff')),
    ('panel-row-12c-a', 0x48F06C, bytes.fromhex('e838a5f8ff')),
    ('panel-row-12c-b', 0x48F215, bytes.fromhex('e88fa3f8ff')),
)
CAVE_STRIDE = 0x40
RET_BASE = 0x200
DUMMY_SLOT = 0x240
CAVE_SIZE = 0x1000
PAGE_RWX = 0x40
MEM_COMMIT_RESERVE = 0x3000
ACCESS = 0x0010 | 0x0020 | 0x0008 | 0x0400


def build_cave(cave: int, dummy_slot: int) -> bytes:
    # NOTE 2026-10-19 19:3x: the site hook is a `jmp`, so at cave entry the
    # stack still holds the two pushed arguments and NO return address.
    # A plain `call WALKER` therefore hands the callee exactly the argument
    # layout it expects ([esp+4]=arg1 container, [esp+8]=arg2 id); the walker
    # is stdcall (`ret 8`) and consumes them plus our return address.
    b = bytearray()
    b += b'\xe8' + struct.pack('<i', WALKER - (cave + 5))     # call walker
    b += b'\x85\xc0'                                          # test eax,eax
    b += b'\x75' + bytes([0x2A - 0x09])                       # jnz have
    b += b'\xa1' + struct.pack('<I', dummy_slot)              # mov eax,[DUMMY]
    b += b'\x85\xc0'                                          # test eax,eax
    b += b'\x75' + bytes([0x2A - 0x12])                       # jnz have
    b += b'\x6a\x44'                                          # push 0x44
    b += b'\xe8' + struct.pack('<i', OPNEW - (cave + 0x19))   # call operator new
    b += b'\x59'                                              # pop ecx
    b += b'\x85\xc0'                                          # test eax,eax
    b += b'\x74' + bytes([0x2A - 0x1E])                       # jz have
    b += b'\x8b\xc8'                                          # mov ecx,eax
    b += b'\xe8' + struct.pack('<i', CTOR - (cave + 0x25))    # call ctor
    b += b'\xa3' + struct.pack('<I', dummy_slot)              # mov [DUMMY],eax
    # have: 0x2A -> jump back to the instruction after the original call
    b += b'\xe9' + b'\x00\x00\x00\x00'                        # jmp site+5 (patched by caller)
    assert len(b) == 0x2F, hex(len(b))
    return bytes(b)


def finish_cave(blob: bytes, cave: int, site: int) -> bytes:
    """Patch the trailing jmp of a site cave (cave+0x2A) to resume at site+5."""
    out = bytearray(blob)
    struct.pack_into('<i', out, 0x2B, (site + 5) - (cave + 0x2F))
    return bytes(out)


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
        for i, (name, site, orig) in enumerate(SITES):
            base = cave + i * CAVE_STRIDE
            b = finish_cave(build_cave(base, cave + DUMMY_SLOT), base, site)
            assert b[0] == 0xE8
            assert (base + 5 + struct.unpack_from('<i', b, 1)[0]) & 0xFFFFFFFF == WALKER
            assert b[5:7] == b'\x85\xc0'
            assert b[7] == 0x75 and 0x09 + b[8] == 0x2A
            assert b[9] == 0xA1 and struct.unpack_from('<I', b, 10)[0] == cave + DUMMY_SLOT
            assert b[14:16] == b'\x85\xc0'
            assert b[16] == 0x75 and 0x12 + b[17] == 0x2A
            assert b[18:20] == b'\x6a\x44'
            assert b[20] == 0xE8
            assert (base + 0x19 + struct.unpack_from('<i', b, 21)[0]) & 0xFFFFFFFF == OPNEW
            assert b[25] == 0x59 and b[26:28] == b'\x85\xc0'
            assert b[28] == 0x74 and 0x1E + b[29] == 0x2A
            assert b[30:32] == b'\x8b\xc8' and b[32] == 0xE8
            assert (base + 0x25 + struct.unpack_from('<i', b, 33)[0]) & 0xFFFFFFFF == CTOR
            assert b[37] == 0xA3 and struct.unpack_from('<I', b, 38)[0] == cave + DUMMY_SLOT
            assert b[0x2A] == 0xE9
            assert (base + 0x2F + struct.unpack_from('<i', b, 0x2B)[0]) & 0xFFFFFFFF == site + 5
            assert len(b) == 0x2F
            hook = site_hook(site, base)
            assert hook[0] == 0xE9
            assert (site + 5 + struct.unpack_from('<i', hook, 1)[0]) & 0xFFFFFFFF == base
            assert len(orig) == 5
        print(json.dumps({'selftest': True, 'sites': len(SITES), 'cave_bytes': 0x2F}))
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
        for name, site, orig in SITES:
            got = read_at(k, h, site, 5)
            if got is None:
                print(json.dumps({'error': 'read failed', 'pid': pid, 'site': name}))
                return 1
            current[name] = got

        if args.revert:
            out = {'pid': pid, 'mode': 'revert', 'sites': []}
            for name, site, orig in SITES:
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
        for name, site, orig in SITES:
            cur = current[name]
            if cur[0] == 0xE9:
                continue
            if cur != orig:
                print(json.dumps({'error': 'unexpected site bytes', 'pid': pid,
                                  'site': name, 'hex': cur.hex()}))
                return 1
            todo.append((name, site))
        if not todo:
            print(json.dumps({'pid': pid, 'mode': 'panel-row-fallback', 'ok': True, 'already': True}))
            return 0
        if args.dry_run:
            print(json.dumps({'pid': pid, 'mode': 'panel-row-fallback', 'ok': True,
                              'dry_run': True, 'would_patch': [t[0] for t in todo]}))
            return 0

        cave = k.VirtualAllocEx(h, None, CAVE_SIZE, MEM_COMMIT_RESERVE, PAGE_RWX)
        if not cave:
            print(json.dumps({'error': 'VirtualAllocEx', 'err': c.get_last_error()}))
            return 1
        cave = int(cave)
        patched = []
        for name, site in todo:
            i = [s[0] for s in SITES].index(name)
            base = cave + i * CAVE_STRIDE
            blob = finish_cave(build_cave(base, cave + DUMMY_SLOT), base, site)
            ok, back = write_at(k, h, base, blob)
            if not ok:
                print(json.dumps({'error': 'cave write mismatch', 'site': name, 'back': back}))
                return 1
            ok2, back2 = write_at(k, h, site, site_hook(site, base))
            patched.append({'site': name, 'va': hex(site), 'ok': bool(ok2), 'back': back2})
            if not ok2:
                print(json.dumps({'pid': pid, 'cave': hex(cave), 'patched': patched, 'ok': False}))
                return 1
        print(json.dumps({'pid': pid, 'cave': hex(cave), 'patched': patched,
                          'mode': 'panel-row-fallback', 'ok': True}))
        return 0
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    sys.exit(main())
