"""Single-entry service startup: reuse only the expected loopback service."""
import json,os,time,socket,subprocess,urllib.request,urllib.error
from contextlib import contextmanager
from pathlib import Path

def bridge_upgrade_due(health,root):
 """Upgrade a collector only between matches, never interrupt an active replay."""
 try:version=json.loads((Path(root)/'RELEASE.json').read_text(encoding='utf8'))['version']
 except (OSError,ValueError,KeyError):return False
 if not health or not health.get('release_version') or health['release_version']==version:return False
 for key in ('replay_archive','training_archive'):
  archive=health.get(key) or {}
  if archive.get('open') or archive.get('recording'):return False
 phase=health.get('phase')
 if phase=='waiting_for_game' and not health.get('identity'):return True
 age=health.get('snapshot_age_s')
 return bool(phase=='waiting_for_player' and health.get('identity') and not health.get('error')
             and type(age) in (float,int) and 0<=age<=4)

def probe(url,service):
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=4) as r:d=json.load(r)
 except urllib.error.URLError as e:
  if isinstance(e.reason,ConnectionRefusedError) or getattr(e.reason,'errno',None) in (61,111,10061) or getattr(e.reason,'winerror',None)==10061:return None
  raise RuntimeError('采集服务无响应，请查看启动日志；不重复拉起') from e
 except (ValueError,TimeoutError,OSError) as e:raise RuntimeError('采集服务响应异常；不重复拉起') from e
 if d.get('service')!=service:raise RuntimeError('采集端口被其他服务占用，未启动新进程')
 return d

@contextmanager
def startup_lock(path):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a+b') as f:
  if f.seek(0,2)==0:f.write(b'0');f.flush()
  f.seek(0)
  if os.name=='nt':
   import msvcrt
   msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
  else:
   import fcntl
   fcntl.flock(f.fileno(),fcntl.LOCK_EX)
  try:yield
  finally:
   f.seek(0)
   if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)

def ensure_service(url,service,command,cwd,log_path,timeout=25):
 log_path=Path(log_path)
 with startup_lock(log_path.with_suffix('.startup.lock')):
  state=probe(url,service)
  if state is not None:return {'mode':'reused','health':state}
  log_path.parent.mkdir(parents=True,exist_ok=True)
  opts={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
  with log_path.open('ab') as log:
   child=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,**opts)
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   state=probe(url,service)
   if state is not None:return {'mode':'started','health':state,'launcher_pid':child.pid}
   if child.poll() is not None:raise RuntimeError('采集桥启动退出；请查看 '+str(log_path))
   time.sleep(.25)
  raise RuntimeError('采集桥尚未就绪；请查看 '+str(log_path)+'，不要重复启动')
