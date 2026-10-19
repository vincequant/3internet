#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P41 live session join (Mac side): 風夜 session enters the room, holds.

Adapted from the proven p39c2_orchestrate.py registration half. Differences:
  - NO target host / NO send authorization: this run only REGISTERS a session
    and holds it (the leave frame is fired later by p41_fire_leave.py).
  - Room selection: --line name match in the 0x2013 room directory (same rule
    as p39c2: the room whose name contains e.g. 多线3).

Flow: lobby login (风夜) -> 0x2013 directory -> 0x200b enter -> 0x9000 grant
      (virtual_ip/user_id/token) -> 0x2002 hall leave -> spawn the Wine loader
      parent (p39c2_loader_host.py) -> registration receipts -> ready.json ->
      hold until stop-p41 (or parent exit).

One session per run; nothing is sent to the relay beyond normal loader
service traffic.
"""
import argparse
import fcntl
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from login_protocol import (Frames, Reader, Transport, encode, login_body,
                            wrap, room_directory, game_directory, user_record)
import p39c2_frame as frame_codec

LAB = Path.home() / 'sgi-protocol-lab-20260915'
LOGIN_SERVER = ('121.41.166.208', 25001)
EVIDENCE_ROOT = LAB / 'evidence' / 'p41-leave-live-20261016'
FORBIDDEN = {'p39c2_loader_host.py', 'p36e3_nonmember_probe.py',
             'p39c2_orchestrate.py', 'p1_directed_probe.py', 'p2_loader_host.py'}


def zpath(path):
    return 'Z:' + str(path).replace('/', '\\')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def read_jsonl(path, tail=None):
    rows = []
    try:
        with Path(path).open(encoding='utf-8') as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows[-tail:] if tail else rows


def wine_paths():
    sys.path.insert(0, str(Path.home() / 'Library/Application Support/SGI-Room-Monitor/opt'))
    from sgi_room_monitor.provision import default_paths, wine_env
    paths = default_paths()
    return paths['wine'], wine_env(
        paths['wine'],
        str(Path.home() / 'Library/Application Support/SGI-Wine/prefix-monitor'))


def jsonl(fh, obj):
    obj = dict(obj, wall=time.time())
    fh.write(json.dumps(obj, ensure_ascii=False, default=str) + '\n')
    fh.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--credentials', required=True)
    ap.add_argument('--line', default='多线3')
    ap.add_argument('--session-name', default='SGZWLB')
    ap.add_argument('--room-id', type=int, default=0,
                    help='强制目标房号（默认按 --line 在目录中匹配）')
    ap.add_argument('--reg-name', default='',
                    help='loader 注册的显示名（默认=登入账号名；同名入座测试用）')
    ap.add_argument('--keep-hall', action='store_true',
                    help='进房后不发送 0x2002；保持大厅连线并回应心跳（住下来模式）')
    ap.add_argument('--hold', type=int, default=5400)
    ap.add_argument('--login-timeout', type=int, default=240)
    args = ap.parse_args()

    lock = (LAB / 'p41.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ps = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    for line in ps.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        names = {Path(v.strip('"').replace('\\', '/')).name
                 for v in parts[1].split() if v.strip()}
        if names & FORBIDDEN:
            raise SystemExit('existing_research_chain_pid_' + parts[0])

    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    run_dir = EVIDENCE_ROOT / ('run-' + time.strftime('%H%M%S'))
    run_dir.mkdir(parents=True, exist_ok=False)
    live = (run_dir / 'orchestrator.jsonl').open('w', encoding='utf-8')
    started = time.time()
    jsonl(live, {'ev': 'start', 'args': {k: v for k, v in vars(args).items()
                                         if k != 'credentials'},
                 'credentials_file': Path(args.credentials).name,
                 'run_dir': str(run_dir)})
    identity = {
        'kind': 'p41_session_join', 'run_dir': str(run_dir), 'started_wall': started,
        'sources': {name: sha256_file(Path(__file__).resolve().parent / name)
                    for name in ('p41_orchestrate.py', 'p41_leave_frame.py',
                                 'p39c2_loader_host.py', 'p36e3_nonmember_probe.py')},
        'line': args.line, 'session_name': args.session_name,
    }
    (run_dir / 'run_identity.json').write_text(
        json.dumps(identity, ensure_ascii=False, indent=1), encoding='utf-8')

    creds = json.loads(Path(args.credentials).read_text())
    account = creds['username']
    password = creds['password']

    result = {'kind': 'p41_session_join', 'account': account,
              'run_dir': str(run_dir), 'login_verified': False,
              'hall_left': False, 'relay_started': False, 'frames': []}
    parser = Frames()
    transport = Transport()
    relay_config = None
    target = None
    parent = None
    own_id = None
    parent_log_fh = None
    parent_err_fh = None

    def spawn_parent(relay_cfg):
        wine, env = wine_paths()
        env = dict(env)
        env['P2_CHILD_SCRIPT'] = 'p36e3_nonmember_probe.py'
        env['P2_CHILD_ARGS_JSON'] = json.dumps([
            '--log', zpath(run_dir / 'p36e3_live.jsonl'),
            '--stop-file', zpath(run_dir / 'stop-e3')])
        env['P2_CHILD_STDERR'] = zpath(run_dir / 'child.stderr')
        env['P39C2_CTX_FILE'] = zpath(run_dir / 'ctx.json')
        env['P39C2_TABLE_LOG'] = zpath(run_dir / 'table.jsonl')
        log_fh = (run_dir / 'loader_host.stdout').open('w')
        err_fh = (run_dir / 'loader_host.stderr').open('w')
        proc = subprocess.Popen(
            [wine, str(LAB / 'python32/sgi-protocol-probe.exe'),
             '-X', 'utf8', str(LAB / 'p39c2_loader_host.py')],
            stdin=subprocess.PIPE, stdout=log_fh, stderr=err_fh, text=True, env=env)
        proc.stdin.write(json.dumps(relay_cfg))
        proc.stdin.close()
        return proc, log_fh, err_fh

    try:
        sock = socket.create_connection(LOGIN_SERVER, timeout=8)
        try:
            sock.sendall(wrap(encode(0x2001, 1, login_body(account, password))))
            deadline1 = time.monotonic() + args.login_timeout
            while relay_config is None and time.monotonic() < deadline1:
                sock.settimeout(0.25)
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    data = None
                except OSError as error:
                    jsonl(live, {'ev': 'login_socket_error', 'detail': str(error)[:200]})
                    break
                if data:
                    for main_, sub, payload in transport.feed(data):
                        if main_ == 101 and sub == 1:
                            for cmd, seq, body in parser.feed(payload):
                                row = {'command': hex(cmd), 'sequence': seq, 'bytes': len(body)}
                                if cmd == 0x2012:
                                    game, _ = game_directory(body)
                                    result.setdefault('games', []).append(game['name'])
                                    if '三国对战房' in game['name']:
                                        result['target_game'] = game['id']
                                elif cmd == 0x2013:
                                    room, _ = room_directory(body)
                                    result.setdefault('directory', []).append(
                                        {k: room[k] for k in ('game_id', 'id', 'name')})
                                    if (args.room_id and room['id'] == args.room_id) or (
                                            not args.room_id
                                            and room['game_id'] == result.get('target_game')
                                            and args.line in room['name'].replace(' ', '')):
                                        target = room
                                        result['target_room'] = {
                                            'room_id': target['id'], 'name': target['name'],
                                            'relay_server': target['server'],
                                            'relay_port': target['port']}
                                elif cmd == 0x2011:
                                    r = Reader(body)
                                    auth = r.number()
                                    r.string()
                                    result['login_verified'] = auth == 0
                                elif cmd == 0x9000 and len(body) >= 6:
                                    r = Reader(body)
                                    enter_result = r.number()
                                    r.string()
                                    ack_room = r.number()
                                    user = user_record(r)
                                    token = r.string()
                                    row['enter_result'] = enter_result
                                    row['ack_room'] = ack_room
                                    if enter_result == 0 and target and ack_room == target['id']:
                                        result['enter_result'] = 0
                                        relay_config = {
                                            'username': (args.reg_name or account),
                                            'virtual_ip': user['s2c'],
                                            'server': target['server'] or LOGIN_SERVER[0],
                                            'port': target['port'], 'game_id': target['game_id'],
                                            'room_id': target['id'], 'user_id': user['id'],
                                            'token': token, 'search_target': '0.0.0.0',
                                            'session_name': args.session_name,
                                            'hold_seconds': args.hold}
                                        result['virtual_ip'] = user['s2c']
                                        result['user_id'] = user['id']
                                        if args.keep_hall:
                                            result['hall_kept'] = True
                                            jsonl(live, {'ev': 'hall_kept'})
                                        else:
                                            sock.sendall(wrap(encode(0x2002, 3)))
                                            result['hall_left'] = True
                                        jsonl(live, {'ev': 'enter_ok',
                                                     'virtual_ip': user['s2c'],
                                                     'user_id': user['id'],
                                                     'room': {'id': target['id'],
                                                              'server': target['server'],
                                                              'port': target['port']}})
                                result['frames'].append(row)
                if result.get('login_verified') and target is not None \
                        and not result.get('enter_requested'):
                    sock.sendall(wrap(encode(0x200b, 2, struct.pack('<I', target['id']))))
                    result['enter_requested'] = target['id']
                    jsonl(live, {'ev': 'enter_requested', 'room': target['id']})
            if relay_config is None:
                jsonl(live, {'ev': 'login_timeout_or_error',
                             'login_verified': result['login_verified'],
                             'target': bool(target)})
            if relay_config is not None:
                result['relay_started'] = True
                (run_dir / 'relay-config.json').write_text(
                    json.dumps(relay_config, ensure_ascii=False, indent=1),
                    encoding='utf-8')
                parent, parent_log_fh, parent_err_fh = spawn_parent(relay_config)
                jsonl(live, {'ev': 'parent_spawned', 'pid': parent.pid})
                deadline2 = time.monotonic() + args.hold + 300
                hall_seq = 4
                hall_last_tx = 0.0
                if args.keep_hall:
                    sock.setblocking(False)
                while time.monotonic() < deadline2:
                    if args.keep_hall:
                        try:
                            while True:
                                data = sock.recv(65536)
                                if not data:
                                    break
                                for main_, sub, payload in transport.feed(data):
                                    if main_ == 101 and sub == 1:
                                        for cmd, seq, body in parser.feed(payload):
                                            if cmd == 0x2008 and time.monotonic() - hall_last_tx > 2:
                                                sock.sendall(wrap(encode(0x2008, hall_seq)))
                                                hall_last_tx = time.monotonic()
                                                jsonl(live, {'ev': 'hall_keepalive', 'seq': hall_seq, 'why': 'pong'})
                                                hall_seq += 1
                        except (BlockingIOError, InterruptedError):
                            pass
                        except OSError as error:
                            jsonl(live, {'ev': 'hall_socket_error', 'detail': str(error)[:120]})
                            break
                        if time.monotonic() - hall_last_tx >= 16.0:
                            try:
                                sock.sendall(wrap(encode(0x2008, hall_seq)))
                                hall_last_tx = time.monotonic()
                                jsonl(live, {'ev': 'hall_keepalive', 'seq': hall_seq, 'why': 'timer'})
                                hall_seq += 1
                            except OSError as error:
                                jsonl(live, {'ev': 'hall_socket_error', 'detail': str(error)[:120]})
                                break
                    ctx = read_json(run_dir / 'ctx.json')
                    if ctx:
                        if 'ctx_first_seen' not in result:
                            result['ctx_first_seen'] = ctx
                            jsonl(live, {'ev': 'ctx_seen', 'ctx': ctx})
                        result['ctx_last'] = ctx
                    if own_id is None:
                        for ev in read_jsonl(run_dir / 'p36e3_live.jsonl'):
                            if ev.get('ev') == 'relay_address':
                                own_id = ev.get('own_id')
                                jsonl(live, {'ev': 'child_relay_address', 'own_id': own_id})
                    if ctx and ctx.get('registered') and own_id is not None \
                            and not (run_dir / 'registration-receipt.json').exists():
                        expected = frame_codec.ip_to_id(relay_config['virtual_ip'])
                        receipt = {'ev': 'registration_receipt', 'own_id': own_id,
                                   'expected_from_virtual_ip': expected,
                                   'consistent': own_id == expected, 'ctx': ctx}
                        (run_dir / 'registration-receipt.json').write_text(
                            json.dumps(dict(receipt, wall=time.time()),
                                       ensure_ascii=False, indent=1), encoding='utf-8')
                        jsonl(live, receipt)
                        (run_dir / 'ready.json').write_text(
                            json.dumps({'wall': time.time(), 'own_id': own_id,
                                        'own_hex': '%08x' % own_id,
                                        'virtual_ip': relay_config['virtual_ip'],
                                        'room_id': relay_config['room_id'],
                                        'b_port': ctx.get('b_port')},
                                       ensure_ascii=False, indent=1), encoding='utf-8')
                        jsonl(live, {'ev': 'ready', 'own_id': own_id,
                                     'b_port': ctx.get('b_port')})
                    if (run_dir / 'stop-p41').exists():
                        jsonl(live, {'ev': 'stop_requested'})
                        break
                    if parent.poll() is not None:
                        jsonl(live, {'ev': 'parent_exited', 'rc': parent.returncode})
                        break
                    time.sleep(0.5)
                else:
                    jsonl(live, {'ev': 'deadline_reached'})
        finally:
            if args.keep_hall and result.get('hall_kept') and not result.get('hall_left'):
                try:
                    sock.sendall(wrap(encode(0x2002, 3)))
                    result['hall_left'] = True
                    jsonl(live, {'ev': 'hall_left_on_stop'})
                except OSError:
                    pass
            try:
                sock.close()
            except OSError:
                pass
    finally:
        if parent is not None and parent.poll() is None:
            (run_dir / 'stop-e3').write_text(json.dumps({'wall': time.time()}),
                                             encoding='utf-8')
            stop_ts = time.monotonic()
            while parent.poll() is None and time.monotonic() - stop_ts < 240:
                time.sleep(0.5)
        (run_dir / 'stop-p41').write_text(json.dumps({'wall': time.time()}),
                                          encoding='utf-8')
        for fh in (parent_log_fh, parent_err_fh):
            try:
                if fh:
                    fh.close()
            except OSError:
                pass
        parent_exit = None if parent is None else parent.poll()
        result['parent_exit'] = parent_exit
        result['elapsed_ms'] = round((time.time() - started) * 1000)
        (run_dir / 'summary.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        jsonl(live, {'ev': 'end', 'parent_exit': parent_exit})
        print(json.dumps({'run_dir': str(run_dir), 'own_id': own_id,
                          'parent_exit': parent_exit}, ensure_ascii=True))


if __name__ == '__main__':
    main()
