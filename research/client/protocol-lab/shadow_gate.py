#!/usr/bin/env python3
"""Read-only: the resident-start gate fields.

Gate (p51_shadow_resident.py, action=start):
    core+0x660 == 0  (local UI queue drained)
    core+0x6bc in (0,2)  (not mid-round; 1 = round in flight)

Also prints netobj+0x84b4 (receive backlog) and +0x8444 (frame counter) so the
"is anything moving" question can be answered in the same sample.

Usage (wine py32, shadow prefix):
  shadow_gate.py [--bridge Z:\\...\\shadow\\bridge] [--seconds 20] [--interval 2]
"""
import argparse
import ctypes as c
import json
import os
import struct
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', default=os.environ.get(
        'SGI_BRIDGE_Z', r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge'))
    ap.add_argument('--seconds', type=float, default=20.0)
    ap.add_argument('--interval', type=float, default=2.0)
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
    sys.path.insert(0, args.bridge)
    from collector import Collector
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe'}))
        return 1
    col = Collector(pid)
    try:
        col.bind()
        core = int(col.core)
    finally:
        col.close()
    h = k.OpenProcess(0x0010, False, pid)

    def rd(addr):
        buf = c.create_string_buffer(4)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, 4, c.byref(got)) or got.value != 4:
            return None
        return struct.unpack('<I', buf.raw)[0]

    base = None
    psapi = c.WinDLL('psapi')
    psapi.EnumProcessModulesEx.argtypes = [c.c_void_p, c.POINTER(c.c_void_p), c.c_uint32,
                                           c.POINTER(c.c_uint32), c.c_uint32]
    psapi.GetModuleFileNameExW.argtypes = [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_uint32]
    modules = (c.c_void_p * 512)()
    needed = c.c_uint32()
    if psapi.EnumProcessModulesEx(h, modules, c.sizeof(modules), c.byref(needed), 3):
        for item in modules[:needed.value // c.sizeof(c.c_void_p)]:
            name = c.create_unicode_buffer(1024)
            psapi.GetModuleFileNameExW(h, item, name, len(name))
            if name.value.lower().endswith('\\koeinm.dll'):
                base = item
    net = (base + 0x12170) if base else None

    end = time.time() + args.seconds
    while time.time() < end:
        ui_queue = rd(core + 0x660)
        f6bc = rd(core + 0x6bc)
        sample = {'wall': round(time.time(), 2), 'core': hex(core),
                  'ui_queue_660': ui_queue, 'f6bc_6bc': f6bc,
                  'gate_ok': (ui_queue == 0 and f6bc in (0, 2))}
        if net:
            sample['rx_backlog_84b4'] = rd(net + 0x84b4)
            sample['frames_8444'] = rd(net + 0x8444)
            sample['sync_state_84a8'] = rd(net + 0x84a8)
        print(json.dumps(sample), flush=True)
        time.sleep(args.interval)
    return 0


if __name__ == '__main__':
    sys.exit(main())
