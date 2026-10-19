"""P1 directed-search probe on the second Mac: own grant, foreign room target.

One bounded login; enters the requested line with a real account, leaves the
hall (0x2002) immediately after the relay grant, then runs the original DLL
loader with a directed search target plus a broadcast control. Evidence-only;
prints one JSON object; never prints the password or token.

Usage:
  python3 p1_directed_probe.py --credentials <json-path> \
      --line 多线3 --target 10.x.x.x [--timeout-loader 60]
"""
import argparse
import fcntl
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from login_protocol import Frames, Reader, Transport, encode, login_body, wrap, room_directory, game_directory, user_record

PROBE_ROOT = Path(__file__).resolve().parent
LAB_REMOTE = Path.home()/'sgi-protocol-lab-20260915'


def wine_paths():
    sys.path.insert(0, str(Path.home() / 'Library/Application Support/SGI-Room-Monitor/opt'))
    from sgi_room_monitor.provision import default_paths, wine_env
    paths = default_paths()
    return paths['wine'], wine_env(paths['wine'],
        str(Path.home()/'Library/Application Support/SGI-Wine/prefix-monitor'))


def reg(work, args, timeout=60):
    return subprocess.run([work, 'reg', *args], env=WINE_ENV, capture_output=True,
                          timeout=timeout)


def main():
    global WINE_ENV
    ap = argparse.ArgumentParser()
    ap.add_argument('--credentials', required=True)
    ap.add_argument('--line', default='多线3')
    ap.add_argument('--target', required=True)
    ap.add_argument('--loader-timeout', type=int, default=90)
    ap.add_argument('--loader-script', default='p1_loader_directed.py')
    ap.add_argument('--session-name', default='SGZWLB')
    ap.add_argument('--hold-seconds', type=int, default=20)
    ap.add_argument('--winedebug', default=None)
    args = ap.parse_args()

    creds = json.loads(Path(args.credentials).read_text())
    password = creds.pop('password')
    del password
    account = creds['username']

    result = {'kind': 'p1_directed_search', 'account': account, 'line': args.line,
              'target': args.target, 'frames': [], 'rooms': [], 'login_verified': False,
              'hall_left': False, 'relay_started': False, 'enter_result': None}
    started = time.monotonic()
    creds_path = Path(args.credentials)
    login_server = None
    target = None
    relay_config = None
    parser = Frames()
    transport = Transport()
    loader = None
    with socket.create_connection(('121.41.166.208', 25001), timeout=8) as sock:
        sock.sendall(wrap(encode(0x2001, 1, login_body(account, json.loads(creds_path.read_text())['password']))))
        end = time.monotonic() + 30
        while time.monotonic() < end:
            sock.settimeout(max(0.1, end - time.monotonic()))
            try:
                data = sock.recv(65536)
            except socket.timeout:
                result['end'] = 'timeout'
                break
            if not data:
                result['end'] = 'server_closed'
                break
            decoded = []
            for main, sub, payload in transport.feed(data):
                if main == 101 and sub == 1:
                    decoded.extend(parser.feed(payload))
            for cmd, seq, body in decoded:
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
                    if room['game_id'] == result.get('target_game') and args.line in room['name'].replace(' ', ''):
                        target = room
                        result['target_room'] = {'room_id': target['id'], 'name': target['name'],
                            'relay_server': target['server'], 'relay_port': target['port']}
                elif cmd == 0x2011:
                    r = Reader(body)
                    auth = r.number()
                    r.string()
                    result['login_verified'] = auth == 0
                elif cmd == 0x9000 and len(body) >= 6:
                    r = Reader(body)
                    enter_result = r.number()
                    r.string()  # enter message, schema not established
                    ack_room = r.number()
                    user = user_record(r)
                    token = r.string()
                    row['enter_result'] = enter_result
                    row['ack_room'] = ack_room
                    if enter_result == 0 and target and ack_room == target['id']:
                        result['enter_result'] = 0
                        relay_config = {'username': account, 'virtual_ip': user['s2c'],
                            'server': target['server'] or '121.41.166.208', 'port': target['port'],
                            'game_id': target['game_id'], 'room_id': target['id'],
                            'user_id': user['id'], 'token': token,
                            'search_target': args.target,
                            'session_name': args.session_name,
                            'hold_seconds': args.hold_seconds}
                        result['virtual_ip'] = user['s2c']
                        result['line_server'] = target['server']
                        result['line_port'] = target['port']
                        sock.sendall(wrap(encode(0x2002, 3)))
                        result['hall_left'] = True
                result['frames'].append(row)
            if result.get('login_verified') and target and not result.get('enter_requested'):
                sock.sendall(wrap(encode(0x200b, 2, struct.pack('<I', target['id']))))
                result['enter_requested'] = target['id']
            if relay_config and not result['relay_started']:
                result['relay_started'] = True
                wine, WINE_ENV = wine_paths()
                WINE_ENV = dict(WINE_ENV)
                if args.winedebug:
                    WINE_ENV['WINEDEBUG'] = args.winedebug
                added = reg(wine, ['query', r'HKCU\Software\Wine\AppDefaults\sgi-protocol-probe.exe', '/v', 'Version']).returncode != 0
                if added:
                    reg(wine, ['add', r'HKCU\Software\Wine\AppDefaults\sgi-protocol-probe.exe', '/v', 'Version', '/t', 'REG_SZ', '/d', 'win81', '/f'])
                result['registry_key_added'] = added
                try:
                    relay_cfg = json.dumps(relay_config)
                    del relay_config
                    loader = subprocess.Popen([wine, str(LAB_REMOTE/'python32/sgi-protocol-probe.exe'),
                        '-X', 'utf8', str(LAB_REMOTE/args.loader_script)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, env=WINE_ENV)
                    out, err = loader.communicate(input=relay_cfg, timeout=args.loader_timeout)
                    result['loader_exit'] = loader.returncode
                    result['loader'] = [json.loads(x) for x in out.splitlines() if x.startswith('{')]
                    result['loader_stderr_tail'] = (err or '').strip()[-300:]
                finally:
                    if added:
                        reg(wine, ['delete', r'HKCU\Software\Wine\AppDefaults\sgi-protocol-probe.exe', '/f'])
            if result.get('relay_started') and loader is not None and loader.poll() is not None:
                result['end'] = 'loader_done'
                break
        if result.get('relay_started'):
            try:
                sock.sendall(wrap(encode(0x2002, 3)))
            except OSError:
                pass
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    result['observed_at'] = time.time()
    result['credentials_file'] = str(creds_path)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        WINE_ENV = None
        sys.exit(main() or 0)
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__, 'detail': str(error)[:200]}, ensure_ascii=True))
        sys.exit(1)
