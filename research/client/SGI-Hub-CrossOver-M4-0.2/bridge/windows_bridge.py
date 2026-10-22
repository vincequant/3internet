"""Run inside the SAME CrossOver bottle as SANPK, using Windows Python."""
import os,sys,json,ctypes,threading,time,socket
from pathlib import Path
from ctypes import wintypes as W
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from datetime import datetime,timezone
from player_identity import PlayerIdentity
from recovery import RecoveryController,SERVICE,FRESH_WINDOW_S,compute_fresh
from state_history import History, attach_history, default_root
from game_archive import GameArchiveRecorder
from player_observations import PlayerObservationJournal
from network_payload_worker import PayloadCapture
from match_opening import KEEP_MIN_FRAMES
from replay_training import read_capture_config
from bridge_bind import bind_servers
from command_transport import SourceCommandExporter

def offer_war(observed,recorder):
 from war_sync import get_shared_uploader
 uploader=get_shared_uploader()
 if not uploader:return
 uploader.offer_live(observed,recorder.public_status())

def find_game():
 k=ctypes.WinDLL('kernel32',use_last_error=True)
 class Entry(ctypes.Structure):
  _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]
 k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];k.CreateToolhelp32Snapshot.restype=W.HANDLE
 k.Process32FirstW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
 k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
 k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
 k.GetProcessTimes.argtypes=[W.HANDLE]+[ctypes.POINTER(W.FILETIME)]*4;k.GetProcessTimes.restype=W.BOOL
 k.CloseHandle.argtypes=[W.HANDLE]
 h=k.CreateToolhelp32Snapshot(2,0);e=Entry();e.dwSize=ctypes.sizeof(e);found=[]
 if h==ctypes.c_void_p(-1).value:raise RuntimeError('无法枚举当前Bottle进程')
 try:
  ok=k.Process32FirstW(h,ctypes.byref(e))
  while ok:
   if e.szExeFile.lower()=='sanpk.exe':
    process=k.OpenProcess(0x1000,False,e.th32ProcessID)
    if process:
     try:
      buf=ctypes.create_unicode_buffer(32768);length=W.DWORD(len(buf))
      if k.QueryFullProcessImageNameW(process,0,buf,ctypes.byref(length)):
       ft=[W.FILETIME() for _ in range(4)]
       ticks=None;created=None
       if k.GetProcessTimes(process,*[ctypes.byref(t) for t in ft]):
        ticks=(ft[0].dwHighDateTime<<32)|ft[0].dwLowDateTime
        created=datetime.fromtimestamp(ticks/1e7-11644473600,timezone.utc).isoformat()
       found.append({'pid':e.th32ProcessID,'path':buf.value,'creation_filetime':ticks,'created_utc':created})
     finally:k.CloseHandle(process)
   ok=k.Process32NextW(h,ctypes.byref(e))
 finally:k.CloseHandle(h)
 if not found:return {'status':'none','instances':[]}
 if len(found)!=1:return {'status':'multiple','instances':found}
 return {'status':'ok','instances':found}

def publish_payload(raw,now=None):
 data=dict(raw)
 snap=data.get('state')
 data['fresh']=compute_fresh(data.get('fresh'),data.get('error'),snap,now,FRESH_WINDOW_S)
 if snap and snap.get('capture_end'):
  try:
   age=( (now or datetime.now(timezone.utc)) - datetime.fromisoformat(snap['capture_end']) ).total_seconds()
   data['snapshot_age_s']=age
  except (TypeError,ValueError):
   data['snapshot_age_s']=None
 else:
  data['fresh']=False
 return data

