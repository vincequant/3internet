import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]
from unit_target_attack import BUILD
from native_unit_rules import primary_skill_text, unit_skill_mask
from unit_special_chance import (special_preview, special_brief, special_details,
                                raid_percent, counter_pass_percent, native_distance,
                                personal_special_percent)


def scenario():
    def general(gid, owner, intel, mask):
        return dict(general_id_raw=gid, owner_raw=owner, status_code=2, name=f'将{gid}',
                    attributes={'intel': intel}, skill_mask_raw=mask, combat_modifier_flags_word=0)
    def unit(uid, owner, ids, xy):
        return dict(unit_id=uid, owner_raw=owner, general_ids=ids, unit_kind='强化步兵',
                    world_xy_raw=xy, morale=100, raw_1d=100, unit_state_flags_raw=0,
                    native_order_type_raw=0, native_order_payload_raw=0)
    return dict(build_sha256=BUILD, combat_rules={'flags_raw': 0}, entities={
        'generals': [general(1, 0, 95, 0x5600 | 0x40 | 0x80),
                     general(2, 1, 100, 0x12800), general(3, 1, 200, 0),
                     general(4, 2, 255, 0x12800)],
        'lords': [dict(force_id=0, diplomacy_relations=[0, 1, 3]),
                  dict(force_id=1, diplomacy_relations=[1, 0, 0]),
                  dict(force_id=2, diplomacy_relations=[3, 0, 0])],
        'field_units': [unit(0, 0, [1], [50, 100]), unit(1, 1, [2, 3], [51, 100]),
                        unit(2, 2, [4], [50, 101])]})


