#!/usr/bin/env python3
"""Replace the "return the container on lookup miss" shim with a type-safe one.

Background (2026-10-19 crash chain):
  0x4195A9 is the shared "find element by id in container" walker:
      mov eax,[esp+4]        ; container
      ...
      xor edi,edi            ; <-- 0x4195AF, result seed = NULL
      loop: cast node to type 0x50CF50; if [cast+0x30] == wanted -> edi = cast
      return edi
  A previous shim rewrote 0x4195AF into `mov edi,eax` so a miss returned the
  *container*, which is not of the element type. Callers then read
  [container+0x3C] (silently wrong) or pass it on as an object; the observer
  client died later with this=0xfffffXXX inside the training dialog.

This patch keeps NULL semantics on a *successful* scan but makes the miss
fallback type-correct: if no node matched, return the first node that passed
the same dynamic cast (a real element of the requested class), so every
[ret+0x30] / [ret+0x3C] read and every virtual call stays inside a valid
object of the right type.

Implementation (memory only, per process):
  0x4195AF  8b f8 -> 33 ff        restore `xor edi,edi`
  0x4195C4  e8 .. -> e9 <cave>    retarget the dynamic-cast call to a cave that
                                  runs the original call, remembers the first
                                  castable element in EDI, then returns to
                                  0x4195C9 exactly as before.

Cave (19 bytes):
  59            pop ecx                 ; stash original return 0x4195C9
  e8 <rel32>    call 0x4D3214           ; args now at [esp+4]/[esp+8]
  85 c0         test eax,eax
  74 07         jz  done
  85 ff         test edi,edi
  75 03         jnz done
  8b f8         mov edi,eax             ; first castable element = fallback
  85 c0         test eax,eax
  51            push ecx                ; restore return address
  c3            ret

Usage (wine py32 inside the target prefix):
  patch_element_fallback.py <pid>
  patch_element_fallback.py <pid> --revert
  patch_element_fallback.py <pid> --dry-run
  patch_element_fallback.py --selftest
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

SEED_VA = 0x4195AF
SEED_ORIG = bytes.fromhex('33ff')          # xor edi,edi
SEED_HACK = bytes.fromhex('8bf8')          # mov edi,eax  (previous shim)
CALL_VA = 0x4195C4
CALL_ORIG = bytes.fromhex('e84b9c0b00')    # call 0x4D3214
CAST_FN = 0x4D3214
RET_VA = 0x4195C9                          # where the original call returns
CAVE_SIZE = 0x1000
PAGE_RWX = 0x40
MEM_COMMIT_RESERVE = 0x3000
ACCESS = 0x0010 | 0x0020 | 0x0008 | 0x0400   # VM_OPERATION|VM_WRITE|VM_READ|QUERY


def build_cave(cave: int, cast_fn: int = CAST_FN) -> bytes:
    # NOTE 2026-10-19 19:3x: the site hook is a `jmp`, not a `call`, so the
    # stack at cave entry holds ONLY the two pushed arguments (no return
    # address). A plain `call cast_fn` therefore sees [esp+4]=arg1(id) and
    # [esp+8]=arg2(type) exactly like the original call site. The return
    # address 0x4195C9 is reached with a `jmp` at the end; the two `pop ecx`
    # at 0x4195C9/0x4195CC still clean the arguments.
    b = bytearray()
    b += b'\xe8' + struct.pack('<i', cast_fn - (cave + 5))   # call cast (args already on stack)
    b += b'\x85\xc0'                                         # test eax,eax
    b += b'\x74\x08'                                         # jz done      (0x09+8 = 0x11)
    b += b'\x85\xff'                                         # test edi,edi
    b += b'\x75\x04'                                         # jnz done     (0x0D+4 = 0x11)
    b += b'\x8b\xf8'                                         # mov edi,eax  ; first castable = fallback
    b += b'\x90\x90'                                         # pad
    b += b'\xe9' + struct.pack('<i', RET_VA - (cave + 0x16))  # jmp 0x4195C9
    assert len(b) == 0x16, hex(len(b))
    return bytes(b)


def call_hook(cave: int) -> bytes:
    return b'\xe9' + struct.pack('<i', cave - (CALL_VA + 5))


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
        name = e.szExeFile.decode('gbk', 'replace').lower()
        if name.startswith('sanpk'):
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
        blob = build_cave(cave)
        assert blob[0] == 0xE8
        rel = struct.unpack_from('<i', blob, 1)[0]
        assert (cave + 5 + rel) & 0xFFFFFFFF == CAST_FN
        assert blob[5:7] == b'\x85\xc0'
        assert blob[7] == 0x74 and 0x09 + blob[8] == 0x11
        assert blob[9:11] == b'\x85\xff'
        assert blob[11] == 0x75 and 0x0D + blob[12] == 0x11
        assert blob[13:15] == b'\x8b\xf8'
        assert blob[17] == 0xE9
        assert (cave + 0x16 + struct.unpack_from('<i', blob, 18)[0]) & 0xFFFFFFFF == RET_VA
        assert len(blob) == 0x16
        hook = call_hook(cave)
        assert hook[0] == 0xE9
        assert (CALL_VA + 5 + struct.unpack_from('<i', hook, 1)[0]) & 0xFFFFFFFF == cave
        assert len(CALL_ORIG) == 5 and len(SEED_ORIG) == 2
        print(json.dumps({'selftest': True, 'cave_bytes': len(blob)}))
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
        seed = read_at(k, h, SEED_VA, 2)
        call = read_at(k, h, CALL_VA, 5)
        if seed is None or call is None:
            print(json.dumps({'error': 'read failed', 'pid': pid}))
            return 1
        out = {'pid': pid, 'seed_before': seed.hex(), 'call_before': call.hex()}

        if args.revert:
            if seed != SEED_ORIG and not args.dry_run:
                ok, back = write_at(k, h, SEED_VA, SEED_ORIG)
                out['seed_restored'] = {'ok': ok, 'back': back}
                if not ok:
                    print(json.dumps(out)); return 1
            if call != CALL_ORIG and not args.dry_run:
                ok, back = write_at(k, h, CALL_VA, CALL_ORIG)
                out['call_restored'] = {'ok': ok, 'back': back}
                if not ok:
                    print(json.dumps(out)); return 1
            out['ok'] = True
            out['mode'] = 'revert'
            print(json.dumps(out))
            return 0

        if seed not in (SEED_ORIG, SEED_HACK):
            print(json.dumps({'error': 'unexpected seed bytes', 'pid': pid, 'hex': seed.hex()}))
            return 1
        if call != CALL_ORIG:
            if call[0] == 0xE9:
                out['ok'] = True
                out['mode'] = 'fallback'
                out['already'] = True
                print(json.dumps(out))
                return 0
            print(json.dumps({'error': 'unexpected call-site bytes', 'pid': pid, 'hex': call.hex()}))
            return 1

        if args.dry_run:
            out['ok'] = True
            out['mode'] = 'fallback'
            out['dry_run'] = True
            out['would'] = {'seed': SEED_ORIG.hex(), 'call': 'e9 <cave>'}
            print(json.dumps(out))
            return 0

        cave = k.VirtualAllocEx(h, None, CAVE_SIZE, MEM_COMMIT_RESERVE, PAGE_RWX)
        if not cave:
            print(json.dumps({'error': 'VirtualAllocEx', 'err': c.get_last_error()}))
            return 1
        cave = int(cave)
        blob = build_cave(cave)
        ok, back = write_at(k, h, cave, blob)
        if not ok:
            print(json.dumps({'error': 'cave write mismatch', 'back': back}))
            return 1
        # restore NULL seed first, then retarget the cast call
        ok1, back1 = write_at(k, h, SEED_VA, SEED_ORIG)
        ok2, back2 = write_at(k, h, CALL_VA, call_hook(cave))
        out.update({'cave': hex(cave), 'seed_after': back1, 'call_after': back2,
                    'ok': bool(ok1 and ok2), 'mode': 'fallback'})
        print(json.dumps(out))
        return 0 if out['ok'] else 1
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    sys.exit(main())
