import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.collector import normalize_reader
from sgi_room_monitor.states import CACHE, LIVE, READ_FAIL
from sgi_room_monitor.store import empty_snapshot


class CollectorNormalizeTests(unittest.TestCase):
    def test_mismatch_is_cache_not_zero(self):
        config = {'instance_id': 'm1', 'platform_line': '多线2（主线）', 'platform_room': '三国对战房'}
        payload = {'status': 'fresh', 'rooms': [{'id': '1', 'name': '甲[张]', 'current': 5, 'maximum': 8}],
                   'ui_listbox': 'mismatch', 'observed_at': 1}
        snap = normalize_reader(payload, config, 1, True)
        self.assertEqual(snap['data_status'], CACHE)
        self.assertEqual(snap['rooms'][0]['current'], 5)

    def test_empty_agree_is_live_empty(self):
        config = {'instance_id': 'm1', 'platform_line': '多线2（主线）', 'platform_room': '三国对战房'}
        payload = {'status': 'fresh', 'rooms': [], 'ui_listbox': 'empty_agree', 'observed_at': 1,
                   'connection': {'target_connected': True, 'list_window_ready': True,
                                  'observed_line': '多线2（主线）', 'source': 'lobby_tree_and_game_select'}}
        snap = normalize_reader(payload, config, 1, True)
        self.assertEqual(snap['data_status'], LIVE)
        self.assertEqual(snap['rooms'], [])
        self.assertIn('空列表', snap['message'])

    def test_unverified_empty_not_zero(self):
        config = {'instance_id': 'm1', 'platform_line': '多线2（主线）', 'platform_room': '三国对战房'}
        payload = {'status': 'fresh', 'rooms': [], 'ui_listbox': 'unknown', 'observed_at': 1}
        snap = normalize_reader(payload, config, 1, True)
        self.assertEqual(snap['data_status'], READ_FAIL)
        self.assertIn('不能当有效空列表', snap['message'])


class ServiceCommandTests(unittest.TestCase):
    def test_queue_commands(self):
        from sgi_room_monitor.service import MonitorService
        with tempfile.TemporaryDirectory() as folder:
            with patch('sgi_room_monitor.service.load_config', return_value={
                'data_dir': folder, 'alert_threshold': 4, 'refresh_interval_sec': 15,
                'instance_id': 'm1', 'platform_line': '多线2（主线）', 'grokbot': {},
            }):
                service = MonitorService(folder, notify=False)
                self.assertTrue(service.request('暂停监控')['ok'])
                self.assertEqual(service.commands.get_nowait()['action'], 'pause')
                self.assertFalse(service.request('???')['ok'])


if __name__ == '__main__':
    unittest.main()
