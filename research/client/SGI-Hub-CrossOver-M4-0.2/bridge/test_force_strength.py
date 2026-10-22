import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / 'app')]
from force_strength import (
    five_stat_total, format_average, top_five_stat_average,
    unit_attack_average, unit_attack_total, unit_attack_value,
)


def officer(*stats):
    lead, war, intel, pol, cha = stats
    return {'attributes': dict(lead=lead, war=war, intel=intel, pol=pol, cha=cha)}


class ForceStrength(unittest.TestCase):
    def test_total_and_top10_average(self):
        self.assertEqual(five_stat_total(officer(90, 80, 70, 60, 50)), 350)
        self.assertIsNone(five_stat_total({'attributes': {'lead': 90}}))
        highs = [officer(100, 100, 100, 100, 100 - i) for i in range(10)]
        lows = [officer(10, 10, 10, 10, i) for i in range(8)]
        self.assertEqual(top_five_stat_average(lows + highs), 495.5)
        self.assertEqual(format_average(495.5), '495.5')
        self.assertEqual(format_average(400.0), '400')
        self.assertEqual(format_average(None), '—')

    def test_fewer_than_ten_uses_available(self):
        officers = [officer(80, 80, 80, 80, 80), officer(70, 70, 70, 70, 70)]
        self.assertEqual(top_five_stat_average(officers), 375)
        self.assertIsNone(top_five_stat_average([]))
        self.assertIsNone(top_five_stat_average([{'attributes': {}}]))

    def test_unit_attack_sum_and_average(self):
        units = [
            {'target_attack_unit': '120'},
            {'target_attack_unit': 80},
            {'target_attack_unit': '90–110'},
            {'target_attack_unit': '缺参数'},
            {'target_attack_unit': '基值 150（缺战力）'},
        ]
        self.assertEqual(unit_attack_value(units[0]), 120)
        self.assertEqual(unit_attack_value(units[2]), 100)
        self.assertIsNone(unit_attack_value(units[3]))
        self.assertIsNone(unit_attack_value(units[4]))
        self.assertEqual(unit_attack_total(units), 300)
        self.assertEqual(unit_attack_average(units), 100)
        self.assertIsNone(unit_attack_total([]))
        self.assertIsNone(unit_attack_average([{'target_attack_unit': '研究中'}]))
        self.assertEqual(format_average(unit_attack_total(units)), '300')
        from force_strength import force_attack_rows
        state = {
            'entities': {
                'lords': [{'force_id': 3, 'name': '齐'}, {'force_id': 10, 'name': '周'}],
                'field_units': [
                    {'owner_raw': 3, 'target_attack_unit': 120},
                    {'owner_raw': 3, 'target_attack_unit': 80},
                    {'owner_raw': 10, 'target_attack_unit': '缺参数'},
                ],
            },
        }
        rows = force_attack_rows(state)
        self.assertEqual([row['name'] for row in rows], ['齐', '周'])
        self.assertEqual(rows[0]['total'], 200)
        self.assertEqual(rows[0]['unit_count'], 2)
        self.assertIsNone(rows[1]['total'])
        self.assertIn('总战力 200', rows[0]['line'])
        self.assertIn('总战力 —', rows[1]['line'])
