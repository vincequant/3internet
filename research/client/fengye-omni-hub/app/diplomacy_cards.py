"""Selected-force hand descriptions. Rules are reference, not action availability."""
import json,tkinter as tk
from tkinter import ttk
from pathlib import Path
from tutorial_rules import CARD_POINTS
DATA=json.loads(Path(__file__).with_name('diplomacy_card_effects.json').read_text(encoding='utf8'))
def card_rows(force):
 hand=force.get('hand_cards')
 if not isinstance(hand,dict):return []
 rows=[]
 for slot in hand.get('slots',[]):
  cid=slot.get('card_id');ref=DATA['cards'].get(str(cid),{})
  empty=cid==0;points=CARD_POINTS.get(cid)
  rows.append({'slot':slot.get('slot'),'card_id':cid,'name':slot.get('name') or ref.get('name','未知卡片'),
   'category':'空槽' if empty else ref.get('category','未收录'),'points':'—' if empty else str(points) if points is not None else '未核实',
   'effect':'当前卡位为空。' if empty else ref.get('effect','此卡片尚无可靠说明，不能根据卡片编号推断作用或点数。')})
 return rows
class DiplomacyCards(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={};self.signature=None
  self.heading=tk.Label(self,bg='#f7f4ea',fg='#302c22',anchor='w');self.heading.pack(fill='x',padx=8,pady=6)
  self.tree=app.tree(self,[('slot','卡位',45),('name','卡片',110),('category','类别',90),('points','外交点',65),('effect','作用说明',350)])
  self.tree.configure(height=5);self.tree.master.pack_configure(expand=False)
  self.tree.bind('<<TreeviewSelect>>',self.select)
  self.detail=tk.Text(self,height=9,wrap='word',bg='#f7f4ea',fg='#302c22',font=(app.face,11),relief='flat',padx=10,pady=8)
  self.detail.pack(fill='both',expand=True)
  tk.Label(self,text='规则来源：三国志联机网·外交卡片。点击上方卡片读完整说明；持卡不等于当前可使用或效果已生效。',bg='#f7f4ea',fg='#786e56',wraplength=580,anchor='w',justify='left').pack(fill='x',padx=8,pady=5)
 def update_force(self,force):
  rows=card_rows(force);signature=(force.get('force_id'),json.dumps(rows,ensure_ascii=False))
  if signature==self.signature:return
  selected=self.tree.selection();slot=selected[0] if selected and self.signature and self.signature[0]==force.get('force_id') else None
  self.signature=signature;self.rows={str(i):row for i,row in enumerate(rows)};self.tree.delete(*self.tree.get_children())
  count=sum(r['card_id'] not in (0,None) for r in rows)
  self.heading.config(text=f"{force.get('name','当前势力')} · 持有 {count} 张外交卡片" if rows else '该势力手牌尚未采集')
  self.app.book.tab(self,text=f'外交卡片 ({count})' if rows else '外交卡片（未采集）')
  for iid,row in self.rows.items():self.tree.insert('','end',iid=iid,values=tuple(row[k] for k in ('slot','name','category','points','effect')))
  if rows:self.tree.selection_set(slot if slot in self.rows else next((i for i,r in self.rows.items() if r['card_id']),next(iter(self.rows))))
  self.select()
 def select(self,event=None):
  selected=self.tree.selection();r=self.rows.get(selected[0]) if selected else None
  text=(f"{r['name']} · {r['category']} · 外交点 {r['points']}\n\n{r['effect']}\n\n" if r else '暂无可显示手牌。\n\n')
  text+='使用规则：先选1张功能主卡，最多再加4张合法附加卡。外交武将基础点为政治＋魅力；主动方提案、被动方拒绝技能按对应场景加成20%，再叠加卡片点数。特殊卡和房间禁卡规则另行判断。'
  self.detail.config(state='normal');self.detail.delete('1.0','end');self.detail.insert('end',text);self.detail.config(state='disabled')
