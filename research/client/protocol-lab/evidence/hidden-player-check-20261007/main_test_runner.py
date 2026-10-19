from pathlib import Path
import json,subprocess,os,sys,tempfile
ROOT=Path(__file__).resolve().parents[5]
BASE=Path.home()/'Library/Application Support/SGI-Wine'
rt=json.loads((BASE/'runtime.json').read_text());assert Path(rt['prefix']).name=='prefix-sikarugir10'
env=dict(os.environ,WINEPREFIX=rt['prefix'],WINEDEBUG='-all',DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'],WINEDLLOVERRIDES='winegstreamer=d;winemenubuilder.exe=d',LANG='zh_CN.UTF-8',LC_ALL='zh_CN.UTF-8')
for key in ['DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH','CX_BOTTLE','CX_ROOT','WINESERVER','WINELOADER','WINEDLLPATH']:env.pop(key,None)
CLIENT=ROOT/'research/client/SGI-Hub-CrossOver-M4-0.2'
helper=CLIENT/'room_monitor/sgi_room_monitor/wine_lobby_ops.py'
python=CLIENT/'bridge/win32-python/python.exe'
assert helper.exists() and python.exists()
cred_path=None
try:
 if '--login' in sys.argv[1:]:
  sys.path.insert(0,str(CLIENT/'room_monitor'))
  from sgi_room_monitor.credentials import load_credentials
  creds=load_credentials({'main_account_username':rt['main_account_username'],'data_dir':str(BASE)},kind='main',prompt=False)
  assert creds['username']==rt['main_account_username'] and creds['password']
  fd,cred_path=tempfile.mkstemp(prefix='sgi-main-test-auth-',suffix='.json');os.fchmod(fd,0o600)
  with os.fdopen(fd,'w') as f:json.dump(creds,f)
  del creds;env['SGI_MONITOR_CRED_FILE']=cred_path
 r=subprocess.run([rt['wine'],str(python),'-X','utf8',str(helper)]+sys.argv[1:],env=env,capture_output=True,text=True,timeout=25)
 name='main-'+('-'.join(x.strip('-').replace('/','_') for x in sys.argv[1:]) or 'inspect')
 (Path(__file__).parent/(name+'.jsonl')).write_text(r.stdout)
 for line in r.stdout.splitlines():
  if line.startswith('{'):
   v=json.loads(line)
   print(json.dumps({k:v[k] for k in ['status','message','titles','login','logged_in','captcha','trees','lists','has_start','game_select','game_windows','sanpk_running'] if k in v},ensure_ascii=False))
 print(json.dumps({'returncode':r.returncode,'stderr':r.stderr[-1500:]}))
finally:
 if cred_path:Path(cred_path).unlink(missing_ok=True)
