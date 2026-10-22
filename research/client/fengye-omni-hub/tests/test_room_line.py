"""進房頁的線路選擇與「解除卡住」（2026-10-21，0.2.89）。

風夜能看到的房間清單屬於某一條線（多线2／多线3）：線路是在協議登入的那一刻
決定的，所以換線＝重新登入一次。面板必須把「現在在哪條線」講清楚，也不能
讓使用者在錯誤的線上找房。

另外：2026-10-21 實測，客戶端會被「按【确认】搜寻服务器」模態框卡死
（遊戲選擇視窗 disabled），面板要有一鍵解除的入口。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from native_window import FengyeWindow


def _window(wanted='多线3（备用）', session=''):
    """不建立 Tk 視窗，只放需要的屬性。"""
    app = object.__new__(FengyeWindow)
    app.ghost_line = mock.Mock()
    app.ghost_line.get.return_value = wanted
    app._line_state = {'session': session, 'configured': session} if session else {}
    return app


class LineChoiceTests(unittest.TestCase):
    def test_same_line_does_not_need_relogin(self):
        app = _window('多线3（备用）', '多线3（备用）')
        self.assertFalse(app._line_needs_relogin())
        self.assertEqual(app._line_wanted(), '多线3（备用）')
        self.assertEqual(app._line_session(), '多线3（备用）')

    def test_other_line_needs_relogin(self):
        app = _window('多线2（主线）', '多线3（备用）')
        self.assertTrue(app._line_needs_relogin())

    def test_without_a_session_there_is_nothing_to_switch(self):
        app = _window('多线2（主线）', '')
        self.assertFalse(app._line_needs_relogin())
        self.assertEqual(app._line_session(), '')


class LineScriptTests(unittest.TestCase):
    def _armed_app(self, wanted='多线2（主线）', session=''):
        app = _window(wanted, session)
        app.bind_slot = mock.Mock(return_value=None)
        app.command_service = mock.Mock()
        app._ghost_hall_alive = mock.Mock(return_value=False)
        app._protocol_session_alive = mock.Mock(return_value=False)
        app._lab_root = mock.Mock(return_value=Path('/lab'))
        app._lab_async = mock.Mock()
        app.lab_nickname = mock.Mock(**{'get.return_value': '待秋至'})
        app.root = mock.Mock()
        return app

    def test_arm_writes_the_line_before_the_protocol_login(self):
        app = self._armed_app()
        app._lab_arm()
        label, script = app._lab_async.call_args[0][0], app._lab_async.call_args[0][1]
        self.assertIn('protocol-up', script)
        self.assertIn("line set '多线2（主线）'", script)
        self.assertLess(script.index('line set'), script.index('protocol-up'))
        self.assertIn('進房', label)

    def test_switching_line_asks_first_and_relogs_in(self):
        app = self._armed_app(wanted='多线2（主线）', session='多线3（备用）')
        app._protocol_session_alive = mock.Mock(return_value=True)
        with mock.patch('native_window.messagebox.askokcancel', return_value=True) as ask:
            app._lab_arm()
        self.assertTrue(ask.called)
        script = app._lab_async.call_args[0][1]
        self.assertIn('protocol-down', script)
        self.assertIn('protocol-up', script)
        self.assertIn("line set '多线2（主线）'", script)

    def test_switching_line_can_be_cancelled(self):
        app = self._armed_app(wanted='多线2（主线）', session='多线3（备用）')
        app._protocol_session_alive = mock.Mock(return_value=True)
        with mock.patch('native_window.messagebox.askokcancel', return_value=False):
            app._lab_arm()
        self.assertFalse(app._lab_async.called)

    def test_search_refuses_while_the_session_is_on_another_line(self):
        app = _window('多线2（主线）', '多线3（备用）')
        app._ghost_hall_alive = mock.Mock(return_value=False)
        app.lab_label = mock.Mock()
        app.lab_search_rooms()
        call = app.lab_label.configure.call_args
        text = call.kwargs.get('text') or (call[0][1] if len(call[0]) > 1 else '')
        self.assertIn('多线2（主线）', text)
        self.assertIn('多线3（备用）', text)


class LineStatusTests(unittest.TestCase):
    def _app(self, wanted, session):
        app = _window(wanted, session)
        app._lab_root = mock.Mock(return_value=Path('/lab'))
        app.line_status_label = mock.Mock()
        payload = {'configured': session, 'session': session, 'same': session == wanted}

        def fake_run(script, done, timeout=90):
            done(payload, '')

        app._lab_run_json = fake_run
        return app

    def _text(self, app):
        call = app.line_status_label.configure.call_args
        return call.kwargs.get('text') or (call[0][1] if len(call[0]) > 1 else '')

    def test_same_line_shows_plain_status(self):
        app = self._app('多线3（备用）', '多线3（备用）')
        app.lab_line_refresh()
        text = self._text(app)
        self.assertIn('多线3（备用）', text)
        self.assertNotIn('⚠', text)

    def test_other_line_warns_that_a_relogin_is_needed(self):
        app = self._app('多线2（主线）', '多线3（备用）')
        app.lab_line_refresh()
        text = self._text(app)
        self.assertIn('⚠', text)
        self.assertIn('多线2（主线）', text)
        self.assertIn('多线3（备用）', text)


class UnblockTests(unittest.TestCase):
    def test_unblock_calls_the_lab_command(self):
        app = _window()
        app._lab_root = mock.Mock(return_value=Path('/lab'))
        app._lab_run_json = mock.Mock()
        app.lab_label = mock.Mock()
        app.lab_unblock()
        script = app._lab_run_json.call_args[0][0]
        self.assertIn('sticky.sh unblock', script)

    def test_unblock_reports_the_result(self):
        app = _window()
        app._lab_root = mock.Mock(return_value=Path('/lab'))
        app.lab_label = mock.Mock()
        app._lab_run_json = mock.Mock()
        payload = {'ok': True, 'drained': 3, 'select_enabled': True,
                   'rooms_after': ['SGZWLB[风云]']}
        app._lab_run_json.side_effect = lambda script, done, timeout=90: done(payload, '')
        app.lab_unblock()
        call = app.lab_label.configure.call_args
        text = call.kwargs.get('text') or (call[0][1] if len(call[0]) > 1 else '')
        self.assertIn('3', text)
        self.assertIn('SGZWLB[风云]', text)


if __name__ == '__main__':
    unittest.main()
