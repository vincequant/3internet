"""SANPK 3.5 read-only diplomacy formulas, independent of website officer matching."""
import struct
CARD_POINTS={1:100,2:30,3:40,4:40,5:50,6:50,7:40,8:40,9:80,10:100,11:40,12:20,13:20,14:30,16:200,17:300,18:100,19:100,20:100,23:80,24:80,25:80,26:10,27:20,28:40}
WHITE_IDS=frozenset(range(16,26))
POINT_WHITE_IDS=WHITE_IDS-{21,22}
SKILLS={'主动':0x20000,'被动':0x40000,'策反':0x80000}
def raw(row,size):
 try:b=bytes.fromhex((row or {}).get('raw_hex',''))
 except (ValueError,TypeError):return None
 return b if len(b)>=size else None
def word(b,n):return struct.unpack_from('<h',b,n)[0]
def dword(b,n):return struct.unpack_from('<I',b,n)[0]
def officer(row):
 b=raw(row,0x46)
 if b is None:
  try:
   a=[row['attributes'][k] for k in ('lead','war','intel','pol','cha')];flags=row['combat_modifier_flags_word']
   g=dict(id=row['general_id_raw'],owner=row['owner_raw'],status=row['status_code'],birth=row.get('birth_year_candidate'),soldiers=row.get('soldiers'),
          skills=row['skill_mask_raw'],relation=row.get('relation_byte_2e'),ambition=row.get('defection_ambition'),entry=row.get('defection_entry_year'),clan=row.get('defection_clan_id'),parent=row.get('defection_parent_id'),row=row)
   if any(type(x) is not int or not 0<=x<=255 for x in a) or any(type(x) is not int for x in (flags,g['id'],g['owner'],g['status'],g['skills'])):return None
  except (KeyError,TypeError):return None
 else:
  a=list(b[0x25:0x2a]);flags=struct.unpack_from('<H',b,0x44)[0]
  g=dict(id=word(b,10),owner=word(b,8),status=word(b,0x21),birth=word(b,0x1e),soldiers=word(b,0x23)&65535,
         skills=dword(b,0x2a),relation=b[0x2e],ambition=b[0x30],entry=word(b,0x38),clan=word(b,0x3e),parent=word(b,0x40),row=row)
 for i,bit in ((0,0x10),(1,0x20),(3,0x40)):
  if flags&bit:a[i]+=a[i]*2//5
 return dict(g,stats=a)
def envoy_score(row,role):
 g=officer(row)
 if g is None:return None
 base=g['stats'][3]+g['stats'][4];bonus=bool(g['skills']&SKILLS[role]);actor=(base*12+5)//10 if bonus else base
 return dict(name=row.get('name') or '未命名',id=g['id'],status=g['status'],actor=actor,base=base,bonus=bonus)
def envoys(state,fid,role):
 # The native diplomacy dialog uses status 0/6; field officers cannot be sent.
 result=[envoy_score(g,role) for g in ((state or {}).get('entities') or {}).get('generals',[]) if g.get('owner_raw')==fid]
 return sorted((g for g in result if g and g['status'] in (0,6)),key=lambda g:(-g['actor'],g['id']))
