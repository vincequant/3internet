import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bridge'), str(ROOT / 'app')]

from state_extensions import UNIT_TYPES, decode_unit
from unit_memory import attack_reference, attack_label, memory_line, rice_days, rice_label


class UnitMemoryTests(unittest.TestCase):
    def test_legacy_reference_is_never_guessed_from_new_ranges(self):
        from unit_target_attack import preserve_legacy_reference
        source='unit=SANPK 3.5 table; building=SANPK 3.5 static'
        for value in ('184–369','缺参数',True,-1,None,1.5):
            row={'target_attack_unit':value,'target_attack_components':{'source':source}}
            preserve_legacy_reference(row)
            self.assertNotIn('legacy_attack_reference',row)
        for model,src in (('sanpk-3.5-attack-index-v1',source),(None,'unverified')):
            row={'target_attack_unit':'124','attack_model':model,
                 'target_attack_components':{'source':src}}
            preserve_legacy_reference(row)
            self.assertNotIn('legacy_attack_reference',row)

    def test_decode_unit_soldiers_and_rice(self):
        vt = next(iter(UNIT_TYPES))
        buf = bytearray(168)
        struct.pack_into('<hh', buf, 4, 65, 83)
        struct.pack_into('<HH', buf, 8, 0, 7)
        struct.pack_into('<3H', buf, 0xf, 12, 65535, 65535)
        struct.pack_into('<I', buf, 0x15, 3959)
        struct.pack_into('<I', buf, 0x19, 1426)
        buf[0x1d] = 79
        buf[0x29] = 90
        row = decode_unit(0x1000, bytes(buf), vt)
        self.assertEqual(row['soldiers_candidate'], 3959)
        self.assertEqual(row['rice_candidate'], 1426)
        self.assertEqual(row['raw_1d'], 79)
        self.assertEqual(row['armament_degree_raw'], 90)
        self.assertEqual(row['general_ids'], [12, None, None])
        self.assertEqual(row['world_xy_raw'], [65, 83])

    def test_rice_days_from_guide(self):
        self.assertEqual(rice_days(2969, 2969), 6)
        self.assertAlmostEqual(rice_days(3959, 1426), 6 * 1426 / 3959)
        self.assertEqual(rice_days(4000, 0), 0)
        self.assertIsNone(rice_days(0, 100))
        self.assertIsNone(rice_days(None, 100))
        self.assertIn('约6天', rice_label({'soldiers_candidate': 2969, 'rice_candidate': 2969}))
        self.assertIn('1,426', rice_label({'soldiers_candidate': 3959, 'rice_candidate': 1426}))

    def test_memory_line_order_hides_training(self):
        text = memory_line({
            'soldiers_candidate': 3959,
            'rice_candidate': 1426,
            'morale': 79,
            'training_degree': 90,
            'basic_combat_power': 78,
            'target_attack_unit': 97,
            'size_label': '小队',
        })
        self.assertIn('兵数 3,959', text)
        self.assertIn('粮食 1,426（约2.2天）', text)
        self.assertIn('战力 78', text)
        self.assertIn('士气 79', text)
        self.assertIn('攻击[当前/陆地满士气] [未知/未知]', text)
        self.assertNotIn('训练', text)
        self.assertEqual(attack_label({}), '[未知/未知]')
        self.assertIn('粮食 未知', memory_line({}))


    def test_map_reference_does_not_guess_from_native_index(self):
        for value in ('184–369', '缺参数', '', None, True, -1, 'nan', 1.5):
            self.assertIsNone(attack_reference({'target_attack_unit':value}))
        self.assertEqual(attack_reference({'target_attack_unit':'82'}),82)
        self.assertEqual(attack_reference({'target_attack_unit':0}),0)
        self.assertIsNone(attack_reference({'target_attack_unit':'867',
            'attack_model':'sanpk-3.5-attack-index-v1','native_attack_index':867}))
        row={'target_attack_unit':'184–369','attack_model':'sanpk-3.5-attack-index-v1',
             'basic_combat_power':74,'target_attack_components':{'reference_unit':[167]}}
        self.assertEqual(attack_reference(row),82)
        self.assertIn('攻击[当前/陆地满士气] [未知/未知]',memory_line(row))
        row['basic_combat_power']=None
        self.assertIsNone(attack_reference(row))
        row['website_attack_power']=0
        self.assertEqual(attack_reference(row),0)

    def test_pair_rejects_legacy_ranges_bad_scalars_and_hides_transport_attack(self):
        self.assertEqual(attack_label({'target_attack_unit':'184–369'}),'[未知/未知]')
        for bad in (True,-1,1.5,'184',None):
            self.assertEqual(attack_label({'attack_model':'sanpk-3.5-attack-index-v1',
                'native_attack_index':bad,'native_attack_index_full_morale':246}),'[未知/246]')
        self.assertEqual(attack_label({'attack_model':'other','native_attack_index':184,
            'native_attack_index_full_morale':246}),'[未知/未知]')
        row={'unit_kind':'运输兵','morale':50}
        self.assertEqual(attack_label(row),'—')
        self.assertNotIn('攻击',memory_line(row))


if __name__ == '__main__':
    unittest.main()
