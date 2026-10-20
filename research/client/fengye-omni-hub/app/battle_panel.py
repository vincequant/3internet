"""World proximity list and live two-unit tactical scene."""
import tkinter as tk
from tkinter import ttk
from battle_model import battle_candidates,freshness,game_session
from city_tactical import CityTactical,fmt
from unit_memory import memory_line
from battle_colors import owner_style,city_caption,ColoredBattleCells
BG='#f7f4ea';FG='#302c22'

class BattleMap(CityTactical):
 def __init__(self,parent):self.pair_ids=();super().__init__(parent,legacy_id=None)
 def draw(self):
  super().draw()
  points={}
  for x,y,iid in self.hit_points:
   kind,row,_=self.items[iid]
   if kind=='部队' and row.get('unit_id') in self.pair_ids:points[row['unit_id']]=(x,y)
  for tag,uid,color in zip(('A','B'),self.pair_ids,('#ffe366','#ff7965')):
   if uid in points:
    x,y=points[uid];self.canvas.create_oval(x-30,y-31,x+30,y+20,outline=color,width=4,tags='battle_focus');self.canvas.create_text(x,y-43,text=tag+' #'+str(uid),fill=color,font=('Microsoft YaHei',12,'bold'),tags='battle_focus')
  if len(points)==2:
   a,b=[points[k] for k in self.pair_ids];self.canvas.create_line(*a,*b,fill='#ffb65e',width=2,dash=(5,4),tags='battle_pair_link')

