import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from game_archive import (
    ArchiveReader, GameArchiveRecorder, apply_delta, build_demo_state,
    compact_state, compute_delta, default_archive_root, gameplay_fingerprint,
    list_archives, normalize_state, payload_from_state, rebuild_index, refresh_index,
    wait_recorder, write_demo_archive, write_packed_archive,
)
from match_opening import purge_unkept_archives
from replay_view import (
    ReplayCursor, classify_op, event_index, filter_forces, force_command_ledger,
    history_upto, interpolate_units, is_replay_command, track_upto,
    unit_generation_tracks,
)

APP = Path(__file__).resolve().parent.parent / 'app'
if str(APP) not in sys.path:
    sys.path.append(str(APP))


def live(state, **extra):
    return payload_from_state(state, **extra)


def make_3v3_state(seq=0, **kwargs):
    state = build_demo_state(seq, **kwargs)
    names = ('齐', '义渠', '汉', '周', '蜀', '巴')
    lords = []
    for index, name in enumerate(names):
        rels = [0] * 22
        bloc = range(3) if index < 3 else range(3, 6)
        for other in bloc:
            if other != index:
                rels[other] = 3
        lords.append({
            'force_id': index, 'name': name, 'gold': 10000 + seq, 'rice': 20000,
            'prestige': 50, 'diplomacy_relations': rels,
        })
    state['entities']['lords'] = lords
    return state


def make_1v1_state(seq=0, **kwargs):
    state = build_demo_state(seq, **kwargs)
    state['entities']['lords'] = [
        {'force_id': 17, 'name': '韩', 'gold': 10000 + seq, 'rice': 20000, 'prestige': 50,
         'diplomacy_relations': [0] * 22},
        {'force_id': 7, 'name': '蜀', 'gold': 10000 + seq, 'rice': 20000, 'prestige': 50,
         'diplomacy_relations': [0] * 22},
    ]
    return state


def make_computer_state(seq=0, **kwargs):
    state = build_demo_state(seq, **kwargs)
    state['entities']['lords'] = [
        {'force_id': i, 'name': f'国{i}', 'gold': 1000, 'rice': 1000, 'prestige': 1,
         'diplomacy_relations': [0] * 22}
        for i in range(8)
    ]
    return state


class ArchiveFormatTests(unittest.TestCase):
    def test_delta_roundtrip_matches_full_state(self):
        a = compact_state(build_demo_state(0, move=0))
        b = compact_state(build_demo_state(1, move=2))
        b['entities']['lords'][0]['gold'] = 11111
        restored = apply_delta(a, compute_delta(a, b))
        self.assertEqual(restored['entities']['field_units'][0]['world_xy_raw'], [52, 101])
        self.assertEqual(restored['entities']['lords'][0]['gold'], 11111)
        self.assertEqual(restored['snapshot_id'], b['snapshot_id'])
        self.assertEqual(normalize_state(restored), normalize_state(b))

    def test_gameplay_fingerprint_ignores_snapshot_stamp(self):
        a = build_demo_state(0)
        b = build_demo_state(0)
        b['snapshot_id'] = 'OTHER-STAMP'
        b['capture_end'] = '2026-09-16T00:05:00+00:00'
        self.assertEqual(gameplay_fingerprint(a), gameplay_fingerprint(b))
        self.assertNotEqual(gameplay_fingerprint(a), gameplay_fingerprint(build_demo_state(1)))

    def test_packed_archive_random_seek_matches_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            states = [build_demo_state(i, season=1 if i < 5 else 2, move=i) for i in range(12)]
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=3)
            with ArchiveReader(path) as reader:
                sequential = reader.load_all_states()
                for seq in (1, 4, 7, 12, 3, 12, 1):
                    self.assertEqual(reader.load_frame(seq), sequential[seq - 1])
                self.assertEqual(reader.frame_count(), 12)
                self.assertGreaterEqual(len(reader.index['quarters']), 2)


