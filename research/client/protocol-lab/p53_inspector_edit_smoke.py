#!/usr/bin/env python3
"""Component smoke for the panel's own write path (no window, no game messages).

Reads one unit and its general, then performs NO-OP writes (current value back)
through ReadOnlyGame.write_bytes, exercising VirtualProtectEx/WriteProcessMemory
without changing any data. Prints JSON; exit 0 only if every step reported ok.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p53_unit_inspector import ReadOnlyGame


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--pid', type=int)
    args = ap.parse_args()
    reader = ReadOnlyGame(args.bridge, pid=args.pid)
    out = {'steps': []}
    try:
        snap = reader.capture()
        units = snap.get('units') or []
        out['units'] = len(units)
        if not units:
            out['error'] = 'no units on the map right now'
            print(json.dumps(out, ensure_ascii=False))
            return 1
        row = units[0]
        address = row['address']
        address = int(address, 16) if isinstance(address, str) else int(address)
        value = reader.unit_field(address, 'rice')
        out['steps'].append(dict(step='unit_noop',
                                 **reader.edit_unit(address, 'rice', value)))
        gid = next((g for g in (row.get('general_ids') or []) if g is not None), None)
        out['general_id'] = gid
        if gid is not None:
            stats = reader.general_stats(gid)
            out['general_read'] = dict(values=stats['values'],
                                       blade_total=stats['blade_total'])
            out['steps'].append(dict(step='general_noop',
                                     **reader.edit_general(gid, 'lead',
                                                           stats['values']['lead'])))
        out['ok'] = all(step.get('ok') for step in out['steps'])
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out['ok'] else 2
    finally:
        reader.close()


if __name__ == '__main__':
    raise SystemExit(main())
