"""Player attribution regression tests; no game input or memory access."""
import sys, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from player_identity import PlayerIdentity
from player_view import player_id,local_projection,comparison_ids
from training_prediction import force_predictions
from portable_client import invalidate_player


def force(fid,raw,gold):
 return dict(force_id=fid,name=str(fid),ruler_general_id=fid,gold=gold,rice=100000,
             armament_raw=dict(zip(('infantry','cavalry','bow'),raw)),
             troop_stock=dict(infantry=20000,cavalry=10000,bow=20000))


def payload(fid=0):
 forces=[force(0,[190,130,130],31724),force(11,[200,100,180],27613),force(5,[100,120,160],10000)]
 f=next(f for f in forces if f['force_id']==fid)
 return {'fresh':True,'error':None,'state':{'identity':{'pid':1,'path':'game','creation_filetime':1},'core_address':'0xabc',
 'clock_candidates':{'year_u16':200,'season_u16':2},
 'entities':{'lords':forces,'generals':[]},'current_local_projection':copy.deepcopy(f)}}


class PlayerTests(unittest.TestCase):
 def confirm(self,p,fid):
  store=PlayerIdentity();out=store.observe(p)
  return store,store.confirm(out,store.session,fid)
 def test_wei_song_and_other_players(self):
  for fid in (0,11,5):
   with self.subTest(fid=fid):
    store,out=self.confirm(payload(fid),fid);s=out['state']
    self.assertEqual(player_id(s),fid)
    for f in s['entities']['lords']:
     predictions=force_predictions(s,f)
     self.assertEqual(predictions['infantry']['raw_before'],f['armament_raw']['infantry'])
     self.assertEqual(predictions['infantry']['gold'],f['gold'])
     self.assertEqual(predictions['infantry']['source'],'操作层' if f['force_id']==fid else '势力层')
    self.assertEqual(comparison_ids(s,11),list(dict.fromkeys([fid,11])))
 def test_wei_projection_never_applied_to_song(self):
  store,out=self.confirm(payload(),0);s=out['state']
  self.assertIsNone(local_projection(s,11))
  song=s['entities']['lords'][1];pred=force_predictions(s,song)
  self.assertEqual([pred[k]['raw_before'] for k in ('infantry','cavalry','bow')],[200,100,180])
  self.assertEqual(pred['infantry']['gold'],27613)
 def test_unknown_even_if_unique_full_match(self):
  s=PlayerIdentity().observe(payload())['state']
  self.assertIsNone(player_id(s));self.assertIsNone(local_projection(s,0))
  self.assertEqual(s['core_projection_divergence'],{})
 def test_equal_gold_does_not_identify(self):
  p=payload();p['state']['entities']['lords'][1]['gold']=31724
  self.assertIsNone(player_id(PlayerIdentity().observe(p)['state']))
 def test_ambiguous_stays_unknown_until_explicit_confirmation(self):
  p=payload();f=p['state']['entities']['lords'][0]
  p['state']['entities']['lords'][1].update({k:copy.deepcopy(f[k]) for k in ('gold','rice','armament_raw','troop_stock')})
  store=PlayerIdentity();out=store.observe(p)
  self.assertEqual(out['player_identity']['candidate_force_ids'],[0,11]);self.assertIsNone(out['player_force_id'])
 def test_conflicting_manual_selection_rejected(self):
  store=PlayerIdentity();out=store.observe(payload())
  with self.assertRaises(ValueError):store.confirm(out,store.session,11)
 def test_instance_root_clock_and_roster_changes_revoke(self):
  for field in ('process','root','clock','roster'):
   p=payload();store,out=self.confirm(p,0);session=store.session
   if field=='process':p['state']['identity']['creation_filetime']=2
   elif field=='root':p['state']['core_address']='0xdef'
   elif field=='clock':p['state']['clock_candidates']['season_u16']=1
   else:p['state']['entities']['lords'][0]['name']='new'
   out=store.observe(p)
   self.assertIsNone(out['player_force_id']);self.assertNotEqual(session,store.session)
   with self.assertRaises(ValueError):store.confirm(out,session,0)
 def test_disconnect_reconnect_does_not_restore_identity(self):
  p=payload();store,out=self.confirm(p,0)
  p['fresh']=False;out=store.observe(p);self.assertIsNone(out['player_force_id'])
  p['fresh']=True;out=store.observe(p);self.assertIsNone(out['player_force_id'])
 def test_divergence_same_force_only(self):
  p=payload();store,out=self.confirm(p,0)
  p['state']['current_local_projection']['gold']=31000
  s=store.observe(p)['state']
  self.assertEqual(s['core_projection_divergence'],{'gold':{'core':31724,'local_projection':31000}})
 def test_projection_conflict_revokes(self):
  p=payload();store,out=self.confirm(p,0)
  p['state']['current_local_projection']=copy.deepcopy(p['state']['entities']['lords'][1])
  self.assertIsNone(store.observe(p)['player_force_id'])
 def test_frontend_disconnect_clears_identity_and_history(self):
  store,out=self.confirm(payload(),0);s=out['state'];s['history']={'recent_changes':[1]}
  s=invalidate_player(s)
  self.assertIsNone(player_id(s));self.assertIsNone(local_projection(s,0));self.assertNotIn('history',s)
 def test_manual_change_rotates_session_and_drops_old_history(self):
  p=payload();p['state']['current_local_projection']['gold']=1
  store,out=self.confirm(p,0);session=store.session
  out['state']['history']={'player_session_id':session,'recent_changes':[{'owner':0}]}
  out=store.confirm(out,session,11)
  self.assertNotEqual(session,store.session);self.assertNotIn('history',out['state'])
 def test_history_only_accepted_for_current_session(self):
  store,out=self.confirm(payload(),0)
  out['state']['history']={'player_session_id':store.session,'recent_changes':[]}
  self.assertIn('history',store.apply(out)['state'])
  out['state']['history']['player_session_id']='previous-match'
  self.assertNotIn('history',store.apply(out)['state'])
 def test_view_selection_does_not_change_identity(self):
  store,out=self.confirm(payload(),0);s=out['state']
  for fid in (11,5,0):
   comparison_ids(s,fid);local_projection(s,fid)
   self.assertEqual(player_id(s),0)

if __name__=='__main__':unittest.main(verbosity=2)
