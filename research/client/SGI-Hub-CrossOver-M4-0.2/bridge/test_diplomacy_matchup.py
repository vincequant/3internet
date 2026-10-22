"""Native points, white-card reversal, tie direction and unknown inputs."""
import sys,struct,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from diplomacy_matchup_model import card_pack,envoy_score,matchup_rows

def card(slot,cid,name=None):return dict(slot=slot,card_id=cid,name=name or str(cid))
def force(fid,cards):return dict(force_id=fid,name=str(fid),hand_cards={'slots':cards})
def general(fid,pol=80,cha=80,skills=0,flags=0,status=0):
 b=bytearray(96);struct.pack_into('<h',b,8,fid);struct.pack_into('<h',b,10,fid);struct.pack_into('<h',b,0x21,status);b[0x28]=pol;b[0x29]=cha;struct.pack_into('<I',b,0x2a,skills);struct.pack_into('<H',b,0x44,flags)
 return dict(owner_raw=fid,name='使者'+str(fid),raw_hex=b.hex())
def state(a,b,ga=None,gb=None):return dict(entities=dict(lords=[a,b],generals=[ga or general(1),gb or general(2)]))
class DiplomacyMatchup(unittest.TestCase):
 def test_white_card_is_an_explicit_scenario_and_native_points(self):
  f=force(1,[card(1,1),card(2,17),card(3,16),card(4,28),card(5,14)])
  self.assertEqual(card_pack(f,'主动')['card_points'],170)
  white=card_pack(f,'主动',True);self.assertEqual(white['card_points'],670);self.assertTrue(white['seal'])
 def test_swap_cards_never_supplement(self):
  f=force(1,[card(1,9),card(2,21),card(3,22),card(4,23),card(5,28)])
  self.assertEqual([c['card_id'] for c in card_pack(f,'被动',True)['chosen']],[9,23,28])
 def test_four_supplement_limit(self):
  f=force(1,[card(1,1)]+[card(i,cid) for i,cid in enumerate((28,27,26,12,14),2)])
  p=card_pack(f,'主动');self.assertEqual(len(p['chosen']),5);self.assertEqual(p['card_points'],210);self.assertTrue(p['trimmed'])
 def test_native_skill_and_treasure_without_website_match(self):
  g=general(1,97,96,0x80000|0x20000,0x40)
  self.assertEqual(envoy_score(g,'策反')['actor'],277)
  self.assertEqual(envoy_score(g,'主动')['actor'],277)
  self.assertEqual(envoy_score(g,'被动')['actor'],231)
  self.assertIsNone(envoy_score({'attributes':{'pol':100,'cha':100}},'主动'))
 def test_white_reverses_and_both_white_can_reverse_again(self):
  s=state(force(1,[card(1,1),card(2,23,'的庐')]),force(2,[card(1,9),card(2,28),card(3,16,'诏书')]))
  r=matchup_rows(s,1)[0];self.assertEqual(r['delta'],'-20');self.assertEqual(r['result'],'负');self.assertIn('胜',r['our_white']);self.assertIn('的庐',r['solution']);self.assertIn('负',r['both_white'])
 def test_equal_points_favour_initiator_both_directions(self):
  s=state(force(1,[card(1,1),card(2,9)]),force(2,[card(1,1),card(2,9)]),general(1,90,90),general(2,100,100))
  rows=matchup_rows(s,1);ours=next(r for r in rows if r['scene']=='我方宣战');self.assertEqual(ours['delta'],'+0');self.assertEqual(ours['result'],'胜')
  s['entities']['generals']=[general(1,100,100),general(2,90,90)]
  theirs=next(r for r in matchup_rows(s,1) if r['scene']=='对方宣战');self.assertEqual(theirs['delta'],'+0');self.assertEqual(theirs['result'],'负')
 def test_missing_envoy_is_not_a_card_only_win(self):
  s=state(force(1,[card(1,1)]),force(2,[card(1,8)]));s['entities']['generals']=[]
  r=matchup_rows(s,1)[0];self.assertEqual(r['result'],'未知');self.assertEqual(r['delta'],'—')
 def test_missing_reject_card_and_field_envoy(self):
  s=state(force(1,[]),force(2,[card(1,1)]));self.assertEqual(matchup_rows(s,1)[0]['result'],'负')
  self.assertEqual(matchup_rows(s,2)[0]['result'],'胜')
  s['entities']['lords'][0]['hand_cards']['slots']=[card(1,10)];self.assertEqual(matchup_rows(s,2)[0]['result'],'未知')
 def test_allies_skipped_and_unknown_identity(self):
  s=state(force(1,[card(1,1)]),force(2,[card(1,9)]));self.assertEqual(matchup_rows(s,None),[])
  s['player_force_id']=1;s['player_identity']={'status':'confirmed','force_id':1};s['entities']['lords'][0]['diplomacy_relations']=[0,0,3]+[0]*19
  self.assertEqual(matchup_rows(s,1),[])
if __name__=='__main__':unittest.main()
