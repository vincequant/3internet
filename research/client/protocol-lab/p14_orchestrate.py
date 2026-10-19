"""P14 A/B orchestrator: host watch + p1 driver with p14_abtest child.

Usage: python3 p14_orchestrate.py
Evidence -> ~/sgi-protocol-lab-20260915/evidence/p14-abtest-20261014/
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home/'sgi-protocol-lab-20260915'
ev = lab/'evidence/p14-abtest-20261014'
ev.mkdir(parents=True, exist_ok=True)
rt = json.loads((home/'Library/Application Support/SGI-Wine/runtime.json').read_text())
env = dict(os.environ, P2_CHILD_SCRIPT='p14_abtest_probe.py')
p1log = open(ev/'p1.json', 'w')
p1err = open(ev/'p1.stderr', 'w')
p1 = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
    '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
    '--target', '10.82.171.21', '--loader-script', 'p2_loader_host.py',
    '--session-name', 'SGZWLB', '--hold-seconds', '30', '--loader-timeout', '150'],
    stdout=p1log, stderr=p1err, env=env)

watch_env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                 DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
watch = subprocess.Popen([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p4_host_watch.py'), '732',
    '--interval', '1', '--duration', '180', '--out', str(ev/'host_watch.jsonl')],
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
hostcheck_env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                     DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
hc = subprocess.run([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p3_host_read.py'), '732'],
    env=hostcheck_env, capture_output=True, timeout=90, text=True)
(ev/'host_check_after.json').write_text(hc.stdout)
summary = {'driver_rc': p1.returncode, 'watch_rc': watch.returncode,
           'host_alive_after': hc.returncode == 0,
           'host_read_after': hc.stdout.strip()[:600],
           'elapsed': round(time.monotonic()-t0)}
(ev/'summary.json').write_text(json.dumps(summary))
print(json.dumps(summary))
