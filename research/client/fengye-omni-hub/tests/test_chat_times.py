"""聊天歷史：遊戲時間標記＋「名字（勢力）」配勢力顏色 的單元測試。

聊天封包本身沒有年份季節，Hub 只能在第一次看到該訊息時，用它當時讀到的回合
（`cmd_targets_data` 的 year/season）標記；讀不到就留空顯示「回合未記錄」。
勢力名要從開局名單（`p34.snapshots`）的 `faction` 欄位對回來。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'app'), str(ROOT / 'bridge')]

import native_window as nw
from chat_force_colors import (chat_parts, force_rgb, hexcolor, luminance,
                               readable, sender_factions)


class ChatTimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(nw, 'CHAT_TIMES', Path(folder.name) / 'chat-times.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = mock.Mock()
        self.app._chat_times = {}
        self.app.cmd_targets_data = {'year': 200, 'season': 0}
        self.app._round_when = lambda data: nw.FengyeWindow._round_when(self.app, data)
        self.app._chat_time_store = lambda: nw.FengyeWindow._chat_time_store(self.app)

    def tag(self, chats):
        return nw.FengyeWindow._tag_chat_times(self.app, chats)

    def test_tags_first_sighting_with_the_game_time(self):
        store = self.tag([{'wall': 100.0, 'text': 'hi'}])
        self.assertEqual(store['100.000'], '200年春')

    def test_an_old_message_keeps_the_time_it_was_first_seen(self):
        self.tag([{'wall': 100.0, 'text': 'hi'}])
        self.app.cmd_targets_data = {'year': 200, 'season': 1}
        store = self.tag([{'wall': 100.0, 'text': 'hi'}, {'wall': 200.0, 'text': 'yo'}])
        self.assertEqual(store['100.000'], '200年春')
        self.assertEqual(store['200.000'], '200年夏')

    def test_persists_to_disk_and_reloads(self):
        self.tag([{'wall': 100.0}])
        saved = json.loads(nw.CHAT_TIMES.read_text(encoding='utf-8'))
        self.assertEqual(saved, {'100.000': '200年春'})
        fresh = mock.Mock()
        fresh._chat_times = None
        store = nw.FengyeWindow._chat_time_store(fresh)
        self.assertEqual(store['100.000'], '200年春')

    def test_without_a_game_time_nothing_is_invented(self):
        self.app.cmd_targets_data = {}
        store = self.tag([{'wall': 100.0}])
        self.assertEqual(store, {})
        self.assertFalse(nw.CHAT_TIMES.exists())


class ForceColourTests(unittest.TestCase):
    def test_known_force_colours(self):
        self.assertEqual(force_rgb('宋'), (189, 74, 24))
        self.assertEqual(hexcolor(force_rgb('宋')), '#bd4a18')
        self.assertIsNone(force_rgb('不存在'))

    def test_light_colours_are_darkened_for_white_text(self):
        bright = force_rgb('晋')
        self.assertIsNotNone(bright)
        self.assertGreater(luminance(bright), 0.6)
        self.assertLessEqual(luminance(readable(bright)), 0.42 + 1e-9)
        dark = force_rgb('魏')
        self.assertEqual(readable(dark), dark)      # 本來就深的不動

    def test_sender_factions_reads_the_start_snapshot(self):
        p34 = {'snapshots': {'start': {'rows': [
            {'id': 11, 'name': '丁滿', 'faction': '宋'},
            {'id': 18, 'name': '風雲', 'faction': '吴'},
        ]}}}
        self.assertEqual(sender_factions(p34), {11: ('丁滿', '宋'), 18: ('風雲', '吴')})
        self.assertEqual(sender_factions({}), {})

    def test_chat_parts_labels_the_force_and_picks_its_colour(self):
        store = {'100.000': '200年春'}
        factions = {11: ('丁滿', '宋')}
        stamp, label, text, colour = chat_parts(
            {'wall': 100.0, 'sender': 11, 'sender_name': '丁滿', 'text': '你好'}, store, factions)
        self.assertIn('200年春', stamp)
        self.assertEqual(label, '丁滿（宋）')
        self.assertEqual(text, '你好')
        self.assertEqual(colour, '#bd4a18')

    def test_chat_parts_without_force_or_time(self):
        stamp, label, text, colour = chat_parts(
            {'wall': 100.0, 'sender': 99, 'sender_name': '路人', 'text': 'hi'}, {}, {})
        self.assertIn('回合未記錄', stamp)
        self.assertEqual(label, '路人')
        self.assertIsNone(colour)


if __name__ == '__main__':
    unittest.main()
