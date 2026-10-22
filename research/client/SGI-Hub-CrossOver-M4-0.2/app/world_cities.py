"""All-city overview, independent of selected force."""
import tkinter as tk
from tkinter import ttk
from tutorial_rules import city_economy
from city_tactical import nearby,city_alert
from recruitment_summary import population_cap
COLS=[('name','城关',85),('traps','周边陷阱',135),('owner','势力',70),('infantry','可产步兵（人）',120),('cavalry','可产骑兵（人）',120),('bow','可产弓兵（人）',120),('population','人口',100),('recruit_cap','人口募兵帽',110),('gold','春金毛收入≈',115),('rice','秋粮毛收入≈',115),('defense','防御',80),('development','开发',65),('commerce','商业',65),('xy','坐标',85)]
def city_values(state,c):
 force=next((f for f in state['entities'].get('lords',[]) if f.get('force_id')==c.get('owner_raw')),{})
 economy=city_economy(c,force) if c.get('type')=='city' else None
 def amounts(kind):
  if c.get('type')!='city':return '不适用'
  result=c.get('recruitment_capacity') or {}
  v=(result.get('amounts') or {}).get(kind)
  return v if type(v) is int else '未采集'
 value=lambda v:'未知' if v is None else f'{v:,}' if isinstance(v,int) else v
 cap=(c.get('recruitment_capacity') or {}).get('population_cap')
 if cap is None and c.get('type')=='city':cap=population_cap(c.get('population'))
 if c.get('type')!='city':cap_text='不适用'
 elif type(cap) is int:cap_text=f'{cap:,}'
 else:cap_text='未采集'
 return (c.get('name','?'),city_alert(state,c)[0],force.get('name','无主/未知'),*(amounts(k) for k in ('infantry','cavalry','bow')),value(c.get('population')),cap_text,
  round(economy['gold'],1) if economy else '未知',round(economy['rice'],1) if economy else '未知',value(c.get('defense')),value(c.get('development')),value(c.get('commerce')),str(c.get('world_xy_raw')))
class WorldCities(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={};self.order=None;self.busy=False
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=8,pady=6)
  tk.Label(bar,text='城关 / 势力 / 坐标',bg='#f7f4ea').pack(side='left');self.query=tk.StringVar();tk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=8);self.query.trace_add('write',lambda *_:self.refresh())
  tk.Label(self,text='步/骑/弓各为该兵种单次征兵能力：各自 min(该种兵营合计, 人口帽)，互不占用。人口帽≈人口/10，人口<50000为0，最多50000；建练兵所不会减骑/弓可产。不是现有库存或每季保证收入；实际征兵时机、连线由游戏决定。春金秋粮为毛收入。双击一行打开定位小窗。',bg='#f7f4ea',anchor='w',wraplength=1050).pack(fill='x',padx=8)
  box=tk.Frame(self);box.pack(fill='both',expand=True);self.tree=ttk.Treeview(box,columns=[c[0] for c in COLS],show='headings')
  y=ttk.Scrollbar(box,command=self.tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);x.pack(side='bottom',fill='x');y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  for key,title,width in COLS:self.tree.column(key,width=width,stretch=False);self.tree.heading(key,text=title,command=lambda k=key:self.sort(k))
  self.tree.tag_configure('trap',background='#f8d6d3',foreground='#8f231f');self.tree.bind('<Double-1>',self.locate)
 def sort(self,key):
  self.order=(key,not self.order[1] if self.order and self.order[0]==key else True);self.refresh()
 def refresh(self):
  if not self.app.doc:return
  self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={};rows=[];q=self.query.get().strip().lower()
  for c in self.app.doc['entities'].get('cities_and_barriers',[]):
   v=city_values(self.app.doc,c)
   if not q or any(q in str(x).lower() for x in v):rows.append((c,v))
  if self.order:
   idx=[c[0] for c in COLS].index(self.order[0])
   def key(row):
    v=str(row[1][idx]).replace(',','')
    try:return (1,float(v))
    except ValueError:return (0,v)
   rows.sort(key=key,reverse=self.order[1])
  for i,(c,v) in enumerate(rows):self.tree.insert('','end',iid=str(i),values=v,tags=('trap',) if city_alert(self.app.doc,c)[1] else ());self.rows[str(i)]=c
  self.busy=False
 def locate(self,_=None):
  selected=self.tree.selection()
  if not self.busy and selected and selected[0] in self.rows:self.app.locate_object('cities',self.rows[selected[0]])
