"""Mapped Tk events, including the inherited panorama's class wheel bindings.

An unmapped/withdrawn window silently drops generated wheel events. These
windows are mapped off-screen; assertions check Tk's actual canvas origin,
which can move even while yview() still reports (0, 1).
"""
import sys
import tkinter as tk
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]

from tkinter import ttk
from map_navigation import bind_pointer_wheel
from fengye_battle_panel import ShadowPanorama
from panorama_model import MIN_ZOOM


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
        self.book = ttk.Notebook(self.root)
        self.book.pack(fill='both', expand=True)
        self.page = tk.Frame(self.book)
        self.book.add(self.page, text='戰場')
        # This is the actual renderer mounted by BattlePanel; no retired map
        # camera, game reads, network source or commands are involved.
        self.app = ShadowPanorama(self.page, title='戰場測試', detachable=False)
        self.app.pack(fill='both', expand=True)
        self.root.update()
        self.canvas = self.app.canvas
        self.assertTrue(self.canvas.winfo_ismapped())
        self.app.center, self.app.zoom = (50.5, 101.0), 3.0
        self.app.update_state({'entities': {}})
        self.root.update()
        self.initial_zoom = self.app.zoom
        self.anchor = (round(self.canvas.winfo_width()*.44),
                       round(self.canvas.winfo_height()*.47))

    def callback_error(self, *_error):
        self.errors.append(_error)

    def assert_origin(self):
        self.assertEqual((self.canvas.canvasx(0), self.canvas.canvasy(0)), (0, 0))
        self.assertEqual(self.errors, [])

    def flush_draw(self):
        # Panorama coalesces draws with an actual after timer. update() alone
        # can return before fit/Configure has applied its legal camera clamp.
        deadline = time.monotonic() + 1
        while getattr(self.app, '_draw_job', None) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertIsNone(getattr(self.app, '_draw_job', None))

    def touch(self, dx=0, dy=0):
        try:
            self.canvas.bind('<TouchpadScroll>')
        except tk.TclError:
            self.skipTest('TouchpadScroll requires Tk 9')
        packed = ((dx & 0xffff) << 16) | (dy & 0xffff)
        self.app._wheel_at = 0
        x, y = self.anchor
        self.canvas.event_generate('<TouchpadScroll>', delta=packed, x=x, y=y,
                                   rootx=self.canvas.winfo_rootx() + x,
                                   rooty=self.canvas.winfo_rooty() + y)
        self.root.update()

    def test_touchpad_changes_zoom_without_scrolling_canvas(self):
        for _ in range(12):
            self.touch(dy=16)
            self.assert_origin()
        self.assertGreater(self.app.zoom, self.initial_zoom)

    def test_touchpad_zoom_keeps_pointer_world_point(self):
        source = self.app._world_at(*self.anchor)
        self.touch(dy=16)
        self.assertAlmostEqual(self.app.zoom, self.initial_zoom + .5)
        point = self.app._world_at(*self.anchor)
        self.assertAlmostEqual(source[0], point[0], places=6)
        self.assertAlmostEqual(source[1], point[1], places=6)
        self.assert_origin()

    def test_horizontal_and_reverse_touchpad_do_not_scroll(self):
        for dx, dy in ((16, 0), (0, -16), (-16, 0), (0, 16)):
            old = self.app.zoom
            self.touch(dx, dy)
            self.assertNotEqual(self.app.zoom, old)
            self.assert_origin()

    def test_tiny_touchpad_events_are_consumed(self):
        for _ in range(24):
            self.touch(dy=1)
            self.assert_origin()
        self.assertGreater(self.app.zoom, self.initial_zoom)

    def test_wheel_and_linux_buttons_only_change_camera(self):
        for event, kwargs in (('<MouseWheel>', {'delta': 120}),
                              ('<Shift-MouseWheel>', {'delta': -120}),
                              ('<Button-4>', {}), ('<Button-5>', {})):
            old = self.app.zoom
            self.app._wheel_at = 0
            x, y = self.anchor
            self.canvas.event_generate(event, x=x, y=y,
                rootx=self.canvas.winfo_rootx()+x, rooty=self.canvas.winfo_rooty()+y, **kwargs)
            self.root.update()
            self.assertNotEqual(self.app.zoom, old)
            self.assert_origin()

    def test_canvas_cannot_drift_even_from_class_scroll(self):
        self.canvas.yview_scroll(-12, 'units')
        self.canvas.xview_scroll(12, 'units')
        self.root.update()
        # Without a bounded viewport yview is (0,1) but canvasy(0) is -432.
        self.assert_origin()

    def test_wasd_pans_even_when_focus_is_not_the_canvas(self):
        # 2026-10-20 使用者回報「WASD 經常用不了」：焦點在別的控制項時，
        # 綁在 canvas 上的按鍵收不到事件。改成 toplevel 統一派送。
        button = ttk.Button(self.page, text='焦點測試')
        button.pack()
        self.root.update()
        button.focus_set()
        self.root.update()
        before = self.app.center
        button.event_generate('<KeyPress-w>')
        self.root.update()
        self.assertLess(self.app.center[1], before[1])
        self.assert_origin()

    def test_wasd_in_a_text_field_does_not_pan(self):
        entry = ttk.Entry(self.page)
        entry.pack()
        self.root.update()
        entry.focus_set()
        self.root.update()
        before = self.app.center
        entry.event_generate('<KeyPress-w>')
        self.root.update()
        self.assertEqual(self.app.center, before)
        self.assert_origin()

    def test_reset_drag_and_tab_switch_preserve_canvas_origin(self):
        self.touch(dy=16)
        before = self.app.center
        x, y = self.anchor
        self.canvas.event_generate('<ButtonPress-1>', x=x, y=y)
        self.canvas.event_generate('<B1-Motion>', x=x+30, y=y+30)
        self.canvas.event_generate('<ButtonRelease-1>', x=x+30, y=y+30)
        self.root.update()
        self.assertNotEqual(self.app.center, before)
        self.app.fit()
        self.flush_draw()
        # The original panorama computes the minimum legal fit for this
        # viewport's aspect ratio, so fit need not be exactly MIN_ZOOM.
        self.assertGreaterEqual(self.app.zoom, MIN_ZOOM)
        self.assertLess(self.app.zoom, self.initial_zoom)
        self.assert_origin()
        fitted = (self.app.center, self.app.zoom)
        other = tk.Frame(self.book)
        self.book.add(other, text='other')
        self.book.select(other)
        self.root.update()
        self.book.select(self.page)
        self.root.update()
        self.flush_draw()
        self.assertTrue(self.canvas.winfo_ismapped())
        self.assertEqual((self.app.center, self.app.zoom), fitted)
        self.assert_origin()


if __name__ == '__main__':
    unittest.main()
