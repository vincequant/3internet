import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import hashlib
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from fengye_source import FengyeSource, backend, control_ready, feed_items, mode_text, validate_control, decoded_commands


def online():
    return {'transport': {'status': 'online', 'checked_at': time.time()},
            'p34': {'live_probe': True, 'run_name': 'run-test'}}


class FakeSources:
    source_file = None

    def __init__(self):
        self.current = online()
        self.calls = []

    def view(self):
        return self.current

    def refresh(self, search=False):
        return self.current

    def control(self, payload):
        self.calls.append(payload)
        return {'status': 'sent', 'id': 'single-request'}


class NativeTests(unittest.TestCase):
    def test_controls_require_probe_online_and_fresh_observation(self):
        v = online()
        now = v['transport']['checked_at']
        self.assertTrue(control_ready(v, now))
        self.assertFalse(control_ready(v, now + 21))
        self.assertFalse(control_ready(v, now - 1))
        for status in ('file', 'offline', 'not_checked'):
            v['transport']['status'] = status
            self.assertFalse(control_ready(v, now))
        v = online()
        v['p34']['live_probe'] = False
        self.assertFalse(control_ready(v))

    def test_replay_never_sends_even_if_file_claims_probe_live(self):
        fake = FakeSources()
        fake.source_file = 'record.json'
        source = FengyeSource(sources=fake)
        self.assertEqual(source.send({'op': 'stop'})['status'], 'error')
        self.assertEqual(fake.calls, [])

    def test_native_source_sends_exactly_one_request(self):
        fake = FakeSources()
        source = FengyeSource(sources=fake)
        self.assertEqual(source.send({'op': 'chat', 'text': '风夜测试', 'extra': 'ignored'})['status'], 'sent')
        self.assertEqual(fake.calls, [{'op': 'chat', 'text': '风夜测试'}])

    def test_failed_or_ambiguous_backend_is_not_retried(self):
        fake = FakeSources()
        fake.control = mock.Mock(side_effect=TimeoutError('unknown result'))
        with self.assertRaises(TimeoutError):
            FengyeSource(sources=fake).send({'op': 'stop'})
        fake.control.assert_called_once_with({'op': 'stop'})

    def test_gbk_character_limit_is_not_a_byte_limit(self):
        self.assertEqual(len(validate_control({'op': 'chat', 'text': '风' * 120})['text']), 120)
        for text in ('风' * 121, '🙂', '', '   '):
            with self.assertRaises(ValueError):
                validate_control({'op': 'chat', 'text': text})

    def test_replay_does_not_start_http_or_ssh(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.json'
            path.write_text(json.dumps({'p34': {'live_probe': True, 'run_name': 'old-run'}}))
            with mock.patch.object(backend, 'make_server') as listen, mock.patch.object(backend.subprocess, 'run') as runner:
                source = FengyeSource(data_dir=Path(folder) / 'cache', replay=path)
                view = source.refresh()
                self.assertEqual(view['transport']['status'], 'file')
                self.assertFalse(control_ready(view))
                self.assertIn('回放', mode_text(view))
                self.assertEqual(source.send({'op': 'stop'})['status'], 'error')
                runner.assert_not_called()
                listen.assert_not_called()

    def test_backend_limiter_and_no_retry_survive_direct_native_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({'status': 'sent', 'id': 'once'}), ''))
            raw_source = backend.Sources(host='authorized-test-host', data_dir=folder, runner=runner)
            raw_source.transport = online()['transport']
            raw_source.raw = {'p34': {'live_probe': True}}
            source = FengyeSource(sources=raw_source)
            self.assertEqual(source.send({'op': 'stop'})['status'], 'sent')
            self.assertEqual(source.send({'op': 'stop'})['status'], 'rate_limited')
            self.assertEqual(runner.call_count, 1)

    def test_feed_keeps_real_counts_and_bounds_raw_detail(self):
        raw_hex = b'CSanInetDomesticCmd'.hex() + '00' * 500
        view = {'p34': {'frames': [{'wall': 1, 'cmd': 7, 'len': 714}],
                        'sync': {'nonempty': [{'wall': 2, 'round': 9, 'records': [{'raw': raw_hex}]}]},
                        'chat': {'messages': [{'wall': 3, 'text': 'hello'}]},
                        'control': {'events': [{'wall': 4, 'ev': 'control_done', 'rc': 0}]}}}
        before = copy.deepcopy(view)
        items = feed_items(view)
        self.assertEqual(len(items), 4)
        self.assertEqual([x['kind'] for x in items], ['control', 'chat', 'data', 'frame'])
        self.assertEqual(items[2]['label'], 'CSanInetDomesticCmd')
        self.assertEqual(len(items[2]['detail'].split('\n')[-1]), 240)
        self.assertEqual(view, before)
        self.assertEqual(feed_items({}), [])

    def test_source_backend_fork_matches_reviewed_original(self):
        original = ROOT.parent / 'fengye-status-hub'
        if not original.exists():
            self.skipTest('source checkout comparison only')
        for name in ('server.py', 'remote_snapshot.py'):
            self.assertEqual((ROOT / 'backend' / name).read_bytes(), (original / name).read_bytes())

    def test_original_world_rendering_and_history_are_preserved(self):
        sys.path.insert(0, str(ROOT / 'app'))
        sys.path.insert(0, str(ROOT / 'bridge'))
        from native_window import FengyeWindow
        from omni_window import OmniWindow
        self.assertTrue(issubclass(FengyeWindow, OmniWindow))
        self.assertIs(FengyeWindow.fetch, OmniWindow.fetch)
        self.assertIs(FengyeWindow.tick, OmniWindow.tick)
        self.assertIs(FengyeWindow.confirm_player, OmniWindow.confirm_player)
        self.assertIs(FengyeWindow.pick_history_archive, OmniWindow.pick_history_archive)
        self.assertIs(FengyeWindow.clear_history_review, OmniWindow.clear_history_review)

    def test_fengye_uses_original_command_decoder_without_inventing_world_state(self):
        name = b'CSanInetDomesticCmd'
        raw = struct.pack('<3H', 0xffff, 1, len(name)) + name
        raw += struct.pack('<3iB4i', 18, 0, 0, 0, 17, 1, 79, 1)
        record = {'raw': raw.hex(), 'len': len(raw), 'sha8': hashlib.sha256(raw).hexdigest()[:12], 'sender': 12345}
        view = {'p34': {'run_name': 'test-run', 'sync': {'nonempty': [{'wall': 1000, 'round': 9, 'records': [record]}]}}}
        rows = decoded_commands(view)
        self.assertEqual(rows[0]['action'], '骑兵训练')
        self.assertEqual(rows[0]['actor_force_id'], 17)
        self.assertEqual(rows[0]['sender'], 12345)
        self.assertFalse(rows[0]['server_result_verified'])
        self.assertNotIn('entities', rows[0])
        record['sha8'] = '0' * 12
        self.assertIn('error', decoded_commands(view)[0])
        record['raw'] = record['raw'][:-2]
        self.assertIn('error', decoded_commands(view)[0])


if __name__ == '__main__':
    unittest.main()
