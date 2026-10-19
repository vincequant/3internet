"""Deploy the two native experiment scripts and retain only sanitized output."""
import subprocess
import json
import time
from pathlib import Path

base = Path(__file__).resolve().parent
files = {name: (base/name).read_text() for name in ['login_protocol.py', 'native_login_probe.py', 'loader_probe.py', 'koeinm_probe.py']}
code = ('from pathlib import Path\nimport subprocess,sys\n'
        'p=Path.home()/"sgi-protocol-lab-20260915"\nfiles='+ascii(files)+'\n'
        'for n,s in files.items(): (p/n).write_text(s,encoding="utf-8")\n'
        'r=subprocess.run([sys.executable,str(p/"native_login_probe.py")],capture_output=True,text=True,timeout=45)\n'
        'print(r.stdout)\nraise SystemExit(r.returncode)\n')
r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                    'vkquant@fd7a:115c:a1e0::f930:8943', 'python3 -'],
                   input=code, text=True, capture_output=True, timeout=55)
for line in r.stdout.splitlines():
    if not line.startswith('{'):
        continue
    value = json.loads(line)
    print(json.dumps({k: value[k] for k in ['error_type', 'login_verified', 'enter_requested',
        'rooms', 'credentials_only_verified', 'query_status', 'elapsed_ms', 'observed_at'] if k in value}, ensure_ascii=False))
print(r.stderr)
(base/'evidence'/('native-'+str(time.time_ns())+'.txt')).write_text(r.stdout)
raise SystemExit(r.returncode)
