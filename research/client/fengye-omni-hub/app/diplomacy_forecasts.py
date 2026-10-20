"""Read-only defection forecast and user-selectable card-draw distributions."""
import json,queue,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from native_diplomacy import forecast
from card_probability import probability_rows
BG,FG,MUTED='#f7f4ea','#302c22','#786e56'
NAMES=json.loads(Path(__file__).with_name('diplomacy_card_effects.json').read_text(encoding='utf8'))['cards']
NAMES={k:v['name'] for k,v in NAMES.items()}
def percent(p):return f'{float(p)*100:.2f}%'
class DefectionBoard(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.state=None;self.own_id=None;self.options={};self.rows={};self.signature=None;self.live_signature=None;self.supplement=None;self.supplement_time=None;self.busy=False;self.events=queue.Queue();self.auto_attempt=None
  tk.Label(self,text='策反 · 成功率与叛离人选',bg=BG,fg=FG,font=(app.face,17,'bold'),anchor='w').pack(fill='x',padx=12,pady=10)
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=12)
  tk.Label(bar,text='使者：',bg=BG,fg=FG).pack(side='left');self.actor=tk.StringVar();self.combo=ttk.Combobox(bar,textvariable=self.actor,state='readonly',width=36);self.combo.pack(side='left');self.combo.bind('<<ComboboxSelected>>',self.calculate)
  self.load_button=ttk.Button(bar,text='更新本机预判资料',command=self.load_current);self.load_button.pack(side='left',padx=14)
  self.bind('<Map>',self.auto_load)
  self.summary=tk.Label(self,text='',bg=BG,fg=MUTED,anchor='w',justify='left',wraplength=1050);self.summary.pack(fill='x',padx=12,pady=10)
  self.tree=app.tree(self,[('force','目标势力',100),('chance','成功率',110),('city','叛离城池',180),('generals','叛离武将',340),('reason','条件',280)])
  self.detail=tk.Text(self,height=9,wrap='word',bg=BG,fg=FG,font=(app.face,12),relief='flat',padx=12,pady=8);self.detail.pack(fill='x')
  self.tree.bind('<<TreeviewSelect>>',self.select)
  self.bind('<Configure>',lambda e:self.summary.configure(wraplength=max(300,e.width-30)))
 def refresh(self,state,own_id):
  signature=repr(((state or {}).get('identity'),(state or {}).get('clock_candidates'),bool(getattr(self.app,'review',None))))
  if signature!=self.live_signature:self.live_signature=signature;self.supplement=None;self.supplement_time=None
  if any('defection_exiled_flag' in f for f in ((state or {}).get('entities') or {}).get('lords',[])):self.supplement=None;self.supplement_time=None
  changed=own_id!=self.own_id;self.input_state=state;self.state=self.supplement or state;self.own_id=own_id
  self.fill(changed)
  self.auto_load()
 def fill(self,changed=False):
  state=self.state;own_id=self.own_id
  data=forecast(state,own_id);self.options={f"{g['name']} · 政魅{g['base']} · 策反点{g['actor']}":g['id'] for g in data['envoys']}
  self.combo.configure(values=list(self.options))
  if changed or self.actor.get() not in self.options:self.actor.set(next(iter(self.options),''))
  self.calculate()
 def auto_load(self,_=None):
  if not self.winfo_viewable() or self.busy or self.auto_attempt==self.live_signature or not self.state or self.supplement:return
  if any('defection_exiled_flag' in f for f in (self.state.get('entities') or {}).get('lords',[])):return
  self.auto_attempt=self.live_signature;self.load_current(automatic=True)
 def load_current(self,automatic=False):
  if self.busy:return
  from connection import load_config
  try:
   if getattr(self.app,'review',None) or load_config()['mode']!='local':raise ValueError('回放与远端仅使用所选帧保存的预判资料')
   if not (self.input_state or {}).get('identity'):raise ValueError('等待本机实时游戏资料。')
  except (ValueError,AttributeError) as e:
   if not automatic:self.summary.configure(text=str(e))
   return
  self.busy=True;self.load_button.configure(state='disabled');self.summary.configure(text='正在只读核对策反资料…');state=self.input_state;signature=self.live_signature
  def worker():
   try:
    from card_pool_client import fetch
    self.events.put((signature,fetch(state,kind='diplomacy'),None))
   except Exception as e:self.events.put((signature,None,str(e)))
  threading.Thread(target=worker,daemon=True).start();self.after(100,self.poll)
 def poll(self):
  try:signature,result,error=self.events.get_nowait()
  except queue.Empty:self.after(100,self.poll);return
  self.busy=False;self.load_button.configure(state='normal')
  if signature!=self.live_signature:self.summary.configure(text='当前帧已改变，请等待刷新后重新读取。');return
  if error:self.summary.configure(text=error);return
  self.supplement=result['diplomacy_state'];self.supplement_time=result['captured_at'][11:19];self.state=self.supplement;self.fill()
 def calculate(self,_=None):
  data=forecast(self.state,self.own_id,self.options.get(self.actor.get()));self.data=data
  actor=data['envoy'];text=('持有策反卡' if data['held'] else '未持有策反卡 · 以下为持卡情景')+'。成功后武将与城池另立新势力。'
  text+='\n'+(f"使者{actor['name']}：政治＋魅力{actor['base']}，计谋技能"+('生效' if actor['bonus'] else '未生效')+f"，策反点{actor['actor']}。未提交时按随机参数0–19取平均；已提交且使者相同则用当前参数。" if actor else '使者原始资料不足，暂不能计算成功率。')
  if self.supplement_time:text+='\n本机只读预判资料：'+self.supplement_time+' UTC；可手动更新。'
  self.summary.configure(text=text)
  signature=repr(data)
  if signature==self.signature:return
  self.signature=signature;old=self.tree.selection();self.rows={str(i):r for i,r in enumerate(data['rows'])};self.tree.delete(*self.tree.get_children())
  for i,r in self.rows.items():
   gs=r['generals'];names='、'.join(g['row'].get('name',str(g['id']))+('（必入选）' if g['inclusion']==1 else f"（入选{percent(g['inclusion'])}）") for g in gs) if gs is not None else '资料不足'
   cities='、'.join(c.get('name',str(c.get('city_id'))) for c in r['cities']) if r['cities'] is not None else '资料不足'
   chance='未知' if r['chance'] is None else f"{r['chance']:.2f}%";condition=r['reason'] or ('已提交参数'+str(r['parameter']) if r['parameter'] is not None else '平均成功率；结算时重新判定')
   self.tree.insert('','end',iid=i,values=(r['force'].get('name'),chance,cities,names,condition))
  if self.rows:self.tree.selection_set(old[0] if old and old[0] in self.rows else '0')
  self.select()
 def select(self,_=None):
  selection=self.tree.selection();r=self.rows.get(selection[0]) if selection else None;lines=[]
  if r:
   lines=[f"目标：{r['force'].get('name')}"]
   if r['range']:lines.append(f"随机参数尚未确定时，门槛判定范围 {r['range'][0]}%–{r['range'][1]}%；表中成功率还须满足城池、人选和空闲势力条件。")
   for g in r['generals'] or []:
    lines.append(f"{g['row'].get('name',g['id'])}：统武智政合计{sum(g['stats'][:4])} · 入仕年{g['entry']} · 野心{g['ambition']} · 带兵{g['soldiers']:,} · 入选{percent(g['inclusion'])} · 新君主{percent(g['leader'])}")
   lines+=['先排除君主、保护武将、亲属同族、相性差不足20及出征等状态；取四维最高，再取资历最短的同分人选，最后按野心、带兵和年龄择最多三人。完全同分才随机。','城池先排除首都与关隘；优先不直接邻接首都的城池，再取人口最高者。人口同分时随机。','这里是选定帧条件下的预判；结算前人事、城池或宝物变化会改变结果。']
  self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('end','\n'.join(lines) or '等待势力资料。');self.detail.configure(state='disabled')
