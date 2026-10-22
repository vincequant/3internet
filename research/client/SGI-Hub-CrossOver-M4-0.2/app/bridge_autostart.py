"""Launch the read-only bridge in the game's selected Wine environment."""
from pathlib import Path
import os,json,signal,subprocess,threading,time
from service_startup import ensure_service,probe,bridge_upgrade_due
URL='http://127.0.0.1:8769/health'
SERVICE='sgi-crossover-bridge-1'
WATCH_INTERVAL_S=12
_watch_lock=threading.Lock()
_watch_started=False

def configure_local_runtime(root):
 config=Path(os.environ.get('SGI_CONNECTION_CONFIG',Path(root)/'connection.local.json'))
 if not config.is_file():return
 from connection import local_config
 local=local_config()
 source=(local or {}).get('expected_source') or (local or {}).get('label')
 if source:
  os.environ.setdefault('SGI_SOURCE_ID',source)
 runtime=(local or {}).get('wine_runtime') or json.loads(config.read_text(encoding='utf8')).get('wine_runtime')
 if not runtime:return
 for key,field in [('SGI_WINE_BINARY','wine'),('WINEPREFIX','prefix'),('SGI_RUNTIME_ID','runtime_id'),('DYLD_FALLBACK_LIBRARY_PATH','dependency_lib')]:
  if runtime.get(field):os.environ.setdefault(key,runtime[field])
 os.environ.setdefault('WINEDEBUG','-all,err+all')
 os.environ.setdefault('LANG','zh_CN.UTF-8')
 os.environ.setdefault('LC_ALL','zh_CN.UTF-8')
 os.environ.setdefault('WINEDLLOVERRIDES','winegstreamer=d')
 export_mac_war_write_env()

def export_mac_war_write_env():
 """Let the Wine collector read the Mac host upload file. Do not print the token."""
 mac=Path.home()/'.config'/'sgi-war'/'write.env'
 if not mac.is_file():
  return
 os.environ.setdefault('SGI_WAR_WRITE_ENV','Z:'+str(mac).replace('/','\\'))
 prefix=os.environ.get('WINEPREFIX')
 if not prefix:
  return
 dest=Path(prefix).expanduser()/'drive_c'/'users'/'vk'/'.config'/'sgi-war'/'write.env'
 dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists() or dest.stat().st_mtime<mac.stat().st_mtime:
  dest.write_bytes(mac.read_bytes())
  dest.chmod(0o600)
def bridge_command(root):
 root=Path(root)
 python=root/'bridge/python/python.exe'
 if not python.is_file():raise RuntimeError('缺少环境内 Python：'+str(python))
 code='import pathlib,runpy,sys; runpy.run_path(str(pathlib.Path(sys.executable).resolve().parent.parent / "windows_bridge.py"),run_name="__main__")'
 standalone=os.environ.get('SGI_WINE_BINARY')
 if standalone:
  wine=Path(standalone).expanduser()
  prefix=Path(os.environ.get('WINEPREFIX','')).expanduser()
  if not wine.is_file() or not os.access(wine,os.X_OK):raise RuntimeError('找不到 Wine 运行程序：'+str(wine))
  if not prefix.is_absolute() or not (prefix/'system.reg').is_file():raise RuntimeError('独立 Wine 环境尚未初始化')
  return [str(wine),str(python),'-X','utf8','-B','-c',code],'wine-bridge-auto.log'
 bottle=os.environ.get('SGI_BOTTLE','SanguoInternet')
 wine=Path(os.environ.get('SGI_CX_WINE','/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine'))
 bottle_path=Path.home()/'Library/Application Support/CrossOver/Bottles'/bottle
 if not wine.is_file() or not os.access(wine,os.X_OK):raise RuntimeError('找不到CrossOver运行程序：'+str(wine))
 if not bottle_path.is_dir():raise RuntimeError('找不到游戏容器：'+str(bottle_path))
 return [str(wine),'--bottle',bottle,str(python),'-X','utf8','-B','-c',code],'crossover-bridge-auto.log'

