"""City-centered original terrain with read-only live overlays and explicit reference vision."""
import tkinter as tk
from tkinter import ttk
from collections import Counter,defaultdict
from unit_proximity import annotate,COLORS
from tactical_terrain import Terrain,world_pixel
from PIL import ImageTk,Image,ImageDraw
BG='#f7f4ea';FG='#302c22'
BUILDINGS={'parade_ground':'练兵所（兵营）','horse_farm':'牧场','bow_studio':'弓工坊'}
def fmt(v):
 if v is None:return '未解析'
 if isinstance(v,(list,tuple)):return '/'.join(str(x) for x in v)
 return f'{v:,}' if type(v) is int else str(v)
def position(r):
 p=r.get('world_xy_raw')
 return tuple(p) if isinstance(p,(list,tuple)) and len(p)==2 and all(type(v) is int for v in p) and 0<=p[0]<101 and 0<=p[1]<202 else None

def nearby(state,city,radius=3):
 center=position(city)
 result={'traps':[],'units':[],'buildings':[],'cities':[],'known':'traps' in state.get('entities',{})}
 if center is None:return result
 for source,target in [('traps','traps'),('field_units','units'),('production_buildings','buildings'),('cities_and_barriers','cities')]:
  for r in state.get('entities',{}).get(source,[]):
   p=position(r)
   if p and max(abs(p[0]-center[0]),abs(p[1]-center[1]))<=radius:result[target].append(r)
 return result

def city_alert(state,city):
 info=nearby(state,city)
 if not info['known']:return '陷阱未采集',False
 counts=Counter(t.get('trap_kind','未知') for t in info['traps'])
 if not counts:return '附近未读到',False
 return f"有 {len(info['traps'])} 处 · "+' / '.join(f'{k}{n}' for k,n in counts.items()),True

