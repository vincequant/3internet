import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from city_talent import COLS, WILD_COLS, blade_order_label, city_five_averages, city_for_officer, city_wild_officers, format_five_avg, lead_war_total, meets_floor, number_floor, passes_city_filters, summarize, SKILL_COLS
from omni_window import OmniWindow


def officer(gid, city_id, name='甲', status=1, owner=65535, **attrs):
    return {
        'general_id_raw': gid, 'name': name, 'status_code': status, 'owner_raw': owner,
        'location_city_id': city_id, 'attributes': {'lead': 80, 'war': 80, 'intel': 80, 'pol': 80, 'cha': 80, **attrs},
    }


class CityTalentTests(unittest.TestCase):
    def test_city_for_officer_skips_barriers(self):
        state = {'entities': {'cities_and_barriers': [
            {'city_id': 1, 'name': '陈留', 'type': 'city'},
            {'city_id': 2, 'name': '武关', 'type': 'barrier'},
        ]}}
        self.assertEqual(city_for_officer(state, officer(9, 1))['name'], '陈留')
        self.assertIsNone(city_for_officer(state, officer(8, 2)))
        self.assertIsNone(city_for_officer(state, officer(7, None)))

    def test_city_wild_lists_same_city_only(self):
        city = {'city_id': 1, 'name': '陈留', 'type': 'city'}
        state = {'entities': {
            'cities_and_barriers': [city],
            'generals': [
                officer(1, 1, '孙尚香'),
                officer(2, 1, '黄月英', war=94),
                officer(3, 9, '别人'),
                officer(4, 1, '已仕', status=0, owner=3),
            ],
        }}
        names = [row['name'] for row in city_wild_officers(state, city)]
        self.assertEqual(names, ['黄月英', '孙尚香'])

    def test_city_avg_uses_known_five_and_drops_unknown_column(self):
        keys = [key for key, _title, _width in COLS]
        self.assertEqual(keys, ['name', 'owner', 'total', 'ride', 'bow', 'navy', 'ambush', 'blade', 'blade_avg', 'pol', 'blades'])
        self.assertNotIn('thunder', keys)
        self.assertEqual([key for key, _title, _width in WILD_COLS],
                         ['name', 'id', 'blade', 'pol', 'threshold', 'chance'])
        self.assertEqual(lead_war_total(officer(1, 1, lead=115, war=70)), 185)
        self.assertIsNone(lead_war_total(officer(1, 1, war=None)))
        self.assertEqual([title for _key, title, _width in SKILL_COLS], ['骑', '弓', '水', '埋伏'])
        self.assertNotIn('n450', keys)
        self.assertNotIn('unknown', keys)
        source = (Path(__file__).resolve().parents[1] / 'app' / 'city_talent.py').read_text(encoding='utf-8')
        self.assertIn("bind('<Double-1>',self.locate)", source)
        self.assertNotIn("bind('<ButtonRelease-1>',self.locate)", source)
        self.assertIn('prefer_world=True', source)
        self.assertNotIn('show_city_wild=True', source)
        self.assertIn('双击城池打开全图定位', source)
        self.assertIn('identify_row', source)
        self.assertIn('identify_region', source)
        self.assertNotIn("bind('<<TreeviewSelect>>',self.locate)", source)
        self.assertNotIn('>450人数', source)
        self.assertNotIn('占本城%', source)
        self.assertNotIn('优先比较', source)
        self.assertIsNone(number_floor(''))
        self.assertIsNone(number_floor('甲'))
        self.assertEqual(number_floor('180'), 180)
        self.assertTrue(meets_floor(180, 180))
        self.assertFalse(meets_floor(179, 180))
        self.assertFalse(meets_floor(None, 180))
        self.assertTrue(meets_floor(None, None))
        self.assertEqual(format_five_avg(400), '400')
        self.assertEqual(format_five_avg(400.5), '400.5')
        city = {'city_id': 1, 'name': '陈留', 'type': 'city'}
        state = {'entities': {
            'cities_and_barriers': [city],
            'lords': [{'force_id': 3, 'name': '吴'}],
            'generals': [
                officer(1, 1, '完整甲'),
                officer(2, 1, '完整乙', lead=90, war=90, intel=90, pol=90, cha=90),
                officer(3, 1, '缺属性', cha=None),
                officer(4, 1, '已仕', status=0, owner=3),
            ],
        }}
        rows, meta = summarize(state)
        self.assertEqual(meta['total'], 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['total'], 3)
        self.assertEqual(rows[0]['blade'], 180)
        self.assertEqual(rows[0]['blade_avg'], 500 / 3)
        self.assertEqual(rows[0]['pol'], 90)
        self.assertEqual(rows[0]['blades'], '完整乙 180、缺属性 160、完整甲 160')
        self.assertNotIn('max', rows[0])
        self.assertNotIn('unknown', rows[0])
        self.assertEqual(city_five_averages(state), {1: 500 / 3})
        self.assertEqual(rows[0]['ride'], 0)
        self.assertIsNone(rows[0].get('raid'))
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertIn('if self.rendering_tables:return', hub)
        self.assertNotIn('if record is None and self.rendering_tables:return', hub)
        self.assertIn('def _dismiss_location_window', hub)
        self.assertIn("protocol('WM_DELETE_WINDOW',self._dismiss_location_window)", hub)
        self.assertIn('def _popup_is_front', hub)
        self.assertIn('def _hub_has_focus', hub)
        self.assertIn('def _hide_idle_popups', hub)
        self.assertIn('self._hide_idle_popups()', hub)
        self.assertIn('self._locator_hold()', hub)
        self.assertNotIn('self.location_window.focus_force()', hub)
        self.assertIn('if self._locator_held() or self._hub_has_focus():', hub)
        self.assertIn('if self._popup_mapped(self.location_window):', hub)
        self.assertNotIn('if self._popup_is_front(self.location_window):', hub)
        self.assertNotIn("('city_avg','平均五维',90)", hub)
        self.assertIn("('blade','统武',55)", hub)
        self.assertIn("('pol','政治',55)", hub)
        self.assertIn("text='最高统武≥'", source)
        self.assertIn("text='政治≥'", source)
        self.assertIn("text='平均统武≥'", source)
        self.assertIn("text=f'{title}≥'", source)
        self.assertIn("text='%'", source)
        sample = {'name': '陈留', 'owner': '吴', 'blade': 180, 'blade_avg': 150.5, 'pol': 90, 'ride': 67, 'bow': 33, 'navy': 33, 'ambush': 67}
        self.assertTrue(passes_city_filters(sample, '', {}))
        self.assertTrue(passes_city_filters(sample, '陈', {'blade_avg': 150, 'ride': 67, 'ambush': 60}))
        self.assertFalse(passes_city_filters(sample, '', {'blade_avg': 151}))
        self.assertFalse(passes_city_filters(sample, '', {'bow': 34}))
        self.assertFalse(passes_city_filters(sample, '', {'navy': 34}))
        self.assertFalse(passes_city_filters(sample, '', {'ride': None, 'ambush': 68}))
        self.assertFalse(passes_city_filters({**sample, 'blade_avg': None}, '', {'blade_avg': 1}))
        filters = (Path(__file__).resolve().parents[1] / 'app' / 'talent_filters.py').read_text(encoding='utf-8')
        self.assertIn("SKILL_TAGS=('骑马','弓箭','埋伏','水军')", filters)
        self.assertNotIn('SKILL_OPTIONS[1:]', filters)
        self.assertIn('lead_war_total(r)', hub)
        self.assertNotIn('format_five_avg(city_avgs.get(cid)', hub)
        self.assertNotIn('属性缺失', hub)

    def test_skill_counts_use_matched_website_skills(self):
        city = {'city_id': 1, 'name': '陈留', 'type': 'city'}
        wei_ge = officer(1, 1, '威哥', lead=115, war=70, intel=105, pol=95, cha=100)
        si_ma = officer(2, 1, '司马错', lead=87, war=82, intel=90, pol=63, cha=66)
        unmatched = officer(3, 1, '诸葛亮')
        state = {'entities': {
            'cities_and_barriers': [city],
            'lords': [{'force_id': 3, 'name': '吴'}],
            'generals': [wei_ge, si_ma, unmatched],
        }}
        row = summarize(state)[0][0]
        self.assertEqual(row['total'], 3)
        self.assertEqual(row['ride'], 67)
        self.assertEqual(row['bow'], 33)
        self.assertEqual(row['ambush'], 67)
        self.assertNotIn('raid', row)
        self.assertNotIn('thunder', row)
        self.assertEqual(row['navy'], 33)

    def test_blade_order_lists_wild_officers_highest_first(self):
        high = officer(1, 1, '孙坚', lead=100, war=87)
        mid = officer(2, 1, '无忧', lead=70, war=75)
        low = officer(3, 1, '张昭', lead=40, war=5)
        hired = officer(4, 1, '已仕', lead=120, war=120, status=0, owner=3)
        self.assertEqual(blade_order_label([low, high, mid]), '孙坚 187、无忧 145、张昭 45')
        self.assertEqual(blade_order_label([]), '—')
        city = {'city_id': 1, 'name': '襄阳', 'type': 'city'}
        state = {'entities': {
            'cities_and_barriers': [city],
            'lords': [{'force_id': 2, 'name': '韩'}],
            'generals': [low, high, mid, hired],
        }}
        row = summarize(state)[0][0]
        self.assertEqual(row['blades'], '孙坚 187、无忧 145、张昭 45')
        self.assertEqual(row['total'], 3)
        self.assertNotIn('likely', row)
        source = (Path(__file__).resolve().parents[1] / 'app' / 'city_talent.py').read_text(encoding='utf-8')
        self.assertIn("('blades','统武顺序',420)", source)
        self.assertNotIn('最可能录用', source)

    def test_idle_hide_keeps_locator_while_hub_still_focused(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        try:
            root.geometry('320x120+40+40')
            main = tk.Entry(root)
            main.pack()
            popup = tk.Toplevel(root)
            popup.geometry('240x160+380+40')
            root.update()
            main.focus_force()
            root.update()
            self.assertIsNotNone(root.focus_displayof())
            self.assertEqual(str(root.focus_displayof().winfo_toplevel()), str(root))

            class Fake:
                _popup_mapped = OmniWindow._popup_mapped
                _hide_idle_popups = OmniWindow._hide_idle_popups
                def __init__(self):
                    self.root = root
                    self.location_window = popup
                    self.place_window = None
                    self.hub_focus = True
                def _hub_has_focus(self):
                    return self.hub_focus
                def _locator_held(self):
                    return False
                def _dismiss_location_window(self):
                    popup.withdraw()
                def _dismiss_place_window(self):
                    pass

            fake = Fake()
            self.assertTrue(OmniWindow._hub_has_focus(fake))
            fake._hide_idle_popups()
            popup.update()
            self.assertTrue(popup.winfo_ismapped())
            fake.hub_focus = False
            fake._hide_idle_popups()
            popup.update()
            self.assertFalse(popup.winfo_ismapped())
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
