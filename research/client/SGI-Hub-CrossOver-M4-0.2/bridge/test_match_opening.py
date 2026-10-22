import json
import tempfile
import unittest
from pathlib import Path

from game_archive import build_demo_state, write_packed_archive
from match_opening import (
    archive_label, classify_opening, clamp_replay_seq, finalize_opening,
    first_locked_seq, kept_archive, kept_opening, listed_archive,
    purge_unkept_archives,
)


def rels(*pairs):
    row = [0] * 22
    for fid, value in pairs:
        row[fid] = value
    return row


def lord(fid, name, *ally):
    return {'force_id': fid, 'name': name, 'diplomacy_relations': rels(*((other, 3) for other in ally))}


class OpeningTests(unittest.TestCase):
    def test_three_allies_vs_three_normals_is_player_3v3(self):
        state = {'entities': {'lords': [
            lord(0, '蜀', 1, 2), lord(1, '吴', 0, 2), lord(2, '魏', 0, 1),
            lord(7, '晋'), lord(8, '楚'), lord(9, '齐'),
        ]}}
        info = classify_opening(state)
        self.assertEqual(info['match_kind'], 'player')
        self.assertEqual(info['format'], '3v3')
        self.assertTrue(info['opening_locked'])
        self.assertIn('玩家局 3v3', info['title'])
        self.assertIn('蜀/吴/魏', info['title'])

    def test_two_alliance_blocs(self):
        state = {'entities': {'lords': [
            lord(0, '蜀', 1), lord(1, '吴', 0),
            lord(7, '晋', 8), lord(8, '楚', 7),
        ]}}
        info = classify_opening(state)
        self.assertEqual(info['format'], '2v2')
        self.assertEqual(info['match_kind'], 'player')

    def test_settled_1v1_without_alliance_is_player(self):
        info = classify_opening({'entities': {'lords': [lord(17, '蜀'), lord(7, '晋')]}})
        self.assertEqual(info['title'], '玩家局 1v1 蜀 vs 晋')
        self.assertTrue(info['opening_locked'])

    def test_full_map_without_alliance_is_unlocked_computer(self):
        lords = [lord(i, f'国{i}') for i in range(22)]
        info = classify_opening({'entities': {'lords': lords}})
        self.assertEqual(info['match_kind'], 'computer')
        self.assertFalse(info['opening_locked'])
        sealed = finalize_opening(info, sealed=True)
        self.assertTrue(sealed['opening_locked'])
        self.assertEqual(sealed['title'], '电脑局 22势力')

    def test_label_uses_title(self):
        text = archive_label({
            'title': '玩家局 1v1 蜀 vs 晋',
            'match_kind': 'player',
            'frame_count': 161,
            'completeness': 'complete',
            'last_capture_end': '2026-09-16T01:48:44+00:00',
        })
        self.assertTrue(text.startswith('玩家局 1v1 蜀 vs 晋'))
        self.assertIn('161帧', text)
        self.assertNotIn('采集 ·', text)

    def test_listed_archive_hides_computer_and_demo(self):
        self.assertTrue(listed_archive({'title': '玩家局 1v1 蜀 vs 晋', 'match_kind': 'player'}))
        self.assertFalse(listed_archive({'title': '电脑局 22势力', 'match_kind': 'computer'}))
        self.assertFalse(listed_archive({'title': '电脑局 22势力', 'match_kind': None}))
        self.assertFalse(listed_archive({'title': '玩家局 1v1 蜀 vs 晋', 'simulated': True}))

    def test_kept_opening_is_player_duels(self):
        self.assertTrue(kept_opening({'format': '3v3'}))
        self.assertTrue(kept_opening({'format': '1v1'}))
        self.assertTrue(kept_opening({'format': '2v2'}))
        self.assertFalse(kept_opening({'format': '22势力'}))
        self.assertFalse(kept_opening({'format': '8势力'}))
        self.assertTrue(kept_opening({'format': '1v1'}, keep_formats=None))
        self.assertFalse(kept_archive({'format': '1v1', 'frame_count': 120}))
        self.assertFalse(kept_archive({'format': '3人', 'frame_count': 2789}))
        self.assertTrue(kept_archive({'format': '1v1', 'frame_count': 1000}))
        self.assertTrue(kept_archive({'format': '1v1', 'frame_count': 120}, min_frames=0))
        self.assertFalse(kept_archive({'format': '3v3', 'frame_count': 870, 'completeness': 'write_error'}))
        self.assertFalse(kept_archive({'format': '3v3', 'frame_count': 870, 'write_error': 'access denied'}))
        self.assertTrue(kept_archive({'format': '1v1', 'frame_count': 2789, 'match_kind': 'player'}))

    def test_purge_drops_short_player_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            short = write_packed_archive(
                Path(tmp) / 'short',
                [build_demo_state(0), build_demo_state(1)],
            )
            long = write_packed_archive(Path(tmp) / 'long', [build_demo_state(i) for i in range(6)])
            for path, count, fmt in ((short, 2, '1v1'), (long, 6, '1v1')):
                data = json.loads((path / 'manifest.json').read_text(encoding='utf8'))
                data.update({'format': fmt, 'opening_locked': True, 'title': '玩家局 1v1 测试',
                             'frame_count': count, 'last_seq': count, 'open': False})
                (path / 'manifest.json').write_text(json.dumps(data), encoding='utf8')
            removed = purge_unkept_archives(tmp, min_frames=5)
            self.assertEqual(len(removed), 1)
            self.assertTrue(str(short) in removed[0] or Path(removed[0]).name == Path(short).name)
            self.assertTrue((Path(tmp) / 'long' / 'manifest.json').is_file())
            self.assertFalse((Path(tmp) / 'short' / 'manifest.json').is_file())

    def test_first_locked_seq_skips_22_force_prelude(self):
        def packed_lords(count, allied=False):
            rows = []
            for fid in range(count):
                if allied and count == 6:
                    mates = [i for i in (range(3) if fid < 3 else range(3, 6)) if i != fid]
                    rows.append(lord(fid, f'国{fid}', *mates))
                else:
                    rows.append(lord(fid, f'国{fid}'))
            return rows

        with tempfile.TemporaryDirectory() as tmp:
            states = []
            for i in range(8):
                state = build_demo_state(i)
                state['entities']['lords'] = packed_lords(22 if i < 4 else 6, allied=(i >= 4))
                states.append(state)
            path = write_packed_archive(Path(tmp) / 'm', states)
            self.assertEqual(first_locked_seq(path), 5)

    def test_clamp_replay_seq_stays_in_settled_match(self):
        self.assertEqual(clamp_replay_seq(1, 43, 2897), 43)
        self.assertEqual(clamp_replay_seq(306, 43, 2897), 306)
        self.assertEqual(clamp_replay_seq(9999, 43, 2897), 2897)
        self.assertEqual(clamp_replay_seq('43', 43, 2897), 43)


if __name__ == '__main__':
    unittest.main()
