"""Mapped Tk events, including the inherited panorama's class wheel bindings.

An unmapped/withdrawn window silently drops generated wheel events. These
windows are mapped off-screen; assertions check Tk's actual canvas origin,
which can move even while yview() still reports (0, 1).
"""
import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]

from tkinter import ttk
from map_navigation import bind_pointer_wheel
from native_window import FengyeWindow, map_unproject


class MapEventTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped Tk display unavailable: %s' % exc)
        self.addCleanup(self.root.destroy)
        self.root.geometry('1200x780+3200+2000')
        self.root.report_callback_exception = self.callback_error
        self.errors = []
        # Synthetic off-screen events must use their supplied root position,
        # not the user's unrelated physical pointer on the real desktop.
        pointer = mock.patch('map_navigation._pointer_root', return_value=None)
        pointer.start()
        self.addCleanup(pointer.stop)
        # OmniWindow installs these bindings even though its maps are hidden.
        self.legacy = tk.Canvas(self.root)
        bind_pointer_wheel(self.legacy, lambda *_: None)
        self.app = FengyeWindow.__new__(FengyeWindow)
        self.app.root = self.root
        self.app.face = 'Helvetica'
        self.app.control_book = ttk.Notebook(self.root)
        self.app.control_book.pack(fill='both', expand=True)
        self.app.battle_page = tk.Frame(self.app.control_book)
        self.app.command_page = tk.Frame(self.app.control_book)
        self.app.control_book.add(self.app.battle_page, text='戰場')
        self.app._battle_refresh = lambda: None  # No game, network or commands.
        self.app._build_battle_page()
        self.root.update()
        self.canvas = self.app.battle_map
        self.assertTrue(self.canvas.winfo_ismapped())
        self.app._battle_draw_map(
            [{'xy': [50, 100], 'name': '測試城', 'owner': 1}], [], {})
        self.root.update()

    def callback_error(self, *_error):
        self.errors.append(_error)

    def assert_origin(self):
        self.assertEqual((self.canvas.canvasx(0), self.canvas.canvasy(0)), (0, 0))
        self.assertEqual(self.errors, [])

    def touch(self, dx=0, dy=0):
        try:
            self.canvas.bind('<TouchpadScroll>')
        except tk.TclError:
            self.skipTest('TouchpadScroll requires Tk 9')
        packed = ((dx & 0xffff) << 16) | (dy & 0xffff)
        self.app._battle_wheel_at = 0
        self.canvas.event_generate('<TouchpadScroll>', delta=packed, x=500, y=140,
                                   rootx=self.canvas.winfo_rootx() + 500,
                                   rooty=self.canvas.winfo_rooty() + 140)
        self.root.update()

    def test_touchpad_changes_zoom_without_scrolling_canvas(self):
        for _ in range(12):
            self.touch(dy=16)
            self.assert_origin()
        self.assertGreater(self.app.battle_zoom, 1)

    def test_touchpad_zoom_keeps_pointer_world_point(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        before = self.app._battle_geometry(w, h)[3]
        source = map_unproject(500, 140, before, w, h)
        self.touch(dy=16)
        after = self.app._battle_geometry(w, h)[3]
        self.assertAlmostEqual(self.app.battle_zoom, 1.2)
        point = map_unproject(500, 140, after, w, h)
        self.assertAlmostEqual(source[0], point[0], places=6)
        self.assertAlmostEqual(source[1], point[1], places=6)
        self.assert_origin()

    def test_horizontal_and_reverse_touchpad_do_not_scroll(self):
        for dx, dy in ((16, 0), (0, -16), (-16, 0), (0, 16)):
            self.touch(dx, dy)
            self.assert_origin()

    def test_tiny_touchpad_events_are_consumed(self):
        for _ in range(24):
            self.touch(dy=1)
            self.assert_origin()

    def test_wheel_and_linux_buttons_only_change_camera(self):
        for event, kwargs in (('<MouseWheel>', {'delta': 120}),
                              ('<Shift-MouseWheel>', {'delta': -120}),
                              ('<Button-4>', {}), ('<Button-5>', {})):
            self.app._battle_wheel_at = 0
            self.canvas.event_generate(event, x=500, y=140, **kwargs)
            self.root.update()
            self.assert_origin()

    def test_canvas_cannot_drift_even_from_class_scroll(self):
        self.canvas.yview_scroll(-12, 'units')
        self.canvas.xview_scroll(12, 'units')
        self.root.update()
        # Without a bounded viewport yview is (0,1) but canvasy(0) is -432.
        self.assert_origin()

    def test_reset_drag_and_tab_switch_preserve_canvas_origin(self):
        self.touch(dy=16)
        self.app._battle_drag_start(SimpleNamespace(x=500, y=140))
        self.app._battle_drag_move(SimpleNamespace(x=530, y=170))
        self.app._battle_drag_end()
        self.app._battle_reset_view()
        self.root.update()
        self.assertEqual(self.app.battle_zoom, 1)
        self.assert_origin()
        other = tk.Frame(self.app.control_book)
        self.app.control_book.add(other, text='other')
        self.app.control_book.select(other)
        self.root.update()
        self.app.control_book.select(self.app.battle_page)
        self.root.update()
        self.assert_origin()


if __name__ == '__main__':
    unittest.main()
