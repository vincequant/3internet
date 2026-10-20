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
        # The renderer remains available; all inherited player-source entry
        # points are explicitly closed in this Fengye-only viewer.
        self.assertIsNot(FengyeWindow.fetch, OmniWindow.fetch)
        app = mock.Mock()
        with mock.patch('portable_client.poll') as poll:
            FengyeWindow.fetch(app)
            FengyeWindow.tick(app)
            poll.assert_not_called()
        with self.assertRaises(ValueError):
            FengyeWindow._apply_review(app, {'state': {'private_player_state': True}})

    def test_disabled_source_does_not_copy_or_open_player_settings(self):
        import os
        from local_runtime import configure
        import connection
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ):
            configure(folder)
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(connection.source_options(), {})
            cfg = connection.load_config()
            self.assertTrue(cfg['disabled'])
            with mock.patch.object(connection.subprocess, 'Popen') as spawn:
                with self.assertRaises(ConnectionError):
                    connection.Connection(cfg).ensure()
                spawn.assert_not_called()

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

    def test_dur_text_formats_long_windows(self):
        from native_window import dur_text
        self.assertEqual(dur_text(59), '59秒')
        self.assertEqual(dur_text(60), '1分')
        self.assertEqual(dur_text(82800), '23時00分')
        self.assertEqual(dur_text(-5), '0秒')
        self.assertEqual(dur_text(None), '—')
        self.assertEqual(dur_text('x'), '—')

    def test_mode_text_reports_current_session_and_never_replays(self):
        view = {'transport': {'status': 'online', 'checked_at': time.time()},
                'session': {'alive': True, 'fresh': True, 'phase': 'room'},
                'p34': {'run_name': 'run-x', 'live_probe': False}}
        self.assertEqual(mode_text(view), '本局會話 · 已在房間')
        view['session'] = {'alive': False, 'fresh': False, 'phase': 'stopped'}
        self.assertEqual(mode_text(view), '本局會話 · 已停止')
        view['session'] = None
        self.assertEqual(mode_text(view), '未就緒 · 尚無本局資料')
        view['p34'] = {'run_name': 'run-x', 'live_probe': True}
        self.assertEqual(mode_text(view), '在線 · 風夜探針')

    def test_operator_notification_is_local_and_never_injects_shell(self):
        import native_window
        calls = []
        with mock.patch.object(native_window.subprocess, 'Popen',
                               side_effect=lambda cmd, **kw: calls.append(cmd)), \
             mock.patch.object(native_window.sys, 'platform', 'darwin'):
            native_window.notify_operator('摘席已執行 "x"', '可以按開始"y"', sound='Glass')
        self.assertEqual(len(calls), 2)
        self.assertIn('osascript', calls[0][0])
        self.assertIn('afplay', calls[1][0])
        self.assertIn('Glass', calls[1][1])
        self.assertNotIn('"x"', ' '.join(calls[0]))
        calls.clear()
        with mock.patch.object(native_window.subprocess, 'Popen',
                               side_effect=lambda cmd, **kw: calls.append(cmd)), \
             mock.patch.object(native_window.sys, 'platform', 'win32'):
            native_window.notify_operator('t', 'm')
        self.assertEqual(calls, [])

    def test_one_click_retry_sequences_room_recovery(self):
        from native_window import FengyeWindow
        app = mock.Mock()
        app.retry_next = lambda: FengyeWindow.retry_next(app)
        app.room_busy = app.room_pending = app.room_uncertain = False
        app.room_line.get.return_value = '多线3'
        app.room_nickname.get.return_value = '風夜'
        app.rooms.state = {'connected': True, 'fresh': True, 'alive': True, 'phase': 'room'}
        app.retry = {'steps': ['leave', 'stop', 'wait_teardown', 'start', 'wait_lobby',
                               'search', 'wait_rooms'],
                     'deadline': time.monotonic() + 60, 'start_retries': 0}
        app.retry_next()
        app.room_action.assert_called_once_with({'op': 'leave'})
        self.assertEqual(app.retry['steps'][0], 'stop')
        app.room_action.reset_mock()
        FengyeWindow._maybe_retry(app, {'op': 'leave', 'status': 'completed'})
        app.room_action.assert_called_once_with({'op': 'stop'})
        self.assertEqual(app.retry['steps'][0], 'wait_teardown')
        app.rooms.state = {'alive': False, 'fresh': False, 'phase': 'stopped'}
        app.room_action.reset_mock()
        app.retry_next()
        app.room_action.assert_called_once_with({'op': 'start', 'line': '多线3'})
        self.assertEqual(app.retry['steps'][0], 'wait_lobby')
        app.rooms.state = {'alive': True, 'fresh': True, 'phase': 'lobby'}
        app.room_action.reset_mock()
        FengyeWindow._maybe_retry(app, {'op': 'start', 'status': 'started'})
        app.room_action.assert_called_once_with({'op': 'search'})
        self.assertEqual(app.retry['steps'][0], 'wait_rooms')
        app.rooms.state = {'alive': True, 'fresh': True, 'phase': 'lobby',
                           'room_query': {'observed_at': time.time(), 'rooms': [
                               {'id': '175046558', 'name': 'SGZWLB'}]}}
        app.room_action.reset_mock()
        app.retry_next()
        app.room_action.assert_called_once_with(
            {'op': 'join', 'room_id': '175046558', 'nickname': '風夜', 'quick': True})
        self.assertEqual(app.retry['steps'], [])
        FengyeWindow._maybe_retry(app, {'op': 'join', 'status': 'completed'})
        self.assertIsNone(app.retry)

    def test_one_click_retry_aborts_on_empty_or_multiple_rooms(self):
        from native_window import FengyeWindow
        app = mock.Mock()
        app.retry_next = lambda: FengyeWindow.retry_next(app)
        app.room_busy = app.room_pending = app.room_uncertain = False
        for rooms in ([], [{'id': '1', 'name': 'A'}, {'id': '2', 'name': 'B'}]):
            app.retry = {'steps': ['wait_rooms'], 'deadline': time.monotonic() + 60,
                         'start_retries': 0}
            app.rooms.state = {'alive': True, 'fresh': True, 'phase': 'lobby',
                               'room_query': {'observed_at': time.time(), 'rooms': rooms}}
            app.room_action.reset_mock()
            app.retry_next()
            app.room_action.assert_not_called()
            self.assertIsNone(app.retry)

    def test_one_click_enter_chains_login_search_join(self):
        # 0.2.21：一鍵上場＝登入(如需)→更新房間→進入（自動報到→藏身），完成後自動收束。
        from native_window import FengyeWindow
        app = mock.Mock()
        app.retry_next = lambda: FengyeWindow.retry_next(app)
        app._retry_label = lambda: FengyeWindow._retry_label(app)
        app.one_click_enter = lambda: FengyeWindow.one_click_enter(app)
        app.room_busy = app.room_pending = app.room_uncertain = False
        app.retry = None
        app.source.sources.source_file = None
        app.room_line.get.return_value = '多线3'
        app.room_nickname.get.return_value = '待秋至'
        app.rooms.state = {}
        app.room_action.reset_mock()
        app.one_click_enter()
        app.room_action.assert_called_once_with({'op': 'start', 'line': '多线3'})
        self.assertEqual(app.retry['label'], '一鍵上場')
        self.assertEqual(app.retry['steps'], ['wait_lobby', 'search', 'wait_rooms'])
        app.retry = None
        app.rooms.state = {'alive': True, 'fresh': True, 'phase': 'lobby'}
        app.room_action.reset_mock()
        app.one_click_enter()
        app.room_action.assert_called_once_with({'op': 'search'})
        self.assertEqual(app.retry['steps'], ['wait_rooms'])
        app.retry = None
        app.rooms.state = {'alive': True, 'fresh': True, 'phase': 'lobby',
                           'room_query': {'observed_at': time.time(),
                                          'rooms': [{'id': '175046558', 'name': 'SGZWLB[丁满]'}]}}
        app.room_action.reset_mock()
        app.one_click_enter()
        app.room_action.assert_called_once_with(
            {'op': 'join', 'room_id': '175046558', 'nickname': '待秋至', 'quick': True})
        self.assertEqual(app.retry['steps'], [])
        app.retry = None
        app.rooms.state = {'alive': True, 'fresh': True, 'connected': True}
        app.room_action.reset_mock()
        app.one_click_enter()
        app.room_action.assert_not_called()

    def test_force_table_and_buttons_keep_only_player_seats(self):
        # 0.2.19：電腦／空席（操控欄無值）在席位表隱去、按鈕停用；讀不到資料或姓名不明時，不顯示可點擊的數字目標。
        from native_window import FengyeWindow
        app = mock.Mock()
        app._seat_table.return_value = {0: ('丁满', '韩'), 1: ('风云', '吴'),
                                        2: ('電腦', '巴'), 3: ('電腦', '中山')}
        result = {'slot_forces': {'0': 2, '1': 8, '2': -1, '3': -1}, 'slot_now': 1, 'action': 'read'}
        text = FengyeWindow._format_force(app, '讀取風夜席位', result)
        self.assertIn('丁满・韩', text)
        self.assertNotIn('id ', text)
        self.assertIn('风云・吴', text)
        self.assertNotIn('電腦', text)
        self.assertNotIn('2→', text)
        empty = FengyeWindow._format_force(app, '讀取風夜席位', {'slot_forces': {'0': -1}, 'slot_now': 0})
        self.assertIn('還沒取得可切換的玩家名單', empty)
        buttons = {s: mock.Mock() for s in range(4)}
        app.local_slot_buttons = buttons
        app.fengye_slot_buttons = None
        FengyeWindow._update_slot_buttons(app, result)
        buttons[0].configure.assert_called_once_with(text='丁满・韩', state='normal')
        buttons[1].configure.assert_called_once_with(text='风云・吴', state='normal')
        buttons[2].configure.assert_called_once_with(text='等待玩家名單', state='disabled')
        buttons[3].configure.assert_called_once_with(text='等待玩家名單', state='disabled')
        for button in buttons.values():
            button.reset_mock()
        FengyeWindow._update_slot_buttons(app, {'rc': 1, 'stderr': 'no sanpk.exe'})
        for button in buttons.values():
            button.configure.assert_called_once_with(text='等待玩家名單', state='disabled')

    def test_longrun_health_and_window_survive_intel_and_whitelist(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('rs_longrun', ROOT / 'backend' / 'remote_snapshot.py')
        rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rs)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            identity = {'mode': 'p42_prestart_d8_passive', 'observe_seconds': 82800,
                        'hold_seconds': 86400, 'long_run': True, 'health_seconds': 300,
                        'tail_seconds': 60, 'collector_log': 'p42_live.jsonl'}
            (run / 'run_identity.json').write_text(json.dumps(identity), encoding='utf-8')
            logs = [
                {'ev': 'passive_listen_started', 'wall': 1000.0, 'observe_seconds': 82800},
                {'ev': 'health_sample', 'wall': 1300.0, 'connected': 1, 'packets': 42,
                 'release_calls': 42, 'receiver_errors': 0, 'tx_seq': 5, 'native_state': 2,
                 'd8_seconds': 300.0, 'last_activity_age': 12.5, 'observe_remaining': 82500,
                 'log_bytes': 123456},
                {'ev': 'd8_prestart_send_return', 'wall': 900.0, 'raw_rc': 1, 'target': 7,
                 'native_state_after': 1},
            ]
            intel = rs.p34_intel(run, identity, logs, 'running', 'p42-prestart-d8-20261016')
            lr = intel['longrun']
            self.assertTrue(lr['long_run'])
            self.assertEqual(lr['listen_started_wall'], 1000.0)
            self.assertEqual(lr['health']['packets'], 42)
            self.assertEqual(lr['health']['observe_remaining'], 82500)
            self.assertEqual(intel['window']['end_wall'], 900.0 + 82800)
            view = backend.p34_view({'p34': intel})
            self.assertTrue(view['longrun']['long_run'])
            self.assertEqual(view['longrun']['health']['packets'], 42)
            self.assertEqual(view['longrun']['health_seconds'], 300)
            self.assertIsNone(view['longrun']['end_reason'])
            self.assertFalse(view['longrun']['tail_recorded'])

    def test_longrun_end_reason_read_from_summary(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('rs_longrun2', ROOT / 'backend' / 'remote_snapshot.py')
        rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rs)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / 'summary.json').write_text(json.dumps(
                {'end_reason': 'control_stop', 'post_exit_tail_written': True}), encoding='utf-8')
            intel = rs.p34_intel(run, {}, [], None, None)
            self.assertEqual(intel['longrun']['end_reason'], 'control_stop')
            self.assertTrue(intel['longrun']['tail_recorded'])
            view = backend.p34_view({'p34': intel})
            self.assertEqual(view['longrun']['end_reason'], 'control_stop')
            self.assertTrue(view['longrun']['tail_recorded'])

    def test_fengye_labels_move_and_phase_end_with_names_without_inventing(self):
        # 0.2.14：移動/階段結束以類別名標註、發送者帶名字與勢力；原文與欄位不動。
        move = b'CSanInetUnitNetCmdMove'
        body = struct.pack('<III', 17, 0, 0) + b'\x00'
        body += struct.pack('<HII', 1, 67, 53) + struct.pack('<H', 3) + struct.pack('<I', 0)
        body += struct.pack('<HHH', 0xffff, 0xffff, 0)
        raw = struct.pack('<3H', 0xffff, 1, len(move)) + move + body
        record = {'raw': raw.hex(), 'len': len(raw), 'sha8': hashlib.sha256(raw).hexdigest()[:12], 'sender': 222}
        phase = b'CSanInetPhaseEndCmd'
        praw = struct.pack('<3H', 0xffff, 1, len(phase)) + phase + struct.pack('<III', 21, 1, 5000) + b'\x00'
        precord = {'raw': praw.hex(), 'len': len(praw), 'sha8': hashlib.sha256(praw).hexdigest()[:12], 'sender': 333}
        view = {'p34': {'run_name': 't', 'member_names': {'222': '風雲'},
                        'snapshots': {'start': {'rows': [{'id': 222, 'name': '風雲', 'faction': '晋'}]}},
                        'sync': {'nonempty': [{'wall': 1, 'round': 4, 'records': [record, precord]}]}}}
        rows = decoded_commands(view)
        self.assertEqual(rows[0]['who_display'], '風雲（晋）')
        self.assertEqual(rows[0].get('class_cn'), '部隊移動')
        self.assertEqual(rows[0].get('move_xy'), [67, 53])
        self.assertEqual(rows[0].get('value_display'), '(67, 53)')
        self.assertIn('候選', rows[0].get('status_text', ''))
        self.assertEqual(rows[1].get('class_cn'), '階段結束')
        self.assertEqual(rows[1]['sender'], 333)


if __name__ == '__main__':
    unittest.main()
