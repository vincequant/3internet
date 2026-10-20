"""Occupied map cells (buildings / traps / cities+barriers), read-only.

Used by the console to refuse a build on a cell that already holds an object.
Same occupancy rule as `_p60_pick_cell_wide.py`: production buildings, traps and
cities/barriers all count as taken, keyed by `world_xy_raw`.
"""
import json
import sys

sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector

pid = int(sys.argv[1])
c = Collector(pid)
try:
    c.bind()
    snap = c.capture()
    ents = snap.get('entities') or {}
    rows = []
    for key, kind in (('production_buildings', 'building'), ('traps', 'trap'),
                      ('cities_and_barriers', 'city')):
        for row in (ents.get(key) or []):
            xy = row.get('world_xy_raw') or []
            if len(xy) == 2 and isinstance(xy[0], int) and isinstance(xy[1], int) and xy[0] >= 0:
                rows.append({'kind': kind, 'type': row.get('type'),
                             'owner': row.get('owner_raw'), 'xy': [xy[0], xy[1]]})
    print(json.dumps({'ok': True, 'count': len(rows), 'occupied': rows}, ensure_ascii=False))
except Exception as exc:  # noqa: BLE001
    print(json.dumps({'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}))
finally:
    c.close()
