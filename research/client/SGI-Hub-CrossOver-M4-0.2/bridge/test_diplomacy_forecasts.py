"""Read-only native forecast boundaries, finite-deck exact probabilities, reader races."""
import unittest,sys,struct,copy,itertools
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from native_diplomacy import forecast,defector_candidates,defection_gate,defection_cities,envoy_score
from card_probability import distribution,probability_rows
from card_pool import read_pool

def general(id,owner=2,clan=None,parent=-1,relation=30,entry=190,ambition=5,stats=(70,70,70,70,70),status=0,skills=0):
 b=bytearray(96);struct.pack_into('<hh',b,8,owner,id);struct.pack_into('<h',b,0x1e,180);struct.pack_into('<h',b,0x21,status);struct.pack_into('<H',b,0x23,10000);b[0x25:0x2a]=bytes(stats);struct.pack_into('<I',b,0x2a,skills);b[0x2e]=relation;b[0x30]=ambition;struct.pack_into('<h',b,0x38,entry);struct.pack_into('<hh',b,0x3e,clan if clan is not None else id+1,parent)
 return dict(general_id_raw=id,owner_raw=owner,name='将'+str(id),raw_hex=b.hex())
def force(id,ruler,capital=10,held=False):
 b=bytearray(273);struct.pack_into('<h',b,8,id);struct.pack_into('<h',b,0xe,id+1);struct.pack_into('<h',b,0x12,ruler);struct.pack_into('<h',b,0x14,capital);struct.pack_into('<h',b,0x80,-1)
 return dict(force_id=id,name='势力'+str(id),raw_hex=b.hex(),hand_cards={'slots':[dict(slot=1,card_id=15,name='策反')] if held else []})
def city(id,pop=10000,neighbors=(),owner=2):
 b=bytearray(81);struct.pack_into('<8h',b,0x26,*(list(neighbors)+[-1]*8)[:8]);struct.pack_into('<I',b,0x3f,pop)
 return dict(city_id=id,type='city',owner_raw=owner,name='城'+str(id),raw_hex=b.hex())
def fixture():return dict(entities=dict(lords=[force(1,0,held=True),force(2,10)],generals=[general(0,owner=1,stats=(90,90,90,100,100),skills=0x80000),general(10,relation=0),general(11)],cities_and_barriers=[city(10,999999),city(11,50000,(10,)),city(12,30000)]))
def compact_fixture(state):
 from state_extensions import extend_general,extend_force
 from recovery import slim_snapshot
 s=copy.deepcopy(state)
 for g in s['entities']['generals']:
  b=bytes.fromhex(g['raw_hex']);g.update(birth_year_candidate=struct.unpack_from('<h',b,0x1e)[0],soldiers=struct.unpack_from('<H',b,0x23)[0],attributes=dict(zip(('lead','war','intel','pol','cha'),b[0x25:0x2a])));extend_general(g,b)
 for f in s['entities']['lords']:
  b=bytes.fromhex(f['raw_hex']);f.update(ruler_general_id=struct.unpack_from('<h',b,0x12)[0],capital_city_id=struct.unpack_from('<h',b,0x14)[0],color_index_raw=struct.unpack_from('<h',b,0xe)[0],armament_raw={});extend_force(f,b)
 for c in s['entities']['cities_and_barriers']:
  b=bytes.fromhex(c['raw_hex']);c.update(population=struct.unpack_from('<I',b,0x3f)[0],neighbor_city_ids=list(struct.unpack_from('<8h',b,0x26)))
 return slim_snapshot(s)