class RecorderLifecycleTests(unittest.TestCase):
    def _rec(self, tmp):
        return GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', keep_formats=None)

    def test_auto_open_and_hubless_two_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.saw_pre_live = True
                first = [build_demo_state(i, filetime=1, pid=10) for i in range(4)]
                for state in first:
                    rec.ingest(live(state))
                wait_recorder(rec)
                first_dir = rec.public_status()['directory']
                first_id = rec.public_status()['match_id']
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
                second = [build_demo_state(i, filetime=2, pid=11, year=201) for i in range(3)]
                for state in second:
                    rec.ingest(live(state))
                wait_recorder(rec)
                second_dir = rec.public_status()['directory']
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
            finally:
                rec.close()
            self.assertNotEqual(first_dir, second_dir)
            self.assertNotEqual(first_id, rec.public_status().get('match_id'))
            a = json.loads((Path(first_dir) / 'manifest.json').read_text(encoding='utf8'))
            b = json.loads((Path(second_dir) / 'manifest.json').read_text(encoding='utf8'))
            self.assertFalse(a['open'])
            self.assertFalse(b['open'])
            self.assertEqual(a['frame_count'], 4)
            self.assertEqual(b['frame_count'], 3)
            self.assertEqual(a['end_reason'], 'process_gone')
            with ArchiveReader(first_dir) as reader:
                self.assertEqual(reader.load_frame(1)['snapshot_id'], first[0]['snapshot_id'])
                self.assertEqual(reader.load_frame(4)['snapshot_id'], first[3]['snapshot_id'])

    def test_same_process_clock_rollback_splits_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.saw_pre_live = True
                for i in range(3):
                    rec.ingest(live(build_demo_state(i, year=202, season=3, filetime=9, pid=8)))
                wait_recorder(rec)
                old = rec.public_status()['directory']
                nxt = build_demo_state(0, year=200, season=0, filetime=9, pid=8)
                nxt['capture_end'] = '2026-09-16T04:00:00+00:00'
                rec.ingest(live(nxt))
                wait_recorder(rec)
                new = rec.public_status()['directory']
            finally:
                rec.close()
            self.assertNotEqual(old, new)
            old_m = json.loads((Path(old) / 'manifest.json').read_text(encoding='utf8'))
            new_m = json.loads((Path(new) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(old_m['end_reason'], 'new_match_same_process')
            self.assertEqual(old_m['frame_count'], 3)
            self.assertEqual(new_m['frame_count'], 1)
            self.assertTrue((Path(old) / 'frames.jsonl').is_file())

    def test_pid_reuse_uses_creation_filetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.ingest(live(build_demo_state(0, pid=5, filetime=100)))
                wait_recorder(rec)
                first = rec.public_status()['directory']
                rec.ingest(live(build_demo_state(1, pid=5, filetime=200, year=201)))
                wait_recorder(rec)
                second = rec.public_status()['directory']
            finally:
                rec.close()
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads((Path(first) / 'manifest.json').read_text(encoding='utf8'))['frame_count'], 1)

    def test_duplicate_and_out_of_order_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                a = build_demo_state(1)
                b = build_demo_state(2)
                rec.ingest(live(a))
                rec.ingest(live(a))
                rec.ingest(live(b))
                older = build_demo_state(0)
                older['capture_end'] = '2026-09-16T00:00:00+00:00'
                rec.ingest(live(older))
                wait_recorder(rec)
                directory = rec.public_status()['directory']
            finally:
                rec.close()
            with ArchiveReader(directory) as reader:
                self.assertEqual(reader.frame_count(), 2)
                self.assertEqual(reader.load_frame(1)['snapshot_id'], a['snapshot_id'])
                self.assertEqual(reader.load_frame(2)['snapshot_id'], b['snapshot_id'])

    def test_transient_gap_does_not_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.ingest(live(build_demo_state(0)))
                wait_recorder(rec)
                directory = rec.public_status()['directory']
                rec.ingest(live(None, phase='recovering', error_class='transient_inconsistent'))
                rec.ingest(live(None, phase='recovering', error_class='transient_inconsistent'))
                rec.ingest(live(build_demo_state(1)))
                wait_recorder(rec)
            finally:
                rec.close()
            manifest = json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['end_reason'], 'collector_stop')
            with ArchiveReader(directory) as reader:
                self.assertEqual(reader.frame_count(), 2)
                self.assertTrue(reader.index['gaps'])

    def test_viewer_disconnect_is_not_a_signal(self):
        src = Path(__file__).with_name('game_archive.py').read_text(encoding='utf8')
        self.assertNotIn('urllib.request', src)
        self.assertNotIn('127.0.0.1:8769', src)
        self.assertNotIn('api/state', src)

    def test_mid_start_is_labeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.saw_pre_live = False
                rec.ingest(live(build_demo_state(0, year=202, season=3)))
                wait_recorder(rec)
                directory = rec.public_status()['directory']
            finally:
                rec.close()
            manifest = json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf8'))
            self.assertTrue(manifest['started_mid_match'])
            self.assertEqual(manifest['first_frame_note'], '从此处开始记录')

    def test_sealed_archive_not_overwritten_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            try:
                rec.ingest(live(build_demo_state(0, filetime=1)))
                wait_recorder(rec)
                first = rec.public_status()['directory']
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
                rec.ingest(live(build_demo_state(0, filetime=1, year=201)))
                wait_recorder(rec)
            finally:
                rec.close()
            self.assertEqual(json.loads((Path(first) / 'manifest.json').read_text(encoding='utf8'))['frame_count'], 1)
            self.assertGreaterEqual(len(list_archives(tmp)), 2)

    def test_idle_timeout_seals_unchanged_board(self):
        class Clock:
            def __init__(self):
                self.value = '2026-09-16T00:00:00+00:00'

            def __call__(self):
                return self.value

        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
                clock=clock,
                idle_seal_s=300,
                keep_formats=None,
            )
            try:
                rec.saw_pre_live = True
                first = build_demo_state(0, season=0, filetime=3, pid=33)
                rec.ingest(live(first))
                wait_recorder(rec)
                directory = rec.public_status()['directory']
                almost = build_demo_state(0, season=0, filetime=3, pid=33)
                almost['snapshot_id'] = 'IDLE-299'
                almost['capture_end'] = '2026-09-16T00:04:59+00:00'
                clock.value = '2026-09-16T00:04:59+00:00'
                rec.ingest(live(almost))
                wait_recorder(rec)
                self.assertTrue(rec.public_status()['open'])
                frozen = build_demo_state(0, season=0, filetime=3, pid=33)
                frozen['snapshot_id'] = 'IDLE-300'
                frozen['capture_end'] = '2026-09-16T00:05:00+00:00'
                clock.value = '2026-09-16T00:05:00+00:00'
                rec.ingest(live(frozen))
                wait_recorder(rec)
                self.assertFalse(rec.public_status()['open'])
                still = build_demo_state(0, season=0, filetime=3, pid=33)
                still['snapshot_id'] = 'IDLE-301'
                rec.ingest(live(still))
                wait_recorder(rec)
                self.assertFalse(rec.public_status()['open'])
                nxt = build_demo_state(1, season=0, filetime=3, pid=33)
                rec.ingest(live(nxt))
                wait_recorder(rec)
                self.assertTrue(rec.public_status()['open'])
                second = rec.public_status()['directory']
            finally:
                rec.close()
            manifest = json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['end_reason'], 'idle_timeout')
            self.assertEqual(manifest['completeness'], 'complete')
            self.assertGreaterEqual(manifest['frame_count'], 2)
            self.assertNotEqual(directory, second)

    def test_idle_timeout_on_duplicate_snapshot_and_writer_tick(self):
        class Clock:
            def __init__(self):
                self.value = '2026-09-16T00:00:00+00:00'

            def __call__(self):
                return self.value

        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
                clock=clock,
                idle_seal_s=300,
                keep_formats=None,
            )
            try:
                rec.saw_pre_live = True
                state = build_demo_state(0, season=0, filetime=4, pid=44)
                rec.ingest(live(state))
                wait_recorder(rec)
                directory = rec.public_status()['directory']
                rec.ingest(live(state))
                wait_recorder(rec)
                self.assertTrue(rec.public_status()['open'])
                clock.value = '2026-09-16T00:05:00+00:00'
                rec.ingest(live(state))
                wait_recorder(rec)
                self.assertFalse(rec.public_status()['open'])
                rec.ingest(live(build_demo_state(0, season=0, filetime=5, pid=55)))
                wait_recorder(rec)
                self.assertTrue(rec.public_status()['open'])
                later = rec.public_status()['directory']
                clock.value = '2026-09-16T00:10:01+00:00'
                time.sleep(0.35)
                wait_recorder(rec)
                self.assertFalse(rec.public_status()['open'])
            finally:
                rec.close()
            first = json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf8'))
            second = json.loads((Path(later) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(first['end_reason'], 'idle_timeout')
            self.assertEqual(second['end_reason'], 'idle_timeout')
            self.assertEqual(first['frame_count'], 1)

    def test_default_keep_player_1v1_2v2_3v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
            )
            try:
                rec.saw_pre_live = True
                rec.ingest(live(make_computer_state(0, season=0, pid=1, filetime=1)))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
                self.assertEqual(list_archives(tmp), [])
                rec.ingest(live(make_3v3_state(0, season=0, pid=2, filetime=2)))
                rec.ingest(live(make_3v3_state(1, season=0, pid=2, filetime=2)))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
            finally:
                rec.close()
            rows = list_archives(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['format'], '3v3')
            self.assertIn('玩家局 3v3', rows[0]['title'])
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
            )
            try:
                rec.saw_pre_live = True
                rec.ingest(live(make_1v1_state(0, season=0, pid=3, filetime=3)))
                rec.ingest(live(make_1v1_state(1, season=0, pid=3, filetime=3)))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
            finally:
                rec.close()
            rows = list_archives(tmp)
            self.assertEqual({row['format'] for row in rows}, {'1v1', '3v3'})
            removed = purge_unkept_archives(tmp, min_frames=0)
            self.assertEqual(removed, [])
            self.assertEqual(len(list_archives(tmp)), 2)

    def test_computer_match_never_creates_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
            )
            try:
                rec.saw_pre_live = True
                for seq in range(85):
                    rec.ingest(live(make_computer_state(seq, season=0, pid=11, filetime=11)))
                wait_recorder(rec)
            finally:
                rec.close()
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(list_archives(tmp), [])

    def test_player_match_starts_after_computer_prelude(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
            )
            try:
                rec.saw_pre_live = True
                for seq in range(12):
                    rec.ingest(live(make_computer_state(seq, season=0, pid=12, filetime=12)))
                rec.ingest(live(make_3v3_state(12, season=0, pid=12, filetime=12)))
                rec.ingest(live(make_3v3_state(13, season=0, pid=12, filetime=12)))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
            finally:
                rec.close()
            rows = list_archives(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['format'], '3v3')
            self.assertEqual(rows[0]['frame_count'], 2)

    def test_short_player_match_discarded_when_min_frames_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
                keep_min_frames=5,
            )
            try:
                rec.saw_pre_live = True
                rec.ingest(live(make_1v1_state(0, season=0, pid=9, filetime=9)))
                rec.ingest(live(make_1v1_state(1, season=0, pid=9, filetime=9)))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
                self.assertEqual(rec.public_status().get('end_reason'), 'too_short')
            finally:
                rec.close()
            self.assertEqual(list_archives(tmp), [])

    def test_1v1_keeps_archive_after_defection_third_lord(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp),
                app_dir=Path(__file__).resolve().parent.parent / 'app',
                keep_min_frames=5,
            )
            try:
                rec.saw_pre_live = True
                for seq in range(4):
                    rec.ingest(live(make_1v1_state(seq, season=0, pid=21, filetime=21)))
                for seq in range(4, 12):
                    state = make_1v1_state(seq, season=0, pid=21, filetime=21)
                    state['entities']['lords'].append({
                        'force_id': 0, 'name': '孙叔敖', 'gold': 3000, 'rice': 3000, 'prestige': 1,
                        'diplomacy_relations': [0] * 22,
                    })
                    rec.ingest(live(state))
                rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
                wait_recorder(rec)
            finally:
                rec.close()
            rows = list_archives(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['format'], '1v1')
            self.assertIn('玩家局 1v1', rows[0]['title'])
            self.assertGreaterEqual(rows[0]['frame_count'], 5)
            self.assertNotEqual(rows[0].get('end_reason'), 'not_kept_format')


