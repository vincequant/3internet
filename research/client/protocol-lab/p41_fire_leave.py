#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P41 fire: send ONE leave instruction to the run's own loader (B port).

Usage: python3 p41_fire_leave.py <run-dir> [--tag2 N]

Reads <run-dir>/ready.json (own_id, b_port), builds
p41_leave_frame.build_leave_instr1000(own_id, tag2, flags 01 01 broadcast),
sends it ONCE to 127.0.0.1:<b_port>, writes fire-receipt.json.
Refuses to fire twice (one frame per run; no retries).
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
import p39c2_frame as frame_codec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--tag2', type=int, default=0)
    args = ap.parse_args()
    run_dir = Path(args.run_dir).resolve()
    ready = json.loads((run_dir / 'ready.json').read_text(encoding='utf-8'))
    own_id = ready['own_id']
    b_port = ready['b_port']
    receipt_path = run_dir / 'fire-receipt.json'
    if receipt_path.exists():
        print(json.dumps({'refused': 'already_fired', 'receipt': str(receipt_path)}))
        return 1
    if not isinstance(b_port, int) or not (1 <= b_port <= 65535):
        print(json.dumps({'refused': 'b_port_invalid', 'b_port': b_port}))
        return 1
    tag2 = args.tag2 or random.randrange(0x10000)
    instr = p41.build_leave_instr1000(own_id, tag2)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    rc = sock.sendto(instr, ('127.0.0.1', b_port))
    sockname = list(sock.getsockname())
    sock.close()
    receipt = {
        'ev': 'p41_fire_receipt', 'wall': time.time(), 'rc': rc,
        'dst': ['127.0.0.1', b_port], 'sockname': sockname,
        'instruction_hex': instr.hex(),
        'instruction_sha256': hashlib.sha256(instr).hexdigest(),
        'own_id': own_id, 'own_hex': '%08x' % own_id, 'tag2': '%04x' % tag2,
        'expected_wire_payload': p41.build_leave_payload(own_id, tag2).hex(),
        'note': 'one frame per run; no retries',
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=1),
                            encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
