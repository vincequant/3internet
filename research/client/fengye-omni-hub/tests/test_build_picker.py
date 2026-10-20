"""Construction picker geometry, strict candidates and mapped Tk interaction."""
import importlib.util
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'app')]
from PIL import Image
from build_picker import (BuildPicker, EmbeddedConstructionMap, cell_at_pixel,
                          construction_candidates, cell_set, cell_vertices, crop_box,
                          hit_cell, nearby_cells, project, valid_candidates,
                          view_geometry, world_pixel)

HELPER_PATH = ROOT.parent/'protocol-lab'/'_p60_pick_cell_wide.py'
helper = None
if HELPER_PATH.is_file():
    spec = importlib.util.spec_from_file_location('construction_cell_helper', HELPER_PATH)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)


class CellGeometryTests(unittest.TestCase):
    def test_all_81_centers_hit_correct_staggered_cell(self):
        center = (50, 100)
        box = crop_box(center)
        view = view_geometry(box, 940, 300)
        for xy in nearby_cells(center):
            sx, sy = project(world_pixel(*xy), box, view)
            self.assertEqual(hit_cell(sx, sy, center, box, view), xy)
        self.assertIsNone(hit_cell(-100, -100, center, box, view))

    def test_cell_geometry_matches_original_diamonds_and_map_edges(self):
        for center in ((0, 0), (100, 201), (52, 99)):
            box = crop_box(center)
            view = view_geometry(box, 600, 250)
            for xy in nearby_cells(center):
                for px, py in cell_vertices(*xy):
                    self.assertLessEqual(box[0], px)
                    self.assertLessEqual(box[1], py)
                    self.assertGreaterEqual(box[2], px)
                    self.assertGreaterEqual(box[3], py)
                self.assertEqual(hit_cell(*project(world_pixel(*xy), box, view), center, box, view), xy)

    def test_only_explicit_unoccupied_candidates_are_selectable(self):
        payload = {'ok': True, 'cells': [[50, 100], [51, 100], [52, 100], [53, 100], [0, 0]],
                   'occupied': {(52, 100): 'city'}, 'busy': [{'xy': [53, 100]}]}
        self.assertEqual(valid_candidates(payload, (50, 100))[0], {(51, 100)})
        payload['ok'] = False
        self.assertEqual(valid_candidates(payload, (50, 100)), (set(), set(), set()))
        self.assertEqual(cell_set([[1.2, 2], [None, 2], [-1, 2], [101, 0], ['1', 2], [1, 2]]), {(1, 2)})

    @unittest.skipIf(helper is None, 'Collector helper is a separate lab deployment')
    def test_helper_returns_all_verified_candidates_not_eight(self):
        terrain = bytearray([2]*101*202)
        terrain[100*101+51] = 4
        snapshot = {'terrain_grid': {'width': 101, 'height': 202, 'types': terrain.hex()},
                    'entities': {'production_buildings': [{'world_xy_raw': [49, 100]}],
                                 'traps': [{'world_xy_raw': [50, 99]}],
                                 'cities_and_barriers': [{'world_xy_raw': [50, 100]}]}}
        result = helper.construction_cells(snapshot, 50, 100)
        cells = {tuple(row['xy']) for row in result['candidates']}
        self.assertEqual(len(cells), 77)
        for blocked in ((49, 100), (50, 99), (50, 100), (51, 100)):
            self.assertNotIn(blocked, cells)
        self.assertEqual(result['radius'], 4)
        self.assertEqual(result['schema_version'], 2)
        self.assertIn((54, 104), cells)
        self.assertNotIn((55, 100), cells)

    @unittest.skipIf(helper is None, 'Collector helper is a separate lab deployment')
    def test_incomplete_helper_terrain_is_unknown(self):
        with self.assertRaises(ValueError):
            helper.construction_cells({'terrain_grid': {'width': 5, 'height': 5, 'types': '02'}}, 0, 0)


class BuildPickerTkTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped Tk display unavailable: %s' % exc)
        self.root.geometry('1000x550+3200+2000')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.root.destroy)
        terrain = mock.Mock()
        terrain.crop.side_effect = lambda box: Image.new('RGB', (int(box[2]-box[0]), int(box[3]-box[1])), '#68724e')
        patch = mock.patch('build_picker.shared_terrain', return_value=terrain)
        patch.start()
        self.addCleanup(patch.stop)
        self.chosen = []

    def pump_until(self, predicate, timeout=3):
        limit = time.monotonic()+timeout
        while not predicate() and time.monotonic() < limit:
            self.root.update()
            time.sleep(.005)
        self.root.update()
        self.assertTrue(predicate())
        self.assertEqual(self.errors, [])

    def picker(self, loader):
        picker = BuildPicker(self.root, {'city_id': 8, 'name': '臨淄', 'xy': [50, 100]},
                             '建設', lambda x, y: self.chosen.append((x, y)), loader)
        picker.geometry('1000x500+3200+2000')
        self.root.update()
        self.assertTrue(picker.winfo_ismapped())
        self.assertTrue(picker.canvas.winfo_ismapped())
        return picker

    def click_cell(self, picker, xy):
        box = crop_box(picker.center)
        view = view_geometry(box, picker.canvas.winfo_width(), picker.canvas.winfo_height())
        sx, sy = project(world_pixel(*xy), box, view)
        picker.canvas.event_generate('<Button-1>', x=round(sx), y=round(sy))
        self.root.update()

    def test_real_mapped_click_requires_explicit_selection_then_confirmation(self):
        ui_thread = threading.get_ident()
        threads = []
        def loader():
            threads.append(threading.get_ident())
            return {'ok': True, 'cells': [[51, 100], [52, 100]], 'busy': [[52, 100]]}
        picker = self.picker(loader)
        self.pump_until(lambda: picker._known and picker._active is None)
        self.assertNotEqual(threads[0], ui_thread)
        self.assertIsNone(picker.selected)
        self.assertEqual(str(picker.use_button.cget('state')), 'disabled')
        self.click_cell(picker, (52, 100))
        self.assertIsNone(picker.selected)
        self.click_cell(picker, (51, 100))
        self.assertEqual(picker.selected, (51, 100))
        self.assertEqual(self.chosen, [])
        picker.use_button.invoke()
        self.assertEqual(self.chosen, [(51, 100)])
        self.assertFalse(picker.winfo_exists())

    def test_refresh_invalidates_selected_busy_cell(self):
        payload = {'ok': True, 'cells': [[51, 100]]}
        picker = self.picker(lambda: dict(payload))
        self.pump_until(lambda: picker._known and picker._active is None)
        self.click_cell(picker, (51, 100))
        payload['busy'] = [[51, 100]]
        picker.refresh()
        self.pump_until(lambda: picker._active is None)
        self.assertIsNone(picker.selected)
        self.assertIn('請重選', picker.status.cget('text'))
        self.assertEqual(str(picker.use_button.cget('state')), 'disabled')

    def test_unknown_read_cannot_reuse_previous_candidates(self):
        payload = {'ok': True, 'cells': [[51, 100]]}
        picker = self.picker(lambda: dict(payload))
        self.pump_until(lambda: picker._known and picker._active is None)
        self.click_cell(picker, (51, 100))
        payload.update(ok=False, error='離線')
        picker.refresh()
        self.pump_until(lambda: picker._active is None)
        self.assertFalse(picker._known)
        self.assertEqual(picker.candidates, set())
        picker._use()
        self.assertEqual(self.chosen, [])

    def test_singleflight_and_old_city_reply_discarded(self):
        gate = threading.Event()
        calls = []
        def first():
            calls.append(1)
            gate.wait(2)
            return {'ok': True, 'cells': [[51, 100]]}
        picker = self.picker(first)
        for _ in range(3):
            self.assertFalse(picker.refresh())
        self.assertEqual(calls, [1])
        picker.set_city({'name': '新城', 'xy': [60, 110]}, loader=lambda: {'ok': True, 'cells': [[61, 110]]})
        gate.set()
        self.pump_until(lambda: picker._known and picker._active is None)
        self.assertEqual(picker.candidates, {(61, 110)})
        self.assertIsNone(picker.selected)

    def test_auto_refresh_and_close_discard_late_reply(self):
        calls = []
        gate = threading.Event()
        def loader():
            calls.append(1)
            if len(calls) == 2:
                gate.wait(10)
            return {'ok': True, 'cells': [[51, 100]]}
        picker = self.picker(loader)
        picker.refresh_seconds = .06
        self.pump_until(lambda: len(calls) == 2)
        picker.destroy()
        gate.set()
        self.root.update()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.chosen, [])


    @staticmethod
    def raw_payload():
        return {'ok': True, 'source_prefix': 'prefix-fengye-shadow',
                'cells': [[51, 100], [52, 100]], 'busy': [[52, 100]],
                'occupied': [[50, 100], [50, 102]],
                'state': {'readonly': True, 'entities': {
                    'lords': [{'force_id': 3, 'name': '齊', 'color_index_raw': 3,
                               'gold': 37022, 'rice': 95000, 'capital_city_id': 8}],
                    'cities_and_barriers': [{'type': 'city', 'city_id': 8,
                        'name': '臨淄', 'owner_raw': 3, 'world_xy_raw': [50, 100],
                        'city_art_variant_flag': 1, 'defense': [100, 100], 'population': 50000}],
                    'field_units': [{'type': 'field_unit', 'unit_id': 7,
                        'unit_kind': '强化骑兵', 'owner_raw': 3, 'world_xy_raw': [49, 100],
                        'general_ids': [], 'raw_1d': 82}],
                    'production_buildings': [{'type': 'horse_farm', 'owner_raw': 3,
                        'world_xy_raw': [50, 102], 'linked_city_id': 8,
                        'object_id_candidate': 9, 'building_ui_amount': 2000}],
                    'traps': [], 'generals': []}}}

    def panorama_cell(self, picker, xy):
        from panorama_model import layer_for_zoom
        page = picker.panorama
        return page._project(*xy, page.canvas.winfo_width(), page.canvas.winfo_height(), layer_for_zoom(page.zoom))

    def test_original_panorama_draws_real_sprites_and_transparent_selectable_outlines(self):
        payload = self.raw_payload()
        picker = self.picker(lambda: payload)
        self.pump_until(lambda: picker._known and picker._active is None and picker._panorama_mode)
        self.root.update()
        page = picker.panorama
        page.draw(refresh_view=False)
        from fengye_battle_panel import ShadowPanorama
        self.assertIsInstance(page, ShadowPanorama)
        self.assertTrue(page.canvas.winfo_ismapped())
        sprite_items = [item for item in page.canvas.find_withtag('ov') if page.canvas.type(item) == 'image']
        self.assertGreaterEqual(len(sprite_items), 3)  # Actual city/unit/building/flag artwork.
        outlines = page.canvas.find_withtag('build-candidate')
        self.assertTrue(outlines)
        self.assertTrue(all(page.canvas.itemcget(item, 'fill') == '' for item in outlines))
        self.assertEqual(page.canvas.find_withtag('cell-label'), ())
        sx, sy = self.panorama_cell(picker, (51, 100))
        page.canvas.event_generate('<ButtonPress-1>', x=round(sx), y=round(sy))
        page.canvas.event_generate('<ButtonRelease-1>', x=round(sx), y=round(sy))
        self.root.update()
        self.assertEqual(picker.selected, (51, 100))
        self.assertEqual(self.chosen, [])
        selected = page.canvas.find_withtag('build-selected')
        self.assertEqual(len(selected), 1)
        self.assertEqual(page.canvas.itemcget(selected[0], 'fill'), '')
        self.assertEqual(page.canvas.itemcget(selected[0], 'outline'), '#ffe35c')
        picker.use_button.invoke()
        picker._use()  # A queued duplicate callback must not repeat selection.
        self.assertEqual(self.chosen, [(51, 100)])

    def test_original_panorama_wheel_and_drag_preserved_but_objects_never_send(self):
        picker = self.picker(self.raw_payload)
        self.pump_until(lambda: picker._known and picker._active is None and picker._panorama_mode)
        page = picker.panorama
        canvas = page.canvas
        zoom = page.zoom
        page._wheel_at = 0
        with mock.patch('map_navigation._pointer_root', return_value=None):
            canvas.event_generate('<MouseWheel>', delta=120, x=500, y=140)
            self.root.update()
        self.assertGreater(page.zoom, zoom)
        center = page.center
        canvas.event_generate('<ButtonPress-1>', x=500, y=140)
        canvas.event_generate('<B1-Motion>', x=540, y=160)
        canvas.event_generate('<ButtonRelease-1>', x=540, y=160)
        self.root.update()
        self.assertNotEqual(page.center, center)
        self.assertIsNone(picker.selected)
        self.assertEqual(self.chosen, [])
        self.assertEqual((canvas.canvasx(0), canvas.canvasy(0)), (0, 0))
        # Clicking the city itself has no original origin callback/card/send.
        sx, sy = self.panorama_cell(picker, (50, 100))
        canvas.event_generate('<ButtonPress-1>', x=round(sx), y=round(sy))
        canvas.event_generate('<ButtonRelease-1>', x=round(sx), y=round(sy))
        self.root.update()
        self.assertIsNone(picker.selected)
        self.assertEqual(self.chosen, [])
        # Exact cell selection still follows the original camera after both
        # zoom and drag; there is no second, drifting picker projection.
        sx, sy = self.panorama_cell(picker, (51, 100))
        canvas.event_generate('<ButtonPress-1>', x=round(sx), y=round(sy))
        canvas.event_generate('<ButtonRelease-1>', x=round(sx), y=round(sy))
        self.root.update()
        self.assertEqual(picker.selected, (51, 100))
        self.assertEqual(self.chosen, [])

    def test_missing_full_state_keeps_last_original_frame_but_disables_choice(self):
        payload = self.raw_payload()
        picker = self.picker(lambda: dict(payload))
        self.pump_until(lambda: picker._known and picker._active is None and picker._panorama_mode)
        page = picker.panorama
        old_state = page.state
        payload.pop('state')
        picker.refresh()
        self.pump_until(lambda: picker._active is None)
        self.assertIs(page.state, old_state)
        self.assertFalse(picker._known)
        self.assertEqual(picker.candidates, set())
        self.assertIn('資料已過期', page.status.get())
        self.assertEqual(str(picker.use_button.cget('state')), 'disabled')


