from pathlib import Path
import json,subprocess,os,shutil
ROOT=Path(__file__).resolve().parents[5];lab=Path(__file__).resolve().parent
rt=json.loads((Path.home()/'Library/Application Support/SGI-Wine/runtime.json').read_text());client=ROOT/'research/client/SGI-Hub-CrossOver-M4-0.2';py=client/'bridge/win32-python/python.exe';exe=py.with_name('sgi-raw-discovery-20261007.exe');assert not exe.exists();shutil.copy2(py,exe)
env=dict(os.environ,WINEPREFIX=rt['prefix'],WINEDEBUG='-all',DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'],LANG='zh_CN.UTF-8',LC_ALL='zh_CN.UTF-8');key=r'Software\Wine\AppDefaults\sgi-raw-discovery-20261007.exe'
setup="import winreg; k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,"+repr(key)+"); winreg.SetValueEx(k,'Version',0,winreg.REG_SZ,'win81'); k.Close()"
cleanup="import winreg; winreg.DeleteKey(winreg.HKEY_CURRENT_USER,"+repr(key)+")"
created=False
try:
 r=subprocess.run([rt['wine'],str(py),'-c',setup],env=env,capture_output=True,text=True,timeout=10);assert r.returncode==0;created=True
 with (lab/'raw-discovery.jsonl').open('w') as out,(lab/'raw-discovery.stderr').open('w') as err:
  proc=subprocess.Popen([rt['wine'],str(exe),'-X','utf8',str(lab/'raw_nonjoining_search.py')],env=env,stdout=out,stderr=err)
  print(json.dumps({'stage':'probe_started','launcher_pid':proc.pid}),flush=True)
  try:rc=proc.wait(timeout=35)
  except subprocess.TimeoutExpired:proc.kill();rc=proc.wait()
 print(json.dumps({'stage':'probe_finished','exit':rc}),flush=True)
 print((lab/'raw-discovery.jsonl').read_text(),flush=True);print((lab/'raw-discovery.stderr').read_text()[-2000:],flush=True)
finally:
 if created:
  r=subprocess.run([rt['wine'],str(py),'-c',cleanup],env=env,capture_output=True,text=True,timeout=10);print(json.dumps({'probe_registry_removed':r.returncode==0}),flush=True)
 exe.unlink(missing_ok=True)
