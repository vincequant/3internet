import sys
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'bridge')]
from quick_plain_training import PlainTraining
from quick_control_model import alms_operand, training_operand
from quick_effects import TOKENS


class PlainTrainingControls(unittest.TestCase):
    def test_one_plain_300_operand_without_target_hooks(self):
        p=PlainTraining(Mock(),Mock())
        for politics in (300,1000):
            p.politics=politics
            for action in TOKENS:
                code,hooks=p.input_trampoline(0x6000000,0x6100000,0x6200000,0x6300000,action)
                self.assertEqual(code.count(b'\xb8'+struct.pack('<i',politics)),1)
                self.assertNotIn(struct.pack('<i',TOKENS[action]),code)
                self.assertEqual(set(hooks),{0x4a3c88})
        self.assertFalse(p.uses_training_targets)
        p.ensure_rules({});self.assertIsNone(p.rule_hooks)

    def test_invalid_or_shortcut_requests_do_not_patch(self):
        p=PlainTraining(Mock(),Mock());p.install=Mock()
        for action,value in [('alms',30),('bow',True),('bow',-1),('bow',0),('bow',766)]:
            with self.assertRaises(ValueError):p.arm(action,value)
        p.install.assert_not_called()
        with self.assertRaises(ValueError):p.execute('bow',False,True,Mock())
        p.install.assert_not_called()

    def test_existing_target_rule_mixing_rejected(self):
        p=PlainTraining(Mock(),Mock());p.rule_hooks={1:b'hook'}
        with self.assertRaises(ValueError):p.ensure_rules({})

    def test_panel_training_uses_officer_politics_times_three(self):
        native=Mock();native.last_input=0;native.execute.return_value={'status':'dialog_observed'}
        p=PlainTraining(native,Mock());p.arm=Mock();p.restore=Mock()
        row=dict(name='荀彧', politics=120, operand=360)
        with patch('quick_plain_training.require_menu'), patch('quick_plain_training.current_training_operand', return_value=row):
            for action in TOKENS:
                result=p.execute(action,True,True,Mock())
                p.arm.assert_called_with(action,360)
                self.assertEqual(result['politics_operand'],360)
                self.assertEqual(result['trainer'],'荀彧')
                self.assertFalse(result['target_level_rules'])
            native.execute.side_effect=ValueError('input failed')
            with self.assertRaises(ValueError):p.execute('bow',True,True,Mock())
            p.restore.assert_called_once()
            self.assertFalse(native.effects_pending)

    def test_alms_operand_adds_thirty_without_training_rules(self):
        p=PlainTraining(Mock(),Mock())
        code,hooks=p.input_trampoline(0x6000000,0x6100000,0x6200000,0x6300000,'alms')
        self.assertEqual(set(hooks),{0x4a482c})
        self.assertIn(bytes.fromhex('83 c2 05 8d 14 52 83 ea 05'), code)
        self.assertNotIn(b'\xba'+struct.pack('<I',25), code)
        self.assertNotIn(b'\xba'+struct.pack('<I',195), code)
        for remainder in range(5):
            self.assertEqual(alms_operand(remainder) + 5, (remainder + 5) * 3)

    def test_training_operand_is_our_best_politics_times_three(self):
        payload={'state':{
            'player_force_id':1,
            'player_identity':{'status':'confirmed','force_id':1},
            'entities':{'generals':[
                {'owner_raw':1,'name':'荀彧','attributes':{'pol':120}},
                {'owner_raw':1,'name':'典韦','attributes':{'pol':40}},
                {'owner_raw':2,'name':'周瑜','attributes':{'pol':200}},
            ]},
        }}
        self.assertEqual(training_operand(payload), dict(politics=120, name='荀彧', operand=360))
        with self.assertRaises(ValueError):
            training_operand({'state':{'entities':{'generals':[]}}})
        import inspect
        lines = [line.strip() for line in inspect.getsource(training_operand).splitlines()]
        self.assertFalse(any(line.startswith(('from force_compare', 'import force_compare')) for line in lines))


if __name__=='__main__':unittest.main()
