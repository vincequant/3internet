"""P63 natural-drop agent: make a target SANPK client die in-process (ExitProcess).

Purpose: verify that a *real* disconnect (process death -> socket closes -> loader/relay
drops the session) produces the game's standard "恢复连线中 -> 无法重新连线 -> 退出" text,
i.e. a natural-looking drop, as opposed to the D8 "silent de-list" half-state.

Runs under Wine py32 inside the target prefix. Read the resulting host text/roster
from the host prefix.

Usage:
  python.exe p63_drop_inject.py --target-name SANPK.exe [--plan] [--force]
Exit code 0 on success.
"""
from __future__ import annotations

import ctypes as c
import json
import sys
from ctypes import wintypes as w


def _win():
    return c, w, c.WinDLL('kernel32', use_last_error=True)


def _psapi():
    c_, w_, k = _win()
    return c_.WinDLL('psapi', use_last_error=True)


def find_process(name):
    c_, w_, k = _win()
    class Entry(c_.Structure):
        _fields_ = [('dwSize', w_.DWORD), ('cntUsage', w_.DWORD), ('th32ProcessID', w_.DWORD),
                    ('th32DefaultHeapID', c_.c_size_t), ('th32ModuleID', w_.DWORD),
                    ('cntThreads', w_.DWORD), ('th32ParentProcessID', w_.DWORD),
                    ('pcPriClassBase', w_.LONG), ('dwFlags', w_.DWORD),
                    ('szExeFile', w_.WCHAR * 260)]
    k.CreateToolhelp32Snapshot.restype = w_.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    e = Entry(); e.dwSize = c_.sizeof(e)
    pids = []
    ok = k.Process32FirstW(snap, c_.byref(e))
    while ok:
        if e.szExeFile.lower() == name.lower():
            pids.append(int(e.th32ProcessID))
        ok = k.Process32NextW(snap, c_.byref(e))
    return pids


def find_module(pid, name):
    c_, w_, k = _win()
    h = k.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return None
    try:
        ps = _psapi()
        ps.EnumProcessModules.argtypes = [w_.HANDLE, c_.c_void_p, w_.DWORD, c_.POINTER(w_.DWORD)]
        ps.GetModuleBaseNameW.argtypes = [w_.HANDLE, c_.c_void_p, w_.LPWSTR, w_.DWORD]

        class ModInfo(c_.Structure):
            _fields_ = [('lpBaseOfDll', c_.c_void_p), ('SizeOfImage', w_.DWORD),
                        ('EntryPoint', c_.c_void_p)]
        ps.GetModuleInformation.argtypes = [w_.HANDLE, c_.c_void_p, c_.POINTER(ModInfo), w_.DWORD]
        arr = (c_.c_void_p * 1024)()
        need = w_.DWORD(0)
        if not ps.EnumProcessModules(h, arr, c_.sizeof(arr), c_.byref(need)):
            return None
        buf = c_.create_unicode_buffer(260)
        for i in range(min(need.value // c_.sizeof(c_.c_void_p), 1024)):
            if not ps.GetModuleBaseNameW(h, arr[i], buf, 260):
                continue
            if buf.value.lower() == name.lower():
                mi = ModInfo()
                if ps.GetModuleInformation(h, arr[i], c_.byref(mi), c_.sizeof(mi)):
                    return {'base': int(mi.lpBaseOfDll or 0), 'size': int(mi.SizeOfImage)}
        return None
    finally:
        k.CloseHandle(h)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-name', default='SANPK.exe')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    c_, w_, k = _win()
    pids = find_process(args.target_name)
    if len(pids) != 1:
        print(json.dumps({'ok': False, 'error': 'process_count_%d' % len(pids)}))
        return 2
    pid = pids[0]
    mod = find_module(pid, 'kernel32.dll')
    if not mod:
        print(json.dumps({'ok': False, 'error': 'kernel32_missing', 'pid': pid}))
        return 2
    # ExitProcess VA: local kernel32 export offset + target kernel32 base.
    k32 = c_.WinDLL('kernel32', use_last_error=True)
    local_base = int(mod['base'])
    local_exit = int(c_.cast(k32.ExitProcess, c_.c_void_p).value)
    # same-image assumption (Wine maps kernel32 at the same base in all win32 processes)
    proc_exit = local_exit  # if bases match; verified below
    k32.GetModuleHandleW.restype = c_.c_void_p
    here = int(k32.GetModuleHandleW('kernel32.dll') or 0)
    if here and mod['base'] != here:
        # relocate by the delta of the module bases
        proc_exit = local_exit - here + int(mod['base'])
    sc = b'\x6a\x00' + b'\xb8' + proc_exit.to_bytes(4, 'little') + b'\xff\xd0'
    out = {'ok': True, 'pid': pid, 'kernel32_base': hex(mod['base']),
           'exitprocess_va': hex(proc_exit), 'shellcode': sc.hex()}
    if args.plan:
        out['plan_only'] = True
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    h = k.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid)
    if not h:
        out.update(ok=False, error='openprocess_%d' % c_.get_last_error())
        print(json.dumps(out)); return 2
    try:
        addr = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
        if not addr:
            out.update(ok=False, error='virtualalloc_%d' % c_.get_last_error())
            print(json.dumps(out)); return 2
        got = c_.c_size_t()
        if not k.WriteProcessMemory(h, c_.c_void_p(addr), sc, len(sc), c_.byref(got)):
            out.update(ok=False, error='writeprocess_%d' % c_.get_last_error())
            print(json.dumps(out)); return 2
        tid = w_.DWORD(0)
        th = k.CreateRemoteThread(h, None, 0, c_.c_void_p(addr), None, 0, c_.byref(tid))
        if not th:
            out.update(ok=False, error='createthread_%d' % c_.get_last_error())
            print(json.dumps(out)); return 2
        k.CloseHandle(th)
        out.update(thread_id=tid.value, code_addr=hex(addr))
        print(json.dumps(out))
        return 0
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    raise SystemExit(main() or 0)
