"""P20 verified-restart orchestrator: host watch + p1 driver with p16_cmd2 child.

Ghost joins 丁满's rebuilt room and holds the seat for --hold seconds
(default 86400 = one day): no per-run hall churn, no 10-minute pressure.
Only the trigger file ends the wait (host operator starts the game).

Usage (on the vkquant Mac): python3 p18_orchestrate.py [hold_seconds]
  - starts the p1 driver (child joins via OpenSession and holds)
  - starts p4_host_watch against host wine PID 680
  - fires the child only when the trigger file appears:
        touch <wineprefix>/drive_c/trigger-p20   (from any mac shell)
Evidence -> ~/sgi-protocol-lab-20260915/evidence/p20-verified-restart-20261014/
"""
import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home/'sgi-protocol-lab-20260915'
ev = Path(os.environ.get('P21_EVIDENCE_DIR', str(lab/'evidence/p20-verified-restart-20261014')))
ev.mkdir(parents=True, exist_ok=True)
rt = json.loads((home/'Library/Application Support/SGI-Wine/runtime.json').read_text())
trigger_host = Path(rt['prefix'])/'drive_c'/'trigger-p20'
# The child runs in prefix-monitor, whose C: differs from the game prefix.
# Z: is shared across both Wine instances; preserve spaces via JSON argv.
trigger_win = 'Z:' + str(trigger_host).replace('/', '\\')
if trigger_host.exists():
    trigger_host.unlink()

hold = int(sys.argv[1]) if len(sys.argv) > 1 else 86400
env = dict(os.environ, P2_CHILD_SCRIPT='p20_cmd2_verified_probe.py',
           P2_CHILD_ARGS_JSON=json.dumps([
               '--trigger', trigger_win, '--fire-delay', '15',
               '--max-fires', '3', '--fire-gap', '8', '--hold', str(hold),
               '--host-pid', '680', '--verify-interval', '3', '--max-cmd2', '12']),
           TRIGGER_PATH=trigger_win,
           P20_LOG_PATH='Z:' + str(ev/'p20_live.jsonl').replace('/', '\\'))
(ev/'run_identity.json').write_text(json.dumps({
    'orchestrator_pid': os.getpid(), 'wall': time.time(),
    'trigger_host': str(trigger_host), 'trigger_child': trigger_win,
    'host_prefix': rt['prefix'], 'child_prefix': str(home/'Library/Application Support/SGI-Wine/prefix-monitor'),
    'host_pid': 680, 'registration_max_cmd2': 12, 'cmd23_sender': 'watchdog_only',
    'source_sha256': {n: hashlib.sha256((lab/n).read_bytes()).hexdigest()
                      for n in ('p21_orchestrate.py', 'p20_cmd2_verified_probe.py', 'p2_loader_host.py')}
}, ensure_ascii=False, indent=2))
p1log = open(ev/'p1.json', 'w')
p1err = open(ev/'p1.stderr', 'w')
p1 = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
    '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
    '--target', '10.14.211.144', '--loader-script', 'p2_loader_host.py',
    '--session-name', 'SGZWLB', '--hold-seconds', str(hold),
    '--loader-timeout', str(hold + 120)],
    stdout=p1log, stderr=p1err, env=env)

watch_env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                 DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
watch = subprocess.Popen([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p4_host_watch.py'), '680',
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
    '-X', 'utf8', str(lab/'p3_host_read.py'), '680'],
    env=hostcheck_env, capture_output=True, timeout=90, text=True)
(ev/'host_check_after.json').write_text(hc.stdout)
summary = {'driver_rc': p1.returncode, 'watch_rc': watch.returncode,
           'host_alive_after': hc.returncode == 0,
           'trigger_host_path': str(trigger_host),
           'elapsed': round(time.monotonic()-t0)}
(ev/'summary.json').write_text(json.dumps(summary))
print(json.dumps(summary))
