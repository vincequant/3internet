"""P31 row-less join orchestration: one join probe, one existing host watch.

Discovery, relay driver, and monitor layout mirror p29_receive_orchestrate.py,
but the child probe (p31_rowless_probe.py) never sends cmd2/cmd9/cmd23 — the
whole run observes whether the DLL accepts a join that claims no application
row. Refuses to launch while another research chain is present.
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
    args = ap.parse_args()
    assert 60 <= args.hold <= 86400
    lab = Path.home()/'sgi-protocol-lab-20260915'
    lock = (lab/'p31-rowless.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ps = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    forbidden = {'p1_directed_probe.py', 'p2_loader_host.py', 'p4_host_watch.py',
                 'p20_cmd2_verified_probe.py', 'p24_cmd2_featureless_probe.py',
                 'p21_orchestrate.py', 'p25_orchestrate.py', 'p28_receive_probe.py',
                 'p29_receive_orchestrate.py', 'p31_rowless_probe.py'}
    for line in ps.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name
                 for v in shlex.split(parts[1], posix=False)}
        if names & forbidden:
            raise RuntimeError('existing_research_chain_pid_'+parts[0])
    root = lab/'evidence/p31-rowless-join-20261015'
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
    sources = ('p31_orchestrate.py', 'p31_rowless_probe.py', 'p28_window.py',
               'p20_cmd2_verified_probe.py', 'p2_loader_host.py',
               'p1_directed_probe.py', 'p4_host_watch.py', 'p26_find_host.py')
    identity = {'wall': time.time(), 'orchestrator_pid': os.getpid(),
                'host_pid': host['pid'], 'host': host,
                'mode': 'rowless_join_capture_only',
                'hold_seconds': args.hold, 'collector_log': 'p31_live.jsonl',
                'cmd23_sender': None, 'automatic_ready': False,
                'registration_cmd2': 'none_by_design',
                'source_sha256': {s: hashlib.sha256((lab/s).read_bytes()).hexdigest() for s in sources}}
    (ev/'run_identity.json').write_text(json.dumps(identity, ensure_ascii=False, indent=2))
    (ev/'sources').mkdir()
    for source in sources:
        (ev/'sources'/source).write_bytes((lab/source).read_bytes())
    pointer = {'evidence': str(ev), 'wall': time.time(), 'orchestrator_pid': os.getpid(),
               'collector': 'p31_rowless_probe.py', 'mode': 'rowless_join_capture_only'}
    (root/'active-run.json').write_text(json.dumps(pointer))
    child_log = 'Z:'+str(ev/'p31_live.jsonl').replace('/', '\\')
    child_err = 'Z:'+str(ev/'p31.stderr').replace('/', '\\')
    child_env = dict(os.environ, P2_CHILD_SCRIPT='p31_rowless_probe.py',
                     P2_CHILD_ARGS_JSON=json.dumps(['--log', child_log,
                         '--stop-file', 'Z:'+str(ev/'stop-p31').replace('/', '\\')]),
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
                      'watch_pid': watch.pid}), flush=True)

    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    receipt_written = False
    verdict_written = False
    try:
        deadline = time.monotonic()+args.hold+180
        while driver.poll() is None and time.monotonic() < deadline:
            if not verdict_written and (ev/'p31_live.jsonl').exists():
                logs = json_lines(ev/'p31_live.jsonl')
                verdict = next((r for r in logs if r['ev'] == 'verdict'), None)
                if verdict is not None:
                    (ev/'verdict.json').write_text(json.dumps(
                        dict(verdict, observed_at=time.time()), ensure_ascii=False, indent=2))
                    verdict_written = True
            if not receipt_written and (ev/'verdict.json').exists() \
                    and (ev/'host_watch.jsonl').exists():
                own = next((r['own_id'] for r in json_lines(ev/'p31_live.jsonl')
                            if r['ev'] == 'open_enter'), None)
                if own is not None:
                    watched = json_lines(ev/'host_watch.jsonl')
                    if watched:
                        last = watched[-1]
                        hits = [m for m in last.get('members', [])
                                if m['name'] == '风夜' and int(m['id']) == own]
                        if hits and 0 <= time.time()-last['wall'] <= 30:
                            row = hits[0]
                            (ev/'join-receipt.json').write_text(json.dumps(
                                {'own_id': own, 'host_id': host['host_id'],
                                 'observed_at': last['wall'], 'member': row,
                                 'source': 'host_watch.jsonl'},
                                ensure_ascii=False, indent=2))
                            receipt_written = True
            time.sleep(1)
    finally:
        if driver.poll() is None:
            os.killpg(driver.pid, signal.SIGTERM)  # only this owned research group
            try:
                driver.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, signal.SIGKILL)
        stop_file = ev/'stop-p31'
        stop_file.touch()
        summary = {'ended_wall': time.time(), 'verdict_recorded': verdict_written,
                   'dll_member_receipt_recorded': receipt_written,
                   'note': 'verdict.json is the probe-side branch (A1/A2); '
                           'join-receipt.json is the independent host-side DLL '
                           'member-table observation. A1 confirmed only when '
                           'both exist and no app row appeared.'}
        (ev/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
