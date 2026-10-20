"""One-shot controller, executed on the collector Mac through SSH.

Owns only its explicitly started P1/loader/probe chain. Does not read the
player's game process, alter saves, send battle commands or retry actions.
"""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

LAB = Path.home() / 'sgi-protocol-lab-20260915'
HOME = LAB / 'fengye-hub-session'


def read(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def write(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def process_alive(pid, marker):
    if not isinstance(pid, int):
        return False
    p = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
    return p.returncode == 0 and marker in p.stdout


def active_run():
    pointer = read(HOME / 'active.json')
    path = Path(pointer.get('directory', str(HOME / 'none'))).resolve()
    if HOME.resolve() not in path.parents:
        raise ValueError('會話路徑無效')
    return path, pointer


def existing_lobby(search=False):
    """Read/search a unique existing relay without taking over its member."""
    rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True)
    drivers, relays = [], []
    for row in rows.splitlines():
        parts = row.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            argv = shlex.split(parts[2], posix=False)
        except ValueError:
            continue
        first_option = next((i for i, v in enumerate(argv) if v.startswith('--')), len(argv))
        names = {Path(v.strip('"').replace('\\', '/')).name for v in argv[:first_option]}
        if 'p1_directed_probe.py' in names:
            drivers.append((int(parts[0]), argv))
        if names & {'p2_loader_host.py', 'p39c2_loader_host.py'}:
            relays.append((int(parts[0]), int(parts[1])))
    if len(drivers) != 1 or len(relays) != 1 or relays[0][1] != drivers[0][0]:
        return None
    pid, argv = drivers[0]
    line = argv[argv.index('--line')+1] if '--line' in argv else None
    if not line:
        return None
    cache = read(HOME / 'existing-rooms.json')
    if cache.get('driver_pid') != pid:
        cache = {}
    if search or time.time()-cache.get('observed_at', 0) >= 15:
        try:
            rt = read(Path.home() / 'Library/Application Support/SGI-Wine/runtime.json')
            env = dict(os.environ, WINEPREFIX=str(Path.home() / 'Library/Application Support/SGI-Wine/prefix-monitor'),
                       WINEDEBUG='-all', DYLD_FALLBACK_LIBRARY_PATH=rt.get('dependency_lib', ''))
            proc = subprocess.run([rt['wine'], str(LAB/'python32/sgi-protocol-probe.exe'), '-X', 'utf8',
                str(LAB/'koeinm_probe.py'), '--dll', r'C:\sgi\run-3.5\3I\Koeinm.dll',
                '--target', '255.255.255.255', '--port', '7777', '--app-id', '78731', '--with-nethook'],
                env=env, capture_output=True, text=True, timeout=15)
            replies = [json.loads(s) for s in proc.stdout.splitlines() if s.startswith('{')]
            result = next((r for r in reversed(replies) if 'query_status' in r), {})
            if proc.returncode or result.get('start_rc') != 0 or result.get('search_rc') != 0:
                raise ValueError('既有中繼查房未成功')
            import ipaddress
            rooms = result.get('rooms') or []
            for room in rooms:
                room['virtual_ip'] = str(ipaddress.IPv4Address(int(room['id'])))
            cache = {'driver_pid': pid, 'observed_at': result.get('observed_at'),
                     'status': result['query_status'], 'rooms': rooms, 'source': 'existing relay SearchSession'}
            write(HOME / 'existing-rooms.json', cache)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            cache = dict(cache, error='既有中繼查房不可用；保留原觀測時間')
    return {'phase': 'external_lobby', 'session_id': 'existing-' + str(pid), 'alive': True, 'fresh': True,
            'connected': False, 'external': True, 'line': line, 'driver_pid': pid, 'room_query': cache,
            'error': '現有研究會話僅供查房；進退房由原會話管理，未接管'}


def status(heartbeat=True):
    run, pointer = active_run()
    state = read(run / 'state.json')
    alive = process_alive(pointer.get('pid'), str(LAB / 'p1_directed_probe.py'))
    if not alive:
        existing = existing_lobby()
        if existing:
            return existing
    if heartbeat and alive:
        (run / 'heartbeat').touch()
    age = time.time() - state.get('observed_at', 0)
    fresh = alive and 0 <= age <= 15
    ctx = read(run / 'loader-context.json')
    channel = state.get('channel') or {}
    channel.update({k: ctx.get(k) for k in ('a_port', 'b_port', 'init_port')})
    state.update(session_id=pointer.get('id'), alive=alive, fresh=fresh, channel=channel,
                 line=pointer.get('line'), driver_pid=pointer.get('pid'))
    if not fresh:
        state['phase'] = 'starting' if alive and not state else 'stale' if alive else 'stopped'
        state['connected'] = False
    if not state.get('observed_at'):
        state['phase'] = 'starting' if alive else 'stopped'
    return state


def start(payload):
    old = status(False)
    if old.get('alive'):
        return {'status': 'error', 'error': '已有風夜大廳會話，請先停止再切換線路', 'session': old}
    # Never take over another experiment's session or authenticate concurrently.
    rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    blocked = {'p1_directed_probe.py', 'p2_loader_host.py', 'p39c2_loader_host.py'}
    for row in rows.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) != 2:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name for v in shlex.split(parts[1], posix=False)}
        if names & blocked:
            return {'status': 'error', 'error': '另有研究會話運行中，未重複登入或接管'}
    for name in ('p1_directed_probe.py', 'p39c2_loader_host.py', 'p28_window.py', 'p28_wire.py',
                 'query-credentials.fengye.json', 'python32/sgi-protocol-probe.exe'):
        if not (LAB / name).is_file():
            return {'status': 'error', 'error': '採集端缺少已配置的大廳執行環境：' + name}
    probe = base64.b64decode(payload['probe_source'])
    if hashlib.sha256(probe).hexdigest() != payload['probe_sha256']:
        raise ValueError('探針來源校驗失敗')
    session_id = uuid.uuid4().hex[:16]
    run = HOME / ('run-' + time.strftime('%Y%m%d-%H%M%S') + '-' + session_id)
    run.mkdir(parents=True)
    (run / 'room_probe.py').write_bytes(probe)
    protocol = base64.b64decode(payload['protocol_source'])
    if hashlib.sha256(protocol).hexdigest() != payload['protocol_sha256']:
        raise ValueError('協議驗證來源校驗失敗')
    (run / 'room_protocol.py').write_bytes(protocol)
    staged = LAB / 'fengye_hub_room_probe.tmp'
    staged.write_bytes(probe)
    staged.replace(LAB / 'fengye_hub_room_probe.py')
    write(run / 'identity.json', {'session_id': session_id})
    (run / 'heartbeat').touch()
    def zpath(path):
        return 'Z:' + str(path).replace('/', '\\')
    env = dict(os.environ, P2_CHILD_SCRIPT='fengye_hub_room_probe.py',
               P2_CHILD_ARGS_JSON=json.dumps(['--session-dir', zpath(run), '--lab', zpath(LAB)]),
               P2_CHILD_STDERR=zpath(run / 'probe.stderr'),
               P39C2_CTX_FILE=zpath(run / 'loader-context.json'),
               P39C2_TABLE_LOG=zpath(run / 'relay-table.jsonl'))
    with (run / 'driver.json').open('w') as out, (run / 'driver.stderr').open('w') as err:
        child = subprocess.Popen([sys.executable, str(LAB / 'p1_directed_probe.py'),
            '--credentials', str(LAB / 'query-credentials.fengye.json'), '--line', payload['line'],
            '--target', '255.255.255.255', '--loader-script', 'p39c2_loader_host.py',
            '--session-name', 'SGZWLB', '--hold-seconds', '86400', '--loader-timeout', '86520'],
            cwd=LAB, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    pointer = {'id': session_id, 'directory': str(run), 'pid': child.pid,
               'line': payload['line'], 'started_at': time.time(), 'probe_sha256': payload['probe_sha256']}
    write(HOME / 'active.json', pointer)
    return {'status': 'started', 'session': status()}


def dispatch(payload):
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        op = payload.get('op')
        if op == 'status':
            return {'status': 'ok', 'session': status()}
        if op == 'start':
            return start(payload)
        if op not in ('search', 'join', 'leave', 'stop', 'register', 'd8'):
            raise ValueError('未知操作')
        state = status()
        if state.get('external'):
            if op == 'search':
                return {'status': 'ok', 'session': existing_lobby(search=True)}
            return {'status': 'error', 'error': '現有研究會話僅供查房，未接管其進退房', 'session': state}
        if not state.get('fresh'):
            return {'status': 'error', 'error': '大廳會話尚未就緒', 'session': state}
        if payload.get('session_id') != state.get('session_id'):
            return {'status': 'error', 'error': '會話已更換，請重新核實', 'session': state}
        run, _ = active_run()
        pending = read(run / 'request.json')
        result = read(run / 'result.json')
        if pending and pending.get('id') != result.get('id'):
            return {'status': 'error', 'error': '上一個操作仍待回執，未再次送出', 'session': state}
        if op == 'join':
            # Worker validates room ID, freshness, name/encoding, and capacity
            # against its own current SearchSession reply before OpenSession.
            from_payload = {k: payload.get(k) for k in ('op', 'room_id', 'nickname', 'quick')}
        else:
            from_payload = {'op': op}
        from_payload.update(id=uuid.uuid4().hex[:16], session_id=state['session_id'], wall=time.time())
        write(run / 'request.json', from_payload)
        return {'status': 'sent', 'id': from_payload['id'], 'op': op, 'session': state}


if __name__ == '__main__':
    try:
        data = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode('utf-8'))
        print(json.dumps(dispatch(data), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': type(error).__name__ + ': ' + str(error)[:200]}, ensure_ascii=False))
