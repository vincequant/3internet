#!/usr/bin/env python3
"""Round-state probe (read-only): app round fields + DLL sync fields of a SANPK.

Reads from the game core object (same base the collector binds) the fields that
drive the app-side round state machine found in the SANPK disassembly
(2026-10-18):

  core+0x68   app round state      (0..4; writer sites 4441b8=1/444033=2/444747=3/4440f5=4)
  core+0x80   match-active gate    (0 => the round state machine returns early)
  core+0x4d8  phase/season step    (0..6, advanced per round; 6 -> 0x44c4f4)
  core+0x6bc  round-flag           (entry sets 1; 44b8b6 clears at state 3 end)
  core+0x6c4  empty-slot counter   (recomputed per round over +0x46 rows)
  core+0xfce  state-3 exit cond    (== 2 triggers 0x44b8b6 + state 3->0)
  core+0xf5a/0xf5e  state-0 lists
  netobj+0x84a8  DLL sync state    (0..4)
  netobj+0x84c8  sync roster count
  netobj+0x84b4  current command queue count
  core+0x6c0   my_slot; row forces at core+0x4a+s*0x87

Usage (wine py32, any prefix):
  python.exe roundprobe.py --bridge 'Z:\\...\\shadow\\bridge' [--samples 1] [--interval 0.5]
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


def module_base(k, pid, name_lower):
    ps = c.WinDLL('psapi', use_last_error=True)
    ps.EnumProcessModules.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    ps.GetModuleBaseNameW.argtypes = [w.HANDLE, c.c_void_p, w.LPWSTR, w.DWORD]
    h = k.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return None
    try:
        arr = (c.c_void_p * 1024)()
        need = w.DWORD(0)
        if not ps.EnumProcessModules(h, arr, c.sizeof(arr), c.byref(need)):
            return None
        buf = c.create_unicode_buffer(260)
        for m in arr[:need.value // c.sizeof(c.c_void_p)]:
            if ps.GetModuleBaseNameW(h, m, buf, 260) and buf.value.lower() == name_lower:
                return int(m)
    finally:
        k.CloseHandle(h)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--samples', type=int, default=1)
    ap.add_argument('--interval', type=float, default=0.5)
    args = ap.parse_args()

    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector

    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe in this bottle'}))
        return 1
    col = Collector(pid)
    try:
        binding = col.bind()
        core = col.core
    finally:
        col.close()
    kbase = module_base(k, pid, 'koeinm.dll')
    netobj = (kbase + 0x12170) if kbase else None
    h = k.OpenProcess(0x0010, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess failed'}))
        return 1

    def rd(addr, n=4):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    def r32(addr):
        raw = rd(addr, 4)
        return struct.unpack('<I', raw)[0] if raw else None

    def r16(addr):
        raw = rd(addr, 2)
        return struct.unpack('<h', raw)[0] if raw else None

    for i in range(max(1, args.samples)):
        rec = {'wall': round(time.time(), 3), 'i': i, 'pid': pid, 'binding': binding,
               'core': hex(core)}
        # G-relative tick-machine fields (G = core - 0x912; the tick calls read
        # [G+0x68] state / [G+0x80] match gate / [G+0x7c] / [G+0x6c] accumulator).
        rec['tick_state_G68'] = r32(core - 0x8aa)
        rec['gate_G80'] = r32(core - 0x892)
        rec['f_G7c'] = r32(core - 0x896)
        rec['accum_G6c'] = r32(core - 0x8a6)
        rec['timer_G84'] = [r32(core - 0x88e + i * 4) for i in range(6)]
        # core-relative round fields (round driver 44b8ca runs with ecx=core).
        rec['phase_4d8'] = r16(core + 0x4d8)
        rec['f_4d0'] = r16(core + 0x4d0)
        rec['f_4d6'] = r16(core + 0x4d6)
        rec['f_6bc'] = r32(core + 0x6bc)
        rec['f_6c4'] = r32(core + 0x6c4)
        rec['f_648'] = r32(core + 0x648)
        rec['f_64c'] = r32(core + 0x64c)
        rec['f_891'] = r32(core + 0x891)
        rec['my_slot_6c0'] = r32(core + 0x6c0)
        rec['rows_f46'] = [r32(core + 0x46 + s * 0x87) for s in range(8)]
        rec['rows_f4a'] = [r32(core + 0x4a + s * 0x87) for s in range(8)]
        rec['rows_14'] = [r16(core + 0x14 + s * 0x87) for s in range(8)]
        if netobj is not None:
            rec['sync_84a8'] = r32(netobj + 0x84a8)
            rec['sync_count_84c8'] = r32(netobj + 0x84c8)
            rec['queue_84b4'] = r32(netobj + 0x84b4)
            rec['ctr_8440'] = r32(netobj + 0x8440)
            rec['ctr_8444'] = r32(netobj + 0x8444)
        print(json.dumps(rec, ensure_ascii=False))
        if i + 1 < args.samples:
            time.sleep(args.interval)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
