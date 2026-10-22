import copy
import json
from pathlib import Path
import tempfile
import unittest

from game_archive import ArchiveReader, GameArchiveRecorder, wait_recorder, write_packed_archive
from replay_query import MatchQuery
from replay_training import capture_profile, export_observations, read_capture_config, sha, supplement, annotation_summary
from replay_view import decorate_ops
from test_game_archive import make_computer_state, live


class ReplayTrainingTests(unittest.TestCase):
    def test_state_facts_and_command_flags_never_become_original_inputs(self):
        for item in ({'field': '部队移动', 'command': True},
                     {'field': '录用', 'via': 'pending_hire'}, {'field': '金钱', 'before': 10, 'after': 20}):
            row = decorate_ops([item])[0]
            self.assertFalse(row['training_provenance']['native_instruction_captured'])
            self.assertFalse(row['training_provenance']['action_training_eligible'])
        profile = capture_profile(make_computer_state(), {'computer': 'weak', 'ruleset_confirmed': False})
        self.assertEqual(len(profile['per_force_instruction_coverage']), 8)
        self.assertFalse(profile['original_instruction_stream_captured'])
        self.assertTrue(all(r['raw_instruction_count'] is None for r in profile['per_force_instruction_coverage']))

    def test_machine_local_optin_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(read_capture_config(root))
            path = root / 'training-capture.local.json'
            path.write_text('[]')
            with self.assertRaisesRegex(ValueError, 'object'):
                read_capture_config(root)
            path.write_text(json.dumps({'enabled': False}))
            self.assertIsNone(read_capture_config(root))
            valid = {'enabled': True, 'observation_mode': 'omniscient', 'computer': 'weak',
                     'ruleset_id': 'unverified', 'ruleset_confirmed': False, 'scenario': None}
            path.write_text(json.dumps(valid))
            self.assertFalse(read_capture_config(root)['ruleset_confirmed'])
            for key, value in [('enabled', 'true'), ('computer', 'expert'), ('ruleset_confirmed', None),
                               ('observation_mode', 'player_visible')]:
                path.write_text(json.dumps({**valid, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    read_capture_config(root)

    def test_training_recorder_keeps_short_computer_trial_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = GameArchiveRecorder(root=root / 'normal', keep_min_frames=1000)
            training = GameArchiveRecorder(root=root / 'training', keep_formats=None, keep_min_frames=0,
                                           training_context={'computer': 'weak', 'ruleset_confirmed': False})
            try:
                for seq in range(3):
                    payload = live(make_computer_state(seq))
                    normal.ingest(payload)
                    training.ingest(payload)
                wait_recorder(normal);wait_recorder(training)
            finally:
                normal.close();training.close()
            self.assertFalse(list((root / 'normal').glob('*/manifest.json')))
            paths = list((root / 'training').glob('*/manifest.json'))
            self.assertEqual(len(paths), 1)
            with ArchiveReader(paths[0].parent) as reader:
                self.assertEqual(reader.frame_count(), 3)
                self.assertEqual(reader.manifest['recording_purpose'], 'training_research')
                self.assertFalse(reader.manifest['training_context']['ruleset_confirmed'])
                self.assertFalse(reader._read_record(1)['training_observation']['original_instruction_stream_captured'])

    def test_observation_export_separates_future_targets_and_unknown_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'archive'
            write_packed_archive(archive, [make_computer_state(i) for i in range(3)], simulated=True)
            report = export_observations(archive, root / 'export')
            self.assertEqual((report['pairs'], report['action_label_count']), (2, 0))
            self.assertTrue(report['synthetic'])
            rows = [json.loads(line) for line in (root / 'export/observations.jsonl').read_text().splitlines()]
            for row in rows:
                self.assertIsNone(row['action'])
                self.assertFalse(row['action_label_known'])
                self.assertEqual(set(row['features']), {'state_before'})
                self.assertEqual(set(row['targets']), {'observed_state_after'})
                self.assertTrue(row['capture_profile']['synthetic'])
            query = MatchQuery(archive)
            try:
                self.assertFalse(query.latest_snapshot()['training_capture']['original_instruction_stream_captured'])
            finally:
                query.close()
            with self.assertRaises(FileExistsError):
                export_observations(archive, root / 'export')
            with self.assertRaises(ValueError):
                export_observations(archive, root / 'bad', first=1, last=3, max_frames=2)

    def test_export_rejects_reversed_time_and_identity_changes(self):
        for kind in ('clock', 'identity'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                states = [make_computer_state(0), make_computer_state(1)]
                if kind == 'clock':
                    states[1]['capture_end'] = states[0]['capture_end']
                else:
                    states[1]['identity']['pid'] += 1
                write_packed_archive(root / 'archive', states, simulated=True)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    export_observations(root / 'archive', root / 'export')

    def test_read_only_export_never_writes_missing_round_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'archive'
            write_packed_archive(archive, [make_computer_state(i) for i in range(3)], simulated=True)
            index_path = archive / 'index.json'
            index = json.loads(index_path.read_text())
            index.pop('rounds', None)
            index_path.write_text(json.dumps(index))
            (archive / 'rounds.json').unlink(missing_ok=True)
            before = {p.name: sha(p) for p in archive.iterdir() if p.is_file()}
            export_observations(archive, root / 'export')
            self.assertEqual(before, {p.name: sha(p) for p in archive.iterdir() if p.is_file()})
            with ArchiveReader(archive) as reader:
                self.assertEqual(reader.frame_count(), 3)
            self.assertTrue((archive / 'rounds.json').is_file())

    def test_supplement_is_separate_hash_bound_and_cursor_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'archive'
            state = make_computer_state()
            write_packed_archive(archive, [state], simulated=False)
            original = sha(archive / 'frames.jsonl')
            tx, ep, turn = [root / (name + '.json') for name in ('tx','episode','turn')]
            tx.write_text('{"fixture_only":true}')
            turn.write_text('{"fixture_only":true}')
            ep.write_text(json.dumps({'synthetic':False,'config':{'episode_id':'fixture-episode',
                'game_id':'fixture-game','game_build_sha256':state['build_sha256']}}))
            proof = root / 'proof.json'
            proof.write_text(json.dumps({'ui_report': {'inspector': {'identity': {**state['identity'],'sha256':state['build_sha256']}}},
                                        'read_only': True, 'game_command_sent': False,
                                        'submission_sha256':sha(tx),'yes_mouse_receipt_verified':True,
                                        'paid_order_settlement_observed':True,'side_effect_unknown':False,
                                        'outcome':'paid_attempt_no_hire','recruitment_ownership_transition_verified':False,
                                        'checked_at': '2026-10-03T01:00:00+00:00'}))
            row = {'sample_id': 'test-only-not-a-game-label', 'task': 'recruit_ownership',
                   'episode_id':'fixture-episode','game_id':'fixture-game',
                   'synthetic': False, 'observation_mode': 'omniscient', 'scope': 'development_smoke_only',
                   'formal_evaluation_eligible': False, 'game_build_sha256': state['build_sha256'],
                   'features': {'test_fixture': 1},'outcome':{'ownership_acquired':0},
                   'evidence': [{'path':str(p),'sha256':sha(p)} for p in (tx,proof,ep,turn)]}
            dataset = root / 'data';dataset.mkdir()
            (dataset / 'transitions.jsonl').write_text(json.dumps(row) + '\n')
            (dataset / 'manifest.json').write_text(json.dumps({'schema_version': 2,
                'status': 'audited_development_transitions_only', 'accepted': 1,
                'formal_evaluation_eligible': False, 'transitions_sha256': sha(dataset / 'transitions.jsonl')}))
            report = supplement(dataset, archive)
            self.assertFalse(report['original_instruction_stream_captured'])
            self.assertEqual(sha(archive / 'frames.jsonl'), original)
            self.assertEqual(annotation_summary(archive, '2026-10-03T00:00:00+00:00')['audited_transitions_available_at_cursor'], 0)
            self.assertEqual(annotation_summary(archive, '2026-10-03T02:00:00+00:00')['audited_transitions_available_at_cursor'], 1)
            with self.assertRaises(FileExistsError):
                supplement(dataset, archive)
            proof.write_text('{}')
            self.assertEqual(annotation_summary(archive, '2026-10-03T02:00:00+00:00')['missing_or_changed_evidence'], 1)


if __name__ == '__main__':
    unittest.main()
