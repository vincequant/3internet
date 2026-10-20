"""Read-only construction candidates around a city (schema 2).

Keep the established radius-4 / terrain-type-2 rule. This helper does not
invent new buildability rules and never chooses a target for the user.
"""
import json
import os
import sys

SCHEMA_VERSION = 2
RADIUS = 4


def construction_cells(snapshot, cx, cy):
    entities = snapshot.get('entities') or {}
    terrain = snapshot.get('terrain_grid') or {}
    width, height = int(terrain['width']), int(terrain['height'])
    raw = bytes.fromhex(terrain['types'])
    if width <= 0 or height <= 0 or len(raw) < width*height:
        raise ValueError('terrain_grid incomplete')
    if not (0 <= cx < width and 0 <= cy < height):
        raise ValueError('city coordinate outside terrain_grid')
    occupied = {}
    for key, kind in (('production_buildings', 'building'), ('traps', 'trap'),
                      ('cities_and_barriers', 'city')):
        for row in entities.get(key) or []:
            xy = row.get('world_xy_raw') or []
            if len(xy) != 2:
                continue
            x, y = int(xy[0]), int(xy[1])
            if 0 <= x < width and 0 <= y < height:
                occupied[(x, y)] = kind
    candidates = []
    for dy in range(-RADIUS, RADIUS+1):
        for dx in range(-RADIUS, RADIUS+1):
            if dx == 0 and dy == 0:
                continue
            x, y = cx+dx, cy+dy
            if not (0 <= x < width and 0 <= y < height):
                continue
            terrain_type = raw[y*width+x]
            if terrain_type == 2 and (x, y) not in occupied:
                candidates.append({'xy': [x, y], 'terrain': terrain_type,
                                   'dist': abs(dx)+abs(dy)})
    candidates.sort(key=lambda row: (row['dist'], row['xy'][1], row['xy'][0]))
    return {'ok': True, 'schema_version': SCHEMA_VERSION, 'radius': RADIUS,
            'city_xy': [cx, cy], 'terrain_at_city': raw[cy*width+cx],
            'occupied_count': len(occupied),
            'occupied': [{'xy': list(xy), 'kind': kind} for xy, kind in sorted(occupied.items())],
            'candidates': candidates}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Historical Wine path retained; each machine may explicitly override it.
    sys.path.insert(0, os.environ.get('SGI_COLLECTOR_BRIDGE', r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge'))
    from collector import Collector
    pid, cx, cy = map(int, argv[:3])
    # Optional force argument remains accepted for existing callers. The
    # established terrain candidate rule never used it as an ownership rule.
    collector = Collector(pid)
    try:
        collector.bind()
        data = construction_cells(collector.capture(), cx, cy)
        print(json.dumps(data, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'schema_version': SCHEMA_VERSION,
                          'error': str(exc)}, ensure_ascii=False))
    finally:
        collector.close()


if __name__ == '__main__':
    main()
