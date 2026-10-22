import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]
from training_sim import (
    CAMP_YIELD, GOAL_STOCK, OPENING, YEAR1_CIVIL, YEAR_PACE, advantage_kind, apply_action,
    format_best_table, format_force_order, goal_hit, goal_raw, kind_stars, min_commands,
    mix_recruit, opening_state, project_goal, star_glyph, train_gain,
)


class TrainingSimEngine(unittest.TestCase):
    def test_opening_twenty_two_and_ba_infantry(self):
        self.assertEqual(len(OPENING), 22)
        self.assertEqual([row[0] for row in OPENING], list(range(22)))
        ba = opening_state(name='巴')
        self.assertEqual(ba['stock']['infantry'], 35000)
        wei = opening_state(0)
        self.assertEqual(wei['stock'], {'infantry': 30000, 'cavalry': 10000, 'bow': 20000})
        self.assertEqual(wei['raw']['bow'], 130)
        self.assertEqual(wei['camp']['cavalry'], 6500)

    def test_train_gain_strips_stock_ratio_via_formula(self):
        self.assertEqual(train_gain('bow', 0), 20)
        self.assertEqual(train_gain('bow', 100000), 10)
        self.assertEqual(train_gain('cavalry', 0), 30)
        self.assertEqual(train_gain('infantry', 0), 40)

    def test_summer_mix_and_three_commands(self):
        st = opening_state(name='燕')
        st['stock']['bow'] = 0
        st['raw']['bow'] = 300
        st['camp']['bow'] = 100000
        for _ in range(3):
            st = apply_action(st, 'other')
        self.assertEqual(st['season'], 1)
        self.assertEqual(st['stock']['bow'], 100000)
        self.assertEqual(st['raw']['bow'], 180)
        self.assertEqual(st['other'], 3)
        self.assertEqual(st['build'] + st['train'], 0)

    def test_goal_counts_only_build_and_train(self):
        st = opening_state(name='秦')
        st['stock']['bow'] = GOAL_STOCK
        st['raw']['bow'] = 170
        st = apply_action(st, 'other')
        st = apply_action(st, 'train:bow')
        self.assertTrue(goal_hit(st, 'bow'))
        hit = st['reached']['bow']
        self.assertEqual(hit['train'], 1)
        self.assertEqual(hit['build'], 0)
        self.assertEqual(hit['other'], 1)
        self.assertEqual(hit['total'], 1)

    def test_mix_seed_lands_at_180(self):
        raw, stock = mix_recruit(300, 0, 100000)
        self.assertEqual((raw, stock), (180, 100000))
        self.assertEqual(raw, goal_raw('bow'))

    def test_project_wei_bow_reports_build_plus_train(self):
        proj = project_goal(opening_state(0), 'bow')
        self.assertTrue(proj['ok'])
        self.assertGreater(proj['build'], 0)
        self.assertGreater(proj['train'], 0)
        self.assertEqual(proj['total'], proj['build'] + proj['train'])
        self.assertGreaterEqual(proj['stock'], GOAL_STOCK)
        self.assertGreaterEqual(proj['raw'], goal_raw('bow'))
        already = opening_state(0)
        already['stock']['bow'] = 100000
        already['raw']['bow'] = 200
        zero = project_goal(already, 'bow')
        self.assertEqual(zero['total'], 0)

    def test_archive_year_pace(self):
        self.assertEqual(YEAR_PACE['year1']['n'], 38)
        self.assertEqual(YEAR_PACE['year1']['build_mean'], 0.58)
        self.assertEqual(YEAR_PACE['year1']['train_mean'], 4.29)
        self.assertEqual(YEAR_PACE['later']['n'], 64)
        self.assertEqual(YEAR_PACE['later']['build_mean'], 0.44)
        self.assertEqual(YEAR_PACE['later']['train_mean'], 4.31)
        self.assertEqual(YEAR1_CIVIL, 0)
        from training_sim import YEAR1_PRE, YEAR1_POST, goal_stock
        self.assertEqual(YEAR1_PRE, 0)
        self.assertEqual(YEAR1_POST, 3)
        self.assertEqual(goal_stock('cavalry'), 100000)
        qin = min_commands('infantry', name='秦')
        self.assertTrue(qin['ok'])
        wu = min_commands('bow', name='吴')
        self.assertTrue(wu['ok'])
        qiang = min_commands('cavalry', name='羌')
        self.assertTrue(qiang['ok'])
        plan = '\n'.join(qiang.get('plan') or [])
        self.assertNotIn('200年春', plan)
        self.assertIn('最少指令', format_best_table())
        self.assertEqual(kind_stars('infantry', name='秦'), 3)
        self.assertEqual(kind_stars('bow', name='吴'), 3)
        self.assertLessEqual(kind_stars('bow', name='南蛮'), 2)
        self.assertLessEqual(kind_stars('cavalry', name='秦'), 2)
        self.assertEqual(star_glyph(3), '★★★')
        self.assertEqual(star_glyph(1), '★☆☆')
        self.assertEqual(advantage_kind(name='吴'), 'bow')
        self.assertEqual(advantage_kind(name='秦'), 'infantry')
        self.assertEqual(advantage_kind(name='羌'), 'cavalry')
        wu = format_force_order(name='吴')
        self.assertIn('相对优势', wu)
        self.assertIn('盖', wu)
        self.assertIn('练弓', wu)
        qin = min_commands('infantry', name='秦')
        self.assertTrue(qin.get('plan'))

    def test_camp_yield_matches_archive_median(self):
        self.assertEqual(CAMP_YIELD['bow'], 9240)
        self.assertEqual(CAMP_YIELD['cavalry'], 3225)
        self.assertEqual(CAMP_YIELD['infantry'], 14165)

    def test_retired_panel_does_not_compete_with_algorithm_manual(self):
        text = (ROOT / 'app' / 'rules_panel.py').read_text(encoding='utf-8')
        self.assertNotIn('TrainingSimPanel', text)
        self.assertIn("text='算法手册'", text)
        self.assertIn("text='攻击系数计算器'", text)
        self.assertIn('camp-train-simulator', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('year-pace-in-sim', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
