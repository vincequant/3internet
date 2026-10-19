from pathlib import Path
import subprocess,json,os
rt=json.loads((Path.home()/'Library/Application Support/SGI-Wine/runtime.json').read_text());lab=Path.home()/'sgi-protocol-lab-20260915'
env=dict(os.environ,WINEPREFIX=rt['prefix'],WINEDEBUG='-all',DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
for name in ['read_host_members_20261007.py','read_host_slots_20261007.py']:
 r=subprocess.run([rt['wine'],str(lab/'python32/sgi-protocol-probe.exe'),'-X','utf8',str(lab/name)],env=env,capture_output=True,text=True,timeout=20)
 print(json.dumps({'script':name,'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr},ensure_ascii=False))
