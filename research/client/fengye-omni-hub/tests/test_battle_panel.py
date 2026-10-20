"""Shadow provenance, asynchronous refresh, and real mapped original-map rendering."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]
from fengye_battle_panel import BattlePanel, SHADOW_PREFIX, capture_time, prepare_payload
from original_sprites import sprite_file
from panorama_model import object_key


def sample():
    return {'ok': True, 'source_prefix': SHADOW_PREFIX,
            'state': {'readonly': True, 'capture_end': datetime.now(timezone.utc).isoformat(),
                      'entities': {
                          'lords': [{'force_id': 3, 'name': '齊', 'gold': 36972,
                                     'rice': 95000, 'color_index_raw': 3}],
                          'cities_and_barriers': [
                              {'type': 'city', 'city_id': 1, 'name': '臨淄', 'owner_raw': 3,
                               'world_xy_raw': [50, 100], 'city_art_variant_flag': 1,
                               'defense': 100, 'population': 50000}],
                          'generals': [], 'field_units': [], 'traps': [],
                          'production_buildings': []}}}


class PayloadTests(unittest.TestCase):
    def test_rejects_player_source_and_missing_raw_state(self):
        data = sample()
        for source in ('prefix-dingman-local', 'prefix-sikarugir10', None):
            data['source_prefix'] = source
            with self.assertRaisesRegex(ValueError, '風夜資料來源'):
                prepare_payload(data)
        with self.assertRaisesRegex(ValueError, '完整地圖'):
            prepare_payload({'ok': True, 'source_prefix': SHADOW_PREFIX})

    def test_derivation_keeps_raw_immutable_and_unknown_unknown(self):
        data = sample()
        data['state']['entities']['field_units'] = [
            {'type': 'field_unit', 'unit_id': 7, 'unit_kind': '强化骑兵',
             'owner_raw': 3, 'world_xy_raw': [49, 100], 'general_ids': [], 'raw_1d': 82}]
        before = copy.deepcopy(data)
        display = prepare_payload(data)
        self.assertEqual(data, before)
        unit = display['entities']['field_units'][0]
        self.assertEqual(unit['morale'], 82)
        self.assertIsNone(unit['native_attack_index'])

    def test_capture_time_does_not_invent_timestamp(self):
        self.assertIsNone(capture_time({}))
        self.assertIsNone(capture_time({'captured_at': 'bad'}))
        self.assertIsNotNone(capture_time(sample()))


class BattlePanelMappedTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped Tk display unavailable: %s' % exc)
        self.root.geometry('1500x900+3200+2000')
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.root.destroy)
        self.service = mock.Mock()
        self.service.battlefield.return_value = sample()
        self.panel = BattlePanel(self.root, self.service, autostart=False, poll_ms=250)
        self.panel.pack(fill='both', expand=True)
        self.addCleanup(self.panel.dispose)
        self.root.update()
        self.assertTrue(self.panel.panorama.canvas.winfo_ismapped())

    def until(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertTrue(condition())
        self.assertEqual(self.errors, [])

    def load(self):
        self.panel.refresh()
        self.until(lambda: self.panel.raw_state is not None)

    def test_single_flight_keeps_ui_responsive_then_polls_again(self):
        release = threading.Event()
        calls = []
        def read():
            calls.append(threading.get_ident())
            release.wait(2)
            return sample()
        self.service.battlefield.side_effect = read
        try:
            self.panel.start()
            for _ in range(4):
                self.assertFalse(self.panel.refresh())
            self.root.update()
            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0], threading.get_ident())
            marker = []
            self.root.after(10, lambda: marker.append(True))
            self.until(lambda: marker)
        finally:
            release.set()
        self.until(lambda: len(calls) >= 2)
        self.panel.stop()

    def test_error_keeps_last_frame_and_timestamp_but_marks_stale(self):
        self.load()
        original = self.panel.raw_state
        stamp = self.panel.last_capture_at
        self.service.battlefield.return_value = {'ok': False, 'error': '風夜未連線'}
        self.panel.refresh()
        self.until(lambda: self.panel.last_error is not None)
        self.assertIs(self.panel.raw_state, original)
        self.assertEqual(self.panel.last_capture_at, stamp)
        self.assertIn('資料已過期', self.panel.status_var.get())
        self.assertIn('風夜未連線', self.panel.status_var.get())

    def test_empty_state_and_unknown_values_render_without_fabrication(self):
        empty = sample()
        empty['state']['entities'] = {}
        self.service.battlefield.return_value = empty
        self.load()
        self.assertEqual(self.panel.forces.get_children(), ())
        self.assertEqual(self.panel.units.get_children(), ())
        self.assertEqual(self.panel.panorama.hits, [])
        self.assertIsNone(self.panel.last_error)
        unknown = sample()
        unknown['state']['entities']['lords'][0]['gold'] = None
        self.service.battlefield.return_value = unknown
        self.panel.refresh()
        self.until(lambda: not self.panel._inflight)
        row = self.panel.forces.item(self.panel.forces.get_children()[0], 'values')
        self.assertEqual(row[1], '—')
        self.assertIsNone(self.panel.raw_state['entities']['lords'][0]['gold'])

    def test_refresh_preserves_camera_layers_and_original_city_detail(self):
        self.load()
        page = self.panel.panorama
        page.center, page.zoom = (50, 100), 3.0
        page.layers['补给线'].set(False)
        page.draw()
        hit = next(hit for hit in page.hits if hit[2] == object_key(
            '城关', self.panel.display_state['entities']['cities_and_barriers'][0]))
        canvas = page.canvas
        canvas.event_generate('<ButtonPress-1>', x=round(hit[0]), y=round(hit[1]))
        canvas.event_generate('<ButtonRelease-1>', x=round(hit[0]), y=round(hit[1]))
        self.root.update()
        self.assertIn('臨淄', page.detail.get())
        self.assertIn('50', page.detail.get())
        self.assertFalse(page._side_open)
        self.assertFalse(page._side.winfo_ismapped())
        self.root.update()
        camera = (page.center, page.zoom)
        force_key = self.panel.forces.get_children()[0]
        self.panel.forces.selection_set(force_key)
        self.panel.refresh()
        self.until(lambda: not self.panel._inflight)
        self.assertEqual((page.center, page.zoom), camera)
        self.assertFalse(page.layers['补给线'].get())
        self.assertEqual(self.panel.forces.selection(), (force_key,))
        self.assertFalse(page._side_open)
        self.assertFalse(page._side.winfo_ismapped())

    def test_different_original_unit_sprites_and_flags_are_available(self):
        page = self.panel.panorama
        state = sample()['state']
        sprites = page.sprites
        names = [sprite_file({'type': 'field_unit', 'unit_kind': name})
                 for name in ('步兵', '强化骑兵', '强弓兵')]
        self.assertEqual(len(set(names)), 3)
        for name in names:
            self.assertIsNotNone(sprites.named(name, 40), name)
        self.assertIsNotNone(sprites.image(state['entities']['cities_and_barriers'][0], 50, state))
        self.assertIsNotNone(sprites.flag(state, 3, 24))

    def test_toolbar_omits_filters_and_zoom_buttons_have_dark_text(self):
        page = self.panel.panorama
        self.root.update()
        bar = page.winfo_children()[0]
        visible_checks = []
        for widget in bar.winfo_children():
            if isinstance(widget, tk.Checkbutton):
                if widget.winfo_ismapped():
                    visible_checks.append(widget)
                self.assertEqual(bool(widget.winfo_ismapped()), widget.cget('text') == '文字')
            if isinstance(widget, tk.Button):
                self.assertEqual(widget.cget('foreground'), '#203440')
        self.assertEqual([w.cget('text') for w in visible_checks], ['文字'])
        self.assertFalse(page._side_btn.winfo_ismapped())
        self.assertFalse(page._side.winfo_ismapped())
        self.assertFalse(page._side_open)
        holder = page.canvas.master
        nav = next(w for w in holder.master.winfo_children() if w is not holder)
        visible = [w for w in nav.winfo_children() if w.winfo_ismapped()]
        self.assertEqual(len(visible), 5)
        self.assertEqual([w.cget('text') for w in visible][:4], ['↑', '↓', '←', '→'])
        self.assertTrue(all(v.get() for v in page.layers.values()))

    def test_text_toggle_does_not_hide_traps_or_open_opponent_sidebar(self):
        self.load()
        page = self.panel.panorama
        bar = page.winfo_children()[0]
        text_check = next(w for w in bar.winfo_children()
                          if isinstance(w, tk.Checkbutton) and w.cget('text') == '文字')
        self.assertTrue(text_check.winfo_ismapped())
        self.assertTrue(page.layers['文字'].get())
        text_check.invoke()
        self.root.update()
        self.assertFalse(page.layers['文字'].get())
        self.assertTrue(page.layers['陷阱'].get())
        self.assertFalse(page._side_open)
        text_check.invoke()
        self.root.update()
        self.assertTrue(page.layers['文字'].get())
        # A detached window copies layer values before drawing. The viewer
        # must keep trap visibility even if an old saved view disabled it.
        page.layers['陷阱'].set(False)
        page.draw()
        self.assertTrue(page.layers['陷阱'].get())
        self.assertFalse(page._side.winfo_ismapped())

    def test_detached_window_uses_same_shadow_snapshot_without_player_api(self):
        self.load()
        with mock.patch('wine_nav.open_panorama') as launch:
            win = self.panel.panorama.open_detached()
            self.root.update()
            page = self.panel._detached[0][1]
            self.assertIs(page.state, self.panel.display_state)
            launch.assert_not_called()
            self.assertTrue(win.winfo_ismapped())

    def test_native_scroll_origin_stays_fixed_for_mapped_trackpad_events(self):
        page = self.panel.panorama
        canvas = page.canvas
        with mock.patch('map_navigation._pointer_root', return_value=None):
            try:
                canvas.bind('<TouchpadScroll>')
            except tk.TclError:
                self.skipTest('TouchpadScroll requires Tk 9')
            for _ in range(5):
                page._wheel_at = 0
                canvas.event_generate('<TouchpadScroll>', delta=16, x=200, y=150,
                    rootx=canvas.winfo_rootx() + 200, rooty=canvas.winfo_rooty() + 150)
                self.root.update()
                self.assertEqual((canvas.canvasx(0), canvas.canvasy(0)), (0, 0))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
