#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P39c2 single-shot authorization writer (the human gate).

Only the operator runs this, and only after the user confirms the scene and
says go (task book condition). The orchestrator re-validates everything and
sends at most one frame per run; a refused authorization sends nothing.

  python3 p39c2_authorize.py --run-dir <run> --target 10.x.y.z \
      --target-port 7777 --own-id <int> --note "user said: 开始"
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import p39c2_frame as frame_codec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--target', required=True, help='host id display 10.x.y.z')
    ap.add_argument('--target-port', type=int, required=True)
    ap.add_argument('--own-id', type=int, required=True)
    ap.add_argument('--own-port', type=int, default=7777)
    ap.add_argument('--note', default='')
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    if not (run_dir / 'orchestrator.jsonl').exists():
        raise SystemExit('run_dir_has_no_orchestrator_log')
    if (run_dir / 'send-receipt.json').exists():
        raise SystemExit('run_already_sent_refusing_reauthorization')
    auth = {
        'authorized': True,
        'written_by': 'operator',
        'wall': time.time(),
        'nonce': os.urandom(8).hex(),
        'target_id': frame_codec.ip_to_id(args.target),
        'target_display': args.target,
        'target_port': args.target_port,
        'own_id': args.own_id,
        'own_port': args.own_port,
        'note': args.note,
    }
    blob = json.dumps(auth, ensure_ascii=False, indent=1)
    (run_dir / 'send-authorization.json').write_text(blob, encoding='utf-8')
    history = run_dir / 'authorizations.jsonl'
    with history.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(dict(auth, sha256=hashlib.sha256(blob.encode()).hexdigest()),
                            ensure_ascii=False) + '\n')
    print(json.dumps({'written': str(run_dir / 'send-authorization.json'),
                      'target_id': auth['target_id'], 'nonce': auth['nonce']},
                     ensure_ascii=True))


if __name__ == '__main__':
    main()
