#!/usr/bin/env python3
"""Shadow slot logger — read-only sampler of a SANPK client's receive slot.

Reads the Koeinm netobj receive slot ([netobj+0x414c] size, [+0x4150] sender,
[+0x14c] data) every tick, and logs each DISTINCT frame (sender, sha256) with
its raw bytes to a JSONL file. Purpose: count how many command records the
host accepted/broadcast on behalf of the hidden shadow (c5 batches carry the
accepted command stream). Sampling is opportunistic (possible missed frames).

Usage (under wine py32 in the target prefix):
  python.exe shadow_slotlog.py --pid-map auto --interval 0.2 --out Z:\\...\\slots.jsonl
"""
from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import struct
import sys
import time
from ctypes import wintypes as w
from pathlib import Path


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
    ap.add_argument('--out', required=True)
    ap.add_argument('--interval', type=float, default=0.2)
    ap.add_argument('--duration', type=float, default=0.0)
    args = ap.parse_args()
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe in this bottle'}))
        return 1
    base = module_base(k, pid, 'koeinm.dll')
    if not base:
        print(json.dumps({'error': 'koeinm.dll not loaded'}))
        return 1
    netobj = base + 0x12170
    h = k.OpenProcess(0x0010, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess failed'}))
        return 1

    def rd(addr, n):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    out = open(args.out, 'a', buffering=1, encoding='utf-8')
    seen = set()
    started = time.monotonic()
    count = 0
    while args.duration <= 0 or time.monotonic() - started < args.duration:
        hdr = rd(netobj + 0x414c, 8)
        if hdr:
            size, sender = struct.unpack('<ii', hdr)
            if 0 < size <= 0x4000:
                raw = rd(netobj + 0x14c, size)
                if raw:
                    key = (sender, hashlib.sha256(raw).digest())
                    if key not in seen:
                        seen.add(key)
                        count += 1
                        out.write(json.dumps({
                            'wall': round(time.time(), 3),
                            't': round(time.monotonic() - started, 2),
                            'sender': sender, 'length': size,
                            'kind': raw[0],
                            'raw_hex': raw.hex(),
                            'sha256': hashlib.sha256(raw).hexdigest(),
                            'evidence_type': 'slot_sample; possible_missed_frames',
                        }, ensure_ascii=False) + '\n')
        time.sleep(max(0.05, args.interval))
    out.close()
    print(json.dumps({'slotlog_done': True, 'frames': count, 'out': args.out}))
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