class CityTactical(tk.Frame):
 def __init__(self,parent,legacy_id=None):
  super().__init__(parent,bg=BG);self.state=None;self.city=None;self.identity=None;self.legacy_id=legacy_id;self.selected=None;self.items={}
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=8,pady=5)
  self.heading=tk.Label(bar,text='点击城关查看周边',bg=BG,fg=FG,anchor='w');self.heading.pack(side='left',fill='x',expand=True)
  tk.Label(bar,text='半径',bg=BG,fg=FG).pack(side='left')
  self.radius=tk.StringVar(value='3');box=ttk.Combobox(bar,textvariable=self.radius,values=['3','5','10'],state='readonly',width=4);box.pack(side='left');box.bind('<<ComboboxSelected>>',lambda _:self.render())
  self.vision=tk.BooleanVar(value=False);tk.Checkbutton(bar,text='城周3格参考遮罩',variable=self.vision,command=self.draw,bg=BG,fg=FG,selectcolor=BG).pack(side='left')
  self.terrain=None;self.terrain_error='';self.bg_cache=None
  try:self.terrain=Terrain()
  except (OSError,ValueError) as error:self.terrain_error=str(error)
  self.city_summary=tk.Label(self,bg=BG,fg=FG,anchor='w',justify='left',wraplength=1080);self.city_summary.pack(fill='x',padx=8,pady=(0,5))
  body=tk.Frame(self,bg=BG);body.pack(fill='both',expand=True)
  self.canvas=tk.Canvas(body,bg='#eee8d5',highlightthickness=0,width=520);self.canvas.pack(side='left',fill='both',expand=True)
  right=tk.Frame(body,bg=BG,width=420);right.pack(side='right',fill='both')
  self.info_book=ttk.Notebook(right);self.info_book.pack(fill='both',expand=True)
  objects=tk.Frame(self.info_book,bg=BG);self.info_book.add(objects,text='周边对象')
  facts=tk.Frame(self.info_book,bg=BG);self.info_book.add(facts,text='城关资料 / 武将')
  self.facts=tk.Text(facts,wrap='word',width=38,height=18,bg=BG,fg=FG,relief='flat',padx=8,pady=8,font=('Microsoft YaHei',10));fact_scroll=ttk.Scrollbar(facts,orient='vertical',command=self.facts.yview);self.facts.configure(yscrollcommand=fact_scroll.set);fact_scroll.pack(side='right',fill='y');self.facts.pack(fill='both',expand=True)
  columns=('kind','name','pos','relative','owner')
  self.tree=ttk.Treeview(objects,columns=columns,show='headings',height=18,selectmode='browse')
  for k,text,w in zip(columns,['对象','名称 / 编将','绝对坐标','相对城心','归属'],[60,125,75,80,65]):self.tree.heading(k,text=text);self.tree.column(k,width=w,minwidth=45,stretch=True)
  scrollbar=ttk.Scrollbar(objects,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  self.detail=tk.Label(self,bg=BG,fg=FG,anchor='w',justify='left',wraplength=1020);self.detail.pack(fill='x',padx=8,pady=5)
  self.note=tk.Label(self,text='原版地形 + 实时对象位置；城关、建筑、陷阱、部队使用示意图标。全知显示不受玩家视野限制。\n遮罩仅为城周3格坐标参考，不是已解析的游戏迷雾；附近陷阱按坐标距离≤3统计，不代表都由该城建设。空表不保证安全。',bg=BG,fg='#6d6046',justify='left',anchor='w',wraplength=1020);self.note.pack(fill='x',padx=8,pady=4)
  self.bind('<Configure>',self.resize_text)
  self.canvas.bind('<Configure>',lambda _:self.draw());self.canvas.bind('<Button-1>',self.click);self.tree.bind('<<TreeviewSelect>>',self.select_row)
 def resize_text(self,event):
  if event.widget is not self:return
  for label in (self.city_summary,self.detail,self.note):label.configure(wraplength=max(300,event.width-24))
  self.heading.configure(wraplength=max(250,event.width-350))
 def focus(self,state,city):
  self.state=state;self.identity=dict(state.get('identity',{}));self.city=dict(city);self.selected=None;self.render()
 def update_state(self,state):
  self.state=state
  if self.city is None:return
  if state.get('identity')!=self.identity:self.clear('对局已变化，请重新选择城关');return
  matches=[c for c in state['entities']['cities_and_barriers'] if c.get('city_id')==self.city.get('city_id') and c.get('type')==self.city.get('type')]
  if len(matches)!=1:self.clear('原城关已消失或标识不唯一');return
  self.city=matches[0];self.render()
 def clear(self,text):
  self.city=None;self.items={};self.selected=None;self.tree.delete(*self.tree.get_children());self.canvas.delete('all');self.heading.config(text=text);self.detail.config(text='');self.city_summary.config(text='');self.set_facts('')
 def render(self):
  if not self.state or not self.city:return
  center=position(self.city)
  if center is None:self.clear('城关坐标未解析');return
  radius=int(self.radius.get());info=nearby(self.state,self.city,radius);alert,_=city_alert(self.state,self.city)
  self.heading.config(text=f"{self.city['name']} {center} · 3格内：{alert} · {radius}格内：建筑{len(info['buildings'])} / 陷阱{len(info['traps'])} / 部队{len(info['units'])}")
  annotate(self.state,self.legacy_id)
  forces={f['force_id']:f['name'] for f in self.state['entities']['lords']};generals={g['general_id_raw']:g.get('name','?') for g in self.state['entities']['generals']}
  self.refresh_city_facts(info)
  old_scroll=self.tree.yview()[0];self.items={};self.tree.delete(*self.tree.get_children());self.tree.tag_configure('trap',background='#f8d6d3',foreground='#a12318')
  for band,color in COLORS.items():self.tree.tag_configure(band,background=color,foreground=FG)
  for kind,rows in [('城关',info['cities'] or [self.city]),('建筑',info['buildings']),('陷阱',info['traps']),('部队',info['units'])]:
   for index,row in enumerate(rows):
    iid=kind+':'+str(row.get('type',''))+':'+str(row.get('address') or row.get('unit_id',row.get('city_id',row.get('trap_id',row.get('object_id_candidate',index)))));p=position(row);name=row.get('trap_kind') or row.get('name') or BUILDINGS.get(row.get('type')) or row.get('unit_kind','?')
    if kind=='部队':name+=' '+('/'.join(generals.get(g,'?') for g in row.get('general_ids',[]) if g is not None))
    if self.tree.exists(iid):iid+=':'+str(index)
    tag='trap' if kind=='陷阱' else row.get('proximity_band','')
    self.tree.insert('','end',iid=iid,values=(kind,name,f'{p[0]},{p[1]}',f'{p[0]-center[0]:+},{p[1]-center[1]:+}',forces.get(row.get('owner_raw'),'无主/未知')),tags=(tag,))
    self.items[iid]=(kind,row,name)
  if self.selected not in self.items:self.selected=None
  if self.selected:self.tree.selection_set(self.selected)
  self.tree.yview_moveto(old_scroll);self.show_detail();self.draw()
 def set_facts(self,text):
  scroll=self.facts.yview()[0];self.facts.configure(state='normal');self.facts.delete('1.0','end');self.facts.insert('1.0',text);self.facts.configure(state='disabled');self.facts.yview_moveto(scroll)
 def refresh_city_facts(self,info):
  city=self.city;forces={f['force_id']:f for f in self.state['entities'].get('lords',[])};force=forces.get(city.get('owner_raw'));owner=force.get('name') if force else '无主/未知'
  buildings=Counter(BUILDINGS.get(b.get('type'),b.get('type','未知建筑')) for b in info['buildings']);building_text=' / '.join(f'{name}{count}' for name,count in buildings.items()) or ('附近未读到' if 'production_buildings' in self.state['entities'] else '建筑未采集')
  self.city_summary.config(text=f"{owner} · 防御 {fmt(city.get('defense'))} · 人口 {fmt(city.get('population'))} · 开发 {fmt(city.get('development'))} · 商业 {fmt(city.get('commerce'))}\n附近建筑：{building_text}")
  text=f"{city.get('name','城关')} · {'城市' if city.get('type')=='city' else '关隘'}\n归属：{owner}\n城关ID：{city.get('city_id','未知')}\n坐标：{position(city)}\n防御：{fmt(city.get('defense'))}\n人口：{fmt(city.get('population'))}\n开发：{fmt(city.get('development'))}\n商业：{fmt(city.get('commerce'))}\n"
  if force:text+='首都：'+('是' if force.get('capital_city_id')==city.get('city_id') else '否')+'\n'
  text+='城内步/骑/弓兵力、城内士气：当前接口未提供；不以势力库存或武将带兵数代替。\n'
  text+='\n周边建筑（当前查看半径）\n'+building_text+'\n'
  for b in info['buildings']:
   bf=forces.get(b.get('owner_raw'),{}).get('name','无主/未知');text+=f"· {BUILDINGS.get(b.get('type'),b.get('type'))} {position(b)} · {bf}\n"
  if force and city.get('type')=='city':
   from tutorial_rules import city_economy
   econ=city_economy(city,force)
   if econ:text+=f"\n收支参考（按当前属性）\n春金毛收入 ≈ {econ['gold']:,.1f}\n秋粮毛收入 ≈ {econ['rice']:,.1f}\n人口募兵上限 ≈ {econ['recruit_cap']:,.0f}\n未扣维护与俸禄，不是净收益。\n"
  officers=[g for g in self.state['entities'].get('generals',[]) if g.get('location_city_id')==city.get('city_id') and g.get('status_code') in (0,1,4,6)]
  text+=f"\n所在地字段指向本城的武将（{len(officers)}）\n"
  for g in sorted(officers,key=lambda x:(x.get('status_code',99),x.get('name',''))):
   stats=g.get('attributes',{});text+=f"· {g.get('name','?')} · {g.get('status_label','状态未命名')} · {forces.get(g.get('owner_raw'),{}).get('name','无主/未知')}\n  统{fmt(stats.get('lead'))} 武{fmt(stats.get('war'))} 智{fmt(stats.get('intel'))} 政{fmt(stats.get('pol'))} 魅{fmt(stats.get('cha'))}\n"
  text+='\n所在地与状态沿用采集字段；排除出阵、死亡和未登场记录，不把历史城市位置当作当前驻城。建筑等级与建成状态尚未解析。'
  self.set_facts(text)
 def draw(self):
  c=self.canvas;c.delete('all');self.hit_points=[]
  if not self.city:return
  center=position(self.city);radius=int(self.radius.get());w=c.winfo_width();h=c.winfo_height()
  if w<20 or h<20:return
  cx,cy=world_pixel(*center);scale=min(w/(192*radius+192),h/(48*radius+144));scale=max(.05,scale)
  # Keep the game's 2:1 diamonds and staggered rows; never stretch the map.
  def screen(p):
   x,y=world_pixel(*p);return (w/2+(x-cx)*scale,h/2+(y-cy)*scale)
  left=int(cx-w/scale/2);top=int(cy-h/scale/2);box=(left,top,left+int(w/scale)+1,top+int(h/scale)+1)
  cache_key=(box,w,h,self.vision.get(),center)
  if self.terrain:
   if self.bg_cache is None or self.bg_cache[0]!=cache_key:
    im=self.terrain.crop(box).resize((w,h),Image.Resampling.LANCZOS)
    if self.vision.get():
     veil=Image.new('RGBA',(w,h),(15,25,22,130));d=ImageDraw.Draw(veil)
     for yy in range(max(0,center[1]-3),min(202,center[1]+4)):
      for xx in range(max(0,center[0]-3),min(101,center[0]+4)):
       x,y=screen((xx,yy));dx=48*scale;dy=24*scale
       d.polygon([(x-dx,y),(x,y-dy),(x+dx,y),(x,y+dy)],fill=(0,0,0,0))
     im=Image.alpha_composite(im.convert('RGBA'),veil)
    self.terrain_preview=im.copy();self.bg_cache=(cache_key,ImageTk.PhotoImage(im))
   c.create_image(0,0,image=self.bg_cache[1],anchor='nw',tags='terrain')
  else:
   c.create_text(w/2,20,text='底图不可用 · 保留坐标定位：'+self.terrain_error,fill=FG)
  grouped=defaultdict(list)
  for iid,(kind,row,name) in self.items.items():grouped[position(row)].append((iid,kind,row,name))
  for p,rows in sorted(grouped.items(),key=lambda item:(item[0][1],item[0][0])):
   x,y=screen(p)
   for i,(iid,kind,row,name) in enumerate(rows):
    px=x+(i-(len(rows)-1)/2)*24;sz=max(8,min(19,26*scale));self.hit_points.append((px,y,iid))
    if iid==self.selected:c.create_oval(px-25,y-25,px+25,y+25,outline='#ffef64',width=3)
    if kind=='陷阱':
     label=row['trap_kind']
     if label=='火计':
      c.create_polygon(px-sz,y+6,px-sz*.65,y-8,px-4,y-3,px+3,y-24,px+sz,y-5,px+sz*.7,y+7,fill='#ed4723',outline='#92200a',width=2,tags='trap')
      c.create_polygon(px-6,y+5,px-3,y-6,px+3,y-13,px+8,y+6,fill='#ffe055',outline='',tags='trap')
     elif label=='落石':
      for dx,dy in [(-9,3),(5,6),(0,-6)]:c.create_polygon(px+dx-9,y+dy+4,px+dx-6,y+dy-6,px+dx+2,y+dy-11,px+dx+10,y+dy+4,fill='#b6b2a0',outline='#494a3d',width=2,tags='trap')
     else:c.create_oval(px-sz,y-10,px+sz,y+9,fill='#302a20',outline='#c3b68b',width=4,tags='trap')
     color='#8f190a'
    elif kind=='建筑':
     fill={'parade_ground':'#cfb781','horse_farm':'#acc58c','bow_studio':'#a9bdc9'}.get(row.get('type'),'#c9c2ab')
     c.create_rectangle(px-14,y-8,px+14,y+9,fill=fill,outline='#494831',width=2,tags='building')
     c.create_polygon(px-20,y-8,px,y-20,px+20,y-8,fill=fill,outline='#494831',width=2,tags='building')
     c.create_line(px-9,y+10,px-9,y-4,px+9,y-4,px+9,y+10,fill='#65513a',width=2,tags='building')
     label=BUILDINGS.get(row.get('type'),'建筑');color='#344d24'
    elif kind=='城关':
     c.create_rectangle(px-17,y-10,px+17,y+8,fill='#c1a376',outline='#422c13',width=2,tags='city')
     c.create_polygon(px-28,y-10,px,y-27,px+28,y-10,px,y-3,fill='#97612d',outline='#392411',width=2,tags='city');label=row.get('name','城关');color='#423015'
    else:
     fill=row.get('proximity_color') or '#d6dce2'
     c.create_polygon(px,y-19,px-16,y+5,px+16,y+5,fill=fill,outline='#283c30',width=2,tags='unit')
     c.create_line(px+13,y-23,px+13,y+7,fill='#263222',width=2)
     c.create_polygon(px+13,y-23,px+27,y-19,px+13,y-14,fill=fill,outline='#263222',tags='unit');label=row.get('unit_kind','部队');color='#163b24'
    tid=c.create_text(px,y+21,text=label,fill=color,font=('Microsoft YaHei',9,'bold'));bounds=c.bbox(tid)
    if bounds:
     rect=c.create_rectangle(bounds[0]-2,bounds[1],bounds[2]+2,bounds[3],fill='#f7f4df',outline='');c.tag_lower(rect,tid)
  c.create_text(8,h-12,text='全知对象 · '+('参考遮罩开启' if self.vision.get() else '无遮罩'),anchor='w',fill='#fff6da',font=('Microsoft YaHei',10,'bold'))
 def select_row(self,_=None):
  selection=self.tree.selection()
  if selection:self.selected=selection[0];self.show_detail();self.draw()
 def click(self,event):
  candidates=[(x,y,iid) for x,y,iid in getattr(self,'hit_points',[]) if (x-event.x)**2+(y-event.y)**2<=30**2]
  if not candidates:return
  candidates.sort(key=lambda v:(v[0]-event.x)**2+(v[1]-event.y)**2);ids=[v[2] for v in candidates]
  iid=ids[(ids.index(self.selected)+1)%len(ids)] if self.selected in ids else ids[0]
  self.selected=iid;self.tree.selection_set(iid);self.tree.see(iid);self.show_detail();self.draw()
 def show_detail(self):
  if self.selected not in self.items:self.detail.config(text='点击图标或右侧对象，查看位置与参数；同格多对象可连续点击切换。');return
  kind,row,name=self.items[self.selected];p=position(row);text=f'{kind} · {name} · 坐标{p}'
  if kind=='部队':
   text+=f" · 兵数{row.get('soldiers_candidate','未知')} · 训练{row.get('training_degree') if row.get('training_degree') is not None else '未知'} · 编组战力{row.get('basic_combat_power','未知')} · 对部队{row.get('target_attack_unit','缺参数')} · 攻城{row.get('target_attack_building','缺参数')}\n计谋点数：{row.get('skill_points_display','未定位')} · 技能资料：{row.get('unit_skills_reference','未匹配')}\n{row.get('target_attack_note','')}"
  if kind=='城关':text+=f" · 防御 {fmt(row.get('defense'))} · 人口 {fmt(row.get('population'))} · 开发 {fmt(row.get('development'))} · 商业 {fmt(row.get('commerce'))}"
  if kind=='建筑':text+=f" · 对象ID {fmt(row.get('object_id_candidate'))} · 按实际对象坐标显示；建成状态/等级尚未解析，附近不等于归属该城"
  if kind=='陷阱':text+=' · 独立只读对象；所属城市字段尚待核定'
  self.detail.config(text=text)
