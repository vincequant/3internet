import copy
from pathlib import Path
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parent.parent/'app'), str(Path(__file__).resolve().parent)]
from preparation_model import (BUILD, SIZES, training_bases, combat_power, size_index, recommend,
    formation, useful_skills, advise_gap, destination_unit, grade_short, kind_ceiling,
    lowest_training_to_beat, training_to_beat, parse_target, reference_attack, training_path_text,
    reach_band, troop_tier, row_grade, annotate_candidate)
from unit_combat import enrich_unit_combat

def general(gid, soldiers=7000, lead=90, war=80, status=0):
    return dict(general_id_raw=gid, name='测试'+str(gid), owner_raw=20,
                soldiers=soldiers, attributes=dict(lead=lead,war=war,intel=80,pol=70,cha=60),
                status_code=status, combat_modifier_flags=0)

def state():
    return dict(build_sha256=BUILD,player_force_id=20,player_identity=dict(status='confirmed',force_id=20),
                entities=dict(lords=[dict(force_id=20,name='汉',prestige=169,
                                         troop_stock=dict(infantry=23500,cavalry=8860,bow=6500),
                                         armament_raw=dict(infantry=93,cavalry=221,bow=139))],
                              generals=[general(1,14000,84,100,2),general(2,7000,110,60),general(3,5000,81,94)],field_units=[]))

def keep_enemy_generals(s, own):
    s['entities']['generals'] = own + [g for g in s['entities']['generals'] if g.get('owner_raw') == 1]

def infantry_row(result, label='攻击优先'):
    return next(r for r in result['rows'] if r['kind'] == 'infantry' and r['label'] == label)

