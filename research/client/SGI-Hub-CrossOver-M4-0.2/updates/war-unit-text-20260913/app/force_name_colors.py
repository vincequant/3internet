"""Shared faction-name presentation for tables, text, headings and selectors."""
import re
import tkinter as tk
from tkinter import ttk,font as tkfont
from battle_colors import owner_style

class ForceNameColors:
 def __init__(self,app):
  self.app=app;self.root=app.root;self.names={};self.pattern=None;self.color_signature=();self.tables={};self.labels={};self.combos={};self.text_cache={}
  self.root.after(300,self.tick)
 def spans(self,text):
  return [(m.start(),m.end(),self.names[m.group()]) for m in self.pattern.finditer(str(text))] if self.pattern else []
 def update_names(self):
  names={}
  for f in (self.app.doc or {}).get('entities',{}).get('lords',[]):
   if f.get('name'):names.setdefault(f['name'],[]).append(f['force_id'])
  self.names={n:ids[0] for n,ids in names.items() if len(ids)==1}
  self.color_signature=tuple((n,fid,owner_style(self.app.doc,fid)[0]) for n,fid in self.names.items())
  # Match names, not the same character inside an officer, city, skill or card name.
  self.pattern=re.compile(r'(?<![\w\u3400-\u9fff])(?:'+'|'.join(re.escape(n) for n in sorted(self.names,key=len,reverse=True))+r')(?![\w\u3400-\u9fff])') if self.names else None
 def walk(self,w):
  if getattr(w,'_force_paint',False):return
  yield w
  for child in w.winfo_children():yield from self.walk(child)
 def tick(self):
  try:self.refresh()
  except tk.TclError:
   if not self.root.winfo_exists():return
  if self.root.winfo_exists():self.root.after(300,self.tick)
 def refresh(self):
  self.update_names()
  for w in list(self.walk(self.root)):
   if isinstance(w,ttk.Combobox):self.combo(w)
   elif isinstance(w,ttk.Treeview) and not hasattr(w,'_battle_colors'):
    if w not in self.tables:self.tables[w]=FactionCells(w,self)
    if w.winfo_viewable():self.tables[w].paint()
   elif isinstance(w,tk.Text):self.text(w)
   elif isinstance(w,tk.Label) and w.winfo_viewable():self.label(w)
   elif isinstance(w,tk.LabelFrame):
    spans=self.spans(w.cget('text'))
    if spans:w.configure(fg=owner_style(self.app.doc,spans[0][2])[0])
  for cache in (self.tables,self.labels,self.combos,self.text_cache):
   for w in list(cache):
    if not w.winfo_exists():cache.pop(w)
 def text(self,w):
  value=w.get('1.0','end-1c');sig=(value,self.color_signature)
  if self.text_cache.get(w)==sig:return
  self.text_cache[w]=sig
  for tag in w.tag_names():
   if str(tag).startswith('force_name_'):w.tag_delete(tag)
  for a,b,fid in self.spans(value):
   fg,bg=owner_style(self.app.doc,fid);tag='force_name_'+str(fid);w.tag_configure(tag,foreground=fg);w.tag_add(tag,f'1.0+{a}c',f'1.0+{b}c');w.tag_raise(tag)
 def draw_text(self,c,text,font,x,y,basefg,spans):
  previous=0
  for a,b,fid in spans:
   plain=text[previous:a]
   if plain:c.create_text(x,y,text=plain,font=font,anchor='nw',fill=basefg);x+=font.measure(plain)
   value=text[a:b];fg,bg=owner_style(self.app.doc,fid);width=font.measure(value)
   c.create_text(x,y,text=value,font=font,anchor='nw',fill=fg);x+=width;previous=b
  if previous<len(text):c.create_text(x,y,text=text[previous:],font=font,anchor='nw',fill=basefg)
 def label(self,w):
  value=str(w.cget('text'));spans=self.spans(value);old=self.labels.get(w)
  if not spans or w.cget('image'):
   if old:old[1].place_forget()
   return
  sig=(value,w.winfo_width(),w.winfo_height(),str(w.cget('font')),w.cget('bg'),w.cget('fg'),str(w.cget('wraplength')),self.color_signature)
  if old and old[0]==sig:old[1].place(x=0,y=0,relwidth=1,relheight=1);return
  c=old[1] if old else tk.Canvas(w,bd=0,highlightthickness=0,takefocus=False)
  c._force_paint=True;c.configure(bg=w.cget('bg'));c.place(x=0,y=0,relwidth=1,relheight=1);c.delete('all')
  self.labels[w]=(sig,c);font=tkfont.Font(root=w,font=w.cget('font'));wrap=w.winfo_pixels(w.cget('wraplength'))
  lines=[];offset=0
  for paragraph in value.split('\n'):
   start=0
   while wrap and font.measure(paragraph[start:])>wrap:
    end=start+1
    while end<len(paragraph) and font.measure(paragraph[start:end+1])<=wrap:end+=1
    # Use the last space for Latin words, otherwise wrap between characters.
    space=paragraph.rfind(' ',start,end)
    if space>start:end=space
    lines.append((paragraph[start:end],offset+start));start=end
    while start<len(paragraph) and paragraph[start]==' ':start+=1
   lines.append((paragraph[start:],offset+start));offset+=len(paragraph)+1
  height=font.metrics('linespace');anchor=str(w.cget('anchor'));pad=w.winfo_pixels(w.cget('padx'));pady=w.winfo_pixels(w.cget('pady'));block=max((font.measure(line) for line,_ in lines),default=0)
  top=pady if 'n' in anchor else w.winfo_height()-len(lines)*height-pady if 's' in anchor else (w.winfo_height()-len(lines)*height)/2
  left=pad if 'w' in anchor else w.winfo_width()-block-pad if 'e' in anchor else (w.winfo_width()-block)/2
  for i,(line,start) in enumerate(lines):
   justify=str(w.cget('justify'));x=left+(block-font.measure(line))*(0 if justify=='left' else 1 if justify=='right' else .5)
   parts=[(max(a,start)-start,min(b,start+len(line))-start,fid) for a,b,fid in spans if a<start+len(line) and b>start]
   self.draw_text(c,line,font,x,top+i*height,w.cget('fg'),parts)
 def combo(self,w):
  values=w.cget('values')
  if not any(self.spans(v) for v in values):return
  if w not in self.combos:
   self.combos[w]=None
   for event in ('<Button-1>','<Down>','<space>'):
    w.bind(event,lambda _,w=w:self.open_picker(w),add='+')
  spans=self.spans(w.get());c=self.combos[w]
  if c is None:
   c=tk.Canvas(w,bd=0,highlightthickness=0,takefocus=False);c._force_paint=True;self.combos[w]=c;c.bind('<Button-1>',lambda _:self.open_picker(w))
  if not spans:c.place_forget();return
  fg,bg=owner_style(self.app.doc,spans[0][2]);c.configure(bg=bg);c.place(x=4,y=3,width=max(0,w.winfo_width()-28),height=max(0,w.winfo_height()-6));c.delete('all')
  c.create_text(3,max(0,w.winfo_height()-6)/2,text=w.get(),anchor='w',fill=fg,font='TkDefaultFont')
 def open_picker(self,w):
  if w.instate(['disabled']):return 'break'
  if getattr(self,'picker',None) is not None and self.picker.winfo_exists():self.picker.destroy()
  pop=tk.Toplevel(self.root);self.picker=pop;pop._force_paint=True;pop.withdraw();pop.overrideredirect(True);pop.transient(w.winfo_toplevel())
  values=list(w.cget('values'));rows=min(12,max(1,len(values)))
  box=tk.Listbox(pop,height=rows,exportselection=False,activestyle='dotbox',font='TkDefaultFont');bar=ttk.Scrollbar(pop,command=box.yview);box.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');box.pack(fill='both',expand=True)
  for value in values:
   box.insert('end',value);spans=self.spans(value);fg,bg=owner_style(self.app.doc,spans[0][2]) if spans else ('#302c22','#f7f4ea');box.itemconfigure('end',fg=fg,bg=bg,selectforeground=fg,selectbackground=bg)
  current=w.current()
  if current>=0:box.selection_set(current);box.activate(current);box.see(current)
  pop.update_idletasks();width=max(w.winfo_width(),box.winfo_reqwidth()+bar.winfo_reqwidth());height=box.winfo_reqheight()
  x=min(w.winfo_rootx(),pop.winfo_screenwidth()-width);y=w.winfo_rooty()+w.winfo_height()
  if y+height>pop.winfo_screenheight():y=w.winfo_rooty()-height
  pop.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}');pop.deiconify();box.focus_set();pop.grab_set()
  def close():
   if pop.winfo_exists():pop.grab_release();pop.destroy();w.focus_set()
  def choose(_=None):
   selected=box.curselection()
   if selected:w.current(selected[0]);w.event_generate('<<ComboboxSelected>>')
   close();return 'break'
  box.bind('<ButtonRelease-1>',choose);box.bind('<Return>',choose);pop.bind('<Escape>',lambda _:close())
  pop.bind('<Button-1>',lambda e:close() if not (0<=e.x_root-pop.winfo_rootx()<pop.winfo_width() and 0<=e.y_root-pop.winfo_rooty()<pop.winfo_height()) else None,add='+')
  return 'break'

