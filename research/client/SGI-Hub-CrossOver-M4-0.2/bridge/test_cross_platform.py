import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from test_player_identity import payload
from player_identity import PlayerIdentity
from city_production import enrich_production,population_cap
from connection import Connection
class AutomaticIdentity(unittest.TestCase):
 def ctx(self,fid=0):
  p=payload(fid);p['state']['player_context']={'force_id':fid,'slot':0,'status':'verified','source':'game_player_context','stable':True};return p
 def test_context_not_resource_guess(self):
  for fid in (0,11,5):
   p=self.ctx(fid);p['state']['current_local_projection']['gold']=123
   a=PlayerIdentity().observe(p);self.assertEqual(a['player_force_id'],fid);self.assertEqual(a['player_identity']['source'],'game_player_context')
 def test_lost_context_revokes_then_recovers(self):
  p=self.ctx();s=PlayerIdentity();self.assertEqual(s.observe(p)['player_force_id'],0)
  p['state']['player_context']['stable']=False;self.assertIsNone(s.observe(p)['player_force_id'])
  p['state']['player_context']['stable']=True;self.assertEqual(s.observe(p)['player_force_id'],0)
 def test_switch_and_disconnect(self):
  s=PlayerIdentity();a=s.observe(self.ctx());old=a['player_identity']['session_id']
  b=s.observe(self.ctx(11));self.assertEqual(b['player_force_id'],11);self.assertNotEqual(old,b['player_identity']['session_id'])
  p=self.ctx(11);p['fresh']=False;self.assertIsNone(s.observe(p)['player_force_id']);self.assertEqual(s.observe(self.ctx(11))['player_force_id'],11)
 def test_wrong_manual_override_rejected(self):
  s=PlayerIdentity();p=s.observe(self.ctx())
  with self.assertRaises(ValueError):s.confirm(p,s.session,11)
 def test_missing_duplicate_or_invalid_id(self):
  for fid in (22,None,True):
   p=self.ctx();p['state']['player_context']['force_id']=fid
   self.assertIsNone(PlayerIdentity().observe(p)['player_force_id'])
  p=self.ctx();p['state']['entities']['lords'].append(copy.deepcopy(p['state']['entities']['lords'][0]));self.assertIsNone(PlayerIdentity().observe(p)['player_force_id'])
class Recruitment(unittest.TestCase):
 def test_population_boundary_and_muldiv_rounding(self):
  self.assertEqual([population_cap(p) for p in (49999,50000,50049,50050,1000000)], [0,5000,5000,5010,50000])
 def test_association_caps_and_unknown(self):
  city={'city_id':1,'type':'city','population':100050}
  e={'cities_and_barriers':[city], 'production_buildings':[{'type':'parade_ground','linked_city_id':1,'building_ui_amount':8000},{'type':'parade_ground','linked_city_id':1,'building_ui_amount':8000},{'type':'horse_farm','linked_city_id':2,'building_ui_amount':9000}]}
  enrich_production(e);self.assertEqual(city['recruitment_capacity']['amounts'],dict(infantry=10010,cavalry=0,bow=0))
  del e['production_buildings'][0]['linked_city_id'];enrich_production(e);self.assertIsNone(city['recruitment_capacity']['amounts']['infantry'])
 def test_barrier_not_city(self):
  e={'cities_and_barriers':[{'city_id':1,'type':'barrier'}], 'production_buildings':[]};enrich_production(e);self.assertEqual(e['cities_and_barriers'][0]['recruitment_capacity']['status'],'not_applicable')
class Protocol(unittest.TestCase):
 def test_wrong_source_and_readonly(self):
  c=Connection({'mode':'remote','port':18769,'expected_source':'VKQUANT'})
  good=dict(protocol_version=1,service='sgi-crossover-bridge-1',source_id='VKQUANT',read_only_endpoint=True)
  c.validate(good)
  for key,value in [('protocol_version',2),('source_id','Windows'),('source_id','vkquant'),('read_only_endpoint',False)]:
   with self.assertRaises(ValueError):c.validate(dict(good,**{key:value}))

class NativePathAndFreshness(unittest.TestCase):
 def test_native_path_is_explicit_and_not_any_sanpk(self):
  from recovery import RecoveryController
  path=r'D:\Coding\sanguo-internet\run-3.5\3I\SANPK.exe'
  instance={'pid':1,'path':path,'creation_filetime':1}
  c=RecoveryController(lambda:{'status':'ok','instances':[instance]},lambda *a:None,lambda *a:None,expected_path=path)
  calls=[];c._attach=lambda inst,ident:calls.append(inst) or 1
  c.step();self.assertEqual(calls,[instance])
  instance['path']=r'D:\Other\SANPK.exe';c.step();self.assertEqual(c.error_class,'path_mismatch')
 def test_future_snapshot_not_fresh(self):
  from recovery import compute_fresh
  from datetime import datetime,timezone,timedelta
  now=datetime.now(timezone.utc)
  self.assertFalse(compute_fresh(True,None,{'capture_end':(now+timedelta(seconds=60)).isoformat()},now))

class ForceUnitMembership(unittest.TestCase):
 def test_zero_force_switch_and_unknown_owner(self):
  from omni_window import intelligence_rows
  units=[{'unit_id':1,'owner_raw':0},{'unit_id':2,'owner_raw':11},{'unit_id':3,'owner_raw':0},{'unit_id':4}]
  state={'entities':dict(lords=[],generals=[],cities_and_barriers=[],production_buildings=[],field_units=units)}
  for fid,expected in ((0,[1,3]),(11,[2]),(21,[]),(None,[])):
   self.assertEqual([u['unit_id'] for u in intelligence_rows(state,fid)['force_units']],expected)
 def test_no_units_collected(self):
  from omni_window import intelligence_rows
  state={'entities':dict(lords=[],generals=[],cities_and_barriers=[],production_buildings=[])}
  self.assertEqual(intelligence_rows(state,0)['force_units'],[])

class NativeModuleEnumeration(unittest.TestCase):
 def test_wow64_duplicate_and_ambiguous_images(self):
  from runtime_image import unique_image_base
  self.assertEqual(unique_image_base([0x400000,0x400000]),0x400000)
  for bases in ([],[None],[0],[0x400000,0x800000]):
   with self.assertRaises(RuntimeError):unique_image_base(bases)

if __name__=='__main__':unittest.main()