class DefectionTests(unittest.TestCase):
 def test_gate_discontinuity_and_average(self):
  self.assertEqual([defection_gate(130+d,0) for d in (29,30,69,70,100)], [0,15,34,70,100])
  s=fixture();old=copy.deepcopy(s);r=forecast(s,1)['rows'][0];self.assertEqual(r['chance'],97.75);self.assertEqual(r['cities'][0]['city_id'],12);self.assertEqual([g['id'] for g in r['generals']],[11]);self.assertEqual(s,old)
 def test_ability_before_ambition_and_service(self):
  s=fixture();s['entities']['generals'] += [general(12,ambition=1,stats=(80,80,80,80,80)),general(13,ambition=10,entry=199)]
  self.assertEqual([g['id'] for g in defector_candidates(s,s['entities']['lords'][1])[0]],[12])
  s['entities']['generals'][-1]=general(13,stats=(80,80,80,80,80),entry=199)
  self.assertEqual([g['id'] for g in defector_candidates(s,s['entities']['lords'][1])[0]],[13])
 def test_ties_limit_membership_and_leader(self):
  s=fixture();s['entities']['generals'] += [general(i) for i in (12,13,14)]
  gs=forecast(s,1)['rows'][0]['generals'];self.assertEqual(len(gs),4);self.assertEqual([g['inclusion'] for g in gs],[.75]*4);self.assertEqual([g['leader'] for g in gs],[.25]*4)
 def test_outbound_protected_relatives_not_eligible(self):
  for kw in (dict(status=2),dict(parent=10),dict(clan=11),dict(relation=19)):
   s=fixture();s['entities']['generals'][-1]=general(11,**kw);self.assertEqual(forecast(s,1)['rows'][0]['chance'],0)
 def test_city_fallback_tie_and_missing(self):
  s=fixture();s['entities']['cities_and_barriers']=[city(10,999999),city(11,10000,(10,)),city(12,10000,(10,))]
  cs,_=defection_cities(s,s['entities']['lords'][1]);self.assertEqual([c['city_id'] for c in cs],[11,12])
  del s['entities']['cities_and_barriers'][1]['raw_hex'];self.assertIsNone(forecast(s,1)['rows'][0]['chance'])
 def test_missing_raw_and_no_free_slot_and_pending_parameter(self):
  s=fixture();b=bytearray.fromhex(s['entities']['lords'][0]['raw_hex']);struct.pack_into('<hh',b,0x63,2,0);b[0x67]=15;b[0x6c]=19;s['entities']['lords'][0]['raw_hex']=b.hex()
  r=forecast(s,1)['rows'][0];self.assertEqual((r['chance'],r['parameter']),(91,19)) # score240 =>91
  del s['entities']['generals'][-1]['raw_hex'];self.assertIsNone(forecast(s,1)['rows'][0]['chance'])
  s=fixture();s['entities']['lords']=[force(i,0) for i in range(22)];self.assertTrue(all(r['chance']==0 for r in forecast(s,1)['rows']))
 def test_compact_archived_fields_match_raw_forecast(self):
  s=fixture();b=bytearray.fromhex(s['entities']['lords'][0]['raw_hex']);struct.pack_into('<hh',b,0x63,2,0);b[0x67]=15;b[0x6c]=19;s['entities']['lords'][0]['raw_hex']=b.hex()
  compact=compact_fixture(s);self.assertFalse(any('raw_hex' in r for rows in compact['entities'].values() for r in rows))
  expected=forecast(s,1)['rows'][0];actual=forecast(compact,1)['rows'][0]
  for key in ('chance','gate','parameter','reason','range'):self.assertEqual(actual[key],expected[key])
  self.assertEqual([g['id'] for g in actual['generals']],[g['id'] for g in expected['generals']]);self.assertEqual([c['city_id'] for c in actual['cities']],[12])
 def test_existing_compact_envoy_works_missing_new_candidates_stays_unknown(self):
  s=compact_fixture(fixture());g=s['entities']['generals'][0]
  for key in list(g):
   if key.startswith('defection_'):del g[key]
  self.assertEqual(envoy_score(g,'策反')['actor'],240)
  del s['entities']['generals'][-1]['defection_clan_id'];self.assertIsNone(forecast(s,1)['rows'][0]['chance'])