class BattleScene(tk.Toplevel):
 def __init__(self,root):
  super().__init__(root);self.configure(bg=BG);self.geometry('1320x900');self.minsize(1000,720);self.session=None;self.key=None
  self.banner=tk.Label(self,bg=BG,fg=FG,font=('Microsoft YaHei',13,'bold'),anchor='w');self.banner.pack(fill='x',padx=10,pady=6)
  row=tk.Frame(self,bg=BG);row.pack(fill='x',padx=8);self.sides=[];self.side_titles=[]
  for i in range(2):
   group=tk.Frame(row,bg=BG);group.grid(row=0,column=i,sticky='nsew',padx=3)
   title=tk.Label(group,anchor='w',padx=8,font=('Microsoft YaHei',12,'bold'));title.pack(fill='x');self.side_titles.append(title)
   cell=tk.Label(group,bg='#eee9d9',fg=FG,justify='left',anchor='nw',padx=8,pady=5,font=('Microsoft YaHei',10),wraplength=610);cell.pack(fill='both',expand=True);row.columnconfigure(i,weight=1,uniform='sides');self.sides.append(cell)
  row.bind('<Configure>',lambda e:[c.configure(wraplength=max(250,e.width//2-25)) for c in self.sides])
  self.city_owner=tk.Label(self,anchor='w',padx=10,font=('Microsoft YaHei',11,'bold'));self.city_owner.pack(fill='x',padx=10,pady=4)
  self.map=BattleMap(self);self.map.pack(fill='both',expand=True)
 def show(self,state,battle):
  self.session=game_session(state);self.key=battle['key'];self.update_battle(state,battle);self.deiconify();self.lift()
 def update_battle(self,state,battle):
  if game_session(state)!=self.session:self.end('对局已改变，请重新选择战役');return
  if battle is None:self.end('该组部队已不满足5格条件，或对象已消失；请在战役列表重新选择');return
  a,b=battle['a'],battle['b'];self.title(battle['name']+' · '+battle['force_a']+' / '+battle['force_b'])
  self.banner.config(text=f"{battle['name']} · 相距 {battle['distance']} 格 · {freshness(state)} · 是否交战未核实")
  city=battle.get('city');fg,bg=owner_style(state,(city or {}).get('owner_raw'));self.city_owner.config(text='最近城关：'+city_caption(state,city),fg=fg,bg=bg)
  for tag,unit,force,title in zip(('A','B'),(a,b),(battle['force_a'],battle['force_b']),self.side_titles):
   fg,bg=owner_style(state,unit.get('owner_raw'));title.config(text=tag+' · '+force,fg=fg,bg=bg)
  generals={}
  for g in state['entities'].get('generals',[]):generals.setdefault(g.get('general_id_raw'),[]).append(g)
  for tag,unit,force,label in zip(('A','B'),(a,b),(battle['force_a'],battle['force_b']),self.sides):
   names=[]
   for gid in unit.get('general_ids',[]):
    if gid is None:continue
    gs=generals.get(gid,[]);names.append(gs[0].get('name','?') if len(gs)==1 else 'ID'+str(gid)+'待核')
   label.config(text=f"{tag} · {force} · {unit.get('unit_kind','部队')} #{unit['unit_id']} · {' / '.join(names)}\n{memory_line(unit)}\n编组战力 {fmt(unit.get('basic_combat_power'))}\n技能资料：{unit.get('unit_skills_reference','未匹配')}")
  self.map.pair_ids=(a['unit_id'],b['unit_id']);self.map.radius.set('5')
  if self.map.city is None or self.map.city.get('unit_id')!=a['unit_id']:self.map.focus_unit(state,a)
  else:self.map.update_state(state)
 def end(self,message):
  self.banner.config(text=message);self.map.clear(message)
  for c in self.sides:c.config(text='当前对阵已失效')
  for c in self.side_titles+[self.city_owner]:c.config(text='',fg=FG,bg=BG)

class BattlePanel(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.rows={};self.scene=None;self.busy=False;self.session=None
  self.heading=tk.Label(self,bg=BG,fg=FG,anchor='w');self.heading.pack(fill='x',padx=10,pady=6)
  self.query=tk.StringVar();bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=8,pady=4);tk.Label(bar,text='城市 / 势力 / 部队',bg=BG,fg=FG).pack(side='left');tk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True);self.query.trace_add('write',lambda *_:self.refresh())
  self.tree=app.tree(self,[('name','战场点',160),('city','最近城关 / 占领势力',175),('city_distance','距城中心≈',95),('force_a','A势力',75),('a','A部队',135),('force_b','B势力',75),('b','B部队',135),('distance','相距格数',80),('xy','战场中点',100),('status','判定依据',220)])
  self.colored_cells=ColoredBattleCells(self.tree,lambda:self.app.doc)
  self.tree.bind('<Double-1>',lambda _=None:self.open_scene(force=True))
  tk.Label(self,text='双击一行打开双方部队、原版地形与周边对象。按坐标切比雪夫距离≤5格筛选不同势力；这是近距离对阵候选，不是已解析的战争关系、攻击范围或战斗录像。同一区域有多组部队时逐对列出。',bg=BG,fg='#786e56',wraplength=1100,justify='left',anchor='w').pack(fill='x',padx=10,pady=6)
 def refresh(self):
  s=self.app.doc
  if not s:return
  current=game_session(s);changed=current!=self.session;self.session=current
  battles=battle_candidates(s);all_rows={r['key']:r for r in battles};query=self.query.get().strip().lower()
  selected=self.tree.selection();old=selected[0] if selected and not changed else None;self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={}
  for row in battles:
   a,b=row['a'],row['b'];v=(row['name'],city_caption(s,row['city']),row['city_distance'] if row['city_distance'] is not None else '未知',row['force_a'],f"{a.get('unit_kind','部队')} #{a['unit_id']}",row['force_b'],f"{b.get('unit_kind','部队')} #{b['unit_id']}",row['distance'],str(row['midpoint']),row['status'])
   if query and not any(query in str(x).lower() for x in v):continue
   self.rows[row['key']]=row;self.tree.insert('','end',iid=row['key'],values=v)
  self.colored_cells.rows=self.rows;self.colored_cells.schedule()
  if old in self.rows:self.tree.selection_set(old)
  self.busy=False;self.heading.config(text=f"{freshness(s)} · 发现 {len(battles)} 组战役候选 / 当前显示 {len(self.rows)} 组")
  if self.scene is not None and self.scene.winfo_exists():self.scene.update_battle(s,all_rows.get(self.scene.key))
 def open_scene(self,event=None,force=False):
  if self.busy:return
  selected=self.tree.selection();row=self.rows.get(selected[0]) if selected else None
  if row is None:return
  if self.scene is None or not self.scene.winfo_exists():self.scene=BattleScene(self.app.root)
  elif self.scene.key==row['key'] and self.scene.session==game_session(self.app.doc) and not force:return
  self.scene.show(self.app.doc,row)
