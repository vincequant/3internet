import copy
import itertools
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch, Mock
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from recruitment_probability import BUILD, INPUT_VERSION, threshold, random_order_chances, city_probabilities
from quick_control_model import binding, probability_candidate, probability_previews, validate_probability_request
from state_extensions import extend_general


def fixture():
    from test_quick_control import Controls
    p,refs=Controls().policy_payload();s=p['state']
    s.update(consistency={'root_headers_and_clock_unchanged':True},player_force_id=11,
             player_identity={'status':'confirmed','force_id':11})
    s['entities']['lords']=[{'force_id':11,'name':'宋','prestige':163,'ruler_general_id':583}]
    for g in s['entities']['generals']:
        g.update(relation_byte_2e=75,excluded_ruler_word_42=65535,recruitment_input_verification=INPUT_VERSION)
    s['entities']['generals'].append({'general_id_raw':583,'name':'宋王','status_code':0,'owner_raw':11,
             'location_city_id':4,'relation_byte_2e':90,'recruitment_input_verification':INPUT_VERSION})
    s['coverage']={'generals':{'count':len(s['entities']['generals']),'structurally_valid':True}}
    return p,refs


class RecruitmentProbabilityTests(unittest.TestCase):
    def test_r6_probabilities_equal_r5(self):
        p,_=fixture();s=p['state']
        before=city_probabilities(s,4,11)
        s['build_sha256']='df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
        self.assertEqual(city_probabilities(s,4,11),before)

    def test_native_known_thresholds_and_rounding(self):
        self.assertEqual([threshold(163,a,90) for a in (75,70,20,31)],[73,76,60,66])
        self.assertEqual([threshold(200,a,90) for a in (75,70,20,31)],[90,93,73,81])
        self.assertEqual(threshold(1,75,75),1)
        self.assertEqual(threshold(200,75,75),100)
        for args in ((201,75,90),(163,None,90),(True,75,90),(163,-1,90)):
            self.assertIsNone(threshold(*args))

    def test_model_matches_exhaustive_random_orders(self):
        for ps in ([.73,.76,.60,.66],[1.,0.,.5],[0.],[1.]):
            expected=[0.]*len(ps)
            permutations=list(itertools.permutations(range(len(ps))))
            for order in permutations:
                survive=1.
                for i in order:
                    expected[i]+=survive*ps[i]/len(permutations)
                    survive*=1-ps[i]
            actual,none=random_order_chances(ps)
            for a,e in zip(actual,expected):self.assertAlmostEqual(a,e,places=12)
            self.assertAlmostEqual(sum(actual)+none,1.,places=12)

    def test_large_pool_stability_and_symmetry(self):
        for n in (2,7,40,200,923):
            result,none=random_order_chances([.9]*n)
            self.assertTrue(all(0<=v<=1 for v in result))
            self.assertAlmostEqual(sum(result)+none,1.,places=11)
            self.assertAlmostEqual(max(result)-min(result),0.,places=12)
        self.assertEqual(random_order_chances([]),([],1.))
        for ps in ([math.nan],[1.01],[-.1]):
            with self.assertRaises(ValueError):random_order_chances(ps)

    def test_decode_raw_inputs_not_website(self):
        raw=bytearray(96);raw[0x2e]=90;struct.pack_into('<H',raw,0x42,583)
        row={};extend_general(row,raw)
        self.assertEqual(row['relation_byte_2e'],90)
        self.assertEqual(row['excluded_ruler_word_42'],583)
        self.assertEqual(row['recruitment_input_verification'],INPUT_VERSION)

    def test_city_pool_includes_unfiltered_competitors_and_exclusion(self):
        p,_=fixture();s=p['state'];model=city_probabilities(s,4,11)
        self.assertEqual(model['pool_count'],5)
        self.assertAlmostEqual(sum(r['chance'] for r in model['rows'].values())+model['none_chance'],1.)
        s['entities']['generals'][0]['excluded_ruler_word_42']=583
        model=city_probabilities(s,4,11)
        self.assertEqual(model['rows'][1]['chance'],0)
        self.assertTrue(model['rows'][1]['excluded'])

    def test_unknown_and_cross_source_never_become_zero_chance(self):
        p,_=fixture()
        for modify in (
            lambda s:s.update(build_sha256='other'),
            lambda s:s.update(consistency={}),
            lambda s:s.update(coverage={}),
            lambda s:s['entities']['generals'][0].pop('relation_byte_2e'),
            lambda s:s['entities']['generals'].append(dict(s['entities']['generals'][0])),
            lambda s:s['entities']['generals'][-1].pop('recruitment_input_verification'),
            lambda s:s['entities']['generals'][0].update(location_city_id=None),
        ):
            s=copy.deepcopy(p['state']);modify(s);model=city_probabilities(s,4,11)
            self.assertTrue(model['reason']);self.assertIsNone(model['none_chance'])
            self.assertTrue(all(r['chance'] is None for r in model['rows'].values()))
        self.assertTrue(city_probabilities(p['state'],4,0)['reason'])

    def test_probability_first_attribute_tie_and_current_pool_recheck(self):
        p,refs=fixture();b=binding(p)
        with patch.dict('officer_reference.INDEX',refs):
            row=probability_candidate(p,b,'bow_ambush')
            self.assertEqual(row['id'],3) # same probability, higher blade
            p['state']['entities']['generals'][0]['relation_byte_2e']=90
            row=probability_candidate(p,b,'bow_ambush')
            self.assertEqual(row['id'],1) # higher probability beats higher blade
            self.assertEqual(len(row['pool_signature']),5) # includes no-ambush rival
            req={'policy':'bow_ambush','selection':row}
            import json
            req=json.loads(json.dumps(req)) # actual UI/helper JSON boundary
            self.assertEqual(validate_probability_request(p,b,req)['id'],1)
            p['state']['entities']['generals'][3]['relation_byte_2e']=80
            with self.assertRaises(ValueError):validate_probability_request(p,b,req)
            self.assertTrue(all('error' in r for r in probability_previews(p,b,{4}).values()))

    def test_plain_endpoint_uses_ordinary_submit_and_no_guarantee(self):
        from quick_control_native import dispatch_request
        p,refs=fixture();native=Mock();native.bound=binding(p);effects=Mock();effects.active=None
        recruiter=Mock();recruiter.pending={};emit=Mock()
        import io,json
        with patch.dict('officer_reference.INDEX',refs):
            row=probability_candidate(p,native.bound,'politics')
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(p).encode())):
                dispatch_request(native,effects,{'action':'recruit_probability','policy':'politics','selection':row},True,False,emit,recruiter)
        recruiter.submit_ordinary.assert_called_once()
        recruiter.submit.assert_not_called();recruiter.install.assert_not_called();effects.execute.assert_not_called()

    def test_ui_probability_sort_and_selection_survive_refresh(self):
        import tkinter as tk
        from city_talent import CityWildPanel
        try:root=tk.Tk()
        except tk.TclError:self.skipTest('no display')
        try:
            p,_=fixture();s=p['state'];panel=CityWildPanel(root);panel.pack()
            city=s['entities']['cities_and_barriers'][0];panel.focus(s,city)
            self.assertIn('录取估算',panel.tree.heading('chance')['text'])
            panel.sort('pol');first=panel.tree.get_children()[0]
            gid=panel.rows[first]['general_id_raw'];panel.tree.selection_set(first)
            s['entities']['lords'][0]['prestige']=200;panel.refresh(s)
            self.assertEqual(panel.rows[panel.tree.selection()[0]]['general_id_raw'],gid)
            self.assertIn('民望 200',panel.note.cget('text'))
            s['player_identity']['status']='unknown';panel.refresh(s)
            self.assertTrue(all(panel.tree.set(i,'chance')=='—' for i in panel.tree.get_children()))
        finally:root.destroy()


if __name__=='__main__':unittest.main()
