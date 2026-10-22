import json
import socket
import struct
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.login_protocol import encode, pack_string, wrap
from sgi_room_monitor.protocol_session import (
    GRANT_FIELDS, HallSession, classify_auth_message, grant_complete, pick_game,
    pick_room, public_session_view,
)
from sgi_room_monitor.sanpk_takeover import takeover_feasible, try_launch_playable_sanpk


FAKE_TOKEN = 'secret-grant-token'
FAKE_PASSWORD = 'hidden-password'


def _frame(command, sequence, body):
    return wrap(encode(command, sequence, body))


def _game_body(game_id, name):
    return (struct.pack('<I', game_id) + pack_string(name) + pack_string('') + pack_string('')
            + struct.pack('<BB', 0, 0) + pack_string('') + pack_string('') + pack_string(''))


def _room_body(game_id, room_id, name, server='121.41.166.208', port=7777):
    return (struct.pack('<II', game_id, room_id) + pack_string(name) + struct.pack('<B', 0)
            + struct.pack('<IIII', 0, 0, 0, 0) + pack_string(server) + struct.pack('<H', port)
            + pack_string('') + pack_string('') + struct.pack('<I', 0))


def _auth_body(result, message):
    return struct.pack('<I', result) + pack_string(message)


def _user_record(user_id=9, name='tester', vip='10.0.0.2'):
    return (struct.pack('<I', user_id) + pack_string(name) + pack_string('')
            + struct.pack('<I', 0) + pack_string('') + struct.pack('<6I', 0, 0, 0, 0, 0, 0)
            + pack_string(vip) + struct.pack('<B', 0))


def _enter_body(result, message, room_id, token=FAKE_TOKEN, vip='10.0.0.2'):
    return (struct.pack('<I', result) + pack_string(message) + struct.pack('<I', room_id)
            + _user_record(vip=vip) + pack_string(token))


def _member_body(room_id, records, flag=0):
    return struct.pack('<II', room_id, len(records)) + b''.join(records) + struct.pack('<B', flag)


def _login_reply(token=FAKE_TOKEN, vip='10.0.0.2'):
    return (
        _frame(0x2012, 1, _game_body(1001, '三国对战房'))
        + _frame(0x2013, 1, _room_body(1001, 88, '多线2'))
        + _frame(0x2011, 1, _auth_body(0, '成功'))
        + _frame(0x9000, 2, _enter_body(0, '成功', 88, token, vip=vip))
    )


class FakeSock:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.timeout = None
        self.closed = False
        self._lock = threading.Lock()

    def sendall(self, data):
        with self._lock:
            if self.closed:
                raise OSError('closed')
            self.sent.append(data)

    def recv(self, _n):
        with self._lock:
            if self.closed:
                return b''
            if self.chunks:
                return self.chunks.pop(0)
        raise socket.timeout()

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        with self._lock:
            self.closed = True


class PickTests(unittest.TestCase):
    def test_pick_sanguo_not_civ4(self):
        games = [{'id': 7, 'name': '文明4对战房'}, {'id': 1001, 'name': '三国对战房'}]
        self.assertEqual(pick_game(games)['id'], 1001)

    def test_pick_multiline2_not_civ_line(self):
        rooms = [
            {'game_id': 7, 'id': 1, 'name': '多线2'},
            {'game_id': 1001, 'id': 2, 'name': '多线2（主线）'},
            {'game_id': 1001, 'id': 3, 'name': '多线1'},
        ]
        self.assertEqual(pick_room(rooms, 1001)['id'], 2)

    def test_auth_already_logged_in_is_needs_user(self):
        info = classify_auth_message('用户已经登录')
        self.assertTrue(info['needs_user'])
        self.assertIn('已经登录', info['categories'])

    def test_public_view_drops_token(self):
        view = public_session_view({
            'ok': True, 'token': FAKE_TOKEN, 'password': 'x',
            '_grant': {'token': FAKE_TOKEN}, 'room_name': '多线2',
            'nested': {'token': FAKE_TOKEN, 'room_name': '多线2'},
            'members': [{'id': 1, 'name': 'a', 'token': FAKE_TOKEN}],
        })
        dumped = json.dumps(view)
        self.assertNotIn(FAKE_TOKEN, dumped)
        self.assertNotIn('password', dumped)
        self.assertEqual(view['room_name'], '多线2')
        self.assertEqual(view['nested']['room_name'], '多线2')
        self.assertEqual(view['members'][0]['name'], 'a')
        self.assertNotIn('token', view['members'][0])

    def test_grant_complete_requires_eight_fields(self):
        grant = {key: 1 for key in GRANT_FIELDS}
        grant['token'] = FAKE_TOKEN
        grant['username'] = 'tester'
        grant['virtual_ip'] = '10.0.0.2'
        grant['server'] = '121.41.166.208'
        self.assertTrue(grant_complete(grant))
        missing = dict(grant)
        missing['token'] = ''
        self.assertFalse(grant_complete(missing))
        self.assertFalse(grant_complete(None))


