"""Lock step/ride numbers to the live website JS, across many input nodes."""
import math
import unittest
from training_curves import calculator_attack
from website_combat import attack

def js_round(n):
    return math.floor(n + 0.5)

# https://sanguoyouxi.vip/cx/gj/index.html unitData + sizeBonus, fetched 2026-09-14
UNITDATA = {
    '强化步兵': (150, 40, (0, 100, 200)),
    '重装步兵': (190, 40, (0, 100, 200)),
    '铁骑兵': (200, 50, (0, 150, 350)),
    '强化骑兵': (150, 50, (0, 150, 350)),
    '生步兵': (50, 100, (0, 100, 200)),
    '生骑兵': (100, 50, (0, 150, 350)),
}
CURVE_NAME = {
    ('infantry', 0): '生步兵', ('infantry', 1): '强化步兵', ('infantry', 2): '重装步兵',
    ('cavalry', 0): '生骑兵', ('cavalry', 1): '强化骑兵', ('cavalry', 2): '铁骑兵',
}

def website_js(kind, size, armament, ability=100):
    base, arm_base, sizes = UNITDATA[kind]
    total = base + sizes[size] + js_round(arm_base * armament / 100)
    return js_round(ability * total / 150)


class WebsiteCurveNodes(unittest.TestCase):
    def test_user_screenshots_and_cavalry_stays_ahead(self):
        self.assertEqual(attack('铁骑兵', 0, 100, 100), 167)
        self.assertEqual(attack('重装步兵', 0, 100, 100), 153)
        self.assertEqual(calculator_attack('cavalry', 300, 0), 167)
        self.assertEqual(calculator_attack('infantry', 300, 0), 153)
        for size in (0, 1, 2):
            self.assertLess(calculator_attack('infantry', 300, size), calculator_attack('cavalry', 300, size))

    def test_js_grid_matches_hub_calculator(self):
        for kind in UNITDATA:
            for size in (0, 1, 2):
                for arm in (0, 1, 21, 39, 50, 80, 93, 99, 100):
                    for ability in (80, 91, 100):
                        self.assertEqual(attack(kind, size, arm, ability), website_js(kind, size, arm, ability),
                                         (kind, size, arm, ability))

    def test_curve_nodes_use_tier_and_remainder(self):
        for kind in ('infantry', 'cavalry'):
            for raw in (0, 21, 50, 80, 93, 99, 100, 139, 150, 180, 199, 200, 221, 250, 292, 300):
                site = CURVE_NAME[(kind, 0 if raw < 100 else 1 if raw < 200 else 2)]
                degree = 100 if raw >= 300 else raw % 100
                for size in (0, 1, 2):
                    self.assertEqual(calculator_attack(kind, raw, size), attack(site, size, degree, 100),
                                     (kind, raw, size, site, degree))


if __name__ == '__main__':
    unittest.main()
