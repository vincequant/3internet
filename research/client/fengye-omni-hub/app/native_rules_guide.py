"""Evidence-backed native-rule explanations inside 攻略预判. No game actions."""
import tkinter as tk
from tkinter import ttk
from native_rules_model import BUILD,CARD_NAMES,SYNC_ROWS,RECRUIT_TEXT,CARD_TEXT,card_rows,recruit_rows,percent
BG='#f7f4ea';FG='#302c22';GOLD='#946a26';GREEN='#315447'

def label(parent,text='',**kw):return tk.Label(parent,text=text,**dict(dict(bg=BG,fg=FG,anchor='w',justify='left'),**kw))
def table(parent,columns,height=8):
 frame=tk.Frame(parent,bg=BG);frame.pack(fill='both',expand=True,padx=10,pady=6)
 tree=ttk.Treeview(frame,columns=[c[0] for c in columns],show='headings',height=height)
 for key,title,width in columns:tree.heading(key,text=title);tree.column(key,width=width,minwidth=55,stretch=True,anchor='center')
 v=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);h=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
 tree.configure(yscrollcommand=v.set,xscrollcommand=h.set);tree.grid(row=0,column=0,sticky='nsew');v.grid(row=0,column=1,sticky='ns');h.grid(row=1,column=0,sticky='ew')
 frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1);return tree

def prose(parent,lines,face,height=7):
 shell=tk.Frame(parent,bg=BG);shell.pack(fill='x',padx=10,pady=5)
 text=tk.Text(shell,height=height,wrap='word',bg=BG,fg=FG,font=(face,12),relief='flat',padx=8,pady=5)
 scroll=ttk.Scrollbar(shell,orient='vertical',command=text.yview);scroll.pack(side='right',fill='y');text.pack(fill='x',expand=True);text.configure(yscrollcommand=scroll.set)
 text.insert('1.0','\n\n'.join(lines));text.configure(state='disabled');return text