class SessionTests(unittest.TestCase):
    def test_login_enter_once_no_secrets_in_result(self):
        sock = FakeSock([_login_reply()])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        dumped = json.dumps(public_session_view(result))
        self.assertTrue(result['ok'])
        self.assertTrue(result['submitted'])
        self.assertTrue(result['entered'])
        self.assertEqual(result['room_id'], 88)
        self.assertNotIn(FAKE_PASSWORD, dumped)
        self.assertNotIn(FAKE_TOKEN, dumped)
        self.assertNotIn('5F4DCC3B5AA765D61D8327DEB882CF99', dumped)
        grant = session.grant_for_takeover()
        self.assertEqual(grant['token'], FAKE_TOKEN)
        self.assertEqual(set(grant), set(GRANT_FIELDS))
        session.close()
        self.assertTrue(sock.closed)
        self.assertIn(_frame(0x2002, 4, b''), sock.sent)
        self.assertIsNone(session.grant_for_takeover())

    def test_already_logged_in_stops_without_enter(self):
        reply = _frame(0x2011, 1, _auth_body(1, '用户已经登录'))
        sock = FakeSock([reply])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        self.assertTrue(result['submitted'])
        self.assertTrue(result['needs_user'])
        self.assertFalse(result['entered'])
        self.assertIn('已经登录', result['message'])
        self.assertEqual(len(sock.sent), 1)
        session.close()
        self.assertEqual(len(sock.sent), 1)

    def test_connect_fail_is_not_submitted(self):
        def boom(*_a):
            raise socket.timeout()
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=boom, timeout=1)
        self.assertFalse(result['submitted'])
        self.assertFalse(result['ok'])
        self.assertIn('回退', result['message'])

    def test_missing_token_is_fail_closed(self):
        sock = FakeSock([_login_reply(token='')])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        self.assertFalse(result['ok'])
        self.assertTrue(result['needs_user'])
        self.assertIsNone(session.grant_for_takeover())
        dumped = json.dumps(public_session_view(result))
        self.assertNotIn(FAKE_TOKEN, dumped)
        session.close()

    def test_empty_virtual_ip_is_fail_closed(self):
        sock = FakeSock([_login_reply(vip='')])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        self.assertFalse(result['ok'])
        self.assertIsNone(session.grant_for_takeover())
        session.close()

    def test_close_logout_false_does_not_send(self):
        sock = FakeSock([_login_reply()])
        session = HallSession()
        session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        before = list(sock.sent)
        session.close(logout=False)
        self.assertEqual(sock.sent, before)
        self.assertNotIn(_frame(0x2002, 4, b''), sock.sent)

    def test_pump_parses_members_and_keeps_socket(self):
        members = _frame(0x2004, 0, _member_body(88, [_user_record()]))
        tick = _frame(0x205c, 0, b'\x00' * 12)
        junk = _frame(0x205b, 0, b'\x00' * 8)
        sock = FakeSock([_login_reply(), members + tick + junk])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        self.assertTrue(result['ok'])
        self.assertFalse(sock.closed)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if session.result.get('members') and session.result.get('keepalive_rx'):
                break
            time.sleep(0.05)
        self.assertEqual(session.result['members'], [{'id': 9, 'name': 'tester'}])
        self.assertEqual(session.result['member_count'], 1)
        self.assertTrue(session.result['member_complete'])
        self.assertGreaterEqual(session.result['keepalive_rx'], 1)
        dumped = json.dumps(public_session_view(session.result))
        self.assertNotIn(FAKE_TOKEN, dumped)
        self.assertNotIn(FAKE_PASSWORD, dumped)
        self.assertNotIn('10.0.0.2', dumped)
        self.assertTrue(session._pump.is_alive())
        session.close()
        self.assertTrue(sock.closed)
        self.assertIn(_frame(0x2002, 4, b''), sock.sent)
        self.assertTrue(session.result.get('logout_sent'))
        self.assertIsNone(session.grant_for_takeover())

    def test_bad_member_frame_does_not_drop_session(self):
        bad = _frame(0x2004, 0, struct.pack('<II', 88, 1))
        tick = _frame(0x205c, 0, b'\x00' * 12)
        sock = FakeSock([_login_reply(), bad + tick])
        session = HallSession()
        result = session.login_and_enter('tester', FAKE_PASSWORD, connect=lambda *a: sock, timeout=2)
        self.assertTrue(result['ok'])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if session.result.get('keepalive_rx'):
                break
            time.sleep(0.05)
        self.assertGreaterEqual(session.result.get('keepalive_rx') or 0, 1)
        self.assertFalse(sock.closed)
        session.close()


