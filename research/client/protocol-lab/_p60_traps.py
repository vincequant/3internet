import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid=int(sys.argv[1]); c=Collector(pid)
try:
    c.bind(); s=c.capture(); e=s.get('entities') or {}
    tr=[{k:r.get(k) for k in ('type','world_xy_raw','owner_raw','linked_city_id','defense_current','defense_max','trap_ui_amount','object_id_candidate')} for r in (e.get('traps') or [])]
    print(json.dumps({'ok':True,'traps':tr,'production':len(e.get('production_buildings') or [])},ensure_ascii=False))
finally:
    c.close()
