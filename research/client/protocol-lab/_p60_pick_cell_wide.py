"""Read-only native construction-mask candidates around a selected city.

Schema 3 replaces the historical square-radius/type-2 heuristic. The pure
rules are shared with the Hub; game input and native function calls are absent.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _p60_construction_rules import construction_candidates, native_distance

SCHEMA_VERSION = 3
RADIUS = 3


def construction_cells(snapshot, cx, cy, force=None, build_type=7):
    terrain = snapshot.get('terrain_grid') or {}
    width, height = terrain.get('width'), terrain.get('height')
    if type(width) is not int or type(height) is not int or not (0 <= cx < width and 0 <= cy < height):
        raise ValueError('city coordinate or terrain_grid unknown')
    matches = [r for r in (snapshot.get('entities') or {}).get('cities_and_barriers') or []
               if r.get('world_xy_raw') == [cx, cy] and
               (force is None or r.get('owner_raw') == force)]
    if len(matches) != 1:
        raise ValueError('source-bound city is missing or ambiguous')
    city = matches[0]
    actor = city.get('owner_raw') if force is None else force
    data = construction_candidates(snapshot, actor, build_type=build_type)
    if not data['ok']:
        raise ValueError(data.get('error') or 'native construction mask unknown')
    raw = bytes.fromhex(terrain['types'])
    candidates = [dict(xy=list(xy), terrain=raw[xy[0]*height+xy[1]],
                       dist=native_distance(*xy, cx, cy), city_id=linked['city_id'])
                  for xy, linked in data['cells'].items() if linked['city_id'] == city['city_id']]
    return {'ok': True, 'schema_version': SCHEMA_VERSION, 'native_schema': data['schema'],
            'radius': RADIUS, 'radius_metric': 'max(abs(2*x+y%2-(2*cx+cy%2)),abs(y-cy))',
            'build_type': build_type, 'city_xy': [cx, cy], 'terrain_at_city': raw[cx*height+cy],
            'occupied_count': len(data['occupied']),
            'occupied': [{'xy': list(xy), 'kind': 'object'} for xy in sorted(data['occupied'])],
            'excluded_upgrades': data['excluded_upgrades'],
            'upgrade_disabled_reason': data['upgrade_disabled_reason'],
            'complete': data.get('complete', True), 'unknown_cells': data.get('unknown_cells', 0),
            'candidates': candidates}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.path.insert(0, os.environ.get('SGI_COLLECTOR_BRIDGE', r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge'))
    from collector import Collector
    from _p60_construction_grid import with_construction_grid
    Collector = with_construction_grid(Collector)
    pid, cx, cy = map(int, argv[:3])
    force = int(argv[3]) if len(argv) > 3 else None
    build_type = int(argv[4]) if len(argv) > 4 else 7
    collector = Collector(pid)
    try:
        collector.bind()
        print(json.dumps(construction_cells(collector.capture(), cx, cy, force, build_type), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'schema_version': SCHEMA_VERSION, 'error': str(exc)}, ensure_ascii=False))
    finally:
        collector.close()


if __name__ == '__main__':
    main()
