"""Mapped command UI; all services are fakes and no game input can be sent."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]
from command_panel import CommandPanel
GAME_KEY = 'mapped-command-panel-current-game'


def snapshot():
    data = {'ok': True, 'game_key': GAME_KEY, 'phase': 1, 'phase_text': '內政（可送）',
            'targets': [{'prefix': 'prefix-fengye-shadow', 'alive': True, 'pid': 360}],
            'forces': [
                {'force_id': 3, 'name': '齊', 'gold': 37022,
                 'armament': {'infantry': 10, 'cavalry': 20, 'bow': 30}},
                {'force_id': 4, 'name': '巴', 'gold': 28840,
                 'armament': {'infantry': 15, 'cavalry': 25, 'bow': 35}}],
            'player_slots': [{'force_id': 3, 'nickname': '風雲'},
                             {'force_id': 4, 'nickname': '丁滿'}],
            'cities': [{'city_id': 12, 'name': '臨淄', 'owner': 3, 'xy': [50, 100]},
                       {'city_id': 13, 'name': '黃縣', 'owner': 3, 'xy': [75, 52]},
                       {'city_id': 14, 'name': '江州', 'owner': 4, 'xy': [20, 150]}]}
    raw = {'readonly': True, 'capture_end': datetime.now(timezone.utc).isoformat(),
           'terrain_grid': {'width': 101, 'height': 202, 'types': '02'*(101*202)},
           'entities': {'lords': copy.deepcopy(data['forces']), 'generals': [],
                        'field_units': [], 'traps': [], 'production_buildings': [],
                        'cities_and_barriers': [dict(c, type='city', owner_raw=c['owner'],
                                                     world_xy_raw=c['xy'])
                                               for c in data['cities']]}}
    data['_battle_payload'] = {'ok': True, 'source_prefix': 'prefix-fengye-shadow',
                               'game_key': GAME_KEY, 'state': raw,
                               'captured_at': raw['capture_end']}
    data['_busy_cells'] = []
    return data


class FakeService:
    def __init__(self):
        self.data = snapshot()
        self.jobs = []
        self.submitted = []
        self.cancelled = []
        self.read_threads = []
        self.read_gate = None
        self.read_started = threading.Event()
        self.site_reads = []
        self.current_key = GAME_KEY

    def jobs_view(self):
        return {'ok': True, 'jobs': copy.deepcopy(self.jobs),
                'current_game_key': self.current_key,
                'current_jobs': copy.deepcopy(self.jobs)}

    def submit(self, payload, info=None, execute=True):
        self.submitted.append((copy.deepcopy(payload), info, execute))
        job = {'id': 'job-%d' % (len(self.jobs)+1), 'created': time.time(),
               'game_key': GAME_KEY,
               'actor_label': payload.get('actor_label'), 'preset': payload['preset'],
               'params': dict(payload), 'city_name': payload.get('city_name'),
               'status': 'pending', 'events': [], 'note': '已排隊'}
        self.jobs.append(job)
        return {'ok': True, 'job': copy.deepcopy(job)}

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        job = next(row for row in self.jobs if row['id'] == job_id)
        job['status'] = 'cancelled'
        return {'ok': True, 'job': copy.deepcopy(job)}

    def targets(self, refresh=False):
        self.read_threads.append((threading.get_ident(), refresh))
        self.read_started.set()
        if self.read_gate:
            self.read_gate.wait(3)
        return copy.deepcopy(self.data)

    def build_sites(self, prefix, xy, actor):
        self.site_reads.append((prefix, list(xy), actor, threading.get_ident()))
        return {'ok': True, 'cells': [[51, 100], [52, 101], [49, 100], [50, 101]],
                'occupied': {(49, 100): 'building'}, 'busy': [[50, 101]]}

    def battlefield(self):
        return copy.deepcopy(self.data['_battle_payload'])

    def busy_build_cells(self):
        return set()


class CommandPanelMappedTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped Tk display unavailable: %s' % exc)
        self.root.geometry('1300x850+3200+2000')
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.service = FakeService()
        self.observed = []
        self.panel = CommandPanel(self.root, self.service, on_snapshot=self.observed.append,
                                  autostart=False)
        self.panel.pack(fill='both', expand=True)
        self.root.update()
        self.assertTrue(self.panel.winfo_ismapped())
        self.addCleanup(self.cleanup)
        self.panel._apply_snapshot(snapshot())
        self.root.update()

    def cleanup(self):
        if self.service.read_gate:
            self.service.read_gate.set()
        self.panel.destroy()
        self.root.destroy()

    def until(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertTrue(predicate())
        self.assertEqual(self.errors, [])

    def test_seven_direct_action_buttons_and_no_command_dropdown(self):
        self.assertEqual([b.cget('text') for b in self.panel.train_buttons.values()],
                         ['步兵', '騎兵', '弓兵'])
        self.assertEqual([b.cget('text') for b in self.panel.build_buttons.values()],
                         ['兵營', '馬房', '弓房', '陷阱'])
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        # The shared renderer retains its hidden opponent model widgets;
        # only the actual visible UI may contain the force dropdown.
        combos = [w for w in descendants(self.panel)
                  if isinstance(w, ttk.Combobox) and w.winfo_ismapped()]
        self.assertEqual(combos, [self.panel.force_box])
        city_names = {'臨淄', '黃縣', '江州'}
        buttons = [w for w in descendants(self.panel) if isinstance(w, (tk.Button, ttk.Button))]
        self.assertFalse(any(str(w.cget('text')).lstrip('● ') in city_names for w in buttons))
        self.assertTrue(self.panel.map_view.canvas.winfo_ismapped())
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in descendants(self.panel)))

    def test_building_expands_map_and_queued_action_reopens_visible_timeline(self):
        self.root.geometry('1280x650+3200+2000')
        self.root.update()
        before = self.panel.map_view.canvas.winfo_height()
        self.panel.build_buttons[6].invoke()
        self.root.update()
        self.assertFalse(self.panel.tabs.winfo_ismapped())
        self.assertTrue(self.panel.map_view.confirm_button.winfo_ismapped())
        self.assertGreater(self.panel.map_view.canvas.winfo_height(), before+100)
        self.assertEqual(self.service.submitted, [])
        self.panel.train_buttons[0].invoke()
        self.root.update()
        self.assertTrue(self.panel.tabs.winfo_ismapped())
        self.assertTrue(self.panel.tables['active'].bbox('job-1'))
        self.assertTrue(self.panel.details.winfo_ismapped())

    def test_training_click_immediately_creates_one_canonical_active_row(self):
        started = time.monotonic()
        self.panel.train_buttons[1].invoke()
        # No Tk polling step is needed for the queue row to become visible.
        self.assertLess(time.monotonic()-started, .5)
        self.assertEqual(len(self.service.submitted), 1)
        payload, info, execute = self.service.submitted[0]
        self.assertEqual((payload['preset'], payload['troop'], payload['actor']), ('train', 1, 3))
        self.assertEqual(payload['prefix'], 'prefix-fengye-shadow')
        self.assertIs(info, self.panel.snapshot)
        self.assertTrue(execute)
        self.assertEqual(self.panel.tables['active'].get_children(), ('job-1',))
        self.assertEqual(self.panel.tables['completed'].get_children(), ())
        self.assertIn('已排隊', self.panel.tables['active'].item('job-1', 'values'))
        self.assertIn('風雲・齊', self.panel.tables['active'].item('job-1', 'values'))
        for button in (*self.panel.train_buttons.values(), *self.panel.build_buttons.values()):
            self.assertNotIn('disabled', button.state())
        self.panel.train_buttons[0].invoke()
        self.assertEqual(len(self.service.submitted), 2)
        self.assertEqual(len(self.panel.tables['active'].get_children()), 2)

    def test_laptop_layout_keeps_map_queue_details_and_confirmation_inside_panel(self):
        # A 1280x928 main window leaves about 650 px after the application
        # header. Test that actual remaining area, not the root's larger size.
        self.root.geometry('1280x650+3200+2000')
        self.panel.train_buttons[0].invoke()
        self.panel.build_buttons[7].invoke()
        self.panel.queue_toggle.invoke()  # Both map and timeline explicitly open.
        self.until(lambda: bool(self.panel.map_view.candidates))
        self.root.update_idletasks()
        self.root.update()
        self.assertEqual(self.panel.winfo_height(), 650)
        canvas = self.panel.map_view.canvas
        self.assertGreater(canvas.winfo_height(), 100)
        for widget in (canvas, self.panel.tables['active'], self.panel.details,
                       self.panel.map_view.confirm_button):
            with self.subTest(widget=str(widget)):
                top = widget.winfo_rooty()-self.panel.winfo_rooty()
                bottom = top+widget.winfo_height()
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(bottom, self.panel.winfo_height(),
                                     'visible bottom %s exceeds panel height %s' %
                                     (bottom, self.panel.winfo_height()))
        self.assertTrue(self.panel.tables['active'].bbox('job-1'))

    def test_embedded_map_requires_diamond_then_confirmation_before_enqueue(self):
        self.panel.build_buttons[8].invoke()
        picker = self.panel.map_view
        self.until(lambda: bool(picker.candidates) and picker.canvas.winfo_ismapped())
        self.assertIsNone(picker.selected)
        self.assertEqual(self.service.submitted, [])
        self.assertIn('disabled', picker.confirm_button.state())
        self.assertIn((51, 100), picker.candidates)
        self.assertIn((76, 52), picker.candidates)
        self.assertNotIn((21, 150), picker.candidates)  # Other faction's city.
        page = picker.panorama
        page.center, page.zoom = (50, 100), 3.0
        page.draw()
        sx, sy = page._project(51, 100, picker.canvas.winfo_width(),
                               picker.canvas.winfo_height(), 'mbm')
        picker.canvas.event_generate('<ButtonPress-1>', x=round(sx), y=round(sy))
        picker.canvas.event_generate('<ButtonRelease-1>', x=round(sx), y=round(sy))
        self.root.update()
        self.assertEqual(picker.selected, (51, 100))
        self.assertEqual(self.service.submitted, [])
        picker.confirm_button.invoke()
        self.assertEqual(len(self.service.submitted), 1)
        payload = self.service.submitted[0][0]
        self.assertEqual({k: payload[k] for k in ('preset', 'city', 'build_type', 'x', 'y')},
                         {'preset': 'build', 'city': 12, 'build_type': 8, 'x': 51, 'y': 100})
        self.assertEqual(self.panel.tables['active'].get_children(), ('job-1',))
        row = self.panel.tables['active'].item('job-1', 'values')
        self.assertEqual(row[1], '風雲・齊')
        self.assertIn('馬房 · 臨淄 (51,100)', row[2])
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))

    def test_build_button_highlights_all_owned_cities_without_auto_selection(self):
        self.panel.build_buttons[7].invoke()
        picker = self.panel.map_view
        self.until(lambda: bool(picker.candidates))
        self.assertEqual({city['city_id'] for city in picker.candidates.values()}, {12, 13})
        self.assertIsNone(picker.selected)
        self.assertEqual(self.service.submitted, [])
        self.panel.force_box.current(1)
        self.panel.force_box.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.until(lambda: {city['city_id'] for city in picker.candidates.values()} == {14})
        self.assertIsNone(picker.selected)

    def test_cancel_selected_moves_the_same_row_to_other(self):
        self.panel.train_buttons[0].invoke()
        self.panel.tables['active'].selection_set('job-1')
        self.panel._show_detail()
        self.panel.cancel_button.invoke()
        self.assertEqual(self.service.cancelled, ['job-1'])
        self.assertEqual(self.panel.tables['active'].get_children(), ())
        self.assertEqual(self.panel.tables['other'].get_children(), ('job-1',))
        self.assertEqual(self.panel.tables['completed'].get_children(), ())

    def test_only_verified_completed_status_is_shown_on_completed_page(self):
        for index, status in enumerate(('fired', 'verifying', 'completed', 'unknown', 'restoring')):
            self.service.jobs.append({'id': 'job-%s' % index, 'created': time.time(),
                                      'game_key': GAME_KEY,
                                      'preset': 'train', 'params': {'troop': 0},
                                      'status': status, 'events': []})
        self.panel.render_jobs()
        self.assertEqual(self.panel.tables['completed'].get_children(), ('job-2',))
        self.assertEqual(set(self.panel.tables['active'].get_children()),
                         {'job-0', 'job-1', 'job-3', 'job-4'})

    def test_legacy_missing_and_other_game_jobs_are_absent_from_all_tabs(self):
        self.panel.train_buttons[0].invoke()
        template = self.service.jobs[0]
        for index, change in enumerate(({'game_key': None}, {'game_key': 'other-game'},
                                        {'legacy': True}, {'status': 'legacy_completed'})):
            self.service.jobs.append(dict(copy.deepcopy(template), id='hidden-%d' % index, **change))
        self.panel.render_jobs()
        self.assertEqual(self.panel.tables['active'].get_children(), ('job-1',))
        self.assertEqual(self.panel.tables['completed'].get_children(), ())
        self.assertEqual(self.panel.tables['other'].get_children(), ())
        self.service.current_key = None
        self.panel.render_jobs()
        self.assertTrue(all(not tree.get_children() for tree in self.panel.tables.values()))

    def test_selected_current_job_only_moves_to_completed_after_actual_completion(self):
        self.panel.train_buttons[0].invoke()
        active = self.panel.tables['active']
        active.selection_set('job-1')
        for status in ('waiting_phase', 'fired', 'verifying'):
            self.service.jobs[0]['status'] = status
            self.panel.render_jobs()
            self.assertEqual(active.get_children(), ('job-1',))
            self.assertEqual(active.selection(), ('job-1',))
            self.assertEqual(self.panel.tables['completed'].get_children(), ())
            self.assertIn('disabled', self.panel.cancel_button.state())
        self.service.jobs[0]['status'] = 'completed'
        self.panel.render_jobs()
        self.assertEqual(active.get_children(), ())
        self.assertEqual(self.panel.tables['completed'].get_children(), ('job-1',))
        self.assertEqual(self.panel.tables['other'].get_children(), ())
        self.root.update()
        details = self.panel.details.get('1.0', 'end-1c')
        self.assertIn('風雲・齊', details)
        self.assertIn('已完成', details)
        self.assertTrue(self.panel.details.winfo_ismapped())

    def test_refresh_is_singleflight_background_and_preserves_selected_force(self):
        self.panel.force_box.current(1)
        self.panel.force_box.event_generate('<<ComboboxSelected>>')
        self.service.read_gate = threading.Event()
        try:
            self.assertTrue(self.panel.refresh())
            for _ in range(4):
                self.assertFalse(self.panel.refresh())
            self.until(self.service.read_started.is_set)
            self.assertEqual(len(self.service.read_threads), 1)
            self.assertNotEqual(self.service.read_threads[0][0], threading.get_ident())
            marker = []
            self.root.after(10, lambda: marker.append(True))
            self.until(lambda: bool(marker))
        finally:
            self.service.read_gate.set()
        self.until(lambda: not self.panel._busy)
        self.assertEqual(self.panel.selected_force()['force_id'], 4)
        self.assertEqual(self.observed[-1]['forces'][1]['force_id'], 4)

    def test_automatic_reads_continue_with_adjustable_interval(self):
        self.panel.refresh_seconds = .05
        self.panel._auto = True
        self.until(lambda: len(self.service.read_threads) >= 2)
        self.panel._auto = False
        self.assertTrue(all(refresh for _tid, refresh in self.service.read_threads))

    def test_unknown_values_are_never_rendered_as_literal_none_or_live_numbers(self):
        data = snapshot()
        data['forces'][0].update(gold=None, armament={'infantry': None, 'cavalry': None, 'bow': None})
        data['phase'] = None
        data['phase_text'] = None
        self.panel._apply_snapshot(data)
        values = self.panel.values.cget('text')
        live = self.panel.live.cget('text')
        self.assertNotIn('None', values)
        self.assertNotIn('None', live)
        self.assertTrue('未知' in values or '—' in values)


if __name__ == '__main__':
    unittest.main()