def bridge_pids():
 found=[]
 try:
  listing=subprocess.check_output(['/bin/ps','-axo','pid=,command='],text=True,errors='replace',timeout=5)
 except (subprocess.CalledProcessError,subprocess.TimeoutExpired,OSError):
  return found
 for line in listing.splitlines():
  if 'windows_bridge.py' not in line or 'python.exe' not in line:
   continue
  if 'SANPK.exe' in line or 'SANGUO.exe' in line:
   continue
  pid=line.strip().split(None,1)[0]
  if pid.isdigit():
   found.append(int(pid))
 return found

def stop_bridge_processes():
 """Stop the Wine collector only. Never signals SANPK/SANGUO/Hub."""
 pids=bridge_pids()
 for pid in pids:
  try:os.kill(pid,signal.SIGTERM)
  except ProcessLookupError:pass
 deadline=time.time()+3
 while time.time()<deadline and bridge_pids():
  time.sleep(0.2)
 for pid in bridge_pids():
  try:os.kill(pid,signal.SIGKILL)
  except ProcessLookupError:pass
 return pids

def ensure_bridge(root):
 root=Path(root)
 configure_local_runtime(root)
 health=probe(URL,SERVICE)
 expected=os.environ.get('SGI_SOURCE_ID')
 if health is not None and expected and health.get('source_id') and health.get('source_id')!=expected:
  stop_bridge_processes()
  deadline=time.time()+4
  while time.time()<deadline and probe(URL,SERVICE) is not None:
   time.sleep(0.2)
  health=None
 if health is not None:
  if os.environ.get('SGI_WINE_BINARY') and health.get('runtime_id')!=os.environ.get('SGI_RUNTIME_ID','wine-standalone'):
   raise RuntimeError('已有采集服务属于另一运行环境，请先关闭旧采集服务再切换 Wine')
  if not bridge_upgrade_due(health,root):return {'mode':'reused','health':health}
  # Match this installation's Python command, not every Wine Python process.
  listing=subprocess.check_output(['/bin/ps','-axo','pid=,command='],text=True,timeout=5)
  python=str(root/'bridge/python/python.exe')
  owned=[int(line.strip().split(None,1)[0]) for line in listing.splitlines()
         if python in line and 'windows_bridge.py' in line and line.strip().split(None,1)[0].isdigit()]
  if len(owned)!=1:return {'mode':'upgrade_pending','health':health}
  # Recheck immediately before stopping our collector; a room may have started.
  if not bridge_upgrade_due(probe(URL,SERVICE),root):return {'mode':'reused','health':health}
  os.kill(owned[0],signal.SIGTERM)
  deadline=time.monotonic()+4
  while time.monotonic()<deadline:
   try:os.kill(owned[0],0)
   except ProcessLookupError:break
   time.sleep(.1)
  else:raise RuntimeError('旧采集桥仍在退出，等待下次检查；未重复启动')
  if probe(URL,SERVICE) is not None:raise RuntimeError('采集端口尚未释放，未重复启动')
 command,log=bridge_command(root)
 return ensure_service(URL,SERVICE,command,root,root/'logs'/log)

def watch_bridge(root, interval=WATCH_INTERVAL_S, starter=None):
 """Keep the host-side collector up after Wine/game restarts. Does not touch SANPK."""
 global _watch_started
 root=Path(root)
 with _watch_lock:
  if _watch_started:
   return False
  _watch_started=True
 def loop():
  while True:
   time.sleep(interval)
   try:
    starter() if starter else ensure_bridge(root)
   except Exception as error:
    print('采集桥看守：'+str(error),flush=True)
 threading.Thread(target=loop,daemon=True,name='sgi-bridge-watch').start()
 return True

if __name__=='__main__':
 import argparse,json
 parser=argparse.ArgumentParser()
 parser.add_argument('--watch',action='store_true')
 args=parser.parse_args()
 root=Path(__file__).resolve().parent.parent
 print(json.dumps(ensure_bridge(root),ensure_ascii=False),flush=True)
 if args.watch:
  watch_bridge(root)
  while True:
   time.sleep(3600)
