import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.collector import normalize_reader
from sgi_room_monitor.evidence import attach_connection, connection_evidence, lifecycle_state
from sgi_room_monitor.identity import occupancy
from sgi_room_monitor.lobby import click_start_game, ensure_platform
from sgi_room_monitor.platform import running_in_prefix
from sgi_room_monitor.states import GAME_STARTING, LIST_WINDOW_READY, LIVE, READ_FAIL, ROOM_CONNECTED


def _verified():
    return {'target_connected': True, 'list_window_ready': True, 'observed_line': '多线2（主线）',
            'observed_room': '三国对战房', 'source': 'lobby_tree_and_game_select'}


class EvidenceTests(unittest.TestCase):
    def test_sanpk_process_is_not_list_ready(self):
        info = {'sanpk_running': True, 'game_select': False, 'logged_in': True, 'trees': []}
        state, ev = lifecycle_state(info, {'platform_line': '多线2（主线）'})
        self.assertEqual(state, GAME_STARTING)
        self.assertFalse(ev['list_window_ready'])

    def test_blank_select_without_line_is_not_connected(self):
        info = {'game_select': True, 'sanpk_running': True, 'trees': [], 'titles': ['游戏选择']}
        state, ev = lifecycle_state(info, {'platform_line': '多线2（主线）'})
        self.assertEqual(state, GAME_STARTING)
        self.assertFalse(ev['target_connected'])

    def test_tree_selection_is_connection_evidence(self):
        info = {
            'logged_in': True,
            'trees': [{'items': [
                {'text': '三国对战房', 'selected': True},
                {'text': '多线2（主线）', 'selected': True},
            ]}],
        }
        ev = connection_evidence(info, {'platform_line': '多线2（主线）', 'platform_room': '三国对战房'})
        self.assertTrue(ev['target_connected'])
        self.assertEqual(ev['observed_line'], '多线2（主线）')
        self.assertEqual(lifecycle_state(info, {'platform_line': '多线2（主线）'})[0], ROOM_CONNECTED)

    def test_unverified_empty_is_read_fail(self):
        config = {'instance_id': 'm1', 'platform_line': '多线2（主线）', 'platform_room': '三国对战房'}
        payload = {'status': 'fresh', 'rooms': [], 'ui_listbox': 'empty_agree', 'observed_at': 1}
        snap = normalize_reader(payload, config, 1, True)
        self.assertEqual(snap['data_status'], READ_FAIL)
        self.assertIn('不能当有效空列表', snap['message'])

    def test_verified_empty_stays_live(self):
        config = {'instance_id': 'm1', 'platform_line': '多线2（主线）', 'platform_room': '三国对战房'}
        payload = {'status': 'fresh', 'rooms': [], 'ui_listbox': 'empty_agree', 'observed_at': 1,
                   'connection': _verified()}
        snap = normalize_reader(payload, config, 1, True)
        self.assertEqual(snap['data_status'], LIVE)
        self.assertEqual(snap['observed_line'], '多线2（主线）')
        self.assertTrue(snap['connection_verified'])

    def test_config_line_is_not_copied_as_observed(self):
        snap = attach_connection({'data_status': READ_FAIL, 'rooms': [], 'message': 'x'}, {}, {
            'platform_line': '多线2（主线）', 'platform_room': '三国对战房',
        })
        self.assertEqual(snap['platform_line_source'], 'config_unverified')
        self.assertIsNone(snap['observed_line'])

    def test_unknown_occupancy_is_not_zero(self):
        self.assertEqual(occupancy({'name': '甲[张]'}), (None, None))
        self.assertEqual(occupancy({'current': 3, 'maximum': 8}), (3, 8))

    def test_ensure_platform_does_not_trust_sanpk_name(self):
        with patch('sgi_room_monitor.lobby.prefixes_conflict', return_value=None):
            with patch('sgi_room_monitor.lobby.running_in_prefix', return_value=True):
                with patch('sgi_room_monitor.lobby.inspect_lobby', return_value={
                    'sanpk_running': True, 'game_select': False, 'logged_in': True, 'trees': [], 'titles': [],
                }):
                    result = ensure_platform({
                        'monitor_prefix': '/tmp/prefix-monitor',
                        'main_prefix': '/tmp/prefix-main',
                        'platform_line': '多线2（主线）',
                    })
        self.assertNotEqual(result['state'], LIST_WINDOW_READY)
        self.assertEqual(result['state'], GAME_STARTING)

    def test_click_start_does_not_ready_on_sanpk_alone(self):
        with patch('sgi_room_monitor.lobby.prefixes_conflict', return_value=None):
            with patch('sgi_room_monitor.lobby.running_in_prefix', return_value=True):
                with patch('sgi_room_monitor.lobby.inspect_lobby', return_value={
                    'sanpk_running': True, 'game_select': False, 'trees': [], 'titles': [],
                }):
                    result = click_start_game({
                        'monitor_prefix': '/tmp/prefix-monitor',
                        'main_prefix': '/tmp/prefix-main',
                        'platform_line': '多线2（主线）',
                    })
        self.assertFalse(result['ok'])
        self.assertEqual(result['state'], GAME_STARTING)

    def test_windows_prefix_not_global_tasklist(self):
        rows = [{'ProcessId': 1, 'ExecutablePath': r'C:\other\SANPK.exe', 'CommandLine': 'SANPK.exe'}]
        with patch('sgi_room_monitor.platform.sys.platform', 'win32'):
            with patch('sgi_room_monitor.platform.windows_processes', return_value=rows):
                self.assertFalse(running_in_prefix(r'C:\sgi\monitor', 'SANPK.exe'))
            with patch('sgi_room_monitor.platform.windows_processes', return_value=[
                {'ProcessId': 2, 'ExecutablePath': r'C:\sgi\monitor\SANPK.exe', 'CommandLine': 'SANPK.exe'},
            ]):
                self.assertTrue(running_in_prefix(r'C:\sgi\monitor', 'SANPK.exe'))


if __name__ == '__main__':
    unittest.main()
