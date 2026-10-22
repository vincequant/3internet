import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from force_troop_totals import (
    append_troop_series, force_troop_sample, merge_troop_series, samples_for_force,
    season_chart_label, seasons_until_next_summer, troop_series_point, unit_kind,
)


def state():
    return {
        'clock_candidates': {'year_u16': 200, 'season_u16': 0, 'turn_u16': 2},
        'entities': {
            'lords': [{
                'force_id': 3, 'name': '齐',
                'troop_stock': {'infantry': 1000, 'cavalry': 400, 'bow': 50},
                'armament_raw': {'infantry': 70, 'cavalry': 200, 'bow': 10},
            }],
            'field_units': [
                {'owner_raw': 3, 'unit_kind': '重装骑兵', 'soldiers_candidate': 2400, 'general_ids': [8]},
                {'owner_raw': 3, 'unit_kind': '游荡部队', 'soldiers_candidate': 20000},
                {'owner_raw': 9, 'unit_kind': 'infantry', 'soldiers_candidate': 999},
            ],
            'generals': [
                {'general_id_raw': 1, 'owner_raw': 3, 'status_code': 0, 'soldiers': 800},
                {'general_id_raw': 8, 'owner_raw': 3, 'status_code': 2, 'soldiers': 2400},
                {'general_id_raw': 2, 'owner_raw': 9, 'status_code': 0, 'soldiers': 500},
            ],
        },
    }


