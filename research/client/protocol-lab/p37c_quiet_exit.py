#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P37c quiet exit: fire the P41 leave instruction (the 0x21 broadcast) from
the ghost's own loader so the member leaves quietly before the chain stops.

Usage:
  python3 p37c_quiet_exit.py <run-dir> --own-id <ghost session id> [--tag2 N]

Reads <run-dir>/ctx.json (b_port; written by p39c2_loader_host), builds
p41_leave_frame.build_leave_instr1000(own_id, tag2) — flags 01 01 broadcast —
sends ONE datagram to 127.0.0.1:<b_port>, writes quiet-exit-receipt.json.
No retries; refuses a second fire for the same run dir.
"""
import argparse
import hashlib
import json
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p41_leave_frame as p41


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--own-id', type=int, required=True)
    ap.add_argument('--tag2', type=int, default=0)
    args = ap.parse_args()
    run = Path(args.run_dir).resolve()
    receipt_path = run / 'quiet-exit-receipt.json'
    if receipt_path.exists():
        print(json.dumps({'refused': 'already_fired', 'receipt': str(receipt_path)}))
        return 1
    ctx = json.loads((run / 'ctx.json').read_text(encoding='utf-8'))
    b_port = ctx.get('b_port')
    if not isinstance(b_port, int) or not (1 <= b_port <= 65535):
        print(json.dumps({'refused': 'b_port_invalid', 'ctx': ctx}))
        return 1
    tag2 = args.tag2 or random.randrange(1, 0x10000)
    instr = p41.build_leave_instr1000(args.own_id, tag2)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    rc = sock.sendto(instr, ('127.0.0.1', b_port))
    sockname = list(sock.getsockname())
    sock.close()
    receipt = {
        'ev': 'p37c_quiet_exit', 'wall': time.time(), 'rc': rc,
        'dst': ['127.0.0.1', b_port], 'sockname': sockname,
        'instruction_hex': instr.hex(),
        'instruction_sha256': hashlib.sha256(instr).hexdigest(),
        'own_id': args.own_id, 'own_hex': '%08x' % args.own_id,
        'tag2': '%04x' % tag2,
        'expected_wire_payload': p41.build_leave_payload(args.own_id, tag2).hex(),
        'note': 'one frame per run; no retries',
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=1),
                            encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
