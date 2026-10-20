import tkinter as tk
from tkinter import ttk
from decision_support import recommend_officers
class DecisionPanel(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={}
  tk.Label(self,text='实际出征部队 · 自动攻击力判断',bg='#f7f4ea',fg='#302c22',font=('Microsoft YaHei',13,'bold')).pack(anchor='w',padx=10,pady=(10,3))
  self.result=tk.Label(self,bg='#eee9d9',fg='#6c5128',anchor='w',justify='left',font=('Microsoft YaHei',10));self.result.pack(fill='x',padx=10,pady=6)
  tk.Button(self,text='查看我军与其他势力的实际部队攻击力 →',command=self.open_units,bg='#eee9d9',fg='#302c22').pack(anchor='w',padx=10,pady=6)
  tk.Label(self,text='逐队读取兵种、兵数、编成将和武装字段，自动代入公式。无需手填，也不使用示例能力100。\n公式攻击力用于同条件比较；不是实际扣血或胜率。缺少参数的部队在列表说明原因。',bg='#f7f4ea',fg='#80745a',justify='left').pack(anchor='w',padx=10)
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=10,pady=8)
  tk.Label(bar,text='在野人才任务推荐',bg='#f7f4ea',font=('Microsoft YaHei',12,'bold')).pack(side='left')
  self.task=tk.StringVar(value='战斗');combo=ttk.Combobox(bar,textvariable=self.task,values=['战斗','训练 / 内政','计略','网站攻击力','网站计略','网站外交力','五维总和'],state='readonly',width=13);combo.pack(side='left',padx=12);combo.bind('<<ComboboxSelected>>',lambda _=None:self.refresh())
  from officer_reference import SKILL_OPTIONS
  tk.Label(bar,text='技能',bg='#f7f4ea',fg='#302c22').pack(side='left')
  self.skill=tk.StringVar(value='全部技能')
  self.skill_combo=ttk.Combobox(bar,textvariable=self.skill,values=SKILL_OPTIONS,state='readonly',width=12);self.skill_combo.pack(side='left',padx=6);self.skill_combo.bind('<<ComboboxSelected>>',lambda _=None:self.refresh())
  tk.Label(self,text='仅显示有网站外交力参考的在野将，隐藏关隘人才；移入城市后自动恢复。点列头排序，双击武将定位地图。',bg='#f7f4ea',fg='#80745a').pack(anchor='w',padx=10)
  from officer_reference import COLUMNS
  self.tree=app.tree(self,[('name','武将',75),('city','所在城',75),('score','候选指标',65),('why','推荐依据与限制',300)]+COLUMNS)
  self.tree.bind('<Double-1>',self.locate)
 def refresh(self):
  state=self.app.doc
  if not state:return
  from unit_combat import enrich_unit_combat
  enrich_unit_combat(state)
  units=state.get('entities',{}).get('field_units',[])
  ready=sum(u.get('website_attack_power') is not None for u in units)
  self.result.config(text=f'当前已采集 {len(units)} 支出征部队，其中 {ready} 支可计算公式攻击力。\n在「全图部队」直接比较攻击力、编组战力、训练与规模；点击部队定位地图。')
  rows=recommend_officers(state,self.task.get(),self.app.global_filter.get(),self.app.city_filter.get(),self.skill.get())
  self.rows={str(i):r for i,r in enumerate(rows)};self.tree.delete(*self.tree.get_children())
  for iid,r in self.rows.items():
   g=r['officer'];from officer_reference import cells
   self.tree.insert('','end',iid=iid,values=(g.get('name','?'),g.get('location_city_name') or '未解析',f"{r['score']:g}",r['why'],*cells(g)))
 def open_units(self):
  self.app.workspace.select(self.app.frames['field_units'])
 def locate(self,_=None):
  selection=self.tree.selection()
  if not selection:return
  r=self.rows.get(selection[0])
  if not r:return
  self.app.workspace.select(self.app.global_page)
  self.app.global_book.select(self.app.frames['wild'])
  self.app.city_locator.focus_officer(r['officer'])
