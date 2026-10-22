"""War/refusal presentation; arithmetic is available without Tk."""
import tkinter as tk
from diplomacy_matchup_model import *
class WarRejectBoard(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.rows={};self.signature=None
  tk.Label(self,text='宣战与拒绝 · 白卡反转',bg=BG,fg=FG,font=(app.face,16,'bold'),anchor='w').pack(fill='x',padx=12,pady=(10,4))
  tk.Label(self,text='采用当前最高点数可用使者。基准不消耗白卡；点差＝宣战方－拒绝方，同点宣战方胜。分别比较我方、对方与双方加白卡；斩使的特殊回应另算。',bg=BG,fg='#756443',anchor='w',justify='left',wraplength=1100).pack(fill='x',padx=12,pady=6)
  self.columns=('scene','opponent','result','delta','our_white','their_white','both_white','solution')
  self.tree=app.tree(self,[('scene','场面',95),('opponent','对手',80),('result','不耗白卡',80),('delta','宣战点差',90),('our_white','我方加白卡',230),('their_white','对方加白卡',230),('both_white','双方加白卡',140),('solution','我方反转所需',250)])
  self.tree.tag_configure('win',background='#d4efd4',foreground='#1d6b32');self.tree.tag_configure('loss',background='#f8d0d0',foreground='#9d1c1c')
  self.detail=tk.Label(self,text='',bg=BG,fg=FG,anchor='w',justify='left',wraplength=1100);self.detail.pack(fill='x',padx=12,pady=10)
  self.tree.bind('<<TreeviewSelect>>',self.select)
  self.bind('<Configure>',lambda e:self.detail.configure(wraplength=max(300,e.width-30)))
 def select(self,_=None):
  selected=self.tree.selection();r=self.rows.get(selected[0]) if selected else None
  self.detail.configure(text=(f"不耗白卡\n宣战：{r['attack']}\n拒绝：{r['defend']}\n加入白卡\n宣战：{r['white_attack']}\n拒绝：{r['white_defend']}\n{r['note']}" if r else '等待已确认的我方势力和手牌。'))
 def refresh(self,state,own_id):
  rows=matchup_rows(state,own_id)
  if rows==self.signature:return
  self.signature=rows;selected=self.tree.selection();self.rows={str(i):r for i,r in enumerate(rows)};self.tree.delete(*self.tree.get_children())
  for i,r in self.rows.items():self.tree.insert('','end',iid=i,tags=(r['tone'],),values=tuple(r[k] for k in self.columns))
  if self.rows:self.tree.selection_set(selected[0] if selected and selected[0] in self.rows else '0')
  self.select()
