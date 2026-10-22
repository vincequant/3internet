"""Start the isolated lobby/game. Never touch the main prefix or its processes."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .credentials import load_credentials, missing_credentials
from .evidence import connection_evidence, lifecycle_state
from .lobby_ops import run_ops
from .platform import running_in_prefix
from .provision import default_paths, wine_env
from .states import (
    GAME_STARTING, LIST_WINDOW_READY, LOBBY_LOGGED_IN, LOGGING_IN, NEEDS_USER,
    PENDING_LOGIN, ROOM_CONNECTED,
)


CAPTCHA_MARKERS = ('验证码', '安全验证', '人机验证', '异常登录', '账号异常')
LOGIN_MARK = 'login-attempted.json'


def prefixes_conflict(config):
    monitor = Path(config.get('monitor_prefix') or '').expanduser()
    main = Path(config.get('main_prefix') or '').expanduser()
    if not config.get('monitor_prefix'):
        return '未配置独立 monitor_prefix'
    if not monitor.is_dir():
        return f'监控 Wine prefix 不存在: {monitor}'
    if config.get('main_prefix') and monitor.resolve() == main.resolve():
        return '监控 prefix 与主号相同'
    return None


def prefix_in_command(command, prefix):
    if not prefix:
        return False
    return str(Path(prefix).expanduser()) in (command or '')


def ensure_platform(config):
    conflict = prefixes_conflict(config)
    if conflict:
        return {'state': NEEDS_USER, 'message': conflict, 'needs_user': True}
    prefix = str(Path(config['monitor_prefix']).expanduser())
    info = inspect_lobby(config) if running_in_prefix(prefix, 'SANGUO.exe') or running_in_prefix(prefix, 'SANPK.exe') else {}
    if info and not info.get('error'):
        state, evidence = lifecycle_state(info, config)
        if state == LIST_WINDOW_READY:
            return {'state': LIST_WINDOW_READY, 'message': '已核验监控实例的游戏选择窗口',
                    'needs_user': False, 'evidence': evidence}
        if state in (ROOM_CONNECTED, LOBBY_LOGGED_IN, GAME_STARTING):
            return {'state': state, 'message': _state_message(state, evidence),
                    'needs_user': False, 'evidence': evidence}
    if missing_credentials(config):
        return {'state': PENDING_LOGIN, 'message': '缺少小号凭据。请执行 sgi-room-monitor creds-set。',
                'needs_user': True}
    if not running_in_prefix(prefix, 'SANGUO.exe'):
        launched = launch_lobby(config)
        if launched.get('error'):
            return {'state': NEEDS_USER, 'message': launched['error'], 'needs_user': True}
    login = complete_login(config)
    if login.get('needs_user'):
        return login
    return {'state': LOBBY_LOGGED_IN, 'message': login.get('message') or '监控大厅已登录',
            'needs_user': False, 'evidence': login.get('evidence')}


def launch_lobby(config):
    paths = default_paths()
    wine = Path(paths['wine'])
    if not wine.is_file():
        return {'error': '找不到 Wine 可执行文件'}
    prefix = Path(config['monitor_prefix']).expanduser()
    lobby = prefix / 'drive_c/sgi/run-3.5/SANGUO.exe'
    if not lobby.is_file():
        return {'error': f'监控 prefix 内没有大厅: {lobby}'}
    env = wine_env(wine, prefix)
    subprocess.Popen(
        [str(wine), str(lobby)],
        env=env,
        cwd=str(lobby.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if running_in_prefix(str(prefix), 'SANGUO.exe'):
            return {'ok': True, 'message': '已在独立 prefix 启动大厅'}
        time.sleep(1)
    return {'error': '监控大厅启动超时'}


def complete_login(config):
    info = inspect_lobby(config)
    if info.get('error'):
        return {'state': NEEDS_USER, 'message': info['error'], 'needs_user': True}
    if info.get('captcha'):
        return {'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'], 'needs_user': True}
    if info.get('already_logged_in'):
        return {'state': NEEDS_USER,
                'message': '小号提示「用户已经登录」。请在监控大厅（不是主号）勾选「强制登录」后点登录，或先在另一台已登录的机器退出。服务不会再自动交密码。',
                'needs_user': True}
    if info.get('logged_in') or info.get('has_start'):
        return {'state': LOBBY_LOGGED_IN, 'message': '监控大厅已登录', 'needs_user': False,
                'evidence': connection_evidence(info, config)}
    mark = _login_mark(config)
    if mark.get('submitted'):
        return {'state': NEEDS_USER,
                'message': '已提交过一次登录但仍停在登录窗，不会再次交密码。请本人处理验证码或错误提示。',
                'needs_user': True}
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and not info.get('has_login_button'):
        time.sleep(2)
        info = inspect_lobby(config)
        if info.get('logged_in') or info.get('has_start'):
            return {'state': LOBBY_LOGGED_IN, 'message': '监控大厅已登录', 'needs_user': False,
                    'evidence': connection_evidence(info, config)}
        if info.get('captcha'):
            return {'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'], 'needs_user': True}
    submitted = run_wine_ops(config, ['--login'], with_creds=True)
    payload = submitted.get('payload') or {}
    _write_login_mark(config, payload.get('status') or submitted.get('error') or 'unknown')
    if payload.get('status') in ('logged_in',):
        return {'state': LOBBY_LOGGED_IN, 'message': '监控大厅已登录', 'needs_user': False}
    if payload.get('status') != 'submitted':
        return {'state': NEEDS_USER,
                'message': payload.get('message') or submitted.get('error') or '登录未提交',
                'needs_user': True}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(2)
        info = inspect_lobby(config)
        if info.get('captcha'):
            return {'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'], 'needs_user': True}
        if info.get('already_logged_in'):
            return _already_online()
        if info.get('logged_in') or info.get('has_start'):
            return {'state': LOBBY_LOGGED_IN, 'message': '监控大厅已登录', 'needs_user': False,
                    'evidence': connection_evidence(info, config)}
        if not info.get('login') and info.get('titles'):
            return {'state': LOBBY_LOGGED_IN, 'message': '登录窗已关闭', 'needs_user': False}
    return {'state': NEEDS_USER, 'message': '登录已提交一次，但仍未见已登录界面。请本人查看监控大厅。',
            'needs_user': True}


def _already_online():
    return {'state': NEEDS_USER, 'needs_user': True,
            'message': '小号提示「用户已经登录」。请在监控大厅（不是主号窗口）勾选「强制登录」后点登录，或先在另一台已登录的机器退出。服务不会再自动交密码。'}


def ensure_target_room(config):
    """Select 多线2 on the monitor lobby tree. Config labels are targets, not proof."""
    conflict = prefixes_conflict(config)
    if conflict:
        return {'ok': False, 'state': NEEDS_USER, 'message': conflict, 'needs_user': True}
    info = inspect_lobby(config)
    if info.get('error'):
        return {'ok': False, 'state': NEEDS_USER, 'message': info['error'], 'needs_user': True}
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                'needs_user': True}
    evidence = connection_evidence(info, config)
    if evidence.get('target_connected'):
        return {'ok': True, 'state': ROOM_CONNECTED,
                'message': '大厅树已选中 ' + (evidence.get('observed_line') or '目标线路'),
                'evidence': evidence}
    last = None
    for name in _tree_targets(config):
        last = run_wine_ops(config, ['--select-tree', name])
        payload = last.get('payload') or {}
        if payload.get('status') == 'clicked':
            time.sleep(1.2)
            info = inspect_lobby(config)
            evidence = connection_evidence(info, config)
            if evidence.get('target_connected'):
                return {'ok': True, 'state': ROOM_CONNECTED,
                        'message': '已进入 ' + (evidence.get('observed_line') or name),
                        'evidence': evidence}
    return {'ok': False, 'state': LOBBY_LOGGED_IN, 'needs_user': True,
            'message': (last or {}).get('payload', {}).get('message')
            or (last or {}).get('error')
            or '未能核验已进入多线2。请在监控小号大厅（不是主号）点「多线2（主线）」。',
            'evidence': evidence}


def click_start_game(config):
    """Start SANPK only on the monitor lobby. SANPK process alone is not list-ready."""
    conflict = prefixes_conflict(config)
    if conflict:
        return {'ok': False, 'state': NEEDS_USER, 'message': conflict}
    prefix = str(Path(config['monitor_prefix']).expanduser())
    info = inspect_lobby(config)
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                'needs_user': True}
    evidence = connection_evidence(info, config)
    if info.get('game_select') and evidence.get('target_connected'):
        return {'ok': True, 'state': LIST_WINDOW_READY,
                'message': '已核验监控实例的游戏选择窗口', 'evidence': evidence}
    if info.get('game_select') and not evidence.get('target_connected'):
        return {'ok': False, 'state': GAME_STARTING, 'needs_user': True,
                'message': '已有游戏选择窗口，但未核验多线2连接。空白列表不能当有效空。',
                'evidence': evidence}
    if running_in_prefix(prefix, 'SANPK.exe') and not info.get('game_select'):
        return {'ok': False, 'state': GAME_STARTING,
                'message': '监控 SANPK 已在跑，但未见游戏选择窗口，不能当作列表就绪',
                'evidence': evidence}
    if not running_in_prefix(prefix, 'SANGUO.exe'):
        return {'ok': False, 'state': PENDING_LOGIN, 'message': '监控大厅未运行'}
    entered = ensure_target_room(config)
    if not entered.get('ok'):
        return entered
    started = run_wine_ops(config, ['--start-game'])
    payload = started.get('payload') or {}
    if payload.get('status') != 'clicked':
        return {'ok': False, 'state': ROOM_CONNECTED, 'needs_user': True,
                'message': payload.get('message') or started.get('error')
                or '未点到启动游戏。请在监控小号大厅进入目标房间后点「启动游戏」。',
                'evidence': entered.get('evidence')}
    waited = wait_for_list(config, timeout=90)
    waited['ok'] = waited.get('state') == LIST_WINDOW_READY
    return waited


def inspect_lobby(config):
    result = run_wine_ops(config, [])
    if result.get('error'):
        return {'error': result['error']}
    return result.get('payload') or {}


def run_wine_ops(config, flags, with_creds=False, timeout=40):
    """Monitor-only wrapper: always uses monitor_prefix. Main account uses main_lobby."""
    prefix = Path(config['monitor_prefix']).expanduser()
    return run_ops(
        config, flags, prefix,
        with_creds=with_creds,
        creds_loader=(lambda: load_credentials(config, prompt=False)) if with_creds else None,
        cred_error='小号凭据不完整',
        timeout=timeout,
    )


def detect_user_block(titles):
    text = ' '.join(titles or [])
    for marker in CAPTCHA_MARKERS:
        if marker in text:
            return f'需要本人处理：{marker}'
    return None


def wait_for_list(config, timeout=90):
    prefix = str(Path(config.get('monitor_prefix') or '').expanduser())
    deadline = time.monotonic() + timeout
    saw_sanpk = False
    last = {}
    while time.monotonic() < deadline:
        info = inspect_lobby(config)
        last = connection_evidence(info, config)
        if info.get('game_select') and last.get('target_connected'):
            return {'state': LIST_WINDOW_READY, 'message': '已核验游戏选择窗口且大厅在目标线路',
                    'evidence': last}
        if info.get('game_select'):
            return {'state': GAME_STARTING, 'needs_user': True,
                    'message': '游戏选择已出现，但未核验多线2，不能报有效空列表',
                    'evidence': last}
        if running_in_prefix(prefix, 'SANPK.exe'):
            saw_sanpk = True
        time.sleep(2)
    if saw_sanpk:
        return {'state': GAME_STARTING, 'needs_user': True,
                'message': '监控 SANPK 已出现但未见已核验的游戏选择窗口', 'evidence': last}
    return {'state': GAME_STARTING, 'message': '等待游戏选择超时', 'needs_user': True,
            'evidence': last}


def _tree_targets(config):
    titles = []
    room = (config.get('platform_room') or '').strip()
    line = (config.get('platform_line') or '').strip()
    if room:
        titles.append(room)
    if '多线2' in line:
        titles.append('多线2（主线）')
        titles.append('多线2')
    elif line:
        titles.append(line)
    return titles


def _wanted_titles(config):
    return _tree_targets(config) + ['游戏房间']


def _state_message(state, evidence):
    evidence = evidence or {}
    if state == LIST_WINDOW_READY:
        return '已核验游戏选择窗口'
    if state == ROOM_CONNECTED:
        return '大厅树已选中 ' + (evidence.get('observed_line') or '目标线路')
    if state == GAME_STARTING:
        return '游戏已启动，尚未核验游戏选择窗口'
    if state == LOGGING_IN:
        return '正在登录监控大厅'
    return '监控大厅已登录'


def _login_mark(config):
    path = Path(config.get('data_dir') or '') / LOGIN_MARK
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {'submitted': True}


def _write_login_mark(config, status):
    path = Path(config.get('data_dir') or '') / LOGIN_MARK
    if not path.parent.is_dir():
        return
    path.write_text(json.dumps({'submitted': True, 'status': status, 'at': time.time()},
                               ensure_ascii=False) + '\n', encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass
