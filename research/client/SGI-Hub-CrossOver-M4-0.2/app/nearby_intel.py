"""Read-only union of objects near player cities/units, using coordinate distance."""
import tkinter as tk
from tkinter import ttk
from unit_proximity import player_id,xy
from map_unit_labels import unit_label
from unit_memory import memory_line
from force_relations import unit_row_tags, WAR_UNIT_TAG, WAR_UNIT_FOREGROUND
from officer_sortie import AMBUSH_INK, unit_has_ambush
TYPES={'field_units':('部队','unit_id'),'cities_and_barriers':('城关','city_id'),'production_buildings':('建筑','object_id_candidate'),'traps':('陷阱','trap_id')}
NAMES={'parade_ground':'练兵所','horse_farm':'牧场','bow_studio':'弓工坊'}
def collect_nearby(state,radius=5,origin_mode='城池＋部队',legacy_id=None):
 fid=player_id(state,legacy_id);entities=state.get('entities',{});origins=[]
 if fid is None:return [],'我方势力尚未确认'
 for source in ('cities_and_barriers','field_units'):
  if origin_mode=='仅城池' and source=='field_units' or origin_mode=='仅部队' and source=='cities_and_barriers':continue
  for r in entities.get(source,[]):
   if r.get('owner_raw')==fid and xy(r) is not None:origins.append((source,r))
 if not origins:return [],'没有可定位的我方城池或部队'
 rows=[];seen=set()
 for source,(kind,idkey) in TYPES.items():
  for r in entities.get(source,[]):
   p=xy(r)
   if p is None:continue
   distance,origin_source,origin=min((max(abs(p[0]-xy(o)[0]),abs(p[1]-xy(o)[1])),s,i) for i,(s,o) in enumerate(origins))
   if distance>radius:continue
   identity=(source,r.get('type'),r.get(idkey)) if r.get(idkey) is not None else (source,'index',r.get('container_index'),tuple(p))
   if identity in seen:continue
   seen.add(identity);o=origins[origin][1]
   origin_name=o.get('name') or (o.get('unit_kind','部队')+' #'+str(o.get('unit_id','?')))
   name=r.get('name') or r.get('trap_kind') or NAMES.get(r.get('type')) or r.get('unit_kind',kind)
   detail=(unit_label(state,r)+' · '+memory_line(r)) if source=='field_units' else ('建筑值 '+str(r.get('building_ui_amount','未采集')) if source=='production_buildings' else '')
   rows.append({'source':source,'kind':kind,'record':r,'name':name,'distance':distance,'origin':origin_name,'detail':detail,'own':r.get('owner_raw')==fid})
 rows.sort(key=lambda r:(not r['own'],r['distance'],r['kind'],r['name']))
 return rows,f'以 {len(origins)} 个我方城池/部队为中心 · 坐标距离≤{radius}格；不是行军距离或真实视野'
def warning_level(rows):
 distances=[r['distance'] for r in rows if not r['own']]
 return 'red' if any(d<=5 for d in distances) else 'yellow' if any(d<=10 for d in distances) else 'normal'

