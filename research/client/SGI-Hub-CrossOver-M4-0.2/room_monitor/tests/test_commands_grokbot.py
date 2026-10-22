import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.commands import apply_command, parse_command
from sgi_room_monitor.grokbot import owner_telegram_id, send_text
from sgi_room_monitor.lobby import prefixes_conflict


class CommandTests(unittest.TestCase):
    def test_parse_natural_language(self):
        self.assertEqual(parse_command('开始监控')['action'], 'start')
        self.assertEqual(parse_command('现在几个人')['action'], 'list')
        self.assertEqual(parse_command('只看等待中的房间')['action'], 'waiting')
        self.assertEqual(parse_command('设置人数提醒 6')['value'], 6)
        self.assertEqual(parse_command('调整刷新间隔 20')['value'], 20)
        self.assertEqual(parse_command('暂停监控')['action'], 'pause')
        self.assertEqual(parse_command('恢复监控')['action'], 'resume')
        self.assertEqual(parse_command('停止监控')['action'], 'stop')
        self.assertEqual(parse_command('查看监控健康状态')['action'], 'health')

    def test_apply_threshold_and_interval(self):
        settings = apply_command({'action': 'threshold', 'value': 5}, {})
        self.assertEqual(settings['alert_threshold'], 5)
        settings = apply_command({'action': 'interval', 'value': 30}, settings)
        self.assertEqual(settings['refresh_interval_sec'], 30)
        with self.assertRaises(ValueError):
            apply_command({'action': 'threshold', 'value': 99}, {})


class GrokbotTests(unittest.TestCase):
    def test_owner_only_and_group_forbidden(self):
        channels = {'telegram': {'enabled': True, 'allowFrom': ['1001']}}
        self.assertEqual(owner_telegram_id(channels, 'owner'), '1001')
        with self.assertRaises(RuntimeError):
            owner_telegram_id(channels, '999')
        with self.assertRaises(RuntimeError):
            send_text('hi', {'grokbot': {'allow_groups': True, 'backend': 'openclaw-telegram'}})

    def test_send_failure_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            channels = {'telegram': {'enabled': True, 'allowFrom': ['1']}}
            with patch('sgi_room_monitor.grokbot.load_openclaw_channels', return_value=channels):
                with self.assertRaises(RuntimeError):
                    send_text('hi', {'data_dir': folder, 'grokbot': {'to': '1'}},
                              runner=lambda target, text: (_ for _ in ()).throw(RuntimeError('boom')))
            log = (Path(folder) / 'send-log.jsonl').read_text(encoding='utf-8')
            self.assertIn('boom', log)
            self.assertIn('"ok": false', log)


class LobbyGuardTests(unittest.TestCase):
    def test_refuse_same_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'system.reg').write_text('x', encoding='utf-8')
            message = prefixes_conflict({'monitor_prefix': str(path), 'main_prefix': str(path)})
            self.assertIn('主号', message)


if __name__ == '__main__':
    unittest.main()
