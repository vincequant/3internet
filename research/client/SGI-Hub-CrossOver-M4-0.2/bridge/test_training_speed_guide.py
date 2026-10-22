import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from training_speed_guide import BOW, CAMPS, HEAD, LEAD, SECTIONS, TRAIN_FULL
from tutorial_rules import RULES


class TrainingSpeedGuideData(unittest.TestCase):
    def test_camp_and_full_training_medians(self):
        by = {row[0]: row for row in CAMPS}
        self.assertEqual(by['练兵所'][1:], (10, 14165, 12963, 8870, 15000))
        self.assertEqual(by['牧场'][1], 34)
        self.assertEqual(by['牧场'][2], 3225)
        self.assertEqual(by['弓工坊'][2], 9240)
        train = {row[0]: row for row in TRAIN_FULL}
        self.assertEqual(train['弓'][2], 20.0)
        self.assertEqual(train['骑'][2], 32.0)
        self.assertEqual([row[0] for row in BOW],
                         ['1万以下', '1–3万', '3–5万', '5–7万', '7–9万', '9万以上'])
        self.assertEqual(BOW[0][2], 20)
        self.assertEqual(BOW[-1][2], 10)

    def test_hundred_thousand_bow_advice(self):
        self.assertEqual(HEAD, '盖营与练兵实测')
        self.assertIn('1.42 万', LEAD)
        self.assertIn('9240', LEAD)
        self.assertIn('3225', LEAD)
        self.assertIn('+20', LEAD)
        body = '\n'.join(part[1] for part in SECTIONS)
        self.assertIn('14–15', body)
        self.assertIn('18', body)
        skill = RULES['练兵技巧']
        self.assertIn('3/5', skill)
        self.assertIn('9240', skill)
        self.assertIn('3225', skill)
        self.assertNotIn('混合后的训练公式未给出', skill)

    def test_retired_rules_panel_is_replaced_by_manual(self):
        text = (ROOT / 'app' / 'rules_panel.py').read_text(encoding='utf-8')
        omni = (ROOT / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertNotIn('TrainingSpeedGuide', text)
        self.assertNotIn("text='盖营与练兵实测'", text)
        self.assertIn("text='算法手册'", text)
        self.assertIn("workspace.add(self.rules_panel,text='攻略预判')", omni)
        self.assertIn('training-speed-archive-guide', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
