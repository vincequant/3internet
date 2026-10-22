import os
import unittest
from unittest.mock import patch

from room_instance import choose_instances, identity_alive, matches_target, parse_target_argv
from room_list_probe import probe_flags


def win(hwnd=11, pid=100, title='游戏选择', klass='#32770', prefix='', command='', exe_win=r'C:\sgi\run-3.5\3I\SANPK.exe'):
    return {
        'hwnd': hwnd, 'pid': pid, 'title': title, 'class': klass,
        'exe_win': exe_win, 'exe_unix': command, 'command': command, 'prefix': prefix,
    }


class InstanceTests(unittest.TestCase):
    def test_default_keeps_all(self):
        rows = [win(), win(hwnd=22, pid=200, command='/tmp/prefix-monitor/drive_c/SANPK.exe')]
        self.assertEqual(len(choose_instances(rows, None)), 2)

    def test_prefix_selects_monitor_only(self):
        main = win(command='/Users/vk/Library/Application Support/SGI-Wine/prefix/drive_c/sgi/run-3.5/3I/SANPK.exe',
                   prefix='/Users/vk/Library/Application Support/SGI-Wine/prefix')
        alt = win(hwnd=22, pid=200,
                  command='/Users/vk/Library/Application Support/SGI-Wine/prefix-monitor/drive_c/sgi/run-3.5/3I/SANPK.exe',
                  prefix='/Users/vk/Library/Application Support/SGI-Wine/prefix-monitor')
        chosen = choose_instances([main, alt], {'prefix': '/Users/vk/Library/Application Support/SGI-Wine/prefix-monitor'})
        self.assertEqual([item['pid'] for item in chosen], [200])

    def test_pid_alone_not_enough_after_reuse(self):
        saved = win(pid=100, hwnd=11, prefix='/tmp/prefix-monitor')
        reused = win(pid=100, hwnd=11, prefix='/tmp/other', command='/tmp/other/SANPK.exe')
        self.assertFalse(identity_alive(saved, reused))
        same = win(pid=300, hwnd=99, prefix='/tmp/prefix-monitor', command='/tmp/prefix-monitor/SANPK.exe')
        saved['exe'] = '/tmp/prefix-monitor/SANPK.exe'
        saved['prefix'] = '/tmp/prefix-monitor'
        self.assertTrue(identity_alive(saved, same))

    def test_unix_prefix_matches_wine_pe_path_via_wineprefix(self):
        cand = win()
        target = {'prefix': '/tmp/prefix-monitor'}
        with patch.dict(os.environ, {'WINEPREFIX': '/tmp/prefix-monitor'}, clear=False):
            self.assertTrue(matches_target(cand, target))
        with patch.dict(os.environ, {'WINEPREFIX': '/tmp/other'}, clear=False):
            self.assertFalse(matches_target(cand, target))

    def test_hwnd_mismatch_rejected_when_targeted(self):
        self.assertFalse(matches_target(win(hwnd=11), {'hwnd': 22}))

    def test_parse_and_flags_keep_refresh_last(self):
        target = parse_target_argv(['--prefix', '/tmp/prefix-monitor', '--refresh', '--quiet'])
        self.assertEqual(target['prefix'], '/tmp/prefix-monitor')
        flags = probe_flags(refresh=True, quiet=True, prefix='/tmp/prefix-monitor')
        self.assertEqual(flags[-1], '--refresh')
        self.assertEqual(flags[:2], ['--prefix', '/tmp/prefix-monitor'])


if __name__ == '__main__':
    unittest.main()
