"""P42 pre-start D8 manual run (single machine): preflight -> consent -> gate -> driver -> receipts.

Prepared-only by default; --launch additionally requires a fresh explicit
new-room consent file (contract P42, user_room_report == 已建房). One probe
child (p42_prestart_d8_probe.py) joins, registers with cmd2, then sends exactly
one D8 while the native sync state is idle (1). No cmd1, no cmd9, no sync
rounds. All writes stay inside the run directory; preflights are read-only.
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

ROOT = 'p42-prestart-d8-20261016'


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def resolve_windows(observe_seconds, hold_seconds, long_run):
    """P45: pick observation windows; explicit values always win.

    Standard runs keep the historic 60min/2h pair; --long-run defaults to a
    23h listen window inside a 24h keepalive (assert ceiling in main()).
    """
    if observe_seconds is None:
        observe_seconds = 82800 if long_run else 3600
    if hold_seconds is None:
        hold_seconds = 86400 if long_run else 7200
    return observe_seconds, hold_seconds


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
    ap.add_argument('--hold', type=int, default=None)
    ap.add_argument('--observe-seconds', type=int, default=None)
    ap.add_argument('--long-run', action='store_true',
                    help='P45 long-run mode: 23h listen window / 24h keepalive; '
                         'manual stop; 60s post-exit tail (explicit --hold/'
                         '--observe-seconds still win)')
    ap.add_argument('--health-seconds', type=int, default=300)
    ap.add_argument('--tail-seconds', type=int, default=60)
    ap.add_argument('--ghost-name', default='小白')
    ap.add_argument('--child-script', default='p42_prestart_d8_probe.py',
                    help='Probe child script inside the lab dir (use p43_* for the hardened build)')
    ap.add_argument('--host-name', default=os.environ.get('SGI_HOST_NAME', '风云'))
    ap.add_argument('--launch', action='store_true')
    ap.add_argument('--live-authorization', help='Fresh explicit new-room approval JSON')
    args = ap.parse_args()
    args.observe_seconds, args.hold = resolve_windows(
        args.observe_seconds, args.hold, args.long_run)
    if not args.launch:
        print(json.dumps({'state': 'prepared_only', 'chain_started': False,
                          'new_member_id': None, 'd8_prestart': False}))
        return
    if not args.live_authorization:
        raise ValueError('new_room_user_approval_required')
    permission = json.loads(Path(args.live_authorization).read_text(encoding='utf-8'))
    if (permission.get('contract') != 'P42'
            or permission.get('phase3_confirmed') is not True
            or permission.get('new_room_confirmed') is not True
            or permission.get('user_room_report') != '已建房'
            or not 0 <= time.time()-permission.get('confirmed_wall', 0) <= 600):
        raise ValueError('fresh_explicit_new_room_approval_required')
    if not 3600 <= args.observe_seconds < args.hold <= 86400:
        raise ValueError('bounded_observation_required')
    if not 30 <= args.health_seconds <= 1800:
        raise ValueError('health_seconds_bounds')
    if not 10 <= args.tail_seconds <= 600:
        raise ValueError('tail_seconds_bounds')
    lab = Path.home()/'sgi-protocol-lab-20260915'
    lock = (lab/'p42-prestart-d8.lock').open('a')
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
                 'p34_d8_probe.py', 'p34_d8_orchestrate.py',
                 'p42_prestart_d8_probe.py', 'p42_prestart_d8_run.py',
                 'p37_chat_probe.py', 'p37b_samename_join.py'}
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
    root = lab/'evidence'/ROOT
    ev = root/('run-'+time.strftime('%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)
    sources = ('p42_prestart_d8_run.py', 'p42_prestart_d8_probe.py', 'p42_wire.py',
               'p34_wire.py', 'p34_sync.py', 'p33_wire.py', 'p33_sync.py',
               'p32_protocol.py', 'p30_ready.py', 'p28_window.py', 'p28_wire.py',
               'p20_cmd2_verified_probe.py', 'p40_d5_inject.py', 'p2_loader_host.py',
               'p1_directed_probe.py', 'p26_find_host.py', 'p19_app_rows_read.py',
               'p32_app_rows_read.py', 'p33_host_watch.py')
    sources = tuple(dict.fromkeys(sources + (args.child_script,)))
    (ev/'sources').mkdir()
    for name in sources:
        (ev/'sources'/name).write_bytes((lab/name).read_bytes())
    rt = json.loads((Path.home()/'Library/Application Support/SGI-Wine/runtime.json').read_text())
    bridge = lab/'bridge'
    if (bridge/'probe.py').exists():
        os.environ.setdefault('SGI_BRIDGE_Z', 'Z:'+str(bridge).replace('/', '\\'))
    env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
               DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'], SGI_HOST_NAME=args.host_name)
    wine = [rt['wine'], str(lab/'python32/sgi-protocol-probe.exe'), '-X', 'utf8']

    def read_probe(script, extra, label, timeout=40):
        r = subprocess.run(wine+[str(lab/script)]+extra, env=env,
                           capture_output=True, text=True, timeout=timeout)
        (ev/(label+'.stdout')).write_text(r.stdout)
        (ev/(label+'.stderr')).write_text(r.stderr)
        if r.returncode:
            raise RuntimeError(label+'_failed')
        return json.loads(r.stdout)

    hosts = [h for h in read_probe('p26_find_host.py', [], 'host_discovery')['hosts']
             if h.get('host_name') == args.host_name]
    if len(hosts) != 1:
        raise RuntimeError('host_discovery_not_unique')
    host = hosts[0]
    read_probe('p19_app_rows_read.py', [str(host['pid'])], 'p19-preflight')
    tables = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-preflight')['tables']
    current = [t for t in tables if t['rows'][0].get('id') == host['host_id']
               and t['rows'][0].get('name') == args.host_name
               and t['table_hypothesis'] != 'P_pair_upper']
    if len(current) != 1:
        raise RuntimeError('current_lobby_table_not_unique')
    free = [r for r in current[0]['rows'] if r.get('id') == 0]
    if not free:
        raise RuntimeError('no_free_row_for_ghost_join')
    identity = {'wall': time.time(), 'orchestrator_pid': os.getpid(), 'host': host,
                'host_pid': host['pid'], 'mode': 'p42_prestart_d8_passive',
                'child_script': args.child_script,
                'ghost_name': args.ghost_name, 'collector_log': 'p42_live.jsonl',
                'hold_seconds': args.hold, 'observe_seconds': args.observe_seconds,
                'long_run': bool(args.long_run),
                'health_seconds': args.health_seconds,
                'tail_seconds': args.tail_seconds,
                'cmd1_max_calls': 0, 'cmd9_max_calls': 0, 'd8_max_calls': 1,
                'free_rows_at_preflight': len(free),
                'source_sha256': {s: hashlib.sha256((ev/'sources'/s).read_bytes()).hexdigest()
                                  for s in sources}}
    game = Path(rt['prefix'])/'drive_c/sgi/run-3.5/3I'
    identity['native_sha256'] = {name: hashlib.sha256((game/name).read_bytes()).hexdigest()
                                 for name in ('SANPK.exe', 'Koeinm.dll')}
    identity['new_room_approval'] = permission
    write_json(ev/'run_identity.json', identity)
    write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
               'orchestrator_pid': os.getpid(), 'collector': 'p42_prestart_d8_probe.py',
               'state': 'running_not_yet_registered'})
    z = lambda p: 'Z:'+str(p).replace('/', '\\')
    ghost_args = []
    if args.ghost_name != '风夜':
        ghost_args = ['--username', args.ghost_name]
        if args.ghost_name == ' ':
            ghost_args.append('--allow-blank-username')
    child_env = dict(os.environ, P2_CHILD_SCRIPT=args.child_script,
                     P2_CHILD_ARGS_JSON=json.dumps(['--log', z(ev/'p42_live.jsonl'),
                         '--gate-file', z(ev/'register-gate.json'), '--execute',
                         '--d8-pre-start',
                         '--p42-authorization-file', z(ev/'p42_authorization.json'),
                         '--stop-file', z(ev/'stop-p42'),
                         '--control-file', z(ev/'hub-control.json'),
                         '--control-result', z(ev/'hub-control-result.json'),
                         '--observe-seconds', str(args.observe_seconds)] + ghost_args),
                     P2_CHILD_STDERR=z(ev/'p42.stderr'))
    end_reason = None
    driver = watch = None
    log_tail = Tail(ev/'p42_live.jsonl')
    watch_tail = Tail(ev/'host_watch.jsonl')
    logs, watched = [], []
    gate_written = arm_written = d8_seen = registered_sampled = False
    start_seen = post_start_sampled = False
    d8_samples = []
    d8_send_wall = [0.0]
    d8_last_attempt = [0.0]
    own_id_seen = [None]

    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        watch = subprocess.Popen(wine+[str(lab/'p33_host_watch.py'), str(host['pid']),
            '--interval', '1', '--duration', str(args.hold+240), '--out', str(ev/'host_watch.jsonl')],
            env=env, stdout=(ev/'watch.stdout').open('w'), stderr=(ev/'watch.stderr').open('w'))
        driver = subprocess.Popen(['python3', str(lab/'p1_directed_probe.py'),
            '--credentials', str(lab/'query-credentials.fengye.json'), '--line', '多线3',
            '--target', host['host_ip'], '--loader-script', 'p2_loader_host.py',
            '--session-name', host['session_name'], '--hold-seconds', str(args.hold),
            '--loader-timeout', str(args.hold+120)], env=child_env,
            stdout=(ev/'p1.json').open('w'), stderr=(ev/'p1.stderr').open('w'),
            start_new_session=True)
        write_json(ev/'processes.json', {'driver_pid': driver.pid, 'watch_pid': watch.pid,
                   'orchestrator_pid': os.getpid()})
        print(json.dumps({'evidence': str(ev), 'host': host, 'driver_pid': driver.pid,
                          'watch_pid': watch.pid}, ensure_ascii=False), flush=True)
        deadline = time.monotonic()+args.hold+150
        while driver.poll() is None and time.monotonic() < deadline:
            logs.extend(log_tail.read())
            watched.extend(watch_tail.read())
            pending = next((r for r in logs if r.get('ev') == 'waiting_host_gate'), None)
            if pending:
                own_id_seen[0] = pending['own_id']
            if pending and watched and not gate_written:
                last = watched[-1]
                hits = [m for m in last.get('members', [])
                        if m.get('name') == args.ghost_name
                        and int(m.get('id') or 0) == pending['own_id']]
                if (len(hits) == 1 and 0 <= time.time()-last.get('wall', 0) <= 6
                        and not (ev/'register-gate.json').exists()):
                    row = hits[0]
                    write_json(ev/'register-gate.json', {
                        'own_id': pending['own_id'], 'host_id': host['host_id'],
                        'observed_at': last['wall'], 'host_sB': row['seq_28'],
                        'next_seq': int(row['seq_28'])+1, 'ghost_index': None,
                        'source': 'host_watch.jsonl'})
                    write_json(ev/'p42_authorization.json', {
                        'contract': 'P42', 'source': 'p42_derived_authorization',
                        'enable_d8_prestart': True, 'own_id': pending['own_id'],
                        'host_id': host['host_id'], 'observed_wall': time.time(),
                        'collector_log': z(ev/'p42_live.jsonl'),
                        'ghost_name': args.ghost_name,
                        'basis': ('host_watch member row at registration gate; probe '
                                  'additionally requires own cmd2 ack and idle state 1')})
                    gate_written = arm_written = True
            cmd2 = [r for r in logs if r.get('ev') == 'send_return'
                    and r.get('label') == 'cmd2' and r.get('rc') == 0]
            if (cmd2 and gate_written and not registered_sampled
                    and time.time()-cmd2[0]['wall'] >= 2):
                registered_sampled = True
                machine = next((r['machine_name'] for r in logs if r.get('ev') == 'start_enter'), None)
                try:
                    rows = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-post-cmd2')
                except Exception:
                    rows = None
                if rows is not None:
                    hits = [(t, r) for t in rows['tables'] if t['table_hypothesis'] != 'P_pair_upper'
                            for r in t['rows'] if r.get('id') == pending['own_id'] and r.get('name') == args.ghost_name]
                    if len(hits) == 1 and hits[0][1].get('w4') == 2 and hits[0][1].get('machine_name') == machine:
                        write_json(ev/'registration-receipt.json', {
                            'own_id': pending['own_id'], 'host_id': host['host_id'],
                            'wall': rows['wall'], 'table': hits[0][0]['row0'], 'row': hits[0][1],
                            'machine_name': machine})
            sends = [r for r in logs if r.get('ev') == 'd8_prestart_send_return']
            if sends and not d8_seen:
                d8_seen = True
                d8_send_wall[0] = sends[-1].get('wall') or time.time()
                write_json(ev/'p42-d8-sent.json', {
                    'own_id': own_id_seen[0], 'host_id': host['host_id'],
                    'raw_rc': sends[-1].get('raw_rc'), 'target': sends[-1].get('target'),
                    'native_state_after': sends[-1].get('native_state_after'),
                    'wall': sends[-1].get('wall'),
                    'note': 'single pre-start D8; passive listen follows'})
            last_gap_ref = max(d8_samples[-1]['wall'] if d8_samples else d8_send_wall[0],
                               d8_last_attempt[0])
            if (d8_seen and len(d8_samples) < 8
                    and time.time()-last_gap_ref >= (12 if not d8_samples else 20)):
                label = 'rows-post-d8-%d' % (len(d8_samples)+1)
                d8_last_attempt[0] = time.time()
                try:
                    read_probe('p32_app_rows_read.py', [str(host['pid'])], label)
                except Exception:
                    captured = None
                else:
                    captured = json.loads((ev/(label+'.stdout')).read_text())
                if captured is not None:
                    d8_samples.append({'wall': time.time(), 'attempt': len(d8_samples)+1})
                    hits = [r for t in captured['tables'] if t['table_hypothesis'] != 'P_pair_upper'
                            for r in t['rows'] if r.get('id') == own_id_seen[0]
                            and r.get('name') == args.ghost_name]
                    if not hits:
                        write_json(ev/'d8-effect.json', {
                            'own_id': own_id_seen[0], 'host_id': host['host_id'],
                            'observed_wall': captured['wall'], 'row_present': False,
                            'attempt': len(d8_samples), 'source': 'p32_app_rows_read'})
                    elif len(d8_samples) == 8:
                        write_json(ev/'d8-effect.json', {
                            'own_id': own_id_seen[0], 'host_id': host['host_id'],
                            'observed_wall': captured['wall'], 'row_present': True, 'attempts': 8,
                            'unknown': 'row_not_cleared_within_window',
                            'source': 'p32_app_rows_read'})
            if not start_seen and any(r.get('ev') == 'start_command_received' for r in logs):
                start_seen = True
                write_json(ev/'start-seen.json', {'wall': time.time(),
                           'own_id': own_id_seen[0],
                           'note': 'host start broadcast observed by passive probe'})
            if (start_seen and not post_start_sampled
                    and time.time()-json.loads((ev/'start-seen.json').read_text())['wall'] >= 10):
                post_start_sampled = True
                try:
                    read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows-post-start')
                except Exception:
                    pass
            if (ev/'stop-p42').exists():
                break
            time.sleep(.5)
        # P45 post-exit tail: signal the probe, let it finish, then keep the
        # host-side watch running to record what the host/room shows after the
        # ghost has left (manual stop, hold expiry or probe exit all come here).
        (ev/'stop-p42').touch()
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
        logs.extend(log_tail.read())
        watched.extend(watch_tail.read())
        for row in reversed(logs):
            if row.get('ev') in ('stop_requested', 'hold_expired', 'disconnect_observed',
                                 'control_stop', 'abort', 'session_dead_before_register'):
                end_reason = row.get('ev')
                break
        else:
            end_reason = 'driver_exit_unclassified'
        tail_rows = []
        if watch is not None and watch.poll() is None:
            tail_deadline = time.monotonic()+args.tail_seconds
            while time.monotonic() < tail_deadline and watch.poll() is None:
                tail_rows.extend(watch_tail.read())
                time.sleep(.5)
            tail_rows.extend(watch_tail.read())
        with (ev/'post-exit-watch.jsonl').open('w') as tail_out:
            for row in tail_rows:
                tail_out.write(json.dumps(row, ensure_ascii=False)+'\n')
        last_members = []
        if tail_rows:
            for member in (tail_rows[-1].get('members') or [])[:8]:
                if isinstance(member, dict):
                    last_members.append({k: member.get(k) for k in
                                         ('name', 'id', 'seq_28', 'active', 'reconn', 'failed')
                                         if k in member})
        write_json(ev/'post-exit-tail.json', {
            'end_reason': end_reason, 'wall': time.time(),
            'tail_seconds': args.tail_seconds, 'samples': len(tail_rows),
            'first_wall': tail_rows[0].get('wall') if tail_rows else None,
            'last_wall': tail_rows[-1].get('wall') if tail_rows else None,
            'watch_alive_after_tail': bool(watch is not None and watch.poll() is None),
            'last_members': last_members,
            'note': ('host-side watch kept running after probe exit; '
                     'raw rows in post-exit-watch.jsonl')})
    finally:
        (ev/'stop-p42').touch()
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
        write_json(ev/'summary.json', {
            'ended_wall': time.time(), 'gate_written': gate_written,
            'arm_written': arm_written, 'd8_seen': d8_seen, 'start_seen': start_seen,
            'rows_post_d8_attempts': len(d8_samples),
            'd8_effect_written': (ev/'d8-effect.json').exists(),
            'end_reason': end_reason,
            'post_exit_tail_written': (ev/'post-exit-tail.json').exists(),
            'driver_rc': None if driver is None else driver.poll(),
            'watch_rc': None if watch is None else watch.poll()})
        write_json(root/'active-run.json', {'evidence': str(ev), 'wall': time.time(),
                   'orchestrator_pid': os.getpid(),
                   'state': 'ended_historical_pointer'})


if __name__ == '__main__':
    main()
