#!/usr/bin/env python3
"""Read-only scene state of the shadow client.

mode == 3  -> the client is inside the match map (units exist, panel clickable).
mode == 1  -> still in the room/lobby (opening snapshot not consumed).

Usage (wine py32, shadow prefix):
  shadow_mode.py [--bridge Z:\\...\\shadow\\bridge]
"""
import argparse
import ctypes as c
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', default=os.environ.get(
        'SGI_BRIDGE_Z', r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge'))
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    import p53_unit_data as D
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

    def rd(addr, n):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    try:
        ctx = D.context(rd)
    except Exception as error:
        print(json.dumps({'error': 'context_failed', 'detail': str(error), 'core': hex(core)}))
        return 1
    print(json.dumps({'pid': pid, 'core': hex(ctx['core']), 'mode': ctx['mode'],
                      'phase': ctx['phase'], 'dimensions': ctx['dimensions'],
                      'clock_hex': ctx['clock'], 'modal': ctx['modal'],
                      'in_map': ctx['mode'] == 3}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