class NativeRulesGuide(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.state={};self.force_id=None;self.signature=None;self.city_options={'全部城池':None}
  label(self,'原版内藏规则 · 研究预判',font=(app.face,18,'bold'),fg=GOLD).pack(fill='x',padx=12,pady=(10,4))
  self.context=label(self,'等待快照',fg=GREEN);self.context.pack(fill='x',padx=12,pady=4)
  tabs=ttk.Notebook(self);tabs.pack(fill='both',expand=True)
  recruit=tk.Frame(tabs,bg=BG);cards=tk.Frame(tabs,bg=BG);sync=tk.Frame(tabs,bg=BG)
  for pane,name in ((recruit,'招揽 · 民望对比'),(cards,'外交手牌 · 抽取规则'),(sync,'双端同步 · 验证范围')):tabs.add(pane,text=name)
  bar=tk.Frame(recruit,bg=BG);bar.pack(fill='x',padx=10,pady=8)
  label(bar,'城池：').pack(side='left');self.city=tk.StringVar(value='全部城池');self.combo=ttk.Combobox(bar,textvariable=self.city,values=['全部城池'],state='readonly',width=20);self.combo.pack(side='left');self.combo.bind('<<ComboboxSelected>>',self.render_recruit)
  label(bar,' 统武高于：').pack(side='left');self.minimum=tk.StringVar(value='150');entry=ttk.Entry(bar,textvariable=self.minimum,width=6);entry.pack(side='left');entry.bind('<Return>',self.render_recruit);entry.bind('<FocusOut>',self.render_recruit)
  ttk.Button(bar,text='重算',command=self.render_recruit).pack(side='left',padx=8)
  self.note=label(recruit,wraplength=1100);self.note.pack(fill='x',padx=12,pady=3)
  self.tree=table(recruit,[('name','武将',100),('city','城池',85),('blade','统武',65),('pool','同城在野',85),('chance','整笔录到他≈',125),('chance200','民望200时≈',125),('threshold','轮到他/100',110),('threshold200','民望200门槛',110)])
  prose(recruit,RECRUIT_TEXT,app.face,7)
  label(recruit,'依据：原版函数隔离执行 57,201 项；普通招揽两笔双Mac结果对照。表格按整体估算概率优先、统武次序。',wraplength=1100,fg=GOLD).pack(fill='x',padx=12,pady=6)
  cbar=tk.Frame(cards,bg=BG);cbar.pack(fill='x',padx=10,pady=8)
  label(cbar,'想要的卡：').pack(side='left');self.wanted=tk.StringVar(value=CARD_NAMES['1']);wanted=ttk.Combobox(cbar,textvariable=self.wanted,values=list(CARD_NAMES.values()),state='readonly',width=24);wanted.pack(side='left');wanted.bind('<<ComboboxSelected>>',self.render_cards)
  self.card_note=label(cards,wraplength=1100,fg=GREEN);self.card_note.pack(fill='x',padx=12,pady=4)
  self.cards=table(cards,[('slot','位置（左→右）',130),('name','当前手牌',240),('seasonal','普通满手季更分类',230)],height=5)
  prose(cards,CARD_TEXT,app.face,11)
  label(cards,'依据：手牌读取已核准；原版洗牌/领取路径静态定位；DLL随机数及卡类在隔离x86进程核对。尚无强制抽卡双端实测。',wraplength=1100,fg=GOLD).pack(fill='x',padx=12,pady=6)
  self.sync=table(sync,[('feature','项目',240),('level','证据级别',180),('scope','实际范围与限制',740)])
  for row in SYNC_ROWS:self.sync.insert('','end',values=row)
  prose(sync,('大白话：两边按同一条指令、同一套规则计算，才有机会得到同一个结果。只把自己最后的数值改漂亮，对方通常仍按原版算。',
    '已经测到的“双方数值相同”，只证明那一局那一笔的结果一致；没有抓到服务端全部校验和原始网络指令，不能把它说成服务器接受任意参数。',
    '新增修改要先记录双方初值、原版指令参数和费用，再正常结束同一个内政回合，核对训练、兵数、钱粮、民望、将领归属及后续出兵。缺一端结果就保持待验证。'),app.face,6)
  label(sync,'历史来源：quick-sync-release / hub-recruit-probability / quick-sync 对照记录（2026-10-04 至 05）。',wraplength=1100,fg=GOLD).pack(fill='x',padx=12,pady=6)
 def refresh(self,state,force_id):
  self.state=state or {};self.force_id=force_id
  force=next((f for f in self.state.get('entities',{}).get('lords',[]) if f.get('force_id')==force_id),None)
  stamp=self.state.get('capture_end') or '未标时间';self.context.configure(text=f"快照势力：{force.get('name','?')} · 民望{force.get('prestige','未知')} · {stamp}" if force else '等待势力及快照；未计算未来结果')
  entities=self.state.get('entities') or {};cities=entities.get('cities_and_barriers') or [];wild={g.get('location_city_id') for g in entities.get('generals',[]) if g.get('status_code')==1}
  self.city_options={'全部城池':None}
  self.city_options.update({f"{c.get('name','?')} #{c['city_id']}":c['city_id'] for c in cities if c.get('type')=='city' and c.get('city_id') in wild})
  self.combo.configure(values=list(self.city_options))
  identity=(str(self.state.get('identity')),str(self.state.get('player_identity',{}).get('session_id')),force_id)
  if identity!=self.signature or self.city.get() not in self.city_options:self.city.set('全部城池')
  self.signature=identity;self.render_recruit();self.render_cards()
 def render_recruit(self,_=None):
  self.tree.delete(*self.tree.get_children())
  try:
   limit=int(self.minimum.get()) if self.minimum.get().strip() else None
   if limit is not None and not 0<=limit<=510:raise ValueError()
  except ValueError:self.note.configure(text='统武门槛请输入0至510的整数；留空显示全部。');return
  rows,reason=recruit_rows(self.state,self.force_id,self.city_options.get(self.city.get()),limit)
  for r in rows:self.tree.insert('','end',values=(r['name'],r['city'],r['blade'] if r['blade'] is not None else '未知',r['pool'],percent(r['chance']),percent(r['chance200']),r['threshold'] if r['threshold'] is not None else '未知',r['threshold200'] if r['threshold200'] is not None else '未知'))
  self.note.configure(text=f"显示{len(rows)}人；同城全体候选参与计算，过滤不会提高概率。"+(' '+reason if reason else ' 未计入另一势力抢先招揽、待结算民望变化。'))
 def render_cards(self,_=None):
  self.cards.delete(*self.cards.get_children());force=next((f for f in self.state.get('entities',{}).get('lords',[]) if f.get('force_id')==self.force_id),None)
  rows=card_rows(force)
  for row in rows:self.cards.insert('','end',values=(row['slot'],row['name'],row['seasonal'] if self.state.get('build_sha256')==BUILD else '版本未核准'))
  count=sum(row['name']==self.wanted.get() for row in rows)
  self.card_note.configure(text=f"当前持有「{self.wanted.get()}」{count}张；下季度会否领到：未核准。" if rows else '尚未读取所选势力的手牌；未来抽取结果未知。')