class DrawTests(unittest.TestCase):
 def test_known_small_deck_vs_every_combination(self):
  for total in range(1,9):
   for hits in range(total+1):
    for n in range(min(5,total)+1):
     combos=list(itertools.combinations(range(total),n));want=[Fraction(sum(sum(i<hits for i in c)==k for c in combos),len(combos)) for k in range(n+1)]
     self.assertEqual(distribution(total,hits,n),want)
 def test_four_and_five_differ_and_exact_sum(self):
  counts={i:0 for i in range(1,29)};counts.update({1:2,2:1,17:1,26:6})
  four=probability_rows(counts,4,{});five=probability_rows(counts,5,{})
  self.assertEqual(four[0]['at_least_one'],Fraction(2,5));self.assertEqual(five[0]['at_least_one'],Fraction(1,2))
  for row in four+five:self.assertEqual(sum(row['distribution']),1)
  self.assertEqual(distribution(0,0,0),[1]);self.assertEqual(distribution(5,5,4),[0,0,0,0,1])
 def test_bad_pool_draw_overflow_and_missing_category(self):
  for args in ((5,1,6),(5,-1,1),(5,6,2),(5,1,True)):
   with self.assertRaises(ValueError):distribution(*args)
  with self.assertRaises(ValueError):probability_rows({1:1},1,{})
class PoolTests(unittest.TestCase):
 def collector(self,change=False,unknown=False):
  memory={0x148c:bytes(28),0x2000:struct.pack('<Ih',0x504228,-1),0x2010:struct.pack('<Ih',0x504588,-2),0x2020:struct.pack('<Ih',0x504528,1),0x2030:struct.pack('<Ih',0x504288 if not unknown else 1,-1)}
  def direct(a,n):return bytes(n) if change and a==0x2000 else memory[a]
  return SimpleNamespace(core=0x1000,headers=[],read=lambda a,n:memory[a],m=SimpleNamespace(read=direct),walk=lambda *a,**kw:([(i,p) for i,p in enumerate((0x2000,0x2010,0x2020,0x2030))],{'count':4})),memory
 def test_ownership_disabled_and_stable_double_read(self):
  c,m=self.collector();r=read_pool(c);self.assertEqual(r['status'],'verified');self.assertEqual((r['total'],r['counts']['1'],r['counts']['17']),(2,1,0))
  flags=bytearray(28);flags[1]=1;m[0x148c]=bytes(flags);self.assertEqual(read_pool(c)['total'],1)
 def test_race_unknown_type_and_bound_are_not_partial_counts(self):
  for kw in (dict(change=True),dict(unknown=True)):
   c,_=self.collector(**kw);r=read_pool(c);self.assertEqual(r['status'],'unknown');self.assertNotIn('counts',r)
  c,_=self.collector();c.walk=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('container safety bound exceeded'));self.assertEqual(read_pool(c)['status'],'unknown')
class ReadBindingTests(unittest.TestCase):
 def test_live_local_identity_required_and_replay_remote_never_fall_through(self):
  from card_pool_client import request_for
  identity={'pid':760,'path':r'C:\sgi\SANPK.exe','creation_filetime':123}
  state={'identity':identity,'core_address':'0x100000','build_sha256':'fixture'}
  health=dict(service='sgi-crossover-bridge-1',phase='live',fresh=True,source_id='local',identity=identity,core_address='0x100000')
  cfg={'mode':'local','expected_source':'local'};self.assertEqual(request_for(state,health,cfg)['identity'],identity)
  for config,view,h in (({'mode':'remote'},False,health),(cfg,True,health),(cfg,False,dict(health,fresh=False)),(cfg,False,dict(health,source_id='other')),(cfg,False,dict(health,identity=dict(identity,creation_filetime=124)))):
   with self.assertRaises(ValueError):request_for(state,h,config,view)
if __name__=='__main__':unittest.main()
