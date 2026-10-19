"""P33 bounded read-only P4 observer plus DLL sync roster; no sends/writes."""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time
from pathlib import Path

bridge = Path(os.environ.get('SGI_BRIDGE_Z', r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge'))
assert (bridge/'probe.py').exists()
sys.path.insert(0, str(bridge))
os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
from probe import Memory, kernel  # noqa: E402

ROW_FIELDS = ((0x2c, 'confirmed_2c'), (0x24, 'seq_24'), (0x28, 'seq_28'),
              (0x30, 'f_30'), (0x34, 'reconnecting'), (0x38, 'failed'),
              (0x40, 'f_40'), (0x4c, 'active'))


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
    for item in modules[:needed.value // c.sizeof(c.c_void_p)]:
        name = c.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(handle, item, name, len(name))
        if name.value.lower().endswith('\\' + name_lower):
            return item
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pid', type=int)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--duration', type=float, default=200.0)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    m = Memory(args.pid)
    out = open(args.out, 'w', buffering=1, encoding='utf-8')
    t0 = time.monotonic()
    ticks = 0
    try:
        base = module_base(m.h, 'koeinm.dll')
        if not base:
            print(json.dumps({'error': 'koeinm.dll module not found'}))
            return 1
        netobj = base + 0x12170
        while time.monotonic() - t0 < args.duration:
            tick = {'t': round(time.monotonic() - t0, 2), 'wall': round(time.time(), 2)}
            raw = m.read(netobj, 0x84cc)
            if not raw or len(raw) < 0x84cc:
                tick['error'] = 'netobj read failed'
            else:
                u32 = lambda off: struct.unpack_from('<I', raw, off)[0]
                tick.update({
                    'is_host_148': u32(0x148),
                    'join_8414': u32(0x8414), 'flag_8410': u32(0x8410),
                    'ctr_8440': u32(0x8440), 'ctr_8444': u32(0x8444),
                    'last_len_414c': struct.unpack_from('<i', raw, 0x414c)[0],
                    'last_sender_4150': u32(0x4150),
                    'last_msg_14c': raw[0x14c:0x14c+40].hex(),
                })
                count, table = u32(0x43bc), u32(0x43b8)
                members = []
                if count and table:
                    tbuf = m.read(table, min(count, 8)*0x164)
                    if tbuf:
                        for i in range(min(count, 8)):
                            row = tbuf[i*0x164:(i+1)*0x164]
                            entry = {'id': str(struct.unpack_from('<I', row, 0)[0]),
                                     'name': row[4:35].split(b'\0')[0].decode('gbk', 'replace')}
                            for off, key in ROW_FIELDS:
                                entry[key] = struct.unpack_from('<I', row, off)[0]
                            members.append(entry)
                tick['native_sync_state_84a8'] = u32(0x84a8)
                tick['sync_count_84c8'] = u32(0x84c8)
                sptr, scount = u32(0x84c4), u32(0x84c8)
                sync = []
                if sptr and 0 < scount <= 8:
                    sbuf = m.read(sptr, scount*8)
                    if sbuf and len(sbuf) == scount*8:
                        sync = [{'id': struct.unpack_from('<I', sbuf, j*8)[0],
                                 'ready_flag': struct.unpack_from('<I', sbuf, j*8+4)[0]} for j in range(scount)]
                tick['sync_rows'] = sync
                tick['member_count'] = count
                tick['members'] = members
            out.write(json.dumps(tick, ensure_ascii=False) + '\n')
            ticks += 1
            time.sleep(args.interval)
    finally:
        m.close()
        out.close()
    print(json.dumps({'watch_done': True, 'ticks': ticks, 'out': args.out}))
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
