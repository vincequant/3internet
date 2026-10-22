"""One wild-officer list: role ranking plus clickable native skill artwork."""
import tkinter as tk
from tkinter import ttk
from talent_roles import role_value
from officer_reference import eligible_wild
from officer_sortie import roster_skill_flags
from city_talent import lead_war_total, meets_floor, number_floor, officer_politics
from decision_support import recommend_officers
from wild_locations import wild_location_groups
BG='#f7f4ea';FG='#302c22'
SKILL_TAGS=('骑马','弓箭','埋伏','水军')
SKILL_KEYS={'骑马':'ride','弓箭':'bow','埋伏':'ambush','水军':'navy'}
SKILL_LOOK={'骑马':('#1f6b45','#f4fff8','#d7efe0','#145c38'),'弓箭':('#1f4e86','#f4f8ff','#d7e4f6','#1a4578'),'水军':('#0e6e78','#f3fcfd','#d4f1f4','#0c5c66'),'埋伏':('#8a5a00','#fff8e6','#f8e6c0','#8a5a00')}
def floor_value(owner,name):
 var=getattr(owner,name,None)
 if var is None or not hasattr(var,'get'):return None
 return number_floor(var.get())
TASK_KEYS={'攻击力':'网站攻击力','计略率':'网站计略','外交力':'网站外交力','五维合计':'五维总和'}

def officer_has_skills(officer, selected, mode='同时具备'):
 if not selected:return True
 flags=roster_skill_flags(officer)
 have={key for key,on in flags.items() if on}
 wanted={SKILL_KEYS[name] for name in selected if name in SKILL_KEYS}
 if not wanted:return True
 return wanted<=have if mode=='同时具备' else bool(wanted&have)

