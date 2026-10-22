import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from opening_troop_routes import BY_ID, BY_NAME, EMPTY, FALLBACK, ROUTES, opening_route_note


class OpeningTroopRoutesTests(unittest.TestCase):
    def test_covers_all_twenty_two_nations(self):
        self.assertEqual([row[0] for row in ROUTES], list(range(22)))
        self.assertEqual(len(BY_ID), 22)
        self.assertEqual(len(BY_NAME), 22)
        for force_id, name, text in ROUTES:
            self.assertNotIn('22国', text, name)
            self.assertLessEqual(len(text), 40, name)
            self.assertEqual(opening_route_note({'force_id': force_id, 'name': '错名'}), text)
            self.assertEqual(opening_route_note({'name': name}), text)

    def test_wei_qi_wu_and_unknown(self):
        self.assertIn('开局练步', opening_route_note({'force_id': 0}))
        self.assertIn('步训90', opening_route_note({'force_id': 0}))
        self.assertIn('开局练步', opening_route_note({'force_id': 3, 'name': '齐'}))
        self.assertIn('开局练弓', opening_route_note({'name': '吴'}))
        self.assertEqual(opening_route_note(None), EMPTY)
        self.assertNotIn('22国', EMPTY)
        self.assertEqual(opening_route_note({'force_id': 99, 'name': '庄子'}), FALLBACK)

    def test_stock_tab_shows_opening_note(self):
        import tkinter as tk
        from military_summary import MilitarySummary
        root = tk.Tk()
        root.withdraw()
        try:
            page = MilitarySummary(root)
            page.update_force({
                'force_id': 0, 'name': '魏',
                'armament_raw': {'infantry': 190, 'cavalry': 130, 'bow': 130},
                'troop_stock': {'infantry': 30000, 'cavalry': 10000, 'bow': 20000},
            }, {'entities': {}})
            self.assertIn('开局练步', page.note.cget('text'))
            self.assertEqual(page.tiles['infantry'][3]['value'].cget('text'), '90')
            self.assertEqual(page.tiles['infantry'][3]['fill'].cget('bg'), '#d46512')
            self.assertAlmostEqual(float(page.tiles['infantry'][3]['fill'].place_info()['relwidth']), 0.9)
            self.assertEqual(page.tiles['infantry'][4].cget('text'), '80%')
            page.update_force({
                'force_id': 0, 'name': '魏',
                'armament_raw': {'infantry': 45, 'cavalry': 245, 'bow': 0},
                'troop_stock': {'infantry': 0, 'cavalry': 0, 'bow': 500},
            }, {'entities': {}})
            self.assertEqual(page.tiles['infantry'][3]['fill'].cget('bg'), '#3d4f63')
            self.assertAlmostEqual(float(page.tiles['infantry'][3]['fill'].place_info()['relwidth']), 0.45)
            self.assertEqual(page.tiles['cavalry'][3]['fill'].cget('bg'), '#6b2d9b')
            self.assertEqual(page.tiles['bow'][3]['value'].cget('text'), '0')
            self.assertEqual(page.tiles['bow'][4].cget('text'), '100%')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
