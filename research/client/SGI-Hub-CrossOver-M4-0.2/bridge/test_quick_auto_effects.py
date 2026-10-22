import struct
import unittest
from contextlib import nullcontext
from unittest.mock import Mock,patch
from quick_auto_effects import AutoEffects,auto_trampoline,AUTO_SITES
from quick_control_native import dispatch_request


def state(**changes):
    # Keep native tests independent of Tk, absent from the embedded bridge Python.
    result = dict(document=0x100000, view=0x200000, phase=1, mode=2, time_setting=1,
                  unit_count=0, start_tick=100000, tick=110000, allowance=1,
                  ending=0, modal=0, native_dialogs=False, widget_count=0, map_mode=0,
                  selected_unit=0, selected_order=-1, strategy_dialog=0,
                  recruit_dialog=0, map_widget=0, orders_used=0, hwnd=111, main_hwnd=110)
    result.update(changes); return result


class AutoEffectsTests(unittest.TestCase):
    def helper(self):
        native=Mock();native.bound={'core':0x100000};effects=Mock();effects.active=None
        emit=Mock();before=Mock();a=AutoEffects(native,emit,effects,before)
        native.capture.return_value=state()
        return a,native,effects,emit,before

    def test_toggle_does_not_send_game_order_and_waits_for_strategic_input(self):
        a,n,e,emit,before=self.helper();a.install=Mock();a.set_enabled(True,True)
        n.capture.return_value=state(phase=3,selected_unit=123,selected_order=0)
        a.poll();a.install.assert_not_called();n.execute.assert_not_called();before.assert_not_called()
        n.capture.return_value=state();a.last_poll=0;a.poll();a.install.assert_called_once()
        a.restore=Mock();a.set_enabled(False,True);a.restore.assert_called_once();self.assertFalse(a.enabled)

    def test_disabled_invalid_and_active_confirmation_cannot_enable(self):
        a,n,e,emit,before=self.helper()
        for value,allowed in ((True,False),(1,True)):
            with self.assertRaises(ValueError):a.set_enabled(value,allowed)
        e.active={'action':'alms'}
        with self.assertRaises(ValueError):a.set_enabled(True,True)
        self.assertFalse(a.enabled);n.execute.assert_not_called()

    def test_auto_mode_blocks_double_modifier_but_allows_focus_and_ordinary_recruit(self):
        a,n,e,emit,before=self.helper();a.enabled=True
        for action in ('infantry','cavalry','bow','alms'):
            with self.assertRaises(ValueError):dispatch_request(n,e,{'action':action},True,True,emit,automatic=a)
        e.execute.assert_not_called();n.execute.assert_not_called()
        for action in ('focus_unit','recruit'):
            dispatch_request(n,e,{'action':action},True,True,emit,automatic=a)
            n.execute.assert_called_with(action,True,True,emit,False)

    def test_scope_change_restores_and_disables_without_auto_retry(self):
        a,n,e,emit,before=self.helper();a.enabled=True;a.hooks={1:b'hook'};a.context=(1,2,3,0,16)
        a.observe=Mock();a.restore=Mock(side_effect=lambda:setattr(a,'hooks',None))
        a.identity=Mock(return_value=(1,2,3,0,17));a.poll()
        a.restore.assert_called_once();self.assertFalse(a.enabled)

    def test_three_orders_and_phase_end_keep_switch_on_then_rearm_next_input(self):
        for changes in ({'orders_used':3},{'ending':1},{'phase':2},{'phase':3},{'mode':3}):
            with self.subTest(changes=changes):
                a,n,e,emit,before=self.helper();a.enabled=True;a.hooks={1:b'hook'}
                a.context=(1,2,3,0,16);a.identity=Mock(return_value=a.context)
                a.observe=Mock();a.restore=Mock(side_effect=lambda:setattr(a,'hooks',None))
                n.capture.return_value=state(**changes);a.poll()
                a.restore.assert_called_once();self.assertTrue(a.enabled);self.assertIsNone(a.hooks)
                n.capture.return_value=state(orders_used=0,ending=0,phase=1,mode=2)
                a.install=Mock();a.last_poll=0;a.poll()
                a.install.assert_called_once();self.assertTrue(a.enabled)

    def test_failed_install_stops_auto_retries(self):
        a,n,e,emit,before=self.helper();a.enabled=True;a.install=Mock(side_effect=ValueError('conflict'))
        with self.assertRaises(ValueError):a.poll()
        self.assertFalse(a.enabled);a.last_poll=0;a.poll();self.assertEqual(a.install.call_count,1)

    def test_changed_force_while_waiting_cannot_rearm_under_the_old_toggle(self):
        a,n,e,emit,before=self.helper();a.enabled=True;a.scope=(1,2,3,0,16)
        a.identity=Mock(return_value=(1,2,3,0,17));a.install=Mock()
        n.capture.return_value=state(phase=3,orders_used=3);a.poll()
        self.assertFalse(a.enabled);self.assertIsNone(a.scope);a.install.assert_not_called()
        a.last_poll=0;n.capture.return_value=state();a.poll();a.install.assert_not_called()

    def test_counter_receipts_keep_unknown_commit_and_expose_missing_operands(self):
        a,n,e,emit,before=self.helper();a.hooks={1:b'hook'};a.marker=0x200000
        n.read.return_value=struct.pack('<12I',2,97,291,0,0,0,0,0,0,1,2,16)
        a.observe();rows=[c.args[0] for c in emit.call_args_list]
        self.assertEqual(len(rows),2);self.assertTrue(all(r['operand_verified'] for r in rows))
        self.assertEqual(rows[0]['omitted_intermediate_operands'],1)
        self.assertTrue(all(r['command_committed'] is None and r['game_order_sent'] is False for r in rows))
        a.observe();self.assertEqual(emit.call_count,2)

    def test_unreadable_counter_does_not_prevent_hook_restoration(self):
        a,n,e,emit,before=self.helper();a.hooks={key:b'x'*len(value) for key,value in AUTO_SITES.items()}
        a.observe=Mock(side_effect=OSError('counter read failed'));a.patch.writer=Mock(return_value=nullcontext(1))
        a.patch.frozen=Mock(return_value=nullcontext());a.patch.code=Mock()
        n.read.side_effect=lambda address,size:a.hooks[address]
        a.restore();self.assertIsNone(a.hooks);self.assertEqual(a.patch.code.call_count,2)

    def test_input_hooks_do_not_patch_bow_cap_or_settlement(self):
        for alms,site in ((False,0x4a3c88),(True,0x4a482c)):
            code,hook=auto_trampoline(0x1000000,0x1000800,0x200000,0x300000,0x400000,0,16,alms)
            self.assertEqual(len(hook),len(AUTO_SITES[site]))
            self.assertEqual(0x1000000+len(code)+struct.unpack('<i',code[-4:])[0],site+len(AUTO_SITES[site]))
        self.assertEqual(set(AUTO_SITES),{0x4a3c88,0x4a482c})
