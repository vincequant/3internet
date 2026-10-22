import copy
import io
import json
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from officer_report import own_city_reports
from officer_roster import (
    OfficerRoster, OWNED_COLUMNS, POLITICS_COLUMNS, ReportSource, WILD_COLUMNS,
)
from quick_control_model import BUILD, binding, filter_roster


def officer(gid, city, name, lead, war, pol=40, status=1, owner=65535):
    return {
        'general_id_raw': gid, 'name': name, 'status_code': status, 'owner_raw': owner,
        'location_city_id': city,
        'attributes': {'lead': lead, 'war': war, 'intel': 40, 'pol': pol, 'cha': 40},
    }


def payload(pid, source):
    return {
        'source_id': source,
        'identity': {'pid': pid, 'creation_filetime': 11, 'path': r'C:\game\SANPK.exe'},
        'state': {
            'core_address': '0x100000', 'build_sha256': BUILD,
            'capture_end': datetime.now(timezone.utc).isoformat(),
            'player_force_id': 1,
            'player_identity': {'status': 'confirmed', 'force_id': 1},
            'entities': {
                'lords': [{'force_id': 1, 'name': '我'}, {'force_id': 2, 'name': '敌'}],
                'cities_and_barriers': [], 'generals': [],
            },
        },
    }


def match_a():
    doc = payload(10, 'match-a')
    doc['state']['entities']['cities_and_barriers'] = [
        {'city_id': 1, 'name': '晋阳', 'type': 'city', 'owner_raw': 1},
        {'city_id': 2, 'name': '建业', 'type': 'city', 'owner_raw': 2},
        {'city_id': 3, 'name': '武关', 'type': 'barrier', 'owner_raw': 1},
        {'city_id': 8, 'name': '北平', 'type': 'city', 'owner_raw': 1},
    ]
    doc['state']['entities']['generals'] = [
        officer(1, 1, '乐进', 100, 91, pol=120),
        officer(2, 1, '张燕', 95, 85),
        officer(3, 1, '刚好', 90, 80),
        officer(4, 1, '平常', 80, 80),
        officer(5, 1, '小将', 50, 40),
        officer(6, 1, '曹操', 90, 90, pol=80, status=0, owner=1),
        officer(7, 2, '敌将', 100, 100),
        officer(8, 3, '关将', 100, 100),
        officer(9, 8, '高顺', 120, 90),
        officer(10, 8, '弱将', 40, 40),
    ]
    return doc


def match_b():
    doc = payload(81, 'match-b')
    doc['state']['entities']['cities_and_barriers'] = [
        {'city_id': 5, 'name': '成都', 'type': 'city', 'owner_raw': 1},
    ]
    doc['state']['entities']['generals'] = [
        officer(21, 5, '赵云', 100, 90),
        officer(22, 5, '小兵', 40, 40),
    ]
    return doc


class BoundPanel:
    def __init__(self, root):
        import tkinter as tk
        self.root = root
        self.ready = False
        self.bound = None
        self.current_state = {}
        self.pending_targets = {}
        self.busy = False
        self.selecting = False
        self.note = tk.StringVar(master=root)
        self.recruit_calls = []

    def recruit_officer(self, row):
        self.recruit_calls.append(row)


def report_lines(view):
    lines = []
    for row in view.rows.winfo_children():
        for child in row.winfo_children():
            if child.winfo_class() == 'Label':
                lines.append(child.cget('text'))
    return lines


def copy_buttons(view):
    buttons = []
    for row in view.rows.winfo_children():
        for child in row.winfo_children():
            if child.winfo_class() == 'Button':
                buttons.append(child)
    return buttons


def arm(ui):
    for name in ('poll_id', 'auto_id'):
        token = getattr(ui, name, None)
        if token:
            ui.window.after_cancel(token)
            setattr(ui, name, None)


def step(ui, root):
    arm(ui)
    ui.poll()
    root.update()
    arm(ui)


def settle(ui, root, timeout=2):
    end = time.time() + timeout
    while time.time() < end:
        step(ui, root)
        if not ui.loading and ui.results.empty():
            return True
        time.sleep(0.01)
    return False


