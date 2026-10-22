import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from chat_type import WM_CHAR, char_messages, gbk_units, require_chat_target
from chat_type_once import type_line
from win_clipboard import unicode_clipboard


def open_chat(**changes):
    state = dict(hwnd=111, widget_count=1, ending=0, native_dialogs=False,
                 confirmation_typed=False, recruit_visible=False, strategy_dialog=0,
                 recruit_dialog=0, map_mode=0, map_widget=0)
    state.update(changes)
    return state


class ChatTypeTests(unittest.TestCase):
    def test_line_is_gbk_bytes_without_enter(self):
        units = gbk_units('卢江 白起  2/5')
        self.assertEqual(bytes(units), '卢江 白起  2/5'.encode('gbk'))
        self.assertNotIn(0x0d, units)
        self.assertNotIn(0x0a, units)
        messages = char_messages(111, '卢江 白起  2/5')
        self.assertTrue(all(message[1] == WM_CHAR for message in messages))

    def test_newline_and_overlong_are_refused(self):
        with self.assertRaises(ValueError):
            gbk_units('卢江\n建业')
        with self.assertRaises(ValueError):
            gbk_units('将' * 80)

    def test_only_an_open_chat_widget_is_accepted(self):
        self.assertEqual(require_chat_target(open_chat()), 111)
        for change in (
            dict(widget_count=0), dict(native_dialogs=True), dict(confirmation_typed=True),
            dict(recruit_visible=True), dict(strategy_dialog=1), dict(map_mode=1),
        ):
            with self.assertRaises(ValueError):
                require_chat_target(open_chat(**change))

    def test_type_line_waits_for_the_game_and_posts_each_byte(self):
        posted = []
        class User:
            def PostMessageA(self, hwnd, message, wparam, lparam):
                posted.append((hwnd, message, wparam, lparam))
                return True
        class Native:
            bound = {'pid': 7}
            u = User()
            def owner(self, hwnd):
                return 7
            def capture(self):
                return open_chat()
        clocks = iter([0, 0.2, 0.2])
        sleeps = []
        count = type_line(
            Native(), 'A',
            lambda: next(clocks) > 0,
            lambda delay: sleeps.append(delay),
            timeout=1,
        )
        self.assertEqual(count, 1)
        self.assertEqual(posted, [(111, WM_CHAR, ord('A'), 1)])
        self.assertTrue(sleeps)

    def test_wine_script_finds_the_app_package(self):
        source = Path(__file__).resolve().parent.joinpath('chat_type_once.py').read_text(encoding='utf-8')
        self.assertLess(source.index("parents[1] / 'app'"), source.index('from quick_control_model import binding'))

    def test_lobby_clipboard_is_utf16_text(self):
        self.assertEqual(unicode_clipboard('卢江'), '卢江'.encode('utf-16le') + b'\x00\x00')


if __name__ == '__main__':
    unittest.main()
