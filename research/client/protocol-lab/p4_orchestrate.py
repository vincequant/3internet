"""P4 orchestrator: host watch (1s JSONL) + p1 driver with p4_forge_frame child.

Usage: python3 p4_orchestrate.py [phases]   (default chat,o4i6,o6i6,o4i63)
Evidence -> ~/sgi-protocol-lab-20260915/evidence/p4-frame-20261013/
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home/'sgi-protocol-lab-20260915'
ev = lab/'evidence/p4-frame-20261013'
ev.mkdir(parents=True, exist_ok=True)
rt = json.loads((home/'Library/Application Support/SGI-Wine/runtime.json').read_text())
phases = sys.argv[1] if len(sys.argv) > 1 else 'chat,o4i6,o6i6,o4i63'
env = dict(os.environ, P2_CHILD_SCRIPT='p4_forge_frame.py',
           P2_CHILD_ARGS=f'--phases {phases}')
p1log = open(ev/'p1.json', 'w')
p1err = open(ev/'p1.stderr', 'w')
driver_env = dict(env)
driver_env.pop('P2_CHILD_SCRIPT', None)
driver_env.pop('P2_CHILD_ARGS', None)
p1 = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
    '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
    '--target', '10.82.171.21', '--loader-script', 'p2_loader_host.py',
    '--session-name', 'SGZWLB', '--hold-seconds', '40', '--loader-timeout', '150'],
    stdout=p1log, stderr=p1err, env=env)

watch_env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                 DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
watch = subprocess.Popen([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p4_host_watch.py'), '732',
    '--interval', '1', '--duration', '210', '--out', str(ev/'host_watch.jsonl')],
    env=watch_env, stdout=open(ev/'watch.stdout', 'w'), stderr=open(ev/'watch.stderr', 'w'))

t0 = time.monotonic()
while p1.poll() is None and time.monotonic() - t0 < 170:
    time.sleep(3)
try:
    p1.wait(timeout=30)
except Exception:
    p1.kill()
time.sleep(12)
if watch.poll() is None:
    watch.terminate()
    time.sleep(3)
watch.poll()
summary = {'driver_rc': p1.returncode, 'watch_rc': watch.returncode,
           'elapsed': round(time.monotonic()-t0)}
(ev/'summary.json').write_text(json.dumps(summary))
print(json.dumps(summary))
