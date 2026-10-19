"""E-P35 manual run (host machine): preflight -> arming -> gate -> driver -> receipts.

One probe child runs with --exit-before-start: it fires exactly one cmd1 after
registration (pre-start), then keeps the session for cmd7/cmd9/cmd10 and starts
the minimal sync worker only once the host start broadcast (cmd10) is seen.
Read-only preflights; all writes stay inside the run directory.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

lab = Path.home() / 'sgi-protocol-lab-20260915'
rt = json.loads((Path.home() / 'Library/Application Support/SGI-Wine/runtime.json').read_text())
env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
           DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
wine = [rt['wine'], str(lab / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8']


def probe(script, extra, timeout=120):
    return subprocess.run(wine + [str(lab / script)] + extra, env=env,
                          capture_output=True, text=True, timeout=timeout)


def main():
    ev = lab / 'evidence/p35-exit-before-start-20261016' / ('run-' + time.strftime('%H%M%S'))
    ev.mkdir(parents=True, exist_ok=False)

    r = probe('p26_find_host.py', [])
    (ev / 'host_discovery.stdout').write_text(r.stdout)
    hosts = [h for h in json.loads(r.stdout).get('hosts', [])
             if h.get('host_name') == os.environ.get('SGI_HOST_NAME', '丁满')]
    if len(hosts) != 1:
        raise SystemExit('host_not_unique')
    host = hosts[0]
    for script, label in (('p19_app_rows_read.py', 'p19-preflight'),
                          ('p32_app_rows_read.py', 'rows-preflight')):
        rr = probe(script, [str(host['pid'])])
        (ev / (label + '.stdout')).write_text(rr.stdout)

    now = time.time()
    arming = {'contract': 'P35', 'enable_exit_before_start': True,
              'host_id': host['host_id'], 'observed_wall': now,
              'host_name': host['host_name'], 'session': host['session_name'],
              'note': 'E-P35 pre-start cmd1 (one shot); user reported a new room'}
    (ev / 'p35_authorization.json').write_text(json.dumps(arming, ensure_ascii=False, indent=2))
    consent = {'contract': 'P35', 'user_room_report': '已建房',
               'transcribed_from': '用户原话「B, 我已新建房間」(2026-10-16)',
               'confirmed_wall': now, 'host': host}
    (ev / 'consent.json').write_text(json.dumps(consent, ensure_ascii=False, indent=2))

    watch = subprocess.Popen(wine + [str(lab / 'p33_host_watch.py'), str(host['pid']),
                                     '--interval', '1', '--duration', '7400',
                                     '--out', str(ev / 'host_watch.jsonl')],
                             env=env, stdout=(ev / 'watch.stdout').open('w'),
                             stderr=(ev / 'watch.stderr').open('w'))

    gate_state = {'written': False}

    def gate_loop():
        while not gate_state['written']:
            time.sleep(0.5)
            try:
                lines = (ev / 'host_watch.jsonl').read_text().splitlines()
            except OSError:
                continue
            if not lines:
                continue
            try:
                last = json.loads(lines[-1])
            except ValueError:
                continue
            if not 0 <= time.time() - last.get('wall', 0) <= 6:
                continue
            members = last.get('members') or []
            for pos, m in enumerate(members):
                if m.get('name') == '风夜' and m.get('id') and str(m.get('id')) != '0':
                    row = {'own_id': int(m['id']), 'host_id': host['host_id'],
                           'observed_at': last['wall'], 'host_sB': m.get('seq_28'),
                           'next_seq': int(m.get('seq_28', 0)) + 1, 'ghost_index': pos,
                           'source': 'host_watch.jsonl'}
                    (ev / 'register-gate.json').write_text(
                        json.dumps(row, ensure_ascii=False, indent=2))
                    gate_state['written'] = True
                    return

    threading.Thread(target=gate_loop, daemon=True).start()

    z = lambda p: 'Z:' + str(p).replace('/', '\\')
    child_env = dict(os.environ, P2_CHILD_SCRIPT='p34_d8_probe.py',
                     P2_CHILD_ARGS_JSON=json.dumps([
                         '--log', z(ev / 'p35_live.jsonl'),
                         '--gate-file', z(ev / 'register-gate.json'),
                         '--ready', '--execute', '--exit-before-start',
                         '--p35-authorization-file', z(ev / 'p35_authorization.json'),
                         '--sync-effect-file', z(ev / 'not-used-effect.json'),
                         '--d8-authorization-file', z(ev / 'not-used-d8.json'),
                         '--host-withdrawn-file', z(ev / 'not-used-withdrawn.json'),
                         '--stop-file', z(ev / 'stop-p35'),
                         '--control-file', z(ev / 'hub-control.json'),
                         '--control-result', z(ev / 'hub-control-result.json'),
                         '--authorization-file', z(ev / 'not-used-start.json'),
                         '--observe-seconds', '3600']),
                     P2_CHILD_STDERR=z(ev / 'p35.stderr'))
    driver = subprocess.Popen(['python3', str(lab / 'p1_directed_probe.py'),
        '--credentials', str(lab / 'query-credentials.fengye.json'), '--line', '多线3',
        '--target', host['host_ip'], '--loader-script', 'p2_loader_host.py',
        '--session-name', host['session_name'], '--hold-seconds', '7200',
        '--loader-timeout', '7320'],
        env=child_env, stdout=(ev / 'p1.json').open('w'),
        stderr=(ev / 'p1.stderr').open('w'), start_new_session=True)
    (ev / 'processes.json').write_text(json.dumps(
        {'evidence': str(ev), 'watch_pid': watch.pid, 'driver_pid': driver.pid},
        ensure_ascii=False, indent=2))
    print(json.dumps({'evidence': str(ev), 'host': host,
                      'watch_pid': watch.pid, 'driver_pid': driver.pid}), flush=True)

    ack_at = {'wall': None, 'effect_read': False}
    t0 = time.time()
    while time.time() - t0 < 7500 and driver.poll() is None:
        time.sleep(5)
        try:
            lines = (ev / 'p35_live.jsonl').read_text().splitlines()
        except OSError:
            lines = []
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        acks = [e for e in events if e.get('ev') == 'cmd1_ack_observed']
        if acks and ack_at['wall'] is None:
            ack_at['wall'] = acks[0].get('wall')
            (ev / 'p35-cmd1-ack.json').write_text(json.dumps(
                {'ack_wall': ack_at['wall'], 'label': 'cmd1_prestart'},
                ensure_ascii=False, indent=2))
        if (ack_at['wall'] is not None and not ack_at['effect_read']
                and time.time() - ack_at['wall'] >= 12):
            try:
                rr = probe('p32_app_rows_read.py', [str(host['pid'])])
                (ev / 'rows-post-cmd1.stdout').write_text(rr.stdout)
            except Exception:
                pass
            ack_at['effect_read'] = True
        if (ev / 'p35-start-seen.json').exists() is False \
                and any(e.get('ev') == 'start_command_received' for e in events):
            (ev / 'p35-start-seen.json').write_text(json.dumps(
                {'wall': time.time()}, ensure_ascii=False, indent=2))
        if (ev / 'stop-p35').exists():
            break
    (ev / 'monitor_ended.json').write_text(json.dumps(
        {'wall': time.time(), 'driver_rc': driver.poll()}, ensure_ascii=False, indent=2))
    print(json.dumps({'ended': True, 'driver_rc': driver.poll()}), flush=True)


if __name__ == '__main__':
    main()
