"""Read-only city list (id/name/xy/owner) for the Hub command panel."""
import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid = int(sys.argv[1])
c = Collector(pid)
try:
    c.bind(); s = c.capture()
    cities = []
    for r in (s.get('entities') or {}).get('cities_and_barriers') or []:
        xy = r.get('world_xy_raw') or [-1, -1]
        cities.append({'city_id': r.get('city_id'), 'name': r.get('name'),
                       'owner': r.get('owner_raw'), 'xy': xy,
                       'kind': r.get('type')})
    print(json.dumps({'ok': True, 'cities': [x for x in cities if 0 <= (x['owner'] or 65535) < 32]},
                     ensure_ascii=False))
except Exception as exc:
    print(json.dumps({'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}))
finally:
    c.close()
