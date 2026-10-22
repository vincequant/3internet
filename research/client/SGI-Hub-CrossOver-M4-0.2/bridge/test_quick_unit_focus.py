import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quick_unit_focus import UnitFocus, focus_plan, require_focus_state
from test_quick_view_pan import state as pan_state


def state(**changes):
    return pan_state(**dict(dict(mode=2, phase=3, allowance=1, selected_unit=0x200000), **changes))


def context():
    return dict(unit=dict(pointer=0x200000, id=0, owner=16, xy=[56,19]), local_force=16,
                order_xy=[56,19], dimensions=[101,202,96,48], client_size=[1392,850],
                scroll_extent=[9744,4872], roots_hex='roots', order_hex='order')


class FocusTests(unittest.TestCase):
    def test_centers_current_unit_using_only_two_native_camera_messages(self):
        p = focus_plan(state(), context())
        self.assertEqual(p['world_point'], [5472,468])
        self.assertEqual(p['target_origin'], [4776,43])
        self.assertEqual([(r['message'],r['wparam'] & 0xffff, r['wparam'] >> 16,r['lparam'])
                          for r in p['messages']], [(0x114,5,4776,0),(0x115,5,43,0)])
        self.assertFalse(p['game_order'])

    def test_edges_and_resized_view_clamp_to_actual_scroll_extent(self):
        c=context();c['unit']['xy']=[0,0];c['order_xy']=[0,0]
        self.assertEqual(focus_plan(state(),c)['target_origin'],[0,0])
        c['unit']['xy']=[100,201];c['order_xy']=[100,201]
        self.assertEqual(focus_plan(state(),c)['target_origin'],[8352,4022])
        c['client_size']=[10000,6000]
        self.assertEqual(focus_plan(state(),c)['target_origin'],[0,0])

    def test_wrong_phase_dialog_unknown_flags_or_missing_selection_block_before_input(self):
        for changes in ({'modal':1},{'widget_count':1},{'native_dialogs':True},{'phase':1},
                        {'allowance':0},{'ending':1},{'map_mode':1},{'map_widget':1},
                        {'strategy_dialog':1},{'recruit_dialog':1},{'selected_unit':0},
                        {'selected_order':-1},{'map_mode':None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                require_focus_state(state(**changes))

    def test_enemy_changed_order_or_unverified_geometry_rejected(self):
        for change in ('enemy','pointer','order','dimensions','extent','coordinate'):
            c=context()
            if change=='enemy':c['unit']['owner']=17
            elif change=='pointer':c['unit']['pointer']=0x300000
            elif change=='order':c['order_xy']=[57,19]
            elif change=='dimensions':c['dimensions'][2]=97
            elif change=='extent':c['scroll_extent'][0]=65536
            else:c['unit']['xy']=[101,19]
            with self.subTest(change=change), self.assertRaises(ValueError):focus_plan(state(),c)

    def helper(self):
        u=Mock();u.GetForegroundWindow.return_value=100
        def thread(hwnd,pid):pid._obj.value=9;return 1
        def gui(thread,info):info._obj.hwndFocus=101;info._obj.flags=0;return True
        u.GetWindowThreadProcessId.side_effect=thread;u.GetGUIThreadInfo.side_effect=gui
        u.PostMessageW.return_value=True
        n=SimpleNamespace(u=u,k=Mock(),bound={'pid':9},owner=Mock(return_value=9),
                          capture=Mock(side_effect=lambda:state()),read=Mock(return_value=struct.pack('<ii',4776,43)))
        emit=Mock();return UnitFocus(n,emit),n,emit

    @patch('quick_unit_focus.time.sleep')
    @patch('quick_unit_focus.capture_context',side_effect=lambda *args:context())
    def test_panel_button_and_hotkey_have_observed_camera_receipt_without_order_or_write(self,ctx,sleep):
        f,n,emit=self.helper();r=f.execute(True)
        self.assertEqual(r['status'],'unit_focused');self.assertTrue(r['selection_order_unchanged'])
        self.assertEqual(n.u.PostMessageW.call_count,2)
        self.assertEqual([r.args[1] for r in n.u.PostMessageW.call_args_list],[0x114,0x115])
        n.k.WriteProcessMemory.assert_not_called()
        n.u.PostMessageW.reset_mock();n.u.SetForegroundWindow.reset_mock()
        self.assertEqual(f.execute(True,hotkey=True)['status'],'unit_focused')
        n.u.SetForegroundWindow.assert_not_called()
        self.assertTrue(all(c.args[0]['game_order'] is False for c in emit.call_args_list))

    @patch('quick_unit_focus.capture_context',side_effect=lambda *args:context())
    def test_modal_stale_binding_background_and_chat_prevent_any_camera_message(self,ctx):
        for case in ('modal','stale','background','chat','disabled'):
            f,n,_=self.helper()
            if case=='modal':n.capture.side_effect=lambda:state(modal=1)
            elif case=='stale':n.capture.side_effect=ValueError('游戏实例已改变')
            elif case=='background':n.u.GetForegroundWindow.return_value=999
            elif case=='chat':
                def edit(thread,info):info._obj.hwndFocus=102;return True
                n.u.GetGUIThreadInfo.side_effect=edit
            with self.subTest(case=case),self.assertRaises(ValueError):f.execute(case!='disabled',hotkey=True)
            n.u.PostMessageW.assert_not_called()

    @patch('quick_unit_focus.time.sleep')
    @patch('quick_unit_focus.capture_context',side_effect=lambda *args:context())
    def test_explicit_panel_click_can_recenter_owned_camera_while_mac_panel_has_focus(self,ctx,sleep):
        f,n,_=self.helper();n.u.GetForegroundWindow.return_value=999
        n.u.SetForegroundWindow.return_value=False
        self.assertEqual(f.execute(True)['status'],'unit_focused')
        self.assertEqual(n.u.PostMessageW.call_count,2)
        self.assertTrue(all(c.args[1] in (0x114,0x115) for c in n.u.PostMessageW.call_args_list))

    @patch('quick_unit_focus.time.sleep')
    def test_selection_changes_between_axes_stops_and_does_not_retry(self,sleep):
        f,n,_=self.helper();c=context();changed=context();changed['unit']['id']=2
        with patch('quick_unit_focus.capture_context',side_effect=[c,c,changed]):r=f.execute(True)
        self.assertEqual(r['status'],'unknown');self.assertEqual(n.u.PostMessageW.call_count,1)

    @patch('quick_unit_focus.time.sleep')
    @patch('quick_unit_focus.capture_context',side_effect=lambda *args:context())
    def test_failed_post_and_unknown_readback_never_repeat_input(self,ctx,sleep):
        f,n,_=self.helper();n.u.PostMessageW.return_value=False
        self.assertEqual(f.execute(True)['status'],'unknown');self.assertEqual(n.u.PostMessageW.call_count,1)
        f,n,_=self.helper();n.read.return_value=struct.pack('<ii',64,3280)
        self.assertEqual(f.execute(True)['status'],'unknown');self.assertEqual(n.u.PostMessageW.call_count,2)
