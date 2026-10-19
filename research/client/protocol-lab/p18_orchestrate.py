"""P18 permanent-seat orchestrator: host watch + p1 driver with p16_cmd2 child.

Ghost joins 丁满's rebuilt room and holds the seat for --hold seconds
(default 86400 = one day): no per-run hall churn, no 10-minute pressure.
Only the trigger file ends the wait (host operator starts the game).

Usage (on the vkquant Mac): python3 p18_orchestrate.py [hold_seconds]
  - starts the p1 driver (child joins via OpenSession and holds)
  - starts p4_host_watch against host wine PID 668
  - fires the child only when the trigger file appears:
        touch <wineprefix>/drive_c/trigger-p15   (from any mac shell)
Evidence -> ~/sgi-protocol-lab-20260915/evidence/p18-permanent-seat-20261014/
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home/'sgi-protocol-lab-20260915'
ev = lab/'evidence/p18-permanent-seat-20261014'
ev.mkdir(parents=True, exist_ok=True)
rt = json.loads((home/'Library/Application Support/SGI-Wine/runtime.json').read_text())
trigger_win = 'C:\\trigger-p15'
trigger_host = Path(rt['prefix'])/'drive_c'/'trigger-p15'
if trigger_host.exists():
    trigger_host.unlink()

hold = int(sys.argv[1]) if len(sys.argv) > 1 else 86400
env = dict(os.environ, P2_CHILD_SCRIPT='p16_cmd2_register_probe.py',
           P2_CHILD_ARGS=(f'--trigger {trigger_win} --fire-delay 15 '
                          f'--max-fires 3 --fire-gap 8 --hold {hold}'),
           TRIGGER_PATH=trigger_win)
p1log = open(ev/'p1.json', 'w')
p1err = open(ev/'p1.stderr', 'w')
p1 = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
    '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
    '--target', '10.152.13.122', '--loader-script', 'p2_loader_host.py',
    '--session-name', 'SGZWLB', '--hold-seconds', str(hold),
    '--loader-timeout', str(hold + 120)],
    stdout=p1log, stderr=p1err, env=env)

watch_env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                 DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
watch = subprocess.Popen([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p4_host_watch.py'), '668',
    '--interval', '5', '--duration', str(hold + 60), '--out', str(ev/'host_watch.jsonl')],
    env=watch_env, stdout=open(ev/'watch.stdout', 'w'), stderr=open(ev/'watch.stderr', 'w'))

t0 = time.monotonic()
while p1.poll() is None and time.monotonic() - t0 < hold + 100:
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
    '-X', 'utf8', str(lab/'p3_host_read.py'), '668'],
    env=hostcheck_env, capture_output=True, timeout=90, text=True)
(ev/'host_check_after.json').write_text(hc.stdout)
summary = {'driver_rc': p1.returncode, 'watch_rc': watch.returncode,
           'host_alive_after': hc.returncode == 0,
           'trigger_host_path': str(trigger_host),
           'elapsed': round(time.monotonic()-t0)}
(ev/'summary.json').write_text(json.dumps(summary))
print(json.dumps(summary))
