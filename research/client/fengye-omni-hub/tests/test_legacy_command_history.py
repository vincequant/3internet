"""Local old-record migration is read-only to its evidence and never dispatches."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_service import CommandService, RECEIPT_MAGIC2
from legacy_command_history import import_legacy_jobs


def plan(preset='train', **changes):
    subtype = {'train': 0, 'alms': 2, 'rice': 3, 'build': 4, 'personnel': 5}[preset]
    values = {4: 20 if preset == 'personnel' else 18, 8: subtype, 12: 0, 20: 3, 24: 0,
              28: 75 if preset == 'train' else 4, 32: 0 if preset == 'train' else 4}
    if preset == 'build':
        values.update({12: 79 | (50 << 16), 24: 9, 28: 29, 32: 2000})
    elif preset == 'rice':
        values.update({24: 1, 28: 1000, 32: 0})
    elif preset == 'personnel':
        values = {4: 20, 8: 5, 12: 0, 20: 3, 24: 77}
    data = {'mode': 'generic_cmd', 'preset': preset,
            'class': 'personnel' if preset == 'personnel' else 'domestic',
            'pid': 360, 'creation': 134369382702094100, 'thread_id': 123,
            'fields': [{'off': hex(offset), 'val': value} for offset, value in values.items()]}
    data.update(changes)
    return data


def receipt(data, rc=1):
    fields = {int(item['off'], 0): item['val'] for item in data['fields']}
    values = [RECEIPT_MAGIC2, rc, 0x3412a00, 100, 1, 1, 1, 1234, 0x503a00,
              fields.get(4, 18), fields.get(8, 0), fields.get(12, 0), fields.get(20, 0),
              fields.get(24, 0), fields.get(28, 0), fields.get(32, 0)]
    return struct.pack('<16I', *(value & 0xffffffff for value in values))


class LegacyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lab = Path(self.temp.name)
        def forbidden(*args, **kwargs):
            self.fail('legacy import attempted a process or game operation')
        self.service = CommandService(lab=self.lab, runner=forbidden,
                                      history_path=self.lab / 'display-history.json')

    def write(self, data, tag='74021f19', received=True):
        path = self.lab / ('p60_ui_' + tag + '.json')
        path.write_text(json.dumps(data), encoding='utf-8')
        if received:
            path.with_suffix('.bin').write_bytes(receipt(data))
        return path

    def test_actual_train_fields_are_restored_without_new_defaults(self):
        self.write(plan())
        result = import_legacy_jobs(self.service)
        self.assertEqual(result['imported'], 1)
        job = self.service.jobs[0]
        self.assertEqual(job['preset'], 'train')
        self.assertEqual(job['params'], {'actor': 3, 'troop': 0, 'value': 75, 'extra': 0})
        self.assertEqual(job['status'], 'legacy_sent')
        self.assertEqual(job['target_pid'], 360)
        self.assertFalse(job['legacy']['effect_verified'])
        self.assertIsNone(job['source_prefix'])
        self.assertEqual(self.service.queue, [])
        self.assertFalse(self.service._worker_running)
        self.assertIsNone(self.service._prefix_blocker('prefix-fengye-shadow'))

    def test_alms_is_not_mislabelled_as_training(self):
        self.write(plan('alms'))
        import_legacy_jobs(self.service)
        job = self.service.jobs[0]
        self.assertEqual(job['preset'], 'alms')
        self.assertEqual(job['params']['value'], 4)
        self.assertEqual(job['params']['extra'], 4)
        self.assertNotIn('troop', job['params'])
        self.assertEqual(job['receipt']['subtype'], 2)

    def test_missing_receipt_keeps_display_only_unknown(self):
        self.write(plan(), received=False)
        import_legacy_jobs(self.service)
        job = self.service.jobs[0]
        self.assertEqual(job['status'], 'legacy_unknown')
        self.assertIsNone(job['receipt'])
        self.assertNotIn('finished', job)
        self.assertIsNone(self.service._prefix_blocker('prefix-fengye-shadow'))
        self.assertEqual(self.service.queue, [])

    def test_existing_tag_is_not_imported_twice(self):
        self.write(plan())
        self.assertEqual(import_legacy_jobs(self.service)['imported'], 1)
        self.assertEqual(import_legacy_jobs(self.service)['imported'], 0)
        loaded = CommandService(lab=self.lab, history_path=self.service.history_path)
        self.assertEqual(import_legacy_jobs(loaded)['imported'], 0)
        self.assertEqual(len(loaded.jobs), 1)

    def test_existing_modern_job_with_same_tag_takes_precedence(self):
        self.write(plan())
        self.service.jobs.append({'id': 'modern', 'tag': '74021f19', 'created': 1})
        self.assertEqual(import_legacy_jobs(self.service)['imported'], 0)
        self.assertEqual(self.service.jobs[0]['id'], 'modern')

    def test_missing_value_stays_unknown_not_75_or_zero(self):
        data = plan()
        data['fields'] = [field for field in data['fields'] if field['off'] != '0x1c']
        self.write(data, received=False)
        import_legacy_jobs(self.service)
        job = self.service.jobs[0]
        self.assertEqual(job['status'], 'legacy_unknown')
        self.assertNotIn('value', job['params'])
        self.assertIn('0x1c', job['legacy']['missing_fields'])

    def test_build_xy_city_kind_and_cost_use_verified_abi(self):
        self.write(plan('build'))
        import_legacy_jobs(self.service)
        params = self.service.jobs[0]['params']
        self.assertEqual((params['x'], params['y']), (79, 50))
        self.assertEqual(params['city'], 29)
        self.assertEqual(params['build_type'], 9)
        self.assertEqual(params['extra'], 2000)

    def test_rice_and_personnel_keep_their_own_fields(self):
        self.write(plan('rice'), '11111111')
        self.write(plan('personnel'), '22222222')
        import_legacy_jobs(self.service)
        jobs = {job['preset']: job for job in self.service.jobs}
        self.assertEqual(jobs['rice']['params']['buy'], 1)
        self.assertEqual(jobs['rice']['params']['value'], 1000)
        self.assertEqual(jobs['personnel']['params']['subtype'], 5)
        self.assertEqual(jobs['personnel']['params']['target_id'], 77)
        self.assertNotIn('value', jobs['personnel']['params'])

    def test_bad_json_and_bad_receipt_are_preserved_byte_for_byte(self):
        path = self.write(plan())
        path.with_suffix('.bin').write_bytes(b'bad receipt')
        bad = self.lab / 'p60_ui_11111111.json'
        bad.write_bytes(b'{not json')
        original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, path.with_suffix('.bin'), bad)}
        result = import_legacy_jobs(self.service)
        self.assertEqual(result['imported'], 1)
        self.assertTrue(result['errors'])
        self.assertEqual(self.service.jobs[0]['status'], 'legacy_unknown')
        for p, digest in original.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), digest)

    def test_preset_subtype_conflict_is_not_invented_into_a_command(self):
        data = plan('alms')
        data['preset'] = 'train'
        self.write(data)
        result = import_legacy_jobs(self.service)
        self.assertEqual(result['imported'], 0)
        self.assertTrue(result['errors'])

    def test_plan_only_records_are_not_imported_as_sent(self):
        self.write(plan(plan_only=True))
        self.assertEqual(import_legacy_jobs(self.service)['imported'], 0)
        self.assertEqual(self.service.jobs, [])

    def test_only_explicit_local_ledger_configuration_enables_import(self):
        self.write(plan())
        self.service.history_path = None
        result = import_legacy_jobs(self.service)
        self.assertFalse(result['enabled'])
        self.assertEqual(self.service.jobs, [])

    def test_receipt_must_match_original_plan_fields(self):
        path = self.write(plan())
        data = bytearray(path.with_suffix('.bin').read_bytes())
        struct.pack_into('<I', data, 13*4, 2)  # troop differs from plan
        path.with_suffix('.bin').write_bytes(data)
        import_legacy_jobs(self.service)
        self.assertEqual(self.service.jobs[0]['status'], 'legacy_unknown')
        self.assertIsNone(self.service.jobs[0]['receipt'])

    def test_state_mtime_and_process_creation_time_have_distinct_semantics(self):
        path = self.write(plan())
        import_legacy_jobs(self.service)
        job = self.service.jobs[0]
        self.assertEqual(job['created'], path.stat().st_mtime)
        self.assertEqual(job['legacy']['process_creation_filetime'], 134369382702094100)
        self.assertEqual(job['legacy']['time_semantics'], 'state_file_write_time')


if __name__ == '__main__':
    unittest.main()
