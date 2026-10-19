#!/usr/bin/env python3
"""Watch a hub session's received frames for a value (default 54321) and log hits.

Read-only tail of packets.jsonl; used while a live experiment is running so the
hit (or its absence) has a timestamp independent of when we look.
"""
import argparse
import json
import os
import struct
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--value', type=int, default=54321)
    ap.add_argument('--minutes', type=float, default=20.0)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    needle = struct.pack('<I', args.value)
    end = time.time() + args.minutes * 60
    seen = 0
    with open(args.out, 'a', buffering=1, encoding='utf-8') as log:
        log.write('--- watch start %s value=%d ---\n' % (time.strftime('%H:%M:%S'), args.value))
        while time.time() < end:
            path = os.path.join(args.session, 'packets.jsonl')
            try:
                with open(path, 'rb') as handle:
                    handle.seek(max(0, handle.seek(0, os.SEEK_END) - 65536))
                    tail = handle.read().decode('utf-8', 'replace').splitlines()
            except OSError:
                time.sleep(1)
                continue
            for line in tail:
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('ev') != 'received_packet':
                    continue
                raw = (row.get('raw_hex') or '').lower()
                if len(needle.hex()) and needle.hex() in raw:
                    seen += 1
                    obj = row.get('object') or {}
                    log.write('%s HIT class=%s cmd=%s len=%s\n' % (
                        time.strftime('%H:%M:%S', time.localtime(row.get('wall') or time.time())),
                        obj.get('class_name'), obj.get('cmd'), row.get('length')))
            time.sleep(1.5)
        log.write('--- watch end %s hits=%d ---\n' % (time.strftime('%H:%M:%S'), seen))


if __name__ == '__main__':
    main()
