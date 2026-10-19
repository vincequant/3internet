import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid=int(sys.argv[1]); force=int(sys.argv[2]) if len(sys.argv)>2 else 1
c=Collector(pid)
try:
    c.bind(); s=c.capture(); e=s.get('entities') or {}
    cities=[r for r in (e.get('cities_and_barriers') or []) if r.get('owner_raw')==force]
    builds=[r for r in (e.get('production_buildings') or []) if r.get('owner_raw')==force]
    print(json.dumps({'ok':True,'force':force,
        'cities':[{'id':r.get('city_id'),'name':r.get('name'),'xy':r.get('world_xy_raw'),'owner':r.get('owner_raw')} for r in cities],
        'buildings':[{'type':r.get('type'),'xy':r.get('world_xy_raw'),'linked':r.get('linked_city_id'),'amount':r.get('building_ui_amount'),'def':[r.get('defense_current'),r.get('defense_max')]} for r in builds],
        'building_total':len(e.get('production_buildings') or [])}, ensure_ascii=False))
finally:
    c.close()
