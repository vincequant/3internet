"""Proximity candidates, never claims of a war relation or an attack order."""
from collections import Counter
from itertools import combinations
from datetime import datetime,timezone

def xy(row):
 p=row.get('world_xy_raw')
 return tuple(p) if isinstance(p,(list,tuple)) and len(p)==2 and all(type(v) is int for v in p) and 0<=p[0]<101 and 0<=p[1]<202 else None

def distance(a,b):return max(abs(a[0]-b[0]),abs(a[1]-b[1]))

def battle_candidates(state):
 entities=(state or {}).get('entities',{});units=entities.get('field_units',[])
 forces={f.get('force_id'):f.get('name','未知') for f in entities.get('lords',[]) if type(f.get('force_id')) is int}
 counts=Counter(u.get('unit_id') for u in units)
 units=sorted((u for u in units if type(u.get('unit_id')) is int and counts[u['unit_id']]==1 and type(u.get('owner_raw')) is int and u['owner_raw'] in forces and xy(u) is not None),key=lambda u:u['unit_id'])
 cities=[c for c in entities.get('cities_and_barriers',[]) if xy(c) is not None and c.get('name')]
 out=[]
 for a,b in combinations(units,2):
  if a['owner_raw']==b['owner_raw']:continue
  ap,bp=xy(a),xy(b);gap=distance(ap,bp)
  if gap>5:continue
  midpoint=((ap[0]+bp[0])/2,(ap[1]+bp[1])/2)
  city=min(cities,key=lambda c:(distance(xy(c),midpoint),str(c.get('city_id')))) if cities else None
  city_gap=distance(xy(city),midpoint) if city else None
  name=(city['name']+'附近战役') if city and city_gap<=8 else ('野外战役 · '+city['name']+'方向' if city else '野外战役')
  out.append({'key':f"{a['unit_id']}:{b['unit_id']}",'name':name,'city':city,'city_distance':city_gap,'midpoint':midpoint,'distance':gap,'a':a,'b':b,'force_a':forces[a['owner_raw']],'force_b':forces[b['owner_raw']], 'status':'异势力近距；敌对/交战未核实'})
 return sorted(out,key=lambda r:(r['distance'],r['name'],r['key']))

def freshness(state):
 try:
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['capture_end'])).total_seconds()
  return '当前快照' if 0<=age<5 else '旧快照 · 位置可能已变化'
 except (KeyError,TypeError,ValueError):return '快照时间未知'

def game_session(state):return (str((state or {}).get('identity')),((state or {}).get('player_identity') or {}).get('session_id'))
