import tkinter as tk
from tkinter import ttk
from decision_support import recommend_officers,attack_scenario
from training_prediction import force_predictions
class DecisionPanel(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={}
  tk.Label(self,text='网站参考收益 · 与实时事实分开',bg='#f7f4ea',font=('Microsoft YaHei',13,'bold')).pack(anchor='w',padx=10,pady=(10,3))
  self.enabled=tk.BooleanVar(value=False);self.size=tk.StringVar(value='小队');self.ability=tk.StringVar(value='100')
  tk.Checkbutton(self,text='启用情景假设：本局训练度对应网页武装度（尚未验证）',variable=self.enabled,command=self.refresh,bg='#f7f4ea').pack(anchor='w',padx=10)
  line=tk.Frame(self,bg='#f7f4ea');line.pack(fill='x',padx=10)
  tk.Label(line,text='固定规模',bg='#f7f4ea').pack(side='left');combo=ttk.Combobox(line,textvariable=self.size,values=['小队','中队','大队'],state='readonly',width=6);combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
  tk.Label(line,text='假设编组战斗能力 0–150',bg='#f7f4ea').pack(side='left',padx=8);tk.Entry(line,textvariable=self.ability,width=6).pack(side='left');self.ability.trace_add('write',lambda *_:self.refresh())
  self.result=tk.Label(self,bg='#eee9d9',fg='#6c5128',anchor='w',justify='left',font=('Microsoft YaHei',10));self.result.pack(fill='x',padx=10,pady=6)
  tk.Label(self,text='网页缓存参考，非本机伤害或胜率；假设编组能力不会自动用单将属性代入。',bg='#f7f4ea',fg='#80745a').pack(anchor='w',padx=10)
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=10,pady=8)
  tk.Label(bar,text='在野人才任务推荐',bg='#f7f4ea',font=('Microsoft YaHei',12,'bold')).pack(side='left')
  self.task=tk.StringVar(value='战斗');combo=ttk.Combobox(bar,textvariable=self.task,values=['战斗','训练 / 内政','计略'],state='readonly',width=13);combo.pack(side='left',padx=12);combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
  tk.Label(self,text='按当前属性排序；技能未匹配不参与评分。单击推荐武将跳到在野地图定位。',bg='#f7f4ea',fg='#80745a').pack(anchor='w',padx=10)
  self.tree=app.tree(self,[('name','武将',75),('city','所在城',75),('score','候选指标',65),('why','推荐依据与限制',400)])
  self.tree.bind('<<TreeviewSelect>>',self.locate)
 def refresh(self):
  state=self.app.doc
  if not state:return
  force=next((f for f in state['entities']['lords'] if f['force_id']==self.app.sel),None)
  if force:
   if not self.enabled.get():self.result.config(text=f"当前势力：{force['name']}。网站收益尚未启用；本机训练预测仍显示在军备页。")
   else:
    try:
     ability=float(self.ability.get());size=['小队','中队','大队'].index(self.size.get());lines=[f"{force['name']} · 假设{self.size.get()} / 编组能力 {ability:g}，前后保持不变"]
     for kind,pred in force_predictions(state,force).items():
      r=attack_scenario(kind,pred,size,ability);name={'infantry':'步兵','cavalry':'骑兵','bow':'弓兵'}[kind]
      if r is None:lines.append(name+'：网站无参数或本局输入不足');continue
      percent=f"（{r['percent_low']:+.1f}% 至 {r['percent_high']:+.1f}%）" if r['percent_low'] is not None else '（基线0，不计算比例）'
      lines.append(f"{name} 网站参考攻击：{r['before']} → {r['low']}–{r['high']} {percent}")
     self.result.config(text='\n'.join(lines))
    except (ValueError,TypeError):self.result.config(text='请填写0–150的有限数字；不采用无效输入计算。')
  rows=recommend_officers(state,self.task.get(),self.app.global_filter.get(),self.app.city_filter.get())
  self.rows={str(i):r for i,r in enumerate(rows)};self.tree.delete(*self.tree.get_children())
  for iid,r in self.rows.items():
   g=r['officer'];self.tree.insert('','end',iid=iid,values=(g.get('name','?'),g.get('location_city_name') or '未解析',f"{r['score']:g}",r['why']))
 def locate(self,_=None):
  selection=self.tree.selection()
  if not selection:return
  r=self.rows.get(selection[0])
  if not r:return
  self.app.global_book.select(self.app.frames['wild']);self.app.city_locator.focus_officer(r['officer'])
