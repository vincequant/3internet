#!/usr/bin/env python3
"""P57 / P56-E1 scanner: look for a value inside the shadow's received frames.

Read-only over a recorder session's packets.jsonl. Every received frame carries
raw_hex, so a value the shadow writes locally can be traced to the wire: if the
host rebroadcasts it (or our client uploads it and the host echoes it), the hex
will appear in `raw_hex` after the write.

Usage (macOS python3, host side):
  p57_e1_scan.py --session ~/sgi-protocol-lab-20260915/fengye-hub-session/run-... \\
      --value 54321 [--since 1792343000] [--hex 31d40000]
"""
import argparse
import json
import os
import struct
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--value', type=int, help='decimal value, scanned as LE u32 and as BE u32')
    ap.add_argument('--hex', help='explicit hex needle (bytes, no spaces)')
    ap.add_argument('--since', type=float, default=0.0, help='only frames with wall >= this epoch')
    ap.add_argument('--limit', type=int, default=40)
    args = ap.parse_args()

    needles = []
    if args.value is not None:
        needles.append(('LE32', struct.pack('<I', args.value).hex()))
        needles.append(('BE32', struct.pack('>I', args.value).hex()))
    if args.hex:
        needles.append(('HEX', args.hex.lower()))
    if not needles:
        raise SystemExit('need --value or --hex')

    path = os.path.join(args.session, 'packets.jsonl')
    hits = 0
    scanned = 0
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            try:
                e = json.loads(line)
            except Exception:
                continue
            wall = e.get('wall') or 0
            if wall < args.since:
                continue
            raw = (e.get('raw_hex') or '').lower()
            if not raw:
                continue
            scanned += 1
            for label, needle in needles:
                if needle in raw:
                    hits += 1
                    obj = e.get('object') or {}
                    when = time.strftime('%H:%M:%S', time.localtime(wall)) if wall else '-'
                    pos = raw.find(needle)
                    print(json.dumps({
                        'hit': hits, 'when': when, 'ev': e.get('ev'),
                        'type': e.get('type'), 'class': obj.get('class_name'),
                        'cmd': obj.get('cmd'), 'length': e.get('length'),
                        'needle': label, 'offset_hex': pos // 2,
                        'context': raw[max(0, pos - 24):pos + len(needle) + 24],
                    }, ensure_ascii=False))
                    if hits >= args.limit:
                        print('... limit reached (%d hits)' % hits)
                        return
    print(json.dumps({'value': args.value, 'hex': args.hex, 'frames_scanned': scanned,
                      'hits': hits, 'session': os.path.basename(args.session.rstrip('/'))},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
