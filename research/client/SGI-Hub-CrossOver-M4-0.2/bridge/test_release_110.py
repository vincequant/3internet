import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from battle_model import battle_candidates
from recruitment_summary import annual_recruitment,recruitment_text
from diplomacy_cards import card_rows

class NewReferences(unittest.TestCase):
 def test_recruitment_by_city_owner_and_missing_not_zero(self):
  def city(owner,amount):return {'type':'city','owner_raw':owner,'recruitment_capacity':{'amounts':dict.fromkeys(('infantry','cavalry','bow'),amount)}}
  s={'entities':{'cities_and_barriers':[city(0,2000),city(0,3000),city(11,9000),{'type':'barrier','owner_raw':0}]}}
  self.assertEqual(annual_recruitment(s,0)['infantry']['known'],5000)
  self.assertEqual(annual_recruitment(s,21)['infantry']['known'],0)
  s['entities']['cities_and_barriers'].append(city(0,None));v=annual_recruitment(s,0)['bow']
  self.assertEqual(v['missing'],1);self.assertIn('未知',recruitment_text(v))
  self.assertIn('未采集',recruitment_text(annual_recruitment({},0)['bow']))
 def test_cards_follow_hand_unknown_is_not_known(self):
  f={'hand_cards':{'slots':[{'slot':1,'card_id':18,'name':'倚天剑'},{'slot':2,'card_id':0,'name':'空槽'},{'slot':3,'card_id':999,'name':'未知'}]}}
  rows=card_rows(f);self.assertEqual(rows[0]['points'],'100');self.assertEqual(rows[1]['category'],'空槽');self.assertEqual(rows[2]['points'],'未核实')
  self.assertEqual(card_rows({}),[])
class BattleCandidates(unittest.TestCase):
 def state(self):
  def u(i,o,x,y):return {'unit_id':i,'owner_raw':o,'world_xy_raw':[x,y]}
  return {'entities':{'lords':[{'force_id':0,'name':'魏'},{'force_id':11,'name':'宋'}],'cities_and_barriers':[{'city_id':1,'name':'许昌','world_xy_raw':[12,12]}], 'field_units':[u(0,0,10,10),u(1,11,15,15),u(2,11,16,16)]}}
 def test_inclusive_five_not_six_same_force_and_pair_once(self):
  rows=battle_candidates(self.state());self.assertEqual([r['key'] for r in rows],['0:1']);self.assertEqual(rows[0]['distance'],5);self.assertEqual(rows[0]['name'],'许昌附近战役')
 def test_invalid_duplicate_and_no_false_fights(self):
  s=self.state();s['entities']['field_units'].append(copy.deepcopy(s['entities']['field_units'][0]));self.assertEqual(battle_candidates(s),[])
  s=self.state();s['entities']['field_units'][0]['world_xy_raw']=[-1,-1];self.assertEqual(battle_candidates(s),[])
  s=self.state();s['entities']['field_units'][0]['owner_raw']=65535;self.assertEqual(battle_candidates(s),[])
 def test_move_out_ends_candidate_and_no_city_supported(self):
  s=self.state();s['entities']['cities_and_barriers']=[];self.assertEqual(battle_candidates(s)[0]['name'],'野外战役')
  s['entities']['field_units'][0]['world_xy_raw']=[0,0];self.assertEqual(battle_candidates(s),[])