class RecoveryTests(unittest.TestCase):
    def test_truncated_tail_keeps_complete_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(
                Path(tmp) / 'm',
                [build_demo_state(i) for i in range(5)],
                keyframe_every=2,
            )
            with (path / 'frames.jsonl').open('ab') as handle:
                handle.write(b'{"z":true,"payload":"deadbeef')
            index = rebuild_index(path)
            self.assertTrue(index['tail_truncated'])
            self.assertEqual(len(index['frames']), 5)
            with ArchiveReader(path) as reader:
                self.assertEqual(reader.load_frame(5)['snapshot_id'], build_demo_state(4)['snapshot_id'])
                self.assertTrue(reader.index.get('tail_truncated'))
            refreshed = refresh_index(path)
            self.assertTrue(refreshed['tail_truncated'])
            self.assertEqual(len(refreshed['frames']), 5)

    def test_refresh_index_reuses_stored_without_full_decode(self):
        import game_archive
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', [build_demo_state(i) for i in range(8)], keyframe_every=3)
            real = game_archive.decode_line
            calls = {'n': 0}

            def wrapped(line):
                calls['n'] += 1
                return real(line)

            game_archive.decode_line = wrapped
            try:
                index = refresh_index(path)
            finally:
                game_archive.decode_line = real
            self.assertEqual(len(index['frames']), 8)
            self.assertLess(calls['n'], 2)

    def test_write_failure_does_not_raise_into_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', keep_formats=None)

            def boom(_path):
                raise OSError('No space left on device')

            rec.fs_check = boom
            rec.ingest(live(build_demo_state(0)))
            wait_recorder(rec, 1.5)
            rec.close()
            self.assertIn('No space left', rec.public_status().get('write_error') or '')
            self.assertEqual(rec.public_status().get('completeness'), 'write_error')

    def test_force_stop_leaves_readable_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', keep_formats=None)
            rec.ingest(live(build_demo_state(0)))
            rec.ingest(live(build_demo_state(1)))
            wait_recorder(rec)
            directory = rec.public_status()['directory']
            rec.close()
            with ArchiveReader(directory) as reader:
                self.assertGreaterEqual(reader.frame_count(), 1)
                reader.load_frame(1)

    def test_queue_overflow_keeps_control_ops(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(
                root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', queue_max=2,
                keep_formats=None,
            )
            rec.apply_gate.clear()
            rec.ingest(live(build_demo_state(0)))
            for i in range(1, 8):
                rec.ingest(live(build_demo_state(i)))
            self.assertGreater(rec.dropped_frames, 0)
            self.assertTrue(rec.public_status().get('overflow'))
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
            self.assertIn('seal', rec.pending_ops())
            rec.apply_gate.set()
            wait_recorder(rec)
            rec.close()
            rows = list_archives(tmp)
            self.assertTrue(rows)
            self.assertEqual(rows[0].get('end_reason'), 'process_gone')


class ReplayAnalysisTests(unittest.TestCase):
    def test_no_future_leak_and_event_targets(self):
        states = [build_demo_state(i, season=1 if i < 4 else 2, move=i) for i in range(8)]
        early = history_upto(states[:4])
        later = history_upto(states)
        self.assertEqual(early['current_quarter']['phase']['season_u16'], 1)
        self.assertTrue(later['quarters'])
        self.assertNotEqual(
            [row.get('label') for row in later['quarters']],
            [row.get('label') for row in early.get('quarters') or []],
        )
        events = event_index(states[:5])
        self.assertTrue(any(row['type'] == '部队坐标' for row in events))
        self.assertTrue(all(row['seq'] <= 5 for row in events))

    def test_light_view_skips_track_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', [build_demo_state(i, move=i) for i in range(6)])
            cursor = ReplayCursor(path)
            try:
                full = cursor.view(6)
                light = cursor.view(6, include_tracks=False, include_history=False, include_events=False)
            finally:
                cursor.close()
            self.assertTrue(full['tracks'])
            self.assertEqual(light['tracks'], {})
            self.assertEqual(light['history']['quarters'], [])
            self.assertEqual(light['events'], [])
            self.assertEqual(light['seq'], 6)

    def test_light_view_skips_ensure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', [build_demo_state(i, move=i) for i in range(8)])
            cursor = ReplayCursor(path)
            try:
                light = cursor.view(8, include_tracks=False, include_history=False, include_events=False)
                self.assertEqual(cursor._ready, 0)
                raw = cursor.frame_state(8, clone=False)
                again = cursor.frame_state(8, clone=False)
            finally:
                cursor.close()
            self.assertEqual(light['seq'], 8)
            self.assertEqual(light['events'], [])
            self.assertIs(raw, again)

    def test_load_frame_clone_false_advances_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            states = [build_demo_state(i, move=i) for i in range(4)]
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=10)
            with ArchiveReader(path) as reader:
                first = reader.load_frame(1, clone=False)
                second = reader.load_frame(2, clone=False)
                self.assertIs(first, second)
                frozen = reader.load_frame(2, clone=True)
                self.assertIsNot(frozen, second)
                frozen['snapshot_id'] = 'mutated'
                self.assertNotEqual(second['snapshot_id'], 'mutated')
                self.assertEqual(reader.load_frame(3, clone=False)['snapshot_id'], states[2]['snapshot_id'])

    def test_unit_id_reuse_not_stitched(self):
        a = build_demo_state(0)
        a['entities']['field_units'] = [
            {'unit_id': 1, 'unit_kind': 'infantry', 'owner_raw': 0, 'world_xy_raw': [10, 10]},
        ]
        b = build_demo_state(1)
        b['entities']['field_units'] = []
        c = build_demo_state(2)
        c['entities']['field_units'] = [
            {'unit_id': 1, 'unit_kind': 'cavalry', 'owner_raw': 1, 'world_xy_raw': [80, 80]},
        ]
        tracks = unit_generation_tracks([a, b, c])
        self.assertEqual(len(tracks), 2)
        live = track_upto(tracks, 3, 1)
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]['generation'], 2)
        self.assertTrue(live[0]['live_at_seq'])
        gone = track_upto(tracks, 2, 1)
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0]['generation'], 1)

    def test_evidence_classes(self):
        self.assertEqual(classify_op({'via': 'pending_hire'}), 'fact')
        self.assertEqual(classify_op({'command': True, 'field': '新建练兵所'}), 'inferred')
        self.assertEqual(classify_op({'field': '金钱', 'before': 1, 'after': 2}), 'observed_change')

    def test_force_command_ledger_keeps_living_forces(self):
        self.assertFalse(is_replay_command({'field': '粮食', 'command': False}))
        a = build_demo_state(0)
        b = build_demo_state(1, move=3)
        b['entities']['production_buildings'] = list(a['entities']['production_buildings']) + [{
            'type': 'horse_farm', 'owner_raw': 0, 'building_ui_amount': 5000,
            'world_xy_raw': [52, 101], 'linked_city_id': 1, 'object_id_candidate': 22,
        }]
        b['entities']['field_units'] = list(b['entities']['field_units']) + [{
            'unit_id': 8, 'unit_kind': 'infantry', 'owner_raw': 1,
            'world_xy_raw': [52, 124], 'soldiers_candidate': 1000,
        }]
        events = event_index([a, b])
        ledger = force_command_ledger(events, b['entities']['lords'])
        self.assertEqual([row['name'] for row in ledger], ['演示魏', '演示吴'])
        wei = next(row for row in ledger if row['name'] == '演示魏')
        wu = next(row for row in ledger if row['name'] == '演示吴')
        wei_fields = [item.get('field') for q in wei['quarters'] for item in q['civil'] + q['military']]
        wu_fields = [item.get('field') for q in wu['quarters'] for item in q['civil'] + q['military']]
        self.assertTrue(any(str(field).startswith('新建') for field in wei_fields), wei_fields)
        self.assertIn('部队移动', wei_fields)
        self.assertIn('出征', wu_fields)
        self.assertNotIn('粮食', wei_fields)
        self.assertTrue(any(q.get('civil') for q in wei['quarters']),
                        [q.get('label') for q in wei['quarters']])
        empty = force_command_ledger([], [{'force_id': 3, 'name': '齐'}, {'force_id': 10, 'name': '周'}])
        self.assertEqual([row['name'] for row in empty], ['齐', '周'])
        self.assertTrue(all(row['command_count'] == 0 for row in empty))
        founding = force_command_ledger([
            {'field': '主动加入', 'via': 'owner_change', 'owner': 3, 'seq': 43,
             'phase': {'year_u16': 200, 'season_u16': 0}, 'line': '加入 华雄：东狼关'},
            {'field': '粮食', 'owner': 3, 'seq': 43, 'phase': {'year_u16': 200, 'season_u16': 0}},
            {'field': '出征', 'command': True, 'owner': 3, 'seq': 166,
             'phase': {'year_u16': 200, 'season_u16': 1}, 'line': '出征 强化骑兵'},
        ], [{'force_id': 3, 'name': '齐'}], opening_seq=43)
        self.assertEqual(founding[0]['command_count'], 1)
        self.assertEqual(founding[0]['quarters'][0]['military'][0]['field'], '出征')
        split = force_command_ledger([
            {'field': '新建练兵所', 'command': True, 'owner': 3, 'seq': 200,
             'phase': {'year_u16': 200, 'season_u16': 0, 'round_u8': 0}, 'line': '新建'},
            {'field': '出征', 'command': True, 'owner': 3, 'seq': 250,
             'phase': {'year_u16': 200, 'season_u16': 0, 'round_u8': 1}, 'line': '出征春'},
            {'field': '出征', 'command': True, 'owner': 3, 'seq': 310,
             'phase': {'year_u16': 200, 'season_u16': 1, 'round_u8': 0}, 'line': '出征 一'},
            {'field': '部队移动', 'command': True, 'owner': 3, 'seq': 400,
             'phase': {'year_u16': 200, 'season_u16': 1, 'round_u8': 1}, 'line': '移动'},
            {'field': '出征', 'command': True, 'owner': 3, 'seq': 450,
             'phase': {'year_u16': 200, 'season_u16': 1, 'round_u8': 2}, 'line': '出征 三'},
        ], [{'force_id': 3, 'name': '齐'}], opening_seq=1, quarters_per_force=0)
        self.assertEqual([q['label'] for q in split[0]['quarters']], ['200年春', '200年夏'])
        self.assertEqual(len(split[0]['quarters'][0]['civil']), 1)
        self.assertEqual(len(split[0]['quarters'][0]['military']), 1)
        self.assertEqual(len(split[0]['quarters'][1]['military']), 3)
        from replay_view import history_command_events
        hist = {'current_quarter': {'phase': {'year_u16': 200, 'season_u16': 1}, 'forces': [
            {'owner': 0, 'name': '演示魏', 'operations': [
                {'field': '新建牧场', 'command': True, 'line': '新建 1 座牧场：许昌'},
            ]},
        ]}}
        self.assertTrue(history_command_events(hist))

    def test_interpolation_is_marked_and_optional(self):
        a = compact_state(build_demo_state(0, move=0))
        b = compact_state(build_demo_state(1, move=4))
        mid = interpolate_units(a, b, 0.5)
        self.assertTrue(mid['visual_interpolation'])
        self.assertTrue(mid['entities']['field_units'][0]['interpolated'])
        self.assertEqual(mid['entities']['field_units'][0]['world_xy_raw'][0], 52.0)

    def test_cursor_shared_and_demo_labeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_demo_archive(Path(tmp) / 'demo')
            cursor = ReplayCursor(path)
            try:
                view = cursor.view(1)
                self.assertTrue(view['simulated'])
                self.assertIn('模拟', json.dumps(cursor.manifest(), ensure_ascii=False))
                cursor.seek(10)
                later = cursor.view()
                self.assertEqual(later['seq'], 10)
                self.assertEqual(later['state']['phase_candidate']['season_u16'], 1)
                self.assertTrue(later['history']['current_quarter'] or later['history']['quarters'])
                cursor.seek(1)
                again = cursor.view()
                self.assertEqual(again['state']['snapshot_id'], view['state']['snapshot_id'])
                self.assertEqual(again['history']['current_quarter']['phase']['season_u16'], 0)
                self.assertFalse(again['history']['quarters'])
                self.assertTrue(all(row.get('seq', 0) <= 1 for row in again['events']))
            finally:
                cursor.close()


