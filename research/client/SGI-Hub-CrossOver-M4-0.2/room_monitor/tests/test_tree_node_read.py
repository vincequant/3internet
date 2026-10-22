import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.tree_node_read import (
    CALLBACK_MASK, decode_tree_label, label_from_item, line_entered,
    parse_tree_item, result_driven_indices, verify_sanguo,
)


# Anonymized Wine TREEITEM captured 2026-09-17: links/ids zeroed except layout
# markers. Text payload is the public lobby label only, no account data.
LINE2_ITEM = struct.pack(
    '<16I',
    0x00BFB110, 0x00BFB1A0, 0, 1, 0, 0,
    0x0E880000, 130, 2, 1, CALLBACK_MASK, 0,
    0x01D4A000, 1, 2, 0,
)
LINE2_TEXT = '多线2（主线）(4)\x00'.encode('utf-16le')
BAD_ITEM = struct.pack('<16I', *([1] * 16))


class TreeNodeReadTests(unittest.TestCase):
    def test_parse_accepts_callback_layout(self):
        parsed = parse_tree_item(LINE2_ITEM)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['text_ptr'], 0x0E880000)
        self.assertEqual(parsed['callback'], CALLBACK_MASK)

    def test_parse_rejects_short_or_wrong_mask(self):
        self.assertIsNone(parse_tree_item(LINE2_ITEM[:20]))
        self.assertIsNone(parse_tree_item(BAD_ITEM))

    def test_decode_strips_occupant_suffix(self):
        self.assertEqual(decode_tree_label(LINE2_TEXT), '多线2（主线）')
        self.assertEqual(decode_tree_label('房间A\x00'.encode('utf-16le')), '房间A')

    def test_label_from_item_roundtrip(self):
        self.assertEqual(label_from_item(LINE2_ITEM, LINE2_TEXT), '多线2（主线）')
        self.assertIsNone(label_from_item(BAD_ITEM, LINE2_TEXT))

    def test_verify_sanguo_fail_closed(self):
        self.assertFalse(verify_sanguo(None))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'SANGUO.exe'
            path.write_bytes(b'not-the-game')
            self.assertFalse(verify_sanguo(path))

    def test_result_driven_prefers_depth2_for_line2(self):
        items = [
            {'depth': 0}, {'depth': 1}, {'depth': 1},
            {'depth': 2}, {'depth': 2}, {'depth': 2},
        ]
        self.assertEqual(result_driven_indices(items, ['多线2（主线）']), [3, 4, 5, 1, 2])

    def test_pick_unique_line_prefers_sanguo_room_or_selected(self):
        from sgi_room_monitor.tree_node_read import pick_unique_line
        a = {'text': '多线2（主线）', 'parent': '★★★三国对战房★★★', 'selected': False}
        b = {'text': '多线2（主线）', 'parent': '★★★文明4文明系列★★★', 'selected': False}
        self.assertEqual(pick_unique_line([a, b])['parent'], '★★★三国对战房★★★')
        b['selected'] = True
        self.assertEqual(pick_unique_line([a, b])['parent'], '★★★文明4文明系列★★★')

    def test_line_entered_uses_observable_hall(self):
        self.assertFalse(line_entered({'titles': ['房间用户(0)'], 'has_start': False}))
        self.assertTrue(line_entered({'has_start': True, 'titles': ['房间用户(0)']}))
        self.assertTrue(line_entered({'titles': ['多线2（主线）'], 'has_start': False}))
        self.assertTrue(line_entered({'titles': ['房间用户(3)']}))
        self.assertTrue(line_entered({'game_select': True}))


if __name__ == '__main__':
    unittest.main()
