import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from quick_control_model import binding, probability_roster, owned_candidates, filter_roster, roster_cell,validate_roster_request
from test_recruitment_probability import fixture


class RosterTests(unittest.TestCase):
    def rows(self):
        p,refs=fixture()
        with patch.dict('officer_reference.INDEX',refs):rows=probability_roster(p,binding(p))
        return p,rows

    def owned_fixture(self):
        p,refs=fixture()
        for g,status in zip(p['state']['entities']['generals'][:5],(0,2,4,6,9)):
            g.update(owner_raw=11,status_code=status,status_label=f'测试状态{status}')
        p['state']['entities']['generals'][4]['location_city_id']=None
        rival=copy.deepcopy(p['state']['entities']['generals'][0]);rival.update(general_id_raw=50,owner_raw=10)
        dead=dict(rival,general_id_raw=51,owner_raw=11,status_code=5)
        wild=dict(rival,general_id_raw=52,owner_raw=65535,status_code=1)
        unborn=dict(rival,general_id_raw=53,owner_raw=11,status_code=3)
        p['state']['entities']['generals'].extend((rival,dead,wild,unborn))
        return p,refs

    def test_owned_roster_confirmed_force_skills_locations_and_statuses(self):
        p,refs=self.owned_fixture();b=binding(p)
        with patch.dict('officer_reference.INDEX',refs):
            rows=owned_candidates(p,b)
            self.assertEqual({r['id'] for r in rows},{1,2,3,4,5})
            self.assertTrue(all(r['row_kind']=='owned' and r['owner_id']==11 for r in rows))
            self.assertEqual([r['blade'] for r in rows],sorted([r['blade'] for r in rows],reverse=True))
            all_four=filter_roster(rows,required_skills=['ride','bow','charge','ambush'])
            self.assertEqual([r['id'] for r in all_four],[5]);self.assertEqual(all_four[0]['city'],'位置未知')
            with self.assertRaises(ValueError):validate_roster_request(p,b,{'selection':all_four[0]})
            p['state']['entities']['generals'][4]['attributes']['intel']=99
            unmatched=owned_candidates(p,b)
            row=next(r for r in unmatched if r['id']==5)
            self.assertEqual(roster_cell(row,'ride'),'未知')
            self.assertFalse(filter_roster(unmatched,required_skills=['ride','bow','charge','ambush']))
            p['state']['player_force_id']=10;p['state']['player_identity']['force_id']=10
            self.assertEqual([r['id'] for r in owned_candidates(p,b)],[50])
            p['state']['player_identity']['status']='unknown'
            with self.assertRaises(ValueError):owned_candidates(p,b)
            with self.assertRaises(ValueError):owned_candidates(p,dict(b,pid=b['pid']+1))

    def test_owned_mode_ignores_recruit_filters_and_never_sends_orders(self):
        import tkinter as tk,time
        from officer_roster import OfficerRoster,OWNED_COLUMNS,WILD_COLUMNS
        try:root=tk.Tk()
        except tk.TclError:self.skipTest('no display')
        panel=SimpleNamespace(root=root,ready=False,bound=None,current_state={},pending_targets={},recruit_officer=Mock())
        ui=OfficerRoster(panel,'http://invalid')
        try:
            p,refs=self.owned_fixture();panel.ready=True;panel.bound=binding(p);ui.bound=panel.bound
            with patch.dict('officer_reference.INDEX',refs):ui.owned_rows=owned_candidates(p,ui.bound)
            ui.updated_at=time.monotonic();panel.current_state=dict(mode=2,phase=1,allowance=1,orders_used=0,modal=0)
            ui.minimum.set('≥90%');ui.city_first_only.set(True);ui.min_blade.set('')
            ui.mode.set('owned');ui.change_mode();root.update()
            self.assertEqual(set(map(int,ui.visible)),{1,2,3,4,5})
            self.assertEqual(tuple(ui.tree['displaycolumns']),OWNED_COLUMNS)
            self.assertEqual(ui.minimum_choice.winfo_manager(),'');self.assertEqual(ui.first_check.winfo_manager(),'')
            self.assertEqual(ui.recruit_button.winfo_manager(),'')
            for v in ui.skill_vars.values():v.set(True)
            ui.render();self.assertEqual(list(ui.visible),['5'])
            ui.tree.selection_set('5');ui.choose();ui.recruit();panel.recruit_officer.assert_not_called()
            self.assertNotIn('录取估算',ui.detail.get());self.assertIn('统武',ui.detail.get())
            self.assertEqual(str(ui.recruit_button['state']),'disabled')
            ui.mode.set('blade');ui.change_mode();root.update()
            self.assertEqual(tuple(ui.tree['displaycolumns']),WILD_COLUMNS)
            self.assertEqual(ui.minimum_choice.winfo_manager(),'pack');self.assertEqual(ui.first_check.winfo_manager(),'pack')
            self.assertEqual(ui.recruit_button.winfo_manager(),'pack')
            panel.bound=dict(panel.bound,pid=panel.bound['pid']+1);ui.poll()
            self.assertFalse(ui.owned_rows);self.assertFalse(ui.rows)
        finally:ui.close();root.destroy()

    def test_full_pool_estimate_is_unchanged_by_combined_skill_filters(self):
        p,rows=self.rows();original=copy.deepcopy(rows)
        filtered=filter_roster(rows,required_skills=['ride','charge','ambush'])
        self.assertTrue(filtered)
        self.assertTrue(all(r['ride'] and r['charge'] and r['ambush'] for r in filtered))
        self.assertEqual(rows,original)
        from recruitment_probability import city_probabilities
        full=city_probabilities(p['state'],4,11)
        for row in filtered:self.assertEqual(row['success_probability'],full['rows'][row['id']]['chance'])

    def test_numeric_descending_sort_probability_filter_search_and_unknowns(self):
        _,rows=self.rows()
        self.assertEqual([r['blade'] for r in filter_roster(rows)],sorted((r['blade'] for r in rows),reverse=True))
        rows[0]['success_probability']=.95;rows[1]['success_probability']=None
        rows[1]['skills_matched']=False
        self.assertEqual(filter_roster(rows,'probability')[0]['id'],rows[0]['id'])
        self.assertEqual(filter_roster(rows,'probability')[-1]['id'],rows[1]['id'])
        self.assertEqual([r['id'] for r in filter_roster(rows,min_probability=.9)],[rows[0]['id']])
        self.assertNotIn(rows[1],filter_roster(rows,required_skills=['bow']))
        self.assertEqual(roster_cell(rows[1],'probability'),'—')
        self.assertEqual(roster_cell(rows[1],'ride'),'未知')
        self.assertEqual(filter_roster(rows,search=str(rows[0]['id']))[0]['id'],rows[0]['id'])
        for kwargs in ({'sort':'unknown'},{'required_skills':['unknown']},{'min_probability':1.1}):
            with self.assertRaises(ValueError):filter_roster(rows,**kwargs)

    def test_wrong_game_binding_is_rejected(self):
        p,_=fixture();b=binding(p)
        with self.assertRaises(ValueError):probability_roster(p,dict(b,pid=b['pid']+1))

    def test_blade_filter_is_strict_above150_and_can_be_cleared(self):
        _,rows=self.rows();rows=copy.deepcopy(rows[:3])
        for r,n in zip(rows,(149,150,151)):r['blade']=n
        self.assertEqual([r['blade'] for r in filter_roster(rows,min_blade=150)],[151])
        self.assertEqual(len(filter_roster(rows,min_blade=None)),3)
        for limit in (-1,511,150.5,True):
            with self.assertRaises(ValueError):filter_roster(rows,min_blade=limit)

    def test_intel_roster_uses_native_bits_then_website_and_filters_like_politics(self):
        p, refs = fixture()
        generals = p['state']['entities']['generals']
        generals[0].update(skill_mask_raw=0x200, combat_modifier_flags_word=0)
        generals[0]['attributes']['intel'] = 80
        generals[1].update(skill_mask_raw=0, combat_modifier_flags_word=0)
        generals[1]['attributes']['intel'] = 99
        generals[2]['attributes']['intel'] = 80
        refs['fixture-3'][0]['stats']['intelligence'] = 80
        refs['fixture-3'][0]['skills'] = ['火攻', '落石']
        with patch.dict('officer_reference.INDEX', refs):
            rows = {r['id']: r for r in probability_roster(p, binding(p))}
        self.assertEqual(rows[1]['special_source'], 'native')
        self.assertEqual(rows[1]['special_skills'], ['火攻'])
        self.assertEqual(rows[1]['special_percent'], 40)
        self.assertEqual(roster_cell(rows[1], 'special'), '40.00%')
        self.assertEqual(rows[2]['special_percent'], 0)
        self.assertEqual(rows[2]['special_source'], 'native')
        self.assertEqual(rows[3]['special_source'], 'website')
        self.assertEqual(rows[3]['special_skills'], ['火攻', '落石'])
        self.assertEqual(rows[3]['special_percent'], 64)
        ordered = filter_roster(list(rows.values()), 'intel')
        self.assertEqual(ordered[0]['id'], 2)
        self.assertEqual([r['intel'] for r in filter_roster(list(rows.values()), 'intel', min_intel=70)], [99, 80, 80])
        self.assertEqual([r['id'] for r in filter_roster(list(rows.values()), 'special', max_intel=80)], [3, 1, 4, 5])
        for kwargs in ({'min_intel': True}, {'max_intel': 256}, {'min_intel': 80, 'max_intel': 80}):
            with self.assertRaises(ValueError):
                filter_roster(list(rows.values()), **kwargs)

    def test_politics_strict_lower_no_upper_and_optional_ceiling(self):
        _,rows=self.rows();rows=copy.deepcopy(rows[:3])
        for r,n in zip(rows,(110,111,121)):r['politics']=n;r['blade']=100
        self.assertEqual([r['politics'] for r in filter_roster(rows,'politics',min_politics=110)],[121,111])
        self.assertEqual([r['politics'] for r in filter_roster(rows,min_politics=110,max_politics=120)],[111])
        for kwargs in ({'min_politics':True},{'max_politics':256},{'min_politics':110,'max_politics':110}):
            with self.assertRaises(ValueError):filter_roster(rows,**kwargs)

    def test_city_rank_share_ties_hidden_rival_and_unknown(self):
        p,refs=fixture();b=binding(p)
        with patch.dict('officer_reference.INDEX',refs):
            rows=probability_roster(p,b)
            self.assertTrue(all(r['city_rank']==1 and r['city_top_tied'] for r in rows))
            self.assertEqual(roster_cell(rows[0],'city_top'),'并列第一')
            self.assertAlmostEqual(rows[0]['city_success_share'],.2)
            # Rival is removed only from display eligibility, not the native full city pool.
            p['state']['entities']['generals'][0]['relation_byte_2e']=90
            with patch('quick_control_model.wild_candidates',return_value=copy.deepcopy([r for r in rows if r['id']!=1])):
                hidden=probability_roster(p,b)
            self.assertTrue(all(r['city_rank']==2 and r['city_pool_count']==5 for r in hidden))
            self.assertTrue(all(roster_cell(r,'city_top')=='非第一' for r in hidden))
            self.assertTrue(roster_cell(hidden[0],'city_rank').startswith('第2名/'))
            self.assertFalse(filter_roster(hidden,city_first_only=True))
            full=probability_roster(p,b)
            self.assertEqual([r['id'] for r in filter_roster(full,city_first_only=True)],[1])
            p['state']['entities']['generals'][0].pop('relation_byte_2e')
            unknown=probability_roster(p,b)
            self.assertTrue(all(r['city_rank'] is None and r['city_success_share'] is None for r in unknown))
            self.assertEqual(roster_cell(unknown[0],'city_top'),'未知')
            self.assertFalse(filter_roster(unknown,city_first_only=True))

    def test_zero_probability_never_claims_city_winner(self):
        p,refs=fixture();p['state']['entities']['lords'][0]['prestige']=0
        with patch.dict('officer_reference.INDEX',refs):rows=probability_roster(p,binding(p))
        self.assertTrue(all(r['city_rank'] is None and r['city_success_share'] is None for r in rows))

    def test_selected_row_not_highest_is_rechecked_and_dispatches_without_hooks(self):
        import io,json
        from quick_control_native import dispatch_request
        p,refs=fixture();b=binding(p)
        with patch.dict('officer_reference.INDEX',refs):
            row=probability_roster(p,b)[-1]
            req=json.loads(json.dumps({'action':'recruit_roster','selection':row}))
            self.assertEqual(validate_roster_request(p,b,req)['id'],row['id'])
            with self.assertRaises(ValueError):validate_roster_request(p,b,req,{row['city_id']})
            n=Mock();n.bound=b;e=Mock();e.active=None;recruiter=Mock();recruiter.pending={}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(p).encode())):
                dispatch_request(n,e,req,True,False,Mock(),recruiter)
            self.assertEqual(recruiter.submit_ordinary.call_args.args[0]['id'],row['id'])
            recruiter.install.assert_not_called();e.execute.assert_not_called()
            p['state']['entities']['generals'][0]['relation_byte_2e']=0
            with self.assertRaises(ValueError):validate_roster_request(p,b,req)

    def test_real_ui_columns_filters_selection_and_rebind_without_input(self):
        import tkinter as tk
        from officer_roster import OfficerRoster,COLUMNS,POLITICS_COLUMNS,INTEL_COLUMNS
        try:root=tk.Tk()
        except tk.TclError:self.skipTest('no display')
        panel=SimpleNamespace(root=root,ready=False,bound=None,current_state={},pending_targets={},recruit_officer=Mock())
        ui=OfficerRoster(panel,'http://invalid')
        try:
            p,rows=self.rows();panel.ready=True;panel.bound=binding(p)
            import time
            ui.bound=panel.bound;ui.rows=rows;ui.updated_at=time.monotonic();ui.render();root.update()
            self.assertEqual(tuple(ui.tree['columns']),tuple(k for k,_,_ in COLUMNS))
            self.assertEqual(ui.sort.get(),'统武从高到低')
            self.assertFalse(ui.city_first_only.get())
            ui.city_first_only.set(True);ui.render()
            self.assertTrue(all(r['city_rank']==1 for r in ui.visible.values()))
            ui.city_first_only.set(False);ui.render()
            self.assertEqual(ui.min_blade.get(),'170');self.assertIn('politics',ui.tree['columns'])
            original=copy.deepcopy(ui.rows)
            for r,n in zip(ui.rows,(110,111,121,112,90)):r['politics']=n;r['blade']=100
            for variable in ui.skill_vars.values():variable.set(True)
            ui.mode.set('politics');ui.change_mode();root.update()
            self.assertEqual(tuple(ui.tree['displaycolumns']),POLITICS_COLUMNS)
            self.assertEqual(ui.skill_controls.winfo_manager(),'')
            self.assertNotIn('统武从高到低',ui.sort_choice['values'])
            self.assertEqual(ui.min_politics.get(),'110');self.assertEqual(ui.max_politics.get(),'')
            self.assertEqual([r['politics'] for r in ui.visible.values()],[121,112,111])
            ui.tree.selection_set(ui.tree.get_children()[0]);ui.choose()
            self.assertNotIn('技能：',ui.detail.get());self.assertNotIn('统武 ',ui.detail.get())
            ui.max_politics.set('120');self.assertTrue(all(110<r['politics']<=120 for r in ui.visible.values()))
            ui.min_politics.set('invalid');self.assertFalse(ui.visible)
            ui.min_politics.set('110');ui.max_politics.set('');ui.rows=original
            ui.mode.set('blade');ui.change_mode();root.update()
            self.assertEqual(ui.skill_controls.winfo_manager(),'pack')
            self.assertTrue(all(v.get() for v in ui.skill_vars.values()))
            for variable in ui.skill_vars.values():variable.set(False)
            ui.min_blade.set('');ui.render()
            gid=ui.tree.get_children()[0];ui.tree.selection_set(gid);ui.choose()
            ui.set_sort('录取估算从高到低');self.assertEqual(ui.tree.selection(),(gid,))
            self.assertIn('录取估算',ui.detail.get())
            panel.current_state=dict(mode=2,phase=1,allowance=1,orders_used=0,modal=0)
            ui.update_button();self.assertEqual(str(ui.recruit_button['state']),'normal')
            ui.recruit();panel.recruit_officer.assert_called_once()
            self.assertEqual(panel.recruit_officer.call_args.args[0]['id'],int(gid))
            panel.pending_targets={1:{'city_id':ui.visible[gid]['city_id']}};ui.update_button()
            self.assertEqual(str(ui.recruit_button['state']),'disabled');panel.pending_targets={}
            ui.mode.set('intel');ui.change_mode();root.update()
            self.assertEqual(tuple(ui.tree['displaycolumns']),INTEL_COLUMNS)
            self.assertEqual(ui.skill_controls.winfo_manager(),'')
            self.assertEqual(ui.blade_controls.winfo_manager(),'')
            self.assertEqual(ui.politics_controls.winfo_manager(),'')
            self.assertEqual(ui.intel_controls.winfo_manager(),'pack')
            self.assertEqual(ui.sort.get(),'智力从高到低')
            self.assertEqual(ui.min_intel.get(),'90')
            self.assertFalse(hasattr(ui,'max_intel'))
            self.assertNotIn('统武从高到低',ui.sort_choice['values'])
            self.assertFalse(ui.visible)
            ui.min_intel.set('0');self.assertTrue(ui.visible)
            ui.tree.selection_set(ui.tree.get_children()[0]);ui.choose()
            self.assertIn('特殊成功率',ui.detail.get());self.assertNotIn('统武 ',ui.detail.get())
            ui.min_intel.set('1');self.assertFalse(ui.visible)
            ui.min_intel.set('甲');self.assertFalse(ui.visible);ui.min_intel.set('90')
            ui.mode.set('blade');ui.change_mode();root.update()
            self.assertEqual(ui.intel_controls.winfo_manager(),'')
            ui.min_blade.set('invalid');self.assertFalse(ui.visible);ui.min_blade.set('')
            ui.skill_vars['bow'].set(True);ui.skill_vars['ambush'].set(True);ui.render()
            self.assertTrue(ui.visible);self.assertTrue(all(r['bow'] and r['ambush'] for r in ui.visible.values()))
            self.assertIn(' / ',ui.note.get())
            panel.bound=dict(panel.bound,pid=panel.bound['pid']+1);ui.poll()
            self.assertFalse(ui.rows);self.assertFalse(ui.tree.get_children())
            self.assertFalse(hasattr(ui,'send'))
        finally:ui.close();root.destroy()


if __name__=='__main__':unittest.main()