class EmbeddedCandidateTests(unittest.TestCase):
    @staticmethod
    def payload():
        payload = BuildPickerTkTests.raw_payload()
        payload['game_key'] = 'game-a'
        payload['state']['capture_end'] = datetime.now(timezone.utc).isoformat()
        payload['state']['terrain_grid'] = {'width': 101, 'height': 202, 'types': bytes([2]*101*202).hex()}
        payload['state']['entities']['cities_and_barriers'].extend([
            {'type': 'city', 'city_id': 9, 'name': '黃縣', 'owner_raw': 3, 'world_xy_raw': [54, 100],
             'city_art_variant_flag': 0, 'defense': [100, 100]},
            {'type': 'city', 'city_id': 10, 'name': '敵城', 'owner_raw': 4, 'world_xy_raw': [75, 100],
             'city_art_variant_flag': 0, 'defense': [100, 100]},
        ])
        return payload

    def test_one_snapshot_all_owned_cities_and_stable_nearest_city(self):
        payload = self.payload()
        result = construction_candidates(payload['state'], 3)
        self.assertTrue(result['ok'])
        cells = result['cells']
        self.assertGreater(len(cells), 80)
        self.assertIn((46, 96), cells)
        self.assertIn((58, 104), cells)
        self.assertNotIn((75, 99), cells)  # No candidate from an enemy city.
        self.assertNotIn((50, 100), cells)
        self.assertNotIn((54, 100), cells)
        self.assertNotIn((50, 102), cells)  # Existing horse farm.
        self.assertEqual(cells[(52, 100)]['city_id'], 8)  # Equal distance: lower ID.
        self.assertEqual(cells[(53, 100)]['city_id'], 9)  # Closest city.
        payload['state']['entities']['cities_and_barriers'].reverse()
        reversed_result = construction_candidates(payload['state'], 3)
        self.assertEqual(reversed_result['cells'][(52, 100)]['city_id'], 8)

    def test_busy_and_non_type2_excluded_without_per_city_reader(self):
        payload = self.payload()
        raw = bytearray.fromhex(payload['state']['terrain_grid']['types'])
        raw[99*101+49] = 4
        payload['state']['terrain_grid']['types'] = raw.hex()
        result = construction_candidates(payload['state'], 3, busy=[(49, 100)])
        self.assertNotIn((49, 100), result['cells'])
        self.assertNotIn((49, 99), result['cells'])

    def test_compact_metadata_cannot_override_raw_city_ownership(self):
        payload = self.payload()
        misleading = [{'city_id': 10, 'name': '偽己方城', 'owner': 3, 'xy': [75, 100]}]
        result = construction_candidates(payload['state'], 3, misleading)
        self.assertNotIn((75, 99), result['cells'])
        self.assertEqual(result['cells'][(51, 100)]['owner'], 3)

    def test_unknown_grid_or_object_location_never_becomes_buildable(self):
        for defect in ('grid', 'object', 'missing'):
            state = self.payload()['state']
            if defect == 'grid':
                state['terrain_grid']['types'] = '02'
            elif defect == 'object':
                state['entities']['production_buildings'][0]['world_xy_raw'] = None
            else:
                state['entities'].pop('traps')
            result = construction_candidates(state, 3)
            self.assertFalse(result['ok'])
            self.assertEqual(result['cells'], {})

    def test_exact_global_hit_on_staggered_grid_and_boundaries(self):
        for xy in ((0, 0), (100, 201), (50, 100), (51, 101), (75, 52)):
            self.assertEqual(cell_at_pixel(*world_pixel(*xy)), xy)
        self.assertIsNone(cell_at_pixel(-100, -100))
        self.assertIsNone(cell_at_pixel(99999, 99999))


class EmbeddedMapTkTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped Tk display unavailable: %s' % exc)
        self.root.geometry('1200x780+3200+2000')
        self.errors, self.calls = [], []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.root.destroy)
        self.map = EmbeddedConstructionMap(self.root, self.callback)
        self.map.pack(fill='both', expand=True)
        self.payload = EmbeddedCandidateTests.payload()
        self.map.set_context('兵營', 3, [], self.payload)
        self.map.panorama.center, self.map.panorama.zoom = (52, 100), 3.0
        self.root.update()
        self.map.panorama.draw(refresh_view=False)
        self.assertTrue(self.map.canvas.winfo_ismapped())
        self.assertEqual(self.errors, [])

    def callback(self, city, x, y):
        self.calls.append((city['city_id'], x, y))
        return True

    def click(self, xy):
        from panorama_model import layer_for_zoom
        page = self.map.panorama
        x, y = page._project(*xy, page.canvas.winfo_width(), page.canvas.winfo_height(), layer_for_zoom(page.zoom))
        page.canvas.event_generate('<ButtonPress-1>', x=round(x), y=round(y))
        page.canvas.event_generate('<ButtonRelease-1>', x=round(x), y=round(y))
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_embedded_original_sprite_map_click_then_confirm_once_without_child_window(self):
        self.assertEqual([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)], [])
        sprites = [i for i in self.map.canvas.find_withtag('ov') if self.map.canvas.type(i) == 'image']
        self.assertGreaterEqual(len(sprites), 3)
        self.assertTrue(self.map.canvas.find_withtag('build-candidate'))
        self.assertTrue(all(self.map.canvas.itemcget(i, 'fill') == '' for i in self.map.canvas.find_withtag('build-candidate')))
        self.click((53, 100))
        self.assertEqual(self.map.selected, (53, 100))
        self.assertEqual(self.calls, [])
        self.map.confirm_button.invoke()
        self.map.confirm_button.invoke()
        self.assertEqual(self.calls, [(9, 53, 100)])
        self.assertIsNone(self.map.selected)
        self.assertNotIn((53, 100), self.map.candidates)
        self.assertEqual([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)], [])

    def test_success_reservation_survives_stale_busy_then_service_takes_over(self):
        self.click((51, 100))
        self.map.confirm_button.invoke()
        self.map.set_context('兵營', 3, [], self.payload, busy=[])
        self.assertNotIn((51, 100), self.map.candidates)
        self.map.set_context('兵營', 3, [], self.payload, busy=[(51, 100)])
        self.assertNotIn((51, 100), self.map.candidates)
        # The service has now observed the reservation; later cancellation
        # releases it without permanently hiding the cell in this UI.
        self.map.set_context('兵營', 3, [], self.payload, busy=[])
        self.assertIn((51, 100), self.map.candidates)

    def test_cancel_before_first_busy_poll_releases_only_on_newer_snapshot(self):
        self.click((51, 100))
        self.map.confirm_button.invoke()
        self.map.set_context('兵營', 3, [], self.payload, busy=[])
        self.assertNotIn((51, 100), self.map.candidates)
        newer = deepcopy(self.payload)
        newer['state']['snapshot_id'] = 'after-cancellation'
        newer['state']['capture_end'] = datetime.now(timezone.utc).isoformat()
        self.map.set_context('兵營', 3, [], newer, busy=[])
        self.assertIn((51, 100), self.map.candidates)

    def test_invalid_map_click_clears_previous_choice(self):
        self.click((51, 100))
        self.assertEqual(self.map.selected, (51, 100))
        self.click((50, 100))  # City is occupied, never a candidate.
        self.assertIsNone(self.map.selected)
        self.map.confirm_button.invoke()
        self.assertEqual(self.calls, [])

    def test_callback_failure_keeps_selection_and_reentrant_confirmation_is_blocked(self):
        def denied(city, x, y):
            self.calls.append((city['city_id'], x, y))
            self.assertFalse(self.map._confirm())
            return False
        self.map.on_select = denied
        self.click((51, 100))
        self.map.confirm_button.invoke()
        self.assertEqual(self.calls, [(8, 51, 100)])
        self.assertEqual(self.map.selected, (51, 100))
        self.assertIn((51, 100), self.map.candidates)
        self.assertEqual(str(self.map.confirm_button.cget('state')), 'normal')

    def test_same_context_refresh_keeps_camera_and_valid_choice_but_busy_invalidates(self):
        self.click((51, 100))
        page = self.map.panorama
        camera = page.center, page.zoom
        self.map.set_context('兵營', 3, [], deepcopy(self.payload))
        self.assertEqual((page.center, page.zoom), camera)
        self.assertEqual(self.map.selected, (51, 100))
        self.map.set_context('兵營', 3, [], self.payload, busy=[(51, 100)])
        self.assertIsNone(self.map.selected)
        self.assertEqual(str(self.map.confirm_button.cget('state')), 'disabled')

    def test_type_actor_and_game_change_clear_selection_mode_none_keeps_original_navigation(self):
        self.click((51, 100))
        self.map.set_context('馬房', 3, [], self.payload)
        self.assertIsNone(self.map.selected)
        self.click((51, 100))
        changed = deepcopy(self.payload)
        changed['game_key'] = 'game-b'
        self.map.set_context('馬房', 3, [], changed)
        self.assertIsNone(self.map.selected)
        self.map.set_context('馬房', 4, [], changed)
        self.assertIsNone(self.map.selected)
        self.assertIn((75, 99), self.map.candidates)
        page = self.map.panorama
        camera = page.center, page.zoom
        state = page.state
        self.map.set_context(None, 4, [], changed)
        self.assertEqual(self.map.candidates, {})
        self.assertEqual((page.center, page.zoom), camera)
        self.assertIsNotNone(page.state)
        self.assertEqual(self.map.canvas.find_withtag('build-candidate'), ())
        self.map.confirm_button.invoke()
        self.assertEqual(self.calls, [])

    def test_failed_full_state_keeps_map_but_unknown_or_expired_cannot_confirm(self):
        self.click((51, 100))
        state = self.map.panorama.state
        self.map.set_context('兵營', 3, [], {'ok': False, 'error': '離線'})
        self.assertIs(self.map.panorama.state, state)
        self.assertFalse(self.map._known)
        self.assertIsNone(self.map.selected)
        self.assertEqual(self.map.candidates, {})
        self.map.confirm_button.invoke()
        self.assertEqual(self.calls, [])
        self.map.set_context('兵營', 3, [], self.payload)
        self.click((51, 100))
        self.map._payload['state']['capture_end'] = '2000-01-01T00:00:00+00:00'
        self.assertFalse(self.map._confirm())
        self.assertIsNone(self.map.selected)
        self.assertEqual(str(self.map.confirm_button.cget('state')), 'disabled')
        self.assertEqual(self.calls, [])

    def test_short_embedded_map_reserves_confirmation_footer(self):
        self.root.geometry('1200x220+3200+2000')
        self.root.update()
        self.assertTrue(self.map.confirm_button.winfo_ismapped())
        self.assertGreater(self.map.canvas.winfo_height(), 100)
        footer_bottom = self.map.confirm_button.winfo_rooty()+self.map.confirm_button.winfo_height()
        self.assertLessEqual(footer_bottom, self.map.winfo_rooty()+self.map.winfo_height())
        self.assertEqual(self.errors, [])

    def test_original_camera_scroll_drag_and_bounded_height_remain_available(self):
        page, canvas = self.map.panorama, self.map.canvas
        self.assertEqual(int(canvas.cget('height')), 250)
        self.assertLessEqual(page.winfo_reqheight(), 320)
        old_zoom = page.zoom
        page._wheel_at = 0
        with mock.patch('map_navigation._pointer_root', return_value=None):
            canvas.event_generate('<MouseWheel>', delta=120, x=500, y=140)
            self.root.update()
        self.assertGreater(page.zoom, old_zoom)
        center = page.center
        canvas.event_generate('<ButtonPress-1>', x=500, y=140)
        canvas.event_generate('<B1-Motion>', x=540, y=160)
        canvas.event_generate('<ButtonRelease-1>', x=540, y=160)
        self.root.update()
        self.assertNotEqual(page.center, center)
        self.assertIsNone(self.map.selected)
        self.click((51, 100))
        self.assertEqual(self.map.selected, (51, 100))
        self.assertEqual(self.calls, [])
        self.assertEqual((canvas.canvasx(0), canvas.canvasy(0)), (0, 0))


if __name__ == '__main__':
    unittest.main()
