"""P25 silent-entry orchestrator: auto-discovered host + featureless ghost.

Differences from p21 (p20 chain):
- discovers the host SANPK wine PID and join target automatically via
  p23_read_host_ip.py (no manual IP/PID steps after a room rebuild)
- child is p24_cmd2_featureless_probe.py: cmd2 with b=2 and text=<machine
  name> so the ghost's host row is byte-identical to real clients' rows
  (w4=2, L+0a filled) instead of the minimal w4=1 / empty-text row
- child retries OpenSession and waits for the host app before its first
  cmd2, so a join fired right after room creation never burns attempts

Usage (on the vkquant Mac): python3 p25_orchestrate.py [hold_seconds]
  - discovers the host, then starts the p1 driver with the p24 child
  - starts p4_host_watch against the discovered host PID
  - fires the child's cmd23 only when the trigger file appears:
        touch <wineprefix>/drive_c/trigger-p20   (same convention as p21)
Evidence -> ~/sgi-protocol-lab-20260915/evidence/p24-silent-entry-<date>/
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home/'sgi-protocol-lab-20260915'
datestamp = time.strftime('%Y%m%d')
ev = lab/f'evidence/p24-silent-entry-{datestamp}'
ev.mkdir(parents=True, exist_ok=True)
rt = json.loads((home/'Library/Application Support/SGI-Wine/runtime.json').read_text())
trigger_win = 'C:\\trigger-p20'
trigger_host = Path(rt['prefix'])/'drive_c'/'trigger-p20'
if trigger_host.exists():
    trigger_host.unlink()

hold = 86400
for a in sys.argv[1:]:
    if not a.startswith('--'):
        hold = int(a)

WINE_ENV = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
                DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])


def wine_probe(script, pid='', timeout=150):
    args = [rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'), '-X', 'utf8',
            str(lab/script)]
    if pid:
        args.append(str(pid))
    return subprocess.run(args, env=WINE_ENV, capture_output=True,
                          timeout=timeout, text=True).stdout


def find_host():
    """Find the room host via the read-only win32 enumeration probe."""
    out = (wine_probe('p26_find_host.py') or '{}')
    try:
        disc = json.loads(out)
    except Exception:
        disc = {}
    hosts = [h for h in disc.get('hosts', [])
             if h.get('host_ip') and h.get('session_name')]
    if not hosts:
        return None, disc.get('all', [])
    return hosts[0], disc.get('all', [])


host, candidates = find_host()
(ev/'host_discovery.json').write_text(
    json.dumps({'picked': host, 'candidates': candidates},
               ensure_ascii=False, indent=1))
if not host:
    print(json.dumps({'abort': 'no_host_found'}))
    sys.exit(2)
host_pid = host['pid']
target = host['host_ip']
session_name = host.get('session_name') or 'SGZWLB'
print(json.dumps({'host_pid': host_pid, 'target': target,
                  'session_name': session_name}), flush=True)

env = dict(os.environ, P2_CHILD_SCRIPT='p24_cmd2_featureless_probe.py',
           P2_CHILD_ARGS=(f'--trigger {trigger_win} --fire-delay 15 '
                          f'--max-fires 3 --fire-gap 8 --hold {hold} '
                          f'--host-pid {host_pid} --verify-interval 3 '
                          f'--max-cmd2 12 --join-retries 30 --host-wait 600'),
           TRIGGER_PATH=trigger_win)
p1log = open(ev/'p1.json', 'w')
p1err = open(ev/'p1.stderr', 'w')
p1 = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
    '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
    '--target', target, '--loader-script', 'p2_loader_host.py',
    '--session-name', session_name, '--hold-seconds', str(hold),
    '--loader-timeout', str(hold + 120)],
    stdout=p1log, stderr=p1err, env=env)

watch_env = dict(WINE_ENV)
watch = subprocess.Popen([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p4_host_watch.py'), str(host_pid),
    '--interval', '5', '--duration', str(hold + 60), '--out', str(ev/'host_watch.jsonl')],
    env=watch_env, stdout=open(ev/'watch.stdout', 'w'),
    stderr=open(ev/'watch.stderr', 'w'))

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
hc = subprocess.run([rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'),
    '-X', 'utf8', str(lab/'p3_host_read.py'), str(host_pid)],
    env=WINE_ENV, capture_output=True, timeout=90, text=True)
(ev/'host_check_after.json').write_text(hc.stdout)
summary = {'host_pid': host_pid, 'target': target, 'driver_rc': p1.returncode,
           'watch_rc': watch.returncode, 'host_alive_after': hc.returncode == 0,
           'trigger_host_path': str(trigger_host),
           'elapsed': round(time.monotonic()-t0)}
(ev/'summary.json').write_text(json.dumps(summary))
print(json.dumps(summary))