class ForceTroopTotalsTests(unittest.TestCase):
    def test_adds_field_not_other_force_or_deployed_officer(self):
        sample = force_troop_sample(state(), 3)
        self.assertEqual(sample['kinds']['infantry']['total'], 1000)
        self.assertEqual(sample['kinds']['cavalry']['warehouse'], 400)
        self.assertEqual(sample['kinds']['cavalry']['field'], 2400)
        self.assertEqual(sample['kinds']['cavalry']['total'], 2800)
        self.assertEqual(sample['city'], 800)
        self.assertEqual(sample['field_other'], 20000)
        self.assertIsNone(unit_kind({'unit_kind': '游荡部队'}))
        self.assertEqual(unit_kind({'unit_kind': '重装骑兵'}), 'cavalry')
        self.assertEqual(unit_kind({'unit_kind': '强弓兵'}), 'bow')

    def test_series_replaces_same_label(self):
        first = troop_series_point(state())
        again = troop_series_point(state())
        rows = append_troop_series([], first)
        rows = append_troop_series(rows, again)
        self.assertEqual(len(rows), 1)
        self.assertIn('春', first['label'])
        text = (Path(__file__).resolve().parents[1] / 'app' / 'force_troop_totals.py').read_text(encoding='utf-8')
        self.assertIn("sys.path.insert(0, str(_bridge))", text)
        hist = (Path(__file__).resolve().parents[1] / 'bridge' / 'state_history.py').read_text(encoding='utf-8')
        self.assertIn("parent.parent / 'app'", hist)
        self.assertIn('if not self.troop_series and self.baseline', hist)

    def test_merge_keeps_earlier_quarters(self):
        spring = troop_series_point(state())
        winter_state = state()
        winter_state['clock_candidates'] = {'year_u16': 200, 'season_u16': 3, 'turn_u16': 2}
        winter = troop_series_point(winter_state)
        merged = merge_troop_series([spring], [], [winter])
        self.assertEqual([row['label'] for row in merged], [spring['label'], winter['label']])
        panel = (Path(__file__).resolve().parents[1] / 'app' / 'training_record_panel.py').read_text(encoding='utf-8')
        self.assertIn('merge_troop_series', panel)
        self.assertIn('self.session', panel)
        self.assertIn("kind + '-stock'", panel)
        self.assertIn("kind + '-train'", panel)
        self.assertIn("side='left'", panel)
        self.assertIn("text=title", panel)
        self.assertIn("'步兵'", panel)
        self.assertIn("'骑兵'", panel)
        self.assertIn("'弓兵'", panel)
        self.assertIn('ttk.Notebook', panel)
        self.assertIn('width=1, height=1', panel)
        self.assertIn('scrollregion', panel)
        self.assertIn('create_rectangle', panel)
        self.assertIn('_left_margin', panel)
        self.assertIn('from opening_troop_routes import opening_route_note', panel)
        self.assertIn('opening_route_note(force)', panel)
        self.assertNotIn('self.note', panel)
        self.assertNotIn('步、骑、弓分开画', panel)
        self.assertNotIn('charts.columnconfigure', panel)
        self.assertIn("TIER_LINES = ((100, '#e07018'), (200, '#7a3cb8'))", panel)
        self.assertIn('dash=(5, 4)', panel)
        self.assertIn('predicted_after_summer', panel)
        self.assertNotIn('self.stock_canvas', panel)
        self.assertNotIn('self.train_canvas', panel)

    def test_seasons_until_next_summer(self):
        self.assertEqual(
            [(row['year'], row['season'], row['label']) for row in seasons_until_next_summer(200, 3)],
            [(201, 0, '201年春'), (201, 1, '201年夏')],
        )
        self.assertEqual(
            [row['label'] for row in seasons_until_next_summer(200, 0)],
            ['200年夏'],
        )
        self.assertEqual(
            [row['label'] for row in seasons_until_next_summer(200, 1)],
            ['200年秋', '200年冬', '201年春', '201年夏'],
        )
        self.assertEqual(seasons_until_next_summer(200, 9), [])
        sample = samples_for_force([troop_series_point(state())], 3)[0]
        self.assertEqual(sample['year'], 200)
        self.assertEqual(sample['season'], 0)

    def test_series_keeps_one_point_per_season(self):
        civil_state = state()
        civil_state['clock_candidates'] = {'year_u16': 200, 'season_u16': 0, 'turn_u16': 0}
        civil = troop_series_point(civil_state)
        military = state()
        military['clock_candidates'] = {'year_u16': 200, 'season_u16': 0, 'turn_u16': 2}
        military['entities']['lords'][0]['armament_raw'] = {'infantry': 10, 'cavalry': 200, 'bow': 10}
        later = troop_series_point(military)
        rows = append_troop_series([], civil)
        rows = append_troop_series(rows, later)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['forces']['3']['kinds']['infantry']['raw'], 70)
        self.assertIn('内政', rows[0]['label'])
        summer = state()
        summer['clock_candidates'] = {'year_u16': 200, 'season_u16': 1, 'turn_u16': 0}
        summer['entities']['lords'][0]['armament_raw'] = {'infantry': 40, 'cavalry': 200, 'bow': 10}
        summer_r2 = state()
        summer_r2['clock_candidates'] = {'year_u16': 200, 'season_u16': 1, 'turn_u16': 2}
        summer_r2['entities']['lords'][0]['armament_raw'] = {'infantry': 5, 'cavalry': 200, 'bow': 10}
        rows = append_troop_series(rows, troop_series_point(summer))
        rows = append_troop_series(rows, troop_series_point(summer_r2))
        self.assertEqual([(row['year'], row['season']) for row in rows], [(200, 0), (200, 1)])
        self.assertEqual(rows[1]['forces']['3']['kinds']['infantry']['raw'], 40)
        labels = [row['label'] for row in samples_for_force(rows, 3)]
        self.assertEqual(labels, ['200年春', '200年夏'])

    def test_merge_does_not_repeat_seasons(self):
        spring = troop_series_point(state())
        winter_state = state()
        winter_state['clock_candidates'] = {'year_u16': 200, 'season_u16': 3, 'turn_u16': 2}
        winter = troop_series_point(winter_state)
        merged = merge_troop_series([spring, winter], [spring, winter], [winter])
        self.assertEqual(len(merged), 2)
        self.assertEqual([season_chart_label(row) for row in merged], ['200年春', '200年冬'])

    def test_forecast_panel_draws_dash_to_next_summer(self):
        import tkinter as tk
        from training_record_panel import TrainingRecordPanel
        winter = state()
        winter['clock_candidates'] = {'year_u16': 200, 'season_u16': 3, 'turn_u16': 2}
        winter['entities']['cities_and_barriers'] = [{
            'type': 'city', 'owner_raw': 3, 'city_id': 1, 'name': '平原',
            'recruitment_capacity': {
                'population_cap': 10000,
                'amounts': {'infantry': 5000, 'cavalry': 1000, 'bow': 0},
            },
        }]
        root = tk.Tk()
        root.withdraw()
        try:
            panel = TrainingRecordPanel(root)
            panel.update_force(winter['entities']['lords'][0], winter)
            self.assertEqual(str(panel.kind_book.index('current')), '0')
            self.assertEqual(panel.forecast_labels, ['201年春', '201年夏'])
            inf = panel.forecast['infantry']
            self.assertEqual(inf['stock'], [1000, 6000])
            self.assertEqual(inf['train'], [70, (70 * 1000 + 42 * 5000) // 6000])
            canvas = panel.canvases['infantry-stock']
            canvas.config(width=400, height=120)
            panel.update_idletasks()
            panel.redraw()
            dashes = [
                canvas.itemcget(item, 'dash')
                for item in canvas.find_all()
                if canvas.type(item) == 'line' and canvas.itemcget(item, 'dash')
            ]
            self.assertTrue(any('5' in str(row) for row in dashes))
            titles = [
                canvas.itemcget(item, 'text')
                for item in canvas.find_all()
                if canvas.type(item) == 'text' and '预201年夏' in canvas.itemcget(item, 'text')
            ]
            self.assertTrue(titles)
            self.assertIn('6,000', titles[0])
            train = panel.canvases['infantry-train']
            train.config(width=400, height=120)
            panel.update_idletasks()
            panel.redraw()
            fills = {
                train.itemcget(item, 'fill')
                for item in train.find_all()
                if train.type(item) == 'line'
            }
            self.assertIn('#e07018', fills)
            self.assertIn('#7a3cb8', fills)
            self.assertIs(panel.canvases['infantry-stock'].master, panel.canvases['infantry-train'].master)
            self.assertIsNot(panel.canvases['infantry-stock'].master, panel.canvases['cavalry-stock'].master)
            self.assertEqual(panel.kind_book.tab(0, 'text'), '步兵')
            self.assertEqual(panel.kind_book.tab(1, 'text'), '骑兵')
            self.assertEqual(panel.kind_book.tab(2, 'text'), '弓兵')
            self.assertEqual(str(panel.kind_book.index('current')), '0')
            self.assertGreaterEqual(panel._left_margin(canvas, [0, 50000, 100000]), 56)
            self.assertEqual(str(panel.canvases['bow-stock'].cget('height')), '1')
            self.assertEqual(str(panel.canvases['bow-train'].cget('width')), '1')
            from test_training_activity import packet
            winter['native_command_evidence'] = {'rows': [packet(actor=3), packet(4, 7, 'camp1', actor=3)]}
            for _ in range(2):
                panel.update_force(winter['entities']['lords'][0], winter)
                self.assertEqual(panel.activity.cget('text'), '累计记录：训练 1 次 · 盖兵营 1 次')
                self.assertEqual(panel.kind_activity['infantry'].cget('text'), '步兵累计：训练 0 次 · 盖练兵所 1 次')
                self.assertEqual(panel.kind_activity['cavalry'].cget('text'), '骑兵累计：训练 1 次 · 盖牧场 0 次')
            panel.update_activity(9, winter)
            self.assertEqual(panel.activity.cget('text'), '累计记录：训练 0 次 · 盖兵营 0 次')
            panel.update_force(winter['entities']['lords'][0], state())
            self.assertEqual(panel.activity_counts['training'], 0)
            self.assertEqual(panel.activity_counts['building'], 0)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
