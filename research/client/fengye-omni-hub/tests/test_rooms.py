import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.room_protocol import nickname, request, reserve_join
from room_client import RoomClient


class RoomTests(unittest.TestCase):
    def test_names_validate_actual_wire_limit_and_controls(self):
        self.assertEqual(nickname('風夜'), '風夜')
        self.assertEqual(nickname('風'*15), '風'*15)
        for value in ('風'*16, '', ' ', 'A\nB', '🙂', 'A\x00B'):
            with self.assertRaises(ValueError):
                nickname(value)

    def test_join_is_bound_to_fresh_room_reply(self):
        p = request({'op': 'join', 'room_id': '16909060', 'nickname': '小白', 'virtual_ip': 'evil'})
        self.assertEqual(p['virtual_ip'], '1.2.3.4')
        state = {'phase': 'lobby', 'connected': False, 'room_query': {'observed_at': 100,
                 'rooms': [{'id': '16909060', 'name': 'SGZWLB', 'current': 1, 'maximum': 8}]}}
        self.assertEqual(reserve_join(p, state, 101)['session_name'], 'SGZWLB')
        with self.assertRaises(ValueError):
            reserve_join(p, state, 161)
        state['connected'] = True
        with self.assertRaises(ValueError):
            reserve_join(p, state, 101)
        state['connected'] = False
        state['room_query']['rooms'][0]['current'] = 8
        with self.assertRaises(ValueError):
            reserve_join(p, state, 101)
        state['room_query']['rooms'] = []
        with self.assertRaises(ValueError):
            reserve_join(p, state, 101)

    def test_join_quick_flag_only_passes_when_true(self):
        p = request({'op': 'join', 'room_id': '42', 'nickname': '風夜', 'quick': True})
        self.assertTrue(p['quick'])
        p = request({'op': 'join', 'room_id': '42', 'nickname': '風夜'})
        self.assertNotIn('quick', p)

    def test_remote_writer_forwards_quick_join(self):
        spec = importlib.util.spec_from_file_location('room_remote_quick', ROOT/'backend/room_remote.py')
        remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(remote)
        with tempfile.TemporaryDirectory() as folder:
            remote.HOME = Path(folder)
            run = Path(folder)/'run-owned'; run.mkdir()
            remote.write(remote.HOME/'active.json', {'directory': str(run)})
            with mock.patch.object(remote, 'status', return_value={'session_id': 's1', 'fresh': True}):
                result = remote.dispatch({'op': 'join', 'room_id': '42', 'nickname': '風夜',
                                          'quick': True, 'session_id': 's1'})
                self.assertEqual(result['status'], 'sent')
                payload = json.loads((run/'request.json').read_text())
                self.assertTrue(payload.get('quick'))
                self.assertEqual(payload['room_id'], '42')

    def test_replay_never_starts_ssh_or_session(self):
        runner = mock.Mock()
        client = RoomClient(host='test-host', replay=True, runner=runner)
        for op in ('status', 'start', 'search', 'leave', 'stop'):
            self.assertEqual(client.call({'op': op})['status'], 'error')
        runner.assert_not_called()

    def test_client_sends_one_bound_request_no_retry_on_timeout(self):
        runner = mock.Mock(side_effect=subprocess.TimeoutExpired('ssh', 15))
        client = RoomClient(host='test-host', runner=runner)
        client.state = {'session_id': 'session-1'}
        result = client.call({'op': 'join', 'room_id': 42, 'nickname': '風夜'})
        self.assertEqual(result['status'], 'unknown')
        runner.assert_called_once()
        cmd = runner.call_args[0][0]
        encoded = cmd[-1].split()[-1]
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        self.assertEqual(payload['session_id'], 'session-1')
        self.assertEqual(payload['nickname'], '風夜')

    def test_remote_writer_rejects_other_session_and_pending(self):
        spec = importlib.util.spec_from_file_location('room_remote_test', ROOT/'backend/room_remote.py')
        remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(remote)
        with tempfile.TemporaryDirectory() as folder:
            remote.HOME = Path(folder)
            run = Path(folder)/'run-owned'; run.mkdir()
            remote.write(remote.HOME/'active.json', {'directory': str(run)})
            current = {'session_id': 's1', 'fresh': True}
            with mock.patch.object(remote, 'status', return_value=current):
                self.assertEqual(remote.dispatch({'op': 'leave', 'session_id': 'other'})['status'], 'error')
                self.assertFalse((run/'request.json').exists())
                result = remote.dispatch({'op': 'leave', 'session_id': 's1'})
                self.assertEqual(result['status'], 'sent')
                first = (run/'request.json').read_bytes()
                result = remote.dispatch({'op': 'leave', 'session_id': 's1'})
                self.assertEqual(result['status'], 'error')
                self.assertEqual((run/'request.json').read_bytes(), first)

    def test_prestart_ops_validate_refuse_replay_and_forward_once(self):
        for op in ('register', 'd8'):
            self.assertEqual(request({'op': op}), {'op': op})
        with self.assertRaises(ValueError):
            request({'op': 'launch'})
        runner = mock.Mock()
        client = RoomClient(host='test-host', replay=True, runner=runner)
        for op in ('register', 'd8'):
            self.assertEqual(client.call({'op': op})['status'], 'error')
        runner.assert_not_called()

    def test_remote_writer_forwards_prestart_ops_with_pending_guard(self):
        spec = importlib.util.spec_from_file_location('room_remote_prestart', ROOT/'backend/room_remote.py')
        remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(remote)
        with tempfile.TemporaryDirectory() as folder:
            remote.HOME = Path(folder)
            run = Path(folder)/'run-owned'; run.mkdir()
            remote.write(remote.HOME/'active.json', {'directory': str(run)})
            with mock.patch.object(remote, 'status', return_value={'session_id': 's1', 'fresh': True}):
                for op in ('register', 'd8'):
                    result = remote.dispatch({'op': op, 'session_id': 's1'})
                    self.assertEqual(result['status'], 'sent')
                    payload = json.loads((run/'request.json').read_text())
                    self.assertEqual(payload['op'], op)
                    blocked = remote.dispatch({'op': 'leave', 'session_id': 's1'})
                    self.assertEqual(blocked['status'], 'error')
                    remote.write(run/'result.json', {'id': payload['id']})

    def test_start_refuses_to_take_over_another_research_chain(self):
        spec = importlib.util.spec_from_file_location('room_remote_start', ROOT/'backend/room_remote.py')
        remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
        with mock.patch.object(remote, 'status', return_value={'alive': False}), \
             mock.patch.object(remote.subprocess, 'check_output', return_value='12 python3 /lab/p1_directed_probe.py'), \
             mock.patch.object(remote.subprocess, 'Popen') as spawn:
            result = remote.start({'line': '多线3'})
            self.assertEqual(result['status'], 'error')
            spawn.assert_not_called()

    def test_existing_driver_loader_script_option_is_not_a_second_relay(self):
        spec = importlib.util.spec_from_file_location('room_remote_existing', ROOT/'backend/room_remote.py')
        remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
        ps = ('14133 14066 /usr/bin/python3 /lab/p1_directed_probe.py --line 多线3 --loader-script p2_loader_host.py\n'
              '14216 14133 /lab/python.exe -X utf8 /lab/p2_loader_host.py\n')
        with tempfile.TemporaryDirectory() as folder:
            remote.HOME = Path(folder)
            remote.write(remote.HOME/'existing-rooms.json', {'driver_pid': 14133, 'observed_at': time.time(), 'rooms': []})
            with mock.patch.object(remote.subprocess, 'check_output', return_value=ps), \
                 mock.patch.object(remote.subprocess, 'Popen') as spawn:
                state = remote.existing_lobby()
                self.assertTrue(state['external'])
                self.assertEqual(state['driver_pid'], 14133)
                spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
