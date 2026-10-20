"""Independent faction colors in battle cells, using the shared named palette."""
import tkinter as tk
from native_city_map import state_force_rgb

def owner_style(state,owner):
 rgb=state_force_rgb(state,owner)
 color='#%02x%02x%02x'%rgb
 return color,'#f7f4ea'

def city_caption(state,city):
 if not city:return '未知城关'
 matches=[f for f in (state or {}).get('entities',{}).get('lords',[]) if f.get('force_id')==city.get('owner_raw')]
 owner=matches[0].get('name','归属未知') if len(matches)==1 else '归属未知'
 return city['name']+' · '+owner

class ColoredBattleCells:
 """Paint only the three colored cells; retain Treeview sorting and selection."""
 def __init__(self,tree,state):
  tree._battle_colors=True
  self.tree=tree;self.state=state;self.rows={};self.cells={};self.pending=None
  for axis in ('x','y'):
   callback=tree.cget(axis+'scrollcommand')
   def moved(*args,callback=callback):
    if callback:tree.tk.call(callback,*args)
    self.schedule()
   tree.configure(**{axis+'scrollcommand':moved})
  for event in ('<Configure>','<Map>','<<TreeviewSelect>>','<ButtonRelease-1>'):
   tree.bind(event,lambda _=None:self.schedule(),add='+')
 def schedule(self):
  if self.pending is None:self.pending=self.tree.after_idle(self.paint)
 def select(self,key):
  self.tree.focus_set();self.tree.focus(key);self.tree.selection_set(key)
 def wheel(self,event):
  self.tree.event_generate('<MouseWheel>',delta=event.delta)
  return 'break'
 def paint(self):
  self.pending=None;t=self.tree;s=self.state();visible=set();width=t.winfo_width();selected=set(t.selection())
  for key in t.get_children():
   row=self.rows.get(key)
   if row is None:continue
   for col,owner in (('force_a',row['a'].get('owner_raw')),('force_b',row['b'].get('owner_raw')),('city',(row.get('city') or {}).get('owner_raw'))):
    box=t.bbox(key,col)
    if not box:continue
    x,y,w,h=box;left=max(1,x);right=min(width-1,x+w)
    if right<=left:continue
    cellkey=(key,col);visible.add(cellkey)
    c=self.cells.get(cellkey)
    if c is None:
     c=tk.Canvas(t,highlightthickness=0,bd=0,takefocus=False);self.cells[cellkey]=c
     c.bind('<Button-1>',lambda _=None,key=key:self.select(key))
     c.bind('<Double-1>',lambda _=None,key=key:self.select(key))
     c.bind('<MouseWheel>',self.wheel)
    fg,bg=owner_style(s,owner)
    for tag in t.item(key,'tags'):
     background=t.tag_configure(tag).get('background')
     if background:bg=background
    if key in selected:bg='#6a5421'
    c.configure(bg=bg);c.place(x=left,y=y,width=right-left,height=h);c.delete('all')
    c.create_text(x-left+6,h/2,text=t.set(key,col),anchor='w',fill=fg,font=('Microsoft YaHei',11,'bold'))
    if key in selected:c.create_rectangle(0,0,right-left-1,h-1,outline='#9c791c',width=2)
    c.tk.call('raise',str(c))
  for key in list(self.cells):
   if key not in visible:self.cells.pop(key).destroy()
