import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from force_compare import COLS, NOTE, SKILL_COLS, _cell, best_politics, boost_stat, boosted_peaks, cavalry_strike, exceed_player, owned_officers, solo_ability, summarize, training_text


def officer(gid, owner, name='甲', pol=80, cha=10, **attrs):
    stats = {'lead': 80, 'war': 80, 'intel': 80, 'pol': pol, 'cha': cha}
    stats.update(attrs)
    return {
        'general_id_raw': gid, 'name': name, 'owner_raw': owner, 'status_code': 0,
        'attributes': stats,
    }


def force(fid, name, infantry_raw=72, cavalry_raw=150, bow_raw=20):
    return {
        'force_id': fid, 'name': name,
        'armament_raw': {'infantry': infantry_raw, 'cavalry': cavalry_raw, 'bow': bow_raw},
    }


class ForceCompareTests(unittest.TestCase):
    def test_efficiency_is_highest_politics_not_stock_or_charm(self):
        self.assertIn('最高政治', NOTE)
        self.assertIn('可超过100', NOTE)
        self.assertIn('不看库存档位', NOTE)
        self.assertIn('不看魅力', NOTE)
        self.assertIn('超过我方最高统武', NOTE)
        self.assertNotIn('战斗力', NOTE)
        self.assertEqual([title for _key, title, _width in COLS],
                         ['势力', '练兵效率', '统武', '骑战力', '步训练度', '骑训练度', '弓训练度', '步兵数', '骑兵数', '弓兵数', '部队数', '最高骑战力', '骑', '弓', '伏'])
        self.assertIn('部队数是该势力当前出征部队的支数', NOTE)
        self.assertIn('最高骑战力是这些部队里骑兵', NOTE)
        self.assertIn('force-compare-unit-peak-cav', (Path(__file__).resolve().parents[1] / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertNotIn('库存', ''.join(title for _key, title, _width in COLS))
        self.assertEqual(training_text('cavalry', 150), '强化骑兵 50/100')
        self.assertIsNone(training_text('bow', None))
        self.assertEqual(best_politics([officer(1, 1, pol=40), officer(2, 1, pol=88, cha=99)]), 88)
        self.assertEqual(best_politics([officer(1, 1, '荀彧', pol=99), officer(2, 1, '迷乱', pol=116)]), 116)
        self.assertEqual(_cell(116, 'best_pol', {'trainer': '迷乱'}), '116 迷乱')
        self.assertIsNone(best_politics([]))

    def test_summarize_lists_politics_training_and_skill_counts(self):
        self.assertEqual([title for _key, title, _names in SKILL_COLS], ['骑', '弓', '伏'])
        wei_ge = officer(1, 1, '威哥', lead=115, war=70, intel=105, pol=95, cha=100)
        si_ma = officer(2, 1, '司马错', lead=87, war=82, intel=90, pol=63, cha=66)
        unmatched = officer(3, 1, '诸葛亮', pol=100, cha=100)
        custom = officer(5, 1, '迷乱', pol=116, cha=80)
        other = officer(4, 5, '威哥', lead=115, war=70, intel=105, pol=95, cha=100)
        state = {
            'player_identity': {'status': 'confirmed', 'force_id': 1},
            'player_force_id': 1,
            'entities': {
                'lords': [force(1, '赵'), force(5, '燕')],
                'generals': [wei_ge, si_ma, unmatched, custom, other],
            },
        }
        self.assertEqual([g['name'] for g in owned_officers(state, 1)], ['威哥', '司马错', '诸葛亮', '迷乱'])
        rows = {row['name']: row for row in summarize(state)}
        zhao, yan = rows['赵'], rows['燕']
        self.assertEqual(zhao['best_pol'], 116)
        self.assertEqual(zhao['trainer'], '迷乱')
        self.assertEqual(zhao['best_blade'], 185)
        self.assertEqual(zhao['blade_name'], '威哥')
        self.assertEqual(_cell(185, 'best_blade', zhao), '185 威哥')
        self.assertNotIn('best_combat', zhao)
        stronger = officer(6, 5, '白起', lead=120, war=90)
        tied = officer(7, 5, '同值', lead=100, war=85)
        state['entities']['generals'].extend([stronger, tied])
        self.assertEqual(exceed_player(state, 1), '当前是我方。最高统武 185 威哥')
        self.assertEqual(exceed_player(state, 5), '超过我方最高统武 185 威哥：210 白起')
        self.assertEqual(exceed_player(state, None), '我方最高统武 185 威哥。点一个势力，列出统武更高的一侧。')
        self.assertEqual(solo_ability(wei_ge), 92)
        self.assertEqual(cavalry_strike(92, 150), 322)
        self.assertEqual(zhao['cav_power'], 322)
        self.assertEqual(zhao['cav_power_name'], '威哥')
        self.assertEqual(_cell(322, 'cav_power', zhao), '322 威哥')
        weak = officer(8, 8, '弱将', lead=40, war=40)
        state['entities']['lords'].append(force(8, '齐', cavalry_raw=0))
        state['entities']['generals'].append(weak)
        self.assertEqual(
            exceed_player(state, 8),
            '我方超过对方最高统武 80 弱将：185 威哥、169 司马错、160 诸葛亮、160 迷乱',
        )
        equal = officer(10, 9, '同高', lead=115, war=70)
        state['entities']['lords'].append(force(9, '齐二'))
        state['entities']['generals'].append(equal)
        self.assertEqual(exceed_player(state, 9), '没有将超过对方最高统武 185 同高')
        self.assertEqual(exceed_player({'entities': state['entities']}, 5), '未确认我方，不能比较统武。')
        self.assertEqual(zhao['inf_train'], '步兵 72/100')
        self.assertEqual(zhao['cav_train'], '强化骑兵 50/100')
        self.assertEqual(zhao['bow_train'], '弓兵 20/100')
        self.assertIsNone(zhao['inf_soldiers'])
        self.assertEqual(_cell(None, 'inf_soldiers'), '—')
        self.assertEqual(_cell(12500, 'inf_soldiers'), '12,500')
        state['entities']['lords'][0]['troop_stock'] = {'infantry': 8000, 'cavalry': 1000, 'bow': 0}
        state['entities']['field_units'] = [
            {'owner_raw': 1, 'unit_kind': '重装步兵', 'soldiers_candidate': 14000},
            {'owner_raw': 1, 'unit_kind': '弓兵', 'soldiers_candidate': 6000},
            {'owner_raw': 5, 'unit_kind': '骑兵', 'soldiers_candidate': 9000},
        ]
        counted = {row['name']: row for row in summarize(state)}
        self.assertEqual(counted['赵']['inf_soldiers'], 22000)
        self.assertEqual(counted['赵']['unit_count'], 2)
        self.assertIsNone(counted['赵']['unit_cav'])
        self.assertEqual(_cell(None, 'unit_cav'), '—')
        state['entities']['field_units'].extend([
            {'owner_raw': 1, 'unit_kind': '重装步兵', 'target_attack_unit': 900, 'general_ids': [1]},
            {'owner_raw': 1, 'unit_kind': '铁骑兵', 'target_attack_unit': 210, 'general_ids': [2]},
            {'owner_raw': 1, 'unit_kind': '骑兵', 'target_attack_unit': '280', 'combat_inputs': [{'name': '威哥'}]},
            {'owner_raw': 1, 'unit_kind': '运输兵', 'target_attack_unit': 50},
            {'owner_raw': 5, 'unit_kind': '骑兵', 'target_attack_unit': '缺参数', 'general_ids': [4]},
        ])
        peaked = {row['name']: row for row in summarize(state)}
        self.assertEqual(peaked['赵']['unit_count'], 6)
        self.assertEqual(peaked['赵']['unit_cav'], 280)
        self.assertEqual(peaked['赵']['unit_cav_name'], '威哥')
        self.assertEqual(_cell(280, 'unit_cav', peaked['赵']), '280 威哥')
        self.assertEqual(peaked['燕']['unit_count'], 2)
        self.assertIsNone(peaked['燕']['unit_cav'])
        self.assertEqual(counted['赵']['cav_soldiers'], 1000)
        self.assertEqual(counted['赵']['bow_soldiers'], 6000)
        self.assertEqual(counted['燕']['cav_soldiers'], 9000)
        self.assertIsNone(counted['燕']['inf_soldiers'])
        self.assertNotIn('inf_eff', zhao)
        self.assertNotIn('inf_gain', zhao)
        self.assertEqual(zhao['ride'], 2)
        self.assertEqual(zhao['bow_skill'], 1)
        self.assertEqual(zhao['ambush'], 2)
        self.assertEqual(zhao['tag'], 'player')
        self.assertEqual(yan['best_pol'], 95)
        self.assertEqual(yan['ride'], 1)
        self.assertEqual(yan['bow_skill'], 1)
        self.assertEqual(yan['ambush'], 1)

    def test_unmatched_officer_does_not_count_skills(self):
        with patch('force_compare.listed_skill_count', return_value=0) as count:
            state = {'entities': {
                'lords': [force(2, '齐')],
                'generals': [officer(9, 2, '无名')],
            }}
            row = summarize(state)[0]
            self.assertEqual(row['ride'], 0)
            self.assertEqual(count.call_count, 3)

    def test_hub_adds_compare_tab(self):
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertIn('from force_compare import ForceCompare', hub)
        self.assertIn("self.workspace.add(self.force_compare,text='势力对比')", hub)
        self.assertIn('self.force_compare.refresh()', hub)

    def test_gray_cards_raise_the_peak_they_touch(self):
        officers = [
            officer(1, 1, '统高', lead=100, war=40, pol=70),
            officer(2, 1, '武高', lead=60, war=90, pol=50),
            officer(3, 1, '政高', lead=50, war=50, pol=80),
        ]
        plain = boosted_peaks(officers, set())
        self.assertEqual((plain['blade'], plain['blade_name'], plain['blade_boosted']), (150, '武高', False))
        self.assertEqual((plain['pol'], plain['pol_name'], plain['pol_boosted']), (80, '政高', False))
        sword = boosted_peaks(officers, {18})
        self.assertEqual(sword['blade'], boost_stat(100) + 40)
        self.assertEqual((sword['blade_name'], sword['blade_boosted']), ('统高', True))
        self.assertFalse(sword['pol_boosted'])
        horse = boosted_peaks(officers, {19})
        self.assertEqual(horse['blade'], 60 + boost_stat(90))
        self.assertEqual((horse['blade_name'], horse['blade_boosted']), ('武高', True))
        book = boosted_peaks(officers, {20})
        self.assertEqual((book['pol'], book['pol_name'], book['pol_boosted']), (boost_stat(80), '政高', True))
        self.assertFalse(book['blade_boosted'])
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertNotIn('最高统武', hub)
        self.assertNotIn('最高政治', hub)


if __name__ == '__main__':
    unittest.main()
