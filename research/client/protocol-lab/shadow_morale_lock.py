#!/usr/bin/env python3
"""Hold one unit's morale at a fixed value (士气锁定) inside the shadow client.

Runs in the shadow prefix (Wine python). Every --interval seconds it re-reads the
unit and, if morale drifted, writes the locked value back through the same verified
path as the Hub editor (object type check -> native clamp -> write -> readback).

Stop conditions (whichever comes first):
  * the --state file disappears or its "pid" no longer matches this process
  * --seconds elapsed
  * the unit cannot be found for N consecutive rounds (the unit died/disbanded)

Only the shadow client's own memory is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--owner', type=int, required=True)
    ap.add_argument('--unit-id', type=int, required=True)
    ap.add_argument('--value', type=int, required=True)
    ap.add_argument('--interval', type=float, default=0.8)
    ap.add_argument('--seconds', type=int, default=7200)
    ap.add_argument('--state', default=r'Z:\Users\vk\sgi-fengye-lab\shadow\morale-lock.json')
    ap.add_argument('--log', default=r'Z:\Users\vk\sgi-fengye-lab\shadow\logs\morale-lock.jsonl')
    args = ap.parse_args(argv)

    from p53_unit_inspector import ReadOnlyGame

    state_path = Path(args.state)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(**kv):
        kv.setdefault('wall', time.time())
        try:
            with log_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(kv, ensure_ascii=False) + '\n')
        except OSError:
            pass

    reader = ReadOnlyGame(args.bridge, None)
    address = None
    wrote = 0
    misses = 0
    deadline = time.time() + args.seconds
    state_path.write_text(json.dumps(dict(
        pid=os.getpid(), owner=args.owner, unit_id=args.unit_id,
        value=args.value, started_at=time.time()), ensure_ascii=False), encoding='utf-8')
    log(event='lock_start', owner=args.owner, unit_id=args.unit_id, value=args.value)
    try:
        while time.time() < deadline:
            # stop when the supervisor no longer owns this lock file
            try:
                state = json.loads(state_path.read_text(encoding='utf-8'))
            except OSError:
                log(event='lock_stop', reason='state_file_gone'); break
            except ValueError:
                state = None
            if state is None or state.get('pid') != os.getpid():
                log(event='lock_stop', reason='state_replaced')
                break
            try:
                snapshot = reader.capture()
                unit = None
                for row in snapshot.get('units', []):
                    if (row.get('owner_raw') == args.owner
                            and row.get('unit_id') == args.unit_id):
                        unit = row
                        break
                if unit is None:
                    misses += 1
                    if misses >= 20:
                        log(event='lock_stop', reason='unit_not_found')
                        break
                else:
                    misses = 0
                    address = int(unit['address'])
                    current = reader.unit_field(address, 'morale')
                    if current != args.value:
                        record = reader.edit_unit(address, 'morale', args.value)
                        wrote += 1
                        log(event='morale_hold', before=record['before'],
                            after=record['after'], requested=args.value)
            except Exception as error:
                log(event='error', error=repr(error))
            time.sleep(max(0.2, args.interval))
    finally:
        reader.close()
        try:
            if state_path.exists():
                now = json.loads(state_path.read_text(encoding='utf-8'))
                if now.get('pid') == os.getpid():
                    state_path.unlink()
        except Exception:
            pass
        log(event='lock_end', wrote=wrote)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
