"""Run wine_lobby_ops against one explicit prefix. Monitor and main both call this."""
import json
import os
import subprocess
import sys
from pathlib import Path

from .provision import default_paths, wine_env


WINE_CRED_WINDOWS = r'C:\sgi\room_monitor\.login.json'
WINE_SCRIPT_WINDOWS = r'C:\sgi\room_monitor\wine_lobby_ops.py'
WINE_IMAGE_ROOT = r'C:\sgi\run-3.5'


def ops_script():
    return Path(__file__).resolve().parent / 'wine_lobby_ops.py'


def prefix_dest_dir(prefix):
    prefix = Path(prefix).expanduser()
    if sys.platform == 'win32':
        return prefix / 'room_monitor'
    return prefix / 'drive_c/sgi/room_monitor'


def run_ops(config, flags, prefix, with_creds=False, creds_loader=None,
            cred_error='凭据不完整', timeout=40):
    """Copy ops into the target prefix, optionally drop a 0600 cred file, then wipe it."""
    prefix = Path(prefix).expanduser()
    script = ops_script()
    if not script.is_file():
        return {'error': '缺少 wine_lobby_ops.py'}
    dest_dir = prefix_dest_dir(prefix)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / 'wine_lobby_ops.py'
    dest.write_text(script.read_text(encoding='utf-8'), encoding='utf-8')
    helper = script.with_name('tree_node_read.py')
    if helper.is_file():
        (dest_dir / 'tree_node_read.py').write_text(helper.read_text(encoding='utf-8'), encoding='utf-8')
    cred_path = dest_dir / '.login.json'
    try:
        env, cmd, early = _ops_command(config, prefix, dest, flags)
        if early:
            return early
        if with_creds:
            if creds_loader is None:
                return {'error': cred_error}
            creds = creds_loader()
            if not creds.get('username') or not creds.get('password'):
                return {'error': cred_error}
            cred_path.write_text(
                json.dumps({'username': creds['username'], 'password': creds['password']},
                           ensure_ascii=False),
                encoding='utf-8')
            cred_path.chmod(0o600)
            env['SGI_MONITOR_CRED_FILE'] = env.get('SGI_MONITOR_CRED_FILE') or str(cred_path)
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'error': '大厅操作超时'}
    except OSError as error:
        return {'error': f'无法启动大厅操作: {error}'}
    finally:
        _wipe_cred_file(cred_path)
    text = (result.stdout or '').strip()
    if not text:
        return {'error': ((result.stderr or '大厅操作无输出')[:240])}
    try:
        return {'payload': json.loads(text.splitlines()[-1])}
    except json.JSONDecodeError:
        return {'error': '大厅操作输出无法解析'}


def _ops_command(config, prefix, dest, flags):
    flags = list(flags or [])
    from .win32_runtime import helper_exe, verify_helper
    helper = helper_exe((config or {}).get('hub_root'))
    helper_ok = bool(helper and verify_helper((config or {}).get('hub_root')).get('ok'))
    if sys.platform == 'win32':
        env = dict(os.environ)
        env['SGI_ALLOWED_IMAGE_ROOT'] = str(prefix)
        env['SGI_MONITOR_CRED_FILE'] = str(dest.parent / '.login.json')
        python = str(helper) if helper_ok else sys.executable
        cmd = [python, '-X', 'utf8', '-B', str(dest)]
        cmd.extend(flags)
        return env, cmd, None
    paths = default_paths()
    wine = Path(config.get('wine') or paths.get('wine') or '')
    hub = Path(config.get('hub_root') or '')
    python = Path(helper) if helper_ok else (hub / 'bridge/python/python.exe')
    if not wine.is_file():
        return None, None, {'error': '找不到 Wine'}
    if not python.is_file():
        return None, None, {'error': f'找不到环境内 Python: {python}'}
    env = wine_env(wine, prefix)
    env['SGI_ALLOWED_IMAGE_ROOT'] = WINE_IMAGE_ROOT
    env['SGI_MONITOR_CRED_FILE'] = WINE_CRED_WINDOWS
    script = WINE_SCRIPT_WINDOWS if helper_ok or python != sys.executable else str(dest)
    if helper_ok:
        script = WINE_SCRIPT_WINDOWS
    cmd = [str(wine), str(python), '-X', 'utf8', '-B', script]
    cmd.extend(flags)
    return env, cmd, None


def _wipe_cred_file(path):
    path = Path(path)
    try:
        if path.is_file():
            path.write_bytes(b'')
            path.unlink()
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


def inspect_prefix(config, prefix, timeout=40):
    result = run_ops(config, [], prefix, timeout=timeout)
    if result.get('error'):
        return {'error': result['error']}
    return result.get('payload') or {}
