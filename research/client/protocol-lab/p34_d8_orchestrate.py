"""P34 prepared-only default; --launch additionally requires fresh user consent.
Never run this contract as a join/experiment without separate Phase3 approval.
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
from p32_audit import audit
from p33_audit import sync_audit
from p34_audit import d8_audit


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class Tail:
    def __init__(self, path):
        self.path, self.offset, self.pending = path, 0, b''

    def read(self):
        try:
            with self.path.open('rb') as f:
                f.seek(self.offset)
                chunk = f.read()
                self.offset = f.tell()
        except FileNotFoundError:
            return []
        parts = (self.pending+chunk).split(b'\n')
        self.pending = parts.pop()
        return [json.loads(line.decode('utf-8')) for line in parts if line]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hold', type=int, default=7200)
    ap.add_argument('--observe-seconds', type=int, default=3600)
    ap.add_argument('--ghost-name', default='风夜',
                    help="Expected ghost display name for host/app row matching; "
                         "' ' (single space) additionally needs the blank-name probe flag")
    ap.add_argument('--launch', action='store_true')
    ap.add_argument('--live-authorization', help='Fresh explicit user Phase3/new-room approval JSON')
    args = ap.parse_args()
    if not args.launch:
        print(json.dumps({'state': 'prepared_only', 'research_chain_started': False,
                          'new_member_id': None, 'd8': False}))
        return
    if not args.live_authorization:
        raise ValueError('Phase3_user_approval_required')
    permission = json.loads(Path(args.live_authorization).read_text(encoding='utf-8'))
    if (permission.get('contract') != 'P34' or permission.get('phase3_confirmed') is not True
            or permission.get('new_room_confirmed') is not True
            or permission.get('user_room_report') != '已建房'
            or not 0 <= time.time()-permission.get('confirmed_wall', 0) <= 600):
        raise ValueError('fresh_explicit_Phase3_new_room_approval_required')
    if not 3600 <= args.observe_seconds < args.hold <= 86400:
        raise ValueError('bounded_60min_observation_required')
    lab = Path.home()/'sgi-protocol-lab-20260915'
    lock = (lab/'p34-d8.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ps = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True)
    own_tree = set()
    walker = os.getpid()
    for _ in range(6):
        try:
            row = subprocess.check_output(['ps', '-o', 'ppid=', '-p', str(walker)],
                                          text=True).strip()
            walker = int(row)
        except (ValueError, subprocess.SubprocessError):
            break
        own_tree.add(walker)
    own_tree.add(os.getpid())
    forbidden = {'p1_directed_probe.py', 'p2_loader_host.py', 'p4_host_watch.py',
                 'p20_cmd2_verified_probe.py', 'p24_cmd2_featureless_probe.py',
                 'p21_orchestrate.py', 'p25_orchestrate.py', 'p28_receive_probe.py',
                 'p29_receive_orchestrate.py', 'p31_rowless_probe.py', 'p31_orchestrate.py',
                 'p32_fakeexit_orchestrate.py', 'p32_fakeexit_probe.py',
                 'p33_host_watch.py', 'p33_sync_probe.py', 'p33_sync_orchestrate.py',
                 'p34_d8_probe.py', 'p34_d8_orchestrate.py'}
    for line in ps.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            proc_pid = int(parts[0])
        except ValueError:
            continue
        if proc_pid == os.getpid() or proc_pid in own_tree:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name
                 for v in shlex.split(parts[1], posix=False)}
        if names & forbidden:
            raise RuntimeError('existing_research_chain_pid_'+parts[0])
    root = lab/'evidence/p34-d8-invisible-20261015'
    ev = root/('run-'+time.strftime('%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    sources = ('p34_d8_orchestrate.py', 'p34_d8_probe.py', 'p34_sync.py', 'p34_wire.py',
               'p34_audit.py', 'p34_frames_extract.py', 'p40_d5_inject.py',
               'p33_sync_orchestrate.py', 'p33_sync_probe.py', 'p33_sync.py',
               'p33_wire.py', 'p33_host_watch.py', 'p33_audit.py', 'p32_protocol.py',
               'p32_audit.py', 'p32_app_rows_read.py', 'p28_window.py', 'p28_wire.py',
               'p30_ready.py', 'p20_cmd2_verified_probe.py', 'p2_loader_host.py',
               'p1_directed_probe.py', 'p4_host_watch.py', 'p26_find_host.py',
               'p19_app_rows_read.py')
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
             if h.get('host_name') == os.environ.get('SGI_HOST_NAME', '丁满')]
    if len(hosts) != 1:
        raise RuntimeError('host_discovery_not_unique')
    host = hosts[0]
    read_probe('p19_app_rows_read.py', [str(host['pid'])], 'p19-preflight')
    tables = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-preflight')['tables']
    current = [t for t in tables if t['rows'][0].get('id') == host['host_id']
               and t['rows'][0].get('name') == os.environ.get('SGI_HOST_NAME', '丁满')
               and t['table_hypothesis'] != 'P_pair_upper']
    if len(current) != 1 or not any(r.get('id') == 0 and r.get('state') == 0
                                  and r.get('w4') == 0 for r in current[0]['rows']):
        raise RuntimeError('current_lobby_or_free_row_not_unique')
    identity = {'wall': time.time(), 'orchestrator_pid': os.getpid(), 'host': host,
                'host_pid': host['pid'], 'mode': 'p34_d8_invisible_spectator',
                'ghost_name': args.ghost_name,
                'collector_log': 'p34_live.jsonl', 'hold_seconds': args.hold,
                'observe_seconds': args.observe_seconds, 'cmd1_max_calls': 1,
                'd8_max_calls': 1, 'cmd23_sender': None, 'cmd1_requires_user_report': True,
                'source_sha256': {s: hashlib.sha256((ev/'sources'/s).read_bytes()).hexdigest()
                                  for s in sources}}
    game = Path(rt['prefix'])/'drive_c/sgi/run-3.5/3I'
    identity['native_sha256'] = {name: hashlib.sha256((game/name).read_bytes()).hexdigest()
                                 for name in ('SANPK.exe', 'Koeinm.dll')}
    identity['phase3_approval'] = permission
    write_json(ev/'run_identity.json', identity)
    write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
               'orchestrator_pid': os.getpid(), 'collector': 'p34_d8_probe.py',
               'state': 'running_not_yet_registered'})
    z = lambda p: 'Z:'+str(p).replace('/', '\\')
    ghost_args = []
    if args.ghost_name != '风夜':
        ghost_args = ['--username', args.ghost_name]
        if args.ghost_name == ' ':
            ghost_args.append('--allow-blank-username')
    child_env = dict(os.environ, P2_CHILD_SCRIPT='p34_d8_probe.py',
                    P2_CHILD_ARGS_JSON=json.dumps(['--log', z(ev/'p34_live.jsonl'),
                        '--gate-file', z(ev/'register-gate.json'), '--ready', '--execute',
                        '--sync-effect-file', z(ev/'fakeexit-effect.json'),
                        '--d8-authorization-file', z(ev/'d8-authorization.json'),
                        '--host-withdrawn-file', z(ev/'host-withdrawn.json'),
                        '--stop-file', z(ev/'stop-p34'),
                        '--control-file', z(ev/'hub-control.json'),
                        '--control-result', z(ev/'hub-control-result.json'),
                        '--d5-authorization-file', z(ev/'d5-authorization.json'),
                        '--authorization-file', z(ev/'user-start-report.json'),
                        '--observe-seconds', str(args.observe_seconds)] + ghost_args),
                    P2_CHILD_STDERR=z(ev/'p34.stderr'))
    driver = watch = None
    log_tail = Tail(ev/'p34_live.jsonl')
    watch_tail = Tail(ev/'host_watch.jsonl')
    logs, watched = [], []
    last_audit = 0
    gate_written = registered = post_rows_written = d8_auth_written = False
    d8_seen = False
    withdrawal_samples = []
    rows_d8_attempts = []

    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    def current_verdict():
        try:
            ui = json.loads((ev/'user-ui-row-report.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            ui = None
        return dict(audit(logs, watched), **sync_audit(logs, watched, None,
                    host['host_id'], z(ev/'p34_live.jsonl')),
                    **d8_audit(logs, watched, ui, host['host_id'], z(ev/'p34_live.jsonl')))

    try:
        watch = subprocess.Popen(wine+[str(lab/'p33_host_watch.py'), str(host['pid']),
            '--interval', '1', '--duration', str(args.hold+60), '--out', str(ev/'host_watch.jsonl')],
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
            logs.extend(log_tail.read())
            watched.extend(watch_tail.read())
            pending = next((r for r in logs if r.get('ev') == 'waiting_host_gate'), None)
            if pending and watched and not gate_written:
                last = watched[-1]
                hits = [m for m in last.get('members', [])
                        if m['name'] == args.ghost_name and int(m['id']) == pending['own_id']]
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
                        for r in t['rows'] if r.get('id') == pending['own_id']
                        and r.get('name') == args.ghost_name]
                if len(hits) == 1 and hits[0][1]['w4'] == 2 and hits[0][1]['machine_name'] == machine:
                    registered = True
                    write_json(ev/'registration-receipt.json', {'own_id': pending['own_id'],
                               'host_id': host['host_id'], 'wall': rows['wall'],
                               'table': hits[0][0]['row0'], 'row': hits[0][1], 'machine_name': machine})
            if time.monotonic()-last_audit >= 5:
                verdict = current_verdict()
                verdict['registered_verified'] = registered
                verdict['updated_wall'] = time.time()
                write_json(ev/'verdict.json', verdict)
                if verdict['cmd1_wall'] and time.time()-verdict['cmd1_wall'] >= 10 and not post_rows_written:
                    read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-post-cmd1')
                    post_rows_written = True
                    captured = json.loads((ev/'rows-post-cmd1.stdout').read_text())
                    hits = [r for t in captured['tables'] if t['table_hypothesis'] == 'P_pair_upper'
                            for r in t['rows'] if r.get('id') == verdict['own_id']
                            and r.get('name') == args.ghost_name and r.get('state') == 2]
                    if len(hits) == 1:
                        write_json(ev/'fakeexit-effect.json', {'own_id': verdict['own_id'],
                            'host_id': host['host_id'], 'observed_wall': captured['wall'],
                            'P_state': 2, 'source': 'p32_app_rows_read'})
                if (not d8_auth_written and post_rows_written
                        and (ev/'fakeexit-effect.json').exists()
                        and len([r for r in logs if r.get('ev') == 'sync_round_complete']) >= 1
                        and any(r.get('ev') == 'cmd1_ack_observed' for r in logs)):
                    write_json(ev/'d8-authorization.json', {
                        'contract': 'P34', 'source': 'p34_derived_authorization',
                        'enable_d8': True, 'cmd1_acked': True, 'completed_rounds':
                        len([r for r in logs if r.get('ev') == 'sync_round_complete']),
                        'own_id': verdict['own_id'], 'host_id': host['host_id'],
                        'observed_wall': time.time(),
                        'collector_log': z(ev/'p34_live.jsonl'),
                        'basis': 'user_start_report_plus_cmd1_ack_plus_effect_plus_completed_sync_round'})
                    d8_auth_written = True
                if d8_auth_written and not d8_seen:
                    sends = [r for r in logs if r.get('ev') == 'd8_send_return']
                    if sends:
                        d8_seen = True
                        write_json(ev/'d8-sent-receipt.json', {
                            'own_id': verdict['own_id'], 'host_id': host['host_id'],
                            'raw_rc': sends[-1]['raw_rc'], 'wall': time.time(),
                            'note': 'host processes at its current round end (36e0); row clears then'})
                if d8_seen and not (ev/'host-withdrawn.json').exists():
                    recent = [s for s in watched if 0 <= time.time()-s.get('wall', 0) <= 6]
                    hits = [s for s in recent
                            if all(row['id'] != verdict['own_id'] for row in (s.get('sync_rows') or []))
                            and s.get('sync_rows')]
                    if len(hits) >= 3:
                        write_json(ev/'host-withdrawn.json', {'own_id': verdict['own_id'],
                                   'host_id': host['host_id'], 'observed_wall': time.time(),
                                   'consecutive_absent_samples': len(hits),
                                   'source': 'host_watch_sync_rows'})
                if d8_seen and not (ev/'d8-effect.json').exists() and len(rows_d8_attempts) < 8 \
                        and (not rows_d8_attempts
                             or time.time()-rows_d8_attempts[-1]['wall'] >= 20):
                    label = 'rows-post-d8-%d' % (len(rows_d8_attempts)+1)
                    read_probe('p32_app_rows_read.py', [str(host['pid'])], label)
                    rows_d8_attempts.append({'wall': time.time(), 'attempt': len(rows_d8_attempts)+1})
                    captured = json.loads((ev/(label+'.stdout')).read_text())
                    hits = [r for t in captured['tables'] if t['table_hypothesis'] != 'P_pair_upper'
                            for r in t['rows'] if r.get('id') == verdict['own_id']
                            and r.get('name') == args.ghost_name]
                    if not hits:
                        write_json(ev/'d8-effect.json', {'own_id': verdict['own_id'],
                            'host_id': host['host_id'], 'observed_wall': captured['wall'],
                            'row_present': False, 'attempt': len(rows_d8_attempts),
                            'source': 'p32_app_rows_read'})
                    elif len(rows_d8_attempts) == 8:
                        write_json(ev/'d8-effect.json', {'own_id': verdict['own_id'],
                            'host_id': host['host_id'], 'observed_wall': captured['wall'],
                            'row_present': True, 'attempts': 8,
                            'unknown': 'row_not_cleared_within_window', 'source': 'p32_app_rows_read'})
                last_audit = time.monotonic()
            if (ev/'stop-p34').exists():
                break
            time.sleep(.5)
    finally:
        (ev/'stop-p34').touch()
        if driver is not None and driver.poll() is None:
            try:
                driver.wait(timeout=20)
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
        logs.extend(log_tail.read())
        watched.extend(watch_tail.read())
        write_json(ev/'verdict.json', current_verdict())
        write_json(ev/'summary.json', {'ended_wall': time.time(), 'registered_verified': registered,
                   'd8_auth_written': d8_auth_written, 'd8_seen': d8_seen,
                   'rows_post_d8_attempts': len(rows_d8_attempts),
                   'driver_rc': None if driver is None else driver.poll(),
                   'watch_rc': None if watch is None else watch.poll()})
        write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
                   'orchestrator_pid': os.getpid(), 'state': 'ended_historical_pointer'})


if __name__ == '__main__':
    main()
