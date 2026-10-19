"""Read-only battlefield snapshot for the console: forces, cities, units (one capture)."""
import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid = int(sys.argv[1])
c = Collector(pid)
try:
    c.bind(); s = c.capture(); e = s.get('entities') or {}
    lords = [{'force_id': r.get('force_id'), 'name': r.get('name'),
              'gold': r.get('gold'), 'rice': r.get('rice'),
              'armament': r.get('armament'), 'troop_stock': r.get('troop_stock')}
             for r in (e.get('lords') or [])]
    cities = [{'city_id': r.get('city_id'), 'name': r.get('name'), 'owner': r.get('owner_raw'),
               'xy': r.get('world_xy_raw'), 'defense': r.get('defense')}
              for r in (e.get('cities_and_barriers') or [])]
    units = [{'unit_id': r.get('unit_id'), 'owner': r.get('owner_raw'), 'kind': r.get('unit_kind'),
              'xy': r.get('world_xy_raw'), 'attack': r.get('native_attack_index'),
              'morale': r.get('morale'), 'generals': r.get('general_ids')}
             for r in (e.get('field_units') or [])]
    print(json.dumps({'ok': True, 'lords': lords, 'cities': cities, 'units': units},
                     ensure_ascii=False))
except Exception as exc:
    print(json.dumps({'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}))
finally:
    c.close()
