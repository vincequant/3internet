import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from diplomacy_state import decode_relations
from force_relations import at_war, relation_to_player

def fixture():
    raw=bytearray(273);raw[0x32+19]=1
    return {'player_force_id':20,'player_identity':{'status':'confirmed','force_id':20},
            'entities':{'lords':[{'force_id':20,'diplomacy_relations':decode_relations(raw)},
                                 {'force_id':19,'diplomacy_relations':[0]*22}, {'force_id':1}]}}
class Relations(unittest.TestCase):
    def test_current_game_screenshot(self):
        s=fixture();self.assertTrue(at_war(s,19));self.assertFalse(at_war(s,20));self.assertFalse(at_war(s,1))
    def test_reads_player_direction_like_game_ui(self):
        s=fixture();s['entities']['lords'][0]['diplomacy_relations'][19]=0
        s['entities']['lords'][1]['diplomacy_relations'][20]=1
        self.assertFalse(at_war(s,19))
    def test_peace_refresh_and_changed_player(self):
        s=fixture();s['entities']['lords'][0]['diplomacy_relations'][19]=2
        self.assertFalse(at_war(s,19));self.assertEqual(relation_to_player(s,19),2)
        s=fixture();s['player_force_id']=19;s['player_identity']['force_id']=19
        self.assertFalse(at_war(s,20));self.assertFalse(at_war(s,19))
    def test_unknown_player_or_missing_data_never_red(self):
        s=fixture();s['player_identity']['status']='unknown';self.assertFalse(at_war(s,19))
        s=fixture();s['entities']['lords'][0].pop('diplomacy_relations');self.assertIsNone(relation_to_player(s,19))
        s=fixture();s['entities']['lords'].append(s['entities']['lords'][0]);self.assertFalse(at_war(s,19))
    def test_malformed_or_out_of_range_never_red(self):
        s=fixture()
        for value in [None,True,'1',4,-1]:
            s['entities']['lords'][0]['diplomacy_relations'][19]=value;self.assertFalse(at_war(s,19))
        self.assertFalse(at_war(s,-1));self.assertFalse(at_war(s,22))
    def test_decoder_boundary_and_invalid_values(self):
        raw=bytearray(273);raw[0x31]=1;raw[0x32]=3;raw[0x47]=2;raw[0x48]=1
        r=decode_relations(raw);self.assertEqual(len(r),22);self.assertEqual(r[0],3);self.assertEqual(r[-1],2);self.assertNotIn(1,r)
        raw[0x33]=255;self.assertIsNone(decode_relations(raw)[1]);self.assertIsNone(decode_relations(bytes(20)))

    def test_priority_and_alliance(self):
        from force_relations import force_priority, allied, regroup_forces
        s=fixture();s['entities']['lords'][0]['diplomacy_relations'][1]=3
        self.assertTrue(allied(s,1))
        self.assertEqual([force_priority(s,i) for i in [20,19,1,4]],[0,1,2,3])
        class Tree:
            def __init__(self):self.ids=['4','1','19','20','5']
            def get_children(self):return self.ids[:]
            def move(self,i,parent,index):self.ids.remove(i);self.ids.insert(index,i)
        t=Tree();regroup_forces(t,s);self.assertEqual(t.ids,['20','19','1','4','5'])
        s['entities']['lords'][0]['diplomacy_relations'][19]=3
        s['entities']['lords'][0]['diplomacy_relations'][1]=1
        regroup_forces(t,s);self.assertEqual(t.ids,['20','1','19','4','5'])
        s['player_identity']['status']='unknown'
        self.assertFalse(allied(s,19));self.assertEqual(force_priority(s,20),3)
