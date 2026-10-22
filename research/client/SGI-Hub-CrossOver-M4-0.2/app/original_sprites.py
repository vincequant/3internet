"""Static original artwork; field-unit type and production amount select variants."""
from pathlib import Path
import json
from PIL import Image,ImageTk
from native_unit_rules import boat_sprite
_PORTRAIT_ATLAS=None
ROOT=Path(__file__).parent/'assets/sprites'
CATALOG=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
SPRITE_ALIAS={"铁骑兵":"重装骑兵","铁骑":"重装骑兵"}
if "重装骑兵" in CATALOG.get("units",{}):
 CATALOG["units"]["铁骑兵"]=CATALOG["units"]["重装骑兵"]
 CATALOG["units"]["铁骑"]=CATALOG["units"]["重装骑兵"]
def sprite_file(row,state=None):
 if row.get("type")=="trap":return {"火计":"fire.png","落石":"rock.png","陷阱":"pit.png"}.get(row.get("trap_kind"))
 if row.get("type") in ("city","barrier"):
  own=(state or {}).get("player_force_id")==row.get("owner_raw")
  if row["type"]=="city":
   variant=row.get("city_art_variant_flag")
   index=(0 if variant else 2)+(0 if own else 1)
  else:index={"阳平关":30,"虎牢关":26,"函谷关":27,"武关":28,"东狼关":29}.get(row.get("name"),25)+(0 if own else 6)
  return f"city-{index}.png"
 if row.get("on_water") is True:
  return boat_sprite(state,row)
 if row.get("unit_kind") in ("运输兵","粮仓兵","粮仓"):return "transport.png"
 if row.get('type') in CATALOG['buildings']:
  amount=row.get('building_ui_amount')
  if type(amount) not in (int,float) or not 0<=amount<=15000:return None
  return CATALOG['buildings'][row['type']][0 if amount<5000 else 1 if amount<10000 else 2]['file']
 kind=SPRITE_ALIAS.get(row.get('unit_kind'), row.get('unit_kind'))
 return CATALOG['units'].get(kind,{}).get('file')
class OriginalSprites:
 _CACHE={}
 def __init__(self,master):
  top=master
  try:top=master.winfo_toplevel()
  except Exception:pass
  self.master=top
  self.cache=OriginalSprites._CACHE.setdefault(id(top),{})
 def image(self,row,size,state=None):
  return self.named(sprite_file(row,state),size)
 def named(self,name,size):
  if not name:return None
  key=(name,size)
  if key not in self.cache:
   try:
    with Image.open(ROOT/name) as im:
     im=im.convert('RGBA');im.thumbnail((size,size),Image.Resampling.NEAREST);self.cache[key]=ImageTk.PhotoImage(im,master=self.master)
   except (OSError,ValueError):return None
  return self.cache[key]

 def flag(self,state,owner,size=22):
  matches=[f for f in (state or {}).get('entities',{}).get('lords',[]) if f.get('force_id')==owner]
  index=matches[0].get('color_index_raw') if len(matches)==1 else None
  return self.named(f'flag-{index}.png',size) if type(index) is int and 1<=index<=22 else None
 def portrait(self,index):
  if type(index) is not int or not 0<=index<CATALOG['portraits']['count']:return None
  key=('portrait',index)
  if key not in self.cache:
   global _PORTRAIT_ATLAS
   if _PORTRAIT_ATLAS is None:
    with Image.open(ROOT/'portraits.png') as source:_PORTRAIT_ATLAS=source.copy()
   x=index%32*96;y=index//32*120;self.cache[key]=ImageTk.PhotoImage(_PORTRAIT_ATLAS.crop((x,y,x+96,y+120)),master=self.master)
  return self.cache[key]
