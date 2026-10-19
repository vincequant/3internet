#!/usr/bin/env python3
"""One-shot dword poke for the shadow SANPK (lab process only).

Reads a dword at a fixed VA, optionally writes a new value, reads back.
Default: 0x53BA54 (the app's global tick re-entry guard) -> 0.
"""
from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

TH32CS_SNAPPROCESS = 0x2
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
MAX_PATH = 260


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


def find_sanpk_pid():
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    ok = k32.Process32First(snap, ctypes.byref(entry))
    while ok:
        name = entry.szExeFile.decode('gbk', 'replace')
        if name.lower().startswith('sanpk'):
            pid = entry.th32ProcessID
            k32.CloseHandle(snap)
            return pid, name
        ok = k32.Process32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return None, None


def read_dword(h, addr):
    buf = ctypes.create_string_buffer(4)
    read = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(read))
    if not ok:
        return None
    return int.from_bytes(buf.raw, 'little')


def write_dword(h, addr, value):
    data = value.to_bytes(4, 'little')
    written = ctypes.c_size_t(0)
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, 4, ctypes.byref(written))
    return bool(ok)


def main():
    addr = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x53BA54
    ro = (len(sys.argv) <= 2) or (sys.argv[2] == 'r')
    new_value = 0 if ro else int(sys.argv[2], 16)
    pid, name = find_sanpk_pid()
    if not pid:
        raise SystemExit('no SANPK')
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed %d' % ctypes.get_last_error())
    before = read_dword(h, addr)
    print(json.dumps({'pid': pid, 'addr': hex(addr), 'before': None if before is None else hex(before)}))
    if before is None:
        raise SystemExit('read failed %d' % ctypes.get_last_error())
    if ro:
        print(json.dumps({'mode': 'read_only'}))
    else:
        ok = write_dword(h, addr, new_value)
        after = read_dword(h, addr)
        print(json.dumps({'write_ok': ok, 'after': None if after is None else hex(after)}))
    k32.CloseHandle(h)


if __name__ == '__main__':
    main()
