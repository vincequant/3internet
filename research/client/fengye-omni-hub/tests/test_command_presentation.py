"""Names and effects stay readable without exposing transport diagnostics."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_presentation import actor_text, action_text, progress_text, job_detail

SNAPSHOT = {'forces': [{'force_id': 3, 'name': '齊'}],
            'player_slots': [{'force_id': 3, 'nickname': '風雲'}],
            'cities': [{'city_id': 12, 'name': '臨淄'}]}


class PresentationTests(unittest.TestCase):
    def test_actor_and_city_resolve_actual_names_not_ids(self):
        for label in ('3', '3・4', '—・3', '風雲・3', None):
            job = {'preset': 'build', 'actor': 3, 'actor_label': label,
                   'params': {'city': 12, 'x': 78, 'y': 51, 'build_type': 6}}
            self.assertEqual(actor_text(job, SNAPSHOT), '風雲・齊')
            self.assertEqual(action_text(job, SNAPSHOT), '陷阱 · 臨淄 (78,51)')

    def test_unknown_names_never_fall_back_to_numeric_ids(self):
        job = {'actor': 3, 'actor_label': '3', 'preset': 'build',
               'city_name': '城池', 'params': {'city': 12}}
        self.assertEqual(actor_text(job), '未知玩家・未知勢力')
        self.assertIn('未知城池', action_text(job))
        self.assertNotIn('12', action_text(job))

    def test_frozen_player_names_survive_later_slot_change(self):
        self.assertEqual(actor_text({'actor_label': '風雲・齊'}, {}), '風雲・齊')

    def test_training_real_before_after_and_gold(self):
        job = {'preset': 'train', 'status': 'completed', 'params': {'troop': 0},
               'effect': {'confirmed': True, 'before': {'training_raw': 120},
                          'after': {'training_raw': 150},
                          'evidence': {'gold_change': {'before': 37022, 'after': 36022}}}}
        self.assertIn('步兵訓練度 120 → 150', progress_text(job))
        self.assertIn('金 37022 → 36022', progress_text(job))

    def test_build_confirmation_names_city_and_does_not_expose_numeric_actor(self):
        job = {'actor': 3, 'preset': 'build', 'status': 'completed',
               'params': {'build_type': 6, 'city': 12, 'x': 78, 'y': 51},
               'effect': {'confirmed': True, 'summary': '勢力 3 raw'},
               'events': [{'at': 1, 'status': 'arming', 'note': 'rc=1 core=0x555'}],
               'error': 'thread_id=12'}
        detail = job_detail(job, SNAPSHOT)
        self.assertIn('風雲・齊', detail)
        self.assertIn('臨淄 (78,51) 已出現新的陷阱', detail)
        for raw in ('rc=', 'core=', 'thread_id', '勢力 3'):
            self.assertNotIn(raw, detail)

    def test_waiting_text_does_not_claim_a_command_already_executed(self):
        text = progress_text({'status': 'waiting_phase_exit'})
        self.assertIn('等下一個內政回合', text)
        self.assertNotIn('已處理過', text)


if __name__ == '__main__':
    unittest.main()
