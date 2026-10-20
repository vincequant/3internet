"""Canonical queued requests: fake transport only, never Wine or game input."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_service import CommandService, RECEIPT_MAGIC2

PREFIX = 'prefix-fengye-shadow'
INFO = {'ok': True, 'game_key': 'mock-current-game',
        'targets': [{'prefix': PREFIX, 'pid': 42}],
        'forces': [{'force_id': 3}],
        'cities': [{'city_id': 7, 'owner': 3, 'name': '洛陽', 'xy': [50, 100]}],
        'player_slots': [{'force_id': 3, 'slot': 1}],
        'local': {'force_id': None, 'slot': 5, 'status': 'hidden'}}


def train(troop=0):
    return {'prefix': PREFIX, 'preset': 'train', 'actor': 3,
            'troop': troop, 'value': 75, 'extra': 30, 'auto_slot': True}


def build(x=52):
    return {'prefix': PREFIX, 'preset': 'build', 'actor': 3,
            'city': 7, 'x': x, 'y': 101, 'build_type': 6,
            'extra': 2000, 'auto_slot': True}


class MockService(CommandService):
    def __init__(self, lab, history_path=None):
        # Keep the pre-seat persistence inside the test's temp dir: a real
        # data/pre_seat.json would leak the mock game key into the app.
        super().__init__(lab=lab, history_path=history_path or (Path(lab) / 'history.json'))
        self.calls = []
        self.switches = []
        self.phase_reads = 0
        self.effect_count = 0
        self._cache = INFO
        # 這一局已經「開局前上身」（mock）
        self.pre_seat = {'slot': 1, 'game_key': INFO['game_key'], 'at': 0.0}
        self.poll_interval = 0.001

    def _start_worker(self):
        pass

    def _start_verifier(self):
        pass

    def targets(self, refresh=False):
        return INFO

    def pid(self, prefix):
        return 42

    def phase(self, prefix=PREFIX):
        self.phase_reads += 1
        return 1, {'f_4d6': 0}

    def reference_state(self, prefix=None):
        return None

    def occupied_cells(self, *a, **k):
        return {}

    def _py(self, prefix, script, extra=(), timeout=30):
        return {'ok': True, 'candidates': [{'xy': [52, 101]}, {'xy': [53, 101]}]}

    def _ghost_home_slot(self, default=None):
        return 5

    def _switch_slot(self, slot, timeout=60):
        self.switches.append(slot)
        return True, 'mock only'

    def _capture_baseline(self, job):
        return {'ok': True, 'count': self.effect_count}

    def _effect_snapshot(self):
        return {'count': self.effect_count}

    def _verify_effect(self, job, baseline, state):
        return {'confirmed': state['count'] > baseline['count'],
                'summary': 'actual mock state changed' if state['count'] > baseline['count'] else 'unchanged'}

    def _run(self, prefix, args, timeout=30):
        self.calls.append(args)
        return SimpleNamespace(stdout='{"thread_id": 123}', stderr='', returncode=0)

    def _wait_receipt(self, job):
        job['receipt'] = {'magic2': RECEIPT_MAGIC2, 'rc': 1}
        self._update(job, 'fired', 'local receipt only')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.svc = MockService(self.temp.name)

    def test_auto_restore_only_after_a_preseat_game_starts(self):
        # 2026-10-21：開局前上身 → 開局後自動切回 5；每局只做一次。
        key = INFO['game_key']
        self.svc.pre_seat = {'slot': 1, 'game_key': key, 'at': 0.0}
        started = dict(INFO, local={'force_id': 3, 'slot': 1}, phase=1)
        self.assertTrue(self.svc.should_auto_restore(started))
        # 只在內政期切回（避免跨回合把客戶端卡住）
        self.assertFalse(self.svc.should_auto_restore(dict(started, phase=3)))
        # 開局後先等幾秒再切
        self.svc._game_seen_at[key] = __import__('time').time()
        self.assertFalse(self.svc.should_auto_restore(started))
        self.svc._game_seen_at[key] = __import__('time').time() - 30
        self.assertTrue(self.svc.should_auto_restore(started))
        self.assertFalse(self.svc.should_auto_restore(started, restored={key}))
        self.assertFalse(self.svc.should_auto_restore(dict(INFO, local={'force_id': None, 'slot': 5})))
        self.assertFalse(self.svc.should_auto_restore(dict(INFO, game_key='other')))
        self.assertFalse(self.svc.should_auto_restore(started, enabled=False))
        self.svc.pre_seat = None
        self.assertFalse(self.svc.should_auto_restore(started))

    def test_refuses_to_send_without_a_preseat_for_this_game(self):
        # 2026-10-20 23:5x：主機只收「開局前已在該席位」的指令，沒有上身的局
        # 一律拒絕，避免送出後留下假成功。
        self.svc.pre_seat = None
        reason = self.svc.validate(train(), INFO)
        self.assertIn('開局前上身', reason or '')

    def test_switch_ghost_seat_takes_a_slot_and_rejects_out_of_range(self):
        # 2026-10-20: 「開局前上身」按鈕走這條；只切席位，不送指令。
        self.assertTrue(self.svc.switch_ghost_seat(0)['ok'])
        self.assertEqual(self.svc.switches, [0])
        bad = self.svc.switch_ghost_seat(9)
        self.assertFalse(bad['ok'])
        self.assertEqual(self.svc.switches, [0], '超出 0–7 不得呼叫切換')
        self.assertFalse(self.svc.switch_ghost_seat(True)['ok'])

    def test_submit_is_immediate_and_does_no_discovery(self):
        self.svc.targets = lambda **k: self.fail('submit discovered targets')
        self.svc.pid = lambda *a: self.fail('submit probed Wine')
        self.svc._run = lambda *a, **k: self.fail('submit injected')
        start = time.monotonic()
        result = self.svc.submit(train(), INFO)
        self.assertLess(time.monotonic() - start, 0.1)
        self.assertTrue(result['ok'])
        job_id = result['job']['id']
        self.assertEqual(job_id, self.svc.queue[0]['id'])
        self.assertEqual(job_id, self.svc.jobs_view()['jobs'][0]['id'])
        self.assertEqual(result['job']['status'], 'pending')

    def test_same_faction_batch_uses_one_borrow_window(self):
        self.svc.submit(train(0), INFO)
        self.svc.submit(train(1), INFO)
        self.svc._dispatch()
        self.assertEqual(len(self.svc.calls), 2)
        self.assertEqual(self.svc.switches, [1, 5])
        # one read for the domestic gate, one re-check after the seat switch
        self.assertEqual(self.svc.phase_reads, 2)
        self.assertEqual([j['status'] for j in self.svc.jobs], ['verifying', 'verifying'])
        self.assertTrue(all(not j.get('finished') for j in self.svc.jobs))

    def test_local_receipt_never_means_completed(self):
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        job = self.svc.jobs[0]
        self.assertEqual(job['status'], 'verifying')
        self.assertIsNone(job.get('finished'))
        self.svc._verification_jobs[job['id']]['deadline'] = 0
        with patch('command_service.time.sleep'):
            self.svc._verification_loop()
        self.assertEqual(job['status'], 'verifying')
        self.assertTrue(job['verification_exhausted'])
        self.assertFalse(job['effect']['confirmed'])

    def test_only_observed_state_change_marks_completed(self):
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.svc.effect_count = 1
        with patch('command_service.time.sleep'):
            self.svc._verification_loop()
        self.assertEqual(self.svc.jobs[0]['status'], 'completed')
        self.assertTrue(self.svc.jobs[0]['effect']['confirmed'])

    def test_same_troop_waits_for_distinct_effect_and_can_cancel(self):
        self.svc.submit(train(0), INFO)
        second = self.svc.submit(train(0), INFO)['job']['id']
        self.svc._dispatch()
        self.assertEqual(len(self.svc.calls), 1)
        self.assertEqual(self.svc.jobs[1]['status'], 'waiting_effect')
        self.assertTrue(self.svc.cancel(second)['ok'])
        self.assertEqual(self.svc.jobs[1]['status'], 'cancelled')

    def test_cancel_pending_keeps_canonical_audit_row(self):
        job_id = self.svc.submit(train(), INFO)['job']['id']
        result = self.svc.cancel(job_id)
        self.assertTrue(result['ok'])
        self.assertEqual(result['job']['id'], job_id)
        self.svc._dispatch()
        self.assertEqual(self.svc.calls, [])
        self.assertEqual(len(self.svc.jobs), 1)
        self.assertEqual(self.svc.jobs[0]['status'], 'cancelled')

    def test_cancel_waiting_phase_has_no_side_effect(self):
        job_id = self.svc.submit(train(), INFO)['job']['id']
        self.svc.phase = lambda *a: (4, {'f_4d6': 0})
        thread = threading.Thread(target=self.svc._dispatch)
        thread.start()
        deadline = time.monotonic() + 1
        while self.svc.jobs[0]['status'] != 'waiting_phase_exit' and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertEqual(self.svc.jobs[0]['status'], 'waiting_phase_exit')
        self.assertTrue(self.svc.cancel(job_id)['ok'])
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.svc.switches, [])
        self.assertEqual(self.svc.calls, [])

    def test_cannot_claim_armed_agent_was_cancelled(self):
        job_id = self.svc.submit(train(), INFO)['job']['id']
        self.svc.jobs[0]['status'] = 'arming'
        self.assertFalse(self.svc.cancel(job_id)['ok'])
        self.assertEqual(self.svc.jobs[0]['status'], 'arming')

    def test_unknown_pauses_batch_new_submit_and_flush(self):
        self.svc._run = lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('mock', 40))
        self.svc.submit(train(0), INFO)
        self.svc.submit(train(1), INFO)
        self.svc._dispatch()
        self.assertEqual([j['status'] for j in self.svc.jobs], ['unknown', 'held'])
        self.assertEqual(self.svc.switches, [1])
        result = self.svc.submit(train(2), INFO)
        self.assertEqual(result['job']['status'], 'held')
        self.assertFalse(self.svc.flush_queue()['ok'])
        self.assertTrue(all(not q['execute'] for q in self.svc.queue))

    def test_unexpected_restore_exception_pauses_next_command(self):
        def switching(slot, timeout=60):
            self.svc.switches.append(slot)
            if slot == 5:
                raise RuntimeError('mock interrupted restore')
            return True, 'ok'
        self.svc._switch_slot = switching
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.jobs[0]['status'], 'restore_failed')
        result = self.svc.submit(train(1), INFO)
        self.assertEqual(result['job']['status'], 'held')

    def test_parameter_exception_precedes_seat_side_effect(self):
        self.svc.build_args = lambda *a: (_ for _ in ()).throw(ValueError('bad param'))
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.jobs[0]['status'], 'error')
        self.assertEqual(self.svc.switches, [])

    def test_unknown_phase_does_not_switch_or_arm(self):
        self.svc.phase = lambda *a: (None, None)
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.jobs[0]['status'], 'error')
        self.assertEqual(self.svc.switches, [])
        self.assertEqual(self.svc.calls, [])

    def test_unusable_pre_state_never_arms_a_command(self):
        self.svc._capture_baseline = lambda job: {'ok': False, 'error': 'partial data'}
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.jobs[0]['status'], 'error')
        self.assertEqual(self.svc.calls, [])
        self.assertEqual(self.svc.switches, [1, 5])

    def test_changed_process_in_pre_state_never_arms(self):
        self.svc._capture_baseline = lambda job: {'ok': True, 'binding': {'identity': {'pid': 99}}}
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.jobs[0]['status'], 'error')
        self.assertEqual(self.svc.calls, [])

    def test_different_factions_do_not_share_the_borrowed_seat(self):
        info = dict(INFO, forces=[{'force_id': 3}, {'force_id': 4}],
                    player_slots=[{'force_id': 3, 'slot': 1}, {'force_id': 4, 'slot': 2}])
        self.svc.targets = lambda **k: info
        self.svc.submit(train(0), info)
        self.svc.submit(dict(train(1), actor=4), info)
        self.svc._dispatch()
        self.assertEqual(self.svc.switches, [1, 5, 2, 5])
        self.assertEqual(len(self.svc.calls), 2)

    def test_build_excludes_itself_in_both_validation_paths(self):
        self.svc.submit(build(), INFO)
        self.svc._dispatch()
        self.assertEqual(len(self.svc.calls), 1)
        self.assertEqual(self.svc.jobs[0]['status'], 'verifying')
        self.assertIn((52, 101), self.svc.busy_build_cells())
        self.assertFalse(self.svc.submit(build(), INFO)['ok'])

    def test_fired_build_reservation_survives_before_settlement(self):
        self.svc.jobs = [{'id': 'x', 'preset': 'build', 'status': 'fired',
                          'params': {'x': 52, 'y': 101}}]
        self.assertIn((52, 101), self.svc.busy_build_cells())

    def test_reload_never_replays_and_unknown_guard_survives(self):
        path = Path(self.temp.name) / 'history.json'
        svc = MockService(self.temp.name, path)
        svc.submit(train(), INFO)
        svc.jobs[0]['status'] = 'unknown'
        svc._save_history()
        loaded = MockService(self.temp.name, path)
        self.assertEqual(loaded.queue, [])
        self.assertEqual(loaded.calls, [])
        self.assertEqual(loaded.submit(train(1), INFO)['job']['status'], 'held')
        self.assertFalse(loaded.flush_queue()['ok'])

    def test_reload_pending_is_cancelled_not_replayed(self):
        path = Path(self.temp.name) / 'history.json'
        svc = MockService(self.temp.name, path)
        svc.submit(train(), INFO)
        loaded = MockService(self.temp.name, path)
        self.assertEqual(loaded.jobs[0]['status'], 'cancelled')
        self.assertEqual(loaded.queue, [])

    def test_malformed_history_row_cannot_break_jobs_view(self):
        path = Path(self.temp.name) / 'history.json'
        path.write_text(json.dumps([{'id': 'bad', 'status': 'fired'}]))
        svc = MockService(self.temp.name, path)
        self.assertEqual(svc.jobs_view()['jobs'], [])
        self.assertIsNotNone(svc.jobs_view()['history_error'])

    def test_reload_preserves_unconfirmed_restore_even_after_observed_effect(self):
        path = Path(self.temp.name) / 'history.json'
        svc = MockService(self.temp.name, path)
        svc.submit(train(), INFO)
        svc.jobs[0].update(status='completed', slot_pending_restore=True,
                           effect={'confirmed': True})
        svc._save_history()
        loaded = MockService(self.temp.name, path)
        self.assertEqual(loaded.jobs[0]['status'], 'unknown')
        self.assertEqual(loaded.submit(train(1), INFO)['job']['status'], 'held')

    def test_targets_exposes_only_same_source_raw_training_and_epoch_time(self):
        self.svc.battlefield = lambda **k: {
            'ok': True, 'source_pid': 42, 'captured_at': '2026-10-20T03:00:00+00:00',
            'lords': [{'force_id': 3, 'gold': 100}], 'cities': [],
            'state': {'entities': {'lords': [{'force_id': 3,
                                            'armament_raw': {'infantry': 120, 'cavalry': 80, 'bow': 40}},
                                           {'force_id': 4, 'armament_raw': {'infantry': 999}}]}}}
        data = CommandService._read_targets(self.svc, refresh=True)
        self.assertEqual(data['forces'][0]['armament_raw'],
                         {'infantry': 120, 'cavalry': 80, 'bow': 40})
        self.assertIsInstance(data['at'], float)

    def test_unresolved_history_is_not_truncated_by_recent_terminals(self):
        path = Path(self.temp.name) / 'history.json'
        svc = MockService(self.temp.name, path)
        svc.submit(train(), INFO)
        svc.jobs[0]['status'] = 'unknown'
        for i in range(220):
            svc.jobs.append(dict(svc.jobs[0], id='done%s' % i, status='error'))
        svc._save_history()
        loaded = MockService(self.temp.name, path)
        self.assertTrue(any(j['status'] == 'unknown' for j in loaded.jobs))
        self.assertEqual(loaded.submit(train(1), INFO)['job']['status'], 'held')
        stored = json.loads(path.read_text())
        self.assertTrue(all('flag' not in j and 'receipt_path' not in j for j in stored))

    def test_real_dispatcher_never_overlaps_seat_changing_jobs(self):
        self.svc._start_worker = CommandService._start_worker.__get__(self.svc)
        active = [0, 0]
        guard = threading.Lock()
        original_run = self.svc._run
        def slow_run(*a, **k):
            with guard:
                active[0] += 1
                active[1] = max(active[1], active[0])
            time.sleep(0.01)
            result = original_run(*a, **k)
            with guard:
                active[0] -= 1
            return result
        self.svc._run = slow_run
        self.svc.submit(train(0), INFO)
        self.svc.submit(train(1), INFO)
        deadline = time.monotonic() + 2
        while self.svc._worker_running and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.svc._worker_running)
        self.assertEqual(len(self.svc.calls), 2)
        self.assertEqual(active[1], 1)


    def test_fires_in_the_current_domestic_phase_without_waiting(self):
        job_id = self.svc.submit(train(), INFO)['job']['id']
        self.svc._dispatch()
        job = self.svc.jobs[0]
        self.assertEqual(job['status'], 'verifying')
        self.assertEqual(job.get('phase_at_submit'), 1)
        self.assertNotIn('waiting_phase_exit',
                         [event['status'] for event in job['events']])
        self.assertEqual(self.svc.switches, [1, 5])
        self.assertEqual(len(self.svc.calls), 1)

    def test_stale_delivery_client_fails_before_the_seat_switch(self):
        self.svc.phase = lambda *a: (4, {'f_4d6': 0, 'rows_f4a': [16, 5]})
        self.svc.reference_state = lambda prefix=None: {
            'phase': 1, 'season': 3, 'roster': (16, 5)}
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        job = self.svc.jobs[0]
        self.assertEqual(job['status'], 'error')
        self.assertIn('停在 season 0', job['note'])
        self.assertEqual(self.svc.switches, [])
        self.assertEqual(self.svc.calls, [])

    def test_waiting_aborts_when_the_real_client_moves_ahead(self):
        self.svc.phase = lambda *a: (2, {'f_4d6': 0, 'rows_f4a': [16, 5]})
        reference = [{'phase': 2, 'season': 0, 'roster': (16, 5)},
                     {'phase': 2, 'season': 1, 'roster': (16, 5)}]
        calls = {'n': 0}

        def next_reference(prefix=None):
            index = min(calls['n'], len(reference) - 1)
            calls['n'] += 1
            return reference[index]

        self.svc.reference_state = next_reference
        self.svc.reference_check_interval = 0.0
        self.svc.submit(train(), INFO)
        self.svc._dispatch()
        job = self.svc.jobs[0]
        self.assertEqual(job['status'], 'error')
        self.assertIn('玩家端已在 season 1', job['note'])
        self.assertEqual(self.svc.switches, [])

    def test_different_roster_is_not_treated_as_stale(self):
        self.assertIsNone(CommandService._staleness_error(
            {'phase': 4, 'season': 0, 'roster': (1, 2)},
            {'phase': 1, 'season': 3, 'roster': (3, 4)}))

    def test_home_seat_survives_a_pending_restore(self):
        self.svc.jobs = [{'id': 'pending', 'slot_pending_restore': True,
                          'slot_home': 5}]
        self.svc.runner = lambda *a, **k: SimpleNamespace(
            stdout='123 bash slotkeep.sh --slot 1 --seconds 1',
            stderr='', returncode=0)
        self.assertEqual(self.svc._ghost_home_slot(default=None), 5)


    def test_eta_text_uses_game_year_and_season(self):
        self.assertEqual(CommandService.eta_text(1, 200, 0),
                         '200年春內政階段（現在）')
        self.assertEqual(CommandService.eta_text(4, 200, 0),
                         '200年夏內政階段結束後')
        self.assertEqual(CommandService.eta_text(2, 200, 3),
                         '201年春內政階段結束後')
        self.assertIsNone(CommandService.eta_text(None, 200, 0))

    def test_submit_keeps_the_payload_eta_text(self):
        result = self.svc.submit(dict(train(), eta_text='200年夏內政階段結束後'), INFO)
        self.assertEqual(result['job']['eta_text'], '200年夏內政階段結束後')

    def test_drop_client_is_local_only_and_uses_p63(self):
        tools = Path(self.temp.name) / 'tools'
        tools.mkdir()
        (tools / 'p63_drop_inject.py').write_text('# fake')
        calls = []

        def run(prefix, args, timeout=30):
            calls.append((prefix, args))
            return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr='')

        self.svc._run = run
        result = self.svc.drop_client('prefix-dingman-local')
        self.assertTrue(result['ok'])
        self.assertEqual(calls[0][0], 'prefix-dingman-local')
        self.assertIn('p63_drop_inject.py', calls[0][1][0])
        refused = self.svc.drop_client('prefix-fengye-shadow')
        self.assertFalse(refused['ok'])
        self.assertEqual(len(calls), 1)


    def test_direct_client_batch_does_not_borrow_the_ghost_seat(self):
        payload = dict(train(), prefix='prefix-dingman-local', auto_slot=False)
        self.svc.submit(payload, INFO)
        self.svc._dispatch()
        self.assertEqual(self.svc.switches, [])
        self.assertEqual(len(self.svc.calls), 1)
        self.assertEqual(self.svc.jobs[0]['status'], 'verifying')
        self.assertEqual(self.svc.jobs[0]['prefix'], 'prefix-dingman-local')


if __name__ == '__main__':
    unittest.main()
