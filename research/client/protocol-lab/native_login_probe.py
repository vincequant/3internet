"""One bounded login attempt on the explicitly authorized second Mac alt only.

Credentials remain in the remote provider. Output contains metadata, no raw bodies.
"""
import json
import fcntl
import platform
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from login_protocol import Frames, Reader, Transport, encode, login_body, wrap, room_directory, game_directory, user_record


def main():
    started = time.monotonic()
    if platform.node().split('.')[0] != 'VKQUANT-COM' or Path.home().name != 'vkquant':
        raise RuntimeError('Probe restricted to the second Mac')
    lock = (Path(__file__).parent/'query.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sys.path.insert(0, str(Path.home() / 'Library/Application Support/SGI-Room-Monitor/opt'))
    from sgi_room_monitor.config import load_config
    from sgi_room_monitor.credentials import load_credentials
    from sgi_room_monitor.provision import wine_env, default_paths
    process_names = subprocess.check_output(['ps', '-axo', 'comm='], text=True).splitlines()
    monitor = '/Users/vkquant/Library/Application Support/SGI-Wine/prefix-monitor/'
    running = [x for x in process_names if x.startswith(monitor)
               and x.lower().endswith(('/sanguo.exe', '/sanpk.exe'))]
    if running:
        raise RuntimeError('Stop the monitor lobby/game before a credentials-only test')
    creds = load_credentials({'credentials_file': str(Path(__file__).parent/'query-credentials.json'), 'account_username': 'abcde'}, prompt=False)
    if creds['username'] != 'abcde' or not creds['password']:
        raise RuntimeError('Expected configured alt account is unavailable')
    packet = wrap(encode(0x2001, 1, login_body(creds['username'], creds['password'])))
    del creds
    result = {'kind': 'native_login_dll_relay_probe', 'authentication_uses_wine': False,
              'query_uses_wine': True,
              'monitor_lobby_or_game_running_at_start': False,
              'account': 'abcde', 'force_login': False, 'frames': [], 'login_verified': False}
    parser = Frames()
    transport = Transport()
    target = None
    target_game = None
    with socket.create_connection(('121.41.166.208', 25001), timeout=8) as sock:
        sock.sendall(packet)
        del packet
        end = time.monotonic() + 12
        while time.monotonic() < end:
            sock.settimeout(max(0.1, end-time.monotonic()))
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
                result.setdefault('transport', []).append({'main': main, 'sub': sub, 'bytes': len(payload)})
                if main == 101 and sub == 1:
                    decoded.extend(parser.feed(payload))
            for cmd, seq, body in decoded:
                row = {'command': hex(cmd), 'sequence': seq, 'body_bytes': len(body),
                       'crc_valid': True}
                if cmd == 0x2012:
                    game, _ = game_directory(body)
                    result.setdefault('games', []).append(game)
                    if '三国对战房' in game['name']:
                        target_game = game['id']
                if cmd == 0x2013:
                    room, _ = room_directory(body)
                    result.setdefault('directory', []).append(room)
                    if room['game_id'] == target_game and '多线2' in room['name'].replace(' ', ''):
                        target = room
                if cmd == 0x2011:
                    r = Reader(body)
                    row['auth_result'] = r.number()
                    # Server text is not logged until its schema is confirmed.
                    message = r.string()
                    row['auth_message_bytes'] = len(message.encode('utf-8'))
                    row['auth_message_categories'] = [word for word in
                        ['已经登录', '已登录', '重复', '密码', '帐号', '账号', '版本', '成功', '错误', '不存在', '强制']
                        if word in message]
                    result['login_verified'] = row['auth_result'] == 0
                    if result['login_verified'] and target:
                        sock.sendall(wrap(encode(0x200b, 2, struct.pack('<I', target['id']))))
                        result['enter_requested'] = target['id']
                if cmd == 0x9000 and seq == 2 and len(body) >= 6:
                    r = Reader(body)
                    row['enter_result'] = r.number()
                    message = r.string()
                    row['enter_message_categories'] = [x for x in ['成功', '错误', '密码', '房间', '不存在'] if x in message]
                    row['ack_room_id'] = r.number()
                    user = user_record(r)
                    token = r.string()
                    row['ack_complete'] = r.pos == len(body)
                    row['token_present'] = bool(token)
                    if row['enter_result'] == 0 and row['ack_room_id'] == target['id']:
                        sock.sendall(wrap(encode(0x200f, 3, struct.pack('<I', target['id']))))
                        relay_config = {'username': user['name'], 'virtual_ip': user['s2c'],
                            'server': target['server'] or '121.41.166.208', 'port': target['port'],
                            'game_id': target['game_id'], 'room_id': target['id'],
                            'user_id': user['id'], 'token': token}
                        wine = default_paths()['wine']
                        prefix = Path.home()/'Library/Application Support/SGI-Wine/prefix-monitor'
                        lab = Path(__file__).parent
                        relay = subprocess.run([str(wine), str(lab/'python32/sgi-protocol-probe.exe'),
                            '-X', 'utf8', str(lab/'loader_probe.py')], input=json.dumps(relay_config),
                            env=wine_env(wine, prefix), capture_output=True, text=True, timeout=25)
                        del relay_config
                        result['relay_exit'] = relay.returncode
                        result['relay'] = [json.loads(x) for x in relay.stdout.splitlines() if x.startswith('{')]
                if cmd == 0x2004:
                    r = Reader(body)
                    room_id, count = r.number(), r.number()
                    if count > 200:
                        raise ValueError('Unexpected user count')
                    users = [user_record(r) for _ in range(count)]
                    flag = r.number('B')
                    if r.pos != len(body):
                        raise ValueError('Unexpected user-list trailing bytes')
                    result.setdefault('room_users', []).append({'room_id': room_id,
                        'users': [{'id': u['id'], 'name': u['name']} for u in users], 'flag': flag})
                result['frames'].append(row)
            if result.get('relay') and any(x['flag'] == 0 for x in result.get('room_users', [])):
                result['end'] = 'query_complete'
                break
        if result['login_verified']:
            try:
                sock.sendall(wrap(encode(0x2002, 4)))
            except OSError:
                pass
    rooms = {}
    for relay in result.get('relay', []):
        for query in relay.get('queries', []):
            for q in query.get('results', []):
                for room in q.get('rooms', []):
                    rooms[(room['id'], room['name'], room['host'])] = room
    result['rooms'] = sorted(rooms.values(), key=lambda x: (x['id'], x['name'], x['host']))
    process_names = subprocess.check_output(['ps', '-axo', 'comm='], text=True).splitlines()
    result['monitor_lobby_or_game_running_at_end'] = any(x.startswith(monitor)
        and x.lower().endswith(('/sanguo.exe', '/sanpk.exe')) for x in process_names)
    result['credentials_only_verified'] = bool(result['login_verified'] and rooms
        and not result['monitor_lobby_or_game_running_at_end'])
    result['query_status'] = 'replies_received' if rooms else 'unconfirmed_empty'
    result['elapsed_ms'] = round((time.monotonic()-started)*1000)
    result['observed_at'] = time.time()
    ok = result['login_verified'] and any(x.get('relay_registered') for x in result.get('relay', []))
    if '--brief' in sys.argv:
        result = {k: result[k] for k in ['account', 'login_verified', 'query_status', 'rooms',
            'credentials_only_verified', 'elapsed_ms', 'observed_at']}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # Exception messages may contain protocol data: log class only.
        print(json.dumps({'error_type': type(error).__name__}))
        sys.exit(1)
