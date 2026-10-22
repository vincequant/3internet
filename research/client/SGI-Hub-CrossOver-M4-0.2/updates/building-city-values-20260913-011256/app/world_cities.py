"""All-city overview, independent of selected force."""
import tkinter as tk
from tkinter import ttk
from tutorial_rules import city_economy
from city_tactical import nearby,city_alert
COLS=[('name','城关',85),('traps','周边陷阱',135),('owner','势力',70),('population','人口',100),('gold','春金毛收入≈',115),('rice','秋粮毛收入≈',115),('barracks','周边兵营等级',140),('other','周边牧场 / 弓工坊',180),('defense','防御',80),('development','开发',65),('commerce','商业',65),('xy','坐标',85)]
def city_values(state,c):
 force=next((f for f in state['entities'].get('lords',[]) if f.get('force_id')==c.get('owner_raw')),{})
 economy=city_economy(c,force) if c.get('type')=='city' else None
 def levels(kind):
  if 'production_buildings' not in state['entities']:return '未采集'
  bs=[b for b in nearby(state,c,3)['buildings'] if b.get('type')==kind]
  if not bs:return '未观察到'
  return ' / '.join(str(b['level'])+'级' if type(b.get('level')) is int else '等级未解析' for b in bs)
 value=lambda v:'未知' if v is None else f'{v:,}' if isinstance(v,int) else v
 return (c.get('name','?'),city_alert(state,c)[0],force.get('name','无主/未知'),value(c.get('population')),
  round(economy['gold'],1) if economy else '未知',round(economy['rice'],1) if economy else '未知',levels('parade_ground'),levels('horse_farm')+' / '+levels('bow_studio'),value(c.get('defense')),value(c.get('development')),value(c.get('commerce')),str(c.get('world_xy_raw')))
class WorldCities(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={};self.order=None;self.busy=False
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=8,pady=6)
  tk.Label(bar,text='城关 / 势力 / 坐标',bg='#f7f4ea').pack(side='left');self.query=tk.StringVar();tk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=8);self.query.trace_add('write',lambda *_:self.refresh())
  tk.Label(self,text='春金、秋粮为毛收入参考；建筑与陷阱按城周坐标3格列出，不代表已确认归属本城。点击城关查看周边。',bg='#f7f4ea',anchor='w',wraplength=1050).pack(fill='x',padx=8)
  box=tk.Frame(self);box.pack(fill='both',expand=True);self.tree=ttk.Treeview(box,columns=[c[0] for c in COLS],show='headings')
  y=ttk.Scrollbar(box,command=self.tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);x.pack(side='bottom',fill='x');y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  for key,title,width in COLS:self.tree.column(key,width=width,stretch=False);self.tree.heading(key,text=title,command=lambda k=key:self.sort(k))
  self.tree.tag_configure('trap',background='#f8d6d3',foreground='#8f231f');self.tree.bind('<<TreeviewSelect>>',self.locate)
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