class CardProbabilityBoard(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.app=app;self.state=None;self.counts=None;self.rows={};self.pool_signature=None;self.busy=False;self.events=queue.Queue()
  tk.Label(self,text='抽中一张',bg=BG,fg=FG,font=(app.face,17,'bold'),anchor='w').pack(fill='x',padx=12,pady=10)
  bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=12)
  tk.Label(bar,text='新抽张数：',bg=BG,fg=FG).pack(side='left');self.draws=tk.StringVar(value='5');self.spin=ttk.Spinbox(bar,from_=0,to=5,width=5,textvariable=self.draws);self.spin.pack(side='left')
  self.load_button=ttk.Button(bar,text='载入当前可抽卡池',command=self.load_current);self.load_button.pack(side='left',padx=14)
  self.hide_zero=tk.BooleanVar(value=True)
  ttk.Checkbutton(bar,text='不显示0%',variable=self.hide_zero,command=self.calculate).pack(side='left')
  self.mode=tk.StringVar(value='当前可抽卡池');self.source=tk.Label(bar,textvariable=self.mode,bg=BG,fg=MUTED);self.source.pack(side='left')
  self.summary=tk.Label(self,text='',bg=BG,fg=MUTED,anchor='w',justify='left',wraplength=1050);self.summary.pack(fill='x',padx=12,pady=10)
  self.tree=app.tree(self,[('name','卡片 / 类别',220),('one','抽中一张',140)])
  self.tree.bind('<<TreeviewSelect>>',self.select)
  self.detail=tk.Label(self,text='',bg=BG,fg=FG,anchor='w',justify='left',wraplength=1100);self.detail.pack(fill='x',padx=12,pady=12)
  self.draws.trace_add('write',lambda *_:self.calculate());self.bind('<Configure>',self.resize)
 def resize(self,e):
  for w in (self.summary,self.detail):w.configure(wraplength=max(300,e.width-30))
 def refresh(self,state,own_id=None):
  self.state=state;pool=(state or {}).get('card_pool') or {}
  signature=repr(((state or {}).get('identity'),(state or {}).get('clock_candidates'),pool))
  if signature!=self.pool_signature:
   self.pool_signature=signature;self.mode.set('当前帧可抽卡池');self.load()
 def load(self):
  pool=(self.state or {}).get('card_pool') or {};self.pool_signature=repr(((self.state or {}).get('identity'),(self.state or {}).get('clock_candidates'),pool))
  self.counts={i:pool.get('counts',{}).get(str(i)) for i in range(1,29)} if pool.get('status')=='verified' else None
  self.calculate()
 def load_current(self):
  if self.busy:return
  if ((self.state or {}).get('card_pool') or {}).get('status')=='verified':self.load();return
  from connection import load_config
  try:
   if getattr(self.app,'review',None) or load_config()['mode']!='local':raise ValueError('回放与远端仅使用所选帧记录的卡池')
  except ValueError as e:self.summary.configure(text=str(e));return
  if not (self.state or {}).get('identity'):self.summary.configure(text='等待本机游戏开始后读取卡池。');return
  self.busy=True;self.load_button.configure(state='disabled');self.summary.configure(text='正在只读核对公共卡池…')
  state=self.state;signature=self.pool_signature
  def worker():
   try:
    from card_pool_client import fetch
    self.events.put((signature,fetch(state),None))
   except Exception as e:self.events.put((signature,None,str(e)))
  threading.Thread(target=worker,daemon=True).start();self.after(100,self.poll)
 def poll(self):
  try:signature,result,error=self.events.get_nowait()
  except queue.Empty:self.after(100,self.poll);return
  self.busy=False;self.load_button.configure(state='normal')
  if signature!=self.pool_signature:self.summary.configure(text='当前帧已改变，请重新载入卡池。');return
  if error:self.summary.configure(text=error);return
  pool=result['card_pool'];self.counts={i:pool['counts'][str(i)] for i in range(1,29)}
  self.mode.set('本机只读卡池 · '+result['captured_at'][11:19]+' UTC');self.calculate()
 def calculate(self):
  self.tree.delete(*self.tree.get_children());self.rows={}
  try:n=int(self.draws.get());assert 0<=n<=5
  except (ValueError,AssertionError):self.summary.configure(text='请选择0至5张。');return
  if self.counts is None:
   self.summary.configure(text='本帧没有完整可抽卡池，暂不能给出真实百分比。新版采集器会记录卡池；本机实时可点「载入当前可抽卡池」补读，旧回放缺失不能由手牌推算。');self.detail.configure(text='');return
  try:rows=probability_rows(self.counts,n,NAMES)
  except ValueError as e:self.summary.configure(text=str(e)+'；不跨越牌组回收计算。');self.detail.configure(text='');return
  total=sum(self.counts.values());self.summary.configure(text=f'从当前可抽的{total}张中新抽{n}张。表中是至少抽中一张该类牌的概率。')
  self.rows={str(i):r for i,r in enumerate(rows)}
  for i,r in self.rows.items():
   if self.hide_zero.get() and not r['at_least_one']:continue
   self.tree.insert('','end',iid=i,values=(r['name'],percent(r['at_least_one'])))
  shown=self.tree.get_children()
  if shown:self.tree.selection_set(shown[0])
  self.select()
 def select(self,_=None):
  selected=self.tree.selection();r=self.rows.get(selected[0]) if selected else None
  self.detail.configure(text=(f"{r['name']} · 新抽{r['draws']}张 · 抽中一张 {percent(r['at_least_one'])}" if r else ''))
