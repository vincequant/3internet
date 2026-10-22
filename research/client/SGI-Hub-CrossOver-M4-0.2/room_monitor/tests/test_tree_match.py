import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SRC = (Path(__file__).resolve().parents[1] / 'sgi_room_monitor/wine_lobby_ops.py').read_text(encoding='utf-8')


def _load_matchers():
    start = SRC.index('def _tree_text')
    end = SRC.index('\ndef select_tree_index')
    ns = {}
    exec(SRC[start:end], ns)
    return ns


class TreeMatchTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_matchers()

    def _trees(self, *titles, hwnd=11):
        items = [{'text': title, 'handle': 100 + i, 'depth': 0 if i == 0 else 1}
                 for i, title in enumerate(titles)]
        return [{'hwnd': hwnd, 'items': items}]

    def test_exact_multiline2_does_not_take_main_line(self):
        trees = self._trees('三国对战房', '多线2（主线）', '多线2')
        match, exact, partial = self.ns['collect_tree_matches'](trees, '多线2')
        self.assertEqual(match['text'], '多线2')
        self.assertEqual(len(exact), 1)
        self.assertEqual(len(partial), 1)

    def test_main_line_exact(self):
        trees = self._trees('三国对战房', '多线2（主线）', '多线2')
        match, exact, _ = self.ns['collect_tree_matches'](trees, '多线2（主线）')
        self.assertEqual(match['text'], '多线2（主线）')
        self.assertEqual(len(exact), 1)

    def test_room_exact(self):
        trees = self._trees('三国对战房', '多线2（主线）', '多线2', '文明4对战房')
        match, exact, _ = self.ns['collect_tree_matches'](trees, '三国对战房')
        self.assertEqual(match['text'], '三国对战房')
        self.assertEqual(len(exact), 1)

    def test_duplicate_handle_is_deduped(self):
        trees = [
            {'hwnd': 11, 'items': [
                {'text': '三国对战房', 'handle': 5},
                {'text': '三国对战房', 'handle': 5},
            ]}
        ]
        match, exact, _ = self.ns['collect_tree_matches'](trees, '三国对战房')
        self.assertIsNotNone(match)
        self.assertEqual(len(exact), 1)

    def test_two_real_hits_are_not_unique(self):
        trees = self._trees('三国对战房', '三国对战房')
        trees[0]['items'][1]['handle'] = 200
        match, exact, _ = self.ns['collect_tree_matches'](trees, '三国对战房')
        self.assertIsNone(match)
        self.assertEqual(len(exact), 2)
        dumped = self.ns['dump_tree_texts'](trees)
        self.assertEqual(dumped, [['三国对战房', '三国对战房']])

    def test_substring_only_when_unique(self):
        trees = self._trees('三国对战房', '多线2（主线）')
        match, exact, partial = self.ns['collect_tree_matches'](trees, '多线2')
        self.assertEqual(match['text'], '多线2（主线）')
        self.assertEqual(exact, [])
        self.assertEqual(len(partial), 1)

    def test_empty_tree_picks_second_depth1_for_line2(self):
        items = [
            {'text': '', 'depth': 0},
            {'text': '', 'depth': 1},
            {'text': '', 'depth': 1},
            {'text': '', 'depth': 1},
        ]
        self.assertEqual(self.ns['pick_empty_tree_index'](items, ['多线2（主线）', '多线2']), 2)
        self.assertEqual(self.ns['pick_empty_tree_index'](items, ['三国对战房']), 1)


if __name__ == '__main__':
    unittest.main()
