"""P26 host discovery probe (read-only, wine python32): enumerate win32
processes, find every SANPK.exe, and for each read the koeinm netobj like
p23 (is_host +0x148, slot table +0x43b8, session name +0x43d8).

Output: one JSON object {'hosts': [...], 'all': [...]}. 'hosts' lists only
entries with is_host==1, host_ip resolvable, non-empty session name and
host_name. Never writes.

Usage (wine python32, from the vkquant Mac): p26_find_host.py
"""
import ctypes as c
import json
import struct
from pathlib import Path

BRIDGE = Path(r'Z:\Users\vkquant\AppData\..\..\Applications\SGI-Game\hub\bridge')
import os  # noqa: E402
os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
import sys  # noqa: E402
import os
sys.path.insert(0, os.environ.get('SGI_BRIDGE_Z', r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge'))
from probe import Memory  # noqa: E402

PSAPI = c.WinDLL('psapi')
K32 = c.WinDLL('kernel32')


def win_pids():
    n = 4096
    while True:
        buf = (c.c_uint32 * n)()
        got = c.c_uint32()
        if not PSAPI.EnumProcesses(c.byref(buf), c.sizeof(buf), c.byref(got)):
            return []
        count = got.value // 4
        return list(buf)[:count]


def sanpk_info(pid):
    try:
        m = Memory(pid)
    except Exception as e:  # noqa
        return None
    try:
        m.load()
        exe = c.create_unicode_buffer(1024)
        if not PSAPI.GetModuleFileNameExW(m.h, None, exe, len(exe)) \
                or not exe.value.lower().endswith('\\sanpk.exe'):
            return None
        kbase = None
        mods = (c.c_void_p * 512)()
        need = c.c_uint32()
        if PSAPI.EnumProcessModulesEx(m.h, mods, c.sizeof(mods),
                                      c.byref(need), 3):
            for item in mods[:need.value // c.sizeof(c.c_void_p)]:
                name = c.create_unicode_buffer(1024)
                if PSAPI.GetModuleFileNameExW(m.h, item, name, len(name)):
                    if name.value.lower().endswith('\\koeinm.dll'):
                        kbase = item
                        break
        if not kbase:
            return None
        netobj = kbase + 0x12170
        is_host = u32_at(m, netobj + 0x148)
        tptr = u32_at(m, netobj + 0x43b8)
        host_id, host_name = None, ''
        if tptr:
            slot = m.read(tptr, 0x40)
            if slot:
                host_id = struct.unpack_from('<I', slot, 0)[0]
                host_name = slot[4:35].split(b'\x00')[0].decode('gbk', 'replace')
        sess = m.read(netobj + 0x43d8, 31) or b''
        session_name = sess.split(b'\x00')[0].decode('gbk', 'replace')
        host_ip = '.'.join(str(x) for x in struct.pack('!I', host_id)) if host_id else None
        return {'pid': pid, 'is_host': is_host, 'host_id': host_id,
                'host_name': host_name, 'session_name': session_name,
                'host_ip': host_ip}
    finally:
        m.close()


def u32_at(m, addr):
    b = m.read(addr, 4)
    return struct.unpack('<I', b)[0] if b else None


def main():
    all_procs, hosts = [], []
    for pid in win_pids():
        try:
            info = sanpk_info(pid)
        except Exception as e:  # noqa
            info = {'pid': pid, 'error': str(e)[:120]}
        if info:
            all_procs.append(info)
            if (info.get('is_host') == 1 and info.get('host_ip')
                    and info.get('session_name')):
                hosts.append(info)
    print(json.dumps({'hosts': hosts, 'all': all_procs, 'readonly': True},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
