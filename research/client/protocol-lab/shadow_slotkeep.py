#!/usr/bin/env python3
"""Shadow slot keeper - re-assert my-slot during the game-start window.

The deseat-ed client resets my_slot (core+0x6C0) to -1 during its session
init (reset sites 0x44ACF7 / 0x44AFDE); this tool keeps writing the target
value at high cadence and logs every WriteProcessMemory it performs (i.e.
every client-side reset it counters) with timestamps.

Read-mostly: 1 read per tick; a write only when the value differs.

Usage (wine py32, shadow prefix):
  shadow_slotkeep.py --slot 1 --seconds 300 --interval 0.25 --out 'Z:\\...\\logs\\slotkeep.jsonl'
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


def _win():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.WriteProcessMemory.restype = w.BOOL
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
    ap.add_argument('--slot', type=int, default=1)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--seconds', type=float, default=300.0)
    ap.add_argument('--interval', type=float, default=0.25)
    ap.add_argument('--out', default='')
    args = ap.parse_args()
    if not 0 <= args.slot < 8:
        raise SystemExit('slot out of range')

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
    h = k.OpenProcess(0x0020 | 0x0010 | 0x0400, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed err=%d' % c.get_last_error())

    def rd():
        buf = c.create_string_buffer(4)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(core + MY_SLOT_OFF), buf, 4, c.byref(got)) or got.value != 4:
            return None
        return struct.unpack('<i', buf.raw)[0]

    def wr(val):
        got = c.c_size_t()
        buf = struct.pack('<i', val)
        ok = k.WriteProcessMemory(h, c.c_void_p(core + MY_SLOT_OFF), buf, 4, c.byref(got))
        return bool(ok) and got.value == 4

    out = open(args.out, 'a', encoding='utf-8') if args.out else sys.stdout
    t0 = time.time()
    writes = 0
    fails = 0
    print(json.dumps({'event': 'start', 'pid': pid, 'core': hex(core), 'slot': args.slot,
                      'seconds': args.seconds, 'interval': args.interval}, ensure_ascii=False), flush=True)
    while time.time() - t0 < args.seconds:
        cur = rd()
        if cur is None:
            fails += 1
            if fails > 20:
                print(json.dumps({'event': 'target_lost'}, ensure_ascii=False), flush=True)
                break
        elif cur != args.slot:
            okw = wr(args.slot)
            writes += 1
            rec = {'wall': round(time.time(), 3), 't': round(time.time() - t0, 2),
                   'was': cur, 'set': args.slot if okw else None}
            out.write(json.dumps(rec, ensure_ascii=False) + '\n')
            out.flush()
        time.sleep(args.interval)
    print(json.dumps({'event': 'end', 'writes': writes, 'read_failures': fails}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
