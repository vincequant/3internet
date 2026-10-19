"""Host runner: VK main-account SearchSession contrast, InitDll 4577 vs 4578.

Does not launch SANPK. Does not write UserConfig. Never logs token or password.
Reads existing wineserver sockets only (no scan).
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

LAB = Path(__file__).resolve().parent
HUB = LAB.parent / 'SGI-Hub-CrossOver-M4-0.2'
WATCHED = {25001, 9151, 4577, 4578, 7777}
TK_URL = 'https://www.vkquant.ai/api/public/sgi-tk/latest'


def _sys_path():
    root = str(HUB / 'room_monitor')
    if root not in sys.path:
        sys.path.insert(0, root)


def prefix_procs(prefix):
    prefix = Path(prefix).resolve()
    root = str(prefix / 'drive_c/sgi/run-3.5')
    found = {'sanguo': [], 'sanpk': [], 'startserver': []}
    listing = subprocess.check_output(['/bin/ps', '-axo', 'pid=,command='], text=True, errors='replace')
    for line in listing.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid, command = int(fields[0]), fields[1]
        if pid == os.getpid():
            continue
        if 'win32_startserver.py' in command or 'main_loader_probe.py' in command:
            found['startserver'].append(pid)
            continue
        if 'sgi_wine_launcher.py lobby' in command:
            found['startserver'].append(pid)
            continue
        if 'SANPK.exe' in command and 'process_watch' not in command:
            found['sanpk'].append(pid)
        if 'SANGUO.exe' in command and 'process_watch' not in command:
            found['sanguo'].append(pid)
    return found


def stop_leftover_protocol(found):
    """Only if SANGUO is absent: leftover protocol SANPK/helper from Hub tests."""
    if found['sanguo']:
        return False, 'SANGUO running; will not stop'
    pids = found['sanpk'] + found['startserver']
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return True, pids


def wineserver_pid():
    listing = subprocess.check_output(['/bin/ps', '-axo', 'pid=,command='], text=True, errors='replace')
    for line in listing.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[1].rstrip().endswith('/wineserver'):
            return int(fields[0])
    return None


def socket_snapshot():
    pid = wineserver_pid()
    rows = []
    if pid is None:
        return {'wineserver_pid': None, 'watched': []}
    try:
        out = subprocess.check_output(
            ['/usr/sbin/lsof', '-nP', '-p', str(pid)],
            text=True, errors='replace', timeout=3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return {'wineserver_pid': pid, 'watched': []}
    for line in out.splitlines():
        if 'UDP' not in line and 'TCP' not in line:
            continue
        if any(str(port) in line for port in WATCHED) or '121.41.166.208' in line:
            rows.append(' '.join(line.split()))
    return {'wineserver_pid': pid, 'watched': rows}


def tk_snapshot():
    try:
        raw = urllib.request.urlopen(TK_URL, timeout=8).read()
        data = json.loads(raw.decode('utf-8'))
    except (OSError, ValueError, TimeoutError):
        return {'ok': False}
    rooms = ((data.get('snapshot') or {}).get('rooms')) or []
    return {
        'ok': True,
        'freshness': data.get('freshness'),
        'rooms': [{'name': r.get('name'), 'host': r.get('host'),
                   'current': r.get('current'), 'id': r.get('id')} for r in rooms],
    }


def public_grant(grant):
    return {k: grant.get(k) for k in
            ('virtual_ip', 'server', 'port', 'game_id', 'room_id', 'user_id', 'username')
            if grant.get(k) not in (None, '')}


def one_trial(port, grant, wine, prefix, py32, script):
    from sgi_room_monitor.provision import wine_env
    payload = dict(public_grant(grant))
    payload['udp_port'] = port
    payload['token'] = grant['token']
    env = wine_env(wine, prefix)
    before = socket_snapshot()
    proc = subprocess.Popen(
        [str(wine), str(py32), '-X', 'utf8', '-B', str(script)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    mid = {}

    def _mid():
        time.sleep(6)
        if proc.poll() is None:
            mid['snap'] = socket_snapshot()

    watcher = threading.Thread(target=_mid, daemon=True)
    watcher.start()
    try:
        out, err = proc.communicate(json.dumps(payload), timeout=55)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        parsed = {'ok': False, 'error': 'probe_timeout'}
        payload['token'] = None
        return parsed, before, mid.get('snap'), socket_snapshot(), (err or '')[-400:]
    payload['token'] = None
    watcher.join(1)
    parsed = None
    for line in (out or '').splitlines():
        if line.startswith('{'):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
    if parsed is None:
        parsed = {'ok': False, 'error': 'no_json', 'exit': proc.returncode}
    after = socket_snapshot()
    return parsed, before, mid.get('snap'), after, (err or '')[-400:]


def copy_scripts(prefix):
    dest = Path(prefix) / 'drive_c/sgi/room_monitor'
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'main_loader_probe.py').write_text(
        (LAB / 'main_loader_probe.py').read_text(encoding='utf-8'), encoding='utf-8')
    (dest / 'koeinm_probe.py').write_text(
        (LAB / 'koeinm_probe.py').read_text(encoding='utf-8'), encoding='utf-8')
    return Path(r'C:\sgi\room_monitor\main_loader_probe.py')


def main():
    _sys_path()
    from sgi_room_monitor.credentials import load_credentials
    from sgi_room_monitor.protocol_session import HallSession
    from sgi_room_monitor.provision import default_paths

    paths = default_paths()
    prefix = paths['main_prefix']
    wine = paths['wine']
    py32 = HUB / 'bridge/win32-python/sgi-py32.exe'
    if not wine.is_file() or not py32.is_file():
        print(json.dumps({'ok': False, 'error': 'missing_wine_or_py32'}))
        return 2
    found = prefix_procs(prefix)
    if found['sanguo']:
        print(json.dumps({'ok': False, 'error': 'sanguo_running', 'pids': found}))
        return 2
    if found['sanpk'] or found['startserver']:
        stopped, detail = stop_leftover_protocol(found)
        if not stopped:
            print(json.dumps({'ok': False, 'error': 'leftover', 'detail': detail}))
            return 2
        time.sleep(3)
        found = prefix_procs(prefix)
        if found['sanpk'] or found['startserver'] or found['sanguo']:
            print(json.dumps({'ok': False, 'error': 'leftover_still', 'pids': found}))
            return 2
    runtime = json.loads(
        (Path.home() / 'Library/Application Support/SGI-Wine/runtime.json').read_text(encoding='utf-8'))
    creds = load_credentials({
        'main_account_username': runtime.get('main_account_username') or '',
        'hub_root': str(HUB),
    }, prompt=False, kind='main')
    username = (creds.get('username') or '').strip()
    password = creds.get('password') or ''
    if not username or not password:
        print(json.dumps({'ok': False, 'error': 'no_main_creds'}))
        return 2
    script = copy_scripts(prefix)
    report = {
        'ok': False,
        'kind': 'main_search_probe_4577_vs_4578',
        'tk_before': tk_snapshot(),
        'trials': [],
        'launched_sanpk': False,
    }
    for port in (4577, 4578):
        session = HallSession()
        try:
            result = session.login_and_enter(username, password, line_title='多线2', timeout=12)
            if not result.get('ok'):
                report['trials'].append({
                    'udp_port': port,
                    'login': {k: result.get(k) for k in
                              ('ok', 'message', 'needs_user', 'game_name', 'room_name')},
                })
                break
            grant = session.grant_for_takeover()
            if not grant or not grant.get('token'):
                report['trials'].append({'udp_port': port, 'error': 'no_grant'})
                break
            shown = public_grant(grant)
            parsed, before, mid, after, err_tail = one_trial(
                port, grant, wine, prefix, py32, script)
            grant.clear()
            trial = {
                'udp_port': port,
                'login': {
                    'ok': True,
                    'game_name': result.get('game_name'),
                    'room_name': result.get('room_name'),
                    'game_id': result.get('game_id'),
                    'room_id': result.get('room_id'),
                },
                'grant': shown,
                'probe': {k: parsed.get(k) for k in parsed
                          if k not in ('token', 'password')},
                'sockets_before': before,
                'sockets_mid': mid,
                'sockets_after': after,
            }
            if err_tail:
                trial['wine_stderr_tail'] = err_tail
            report['trials'].append(trial)
        finally:
            session.close(logout=True)
        time.sleep(8)
    password = None
    creds = None
    report['tk_after'] = tk_snapshot()
    report['ok'] = any(
        (t.get('probe') or {}).get('ok') and (t.get('probe') or {}).get('room_names')
        for t in report['trials'])
    evidence = LAB / 'evidence' / ('main-search-' + str(time.time_ns()) + '.json')
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report['evidence'] = str(evidence)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['trials'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
