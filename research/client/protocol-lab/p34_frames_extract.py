"""Curated frame dump derived OFFLINE from a p34_live.jsonl run log.

The probe already records `raw_hex` for every received notification packet
(type 3/4), every member sync batch (GetCmd) and sampled native slots. This
tool re-emits the Session-1 interesting subset as a small deterministic
frames.jsonl sidecar (derived artifact, nothing fabricated):

  - received_packet type 3                  -> local-delivery frame (chat-class, <=128 cap)
  - received_packet type 4 cmd in 6/7/10/11 -> start/orchestration broadcasts
  - sync_command_received                   -> member sync batch (GetCmd) frames

Unknown delivery shapes stay in the main log untouched; this sidecar only
highlights known classes. Read-only, no network, no native calls.
"""
import argparse
import json
from pathlib import Path

INTERESTING_CMDS = (6, 7, 10, 11)


def select(event):
    ev = event.get('ev')
    if ev == 'received_packet':
        if event.get('type') == 3:
            return 'local_delivery_type3'
        if event.get('type') == 4 and event.get('object', {}).get('cmd') in INTERESTING_CMDS:
            return 'broadcast_cmd_%s' % event['object']['cmd']
        return None
    if ev == 'sync_command_received':
        return 'sync_batch'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--out', required=True, help='New frames.jsonl (must not exist)')
    args = ap.parse_args()
    kept = 0
    with Path(args.log).open(encoding='utf-8') as src, \
            Path(args.out).open('x', encoding='utf-8') as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            why = select(event)
            if not why:
                continue
            record = {'why': why, 'ev': event.get('ev'), 'wall': event.get('wall'),
                      'mono': event.get('mono'), 'type': event.get('type'),
                      'sender': event.get('sender'), 'length': event.get('length'),
                      'raw_hex': event.get('raw_hex'), 'sha256': event.get('sha256')}
            dst.write(json.dumps(record, ensure_ascii=False) + '\n')
            kept += 1
    print(json.dumps({'kept': kept, 'out': args.out}))


if __name__ == '__main__':
    main()
