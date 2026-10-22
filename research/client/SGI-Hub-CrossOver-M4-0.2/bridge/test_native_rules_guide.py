import copy
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from native_rules_model import PROTECTED,card_rows,recruit_rows,SYNC_ROWS
from test_recruitment_probability import fixture
from recruitment_probability import city_probabilities

class NativeRulesTests(unittest.TestCase):
 def test_full_pool_filter_and_200_scenario_preserve_snapshot(self):
  p,_=fixture();s=p['state'];before=copy.deepcopy(s)
  allrows,reason=recruit_rows(s,11,min_blade=None);filtered,_=recruit_rows(s,11,min_blade=150)
  self.assertFalse(reason);self.assertEqual(s,before)
  for r in allrows:
   self.assertEqual(r['chance'],city_probabilities(s,r['city_id'],11)['rows'][r['gid']]['chance'])
  self.assertEqual([r['gid'] for r in filtered],[r['gid'] for r in allrows if r['blade'] is not None and r['blade']>150])
  h=copy.deepcopy(s);h['entities']['lords'][0]['prestige']=200
  for r in filtered:self.assertEqual(r['chance200'],city_probabilities(h,r['city_id'],11)['rows'][r['gid']]['chance'])
 def test_missing_input_and_wrong_build_stay_unknown(self):
  p,_=fixture();s=p['state'];s['entities']['generals'][0].pop('relation_byte_2e')
  rows,reason=recruit_rows(s,11,min_blade=None);self.assertTrue(reason)
  affected=[r for r in rows if r['city_id']==s['entities']['generals'][0]['location_city_id']]
  self.assertTrue(affected);self.assertTrue(all(r['chance'] is None and r['chance200'] is None for r in affected))
  s['build_sha256']='other';rows,_=recruit_rows(s,11,min_blade=None)
  self.assertTrue(all(r['chance'] is None for r in rows))
  self.assertEqual(recruit_rows({},11),([], '所选势力未确认'))
 def test_unplaced_officers_do_not_turn_into_a_fake_city(self):
  p,_=fixture();s=p['state'];g=copy.deepcopy(s['entities']['generals'][0]);g['general_id_raw']=99999;g['location_city_id']=65535;s['entities']['generals'].append(g);s['coverage']['generals']['count']+=1
  rows,reason=recruit_rows(s,11,min_blade=None)
  self.assertNotIn(99999,[r['gid'] for r in rows]);self.assertIn('无有效城池记录',reason)
  self.assertTrue(all(r['chance'] is not None for r in rows))

 def test_native_classification_is_not_a_promised_draw(self):
  rows=card_rows({'hand_cards':{'slots':[{'slot':i,'card_id':i} for i in range(1,29)]}})
  self.assertEqual({r['card_id'] for r in rows if r['seasonal']=='保护类'},set(PROTECTED))
  self.assertEqual(len(PROTECTED),13)
  self.assertEqual(card_rows({'hand_cards':{'slots':[{'slot':1,'card_id':99}]}})[0]['seasonal'],'未确认')
  self.assertTrue(any('尚未' in row[1] for row in SYNC_ROWS if '外交换卡' in row[0]))
 def test_real_ui_rebind_and_clear_no_actions(self):
  import tkinter as tk
  from native_rules_guide import NativeRulesGuide
  try:root=tk.Tk()
  except tk.TclError:self.skipTest('no display')
  root.withdraw();app=SimpleNamespace(face='Arial');ui=NativeRulesGuide(root,app)
  try:
   p,_=fixture();s=p['state'];s['entities']['lords'][0]['hand_cards']={'slots':[{'slot':1,'card_id':1,'name':'宣告开战'},{'slot':2,'card_id':17,'name':'玉玺'}]}
   ui.refresh(s,11);root.update();self.assertTrue(ui.tree.get_children());self.assertEqual(len(ui.cards.get_children()),2)
   self.assertIn('下季度',ui.card_note.cget('text'));self.assertIn('未核准',ui.card_note.cget('text'))
   ui.minimum.set('x');ui.render_recruit();self.assertFalse(ui.tree.get_children());self.assertIn('整数',ui.note.cget('text'))
   ui.minimum.set('150');ui.refresh(None,None);self.assertFalse(ui.tree.get_children());self.assertFalse(ui.cards.get_children());self.assertIn('未读取',ui.card_note.cget('text'))
   ui.refresh(s,11);s2=copy.deepcopy(s);s2['identity']={'pid':999};s2['entities']['generals']=[g for g in s2['entities']['generals'] if g.get('status_code')!=1]
   ui.refresh(s2,11);self.assertFalse(ui.tree.get_children());self.assertEqual(ui.city.get(),'全部城池')
   ui.refresh(s,11);s['build_sha256']='other';ui.refresh(s,11)
   self.assertTrue(all(ui.cards.item(n,'values')[2]=='版本未核准' for n in ui.cards.get_children()))
  finally:root.destroy()

if __name__=='__main__':unittest.main()
