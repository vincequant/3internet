"""同一格不重複建設：佔用表 + 佇列/在途 job 的雙重去重。

背景（2026-10-20）：遊戲的建造函式（0x4515a8 的 4/5/6 分支）建物件前不查
目標格是否已被佔用，所以同一格重複下指令會疊出第二個陷阱——畫面上就是同
一格疊兩三條血條。這裡驗的是面板層的兩道閘：
  1. 佔用表（建築／陷阱／城池關卡）
  2. 佇列 + 在途 job（陷阱要等下回合結算才進記憶體，光看佔用表擋不住連點）
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from command_service import CommandService

CITY = {'city_id': 7, 'name': '洛陽', 'owner': 3, 'xy': [50, 100]}
INFO = {'forces': [{'force_id': 3, 'name': '風夜'}], 'cities': [CITY]}


def build_payload(x=52, y=101, build_type=6):
    return {'prefix': 'prefix-fengye-shadow', 'preset': 'build', 'actor': 3,
            'city': 7, 'x': x, 'y': y, 'build_type': build_type, 'extra': 2000}


class FakeService(CommandService):
    """不碰 wine：pid 與 _py 都給假資料。"""

    def __init__(self, occupied=()):
        super().__init__(lab=ROOT)
        self.calls = []
        self._fake_occupied = list(occupied)

    def pid(self, prefix):
        return 4242

    def _py(self, prefix, script, extra=(), timeout=30):
        self.calls.append((script, tuple(extra)))
        if script.endswith('_p60_occupied.py'):
            return {'ok': True, 'occupied': [
                {'kind': kind, 'xy': list(xy)} for kind, xy in self._fake_occupied]}
        return {'ok': False}

    def targets(self, refresh=False):
        return INFO


class OccupiedCellTests(unittest.TestCase):
    def test_free_cell_passes(self):
        svc = FakeService()
        self.assertIsNone(svc.validate(build_payload(), INFO))

    def test_trap_on_the_cell_is_refused(self):
        svc = FakeService(occupied=[('trap', (52, 101))])
        reason = svc.validate(build_payload(), INFO)
        self.assertIsNotNone(reason)
        self.assertIn('陷阱', reason)
        self.assertIn('52,101', reason)

    def test_building_and_city_are_refused_too(self):
        for kind, word in (('building', '建築'), ('city', '城池')):
            svc = FakeService(occupied=[(kind, (52, 101))])
            reason = svc.validate(build_payload(), INFO)
            self.assertIsNotNone(reason, kind)
            self.assertIn(word, reason)

    def test_other_cells_are_not_blocked(self):
        svc = FakeService(occupied=[('trap', (52, 101))])
        self.assertIsNone(svc.validate(build_payload(x=53, y=101), INFO))

    def test_occupancy_is_cached_so_validate_is_not_a_wine_call_every_time(self):
        svc = FakeService(occupied=[('trap', (52, 101))])
        for _ in range(4):
            svc.validate(build_payload(), INFO)
        reads = [c for c in svc.calls if c[0].endswith('_p60_occupied.py')]
        self.assertEqual(len(reads), 1)

    def test_occupancy_read_failure_keeps_the_last_table(self):
        svc = FakeService(occupied=[('trap', (52, 101))])
        svc.validate(build_payload(), INFO)          # 先讀到一張有陷阱的表
        svc._py = lambda *a, **k: {'ok': False}      # 之後讀失敗
        reason = svc.validate(build_payload(), INFO, occupied=svc.occupied_cells(
            'prefix-fengye-shadow', refresh=True))
        self.assertIsNotNone(reason, '讀失敗時應該沿用舊表，不要放行')


class QueueDedupeTests(unittest.TestCase):
    def setUp(self):
        self.svc = FakeService()

    def test_same_cell_twice_is_refused(self):
        first = self.svc.queue_add(build_payload())
        self.assertTrue(first['ok'])
        second = self.svc.queue_add(build_payload())
        self.assertFalse(second['ok'])
        self.assertIn('佇列', second['error'])
        self.assertEqual(len(self.svc.queue_view()['queue']), 1)

    def test_different_cell_is_allowed(self):
        self.assertTrue(self.svc.queue_add(build_payload(x=52, y=101))['ok'])
        self.assertTrue(self.svc.queue_add(build_payload(x=53, y=101))['ok'])
        self.assertEqual(len(self.svc.queue_view()['queue']), 2)

    def test_pending_cells_are_skipped_by_the_cell_picker(self):
        self.svc.queue_add(build_payload(x=52, y=101))
        busy = self.svc.busy_build_cells()
        self.assertIn((52, 101), busy)
        self.assertNotIn((53, 101), busy)

    def test_in_flight_job_also_blocks_the_cell(self):
        """送出後、還沒回執的 job 也要擋（陷阱要下回合才進記憶體）。"""
        self.svc.jobs = [{'id': 'abc123', 'preset': 'build', 'status': 'firing',
                          'params': {'x': 54, 'y': 101}}]
        reason = self.svc.validate(build_payload(x=54, y=101), INFO)
        self.assertIsNotNone(reason)
        self.assertIn('剛送出', reason)

    def test_finished_job_stops_blocking(self):
        self.svc.jobs = [{'id': 'abc123', 'preset': 'build', 'status': 'fired',
                          'params': {'x': 54, 'y': 101}}]
        self.assertIsNone(self.svc.validate(build_payload(x=54, y=101), INFO))

    def test_non_build_commands_are_untouched(self):
        payload = {'prefix': 'prefix-fengye-shadow', 'preset': 'alms',
                   'actor': 3, 'value': 100, 'extra': 4}
        self.assertTrue(self.svc.queue_add(payload)['ok'])
        self.assertTrue(self.svc.queue_add(payload)['ok'])


if __name__ == '__main__':
    unittest.main()
