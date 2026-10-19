#!/usr/bin/env python3
"""Shadow acting-slot selector — read/write the shadow client's slot index field.

Theory anchor: SANPK getter 0x4B83B reads [core+0x6C0] (my connection slot, 0..7),
then the slot's force id at [core + 0x4A + slot*0x87]. The deseat-ed shadow has
slot=-1 and its view/actor lands on a default force. Writing [core+0x6C0]=N may
switch the shadow's acting identity to that slot's force (i.e. follow a chosen
player regardless of which faction they were randomly assigned).

Safety: this tool WRITES 4 bytes in the SHADOW's own process only (our lab client),
with a saved-old-value state file and a --restore mode. Read mode is read-only.

Usage (wine py32, shadow prefix):
  shadow_setforce.py --read  --bridge 'Z:\\...\\shadow\\bridge' --state 'Z:\\...\\shadow\\setforce.json'
  shadow_setforce.py --slot 1 --bridge ... --state ...
  shadow_setforce.py --restore --bridge ... --state ...
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
from pathlib import Path

SLOT_OFF = 0x6C0
SLOT_STRIDE = 0x87
FORCE_OFF = 0x4A
SLOT_COUNT = 8


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
    ap.add_argument('--slot', type=int, help='0..7 write target')
    ap.add_argument('--read', action='store_true')
    ap.add_argument('--restore', action='store_true')
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--state', required=True)
    args = ap.parse_args()
    if (args.slot is not None) + bool(args.read) + bool(args.restore) != 1:
        raise SystemExit('pick exactly one of --slot/--read/--restore')
    if args.slot is not None and not 0 <= args.slot < SLOT_COUNT:
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
    h = k.OpenProcess(0x0020 | 0x0010 | 0x0400, False, pid)  # VM_WRITE|VM_READ|QUERY
    if not h:
        raise SystemExit('OpenProcess failed err=%d' % c.get_last_error())

    def rd(addr):
        buf = c.create_string_buffer(4)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) or got.value != 4:
            raise SystemExit('read 0x%x failed' % addr)
        return struct.unpack('<i', buf.raw)[0]

    def wr(addr, val):
        got = c.c_size_t()
        buf = struct.pack('<i', val)
        if not k.WriteProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) or got.value != 4:
            raise SystemExit('write 0x%x failed err=%d' % (addr, c.get_last_error()))
        return rd(addr)

    slot_now = rd(core + SLOT_OFF)
    forces = [rd(core + FORCE_OFF + s * SLOT_STRIDE) for s in range(SLOT_COUNT)]
    result = {'core': hex(core), 'binding': binding, 'slot_now': slot_now,
              'slot_forces': {str(s): f for s, f in enumerate(forces)}}

    if args.read:
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.restore:
        state = json.loads(Path(args.state).read_text(encoding='utf-8'))
        old = int(state['old'])
        if state.get('core') not in (None, hex(core)):
            raise SystemExit('state core mismatch: %s vs %s' % (state.get('core'), hex(core)))
        back = wr(core + SLOT_OFF, old)
        print(json.dumps(dict(result, action='restored', restored_to=back), ensure_ascii=False))
        return

    Path(args.state).write_text(json.dumps({'core': hex(core), 'old': slot_now,
                                            'wall': time.time()}, ensure_ascii=False), encoding='utf-8')
    new = wr(core + SLOT_OFF, args.slot)
    print(json.dumps(dict(result, action='written', requested=args.slot, now=new), ensure_ascii=False))


if __name__ == '__main__':
    main()
