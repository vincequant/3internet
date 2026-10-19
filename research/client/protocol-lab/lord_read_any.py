"""Read-only lord/faction snapshot for ANY SANPK pid (diagnostic).

usage: lord_read_any.py <pid>
Prints one JSON line with force_id/name/troop_stock/armament (训练·兵装度).
"""
import json
import sys

sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector  # noqa: E402

pid = int(sys.argv[1])
c = Collector(pid)
try:
    c.bind()
    snap = c.capture()
    lords = ((snap.get('entities') or {}).get('lords')
             or snap.get('lords') or [])
    out = []
    for r in lords:
        out.append({
            'force_id': r.get('force_id'), 'name': r.get('name'),
            'troop_stock': r.get('troop_stock'), 'armament': r.get('armament_raw'),
            'rice': r.get('rice'), 'gold': r.get('gold'),
        })
    print(json.dumps({'ok': True, 'pid': pid, 'lords': out}, ensure_ascii=False))
except Exception as exc:  # noqa: BLE001
    print(json.dumps({'ok': False, 'pid': pid, 'error': '%s: %s' % (type(exc).__name__, exc)}, ensure_ascii=False))
finally:
    c.close()