class RosterSkillFilter(tk.Frame):
 """Skill buttons that filter 全武将 the same way 在野 does."""
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.selected=set();self.buttons={}
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=6,pady=(0,2))
  self.mode=tk.StringVar(value='同时具备')
  mode=ttk.Combobox(bar,textvariable=self.mode,values=['同时具备','具备任一'],state='readonly',width=10)
  mode.pack(side='left',padx=4);mode.bind('<<ComboboxSelected>>',lambda _=None:self.apply())
  tk.Button(bar,text='清除技能',command=self.clear,bg=BG,fg=FG).pack(side='left',padx=4)
  self.icon_bar=tk.Frame(self,bg=BG);self.icon_bar.pack(fill='x',padx=6)
  for name in SKILL_TAGS:
   _on_bg,_on_fg,idle_bg,idle_fg=SKILL_LOOK[name]
   b=tk.Button(self.icon_bar,text=name,command=lambda n=name:self.toggle(n),bg=idle_bg,fg=idle_fg,activebackground=idle_bg,relief='flat',bd=1,padx=5,pady=3,font=(app.face,9))
   self.buttons[name]=b
  self.icon_bar.bind('<Configure>',self.layout)
  self.result=tk.Label(self,bg=BG,fg='#756443',anchor='w',justify='left');self.result.pack(fill='x',padx=6,pady=(2,0))
  self.show_count(None)
 def layout(self,event):
  cols=max(1,event.width//65)
  for i,b in enumerate(self.buttons.values()):b.grid(row=i//cols,column=i%cols,sticky='nsew',padx=2,pady=2)
 def toggle(self,name):
  if name in self.selected:self.selected.remove(name)
  else:self.selected.add(name)
  self.apply()
 def clear(self):self.selected.clear();self.apply()
 def matches(self,officer):
  return officer_has_skills(officer,self.selected,self.mode.get())
 def apply(self):
  for name,b in self.buttons.items():
   on_bg,on_fg,idle_bg,idle_fg=SKILL_LOOK[name]
   chosen=name in self.selected
   b.configure(bg=on_bg if chosen else idle_bg,fg=on_fg if chosen else idle_fg,relief='sunken' if chosen else 'flat')
  self.show_count(None)
  self.app.render_detail()
 def show_count(self,count):
  skills='、'.join(sorted(self.selected)) or '不限'
  head='全武将' if count is None else f'全武将 {count} 名'
  self.result.configure(text=f'{head} · 技能：{skills} · {self.mode.get()}')
class TalentFilters(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.selected=set();self.buttons={};self.images={}
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=6,pady=4)
  self.task=tk.StringVar(value='全部在野')
  self.mode=tk.StringVar(value='同时具备');mode=ttk.Combobox(bar,textvariable=self.mode,values=['同时具备','具备任一'],state='readonly',width=10);mode.pack(side='left',padx=4);mode.bind('<<ComboboxSelected>>',lambda _=None:self.apply())
  tk.Label(bar,text='最高统武≥',bg=BG,fg=FG).pack(side='left',padx=(8,0))
  self.blade_floor=tk.StringVar();tk.Entry(bar,textvariable=self.blade_floor,width=6).pack(side='left',padx=2)
  tk.Label(bar,text='政治≥',bg=BG,fg=FG).pack(side='left')
  self.pol_floor=tk.StringVar();tk.Entry(bar,textvariable=self.pol_floor,width=6).pack(side='left',padx=2)
  self.blade_floor.trace_add('write',lambda *_:self.apply());self.pol_floor.trace_add('write',lambda *_:self.apply())
  tk.Button(bar,text='清除技能',command=self.clear,bg=BG,fg=FG).pack(side='left',padx=4)
  self.map_button=tk.Button(bar,text='展开地图',command=self.toggle_map,bg=BG,fg=FG);self.map_button.pack(side='left',padx=4)
  tk.Button(bar,text='战力说明',command=app.show_combat,bg=BG,fg=FG).pack(side='right',padx=4)
  self.role='全部人才'
  self.icon_bar=tk.Frame(self,bg=BG);self.icon_bar.pack(fill='x',padx=6)
  for name in SKILL_TAGS:
   _on_bg,_on_fg,idle_bg,idle_fg=SKILL_LOOK[name]
   b=tk.Button(self.icon_bar,text=name,command=lambda n=name:self.toggle(n),bg=idle_bg,fg=idle_fg,activebackground=idle_bg,relief='flat',bd=1,padx=5,pady=3,font=(app.face,9));self.buttons[name]=b
  self.icon_bar.bind('<Configure>',self.layout)
  self.result=tk.Label(self,bg=BG,fg='#756443',anchor='w',justify='left',wraplength=980);self.result.pack(fill='x',padx=6,pady=4)
 def layout(self,event):
  cols=max(1,event.width//65)
  for i,b in enumerate(self.buttons.values()):b.grid(row=i//cols,column=i%cols,sticky='nsew',padx=2,pady=2)
 def toggle(self,name):
  if name in self.selected:self.selected.remove(name)
  else:self.selected.add(name)
  self.apply()
 def clear(self):self.selected.clear();self.apply()
 def apply(self):
  for name,b in self.buttons.items():
   on_bg,on_fg,idle_bg,idle_fg=SKILL_LOOK[name]
   chosen=name in self.selected
   b.configure(bg=on_bg if chosen else idle_bg,fg=on_fg if chosen else idle_fg,relief='sunken' if chosen else 'flat')
  self.app.render_detail()
 def rank(self,state):
  if self.task.get()=='全部在野':
   rows=[{'officer':g,'score':None,'why':'基础资料；点列头排序'} for g in wild_location_groups(state)[0] if eligible_wild(g)]
  else:rows=recommend_officers(state,TASK_KEYS.get(self.task.get(),self.task.get()))
  if self.role!='全部人才':
   rows=[r for r in rows if role_value(r['officer'],self.role) is not None]
   rows.sort(key=lambda r:role_value(r['officer'],self.role),reverse=True)
  if self.selected:
   rows=[row for row in rows if officer_has_skills(row['officer'],self.selected,self.mode.get())]
  blade_floor,pol_floor=floor_value(self,'blade_floor'),floor_value(self,'pol_floor')
  if blade_floor is not None or pol_floor is not None:
   rows=[row for row in rows if meets_floor(lead_war_total(row['officer']),blade_floor) and meets_floor(officer_politics(row['officer']),pol_floor)]
  return rows
 def refresh(self):
  count=len(self.app.tables['wild'].get_children())
  hidden=len(wild_location_groups(self.app.doc or {})[1])
  self.result.configure(text=f"在野人才 {count} 名 · 技能："+('、'.join(sorted(self.selected)) or '不限')+' · '+self.mode.get()+f'\n已隐藏关隘在野 {hidden} 人；移入城市后自动显示。')
 def toggle_map(self):
  loc=self.app.city_locator
  if loc.winfo_manager():loc.pack_forget();self.map_button.configure(text='展开地图')
  else:
   siblings=loc.master.winfo_children();idx=siblings.index(loc)
   loc.pack(fill='x',before=siblings[idx+1]);self.map_button.configure(text='收起地图')
