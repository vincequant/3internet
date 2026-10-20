"""Render original read-only sample; no transport or game commands are available.

Usage: python3.14 docs/verify_native_0_2_32.py --snapshot /path/to/battlefield.json
macOS screenshot capture uses the existing /tmp/winid.swift helper described in
the project handoff. The source sample is private and is not distributed.
"""
import argparse
import sys,json,subprocess
from pathlib import Path
from unittest import mock
import tkinter as tk
R=Path(__file__).resolve().parents[1]
args=argparse.ArgumentParser();args.add_argument('--snapshot',required=True);args=args.parse_args()
sys.path[:0]=[str(R),str(R/'app'),str(R/'bridge')]
from mac_light_theme import apply_light_defaults
from fengye_battle_panel import BattlePanel
from build_picker import EmbeddedConstructionMap
from panorama_model import object_key
D=json.loads(Path(args.snapshot).read_text())
root=tk.Tk(); apply_light_defaults(root); root.geometry('1280x820+30+55')
root.title('風夜地圖驗收 — 11:10 原始唯讀樣本回放')
tk.Label(root,text='2026-10-20 11:10 原始唯讀樣本回放 · 不是即時畫面 · 本視窗不發出遊戲指令',fg='#203440',bg='#e7e0c9').pack(fill='x')
service=mock.Mock();service.battlefield.return_value=D
battle=BattlePanel(root,service,autostart=False);battle.pack(fill='both',expand=True)
battle.refresh()
city=next(c for c in D['state']['entities']['cities_and_barriers'] if c['city_id']==6)
def snap(name):
 root.update()
 result=subprocess.check_output(['swift','/tmp/winid.swift','風夜地圖驗收'],text=True)
 wid=result.split()[0]
 subprocess.run(['screencapture','-x','-o','-l'+wid,str(R/'docs'/name)],check=True)
def first():
 if battle.raw_state is None:
  root.after(100,first);return
 page=battle.panorama;page.center=(79,51);page.zoom=3.0
 page.selected=object_key('城关',city);page.draw()
 root.after(300,finish_battle)
def finish_battle():
 snap('panel-0.2.32-battle.png');battle.dispose();battle.destroy()
 picker=EmbeddedConstructionMap(root,lambda *args:False);picker.pack(fill='both',expand=True)
 # A fixed sample clock is only used in this isolated, non-sending renderer
 # check. The original source/timestamps are never changed or labelled live.
 with mock.patch.object(picker,'_fresh',return_value=True):
  picker.set_context('陷阱',3,D['cities'],D,busy=[])
  page=picker.panorama;page.center=(79,51);page.zoom=3
  picker.selected=min(picker.candidates,key=lambda xy:abs(xy[0]-79)+abs(xy[1]-51))
  picker._update_selection();page.draw()
 root.after(300,finish_picker)
def finish_picker():
 snap('panel-0.2.32-picker.png');root.destroy()
root.after(200,first);root.mainloop()
