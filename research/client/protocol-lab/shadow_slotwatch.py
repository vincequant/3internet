#!/usr/bin/env python3
"""Shadow fast slot-watcher - sample my-slot + slot-row fields at high cadence.

Purpose: observe, during the game-start window, when the client resolves its
"my slot" (core+0x6C0) and when the slot rows fill, to evaluate the identity
fix for the deseat-ed shadow (p50-shadow-phaseb NOTES sec.16).

Fields sampled (core-relative; row s at core+4+s*0x87):
  0x16/0x1A  occupancy-ish fields used by slot scanners (0x44B7D7 / 0x44B815)
  0x46       counter field (0x44B7FD)
  0x4A       force id (GetMyForceId 0x44B83B)

Read-only. Usage (wine py32, shadow prefix):
  shadow_slotwatch.py --seconds 150 --interval 0.5 --out 'Z:\\...\\logs\\slotwatch.jsonl'
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
import struct
import sys
import time
from ctypes import wintypes as w

MY_SLOT_OFF = 0x6C0
STRIDE = 0x87
FIELDS = (0x16, 0x1A, 0x46, 0x4A)
COUNT = 8


def _win():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    return k


def find_sanpk(k):
    class E(c.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                    ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD),
                    ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                    ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == c.c_void_p(-1).value or not snap:
        return None
    e = E()
    e.dwSize = c.sizeof(e)
    pid = None
    try:
        ok = k.Process32FirstW(snap, c.byref(e))
        while ok:
            if e.szExeFile.lower() == 'sanpk.exe':
                pid = int(e.th32ProcessID)
            ok = k.Process32NextW(snap, c.byref(e))
    finally:
        k.CloseHandle(snap)
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--seconds', type=float, default=150.0)
    ap.add_argument('--interval', type=float, default=0.5)
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector

    pid = find_sanpk(_win())
    if not pid:
        raise SystemExit('no sanpk.exe in this bottle')
    col = Collector(pid)
    try:
        binding = col.bind()
        core = col.core
    finally:
        col.close()

    k = _win()
    h = k.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed err=%d' % c.get_last_error())

    def rd(addr):
        buf = c.create_string_buffer(4)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) or got.value != 4:
            return None
        return struct.unpack('<i', buf.raw)[0]

    out = open(args.out, 'a', encoding='utf-8') if args.out else sys.stdout
    t0 = time.time()
    print(json.dumps({'event': 'start', 'pid': pid, 'core': hex(core),
                      'seconds': args.seconds, 'interval': args.interval}, ensure_ascii=False), flush=True)
    while time.time() - t0 < args.seconds:
        rec = {'wall': round(time.time(), 3), 't': round(time.time() - t0, 2)}
        rec['my_slot'] = rd(core + MY_SLOT_OFF)
        for off in FIELDS:
            rec['f%02x' % off] = [rd(core + off + s * STRIDE) for s in range(COUNT)]
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        time.sleep(args.interval)
    print(json.dumps({'event': 'end', 'samples': int((time.time() - t0) / max(args.interval, 0.05))},
                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
