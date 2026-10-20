"""Display-only coordinate proximity; never an attack/movement range."""
COLORS={'own':'#d7efdc','near5':'#f8d6d3','near10':'#fff0bd'}
LABELS={'own':'我方','near5':'5格内','near10':'6–10格','far':'10格外','unknown':'距离未知'}
def player_id(state,legacy_id=None):
 if 'player_identity' in state or 'player_force_id' in state:
  meta=state.get('player_identity') or {};fid=state.get('player_force_id')
  return fid if type(fid) is int and meta.get('status')=='confirmed' and meta.get('force_id')==fid else None
 return legacy_id

def xy(unit,world=(101,202)):
 p=unit.get('world_xy_raw')
 return p if isinstance(p,(list,tuple)) and len(p)==2 and all(type(v) is int and 0<=v<world[i] for i,v in enumerate(p)) else None

def annotate(state,legacy_id=None,world=(101,202)):
 fid=player_id(state,legacy_id);units=state.get('entities',{}).get('field_units',[])
 origins=[xy(u,world) for u in units if fid is not None and u.get('owner_raw')==fid and xy(u,world) is not None]
 for u in units:
  pos=xy(u,world);distance=None;band='unknown'
  if fid is not None and u.get('owner_raw')==fid:band='own';distance=0 if pos is not None else None
  elif pos is not None and origins:
   distance=min(max(abs(pos[0]-a[0]),abs(pos[1]-a[1])) for a in origins)
   band='near5' if distance<=5 else 'near10' if distance<=10 else 'far'
  u['proximity_band']=band;u['distance_to_player']=distance;u['proximity_color']=COLORS.get(band)
  u['proximity_label']=LABELS[band]+(f' / {distance}格' if distance is not None and band!='own' else '')
 return units

RANK={'own':0,'near5':1,'near10':2,'far':3,'unknown':3}
def sort_key(unit):
 return (RANK.get(unit.get('proximity_band'),3),unit.get('distance_to_player') if unit.get('distance_to_player') is not None else 9999,unit.get('owner_raw',65535),unit.get('unit_id',-1))