class FactionCells:
 def __init__(self,t,manager):
  self.tree=t;self.manager=manager;self.cells={};self.pending=None
  for axis in ('x','y'):
   prior=t.cget(axis+'scrollcommand')
   def moved(*args,prior=prior):
    if prior:t.tk.call(prior,*args)
    self.schedule()
   t.configure(**{axis+'scrollcommand':moved})
  for ev in ('<Configure>','<Map>','<<TreeviewSelect>>','<ButtonRelease-1>'):t.bind(ev,lambda _:self.schedule(),add='+')
 def schedule(self):
  if self.pending is None:self.pending=self.tree.after_idle(self.scheduled)
 def scheduled(self):self.pending=None;self.paint()
 def select(self,key,double=False):
  t=self.tree;t.focus_set();t.focus(key);t.selection_set(key)
  if double:
   # Selection already invokes existing locate/open handlers.
   t.event_generate('<<TreeviewSelect>>')
 def paint(self):
  t=self.tree
  if not t.winfo_exists():return
  visible=set();width=t.winfo_width();style=ttk.Style(t);font=tkfont.Font(root=t,font=style.lookup(t.cget('style') or 'Treeview','font') or 'TkDefaultFont')
  cols=t['displaycolumns'];cols=t['columns'] if cols==('#all',) else cols
  for key in t.get_children():
   if not t.bbox(key):continue
   for col in cols:
    value=t.set(key,col);spans=self.manager.spans(value)
    if not spans:continue
    box=t.bbox(key,col)
    if not box:continue
    x,y,w,h=box;left=max(x,1);right=min(x+w,width-1)
    if right<=left:continue
    k=(key,col);visible.add(k);c=self.cells.get(k)
    if c is None:
     c=tk.Canvas(t,bd=0,highlightthickness=0,takefocus=False);c._force_paint=True;self.cells[k]=c
     c.bind('<Button-1>',lambda _,key=key:self.select(key));c.bind('<Double-1>',lambda _,key=key:self.select(key,True))
     c.bind('<MouseWheel>',lambda e:t.event_generate('<MouseWheel>',delta=e.delta))
    selected=key in t.selection();bg='#6b5420' if selected else '#f7f4ea';fg='#fff3cf' if selected else '#302c22'
    if not selected:
     for tag in t.item(key,'tags'):
      color=t.tag_configure(tag,'background')
      if color:bg=color
    c.configure(bg=bg);c.place(x=left,y=y,width=right-left,height=h);c.delete('all')
    self.manager.draw_text(c,value,font,x-left+5,(h-font.metrics('linespace'))/2,fg,spans)
    if selected:c.create_rectangle(0,0,right-left-1,h-1,outline='#9c791c',width=2)
  for key in list(self.cells):
   if key not in visible:self.cells.pop(key).destroy()
