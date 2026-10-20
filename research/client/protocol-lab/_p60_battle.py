"""Read-only shadow snapshot, retaining the complete original Collector state.

The caller supplies the shadow prefix and PID. No client fallback/discovery.
The compact fields remain compatible with previous console versions.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bridge'))
from collector import Collector


def snapshot(pid):
    collector = Collector(pid)
    try:
        collector.bind()
        state = collector.capture()
        entities = state.get('entities') or {}
        lords = [{key: row.get(key) for key in
                  ('force_id', 'name', 'gold', 'rice', 'armament', 'troop_stock')}
                 for row in entities.get('lords') or []]
        cities = [{'city_id': row.get('city_id'), 'name': row.get('name'),
                   'owner': row.get('owner_raw'), 'xy': row.get('world_xy_raw'),
                   'defense': row.get('defense')}
                  for row in entities.get('cities_and_barriers') or []]
        units = [{'unit_id': row.get('unit_id'), 'owner': row.get('owner_raw'),
                  'kind': row.get('unit_kind'), 'xy': row.get('world_xy_raw'),
                  'attack': row.get('native_attack_index'), 'morale': row.get('morale'),
                  'generals': row.get('general_ids')}
                 for row in entities.get('field_units') or []]
        return {'ok': True, 'readonly': True, 'state': state,
                'captured_at': state.get('capture_end'),
                'lords': lords, 'cities': cities, 'units': units}
    finally:
        collector.close()


def main():
    try:
        result = snapshot(int(sys.argv[1]))
    except Exception as exc:
        result = {'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
