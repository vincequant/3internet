"""Experiment: repeatedly clear the app tick re-entry lock and watch progress.

usage: lock_probe.py <pid> [count] [interval_ms]

Reads 0x53BA54 (re-entry guard) and core fields before/after; clears the lock
`count` times. Diagnostic only (lab process). Prints one JSON line.
"""
import ctypes as c
import json
import sys
import time
from ctypes import wintypes as w

k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.CloseHandle.argtypes = [w.HANDLE]

LOCK = 0x53BA54


def rd(h, addr, n=4):
    buf = c.create_string_buffer(n)
    got = c.c_size_t()
    if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
        return None
    return buf.raw


def wr(h, addr, val):
    data = val.to_bytes(4, 'little')
    raw = c.create_string_buffer(data, 4)
    got = c.c_size_t()
    return bool(k.WriteProcessMemory(h, c.c_void_p(addr), raw, 4, c.byref(got)) and got.value == 4)


pid = int(sys.argv[1])
count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
interval = (int(sys.argv[3]) if len(sys.argv) > 3 else 100) / 1000.0

h = k.OpenProcess(0x0010 | 0x0020 | 0x0008, False, pid)
if not h:
    print(json.dumps({'error': 'OpenProcess', 'err': c.get_last_error()}))
    raise SystemExit(1)
try:
    before = rd(h, LOCK)
    out = {'pid': pid, 'lock_before': before.hex() if before else None, 'pokes': 0, 'seen_zero': 0}
    for _ in range(count):
        if wr(h, LOCK, 0):
            out['pokes'] += 1
        time.sleep(interval)
        v = rd(h, LOCK)
        if v == b'\x00\x00\x00\x00':
            out['seen_zero'] += 1
    after = rd(h, LOCK)
    out['lock_after'] = after.hex() if after else None
    print(json.dumps(out))
finally:
    k.CloseHandle(h)
