"""Civil/military timer behavior and phase-change write refusal, without Tk."""
import ctypes
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from quick_control_model import extension_plan,timer_value
from quick_control_native import Native


def state(**changes):
    result=dict(document=0x100000,view=0x200000,hwnd=111,phase=3,mode=2,
                time_setting=2,unit_count=9,start_tick=100000,tick=110000,
                allowance=1,ending=0,modal=0,native_dialogs=False,
                orders_used=3,selected_unit=0x300000,selected_order=4)
    result.update(changes)
    return result


class Kernel:
    def __init__(self):self.writes=[];self.closed=[]
    def OpenProcess(self,*args):return 123
    def CloseHandle(self,handle):self.closed.append(handle)
    def WriteProcessMemory(self,handle,address,data,size,got):
        self.writes.append((address,ctypes.string_at(data,size)))
        got._obj.value=size
        return True


class TimerTests(unittest.TestCase):
    def test_all_military_phases_add_exactly_ten_seconds_with_selection_and_used_orders(self):
        for phase in (3,4,5):
            for setting in (0,1,2):
                for units in (0,9):
                    for start,tick in ((100000,110000),(0xfffffff0,0x1ff0)):
                        with self.subTest(phase=phase,setting=setting,units=units,start=start):
                            before=state(phase=phase,time_setting=setting,unit_count=units,start_tick=start,tick=tick)
                            plan=extension_plan(before,True,True)
                            after=dict(before,start_tick=plan['after'])
                            self.assertEqual(timer_value(after)-timer_value(before),10000)
                            second=extension_plan(after,True,True)
                            self.assertEqual(timer_value(dict(after,start_tick=second['after']))-timer_value(before),20000)
                            self.assertEqual(plan['address'],before['document']+0x6c)

    def test_inactive_unlimited_modal_expiring_or_unknown_refused(self):
        cases=[dict(phase=2),dict(phase=0),dict(phase=6),dict(mode=1),dict(mode=3),
               dict(allowance=0),dict(ending=1),dict(modal=1),dict(native_dialogs=True),
               dict(time_setting=3),dict(time_setting=99),dict(unit_count=-1),
               dict(tick=188001),dict(tick=191000)]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                extension_plan(state(**changes),True,True)

    def native(self,samples):
        n=object.__new__(Native);n.k=Kernel();n.bound={'pid':10}
        n.check_identity=Mock();n.capture=Mock(side_effect=samples)
        return n

    def test_native_each_military_phase_writes_once_and_reads_back(self):
        for phase in (3,4,5):
            before=state(phase=phase)
            n=self.native([before,dict(before,tick=110100),dict(before,start_tick=110000,tick=110200)])
            events=[];r=n.extend(before,True,True,events.append)
            self.assertEqual(r['status'],'timer_field_verified')
            self.assertIn('军事回合已加 10 秒',r['note'])
            self.assertEqual(n.k.writes,[(before['document']+0x6c,struct.pack('<I',110000))])
            self.assertEqual(n.k.closed,[123])
            self.assertEqual([e['kind'] for e in events],['timer_write_intent','timer_write_receipt'])
            self.assertFalse(r['game_timer_expiry_verified'])

    def test_phase_or_timer_change_before_intent_never_writes(self):
        before=state()
        for changes in (dict(phase=4),dict(start_tick=100001),dict(time_setting=1),
                        dict(unit_count=8),dict(document=0x110000),dict(view=0x210000)):
            with self.subTest(changes=changes):
                n=self.native([dict(before,**changes)]);events=[]
                with self.assertRaises(ValueError):n.extend(before,True,True,events.append)
                self.assertEqual(n.k.writes,[]);self.assertEqual(events,[])
                self.assertEqual(n.k.closed,[123])

    def test_phase_changes_during_intent_attribution_never_write_or_retry(self):
        before=state()
        for changes in (dict(phase=4),dict(mode=3),dict(allowance=0),dict(start_tick=100001),
                        dict(time_setting=1),dict(unit_count=8),dict(modal=1),dict(tick=188001)):
            with self.subTest(changes=changes):
                n=self.native([before,dict(before,**changes)]);events=[]
                with self.assertRaises(ValueError):n.extend(before,True,True,events.append)
                self.assertEqual(n.k.writes,[])
                self.assertEqual([e['kind'] for e in events],['timer_write_intent'])
                self.assertEqual(n.k.closed,[123])

    def test_postwrite_phase_change_is_unknown_with_one_receipt_no_retry(self):
        before=state()
        n=self.native([before,before,dict(before,start_tick=110000,phase=4)])
        events=[];r=n.extend(before,True,True,events.append)
        self.assertEqual(r['status'],'unknown')
        self.assertEqual(len(n.k.writes),1)
        self.assertEqual([e['kind'] for e in events],['timer_write_intent','timer_write_receipt'])

    def test_changing_selected_unit_does_not_change_timer_basis(self):
        before=state()
        changed=dict(before,selected_unit=0x310000,selected_order=5)
        n=self.native([changed,changed,dict(changed,start_tick=110000)])
        self.assertEqual(n.extend(before,True,True,lambda e:None)['status'],'timer_field_verified')


if __name__=='__main__':unittest.main()
