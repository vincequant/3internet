#!/usr/bin/env python3
"""Targeted recovery tests. Importable on macOS; does not talk to the live game."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP = os.path.abspath(os.path.join(HERE, '..', 'app'))
if APP not in sys.path:
    sys.path.insert(0, APP)

from recovery import (
    RecoveryController, apply_layout_delta, classify_error, compute_fresh,
    discard_scan_buffers, next_backoff, path_matches_expected, process_identity,
    slim_snapshot, snapshot_age_s, CAPTURE_INTERVAL_S, MIN_SCAN_INTERVAL_S,
    PHASE_ERROR, PHASE_LIVE, PHASE_MAP_NOT_READY, PHASE_RECOVERING, PHASE_WAITING_GAME,
)


def inst(pid=664, path=r'C:\sgi\run-3.5\3I\SANPK.exe', created=100):
    return {'pid': pid, 'path': path, 'creation_filetime': created, 'created_utc': 't'}


def snap(core='0x4462e2a', sid='S1', end=None, coherent=True):
    if end is None:
        end = datetime.now(timezone.utc).isoformat()
    return {
        'snapshot_id': sid,
        'capture_end': end,
        'core_address': core,
        'timing': {'capture_ms': 12.5},
        'consistency': {'root_headers_and_clock_unchanged': coherent},
        'current_local_projection': {'gold': 1},
        'entities': {'lords': [{'name': '宋', 'raw_hex': 'aa', 'address': '0x1'}]},
    }


class FakeCollector:
    def __init__(self, pid, cores=None, captures=None, bind_errors=None, capture_errors=None):
        self.pid = pid
        self.core = None
        self.closed = False
        self.bind_calls = 0
        self.capture_calls = 0
        self.segments = ['scan']
        self.cache = {1: b'x'}
        self.headers = [1]
        self.m = type('M', (), {'segments': ['page'], 'regions': ['r'], 'cache': {}, 'close': lambda self: None})()
        self._cores = list(cores if cores is not None else [0x4462e2a])
        self._captures = list(captures or [])
        self._bind_errors = list(bind_errors or [])
        self._capture_errors = list(capture_errors or [])

    def bind(self, discover=False):
        self.bind_calls += 1
        if self._bind_errors:
            err = self._bind_errors.pop(0)
            if err:
                raise err
        if not self._cores:
            raise RuntimeError('Ambiguous/missing GameCore: 0')
        if len(self._cores) != 1:
            raise RuntimeError(f'Ambiguous/missing GameCore: {len(self._cores)}')
        self.core = self._cores[0]
        self.segments.clear()
        self.cache.clear()
        return {'mode': 'one_pass_discovery'}

    def capture(self):
        self.capture_calls += 1
        if self._capture_errors:
            err = self._capture_errors.pop(0)
            if err:
                raise err
        if self._captures:
            return self._captures.pop(0)
        return snap(core=hex(self.core or 0), sid=f'C{self.capture_calls}')

    def close(self):
        self.closed = True
        self.core = None
        discard_scan_buffers(self)


class Scripted:
    def __init__(self):
        self.lookups = []
        self.collectors = []
        self.configure_calls = []
        self.clock = [1000.0]

    def now(self):
        return self.clock[0]

    def advance(self, seconds):
        self.clock[0] += seconds

    def find_game(self):
        if not self.lookups:
            return {'status': 'none', 'instances': []}
        item = self.lookups.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def configure(self, pid, path):
        self.configure_calls.append((pid, path))

    def new_collector(self, pid):
        if not self.collectors:
            raise RuntimeError('no collector scripted')
        item = self.collectors.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecoveryTests(unittest.TestCase):
    def test_layout_delta_from_base_is_idempotent(self):
        base = {'CORE_VT': 0x10, 'DOC_VT': 0x20, 'TYPES': {1: 'a'}, 'UNIT_TYPES': {2: 'b'}}
        once = apply_layout_delta(base, 8)
        twice = apply_layout_delta(base, 8)
        self.assertEqual(once, twice)
        drifted = apply_layout_delta(once, 8)
        self.assertNotEqual(drifted['CORE_VT'], once['CORE_VT'])

    def test_fresh_never_true_for_old_or_errored_snapshot(self):
        now = datetime(2026, 9, 12, 10, 47, tzinfo=timezone.utc)
        old = snap(end=(now - timedelta(seconds=20)).isoformat())
        self.assertFalse(compute_fresh(True, None, old, now))
        live = snap(end=(now - timedelta(seconds=1)).isoformat())
        self.assertTrue(compute_fresh(True, None, live, now))
        self.assertFalse(compute_fresh(True, 'Unreadable page 4462000', live, now))
        self.assertFalse(compute_fresh(False, None, live, now))

    def test_classify_dead_root_and_map_and_version(self):
        self.assertEqual(classify_error(RuntimeError('Unreadable page 4462000'))[0], 'dead_root')
        self.assertEqual(classify_error(RuntimeError('Ambiguous/missing GameCore: 0'))[0], 'map_not_ready')
        self.assertEqual(classify_error(RuntimeError('Ambiguous/missing GameCore: 2'))[0], 'ambiguous_core')
        self.assertEqual(classify_error(RuntimeError('不支持的SANPK版本；停止，不套用结构偏移'))[0], 'unsupported_version')
        self.assertFalse(classify_error(RuntimeError('不支持的SANPK版本；停止，不套用结构偏移'))[3])

    def test_path_and_identity(self):
        self.assertTrue(path_matches_expected(r'C:\sgi\run-3.5\3I\SANPK.exe'))
        self.assertFalse(path_matches_expected(r'C:\other\SANPK.exe'))
        self.assertEqual(process_identity(inst(9, 'p', 3)), (9, 'p', 3))

    def test_old_core_dies_then_new_core_is_bound(self):
        world = Scripted()
        old = FakeCollector(664, cores=[0x4462e2a], capture_errors=[None, RuntimeError('Unreadable page 4462000')])
        new = FakeCollector(664, cores=[0x5511000], captures=[snap(core='0x5511000', sid='NEW')])
        world.lookups = [{'status': 'ok', 'instances': [inst()]}] * 4
        world.collectors = [old, new]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        self.assertEqual(ctl.step(), CAPTURE_INTERVAL_S)
        self.assertEqual(ctl.phase, PHASE_LIVE)
        self.assertEqual(old.capture_calls, 1)
        wait = ctl.step()
        self.assertEqual(ctl.error_class, 'dead_root')
        self.assertTrue(old.closed)
        self.assertIsNone(ctl.collector)
        world.advance(MIN_SCAN_INTERVAL_S)
        ctl.step()
        self.assertEqual(ctl.phase, PHASE_LIVE)
        self.assertTrue(ctl.fresh)
        self.assertIsNone(ctl.error)
        self.assertEqual(ctl.last_ok['snapshot_id'], 'NEW')
        self.assertEqual(ctl.collector.core, 0x5511000)
        self.assertEqual(len(world.configure_calls), 1)

    def test_bind_failure_then_recover(self):
        world = Scripted()
        fail = FakeCollector(664, bind_errors=[RuntimeError('Ambiguous/missing GameCore: 0')])
        ok = FakeCollector(664, cores=[0x1000], captures=[snap(sid='BOUND')])
        world.lookups = [{'status': 'ok', 'instances': [inst()]}] * 3
        world.collectors = [fail, ok]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        wait = ctl.step()
        self.assertEqual(ctl.phase, PHASE_MAP_NOT_READY)
        self.assertTrue(fail.closed)
        self.assertGreater(wait, 0)
        world.advance(wait)
        ctl.step()
        self.assertEqual(ctl.phase, PHASE_LIVE)
        self.assertIsNone(ctl.error)
        self.assertEqual(ctl.last_ok['snapshot_id'], 'BOUND')

    def test_transient_inconsistency_keeps_service_and_old_snapshot(self):
        world = Scripted()
        c = FakeCollector(664, captures=[snap(sid='GOOD'), snap(sid='BAD', coherent=False), snap(sid='GOOD2')])
        world.lookups = [{'status': 'ok', 'instances': [inst()]}] * 3
        world.collectors = [c]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step()
        self.assertEqual(ctl.last_ok['snapshot_id'], 'GOOD')
        ctl.step()
        self.assertEqual(ctl.phase, PHASE_RECOVERING)
        self.assertEqual(ctl.error_class, 'transient_inconsistent')
        self.assertFalse(compute_fresh(ctl.fresh, ctl.error, ctl.last_ok))
        self.assertEqual(ctl.last_ok['snapshot_id'], 'GOOD')
        self.assertFalse(c.closed)
        ctl.step()
        self.assertEqual(ctl.phase, PHASE_LIVE)
        self.assertIsNone(ctl.error)
        self.assertEqual(ctl.last_ok['snapshot_id'], 'GOOD2')

    def test_process_identity_change_reconfigures(self):
        world = Scripted()
        a = FakeCollector(664, captures=[snap(sid='A')])
        b = FakeCollector(900, cores=[0x777], captures=[snap(core='0x777', sid='B')])
        world.lookups = [
            {'status': 'ok', 'instances': [inst(664, created=100)]},
            {'status': 'ok', 'instances': [inst(900, created=200)]},
        ]
        world.collectors = [a, b]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step()
        self.assertEqual(ctl.bound_identity[0], 664)
        world.advance(MIN_SCAN_INTERVAL_S)
        ctl.step()
        self.assertTrue(a.closed)
        self.assertEqual(ctl.phase, PHASE_LIVE)
        self.assertEqual(ctl.bound_identity[0], 900)
        self.assertEqual(world.configure_calls, [(664, r'C:\sgi\run-3.5\3I\SANPK.exe'), (900, r'C:\sgi\run-3.5\3I\SANPK.exe')])

    def test_multiple_instances_do_not_attach_or_report_live(self):
        world = Scripted()
        c = FakeCollector(664, captures=[snap(sid='LIVE')])
        world.lookups = [
            {'status': 'ok', 'instances': [inst()]},
            {'status': 'multiple', 'instances': [inst(664), inst(665)]},
        ]
        world.collectors = [c]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step()
        self.assertTrue(ctl.fresh)
        ctl.step()
        self.assertEqual(ctl.error_class, 'multiple_instances')
        self.assertEqual(ctl.phase, PHASE_ERROR)
        self.assertTrue(c.closed)
        self.assertIsNone(ctl.collector)
        pub = ctl.public_state()
        self.assertFalse(pub['fresh'])
        self.assertEqual(pub['last_snapshot_id'], 'LIVE')

    def test_process_gone_waits_and_releases(self):
        world = Scripted()
        c = FakeCollector(664, captures=[snap(sid='LIVE')])
        world.lookups = [{'status': 'ok', 'instances': [inst()]}, {'status': 'none', 'instances': []}]
        world.collectors = [c]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step()
        ctl.step()
        self.assertEqual(ctl.phase, PHASE_WAITING_GAME)
        self.assertTrue(c.closed)
        self.assertIsNone(ctl.collector)
        self.assertFalse(ctl.public_state()['fresh'])

    def test_unsupported_version_does_not_retry_same_identity(self):
        world = Scripted()
        world.lookups = [{'status': 'ok', 'instances': [inst()]}] * 2
        world.collectors = [RuntimeError('不支持的SANPK版本；停止，不套用结构偏移')]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step()
        self.assertEqual(ctl.error_class, 'unsupported_version')
        self.assertEqual(ctl.phase, PHASE_ERROR)
        ctl.step()
        self.assertEqual(ctl.error_class, 'unsupported_version')
        self.assertEqual(len(world.configure_calls), 1)

    def test_scan_buffers_and_handles_are_released(self):
        holder = type('H', (), {'segments': [1, 2], 'cache': {3: 4}, 'm': type('M', (), {'segments': [9], 'regions': [8]})()})()
        discarded = discard_scan_buffers(holder)
        self.assertGreaterEqual(discarded, 4)
        self.assertEqual(holder.segments, [])
        self.assertEqual(holder.m.segments, [])
        world = Scripted()
        c = FakeCollector(664, captures=[snap()])
        world.lookups = [{'status': 'ok', 'instances': [inst()]}, {'status': 'none', 'instances': []}]
        world.collectors = [c]
        ctl = RecoveryController(world.find_game, world.configure, world.new_collector, now=world.now)
        ctl.step(); ctl.step()
        self.assertTrue(c.closed)
        self.assertEqual(ctl.released_count, 1)
        self.assertIsNotNone(ctl.last_released)
        self.assertIsNone(ctl.collector)
        self.assertFalse(hasattr(ctl, 'closed') and ctl.closed)

    def test_slim_snapshot_drops_raw_hex(self):
        out = slim_snapshot(snap())
        self.assertNotIn('raw_hex', out['entities']['lords'][0])
        self.assertNotIn('address', out['entities']['lords'][0])

    def test_snapshot_age(self):
        now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
        doc = snap(end='2026-09-12T11:59:50+00:00')
        self.assertAlmostEqual(snapshot_age_s(doc, now), 10)


class FakeProcessApi:
    def __init__(self, path=r'C:\sgi\run-3.5\3I\SANPK.exe'):
        self.path = path
        self.opened = []
        self.closed = []
        self._n = 100
        self.fail_query = None
        self.fail_times = None

    def open_process(self, pid):
        self._n += 1
        self.opened.append(self._n)
        return self._n

    def close_handle(self, h):
        self.closed.append(h)

    def query_path(self, h):
        if self.fail_query:
            raise self.fail_query
        return self.path

    def process_times(self, h):
        if self.fail_times:
            raise self.fail_times
        return 123, '2026-09-12T10:00:00+00:00'


class ResourceCleanupTests(unittest.TestCase):
    def setUp(self):
        os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'

    def test_memory_query_path_times_and_mismatch_close_handle_once(self):
        from probe import Memory
        cases = [
            ('query', lambda api: setattr(api, 'fail_query', OSError('identity query failed'))),
            ('times', lambda api: setattr(api, 'fail_times', OSError('creation time query failed'))),
            ('path', lambda api: setattr(api, 'path', r'C:\other\SANPK.exe')),
        ]
        for name, setup in cases:
            api = FakeProcessApi()
            setup(api)
            with self.assertRaises((OSError, RuntimeError), msg=name):
                Memory(1740, api=api)
            self.assertEqual(api.opened, api.closed, msg=name)
            leaked = Memory.__new__(Memory)
            leaked.api = api
            leaked.h = None
            leaked.close()
            leaked.close()
            self.assertEqual(api.opened, api.closed, msg=name + ' idempotent')

    def test_memory_success_close_is_idempotent(self):
        from probe import Memory
        api = FakeProcessApi()
        mem = Memory(1740, api=api)
        self.assertEqual(api.closed, [])
        mem.close()
        mem.close()
        self.assertEqual(api.closed, api.opened)
        self.assertEqual(len(api.closed), 1)

    def test_collector_file_read_and_hash_failures_close_real_memory(self):
        from probe import Memory
        from collector import Collector, BUILD
        api = FakeProcessApi()
        def factory(pid):
            return Memory(pid, api=api)
        with self.assertRaises(OSError):
            Collector(1740, memory_factory=factory, read_exe=lambda p: (_ for _ in ()).throw(OSError('exe unreadable')))
        self.assertEqual(api.opened, api.closed)
        self.assertEqual(len(api.closed), 1)
        api2 = FakeProcessApi()
        with self.assertRaises(RuntimeError):
            Collector(1740, memory_factory=lambda pid: Memory(pid, api=api2), read_exe=lambda p: b'not-the-build')
        self.assertEqual(api2.opened, api2.closed)
        self.assertEqual(len(api2.closed), 1)

    def test_collector_success_then_close_twice(self):
        from probe import Memory
        from collector import Collector, BUILD
        api = FakeProcessApi()
        payload = bytes.fromhex(BUILD)  # 32 bytes, wrong; need content whose sha256 is BUILD
        # BUILD is the hex digest, so return bytes that hash to it via a stub reader:
        class Once:
            def __init__(self):
                self.n = 0
            def __call__(self, path):
                self.n += 1
                return b'sanpk-image'
        # Use a patched hashlib via returning bytes and monkeypatch would be heavier;
        # instead compute any bytes and temporarily accept by wrapping read to return
        # content, then construct with a custom BUILD check by feeding exact digest match.
        content = b'sanpk-image'
        import hashlib
        real = Collector.BUILD if hasattr(Collector, 'BUILD') else BUILD
        # Force match by returning bytes whose digest equals BUILD is impossible unless we
        # inject. Use read_exe that returns content and patch BUILD for this test only.
        import collector as col
        old = col.BUILD
        try:
            col.BUILD = hashlib.sha256(content).hexdigest()
            c = Collector(1740, memory_factory=lambda pid: Memory(pid, api=api), read_exe=lambda p: content)
            self.assertEqual(api.closed, [])
            c.close()
            c.close()
            self.assertEqual(api.closed, api.opened)
        finally:
            col.BUILD = old

    def test_repeated_rebind_collectors_are_collectable(self):
        import gc
        import weakref
        refs = []
        def make(pid):
            c = FakeCollector(pid, captures=[snap(sid=f'R{len(refs)}')])
            refs.append(weakref.ref(c))
            return c
        world = Scripted()
        world.lookups = []
        for i in range(24):
            world.lookups.append({'status': 'ok', 'instances': [inst(created=i + 1)]})
            world.lookups.append({'status': 'none', 'instances': []})
        ctl = RecoveryController(world.find_game, world.configure, make, now=world.now)
        for _ in range(48):
            ctl.step()
            world.advance(MIN_SCAN_INTERVAL_S)
        gc.collect()
        self.assertEqual(ctl.released_count, 24)
        self.assertIsNone(ctl.collector)
        self.assertFalse(any(r() is not None for r in refs))
        self.assertIsInstance(ctl.last_released, dict)
        self.assertNotIn('closed', ctl.__dict__)


class StatusTextTests(unittest.TestCase):
    def test_active_old_collector_reports_deferred_upgrade(self):
        from portable_client import status_text
        from unittest.mock import patch
        with patch('portable_client.viewer_version',return_value='new'):
            p={'fresh':True,'phase':'live','release_version':'old'}
            self.assertIn('更新待本局结束',status_text(p,snap())[0])
            p['release_version']='new'
            self.assertNotIn('更新待本局结束',status_text(p,snap())[0])

    def test_lobby_reports_connection_and_armed_recorder_without_old_match_age(self):
        from portable_client import status_text
        p={'fresh':False,'phase':'waiting_for_player','snapshot_age_s':303,
           'replay_archive':{'recording':False,'open':False,'write_error':None}}
        text,_=status_text(p,snap())
        for part in ('已连接游戏','等待开局','记录监控已启动','回放待开局'):
            self.assertIn(part,text)
        for part in ('旧快照','恢复中','回放记录中'):
            self.assertNotIn(part,text)
        p['replay_archive']['write_error']='private/path'
        self.assertIn('回放写入异常',status_text(p)[0])
        self.assertNotIn('监控已启动',status_text(p)[0])
        self.assertNotIn('private',status_text(p)[0])

    def test_live_recorder_counts_and_unconfirmed_state(self):
        from portable_client import status_text,recording_text
        p={'fresh':True,'phase':'live','replay_archive':{'recording':True,'open':True,'seq':12}}
        self.assertIn('回放记录中 12帧',status_text(p,snap())[0])
        self.assertEqual(recording_text({}),'记录状态未确认')
        p['replay_archive']['recording']=False
        p['native_payload_observations']={'enabled':True,'phase':'backoff'}
        self.assertIn('指令采集异常',recording_text(p))
        p['replay_archive'].update(recording=True,open=True)
        self.assertIn('回放记录中 12帧 · 指令采集异常',recording_text(p))

    def test_status_labels(self):
        from portable_client import status_text
        live = {'fresh': True, 'phase': 'live', 'error': None, 'snapshot_age_s': 1}
        text, color = status_text(live, snap(sid='ABC'))
        self.assertIn('采集实时', text)
        self.assertIn('ABC', text)
        self.assertNotIn('恢复中', text)
        recovering = {'fresh': False, 'phase': 'recovering', 'error': 'Unreadable page 4462000', 'snapshot_age_s': 40}
        text, _ = status_text(recovering, snap())
        self.assertIn('恢复中', text)
        self.assertIn('40秒', text)
        self.assertNotIn('实时', text)
        waiting = {'fresh': False, 'phase': 'waiting_for_game',
                   'error': r"last.tmp' -> 'Z:\\Users\\vk\\Documents\\Coding\\三国志internet\\history-data\\1\\last.json",
                   'snapshot_age_s': None}
        text, _ = status_text(waiting, None)
        self.assertIn('等待游戏', text)
        self.assertNotIn('last.tmp', text)
        self.assertNotIn('Z:', text)
        self.assertNotIn('history-data', text)
        self.assertNotIn('Unreadable page', status_text(recovering, snap())[0])
        stale_live_flag = {'fresh': True, 'phase': 'live', 'error': 'x', 'snapshot_age_s': 1}
        text, _ = status_text(stale_live_flag, snap())
        self.assertNotIn('采集实时', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
