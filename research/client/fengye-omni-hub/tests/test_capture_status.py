from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengye_capture_status import CaptureStatus


def payload(now, game='current-game', sample='frame-1'):
    return {'ok': True, 'source_prefix': 'prefix-fengye-shadow', 'game_key': game,
            'captured_at': now.isoformat(),
            'state': {'readonly': True, 'snapshot_id': sample, 'capture_end': now.isoformat(),
                      'entities': {}}}


class CaptureStatusTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.status = CaptureStatus()

    def test_no_sample_never_claims_live_or_recording(self):
        self.assertIn('等待開局資料', self.status.text(now=self.now))
        self.assertNotIn('實時採集', self.status.text(now=self.now))

    def test_fresh_sample_counts_once_and_preserves_raw(self):
        data = payload(self.now)
        original = deepcopy(data)
        self.assertTrue(self.status.observe(data))
        self.assertFalse(self.status.observe(data))
        self.assertEqual(self.status.frames, 1)
        self.assertIn('實時採集', self.status.text(now=self.now))
        self.assertIn('本次讀取 1 幀', self.status.text(now=self.now))
        self.assertNotIn('回放記錄中', self.status.text(now=self.now))
        self.assertEqual(data, original)

    def test_outage_and_age_show_retry_then_fresh_sample_recovers(self):
        self.status.observe(payload(self.now))
        self.status.failed = True
        self.assertIn('中斷', self.status.text(now=self.now))
        later = self.now+timedelta(seconds=20)
        self.assertTrue(self.status.observe(payload(later, sample='frame-2')))
        self.assertIn('實時採集', self.status.text(now=later))
        self.assertEqual(self.status.frames, 2)
        self.assertIn('已過期', self.status.text(now=later+timedelta(seconds=16)))

    def test_new_game_resets_count_and_rejects_older_same_game_frame(self):
        self.status.observe(payload(self.now))
        self.status.observe(payload(self.now+timedelta(seconds=3), sample='frame-2'))
        self.status.observe(payload(self.now+timedelta(seconds=4), game='new-game'))
        self.assertEqual(self.status.frames, 1)
        self.assertFalse(self.status.observe(payload(self.now, game='new-game')))
        self.assertEqual(self.status.frames, 1)

    def test_foreign_or_unknown_samples_never_claim_live(self):
        data = payload(self.now)
        data['source_prefix'] = 'prefix-dingman-local'
        self.assertFalse(self.status.observe(data))
        data['source_prefix'] = 'prefix-fengye-shadow'
        data['captured_at'] = data['state']['capture_end'] = None
        self.assertFalse(self.status.observe(data))
        self.assertEqual(self.status.frames, 0)
        self.assertIn('樣本回放', self.status.text(replay=True))


if __name__ == '__main__':
    unittest.main()
