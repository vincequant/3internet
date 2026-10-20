import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from player_text import (TECHNICAL, plain_error, room_summary, room_result,
                         operation_result, local_state, control_event,
                         force_choices, force_summary, lab_result)


class PlayerTextTests(unittest.TestCase):
    def readable(self, text):
        self.assertIsNone(TECHNICAL.search(text), text)

    def test_machine_errors_and_results_never_leak_into_system_copy(self):
        raw = 'Traceback: WinError 87; cmd9 rc=-1 {"stdout":"0x8af001"} /Users/vk/sgi-protocol-lab/p51.py'
        texts = [plain_error(raw), operation_result('查看狀態', {'status': 'error', 'error': raw}),
                 room_result({'op': 'join', 'status': 'error', 'error': raw}),
                 lab_result('查看風夜狀態', {'rc': 1, 'stderr': raw}),
                 control_event({'ev': 'control_error', 'reason': raw})]
        for text in texts:
            self.readable(text)

    def test_old_hide_success_is_never_shown_as_ready(self):
        state = {'fresh': False, 'connected': False, 'phase': 'stopped',
                 'ghost_withdrawn': True, 'd8': {'fast': True}}
        title, hint = room_summary(state, now=1000)
        self.assertNotIn('可以', title)
        self.assertNotIn('已藏好', title)
        self.assertIn('未連線', title)
        state.update(fresh=True, connected=True, observed_at=900)
        self.assertNotIn('可以', ' '.join(room_summary(state, now=1000)))

    def test_send_ack_is_not_treated_as_host_confirmation(self):
        state = {'fresh': True, 'observed_at': 999, 'connected': True,
                 'ghost_withdrawn': True, 'd8': {}}
        text = ' '.join(room_summary(state, now=1000))
        self.assertIn('等房主確認', text)
        self.assertNotIn('現在可以', text)
        state['d8']['fast'] = True
        self.assertIn('現在可以', ' '.join(room_summary(state, now=1000)))

    def test_successful_script_is_not_proof_of_game_start(self):
        text = lab_result('風夜進房準備', {'rc': 0, 'stdout': 'ARM_DONE D8=1 pid=123'})
        self.assertIn('已執行', text)
        self.assertNotIn('已藏好', text)
        self.assertNotIn('已開局', text)
        self.readable(text)

    def test_player_choices_show_names_and_factions_without_ids(self):
        payload = {'slot_forces': {'0': 2, '1': 8, '2': -1, '3': 7}, 'slot_now': 1}
        seats = {0: ('丁滿', '韓'), 1: ('風雲', '吳'), 2: ('電腦', '楚')}
        before = copy.deepcopy(payload)
        choices = force_choices(payload, seats)
        self.assertEqual(choices, {0: '丁滿・韓', 1: '風雲・吳'})
        text = force_summary(payload, seats)
        self.assertIn('目前對應玩家：風雲・吳', text)
        self.assertNotIn('2', text)
        self.assertNotIn('8', text)
        self.readable(text)
        self.assertEqual(payload, before)

    def test_missing_name_does_not_offer_anonymous_numeric_target(self):
        payload = {'slot_forces': {'0': 2}, 'slot_now': 0}
        self.assertEqual(force_choices(payload, {}), {})
        self.assertIn('尚未確認', force_summary(payload, {}))

    def test_failed_or_unconfirmed_write_does_not_claim_switch_success(self):
        payload = {'slot_forces': {'0': 2}, 'slot_now': 0, 'action': 'written', 'requested': 1, 'now': 0}
        text = force_summary(payload, {0: ('丁滿', '韓')})
        self.assertNotIn('已切換為', text)
        self.assertIn('結果還沒確認', text)

    def test_unknown_operation_stays_unknown_and_keeps_raw_source(self):
        event = {'ev': 'mystery_internal_005', 'rc': 0, 'reason': None}
        before = dict(event)
        text = control_event(event)
        self.assertIn('還無法確認', text)
        self.readable(text)
        self.assertEqual(event, before)

    def test_character_encoding_error_is_described_in_player_terms(self):
        text = plain_error('GBK unsupported UnicodeEncodeError')
        self.assertIn('遊戲無法顯示的字', text)
        self.readable(text)

    def test_local_state_does_not_expose_process_numbers_or_internal_detail(self):
        title, hint = local_state({'state': 'holding', 'helper_pid': 1266, 'sanpk_pid': 0,
                                  'detail': 'prefix-sikarugir10 helper=1266', 'rooms': []})
        self.assertIn('已連上伺服器', title)
        self.assertNotIn('遊戲已開啟', title)
        self.readable(title + hint)


if __name__ == '__main__':
    unittest.main()
