import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from game_archive import (
    ArchiveReader, GameArchiveRecorder, build_demo_state, compact_state,
    payload_from_state, wait_recorder, write_packed_archive,
)
from replay_query import MatchQuery, current_match, list_matches, player_identity
from replay_view import (
    ReplayCursor, change_to_event, event_index, select_live_track,
    track_draw_polylines, unit_generation_tracks,
)
from state_history import differences, slim
from war_server import WarStore, serve
from war_sync import WarReader, WarSyncQueue, WarUploadCursor, WarUploader


def live(state, **extra):
    return payload_from_state(state, **extra)


class LockAndSealTests(unittest.TestCase):
    def test_sc01_status_and_overflow_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app',
                                      queue_max=2, keep_formats=None)
            rec.apply_gate.clear()
            rec._frame_depth = rec.queue_max
            start = threading.Barrier(3)
            errors = []

            def status():
                start.wait()
                for _ in range(80):
                    rec.public_status()

            def overflow():
                start.wait()
                for i in range(40):
                    rec.ingest(live(build_demo_state(i)))

            threads = [threading.Thread(target=status), threading.Thread(target=overflow)]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(2)
                if thread.is_alive():
                    errors.append('deadlock')
            rec.apply_gate.set()
            rec.close()
            self.assertFalse(errors)

    def test_sc02_seal_after_write_failure_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', keep_formats=None)
            rec.saw_pre_live = True
            rec.apply_gate.clear()
            rec.ingest(live(build_demo_state(0)))
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))

            def boom(*_a, **_k):
                raise OSError('audit simulated disk write failure')

            rec._frame = boom
            rec.apply_gate.set()
            wait_recorder(rec)
            rec.close()
            rows = list_archives_safe(tmp)
            self.assertTrue(rows)
            manifest = json.loads((Path(rows[0]['directory']) / 'manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['completeness'], 'write_error')
            self.assertIn('audit simulated', manifest.get('write_error') or '')
            self.assertNotEqual(manifest['completeness'], 'complete')

    def test_sc02_second_match_not_polluted(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = GameArchiveRecorder(root=Path(tmp), app_dir=Path(__file__).resolve().parent.parent / 'app', keep_formats=None)
            rec.saw_pre_live = True
            rec.apply_gate.clear()
            rec.ingest(live(build_demo_state(0, pid=1, filetime=1)))
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))
            rec.ingest(live(build_demo_state(0, pid=2, filetime=2)))
            rec.ingest(live(None, phase='waiting_for_game', error_class='process_gone'))

            def boom(state, payload, dropped_before=0):
                if state.get('identity', {}).get('pid') == 1:
                    raise OSError('first match disk fail')
                return GameArchiveRecorder._frame(rec, state, payload, dropped_before=dropped_before)

            rec._frame = boom
            rec.apply_gate.set()
            wait_recorder(rec)
            rec.close()
            rows = {row['process']['pid']: row for row in list_archives_safe(tmp)}
            self.assertEqual(rows[1]['completeness'], 'write_error')
            self.assertIn(rows[2]['completeness'], ('complete', 'mid_start'))
            self.assertIsNone(rows[2].get('write_error'))


def list_archives_safe(tmp):
    from game_archive import list_archives
    return list_archives(tmp)


class EventAndTrackTests(unittest.TestCase):
    def test_sc04_same_kind_targets_moving_unit(self):
        a = compact_state(build_demo_state(0))
        a['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'soldiers_candidate': 2400,
             'world_xy_raw': [50, 101]},
            {'unit_id': 8, 'unit_kind': 'cavalry', 'owner_raw': 0, 'soldiers_candidate': 1800,
             'world_xy_raw': [70, 100]},
        ]
        b = compact_state(build_demo_state(1))
        b['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'soldiers_candidate': 2400,
             'world_xy_raw': [50, 101]},
            {'unit_id': 8, 'unit_kind': 'cavalry', 'owner_raw': 0, 'soldiers_candidate': 1800,
             'world_xy_raw': [71, 100]},
        ]
        changes = differences(slim(a), slim(b))
        moves = [row for row in changes if row.get('field') == '部队坐标']
        self.assertEqual(len(moves), 1)
        event = change_to_event(moves[0], 2, slim(b), slim(a))
        self.assertEqual(event['target']['unit_id'], 8)
        self.assertEqual(event['target']['world_xy_before'], [70, 100])
        self.assertEqual(event['target']['world_xy_after'], [71, 100])
        self.assertNotEqual(event['target'].get('unit_id'), 7)

    def test_sc04_disappear_keeps_last_known(self):
        a = compact_state(build_demo_state(0))
        a['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'world_xy_raw': [50, 101]},
            {'unit_id': 8, 'unit_kind': 'cavalry', 'owner_raw': 0, 'world_xy_raw': [70, 100]},
        ]
        b = compact_state(build_demo_state(1))
        b['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'world_xy_raw': [50, 101]},
        ]
        changes = differences(slim(a), slim(b))
        gone = [row for row in changes if row.get('field') == '记录有无' and row.get('entity') == 'field_units']
        self.assertTrue(gone)
        event = change_to_event(gone[0], 2, slim(b), slim(a))
        self.assertEqual(event['target']['unit_id'], 8)
        self.assertTrue(event['target'].get('disappeared'))
        self.assertEqual(event['target']['world_xy_raw'], [70, 100])

    def test_sc05_gap_splits_polylines_and_generation(self):
        a = compact_state(build_demo_state(0))
        a['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'world_xy_raw': [50, 101]}]
        b = compact_state(build_demo_state(1, move=40))
        b['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'world_xy_raw': [90, 101]}]
        tracks = unit_generation_tracks([a, b], gaps=[{'after_seq': 1, 'reason': 'transient_inconsistent'}])
        live = select_live_track(tracks, 2, 7)
        self.assertEqual(len(live), 1)
        lines = track_draw_polylines(live[0])
        self.assertGreaterEqual(len(live[0]['segments']), 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(any(line.get('gap_before') for line in lines))
        joined = [pt for line in lines for pt in line['points']]
        self.assertIn([50, 101], joined)
        self.assertIn([90, 101], joined)
        self.assertNotEqual(len(lines), 1)

    def test_sc05_reuse_picks_live_generation(self):
        a = compact_state(build_demo_state(0))
        a['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'infantry', 'owner_raw': 0, 'world_xy_raw': [10, 10]}]
        b = compact_state(build_demo_state(1))
        b['entities']['field_units'] = []
        c = compact_state(build_demo_state(2))
        c['entities']['field_units'] = [
            {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 1, 'world_xy_raw': [80, 80]}]
        tracks = unit_generation_tracks([a, b, c])
        live = select_live_track(tracks, 3, 7)
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]['generation'], 2)
        self.assertEqual(live[0]['samples'][-1]['world_xy_raw'], [80, 80])


class QueryLayerTests(unittest.TestCase):
    def test_time_bounds_and_no_future(self):
        states = [build_demo_state(i, season=1 if i < 3 else 2, move=i) for i in range(6)]
        states[4]['entities']['production_buildings'].append({
            'type': 'horse_farm', 'owner_raw': 0, 'building_ui_amount': 1,
            'world_xy_raw': [53, 101], 'linked_city_id': 1, 'object_id_candidate': 33,
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=2)
            query = MatchQuery(path)
            try:
                first = query.latest_snapshot()
                early = query.latest_snapshot(before_seq=2)
                self.assertEqual(first['cursor_kind'], 'archive_latest')
                self.assertEqual(early['cursor_kind'], 'historical_cursor')
                self.assertEqual(early['seq'], 2)
                self.assertNotEqual(first['seq'], early['seq'])
                before = query.snapshot_at_capture('2020-01-01T00:00:00+00:00')
                self.assertFalse(before.get('found'))
                self.assertEqual(before.get('reason'), 'before_first_frame')
                mid_time = states[1]['capture_end']
                hit = query.snapshot_at_capture(mid_time)
                self.assertTrue(hit['found'])
                self.assertLessEqual(str(hit['capture_end']), str(mid_time))
                self.assertTrue(hit.get('did_not_select_future'))
                again = query.snapshot_at_capture(mid_time)
                self.assertEqual(again['seq'], hit['seq'])
                later = query.events(end_seq=6, end_inclusive=True)
                early_ev = query.events(end_seq=3, end_inclusive=True)
                self.assertTrue(any('牧场' in str(item.get('line') or item.get('field') or '')
                                    for item in later['data']['events']))
                self.assertFalse(any('牧场' in str(item.get('line') or item.get('field') or '')
                                     for item in early_ev['data']['events']))
                self.assertFalse(first.get('visual_interpolation'))
                self.assertTrue(first['omniscient'])
                self.assertFalse(first['player_identity']['guessed'])
                self.assertTrue(first['player_identity']['confirmed'])
            finally:
                query.close()

    def test_player_identity_not_guessed(self):
        state = compact_state(build_demo_state(0))
        state['player_context'] = {'force_id': 0, 'status': 'unknown'}
        ident = player_identity(state)
        self.assertIsNone(ident['force_id'])
        self.assertFalse(ident['guessed'])

    def test_write_packed_archive_replaces_old_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'm'
            write_packed_archive(path, [build_demo_state(i) for i in range(4)], keyframe_every=2)
            write_packed_archive(path, [build_demo_state(i) for i in range(2)], keyframe_every=2)
            reader = ArchiveReader(path)
            try:
                self.assertEqual(reader.frame_count(), 2)
                self.assertEqual(reader.frames[-1]['seq'], 2)
                self.assertFalse(reader.index.get('seq_rewind_tail'))
            finally:
                reader.close()

    def test_seq_rewind_tail_not_merged_into_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'm'
            write_packed_archive(path, [build_demo_state(i) for i in range(3)], keyframe_every=2)
            extra = (path / 'frames.jsonl').read_bytes()
            with (path / 'frames.jsonl').open('ab') as handle:
                handle.write(extra)
            reader = ArchiveReader(path)
            try:
                self.assertEqual(reader.frame_count(), 3)
                self.assertTrue(reader.index.get('seq_rewind_tail'))
            finally:
                reader.close()
            query = MatchQuery(path)
            try:
                latest = query.latest_snapshot()
                self.assertEqual(latest['seq'], 3)
                self.assertTrue(any(gap.get('reason') == 'seq_rewind_tail' for gap in latest['gaps']))
            finally:
                query.close()

    def test_bundled_demo_seq_matches_manifest(self):
        demo = Path(__file__).resolve().parent.parent / 'app' / 'demo_replay_match'
        query = MatchQuery(demo)
        try:
            latest = query.latest_snapshot()
            manifest = query.manifest()
            self.assertEqual(latest['seq'], manifest.get('last_seq'))
            self.assertEqual(latest['snapshot_id'], manifest.get('last_snapshot_id'))
            self.assertFalse(query.cursor.reader.index.get('seq_rewind_tail'))
        finally:
            query.close()


class WarSyncTests(unittest.TestCase):
    def test_bounded_queue_and_auth_and_consistency(self):
        states = [build_demo_state(i, move=i) for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=2)
            query = MatchQuery(path)
            store = WarStore()
            server = serve('127.0.0.1', 0, 'write-secret', 'read-secret', store=store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            base = 'http://127.0.0.1:%s' % port
            try:
                uploader = WarUploader(base + '/api/sgi-war/ingest', 'write-secret')
                uploader.offer_query(query, history=True)
                queue = WarSyncQueue(history_max=2)
                accepted = sum(1 for i in range(5) if queue.offer_history({'n': i}))
                self.assertEqual(accepted, 2)
                self.assertEqual(len(queue.history), 2)
                self.assertEqual(queue.rejected_full, 3)
                self.assertEqual(queue.dropped_history, 0)
                results = uploader.flush()
                self.assertTrue(any(row.get('ok') for row in results))
                reader = WarReader(base, 'read-secret')
                listing = reader.get('/api/sgi-war/matches')
                self.assertEqual(listing['matches'][0]['match_id'], query.match_id())
                remote = reader.get('/api/sgi-war/matches/%s/latest' % query.match_id())
                local = query.latest_snapshot()
                self.assertEqual(remote['snapshot_id'], local['snapshot_id'])
                self.assertEqual(remote['state']['snapshot_id'], local['data']['snapshot_id'])
                again = uploader.flush()
                first = uploader._post(uploader.pack_snapshot(query))
                self.assertIn(first.get('action'), ('duplicate', 'accepted'))
                from urllib.error import HTTPError
                with self.assertRaises(HTTPError) as raised:
                    WarReader(base, 'wrong').get('/api/sgi-war/matches')
                self.assertEqual(raised.exception.code, 401)
                raised.exception.close()
            finally:
                query.close()
                server.shutdown()
                server.server_close()

    def test_disk_cursor_survives_restart_and_queue_full(self):
        states = [build_demo_state(i, move=i) for i in range(6)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_packed_archive(Path(tmp) / 'm', states, keyframe_every=2,
                                        extra_manifest={'simulated': True, 'test_fixture': True})
            store = WarStore()
            server = serve('127.0.0.1', 0, 'write-secret', 'read-secret', store=store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            base = 'http://127.0.0.1:%s' % port
            query = MatchQuery(path)
            try:
                first = WarUploader(base + '/api/sgi-war/ingest', 'write-secret',
                                    queue=WarSyncQueue(history_max=2))
                first.archive_dir = str(path)
                first.refill_from_archive(test_fixture=True)
                self.assertGreaterEqual(first.queue.rejected_full, 0)
                first.flush()
                cursor = WarUploadCursor(path).load()
                self.assertEqual(cursor['match_id'], query.match_id())
                mid_ack = cursor.get('acked_seq') or 0
                self.assertGreater(mid_ack, 0)
                second = WarUploader(base + '/api/sgi-war/ingest', 'write-secret',
                                     queue=WarSyncQueue(history_max=8))
                second.archive_dir = str(path)
                second.flush()
                later = WarUploadCursor(path).load()
                self.assertGreaterEqual(later.get('acked_seq') or 0, mid_ack)
                reader = WarReader(base, 'read-secret')
                remote = reader.get('/api/sgi-war/matches/%s/summary' % query.match_id())
                self.assertTrue(remote.get('test_fixture') or remote.get('simulated'))
                self.assertEqual(remote['match_id'], query.match_id())
                track = reader.get('/api/sgi-war/matches/%s/track?unit_id=7' % query.match_id())
                self.assertTrue((track.get('data') or {}).get('found'))
            finally:
                query.close()
                server.shutdown()
                server.server_close()


class ScalePerfTests(unittest.TestCase):
    def test_synthetic_923_generals(self):
        n = 80
        states = []
        for i in range(n):
            state = build_demo_state(i % 20, season=1 + (i // 40), move=i % 6)
            state['entities']['generals'] = [
                {'general_id_raw': gid, 'name': '将%s' % gid, 'owner_raw': gid % 8,
                 'status_code': 2, 'location_city_id': (gid % 40) + 1}
                for gid in range(923)
            ]
            state['entities']['field_units'] = [
                {'unit_id': u, 'unit_kind': 'cavalry', 'owner_raw': u % 4,
                 'soldiers_candidate': 1000 + u, 'world_xy_raw': [40 + (u + i) % 30, 90 + u % 10]}
                for u in range(48)
            ]
            states.append(state)
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.perf_counter()
            path = write_packed_archive(Path(tmp) / 'scale', states, keyframe_every=20)
            write_s = time.perf_counter() - t0
            size = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
            query = MatchQuery(path)
            try:
                t1 = time.perf_counter()
                latest = query.latest_snapshot()
                latest_s = time.perf_counter() - t1
                t2 = time.perf_counter()
                hist = query.snapshot_at_capture(states[20]['capture_end'])
                hist_s = time.perf_counter() - t2
                t3 = time.perf_counter()
                ev = query.events(limit=50)
                ev_s = time.perf_counter() - t3
                t4 = time.perf_counter()
                tr = query.unit_track(3)
                tr_s = time.perf_counter() - t4
                t5 = time.perf_counter()
                query.cursor.view(n)
                view_s = time.perf_counter() - t5
            finally:
                query.close()
            report = {
                'label': 'synthetic 923 generals / 48 units / 80 frames',
                'simulated': True,
                'write_seconds': round(write_s, 4),
                'bytes': size,
                'latest_snapshot_seconds': round(latest_s, 4),
                'historical_snapshot_seconds': round(hist_s, 4),
                'events_seconds': round(ev_s, 4),
                'track_seconds': round(tr_s, 4),
                'view_last_seconds': round(view_s, 4),
            }
            out = Path(__file__).resolve().parent.parent / 'logs'
            out.mkdir(exist_ok=True)
            (out / 'replay-query-scale.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            self.assertTrue(latest['found'])
            self.assertEqual(latest['data']['entities']['generals'][0]['general_id_raw'], 0)
            self.assertEqual(len(latest['data']['entities']['generals']), 923)
            self.assertTrue(hist['found'])
            self.assertLess(latest_s, 3.0)
            self.assertLess(view_s, 8.0)


if __name__ == '__main__':
    unittest.main()
