import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.credentials import missing_credentials, status
from sgi_room_monitor.lobby import prefixes_conflict
from sgi_room_monitor.provision import EXCLUDE, EXCLUDE_DIRS, FONT_REPLACEMENTS, TEMPLATE, write_userconfig
from sgi_room_monitor.states import PENDING_CONFIG


class ProvisionCredsTests(unittest.TestCase):
    def test_userconfig_template_empty_password_and_alt_port(self):
        self.assertIn('LoaderUdpPort={port}', TEMPLATE)
        self.assertIn('Password=\n', TEMPLATE)
        self.assertIn('RemberPwd=False', TEMPLATE)
        self.assertIn('UserConfig.ini', EXCLUDE)
        self.assertIn('Save', EXCLUDE_DIRS)
        with tempfile.TemporaryDirectory() as folder:
            path = write_userconfig(Path(folder), 4578)
            text = path.read_bytes().decode('gb18030')
            self.assertIn('LoaderUdpPort=4578', text)
            self.assertNotIn('Password=abc', text)

    def test_missing_creds_is_pending_not_monitoring(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = {'data_dir': folder, 'account_username': ''}
            (Path(folder) / 'credentials.json').write_text('{"username":"","password":""}\n', encoding='utf-8')
            info = status(cfg)
            self.assertFalse(info['ready'])
            self.assertTrue(missing_credentials(cfg))
            self.assertIn('creds-set', info['entry'])
            self.assertNotEqual(PENDING_CONFIG, 'monitoring')

    def test_keychain_ready_without_file_password(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = {'data_dir': folder, 'account_username': 'alt'}
            with patch('sgi_room_monitor.credentials._keychain_has', return_value=True):
                info = status(cfg)
            self.assertTrue(info['ready'])
            self.assertTrue(info['keychain'])

    def test_same_prefix_is_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            same = Path(folder)
            self.assertIn('相同', prefixes_conflict({
                'monitor_prefix': str(same),
                'main_prefix': str(same),
            }))
            self.assertIn('不存在', prefixes_conflict({
                'monitor_prefix': str(same / 'missing'),
                'main_prefix': str(same),
            }))

    def test_cjk_replacements_cover_simsun_and_shell_dlg(self):
        self.assertEqual(FONT_REPLACEMENTS['SimSun'], 'Arial Unicode MS')
        self.assertEqual(FONT_REPLACEMENTS['MS Shell Dlg'], 'Arial Unicode MS')
        self.assertEqual(FONT_REPLACEMENTS['宋体'], 'Arial Unicode MS')

    def test_running_in_prefix_uses_cwd_not_just_command(self):
        if sys.platform == 'win32':
            self.skipTest('Windows uses ExecutablePath, covered by test_windows_prefix_not_global_tasklist')
        from sgi_room_monitor import lobby
        with patch('sgi_room_monitor.provision.prefix_owned_pids', return_value=[
            {'pid': 1, 'command': './3I\\SANPK.exe /1an'},
        ]):
            self.assertTrue(lobby.running_in_prefix('/tmp/prefix', 'SANPK.exe'))
        with patch('sgi_room_monitor.provision.prefix_owned_pids', return_value=[]):
            self.assertFalse(lobby.running_in_prefix('/tmp/prefix', 'SANPK.exe'))


if __name__ == '__main__':
    unittest.main()
