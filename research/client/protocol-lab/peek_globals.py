"""Read a few global game dwords (read-only) from the shadow process.

usage: peek_globals.py <pid>
prints the reentry lock 0x53BA54 and a small set of round/tick globals.
"""
import ctypes as c
import json
import sys
from ctypes import wintypes as w

k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL

TARGETS = {
    'reentry_lock_53ba54': 0x53BA54,
    'tick_busy_53b4c4': 0x53B4C4,
    'g_53b540': 0x53B540,
    'g_53b570': 0x53B570,
}

pid = int(sys.argv[1])
h = k.OpenProcess(0x0010 | 0x0008, False, pid)
if not h:
    print(json.dumps({'error': 'OpenProcess', 'err': c.get_last_error()}))
    raise SystemExit(1)
out = {'pid': pid}
for name, addr in TARGETS.items():
    buf = c.create_string_buffer(4)
    got = c.c_size_t()
    if k.ReadProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) and got.value == 4:
        out[name] = hex(int.from_bytes(buf.raw, 'little'))
    else:
        out[name] = None
k.CloseHandle(h)
print(json.dumps(out))
