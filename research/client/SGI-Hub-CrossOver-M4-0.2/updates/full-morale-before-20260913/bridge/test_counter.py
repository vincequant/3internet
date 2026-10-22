import copy
import unittest
from unittest.mock import patch
from test_preparation import state
from counter_model import targets, initiative, compare, counter_recommend, candidate_cache


def fixture():
    s=state(); s['entities']['lords'][0]['diplomacy_relations']=[0]*22
    s['entities']['lords'][0]['diplomacy_relations'][1]=1
    s['entities']['lords'].append(dict(force_id=1,name='敌'))
    u=dict(unit_id=5,owner_raw=1,unit_kind='步兵',morale=90,general_ids=[],
           basic_combat_power=60,target_attack_components={'unit':[50]})
    s['entities']['field_units']=[u]
    return s,u


class CounterTests(unittest.TestCase):
    def test_target_relationships(self):
        s,u=fixture(); self.assertEqual(targets(s),[u])
        for relation in (0,2,3):
            s['entities']['lords'][0]['diplomacy_relations'][1]=relation
            self.assertFalse(targets(s)); self.assertEqual(bool(targets(s,True)),relation==0)
        s['player_identity']['status']='unknown'; self.assertFalse(targets(s,True))

    def test_strict_comparison(self):
        self.assertEqual(compare({'attack':[100]},[100]),'未超过（含持平）')
        self.assertEqual(compare({'attack':[101,120]},[90,100]),'参考攻击严格超过')
        self.assertEqual(compare({'attack':[50,120]},[90,100]),'仅部分技能情景超过')
        self.assertEqual(compare({'attack':[100]},None),'敌攻击缺参数')

    def test_initiative_not_attack_threshold(self):
        self.assertIn('需士气≥91',initiative(90,90))
        self.assertIn('出场估算可先手',initiative(91,90))
        self.assertIn('先后随机',initiative(100,100))
        self.assertIn('未知',initiative(95,None))

    def test_live_candidates_readonly_and_unknown_build(self):
        s,u=fixture(); before=copy.deepcopy(s)
        result=counter_recommend(s,u)
        self.assertTrue(result['physical']); self.assertEqual(s,before)
        self.assertTrue(any(r['comparison']=='参考攻击严格超过' for r in result['physical']))
        s['build_sha256']='unknown'; self.assertFalse(counter_recommend(s,u)['physical'])

    def test_spells_only_infantry_and_unknown_defence(self):
        s,u=fixture(); candidate_cache.cache_clear()
        with patch('preparation_model.skills_for',return_value={'火攻','计谋'}), patch('counter_model.skills_for',return_value={'火攻','计谋'}):
            r=counter_recommend(s,u)
        candidate_cache.cache_clear()
        self.assertTrue(r['spells'])
        for row in r['spells']:
            self.assertEqual(row['kind'],'infantry'); self.assertIn('不代表没有',row['counter'])


if __name__=='__main__':unittest.main()
