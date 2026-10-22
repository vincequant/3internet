import unittest
from website_combat import attack,factor
from unit_target_attack import enrich_targets,BUILD,rnd,unit_factor,client_factor
from unit_combat import enrich_unit_combat
from native_unit_rules import attack_index,ATTACK_MODEL
from test_preparation import general,formation,training_bases

class WebsiteCombat(unittest.TestCase):
    def test_screenshot_and_calculator_examples(self):
        self.assertEqual(attack('重装步兵',0,300,100),207)
        self.assertEqual(attack('重装步兵',0,100,100),153)
        self.assertEqual(attack('重装步兵',1,50,80),165)
        self.assertEqual(attack('重装步兵',2,100,91),261)
        self.assertEqual(attack('骑兵',2,100,100),333)
        self.assertEqual(factor('重装步兵',1,100),330)
        self.assertIsNone(attack('弓兵',0,100,100))
        self.assertIsNone(attack('步兵',0,100,None))
    def test_native_display_and_website_reference_keep_separate_scales(self):
        g=general(1,lead=100,war=100,status=2)
        g.update(skill_mask_raw=1,combat_modifier_flags_word=0)
        for kind in ['步兵','强化步兵','重装步兵','骑兵','强化骑兵','重装骑兵']:
            for degree in [0,50,100]:
                u=dict(unit_kind=kind,owner_raw=20,general_ids=[1],soldiers_candidate=22000,armament_degree_raw=degree,raw_1d=100,on_water=False)
                s=dict(build_sha256=BUILD,entities=dict(generals=[g],field_units=[u]))
                enrich_unit_combat(s)
                expected=attack(kind,1,degree,100)
                self.assertEqual(u['website_attack_power'],expected)
                shown=rnd(unit_factor(kind,1,degree)*100/150)
                self.assertEqual(shown,expected)
                self.assertEqual(u['target_attack_unit'],str(attack_index(client_factor(kind,1,degree),100,100)))
                self.assertEqual(u['attack_model'],ATTACK_MODEL)
                self.assertNotEqual(u['target_attack_unit'],str(expected))
    def test_bow_uses_client_table(self):
        u=dict(unit_kind='强弓兵',owner_raw=20,size_index=1,training_degree=39,basic_combat_power=100,general_ids=[1],on_water=False,morale=100)
        g=dict(general_id_raw=1,owner_raw=20,status_code=2,skill_mask_raw=0,combat_modifier_flags_word=0)
        enrich_targets(dict(build_sha256=BUILD,entities=dict(field_units=[u],generals=[g])))
        self.assertEqual(unit_factor('强弓兵',1,39),235)
        self.assertEqual(unit_factor('弩兵',0,39),167)
        self.assertEqual(u['target_attack_components']['unit'],[117])
        self.assertEqual(u['target_attack_unit'],'439')
        self.assertEqual(u['target_attack_melee'],'—')
    def test_planning_reference_does_not_substitute_for_native_index(self):
        g=general(1,soldiers=12000,lead=100,war=100)
        f={'troop_stock':{'infantry':20000},'prestige':100}
        r=formation(f,'infantry',[g],training_bases('infantry',300),{1:set()})
        self.assertEqual(r['training'],100)
        self.assertEqual(r['attack'],[153])
        u=dict(unit_kind='重装步兵',size_index=0,training_degree=100,basic_combat_power=100,general_ids=[],on_water=False,morale=100)
        enrich_targets(dict(build_sha256=BUILD,entities=dict(field_units=[u],generals=[])))
        self.assertEqual(u['target_attack_unit'],'713')
        self.assertEqual(u['target_attack_components']['reference_unit'],[230])

if __name__=='__main__':unittest.main()
