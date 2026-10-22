"""Behavior gates and unknown input receipts for the local control panel."""
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest
import struct
import queue
import time
from unittest.mock import Mock
from contextlib import nullcontext
from unittest.mock import patch
import officer_reference

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from quick_control_model import BUILD, DESTRUCTOR_HOTFIX_BUILD, POLICIES, binding, duration_ms, timer_value, extension_plan, require_menu, wild_candidates, select_candidate, candidate_previews, candidate_label, recruitment_hint
from quick_control import Panel
from quick_control_native import Native
from quick_recruit import Recruit,trampolines,multi_trampolines,SITES


def state(**changes):
    result = dict(document=0x100000, view=0x200000, phase=1, mode=2, time_setting=1,
                  unit_count=0, start_tick=100000, tick=110000, allowance=1,
                  ending=0, modal=0, native_dialogs=False, widget_count=0, map_mode=0,
                  selected_unit=0, selected_order=-1, strategy_dialog=0,
                  recruit_dialog=0, map_widget=0, orders_used=0, hwnd=111, main_hwnd=110)
    result.update(changes); return result


class Controls(unittest.TestCase):
    def test_unified_automation_defaults_on_and_retains_user_choice_across_stages(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            panel=Panel(root,smoke=True);panel.ready=True;panel.write=Mock();panel.record=Mock()
            panel.bound=dict(source_id='test',pid=10)
            self.assertTrue(panel.automation.get());panel.settings()
            request=panel.write.call_args.args[0]
            self.assertTrue(request['automation_enabled'])
            self.assertNotIn('auto_time',request);self.assertNotIn('auto_x3',request)
            for phase,orders in ((1,3),(3,3),(1,0)):
                panel.show_state(state(phase=phase,orders_used=orders))
                panel.update_buttons()
                self.assertTrue(panel.automation.get())
                self.assertEqual(str(panel.auto_time_switch['state']),'normal')
            panel.automation.set(False);panel.settings()
            request=panel.write.call_args.args[0]
            self.assertFalse(request['automation_enabled'])
            panel.events.put(dict(kind='ready',state=state(),hotkeys=[]))
            panel.refresh_previews=Mock();panel.drain()
            self.assertFalse(panel.automation.get())
            self.assertFalse(panel.write.call_args.args[0]['automation_enabled'])
            panel.events.put(dict(kind='automation_status',enabled=False,note='三项辅助已关闭'))
            panel.drain();self.assertIn('WASD已关闭',panel.map_keys.get())
        finally:root.destroy()

    def test_military_extension_button_and_disabled_reason(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            panel=Panel(root,smoke=True)
            panel.ready=True
            for phase in (3,4,5):
                panel.current_state=state(phase=phase,unit_count=9,orders_used=3,selected_unit=0x123456)
                panel.update_buttons()
                self.assertEqual(str(panel.buttons['extend']['state']),'normal')
                self.assertIn('军事输入可用',panel.extension_hint.get())
            panel.current_state=state(phase=3,unit_count=9,modal=1)
            panel.update_buttons()
            self.assertEqual(str(panel.buttons['extend']['state']),'disabled')
            self.assertIn('关闭游戏弹窗',panel.extension_hint.get())
        finally:root.destroy()

    def test_ten_seconds_per_click_and_wrap(self):
        s = state(start_tick=0xfffffff0, tick=0x1ff0)
        p = extension_plan(s, True, True)
        after = dict(s, start_tick=p['after'])
        self.assertEqual(p['after'], 9984)
        self.assertEqual(timer_value(after) - timer_value(s), 10000)
        twice = extension_plan(after, True, True)
        self.assertEqual(timer_value(dict(after, start_tick=twice['after'])) - timer_value(s), 20000)
        self.assertEqual(p['address'], s['document']+0x6c)

    def test_game_duration_modes(self):
        self.assertEqual([duration_ms(1,s,0) for s in range(4)], [60000,90000,120000,None])
        self.assertEqual([duration_ms(2,s,0) for s in range(4)], [20000,40000,60000,None])
        self.assertEqual([duration_ms(3,s,1) for s in range(4)], [30000,60000,90000,None])
        self.assertEqual([duration_ms(5,s,0) for s in range(4)], [20000,20000,20000,None])

    def test_extension_refuses_unlimited_expiring_modal_and_unapproved(self):
        for s in (state(time_setting=3), state(tick=188001), state(tick=190001),
                  state(modal=1), state(native_dialogs=True), state(phase=2), state(mode=1), state(mode=3), state(ending=1)):
            with self.subTest(s=s), self.assertRaises(ValueError): extension_plan(s,True,True)
        for enabled, allow in ((False,True),(True,False),(False,False)):
            with self.assertRaises(ValueError): extension_plan(state(),enabled,allow)

    def test_native_commands_reject_modal_busy_and_unknown(self):
        for action, command in [('recruit',32836),('infantry',32822),('cavalry',32823),('bow',32824)]:
            self.assertEqual(require_menu(state(),action,True),command)
        for changes in [dict(mode=1),dict(modal=1),dict(widget_count=1),dict(map_mode=1),dict(orders_used=3),
                        dict(recruit_dialog=123),dict(selected_order=0),dict(phase=5),dict(native_dialogs=True)]:
            with self.assertRaises(ValueError): require_menu(state(**changes),'recruit',True)
        with self.assertRaises(ValueError): require_menu(state(),'arbitrary',True)

    def test_bind_source_freshness_build_and_identity(self):
        now = datetime.now(timezone.utc)
        p = dict(source_id='test', identity=dict(pid=10,creation_filetime=11,path=r'C:\game\SANPK.exe'),
                 state=dict(core_address='0x100000',build_sha256=BUILD,capture_end=now.isoformat()))
        self.assertEqual(binding(p,now)['pid'],10)
        p['state']['build_sha256']=DESTRUCTOR_HOTFIX_BUILD
        self.assertEqual(binding(p,now)['build'],DESTRUCTOR_HOTFIX_BUILD)
        p['state']['build_sha256']=BUILD
        for seconds in (-11,1):
            p['state']['capture_end'] = (now+timedelta(seconds=seconds)).isoformat()
            with self.assertRaises(ValueError): binding(p,now)
        p['state']['capture_end']=now.isoformat();p['state']['build_sha256']='unknown'
        with self.assertRaises(ValueError): binding(p,now)

    def test_bind_waits_for_offline_or_new_game_without_old_identity(self):
        for payload in ({'state':None,'identity':None,'error':'游戏进程不在线'},
                        {'state':None,'identity':{'pid':10}}, {},
                        {'state':{},'identity':None}):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError,'当前尚未进入游戏'):
                binding(payload)

    def test_write_disabled_does_not_open_write_handle(self):
        native=object.__new__(Native)
        class NoKernel:
            def OpenProcess(self,*args): raise AssertionError('write handle must not be opened')
        native.k=NoKernel()
        with self.assertRaises(ValueError): native.extend(state(),True,False,lambda e:None)

    def test_officers_sort_live_values_without_success_labels(self):
        p=dict(source_id='test',identity=dict(pid=10,creation_filetime=11,path=r'C:\game\SANPK.exe'),
               state=dict(core_address='0x100000',build_sha256=BUILD,capture_end=datetime.now(timezone.utc).isoformat(),
                          entities=dict(cities_and_barriers=[dict(city_id=4,type='city',name='测试城')],generals=[])))
        for gid,pol,lead,war in [(1,100,70,70),(2,80,90,90),(3,90,80,80)]:
            p['state']['entities']['generals'].append(dict(general_id_raw=gid,name=str(gid),owner_raw=65535,
                  status_code=1,location_city_id=4,attributes=dict(pol=pol,lead=lead,war=war)))
        bound=binding(p)
        self.assertEqual([r['id'] for r in wild_candidates(p,bound,'politics')],[1,3,2])
        self.assertEqual([r['id'] for r in wild_candidates(p,bound,'blade')],[2,3,1])
        self.assertTrue(all(r['success_probability'] is None and not r['target_guaranteed'] for r in wild_candidates(p,bound)))
        p['state']['entities']['generals'][0]['attributes'].pop('pol')
        self.assertEqual(len(wild_candidates(p,bound)),2)
        with self.assertRaises(ValueError):wild_candidates(p,dict(bound,pid=99))

    def test_target_requires_both_optins_before_any_read_or_input(self):
        r=object.__new__(Recruit)
        r.target=lambda *args: self.fail('no target read before optin')
        for enabled,allow in [(False,True),(True,False),(False,False)]:
            with self.assertRaises(ValueError):r.submit(1,2,enabled,allow,lambda:self.fail('no menu input'))

    def policy_payload(self):
        p=dict(source_id='test',identity=dict(pid=10,creation_filetime=11,path=r'C:\game\SANPK.exe'),
               state=dict(core_address='0x100000',build_sha256=BUILD,capture_end=datetime.now(timezone.utc).isoformat(),
                          entities=dict(cities_and_barriers=[dict(city_id=4,type='city',name='测试城')],generals=[])))
        refs={}
        # Higher raw 统武 without 伏 must not win either skill combination.
        for gid,pol,lead,war,skills in [(1,20,10,10,['弓箭','埋伏']),
                (2,10,15,15,['骑马','伏兵']),(3,9,17,15,['弓箭','埋伏']),
                (4,19,120,120,['骑马','弓箭']),(5,8,15,15,['全技能'])]:
            name='fixture-'+str(gid);attrs=dict(pol=pol,lead=lead,war=war,intel=1,cha=2)
            p['state']['entities']['generals'].append(dict(general_id_raw=gid,name=name,owner_raw=65535,
                status_code=1,location_city_id=4,attributes=attrs))
            refs[name]=[dict(stats={web:attrs[key] for key,web in officer_reference.KEYS.items()},skills=skills)]
        return p,refs

    def test_three_policies_current_maximum_no_threshold_and_ties(self):
        p,refs=self.policy_payload()
        with patch.dict(officer_reference.INDEX,refs):
            b=binding(p)
            self.assertEqual(select_candidate(p,b,'politics')['id'],1)
            self.assertEqual(select_candidate(p,b,'ride_ambush')['id'],2)
            self.assertEqual(select_candidate(p,b,'bow_ambush')['id'],3)
            self.assertEqual(select_candidate(p,b,'ride_ambush')['eligible_count'],2)
            # Removing the selected wild general must pick the current next best.
            p['state']['entities']['generals'][1]['owner_raw']=3
            self.assertEqual(select_candidate(p,b,'ride_ambush')['id'],5)

    def test_preview_shows_each_live_maximum_and_correct_metric(self):
        p, refs = self.policy_payload()
        with patch.dict(officer_reference.INDEX, refs):
            b = binding(p); rows = candidate_previews(p, b)
            self.assertEqual([rows[k]['id'] for k in POLICIES], [1,2,3,5])
            self.assertEqual(candidate_label('politics', rows['politics']), '政治优选\nfixture-1 · 政治 20')
            self.assertEqual(candidate_label('ride_ambush', rows['ride_ambush']), '统武·骑伏\nfixture-2 · 统武 30')
            p['state']['entities']['generals'][0]['owner_raw'] = 3
            self.assertEqual(candidate_previews(p,b)['politics']['id'],4)
            p['state']['entities']['generals'][4]['owner_raw'] = 3
            self.assertIn('error',candidate_previews(p,b)['ride_charge_ambush'])
            with self.assertRaises(ValueError):candidate_previews(p,dict(b,pid=99))
            p['state']['capture_end']=(datetime.now(timezone.utc)-timedelta(seconds=11)).isoformat()
            with self.assertRaises(ValueError):candidate_previews(p,b)

    def panel_stub(self):
        panel=object.__new__(Panel)
        panel.closed=False;panel.smoke=False;panel.ready=False;panel.connecting=False
        panel.busy=False;panel.selecting=False;panel.next_connect=0
        panel.preview_at=0;panel.previews={};panel.bound={'pid':10}
        panel.preview_loading=False;panel.proc=None;panel.connection_error=None
        panel.pending_targets={};panel.submitted_ids=set();panel.current_state={}
        panel.inspecting_id=None
        panel.events=queue.Queue();panel.pending_id=None;panel.record=Mock()
        panel.root=Mock();panel.policy_buttons={k:Mock() for k in POLICIES}
        for name in ('test','allow_write','allow_target','status','note','timer'):
            setattr(panel,name,Mock())
        panel.update_buttons=Mock();panel.connect=Mock();panel.refresh_previews=Mock()
        return panel

    def test_extension_button_matches_native_plan_not_just_connection(self):
        p=self.panel_stub();p.ready=True;p.target_pending=False;p.policy_hint=Mock()
        p.buttons={k:Mock() for k in ('extend','recruit')};p.refresh_button=Mock();p.connect_button=Mock()
        p.test.get.return_value=True;p.allow_write.get.return_value=True
        for s,expected in ((state(orders_used=3),'normal'),(state(phase=5),'normal'),
                           (state(phase=5,mode=3),'disabled'),(state(phase=5,allowance=0),'disabled'),
                           (state(time_setting=3),'disabled'),(state(native_dialogs=True),'disabled'),
                           (state(tick=189000),'disabled'),(state(ending=1),'disabled')):
            p.current_state=s;Panel.update_buttons(p)
            self.assertEqual(p.buttons['extend'].configure.call_args.kwargs['state'],expected)

    def test_auto_connect_retries_and_background_only_inspects(self):
        panel=self.panel_stub();panel.send=Mock()
        panel.marker_loading=False;panel.marker_at=0;panel.refresh_modification_label=Mock()
        panel.heartbeat();panel.connect.assert_called_once()
        panel.connect.reset_mock();panel.connecting=True
        panel.heartbeat();panel.connect.assert_not_called()
        panel.connecting=False;panel.next_connect=time.monotonic()+5
        panel.heartbeat();panel.connect.assert_not_called()
        panel.ready=True;panel.preview_at=time.monotonic()-11
        panel.heartbeat()
        panel.refresh_previews.assert_called_once()
        panel.send.assert_called_once_with('inspect',background=True)
        panel.refresh_modification_label.assert_called_once()
        self.assertFalse(panel.previews)
        panel.busy=True;panel.send.reset_mock();panel.heartbeat();panel.send.assert_not_called()

    def test_connection_loss_clears_candidates_before_rebind(self):
        panel=self.panel_stub();panel.ready=True;panel.previews={'politics':{'id':1}}
        panel.proc=Mock();panel.proc.poll.return_value=None;panel.write=Mock()
        panel.disconnect('游戏实例已变化')
        self.assertFalse(panel.ready);self.assertFalse(panel.previews)
        panel.write.assert_called_once_with({'action':'quit'})
        panel.events.put({'kind':'exit','code':0});panel.drain()
        self.assertGreater(panel.next_connect,time.monotonic())
        panel.connect.assert_not_called()

    def test_delayed_preview_from_previous_binding_is_ignored(self):
        panel=self.panel_stub();panel.ready=True
        panel.events.put({'kind':'candidate_previews','bound':{'pid':99},
                          'previews':{'politics':{'name':'old','politics':120}}})
        panel.drain()
        self.assertFalse(panel.previews)
        for button in panel.policy_buttons.values():button.configure.assert_not_called()

    def test_receipt_timeout_releases_controls_and_never_resends(self):
        panel=self.panel_stub();panel.ready=True;panel.busy=True
        panel.pending_id=7;panel.pending_at=time.monotonic()-61;panel.send=Mock()
        panel.drain()
        self.assertFalse(panel.ready);self.assertFalse(panel.busy);self.assertIsNone(panel.pending_id)
        self.assertIn('不会重发',panel.note.set.call_args.args[0])
        panel.send.assert_not_called()

    def test_changed_game_retires_only_old_helper_and_ignores_late_ready(self):
        panel=self.panel_stub();panel.ready=True;panel.busy=True;panel.pending_id=7
        panel.helper_epoch=3;panel.retire_stale_helper=Mock(side_effect=lambda _:setattr(panel,'helper_epoch',4))
        panel.marker_at=0
        panel.events.put(dict(kind='binding_changed',bound=panel.bound,note='当前游戏实例已改变'))
        panel.events.put(dict(kind='ready',helper_epoch=3,state={'old':True}))
        panel.drain()
        panel.retire_stale_helper.assert_called_once()
        self.assertFalse(panel.ready);self.assertFalse(panel.busy);self.assertFalse(panel.current_state)

    def test_core_change_in_same_process_never_force_stops_helper(self):
        import subprocess
        panel=self.panel_stub();panel.proc=Mock();panel.proc.wait.side_effect=subprocess.TimeoutExpired('helper',3)
        panel.helper_epoch=1;panel.bound=dict(pid=10,created=20,image='game',core=30)
        with patch('quick_control.threading.Thread') as thread:
            panel.retire_stale_helper(dict(panel.bound,core=40))
            thread.call_args.kwargs['target']()
        panel.proc.terminate.assert_not_called();panel.proc.kill.assert_not_called()
        self.assertEqual(panel.events.get_nowait()['kind'],'helper_retire_waiting')

    def test_pending_hint_explains_remaining_orders_and_names_target(self):
        hint=recruitment_hint(True,1,['孙坚'])
        self.assertIn('待结算：孙坚',hint)
        self.assertIn('可继续录取下一名',hint)
        self.assertIn('剩余2次',hint)
        self.assertIn('3次指令已用完',recruitment_hint(True,3))
        self.assertNotIn('待结算',recruitment_hint(True))

    def test_background_refresh_does_not_disable_or_clear_user_action(self):
        panel=self.panel_stub();panel.ready=True;panel.counter=0;panel.target_pending=False
        panel.test.get.return_value=False;panel.write=Mock()
        panel.send('inspect',background=True)
        self.assertFalse(panel.busy);self.assertEqual(panel.inspecting_id,1)
        self.assertIsNone(panel.pending_id)
        panel.send('inspect',background=True);panel.write.assert_called_once()
        # A slow inspection's receipt must not release an unrelated user action.
        panel.busy=True;panel.pending_id=2;panel.pending_at=time.monotonic()
        panel.events.put({'kind':'result','action':'inspect','request_id':1,
                          'result':{'status':'observed'}})
        panel.drain()
        self.assertTrue(panel.busy);self.assertEqual(panel.pending_id,2)
        self.assertIsNone(panel.inspecting_id)

    def test_skill_unknown_or_changed_five_stats_never_guessed(self):
        p,refs=self.policy_payload()
        with patch.dict(officer_reference.INDEX,refs):
            b=binding(p)
            p['state']['entities']['generals'][2]['attributes']['intel']=2
            self.assertEqual(select_candidate(p,b,'bow_ambush')['id'],5)
            p['state']['entities']['generals'][4]['attributes'].pop('cha')
            self.assertEqual(select_candidate(p,b,'bow_ambush')['id'],1)
            p['state']['entities']['generals'][0]['name']='unknown'
            with self.assertRaises(ValueError):select_candidate(p,b,'bow_ambush')
            # Politics can still use observed stats without a skill match.
            self.assertEqual(select_candidate(p,b,'politics')['id'],1)

    def test_ambiguous_general_identity_is_excluded_entirely(self):
        p,refs=self.policy_payload()
        p['state']['entities']['generals'].append(dict(p['state']['entities']['generals'][0]))
        with patch.dict(officer_reference.INDEX,refs):
            self.assertEqual(select_candidate(p,binding(p),'politics')['id'],4)

    def test_ride_charge_ambush_requires_all_three_and_uses_current_max(self):
        p,refs=self.policy_payload()
        with patch.dict(officer_reference.INDEX,refs):
            b=binding(p)
            # Higher 骑伏 candidate without 奇袭/突击 must be excluded.
            self.assertEqual(select_candidate(p,b,'ride_charge_ambush')['id'],5)
            refs['fixture-2'][0]['skills'].append('奇袭')
            self.assertEqual(select_candidate(p,b,'ride_charge_ambush')['id'],2)
            refs['fixture-2'][0]['skills']=['突击','伏兵']
            self.assertEqual(select_candidate(p,b,'ride_charge_ambush')['id'],5)
            refs['fixture-2'][0]['skills']=['骑马','突击','伏兵']
            self.assertEqual(select_candidate(p,b,'ride_charge_ambush')['id'],2)
            p['state']['entities']['generals'][1]['owner_raw']=3
            self.assertEqual(select_candidate(p,b,'ride_charge_ambush')['id'],5)

    def test_changed_selected_attributes_reject_before_menu_or_patch(self):
        r=object.__new__(Recruit);r.pending={};raw=bytearray(96);raw[37:42]=bytes([10,20,30,40,50])
        r.target=lambda *args:dict(raw_before=raw.hex())
        class Fake:pass
        r.n=Fake();r.n.capture=lambda:state()
        for attrs in (dict(lead=10,war=20,pol=41),{},dict(lead=10,war=20,pol=True)):
            with self.assertRaises(ValueError):r.submit(1,2,True,True,lambda:self.fail('no menu on stale selection'),attrs)

    def test_wine_navigation_launches_only_quick_panel(self):
        import wine_nav
        with patch.object(wine_nav,'spawn_detached') as spawn,patch.object(wine_nav,'open_window') as window:
            wine_nav.main(['--launch','quick'])
            spawn.assert_called_once_with([sys.executable,'-B',str(ROOT/'app/quick_control.py')])
            window.assert_not_called()

    def test_settlement_distinguishes_ownership_standby_and_other_force(self):
        for owner,status,expected in [(65535,1,None),(3,9,'target_recruit_settled'),
                                      (3,0,'target_recruit_settled'),(4,9,'target_recruit_failed')]:
            with self.subTest(owner=owner,status=status):
                raw=bytearray(0x60);struct.pack_into('<I',raw,0,0x5056f0)
                struct.pack_into('<H',raw,8,owner);struct.pack_into('<H',raw,0xa,537)
                struct.pack_into('<H',raw,0x21,status)
                class Fake:pass
                n=Fake();n.read=lambda *args:bytes(raw)
                r=object.__new__(Recruit);r.n=n;r.last_poll=0
                r.pending={537:dict(general_id=537,force_id=3,address=0x100000)}
                events=[];restored=[];r.emit=events.append;r.restore=lambda:restored.append(True)
                r.poll()
                if expected is None:self.assertTrue(r.pending);self.assertFalse(events);self.assertFalse(restored)
                else:
                    self.assertFalse(r.pending);self.assertEqual(events[0]['kind'],expected)
                    self.assertEqual(restored,[True])
                    if owner==3:
                        self.assertTrue(events[0]['recruitment_ownership_verified'])
                        self.assertEqual(events[0]['standby_verified'],status==0)
                        self.assertFalse(events[0]['server_result_verified'])

    def test_hook_branches_and_exact_replacement_sizes(self):
        bodies,hooks=trampolines(0x6000000,3,6,537)
        self.assertEqual({a:len(b) for a,b in hooks.items()},{a:len(b) for a,b in SITES.items()})
        for site,data in hooks.items():
            destination=site+5+struct.unpack_from('<i',data,1)[0]
            self.assertIn(destination,bodies)
        for bad in [-1,65535,True,None]:
            with self.assertRaises(ValueError):trampolines(0x6000000,bad,6,537)

    def test_submitted_targets_are_excluded_from_all_next_choices(self):
        p,refs=self.policy_payload()
        with patch.dict(officer_reference.INDEX,refs):
            b=binding(p)
            rows=candidate_previews(p,b,{1,2})
            self.assertEqual(rows['politics']['id'],4)
            self.assertEqual(rows['ride_ambush']['id'],5)
            self.assertEqual(rows['bow_ambush']['id'],3)
            self.assertNotIn(select_candidate(p,b,'ride_charge_ambush',{2})['id'],{2})

    def test_multi_target_filters_reject_duplicate_cross_force_and_fourth(self):
        targets=[dict(force_id=3,city_id=6,general_id=g) for g in (1,2,3)]
        bodies,hooks=multi_trampolines(0x6000000,targets)
        self.assertTrue(all(len(b)<1024 for b in bodies.values()))
        self.assertEqual({a:len(b) for a,b in hooks.items()},{a:len(b) for a,b in SITES.items()})
        for bad in [[],targets+[dict(force_id=3,city_id=6,general_id=4)],
                    [targets[0],targets[0]],[targets[0],dict(targets[1],force_id=4)]]:
            with self.assertRaises(ValueError):multi_trampolines(0x6000000,bad)

    def test_partial_multi_settlement_keeps_other_target_guarantee(self):
        r=object.__new__(Recruit);r.last_poll=0;r.pending={}
        raws={}
        for gid,owner in [(1,3),(2,65535)]:
            r.pending[gid]=dict(general_id=gid,force_id=3,address=gid)
            raw=bytearray(96);struct.pack_into('<I',raw,0,0x5056f0)
            struct.pack_into('<H',raw,8,owner);struct.pack_into('<H',raw,10,gid)
            struct.pack_into('<H',raw,0x21,9 if owner==3 else 1);raws[gid]=raw
        r.n=Mock();r.n.read.side_effect=lambda a,n:bytes(raws[a])
        r.restore=Mock();r.emit=Mock();r.poll()
        self.assertEqual(set(r.pending),{2});r.restore.assert_not_called()
        self.assertEqual(r.emit.call_args.args[0]['pending_count'],1)
        struct.pack_into('<H',raws[2],8,3);struct.pack_into('<H',raws[2],0x21,0)
        r.last_poll=0;r.poll()
        self.assertFalse(r.pending);r.restore.assert_called_once()

    def test_inspect_and_manual_errors_do_not_clear_unsettled_targets(self):
        panel=self.panel_stub();panel.ready=True;panel.target_pending=True
        panel.pending_targets={1:{'name':'待结算将'}}
        panel.events.put({'kind':'result','action':'recruit_target','request_id':2,
                          'result':{'status':'error','note':'本回合指令已用完'}})
        panel.drain()
        self.assertTrue(panel.ready);self.assertEqual(set(panel.pending_targets),{1})
        panel.events.put({'kind':'result','action':'inspect','request_id':3,
                          'result':{'status':'error','note':'transient round transition'}})
        panel.drain()
        self.assertTrue(panel.ready);self.assertEqual(set(panel.pending_targets),{1})
        self.assertEqual(panel.current_state,{})

    def test_failed_second_submission_restores_first_target_filter(self):
        r=object.__new__(Recruit);old={10:b'old'};new={10:b'new'}
        r.hooks=old;r.pending={1:{'general_id':1}}
        r.target=Mock(return_value={'general_id':2});r.n=Mock();r.n.capture.return_value=state()
        r.city_point=Mock(return_value=(100,(2,3)))
        def install(t):r.hooks=new;r.pending[2]=t
        r.install=install;r.point=Mock(side_effect=ValueError('unknown input receipt'))
        r.writer=lambda:nullcontext(1);r.frozen=lambda:nullcontext()
        r.n.read.return_value=b'new';r.code=Mock();r.restore=Mock()
        with self.assertRaisesRegex(ValueError,'unknown input receipt'):
            r.submit(2,6,True,True,lambda:{'status':'dialog_observed'})
        self.assertEqual(set(r.pending),{1});self.assertEqual(r.hooks,old)
        r.code.assert_called_once_with(1,10,b'old');r.restore.assert_not_called()


if __name__ == '__main__': unittest.main()
