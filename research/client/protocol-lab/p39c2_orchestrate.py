#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P39c2 step-1 orchestrator (Mac side): non-member endpoint uplink, ONE shot.

Contract (task book 2026-10-16, channel 2 step 1):
  1. lobby login (research account 风夜) -> SearchSession -> enter 多线3 grant.
  2. spawn the Wine loader parent (p39c2_loader_host.py), which registers the
     non-member endpoint at the real relay and spawns the verified E3 child
     (p36e3_nonmember_probe.py) - no OpenSession anywhere.
  3. wait for ctx.json (B port) + child relay_address (own id); write a
     registration receipt; cross-check own id == virtual ip.
  4. wait for run-dir/send-authorization.json (human gate; written only after
     the user confirms the scene and says go). Then re-check: B port sane,
     target id present in the latest relay-fed table dump, own id match.
  5. build ONE 1000 instruction (p39c2_frame) carrying the 18-byte harmless
     envelope frame; sendto 127.0.0.1:<B port> exactly once; write the send
     receipt (bytes/sha/wall/sockname). No retry - ever; a failed validation
     sends nothing and is logged as a refusal.
  6. hold for observation; stop files end the chain; summary frozen.

Red lines honoured: single shot per run, no retry, only the local registered
endpoint is used, nothing is written to the relay except normal loader
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
EVIDENCE_ROOT = LAB / 'evidence' / 'p39c2-nonmember-uplink-20261016'
FORBIDDEN = {'p39c2_loader_host.py', 'p36e3_nonmember_probe.py',
             'p1_directed_probe.py', 'p2_loader_host.py',
             'p20_cmd2_verified_probe.py'}


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


