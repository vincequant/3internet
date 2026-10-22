"""One wild-officer list: role ranking plus clickable native skill artwork."""
import tkinter as tk
from tkinter import ttk
from talent_roles import ROLES,role_value
from officer_reference import SKILL_OPTIONS,officer_metrics,eligible_wild
from decision_support import recommend_officers
from wild_locations import wild_location_groups
BG='#f7f4ea';FG='#302c22'
ICON_INDEX={'骑马':0,'弓箭':1,'水军':2,'引诱':4,'伪兵':5,'攻城':6,'埋伏':7,'奇袭':8,'无双':9,'谍报':10,'提案':11,'拒绝':12,'计谋':13}
TASK_KEYS={'攻击力':'网站攻击力','计略率':'网站计略','外交力':'网站外交力','五维合计':'五维总和'}
class TalentFilters(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.selected=set();self.buttons={};self.images={}
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=6,pady=4)
  tk.Label(bar,text='任务 / 排序',bg=BG,fg=FG).pack(side='left')
  self.task=tk.StringVar(value='全部在野');self.task_combo=ttk.Combobox(bar,textvariable=self.task,values=['全部在野','战斗','训练 / 内政','计略','攻击力','计略率','外交力','五维合计'],state='readonly',width=14);self.task_combo.pack(side='left',padx=6);self.task_combo.bind('<<ComboboxSelected>>',self.change_task)
  self.mode=tk.StringVar(value='同时具备');mode=ttk.Combobox(bar,textvariable=self.mode,values=['同时具备','具备任一'],state='readonly',width=10);mode.pack(side='left',padx=4);mode.bind('<<ComboboxSelected>>',lambda _:self.apply())
  tk.Button(bar,text='清除技能',command=self.clear,bg=BG,fg=FG).pack(side='left',padx=4)
  self.map_button=tk.Button(bar,text='展开地图',command=self.toggle_map,bg=BG,fg=FG);self.map_button.pack(side='left',padx=4)
  tk.Button(bar,text='全图城关',command=lambda:app.workspace.select(app.world_cities),bg=BG,fg=FG).pack(side='right')
  tk.Button(bar,text='全图部队',command=self.open_units,bg=BG,fg=FG).pack(side='right')
  tk.Button(bar,text='战力说明',command=app.show_combat,bg=BG,fg=FG).pack(side='right',padx=4)
  rolebar=tk.Frame(self,bg=BG);rolebar.pack(fill='x',padx=6,pady=2)
  self.role='全部人才';self.role_buttons={}
  for name in ROLES:
   btn=tk.Button(rolebar,text=name,command=lambda n=name:self.choose_role(n),bg='#e8dbae',fg='#654c19',relief='flat',padx=5,pady=3,font=(app.face,9));btn.pack(side='left',padx=2);self.role_buttons[name]=btn
  self.icon_bar=tk.Frame(self,bg=BG);self.icon_bar.pack(fill='x',padx=6)
  for name in SKILL_OPTIONS[1:]:
   b=tk.Button(self.icon_bar,text=name,command=lambda n=name:self.toggle(n),bg='#dde8df',fg='#294636',activebackground='#bdcfc0',relief='flat',bd=1,padx=5,pady=3,font=(app.face,9));self.buttons[name]=b
  self.icon_bar.bind('<Configure>',self.layout)
  self.result=tk.Label(self,bg=BG,fg='#756443',anchor='w',justify='left',wraplength=980);self.result.pack(fill='x',padx=6,pady=4)
 def layout(self,event):
  cols=max(1,event.width//65)
  for i,b in enumerate(self.buttons.values()):b.grid(row=i//cols,column=i%cols,sticky='nsew',padx=2,pady=2)
 def change_task(self,_=None):
  self.app.sorts.pop(self.app.tables['wild'],None);self.apply()
 def toggle(self,name):
  if name in self.selected:self.selected.remove(name)
  else:self.selected.add(name)
  self.apply()
 def clear(self):self.selected.clear();self.apply()
 def apply(self):
  for name,b in self.buttons.items():b.configure(bg='#58755e' if name in self.selected else '#dde8df',fg='#ffffff' if name in self.selected else '#294636',relief='sunken' if name in self.selected else 'flat')
  self.app.render_detail()
 def choose_role(self,name):
  self.role=name;self.app.sorts.pop(self.app.tables['wild'],None)
  for n,b in self.role_buttons.items():b.configure(bg='#80642b' if n==name else '#e8dbae',fg='#ffffff' if n==name else '#654c19')
  self.apply()
 def rank(self,state):
  if self.task.get()=='全部在野':
   rows=[{'officer':g,'score':None,'why':'基础资料；点列头排序'} for g in wild_location_groups(state)[0] if eligible_wild(g)]
  else:rows=recommend_officers(state,TASK_KEYS.get(self.task.get(),self.task.get()))
  if self.role!='全部人才':
   rows=[r for r in rows if role_value(r['officer'],self.role) is not None]
   rows.sort(key=lambda r:role_value(r['officer'],self.role),reverse=True)
  if self.selected:
   def matches(row):
    skills=set(officer_metrics(row['officer'])['skills'].split(' / '))
    return self.selected<=skills if self.mode.get()=='同时具备' else bool(self.selected&skills)
   rows=[row for row in rows if matches(row)]
  return rows
 def refresh(self):
  count=len(self.app.tables['wild'].get_children())
  tree=self.app.tables['wild']
  if self.role in ('主动外交','被动外交'):
   tree.heading('ref_diplomacy',text=self.role+'力')
   for iid,g in self.app.row_records.get('wild',{}).items():
    if tree.exists(iid):tree.set(iid,'ref_diplomacy',role_value(g,self.role))
  else:tree.heading('ref_diplomacy',text='外交力')
  hidden=len(wild_location_groups(self.app.doc or {})[1])
  self.result.configure(text=f"在野人才 {count} 名 · {self.role if self.role!='全部人才' else self.task.get()} · 技能："+('、'.join(sorted(self.selected)) or '不限')+' · '+self.mode.get()+f'\n已隐藏关隘在野 {hidden} 人；移入城市后自动显示。')
 def open_units(self):self.app.workspace.select(self.app.frames['field_units'])
 def toggle_map(self):
  loc=self.app.city_locator
  if loc.winfo_manager():loc.pack_forget();self.map_button.configure(text='展开地图')
  else:
   siblings=loc.master.winfo_children();idx=siblings.index(loc)
   loc.pack(fill='x',before=siblings[idx+1]);self.map_button.configure(text='收起地图')
