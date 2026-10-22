"""Source-level checks for the protocol StartServer helper mutex hold."""
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / 'sgi_room_monitor/win32_startserver.py'


class Win32StartServerMutexTests(unittest.TestCase):
    def test_nethook_mutex_created_before_popen(self):
        src = HELPER.read_text(encoding='utf-8')
        self.assertIn('def _hold_nethook_mutex', src)
        self.assertIn('CreateMutexA', src)
        self.assertIn("b'NetHookClientRunningFlag'", src)
        self.assertIn('_HELD_HANDLES.append(handle)', src)
        self.assertLess(src.index('_hold_nethook_mutex()'), src.index('subprocess.Popen'))
        self.assertLess(src.index("'mutex_ready'"), src.index("'sanpk_launched'"))
        self.assertIn("'kind': 'nethook_client'", src)
        self.assertNotIn("'token': 'nethook_client'", src)
        self.assertNotIn('print(token', src)
        self.assertNotIn('KOEI Internet Games Mutex', src)
        self.assertIn('GameTool.dll', src)
        self.assertIn('d9e6167baec2628e6af5a0532929698921eaf1a0d28054ff00b1774408fb9640', src)

    def test_eight_param_startserver_still_present(self):
        src = HELPER.read_text(encoding='utf-8')
        self.assertIn('StartServer.argtypes', src)
        self.assertIn('c_char_p, c.c_char_p, c.c_int, c.c_char_p', src)
        self.assertIn("cfg['token'] = None", src)
        self.assertIn('/1an', src)
        self.assertIn('def _loader_udp_port', src)
        self.assertIn('LoaderUdpPort=', src)
        self.assertIn('InitDll(callback, udp_port)', src)
        self.assertNotIn('InitDll(callback, 4578)', src)
        self.assertIn('def _prep_game_search', src)
        self.assertIn('搜寻服务器', src)
        self.assertIn('刷新列表', src)
        self.assertIn('按【确认】搜寻服务器', src)
        self.assertIn('_prep_game_search(user32, pump)', src)
        self.assertIn('_GAME_SELECT_TIMEOUT = 60', src)
        self.assertIn('timeout=_GAME_SELECT_TIMEOUT', src)
        self.assertNotIn('game.returncode', src)
        self.assertIn('exited = game.poll()', src)
        self.assertNotIn('filled_broadcast', src)
        self.assertNotIn('0x000C', src)
        self.assertNotIn('_SEARCH_BROADCAST', src)
        self.assertIn("os.chdir(str(root))", src)
        self.assertIn("SetDllDirectoryW", src)
        self.assertIn("cwd=str(root / '3I')", src)
        self.assertIn('def _launch_sanpk_with_core', src)
        self.assertNotIn("WinDLL(str(root / 'NetHookCore.dll'))", src)
        self.assertIn('LoadLibraryW', src)
        self.assertIn('_CREATE_SUSPENDED', src)
        self.assertIn('core_inject', src)
        self.assertIn('join_name', src)
        self.assertIn('list_names', src)
        self.assertIn("'加入' in cap", src)
        self.assertIn("'创建' not in cap", src)
        self.assertIn('kwankwan', src)
        self.assertIn('WaitForSingleObject(thread, 800)', src)
        self.assertNotIn('WaitForSingleObject(thread, 4000)', src)
        self.assertNotIn('time.sleep(2)', src)
        self.assertIn('time.monotonic() + 3', src)


class LoaderUdpPortTests(unittest.TestCase):
    def test_reads_userconfig_port(self):
        import sys
        import tempfile
        sys.path.insert(0, str(HELPER.parent))
        from win32_startserver import _loader_udp_port
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as folder:
            root = P(folder)
            (root / 'UserConfig.ini').write_bytes(
                '[Misc]\r\nLoaderUdpPort=4577\r\n'.encode('gbk'))
            self.assertEqual(_loader_udp_port(root), 4577)
            self.assertEqual(_loader_udp_port(P(folder) / 'missing'), 4576)
            self.assertEqual(_loader_udp_port(root, {'udp_port': 4580}), 4580)


if __name__ == '__main__':
    unittest.main()
