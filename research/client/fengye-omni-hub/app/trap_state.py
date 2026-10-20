"""Read-only trap layout: MFC runtime classes and creation-container chain."""
import struct
TRAP_TYPES={0x50a0f0:'火计',0x50a1a8:'落石',0x50a260:'陷阱'}
def decode_trap(address,b,kind=None):
 if len(b)!=24:raise ValueError('Trap object requires 24 bytes')
 vt=struct.unpack_from('<I',b)[0]
 kind=kind or TRAP_TYPES.get(vt)
 if kind not in TRAP_TYPES.values():raise ValueError('Unknown trap class')
 x,y=struct.unpack_from('<hh',b,4);owner,oid=struct.unpack_from('<HH',b,8)
 return {'type':'trap','trap_kind':kind,'name':kind,'trap_id':oid,'owner_raw':owner,'world_xy_raw':[x,y],'address':hex(address),'raw_hex':b.hex(),'source_layer':'game_core','verification':'static_constructor_and_core_5b4_chain; live_GUI_alignment_pending','raw_16':struct.unpack_from('<H',b,22)[0]}

def trap_status(state):
 if 'traps' not in state.get('entities',{}):return '陷阱采集尚未加载，不能判断有无'
 return f"陷阱容器已读 {len(state['entities']['traps'])} 条；空表不证明敌城安全，未覆盖其他隐藏机制"

def city_trap_hint(state,city):
 if 'traps' not in state.get('entities',{}):return '未采集'
 xy=city.get('world_xy_raw');rows=[]
 if not xy or len(xy)!=2:return '城市坐标未知'
 for t in state['entities']['traps']:
  p=t.get('world_xy_raw')
  if not p or len(p)!=2 or any(type(v) is not int or v<0 for v in p):continue
  d=max(abs(p[0]-xy[0]),abs(p[1]-xy[1]))
  if d<=3:rows.append(f"{t['trap_kind']}@{p[0]},{p[1]}")
 return '3格内：'+' / '.join(rows) if rows else '无'

def trap_city_ids(state, radius=3):
 """City ids with a trap inside Chebyshev radius. Barriers are not cities."""
 entities = (state or {}).get('entities') or {}
 if 'traps' not in entities:
  return set()
 traps = []
 for trap in entities.get('traps') or []:
  point = trap.get('world_xy_raw')
  if isinstance(point, (list, tuple)) and len(point) == 2 and all(type(value) is int and value >= 0 for value in point):
   traps.append(point)
 found = set()
 for city in entities.get('cities_and_barriers') or []:
  if city.get('type') == 'barrier':
   continue
  xy = city.get('world_xy_raw')
  if not isinstance(xy, (list, tuple)) or len(xy) != 2:
   continue
  for point in traps:
   if max(abs(point[0] - xy[0]), abs(point[1] - xy[1])) <= radius:
    found.add(city.get('city_id'))
    break
 return found