def write_refusal(live, run_dir, reason, auth):
    record = {'ev': 'send_refused', 'reason': reason,
              'authorization_sha256': sha256_file(run_dir / 'send-authorization.json'),
              'authorization': auth}
    out = run_dir / ('send-refusal-%s.json' % record['authorization_sha256'][:12])
    out.write_text(json.dumps(dict(record, wall=time.time()), ensure_ascii=False,
                              indent=1, default=str), encoding='utf-8')
    jsonl(live, record)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--credentials', required=True)
    ap.add_argument('--line', default='多线3')
    ap.add_argument('--session-name', default='SGZWLB')
    ap.add_argument('--target', required=True, help='host id display 10.x.y.z')
    ap.add_argument('--hold', type=int, default=3600)
    ap.add_argument('--post-send-min', type=int, default=60)
    ap.add_argument('--login-timeout', type=int, default=240)
    args = ap.parse_args()

    lock = (LAB / 'p39c2.lock').open('a')
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
        'kind': 'p39c2_step1_run', 'run_dir': str(run_dir), 'started_wall': started,
        'sources': {name: sha256_file(Path(__file__).resolve().parent / name)
                    for name in ('p39c2_frame.py', 'p39c2_loader_host.py',
                                 'p36e3_nonmember_probe.py')},
        'lines': [args.line], 'session_name': args.session_name,
        'target_display': args.target,
    }
    (run_dir / 'run_identity.json').write_text(
        json.dumps(identity, ensure_ascii=False, indent=1), encoding='utf-8')

    creds = json.loads(Path(args.credentials).read_text())
    account = creds['username']
    password = creds['password']
    target_id = frame_codec.ip_to_id(args.target)

    result = {'kind': 'p39c2_step1', 'account': account, 'target': args.target,
              'target_id': target_id, 'run_dir': str(run_dir),
              'login_verified': False, 'hall_left': False,
              'relay_started': False, 'enter_result': None, 'frames': []}
    parser = Frames()
    transport = Transport()
    relay_config = None
    target = None
    parent = None
    own_id = None
    sent = False
    refused_sha = None
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
        env['P39C2_CTX_FILE'] = zpath(run_dir / 'p39c2_ctx.json')
        env['P39C2_TABLE_LOG'] = zpath(run_dir / 'p39c2_table.jsonl')
        log_fh = (run_dir / 'p39c2_host.stdout').open('w')
        err_fh = (run_dir / 'p39c2_host.stderr').open('w')
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
            # ---------------- phase 1: lobby FSM until the relay grant ----------------
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
                                    if room['game_id'] == result.get('target_game') \
                                            and args.line in room['name'].replace(' ', ''):
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
                                            'username': account, 'virtual_ip': user['s2c'],
                                            'server': target['server'] or LOGIN_SERVER[0],
                                            'port': target['port'], 'game_id': target['game_id'],
                                            'room_id': target['id'], 'user_id': user['id'],
                                            'token': token, 'search_target': args.target,
                                            'session_name': args.session_name,
                                            'hold_seconds': args.hold}
                                        result['virtual_ip'] = user['s2c']
                                        result['user_id'] = user['id']
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
                jsonl(live, {'ev': 'login_timeout_or_error', 'login_verified':
                             result['login_verified'], 'target': bool(target)})
            # ---------------- phase 2: registration + single-shot gate ----------------
            if relay_config is not None:
                result['relay_started'] = True
                (run_dir / 'relay-config.json').write_text(
                    json.dumps(relay_config, ensure_ascii=False, indent=1),
                    encoding='utf-8')
                parent, parent_log_fh, parent_err_fh = spawn_parent(relay_config)
                jsonl(live, {'ev': 'parent_spawned', 'pid': parent.pid})

                deadline2 = time.monotonic() + args.hold + 300
                send_wall = None
                while time.monotonic() < deadline2:
                    ctx = read_json(run_dir / 'p39c2_ctx.json')
                    if ctx:
                        if 'ctx_first_seen' not in result:
                            result['ctx_first_seen'] = ctx
                            jsonl(live, {'ev': 'ctx_seen', 'ctx': ctx})
                        result['ctx_last'] = ctx
                    if own_id is None:
                        for ev in read_jsonl(run_dir / 'p36e3_live.jsonl'):
                            if ev.get('ev') == 'relay_address':
                                own_id = ev.get('own_id')
                                jsonl(live, {'ev': 'child_relay_address',
                                             'own_id': own_id})
                    if ctx and ctx.get('registered') and own_id is not None \
                            and not (run_dir / 'registration-receipt.json').exists():
                        expected = frame_codec.ip_to_id(relay_config['virtual_ip'])
                        ok = own_id == expected
                        receipt = {'ev': 'registration_receipt', 'own_id': own_id,
                                   'expected_from_virtual_ip': expected,
                                   'consistent': ok, 'ctx': ctx}
                        (run_dir / 'registration-receipt.json').write_text(
                            json.dumps(dict(receipt, wall=time.time()),
                                       ensure_ascii=False, indent=1),
                            encoding='utf-8')
                        jsonl(live, receipt)
                        if not ok:
                            jsonl(live, {'ev': 'abort_own_id_mismatch'})
                            break
                    auth_path = run_dir / 'send-authorization.json'
                    auth = read_json(auth_path)
                    if auth and not sent and refused_sha != sha256_file(auth_path):
                        table_rows = []
                        for t in read_jsonl(run_dir / 'p39c2_table.jsonl', tail=3):
                            table_rows.extend(t.get('rows', []))
                        reason = frame_codec.validate_authorization(
                            auth, target_id, own_id,
                            ctx.get('b_port') if ctx else None, table_rows)
                        if reason is not None:
                            write_refusal(live, run_dir, reason, auth)
                            refused_sha = sha256_file(auth_path)
                        else:
                            payload = frame_codec.step1_frame(own_id)
                            own_port = int(auth.get('own_port', 7777)) & 0xFFFF
                            instr = frame_codec.instr1000(
                                own_id, own_port, target_id, auth['target_port'],
                                payload, flag4=0, flag5=0)
                            (run_dir / 'sent-datagram.bin').write_bytes(instr)
                            sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            sock_tx.bind(('127.0.0.1', 0))
                            b_port = ctx['b_port']
                            rc = sock_tx.sendto(instr, ('127.0.0.1', b_port))
                            sent = True
                            send_wall = time.time()
                            receipt = {
                                'ev': 'send_receipt', 'rc': rc,
                                'dst': ['127.0.0.1', b_port],
                                'sockname': list(sock_tx.getsockname()),
                                'instruction_hex': instr.hex(),
                                'instruction_sha256': frame_codec.sha256_hex(instr),
                                'frame_hex': payload.hex(),
                                'frame_sha256': frame_codec.sha256_hex(payload),
                                'own_id': own_id, 'own_port': own_port,
                                'target_id': target_id,
                                'target_id_display': frame_codec.id_to_ip(target_id),
                                'target_port': auth['target_port'],
                                'authorization_sha256': sha256_file(auth_path),
                                'authorization': auth,
                                'table_rows_matched': [r for r in table_rows
                                                       if r.get('id') == target_id][:2]}
                            (run_dir / 'send-receipt.json').write_text(
                                json.dumps(dict(receipt, wall=time.time()),
                                           ensure_ascii=False, indent=1,
                                           default=str), encoding='utf-8')
                            jsonl(live, receipt)
                            sock_tx.close()
                            result['send'] = receipt
                    elif auth and sent:
                        dup = run_dir / 'duplicate-refusal.json'
                        if not dup.exists():
                            rec = {'ev': 'send_duplicate_refused',
                                   'authorization_sha256': sha256_file(auth_path),
                                   'note': 'one frame per run; no retries'}
                            dup.write_text(json.dumps(dict(rec, wall=time.time()),
                                                      indent=1), encoding='utf-8')
                            jsonl(live, rec)
                    if (run_dir / 'stop-p39c2').exists():
                        jsonl(live, {'ev': 'stop_requested'})
                        break
                    if parent.poll() is not None:
                        jsonl(live, {'ev': 'parent_exited', 'rc': parent.returncode})
                        break
                    time.sleep(0.5)
                else:
                    jsonl(live, {'ev': 'deadline_reached'})
                if sent and send_wall is not None:
                    result['sent_wall'] = send_wall
        finally:
            try:
                sock.close()
            except OSError:
                pass
    finally:
        # stop sequence: child stop file -> parent exit -> summary
        if parent is not None and parent.poll() is None:
            (run_dir / 'stop-e3').write_text(json.dumps({'wall': time.time()}),
                                             encoding='utf-8')
            stop_ts = time.monotonic()
            while parent.poll() is None and time.monotonic() - stop_ts < 240:
                time.sleep(0.5)
        (run_dir / 'stop-p39c2').write_text(json.dumps({'wall': time.time()}),
                                            encoding='utf-8')
        for fh in (parent_log_fh, parent_err_fh):
            try:
                if fh:
                    fh.close()
            except OSError:
                pass
        parent_exit = None if parent is None else parent.poll()
        parent_final = None
        out_path = run_dir / 'p39c2_host.stdout'
        if out_path.exists():
            lines = [x for x in out_path.read_text(encoding='utf-8').splitlines()
                     if x.strip().startswith('{')]
            if lines:
                try:
                    parent_final = json.loads(lines[-1])
                except ValueError:
                    parent_final = None
        result['parent_exit'] = parent_exit
        result['parent_final'] = parent_final
        result['one_shot'] = {'sent': sent, 'count': 1 if sent else 0}
        result['elapsed_ms'] = round((time.time() - started) * 1000)
        (run_dir / 'summary.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        jsonl(live, {'ev': 'end', 'sent': sent, 'parent_exit': parent_exit})
        print(json.dumps({'run_dir': str(run_dir), 'sent': sent,
                          'own_id': own_id, 'parent_exit': parent_exit,
                          'frame': result.get('send', {}).get('frame_hex'),
                          'instruction': result.get('send', {}).get('instruction_hex')},
                         ensure_ascii=True))


if __name__ == '__main__':
    main()
