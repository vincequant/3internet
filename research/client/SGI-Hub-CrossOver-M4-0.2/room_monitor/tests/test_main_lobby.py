import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.lobby import prefixes_conflict
from sgi_room_monitor.lobby_ops import run_ops
from sgi_room_monitor.main_lobby import (
    click_main_start, complete_main_login, ensure_main_line, reach_game_list,
    require_main_account, reset_login_mark, tree_targets,
)
from sgi_room_monitor.states import LIST_WINDOW_READY, NEEDS_USER, PENDING_LOGIN


def _main_cfg(folder, **extra):
    cfg = {
        'allow_main_account': True,
        'main_prefix': folder,
        'data_dir': folder,
        'hub_root': folder,
        'platform_line': '多线2（主线）',
        'platform_room': '三国对战房',
        'main_account_username': 'main-user',
    }
    cfg.update(extra)
    return cfg


class MainLobbyGuardTests(unittest.TestCase):
    def test_main_path_requires_explicit_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn('allow_main_account', require_main_account({
                'main_prefix': folder,
            }))
            self.assertIsNone(require_main_account({
                'allow_main_account': True,
                'main_prefix': folder,
            }))

    def test_monitor_guard_still_rejects_same_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            same = Path(folder)
            self.assertIn('相同', prefixes_conflict({
                'monitor_prefix': str(same),
                'main_prefix': str(same),
            }))

    def test_main_flag_does_not_disable_monitor_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            same = Path(folder)
            self.assertIn('相同', prefixes_conflict({
                'monitor_prefix': str(same),
                'main_prefix': str(same),
                'allow_main_account': True,
            }))

    def test_tree_prefers_multiline2_main(self):
        names = tree_targets({'platform_line': '多线2（主线）', 'platform_room': '三国对战房'})
        self.assertEqual(names[0], '三国对战房')
        self.assertIn('多线2（主线）', names)
        self.assertIn('多线2', names)


class MainLoginOnceTests(unittest.TestCase):
    def test_second_login_is_refused_after_mark(self):
        from sgi_room_monitor.main_lobby import _write_login_mark
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            _write_login_mark(cfg, 'submitted')
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'login': True, 'has_login_button': True, 'titles': ['登录'],
            }):
                with patch('sgi_room_monitor.main_lobby.run_main_ops') as ops:
                    second = complete_main_login(cfg)
            self.assertTrue(second.get('needs_user'))
            self.assertIn('不会再次交密码', second['message'])
            ops.assert_not_called()

    def test_captcha_stops_without_login(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'captcha': '验证码', 'login': True,
            }):
                with patch('sgi_room_monitor.main_lobby.run_main_ops') as ops:
                    result = complete_main_login(cfg)
            self.assertTrue(result['needs_user'])
            self.assertIn('验证码', result['message'])
            ops.assert_not_called()

    def test_protocol_already_logged_in_does_not_ui_login(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                    'already_logged_in': True, 'login': True, 'has_login_button': True,
                }):
                    with patch('sgi_room_monitor.main_lobby.complete_protocol_login') as proto:
                        with patch('sgi_room_monitor.main_lobby.complete_main_login') as ui:
                            result = reach_game_list(cfg, wait_lobby=1)
            self.assertTrue(result['needs_user'])
            self.assertIn('用户已经登录', result['message'])
            proto.assert_not_called()
            ui.assert_not_called()

    def test_already_logged_in_stops_without_login(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'already_logged_in': True, 'login': True, 'has_login_button': True,
            }):
                with patch('sgi_room_monitor.main_lobby.run_main_ops') as ops:
                    result = complete_main_login(cfg)
            self.assertTrue(result['needs_user'])
            self.assertIn('用户已经登录', result['message'])
            ops.assert_not_called()


