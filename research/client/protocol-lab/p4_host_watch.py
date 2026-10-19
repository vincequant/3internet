"""Read-only Koeinm netobj watcher inside the host's SANPK process (Wine).

Polls once per interval and appends one JSON line:
  - member table rows: id/name/+0x2c confirmed/+0x24/+0x28 seq gates/+0x30/
    +0x34 reconnecting/+0x38 failed/+0x40/+0x4c active
  - last-received-message slot: netobj+0x414c (len), +0x4150 (sender),
    +0x14c (first 40 bytes hex) -- the live capture point for wire frames
  - session flags: +0x148 is_host, +0x8414 join switch, +0x8410, +0x8440/+0x8444

Usage (wine python32): p4_host_watch.py <PID> --out <path.jsonl>
                       [--interval 1.0] [--duration 200]
Read-only via ReadProcessMemory; never writes.
"""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time
from pathlib import Path

bridge = Path(r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge')
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
    out = open(args.out, 'w', buffering=1)
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
            raw = m.read(netobj, 0x8468)
            if not raw or len(raw) < 0x8468:
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
