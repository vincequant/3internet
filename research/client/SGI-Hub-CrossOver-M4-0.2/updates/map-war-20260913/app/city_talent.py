"""City talent concentration using all live wild officers, without reference filters."""
import math
import tkinter as tk
from tkinter import ttk
from wild_locations import wild_location_groups
THRESHOLDS=(450,400,350)
KEYS=('lead','war','intel','pol','cha')
def summarize(state):
 entities=state.get('entities',{});wild,hidden=wild_location_groups(state)
 cities=entities.get('cities_and_barriers',[]);ids=[c.get('city_id') for c in cities]
 unique={i for i in ids if i is not None and ids.count(i)==1};groups={i:[] for i in unique};unlocated=0
 for g in wild:
  cid=g.get('location_city_id')
  if cid in groups:groups[cid].append(g)
  else:unlocated+=1
 forces={f['force_id']:f.get('name','未知') for f in entities.get('lords',[])};rows=[]
 for c in cities:
  if c.get('city_id') not in unique or c.get('type')=='barrier':continue
  gs=groups[c['city_id']];totals=[]
  for g in gs:
   a=g.get('attributes',{})
   if all(type(a.get(k)) in (int,float) and math.isfinite(a[k]) and a[k]>=0 for k in KEYS):totals.append(sum(a[k] for k in KEYS))
  row={'city':c,'name':c.get('name','?'),'owner':forces.get(c.get('owner_raw'),'无主/未知'),'total':len(gs),'unknown':len(gs)-len(totals),'max':max(totals) if totals else None}
  for t in THRESHOLDS:
   n=sum(v>t for v in totals);row[f'n{t}']=n;row[f'p{t}']=100*n/len(gs) if gs else None;row[f'g{t}']=100*n/len(wild) if wild else None
  rows.append(row)
 return rows,{'total':len(wild),'unlocated':unlocated,'hidden_barriers':len(hidden)}
COLS=[('name','城池',85),('owner','势力',60),('total','在野总数',85)]
for t in THRESHOLDS:COLS.extend([(f'n{t}',f'>{t}人数',80),(f'p{t}','占本城%',85),(f'g{t}','占全图%',85)])
COLS.extend([('max','最高五维',90),('unknown','属性缺失',85)])
class CityTalent(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={};self.order=('n450',True);self.busy=False
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=8,pady=6)
  tk.Label(bar,text='优先比较',bg='#f7f4ea').pack(side='left');self.threshold=tk.StringVar(value='450')
  box=ttk.Combobox(bar,textvariable=self.threshold,values=['450','400','350'],width=5,state='readonly');box.pack(side='left',padx=6);box.bind('<<ComboboxSelected>>',self.change_threshold)
  tk.Label(bar,text='城池 / 势力',bg='#f7f4ea').pack(side='left');self.query=tk.StringVar();tk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=6);self.query.trace_add('write',lambda *_:self.refresh())
  self.note=tk.Label(self,bg='#f7f4ea',fg='#675937',anchor='w',justify='left',wraplength=1050);self.note.pack(fill='x',padx=8,pady=4)
  box=tk.Frame(self);box.pack(fill='both',expand=True);self.tree=ttk.Treeview(box,columns=[k for k,_,_ in COLS],show='headings')
  for k,title,width in COLS:self.tree.heading(k,text=title,command=lambda key=k:self.sort(key));self.tree.column(k,width=width,stretch=False)
  y=ttk.Scrollbar(box,command=self.tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);x.pack(side='bottom',fill='x');y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.locate)
 def change_threshold(self,_=None):self.order=('n'+self.threshold.get(),True);self.refresh()
 def sort(self,key):self.order=(key,not self.order[1] if self.order[0]==key else True);self.refresh()
 def refresh(self):
  if not self.app.doc:return
  rows,meta=summarize(self.app.doc);q=self.query.get().strip().lower();rows=[r for r in rows if not q or q in (r['name']+' '+r['owner']).lower()]
  key,reverse=self.order
  def value(r):return (r[key] is not None,r[key] if r[key] is not None else 0,r['n400'],r['n350'],r['max'] or 0)
  rows.sort(key=value,reverse=reverse)
  self.note.configure(text=f"全图在野 {meta['total']} 人 · 已隐藏关隘 {meta['hidden_barriers']} 人 · 所在城未确认 {meta['unlocated']} 人。严格大于阈值；三档累计统计，不相加。\n占本城＝该档人数÷本城全部在野；占全图＝该档人数÷排除关隘后的全图在野。不受技能/资料匹配过滤影响。点列头排序，点城池查看周边。")
  self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={}
  for i,row in enumerate(rows):
   vals=['—' if row[k] is None else f'{row[k]:.1f}%' if k.startswith(('p','g')) else row[k] for k,_,_ in COLS]
   self.tree.insert('','end',iid=str(i),values=vals);self.rows[str(i)]=row
  self.busy=False
 def locate(self,_=None):
  ids=self.tree.selection()
  if not self.busy and ids and ids[0] in self.rows:self.app.locate_object('cities',self.rows[ids[0]]['city'])
