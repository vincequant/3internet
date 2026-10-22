import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from preparation_model import BUILD, training_bases, combat_power, size_index, recommend, formation, useful_skills
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

class Preparation(unittest.TestCase):
    def test_known_training_bases_and_boundaries(self):
        self.assertEqual(training_bases('infantry',93)['unit'],[143,243,343])
        self.assertEqual(training_bases('cavalry',221)['unit'],[205,355,555])
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
        self.assertEqual(len(r['attack']),2)

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
        s=state();before=copy.deepcopy(s);self.assertTrue(recommend(s)['rows']);self.assertEqual(s,before)
        s['player_identity']['status']='unknown';self.assertFalse(recommend(s)['rows'])
        s=state();s['build_sha256']='other';self.assertFalse(recommend(s)['rows'])
        s=state();s['entities']['generals'][1]['status_code']=6
        s['entities']['generals'].append(copy.deepcopy(s['entities']['generals'][2]))
        result=recommend(s);self.assertEqual(result['eligible'],1)
        self.assertTrue(all(r['ids']==(1,) and r['returning'] for r in result['rows']))
        self.assertFalse(recommend(s,False)['rows'])

    def test_deployed_members_excluded_even_status_lags_and_no_duplicates(self):
        s=state();s['entities']['field_units']=[dict(general_ids=[2])]
        result=recommend(s,False)
        self.assertEqual(result['eligible'],1)
        for r in recommend(s)['rows']:
            self.assertEqual(len(r['ids']),len(set(r['ids'])))
            self.assertLessEqual(r['soldiers'],s['entities']['lords'][0]['troop_stock'][r['kind']])

    def test_cavalry_spells_not_counted_and_deputy_proficiency(self):
        self.assertEqual(useful_skills('cavalry',{'骑马','无双','天雷','火攻','计谋'}),{'骑马','无双'})
        s=state();f=s['entities']['lords'][0];gs=s['entities']['generals'][:2]
        r=formation(f,'cavalry',gs,training_bases('cavalry',221),{1:set(),2:{'骑马'}})
        self.assertTrue(r['qualified']);self.assertEqual(r['added'],['骑马']);self.assertEqual(len(r['attack']),1)

if __name__=='__main__':unittest.main()
