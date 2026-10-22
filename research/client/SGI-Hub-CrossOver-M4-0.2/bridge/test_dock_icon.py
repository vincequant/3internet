import subprocess
import sys
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB / 'app'))
sys.path.insert(0, str(HUB))

from dock_icon import apply, icon_path
from publish import allowed


class DockIcons(unittest.TestCase):
    def test_packaged_pngs_exist(self):
        for name in ('hub', 'wine', 'map'):
            path = icon_path(name)
            self.assertIsNotNone(path, name)
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.read_bytes().startswith(b'\x89PNG'), path)
            self.assertGreater(path.stat().st_size, 1000)

    def test_apply_does_not_raise(self):
        apply(None, 'hub')
        apply(None, 'wine')
        apply(None, 'map')
        apply(None, 'missing')

    def test_apply_after_tk_in_child(self):
        # Keep Tk() out of this process: a vanilla NSApp created earlier
        # makes Homebrew Tk 9 abort. Child starts with Tk() then apply().
        code = (
            'import sys,tkinter as tk\n'
            f'sys.path.insert(0,{str(HUB / "app")!r})\n'
            'from dock_icon import apply\n'
            'root=tk.Tk();root.withdraw();apply(root,"hub");root.destroy()\n'
        )
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=30)
        if result.returncode != 0:
            err = (result.stderr or b'').decode('utf8', 'replace')
            if any(mark in err for mark in ('TclError', 'macOSVersion', 'or later required', 'no display')):
                return
            self.fail(err or f'child exited {result.returncode}')

    def test_publish_allows_icon_paths(self):
        self.assertTrue(allowed('app/dock_icon.py'))
        for name in ('hub', 'wine', 'map'):
            self.assertTrue(allowed(f'app/assets/icons/{name}.png'))
        self.assertTrue(allowed('bridge/win32-python/sgi-py32.exe'))
        self.assertTrue(allowed('bridge/win32-python/WIN32-PYTHON.json'))
        self.assertFalse(allowed('bridge/python/python.exe'))

    def test_uses_ctypes_not_appkit(self):
        text = (HUB / 'app' / 'dock_icon.py').read_text(encoding='utf8')
        self.assertIn('ctypes', text)
        self.assertIn('setApplicationIconImage', text)
        self.assertNotIn('import AppKit', text)
        self.assertNotIn('from AppKit', text)
        self.assertNotIn('PyObjC', text)

    def test_tk_entry_points_call_apply(self):
        app = HUB / 'app'
        self.assertIn("apply_dock_icon(root,'hub')", (app / 'mac_main.py').read_text(encoding='utf8'))
        self.assertIn("apply_dock_icon(root,'hub')", (app / 'omni_window.py').read_text(encoding='utf8'))
        self.assertIn("apply_dock_icon(root, 'wine')", (app / 'wine_nav.py').read_text(encoding='utf8'))
        self.assertIn("apply_dock_icon(root, 'map')", (app / 'panorama_map.py').read_text(encoding='utf8'))
        self.assertIn("apply_dock_icon(root,'wine')", (app / 'room_watch.py').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