class SpecialChanceTests(unittest.TestCase):
    def test_personal_special_chains_four_spells_with_full_counter_pass(self):
        all_four = 0x200 | 0x400 | 0x4000 | 0x1000
        self.assertAlmostEqual(personal_special_percent(100, all_four), 87.4375)
        self.assertEqual(personal_special_percent(80, 0x200), 40)
        self.assertEqual(personal_special_percent(80, 0x200, 10), 50)
        self.assertEqual(personal_special_percent(90, 0), 0)
        self.assertIsNone(personal_special_percent(None, 0x200))
        self.assertIsNone(personal_special_percent(80, None))

    def test_matches_exhaustive_native_fragment_boundaries(self):
        for diff, expected in ((-10, 0), (-9, 2.5), (-5, 12.5), (-1, 22.5), (0, 25), (10, 25)):
            self.assertEqual(raid_percent(100 + diff, 100), expected)
        for diff, expected in ((-41, 0), (-40, 25), (-20, 25), (-19, 50), (19, 50), (20, 75), (40, 75), (41, 100)):
            self.assertEqual(counter_pass_percent(100 + diff, 100), expected)
        self.assertIsNone(raid_percent(None, 100))
        self.assertIsNone(counter_pass_percent(True, 100))

    def test_range_uses_native_offset_rows_and_both_relation_directions(self):
        self.assertEqual(native_distance([50, 100], [52, 100]), 4)
        self.assertEqual(native_distance([50, 100], [51, 101]), 3)
        self.assertEqual(native_distance([50, 101], [52, 100]), 3)
        s = scenario(); u = s['entities']['field_units'][0]
        s['entities']['lords'][0]['diplomacy_relations'][1] = 0
        self.assertEqual([t['unit_id'] for t in special_preview(s, u)['targets']], [1])
        # Opponent's preview must use opponent's relations, not player0's allies.
        enemy = s['entities']['field_units'][1]
        self.assertEqual([t['unit_id'] for t in special_preview(s, enemy)['targets']], [0])

    def test_skill_specific_defense_and_ordered_gates(self):
        s = scenario(); original = copy.deepcopy(s); u = s['entities']['field_units'][0]
        p = special_preview(s, u)
        self.assertEqual([r['cast_percent'] for r in p['spells']], [47, 47, 31, 23])
        self.assertEqual([r['defender_intel'] for r in p['spells']], [100] * 4)
        self.assertEqual([r['counter_pass_percent'] for r in p['spells']], [50] * 4)
        self.assertAlmostEqual(p['percent'], (1 - .53 * .53 * .69 * .77) * 50)
        # Raid uses max intelligence200, not the defense skill holder's100.
        self.assertEqual(p['raid'][0]['enemy_intel'], 200)
        self.assertEqual(p['raid'][0]['percent'], 0)
        self.assertEqual(p['wushuang_percent'], 12.5)
        self.assertEqual(s, original)

    def test_caster_is_best_skill_holder_not_best_general(self):
        s = scenario(); u = s['entities']['field_units'][0]
        g = dict(s['entities']['generals'][0], general_id_raw=5, attributes={'intel': 255}, skill_mask_raw=0)
        s['entities']['generals'].append(g); u['general_ids'].append(5)
        self.assertEqual(special_preview(s, u)['spells'][0]['cast_percent'], 47)
        g['skill_mask_raw'] = 0x200
        self.assertEqual(special_preview(s, u)['spells'][0]['cast_percent'], 50)

    def test_counter_pool_changes_when_enemy_moves_and_ally_is_ignored(self):
        s = scenario(); u = s['entities']['field_units'][0]
        enemy = s['entities']['field_units'][1]
        enemy['world_xy_raw'] = [52, 100]
        p = special_preview(s, u)
        self.assertEqual(p['percent'], 0)
        self.assertEqual(p['reason'], '范围内无交战敌队')
        enemy['world_xy_raw'] = [51, 100]
        s['entities']['generals'][1]['skill_mask_raw'] = 0
        p = special_preview(s, u)
        self.assertEqual([r['counter_pass_percent'] for r in p['spells']], [100] * 4)
        self.assertAlmostEqual(p['percent'], (1 - .53 * .53 * .69 * .77) * 100)

    def test_counter_ineligible_native_states_do_not_defend(self):
        for patch in ({'unit_state_flags_raw': 2}, {'native_order_type_raw': 2, 'native_order_payload_raw': 0}, {'unit_kind': '游荡部队'}):
            s = scenario(); u = s['entities']['field_units'][0]
            s['entities']['field_units'][1].update(patch)
            self.assertEqual(special_preview(s, u)['spells'][0]['counter_pass_percent'], 100)

    def test_missing_legacy_fields_never_fabricate_probability(self):
        s = scenario(); u = s['entities']['field_units'][0]
        del s['entities']['field_units'][1]['unit_state_flags_raw']
        self.assertIsNone(special_preview(s, u)['percent'])
        self.assertIn('未知', special_details(s, u))
        del s['entities']['generals'][1]['attributes']['intel']
        self.assertIsNone(special_preview(s, u)['percent'])
        s['build_sha256'] = 'unverified'
        self.assertEqual(special_preview(s, u)['reason'], '版本未核定')

    def test_morale_bonus_and_wushuang_room_setting(self):
        s = scenario(); u = s['entities']['field_units'][0]
        u['morale'] = 29
        self.assertEqual(special_preview(s, u)['percent'], 0)
        u['morale'] = 30
        s['entities']['generals'][0]['combat_modifier_flags_word'] = 0x100
        self.assertEqual([r['cast_percent'] for r in special_preview(s, u)['spells']], [50, 50, 41, 33])
        s['combat_rules']['flags_raw'] = 2
        self.assertEqual(special_preview(s, u)['wushuang_percent'], 0)
        del s['combat_rules']
        self.assertEqual(special_preview(s, u)['wushuang_percent'], 12.5)
        self.assertNotIn('无双', special_brief(s, u))

    def test_native_skill_tags_bow_hiding_and_boat_variant(self):
        from unit_memory import attack_label, memory_line
        from map_unit_labels import unit_label
        from native_unit_rules import boat_sprite
        s = scenario(); u = s['entities']['field_units'][0]
        s['entities']['generals'][0]['skill_mask_raw'] = 0xe7
        self.assertEqual(primary_skill_text(unit_skill_mask(s, u)), '骑 弓 水 伏 奇')
        self.assertIn('无双', primary_skill_text(unit_skill_mask(s, u), full=True))
        label = unit_label(s, u)
        self.assertIn('[水 伏 奇]', label)
        self.assertNotIn('骑', label)
        self.assertNotIn('弓', label)
        self.assertNotIn('无双', label)
        u['on_water'] = True
        self.assertEqual(boat_sprite(s, u), 'warship.png')
        s['entities']['generals'][0]['skill_mask_raw'] &= ~4
        self.assertEqual(boat_sprite(s, u), 'boat.png')
        for kind in ('强弓兵', '重装弓兵', '弩兵', '连弩', '运输兵'):
            u['unit_kind'] = kind
            self.assertEqual(attack_label(u), '—')
            self.assertNotIn('(攻:', unit_label(s, u))
            self.assertNotIn('攻击', memory_line(u))

    def test_archive_retains_counter_state_without_changing_source(self):
        import struct
        from game_archive import compact_state
        s = scenario(); u = s['entities']['field_units'][0]
        b = bytearray(168); b[0xd] = 3
        struct.pack_into('<H', b, 0x7e, 2); struct.pack_into('<I', b, 0x5e, 9)
        u['raw_hex'] = b.hex(); original = copy.deepcopy(s)
        saved = compact_state(s)['entities']['field_units'][0]
        self.assertEqual((saved['unit_state_flags_raw'], saved['native_order_type_raw'], saved['native_order_payload_raw']), (3, 2, 9))
        self.assertNotIn('raw_hex', saved)
        self.assertEqual(s, original)


if __name__ == '__main__':
    unittest.main()
