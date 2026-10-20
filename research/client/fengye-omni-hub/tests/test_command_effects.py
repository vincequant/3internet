"""Observed effects require original, fresh and source-bound Collector data."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fengye_command_effects import capture_effect_baseline, check_effect


def snapshot(number=1, training=100):
    entities = {
        'lords': [{'force_id': 3, 'name': '齊', 'ruler_general_id': 44,
                   'gold': 37022, 'armament_raw': {'infantry': training, 'cavalry': 70, 'bow': 20}}],
        'cities_and_barriers': [{'type': 'city', 'city_id': 29, 'owner_raw': 3, 'world_xy_raw': [80, 50]}],
        'production_buildings': [], 'traps': [],
    }
    return {'schema': 'astra-sgi-core-2', 'readonly': True,
            'identity': {'pid': 100, 'path': r'C:\sgi\SANPK.exe', 'creation_filetime': 123456},
            'source_pid': 100, 'source_prefix': 'prefix-fengye-shadow',
            'core_address': '0x3412a00', 'build_sha256': 'a'*64,
            'snapshot_id': 'sample-%s' % number,
            'capture_start': '2026-10-20T03:00:%02d+00:00' % (number*2),
            'capture_end': '2026-10-20T03:00:%02d+00:00' % (number*2+1),
            'consistency': {'root_headers_and_clock_unchanged': True, 'atomic_game_snapshot': False},
            'entities': entities,
            'coverage': {key: {'structurally_valid': True, 'count': len(rows)} for key, rows in entities.items()}}


def train(troop=0):
    return {'id': 'train-%s' % troop, 'preset': 'train', 'params': {'actor': 3, 'troop': troop, 'value': 75}}


def build(kind=7):
    return {'id': 'build-%s' % kind, 'preset': 'build',
            'params': {'actor': 3, 'city': 29, 'x': 79, 'y': 50, 'build_type': kind}}


def add_building(state, kind=7, **changes):
    row = {'owner_raw': 3, 'world_xy_raw': [79, 50], 'address': '0x444444',
           'object_id_candidate': 5, 'linked_city_id': 29, 'building_ui_amount': 2000,
           'type': {7: 'parade_ground', 8: 'horse_farm', 9: 'bow_studio', 6: 'trap'}[kind]}
    container = 'production_buildings'
    if kind == 6:
        container = 'traps'
        row.update(trap_kind='陷阱', trap_id=5)
    row.update(changes)
    state['entities'][container].append(row)
    state['coverage'][container]['count'] += 1
    return row


class EffectTests(unittest.TestCase):
    def result(self, job, before, after):
        baseline = capture_effect_baseline(job, before)
        self.assertTrue(baseline['ok'], baseline)
        return check_effect(job, baseline, after)

    def test_actual_training_raw_changes_for_each_troop(self):
        for troop, key in ((0, 'infantry'), (1, 'cavalry'), (2, 'bow')):
            before, after = snapshot(), snapshot(2)
            old = before['entities']['lords'][0]['armament_raw'][key]
            after['entities']['lords'][0]['armament_raw'][key] += 30
            after['entities']['lords'][0]['gold'] -= 1000
            result = self.result(train(troop), before, after)
            self.assertTrue(result['confirmed'], result)
            self.assertEqual(result['before']['training_raw'], old)
            self.assertEqual(result['after']['training_raw'], old+30)
            self.assertFalse(result['evidence']['native_command_proof'])
            self.assertFalse(result['evidence']['gold_change']['sufficient_alone'])

    def test_gold_only_local_rc_and_other_troop_do_not_confirm(self):
        before, after = snapshot(), snapshot(2)
        after['entities']['lords'][0]['gold'] -= 1000
        after['entities']['lords'][0]['armament_raw']['cavalry'] += 30
        job = train()
        job['receipt'] = {'rc': 1}
        self.assertFalse(self.result(job, before, after)['confirmed'])

    def test_pre_receipt_or_overlapping_sample_cannot_complete_training(self):
        before = snapshot(1, 100)
        for receipt_time in ('2026-10-20T03:00:06+00:00',
                             '2026-10-20T03:00:04+00:00'):
            job = train()
            job['receipt_at'] = datetime.fromisoformat(receipt_time).timestamp()
            result = self.result(job, before, snapshot(2, 130))
            self.assertFalse(result['confirmed'])
            self.assertIn('回報之後', result['summary'])

    def test_only_a_sample_started_after_observed_receipt_can_complete(self):
        job = train()
        job['receipt_at'] = datetime.fromisoformat('2026-10-20T03:00:05+00:00').timestamp()
        result = self.result(job, snapshot(1, 100), snapshot(3, 130))
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['evidence']['causal_attribution'], 'not_proven')

    def test_pre_receipt_new_building_is_not_marked_completed_yet(self):
        job = build()
        job['receipt_at'] = datetime.fromisoformat('2026-10-20T03:00:06+00:00').timestamp()
        before, early, later = snapshot(), snapshot(2), snapshot(4)
        add_building(early)
        add_building(later)
        self.assertFalse(self.result(job, before, early)['confirmed'])
        self.assertTrue(self.result(job, before, later)['confirmed'])

    def test_malformed_receipt_timestamp_cannot_prove_freshness(self):
        for value in (True, '2026-10-20T03:00:03+00:00', float('nan')):
            job = train()
            job['receipt_at'] = value
            self.assertFalse(self.result(job, snapshot(), snapshot(2, 130))['confirmed'])

    def test_core_raw_not_local_projection_or_display_percentage(self):
        before, after = snapshot(training=95), snapshot(2, training=125)
        after['current_local_projection'] = {'armament_raw': {'infantry': 1}}
        after['entities']['lords'][0]['training_progress'] = {'infantry': 25}
        self.assertTrue(self.result(train(), before, after)['confirmed'])

    def test_cap_requires_a_real_increase(self):
        self.assertTrue(self.result(train(), snapshot(training=290), snapshot(2, training=300))['confirmed'])
        result = self.result(train(), snapshot(training=300), snapshot(2, training=300))
        self.assertFalse(result['confirmed'])
        self.assertIn('未觀測到增加', result['summary'])

    def test_wrong_sized_change_or_decrease_is_not_enough(self):
        for raw in (99, 100, 101, 129, 131, 160):
            self.assertFalse(self.result(train(), snapshot(), snapshot(2, raw))['confirmed'])

    def test_each_new_allowed_building_and_trap(self):
        for kind in (6, 7, 8, 9):
            before, after = snapshot(), snapshot(2)
            add_building(after, kind)
            result = self.result(build(kind), before, after)
            self.assertTrue(result['confirmed'], result)
            self.assertEqual(result['evidence']['new_object']['owner_raw'], 3)

    def test_building_wrong_owner_kind_cell_or_city_is_not_completion(self):
        for change in ({'owner_raw': 2}, {'type': 'horse_farm'}, {'world_xy_raw': [78, 50]}, {'linked_city_id': 28}):
            before, after = snapshot(), snapshot(2)
            add_building(after, **change)
            self.assertFalse(self.result(build(), before, after)['confirmed'])

    def test_fire_or_rock_is_not_requested_trap(self):
        for kind in ('火计', '落石', None):
            before, after = snapshot(), snapshot(2)
            add_building(after, 6, trap_kind=kind)
            self.assertFalse(self.result(build(6), before, after)['confirmed'])

    def test_preexisting_object_is_never_new(self):
        before, after = snapshot(), snapshot(2)
        add_building(before)
        add_building(after)
        self.assertFalse(self.result(build(), before, after)['confirmed'])
        # Changing object ID or replacing a previous other-kind object does
        # not make an already occupied baseline cell eligible either.
        before['entities']['production_buildings'][0]['type'] = 'horse_farm'
        self.assertFalse(self.result(build(), before, after)['confirmed'])

    def test_multiple_new_objects_at_cell_remain_ambiguous(self):
        before, after = snapshot(), snapshot(2)
        add_building(after)
        add_building(after, 6)
        self.assertFalse(self.result(build(), before, after)['confirmed'])

    def test_unknown_or_partial_container_cannot_prove_absence(self):
        for alter in ('missing', 'count', 'structural', 'unstable'):
            before, after = snapshot(), snapshot(2)
            if alter == 'missing':
                before['entities'].pop('traps')
            elif alter == 'count':
                before['coverage']['traps']['count'] = 1
            elif alter == 'structural':
                before['coverage']['traps']['structurally_valid'] = False
            else:
                before['consistency']['root_headers_and_clock_unchanged'] = False
            baseline = capture_effect_baseline(build(), before)
            self.assertFalse(baseline['ok'])
            add_building(after)
            self.assertFalse(check_effect(build(), baseline, after)['confirmed'])

    def test_unknown_object_location_cannot_prove_baseline_cell_empty(self):
        before, after = snapshot(), snapshot(2)
        add_building(before, world_xy_raw=None)
        add_building(after)
        baseline = capture_effect_baseline(build(), before)
        self.assertFalse(baseline['ok'])
        self.assertFalse(check_effect(build(), baseline, after)['confirmed'])

    def test_same_snapshot_stale_or_overlapping_capture_does_not_confirm(self):
        for alter in ('id', 'backwards', 'overlap', 'missingtime'):
            before, after = snapshot(), snapshot(2, 130)
            if alter == 'id':
                after['snapshot_id'] = before['snapshot_id']
            elif alter == 'backwards':
                after['capture_start'] = '2026-10-20T03:00:00+00:00'
                after['capture_end'] = '2026-10-20T03:00:01+00:00'
            elif alter == 'overlap':
                after['capture_start'] = before['capture_end']
            else:
                after.pop('capture_start')
            self.assertFalse(self.result(train(), before, after)['confirmed'])

    def test_different_process_core_build_or_known_game_refused(self):
        for key in ('pid', 'creation_filetime', 'path', 'core_address', 'build_sha256', 'run_id', 'game_id', 'source_prefix'):
            before, after = snapshot(), snapshot(2, 130)
            if key in before['identity']:
                after['identity'][key] = {'pid': 101, 'creation_filetime': 654321, 'path': 'other.exe'}[key]
            elif key == 'core_address':
                after[key] = '0x999999'
            elif key == 'build_sha256':
                after[key] = 'b'*64
            elif key in ('run_id', 'game_id'):
                before[key], after[key] = 'old', 'new'
            else:
                after[key] = 'other-prefix'
            self.assertFalse(self.result(train(), before, after)['confirmed'], key)

    def test_known_identity_disappearing_not_silently_accepted(self):
        before, after = snapshot(), snapshot(2, 130)
        before['run_id'] = 'known-run'
        self.assertFalse(self.result(train(), before, after)['confirmed'])
        self.assertNotIn('run_id', capture_effect_baseline(train(), after)['binding'])

    def test_mutated_or_unknown_target_and_duplicate_force_fail_closed(self):
        before, after = snapshot(), snapshot(2, 130)
        baseline = capture_effect_baseline(train(), before)
        changed = train(1)
        self.assertFalse(check_effect(changed, baseline, after)['confirmed'])
        after['entities']['lords'].append(deepcopy(after['entities']['lords'][0]))
        after['coverage']['lords']['count'] += 1
        self.assertFalse(check_effect(train(), baseline, after)['confirmed'])
        for value in (None, -1, 301, True, '130'):
            after = snapshot(2)
            after['entities']['lords'][0]['armament_raw']['infantry'] = value
            self.assertFalse(check_effect(train(), baseline, after)['confirmed'])

    def test_baseline_is_deep_frozen_and_inputs_not_modified(self):
        job, state = train(), snapshot()
        original = deepcopy(state)
        baseline = capture_effect_baseline(job, state)
        self.assertEqual(state, original)
        state['entities']['lords'][0]['armament_raw']['infantry'] = 250
        self.assertEqual(baseline['observation']['training_raw'], 100)
        job['params']['troop'] = 1
        self.assertEqual(baseline['target']['troop'], 0)

    def test_unsupported_actions_and_non_collector_snapshots_fail_closed(self):
        for job in ({'preset': 'alms', 'params': {'actor': 3}}, train(3), build(4)):
            self.assertFalse(capture_effect_baseline(job, snapshot())['ok'])
        state = snapshot()
        state.pop('readonly')
        self.assertFalse(capture_effect_baseline(train(), state)['ok'])
        self.assertFalse(check_effect(train(), None, snapshot(2, 130))['confirmed'])


if __name__ == '__main__':
    unittest.main()
