"""Calculator regression against independently verified native examples/frames."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from attack_calculator_model import calculate, calculation_text, from_unit
from unit_target_attack import PARAMS


class AttackCalculatorTests(unittest.TestCase):
    def inputs(self, **changes):
        v = dict(kind='强化骑兵', soldiers=12000, training=60, morale=75,
                 officers=[dict(lead=80, war=80)], horse=True, arrow=True, on_water=False)
        v.update(changes)
        return v

    def test_native_fixed_examples_and_half_skill(self):
        for changes, pair in (({}, (388,520)), ({'horse':False}, (193,258)),
                              ({'on_water':True}, (118,520)),
                              ({'on_water':True,'horse':False}, (118,258)),
                              ({'kind':'重装步兵'}, (447,599)),
                              ({'kind':'强弓兵'}, (452,605)),
                              ({'kind':'强弓兵','arrow':False}, (226,302))):
            with self.subTest(changes=changes):
                r = calculate(**self.inputs(**changes))
                self.assertEqual((r['current'],r['land_full']), pair)
        r = calculate(**self.inputs(training=2,horse=False))
        self.assertEqual(r['before_skill'],151);self.assertEqual(r['land_coefficient'],75)

    def test_size_boundaries_morale_zero_and_training_endpoints(self):
        for soldiers, size in ((1,0),(20000,0),(20001,1),(35000,1),(35001,2),(100000,2)):
            r = calculate(**self.inputs(soldiers=soldiers,training=0,morale=0))
            self.assertEqual(r['size'],size);self.assertEqual(r['current'],0)
            self.assertGreater(r['land_full'],0)
        for kind, expected in (('步兵',150),('强化步兵',170),('重装步兵',190),
                               ('骑兵',125),('强化骑兵',175),('重装骑兵',225),
                               ('弓兵',100),('强弓兵',240),('重装弓兵',360)):
            self.assertEqual(calculate(**self.inputs(kind=kind,training=100))['land_coefficient'],expected)

    def test_formation_leader_weight_and_treasure_rounding(self):
        r = calculate(**self.inputs(officers=[dict(lead=100,war=90),dict(lead=80,war=60),dict(lead=60,war=30)]))
        self.assertEqual((r['lead'],r['war'],r['ability']),(85,60,72))
        r = calculate(**self.inputs(officers=[dict(lead=94,war=87,lead_bonus=True,war_bonus=True)]))
        self.assertEqual((r['lead'],r['war'],r['ability']),(131,121,126))
        self.assertEqual(calculate(**self.inputs(officers=[dict(lead=0,war=0)]))['ability'],5)

    def test_water_independence_and_bow_separate_branch(self):
        for kind in PARAMS:
            r = calculate(**self.inputs(kind=kind,on_water=True,training=80,morale=79,officers=[dict(lead=79,war=79)]))
            if '弓兵' in kind:
                self.assertEqual(r['current_coefficient'],r['land_coefficient'])
                self.assertEqual(r['mode'],'远射');self.assertIn('不能与步骑近战',calculation_text(r))
            else:
                self.assertEqual(r['current_coefficient'],50)
                self.assertEqual(r['current'],122)
        r = calculate(**self.inputs(on_water=True,training=80,morale=79,officers=[dict(lead=79,war=79)]))
        self.assertEqual(r['land_full'],529)

    def test_missing_invalid_and_boolean_numeric_inputs_rejected(self):
        for changes in ({'soldiers':0},{'training':101},{'morale':-1},{'morale':True},
                        {'officers':[]},{'officers':[dict(lead=None,war=80)]},
                        {'officers':[dict(lead=80,war=256)]},{'horse':None},{'kind':'运输兵'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                calculate(**self.inputs(**changes))

    def test_actual_recorded_frame_matches_existing_map_values_without_mutation(self):
        fixture = json.loads((Path(__file__).parent/'native-map-321-fixture.json').read_text())
        state = fixture['state'];before = copy.deepcopy(state)
        expected = {u['unit_id']:u for u in fixture['expected_units']}
        full = {27:1024,28:498,32:246}
        from unit_combat import enrich_unit_combat
        derived = enrich_unit_combat(copy.deepcopy(state))
        mapped = {u['unit_id']:u for u in derived['entities']['field_units']}
        for u in state['entities']['field_units']:
            r = calculate(**from_unit(state,u))
            self.assertEqual(r['current'],expected[u['unit_id']]['engine_consumer_pre_random_component'])
            self.assertEqual(r['land_full'],full[u['unit_id']])
            self.assertEqual(r['current'],mapped[u['unit_id']]['native_attack_index'])
            self.assertEqual(r['land_full'],mapped[u['unit_id']]['native_attack_index_full_morale'])
        self.assertEqual(state,before)
        u = copy.deepcopy(state['entities']['field_units'][0]);u.pop('raw_hex',None);u.pop('armament_degree_raw',None)
        with self.assertRaises(ValueError):from_unit(state,u)
        bad = copy.deepcopy(state);bad['build_sha256']='unknown'
        with self.assertRaises(ValueError):from_unit(bad,state['entities']['field_units'][0])

if __name__ == '__main__':unittest.main()
