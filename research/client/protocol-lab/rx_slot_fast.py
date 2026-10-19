#!/usr/bin/env python3
"""Fast receive-slot sampler (read-only): poll netobj+0x14c/0x414c/0x4150 at ~10 ms
and log every changed frame with wall time. Used to decide whether unicast chat
frames ever reach this client.

Usage (wine py32): rx_slot_fast.py --bridge 'Z:\\...\\shadow\\bridge' --seconds 90 --out Z:\\...\\rxfast.jsonl
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--seconds', type=float, default=90)
    ap.add_argument('--interval', type=float, default=0.01)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win, module_base
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe'}))
        return 1
    kbase = module_base(k, pid, 'koeinm.dll')
    if not kbase:
        print(json.dumps({'error': 'no koeinm.dll'}))
        return 1
    netobj = kbase + 0x12170
    h = k.OpenProcess(0x0010, False, pid)

    def rd(addr, n):
        buf = __import__('ctypes').create_string_buffer(n)
        got = __import__('ctypes').c_size_t()
        if not k.ReadProcessMemory(h, __import__('ctypes').c_void_p(addr), buf, n,
                                   __import__('ctypes').byref(got)) or got.value != n:
            return None
        return buf.raw

    last = b''
    n = 0
    out = open(args.out, 'w')
    end = time.time() + args.seconds
    while time.time() < end:
        raw_len = rd(netobj + 0x414c, 4)
        raw_sender = rd(netobj + 0x4150, 4)
        if raw_len is None or raw_sender is None:
            time.sleep(args.interval)
            continue
        ln = struct.unpack('<I', raw_len)[0]
        sender = struct.unpack('<I', raw_sender)[0]
        take = max(0, min(int(ln), 512))
        buf = rd(netobj + 0x14c, take) if take else b''
        if buf is None:
            continue
        sig = struct.pack('<II', ln, sender) + (buf or b'')
        if sig != last:
            last = sig
            n += 1
            out.write(json.dumps({
                't': time.time(), 'len': ln, 'sender': sender,
                'hex': (buf or b'').hex(),
                'sha256': hashlib.sha256(sig).hexdigest()[:16]}, ensure_ascii=False) + '\n')
            out.flush()
        time.sleep(args.interval)
    out.close()
    print(json.dumps({'frames': n, 'netobj': hex(netobj), 'seconds': args.seconds}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
