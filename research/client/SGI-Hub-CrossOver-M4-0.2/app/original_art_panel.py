"""Original-art reference and live-ID officer portrait detail."""
import tkinter as tk
from tkinter import ttk
from original_sprites import OriginalSprites,CATALOG
BG='#f7f4ea';FG='#302c22'
class OriginalArtPanel(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg=BG);self.images=OriginalSprites(self)
  tk.Label(self,text='原版素材图鉴 · 地图显示静态代表帧；效果图仅供攻略参考，不代表正在交战。',bg=BG,fg=FG,anchor='w').pack(fill='x',padx=10,pady=6)
  canvas=tk.Canvas(self,bg=BG,highlightthickness=0);scroll=ttk.Scrollbar(self,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
  grid=tk.Frame(canvas,bg=BG);item=canvas.create_window(0,0,window=grid,anchor='nw');grid.bind('<Configure>',lambda _=None:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
  entries=[(name,v['file']) for name,v in CATALOG['units'].items()]
  entries += [(name,v[1]['file']) for kind,v in CATALOG['buildings'].items() for name in [{'parade_ground':'练兵所','horse_farm':'牧场','bow_studio':'弓工坊'}[kind]]]
  entries += [('运输队','transport.png'),('舟船','boat.png'),('战船（舰型待实景核对）','warship.png'),('城池','city-0.png'),('关隘与城墙','city-25.png'),('城墙片段','wall.png'),('火焰','fire.png'),('落石','rock.png'),('陷坑','pit.png'),('雷电效果','lightning.png'),('箭矢效果','arrow.png'),('烟雾效果','smoke.png')]
  for i,(name,file) in enumerate(entries):
   box=tk.Frame(grid,bg=BG);box.grid(row=i//4,column=i%4,sticky='nsew',padx=6,pady=8);grid.columnconfigure(i%4,weight=1)
   photo=self.images.named(file,90);tk.Label(box,image=photo or '',bg=BG,height=100).pack();tk.Label(box,text=name,bg=BG,fg=FG,wraplength=200).pack()
  tk.Label(grid,text=f"已载入 {CATALOG['portraits']['count']} 张原版武将头像；在武将列表双击姓名查看。旗帜按本局已读取的势力颜色编号选用。",bg=BG,fg=FG,wraplength=900).grid(row=(len(entries)+3)//4,column=0,columnspan=4,pady=12)

def open_officer(app,key):
 selected=app.tables[key].selection()
 record=app.row_records.get(key,{}).get(selected[0]) if selected else None
 open_officer_record(app,record)

def open_officer_record(app,record):
 if not app or not record:return
 from officer_reference import STAT_LABELS,display_attributes,officer_metrics,officer_title,standout_stat
 face=getattr(app,'face','PingFang SC')
 title=officer_title(record)
 window=tk.Toplevel(app.root);window.title(title);window.configure(bg='#e8dcc0');window.geometry('620x360');window.minsize(540,320)
 if not hasattr(app,'combat_windows'):app.combat_windows=[]
 app.combat_windows.append(window)
 shell=tk.Frame(window,bg='#e8dcc0');shell.pack(fill='both',expand=True,padx=14,pady=14)
 card=tk.Frame(shell,bg='#f7f4ea',highlightbackground='#b89a4a',highlightthickness=2);card.pack(fill='both',expand=True)
 images=OriginalSprites(window);window.original_images=images
 photo=images.portrait(record.get('portrait_id'))
 left=tk.Frame(card,bg='#f0e2b8',width=168);left.pack(side='left',fill='y');left.pack_propagate(False)
 frame=tk.Frame(left,bg='#f7f4ea',highlightbackground='#c9b27a',highlightthickness=1)
 frame.pack(padx=16,pady=(18,10))
 tk.Label(frame,image=photo or '',text='' if photo else '—',bg='#f7f4ea',fg='#786e56',padx=6,pady=6).pack()
 lords=((getattr(app,'doc',None) or {}).get('entities') or {}).get('lords') or []
 owner=next((f.get('name') for f in lords if f.get('force_id')==record.get('owner_raw')),'')
 place=record.get('location_city_name') or ''
 soldiers=record.get('soldiers')
 troop=f'{soldiers:,}' if isinstance(soldiers,int) else ''
 pills=tk.Frame(left,bg='#f0e2b8');pills.pack(padx=10,pady=(0,16))
 for text in (owner,place,troop):
  if not text:continue
  tk.Label(pills,text=text,bg='#e8d6a8',fg='#6b5420',font=(face,9,'bold'),padx=6,pady=2).pack(pady=2)
 right=tk.Frame(card,bg='#f7f4ea');right.pack(side='left',fill='both',expand=True,padx=18,pady=16)
 tk.Label(right,text=title,bg='#f7f4ea',fg='#6b3f12',font=(face,20,'bold'),anchor='w').pack(fill='x')
 tk.Frame(right,bg='#d4c7a1',height=1).pack(fill='x',pady=(8,12))
 stand=standout_stat(record);attrs=display_attributes(record)
 row=tk.Frame(right,bg='#f7f4ea');row.pack(fill='x')
 for index,(key,label) in enumerate(STAT_LABELS):
  value=attrs.get(key);hot=stand and label==stand['label']
  cell=tk.Frame(row,bg='#f4df96' if hot else '#fff8ee',highlightbackground='#c9b27a' if hot else '#d4c7a1',highlightthickness=1)
  cell.grid(row=0,column=index,sticky='nsew',padx=4,ipady=8);row.columnconfigure(index,weight=1)
  tk.Label(cell,text=label,bg=cell['bg'],fg='#8a6a12',font=(face,9)).pack()
  tk.Label(cell,text='—' if value is None else str(value),bg=cell['bg'],fg='#6b3f12' if hot else '#302c22',font=(face,16,'bold')).pack()
 m=officer_metrics(record)
 meta=tk.Frame(right,bg='#f7f4ea');meta.pack(fill='x',pady=(14,8))
 for label,value in (('攻',m.get('attack')),('计',m.get('strategy')),('外交',m.get('diplomacy'))):
  if value in (None,''):continue
  tk.Label(meta,text=f'{label}  {value}',bg='#e8d9a8',fg='#5a3d10',font=(face,10,'bold'),padx=10,pady=4).pack(side='left',padx=3)
 skills=m.get('skills')
 if skills and skills not in ('未匹配','网站技能空表'):
  chips=tk.Frame(right,bg='#f7f4ea');chips.pack(fill='x',pady=(2,0))
  for skill in [part.strip() for part in str(skills).split('/') if part.strip()]:
   tk.Label(chips,text=skill,bg='#dce6f2',fg='#1e3f6e',font=(face,9,'bold'),padx=8,pady=3).pack(side='left',padx=3,pady=2)
