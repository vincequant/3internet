"""Force stock and training cards. City remain lives on the 城关 tab."""
import tkinter as tk
from state_extensions import training_progress
from opening_troop_routes import EMPTY, opening_route_note
from preparation_model import GRADE_FG

NAMES={'infantry':('步兵','强化步兵','重装步兵'),'cavalry':('骑兵','强化骑兵','铁骑兵'),'bow':('弓兵','弩兵','连弩')}
KIND_META=(
 ('infantry','步','#efe6d0','#8a6a2a'),
 ('cavalry','骑','#f3e2c4','#8a4e1a'),
 ('bow','弓','#e4ead6','#3f5a2c'),
)
COLS=('兵种级别','库存兵数量','每年夏季募兵≈','训练度','练兵效率')
WELL='#f7f4ea'
INK='#302c22'
MUTED='#756443'

def troop_info(kind,raw):
 t=training_progress(raw)
 if t is None:return {'name':'兵种等级未知','training':None,'tier':None}
 tier=0 if raw<100 else 1 if raw<200 else 2
 return {'name':NAMES[kind][tier],'training':t,'tier':tier}

def training_bar(parent, card_bg, face):
 row=tk.Frame(parent,bg=card_bg)
 row.pack(fill='x')
 track=tk.Frame(row,bg='#d9d0bc',height=16)
 track.pack(side='left',fill='x',expand=True)
 track.pack_propagate(False)
 fill=tk.Frame(track,bg=GRADE_FG[0])
 fill.place(relx=0,rely=0,relheight=1,relwidth=0)
 value=tk.Label(row,text='—',bg=card_bg,fg=INK,font=(face,12),width=4,anchor='e')
 value.pack(side='left',padx=(8,0))
 return {'fill':fill,'value':value}

def paint_training(widget, training, tier):
 if not isinstance(widget, dict):
  widget.config(text=f'{training} / 100' if training is not None else '未知')
  return
 if training is None:
  widget['fill'].place_configure(relwidth=0)
  widget['value'].config(text='—')
  return
 span=max(0.0, min(1.0, training/100))
 color=GRADE_FG[tier] if tier in (0,1,2) else GRADE_FG[0]
 widget['fill'].configure(bg=color)
 widget['fill'].place_configure(relwidth=span)
 widget['value'].config(text=str(training))

class MilitarySummary(tk.Frame):
 """Full-page stock cards; city remain is listed under 城关."""
 def __init__(self,parent,app=None):
  super().__init__(parent,bg=WELL);self.app=app;self.tiles={};self.busy=False
  face=getattr(app,'face','PingFang SC') if app is not None else 'PingFang SC'
  try:
   from display_layout import pixels
  except Exception:
   def pixels(value):return value
  self.note=tk.Label(self,text=EMPTY,
                     bg='#eee0c4',fg='#6b3f12',anchor='w',justify='left',wraplength=720,font=(face,12))
  self.note.pack(fill='x',padx=8,pady=(8,4))
  board=tk.Frame(self,bg=WELL);board.pack(fill='both',expand=True,padx=6,pady=(0,8))
  for col in range(3):board.columnconfigure(col,weight=1)
  board.rowconfigure(0,weight=1)
  for col,(kind,short,card_bg,accent) in enumerate(KIND_META):
   card=tk.Frame(board,bg=card_bg,highlightbackground=accent,highlightthickness=2)
   card.grid(row=0,column=col,sticky='nsew',padx=8,pady=8)
   card.columnconfigure(0,weight=1)
   card.rowconfigure(2,weight=1)
   head=tk.Frame(card,bg=accent)
   head.grid(row=0,column=0,sticky='ew')
   tk.Label(head,text=short,bg=accent,fg='#fff8ee',font=(face,12,'bold'),anchor='w',padx=12,pady=6).pack(side='left')
   stars=tk.Label(head,text='☆☆☆',bg=accent,fg='#f6d36a',font=(face,14,'bold'),anchor='e',padx=12,pady=6)
   stars.pack(side='right')
   name=tk.Label(card,bg=card_bg,fg=INK,font=(face,22,'bold'),anchor='w',padx=14,pady=10)
   name.grid(row=1,column=0,sticky='ew')
   count=tk.Label(card,bg=card_bg,fg=INK,font=(face,28,'bold'),anchor='w',padx=14,pady=8)
   count.grid(row=2,column=0,sticky='nsew')
   body=tk.Frame(card,bg=card_bg);body.grid(row=3,column=0,sticky='ew',padx=14,pady=12)
   def field(title):
    tk.Label(body,text=title,bg=card_bg,fg=MUTED,font=(face,10),anchor='w').pack(fill='x',pady=(8,0))
    value=tk.Label(body,bg=card_bg,fg=INK,font=(face,13),anchor='w',justify='left',wraplength=pixels(220))
    value.pack(fill='x')
    return value
   recruits=field('每年夏季募兵')
   tk.Label(body,text='训练度',bg=card_bg,fg=MUTED,font=(face,10),anchor='w').pack(fill='x',pady=(8,2))
   training=training_bar(body,card_bg,face)
   after=field('夏季后预计')
   efficiency=field('练兵效率')
   self.tiles[kind]=[name,count,recruits,training,efficiency,after,stars]
  self.bind('<Configure>',lambda e:self.note.configure(wraplength=max(180,e.width-24)))

 def update_force(self,force,state=None):
  from recruitment_summary import annual_recruitment,recruitment_text
  from training_prediction import efficiency_ratio
  from training_sim import kind_stars, star_glyph
  if getattr(self,'note',None) is not None:
   self.note.config(text=opening_route_note(force))
  totals=annual_recruitment(state,force.get('force_id'))
  for kind,cells in self.tiles.items():
   name,count,recruits,training=cells[:4]
   recruits.config(text=recruitment_text(totals[kind]))
   info=troop_info(kind,force.get('armament_raw',{}).get(kind));stock=force.get('troop_stock',{}).get(kind)
   tier=info['tier'] if info['tier'] in (0,1,2) else 0
   name.config(text=info['name'],fg=GRADE_FG[tier]);count.config(text=f'{stock:,}' if type(stock) is int else '未知')
   paint_training(training, info['training'], tier)
   if len(cells)>4:cells[4].config(text=efficiency_ratio(stock))
   if len(cells)>5:cells[5].config(text=self._after_text(kind,force.get('armament_raw',{}).get(kind),stock,totals[kind]))
   if len(cells)>6:cells[6].config(text=star_glyph(kind_stars(kind,force_id=force.get('force_id'),name=force.get('name'))))

 def _after_text(self,kind,raw,stock,annual):
  from recruitment_summary import mix_after_recruit
  added=annual.get('known') if isinstance(annual,dict) else None
  pred=mix_after_recruit(raw,stock,added if type(added) is int else None)
  if pred is None:
   return '未知'
  info=troop_info(kind,pred['raw'])
  text=f"{pred['stock']:,} · {info['name']} {info['training']}/100"
  if annual.get('missing'):
   return text+' · 募兵未采全'
  if pred['added']==0:
   return text+' · 无新兵'
  return text

 def update_prediction(self,state,force):
  pass
