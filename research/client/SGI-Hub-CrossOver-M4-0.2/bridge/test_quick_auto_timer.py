"""Once-per-stage automatic time and completion/uncertain-write behavior."""
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from quick_auto_timer import AutoTimer
from quick_control_model import extension_plan,timer_value,duration_ms
import test_quick_timer


def state(phase=1,season=0,**changes):
    clock=bytearray(18)
    struct.pack_into('<h',clock,4,201)
    struct.pack_into('<h',clock,10,season)
    struct.pack_into('<h',clock,12,phase)
    result=test_quick_timer.state(phase=phase,orders_used=0,round_clock=clock.hex(),
                                 player_slot_raw=0,player_force_raw=3)
    result['tick']=(result['start_tick']+duration_ms(phase,2,result['unit_count'])-800)&0xffffffff
    result.update(changes)
    return result


class AutoTimerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.n=Mock();self.n.bound=dict(pid=10,created=11,image='SANPK.exe',
                                       core=0x100912,build='test',source_id='local')
        self.n.capture.return_value=state();self.events=[]
        self.n.extend.return_value=dict(status='timer_field_verified',note='已加 60 秒')
        self.timer=AutoTimer(self.n,self.events.append,self.tmp.name)
        self.timer.set_enabled(True,True)

    def poll(self,**changes):
        if changes:self.n.capture.return_value=state(**changes)
        self.timer.last_poll=0;self.timer.poll()

    def test_one_minute_per_stage_not_per_poll_or_manual_time_change(self):
        self.poll();self.poll();self.poll(start_tick=110000)
        self.assertEqual(self.n.extend.call_count,1)
        # 默认 100%：目标 120000，测试状态剩余 800，delta = 119200。
        self.assertEqual(self.n.extend.call_args.args[-1],119200)

    def test_slider_percent_sets_target_minus_remaining(self):
        self.timer.set_percent(25)
        self.poll()
        self.assertEqual(self.timer.target_ms(), 30000)
        self.assertEqual(self.n.extend.call_args.args[-1], 30000 - 800)
        self.n.extend.reset_mock()
        self.timer.attempted.clear()
        self.timer.set_percent(50)
        self.poll(season=1)
        self.assertEqual(self.n.extend.call_args.args[-1], 60000 - 800)
        self.assertTrue(self.timer.enabled)

    def test_normal_countdown_untouched_until_last_second(self):
        for remaining in (120000,60000,5000,1001):
            self.poll(tick=220000-remaining)
            self.n.extend.assert_not_called();self.assertEqual(self.timer.attempted,set())
        self.poll(tick=219000)
        self.assertEqual(self.n.extend.call_count,1)

    def test_expired_timer_is_never_revived(self):
        for remaining in (0,-1,-500):self.poll(tick=220000-remaining)
        self.n.extend.assert_not_called();self.assertEqual(self.timer.attempted,set())

    def test_prepare_while_normal_countdown_runs_then_use_prepared_writer(self):
        prepared=Mock();prepare=Mock(return_value=prepared);self.timer.prepare=prepare
        self.poll(tick=216000)
        prepare.assert_called_once();self.n.extend.assert_not_called()
        self.poll(tick=219200)
        self.assertEqual(self.n.extend.call_args.args[-2],prepared)
        prepare.assert_called_once()

    def test_slow_prepare_expiry_or_stage_change_never_reserves_or_writes(self):
        for after in (state(tick=220001),state(season=1)):
            self.timer.prepared=None;self.timer.prepared_basis=None
            self.timer.prepare=Mock(return_value=Mock())
            self.n.capture.side_effect=[state(tick=216000),after]
            self.poll()
            self.n.extend.assert_not_called();self.assertEqual(self.timer.attempted,set())
        self.n.capture.side_effect=None

    def test_toggle_and_helper_reconnect_cannot_repeat_same_stage(self):
        self.poll();self.timer.set_enabled(False,True);self.timer.set_enabled(True,True);self.poll()
        self.timer=AutoTimer(self.n,self.events.append,self.tmp.name)
        self.timer.set_enabled(True,True);self.poll()
        self.assertEqual(self.n.extend.call_count,1)

    def test_each_military_stage_and_next_season_receive_once(self):
        self.poll()
        for phase,season in ((3,0),(4,0),(5,0),(1,1)):
            self.poll(phase=phase,season=season);self.poll()
        self.assertEqual(self.n.extend.call_count,5)

    def test_exhausted_civil_quota_does_not_extend_or_uncheck(self):
        self.poll(orders_used=3)
        self.n.extend.assert_not_called();self.assertTrue(self.timer.enabled)
        self.poll(season=1);self.assertEqual(self.n.extend.call_count,1)

    def test_native_completion_never_writes_expiry_or_sends_input(self):
        for change in (dict(mode=3),dict(ending=1),dict(allowance=0)):
            self.poll(**change);self.assertTrue(self.timer.enabled)
        self.n.extend.assert_not_called()
        self.assertFalse(self.n.execute.called)

    def test_no_selection_is_not_treated_as_military_completion(self):
        self.poll(phase=3,selected_unit=0,selected_order=-1)
        self.assertEqual(self.n.extend.call_count,1)
        self.assertFalse(self.n.execute.called)

    def test_unlimited_modal_diplomacy_and_expiring_do_not_reserve_stage(self):
        for change in (dict(time_setting=3),dict(modal=1),dict(native_dialogs=True),
                       dict(phase=2),dict(tick=218001)):
            self.poll(**change)
            self.assertTrue(self.timer.enabled);self.assertEqual(self.timer.attempted,set())
        self.n.extend.assert_not_called()
        self.n.capture.return_value=state();self.poll();self.assertEqual(self.n.extend.call_count,1)

    def test_unknown_receipt_disables_without_retry_after_reenable(self):
        self.n.extend.return_value=dict(status='unknown',note='读回未知')
        self.poll();self.assertFalse(self.timer.enabled)
        self.timer.set_enabled(True,True);self.poll()
        self.assertEqual(self.n.extend.call_count,1)

    def test_exception_after_attempt_is_not_retried_after_restart(self):
        self.n.extend.side_effect=OSError('receipt failure');self.poll()
        self.assertFalse(self.timer.enabled)
        self.timer=AutoTimer(self.n,self.events.append,self.tmp.name)
        self.timer.set_enabled(True,True);self.poll()
        self.assertEqual(self.n.extend.call_count,1)

    def test_unstable_capture_waits_without_losing_switch_or_attempt(self):
        self.n.capture.side_effect=ValueError('stage changing');self.poll()
        self.n.extend.assert_not_called();self.assertTrue(self.timer.enabled)
        self.n.capture.side_effect=None;self.poll()
        self.assertEqual(self.n.extend.call_count,1)

    def test_force_change_disarms_before_write(self):
        self.poll();self.poll(player_force_raw=4)
        self.assertFalse(self.timer.enabled);self.assertEqual(self.n.extend.call_count,1)

    def test_missing_or_mismatched_round_identity_disarms(self):
        for bad in ('', 'ab', '00'*18):
            self.timer.set_enabled(True,True)
            self.poll(round_clock=bad)
            self.assertFalse(self.timer.enabled)
        self.n.extend.assert_not_called()

    def test_reservation_is_on_disk_before_first_memory_attempt(self):
        def extend(*args):
            rows=[json.loads(s) for s in self.timer.path.read_text().splitlines()]
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['binding_sha256'],self.timer.binding_sha)
            self.assertIn(rows[0]['stage'],self.timer.attempted)
            return dict(status='timer_field_verified',note='ok')
        self.n.extend.side_effect=extend;self.poll()

    def test_disk_failure_disables_before_write(self):
        with patch('quick_auto_timer.os.fsync',side_effect=OSError('disk full')):self.poll()
        self.n.extend.assert_not_called();self.assertFalse(self.timer.enabled)

    def test_corrupt_journal_prevents_automatic_write(self):
        self.timer.path.parent.mkdir();self.timer.path.write_text('invalid json')
        self.timer=AutoTimer(self.n,self.events.append,self.tmp.name)
        self.timer.set_enabled(True,True);self.poll()
        self.assertFalse(self.timer.enabled);self.n.extend.assert_not_called()

    def test_source_binding_has_separate_reservation(self):
        self.poll();self.n.bound=dict(self.n.bound,created=12)
        self.timer=AutoTimer(self.n,self.events.append,self.tmp.name)
        self.timer.set_enabled(True,True);self.poll()
        self.assertEqual(self.n.extend.call_count,2)

    def test_disabled_or_write_not_allowed_cannot_extend(self):
        for wanted,allowed in ((False,True),(True,False),(1,True)):
            self.timer.set_enabled(wanted,allowed);self.poll()
        self.n.extend.assert_not_called()


