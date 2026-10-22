"""Automatic current-force tutorial estimates and hand/actor comparison."""
import tkinter as tk
from tkinter import ttk
import webbrowser
from urllib.parse import quote
from tutorial_rules import RULES,CARD_POINTS,force_economy,diplomacy_score
from officer_reference import officer_metrics
from unit_proximity import player_id
from PIL import Image,ImageTk
BG='#f7f4ea';FG='#302c22'
def label(p,text='',**kw):return tk.Label(p,text=text,bg=BG,fg=FG,justify='left',anchor='w',**kw)
class RulesPanel(tk.Frame):
 def __init__(self,parent,app,legacy_id=None):
  super().__init__(parent,bg=BG);self.app=app;self.legacy_id=legacy_id;self.sides={};self.state=None;self.target_force_id=None;self.card_images={}
  tk.Button(self,text='打开完整外交对比页',command=lambda:app.workspace.select(self.diplomacy_page),bg=BG,fg=FG).pack(fill='x',padx=8,pady=5)
  self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True)
  econ=tk.Frame(self.tabs,bg=BG);book=tk.Frame(self.tabs,bg=BG)
  for w,n in [(econ,'当前势力 · 收支预估'),(book,'七篇规则与限制')]:self.tabs.add(w,text=n)
  from strategy_reference import StrategyReference
  self.strategy=StrategyReference(self.tabs,app);self.tabs.add(self.strategy,text='战场计谋 · 攻略参考')
  self.econ_summary=label(econ,wraplength=980);self.econ_summary.pack(fill='x',padx=8,pady=8)
  self.econ_tree=app.tree(econ,[('city','城市',90),('cap','首都',55),('gold','春金毛收入≈',115),('rice','秋粮毛收入≈',115),('recruit','人口募兵上限≈',120)])
  label(econ,'按当前核心属性假设保持至结算；连线、取整、俸禄结算时机与其他支出未完全确认，不称净收入。',wraplength=950).pack(fill='x',padx=8)
  self.diplomacy_page=tk.Frame(app.workspace,bg=BG);app.workspace.add(self.diplomacy_page,text='外交对比 · 手牌计算')
  header=tk.Frame(self.diplomacy_page,bg=BG);header.pack(fill='x',padx=14,pady=(12,6))
  label(header,'外交点数对比',font=(app.face,18,'bold')).pack(side='left')
  tk.Button(header,text='返回势力手牌',command=lambda:app.workspace.select(app.force_page),bg=BG,fg=FG).pack(side='right')
  label(header,'对方势力：').pack(side='left',padx=(24,4))
  self.opponent_var=tk.StringVar();self.opponent_combo=ttk.Combobox(header,textvariable=self.opponent_var,state='readonly',width=16);self.opponent_combo.pack(side='left');self.opponent_combo.bind('<<ComboboxSelected>>',self.choose_opponent)
  self.opponent_options={}
  self.comparison=label(self.diplomacy_page,wraplength=900,font=(app.face,13,'bold'),padx=12,pady=10,relief='groove',bd=1);self.comparison.pack(fill='x',padx=14,pady=6)
  shell=tk.Frame(self.diplomacy_page,bg=BG);shell.pack(fill='both',expand=True,padx=8,pady=4)
  self.dip_canvas=tk.Canvas(shell,bg=BG,highlightthickness=0);scroll=ttk.Scrollbar(shell,orient='vertical',command=self.dip_canvas.yview);scroll.pack(side='right',fill='y');self.dip_canvas.pack(side='left',fill='both',expand=True);self.dip_canvas.configure(yscrollcommand=scroll.set)
  dip=tk.Frame(self.dip_canvas,bg=BG);self.dip_window=self.dip_canvas.create_window((0,0),window=dip,anchor='nw')
  dip.bind('<Configure>',lambda _:self.dip_canvas.configure(scrollregion=self.dip_canvas.bbox('all')))
  self.dip_canvas.bind('<Configure>',self.resize_diplomacy)
  self.diplomacy_tab=dip
  self.context=label(dip,wraplength=980);self.context.pack(fill='x',padx=8,pady=5)
  sides=tk.Frame(dip,bg=BG);sides.pack(fill='x')
  for index,key in enumerate(('own','other')):
   box=tk.LabelFrame(sides,text='我方 · 主动提案' if key=='own' else '所选势力 · 被动回应',bg=BG,fg=FG);box.grid(row=0,column=index,sticky='nsew',padx=5);sides.columnconfigure(index,weight=1,uniform='diplomacy')
   total=label(box,'等待计算',font=(app.face,17,'bold'),wraplength=360);total.pack(fill='x',padx=8,pady=8)
   actor=tk.StringVar();combo=ttk.Combobox(box,textvariable=actor,state='disabled',width=30);combo.pack(fill='x',padx=5,pady=4);combo.bind('<<ComboboxSelected>>',lambda _:self.compare())
   main=tk.StringVar();primary=ttk.Combobox(box,textvariable=main,state='readonly',width=30);primary.pack(fill='x',padx=5,pady=4);primary.bind('<<ComboboxSelected>>',lambda _:self.compare())
   label(box,'点卡面选主卡（金框）；勾选补点卡（绿框）。',wraplength=360).pack(fill='x',padx=5)
   vars=[];checks=[];buttons=[];captions=[]
   hand=tk.Frame(box,bg=BG);hand.pack(fill='x',padx=4,pady=6)
   for i in range(5):
    cell=tk.Frame(hand,bg=BG,width=60,height=160);cell.grid(row=0,column=i,sticky='nsew',padx=2);cell.pack_propagate(False);hand.columnconfigure(i,weight=1,uniform='cards')
    button=tk.Button(cell,text='未采集',command=lambda k=key,n=i:self.select_card_face(k,n),bg='#eee9d9',fg=FG,activebackground='#f4df96',relief='raised',bd=2,highlightthickness=2,highlightbackground='#b4aa8c',padx=0,pady=2,font=(app.face,9),wraplength=56);button.pack(fill='x');buttons.append(button)
    caption=label(cell,'等待手牌',font=(app.face,9),wraplength=60);caption.pack(fill='x',pady=2);captions.append(caption)
    v=tk.BooleanVar(value=False);check=tk.Checkbutton(cell,text='补点',variable=v,command=self.compare,bg=BG,fg=FG,selectcolor='#eee9d9',anchor='w',font=(app.face,9),padx=0);check.pack(fill='x');vars.append(v);checks.append(check)
   score=label(box,wraplength=440);score.pack(fill='x',padx=5,pady=5)
   self.sides[key]={'actor':actor,'combo':combo,'main':main,'primary':primary,'vars':vars,'checks':checks,'card_buttons':buttons,'card_captions':captions,'score':score,'total':total,'box':box,'signature':None,'actors':{},'primaries':{},'cards':[]}

  self.dip_note=label(dip,'仅预览，不出牌。候选使者按现有属将列出，出征/受伤/可接见状态需在游戏确认；技能来自五维一致的网站资料。',wraplength=980);self.dip_note.pack(fill='x',padx=8,pady=8)
  self.rule=tk.StringVar(value='外交卡片');c=ttk.Combobox(book,textvariable=self.rule,values=list(RULES),state='readonly');c.pack(anchor='w',padx=8,pady=5);c.bind('<<ComboboxSelected>>',lambda _:self.show_rule())
  self.rule_text=label(book,wraplength=950);self.rule_text.pack(fill='x',padx=8,pady=8)
  tk.Button(book,text='打开这篇原始攻略',command=lambda:webbrowser.open('https://sanguoyouxi.vip/xsjc/'+quote(self.rule.get())+'.htm'),bg=BG,fg=FG).pack(anchor='w',padx=8)
  self.show_rule()
 def resize_diplomacy(self,event):
  self.dip_canvas.itemconfigure(self.dip_window,width=event.width)
  self.comparison.configure(wraplength=max(300,event.width-40))
  self.context.configure(wraplength=max(300,event.width-32));self.dip_note.configure(wraplength=max(300,event.width-32))
  for d in self.sides.values():
   d['score'].configure(wraplength=max(200,event.width//2-42));d['total'].configure(wraplength=max(200,event.width//2-42))
 def choose_opponent(self,_=None):
  fid=self.opponent_options.get(self.opponent_var.get())
  if fid is None:return
  self.target_force_id=fid;self.app.sel=fid;self.refresh()
 def show_rule(self):self.rule_text.config(text=RULES[self.rule.get()])
 def refresh(self):
  s=self.app.doc
  if not s:return
  self.state=s;forces=s['entities']['lords'];f=next((x for x in forces if x['force_id']==self.app.sel),None)
  if not f:return
  e=force_economy(s,f);self.econ_tree.delete(*self.econ_tree.get_children())
  for c,r in e['rows']:
   self.econ_tree.insert('','end',values=(c['name'],'是' if r and r['capital'] else '否',*(round(r[k],1) if r else '未知' for k in ('gold','rice','recruit_cap'))))
  gold=f.get('gold');rice=f.get('rice');fmt=lambda v:'未知' if v is None else f'{v:,.1f}'
  self.econ_summary.config(text=f"{f['name']} · 春金毛收入≈{e['gold']:,.1f} / 秋粮毛收入≈{e['rice']:,.1f}；缺字段城{e['missing']}座\n已读属将俸禄候选：金{fmt(e['salary_gold'])} / 粮{fmt(e['salary_rice'])}（不可直接相减当净收入）\n卖一半米：约得金{fmt(rice/10 if isinstance(rice,(int,float)) else None)}；若供养皇帝，费用≈{fmt(min(gold/25,1000) if isinstance(gold,(int,float)) else None)}\n信用每+1：本次属性下春金约+{e['gold_per_prestige']:.1f}、秋粮约+{e['rice_per_prestige']:.1f}。施舍+5至10，迁都-30。")
  own=player_id(s,self.legacy_id);a=next((x for x in forces if x['force_id']==own),None)
  if f['force_id']!=own:self.target_force_id=f['force_id']
  opponent=next((x for x in forces if x['force_id']==self.target_force_id and x['force_id']!=own),None)
  self.opponent_options={f"{x['name']} #{x['force_id']}":x['force_id'] for x in forces if x['force_id']!=own}
  self.opponent_combo.configure(values=list(self.opponent_options));self.opponent_var.set(next((text for text,fid in self.opponent_options.items() if opponent and fid==opponent['force_id']),''))
  self.context.config(text='我方未确认：请先确认当前控制势力。' if a is None else f"我方 {a['name']}（声望{a.get('prestige','?')}） / 对方 {opponent['name'] if opponent else '请选择势力'} · 点选主卡或勾选补点卡后自动重算。")
  self.load_side('own',a);self.load_side('other',opponent);self.compare()
 def load_side(self,key,force):
  d=self.sides[key];d['box'].configure(text=('我方 · ' if key=='own' else '对方 · ')+(force['name'] if force else '未选择')+(' · 主动提案' if key=='own' else ' · 被动回应'));cards=force.get('hand_cards',{}).get('slots',[]) if force else []
  sig=(force['force_id'] if force else None,tuple((x['slot'],x['card_id']) for x in cards),str(self.state.get('identity')),str(self.state.get('player_identity',{}).get('session_id')))
  if sig!=d['signature']:
   for v in d['vars']:v.set(False)
   d['main'].set('');d['actor'].set('');d['signature']=sig
  d['cards']=cards
  generals=[g for g in self.state['entities']['generals'] if force and g.get('owner_raw')==force['force_id']]
  generals.sort(key=lambda g:-(g.get('attributes',{}).get('pol',0)+g.get('attributes',{}).get('cha',0)))
  d['actors']={f"{g['name']} #{g['general_id_raw']} 政{g['attributes']['pol']} 魅{g['attributes']['cha']}":g for g in generals}
  d['combo'].configure(values=list(d['actors']))
  role='主动' if key=='own' else '被动'
  ranked=[]
  for text,g in d['actors'].items():
   result=diplomacy_score(g,[{'slot':1,'card_id':26,'name':'测试10点'}],role)
   if result.get('total') is not None:ranked.append((result['actor'],text))
  d['actor'].set(max(ranked)[1] if ranked else '')
  allowed=set(range(1,29)) # Point preview accepts every held card; legality is reported separately.
  d['primaries']={f"槽{c['slot']} {c['name']}":c for c in cards if c['card_id'] in allowed}
  d['primary'].configure(values=list(d['primaries']))
  if d['main'].get() not in d['primaries']:d['main'].set(next(iter(d['primaries']),''))
  for i,button in enumerate(d['card_buttons']):
   c=cards[i] if i<len(cards) else None;cid=c.get('card_id') if c else None
   icon=getattr(self.app.force_art,'icons',{}).get(cid)
   if icon is not None and cid not in self.card_images:self.card_images[cid]=ImageTk.PhotoImage(icon.resize((48,60),Image.Resampling.NEAREST),master=self.app.root)
   photo=self.card_images.get(cid)
   button.configure(image=photo or '',text='' if photo else ('空槽' if cid==0 else '无图' if c else '未采集'),state='normal' if c and cid in range(1,29) else 'disabled')
   points=CARD_POINTS.get(cid)
   d['card_captions'][i].configure(text=f"{c['name']}\n{str(points)+' 点' if points is not None else '点数未知'}" if c and cid else ('空槽' if cid==0 else '未采集'))
 def select_card_face(self,key,index):
  d=self.sides[key]
  if index>=len(d['cards']):return
  card=d['cards'][index];name=next((name for name,c in d['primaries'].items() if c['slot']==card['slot']),None)
  if name is None:return
  d['main'].set(name);d['vars'][index].set(False);self.compare()
 def style_hand(self,d,main):
  for i,button in enumerate(d['card_buttons']):
   c=d['cards'][i] if i<len(d['cards']) else None
   primary=bool(c and main and c['slot']==main['slot'])
   if primary:d['vars'][i].set(False)
   active=bool(c and c.get('card_id'))
   d['checks'][i].configure(text='主卡' if primary else '补点',state='normal' if active and not primary else 'disabled')
   color='#d6a52b' if primary else '#72a879' if d['vars'][i].get() and active else '#b4aa8c'
   button.configure(highlightbackground=color,highlightcolor=color,bg='#f4df96' if primary else '#e1eedf' if d['vars'][i].get() and active else '#eee9d9',relief='sunken' if primary else 'raised')
 def compare(self):
  results=[]
  for key in ('own','other'):
   d=self.sides[key];g=d['actors'].get(d['actor'].get());main=d['primaries'].get(d['main'].get())
   self.style_hand(d,main)
   if not g or not main:d['total'].config(text='尚不能计算');d['score'].config(text='缺少使者或可选功能卡；不能判作0点。');results.append(None);continue
   cards=[main]+[c for i,c in enumerate(d['cards']) if d['vars'][i].get() and c['slot']!=main['slot']]
   r=diplomacy_score(g,cards,'主动' if key=='own' else '被动');r['why']='已匹配技能的属将中最高；'+r['why'];d['score'].config(text=f"{r.get('total') if r.get('total') is not None else '未知'} 点 · {r['why']}")
   d['total'].config(text=f"外交力 {r['actor']} + 卡牌 {r['cards']} = {r['total']} 点" if r.get('total') is not None else '点数未确认')
   # A numeric sum does not prove blue cards are legal supplements.
   if any(c['card_id'] not in {11,12,13,14,16,17,18,19,20,23,24,25,26,27,28} for c in cards[1:]):r=dict(r,total=None,why='附加卡用途未确认')
   legal={1,2,3,4,5,6,7,11,12,13,14,15} if key=='own' else {8,9,10,11,12,13,14}
   r['preview_only']=main['card_id'] not in legal
   results.append(r)
  if all(r and r.get('total') is not None for r in results):
   delta=results[0]['total']-results[1]['total'];msg=f"我方 {results[0]['total']} vs 对方 {results[1]['total']}：点差 {delta:+}。"+('平点规则未说明。' if delta==0 else '仅所选组合点数优势，未推定对方实际出牌。')
   if any(r.get('special') for r in results):msg+='含玉玺：攻略有特殊必成描述，普通点差不作最终判定。'
   if any(r.get('preview_only') for r in results):msg+='所选含点数/特殊卡，仅预览点数，不构成合法功能牌组合。'
   self.comparison.config(text=msg+' 接见、特殊效果及随机规则不完整，不显示伪精确胜率。')
  else:self.comparison.config(text='条件不足：'+ '；'.join(r['why'] if r else '未选定使者/功能卡/我方身份' for r in results))

 def pick_card(self,force_id,slot):
  if not self.app.doc:return
  own=player_id(self.app.doc,self.legacy_id)
  if own is None:
   self.context.config(text='先确认我方势力，才能区分主动与被动外交。');return
  side='own' if force_id==own else 'other'
  if side=='other':self.target_force_id=force_id
  self.refresh();d=self.sides[side]
  chosen=next((name for name,c in d['primaries'].items() if c['slot']==slot),None)
  if chosen is None:return
  for v in d['vars']:v.set(False)
  d['main'].set(chosen);self.compare()
  self.app.workspace.select(self.diplomacy_page)
