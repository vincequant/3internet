import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SRC = (Path(__file__).resolve().parents[1] / 'sgi_room_monitor/wine_lobby_ops.py').read_text(encoding='utf-8')
START = ('启动游戏',)
LOGIN = ('登录',)


class LoginWithoutKeychainTests(unittest.TestCase):
    def test_login_once_can_use_remembered_fields(self):
        self.assertIn('请在大厅登录窗登录', SRC)
        self.assertIn('WM_GETTEXTLENGTH', SRC)
        self.assertNotIn("'凭据文件缺失'", SRC)


def _load_picker():
    start = SRC.index('\ndef _is_tab_sheet')
    end = SRC.index('\ndef click_named')
    ns = {'START_BUTTONS': START}
    exec(SRC[start:end], ns)
    return ns


def _ctrl(hwnd, cls, title='', visible=True, enabled=True, parent=0, **extra):
    row = {
        'hwnd': hwnd,
        'class': cls,
        'title': title,
        'visible': visible,
        'enabled': enabled,
        'parent': parent,
    }
    row.update(extra)
    return row


def _main(*children, hwnd=1, visible=True):
    return [{
        'hwnd': hwnd,
        'class': 'TMainForm',
        'title': '三国志Internet对战平台 6.2',
        'visible': visible,
        'children': list(children),
    }]


class StartButtonPickTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_picker()
        self.pick = self.ns['pick_named_control']

    def _room_page(self, start_hwnd=21, start_parent=None, start_visible=True, start_enabled=True,
                   room_visible=True, news_visible=False, extra=()):
        """One TPageControl with 游戏房间 + 游戏公告, start button on the room sheet (or parent)."""
        page, room, news, panel = 10, 11, 12, 13
        parent = room if start_parent is None else start_parent
        kids = [
            _ctrl(page, 'TPageControl', parent=1),
            _ctrl(room, 'TTabSheet', '游戏房间', visible=room_visible, parent=page),
            _ctrl(news, 'TTabSheet', '游戏公告', visible=news_visible, parent=page),
            _ctrl(panel, 'TPanel', parent=room),
            _ctrl(start_hwnd, 'TButton', '启动游戏', visible=start_visible,
                  enabled=start_enabled, parent=parent),
        ]
        kids.extend(extra)
        return _main(*kids)

    def test_zero_start_buttons_returns_none(self):
        rows = _main(
            _ctrl(10, 'TPageControl', parent=1),
            _ctrl(11, 'TTabSheet', '游戏房间', parent=10),
            _ctrl(20, 'TButton', '登录', parent=1),
        )
        self.assertIsNone(self.pick(rows, START))

    def test_one_start_button_is_picked(self):
        rows = self._room_page()
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)
        self.assertEqual(picked['title'], '启动游戏')

    def test_hidden_tab_duplicate_picks_room_page(self):
        # Hidden 游戏公告 copy is marked visible+enabled on the button itself.
        rows = self._room_page(extra=(
            _ctrl(22, 'TButton', '启动游戏', visible=True, enabled=True, parent=12),
        ))
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)
        self.assertEqual(picked['parent'], 11)

    def test_disabled_on_current_and_enabled_on_hidden_is_none(self):
        rows = self._room_page(start_enabled=False, extra=(
            _ctrl(22, 'TButton', '启动游戏', visible=True, enabled=True, parent=12),
        ))
        self.assertIsNone(self.pick(rows, START))

    def test_two_visible_enabled_on_same_current_sheet_fail_closed(self):
        # Two real front hits on 游戏房间: do not guess.
        rows = self._room_page(extra=(
            _ctrl(23, 'TButton', '启动游戏', visible=True, enabled=True, parent=11),
        ))
        self.assertIsNone(self.pick(rows, START))

    def test_two_current_pages_prefer_room_sheet(self):
        rows = _main(
            _ctrl(10, 'TPageControl', parent=1),
            _ctrl(11, 'TTabSheet', '游戏房间', parent=10),
            _ctrl(12, 'TTabSheet', '游戏公告', visible=False, parent=10),
            _ctrl(21, 'TButton', '启动游戏', parent=11),
            _ctrl(30, 'TPageControl', parent=1),
            _ctrl(31, 'TTabSheet', '房间用户(1)', parent=30),
            _ctrl(32, 'TTabSheet', '我的好友', visible=False, parent=30),
            _ctrl(41, 'TButton', '启动游戏', parent=31),
        )
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)

    def test_two_current_pages_neither_room_fail_closed(self):
        rows = _main(
            _ctrl(10, 'TPageControl', parent=1),
            _ctrl(11, 'TTabSheet', '游戏公告', parent=10),
            _ctrl(21, 'TButton', '启动游戏', parent=11),
            _ctrl(30, 'TPageControl', parent=1),
            _ctrl(31, 'TTabSheet', '我的好友', parent=30),
            _ctrl(41, 'TButton', '启动游戏', parent=31),
        )
        self.assertIsNone(self.pick(rows, START))

    def test_tcm_current_beats_lying_visible_sheets(self):
        # Both sheets claim visible; TCM index 0 is 游戏房间.
        page, room, news = 10, 11, 12
        rows = _main(
            _ctrl(page, 'TPageControl', parent=1),
            _ctrl(room, 'TTabSheet', '游戏房间', visible=True, parent=page),
            _ctrl(news, 'TTabSheet', '游戏公告', visible=True, parent=page),
            _ctrl(21, 'TButton', '启动游戏', visible=True, enabled=True, parent=room),
            _ctrl(22, 'TButton', '启动游戏', visible=True, enabled=True, parent=news),
        )
        self.ns['annotate_current_tabs'](rows, lambda parent: 0 if parent == page else None)
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)

    def test_page_chrome_start_follows_room_pagecontrol(self):
        rows = _main(
            _ctrl(10, 'TPageControl', parent=1),
            _ctrl(11, 'TTabSheet', '游戏房间', parent=10),
            _ctrl(12, 'TTabSheet', '游戏公告', visible=False, parent=10),
            _ctrl(21, 'TButton', '启动游戏', parent=10),
            _ctrl(30, 'TPageControl', parent=1),
            _ctrl(31, 'TTabSheet', '房间用户(1)', parent=30),
            _ctrl(41, 'TButton', '启动游戏', parent=30),
        )
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)

    def test_start_names_do_not_pick_login(self):
        rows = _main(
            _ctrl(11, 'TTabSheet', '游戏房间', parent=10),
            _ctrl(10, 'TPageControl', parent=1),
            _ctrl(21, 'TButton', '启动游戏', parent=11),
            _ctrl(50, 'TButton', '登录', parent=1),
        )
        picked = self.pick(rows, START)
        self.assertEqual(picked['hwnd'], 21)
        login = self.pick(rows, LOGIN)
        self.assertEqual(login['hwnd'], 50)

    def test_duplicate_hwnd_is_one_hit(self):
        btn = _ctrl(21, 'TButton', '启动游戏', parent=11)
        rows = [
            {
                'hwnd': 1, 'class': 'TMainForm', 'title': '平台', 'visible': True,
                'children': [
                    _ctrl(10, 'TPageControl', parent=1),
                    _ctrl(11, 'TTabSheet', '游戏房间', parent=10),
                    btn,
                ],
            },
            {
                'hwnd': 11, 'class': 'TTabSheet', 'title': '游戏房间', 'visible': True,
                'children': [dict(btn)],
            },
        ]
        picked = self.pick(rows, START)
        self.assertIsNotNone(picked)
        self.assertEqual(picked['hwnd'], 21)


if __name__ == '__main__':
    unittest.main()
