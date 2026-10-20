import os,sys,tkinter as tk
from pathlib import Path
def _add_venv_site():
 root=Path(__file__).resolve().parent.parent
 for folder in (root/'.venv'/'lib').glob('python*/site-packages'):
  path=str(folder)
  if path not in sys.path:
   sys.path.append(path)
_add_venv_site()
_root=Path(__file__).resolve().parent.parent
for _folder in (_root/'app', _root/'bridge'):
 if str(_folder) not in sys.path:
  sys.path.insert(0,str(_folder))
from hub_singleton import peer_hub_pid, raise_existing_hub, reload_hub as exec_reload
_peer=peer_hub_pid()
if _peer and raise_existing_hub(_peer):
 print('全知情报已在运行，已切到原窗口',flush=True)
 sys.exit(0)
if _peer:
 print('原窗口没切上来，再开一个全知情报。',flush=True)
from omni_window import OmniWindow
from bridge_autostart import ensure_bridge, watch_bridge
from connection import CONNECTION,local_config
local_source=local_config()
bridge_error=None
if local_source:
 os.environ['SGI_SOURCE_ID']=local_source.get('expected_source',local_source['label'])
 hub_root=Path(__file__).resolve().parent.parent
 if sys.platform=='win32':
  os.environ.setdefault('SGI_GAME_EXE',local_source.get('game_path',r'D:\Coding\sanguo-internet\run-3.5\3I\SANPK.exe'))
  from service_startup import ensure_service,probe,bridge_upgrade_due
  def start_win():
   url='http://127.0.0.1:8769/health';service='sgi-crossover-bridge-1'
   current=probe(url,service)
   if bridge_upgrade_due(current,hub_root):
    pid=current.get('collector_pid')
    if type(pid) is int and pid>0 and pid!=os.getpid():
     # Windows PID from our verified loopback service; never SANPK or its parent.
     import signal,time
     if bridge_upgrade_due(probe(url,service),hub_root):
      os.kill(pid,signal.SIGTERM)
      deadline=time.monotonic()+4
      while probe(url,service) is not None and time.monotonic()<deadline:time.sleep(.1)
   return ensure_service('http://127.0.0.1:8769/health','sgi-crossover-bridge-1',
                  [sys.executable,'-B',str(hub_root/'bridge/windows_bridge.py')],
                  hub_root,hub_root/'logs/native-bridge.log')
  try:
   start_win()
  except Exception as error:
   bridge_error=str(error)
   print('采集桥未就绪，仍打开全知情报：'+bridge_error,flush=True)
  try:
   watch_bridge(hub_root,starter=start_win)
  except Exception as error:
   print('采集桥看守未启动：'+str(error),flush=True)
 else:
  try:
   bridge_start=ensure_bridge(hub_root)
   print('采集桥：'+bridge_start['mode'],flush=True)
  except Exception as error:
   bridge_error=str(error)
   print('采集桥未就绪，仍打开全知情报：'+bridge_error,flush=True)
  try:
   watch_bridge(hub_root)
  except Exception as error:
   print('采集桥看守未启动：'+str(error),flush=True)
root=tk.Tk()
from dock_icon import apply as apply_dock_icon
apply_dock_icon(root,'hub')
from mac_light_theme import apply_light_defaults
apply_light_defaults(root)
from display_layout import configure as configure_display,save as save_display,CHOICES
display_choice=configure_display(root)
app=OmniWindow(root)
MAIN=Path(__file__).resolve()
def restart_hub():
    # Reload this viewer only. Never stop SANPK, SANGUO, or the collector.
    app.stop.set();CONNECTION.close()
    try:root.destroy()
    except tk.TclError:pass
    exec_reload(executable=sys.executable, script=str(MAIN))
app.on_reload=restart_hub
from connection import source_options, select_source
sources=source_options()
if sources:
 from tkinter import ttk, messagebox
 bar=ttk.Frame(root)
 bar.pack(side='top',fill='x',before=root.winfo_children()[0],padx=12,pady=5)
 ttk.Label(bar,text='游戏数据源：').pack(side='left')
 choice=ttk.Combobox(bar,values=list(sources),state='readonly',width=30)
 choice.set(CONNECTION.cfg.get('selected_source',''))
 choice.pack(side='left',padx=8)
 def switch_source(event=None):
  if choice.get()==CONNECTION.cfg.get('selected_source'):return
  try:select_source(choice.get())
  except Exception as error:
   messagebox.showerror('切换失败',str(error));return
  # A new interpreter discards all old snapshots, child windows and reader
  # threads. Close only this viewer's SSH tunnel; never touch a collector.
  restart_hub()
 choice.bind('<<ComboboxSelected>>',switch_source)
from tkinter import ttk,messagebox
density_bar=bar if sources else ttk.Frame(root)
if not sources:density_bar.pack(side='top',fill='x',before=root.winfo_children()[0],padx=12,pady=2)
ttk.Label(density_bar,text='界面缩放：').pack(side='left')
density=ttk.Combobox(density_bar,values=CHOICES,state='readonly',width=7)
density.set(display_choice);density.pack(side='left')
def switch_density(event=None):
 if density.get()==display_choice:return
 try:save_display(density.get())
 except Exception as error:messagebox.showerror('缩放设置失败',str(error));return
 restart_hub()
density.bind('<<ComboboxSelected>>',switch_density)
version=__import__('json').loads((Path(__file__).resolve().parent.parent/'RELEASE.json').read_text(encoding='utf8'))['version']
root.title('三国志全知情报 '+version+' · '+('远端 · ' if CONNECTION.remote else '')+CONNECTION.cfg['label'])
app.status.config(text=('采集桥未就绪：'+bridge_error) if bridge_error else ('正在连接 '+CONNECTION.cfg['label']))
def close():
 app.stop.set();CONNECTION.close();root.destroy()
root.protocol('WM_DELETE_WINDOW',close)
from graceful_shutdown import install as install_shutdown
install_shutdown(root,close)
from verify_gui import install
install(root,app)
try:
 root.mainloop()
finally:
 CONNECTION.close()
