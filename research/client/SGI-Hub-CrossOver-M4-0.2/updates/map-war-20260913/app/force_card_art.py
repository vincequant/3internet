"""Native force-row artwork, using the game's exact card bitmap resources."""
from pathlib import Path
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
 def row(self,force,color,selected,player_force_id=None):
  fid=force['force_id'];hand=force.get('hand_cards');ids=tuple(r['card_id'] for r in hand['slots']) if hand else ()
  sig=(player_force_id,force.get('name'),ids,color,selected,hand is not None)
  if fid in self.rows and self.rows[fid][0]==sig:return self.rows[fid][1]
  bg='#f4df96' if fid==player_force_id else '#6b5420' if selected else '#f7f4ea'
  fg='#85291c' if fid==player_force_id else '#fff3cf' if selected else '#2c281c'
  im=Image.new('RGB',(286,54),bg);draw=ImageDraw.Draw(im)
  draw.rectangle((4,6,16,19),fill=color,outline='#302c22')
  name=('★' if fid==player_force_id else '')+force.get('name','?')
  draw.text((21,3),name,font=self.font,fill=color)
  if fid==player_force_id:draw.text((5,28),'我军',font=self.small,fill=fg)
  for i in range(5):
   x=74+i*42;cid=ids[i] if i<len(ids) else None
   if cid in self.icons:im.paste(self.icons[cid],(x,2))
   else:
    draw.rectangle((x,2,x+39,51),fill='#d4d0c0',outline='#807658')
    draw.text((x+7,17),'空' if cid==0 else '?' if cid is not None else '—',font=self.font,fill='#534a35')
  photo=ImageTk.PhotoImage(im,master=self.master);self.rows[fid]=(sig,photo)
  return photo
