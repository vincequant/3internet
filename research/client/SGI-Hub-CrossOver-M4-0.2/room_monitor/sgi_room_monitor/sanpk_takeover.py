"""Launch playable SANPK from a protocol hall grant via 32-bit StartServer."""
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

from .win32_runtime import apply_win81, helper_exe, verify_helper, win32_command, win81_already_set

# Keep helper/session alive after reach_game_list returns. Closing the pipe
# used to SIGPIPE the helper, which then StopServer and killed SANPK.
_HELD = []


KNOWN_HASHES = {
    'SANPK.exe': '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',
    'Koeinm.dll': '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841',
    'GameTool.dll': (
        '9667eff9c13d0307ba92f47d9f148d4f08bce32dd45e40bf606b27f9f2c179f1',
        'd9e6167baec2628e6af5a0532929698921eaf1a0d28054ff00b1774408fb9640',
    ),
    'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
    'NetHookCore.dll': '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4',
    'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88',
}
_IN_GAME_DIR = ('SANPK.exe', 'Koeinm.dll', 'GameTool.dll')

TAKEOVER_BLOCKED = (
    '协议无法拉起可对战 SANPK：32 位辅助环境或原版 DLL 哈希未核验。'
)


def game_root(prefix):
    prefix = Path(prefix).expanduser()
    wine_layout = prefix / 'drive_c/sgi/run-3.5'
    if wine_layout.is_dir() or (wine_layout / 'SANGUO.exe').is_file():
        return wine_layout
    if (prefix / 'SANGUO.exe').is_file() or (prefix / '3I').is_dir():
        return prefix
    return wine_layout


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_binaries(root):
    root = Path(root)
    checked = {}
    for name, expected in KNOWN_HASHES.items():
        allowed = expected if isinstance(expected, (tuple, list, set, frozenset)) else (expected,)
        if name in _IN_GAME_DIR:
            path = root / '3I' / name
            if not path.is_file():
                path = root / name
        else:
            path = root / name
        if not path.is_file():
            return {'ok': False, 'missing': name, 'checked': checked}
        digest = file_digest(path)
        checked[name] = digest
        if digest not in allowed:
            return {'ok': False, 'mismatch': name, 'checked': {name: digest[:12] + '…'}}
    return {'ok': True, 'checked': {name: 'ok' for name in checked}}


def find_win32_python(prefix=None, extra=None, hub_root=None):
    env = (os.environ.get('SGI_WIN32_PYTHON') or '').strip()
    if env and Path(env).expanduser().is_file():
        return str(Path(env).expanduser())
    if extra and Path(extra).is_file():
        return str(Path(extra))
    found = helper_exe(hub_root)
    return str(found) if found else None


def takeover_feasible(prefix, extra_python=None, hub_root=None):
    if (os.environ.get('SGI_FORCE_UI_FALLBACK') or '').strip() == '1':
        return {
            'ok': False, 'feasible': False, 'reason': 'force_ui_fallback',
            'message': '已禁用协议 SANPK 接管，走大厅回退。', 'degrade': 'ui_start',
        }
    root = game_root(prefix)
    binaries = verify_binaries(root)
    helper = verify_helper(hub_root)
    python32 = find_win32_python(prefix, extra_python, hub_root)
    if not binaries.get('ok'):
        return {
            'ok': False, 'feasible': False,
            'reason': 'binary_mismatch' if binaries.get('mismatch') else 'binary_missing',
            'message': TAKEOVER_BLOCKED, 'degrade': 'ui_start',
        }
    if not helper.get('ok') or not python32:
        return {
            'ok': False, 'feasible': False, 'reason': helper.get('reason') or 'no_win32_python',
            'message': TAKEOVER_BLOCKED, 'degrade': 'ui_start',
        }
    return {
        'ok': False, 'feasible': True, 'reason': None, 'python32': python32,
        'message': '32 位辅助已核验，可尝试 StartServer 拉起 SANPK。',
        'degrade': None,
    }


