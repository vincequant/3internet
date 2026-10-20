import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from backend import fengyun_local

NOT_LOGGED_IN = '协议登录提示用户已经登录。请本人在已登录端退出，或在大厅勾选强制登录。不会再次交密码。'

HOLD_EVENTS = [
    {'ev': 'login', 'ok': True, 'message': '协议已进入多线3（备用）'},
    {'ev': 'helper_spawned', 'pid': 1266},
    {'helper': {'event': 'game_search', 'ok': True, 'list_names': ['SGZWLB[丁满]']}},
    {'ev': 'result', 'ok': True, 'helper_pid': 1266},
    {'ev': 'hold_started', 'helper_pid': 1266},
]
ABORT_EVENTS = [
    {'ev': 'start', 'account': 'fengyun'},
    {'ev': 'login', 'ok': False, 'stage': 'protocol_login', 'message': NOT_LOGGED_IN},
    {'ev': 'abort', 'reason': 'login', 'stage': 'protocol_login'},
]


def make_root(tmp, logs):
    root = Path(tmp)
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    for name, events, age in logs:
        path = root / 'logs' / name
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events),
                        encoding='utf-8')
        if age:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
    return root


class LiveStatusTests(unittest.TestCase):
    def setUp(self):
        # Fixture logs use a fixed account independently of this Mac's profile.
        patcher = mock.patch.object(fengyun_local, 'FLOW_LOG_GLOB', 'direct-fengyun-*.jsonl')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _status(self, helper_pid, sanpk_pid):
        return mock.patch.object(fengyun_local, 'status', return_value={
            'helper_pid': helper_pid, 'sanpk_pid': sanpk_pid, 'stop_file': False, 'staging': True})

    def test_already_logged_message_is_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, [('direct-fengyun-a.jsonl', ABORT_EVENTS, None)])
            with mock.patch.object(fengyun_local, 'DIRECT_ROOT', root), self._status(0, 0):
                info = fengyun_local.live_status()
        self.assertEqual(info['state'], 'already_logged')
        self.assertIn('已登錄', info['headline'])

    def test_holding_reports_rooms_and_login_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, [('direct-fengyun-a.jsonl', HOLD_EVENTS, None)])
            with mock.patch.object(fengyun_local, 'DIRECT_ROOT', root), self._status(1266, 1315):
                info = fengyun_local.live_status()
        self.assertEqual(info['state'], 'holding')
        self.assertEqual(info['rooms'], ['SGZWLB[丁满]'])
        self.assertIn('已在線', info['headline'])

    def test_live_session_wins_over_newer_failed_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, [
                ('direct-fengyun-old.jsonl', HOLD_EVENTS, 300),
                ('direct-fengyun-new.jsonl', ABORT_EVENTS, None)])
            with mock.patch.object(fengyun_local, 'DIRECT_ROOT', root), self._status(1266, 1315):
                info = fengyun_local.live_status()
        self.assertEqual(info['state'], 'holding')
        self.assertEqual(info['rooms'], ['SGZWLB[丁满]'])

    def test_login_short_circuits_when_already_holding(self):
        with mock.patch.object(fengyun_local, 'live_status', return_value={
                'state': 'holding', 'alive': True, 'headline': '已在線', 'detail': 'x', 'rooms': []}), \
             mock.patch.object(fengyun_local, 'status', return_value={
                 'helper_pid': 1, 'sanpk_pid': 2, 'stop_file': False, 'staging': True}), \
             mock.patch.object(fengyun_local, 'ensure_staging') as staging:
            result = fengyun_local.login(line='多线3（备用）')
        self.assertEqual(result['status'], 'already_online')
        staging.assert_not_called()

    def test_login_uses_this_macs_configured_account(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(fengyun_local, 'ACCOUNT', 'dingman'), \
             mock.patch.object(fengyun_local, 'LOG_DIR', Path(tmp)), \
             mock.patch.object(fengyun_local, 'live_status', return_value={'state': 'not_started'}), \
             mock.patch.object(fengyun_local, 'ensure_staging'), \
             mock.patch.object(fengyun_local, 'status', return_value={}), \
             mock.patch.object(fengyun_local.subprocess, 'Popen') as spawn:
            fengyun_local.login()
        self.assertEqual(spawn.call_args.args[0][2], 'dingman')

    def test_force_close_delegates_to_game_only_launcher(self):
        with mock.patch.object(fengyun_local, 'status', return_value={}), \
             mock.patch.object(fengyun_local.subprocess, 'run',
                               return_value=mock.Mock(returncode=0)) as run:
            result = fengyun_local.force_kill()
        self.assertEqual(run.call_args.args[0][-1], 'game-stop')
        self.assertNotIn('-k', run.call_args.args[0])
        self.assertTrue(result['lobby_preserved'])

    def test_failed_game_close_is_not_reported_as_success(self):
        with mock.patch.object(fengyun_local, 'status', return_value={}), \
             mock.patch.object(fengyun_local.subprocess, 'run',
                               return_value=mock.Mock(returncode=1)):
            self.assertEqual(fengyun_local.force_kill()['status'], 'error')


if __name__ == '__main__':
    unittest.main()
