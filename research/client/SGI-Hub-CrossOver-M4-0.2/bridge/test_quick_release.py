"""Retired multiplayer modifiers cannot enter any public execution path."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from quick_control import Panel
from quick_control_model import LABELS, KEYS, RETIRED_ACTIONS, require_available_action, validate_politics_request
from quick_control_native import Native, dispatch_request


class ReleaseControls(unittest.TestCase):
    def test_stale_ui_or_helper_requests_cannot_read_patch_or_input(self):
        native = Mock(); effects = Mock(); effects.active = None; emit = Mock()
        for action in RETIRED_ACTIONS:
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, '已下架'):
                    dispatch_request(native, effects, {'action': action}, True, True, emit)
                native.assert_not_called(); self.assertEqual(native.mock_calls, [])
                self.assertEqual(effects.mock_calls, []); emit.assert_not_called()
                direct = object.__new__(Native)
                with self.assertRaisesRegex(ValueError, '已下架'):
                    direct.execute(action, True, True, emit)
                panel = object.__new__(Panel); panel.note = Mock(); panel.write = Mock()
                panel.send(action)
                panel.write.assert_not_called()

    def test_retired_hotkeys_absent_and_requested_timer_retained(self):
        self.assertEqual(set(LABELS), {'extend', 'focus_unit', 'alms','infantry','cavalry','bow'})
        self.assertEqual(KEYS, {'extend': 'F6', 'focus_unit':'F7', 'alms': 'F11',
                               'infantry':'F8','cavalry':'F9','bow':'F10'})
        self.assertEqual(RETIRED_ACTIONS, {'recruit_target','recruit_politics'})
        for action in (*LABELS, 'inspect'):
            require_available_action(action)
        with self.assertRaises(ValueError): require_available_action('unknown')

    def test_alms_uses_effects_and_regular_recruit_has_no_guarantee(self):
        native = Mock(); effects = Mock(); effects.active = None; emit = Mock()
        dispatch_request(native, effects, {'action': 'alms'}, True, True, emit)
        effects.execute.assert_called_once_with('alms', True, True, emit, False)
        native.execute.assert_not_called()
        effects.reset_mock()
        dispatch_request(native, effects, {'action': 'recruit'}, True, True, emit)
        native.execute.assert_called_once_with('recruit', True, True, emit, False)
        effects.execute.assert_not_called()

    def test_all_three_training_actions_route_to_plain_effects(self):
        native=Mock();effects=Mock();effects.active=None;emit=Mock()
        for action in ('infantry','cavalry','bow'):
            effects.reset_mock()
            dispatch_request(native,effects,{'action':action},True,True,emit)
            effects.execute.assert_called_once_with(action,True,True,emit,False)
        native.execute.assert_not_called()

    def test_inflight_alms_blocks_other_input_but_allows_inspection(self):
        native = Mock(); effects = Mock(); effects.active = {'action': 'alms'}; emit = Mock()
        with self.assertRaisesRegex(ValueError, '施舍确认'):
            dispatch_request(native, effects, {'action': 'recruit'}, True, True, emit)
        native.execute.assert_not_called()
        dispatch_request(native, effects, {'action': 'inspect'}, True, True, emit)
        native.execute.assert_called_once_with('inspect', True, True, emit, False)

    def test_all_four_plain_choices_require_fresh_preview(self):
        import time
        from test_quick_control import Controls,state
        from quick_control_model import POLICIES
        panel=Controls().panel_stub();panel.ready=True;panel.target_pending=False
        panel.current_state=state();panel.preview_at=time.monotonic()
        panel.previews={k:{'id':1} for k in POLICIES}
        panel.policy_hint=Mock();panel.buttons={};panel.refresh_button=Mock();panel.connect_button=Mock()
        Panel.update_buttons(panel)
        for button in panel.policy_buttons.values():button.configure.assert_called_with(state='normal')
        panel.preview_at-=11;Panel.update_buttons(panel)
        for button in panel.policy_buttons.values():button.configure.assert_called_with(state='disabled')

    def test_politics_endpoint_cannot_reintroduce_skill_recruitment(self):
        native=Mock();effects=Mock();effects.active=None;recruiter=Mock()
        for policy in ('ride_ambush','bow_ambush','ride_charge_ambush',None):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, '已下架'):
                dispatch_request(native,effects,{'action':'recruit_politics','policy':policy},True,True,Mock(),recruiter,True)
        self.assertEqual(native.mock_calls,[]);self.assertEqual(recruiter.mock_calls,[])

    def test_politics_request_rechecks_maximum_identity_and_pending(self):
        from test_quick_control import Controls
        from quick_control_model import binding,select_candidate
        payload,_=Controls().policy_payload();bound=binding(payload)
        row=select_candidate(payload,bound,'politics')
        request={'policy':'politics','general_id':row['id'],'city_id':row['city_id'],'expected_attributes':row['attributes']}
        self.assertEqual(validate_politics_request(payload,bound,request)['id'],row['id'])
        for bad in (dict(request,policy='ride_ambush'),dict(request,general_id=999),
                    dict(request,expected_attributes={}),dict(request,city_id=99)):
            with self.assertRaises(ValueError):validate_politics_request(payload,bound,bad)
        with self.assertRaises(ValueError):validate_politics_request(payload,dict(bound,pid=99),request)
        with self.assertRaises(ValueError):validate_politics_request(payload,bound,request,{row['id']})


if __name__ == '__main__': unittest.main()
