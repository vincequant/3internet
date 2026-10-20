"""Current-game isolation uses real identity facts, with no game operations."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import time
import json
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_service import CommandService

PREFIX = 'prefix-fengye-shadow'


def state():
    return {'schema': 'astra-sgi-core-2', 'readonly': True,
            'identity': {'pid': 100, 'path': r'C:\sgi\SANPK.exe', 'creation_filetime': 123456},
            'core_address': '0x3412a00', 'build_sha256': 'a'*64,
            'scenario_map': {'scenario_id': 54},
            'snapshot_id': 'sample-1', 'capture_start': '2026-10-20T03:00:00+00:00',
            'capture_end': '2026-10-20T03:00:01+00:00',
            'consistency': {'root_headers_and_clock_unchanged': True},
            'player_context': {'my_slot': 5, 'my_force': None},
            'entities': {'lords': [{'force_id': 3, 'name': '齊', 'ruler_general_id': 44,
                                    'gold': 37022, 'armament_raw': {'infantry': 100}}],
                         'cities_and_barriers': []}}


def payload():
    return {'prefix': PREFIX, 'preset': 'train', 'actor': 3, 'troop': 0,
            'value': 75, 'extra': 0, 'auto_slot': True}


class SessionService(CommandService):
    def __init__(self, lab, history_path=None):
        self.raw = state()
        self.game_operations = []
        super().__init__(lab=lab, history_path=history_path)
        self.poll_interval = 0.001

    def _start_worker(self):
        pass

    def _start_verifier(self):
        pass

    def _run(self, *args, **kwargs):
        self.game_operations.append('run')
        raise AssertionError('tests must never invoke Wine or inject')

    def _switch_slot(self, *args, **kwargs):
        self.game_operations.append('switch')
        raise AssertionError('tests must never change slots')

    def pid(self, prefix):
        return self.raw['identity']['pid']

    def phase(self, prefix=PREFIX):
        return 2, {}

    def _py(self, prefix, script, extra=(), timeout=30):
        if script.endswith('_p60_battle.py'):
            return {'ok': True, 'readonly': True, 'state': deepcopy(self.raw),
                    'captured_at': self.raw['capture_end'],
                    'lords': [{'force_id': 3, 'name': '齊', 'gold': 37022}], 'cities': []}
        if script.endswith('_p60_slots.py'):
            return {'ok': True, 'slots': [{'force_id': 3, 'slot': 1}]}
        raise AssertionError('unexpected mock read')


class CommandSessionTests(unittest.TestCase):
    def test_actual_launch_import_order_keeps_bridge_effects_and_fengye_binding_separate(self):
        # run.py inserts root, app, then bridge at index zero. A fresh process
        # matters: the suite's root-first imports previously masked this bug.
        program = '''
import sys,json
from pathlib import Path
root=Path(sys.argv[1])
for folder in (root,root/'app',root/'bridge'):
    sys.path.insert(0,str(folder))
import command_effects
assert Path(command_effects.__file__).resolve().parent == root/'bridge'
assert callable(command_effects.force_badges)
from command_service import CommandService
service=CommandService()
assert service._adopt_game(json.load(sys.stdin))
from fengye_command_effects import _binding, capture_effect_baseline, check_effect
assert callable(_binding) and callable(capture_effect_baseline) and callable(check_effect)
'''
        result = subprocess.run([sys.executable, '-c', program, str(ROOT)],
                                input=json.dumps(state()), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.svc = SessionService(self.temp.name)

    def observed(self):
        return self.svc.targets(refresh=True)

    def test_capture_timestamp_and_observer_slot_do_not_change_game_key(self):
        first = self.observed()
        self.svc.raw.update(snapshot_id='sample-2', capture_start='2026-10-20T03:01:00+00:00',
                            capture_end='2026-10-20T03:01:01+00:00')
        self.svc.raw['player_context'] = {'my_slot': 1, 'my_force': 3}
        second = self.observed()
        self.assertEqual(first['game_key'], second['game_key'])
        self.assertEqual(first['game_token'], second['game_token'])
        self.assertNotIn('capture_end', first['game_identity'])
        self.assertNotIn('player_context', first['game_identity'])
        self.assertIn('獨立局 ID 未知', first['game_identity_limitation'])

    def test_real_process_core_build_scenario_and_roster_change_scope(self):
        for mutate in (lambda s: s['identity'].update(pid=101),
                       lambda s: s['identity'].update(creation_filetime=123999),
                       lambda s: s.update(core_address='0x4412a00'),
                       lambda s: s.update(build_sha256='b'*64),
                       lambda s: s.update(scenario_map={'scenario_id': 55}),
                       lambda s: s['entities']['lords'][0].update(ruler_general_id=45)):
            self.svc = SessionService(self.temp.name)
            before = self.observed()
            mutate(self.svc.raw)
            after = self.observed()
            self.assertNotEqual(before['game_key'], after['game_key'])

    def test_current_jobs_exclude_unkeyed_legacy_and_other_game_rows(self):
        info = self.observed()
        result = self.svc.submit(payload(), info)
        current = self.svc.jobs[0]
        self.svc.jobs.extend([dict(current, id='unkeyed', game_key=None),
                              dict(current, id='other-game', game_key='another-game'),
                              dict(current, id='legacy', status='legacy_sent', legacy={'source': 'old'})])
        view = self.svc.jobs_view()
        self.assertEqual(len(view['jobs']), 4)
        self.assertEqual([j['id'] for j in view['current_jobs']], [result['job']['id']])
        self.assertEqual(view['current_game_key'], info['game_key'])

    def test_observing_new_source_cancels_old_unstarted_queue(self):
        info = self.observed()
        old = self.svc.submit(payload(), info)['job']['id']
        self.svc.raw['identity']['creation_filetime'] += 1
        fresh = self.observed()
        self.assertNotEqual(info['game_key'], fresh['game_key'])
        self.assertEqual(self.svc.jobs[0]['status'], 'cancelled')
        self.assertEqual(self.svc.jobs[0]['id'], old)
        self.assertEqual(self.svc.queue, [])
        self.assertEqual(self.svc.jobs_view()['current_jobs'], [])
        self.assertEqual(self.svc.game_operations, [])

    def test_stale_form_cannot_enqueue_into_new_current_game(self):
        info = self.observed()
        self.svc.raw['identity']['creation_filetime'] += 1
        self.observed()
        self.assertFalse(self.svc.submit(payload(), info)['ok'])
        self.assertEqual(self.svc.queue, [])

    def test_fresh_prepare_rejects_a_game_changed_since_click(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        job = self.svc.jobs[0]
        self.svc.raw['identity']['creation_filetime'] += 1
        self.assertIsNone(self.svc._prepare_job(payload(), job))
        self.assertIn(job['status'], ('cancelled', 'error'))
        self.assertEqual(self.svc.game_operations, [])

    def test_game_is_rechecked_after_wait_before_any_slot_change(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        reads = [0]
        def phase(prefix=PREFIX):
            reads[0] += 1
            if reads[0] <= 2:
                return 1, {}
            self.svc.raw['identity']['creation_filetime'] += 1
            return 2, {}
        self.svc.phase = phase
        item = self.svc.queue.pop()
        self.svc._run_batch([(item, self.svc.jobs[0])])
        self.assertIn(self.svc.jobs[0]['status'], ('cancelled', 'error'))
        self.assertGreaterEqual(reads[0], 3)
        self.assertEqual(self.svc.game_operations, [])

    def test_old_unknown_different_real_process_does_not_block_new_game(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        self.svc.jobs[0]['status'] = 'unknown'
        self.svc.raw['identity']['creation_filetime'] += 1
        fresh = self.observed()
        result = self.svc.submit(payload(), fresh)
        self.assertEqual(result['job']['status'], 'pending')
        self.assertEqual(len(self.svc.jobs_view()['current_jobs']), 1)
        self.assertIsNone(self.svc._prefix_blocker(PREFIX))

    def test_same_process_core_roster_change_does_not_clear_unknown_agent(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        self.svc.jobs[0]['status'] = 'unknown'
        self.svc.raw['entities']['lords'][0]['ruler_general_id'] = 45
        fresh = self.observed()
        self.assertNotEqual(info['game_key'], fresh['game_key'])
        result = self.svc.submit(payload(), fresh)
        self.assertEqual(result['job']['status'], 'held')
        self.assertFalse(self.svc.flush_queue()['ok'])

    def test_same_live_process_with_new_core_cannot_clear_unknown_agent(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        self.svc.jobs[0]['status'] = 'unknown'
        self.svc.raw['core_address'] = '0x4412a00'
        fresh = self.observed()
        self.assertNotEqual(info['game_key'], fresh['game_key'])
        self.assertIsNotNone(self.svc._prefix_blocker(PREFIX))
        self.assertEqual(self.svc.submit(payload(), fresh)['job']['status'], 'held')
        self.assertFalse(self.svc.flush_queue()['ok'])
        self.assertEqual(self.svc.game_operations, [])

    def test_old_unkeyed_unknown_from_different_pid_does_not_block_current(self):
        self.svc.jobs.append({'id': 'old', 'created': 1, 'params': {},
                              'prefix': PREFIX, 'preset': 'train', 'status': 'unknown',
                              'target_pid': 99, 'events': []})
        info = self.observed()
        result = self.svc.submit(payload(), info)
        self.assertEqual(result['job']['status'], 'pending')
        self.assertEqual(len(self.svc.jobs_view()['current_jobs']), 1)
        self.assertEqual(len(self.svc.jobs_view()['jobs']), 2)

    def test_same_real_game_survives_panel_restart_without_replaying(self):
        history = Path(self.temp.name) / 'history.json'
        svc = SessionService(self.temp.name, history)
        info = svc.targets(refresh=True)
        original = svc.submit(payload(), info)['job']['id']
        svc.jobs[0].update(status='completed', effect={'confirmed': True}, finished=time.time())
        svc._save_history()
        loaded = SessionService(self.temp.name, history)
        refreshed = loaded.targets(refresh=True)
        self.assertEqual(info['game_key'], refreshed['game_key'])
        self.assertEqual([j['id'] for j in loaded.jobs_view()['current_jobs']], [original])
        self.assertEqual(loaded.queue, [])
        self.assertFalse(loaded._worker_running)
        self.assertEqual(loaded.game_operations, [])

    def test_missing_identity_hides_current_rows_and_disables_submission(self):
        info = self.observed()
        self.svc.submit(payload(), info)
        self.svc.raw['identity'].pop('creation_filetime')
        unknown = self.observed()
        self.assertIsNone(unknown['game_key'])
        self.assertEqual(self.svc.jobs_view()['current_jobs'], [])
        self.assertFalse(self.svc.submit(payload(), unknown)['ok'])
        self.assertEqual(len(self.svc.jobs_view()['jobs']), 1)

    def test_known_session_id_is_part_of_stable_source_identity(self):
        first = self.observed()
        self.svc.raw['session_id'] = 'observed-session-b'
        second = self.observed()
        self.assertNotEqual(first['game_key'], second['game_key'])
        self.assertEqual(second['game_identity']['session_id'], 'observed-session-b')


if __name__ == '__main__':
    unittest.main()
