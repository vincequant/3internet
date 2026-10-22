"""The quick-command panel lives inside the 指令 page, not in its own window.

These tests never touch the game: the panel is built in smoke mode (no helper
process, no command) and the environment switch keeps autoconnect off.
"""
import os
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]

from tkinter import ttk
import quick_command_embed as embed


class PanelLocationTests(unittest.TestCase):
    def test_panel_script_is_the_sgi_hub_panel(self):
        script = embed.panel_script()
        self.assertEqual(script.name, 'quick_control.py')
        self.assertTrue(script.is_file(), script)
        self.assertEqual(script.parent.parent.name, 'SGI-Hub-CrossOver-M4-0.2')

    def test_environment_can_point_at_another_copy(self):
        with mock.patch.dict(os.environ, {'SGI_QUICK_PANEL_APP': '/tmp/somewhere/app'}):
            self.assertEqual(embed.panel_app_dir(), Path('/tmp/somewhere/app'))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SGI_QUICK_PANEL_APP', None)
            self.assertEqual(embed.panel_app_dir(), embed.DEFAULT_PANEL_APP)

    def test_autoconnect_defaults_on_and_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {'SGI_QUICK_EMBED_AUTOCONNECT': '0'}):
            self.assertFalse(embed.autoconnect_enabled())
        with mock.patch.dict(os.environ, {'SGI_QUICK_EMBED_AUTOCONNECT': '1'}):
            self.assertTrue(embed.autoconnect_enabled())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SGI_QUICK_EMBED_AUTOCONNECT', None)
            self.assertTrue(embed.autoconnect_enabled())

    def test_module_is_loaded_once_and_supports_embedding(self):
        first = embed.load_panel_module()
        second = embed.load_panel_module()
        self.assertIs(first, second)
        self.assertTrue(str(first.__file__).endswith('SGI-Hub-CrossOver-M4-0.2/app/quick_control.py'))
        names = first.Panel.__init__.__code__.co_varnames
        self.assertIn('embedded', names)
        self.assertIn('autoconnect', names)
        self.assertIn('smoke', names)

    def test_panel_import_does_not_shadow_hub_modules(self):
        embed.load_panel_module()
        app = embed.panel_app_dir()
        bridge = str(app.parent / 'bridge')
        self.assertIn(bridge, sys.path)
        self.assertLess(sys.path.index(str(ROOT / 'bridge')), sys.path.index(bridge))
        self.assertLess(sys.path.index(str(ROOT / 'app')), sys.path.index(str(app)))

    def test_missing_panel_file_reports_the_path(self):
        with self.assertRaises(FileNotFoundError) as caught:
            embed.load_panel_module('/tmp/definitely-not-here/app')
        self.assertIn('quick_control.py', str(caught.exception))


class ScrollHostTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk display unavailable: %s' % exc)
        self.addCleanup(self.root.destroy)
        self.root.geometry('520x240+3200+2000')

    def test_scrollbar_only_when_content_is_taller(self):
        host = embed.QuickPanelHost(self.root, bg='#f3f6fa')
        host.pack(fill='both', expand=True)
        tall = tk.Frame(host.inner, height=1800, bg='#f3f6fa')
        tall.pack(fill='x')
        self.root.update()
        host._content_changed()
        self.root.update()
        self.assertTrue(host._scroll_shown)
        self.assertTrue(host.scroll.winfo_ismapped())
        tall.configure(height=10)
        self.root.update()
        host._content_changed()
        self.root.update()
        self.assertFalse(host._scroll_shown)
        self.assertFalse(host.scroll.winfo_ismapped())


class EmbeddedPanelTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk display unavailable: %s' % exc)
        self.addCleanup(self.root.destroy)
        self.root.geometry('900x700+3200+2000')
        ttk.Style(self.root).theme_use('clam')
        self.book = ttk.Notebook(self.root)
        self.book.pack(fill='both', expand=True)
        self.page = tk.Frame(self.book, bg='#f3f6fa')
        self.other = tk.Frame(self.book, bg='#f3f6fa')
        self.book.add(self.page, text='指令')
        self.book.add(self.other, text='進房與準備')
        self.book.select(self.page)
        self.root.update()
        self.panel = self.mount(smoke=True)

    def mount(self, smoke=True, autoconnect=False):
        return embed.mount_quick_panel(self.page, bg='#f3f6fa', autoconnect=autoconnect,
                                       smoke=smoke)

    def tearDown(self):
        try:
            self.panel.close()
        except tk.TclError:
            pass

    def test_panel_is_a_child_widget_not_a_window(self):
        before = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.root.update()
        after = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(before, after)
        self.assertEqual(self.panel.host.winfo_toplevel(), self.root)
        self.assertTrue(self.panel.embedded)

    def test_ttk_styles_are_namespaced_so_the_hub_theme_is_untouched(self):
        self.assertEqual(self.panel.st('TButton'), 'Quick.TButton')
        self.assertEqual(self.panel.st('Muted.TLabel'), 'Quick.Muted.TLabel')
        style = ttk.Style(self.root)
        # 內嵌用 Hub 的淺藍白，不是獨立視窗那片米黃。
        self.assertEqual(style.configure('Quick.TLabel').get('background'), '#f3f6fa')
        self.assertNotEqual(style.configure('Quick.TLabel').get('background'), '#ede3c5')
        self.assertNotEqual(style.configure('Quick.TButton').get('background'), '#e0d1a6')
        # 共用的 TLabel 不能被面板改掉（Hub 其他頁面還在用）。
        shared = style.configure('TLabel') or {}
        self.assertNotEqual(shared.get('background'), '#f3f6fa')

    def test_caller_palette_overrides_only_what_it_passes(self):
        panel = embed.mount_quick_panel(self.page, bg='#f3f6fa', autoconnect=False,
                                        smoke=True, palette={'button': '#123456'})
        self.addCleanup(panel.close)
        style = ttk.Style(self.root)
        self.assertEqual(style.configure('Quick.TButton').get('background'), '#123456')
        self.assertEqual(style.configure('Quick.TLabel').get('background'), '#f3f6fa')

    def test_manual_connection_buttons_are_hidden_when_embedded(self):
        self.root.update()
        self.assertFalse(self.panel.connect_button.winfo_ismapped())
        self.assertFalse(self.panel.refresh_button.winfo_ismapped())
        self.assertFalse(self.panel.buttons['extend'].winfo_ismapped())
        # 其他遊戲內指令的按鈕仍在（定位部隊、修改功能裡的訓練）。
        self.assertTrue(self.panel.host.winfo_ismapped())

    def test_panel_visible_only_on_its_own_tab(self):
        self.root.update()
        self.assertTrue(self.panel.panel_visible())
        self.book.select(self.other)
        self.root.update()
        self.assertFalse(self.panel.panel_visible())
        self.book.select(self.page)
        self.root.update()
        self.assertTrue(self.panel.panel_visible())

    def test_hotkeys_only_fire_while_the_page_is_showing(self):
        hits = []
        self.panel.key = lambda action: hits.append(action)
        self.root.focus_force()
        self.root.update()
        self.root.event_generate('<Control-Alt-KeyPress-F7>')
        self.root.update()
        self.assertEqual(hits, ['focus_unit'])
        self.book.select(self.other)
        self.root.update()
        self.root.event_generate('<Control-Alt-KeyPress-F7>')
        self.root.update()
        self.assertEqual(hits, ['focus_unit'])

    def test_embedded_panel_yields_to_the_standalone_window(self):
        from quick_control_instance import PanelInstance
        guard = PanelInstance()
        if not guard.acquire():
            self.skipTest('a quick-command panel is already running on this machine')
        self.addCleanup(guard.close)
        self.assertFalse(self.panel.claim_instance())
        self.assertEqual(self.panel.status.get(), '等待另一個快速軍令視窗關閉')
        self.assertIsNone(self.panel.instance)

    def test_claim_reuses_the_same_lock(self):
        from quick_control_instance import PanelInstance
        probe = PanelInstance()
        if not probe.acquire():
            self.skipTest('another quick-command panel already holds the lock')
        probe.close()
        self.assertTrue(self.panel.claim_instance())
        self.assertIsNotNone(self.panel.instance)
        self.assertTrue(self.panel.claim_instance())
        self.panel.close()
        self.assertIsNone(self.panel.instance)

    def test_tall_layout_does_not_need_a_second_window(self):
        panel = self.panel
        panel.modification_frame.pack(fill='x', before=panel.fold_anchor)
        self.root.update()
        self.assertTrue(panel.modification_frame.winfo_ismapped())
        self.assertEqual(panel.scroll_host.inner.winfo_toplevel(), self.root)

    def test_close_does_not_destroy_the_hub_window(self):
        self.panel.close()
        self.assertTrue(self.panel.closed)
        self.root.update()
        self.assertEqual(self.root.winfo_exists(), 1)
        self.assertTrue(self.root.winfo_ismapped())


class MountTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk display unavailable: %s' % exc)
        self.addCleanup(self.root.destroy)
        self.root.geometry('800x600+3200+2000')
        self.host = tk.Frame(self.root, bg='#f3f6fa')
        self.host.pack(fill='both', expand=True)

    def test_mount_returns_embedded_panel_and_honours_env(self):
        with mock.patch.dict(os.environ, {'SGI_QUICK_EMBED_AUTOCONNECT': '0'}):
            module = embed.load_panel_module()
            with mock.patch.object(module, 'Panel', wraps=module.Panel) as patched:
                panel = embed.mount_quick_panel(self.host, bg='#f3f6fa')
                self.assertTrue(patched.called)
        self.addCleanup(panel.close)
        self.root.update()
        self.assertTrue(panel.embedded)
        self.assertFalse(panel.autoconnect)
        self.assertTrue(panel.host.winfo_ismapped())
        self.assertTrue(hasattr(panel, 'scroll_host'))


if __name__ == '__main__':
    unittest.main()