class MainFlowTests(unittest.TestCase):
    def test_select_line_uses_main_tree_name(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            inspect = [
                {'logged_in': True, 'titles': ['当前用户'], 'trees': []},
                {'logged_in': True, 'titles': ['当前用户'], 'trees': []},
                {'logged_in': True, 'titles': ['当前用户', '多线2（主线）'],
                 'trees': [{'items': [{'text': '多线2（主线）', 'selected': True}]}]},
            ]
            with patch('sgi_room_monitor.main_lobby.inspect_main', side_effect=inspect):
                with patch('sgi_room_monitor.main_lobby.run_main_ops') as ops:
                    ops.return_value = {'payload': {'status': 'clicked', 'title': '多线2（主线）'}}
                    result = ensure_main_line(cfg)
            self.assertTrue(result['ok'])
            names = [call.args[1][1] for call in ops.call_args_list]
            self.assertIn('多线2（主线）', names)
            self.assertEqual(ops.call_args_list[1].args[1], ['--select-tree', '多线2（主线）'])

    def test_start_requires_game_select_not_sanpk_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'sanpk_running': True, 'game_select': False, 'trees': [], 'titles': [],
            }):
                with patch('sgi_room_monitor.main_lobby.running_in_prefix', return_value=True):
                    result = click_main_start(cfg)
            self.assertFalse(result['ok'])
            self.assertTrue(result.get('needs_user'))
            self.assertNotEqual(result['state'], LIST_WINDOW_READY)

    def test_in_match_window_counts_as_playable(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'sanpk_running': True, 'game_select': False, 'has_start': True,
                'logged_in': True, 'trees': [],
                'titles': ['当前用户', '房间用户(4)', '启动游戏', '三国志Internet联机版3.5'],
            }):
                result = click_main_start(cfg)
            self.assertTrue(result['ok'])
            self.assertEqual(result['state'], LIST_WINDOW_READY)
            self.assertIn('联机对局', result['message'])

    def test_reach_without_creds_is_pending_for_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            reset_login_mark(cfg)
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                    with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=True):
                        result = reach_game_list(cfg, wait_lobby=1)
            self.assertTrue(result['needs_user'])
            self.assertEqual(result['state'], PENDING_LOGIN)
            self.assertIn('creds-set', result['message'])
            self.assertIn('协议直连', result['message'])

    def test_ui_path_without_creds_starts_lobby(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder, force_ui_fallback=True)
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=True):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                               return_value={'ok': True}) as start:
                        with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                   return_value={'ok': True}):
                            with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                       return_value={'ok': True, 'needs_user': False}):
                                with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                           return_value={'ok': True}):
                                    with patch('sgi_room_monitor.main_lobby.click_main_start',
                                               return_value={
                                                   'ok': True, 'state': LIST_WINDOW_READY,
                                                   'message': '已核验',
                                               }):
                                        result = reach_game_list(cfg, wait_lobby=1)
            start.assert_called()
            self.assertTrue(result['ok'])
            self.assertNotIn('creds-set', result.get('message') or '')
            self.assertEqual(result.get('channel'), 'ui_fallback')

    def test_reach_reports_protocol_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            stages = []
            proto = {
                'ok': True, 'submitted': True, 'needs_user': False,
                'stage': 'protocol_enter', 'message': '协议已进入多线2',
                'room_name': '多线2', 'login_verified': True, 'entered': True,
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                        with patch('sgi_room_monitor.main_lobby.complete_protocol_login',
                                   return_value=(object(), proto)):
                            with patch('sgi_room_monitor.main_lobby.try_launch_playable_sanpk',
                                       return_value={'ok': True, 'message': 'StartServer'}):
                                with patch('sgi_room_monitor.main_lobby.wait_for_list', return_value={
                                    'state': LIST_WINDOW_READY, 'message': '已核验 SANPK 游戏选择窗口',
                                }):
                                    with patch('sgi_room_monitor.main_lobby._attach_sanguo_after_protocol',
                                               return_value={
                                                   'ok': True, 'lobby_attached': True, 'needs_user': False,
                                                   'message': '已核验 SANPK 游戏选择，大厅已进入多线2',
                                               }) as attach:
                                        result = reach_game_list(
                                            cfg, progress=lambda stage, message, payload: stages.append(stage))
            attach.assert_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result['state'], LIST_WINDOW_READY)
            self.assertEqual(result.get('channel'), 'protocol')
            self.assertTrue(result.get('lobby_attached'))
            self.assertIn('protocol_login', stages)
            self.assertIn('protocol_enter', stages)
            self.assertIn('start_game', stages)
            self.assertIn('list_ready', stages)

    def test_protocol_cold_start_skips_wine_inspect(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            proto = {
                'ok': True, 'submitted': True, 'needs_user': False,
                'stage': 'protocol_enter', 'message': '协议已进入多线2',
                'room_name': '多线2', 'login_verified': True, 'entered': True,
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                    with patch('sgi_room_monitor.main_lobby.running_in_prefix', return_value=False):
                        with patch('sgi_room_monitor.main_lobby.inspect_main') as inspect:
                            with patch('sgi_room_monitor.main_lobby.complete_protocol_login',
                                       return_value=(object(), proto)):
                                with patch('sgi_room_monitor.main_lobby.try_launch_playable_sanpk',
                                           return_value={'ok': True, 'message': 'StartServer'}):
                                    with patch('sgi_room_monitor.main_lobby.wait_for_list', return_value={
                                        'state': LIST_WINDOW_READY, 'message': '已核验 SANPK 游戏选择窗口',
                                    }):
                                        with patch(
                                            'sgi_room_monitor.main_lobby._attach_sanguo_after_protocol',
                                            return_value={
                                                'ok': True, 'lobby_attached': True, 'needs_user': False,
                                                'message': '已核验 SANPK 游戏选择，大厅已进入多线2',
                                            }):
                                            result = reach_game_list(cfg)
            inspect.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('channel'), 'protocol')

    def test_login_form_does_not_open_second_protocol_session(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                    'login': True, 'has_login_button': True, 'titles': ['登录'],
                }):
                    with patch('sgi_room_monitor.main_lobby.complete_protocol_login') as proto:
                        with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                   return_value={'ok': True}):
                            with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                       return_value={'ok': True}):
                                with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                           return_value={'ok': True, 'needs_user': False}):
                                    with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                               return_value={'ok': True}):
                                        with patch('sgi_room_monitor.main_lobby.click_main_start',
                                                   return_value={
                                                       'ok': True, 'state': LIST_WINDOW_READY,
                                                       'message': '已核验 SANPK 游戏选择窗口',
                                                   }):
                                            result = reach_game_list(cfg, wait_lobby=1)
            proto.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('fallback_reason'), 'lobby_owns_session')

    def test_force_ui_skips_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder, force_ui_fallback=True)
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.complete_protocol_login') as proto:
                        with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                   return_value={'ok': True}):
                            with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                       return_value={'ok': True}):
                                with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                           return_value={'ok': True, 'needs_user': False}):
                                    with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                               return_value={'ok': True}):
                                        with patch('sgi_room_monitor.main_lobby.click_main_start',
                                                   return_value={
                                                       'ok': True, 'state': LIST_WINDOW_READY,
                                                       'message': '已核验',
                                                   }):
                                            result = reach_game_list(cfg, wait_lobby=1)
            proto.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('channel'), 'ui_fallback')

    def test_unverified_binaries_skip_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.complete_protocol_login') as proto:
                        with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                   return_value={'ok': True}):
                            with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                       return_value={'ok': True}):
                                with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                           return_value={'ok': True, 'needs_user': False}):
                                    with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                               return_value={'ok': True}):
                                        with patch('sgi_room_monitor.main_lobby.click_main_start',
                                                   return_value={
                                                       'ok': True, 'state': LIST_WINDOW_READY,
                                                       'message': '已核验',
                                                   }):
                                            result = reach_game_list(cfg, wait_lobby=1)
            proto.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('channel'), 'ui_fallback')
            self.assertEqual(result.get('fallback_reason'), 'protocol_unready')

    def test_protocol_direct_runtime_flag_forces_ui(self):
        from sgi_room_monitor.main_lobby import launcher_config, use_protocol_chain
        with tempfile.TemporaryDirectory() as folder:
            cfg = launcher_config(folder, folder, folder, {'protocol_direct': False})
            self.assertTrue(cfg['force_ui_fallback'])
            self.assertFalse(use_protocol_chain(cfg))
            cfg_on = launcher_config(folder, folder, folder, {})
            self.assertFalse(cfg_on['force_ui_fallback'])

    def test_protocol_is_default_when_takeover_feasible(self):
        from sgi_room_monitor.main_lobby import use_protocol_chain
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            with patch('sgi_room_monitor.main_lobby.takeover_feasible',
                       return_value={'feasible': True}):
                self.assertTrue(use_protocol_chain(cfg))
            with patch.dict('os.environ', {'SGI_FORCE_UI_FALLBACK': '1'}):
                self.assertFalse(use_protocol_chain(cfg))
            self.assertFalse(use_protocol_chain(_main_cfg(folder, force_ui_fallback=True)))

    def test_reach_skips_protocol_when_lobby_logged_in(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            evidence = {
                'target_connected': True, 'list_window_ready': True,
                'observed_line': '多线2（主线）',
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                    'logged_in': True, 'has_start': True, 'titles': ['当前用户'],
                }):
                    with patch('sgi_room_monitor.main_lobby.complete_protocol_login') as proto:
                        with patch('sgi_room_monitor.main_lobby.ensure_main_line', return_value={
                            'ok': True, 'state': 'room_connected', 'evidence': evidence,
                        }):
                            with patch('sgi_room_monitor.main_lobby.click_main_start', return_value={
                                'ok': True, 'state': LIST_WINDOW_READY,
                                'message': '已核验 SANPK 游戏选择窗口', 'evidence': evidence,
                            }):
                                result = reach_game_list(cfg, wait_lobby=1)
            self.assertTrue(result['ok'])
            proto.assert_not_called()
            self.assertEqual(result.get('fallback_reason'), 'lobby_already_logged_in')

    def test_protocol_connect_fail_falls_back_to_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            evidence = {
                'target_connected': True, 'list_window_ready': True,
                'observed_line': '多线2（主线）',
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                        with patch('sgi_room_monitor.main_lobby.complete_protocol_login', return_value=(
                            None, {'ok': False, 'submitted': False, 'needs_user': False,
                                   'message': '协议登录服连接失败，将回退大厅界面'},
                        )):
                            with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                       return_value={'ok': True}):
                                with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                           return_value={'ok': True}):
                                    with patch('sgi_room_monitor.main_lobby.complete_main_login', return_value={
                                        'ok': True, 'state': 'lobby_logged_in', 'needs_user': False,
                                    }):
                                        with patch('sgi_room_monitor.main_lobby.ensure_main_line', return_value={
                                            'ok': True, 'state': 'room_connected', 'evidence': evidence,
                                        }):
                                            with patch('sgi_room_monitor.main_lobby.click_main_start',
                                                       return_value={
                                                           'ok': True, 'state': LIST_WINDOW_READY,
                                                           'message': '已核验 SANPK 游戏选择窗口',
                                                           'evidence': evidence,
                                                       }):
                                                result = reach_game_list(cfg, wait_lobby=1)
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('channel'), 'ui_fallback')

    def test_takeover_exception_releases_protocol_and_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            evidence = {
                'target_connected': True, 'list_window_ready': True,
                'observed_line': '多线2（主线）',
            }
            session = object()
            proto = {
                'ok': True, 'submitted': True, 'needs_user': False,
                'stage': 'protocol_enter', 'message': '协议已进入多线2',
                'login_verified': True, 'entered': True,
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                        with patch('sgi_room_monitor.main_lobby.complete_protocol_login',
                                   return_value=(session, proto)):
                            with patch('sgi_room_monitor.main_lobby.try_launch_playable_sanpk',
                                       side_effect=subprocess.TimeoutExpired(cmd=['wine'], timeout=20)):
                                with patch('sgi_room_monitor.main_lobby._release_protocol') as release:
                                    with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                               return_value={'ok': True}):
                                        with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                                   return_value={'ok': True}):
                                            with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                                       return_value={'ok': True, 'needs_user': False}):
                                                with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                                           return_value={'ok': True, 'evidence': evidence}):
                                                    with patch('sgi_room_monitor.main_lobby.click_main_start',
                                                               return_value={
                                                                   'ok': True, 'state': LIST_WINDOW_READY,
                                                                   'message': '已核验', 'evidence': evidence,
                                                               }):
                                                        result = reach_game_list(cfg, wait_lobby=1)
            release.assert_called()
            self.assertTrue(result['ok'])
            self.assertEqual(result.get('channel'), 'ui_fallback')
            self.assertEqual(result.get('fallback_reason'), 'takeover_error')

    def test_protocol_success_attaches_lobby_without_start_game(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            session = object()
            proto = {
                'ok': True, 'submitted': True, 'needs_user': False,
                'stage': 'protocol_enter', 'message': '协议已进入多线2',
                'login_verified': True, 'entered': True,
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                        with patch('sgi_room_monitor.main_lobby.complete_protocol_login',
                                   return_value=(session, proto)):
                            with patch('sgi_room_monitor.main_lobby.try_launch_playable_sanpk',
                                       return_value={'ok': True, 'proc': object()}):
                                with patch('sgi_room_monitor.main_lobby.wait_for_list', return_value={
                                    'state': LIST_WINDOW_READY, 'message': '已核验 SANPK 游戏选择窗口',
                                }):
                                    with patch('sgi_room_monitor.main_lobby._release_protocol') as release:
                                        with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                                   return_value={'ok': True}) as lobby:
                                            with patch('sgi_room_monitor.main_lobby.wait_lobby_ready',
                                                       return_value={'ok': True, 'info': {'login': True}}):
                                                with patch('sgi_room_monitor.main_lobby.complete_main_login',
                                                           return_value={'ok': True, 'needs_user': False}) as login:
                                                    with patch('sgi_room_monitor.main_lobby.ensure_main_line',
                                                               return_value={'ok': True, 'evidence': {
                                                                   'target_connected': True,
                                                                   'observed_line': '多线2（主线）',
                                                               }}) as line:
                                                        with patch('sgi_room_monitor.main_lobby.click_main_start') as start:
                                                            with patch('sgi_room_monitor.main_lobby.time.sleep'):
                                                                result = reach_game_list(cfg, wait_lobby=1)
            lobby.assert_called()
            login.assert_called()
            self.assertTrue(login.call_args.kwargs.get('allow_force'))
            line.assert_called()
            start.assert_not_called()
            release.assert_called_with(session)
            self.assertTrue(result['ok'])
            self.assertTrue(result.get('lobby_attached'))
            self.assertFalse(result.get('needs_user'))
            self.assertIn('大厅已进入多线2', result['message'])
            self.assertEqual(result.get('channel'), 'protocol')

    def test_protocol_attach_keeps_session_if_lobby_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            session = object()
            proto = {
                'ok': True, 'submitted': True, 'needs_user': False,
                'stage': 'protocol_enter', 'message': '协议已进入多线2',
                'login_verified': True, 'entered': True,
            }
            with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={}):
                    with patch('sgi_room_monitor.main_lobby.use_protocol_chain', return_value=True):
                        with patch('sgi_room_monitor.main_lobby.complete_protocol_login',
                                   return_value=(session, proto)):
                            with patch('sgi_room_monitor.main_lobby.try_launch_playable_sanpk',
                                       return_value={'ok': True, 'proc': object()}):
                                with patch('sgi_room_monitor.main_lobby.wait_for_list', return_value={
                                    'state': LIST_WINDOW_READY, 'message': '已核验 SANPK 游戏选择窗口',
                                }):
                                    with patch('sgi_room_monitor.main_lobby._release_protocol') as release:
                                        with patch('sgi_room_monitor.main_lobby.ensure_main_lobby_running',
                                                   return_value={'ok': False, 'error': '找不到 Wine 或主号大厅'}):
                                            result = reach_game_list(cfg, wait_lobby=1)
            release.assert_not_called()
            self.assertTrue(result['ok'])
            self.assertTrue(result.get('needs_user'))
            self.assertFalse(result.get('lobby_attached'))
            self.assertIn('协议会话仍在线', result['message'])

    def test_complete_main_login_force_when_already_online(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            inspect = [
                {'already_logged_in': True, 'login': True, 'has_login_button': True, 'titles': ['用户已经登录']},
                {'logged_in': True, 'has_start': True, 'titles': ['当前用户']},
            ]
            with patch('sgi_room_monitor.main_lobby.inspect_main', side_effect=inspect):
                with patch('sgi_room_monitor.main_lobby.run_main_ops') as ops:
                    ops.side_effect = [
                        {'payload': {'status': 'checked', 'checked': True}},
                        {'payload': {'status': 'submitted'}},
                    ]
                    with patch('sgi_room_monitor.main_lobby.missing_credentials', return_value=False):
                        result = complete_main_login(cfg, allow_force=True)
            self.assertTrue(result['ok'])
            self.assertEqual(ops.call_args_list[0].args[1], ['--force'])
            self.assertEqual(ops.call_args_list[1].args[1], ['--login'])

    def test_login_mark_resets_after_logged_in(self):
        from sgi_room_monitor.main_lobby import _login_mark, _write_login_mark
        with tempfile.TemporaryDirectory() as folder:
            cfg = _main_cfg(folder)
            _write_login_mark(cfg, 'submitted')
            self.assertTrue(_login_mark(cfg).get('submitted'))
            with patch('sgi_room_monitor.main_lobby.inspect_main', return_value={
                'logged_in': True, 'has_start': True, 'titles': ['当前用户'],
            }):
                result = complete_main_login(cfg)
            self.assertTrue(result['ok'])
            self.assertFalse(_login_mark(cfg).get('submitted'))

    def test_reach_reports_stages(self):
        self.test_reach_reports_protocol_stages()


class LobbyOpsWindowsTests(unittest.TestCase):
    def test_windows_uses_native_python_not_wine(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            captured = {}

            def fake_run(cmd, env=None, **kwargs):
                captured['cmd'] = cmd
                captured['env'] = env
                return type('R', (), {'stdout': '{"status":"inspect"}', 'stderr': ''})()

            with patch('sgi_room_monitor.lobby_ops.sys.platform', 'win32'):
                with patch('sgi_room_monitor.lobby_ops.subprocess.run', side_effect=fake_run):
                    result = run_ops({'hub_root': folder}, [], prefix)
            self.assertEqual(result['payload']['status'], 'inspect')
            self.assertTrue(
                captured['cmd'][0] == sys.executable
                or str(captured['cmd'][0]).endswith('sgi-py32.exe'))
            self.assertFalse(any(part == 'wine' or str(part).endswith('/wine') for part in captured['cmd']))
            self.assertEqual(captured['env']['SGI_ALLOWED_IMAGE_ROOT'], str(prefix))
            self.assertFalse((prefix / 'room_monitor' / '.login.json').exists())

    def test_cred_file_is_wiped(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            leftover = {}

            def fake_run(cmd, env=None, **kwargs):
                leftover['exists_during'] = (prefix / 'drive_c/sgi/room_monitor/.login.json').is_file()
                leftover['text'] = (prefix / 'drive_c/sgi/room_monitor/.login.json').read_text(encoding='utf-8')
                return type('R', (), {'stdout': '{"status":"submitted"}', 'stderr': ''})()

            with patch('sgi_room_monitor.lobby_ops.sys.platform', 'darwin'):
                with patch('sgi_room_monitor.lobby_ops._ops_command', return_value=(
                    {'SGI_MONITOR_CRED_FILE': 'x'}, ['true'], None)):
                    with patch('sgi_room_monitor.lobby_ops.subprocess.run', side_effect=fake_run):
                        run_ops({}, ['--login'], prefix, with_creds=True,
                                creds_loader=lambda: {'username': 'u', 'password': 'hidden-secret'})
            self.assertTrue(leftover['exists_during'])
            self.assertIn('hidden-secret', leftover['text'])
            self.assertFalse((prefix / 'drive_c/sgi/room_monitor/.login.json').exists())


class WineImageFilterTests(unittest.TestCase):
    def test_allowed_image_is_fail_closed(self):
        src = (Path(__file__).resolve().parents[1] / 'sgi_room_monitor/wine_lobby_ops.py').read_text(encoding='utf-8')
        start = src.index('def allowed_image')
        end = src.index('\ndef children')
        ns = {'os': __import__('os')}
        exec(src[start:end], ns)
        with patch.dict('os.environ', {'SGI_ALLOWED_IMAGE_ROOT': r'C:\sgi\run-3.5'}):
            self.assertTrue(ns['allowed_image'](r'C:\sgi\run-3.5\SANGUO.exe'))
            self.assertFalse(ns['allowed_image'](r'C:\other\SANGUO.exe'))
            self.assertFalse(ns['allowed_image'](r'C:\sgi\run-3.5\notepad.exe'))
            self.assertFalse(ns['allowed_image'](''))


if __name__ == '__main__':
    unittest.main()
