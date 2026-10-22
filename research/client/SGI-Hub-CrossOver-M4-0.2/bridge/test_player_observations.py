"""Temp-file tests for pre-selection player-slot observations."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from game_archive import GameArchiveRecorder
from player_observations import MAX_RECORD_BYTES, RESEARCHED_BUILD, PlayerObservationJournal

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def slot(force, nickname, raw):
    return {
        'slot': 0, 'source_metadata': 0, 'state_raw': 2, 'force_id': force,
        'nickname': nickname, 'raw_hex': raw, 'encoding': None, 'status': 'unknown',
        'stability': {'slot': True, 'header': True, 'bytes': True},
        'reason': 'empty_nickname' if nickname is None else None,
    }


def observed(phase='waiting_for_player', fresh=False, nickname='韩立(筑基后期)', raw='baab',
             force=7, pid=1096, created=100, when=NOW, snapshot_id='S1', error=None,
             coherent=True, build=RESEARCHED_BUILD, extra_slots=0, core='0x341020a'):
    slots = [slot(force, nickname, raw)] + [dict(slot(force, None, ''), slot=index + 1) for index in range(extra_slots)]
    state = {
        'snapshot_id': snapshot_id,
        'capture_start': (when - timedelta(milliseconds=20)).isoformat(),
        'capture_end': when.isoformat(),
        'build_sha256': build,
        'core_address': core,
        'identity': {'pid': pid, 'path': r'C:\sgi\run-3.5\3I\SANPK.exe', 'creation_filetime': created},
        'consistency': {'root_headers_and_clock_unchanged': coherent},
        'player_slots': slots,
        'player_slots_layout': {'verified': True, 'build_sha256': build, 'status': 'verified'},
    }
    return {
        'phase': phase, 'fresh': fresh, 'error': error, 'state': state,
        'source_id': 'VKQUANT', 'runtime_id': 'default', 'release_version': '1.1.296',
    }


def lines(root):
    rows = []
    for path in sorted(root.rglob('*.jsonl')):
        text = path.read_text(encoding='utf-8')
        for line in text.splitlines():
            if line:
                rows.append((path, json.loads(line)))
    return rows


class ObservationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.journal = PlayerObservationJournal(self.root / 'player-observations')

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_waiting_snapshot_keeps_raw_bytes_without_confirming_force_or_account(self):
        self.journal.ingest(observed(), NOW)
        saved = lines(self.root)
        self.assertEqual(len(saved), 1)
        row = saved[0][1]
        self.assertEqual(row['kind'], 'player_slot_observation')
        self.assertEqual(row['schema'], 'player-observation-1')
        self.assertTrue(row['attribution_not_final'])
        self.assertFalse(row['stable_account_id_verified'])
        self.assertFalse(row['native_command_captured'])
        self.assertFalse(row['force_selection_confirmed'])
        self.assertFalse(row['capture_session_is_match_id'])
        self.assertNotIn('match_id', row)
        self.assertEqual(row['phase'], 'waiting_for_player')
        self.assertFalse(row['fresh'])
        self.assertEqual(row['player_slots'][0]['raw_hex'], 'baab')
        self.assertEqual(row['player_slots'][0]['status'], 'unknown')
        self.assertEqual(row['player_slots'][0]['source_metadata'], 0)
        self.assertEqual(row['player_slots'][0]['force_id'], 7)
        self.assertEqual(row['target']['pid'], 1096)
        status = self.journal.public_status()
        self.assertNotIn('player_slots', status)
        self.assertNotIn('baab', json.dumps(status))

    def test_force_or_name_change_appends_and_same_content_does_not(self):
        self.journal.ingest(observed(snapshot_id='S1'), NOW)
        later = NOW + timedelta(milliseconds=200)
        self.journal.ingest(observed(snapshot_id='S2', when=later), later)
        self.assertEqual(len(lines(self.root)), 1)
        renamed = observed(snapshot_id='S3', when=later, nickname='另一名', raw='abcd', force=1)
        self.journal.ingest(renamed, later)
        saved = lines(self.root)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[1][1]['player_slots'][0]['nickname'], '另一名')
        self.assertEqual(saved[1][1]['player_slots'][0]['raw_hex'], 'abcd')
        self.assertEqual(saved[1][1]['capture_session_id'], saved[0][1]['capture_session_id'])
        phased = observed(phase='live', fresh=True, snapshot_id='S4', when=later, nickname='另一名', raw='abcd', force=1)
        self.journal.ingest(phased, later)
        self.assertEqual(len(lines(self.root)), 3)
        self.assertEqual(lines(self.root)[2][1]['phase'], 'live')

    def test_error_stale_and_incoherent_gap_once_without_replaying_identity(self):
        self.journal.ingest({'phase': 'waiting_for_player', 'fresh': False, 'state': None}, NOW)
        self.journal.ingest(observed(build='0' * 64), NOW)
        self.assertEqual(lines(self.root), [])
        self.journal.ingest(observed(), NOW)
        bad_time = NOW + timedelta(seconds=1)
        self.journal.ingest(observed(error='read failed', when=bad_time), bad_time)
        self.journal.ingest(observed(error='read failed', snapshot_id='AGAIN', when=bad_time), bad_time)
        saved = lines(self.root)
        self.assertEqual([item['kind'] for _, item in saved], ['player_slot_observation', 'player_observation_gap'])
        self.assertNotIn('player_slots', saved[1][1])
        self.assertNotIn('baab', json.dumps(saved[1][1]))
        recovered = observed(snapshot_id='NEW', when=bad_time, nickname='恢复', raw='9999', force=3)
        self.journal.ingest(recovered, bad_time)
        saved = lines(self.root)
        self.assertEqual(saved[-1][1]['player_slots'][0]['nickname'], '恢复')
        self.assertNotEqual(saved[-1][1]['player_slots'][0]['raw_hex'], 'baab')
        stale = observed(snapshot_id='OLD', when=bad_time - timedelta(seconds=6))
        self.journal.ingest(stale, bad_time)
        self.journal.ingest(dict(stale, snapshot_id='OLD2'), bad_time)
        self.assertEqual([item['kind'] for _, item in lines(self.root)].count('player_observation_gap'), 2)
        self.journal.ingest(observed(snapshot_id='BACK', when=bad_time, nickname='再来', raw='cccc'), bad_time)
        before = len(lines(self.root))
        self.journal.ingest(observed(snapshot_id='BAD', when=bad_time, coherent=False), bad_time)
        self.journal.ingest(observed(snapshot_id='BAD2', when=bad_time, coherent=False), bad_time)
        self.journal.ingest(observed(extra_slots=8, when=bad_time), bad_time)
        saved = lines(self.root)
        self.assertEqual(len(saved), before + 1)
        self.assertEqual(saved[-1][1]['kind'], 'player_observation_gap')
        self.assertEqual(saved[-1][1]['reason'], 'incoherent')
        self.assertNotIn('player_slots', saved[-1][1])
        self.assertTrue(all(len(item['player_slots']) <= 8 for _, item in saved if item['kind'] == 'player_slot_observation'))

    def test_binding_change_starts_a_new_file_and_segment_does_not_overwrite(self):
        small = PlayerObservationJournal(self.root / 'segments', max_segment_bytes=200)
        try:
            small.ingest(observed(raw='aa' * 80), NOW)
            first = next((self.root / 'segments').rglob('*.jsonl'))
            original = first.read_bytes()
            small.ingest(observed(raw='bb' * 80, snapshot_id='S2'), NOW)
            files = list((self.root / 'segments').rglob('*.jsonl'))
            self.assertGreaterEqual(len(files), 2)
            self.assertEqual(first.read_bytes(), original)
            small.ingest(observed(pid=2000, created=9, snapshot_id='OTHER'), NOW)
            sessions = {item['capture_session_id'] for _, item in lines(self.root / 'segments') if item['kind'] == 'player_slot_observation'}
            self.assertEqual(len(sessions), 2)
            self.assertEqual(first.read_bytes(), original)
        finally:
            small.close()

    def test_write_error_is_status_not_an_exception(self):
        blocked = self.root / 'blocked'
        blocked.write_text('not a directory', encoding='utf-8')
        journal = PlayerObservationJournal(blocked)
        try:
            journal.ingest(observed(), NOW)
            status = journal.public_status()
            self.assertTrue(status['write_error'])
            self.assertNotIn('player_slots', status)
            self.assertEqual(journal.ingest(observed(error='x'), NOW), None)
        finally:
            journal.close()

    def test_prestart_does_not_open_the_normal_archive(self):
        archive = GameArchiveRecorder(root=self.root / 'archives', keep_min_frames=1)
        try:
            payload = observed()
            archive.ingest(payload)
            self.journal.ingest(payload, NOW)
            self.assertFalse(archive.session_open)
            self.assertEqual(len(lines(self.root / 'player-observations')), 1)
            self.assertEqual(list((self.root / 'archives').rglob('frames.jsonl')), [])
        finally:
            archive.close('test')
        bridge = Path(__file__).resolve().parent / 'windows_bridge.py'
        text = bridge.read_text(encoding='utf-8')
        self.assertIn('recorder.ingest(observed)', text)
        self.assertIn('observations.ingest(observed)', text)
        self.assertIn('player_observations=observations.public_status()', text)
        self.assertNotIn("pop('player_observations'", text)

    def test_prestart_lobby_nickname_kept_when_core_names_are_empty(self):
        def pack(nickname, raw, snapshot_id, when, core_verified):
            payload = observed(nickname=None, raw='', snapshot_id=snapshot_id, when=when)
            payload['state']['player_slots'] = [dict(slot(None, None, ''), slot=index) for index in range(8)]
            payload['state']['player_slots_layout'] = {
                'verified': core_verified,
                'build_sha256': RESEARCHED_BUILD,
                'status': 'verified' if core_verified else 'unknown',
            }
            payload['state']['lobby_player_slots'] = [slot(None, nickname, raw)]
            payload['state']['lobby_player_slots_layout'] = {
                'verified': True, 'build_sha256': RESEARCHED_BUILD, 'status': 'verified',
            }
            return payload

        self.journal.ingest(pack('韩立(筑基后期)', 'baabc1a228d6febbf9baf3c6da29', 'S1', NOW, False), NOW)
        later = NOW + timedelta(milliseconds=200)
        renamed = pack('韩立改名', 'ffff', 'S2', later, False)
        self.journal.ingest(renamed, later)
        self.journal.ingest(renamed, later)
        saved = lines(self.root)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0][1]['lobby_player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertEqual(saved[0][1]['lobby_player_slots'][0]['raw_hex'], 'baabc1a228d6febbf9baf3c6da29')
        self.assertFalse(saved[0][1]['player_slots_layout']['verified'])
        self.assertEqual(saved[0][1]['player_slots_layout']['status'], 'unknown')
        self.assertTrue(all(item.get('nickname') is None for item in saved[0][1]['player_slots']))
        self.assertEqual(saved[1][1]['lobby_player_slots'][0]['nickname'], '韩立改名')
        self.assertEqual(saved[1][1]['lobby_player_slots'][0]['raw_hex'], 'ffff')
        self.assertEqual(saved[0][1]['capture_session_id'], saved[1][1]['capture_session_id'])
        self.assertFalse(saved[1][1]['capture_session_is_match_id'])
        self.assertNotIn('match_id', saved[1][1])
        self.assertNotIn('baabc1a2', json.dumps(self.journal.public_status()))

    def test_same_content_after_gap_writes_a_recovery_row(self):
        self.journal.ingest(observed(snapshot_id='S1'), NOW)
        bad = NOW + timedelta(seconds=1)
        self.journal.ingest(observed(error='read failed', when=bad), bad)
        self.assertTrue(self.journal.public_status()['gapped'])
        self.journal.ingest(observed(snapshot_id='S2', when=bad), bad)
        saved = lines(self.root)
        observations = [item for _, item in saved if item['kind'] == 'player_slot_observation']
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[1]['snapshot_id'], 'S2')
        self.assertEqual(observations[1]['capture_end'], bad.isoformat())
        self.assertEqual(observations[1]['capture_start'], (bad - timedelta(milliseconds=20)).isoformat())
        self.assertEqual(observations[1]['player_slots'][0]['raw_hex'], 'baab')
        self.assertFalse(self.journal.public_status()['gapped'])
        self.assertEqual(self.journal.public_status()['last_kind'], 'player_slot_observation')
        self.journal.ingest(observed(snapshot_id='S3', when=bad), bad)
        self.assertEqual(len(lines(self.root)), len(saved))

    def test_core_change_starts_a_new_session_and_does_not_overwrite(self):
        self.journal.ingest(observed(core='0x341020a'), NOW)
        first = next(self.root.rglob('*.jsonl'))
        original = first.read_bytes()
        self.journal.ingest(observed(core='0x3410300', snapshot_id='CORE'), NOW)
        saved = [item for _, item in lines(self.root) if item['kind'] == 'player_slot_observation']
        self.assertEqual(len(saved), 2)
        self.assertNotEqual(saved[0]['capture_session_id'], saved[1]['capture_session_id'])
        self.assertEqual(saved[1]['core_address'], '0x3410300')
        self.assertFalse(saved[1]['capture_session_is_match_id'])
        self.assertNotIn('match_id', saved[1])
        files = list(self.root.rglob('*.jsonl'))
        self.assertGreaterEqual(len(files), 2)
        self.assertEqual(first.read_bytes(), original)

    def test_invalid_binding_fails_closed(self):
        for pid in (True, '1096', 1.5, 0, -3):
            self.journal.ingest(observed(pid=pid), NOW)
        for created in (True, '100', 2.0, 0, -1):
            self.journal.ingest(observed(created=created), NOW)
        for core in ('341020a', 'nope', '0x10', '0xffff', '0x80000000', '', None, True, 0x341020a):
            self.journal.ingest(observed(core=core), NOW)
        self.assertEqual(lines(self.root), [])
        self.journal.ingest(observed(core='0x341020a'), NOW)
        self.journal.ingest(observed(pid=True, snapshot_id='BAD'), NOW)
        self.journal.ingest(observed(created=1.5, snapshot_id='BAD2'), NOW)
        self.journal.ingest(observed(snapshot_id='BACK'), NOW)
        self.journal.ingest(observed(core='0x10', snapshot_id='LOW'), NOW)
        self.journal.ingest(observed(core='0x80000000', snapshot_id='HIGH'), NOW)
        saved = lines(self.root)
        self.assertEqual(
            [item['kind'] for _, item in saved],
            ['player_slot_observation', 'player_observation_gap', 'player_slot_observation', 'player_observation_gap'])
        self.assertEqual([item['reason'] for _, item in saved if item['kind'] == 'player_observation_gap'], ['binding', 'core'])
        self.assertTrue(all('player_slots' not in item for _, item in saved if item['kind'] == 'player_observation_gap'))
        self.assertTrue(all(item['core_address'] == '0x341020a' for _, item in saved if item['kind'] == 'player_slot_observation'))

    def test_oversize_record_reports_error_and_gap(self):
        self.journal.ingest(observed(), NOW)
        huge = observed(snapshot_id='HUGE')
        huge['state']['player_slots'][0]['raw_hex'] = 'ab' * MAX_RECORD_BYTES
        self.journal.ingest(huge, NOW)
        self.journal.ingest(huge, NOW)
        saved = lines(self.root)
        self.assertEqual([item['kind'] for _, item in saved], ['player_slot_observation', 'player_observation_gap'])
        self.assertEqual(saved[-1][1]['reason'], 'too_large')
        self.assertNotIn('player_slots', saved[-1][1])
        status = self.journal.public_status()
        self.assertIn('65536', status['write_error'])
        self.assertTrue(status['gapped'])
        self.assertNotIn('player_slots', status)
        for path in self.root.rglob('*.jsonl'):
            self.assertLessEqual(path.stat().st_size, 4 * 1024 * 1024)
            for line in path.read_bytes().splitlines():
                self.assertLessEqual(len(line) + 1, MAX_RECORD_BYTES)

    def test_malformed_slot_source_is_not_guessed(self):
        broken = (
            [slot(7, '韩立', 'aa'), 'not-a-dict'],
            [slot(7, 'a', 'aa'), dict(slot(7, 'b', 'bb'), slot=0)],
            [dict(slot(7, 'a', 'aa'), slot=8)],
            [dict(slot(7, 'a', 'aa'), slot=True)],
            [dict(slot(7, 'a', 'aa'), slot=1.5)],
        )
        for slots in broken:
            payload = observed()
            payload['state']['player_slots'] = slots
            self.journal.ingest(payload, NOW)
        self.journal.ingest(observed(extra_slots=8), NOW)
        self.assertEqual(lines(self.root), [])
        mixed = observed(nickname=None, raw='')
        mixed['state']['player_slots'] = ['raw-row', dict(slot(None, None, ''), slot=9)]
        mixed['state']['lobby_player_slots'] = [dict(slot(None, '韩立(筑基后期)', 'baab'), slot=3, status='unknown')]
        mixed['state']['lobby_player_slots_layout'] = {
            'verified': True, 'build_sha256': RESEARCHED_BUILD, 'status': 'verified',
        }
        self.journal.ingest(mixed, NOW)
        saved = lines(self.root)
        self.assertEqual(len(saved), 1)
        row = saved[0][1]
        self.assertEqual(row['player_slots'], ['raw-row', dict(slot(None, None, ''), slot=9)])
        self.assertEqual(row['lobby_player_slots'][0]['nickname'], '韩立(筑基后期)')
        self.assertEqual(row['lobby_player_slots'][0]['slot'], 3)
        self.assertEqual(row['lobby_player_slots'][0]['status'], 'unknown')
        self.assertEqual(len(row['lobby_player_slots']), 1)


if __name__ == '__main__':
    unittest.main()