def main():
 os.environ.setdefault('SGI_GAME_EXE',r'C:\sgi\run-3.5\3I\SANPK.exe')
 from collector import Collector
 from runtime_image import configure
 def configure_game(pid,path):
  os.environ['SGI_GAME_EXE']=path;return configure(pid,path)
 controller=RecoveryController(find_game,configure_game,Collector,expected_path=os.environ['SGI_GAME_EXE'])
 player=PlayerIdentity()
 journal=History(default_root())
 recorder=GameArchiveRecorder(keep_min_frames=KEEP_MIN_FRAMES)
 observations=PlayerObservationJournal()
 training_config_error=None
 try:training_config=read_capture_config(Path(__file__).resolve().parent.parent)
 except (ValueError,TypeError,OSError) as error:
  training_config=None;training_config_error=str(error)
 training_recorder=(GameArchiveRecorder(root=Path(__file__).resolve().parent.parent/'training-archives',
                     keep_formats=None,keep_min_frames=0,training_context=training_config)
                    if training_config is not None else None)
 release=json.loads((Path(__file__).resolve().parent.parent/'RELEASE.json').read_text(encoding='utf8'))
 source_id=os.environ.get('SGI_SOURCE_ID',socket.gethostname())
 state={'service':SERVICE,'fresh':False,'state':None,'error':'starting','phase':'waiting_for_game'};lock=threading.Lock();stop=threading.Event()
 payload_capture=PayloadCapture(root=Path(__file__).resolve().parent.parent)
 command_exporter=SourceCommandExporter()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_GET(self):
   if self.path not in ('/api/state','/health'):return self.send_error(404)
   with lock:data=player.observe(publish_payload(state))
   data.update(protocol_version=1,release_version=release['version'],source_id=source_id,collector_pid=os.getpid(),read_only_endpoint=self.server.server_port==8770,
               runtime_id=os.environ.get('SGI_RUNTIME_ID','default'),replay_archive=recorder.public_status(),
               player_observations=observations.public_status(),native_payload_observations=payload_capture.public_status())
   data['training_archive']=(dict(training_recorder.public_status(),enabled=True) if training_recorder
                             else {'enabled':False,'configuration_error':training_config_error})
   if self.path=='/health':data.pop('state',None)
   elif self.server.server_port==8770:data=command_exporter.attach(data)
   body=json.dumps(data,ensure_ascii=False).encode('utf8');self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  def do_POST(self):
   if self.server.server_port==8770:return self.send_error(403,'Read-only endpoint')
   if self.path!='/api/player':return self.send_error(404)
   if self.headers.get('Origin') or self.headers.get('Content-Type')!='application/json':return self.send_error(403)
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<4096:raise ValueError('invalid request size')
    request=json.loads(self.rfile.read(length))
    with lock:
     current=player.observe(publish_payload(state))
     data=attach_history(player.confirm(current,request.get('session_id'),request.get('force_id'),request.get('source','user_confirmed')),journal)
     state.clear();state.update(data)
    data=dict(data);data.pop('state',None)
    body=json.dumps(data,ensure_ascii=False).encode('utf8')
    self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   except (ValueError,KeyError,TypeError) as error:
    body=json.dumps({'error':str(error)},ensure_ascii=False).encode('utf8')
    self.send_response(409);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 server=remote_server=thread=None
 thread_started=remote_thread_started=False
 def collect():
  try:
   while not stop.is_set():
    wait=controller.step()
    pub=controller.public_state()
    ctx=(pub.get('state') or {}).get('player_context') or {}
    if pub.get('phase')=='live' and ctx.get('slot')==-1:
     pub.update(phase='waiting_for_player',fresh=False)
    with lock:
     observed=player.observe(pub)
     if observed.get('state'):
      observed=attach_history(observed,journal)
     state.clear();state.update(observed)
    observed['source_id']=source_id
    observed['runtime_id']=os.environ.get('SGI_RUNTIME_ID','default')
    observed['release_version']=release['version']
    payload_capture.update(observed)
    recorder.ingest(observed)
    if training_recorder:training_recorder.ingest(observed)
    try:observations.ingest(observed)
    except Exception:pass
    try:
     offer_war(observed,recorder)
    except Exception:
     pass
    stop.wait(wait if wait and wait>0 else 0.2)
  except Exception as error:
   with lock:state.update(fresh=False,error=str(error),phase='error',error_class='unknown')
   print('采集失败：',error,flush=True)
  finally:
   payload_capture.update(None)
   controller.release(forget_configure=True)
 try:
  server,remote_server=bind_servers(Handler)
  if remote_server is not None:
   remote_thread=threading.Thread(target=remote_server.serve_forever,daemon=True)
   remote_thread.start();remote_thread_started=True
  payload_capture.start()
  thread=threading.Thread(target=collect,daemon=True)
  thread.start();thread_started=True
  print('只读采集桥：自动重绑定 http://127.0.0.1:8769/health',flush=True)
  server.serve_forever()
 finally:
  stop.set()
  if thread_started:thread.join(3)
  payload_capture.close();recorder.close('collector_stop');observations.close()
  if training_recorder:training_recorder.close('collector_stop')
  if remote_server is not None:
   if remote_thread_started:remote_server.shutdown()
   remote_server.server_close()
  if server is not None:server.server_close()
  controller.release(forget_configure=True)
if __name__=='__main__':
 try:main()
 except Exception:
  import traceback;traceback.print_exc();input('采集桥失败；按回车退出。')
