"""Read-only Koeinm netobj observer inside the host's SANPK process (Wine).

Usage (wine python32): p3_host_read.py <SANPK_PID>
Dumps member table, reconnect flags, join switch and sequence counter.
Never writes; read-only ReadProcessMemory via the hub bridge Memory helper.
"""
import ctypes as c
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

bridge = Path(r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge')
assert (bridge/'probe.py').exists()
sys.path.insert(0, str(bridge))
os_env = None
import os
os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
from probe import Memory, MBI, kernel  # noqa: E402

def module_base(handle, name_lower):
    psapi = c.WinDLL('psapi')
    psapi.EnumProcessModulesEx.argtypes = [c.c_void_p, c.POINTER(c.c_void_p), c.c_uint32,
                                           c.POINTER(c.c_uint32), c.c_uint32]
    psapi.GetModuleFileNameExW.argtypes = [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_uint32]
    modules = (c.c_void_p*512)()
    needed = c.c_uint32()
    if not psapi.EnumProcessModulesEx(handle, modules, c.sizeof(modules),
                                      c.byref(needed), 3):
        return None
    hit = None
    for item in modules[:needed.value // c.sizeof(c.c_void_p)]:
        name = c.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(handle, item, name, len(name))
        if name.value.lower().endswith('\\' + name_lower):
            hit = item
            break
    return hit


def main():
    pid = int(sys.argv[1])
    m = Memory(pid)
    try:
        hit = module_base(m.h, 'koeinm.dll')
        result = {'pid': pid, 'koeinm_module': hit and hex(hit or 0), 'readonly': True}
        if not hit:
            result['error'] = 'koeinm.dll module not found'
            print(json.dumps(result))
            return 1
        base = hit
        netobj = base + 0x12170
        raw = m.read(netobj, 0x8468)
        if not raw or len(raw) < 0x8468:
            result['error'] = 'netobj read failed'
            print(json.dumps(result))
            return 1
        count = struct.unpack_from('<I', raw, 0x43bc)[0]
        table = struct.unpack_from('<I', raw, 0x43b8)[0]
        members = []
        if count and table:
            tlen = min(count, 8)*0x164
            tbuf = m.read(table, tlen)
            if tbuf:
                for i in range(min(count, 8)):
                    row = tbuf[i*0x164:(i+1)*0x164]
                    members.append({
                        'id': str(struct.unpack_from('<I', row, 0)[0]),
                        'name': row[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                        'reconnecting': struct.unpack_from('<I', row, 0x34)[0],
                        'failed': struct.unpack_from('<I', row, 0x38)[0],
                        'last_activity': struct.unpack_from('<I', row, 0x40)[0],
                    })
        result.update({
            'member_count': count,
            'members': members,
            'join_enabled_8414': struct.unpack_from('<I', raw, 0x8414)[0],
            'flag_8410': struct.unpack_from('<I', raw, 0x8410)[0],
            'seq_8444': struct.unpack_from('<I', raw, 0x8444)[0],
            'observed_at': time.time(),
        })
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        m.close()


if __name__ == '__main__':
    sys.exit(main() or 0)
