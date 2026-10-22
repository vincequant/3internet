"""Completion/cancellation and immutable-cost/attribute boundaries."""
import struct
import time
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch
from test_quick_control import state
from quick_effects import Effects, SITES, TRAINING, trampoline, TOKENS, TARGETS
from quick_control_model import COMMANDS, KEYS, require_menu
from quick_control import Panel
from quick_control_native import output_event


class EffectTests(unittest.TestCase):
    def test_closed_ui_pipe_keeps_restore_intent_in_recovery_record(self):
        bound=dict(pid=123,created=456);event=dict(kind='effect_restore_write_intent',address='0x450a3b')
        with tempfile.TemporaryDirectory() as folder:
            with patch('quick_control_native.__file__',str(Path(folder)/'bridge/helper.py')),patch('builtins.print',side_effect=BrokenPipeError):
                output_event(event,bound)
            rows=list((Path(folder)/'quick-control-records').glob('native-recovery-*.jsonl'))
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0].read_text()),dict(bound=bound,event=event))
    def stub(self, hit=0, used=0, **changes):
        effects=object.__new__(Effects);effects.n=Mock();effects.emit=Mock();effects.restore=Mock()
        effects.n.bound={'core':0x200000}
        effects.n.number.side_effect=lambda a,*args:0x506660 if a==0x400000 else (0x200000 if a==0x53bb30 else 0)
        effects.pending={};effects.last_poll=0;effects.rule_lord=0x400000
        effects.n.read.return_value=struct.pack('<III',hit,78,TOKENS['infantry']&0xffffffff)
        effects.n.capture.return_value=state(orders_used=used,**changes)
        effects.values=Mock(return_value={'gold':9000,'prestige':120})
        effects.active=dict(action='infantry',marker=0x300000,state=state(),before={'gold':10000},
                            at=time.monotonic()-3,operand=None)
        return effects

    def test_commands_and_hotkeys_keep_native_limits(self):
        self.assertEqual(require_menu(state(),'alms',True),32935)
        self.assertEqual(KEYS['alms'],'F11')
        for action in (*TRAINING,'alms'):
            for change in ({'orders_used':3},{'modal':1},{'phase':3},{'allowance':0}):
                with self.assertRaises(ValueError):require_menu(state(**change),action,True)
        self.assertEqual(COMMANDS['infantry'],32822)

    def test_confirmation_cancel_restores_without_effect_or_repeat(self):
        e=self.stub();e.poll()
        e.restore.assert_called_once();self.assertIsNone(e.active)
        event=e.emit.call_args.args[0]
        self.assertEqual(event['kind'],'effect_command_uncommitted');self.assertIsNone(event['operand'])
        e.n.execute.assert_not_called()

    def test_dialog_keeps_effect_armed_until_user_decides(self):
        e=self.stub(modal=1,widget_count=1);e.poll()
        e.restore.assert_not_called();self.assertIsNotNone(e.active)
        e.n.execute.assert_not_called()

    def test_prepared_operand_restores_hook_while_native_feedback_stays_open(self):
        e=self.stub(hit=1,modal=1,widget_count=1);e.poll()
        e.restore.assert_called_once();self.assertEqual(e.active['operand'],dict(before=78,after=TOKENS['infantry']&0xffffffff))
        self.assertEqual(e.emit.call_args.args[0]['kind'],'effect_operand_prepared')
        e.n.execute.assert_not_called()

    def test_queued_once_records_cost_and_operand_without_changing_attributes(self):
        e=self.stub(hit=1,used=1);e.poll();e.poll()
        self.assertIsNone(e.active);self.assertFalse(e.n.effects_pending)
        events=[x.args[0] for x in e.emit.call_args_list]
        self.assertEqual([x['kind'] for x in events],['effect_operand_prepared','effect_command_queued'])
        self.assertEqual(events[1]['before']['gold']-events[1]['after']['gold'],1000)
        self.assertEqual(events[1]['operand']['after'],TOKENS['infantry']&0xffffffff)
        e.n.execute.assert_not_called()

    def test_phase_transition_does_not_claim_verified_commit(self):
        e=self.stub(hit=1,phase=3,used=0);e.poll()
        self.assertEqual(e.emit.call_args.args[0]['kind'],'effect_command_uncommitted')
        e.n.execute.assert_not_called()

    def test_animation_gap_after_preparation_is_not_a_cancel(self):
        e=self.stub(hit=1,used=0);e.poll()
        self.assertIsNotNone(e.active)
        self.assertEqual([x.args[0]['kind'] for x in e.emit.call_args_list],['effect_operand_prepared'])
        e.n.capture.return_value=state(orders_used=1);e.last_poll=0;e.poll()
        self.assertIsNone(e.active)
        self.assertEqual(e.emit.call_args.args[0]['kind'],'effect_command_queued')

    def test_command_count_alone_cannot_claim_enhanced_command(self):
        e=self.stub(used=1);e.poll()
        self.assertEqual(e.emit.call_args.args[0]['kind'],'effect_command_uncommitted')
        self.assertIsNone(e.active);e.n.execute.assert_not_called()

    def test_pending_targets_need_bound_core_and_finished_strategy(self):
        e=self.stub();e.active=None;e.pending={a:dict(start_tick=100000) for a in TRAINING}
        e.n.bound={'core':0x200000}
        fields={0x400000:0x506660,0x53bb30:0x200000,0x400024:300,0x40002a:300,0x400030:199}
        e.n.number.side_effect=lambda a,*args:fields[a]
        e.poll();self.assertEqual(len(e.pending),3);e.emit.assert_not_called()
        e.n.capture.return_value=state(phase=3);e.last_poll=0;e.poll()
        self.assertFalse(e.pending)
        self.assertEqual([x.args[0]['actual'] for x in e.emit.call_args_list],[300,300,199])
        e.n.execute.assert_not_called()

    def test_target_match_in_another_core_is_rejected(self):
        e=self.stub();e.active=None;e.pending={'bow':dict(start_tick=100000)}
        e.n.bound={'core':0x200000};e.n.number.side_effect=lambda a,*args:0x506660 if a==0x400000 else 0x300000
        with self.assertRaises(ValueError):e.poll()
        self.assertIn('bow',e.pending);e.emit.assert_not_called();e.n.execute.assert_not_called()

    def test_read_error_keeps_patch_and_unknown_input_never_replays(self):
        e=self.stub();e.n.read.side_effect=OSError('unreadable')
        with self.assertRaises(OSError):e.poll()
        self.assertIsNotNone(e.active);e.restore.assert_not_called();e.n.execute.assert_not_called()

    def test_invalid_or_disabled_effect_never_allocates_or_inputs(self):
        e=self.stub();e.install=Mock()
        for enabled,write in ((False,True),(True,False),(False,False)):
            with self.assertRaises(ValueError):e.execute('alms',enabled,write,Mock())
        e.install.assert_not_called();e.n.execute.assert_not_called()
        with self.assertRaises(ValueError):trampoline(0x300000,0x300800,0x200000,0x100000,'other')

    def test_site_boundaries_and_original_calls(self):
        for action in (*TRAINING,'alms'):
            code,hooks=trampoline(0x300000,0x300800,0x200000,0x100000,action)
            site=next(iter(hooks));self.assertEqual(len(hooks[site]),len(SITES[site]))
            self.assertEqual(code[-5],0xe9)
            self.assertEqual(0x300000+len(code)+struct.unpack('<i',code[-4:])[0],0x4a39e7 if action=='bow' else site+len(SITES[site]))
            self.assertTrue(all(len(b)==len(SITES[a]) for a,b in hooks.items()))
            if action=='alms':
                at=len(code)-10;self.assertEqual(code[at],0xe8)
                self.assertEqual(0x300000+at+5+struct.unpack_from('<i',code,at+1)[0],0x446482)
            else:self.assertIn(SITES[site],code)

if __name__=='__main__':unittest.main()