class Preparation(unittest.TestCase):
    def test_known_training_bases_and_boundaries(self):
        self.assertEqual(training_bases('infantry',93)['unit'],[143,243,343])
        self.assertEqual(training_bases('cavalry',221)['unit'],[211,361,561])
        self.assertEqual(training_bases('bow',139)['unit'],[167,235,302])
        self.assertEqual([size_index(n) for n in (20000,20001,35000,35001)],[0,1,1,2])
        self.assertIsNone(training_bases('bow',None))

    def test_stock_caps_and_promotion_despite_lower_combat(self):
        s=state();f=s['entities']['lords'][0];gs=[general(1,14000,100,100),general(2,7000,60,60)]
        known={1:set(),2:set()}
        r=formation(f,'infantry',gs,training_bases('infantry',93),known)
        self.assertEqual(r['soldiers'],21000);self.assertEqual(r['size'],1)
        self.assertLess(r['power'],r['leader_power']);self.assertGreater(r['attack'][0],r['baseline'][0])
        r=formation(f,'cavalry',gs,training_bases('cavalry',221),known)
        self.assertEqual(r['soldiers'],8860);self.assertEqual(r['size'],0)
        self.assertEqual(len(r['attack']),1)

    def test_combat_matches_existing_decoder_for_order_and_modifiers(self):
        for flags in (0,0x10,0x20,0x30):
            s=state();gs=s['entities']['generals'];gs[0]['combat_modifier_flags']=flags
            for n in (1,2,3):
                selected=copy.deepcopy(gs[:n])
                for g in selected:g['status_code']=2
                u=dict(unit_kind='步兵',owner_raw=20,general_ids=[g['general_id_raw'] for g in selected],soldiers_candidate=21000,armament_degree_raw=93,raw_1d=80)
                st=dict(build_sha256=BUILD,entities=dict(generals=selected,field_units=[u]))
                enrich_unit_combat(st)
                self.assertEqual(combat_power(selected),u['basic_combat_power'])

    def test_morale_is_estimate_and_cap(self):
        s=state();f=s['entities']['lords'][0];gs=s['entities']['generals'][:1]
        r=formation(f,'infantry',gs,training_bases('infantry',93),{1:set()})
        self.assertEqual(r['morale'],88.25)
        f['prestige']=400
        self.assertEqual(formation(f,'infantry',gs,training_bases('infantry',93),{1:set()})['morale'],100)
        f['prestige']=None
        self.assertIsNone(formation(f,'infantry',gs,training_bases('infantry',93),{1:set()})['morale'])

    def test_identity_version_status_duplicate_and_readonly(self):
        s=state();before=copy.deepcopy(s)
        self.assertFalse(recommend(s)['rows'])
        self.assertIn('填写', recommend(s)['message'])
        self.assertTrue(recommend(s, target=0, leader_id=1)['rows']);self.assertEqual(s,before)
        s['player_identity']['status']='unknown';self.assertFalse(recommend(s, target=0, leader_id=1)['rows'])
        s=state();s['build_sha256']='other';self.assertFalse(recommend(s, target=0, leader_id=1)['rows'])
        s=state();s['entities']['generals'][1]['status_code']=6
        s['entities']['generals'].append(copy.deepcopy(s['entities']['generals'][2]))
        result=recommend(s, target=0, leader_id=1);self.assertEqual(result['eligible'],1)
        self.assertTrue(all(r['ids'][0]==1 and r['returning'] for r in result['rows']))
        self.assertFalse(recommend(s, False, target=0)['rows'])

    def test_deployed_members_excluded_even_status_lags_and_no_duplicates(self):
        s=state();s['entities']['field_units']=[dict(general_ids=[2])]
        result=recommend(s, False, target=0)
        self.assertEqual(result['eligible'],1)
        lead=result['leaders'][0]['id']
        for r in recommend(s, target=0, leader_id=lead)['rows']:
            self.assertEqual(r['ids'][0], lead)
            self.assertEqual(len(r['ids']),len(set(r['ids'])))
            self.assertLessEqual(r['soldiers'],s['entities']['lords'][0]['troop_stock'][r['kind']])

    def test_cavalry_spells_not_counted_and_deputy_proficiency(self):
        self.assertEqual(useful_skills('cavalry',{'骑马','无双','天雷','火攻','计谋'}),{'骑马','无双'})
        s=state();f=s['entities']['lords'][0];gs=s['entities']['generals'][:2]
        r=formation(f,'cavalry',gs,training_bases('cavalry',221),{1:set(),2:{'骑马'}})
        self.assertTrue(r['qualified']);self.assertEqual(r['added'],['骑马']);self.assertEqual(len(r['attack']),1)

    def test_parse_target_and_blank_gives_no_rows(self):
        self.assertEqual(parse_target(' 120 '), 120)
        self.assertEqual(parse_target('1,200'), 1200)
        self.assertEqual(parse_target(80), 80)
        self.assertIsNone(parse_target(''))
        self.assertIsNone(parse_target('abc'))
        result = recommend(state())
        self.assertIsNone(result['enemy'])
        self.assertFalse(result['rows'])
        self.assertIn('填写', result['message'])

    def test_leaders_sorted_by_solo_unit_attack(self):
        result = recommend(state())
        leaders = result['leaders']
        self.assertTrue(leaders)
        attacks = [row['attack'] for row in leaders]
        self.assertEqual(attacks, sorted(attacks, reverse=True))
        self.assertTrue(all('attack_kind' in row for row in leaders))
        self.assertFalse(recommend(state(), target=50)['rows'])
        self.assertIn('主将', recommend(state(), target=50)['message'])

    def test_typed_target_uses_current_roster(self):
        result = recommend(state(), target=50, leader_id=1)
        self.assertEqual(result['enemy'], {'value': 50, 'label': '填写数值'})
        self.assertTrue(result['rows'])
        kinds = set()
        for row in result['rows']:
            self.assertEqual(row['ids'][0], 1)
            self.assertIn(row['source'], ('leader', 'short'))
            if row['source'] == 'leader':
                self.assertGreater(min(row['attack']), 50)
                self.assertEqual(row['band'], 'ready')
                self.assertIn(row.get('grade'), (0, 1, 2))
                self.assertIn('>>', row['versus'])
                self.assertTrue(row['label'].startswith('单出') or row['label'].startswith('加副将'))
            kinds.add(row['kind'])
        self.assertIn('infantry', kinds)
        self.assertIn('cavalry', kinds)
        self.assertIn('主将', result['message'])

    def test_typed_target_shows_minimum_training_when_already_ahead(self):
        result = recommend(state(), target=20, leader_id=1)
        self.assertTrue(result['rows'])
        for row in result['rows']:
            if row.get('source') != 'leader':
                continue
            step = lowest_training_to_beat(row['kind'], row['size'], row['power'], 20)
            self.assertEqual(step['raw'], 0)
            self.assertIn('未训就够', row['versus'])
            self.assertEqual(row['band'], 'ready')
            self.assertIn('>>', row['versus'])
            self.assertNotIn('已过', row['versus'])

    def test_typed_target_trains_when_current_cannot(self):
        s = state()
        keep_enemy_generals(s, [general(1, 8000, 100, 84)])
        s['entities']['lords'][0]['troop_stock'] = dict(infantry=8000, cavalry=0, bow=0)
        result = recommend(s, target=97, leader_id=1)
        row = next(r for r in result['rows'] if r['kind'] == 'infantry' and r.get('source') == 'leader')
        self.assertEqual((row['power'], row['attack']), (92, [88]))
        self.assertEqual(result['enemy']['value'], 97)
        step = training_to_beat('infantry', 93, row['size'], row['power'], 97)
        self.assertTrue(step and step['raw'] is not None)
        self.assertEqual(row['ids'][0], 1)
        self.assertNotIn('训练倒推', row['label'])
        self.assertIn(f'去到 {step["name"]} {step["training"]}', row['versus'])
        self.assertEqual(row['band'], 'train')
        self.assertNotIn('未过', row['versus'])

    def test_pick_training_sorts_when_none_can_beat(self):
        result = recommend(state(), target=9999, leader_id=1)
        self.assertTrue(all(row.get('source') == 'short' for row in result['rows']))
        self.assertTrue(all(row.get('band') == 'fail' for row in result['rows']))
        self.assertTrue(any('过不了' in (row.get('versus') or '') or '过不了' in result['message'] for row in result['rows'])
                        or '过不了' in result['message'])

    def test_cannot_beat_even_at_full_training(self):
        s = state()
        keep_enemy_generals(s, [general(1, 1000, 15, 15)])
        s['entities']['lords'][0]['troop_stock'] = dict(infantry=1000, cavalry=0, bow=0)
        result = recommend(s, target=97, leader_id=1)
        self.assertTrue(result['rows'] == [] or all(row.get('source') == 'short' for row in result['rows']))
        self.assertIn('过不了', result['message'] + ''.join(row.get('versus') or '' for row in result['rows']))

    def test_stock_over_old_cap_includes_infantry(self):
        s = state()
        s['entities']['lords'][0]['troop_stock'] = dict(infantry=106690, cavalry=32690, bow=32970)
        result = recommend(s, target=50, leader_id=1)
        kinds = {row['kind'] for row in result['rows'] if row.get('source') == 'leader'}
        self.assertIn('infantry', kinds)
        self.assertIn('cavalry', kinds)
        self.assertTrue(all(row['ids'][0] == 1 for row in result['rows'] if row.get('source') == 'leader'))

    def test_kind_ceiling_picks_highest_full_train(self):
        weak = {'kind': 'infantry', 'size': 0, 'power': 50, 'attack': [40], 'ids': (1,),
                'troop': '步兵', 'training': 10}
        strong = {'kind': 'infantry', 'size': 1, 'power': 89, 'attack': [159], 'ids': (2, 3),
                  'troop': '强化步兵', 'training': 25}
        row, top = kind_ceiling([weak, strong])
        self.assertEqual(row['ids'], (2, 3))
        self.assertEqual(top, reference_attack('infantry', 300, 1, 89))

    def test_missing_kind_is_explained_when_full_train_falls_short(self):
        s = state()
        s['entities']['lords'][0]['troop_stock'] = dict(infantry=106690, cavalry=32690, bow=0)
        for g, n in zip(s['entities']['generals'], (14000, 10000, 8000)):
            g['soldiers'] = n
        result = recommend(s, target=200, leader_id=1)
        self.assertTrue(result['rows'])
        self.assertTrue(all(row['ids'][0] == 1 for row in result['rows']))
        if not any(row['kind'] == 'infantry' and row.get('source') == 'leader' for row in result['rows']):
            self.assertTrue(any(row.get('source') == 'short' and row['kind'] == 'infantry' for row in result['rows']))

    def test_advise_gap_reassign_and_same_formation_training(self):
        weak = {'kind': 'infantry', 'size': 0, 'power': 92, 'attack': [88], 'ids': (1,),
                'generals': [{'name': '弱将', 'general_id_raw': 1}]}
        strong = {'kind': 'infantry', 'size': 0, 'power': 120, 'attack': [130], 'ids': (2, 3),
                  'generals': [{'name': '赵云', 'general_id_raw': 2}, {'name': '关羽', 'general_id_raw': 3}]}
        text = advise_gap('infantry', 93, weak, {'value': 97, 'label': '魏 · 强化步兵 #7'}, [weak, strong])
        self.assertIn('改配', text)
        self.assertIn('赵云', text)
        self.assertIn('关羽', text)
        step = training_to_beat('infantry', 93, 0, 92, 97)
        self.assertIn(grade_short(step), text)
        self.assertNotIn('累计', text)
        self.assertIn('同编制', text)

    def test_versus_uses_kind_bar_not_raw_total(self):
        row = {'troop': '骑兵', 'training': 21, 'size': 1, 'leader_size': 1, 'attack': [174]}
        step = {'raw': 175, 'attack': 201, 'training': 75, 'name': '强化骑兵'}
        self.assertEqual(training_path_text(row, step), '骑兵 21 >> 去到 强化骑兵 75')
        self.assertEqual(destination_unit(row, step), '强化骑兵中队')
        self.assertNotIn('174', training_path_text(row, step))
        self.assertEqual(training_path_text(row, {'raw': 0, 'attack': 148, 'training': 0, 'name': '骑兵'}),
                         '骑兵 21 >> 未训就够')
        row['leader_size'] = 0
        self.assertIn('加副将凑中队', training_path_text(row, step))

    def test_reach_band_ready_train_fail(self):
        ready = {'attack': [88], 'source': 'leader', 'training_step': {'raw': 0, 'attack': 40}}
        train = {'attack': [88], 'source': 'leader', 'training_step': {'raw': 110, 'attack': 100}}
        fail = {'attack': [88], 'source': 'short', 'training_step': {'raw': None, 'attack': 90}}
        self.assertEqual(reach_band(ready, 50), 'ready')
        self.assertEqual(reach_band(train, 97), 'train')
        self.assertEqual(reach_band(fail, 97), 'fail')
        self.assertEqual(reach_band({'attack': [88], 'source': 'leader'}, 97), 'fail')

    def test_troop_tier_base_mid_high(self):
        self.assertEqual(troop_tier('轻骑兵'), 0)
        self.assertEqual(troop_tier('骑兵 87'), 0)
        self.assertEqual(troop_tier('强化骑兵中队'), 1)
        self.assertEqual(troop_tier('铁骑兵'), 2)
        self.assertEqual(troop_tier('重装骑兵中队'), 2)
        self.assertEqual(troop_tier('强化步兵'), 1)
        self.assertEqual(row_grade({'troop': '骑兵', 'training_step': {'name': '重装骑兵'}}), 2)

    def test_already_beating_does_not_downgrade_heavy_infantry(self):
        row = {'kind': 'infantry', 'size': 0, 'power': 120, 'attack': [200], 'ids': (1,),
               'troop': '重装步兵', 'training': 19, 'leader_size': 0}
        item = annotate_candidate(row, 219, 100)
        self.assertEqual(item['band'], 'ready')
        self.assertIn('已过', item['versus'])
        self.assertNotIn('强化步兵', item['versus'])
        self.assertNotIn('去到', item['versus'])
        self.assertIn('重装步兵', item['label'])
        self.assertNotIn('强化步兵', item['label'])
        self.assertEqual(parse_target('10330'), 10330)

    def test_training_to_beat_stays_at_or_above_current_grade(self):
        step = training_to_beat('infantry', 219, 0, 50, 9999)
        if step and step.get('raw') is not None:
            self.assertGreater(step['raw'], 219)
            self.assertEqual(step['name'], '重装步兵')

if __name__=='__main__':unittest.main()