class ReportSourceTests(unittest.TestCase):
    def test_publish_keeps_only_a_matching_binding(self):
        first, second = match_a(), match_b()
        source = ReportSource()
        source.publish(first, binding(first))
        self.assertEqual(source.doc['entities']['cities_and_barriers'][0]['name'], '晋阳')
        with self.assertRaises(ValueError):
            source.publish(first, binding(second))
        self.assertEqual(source.doc['entities']['cities_and_barriers'][0]['name'], '晋阳')
        source.publish(second, binding(second))
        self.assertEqual(source.doc['entities']['cities_and_barriers'][0]['name'], '成都')
        source.clear()
        self.assertIsNone(source.doc)
        self.assertIsNone(source.bound)

    def test_roster_blade_cutoff_stays_strictly_above(self):
        rows = [
            {'id': 1, 'name': '刚好', 'city': '晋阳', 'blade': 170, 'politics': 40, 'skills_matched': False},
            {'id': 2, 'name': '乐进', 'city': '晋阳', 'blade': 171, 'politics': 40, 'skills_matched': False},
        ]
        self.assertEqual([row['name'] for row in filter_roster(rows, min_blade=170)], ['乐进'])
        self.assertEqual([row['name'] for row in filter_roster(rows, min_blade=None)], ['乐进', '刚好'])


class RosterReportUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.panel = BoundPanel(self.root)
        self.holder = {'event': None, 'payload': match_a(), 'opens': 0}
        def open_url(url, timeout=8):
            self.holder['opens'] += 1
            event = self.holder['event']
            if event is not None and not event.is_set():
                if not event.wait(3):
                    raise TimeoutError('held')
            body = copy.deepcopy(self.holder['payload'])
            body['state']['capture_end'] = datetime.now(timezone.utc).isoformat()
            return io.BytesIO(json.dumps(body).encode())
        self.open_url = open_url
        self.url_patch = patch('urllib.request.urlopen', side_effect=open_url)
        self.url_patch.start()
        self.ui = OfficerRoster(self.panel, 'http://invalid')
        arm(self.ui)

    def tearDown(self):
        event = self.holder.get('event')
        if event is not None:
            event.set()
        if hasattr(self, 'ui'):
            try:
                arm(self.ui)
                self.ui.close()
            except Exception:
                pass
        if hasattr(self, 'url_patch'):
            self.url_patch.stop()
        if hasattr(self, 'root'):
            self.root.destroy()

    def load(self, doc, bound=None):
        self.holder['event'] = None
        self.holder['payload'] = doc
        self.panel.ready = True
        self.panel.bound = binding(doc) if bound is None else bound
        self.ui.refresh()
        self.assertTrue(settle(self.ui, self.root), 'roster read did not settle')

    def test_four_modes_report_format_copy_and_blade_default(self):
        ui, root, panel = self.ui, self.root, self.panel
        labels = [child.cget('text') for child in ui.modes.winfo_children() if child.winfo_class() == 'TRadiobutton']
        self.assertEqual(labels, ['统武名册', '政治名册', '智力名册', '本营将领名册', '本城报将'])
        self.assertEqual(ui.min_blade.get(), '170')
        self.assertIsInstance(ui.report_view.app, ReportSource)
        self.load(match_a())
        ui.mode.set('report')
        ui.change_mode()
        root.update()
        expected = own_city_reports(ui.report_source.doc)
        self.assertEqual(expected, ['晋阳 乐进 张燕  2/5', '北平 高顺  1/2'])
        self.assertEqual(report_lines(ui.report_view), expected)
        self.assertNotIn('建业', '\n'.join(expected))
        self.assertNotIn('武关', '\n'.join(expected))
        self.assertNotIn('曹操', '\n'.join(expected))
        self.assertNotIn('敌将', '\n'.join(expected))
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'normal')
        self.assertEqual(ui.table.winfo_manager(), '')
        self.assertEqual(ui.bar.winfo_manager(), '')
        self.assertEqual(ui.recruit_button.winfo_manager(), '')
        self.assertEqual(ui.skills.winfo_manager(), '')
        self.assertEqual(ui.report_view.winfo_manager(), 'pack')
        buttons = copy_buttons(ui.report_view)
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0].cget('text'), '复制')
        calls = []
        def fake_run(argv, input=None, check=False, **kwargs):
            calls.append(('run', tuple(argv), input))
            return Mock(returncode=0)
        def fake_wine(script, text, timeout):
            calls.append(('wine', script, text, timeout))
            return True, 'ok'
        line = '晋阳 乐进 张燕  2/5'
        body = '晋阳 乐进 张燕  2/5\n北平 高顺  1/2'
        class ImmediateThread:
            def __init__(self, target, daemon=None):
                self._target = target
            def start(self):
                self._target()
        with patch('officer_report.subprocess.run', side_effect=fake_run), \
             patch('officer_report.wine_text', side_effect=fake_wine), \
             patch('officer_report.threading.Thread', ImmediateThread):
            buttons[0].invoke()
            ui.report_view.copy_report()
            root.update()
        wines = [item for item in calls if item[0] == 'wine']
        self.assertEqual(wines, [
            ('wine', 'win_clipboard_once.py', line, 15),
            ('wine', 'win_clipboard_once.py', body, 15),
        ])
        if sys.platform == 'darwin':
            runs = [item for item in calls if item[0] == 'run']
            self.assertEqual(runs, [('run', ('pbcopy',), line.encode()), ('run', ('pbcopy',), body.encode())])
        self.assertIn('已复制', ui.report_view.note.cget('text'))
        self.assertEqual(panel.recruit_calls, [])
        ui.recruit()
        self.assertEqual(panel.recruit_calls, [])
        ui.report_view.blade_floor.set('169')
        self.assertEqual(report_lines(ui.report_view)[0], '晋阳 乐进 张燕 刚好  3/5')
        ui.report_view.blade_floor.set('')
        self.assertTrue(report_lines(ui.report_view)[0].endswith('  5/5'))
        self.assertIn('刚好', report_lines(ui.report_view)[0])
        ui.report_view.blade_floor.set('甲')
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        ui.report_view.blade_floor.set('170')
        self.assertEqual(report_lines(ui.report_view), expected)
        ui.mode.set('blade')
        ui.change_mode()
        root.update()
        self.assertEqual(ui.report_view.winfo_manager(), '')
        self.assertEqual(ui.table.winfo_manager(), 'pack')
        self.assertEqual(ui.recruit_button.winfo_manager(), 'pack')
        self.assertEqual(ui.blade_controls.winfo_manager(), 'pack')
        self.assertEqual(tuple(ui.tree['displaycolumns']), WILD_COLUMNS)
        self.assertEqual(ui.sort.get(), '统武从高到低')
        self.assertIn(170, [row['blade'] for row in ui.rows])
        self.assertEqual({row['name'] for row in ui.visible.values()}, {'乐进', '张燕', '高顺', '敌将'})
        self.assertTrue(all(row['blade'] > 170 for row in ui.visible.values()))
        ui.min_blade.set('500')
        ui.mode.set('politics')
        ui.change_mode()
        root.update()
        self.assertEqual(tuple(ui.tree['displaycolumns']), POLITICS_COLUMNS)
        self.assertEqual(ui.politics_controls.winfo_manager(), 'pack')
        self.assertEqual(ui.blade_controls.winfo_manager(), '')
        self.assertEqual(ui.skill_controls.winfo_manager(), '')
        self.assertNotIn('统武从高到低', ui.sort_choice['values'])
        self.assertEqual({row['name'] for row in ui.visible.values()}, {'乐进'})
        ui.min_blade.set('170')
        ui.mode.set('owned')
        ui.change_mode()
        root.update()
        self.assertEqual(tuple(ui.tree['displaycolumns']), OWNED_COLUMNS)
        self.assertEqual({row['name'] for row in ui.visible.values()}, {'曹操'})
        self.assertEqual(ui.recruit_button.winfo_manager(), '')
        self.assertEqual(ui.minimum_choice.winfo_manager(), '')
        ui.tree.selection_set('6')
        ui.recruit()
        self.assertEqual(panel.recruit_calls, [])
        self.assertEqual(str(ui.recruit_button['state']), 'disabled')
        ui.mode.set('blade')
        ui.change_mode()
        root.update()
        self.assertEqual(ui.recruit_button.winfo_manager(), 'pack')
        self.assertEqual(ui.skill_controls.winfo_manager(), 'pack')
        self.assertEqual(tuple(ui.tree['displaycolumns']), WILD_COLUMNS)

    def test_stale_ticket_keeps_latest_request_and_then_publishes(self):
        ui, root, panel = self.ui, self.root, self.panel
        first = match_a()
        held = threading.Event()
        self.holder['event'] = held
        self.holder['payload'] = first
        panel.ready = True
        panel.bound = binding(first)
        ui.mode.set('report')
        ui.change_mode()
        ui.refresh()
        waited = time.time() + 2
        while time.time() < waited and self.holder['opens'] < 1:
            time.sleep(0.01)
        self.assertTrue(ui.loading)
        current = ui.ticket
        self.assertEqual(self.holder['opens'], 1)
        ui.results.put((current - 1, panel.bound, [], None, [], '', first))
        step(ui, root)
        time.sleep(0.05)
        self.assertEqual(ui.ticket, current)
        self.assertTrue(ui.loading)
        self.assertEqual(self.holder['opens'], 1)
        self.assertIsNone(ui.report_source.doc)
        self.assertTrue(ui.results.empty())
        held.set()
        self.assertTrue(settle(ui, root))
        self.assertEqual(ui.ticket, current)
        self.assertFalse(ui.loading)
        self.assertEqual(self.holder['opens'], 1)
        self.assertEqual(report_lines(ui.report_view), ['晋阳 乐进 张燕  2/5', '北平 高顺  1/2'])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'normal')
        panel.ready = False
        step(ui, root)
        self.assertIsNone(ui.report_source.doc)
        self.assertNotEqual(ui.ticket, current)
        ui.results.put((current, binding(first), [], None, [], '', first))
        step(ui, root)
        self.assertIsNone(ui.report_source.doc)
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        self.assertFalse(ui.loading)

    def test_disconnect_rebind_and_late_result_cannot_restore_report(self):
        ui, root, panel = self.ui, self.root, self.panel
        first = match_a()
        self.load(first)
        ui.mode.set('report')
        ui.change_mode()
        self.assertEqual(report_lines(ui.report_view)[0], '晋阳 乐进 张燕  2/5')
        old_ticket = ui.ticket
        panel.ready = False
        step(ui, root)
        self.assertIsNone(ui.report_source.doc)
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        ui.results.put((old_ticket, binding(first), [], None, [], '', first))
        ui.results.put((ui.ticket, binding(first), [], None, [], '', first))
        step(ui, root)
        step(ui, root)
        self.assertIsNone(ui.report_source.doc)
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        self.load(first)
        self.assertEqual(report_lines(ui.report_view)[0], '晋阳 乐进 张燕  2/5')
        held = threading.Event()
        self.holder['event'] = held
        self.holder['payload'] = first
        ui.refresh()
        self.assertTrue(ui.loading)
        panel.bound = binding(match_b())
        step(ui, root)
        self.assertIsNone(ui.report_source.doc)
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        held.set()
        self.assertTrue(settle(ui, root))
        self.assertIsNone(ui.report_source.doc)
        self.assertFalse(any('晋阳' in line for line in report_lines(ui.report_view)))
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')
        second = match_b()
        self.load(second)
        self.assertEqual(report_lines(ui.report_view), ['成都 赵云  1/2'])
        self.assertNotIn('晋阳', json.dumps(ui.report_source.doc, ensure_ascii=False))
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'normal')

    def test_unknown_probability_still_reports_and_bad_binding_clears(self):
        ui, root = self.ui, self.root
        with patch('officer_roster.probability_roster', side_effect=ValueError('概率未知')):
            self.load(match_a())
        ui.mode.set('report')
        ui.change_mode()
        self.assertEqual(ui.rows, [])
        self.assertEqual(report_lines(ui.report_view), ['晋阳 乐进 张燕  2/5', '北平 高顺  1/2'])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'normal')
        self.assertIn('概率未知', ui.note.get())
        rejected = match_a()
        rejected['state']['build_sha256'] = 'unknown-build'
        self.holder['payload'] = rejected
        ui.refresh()
        self.assertTrue(settle(ui, root))
        self.assertIsNone(ui.report_source.doc)
        self.assertEqual(report_lines(ui.report_view), [])
        self.assertEqual(str(ui.report_view.copy_btn['state']), 'disabled')


if __name__ == '__main__':
    unittest.main()
