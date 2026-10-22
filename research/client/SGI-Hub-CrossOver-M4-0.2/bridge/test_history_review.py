import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]

from game_archive import build_demo_state, write_demo_archive, write_packed_archive
from state_history import load_journal_history
from history_review import (
    archive_day, archive_list_entries, archive_match_label, archive_season_nodes, archive_time_nodes,
    day_label, group_archives_by_day, is_live_recording, load_archive_frame, load_last_frame,
    attach_frame_history, previous_archive, replay_archive_label,
    review_archive, review_archives, review_bundle,
    season_neighbors, season_neighbors_from, status_line, troop_series_from_archive,
)


def _with_turn(state, turn):
    clock = dict(state.get('clock_candidates') or {})
    clock['turn_u16'] = turn
    state['clock_candidates'] = clock
    return state


class HistoryReviewTests(unittest.TestCase):
    def test_previous_archive_skips_open_and_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = write_packed_archive(
                root / '20260101T000000Z-keep',
                [build_demo_state(0, year=200, season=2), build_demo_state(1, year=200, season=3)],
                extra_manifest={'title': '上一局', 'match_id': 'prev-1'},
            )
            write_demo_archive(root / '20260103T000000Z-demo')
            opened = write_packed_archive(
                root / '20260104T000000Z-live',
                [build_demo_state(2)],
                extra_manifest={'title': '进行中', 'match_id': 'live-1'},
            )
            manifest = json.loads((opened / 'manifest.json').read_text(encoding='utf-8'))
            manifest['open'] = True
            (opened / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            chosen = previous_archive(root)
            self.assertEqual(Path(chosen['directory']), older)
            self.assertEqual(chosen['match_id'], 'prev-1')
            bundle = review_bundle(root)
            self.assertEqual(bundle['seq'], 2)
            self.assertEqual(bundle['state']['entities']['lords'][0]['gold'], 10001)
            self.assertIn('相邻帧推断', (bundle['state'].get('history') or {}).get('banner', ''))
            self.assertIn('quarters', bundle['state'].get('history') or {})
            self.assertIn('末帧 2/2', status_line(bundle))
            self.assertIn('只读历史', status_line(bundle))
            self.assertGreaterEqual(len((bundle['state'].get('history') or {}).get('troop_series') or []), 2)
            path = write_packed_archive(
                root / '20260102T000000Z-curve',
                [build_demo_state(0, year=200, season=0), build_demo_state(1, year=200, season=1),
                 build_demo_state(2, year=200, season=2)],
                extra_manifest={'title': '曲线局', 'match_id': 'curve-1'},
            )
            labels = [row.get('label') for row in troop_series_from_archive(path)]
            self.assertGreaterEqual(len(labels), 2)
            self.assertNotEqual(labels[0], labels[-1])
            same_season = write_packed_archive(
                root / '20260102T120000Z-season-only',
                [
                    _with_turn(build_demo_state(0, year=200, season=1), 0),
                    _with_turn(build_demo_state(1, year=200, season=1), 2),
                    _with_turn(build_demo_state(2, year=200, season=1), 4),
                    _with_turn(build_demo_state(3, year=200, season=2), 0),
                ],
                extra_manifest={'title': '一季三回', 'match_id': 'season-only-1'},
            )
            season_keys = [
                (row.get('year'), row.get('season'))
                for row in troop_series_from_archive(same_season)
            ]
            self.assertEqual(season_keys, [(200, 1), (200, 2)])
            manifest['write_error'] = 'access denied'
            manifest['completeness'] = 'write_error'
            (opened / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(previous_archive(root)['match_id'], 'live-1')
            listed = [row['match_id'] for row in review_archives(root)]
            self.assertIn('prev-1', listed)
            self.assertIn('live-1', listed)
            self.assertNotIn(None, listed)
            picked = review_archive(next(row for row in review_archives(root) if row['match_id'] == 'curve-1'))
            self.assertEqual(picked['archive']['match_id'], 'curve-1')

    def test_stale_open_1v1_beats_older_write_error_3v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = write_packed_archive(
                root / '20260101T000000Z-3v3',
                [build_demo_state(0), build_demo_state(1)],
                extra_manifest={'title': '玩家局 3v3 韩/周/羌 vs 晋/蜀/南蛮', 'match_id': 'old-3v3', 'format': '3v3'},
            )
            man = json.loads((older / 'manifest.json').read_text(encoding='utf-8'))
            man['open'] = True
            man['write_error'] = 'access denied'
            man['completeness'] = 'write_error'
            (older / 'manifest.json').write_text(json.dumps(man), encoding='utf-8')
            stale = write_packed_archive(
                root / '20260105T000000Z-1v1',
                [build_demo_state(0), build_demo_state(1), build_demo_state(2)],
                extra_manifest={'title': '玩家局 1v1 蜀 vs 汉', 'match_id': 'stale-1v1', 'format': '1v1'},
            )
            man = json.loads((stale / 'manifest.json').read_text(encoding='utf-8'))
            man['open'] = True
            man['ended_utc'] = None
            man['completeness'] = 'recording'
            man['write_error'] = None
            man['last_capture_end'] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            (stale / 'manifest.json').write_text(json.dumps(man), encoding='utf-8')
            self.assertFalse(is_live_recording(man))
            chosen = previous_archive(root)
            self.assertEqual(chosen['match_id'], 'stale-1v1')
            self.assertIn('1v1', chosen.get('title') or chosen.get('format') or '')

    def test_stale_mid_start_is_listed(self):
        now = datetime.now(timezone.utc)
        stale = {
            'open': True, 'completeness': 'mid_start', 'match_id': 'mid-stale',
            'started_mid_match': True,
            'last_capture_end': (now - timedelta(hours=3)).isoformat(),
        }
        fresh = {
            'open': True, 'completeness': 'mid_start', 'match_id': 'mid-live',
            'started_mid_match': True,
            'last_capture_end': now.isoformat(),
        }
        self.assertFalse(is_live_recording(stale, now=now))
        self.assertTrue(is_live_recording(fresh, now=now))

    def test_fresh_open_recording_is_still_skipped(self):
        row = {
            'open': True, 'completeness': 'recording', 'match_id': 'live',
            'last_capture_end': datetime.now(timezone.utc).isoformat(),
        }
        self.assertTrue(is_live_recording(row))
        self.assertTrue(is_live_recording({'open': True, 'completeness': 'recording', 'match_id': 'live'},
                                          live_match_id='live'))

    def test_empty_root_has_no_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(previous_archive(Path(tmp)))
            with self.assertRaisesRegex(ValueError, '没有可选取'):
                review_bundle(Path(tmp))
            self.assertEqual(review_archives(Path(tmp)), [])

    def test_load_last_frame_rejects_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'empty'
            path.mkdir()
            (path / 'manifest.json').write_text(json.dumps({
                'format_version': 2, 'open': False, 'frames': [], 'last_seq': 0,
            }), encoding='utf-8')
            (path / 'frames.jsonl').write_text('', encoding='utf-8')
            (path / 'index.json').write_text(json.dumps({'frames': []}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '没有帧'):
                load_last_frame(path)

    def test_hub_page_has_review_controls(self):
        text = (ROOT / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertIn('选取存档', text)
        self.assertNotIn('读取上一局末帧', text)
        self.assertIn('回到实时', text)
        self.assertIn('def pick_history_archive', text)
        self.assertIn('def _choose_history_archive', text)
        self.assertIn('def step_review_season', text)
        self.assertIn("text='←'", text)
        self.assertIn("text='→'", text)
        self.assertIn('season_neighbors', text)
        self.assertIn('review-season-step', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('时间节点', text)
        self.assertIn('先选日期，再选对局，再选时间节点', text)
        self.assertIn("column(frame,'日期')", text)
        self.assertIn('group_archives_by_day', text)
        self.assertIn('archive_time_nodes', text)
        self.assertIn("seq=chosen.get('seq')", text)
        self.assertIn('if self.review:', text)
        self.assertIn('存档末帧只读，不改我方身份。', text)
        self.assertIn('选取历史回放存档', text)
        self.assertIn('if live and live!=review:', text)
        self.assertIn('hub-last-frame-review', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('keep-player-1v1-2v2-3v3-archives', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('troop-series-collector-path', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('training-record-split-kind-charts', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('drop-archives-under-1000-frames', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('capture-buildings-not-construction', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('officer-city-nation-map', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('change-tab-round-labels', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('training-record-heavy-cavalry', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('keep-write-error-player-archives', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('review-troop-series-from-archive', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('training-record-season-only', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('panorama-city-hp-unit-move', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        review = (ROOT / 'app' / 'history_review.py').read_text(encoding='utf-8')
        self.assertIn("reader.index.get('quarters')", review)
        self.assertIn('first_seq', review)
        self.assertIn('is_live_recording', review)
        self.assertIn('stale_s', review)
        self.assertIn('def review_archives', review)
        self.assertIn('def review_archive', review)
        self.assertIn('def archive_time_nodes', review)
        self.assertIn('def archive_day', review)
        self.assertIn('def group_archives_by_day', review)
        self.assertIn('def load_archive_frame', review)
        self.assertIn('hub-replay-archive-picker', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('hub-review-time-nodes', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('archive-pick-day-then-match', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('load_journal_history', review)
        self.assertIn('archive-review-quarter-ledger', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))

    def test_journal_ledger_stops_before_the_viewed_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / '42'
            folder.mkdir()
            early = {
                'phase': {'year_u16': 200, 'season_u16': 0, 'round_u8': 0},
                'label': '200年春 · 内政（已过季）', 'closed': True,
                'forces': [{'owner': 1, 'name': '义渠', 'operations': [
                    {'field': '录用', 'line': '录用 甲：西河', 'after': '甲'},
                ]}],
            }
            same = {
                'phase': {'year_u16': 204, 'season_u16': 0, 'round_u8': 0},
                'label': '204年春 · 内政（已过季）', 'closed': True,
                'forces': [{'owner': 1, 'name': '义渠', 'operations': [
                    {'field': '主动加入', 'line': '加入 乙：灵州', 'after': '乙'},
                ]}],
            }
            later = {
                'phase': {'year_u16': 205, 'season_u16': 2, 'round_u8': 2},
                'label': '205年秋 第3回合（已过季）', 'closed': True,
                'forces': [{'owner': 1, 'operations': [
                    {'field': '录用', 'line': '录用 丙', 'after': '丙'},
                ]}],
            }
            (folder / 'quarters.jsonl').write_text(
                '\n'.join(json.dumps(row, ensure_ascii=False) for row in (early, same, later)) + '\n',
                encoding='utf8')
            view = {'year_u16': 204, 'season_u16': 0, 'round_u8': 0}
            clipped = load_journal_history(42, view, root=root)
            self.assertEqual([row['label'] for row in clipped['quarters']], ['200年春 · 内政（已过季）'])
            self.assertIsNone(clipped['current_quarter'])
            closed = load_journal_history(42, view, include_same_phase=True, root=root)
            self.assertEqual(closed['current_quarter']['forces'][0]['operations'][0]['after'], '乙')
            state = {
                'phase_candidate': view,
                'identity': {'creation_filetime': 42},
                'entities': {'lords': [], 'field_units': []},
            }
            doc = attach_frame_history(state, journal_root=root)
            self.assertEqual(len(doc['history']['quarters']), 1)
            self.assertIn('布施', doc['history']['banner'])
            self.assertNotIn('录用 丙', json.dumps(doc['history'], ensure_ascii=False))

    def test_review_can_open_a_season_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_packed_archive(
                root / '20260106T000000Z-nodes',
                [
                    build_demo_state(0, year=200, season=0),
                    build_demo_state(1, year=200, season=1),
                    build_demo_state(2, year=200, season=2),
                    build_demo_state(3, year=200, season=3),
                ],
                extra_manifest={'title': '节点局', 'match_id': 'nodes-1', 'format': '1v1'},
            )
            nodes = archive_time_nodes(path)
            labels = [row['label'] for row in nodes]
            self.assertIn('开局', labels)
            self.assertIn('末帧', labels)
            self.assertTrue(any('200年' in label for label in labels))
            first = load_archive_frame(path, nodes[0]['seq'])
            last = load_last_frame(path)
            self.assertEqual(first['seq'], nodes[0]['seq'])
            self.assertEqual(last['seq'], last['frame_count'])
            self.assertNotEqual(first['state']['snapshot_id'], last['state']['snapshot_id'])
            mid = review_archive(path, seq=nodes[1]['seq'])
            self.assertEqual(mid['seq'], nodes[1]['seq'])
            self.assertEqual(mid['node_label'], nodes[1]['label'])
            self.assertIn(nodes[1]['label'], status_line(mid))
            self.assertNotIn('末帧 4/4', status_line(mid))
            seasons = archive_season_nodes(path)
            self.assertEqual([row['label'] for row in seasons], ['200年夏', '200年秋', '200年冬'])
            inside = [
                {'seq': 10, 'label': '200年春'},
                {'seq': 40, 'label': '200年夏'},
                {'seq': 80, 'label': '200年秋'},
            ]
            prev, nxt = season_neighbors_from(inside, 55)
            self.assertEqual((prev['label'], nxt['label']), ('200年春', '200年秋'))
            prev, nxt = season_neighbors(path, seasons[1]['seq'])
            self.assertEqual(prev['label'], '200年夏')
            self.assertEqual(nxt['label'], '200年冬')
            prev, nxt = season_neighbors(path, seasons[0]['seq'])
            self.assertIsNone(prev)
            self.assertEqual(nxt['seq'], seasons[1]['seq'])
            prev, nxt = season_neighbors(path, seasons[-1]['seq'])
            self.assertEqual(prev['label'], '200年秋')
            self.assertIsNone(nxt)
            jumped = review_archive(path, seq=prev['seq'])
            self.assertEqual(jumped['seq'], seasons[1]['seq'])

    def test_archives_group_by_day_then_match(self):
        rows = [
            {'title': '玩家局 1v1 越 vs 巴', 'frame_count': 8700, 'completeness': 'recording',
             'last_capture_end': '2026-09-21T16:50:00+00:00', 'directory': '/tmp/20260921T165000Z-a'},
            {'title': '玩家局 1v1 吴 vs 越', 'frame_count': 12600, 'completeness': 'recording',
             'last_capture_end': '2026-09-21T16:20:00+00:00', 'directory': '/tmp/20260921T162000Z-b'},
            {'title': '玩家局 1v1 中山 vs 南蛮', 'frame_count': 1350, 'completeness': 'complete',
             'last_capture_end': '2026-09-20T15:46:00+00:00', 'directory': '/tmp/20260920T154600Z-c'},
            {'title': '无时间', 'frame_count': 10, 'completeness': 'complete',
             'directory': '/tmp/no-stamp'},
        ]
        self.assertEqual(archive_day(rows[0]), '2026-09-21')
        self.assertEqual(archive_day(rows[3]), '日期未知')
        groups = group_archives_by_day(rows)
        self.assertEqual([day for day, _items in groups], ['2026-09-21', '2026-09-20', '日期未知'])
        self.assertEqual(day_label('2026-09-21', groups[0][1]), '2026-09-21 · 2局')
        self.assertEqual(len(groups[0][1]), 2)
        self.assertEqual(archive_match_label(rows[0]), '玩家局 1v1 越 vs 巴 · 8700帧 · recording · 16:50')
        self.assertNotIn('2026-09-21', archive_match_label(rows[0]))
        china = timezone(timedelta(hours=8))
        self.assertEqual(archive_day(rows[0], tz=china), '2026-09-22')
        self.assertEqual(archive_day(rows[2], tz=china), '2026-09-20')
        shifted = group_archives_by_day(rows[:3], tz=china)
        self.assertEqual([day for day, _items in shifted], ['2026-09-22', '2026-09-20'])
        entries = archive_list_entries(rows[:3], tz=china)
        self.assertEqual([item['kind'] for item in entries], ['day', 'match', 'match', 'day', 'match'])
        self.assertEqual(entries[0]['label'], '2026-09-22 · 2局')
        self.assertIsNone(entries[0]['row'])
        self.assertTrue(replay_archive_label(rows[0], tz=china).startswith('00:50  玩家局 1v1 越 vs 巴'))
        self.assertNotIn('2026-09', replay_archive_label(rows[0], tz=china))
        replay = (ROOT / 'app' / 'panorama_replay.py').read_text(encoding='utf-8')
        self.assertIn('archive_list_entries', replay)
        self.assertIn('replay-archives-by-day', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