class NearbyIntel(tk.Frame):
 def __init__(self,parent,app,legacy_id=None):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.legacy_id=legacy_id;self.rows={};self.busy=False
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=8,pady=6)
  self.radius=tk.StringVar(value='15');self.origins=tk.StringVar(value='城池＋部队')
  for var,values,width in [(self.radius,['5','10','15'],5),(self.origins,['城池＋部队','仅城池','仅部队'],13)]:
   box=ttk.Combobox(bar,textvariable=var,values=values,state='readonly',width=width);box.pack(side='left',padx=4);box.bind('<<ComboboxSelected>>',lambda _=None:self.refresh())
  self.filters={k:tk.BooleanVar(value=k not in ('cities_and_barriers','production_buildings')) for k in TYPES}
  for source,(name,_) in TYPES.items():tk.Checkbutton(bar,text=name,variable=self.filters[source],command=self.refresh,bg='#f7f4ea').pack(side='left')
  self.note=tk.Label(self,bg='#f7f4ea',anchor='w',wraplength=1050);self.note.pack(fill='x',padx=8)
  columns=[('kind','类型',60),('name','名称',95),('owner','势力',70),('distance','最近距离',85),('origin','最近我方城池/部队',160),('xy','坐标',80),('detail','部队 / 建筑信息',470)]
  box=tk.Frame(self);box.pack(fill='both',expand=True);self.tree=ttk.Treeview(box,columns=[c[0] for c in columns],show='headings')
  for k,title,width in columns:self.tree.heading(k,text=title);self.tree.column(k,width=width,stretch=False)
  y=ttk.Scrollbar(box,command=self.tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);x.pack(side='bottom',fill='x');y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  for tag,color in [('own','#d7efdc'),('near','#f8d6d3'),('middle','#fff0bd')]:self.tree.tag_configure(tag,background=color)
  self.tree.tag_configure(WAR_UNIT_TAG,foreground=WAR_UNIT_FOREGROUND)
  self.tree.tag_configure('ambush_text',foreground=AMBUSH_INK)
  self.tree.bind('<Double-1>',self.locate)
 def refresh(self):
  if not self.app.doc:return
  rows,note=collect_nearby(self.app.doc,int(self.radius.get()),self.origins.get(),self.legacy_id);rows=[r for r in rows if self.filters[r['source']].get()]
  forces={f['force_id']:f.get('name','未知') for f in self.app.doc['entities'].get('lords',[])}
  self.note.configure(text=note+f' · 显示 {len(rows)} 项（去重）');self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={}
  for i,row in enumerate(rows):
   r=row['record'];tag='own' if row['own'] else 'near' if row['distance']<=5 else 'middle' if row['distance']<=10 else ''
   tags=unit_row_tags(self.app.doc,r,row['source'],tag)
   if row['source']=='field_units' and unit_has_ambush(self.app.doc,r):tags=tags+('ambush_text',)
   self.tree.insert('','end',iid=str(i),values=(row['kind'],row['name'],forces.get(r.get('owner_raw'),'无主/未知'),row['distance'],row['origin'],str(xy(r)),row['detail']),tags=tags);self.rows[str(i)]=row
  self.busy=False
  self.update_warning(rows)
 def update_warning(self,rows):
  from datetime import datetime,timezone
  from PIL import Image,ImageDraw,ImageTk
  from force_card_art import load_font
  level=warning_level(rows)
  try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(self.app.doc['capture_end'])).total_seconds()
  except (KeyError,TypeError,ValueError):age=999
  if age>5 or age<0:level='stale'
  if getattr(self,'warning_state',None)==level:return
  self.warning_state=level
  if level=='normal':self.app.workspace.tab(self,text='附近情报',image='');return
  color={'red':'#c32620','yellow':'#b18400','stale':'#77746b'}[level]
  title='附近情报 · '+{'red':'警','yellow':'注意','stale':'旧数据'}[level]
  font=load_font(16);box=font.getbbox(title);image=Image.new('RGBA',(box[2]-box[0]+8,24),(0,0,0,0));draw=ImageDraw.Draw(image);draw.text((4-box[0],(24-(box[3]-box[1]))/2-box[1]),title,font=font,fill=color)
  self.warning_image=ImageTk.PhotoImage(image,master=self.app.root);self.app.workspace.tab(self,text='',image=self.warning_image)
 def locate(self,_=None):
  ids=self.tree.selection()
  if self.busy or not ids or ids[0] not in self.rows:return
  row=self.rows[ids[0]];key={'cities_and_barriers':'cities','production_buildings':'buildings','field_units':'field_units','traps':'traps'}[row['source']]
  self.app.locate_object(key,row['record'])
