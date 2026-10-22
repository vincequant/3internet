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
 def __init__(self,parent):
  super().__init__(parent,bg='#f7f4ea');self.tiles={};self.predictions={}
  for i,(kind,symbol,color) in enumerate([('infantry','盾','#617c54'),('cavalry','骑','#9b6537'),('bow','弓','#477987')]):
   tile=tk.Frame(self,bg='#eee9d9',bd=1,relief='solid');tile.grid(row=0,column=i,sticky='nsew',padx=4,pady=4);self.columnconfigure(i,weight=1,uniform='army')
   icon=tk.Canvas(tile,width=48,height=42,bg='#eee9d9',highlightthickness=0);icon.pack(pady=(7,2))
   if kind=='infantry':
    icon.create_polygon(10,5,38,5,36,25,24,37,12,25,fill=color,outline='#3b4831',width=2)
    icon.create_line(24,9,24,29,fill='#eae5ca',width=3);icon.create_line(16,17,32,17,fill='#eae5ca',width=3)
   elif kind=='cavalry':icon.create_text(24,21,text='♞',font=('Segoe UI Symbol',30),fill=color)
   else:
    icon.create_arc(7,3,37,39,start=270,extent=180,style='arc',outline=color,width=3)
    icon.create_line(22,3,22,39,fill=color);icon.create_line(6,21,43,21,fill='#55462f',width=2,arrow='last')
   name=tk.Label(tile,bg='#eee9d9',fg='#302c22',font=('Microsoft YaHei',12,'bold'));name.pack()
   count=tk.Label(tile,bg='#eee9d9',fg='#514c3b',font=('Microsoft YaHei',10));count.pack(pady=3)
   text=tk.Label(tile,bg='#eee9d9',fg=color,font=('Microsoft YaHei',10));text.pack()
   bar=ttk.Progressbar(tile,maximum=100,length=100);bar.pack(fill='x',padx=10,pady=(4,10))
   prediction=tk.Label(tile,bg='#eee9d9',fg='#6d5325',font=('Microsoft YaHei',9),justify='left',wraplength=185);prediction.pack(fill='x',padx=7,pady=(0,8));self.predictions[kind]=prediction
   self.tiles[kind]=(name,count,text,bar)
 def update_force(self,force):
  for kind,(name,count,text,bar) in self.tiles.items():
   info=troop_info(kind,force.get('armament_raw',{}).get(kind));stock=force.get('troop_stock',{}).get(kind)
   name.config(text=info['name']);count.config(text='库存 '+(f'{stock:,}' if isinstance(stock,int) else '未知'))
   value=info['training'];text.config(text='训练度 '+(str(value)+' / 100' if value is not None else '未知'));bar['value']=value or 0

 def update_prediction(self,state,force):
  from training_prediction import force_predictions,describe_prediction
  predictions=force_predictions(state,force)
  for kind,label in self.predictions.items():label.config(text=describe_prediction(kind,predictions[kind]))
