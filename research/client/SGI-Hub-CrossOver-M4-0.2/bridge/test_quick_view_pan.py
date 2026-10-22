import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from quick_view_pan import PAN_KEYS, HOTKEY_IDS, ViewPan, pan_plan


def state(**changes):
    row = dict(main_hwnd=100, hwnd=101, view=0x100000, phase=4, ending=0,
               modal=0, native_dialogs=False, widget_count=0, map_mode=0,
               map_widget=0, strategy_dialog=0, recruit_dialog=0,
               selected_unit=123, selected_order=0, orders_used=3, viewport=[100, 100])
    row.update(changes); return row


class PanTests(unittest.TestCase):
    def test_scroll_messages_only_and_selected_unit_never_becomes_move_order(self):
        for key, expected in PAN_KEYS.items():
            plan = pan_plan(state(), key, 100, 101)
            self.assertEqual((plan['message'], plan['wparam']), expected)
            self.assertIn(plan['message'], (0x114, 0x115))
            self.assertEqual(plan['lparam'], 0)
        with self.assertRaises(ValueError): pan_plan(state(), 'e', 100, 101)

    def test_input_chat_dialog_menu_and_background_are_rejected(self):
        for change in ({'modal':1}, {'widget_count':1}, {'native_dialogs':True},
                       {'map_widget':12}, {'map_mode':1}, {'strategy_dialog':12},
                       {'recruit_dialog':12}, {'ending':1}, {'phase':0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                pan_plan(state(**change), 'w', 100, 101)
        for fg, focus, flags in [(999,101,0), (100,102,0), (100,101,1)]:
            with self.assertRaises(ValueError): pan_plan(state(),'w',fg,focus,flags)

    def helper(self):
        ui = Mock(); ui.GetForegroundWindow.return_value=100
        def thread(hwnd, pid): pid._obj.value=9; return 1
        def gui(thread, info): info._obj.hwndFocus=101; info._obj.flags=0; return True
        ui.GetWindowThreadProcessId.side_effect=thread
        ui.GetGUIThreadInfo.side_effect=gui
        ui.GetAsyncKeyState.return_value=0
        ui.RegisterHotKey.return_value=True; ui.PostMessageW.return_value=True
        native=SimpleNamespace(u=ui,bound={'pid':9},owner=Mock(return_value=9),
                               capture=Mock(side_effect=lambda:state()),number=Mock(return_value=0))
        emit=Mock(); return ViewPan(native,emit),native,emit

    def test_foreground_registration_repeat_and_background_release(self):
        pan,n,emit=self.helper(); pan.update(True)
        self.assertEqual(pan.registered,set(HOTKEY_IDS))
        for call in n.u.RegisterHotKey.call_args_list:
            self.assertEqual(call.args[2],0)  # normal keyboard repeat, no modifier
        pan.update(True);self.assertEqual(n.u.RegisterHotKey.call_count,4)
        n.owner.return_value=10;pan.update(True)
        self.assertFalse(pan.registered);self.assertEqual(n.u.UnregisterHotKey.call_count,4)
        n.u.PostMessageW.assert_not_called()

    def test_new_dialog_or_edit_focus_releases_keys_without_cached_delay(self):
        pan,n,_=self.helper();pan.update(True)
        n.number.return_value=1;pan.update(True)
        self.assertFalse(pan.registered)
        n.number.return_value=0;pan.update(True)
        self.assertEqual(len(pan.registered),4)
        def edit(thread, info):info._obj.hwndFocus=102;return True
        n.u.GetGUIThreadInfo.side_effect=edit;pan.update(True)
        self.assertFalse(pan.registered)

    def test_modifier_and_registration_conflict_dont_capture_letters(self):
        pan,n,_=self.helper();n.u.GetAsyncKeyState.return_value=0x8000
        pan.update(True);n.u.RegisterHotKey.assert_not_called()
        n.u.GetAsyncKeyState.return_value=0;n.u.RegisterHotKey.return_value=False
        pan.update(True);self.assertFalse(pan.registered)

    def test_execute_rechecks_focus_and_only_posts_camera_event(self):
        pan,n,emit=self.helper();pan.execute('d')
        n.u.PostMessageW.assert_called_once_with(101,0x114,1,0)
        self.assertTrue(all(c.args[0]['game_order'] is False for c in emit.call_args_list))
        def edit(thread,info):info._obj.hwndFocus=102;return True
        n.u.GetGUIThreadInfo.side_effect=edit
        with self.assertRaises(ValueError):pan.execute('w')
        self.assertEqual(n.u.PostMessageW.call_count,1)
