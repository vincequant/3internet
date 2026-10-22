"""One switch gates all three features, including failure and queued keys."""
import unittest
from unittest.mock import Mock
from quick_automation import QuickAutomation


class AutomationTests(unittest.TestCase):
    def controller(self):
        timer=Mock(enabled=False);effects=Mock(enabled=False,hooks=None);pan=Mock();emit=Mock()
        timer.set_enabled.side_effect=lambda wanted,allowed:setattr(timer,'enabled',wanted and allowed)
        effects.set_enabled.side_effect=lambda wanted,allowed:setattr(effects,'enabled',wanted and allowed)
        return QuickAutomation(timer,effects,pan,emit)

    def test_inert_until_combined_switch_and_authorization_then_stop_all(self):
        q=self.controller();q.poll()
        q.timer.poll.assert_not_called();q.effects.poll.assert_not_called();q.pan.update.assert_called_with(False)
        for wanted,allowed in ((False,True),(True,False),(1,True)):
            q.set_enabled(wanted,allowed);self.assertFalse(q.enabled)
        q.set_enabled(True,True);q.poll()
        self.assertTrue(q.enabled);q.timer.poll.assert_called_once();q.effects.poll.assert_called_once()
        q.pan.update.assert_called_with(True)
        q.set_enabled(False,True)
        self.assertFalse(q.timer.enabled);self.assertFalse(q.effects.enabled)
        q.pan.update.assert_called_with(False)

    def test_one_failure_disables_other_features_and_no_timer_retry(self):
        q=self.controller();q.set_enabled(True,True)
        q.timer.poll.side_effect=lambda:setattr(q.timer,'enabled',False)
        q.poll();q.poll()
        self.assertFalse(q.enabled);q.effects.poll.assert_not_called()
        self.assertEqual(q.timer.poll.call_count,1)
        q.pan.update.assert_called_with(False)

    def test_hook_failure_stops_timer_and_releases_camera_keys(self):
        q=self.controller();q.set_enabled(True,True)
        q.effects.poll.side_effect=ValueError('入口改变')
        q.poll();self.assertFalse(q.enabled);self.assertFalse(q.timer.enabled)
        q.pan.update.assert_called_with(False)
        self.assertIn('入口改变',q.emit.call_args.args[0]['note'])

    def test_enable_failure_never_leaves_partial_features_running(self):
        q=self.controller()
        q.timer.set_enabled.side_effect=lambda wanted,allowed:setattr(q.timer,'enabled',False)
        q.set_enabled(True,True)
        self.assertFalse(q.enabled);self.assertFalse(q.effects.enabled)
        q.pan.update.assert_called_with(False)

    def test_restore_failure_is_visible_and_does_not_reactivate_camera(self):
        q=self.controller();q.set_enabled(True,True)
        q.effects.set_enabled.side_effect=OSError('restore failed');q.effects.hooks={123:b'code'}
        q.set_enabled(False,True);self.assertFalse(q.enabled)
        q.pan.update.assert_called_with(False)
        events=[c.args[0] for c in q.emit.call_args_list]
        self.assertTrue(any(e.get('hooks_may_remain') for e in events))
        self.assertIn('restore failed',events[-1]['note'])


if __name__=='__main__':unittest.main()
