"""Read-only unit list for ANY SANPK pid (diagnostic; never writes).

usage: unit_read_any.py <pid>
Prints one JSON line: {ok, units:[{owner,unit_id,kind,soldiers,rice,morale,training,...}]}

Uses the same static layout as p53_unit_data (verified build df9b5225).
"""
import ctypes as c
import json
import sys
from ctypes import wintypes as w

sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\tools')
from p53_unit_data import capture_map  # noqa: E402

k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL

pid = int(sys.argv[1])
h = k.OpenProcess(0x0010 | 0x0008, False, pid)
if not h:
    print(json.dumps({'ok': False, 'error': 'OpenProcess', 'err': c.get_last_error()}))
    raise SystemExit(1)


def read(addr, n):
    buf = c.create_string_buffer(n)
    got = c.c_size_t()
    if not k.ReadProcessMemory(h, c.c_void_p(int(addr)), buf, n, c.byref(got)) or got.value != n:
        raise OSError('read failed at 0x%x' % int(addr))
    return buf.raw


try:
    snap = capture_map(read)
    units = []
    for u in snap['units']:
        raw = bytes.fromhex(u['raw_hex'])
        units.append({
            'addr': hex(u['address']), 'owner': u['owner_raw'], 'unit_id': u['unit_id'],
            'kind': u['kind'], 'soldiers': u['soldiers_candidate'],
            'rice': u['rice_candidate'],
            'morale': raw[0x1d], 'training': raw[0x29],
            'general_ids': u['general_ids'],
        })
    print(json.dumps({'ok': True, 'pid': pid, 'units': units, 'count': len(units)}, ensure_ascii=False))
except Exception as exc:  # noqa: BLE001 - diagnostic tool
    print(json.dumps({'ok': False, 'pid': pid, 'error': '%s: %s' % (type(exc).__name__, exc)}, ensure_ascii=False))
finally:
    k.CloseHandle(h)
