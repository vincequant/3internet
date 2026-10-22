"""Main-account hall login and 多线2 enter over TCP 25001.

Stdlib only. Password is used once to build the login packet, then dropped.
Results never include password, MD5 digest, or enter-grant token.
"""
import socket
import struct
import threading
import time

from .login_protocol import (
    Frames, Reader, Transport, encode, game_directory, login_body,
    member_directory, room_directory, user_record, wrap,
)


HALL_HOST = '121.41.166.208'
HALL_PORT = 25001
LOGIN_CMD = 0x2001
LOGOUT_CMD = 0x2002
MEMBERS_LIST = 0x2004
ENTER_CMD = 0x200b
MEMBERS_CMD = 0x200f
AUTH_END = 0x2011
GAME_DIR = 0x2012
ROOM_DIR = 0x2013
SERVER_TICK = 0x205c
ENTER_ACK = 0x9000

DEFAULT_GAME = '三国对战房'
DEFAULT_LINE = '多线2'
AUTH_STOP_WORDS = ('已经登录', '已登录', '验证码', '验证')
AUTH_FAIL_WORDS = ('密码', '错误', '不存在', '帐号', '账号', '版本')
AUTH_OK_WORDS = ('成功',)
GRANT_FIELDS = (
    'virtual_ip', 'server', 'port', 'game_id', 'room_id', 'user_id', 'username', 'token',
)
# 0x205c is S2C only in protocol-lab captures (12-byte body, seq=0, repeats after
# enter). No client echo or other keepalive command appears in login_protocol,
# native_login_probe outbound, or those captures. Do not invent a C2S ping.


def compact_name(name):
    return (name or '').replace(' ', '').replace('\u3000', '')


def classify_auth_message(message):
    text = message or ''
    categories = [word for word in AUTH_STOP_WORDS + AUTH_FAIL_WORDS + AUTH_OK_WORDS if word in text]
    needs_user = any(word in text for word in AUTH_STOP_WORDS)
    failed = any(word in text for word in AUTH_FAIL_WORDS)
    return {'categories': categories, 'needs_user': needs_user, 'failed': failed}