class TakeoverTests(unittest.TestCase):
    def test_missing_prefix_is_not_feasible(self):
        check = takeover_feasible('/tmp/sgi-missing-prefix-for-test')
        self.assertFalse(check['feasible'])
        self.assertFalse(check['ok'])
        self.assertEqual(check['degrade'], 'ui_start')

    def test_try_launch_does_not_claim_playable(self):
        result = try_launch_playable_sanpk('/tmp/sgi-missing-prefix-for-test')
        self.assertFalse(result['ok'])
        self.assertIn('ui_start', result.get('degrade', ''))

    def test_force_ui_env_disables_takeover(self):
        with patch.dict('os.environ', {'SGI_FORCE_UI_FALLBACK': '1'}):
            check = takeover_feasible('/tmp/sgi-missing-prefix-for-test')
        self.assertFalse(check['feasible'])
        self.assertEqual(check['reason'], 'force_ui_fallback')

    def test_startserver_script_uses_eight_params_not_token_print(self):
        src = (Path(__file__).resolve().parents[1] / 'sgi_room_monitor/win32_startserver.py').read_text(encoding='utf-8')
        self.assertIn('StartServer.argtypes', src)
        self.assertIn('c_char_p, c.c_char_p, c.c_int, c.c_char_p', src)
        self.assertIn("cfg['token'] = None", src)
        self.assertNotIn('print(token', src)
        self.assertIn('/1an', src)
        self.assertIn('CreateMutexA', src)
        self.assertIn("'kind': 'nethook_client'", src)

    def test_gametool_whitelist_accepts_original_and_patch_rejects_unknown(self):
        import tempfile
        from sgi_room_monitor.sanpk_takeover import KNOWN_HASHES, file_digest, verify_binaries
        original, patched = KNOWN_HASHES['GameTool.dll']
        self.assertEqual(len(KNOWN_HASHES['GameTool.dll']), 2)
        self.assertIn('9667eff9c13d0307ba92f47d9f148d4f08bce32dd45e40bf606b27f9f2c179f1',
                      KNOWN_HASHES['GameTool.dll'])
        self.assertIn('d9e6167baec2628e6af5a0532929698921eaf1a0d28054ff00b1774408fb9640',
                      KNOWN_HASHES['GameTool.dll'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / '3I'
            game.mkdir()
            allowed = {
                'SANPK.exe': KNOWN_HASHES['SANPK.exe'],
                'Koeinm.dll': KNOWN_HASHES['Koeinm.dll'],
                'GameTool.dll': '0' * 64,
                'NetHookLoader.dll': KNOWN_HASHES['NetHookLoader.dll'],
                'NetHookCore.dll': KNOWN_HASHES['NetHookCore.dll'],
                'WS2.dll': KNOWN_HASHES['WS2.dll'],
            }
            for name in allowed:
                path = game / name if name in ('SANPK.exe', 'Koeinm.dll', 'GameTool.dll') else root / name
                path.write_bytes(name.encode())
            real = file_digest
            def fake_digest(path):
                name = Path(path).name
                if name == 'GameTool.dll':
                    return '0' * 64
                return KNOWN_HASHES[name] if name != 'GameTool.dll' else '0' * 64
            with patch('sgi_room_monitor.sanpk_takeover.file_digest', side_effect=fake_digest):
                checked = verify_binaries(root)
            self.assertFalse(checked['ok'])
            self.assertEqual(checked.get('mismatch'), 'GameTool.dll')
            unknown = file_digest(game / 'GameTool.dll')
            self.assertNotEqual(unknown, original)
            self.assertNotEqual(unknown, patched)


if __name__ == '__main__':
    unittest.main()