class RepairTests(unittest.TestCase):
    def _rec(self, tmp, **kwargs):
        kwargs.setdefault('keep_formats', None)
        return GameArchiveRecorder(
            root=Path(tmp),
            app_dir=Path(__file__).resolve().parent.parent / 'app',
            **kwargs,
        )

    def test_rc01_paused_writer_does_not_mix_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            rec.apply_gate.clear()
            rec.ingest(live(build_demo_state(0, pid=1, filetime=11)))
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
            rec.ingest(live(build_demo_state(0, pid=2, filetime=22)))
            ops = rec.pending_ops()
            self.assertIn('seal', ops)
            self.assertIn('open', ops)
            rec.apply_gate.set()
            wait_recorder(rec)
            rec.close()
            rows = list_archives(tmp)
            self.assertEqual(len(rows), 2)
            pids = {row['process']['pid'] for row in rows}
            self.assertEqual(pids, {1, 2})
            for row in rows:
                self.assertEqual(row['frame_count'], 1)
                with ArchiveReader(row['directory']) as reader:
                    self.assertEqual(reader.frame_count(), 1)
                    self.assertEqual(reader.load_frame(1)['identity']['pid'], row['process']['pid'])

    def test_rc02_source_switch_and_snapshot_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._rec(tmp)
            rec.saw_pre_live = True
            first = build_demo_state(0, pid=9, filetime=90)
            rec.ingest(live(first, source_id='host-a'))
            wait_recorder(rec)
            first_dir = rec.public_status()['directory']
            second = build_demo_state(1, pid=9, filetime=90)
            rec.ingest(live(second, source_id='host-b'))
            wait_recorder(rec)
            second_dir = rec.public_status()['directory']
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
            wait_recorder(rec)
            again = build_demo_state(0, pid=9, filetime=90, year=201)
            rec.ingest(live(again, source_id='host-b'))
            wait_recorder(rec)
            rec.close()
            self.assertNotEqual(first_dir, second_dir)
            a = json.loads((Path(first_dir) / 'manifest.json').read_text(encoding='utf8'))
            b = json.loads((Path(second_dir) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(a['source_id'], 'host-a')
            self.assertEqual(b['source_id'], 'host-b')
            self.assertEqual(a['frame_count'], 1)
            self.assertEqual(b['frame_count'], 1)
            self.assertEqual(a['end_reason'], 'source_or_process_changed')

    def test_rc03_duplicate_ids_and_top_level_fields(self):
        a = compact_state(build_demo_state(0))
        a['coverage'] = {'generals': 2}
        a['capture_start'] = '2026-09-16T01:00:00+00:00'
        a['consistency'] = {'ok': True}
        a['entities']['generals'] = [
            {'general_id_raw': 3, 'name': '演示将', 'owner_raw': 0, 'status_code': 2},
            {'general_id_raw': 9, 'name': '在野甲', 'owner_raw': 65535, 'status_code': 1},
            {'general_id_raw': 3, 'name': 'reserved', 'owner_raw': 0, 'status_code': 0},
        ]
        b = compact_state(build_demo_state(1, move=1))
        b['coverage'] = {'generals': 3}
        b['consistency'] = {'ok': False, 'reason': 'dup'}
        b['entities']['generals'] = [
            {'general_id_raw': 3, 'name': '演示将', 'owner_raw': 0, 'status_code': 2},
            {'general_id_raw': 9, 'name': '在野甲', 'owner_raw': 0, 'status_code': 9},
            {'general_id_raw': 3, 'name': 'reserved', 'owner_raw': 0, 'status_code': 0},
        ]
        restored = apply_delta(a, compute_delta(a, b))
        self.assertEqual(
            [row['name'] for row in restored['entities']['generals']],
            ['演示将', '在野甲', 'reserved'],
        )
        self.assertEqual(restored['coverage'], {'generals': 3})
        self.assertNotIn('capture_start', restored)
        self.assertEqual(normalize_state(restored), normalize_state(b))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'dup', [a, b], keyframe_every=2)
            with ArchiveReader(path) as reader:
                self.assertEqual(normalize_state(reader.load_frame(1)), normalize_state(a))
                self.assertEqual(normalize_state(reader.load_frame(2)), normalize_state(b))

    def test_rc04_build_then_remove_stays_in_ledger(self):
        a = build_demo_state(0)
        b = build_demo_state(1)
        b['entities']['production_buildings'] = list(a['entities']['production_buildings']) + [{
            'type': 'horse_farm', 'owner_raw': 0, 'building_ui_amount': 5000,
            'world_xy_raw': [52, 101], 'linked_city_id': 1, 'object_id_candidate': 22,
        }]
        c = build_demo_state(2)
        ledger = history_upto([a, b, c])
        ops = [item for force in (ledger['current_quarter'] or {}).get('forces') or []
               for item in force.get('operations') or []]
        text = ' '.join(str(item.get('line') or item.get('field') or '') for item in ops)
        self.assertTrue(any('牧场' in str(item.get('line') or item.get('field') or '') and
                            ('新增' in str(item.get('note') or item.get('line') or '') or
                             '新建' in str(item.get('field') or item.get('line') or ''))
                            for item in ops), text)
        self.assertTrue(any('牧场' in str(item.get('line') or item.get('field') or '') and
                            ('消失' in str(item.get('note') or item.get('line') or '') or
                             '拆除' in str(item.get('note') or '') or
                             item.get('after') in (None, '无'))
                            for item in ops), text)
        build_ev = next(item for item in ops if '新建' in str(item.get('field') or item.get('line') or '')
                        or '新增' in str(item.get('note') or ''))
        self.assertEqual(build_ev.get('seq'), 2)
        self.assertTrue(build_ev.get('target'))

    def test_rc05_interpolation_keeps_current_facts(self):
        before = compact_state(build_demo_state(0, move=0))
        after = compact_state(build_demo_state(1, move=4))
        after['entities']['field_units'][0]['soldiers_candidate'] = 999
        after['entities']['field_units'].append({
            'unit_id': 99, 'unit_kind': 'infantry', 'owner_raw': 1,
            'soldiers_candidate': 500, 'world_xy_raw': [80, 80],
        })
        after['entities']['lords'][0]['gold'] = 1
        mid = interpolate_units(before, after, 0.35)
        unit = mid['entities']['field_units'][0]
        self.assertEqual(unit['soldiers_candidate'], 2400)
        self.assertEqual(unit['owner_raw'], 0)
        self.assertEqual(len(mid['entities']['field_units']), 1)
        self.assertEqual(mid['entities']['lords'][0]['gold'], before['entities']['lords'][0]['gold'])
        self.assertNotEqual(unit['world_xy_raw'][0], 50)
        self.assertLess(unit['world_xy_raw'][0], 54)
        filtered = filter_forces(mid, {0})
        self.assertTrue(all(row.get('owner_raw') == 0 or row.get('force_id') == 0
                            for row in filtered['entities']['field_units']))
        self.assertFalse(any(row.get('unit_id') == 99 for row in filtered['entities']['field_units']))

    def test_rc05_cursor_force_filter_and_no_future_ops(self):
        states = [build_demo_state(i, season=1 if i < 3 else 2, move=i) for i in range(6)]
        states[4]['entities']['production_buildings'].append({
            'type': 'horse_farm', 'owner_raw': 0, 'building_ui_amount': 1,
            'world_xy_raw': [53, 101], 'linked_city_id': 1, 'object_id_candidate': 33,
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=2)
            cursor = ReplayCursor(path)
            try:
                later = cursor.view(6)
                early = cursor.view(2)
                self.assertTrue(any('牧场' in str(item.get('line') or item.get('field') or '')
                                    for item in later['events']))
                self.assertFalse(any('牧场' in str(item.get('line') or item.get('field') or '')
                                     for item in early['events']))
                self.assertEqual(early['history']['current_quarter']['phase']['season_u16'], 1)
                filtered = cursor.view(6, force_ids=[1])
                self.assertTrue(all(row.get('force_id') == 1 for row in filtered['state']['entities']['lords']))
            finally:
                cursor.close()

    def test_rc06_replay_cursor_view_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = 2400
            states = [build_demo_state(i % 50, season=1 + (i // 800), move=i % 20) for i in range(n)]
            path = write_packed_archive(Path(tmp) / 'long', states, keyframe_every=30)
            cursor = ReplayCursor(path)
            try:
                t0 = time.perf_counter()
                last = cursor.view(n)
                first_view_s = time.perf_counter() - t0
                t1 = time.perf_counter()
                near = cursor.view(n - 1)
                hot_s = time.perf_counter() - t1
                t2 = time.perf_counter()
                first = cursor.view(1)
                back_s = time.perf_counter() - t2
                t3 = time.perf_counter()
                for seq in range(2, 52):
                    cursor.view(seq)
                play_s = time.perf_counter() - t3
            finally:
                cursor.close()
            try:
                import resource
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            except Exception:
                rss = None
            size = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
            report = {
                'frames': n,
                'bytes': size,
                'bytes_per_hour_at_1hz': int(size * (3600 / n)),
                'first_view_last_frame_seconds': round(first_view_s, 4),
                'hot_view_prev_frame_seconds': round(hot_s, 4),
                'seek_back_to_first_seconds': round(back_s, 4),
                'play_50_frames_seconds': round(play_s, 4),
                'max_rss': rss,
                'note': 'ReplayCursor.view on compact demo entities; not a 923-general live capture',
            }
            out = Path(__file__).resolve().parent.parent / 'logs'
            out.mkdir(exist_ok=True)
            (out / 'replay-perf.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            self.assertEqual(last['seq'], n)
            self.assertEqual(near['seq'], n - 1)
            self.assertEqual(first['seq'], 1)
            self.assertLess(first_view_s, 5.0)
            self.assertLess(hot_s, 0.35)
            self.assertLess(back_s, 0.35)
            self.assertLess(play_s, 1.5)
            self.assertLess(size, 8 * 1024 * 1024)

    def test_bind_clickable_applies_unique_tag(self):
        import tkinter as tk
        from panorama_replay import bind_clickable
        root = tk.Tk()
        root.withdraw()
        try:
            text = tk.Text(root)
            tag = bind_clickable(text, '跳到事件\n', 'observed_change', lambda: None)
            self.assertTrue(tag.startswith('hit-'))
            self.assertIn(tag, text.tag_names('1.0'))
            binds = str(text.tk.call(text._w, 'tag', 'bind', tag))
            self.assertIn('Button-1', binds)
            replay = Path(__file__).resolve().parent.parent.joinpath('app', 'panorama_replay.py').read_text(encoding='utf8')
            self.assertIn("self._seek(item['seq'])", replay)
            self.assertIn('clamp_replay_seq', replay)
            self.assertIn('_draw_tracks', replay)
            self.assertIn('bind_clickable', replay)
            self.assertNotIn("tag_bind(ev + str(start)", replay)
            self.assertNotIn('打开演示', replay)
            self.assertNotIn("self.archives.insert(0, row)", replay)
            self.assertIn('listed_archive(row)', replay)
            self.assertIn('self._ignore_pick', replay)
            self.assertIn('self._ignore_scrub', replay)
            self.assertIn('include_tracks', replay)
            self.assertIn('lists=heavy', replay)
            self.assertIn('force_command_ledger', replay)
            self.assertIn('OPS_RAW_TITLE', replay)
            self.assertIn('OPS_INFER_TITLE', replay)
            self.assertIn('_refresh_ops', replay)
            self.assertIn('set_force_commands', replay)
            self.assertIn('_step_quarter', replay)
            self.assertIn('bracketleft', replay)
            self.assertIn('include_events', replay)
            self.assertIn('_render_light', replay)
            self.assertIn('_schedule_catchup', replay)
            self.assertIn('clone=False', replay)
            self.assertIn('_catchup_ops', replay)
            self.assertIn('_sync_jumps', replay)
            self.assertIn('calendar_label', replay)
            self.assertIn('_jump_rows', replay)
            self.assertIn("reader.index.get('quarters')", replay)
            self.assertIn('季度  [上一 ]下一', replay)
            self.assertNotIn('季度 / 回合', replay)
            self.assertNotIn('部队位移段', replay)
            self.assertNotIn(' · 帧{first}', replay)
            self.assertNotIn(" · 帧{start}", replay)
        finally:
            root.destroy()


class PerformanceTests(unittest.TestCase):
    def test_long_archive_size_and_seek(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = 240
            states = [build_demo_state(i % 20, season=1 + (i // 80), move=i % 8) for i in range(n)]
            t0 = time.perf_counter()
            path = write_packed_archive(Path(tmp) / 'long', states, keyframe_every=30)
            write_s = time.perf_counter() - t0
            size = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
            with ArchiveReader(path) as reader:
                t1 = time.perf_counter()
                first = reader.load_frame(1)
                mid = reader.load_frame(n // 2)
                last = reader.load_frame(n)
                seek_s = time.perf_counter() - t1
                t2 = time.perf_counter()
                again = reader.load_frame(n // 2)
                cached_s = time.perf_counter() - t2
            report_path = Path(__file__).resolve().parent.parent / 'logs' / 'replay-load-frame.json'
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text(json.dumps({
                'frames': n,
                'write_seconds': round(write_s, 4),
                'bytes': size,
                'random_seek_seconds': round(seek_s, 4),
                'cached_seek_seconds': round(cached_s, 6),
                'note': 'ArchiveReader.load_frame only; ReplayCursor.view is in RepairTests.test_rc06',
            }, indent=2), encoding='utf8')
            self.assertEqual(first['snapshot_id'], states[0]['snapshot_id'])
            self.assertEqual(mid['snapshot_id'], states[n // 2 - 1]['snapshot_id'])
            self.assertEqual(last['snapshot_id'], states[-1]['snapshot_id'])
            self.assertEqual(again['snapshot_id'], mid['snapshot_id'])
            self.assertLess(seek_s, 1.0)


class HookAndReplayIsolationTests(unittest.TestCase):
    def test_bridge_hooks_publish_path(self):
        text = Path(__file__).with_name('windows_bridge.py').read_text(encoding='utf8')
        self.assertIn('GameArchiveRecorder', text)
        self.assertIn('recorder.ingest', text)
        self.assertIn('replay_archive', text)
        self.assertIn("observed['source_id']", text)
        self.assertIn("observed['runtime_id']", text)
        self.assertIn("observed['release_version']", text)
        self.assertIn('offer_war', text)
        self.assertIn('get_shared_uploader', text)
        self.assertIn('offer_live', text)

    def test_replay_script_does_not_start_bridge(self):
        replay = Path(__file__).resolve().parent.parent / 'app' / 'panorama_replay.py'
        text = replay.read_text(encoding='utf8')
        self.assertNotIn('attach_collector', text)
        self.assertNotIn('ensure_bridge', text)
        self.assertNotIn('ensure_service', text)
        self.assertNotIn('portable_client', text)
        self.assertIn('独立全景回放', text)

    def test_default_root_not_flight_recorder(self):
        self.assertNotIn('flight-records', str(default_archive_root()))
        self.assertNotIn('history-data', str(default_archive_root()))


if __name__ == '__main__':
    unittest.main()