class ExtensionDeltaTests(unittest.TestCase):
    def test_plan_accepts_any_nonzero_delta(self):
        before = state()
        for delta in (30000, 90000, 119200, -15000):
            plan = extension_plan(before, True, True, delta)
            self.assertEqual(plan['added_ms'], delta)
            self.assertEqual(plan['after'], (before['start_tick'] + delta) & 0xffffffff)


class MinuteWriteTests(unittest.TestCase):
    def test_exact_minute_civil_military_and_tick_wrap(self):
        for phase in (1,3,4,5):
            for start in (100000,0xfffffff0):
                tick=(start+duration_ms(phase,2,9)-800)&0xffffffff
                before=state(phase=phase,start_tick=start,tick=tick)
                target=(start+60000)&0xffffffff
                n=test_quick_timer.TimerTests().native([before,before,dict(before,start_tick=target)])
                result=n.extend(before,True,True,lambda e:None,60000)
                self.assertEqual(result['status'],'timer_field_verified')
                self.assertEqual(n.k.writes,[(before['document']+0x6c,struct.pack('<I',target))])
                self.assertEqual(timer_value(result['after'])-timer_value(before),60000)

    def test_quota_or_force_or_clock_changes_during_attribution_refuse_write(self):
        before=state()
        for changed in (dict(before,orders_used=3),dict(before,player_force_raw=4),
                        dict(before,round_clock=state(season=1)['round_clock'])):
            n=test_quick_timer.TimerTests().native([before,changed]);events=[]
            with self.assertRaises(ValueError):n.extend(before,True,True,events.append,60000)
            self.assertEqual(n.k.writes,[])
            self.assertEqual([e['kind'] for e in events],['timer_write_intent'])

    def test_any_nonzero_integer_delta_and_no_completed_civil_minute(self):
        for value in (-1, 1000, 60001, 119200):
            extension_plan(state(), True, True, value)
        for value in (0, True, 60000.0):
            with self.assertRaises(ValueError):
                extension_plan(state(), True, True, value)
        with self.assertRaises(ValueError):
            extension_plan(state(orders_used=3), True, True, 60000)

    def test_auto_boundary_and_expiry_during_intent_are_rechecked(self):
        for phase in (1,3,4,5):
            base=state(phase=phase);total=duration_ms(phase,2,9)
            for remaining in (1001,0,-1):
                with self.assertRaises(ValueError):
                    extension_plan(dict(base,tick=base['start_tick']+total-remaining),True,True,60000)
            for remaining in (1000,1):
                extension_plan(dict(base,tick=base['start_tick']+total-remaining),True,True,60000)
            expired=dict(base,tick=base['start_tick']+total)
            n=test_quick_timer.TimerTests().native([base,expired])
            with self.assertRaises(ValueError):n.extend(base,True,True,lambda e:None,60000)
            self.assertEqual(n.k.writes,[])


if __name__=='__main__':unittest.main()
