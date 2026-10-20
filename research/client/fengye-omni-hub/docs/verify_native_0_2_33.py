"""Mapped native read-only verification (macOS, no game commands).

Run from the source checkout after installing the read-only lab helpers.
Uses the /tmp/winid.swift helper from the handoff for screencapture -l.
Counts real automatic frames, renders original pages, opens build mode only.
Submit/switch/game-action entry points are blocked; confirmation is not invoked.
"""
import sys, json, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT,ROOT/'app',ROOT/'bridge'):
 sys.path.insert(0,str(folder))
import native_window as nw
from command_service import CommandService
original_run=CommandService._run
READS={'find_sanpk_pid.py','_p60_battle.py','roundprobe.py','_p60_slots.py','_p60_occupied.py','_p60_pick_cell_wide.py'}
def read_only_run(self,prefix,args,**kwargs):
 assert str(args[0]).replace('\\','/').split('/')[-1] in READS,args[0]
 return original_run(self,prefix,args,**kwargs)
CommandService._run=read_only_run
def blocked(*args,**kwargs):raise AssertionError('read-only native verification cannot send')
CommandService.submit=blocked
CommandService._switch_slot=blocked
original_init=nw.FengyeWindow.__init__
record={}
def init(self,root,*args,**kwargs):
 original_init(self,root,*args,**kwargs)
 root.title('風夜即時驗收 — 唯讀')
 # No game input is available from this verification surface.
 for name in ('room_action','_lab_async','send_chat','send_stop'):
  setattr(self,name,blocked)
 start=time.monotonic()
 def ready():
  if self.capture_status.frames<2:
   if time.monotonic()-start>45:
    record['error']='live automatic reader did not produce two frames'
    finish();return
   root.after(250,ready);return
  record['first_header']=self.status.cget('text')
  record['frames_before']=self.capture_status.frames
  record['forces']=self.command_panel.force_box.cget('values')
  steps=['勢力情報','勢力對比','外部指令','戰場','建設']
  def one():
   if not steps:
    record['last_header']=self.status.cget('text');record['frames_after']=self.capture_status.frames
    record['force_view_error']=self.force_views_error
    finish();return
   title=steps.pop(0)
   tab_title = '外部指令' if title == '建設' else title
   tid=next(t for t in self.control_book.tabs() if self.control_book.tab(t,'text')==tab_title)
   self.control_book.select(tid);root.update()
   if title == '戰場':
    cities=self.command_panel._owned_cities()
    if cities:
     self.battle_panel.panorama.center=tuple(cities[0]['xy'])
     self.battle_panel.panorama.zoom=3.8
     self.battle_panel.panorama.draw(refresh_view=False)
   if title == '建設':
    self.command_panel.build(7)
    picker=self.command_panel.map_view
    cities=self.command_panel._owned_cities()
    if cities:
     picker.panorama.center=tuple(cities[0]['xy']);picker.panorama.zoom=3.8
     picker.panorama.draw(refresh_view=False)
     if picker.candidates:
      xy=min(picker.candidates, key=lambda xy: abs(xy[0]-cities[0]['xy'][0])+abs(xy[1]-cities[0]['xy'][1]))
      from panorama_model import layer_for_zoom
      sx,sy=picker.panorama._project(*xy,picker.canvas.winfo_width(),picker.canvas.winfo_height(),layer_for_zoom(picker.panorama.zoom))
      picker.canvas.event_generate('<Motion>',x=round(sx),y=round(sy))
      picker.canvas.event_generate('<ButtonPress-1>',x=round(sx),y=round(sy))
      picker.canvas.event_generate('<ButtonRelease-1>',x=round(sx),y=round(sy))
      root.update()
      record['construction_candidates']=len(picker.candidates)
      record['selected_cell']=picker.selected
      record['confirm_enabled']=str(picker.confirm_button.cget('state'))
      record['confirmation_invoked']=False
   def snap():
    names={'勢力情報':'forces','勢力對比':'compare','外部指令':'commands','戰場':'battle','建設':'picker'}
    name=names[title]
    if name=='compare':record['compare_rows']=[self.force_compare.tree.item(i,'values') for i in self.force_compare.tree.get_children()]
    if name=='forces':record['force_rows']=[self.force_tree.item(i,'values') for i in self.force_tree.get_children()]
    wid=subprocess.check_output(['swift','/tmp/winid.swift','風夜即時驗收'],text=True).split()[0]
    subprocess.run(['screencapture','-x','-o','-l'+wid,str(ROOT/'docs'/('panel-0.2.33-'+name+'.png'))],check=True)
    root.after(300,one)
   root.after(500,snap)
  one()
 def finish():
  (ROOT/'docs'/'live-0.2.33-verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
  self.stop.set();self.battle_panel.dispose();root.destroy()
 root.after(500,ready)
nw.FengyeWindow.__init__=init
sys.argv=[str(ROOT/'run.py')]
import run
run.main()
