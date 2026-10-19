"""One bounded P32 run; read-only host observers, owned relay and collector."""
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
from p32_audit import audit
from p29_receive_orchestrate import json_lines


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hold', type=int, default=7200)
    ap.add_argument('--observe-seconds', type=int, default=3600)
    args = ap.parse_args()
    if not 3600 <= args.observe_seconds < args.hold <= 86400:
        raise ValueError('bounded_60min_observation_required')
    lab = Path.home()/'sgi-protocol-lab-20260915'
    lock = (lab/'p32-fakeexit.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ps = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    forbidden = {'p1_directed_probe.py', 'p2_loader_host.py', 'p4_host_watch.py',
                 'p20_cmd2_verified_probe.py', 'p24_cmd2_featureless_probe.py',
                 'p21_orchestrate.py', 'p25_orchestrate.py', 'p28_receive_probe.py',
                 'p29_receive_orchestrate.py', 'p31_rowless_probe.py', 'p31_orchestrate.py',
                 'p32_fakeexit_probe.py'}
    for line in ps.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name
                 for v in shlex.split(parts[1], posix=False)}
        if names & forbidden:
            raise RuntimeError('existing_research_chain_pid_'+parts[0])
    root = lab/'evidence/p32-fakeexit-20261015'
    ev = root/('run-'+time.strftime('%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    (ev/'research-processes-preflight.txt').write_text('none\n')
    sources = ('p32_fakeexit_orchestrate.py', 'p32_fakeexit_probe.py', 'p32_protocol.py',
               'p32_audit.py', 'p32_app_rows_read.py', 'p28_window.py', 'p28_wire.py',
               'p30_ready.py', 'p20_cmd2_verified_probe.py', 'p2_loader_host.py',
               'p1_directed_probe.py', 'p4_host_watch.py', 'p26_find_host.py',
               'p19_app_rows_read.py', 'p29_receive_orchestrate.py')
    (ev/'sources').mkdir()
    for name in sources:
        (ev/'sources'/name).write_bytes((lab/name).read_bytes())
    rt = json.loads((Path.home()/'Library/Application Support/SGI-Wine/runtime.json').read_text())
    env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
               DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
    wine = [rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'), '-X', 'utf8']

    def read_probe(script, extra, label):
        r = subprocess.run(wine+[str(lab/script)]+extra, env=env,
                           capture_output=True, text=True, timeout=40)
        (ev/(label+'.stdout')).write_text(r.stdout)
        (ev/(label+'.stderr')).write_text(r.stderr)
        if r.returncode:
            raise RuntimeError(label+'_failed')
        return json.loads(r.stdout)

    hosts = [h for h in read_probe('p26_find_host.py', [], 'host_discovery')['hosts']
             if h.get('host_name') == '丁满']
    if len(hosts) != 1:
        raise RuntimeError('host_discovery_not_unique')
    host = hosts[0]
    read_probe('p19_app_rows_read.py', [str(host['pid'])], 'p19-preflight')
    tables = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-preflight')['tables']
    # Both candidates retained. A paired L is structurally identified by D+b4.
    current = [t for t in tables if t['rows'][0].get('id') == host['host_id']
               and t['rows'][0].get('name') == '丁满'
               and t['table_hypothesis'] != 'P_pair_upper']
    if len(current) != 1 or not any(r.get('id') == 0 and r.get('state') == 0
                                  and r.get('w4') == 0 for r in current[0]['rows']):
        raise RuntimeError('current_lobby_or_free_row_not_unique')
    identity = {'wall': time.time(), 'orchestrator_pid': os.getpid(), 'host': host,
                'host_pid': host['pid'], 'mode': 'p32_own_fakeexit',
                'collector_log': 'p32_live.jsonl', 'hold_seconds': args.hold,
                'observe_seconds': args.observe_seconds, 'cmd1_max_calls': 1,
                'cmd23_sender': None, 'cmd1_requires_user_report': True,
                'source_sha256': {s: hashlib.sha256((ev/'sources'/s).read_bytes()).hexdigest()
                                  for s in sources}}
    game = Path(rt['prefix'])/'drive_c/sgi/run-3.5/3I'
    identity['native_sha256'] = {name: hashlib.sha256((game/name).read_bytes()).hexdigest()
                                 for name in ('SANPK.exe', 'Koeinm.dll')}
    write_json(ev/'run_identity.json', identity)
    write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
               'orchestrator_pid': os.getpid(), 'collector': 'p32_fakeexit_probe.py',
               'state': 'running_not_yet_registered'})
    z = lambda p: 'Z:'+str(p).replace('/', '\\')
    child_env = dict(os.environ, P2_CHILD_SCRIPT='p32_fakeexit_probe.py',
                    P2_CHILD_ARGS_JSON=json.dumps(['--log', z(ev/'p32_live.jsonl'),
                        '--gate-file', z(ev/'register-gate.json'), '--ready',
                        '--stop-file', z(ev/'stop-p32'),
                        '--authorization-file', z(ev/'user-start-report.json'),
                        '--observe-seconds', str(args.observe_seconds)]),
                    P2_CHILD_STDERR=z(ev/'p32.stderr'))
    driver = watch = None
    last_audit = 0
    gate_written = registered = post_rows_written = False

    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        watch = subprocess.Popen(wine+[str(lab/'p4_host_watch.py'), str(host['pid']),
            '--interval', '5', '--duration', str(args.hold+60), '--out', str(ev/'host_watch.jsonl')],
            env=env, stdout=(ev/'watch.stdout').open('w'), stderr=(ev/'watch.stderr').open('w'))
        driver = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
            '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
            '--target', host['host_ip'], '--loader-script', 'p2_loader_host.py',
            '--session-name', host['session_name'], '--hold-seconds', str(args.hold),
            '--loader-timeout', str(args.hold+120)], env=child_env,
            stdout=(ev/'p1.json').open('w'), stderr=(ev/'p1.stderr').open('w'), start_new_session=True)
        write_json(ev/'processes.json', {'driver_pid': driver.pid, 'watch_pid': watch.pid,
                   'orchestrator_pid': os.getpid()})
        print(json.dumps({'evidence': str(ev), 'host': host, 'driver_pid': driver.pid,
                          'watch_pid': watch.pid}, ensure_ascii=False), flush=True)
        deadline = time.monotonic()+args.hold+150
        while driver.poll() is None and time.monotonic() < deadline:
            logs = json_lines(ev/'p32_live.jsonl')
            watched = json_lines(ev/'host_watch.jsonl')
            pending = next((r for r in logs if r.get('ev') == 'waiting_host_gate'), None)
            if pending and watched and not gate_written:
                last = watched[-1]
                hits = [m for m in last.get('members', [])
                        if m['name'] == '风夜' and int(m['id']) == pending['own_id']]
                if len(hits) == 1 and 0 <= time.time()-last['wall'] <= 6:
                    row = hits[0]
                    write_json(ev/'register-gate.json', {'own_id': pending['own_id'],
                               'host_id': host['host_id'], 'observed_at': last['wall'],
                               'host_sB': row['seq_28'], 'next_seq': row['seq_28']+1,
                               'source': 'host_watch.jsonl'})
                    gate_written = True
            if gate_written and not registered and any(r.get('ev') == 'snapshot_stored' for r in logs):
                rows = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-registered')
                machine = next(r['machine_name'] for r in logs if r.get('ev') == 'start_enter')
                hits = [(t, r) for t in rows['tables'] if t['table_hypothesis'] != 'P_pair_upper'
                        for r in t['rows'] if r.get('id') == pending['own_id'] and r.get('name') == '风夜']
                if len(hits) == 1 and hits[0][1]['w4'] == 2 and hits[0][1]['machine_name'] == machine:
                    registered = True
                    write_json(ev/'registration-receipt.json', {'own_id': pending['own_id'],
                               'host_id': host['host_id'], 'wall': rows['wall'],
                               'table': hits[0][0]['row0'], 'row': hits[0][1], 'machine_name': machine})
            if time.monotonic()-last_audit >= 5:
                verdict = audit(logs, watched)
                verdict['registered_verified'] = registered
                verdict['updated_wall'] = time.time()
                write_json(ev/'verdict.json', verdict)
                last_audit = time.monotonic()
                if verdict['cmd1_wall'] and time.time()-verdict['cmd1_wall'] >= 10 and not post_rows_written:
                    read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-post-cmd1')
                    post_rows_written = True
            if (ev/'stop-p32').exists():
                break
            time.sleep(.5)
    finally:
        (ev/'stop-p32').touch()
        if driver is not None and driver.poll() is None:
            try:
                driver.wait(timeout=20)  # child pumps its normal ExitSession/End first
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, signal.SIGTERM)
                try:
                    driver.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(driver.pid, signal.SIGKILL)
                    driver.wait(timeout=5)
        if watch is not None and watch.poll() is None:
            watch.terminate()
            try:
                watch.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watch.kill()
                watch.wait(timeout=5)
        logs, watched = json_lines(ev/'p32_live.jsonl'), json_lines(ev/'host_watch.jsonl')
        write_json(ev/'verdict.json', audit(logs, watched))
        write_json(ev/'summary.json', {'ended_wall': time.time(), 'registered_verified': registered,
                   'driver_rc': None if driver is None else driver.poll(),
                   'watch_rc': None if watch is None else watch.poll()})
        write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
                   'orchestrator_pid': os.getpid(), 'state': 'ended_historical_pointer'})


if __name__ == '__main__':
    main()
