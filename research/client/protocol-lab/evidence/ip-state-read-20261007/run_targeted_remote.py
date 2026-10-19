from pathlib import Path
import subprocess,os,json,shutil
p=Path.home()/"sgi-protocol-lab-20260915"
cfg=json.loads((Path.home()/"Library/Application Support/SGI-Wine/runtime.json").read_text())
env=dict(os.environ,WINEPREFIX=cfg['prefix'],WINEDEBUG='-all')
exe=p/'python32/sgi-ip-read-probe-20261007.exe'
assert not exe.exists()
shutil.copy2(p/'python32/python.exe',exe)
key=r'Software\Wine\AppDefaults\sgi-ip-read-probe-20261007.exe'
registry_set="import winreg; k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,"+repr(key)+"); winreg.SetValueEx(k,'Version',0,winreg.REG_SZ,'win81'); k.Close()"
registry_remove="import winreg; winreg.DeleteKey(winreg.HKEY_CURRENT_USER,"+repr(key)+")"
python=str(p/'python32/python.exe')
created=False
try:
 c=subprocess.run([cfg['wine'],python,'-c',registry_set],env=env,capture_output=True,text=True,timeout=15)
 assert c.returncode==0
 created=True
 r=subprocess.run([cfg['wine'],str(exe),'-X','utf8',str(p/'koeinm_probe.py'),'--dll',r'C:\sgi\run-3.5\3I\Koeinm.dll','--target','10.128.163.42','--port','7777','--app-id','78731','--with-nethook'],env=env,capture_output=True,text=True,timeout=20)
 print(json.dumps({'kind':'nethook_targeted_search','origin':'VKQUANT-COM','target':'10.128.163.42','shared_prefix_with_authenticated_host':True,'probe_relay_registration_verified':False,'reads_game_memory':False,'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr[:160]},ensure_ascii=False))
finally:
 if created:
  c=subprocess.run([cfg['wine'],python,'-c',registry_remove],env=env,capture_output=True,text=True,timeout=15)
  print(json.dumps({'probe_registry_removed':c.returncode==0}))
 exe.unlink(missing_ok=True)
