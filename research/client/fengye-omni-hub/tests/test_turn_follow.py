"""回合跟隨判定（120 秒要有玩家資訊、240 秒判掉隊）的單元測試。"""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]

from turn_follow import (TurnFollower, OK_SECONDS, LOST_SECONDS,
                         round_when, round_shift, sync_phrase)


class TurnFollowerTests(unittest.TestCase):
    def setUp(self):
        self.follower = TurnFollower()

    def test_idle_before_any_received_count(self):
        self.assertEqual(self.follower.state(0.0), 'idle')
        state, text = self.follower.describe(0.0)
        self.assertEqual(state, 'idle')
        self.assertIn('等待玩家資訊', text)

    def test_first_count_starts_the_clock(self):
        self.assertEqual(self.follower.observe(100.0, received=10, run='run-a'), 'start')
        self.assertEqual(self.follower.state(100.0), 'ok')
        self.assertEqual(self.follower.state(219.0), 'ok')

    def test_warning_between_120_and_240_seconds(self):
        self.follower.observe(0.0, received=10, run='run-a')
        self.assertEqual(self.follower.state(OK_SECONDS), 'warn')
        self.assertEqual(self.follower.state(LOST_SECONDS - 0.1), 'warn')
        state, text = self.follower.describe(121.0)
        self.assertEqual(state, 'warn')
        self.assertIn('240', text)

    def test_lost_at_240_and_stays_until_new_data(self):
        self.follower.observe(0.0, received=10, run='run-a')
        self.assertEqual(self.follower.state(LOST_SECONDS), 'lost')
        self.assertEqual(self.follower.state(600.0), 'lost')
        self.assertIn('判定掉隊', self.follower.describe(600.0)[1])
        self.assertEqual(self.follower.observe(601.0, received=11, run='run-a'), 'recovered')
        self.assertEqual(self.follower.state(601.0), 'ok')
        self.assertIn('已恢復', self.follower.describe(601.5)[1])

    def test_new_data_before_timeout_is_not_a_recovery(self):
        self.follower.observe(0.0, received=10, run='run-a')
        self.assertEqual(self.follower.observe(50.0, received=12, run='run-a'), 'data')
        self.assertEqual(self.follower.state(50.0), 'ok')
        self.assertNotIn('恢復', self.follower.describe(50.0)[1])

    def test_new_run_resets_the_window(self):
        self.follower.observe(0.0, received=10, run='run-a')
        self.assertEqual(self.follower.state(300.0), 'lost')
        self.assertEqual(self.follower.observe(300.0, received=3, run='run-b'), 'start')
        self.assertEqual(self.follower.state(300.0), 'ok')

    def test_missing_count_keeps_idle_and_tracks_connection(self):
        self.follower.observe(0.0, received=None, run='run-a', connected=False)
        state, text = self.follower.describe(0.0)
        self.assertEqual(state, 'idle')
        self.assertIn('等待風夜連線', text)

    def test_context_is_appended_to_the_sentence(self):
        self.follower.observe(0.0, received=10, run='run-a')
        self.assertIn('200年春', self.follower.describe(60.0, '200年春')[1])

    def test_zero_received_is_not_data_until_it_moves(self):
        self.assertEqual(self.follower.observe(0.0, received=0, run='run-a'), 'start')
        self.assertEqual(self.follower.state(10.0), 'idle')
        self.assertIn('還沒收到任何資料', self.follower.describe(10.0)[1])
        self.assertEqual(self.follower.observe(30.0, received=0, run='run-a'), None)
        self.assertEqual(self.follower.state(400.0), 'idle')
        self.assertEqual(self.follower.observe(401.0, received=2, run='run-a'), 'data')
        self.assertEqual(self.follower.state(401.0), 'ok')

    def test_thresholds_are_the_agreed_ones(self):
        self.assertEqual(OK_SECONDS, 120.0)
        self.assertEqual(LOST_SECONDS, 240.0)


class RoundPhraseTests(unittest.TestCase):
    def test_round_when_formats_year_and_season(self):
        self.assertEqual(round_when({'year': 200, 'season': 0}), '200年春')
        self.assertEqual(round_when({'season': 3}), '冬')
        self.assertEqual(round_when({}), '')
        self.assertEqual(round_when({'year': 200, 'season': 9}), '')
        self.assertEqual(round_when(None), '')

    def test_round_shift_compares_last_packet_round_with_now(self):
        self.assertEqual(round_shift('200年春', '200年春'), '收包 200年春（現在相同）')
        self.assertEqual(round_shift('200年春', '200年夏'), '收包 200年春 → 現在 200年夏')
        self.assertEqual(round_shift('', '200年春'), '現在 200年春')
        self.assertEqual(round_shift('200年春', ''), '收包 200年春')
        self.assertEqual(round_shift('', ''), '')

    def test_sync_phrase(self):
        self.assertEqual(sync_phrase({'ok': True}), '與玩家端同步')
        self.assertEqual(
            sync_phrase({'ok': False, 'lag_seasons': 1,
                         'reference': {'year': 200, 'season': 1}}),
            '玩家端已到 200年夏（風夜落後 1 季）')
        self.assertEqual(sync_phrase({'ok': None}), '')
        self.assertEqual(sync_phrase(None), '')


if __name__ == '__main__':
    unittest.main()