def pick_game(games, title=DEFAULT_GAME):
    wanted = compact_name(title)
    exact = [row for row in games if compact_name(row.get('name')) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [row for row in games if wanted and wanted in compact_name(row.get('name'))]
    if len(partial) == 1:
        return partial[0]
    return None


def pick_room(rooms, game_id, line=DEFAULT_LINE):
    wanted = compact_name(line) or compact_name(DEFAULT_LINE)
    candidates = [row for row in rooms if row.get('game_id') == game_id
                  and wanted in compact_name(row.get('name'))]
    preferred_names = ['多线2（主线）', '多线2'] if wanted == '多线2' else [wanted]
    for preferred in preferred_names:
        exact = [row for row in candidates if compact_name(row.get('name')) == compact_name(preferred)]
        if len(exact) == 1:
            return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def grant_complete(grant):
    if not isinstance(grant, dict):
        return False
    for key in GRANT_FIELDS:
        value = grant.get(key)
        if value is None or value == '':
            return False
    return True


def public_members(listing):
    users = []
    for row in (listing or {}).get('users') or []:
        users.append({'id': row.get('id'), 'name': row.get('name')})
    return {
        'room_id': (listing or {}).get('room_id'),
        'count': (listing or {}).get('count', len(users)),
        'flag': (listing or {}).get('flag'),
        'users': users,
    }


def public_session_view(payload):
    """Drop any grant/token/password-shaped fields before status or logs."""
    blocked = ('password', 'passwd', 'secret', 'token', 'digest', 'grant', '_grant')

    def _scrub(value):
        if isinstance(value, dict):
            out = {}
            for key, inner in value.items():
                low = str(key).lower()
                if str(key).startswith('_') or low in blocked or any(part in low for part in blocked):
                    continue
                out[key] = _scrub(inner)
            return out
        if isinstance(value, list):
            return [_scrub(item) for item in value]
        return value

    if not isinstance(payload, dict):
        return {}
    return _scrub(payload)


class HallSession:
    """One TCP hall session. Caller must close()."""

    def __init__(self):
        self.sock = None
        self._grant = None
        self._pump = None
        self._stop = threading.Event()
        self._io = threading.Lock()
        self._lock = threading.Lock()
        self._keepalive_rx = 0
        self.members = []
        self.result = {}

    def login_and_enter(self, username, password, host=HALL_HOST, port=HALL_PORT,
                        game_title=DEFAULT_GAME, line_title=DEFAULT_LINE, timeout=12,
                        connect=None):
        started = time.monotonic()
        self.result = {
            'ok': False,
            'submitted': False,
            'needs_user': False,
            'stage': 'protocol_login',
            'message': '正在协议登录大厅…',
            'game_name': None,
            'room_name': None,
            'game_id': None,
            'room_id': None,
            'login_verified': False,
            'entered': False,
            'channel': 'protocol',
        }
        if not username or not password:
            self.result.update(message='主号凭据不完整', needs_user=True, stage='creds')
            return self.result
        try:
            packet = wrap(encode(LOGIN_CMD, 1, login_body(username, password)))
        except ValueError:
            self.result.update(message='登录字段无效', needs_user=True)
            return self.result
        connect = connect or _connect
        try:
            self.sock = connect(host, port, min(8, timeout))
            self.sock.sendall(packet)
            self.result['submitted'] = True
            self.result['message'] = '已提交协议登录，等待目录与进线授权…'
        except (OSError, socket.timeout):
            self.result.update(
                stage='protocol_login',
                message='协议登录服连接失败，将回退大厅界面',
                submitted=False,
            )
            return self.result
        finally:
            packet = None
            password = None
        games, rooms = [], []
        target_game = None
        target = None
        parser = Frames()
        transport = Transport()
        entered = False
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                self.sock.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    data = self.sock.recv(65536)
                except socket.timeout:
                    break
                if not data:
                    self.result['end'] = 'server_closed'
                    break
                decoded = []
                for main, sub, payload in transport.feed(data):
                    if main == 101 and sub == 1:
                        decoded.extend(parser.feed(payload))
                for cmd, seq, body in decoded:
                    if cmd == GAME_DIR:
                        game, _ = game_directory(body)
                        games.append(game)
                        target_game = pick_game(games, game_title)
                    elif cmd == ROOM_DIR:
                        room, _ = room_directory(body)
                        rooms.append(room)
                        if target_game:
                            target = pick_room(rooms, target_game['id'], line_title)
                    elif cmd == AUTH_END:
                        reader = Reader(body)
                        auth_result = reader.number()
                        message = reader.string()
                        info = classify_auth_message(message)
                        self.result['login_verified'] = auth_result == 0
                        self.result['auth_categories'] = info['categories']
                        if info['needs_user']:
                            self.result.update(
                                needs_user=True,
                                stage='protocol_login',
                                message=_auth_stop_message(info['categories']),
                            )
                            return self.result
                        if auth_result != 0 or info['failed']:
                            self.result.update(
                                needs_user=True,
                                stage='protocol_login',
                                message='协议登录被拒绝。请本人查看帐号提示。不会再次交密码。',
                            )
                            return self.result
                        self.result['stage'] = 'protocol_enter'
                        self.result['message'] = '协议已登录，正在进入三国对战房/多线2…'
                        if target_game is None:
                            target_game = pick_game(games, game_title)
                        if target_game and target is None:
                            target = pick_room(rooms, target_game['id'], line_title)
                    elif cmd == ENTER_ACK and seq == 2 and len(body) >= 6:
                        reader = Reader(body)
                        enter_result = reader.number()
                        enter_message = reader.string()
                        ack_room = reader.number()
                        user = user_record(reader)
                        token = reader.string()
                        enter_info = classify_auth_message(enter_message)
                        if enter_result != 0 or (target and ack_room != target['id']):
                            self.result.update(
                                needs_user=True,
                                stage='protocol_enter',
                                message='协议进线未授权。请本人查看大厅。不会再次交密码。',
                                auth_categories=enter_info['categories'],
                            )
                            token = None
                            return self.result
                        grant = {
                            'username': user.get('name'),
                            'virtual_ip': user.get('s2c'),
                            'server': (target or {}).get('server') or host,
                            'port': (target or {}).get('port'),
                            'game_id': (target or {}).get('game_id'),
                            'room_id': (target or {}).get('id') or ack_room,
                            'user_id': user.get('id'),
                            'token': token,
                        }
                        token = None
                        if not grant_complete(grant):
                            grant.clear()
                            self._grant = None
                            self.result.update(
                                ok=False,
                                entered=False,
                                needs_user=True,
                                stage='protocol_enter',
                                message='协议进线授权不完整。不会再次交密码。',
                            )
                            return self.result
                        self._grant = grant
                        entered = True
                        self.result.update(
                            ok=True,
                            entered=True,
                            stage='protocol_enter',
                            message='协议已进入' + ((target or {}).get('name') or '多线2'),
                            game_id=(target or {}).get('game_id'),
                            room_id=(target or {}).get('id') or ack_room,
                            game_name=(target_game or {}).get('name'),
                            room_name=(target or {}).get('name'),
                        )
                        try:
                            self._send(wrap(encode(MEMBERS_CMD, 3, struct.pack('<I', self._grant['room_id']))))
                        except OSError:
                            pass
                    else:
                        self._on_frame(cmd, seq, body)
                if self.result.get('login_verified') and target and not entered:
                    self._send(wrap(encode(ENTER_CMD, 2, struct.pack('<I', target['id']))))
                    entered = 'requested'
                    self.result['stage'] = 'protocol_enter'
                    self.result['message'] = '已请求进入' + target.get('name', '多线2')
                if self.result.get('ok'):
                    break
        except (OSError, ValueError):
            if not self.result.get('needs_user'):
                self.result.update(
                    needs_user=True,
                    message='协议会话异常结束。不会再次交密码。' if self.result.get('submitted')
                    else '协议登录失败，将回退大厅界面',
                )
            return self.result
        self.result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        if self.result.get('ok'):
            self._start_pump()
            return self.result
        if self.result.get('needs_user'):
            return self.result
        if self.result.get('submitted') and not self.result.get('login_verified'):
            self.result.update(
                needs_user=True,
                message='协议登录超时。不会再次交密码。请本人查看大厅。',
            )
            return self.result
        if self.result.get('login_verified') and not self.result.get('entered'):
            self.result.update(
                needs_user=True,
                stage='protocol_enter',
                message='协议已登录但未找到三国对战房/多线2。不会再次交密码。',
            )
            return self.result
        if not self.result.get('submitted'):
            self.result['message'] = '协议登录未发出，将回退大厅界面'
        return self.result

    def grant_for_takeover(self):
        """In-memory only. Caller must not log or persist the token."""
        grant = self._grant
        if not grant_complete(grant):
            return None
        return dict(grant)

    def logout(self):
        sock = self.sock
        if sock is None:
            return False
        try:
            self._send(wrap(encode(LOGOUT_CMD, 4)))
        except OSError:
            return False
        with self._lock:
            self.result['logout_sent'] = True
        return True

    def close(self, logout=True):
        if logout and self.result.get('login_verified'):
            self.logout()
        self._stop.set()
        sock = self.sock
        self.sock = None
        grant = self._grant
        self._grant = None
        if grant:
            grant.clear()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        pump = self._pump
        self._pump = None
        if pump and pump is not threading.current_thread():
            pump.join(timeout=1)

    def _send(self, packet):
        with self._io:
            sock = self.sock
            if sock is None:
                raise OSError('not connected')
            sock.sendall(packet)
            return True

    def _apply_members(self, listing):
        public = public_members(listing)
        with self._lock:
            self.members = list(public['users'])
            self.result['members'] = list(public['users'])
            self.result['member_count'] = public['count']
            self.result['member_room_id'] = public['room_id']
            self.result['member_complete'] = public['flag'] == 0

    def _on_frame(self, cmd, seq, body):
        if cmd == MEMBERS_LIST:
            try:
                listing = member_directory(body)
            except ValueError:
                return
            self._apply_members(listing)
        elif cmd == SERVER_TICK:
            with self._lock:
                self._keepalive_rx += 1
                self.result['keepalive_rx'] = self._keepalive_rx

    def _start_pump(self):
        if self.sock is None or (self._pump and self._pump.is_alive()):
            return
        self._stop.clear()

        def _run():
            transport = Transport()
            parser = Frames()
            while not self._stop.is_set():
                sock = self.sock
                if sock is None:
                    break
                try:
                    sock.settimeout(1.0)
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    if not self._stop.is_set():
                        with self._lock:
                            self.result['end'] = 'server_closed'
                    break
                try:
                    for main, sub, payload in transport.feed(data):
                        if main == 101 and sub == 1:
                            for cmd, seq, body in parser.feed(payload):
                                self._on_frame(cmd, seq, body)
                except ValueError:
                    break

        self._pump = threading.Thread(target=_run, name='sgi-hall-pump', daemon=True)
        self._pump.start()


def login_and_enter(username, password, **kwargs):
    session = HallSession()
    result = session.login_and_enter(username, password, **kwargs)
    if not result.get('ok'):
        session.close(logout=bool(result.get('login_verified')))
        return None, result
    return session, result


def _connect(host, port, timeout):
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    return sock


def _auth_stop_message(categories):
    joined = ''.join(categories or [])
    if '验证' in joined:
        return '协议登录需要验证码。请本人处理，不会再次交密码。'
    if '已经登录' in joined or '已登录' in joined:
        return '协议登录提示用户已经登录。请本人在已登录端退出，或在大厅勾选强制登录。不会再次交密码。'
    return '协议登录需要本人处理。不会再次交密码。'
