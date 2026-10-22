"""Explicit main-account lobby automation. Does not lift monitor prefix guards."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .credentials import load_credentials, missing_credentials
from .evidence import connection_evidence
from .lobby_ops import inspect_prefix, run_ops
from .platform import running_in_prefix
from .protocol_session import public_session_view
from .sanpk_takeover import _HELD, takeover_feasible, try_launch_playable_sanpk
from .states import (
    GAME_STARTING, LIST_WINDOW_READY, LOBBY_LOGGED_IN, NEEDS_USER,
    PENDING_LOGIN, ROOM_CONNECTED,
)


LOGIN_MARK = 'main-login-attempted.json'
DEFAULT_LINE = '多线2（主线）'
DEFAULT_ROOM = '三国对战房'


def require_main_account(config):
    """Main path is opt-in. Sharing a prefix with the monitor is allowed only here."""
    if not config or not config.get('allow_main_account'):
        return '主号自动化须显式 allow_main_account，不会默认使用监控 prefix'
    prefix = Path(config.get('main_prefix') or '').expanduser()
    if not config.get('main_prefix'):
        return '未配置 main_prefix'
    if not prefix.is_dir():
        return f'主号 prefix 不存在: {prefix}'
    return None


def operating_prefix(config):
    return str(Path(config['main_prefix']).expanduser())


def inspect_main(config, timeout=40):
    err = require_main_account(config)
    if err:
        return {'error': err}
    return inspect_prefix(config, operating_prefix(config), timeout=timeout)


def run_main_ops(config, flags, with_creds=False, timeout=40):
    err = require_main_account(config)
    if err:
        return {'error': err}

    def loader():
        return load_credentials(config, prompt=False, kind='main')

    return run_ops(
        config, flags, operating_prefix(config),
        with_creds=with_creds,
        creds_loader=loader if with_creds else None,
        cred_error='主号凭据不完整',
        timeout=timeout,
    )


def tree_targets(config):
    titles = []
    room = (config.get('platform_room') or DEFAULT_ROOM).strip()
    line = (config.get('platform_line') or DEFAULT_LINE).strip()
    if room:
        titles.append(room)
    if '多线2' in line:
        titles.append('多线2（主线）')
        titles.append('多线2')
    elif line:
        titles.append(line)
    return titles


def reach_game_list(config, progress=None, wait_lobby=60):
    """Protocol login+enter first; SANPK via takeover or minimal UI fallback."""
    def report(stage, message, **extra):
        payload = {
            'stage': stage,
            'message': message,
            'needs_user': bool(extra.get('needs_user')),
            'ok': extra.get('ok', False),
            'state': extra.get('state'),
            'event': extra.get('event') or ('needs_user' if extra.get('needs_user') else 'auto_enter'),
            'channel': extra.get('channel') or '',
        }
        for key in ('game_name', 'room_name', 'game_id', 'room_id'):
            if extra.get(key) not in (None, ''):
                payload[key] = extra[key]
        if extra.get('evidence') is not None:
            payload['evidence'] = extra['evidence']
        if extra.get('fallback_reason') is not None:
            payload['fallback_reason'] = extra['fallback_reason']
        if progress:
            progress(stage, message, public_session_view(payload))
        return payload

    err = require_main_account(config)
    if err:
        result = report('guard', err, needs_user=True, state=NEEDS_USER)
        result.update(ok=False, state=NEEDS_USER, needs_user=True)
        return result
    prefix = operating_prefix(config)
    reset_login_mark(config)
    protocol = use_protocol_chain(config)
    lobby_up = running_in_prefix(prefix, 'SANGUO.exe')
    game_up = running_in_prefix(prefix, 'SANPK.exe')
    if protocol and not lobby_up and not game_up:
        info = {}
    else:
        report('wait_lobby', '正在查看主号大厅状态…')
        info = inspect_main(config, timeout=6 if protocol else 40)
        if info.get('error') and protocol:
            info = {}
    if info.get('captcha'):
        result = report('wait_lobby', '需要本人处理：' + info['captcha'],
                        needs_user=True, state=NEEDS_USER)
        result.update(ok=False, state=NEEDS_USER, needs_user=True)
        return result
    if info.get('already_logged_in'):
        result = report('login', _already_online()['message'], needs_user=True, state=NEEDS_USER)
        result.update(_already_online())
        return result
    if info.get('logged_in') or info.get('has_start') or info.get('game_select'):
        return _ui_enter_and_start(config, report, prefix, fallback_reason='lobby_already_logged_in')
    if info.get('login') or info.get('has_login_button'):
        report('login', '大厅已在登录窗，保持单会话，走界面登录…', channel='ui_fallback',
               fallback_reason='lobby_owns_session')
        return _ui_full_path(config, report, prefix, wait_lobby,
                             fallback_reason='lobby_owns_session')

    if not use_protocol_chain(config):
        report('login', '协议直连已关，走大厅界面登录…', channel='ui_fallback',
               fallback_reason='protocol_unready')
        return _ui_full_path(config, report, prefix, wait_lobby,
                             fallback_reason='protocol_unready')
    if missing_credentials(config, kind='main'):
        message = '协议直连需要钥匙串主号凭据。请执行 sgi_wine_launcher.py creds-set，或关掉「协议直连进游戏」。'
        result = report('creds', message, needs_user=True, state=PENDING_LOGIN,
                        channel='protocol')
        result.update(ok=False, state=PENDING_LOGIN, needs_user=True)
        return result

    report('protocol_login', '正在用钥匙串凭据协议登录大厅…', channel='protocol')
    session, proto = complete_protocol_login(config)
    if proto.get('needs_user'):
        _release_protocol(session)
        result = report(
            proto.get('stage') or 'protocol_login', proto.get('message') or '协议登录需要本人处理',
            needs_user=True, state=proto.get('state') or NEEDS_USER, channel='protocol')
        result.update(public_session_view(proto))
        result.update(ok=False, needs_user=True)
        return result
    if not proto.get('ok') and not proto.get('submitted'):
        _release_protocol(session)
        reset_login_mark(config)
        report('login', '协议登录未发出，回退大厅界面登录…', channel='ui_fallback',
               fallback_reason=proto.get('message') or 'protocol_connect')
        return _ui_full_path(config, report, prefix, wait_lobby,
                             fallback_reason=proto.get('message') or 'protocol_connect')
    if not proto.get('ok'):
        _release_protocol(session)
        result = report(
            proto.get('stage') or 'protocol_login', proto.get('message') or '协议登录失败',
            needs_user=True, state=NEEDS_USER, channel='protocol')
        result.update(public_session_view(proto))
        result.update(ok=False, needs_user=True)
        return result

    report('protocol_enter', proto.get('message') or '协议已进入多线2',
           state=ROOM_CONNECTED, channel='protocol',
           game_name=proto.get('game_name'), room_name=proto.get('room_name'),
           game_id=proto.get('game_id'), room_id=proto.get('room_id'))
    report('start_game', '协议已进线，正在用原版 StartServer 拉起 SANPK…',
           state=GAME_STARTING, channel='protocol')
    takeover = {'ok': False, 'reason': 'sanpk_takeover'}
    try:
        takeover = try_launch_playable_sanpk(prefix, session, config=config) or takeover
    except Exception:
        _release_protocol(session)
        reset_login_mark(config)
        report(
            'start_game',
            '协议会话已关闭，回退大厅登录（不会与协议并行）。',
            state=GAME_STARTING, channel='ui_fallback',
            fallback_reason='takeover_error')
        return _ui_full_path(config, report, prefix, wait_lobby,
                             fallback_reason='takeover_error')
    if takeover.get('ok'):
        _HELD.append(takeover.get('proc'))
        waited = wait_for_list(config, timeout=90, require_lobby=False, interval=0.4)
        if waited.get('state') == LIST_WINDOW_READY:
            reset_login_mark(config)
            attached = _attach_sanguo_after_protocol(config, report, prefix, session)
            message = attached.get('message') or waited.get('message') or '已核验 SANPK 游戏选择窗口'
            needs_lobby = bool(attached.get('needs_user') and not attached.get('lobby_attached'))
            result = report(
                'list_ready', message, state=LIST_WINDOW_READY, ok=True,
                event='needs_user' if needs_lobby else 'list_ready',
                channel='protocol', needs_user=needs_lobby)
            result.update(waited)
            result.update(attached)
            result.update(ok=True, state=LIST_WINDOW_READY, prefix=prefix, channel='protocol')
            return result
        _stop_takeover(takeover)
    _release_protocol(session)
    reset_login_mark(config)
    report(
        'start_game',
        '协议会话已关闭，回退大厅登录（不会与协议并行）。',
        state=GAME_STARTING, channel='ui_fallback',
        fallback_reason=takeover.get('reason') or 'sanpk_takeover')
    return _ui_full_path(config, report, prefix, wait_lobby,
                         fallback_reason=takeover.get('reason') or 'sanpk_takeover')


def use_protocol_chain(config):
    if (os.environ.get('SGI_FORCE_UI_FALLBACK') or '').strip() == '1':
        return False
    if config.get('force_ui_fallback'):
        return False
    check = takeover_feasible(operating_prefix(config), hub_root=config.get('hub_root'))
    return bool(check.get('feasible'))


def _release_protocol(session):
    if session is None:
        return
    session.close(logout=True)


def _attach_sanguo_after_protocol(config, report, prefix, session):
    """Keep SANPK; log the official lobby in so 平台 房间用户 can see this account.

    Protocol TCP 25001 is not the SANGUO window. Other players asked how someone
    entered GAME without the platform; attach SANGUO after StartServer and do
    not click 启动游戏 again. If the lobby window never appears, keep the hall
    TCP session so occupancy is not dropped for nothing.
    """
    report(
        'attach_lobby', '协议已进入游戏，正在登录大厅让平台看得到人…',
        state=LIST_WINDOW_READY, channel='protocol')
    launched = ensure_main_lobby_running(config)
    if not launched.get('ok'):
        _HELD.append(session)
        return {
            'ok': True, 'lobby_attached': False, 'needs_user': True,
            'message': (
                '已核验 SANPK 游戏选择，但未能启动大厅：'
                + (launched.get('error') or '未知错误')
                + '。协议会话仍在线。'
            ),
        }
    ready = wait_lobby_ready(config, timeout=60, allow_already_online=True)
    if ready.get('needs_user') and not ready.get('already_logged_in'):
        _HELD.append(session)
        return {
            'ok': True, 'lobby_attached': False, 'needs_user': True,
            'message': (
                '已核验 SANPK 游戏选择。大厅未就绪：'
                + (ready.get('message') or '')
                + '。协议会话仍在线。'
            ),
        }
    _release_protocol(session)
    time.sleep(1.2)
    if ready.get('info', {}).get('logged_in') or ready.get('info', {}).get('has_start'):
        entered = ensure_main_line(config)
        if entered.get('ok'):
            return {
                'ok': True, 'lobby_attached': True, 'needs_user': False,
                'message': '已核验 SANPK 游戏选择，大厅已进入多线2',
                'evidence': entered.get('evidence'),
            }
        return {
            'ok': True, 'lobby_attached': False, 'needs_user': True,
            'message': '已核验 SANPK 游戏选择。大厅已开但未进入多线2：'
            + (entered.get('message') or ''),
            'evidence': entered.get('evidence'),
        }
    login = complete_main_login(config, allow_force=True)
    if login.get('needs_user') or not login.get('ok'):
        return {
            'ok': True, 'lobby_attached': False, 'needs_user': True,
            'message': '已核验 SANPK 游戏选择。请在大厅登录（平台可见）：'
            + (login.get('message') or ''),
        }
    entered = ensure_main_line(config)
    if not entered.get('ok'):
        return {
            'ok': True, 'lobby_attached': False, 'needs_user': True,
            'message': '已核验 SANPK 游戏选择。大厅已登录但未进入多线2：'
            + (entered.get('message') or ''),
            'evidence': entered.get('evidence'),
        }
    return {
        'ok': True, 'lobby_attached': True, 'needs_user': False,
        'message': '已核验 SANPK 游戏选择，大厅已进入多线2',
        'evidence': entered.get('evidence'),
    }


def _stop_takeover(takeover):
    proc = (takeover or {}).get('proc')
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass


def ensure_main_lobby_running(config, timeout=45):
    prefix = operating_prefix(config)
    if running_in_prefix(prefix, 'SANGUO.exe'):
        return {'ok': True}
    wine = Path(config.get('wine') or '')
    if sys.platform == 'win32':
        exe = Path(prefix) / 'SANGUO.exe'
        if not exe.is_file():
            exe = Path(prefix) / 'drive_c/sgi/run-3.5/SANGUO.exe'
        if not exe.is_file():
            return {'ok': False, 'error': '主号目录没有 SANGUO.exe'}
        cmd = [str(exe)]
        env = dict(os.environ)
        cwd = str(exe.parent)
    else:
        from .provision import default_paths, wine_env
        if not wine.is_file():
            wine = Path(default_paths().get('wine') or '')
        exe = Path(prefix) / 'drive_c/sgi/run-3.5/SANGUO.exe'
        if not wine.is_file() or not exe.is_file():
            return {'ok': False, 'error': '找不到 Wine 或主号大厅'}
        cmd = [str(wine), str(exe)]
        env = wine_env(wine, prefix)
        cwd = str(exe.parent)
    subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if running_in_prefix(prefix, 'SANGUO.exe'):
            return {'ok': True}
        time.sleep(1)
    return {'ok': False, 'error': '主号大厅启动超时'}


def complete_protocol_login(config):
    """One protocol password submit. Never retries. Returns (session_or_None, result)."""
    mark = _login_mark(config)
    if mark.get('submitted'):
        return None, {
            'ok': False, 'submitted': True, 'needs_user': True, 'state': NEEDS_USER,
            'stage': 'protocol_login',
            'message': '已提交过一次登录但仍未完成，不会再次交密码。请本人处理验证码或错误提示。',
        }
    creds = load_credentials(config, prompt=False, kind='main')
    username = (creds.get('username') or '').strip()
    password = creds.get('password') or ''
    if not username or not password:
        return None, {
            'ok': False, 'submitted': False, 'needs_user': True, 'state': PENDING_LOGIN,
            'stage': 'creds',
            'message': '缺少主号凭据。请执行 sgi_wine_launcher.py creds-set（写入钥匙串，不进仓库）。',
        }
    from .protocol_session import HallSession
    session = HallSession()
    host = (config.get('hall_host') or '').strip() or None
    port = config.get('hall_port')
    kwargs = {
        'game_title': (config.get('platform_room') or DEFAULT_ROOM).strip() or DEFAULT_ROOM,
        'line_title': '多线2',
        'timeout': int(config.get('protocol_timeout') or 12),
    }
    if host:
        kwargs['host'] = host
    if port:
        kwargs['port'] = int(port)
    try:
        result = session.login_and_enter(username, password, **kwargs)
    finally:
        password = None
        creds = None
    if result.get('submitted'):
        _write_login_mark(config, result.get('stage') or 'protocol_submitted')
    if result.get('ok'):
        result['state'] = ROOM_CONNECTED
        return session, result
    session.close(logout=bool(result.get('login_verified')))
    result.setdefault('state', NEEDS_USER if result.get('submitted') else PENDING_LOGIN)
    return None, result


def _ui_full_path(config, report, prefix, wait_lobby, fallback_reason='protocol_connect'):
    launched = ensure_main_lobby_running(config)
    if not launched.get('ok'):
        result = report('wait_lobby', launched.get('error') or '无法启动主号大厅',
                        needs_user=True, state=NEEDS_USER, channel='ui_fallback',
                        fallback_reason=fallback_reason)
        result.update(ok=False, needs_user=True, state=NEEDS_USER)
        return result
    report('wait_lobby', '正在等待主号大厅窗口…', channel='ui_fallback',
           fallback_reason=fallback_reason)
    ready = wait_lobby_ready(config, timeout=wait_lobby)
    if ready.get('needs_user'):
        result = report('wait_lobby', ready['message'], needs_user=True,
                        state=ready.get('state') or NEEDS_USER, channel='ui_fallback',
                        fallback_reason=fallback_reason)
        result.update(ready)
        return result
    report('login', '正在自动登录主号大厅…', channel='ui_fallback',
           fallback_reason=fallback_reason)
    login = complete_main_login(config)
    if login.get('needs_user'):
        result = report('login', login['message'], needs_user=True,
                        state=login.get('state') or NEEDS_USER, channel='ui_fallback',
                        fallback_reason=fallback_reason)
        result.update(login)
        return result
    return _ui_enter_and_start(config, report, prefix, fallback_reason)


def _ui_enter_and_start(config, report, prefix, fallback_reason='ui'):
    for _ in range(2):
        info = inspect_main(config)
        if info.get('has_start') or info.get('game_select'):
            break
        time.sleep(0.3)
    report('select_line', '大厅已登录，正在选择多线2（主线）…',
           state=LOBBY_LOGGED_IN, channel='ui_fallback', fallback_reason=fallback_reason)
    entered = ensure_main_line(config)
    if not entered.get('ok'):
        result = report(
            'select_line', entered.get('message') or '未能选中多线2（主线）',
            needs_user=True, state=entered.get('state') or LOBBY_LOGGED_IN,
            channel='ui_fallback', fallback_reason=fallback_reason)
        result.update(entered)
        return result
    report('start_game', '已选中多线2（主线），正在启动游戏…',
           state=ROOM_CONNECTED, channel='ui_fallback', fallback_reason=fallback_reason)
    started = click_main_start(config)
    if started.get('needs_user') or not started.get('ok'):
        result = report(
            'start_game', started.get('message') or '未能进入游戏选择',
            needs_user=True, state=started.get('state') or GAME_STARTING,
            channel='ui_fallback', fallback_reason=fallback_reason)
        result.update(started)
        return result
    reset_login_mark(config)
    message = started.get('message') or '已核验 SANPK 游戏选择窗口'
    result = report('list_ready', message, state=LIST_WINDOW_READY, ok=True,
                    event='list_ready', channel='ui_fallback', fallback_reason=fallback_reason)
    result.update(started)
    result['ok'] = True
    result['state'] = LIST_WINDOW_READY
    result['prefix'] = prefix
    return result


def _ui_start_only(config, report, session):
    """After protocol enter: click 启动游戏 if the lobby already shows it. No password."""
    info = inspect_main(config)
    if info.get('error'):
        return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                'message': info['error'], 'stage': 'start_game'}
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                'message': '需要本人处理：' + info['captcha'], 'stage': 'start_game'}
    if info.get('game_select') or info.get('has_start') or info.get('logged_in'):
        started = click_main_start(config)
        if started.get('ok'):
            return started
        if started.get('needs_user'):
            return started
    if info.get('login') and not info.get('logged_in'):
        if session:
            session.close(logout=True)
        return {
            'ok': False, 'state': NEEDS_USER, 'needs_user': True, 'stage': 'start_game',
            'message': (
                '协议已登录并进入多线2，但大厅仍停在登录窗。'
                '已退出协议会话以免占线。请本人在大厅勾选强制登录后点「启动游戏」。'
                '不会再次自动交密码。'
            ),
        }
    return {
        'ok': False, 'state': GAME_STARTING, 'needs_user': True, 'stage': 'start_game',
        'message': '协议已进线，但未见大厅「启动游戏」。请本人点启动游戏。不会再次交密码。',
    }


def wait_lobby_ready(config, timeout=60, allow_already_online=False):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = inspect_main(config)
        if last.get('error'):
            time.sleep(2)
            continue
        if last.get('captcha'):
            return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                    'message': '需要本人处理：' + last['captcha']}
        if last.get('already_logged_in'):
            if allow_already_online:
                return {'ok': True, 'info': last, 'already_logged_in': True}
            return _already_online()
        if (last.get('login') or last.get('logged_in') or last.get('has_start')
                or last.get('has_login_button') or last.get('game_select')):
            return {'ok': True, 'info': last}
        time.sleep(2)
    if last.get('error'):
        return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                'message': last['error']}
    return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
            'message': '登录窗超时，请本人查看主号大厅。不会自动重试。'}


def complete_main_login(config, allow_force=False):
    info = inspect_main(config)
    if info.get('error'):
        return {'ok': False, 'state': NEEDS_USER, 'message': info['error'], 'needs_user': True}
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                'needs_user': True}
    if info.get('already_logged_in') and not allow_force:
        return _already_online()
    if info.get('logged_in') or info.get('has_start') or info.get('game_select'):
        reset_login_mark(config)
        return {'ok': True, 'state': LOBBY_LOGGED_IN, 'message': '主号大厅已登录',
                'needs_user': False, 'evidence': connection_evidence(info, config)}
    if info.get('already_logged_in') and allow_force:
        forced = run_main_ops(config, ['--force'])
        payload = forced.get('payload') or {}
        if payload.get('status') != 'checked' and not payload.get('checked'):
            return _already_online()
    mark = _login_mark(config)
    if mark.get('submitted'):
        return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                'message': '已提交过一次登录但仍停在登录窗，不会再次交密码。请本人处理验证码或错误提示。'}
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and not info.get('has_login_button'):
        time.sleep(2)
        info = inspect_main(config)
        if info.get('logged_in') or info.get('has_start') or info.get('game_select'):
            reset_login_mark(config)
            return {'ok': True, 'state': LOBBY_LOGGED_IN, 'message': '主号大厅已登录',
                    'needs_user': False, 'evidence': connection_evidence(info, config)}
        if info.get('captcha'):
            return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                    'needs_user': True}
        if info.get('already_logged_in') and not allow_force:
            return _already_online()
    submitted = run_main_ops(
        config, ['--login'], with_creds=not missing_credentials(config, kind='main'))
    payload = submitted.get('payload') or {}
    _write_login_mark(config, payload.get('status') or submitted.get('error') or 'unknown')
    if payload.get('status') in ('logged_in',):
        reset_login_mark(config)
        return {'ok': True, 'state': LOBBY_LOGGED_IN, 'message': '主号大厅已登录', 'needs_user': False}
    if payload.get('status') != 'submitted':
        return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
                'message': payload.get('message') or submitted.get('error') or '登录未提交'}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(2)
        info = inspect_main(config)
        if info.get('captcha'):
            return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                    'needs_user': True}
        if info.get('already_logged_in'):
            return _already_online()
        if info.get('logged_in') or info.get('has_start') or info.get('game_select'):
            reset_login_mark(config)
            return {'ok': True, 'state': LOBBY_LOGGED_IN, 'message': '主号大厅已登录',
                    'needs_user': False, 'evidence': connection_evidence(info, config)}
        if not info.get('login') and info.get('titles'):
            reset_login_mark(config)
            return {'ok': True, 'state': LOBBY_LOGGED_IN, 'message': '登录窗已关闭', 'needs_user': False}
    return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
            'message': '登录已提交一次，但仍未见已登录界面。请本人查看主号大厅。'}


def ensure_main_line(config):
    info = inspect_main(config)
    if info.get('error'):
        return {'ok': False, 'state': NEEDS_USER, 'message': info['error'], 'needs_user': True}
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                'needs_user': True}
    evidence = connection_evidence(info, config)
    if evidence.get('target_connected'):
        return {'ok': True, 'state': ROOM_CONNECTED,
                'message': '大厅树已选中 ' + (evidence.get('observed_line') or '多线2（主线）'),
                'evidence': evidence}
    last = None
    for name in tree_targets(config):
        last = run_main_ops(config, ['--select-tree', name])
        payload = last.get('payload') or {}
        if payload.get('status') == 'clicked':
            time.sleep(1.2)
            info = inspect_main(config)
            evidence = connection_evidence(info, config)
            if evidence.get('target_connected'):
                return {'ok': True, 'state': ROOM_CONNECTED,
                        'message': '已进入 ' + (evidence.get('observed_line') or name),
                        'evidence': evidence}
    return {'ok': False, 'state': LOBBY_LOGGED_IN, 'needs_user': True,
            'message': (last or {}).get('payload', {}).get('message')
            or (last or {}).get('error')
            or '未能核验已进入多线2。请在主号大厅点「多线2（主线）」。不会自动重试。',
            'evidence': evidence}


def sanpk_playable(info):
    """真实 SANPK：游戏选择，或已进入联机版对局。搜房探针不会出现这些窗口。"""
    if info.get('game_select'):
        return 'game_select'
    titles = info.get('titles') or []
    if info.get('sanpk_running') and any('三国志Internet联机版' in (title or '') for title in titles):
        return 'in_match'
    return None


def click_main_start(config):
    prefix = operating_prefix(config)
    info = inspect_main(config)
    if info.get('captcha'):
        return {'ok': False, 'state': NEEDS_USER, 'message': '需要本人处理：' + info['captcha'],
                'needs_user': True}
    evidence = connection_evidence(info, config)
    playable = sanpk_playable(info)
    if playable == 'game_select' and evidence.get('target_connected'):
        return {'ok': True, 'state': LIST_WINDOW_READY,
                'message': '已核验 SANPK 游戏选择窗口', 'evidence': evidence}
    if playable == 'in_match' and evidence.get('target_connected'):
        return {'ok': True, 'state': LIST_WINDOW_READY,
                'message': '已核验 SANPK 联机对局窗口（完整客户端，非搜房探针）',
                'evidence': evidence}
    if playable == 'game_select' and not evidence.get('target_connected'):
        return {'ok': False, 'state': GAME_STARTING, 'needs_user': True,
                'message': '已有游戏选择窗口，但未核验多线2连接。空白列表不能当有效空。',
                'evidence': evidence}
    if running_in_prefix(prefix, 'SANPK.exe') and not playable:
        return {'ok': False, 'state': GAME_STARTING, 'needs_user': True,
                'message': '主号 SANPK 已在跑，但未见游戏选择或联机对局窗口，不能当作列表就绪',
                'evidence': evidence}
    if not running_in_prefix(prefix, 'SANGUO.exe') and not info.get('has_start'):
        return {'ok': False, 'state': PENDING_LOGIN, 'needs_user': True,
                'message': '主号大厅未运行'}
    entered = ensure_main_line(config)
    if not entered.get('ok'):
        return entered
    started = run_main_ops(config, ['--start-game'])
    payload = started.get('payload') or {}
    if payload.get('status') != 'clicked':
        return {'ok': False, 'state': ROOM_CONNECTED, 'needs_user': True,
                'message': payload.get('message') or started.get('error')
                or '未点到启动游戏。请在主号大厅进入目标房间后点「启动游戏」。',
                'evidence': entered.get('evidence')}
    waited = wait_for_list(config, timeout=90)
    waited['ok'] = waited.get('state') == LIST_WINDOW_READY
    return waited


def wait_for_list(config, timeout=90, require_lobby=True, interval=2):
    prefix = operating_prefix(config)
    deadline = time.monotonic() + timeout
    saw_sanpk = False
    last = {}
    pause = 0.4 if interval is None else max(0.2, float(interval))
    while time.monotonic() < deadline:
        info = inspect_main(config)
        last = connection_evidence(info, config)
        playable = sanpk_playable(info)
        connected = last.get('target_connected') or not require_lobby
        if playable == 'game_select' and connected:
            return {'state': LIST_WINDOW_READY, 'message': '已核验 SANPK 游戏选择窗口且大厅在多线2（主线）'
                    if require_lobby else '已核验 SANPK 游戏选择窗口',
                    'evidence': last, 'needs_user': False}
        if playable == 'in_match' and connected:
            line = (last.get('observed_line') or '') if require_lobby else ''
            message = '已核验 SANPK 联机对局窗口'
            if line:
                message += '，大厅在' + line
            return {'state': LIST_WINDOW_READY, 'message': message,
                    'evidence': last, 'needs_user': False}
        if playable == 'game_select' and require_lobby:
            return {'state': GAME_STARTING, 'needs_user': True,
                    'message': '游戏选择已出现，但未核验多线2，不能报列表就绪',
                    'evidence': last}
        if running_in_prefix(prefix, 'SANPK.exe'):
            saw_sanpk = True
        time.sleep(pause)
    if saw_sanpk:
        return {'state': GAME_STARTING, 'needs_user': True,
                'message': '主号 SANPK 已出现但未见已核验的游戏选择窗口', 'evidence': last}
    return {'state': GAME_STARTING, 'message': '等待游戏选择超时，请本人查看。不会自动重试。',
            'needs_user': True, 'evidence': last}


def launcher_config(prefix, hub_root, data_dir, runtime=None):
    runtime = runtime or {}
    return {
        'allow_main_account': True,
        'main_prefix': str(prefix),
        'hub_root': str(hub_root or ''),
        'data_dir': str(data_dir),
        'platform_line': runtime.get('platform_line') or DEFAULT_LINE,
        'platform_room': runtime.get('platform_room') or DEFAULT_ROOM,
        'main_account_username': (runtime.get('main_account_username') or '').strip(),
        'wine': runtime.get('wine') or '',
        'force_ui_fallback': runtime.get('protocol_direct') is False,
    }


def run_from_launcher(prefix, hub_root, data_dir, runtime=None, progress=None, wait_lobby=60):
    return reach_game_list(
        launcher_config(prefix, hub_root, data_dir, runtime),
        progress=progress, wait_lobby=wait_lobby)


def _already_online():
    return {'ok': False, 'state': NEEDS_USER, 'needs_user': True,
            'message': '主号提示「用户已经登录」。请本人在该登录窗勾选「强制登录」后点登录，或先在另一台已登录的机器退出。不会再自动交密码。'}


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


def reset_login_mark(config):
    path = Path(config.get('data_dir') or '') / LOGIN_MARK
    try:
        path.unlink()
    except FileNotFoundError:
        pass
