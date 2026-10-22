import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'bridge'))

from sgi_room_monitor.events import data_events, diff_events, format_brief, format_summary, index_rooms, mark_sent, should_emit
from sgi_room_monitor.identity import reused_id
from sgi_room_monitor.states import CACHE, LIVE
from sgi_room_monitor.store import empty_snapshot, keep_last_good


def room(name='甲', host='张', current=3, maximum=8, ident='10'):
    return {'id': ident, 'name': f'{name}[{host}]', 'current': current, 'maximum': maximum}


class EventReplayTests(unittest.TestCase):
    def test_fullwidth_and_numeric_name(self):
        from sgi_room_monitor.identity import occupancy, room_name
        from room_list_model import parse_list_count
        self.assertEqual(parse_list_count('1/2练习 甲[张] ３／８'), (3, 8))
        self.assertEqual(room_name({'name': '1/2练习[小白白]'}), '1/2练习')

    def test_appear_change_threshold_missing(self):
        first = index_rooms([room(current=3)])
        second = index_rooms([room(current=5)])
        events, miss = diff_events(first, second, now=1, threshold=4)
        kinds = [item['type'] for item in events]
        self.assertIn('occupancy_changed', kinds)
        self.assertIn('occupancy_threshold', kinds)
        third = index_rooms([])
        gone, miss = diff_events(second, third, now=2, missing_cycles=2, miss_counts=miss)
        self.assertEqual(gone, [])
        gone, miss = diff_events(second, third, now=3, missing_cycles=2, miss_counts=miss)
        self.assertEqual(gone[0]['type'], 'room_missing')
        self.assertIn('不能据此宣称已开局', gone[0]['note'])

    def test_same_name_reused_id(self):
        old = room(name='甲', host='张', ident='1')
        new = room(name='乙', host='李', ident='1')
        self.assertTrue(reused_id(old, new))
        events, _ = diff_events(index_rooms([old]), index_rooms([new]), now=1)
        self.assertEqual(events[0]['type'], 'room_appeared')
        self.assertTrue(any(item['type'] == 'room_missing' or item['type'] == 'room_appeared' for item in events))

    def test_sort_change_is_not_new_room(self):
        a = room(name='甲', ident='1', current=2)
        b = room(name='乙', host='李', ident='2', current=3)
        events, _ = diff_events(index_rooms([a, b]), index_rooms([b, a]), now=1)
        self.assertEqual(events, [])

    def test_transient_missing_no_event(self):
        first = index_rooms([room()])
        events, miss = diff_events(first, [], now=1, missing_cycles=2)
        self.assertEqual(events, [])
        events, _ = diff_events(first, first, now=2, missing_cycles=2, miss_counts=miss)
        self.assertEqual(events, [])

    def test_cache_failure_not_zero_alert(self):
        good = empty_snapshot(LIVE)
        good['rooms'] = [room(current=6)]
        good['last_success_at'] = 10
        failed = empty_snapshot(CACHE, '搜索超时')
        kept = keep_last_good(failed, good)
        self.assertEqual(kept['rooms'][0]['current'], 6)
        self.assertEqual(kept['data_status'], CACHE)
        self.assertNotEqual(len(kept['rooms']), 0)

    def test_dedup_restart(self):
        event = {'type': 'occupancy_threshold', 'fingerprint': 'abc', 'to': 5, 'from': 3}
        dedup = {'sent': {}}
        self.assertTrue(should_emit(event, dedup, now=10, cooldown=180))
        mark_sent(dedup, event, now=10)
        self.assertFalse(should_emit(event, dedup, now=20, cooldown=180))
        self.assertTrue(should_emit(event, dedup, now=200, cooldown=180))
        need = {'type': 'needs_user', 'key': 'needs_user:x', 'message': 'x'}
        self.assertTrue(should_emit(need, {'sent': {}}, now=1, cooldown=180))
        marked = mark_sent({'sent': {}}, need, now=1)
        self.assertFalse(should_emit(need, marked, now=200, cooldown=180))

    def test_live_lost_and_recovered(self):
        self.assertEqual(data_events(LIVE, CACHE)[0]['type'], 'live_lost')
        self.assertEqual(data_events(CACHE, LIVE)[0]['type'], 'live_recovered')

    def test_summary_mentions_threshold_once(self):
        snap = empty_snapshot(LIVE)
        snap.update({'platform_line': '多线2（主线）', 'observed_at': time.time(), 'rooms': index_rooms([room(current=5)])})
        text = format_summary(snap, first=True, threshold=4)
        self.assertIn('默认人数提醒', text)
        self.assertIn('含房主', text)
        self.assertIn('已开局状态不可观测', text)

    def test_brief_failure_is_not_empty_room(self):
        snap = empty_snapshot(CACHE, '无法定位指定实例的游戏选择窗口')
        snap['connection_verified'] = False
        text = format_brief(snap)
        self.assertIn('未读到实时列表', text)
        self.assertIn('不是「没有房间」', text)


if __name__ == '__main__':
    unittest.main()
