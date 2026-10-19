"""Bounded P28 capture session. Discover the Win32 host; one existing watch.

No cmd23 trigger or automatic ready. Credentials stay in the P1/P2 flow.
Refuses to launch while another research chain is present.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time


def json_lines(path):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass  # a writer may be midway through the final line
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hold', type=int, default=3600)
    ap.add_argument('--ready', action='store_true')
    args = ap.parse_args()
    assert 60 <= args.hold <= 86400
    lab = Path.home()/'sgi-protocol-lab-20260915'
    lock = (lab/'p29-receive.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ps = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    forbidden = {'p1_directed_probe.py', 'p2_loader_host.py', 'p4_host_watch.py',
                 'p20_cmd2_verified_probe.py', 'p24_cmd2_featureless_probe.py',
                 'p21_orchestrate.py', 'p25_orchestrate.py', 'p28_receive_probe.py'}
    for line in ps.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name
                 for v in shlex.split(parts[1], posix=False)}
        if names & forbidden:
            raise RuntimeError('existing_research_chain_pid_'+parts[0])
    root = lab/'evidence/p28-window-receive-20261015'
    ev = root/('run-'+time.strftime('%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    rt = json.loads((Path.home()/'Library/Application Support/SGI-Wine/runtime.json').read_text())
    env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
               DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
    wine = [rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'), '-X', 'utf8']
    disc = subprocess.run(wine+[str(lab/'p26_find_host.py')], env=env,
                          capture_output=True, text=True, timeout=30)
    (ev/'host_discovery.stdout').write_text(disc.stdout)
    (ev/'host_discovery.stderr').write_text(disc.stderr)
    data = json.loads(disc.stdout)
    hosts = [h for h in data['hosts'] if h.get('host_name') == '丁满']
    if disc.returncode or len(hosts) != 1:
        raise RuntimeError('host_discovery_not_unique')
    host = hosts[0]
    mode = 'ready_on_valid_cmd7' if args.ready else 'capture_only'
    sources = ('p29_receive_orchestrate.py', 'p28_receive_probe.py', 'p28_window.py', 'p30_ready.py',
               'p28_wire.py', 'p20_cmd2_verified_probe.py', 'p2_loader_host.py',
               'p1_directed_probe.py', 'p4_host_watch.py', 'p26_find_host.py')
    identity = {'wall': time.time(), 'orchestrator_pid': os.getpid(),
                'host_pid': host['pid'], 'host': host, 'mode': mode,
                'hold_seconds': args.hold, 'collector_log': 'p28_live.jsonl',
                'cmd23_sender': None, 'automatic_ready': args.ready,
                'registration_max_cmd2': 1,
                'source_sha256': {s: hashlib.sha256((lab/s).read_bytes()).hexdigest() for s in sources}}
    (ev/'run_identity.json').write_text(json.dumps(identity, ensure_ascii=False, indent=2))
    (ev/'sources').mkdir()
    for source in sources:
        (ev/'sources'/source).write_bytes((lab/source).read_bytes())
    pointer = {'evidence': str(ev), 'wall': time.time(), 'orchestrator_pid': os.getpid(),
               'collector': 'p28_receive_probe.py', 'mode': mode}
    (root/'active-run.json').write_text(json.dumps(pointer))
    # Compatibility pointer for the local status Hub; actual log comes from identity.
    (lab/'evidence/p27-start-preflight-20261015/active-run.json').write_text(json.dumps(pointer))
    child_log = 'Z:'+str(ev/'p28_live.jsonl').replace('/', '\\')
    child_err = 'Z:'+str(ev/'p28.stderr').replace('/', '\\')
    child_env = dict(os.environ, P2_CHILD_SCRIPT='p28_receive_probe.py',
                     P2_CHILD_ARGS_JSON=json.dumps(['--log', child_log,
                         '--gate-file', 'Z:'+str(ev/'register-gate.json').replace('/', '\\'),
                         '--stop-file', 'Z:'+str(ev/'stop-p28').replace('/', '\\')]+(['--ready'] if args.ready else [])),
                     P2_CHILD_STDERR=child_err)
    driver = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
        '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
        '--target', host['host_ip'], '--loader-script', 'p2_loader_host.py',
        '--session-name', host['session_name'], '--hold-seconds', str(args.hold),
        '--loader-timeout', str(args.hold+120)], env=child_env,
        stdout=(ev/'p1.json').open('w'), stderr=(ev/'p1.stderr').open('w'), start_new_session=True)
    watch = subprocess.Popen(wine+[str(lab/'p4_host_watch.py'), str(host['pid']),
        '--interval', '5', '--duration', str(args.hold+60), '--out', str(ev/'host_watch.jsonl')],
        env=env, stdout=(ev/'watch.stdout').open('w'), stderr=(ev/'watch.stderr').open('w'))
    (ev/'processes.json').write_text(json.dumps({'driver_pid': driver.pid,
        'watch_pid': watch.pid, 'orchestrator_pid': os.getpid()}))
    print(json.dumps({'evidence': str(ev), 'host': host, 'driver_pid': driver.pid,
                      'watch_pid': watch.pid, 'mode': mode}), flush=True)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        deadline = time.monotonic()+args.hold+180
        gate_written = False
        while driver.poll() is None and time.monotonic() < deadline:
            if not gate_written and (ev/'p28_live.jsonl').exists():
                logs = json_lines(ev/'p28_live.jsonl')
                pending = next((r for r in logs if r['ev'] == 'waiting_host_gate'), None)
                if pending and (ev/'host_watch.jsonl').exists():
                    watched = json_lines(ev/'host_watch.jsonl')
                    if not watched:
                        time.sleep(1)
                        continue
                    last = watched[-1]
                    members = [m for m in last.get('members', [])
                               if m['name'] == '风夜' and int(m['id']) == pending['own_id']]
                    if len(members) == 1 and 0 <= time.time()-last['wall'] <= 6:
                        row = members[0]
                        receipt = {'own_id': pending['own_id'], 'host_id': host['host_id'],
                                   'observed_at': last['wall'], 'host_sB': row['seq_28'],
                                   'next_seq': row['seq_28']+1, 'source': 'host_watch.jsonl'}
                        temp = ev/'register-gate.tmp'
                        temp.write_text(json.dumps(receipt), encoding='utf-8')
                        temp.replace(ev/'register-gate.json')
                        gate_written = True
            time.sleep(1)
    finally:
        if driver.poll() is None:
            os.killpg(driver.pid, signal.SIGTERM)  # only this owned research group
            try:
                driver.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, signal.SIGKILL)
        if watch.poll() is None:
            watch.terminate()
            try:
                watch.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watch.kill()
        (ev/'summary.json').write_text(json.dumps({'wall': time.time(),
            'driver_rc': driver.poll(), 'watch_rc': watch.poll(), 'mode': mode}))


if __name__ == '__main__':
    main()
