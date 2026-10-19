"""Run the protocol experiment ONLY on the explicitly authorized second Mac."""
from pathlib import Path
import subprocess
import sys

HOST = 'vkquant@fd7a:115c:a1e0::f930:8943'
ROOT = Path(__file__).resolve().parent
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', HOST]
name = sys.argv[1] if len(sys.argv) > 1 else 'koeinm_probe.py'
assert name in ('koeinm_probe.py', 'monitor_inspect.py', 'monitor_net_read.py')
source = (ROOT / name).read_text()
code = '''import sys,subprocess,json
from pathlib import Path
home=Path.home()
assert home == Path('/Users/vkquant')
sys.path.insert(0,str(home/'Library/Application Support/SGI-Room-Monitor/opt'))
from sgi_room_monitor.provision import wine_env,default_paths
wine=default_paths()['wine']
prefix=home/'Library/Application Support/SGI-Wine/prefix-monitor'
lab=home/'sgi-protocol-lab-20260915'
lab.mkdir(exist_ok=True)
'''
code += 'name=' + repr(name) + '\n'
code += '(lab/name).write_text(' + repr(source) + ')\n'
code += 'flags=' + repr(sys.argv[2:]) + '\n'
code += '''
python = lab/'python32/python.exe'
if '--wine81' in flags:
 flags.remove('--wine81')
 assert name == 'koeinm_probe.py'
 import shutil
 python=lab/'python32/sgi-protocol-probe.exe'
 if not python.exists(): shutil.copy2(lab/'python32/python.exe',python)
 registry_code="import winreg; k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\\Wine\\AppDefaults\\sgi-protocol-probe.exe'); winreg.SetValueEx(k,'Version',0,winreg.REG_SZ,'win81'); k.Close()"
 subprocess.run([str(wine),str(home/'Applications/SGI-Hub/bridge/python/python.exe'),'-c',registry_code],env=wine_env(wine,prefix),check=True,capture_output=True,timeout=15)
if name != 'koeinm_probe.py':
 python = home/'Applications/SGI-Hub/bridge/python/python.exe'
cmd=[str(wine),str(python),'-X','utf8','-B',str(lab/name)]
if name == 'koeinm_probe.py':
 cmd += ['--dll',str(prefix/'drive_c/sgi/run-3.5/3I/Koeinm.dll')]
cmd += flags
p=subprocess.Popen(cmd,env=wine_env(wine,prefix),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try: out,err=p.communicate(timeout=25)
except subprocess.TimeoutExpired:
 p.kill();out,err=p.communicate();print('PROBE_TIMEOUT')
print(out);print('stderr',err[-2000:]);print('exit',p.returncode)
record={'command':cmd,'stdout':out,'stderr':err,'returncode':p.returncode}
import time
(lab/(name+'.'+str(time.time_ns())+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
raise SystemExit(p.returncode)
'''
r = subprocess.run(SSH + ['/usr/bin/python3 -'], input=code, text=True, capture_output=True, timeout=40)
print(r.stdout)
print(r.stderr)
raise SystemExit(r.returncode)
