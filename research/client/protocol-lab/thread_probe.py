#!/usr/bin/env python3
"""Read-only thread EIP probe for a Wine SANPK process (diagnostics).

For each thread of the target process: brief SuspendThread -> GetThreadContext
(CONTEXT_FULL) -> immediately ResumeThread; prints EIP/ESP/EBP/EAX..ESI per
thread. Never writes memory. Used to locate where the round driver D thread
is blocked.
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPTHREAD = 0x4
THREAD_SUSPEND_RESUME = 0x0002
THREAD_GET_CONTEXT = 0x0008
THREAD_QUERY_INFORMATION = 0x0040
CONTEXT_FULL = 0x00010007

MAX_PATH = 260


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
    ]


class CONTEXT(ctypes.Structure):
    _pack_ = 8
    _fields_ = [
        ("ContextFlags", wintypes.DWORD),
        ("Dr0", wintypes.DWORD), ("Dr1", wintypes.DWORD), ("Dr2", wintypes.DWORD),
        ("Dr3", wintypes.DWORD), ("Dr6", wintypes.DWORD), ("Dr7", wintypes.DWORD),
        ("FloatSave", ctypes.c_byte * 112),
        ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
        ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
        ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD), ("Ebx", wintypes.DWORD),
        ("Edx", wintypes.DWORD), ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
        ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD), ("SegCs", wintypes.DWORD),
        ("EFlags", wintypes.DWORD), ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


def find_sanpk_pids():
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        raise SystemExit('snapshot failed: %d' % ctypes.get_last_error())
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    found = []
    ok = k32.Process32First(snap, ctypes.byref(entry))
    while ok:
        name = entry.szExeFile.decode('gbk', 'replace')
        if name.lower().startswith('sanpk'):
            found.append((entry.th32ProcessID, name))
        ok = k32.Process32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return found


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == -1:
        raise SystemExit('thread snapshot failed: %d' % ctypes.get_last_error())
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    out = []
    ok = k32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            out.append(entry.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return out


PROCESS_VM_READ = 0x0010


def rpm(hproc, addr, n):
    buf = ctypes.create_string_buffer(n)
    read = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, n, ctypes.byref(read))
    return buf.raw if ok else None


def probe(pid):
    hproc = k32.OpenProcess(PROCESS_VM_READ, False, pid)
    tids = threads_of(pid)
    print(json.dumps({'pid': pid, 'threads': len(tids), 'vm_read': bool(hproc)}))
    for tid in tids:
        try:
            h = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                               False, tid)
            if not h:
                print(json.dumps({'tid': tid, 'error': 'OpenThread %d' % ctypes.get_last_error()}))
                continue
            k32.SuspendThread(h)
            ctx = CONTEXT()
            ctx.ContextFlags = CONTEXT_FULL
            ok = k32.GetThreadContext(h, ctypes.byref(ctx))
            stack = None
            rawframe = None
            if ok and hproc:
                raw = rpm(hproc, ctx.Esp, 4 * 320)
                if raw:
                    hits = []
                    for i in range(320):
                        v = int.from_bytes(raw[4 * i:4 * i + 4], 'little')
                        if 0x401000 <= v <= 0x500000 or 0x1e0000 <= v <= 0x21ffff:
                            hits.append('%d:%x' % (i, v))
                    stack = hits[:28]
                    rawframe = ['%x' % int.from_bytes(raw[4 * i:4 * i + 4], 'little') for i in range(24)]
            k32.ResumeThread(h)
            k32.CloseHandle(h)
            if not ok:
                print(json.dumps({'tid': tid, 'error': 'GetThreadContext %d' % ctypes.get_last_error()}))
                continue
            print(json.dumps({
                'tid': tid, 'eip': hex(ctx.Eip), 'esp': hex(ctx.Esp), 'ebp': hex(ctx.Ebp),
                'eax': hex(ctx.Eax), 'ebx': hex(ctx.Ebx), 'ecx': hex(ctx.Ecx),
                'edx': hex(ctx.Edx), 'esi': hex(ctx.Esi), 'edi': hex(ctx.Edi),
                'stack': stack,
                'raw': rawframe,
            }))
            time.sleep(0.05)
        except Exception as error:
            print(json.dumps({'tid': tid, 'exception': type(error).__name__}))


def main():
    pids = find_sanpk_pids()
    if not pids:
        raise SystemExit('no SANPK process found')
    for pid, name in pids:
        print(json.dumps({'found': name, 'pid': pid}))
        probe(pid)


if __name__ == '__main__':
    main()
