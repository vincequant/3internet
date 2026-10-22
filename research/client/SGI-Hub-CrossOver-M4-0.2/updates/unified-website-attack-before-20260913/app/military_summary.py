"""Military presentation, using status-window name thresholds (not a combat score)."""
import tkinter as tk
from tkinter import ttk
from state_extensions import training_progress
NAMES={'infantry':('步兵','强化步兵','重装步兵'),'cavalry':('骑兵','强化骑兵','铁骑兵'),'bow':('弓兵','弩兵','连弩')}
def troop_info(kind,raw):
 t=training_progress(raw)
 if t is None:return {'name':'兵种等级未知','training':None,'tier':None}
 tier=0 if raw<100 else 1 if raw<200 else 2
 return {'name':NAMES[kind][tier],'training':t,'tier':tier}
class MilitarySummary(tk.Frame):
 """Compact current-state table; forecasts belong in the decision support page."""
 def __init__(self,parent):
  super().__init__(parent,bg='#f7f4ea');self.tiles={}
  for col,title in enumerate(('兵种级别','库存兵数量','每年夏季募兵≈','训练度','攻击基值 小/中/大')):
   tk.Label(self,text=title,bg='#eee9d9',fg='#756443',font=('Microsoft YaHei',10),anchor='w').grid(row=0,column=col,sticky='ew',padx=2,pady=(2,1))
   self.columnconfigure(col,weight=1)
  for row,kind in enumerate(('infantry','cavalry','bow'),1):
   cells=[]
   for col in range(5):
    cell=tk.Label(self,bg='#f7f4ea',fg='#302c22',font=('Microsoft YaHei',11,'bold' if col==0 else 'normal'),anchor='w',padx=3,pady=1)
    cell.grid(row=row,column=col,sticky='ew',padx=2);cells.append(cell)
   self.tiles[kind]=cells
  self.note=tk.Label(self,text='募兵按现有城市人口估算，未扣断线城市。攻击基值含训练，对部队/弓系远射；骑弓按具备对应技能，未乘武将战力，不是扣血。',bg='#f7f4ea',fg='#786e56',anchor='w',justify='left',wraplength=570,font=('Microsoft YaHei',9))
  self.note.grid(row=4,column=0,columnspan=5,sticky='ew',padx=3,pady=3)
  self.bind('<Configure>',lambda e:self.note.configure(wraplength=max(180,e.width-10)))
 def update_force(self,force,state=None):
  from recruitment_summary import annual_recruitment,recruitment_text
  totals=annual_recruitment(state,force.get('force_id'))
  from preparation_model import training_bases
  from unit_target_attack import supported_combat_build
  for kind,(name,count,recruits,training,attack) in self.tiles.items():
   recruits.config(text=recruitment_text(totals[kind]))
   info=troop_info(kind,force.get('armament_raw',{}).get(kind));stock=force.get('troop_stock',{}).get(kind)
   name.config(text=info['name']);count.config(text=f'{stock:,}' if type(stock) is int else '未知')
   training.config(text=f"{info['training']} / 100" if info['training'] is not None else '未知')
   bases=training_bases(kind,force.get('armament_raw',{}).get(kind)) if supported_combat_build((state or {}).get('build_sha256')) else None
   attack.config(text=' / '.join(map(str,bases['unit'])) if bases else '未核定')
 def update_prediction(self,state,force):
  # Compatibility for older callers; this summary intentionally shows observed data only.
  pass
