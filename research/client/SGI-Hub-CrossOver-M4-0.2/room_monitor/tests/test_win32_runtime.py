import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.win32_runtime import apply_win81, ensure_win81_user_reg, win81_already_set


SAMPLE = """WINE REGISTRY Version 2
;; All keys relative to REGISTRY\\\\User\\\\S-1-5-21-0-0-0-1000

[Software\\\\Wine\\\\AppDefaults\\\\sgi-py32.exe] 1
#time=0
"Version"="win81"

[Software\\\\Wine\\\\Debug] 1
#time=0
"""


class Win81UserRegTests(unittest.TestCase):
    def test_already_set_skips_wine_subprocess(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            (prefix / 'user.reg').write_text(SAMPLE, encoding='utf-8')
            self.assertTrue(win81_already_set(prefix, 'sgi-py32.exe'))
            with patch('sgi_room_monitor.win32_runtime.subprocess.run') as run:
                result = apply_win81({'wine': '/no/wine', 'hub_root': folder}, prefix, 'sgi-py32.exe')
            run.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result['compat'], 'wine-appdefaults-win81-existing')

    def test_writes_missing_key_without_wine(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            (prefix / 'user.reg').write_text('WINE REGISTRY Version 2\n\n', encoding='utf-8')
            self.assertFalse(win81_already_set(prefix, 'sgi-py32.exe'))
            with patch('sgi_room_monitor.win32_runtime.subprocess.run') as run:
                result = apply_win81({'wine': '/no/wine', 'hub_root': folder}, prefix, prefix / 'sgi-py32.exe')
            run.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertTrue(win81_already_set(prefix, 'sgi-py32.exe'))
            self.assertIn('"Version"="win81"', (prefix / 'user.reg').read_text(encoding='utf-8'))

    def test_timeout_returns_false_not_raise(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            wine = prefix / 'wine'
            wine.write_text('x', encoding='utf-8')
            hub = prefix / 'hub'
            (hub / 'bridge' / 'python').mkdir(parents=True)
            (hub / 'bridge' / 'python' / 'python.exe').write_text('x', encoding='utf-8')
            with patch('sgi_room_monitor.win32_runtime.subprocess.run',
                       side_effect=subprocess.TimeoutExpired(cmd=['wine'], timeout=8)):
                result = apply_win81({'wine': str(wine), 'hub_root': str(hub)}, prefix, 'sgi-py32.exe')
            self.assertFalse(result['ok'])
            self.assertEqual(result['reason'], 'win81_registry')

    def test_ensure_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            (prefix / 'user.reg').write_text(SAMPLE, encoding='utf-8')
            self.assertTrue(ensure_win81_user_reg(prefix, 'sgi-py32.exe'))
            self.assertEqual((prefix / 'user.reg').read_text(encoding='utf-8').count('"Version"="win81"'), 1)

    def test_writes_sanpk_appdefaults(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            (prefix / 'user.reg').write_text('WINE REGISTRY Version 2\n\n', encoding='utf-8')
            with patch('sgi_room_monitor.win32_runtime.subprocess.run') as run:
                result = apply_win81({'wine': '/no/wine', 'hub_root': folder}, prefix, 'SANPK.exe')
            run.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertTrue(win81_already_set(prefix, 'SANPK.exe'))
            self.assertIn('AppDefaults\\\\SANPK.exe', (prefix / 'user.reg').read_text(encoding='utf-8'))

    def test_live_timeout_fail_open_after_user_reg(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            (prefix / 'user.reg').write_text('WINE REGISTRY Version 2\n\n', encoding='utf-8')
            wine = prefix / 'wine'
            wine.write_text('x', encoding='utf-8')
            hub = prefix / 'hub'
            (hub / 'bridge' / 'python').mkdir(parents=True)
            (hub / 'bridge' / 'python' / 'python.exe').write_text('x', encoding='utf-8')
            with patch('sgi_room_monitor.win32_runtime.subprocess.run',
                       side_effect=subprocess.TimeoutExpired(cmd=['wine'], timeout=8)):
                result = apply_win81(
                    {'wine': str(wine), 'hub_root': str(hub)}, prefix, 'SANPK.exe', live=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('live'), False)
            self.assertTrue(win81_already_set(prefix, 'SANPK.exe'))


if __name__ == '__main__':
    unittest.main()
