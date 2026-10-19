from pathlib import Path
import subprocess,sys,os,time,json,tempfile
p=Path.home()/"sgi-protocol-lab-20260915/hidden-player-test-20261007"
p.mkdir(exist_ok=True)
files={} # source files were sent separately; see source files in this evidence directory
for n,s in files.items(): (p/n).write_text(s)
sys.path.insert(0,str(Path.home()/"Library/Application Support/SGI-Room-Monitor/opt"))
from sgi_room_monitor.config import load_config
from sgi_room_monitor.credentials import load_credentials
cfg=load_config()
assert cfg['account_username']=='vinceost'
creds=load_credentials(cfg,prompt=False)
assert creds['username']=='vinceost' and creds['password']
runtime=json.loads((Path.home()/"Library/Application Support/SGI-Wine/runtime.json").read_text())
prefix=Path(cfg['monitor_prefix'])
assert prefix.name=='prefix-monitor'
processes=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
assert not any(x.startswith(str(prefix)) and x.lower().endswith(('/sanguo.exe','/sanpk.exe')) for x in processes)
env=dict(os.environ,WINEPREFIX=str(prefix),WINEDEBUG='-all',WINEDLLOVERRIDES='winegstreamer=d;winemenubuilder.exe=d')
fd,path=tempfile.mkstemp(prefix='sgi-guest-auth-',suffix='.json',dir=p)
os.fchmod(fd,0o600)
with os.fdopen(fd,'w') as f:json.dump(creds,f)
del creds
env['SGI_MONITOR_CRED_FILE']=path
if runtime.get('dependency_lib'):env['DYLD_FALLBACK_LIBRARY_PATH']=runtime['dependency_lib']
exe=prefix/'drive_c/sgi/run-3.5/SANGUO.exe'
python=Path.home()/'sgi-protocol-lab-20260915/python32/python.exe'
if runtime.get('dependency_lib'):env['DYLD_FALLBACK_LIBRARY_PATH']=runtime['dependency_lib']
proc=subprocess.Popen([runtime['wine'],str(exe)],env=env,cwd=exe.parent,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(json.dumps({'stage':'alt_lobby_started','launcher_pid':proc.pid,'account':'vinceost','prefix':str(prefix)}),flush=True)
def step(args):
 r=subprocess.run([runtime['wine'],str(python),'-X','utf8',str(p/'wine_lobby_ops.py')]+args,env=env,capture_output=True,text=True,timeout=20)
 print(json.dumps({'stage':'helper_result','args':args,'returncode':r.returncode,'stderr':r.stderr[-3000:]},ensure_ascii=False),flush=True)
 for line in r.stdout.splitlines():
  if line.startswith('{'):
   v=json.loads(line)
   if 'windows' in v:
    print(json.dumps({'stage':'inspect','status':v.get('status'),'has_login':v.get('login'),'has_start':v.get('has_start'),'titles':[x.get('title') for x in v['windows'] if x.get('title')],'tree':v.get('trees'),'lists':v.get('lists')},ensure_ascii=False),flush=True)
   else:print(json.dumps(v,ensure_ascii=False),flush=True)
try:
 time.sleep(5)
 step([])
 step(['--login'])
 time.sleep(4)
 step([])
finally:Path(path).unlink(missing_ok=True)
