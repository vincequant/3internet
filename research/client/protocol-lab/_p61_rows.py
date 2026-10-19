"""Read the host's 8 application rows (slot, member id, name, state) — read-only.

Rows live at core+0xA, stride 0x87 (P31/P33 notes): +0x00 member id, +0x3C presence.
The display name is a fixed GBK buffer per row; we decode a conservative window.
"""
import ctypes as c, json, struct, sys
from ctypes import wintypes as w
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid = int(sys.argv[1])
k = c.WinDLL('kernel32', use_last_error=True)
col = Collector(pid); col.bind(); core = col.core; col.close()
h = k.OpenProcess(0x10, False, pid)
def rd(a, n):
    b = c.create_string_buffer(n); got = c.c_size_t()
    if not k.ReadProcessMemory(h, c.c_void_p(a), b, n, c.byref(got)):
        return None
    return b.raw
rows = []
for i in range(8):
    base = core + 0xA + i * 0x87
    raw = rd(base, 0x87)
    if not raw:
        continue
    mid = struct.unpack_from('<I', raw, 0)[0]
    present = raw[0x3C]
    name = raw[0x04:0x24].split(b'\x00')[0]
    try:
        text = name.decode('gbk', 'replace')
    except Exception:
        text = ''
    rows.append({'slot': i, 'member_id': mid, 'present': present, 'name': text})
print(json.dumps({'ok': True, 'pid': pid, 'core': hex(core), 'rows': rows}, ensure_ascii=False))