def defection_gate(score,parameter):
 d=max(0,score-parameter-130)
 return min(100,0 if d<30 else d//2 if d<70 else d)
def related(g,r):
 return g['parent']==r['id'] or g['id']==r['parent'] or (g['parent']!=-1 and g['parent']==r['parent']) or g['clan']==r['clan']
def distance(a,b):return min(abs(a-b),abs(a+b-150))
def force_inputs(force):
 b=raw(force,0x84)
 if b is not None:return dict(ruler=word(b,0x12),capital=word(b,0x14),protected=word(b,0x80),exiled=b[0x83],color=word(b,0xe))
 return dict(ruler=force.get('ruler_general_id'),capital=force.get('capital_city_id'),protected=force.get('defection_protected_general_id'),exiled=force.get('defection_exiled_flag'),color=force.get('color_index_raw'))
def defector_candidates(state,force):
 info=force_inputs(force)
 if any(type(info[k]) is not int for k in ('ruler','protected')):return None,'缺少势力策反字段'
 rows=[g for g in ((state or {}).get('entities') or {}).get('generals',[]) if g.get('owner_raw')==force['force_id']]
 gs=[officer(g) for g in rows]
 if any(g is None or any(type(g[k]) is not int for k in ('birth','soldiers','relation','ambition','entry','clan','parent')) for g in gs):return None,'缺少武将策反字段'
 ruler=next((g for g in gs if g['id']==info['ruler']),None)
 if ruler is None:return None,'君主资料缺失'
 eligible=[g for g in gs if g['id'] not in (ruler['id'],info['protected']) and g['status'] in (0,6) and not related(g,ruler) and distance(g['relation'],ruler['relation'])>=20]
 if not eligible:return [],''
 ability=max(sum(g['stats'][:4]) for g in eligible);eligible=[g for g in eligible if sum(g['stats'][:4])==ability]
 entry=max(g['entry'] for g in eligible);eligible=[g for g in eligible if g['entry']==entry]
 eligible.sort(key=lambda g:(-g['ambition'],-g['soldiers'],g['birth'],g['id']))
 # Uniform tie model after native shuffle; the first general becomes ruler.
 def key(g):return g['ambition'],g['soldiers'],-g['birth']
 result=[]
 for g in eligible:
  ahead=sum(key(h)>key(g) for h in eligible);ties=sum(key(h)==key(g) for h in eligible)
  inclusion=max(0,min(ties,3-ahead))/ties
  if inclusion:result.append(dict(g,inclusion=inclusion,leader=(1/ties if ahead==0 else 0)))
 return result,''
def defection_cities(state,force):
 capital=force_inputs(force)['capital']
 if type(capital) is not int:return None,'首都资料缺失'
 cities=[c for c in ((state or {}).get('entities') or {}).get('cities_and_barriers',[]) if c.get('owner_raw')==force['force_id'] and c.get('type')=='city' and c.get('city_id')!=capital]
 parsed=[]
 for c in cities:
  cb=raw(c,0x43)
  population=dword(cb,0x3f) if cb is not None else c.get('population')
  neighbors=list(struct.unpack_from('<8h',cb,0x26)) if cb is not None else c.get('neighbor_city_ids')
  if type(population) is not int or not isinstance(neighbors,list) or len(neighbors)!=8 or any(type(n) is not int for n in neighbors):return None,'城池人口或邻接资料缺失'
  parsed.append(dict(row=c,population=population,adjacent=capital in neighbors))
 pool=[c for c in parsed if not c['adjacent']] or parsed
 if not pool:return [],''
 peak=max(c['population'] for c in pool)
 return [c['row'] for c in pool if c['population']==peak],''
def forecast(state,own_id,envoy_id=None):
 forces=((state or {}).get('entities') or {}).get('lords',[]);own=next((f for f in forces if f.get('force_id')==own_id),None)
 available=envoys(state,own_id,'策反') if own else []
 envoy=next((g for g in available if g['id']==envoy_id),available[0] if available else None)
 held=any(c.get('card_id')==15 for c in ((own or {}).get('hand_cards') or {}).get('slots',[]))
 fb=raw(own,0x6d);pending=None
 if fb is not None and fb[0x67]==15 and envoy and word(fb,0x65)==envoy['id'] and fb[0x6c]<20:pending=(word(fb,0x63),fb[0x6c])
 if fb is None:
  p=(own or {}).get('diplomacy_pending') or {}
  if p.get('card_id')==15 and envoy and p.get('envoy')==envoy['id'] and type(p.get('parameter')) is int and 0<=p['parameter']<20:pending=(p.get('target'),p['parameter'])
 # New force requires both a vacant ID and a vacant colour. Missing colours stay unknown.
 colors=[force_inputs(f)['color'] for f in forces];space=None
 if all(type(x) is int for x in colors):space=any(i not in {f['force_id'] for f in forces} for i in range(22)) and any(i not in set(colors) for i in range(1,23))
 result=[]
 for f in forces:
  if f.get('force_id')==own_id:continue
  info=force_inputs(f);gs,why=defector_candidates(state,f);cities,cwhy=defection_cities(state,f)
  reason=why or cwhy
  if info['exiled'] is None:reason=reason or '流亡状态资料缺失'
  elif info['exiled']:reason='目标势力已流亡'
  elif space is False:reason='无空闲势力或颜色位置'
  elif gs==[]:reason='没有符合条件的叛离武将'
  elif cities==[]:reason='没有可叛离的非首都城池'
  elif space is None:reason=reason or '势力颜色资料缺失'
  fixed=pending[1] if pending and pending[0]==f['force_id'] else None
  rates=[defection_gate(envoy['actor'],r) for r in range(20)] if envoy else []
  gate=(rates[fixed] if fixed is not None else sum(rates)/20) if rates else None
  impossible=bool(info['exiled']) or space is False or gs==[] or cities==[]
  chance=0 if impossible else None if reason or not envoy else gate
  result.append(dict(force=f,envoy=envoy,held=held,chance=chance,gate=gate,parameter=fixed,range=(min(rates),max(rates)) if rates else None,generals=gs,cities=cities,reason=reason))
 return dict(held=held,envoys=available,envoy=envoy,rows=result)