def try_launch_playable_sanpk(prefix, session=None, extra_python=None, config=None):
    config = dict(config or {})
    prefix = Path(prefix).expanduser()
    check = takeover_feasible(prefix, extra_python, config.get('hub_root'))
    check['channel'] = 'protocol_sanpk'
    grant = session.grant_for_takeover() if session is not None else None
    if not check.get('feasible'):
        if grant:
            grant.clear()
        check['ok'] = False
        return check
    if not grant or not grant.get('token'):
        check.update(ok=False, feasible=False, reason='no_grant', degrade='ui_start',
                     message='协议进线授权不完整，无法 StartServer。')
        return check
    try:
        compat = apply_win81(config, prefix, check['python32'])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        compat = {'ok': False, 'reason': 'win81_spoof'}
    if not compat.get('ok'):
        grant.clear()
        check.update(ok=False, reason='win81_spoof', degrade='ui_start',
                     message='无法为辅助进程设置 win81 兼容。')
        return check
    sanpk = game_root(prefix) / '3I' / 'SANPK.exe'
    if not sanpk.is_file():
        sanpk = game_root(prefix) / 'SANPK.exe'
    try:
        apply_win81(
            config, prefix, sanpk,
            live=not win81_already_set(prefix, 'SANPK.exe'))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    script_src = Path(__file__).resolve().parent / 'win32_startserver.py'
    dest_dir = prefix / 'room_monitor' if sys.platform == 'win32' else prefix / 'drive_c/sgi/room_monitor'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / 'win32_startserver.py'
    dest.write_text(script_src.read_text(encoding='utf-8'), encoding='utf-8')
    wine_script = dest if sys.platform == 'win32' else Path(r'C:\sgi\room_monitor\win32_startserver.py')
    env, cmd, early = win32_command(config, prefix, wine_script)
    if early:
        grant.clear()
        check.update(ok=False, reason='helper_cmd', degrade='ui_start', message=early.get('error'))
        return check
    payload = {
        'virtual_ip': grant.get('virtual_ip'),
        'server': grant.get('server'),
        'port': grant.get('port'),
        'game_id': grant.get('game_id'),
        'user_id': grant.get('user_id'),
        'username': grant.get('username'),
        'token': grant.get('token'),
        'launch_sanpk': True,
        'game_root': r'C:\sgi\run-3.5' if sys.platform != 'win32' else str(game_root(prefix)),
        'hold_seconds': 7200,
    }
    join_name = str(config.get('join_name') or '').strip()
    if join_name:
        payload['join_name'] = join_name[:40]
    grant.clear()
    event_log = dest_dir / 'startserver-events.jsonl'
    try:
        log_handle = event_log.open('w', encoding='utf-8')
        proc = subprocess.Popen(
            cmd, env=env, stdin=subprocess.PIPE, stdout=log_handle,
            stderr=subprocess.STDOUT, text=True, start_new_session=True)
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload, ensure_ascii=True))
        proc.stdin.close()
        payload['token'] = None
    except OSError as error:
        check.update(ok=False, reason='helper_spawn', degrade='ui_start',
                     message='无法启动 32 位辅助进程')
        return check
    events = []
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        time.sleep(0.05)
        try:
            lines = event_log.read_text(encoding='utf-8').splitlines()
        except OSError:
            lines = []
        events = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append({k: row[k] for k in row if k not in ('token', 'password')})
            if row.get('error'):
                try:
                    proc.kill()
                except OSError:
                    pass
                check.update(ok=False, reason=row.get('error'), degrade='ui_start',
                             message='StartServer 辅助失败：' + str(row.get('error')),
                             events=events)
                return check
        if any(row.get('event') in ('ready', 'sanpk_launched') or row.get('ok') for row in events):
            _HELD.append(proc)
            try:
                log_handle.close()
            except OSError:
                pass
            check.update(ok=True, reason=None, degrade=None, proc=proc,
                         message='已用原版 StartServer 拉起 SANPK', events=events,
                         start_rc=next((e.get('start_rc') for e in events if 'start_rc' in e), None))
            return check
        if proc.poll() is not None:
            break
    try:
        proc.kill()
    except OSError:
        pass
    try:
        log_handle.close()
    except OSError:
        pass
    check.update(ok=False, reason='helper_timeout', degrade='ui_start',
                 message='32 位辅助未确认 StartServer/SANPK。', events=events)
    return check
