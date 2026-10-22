"""Native force-row artwork, using the game's exact card bitmap resources."""
from pathlib import Path
from force_relations import WAR_BACKGROUND, WAR_FOREGROUND, ALLY_BACKGROUND, ALLY_FOREGROUND
import json
from PIL import Image,ImageDraw,ImageFont,ImageTk
CATALOG=json.loads(Path(__file__).with_name('card_catalog.json').read_text(encoding='utf8'))
ASSETS=Path(__file__).parent/'assets'/'res'
def load_font(size):
 for path in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Supplemental/Songti.ttc','C:/Windows/Fonts/msyh.ttc']:
  try:return ImageFont.truetype(path,size)
  except OSError:pass
 return ImageFont.load_default()
class ForceCardArtwork:
 def __init__(self,master):
  self.master=master;self.rows={};self.icons={}
  self.font=load_font(14)
  self.small=load_font(10)
  for cid,rid in CATALOG['icon_resource_ids'].items():
   try:self.icons[int(cid)]=Image.open(ASSETS/f'{rid}.bmp').convert('RGB')
   except OSError:pass
 def row(self,force,color,selected,player_force_id=None,war=False,ally=False,show_cards=True,modified=False):
  fid=force['force_id'];hand=force.get('hand_cards');ids=tuple(r['card_id'] for r in hand['slots']) if hand else ()
  sig=(player_force_id,force.get('name'),ids,color,selected,hand is not None,war,ally,show_cards,modified)
  if fid in self.rows and self.rows[fid][0]==sig:return self.rows[fid][1]
  bg='#f4df96' if fid==player_force_id else WAR_BACKGROUND if war else ALLY_BACKGROUND if ally else '#6b5420' if selected else '#f7f4ea'
  fg='#85291c' if fid==player_force_id else WAR_FOREGROUND if war else ALLY_FOREGROUND if ally else '#fff3cf' if selected else '#2c281c'
  width=286 if show_cards else 72
  im=Image.new('RGB',(width,54),bg);draw=ImageDraw.Draw(im)
  draw.rectangle((4,6,16,19),fill=color,outline='#302c22')
  name=('★' if fid==player_force_id else '')+force.get('name','?')
  draw.text((21,3),name,font=self.font,fill=color)
  if fid==player_force_id:draw.text((5,28),'我军',font=self.small,fill=fg)
  elif war:draw.text((5,28),'与我军战争',font=self.small,fill=WAR_FOREGROUND)
  elif ally:draw.text((5,28),'同盟',font=self.small,fill=ALLY_FOREGROUND)
  if modified:
   badge=modified if isinstance(modified,str) else '外挂'
   draw.rectangle((4,41,11+10*len(badge),53),fill='#b11a1a')
   draw.text((7,40),badge,font=self.small,fill='#ffffff')
  if show_cards:
   for i in range(5):
    x=74+i*42;cid=ids[i] if i<len(ids) else None
    if cid in self.icons:im.paste(self.icons[cid],(x,2))
    else:
     draw.rectangle((x,2,x+39,51),fill='#d4d0c0',outline='#807658')
     draw.text((x+7,17),'空' if cid==0 else '?' if cid is not None else '—',font=self.font,fill='#534a35')
  scale=getattr(self.master,'sgi_ui_scale',1.)
  if scale!=1:im=im.resize((round(width*scale),round(54*scale)),Image.Resampling.LANCZOS)
  photo=ImageTk.PhotoImage(im,master=self.master);self.rows[fid]=(sig,photo)
  return photo
