"""Locate and launch the hashed official 32-bit Windows Python helper."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .provision import default_paths, wine_env


HELPER_NAME = 'sgi-py32.exe'
META_NAME = 'WIN32-PYTHON.json'


def helper_dir(hub_root=None):
    if hub_root:
        candidate = Path(hub_root) / 'bridge' / 'win32-python'
        if (candidate / HELPER_NAME).is_file():
            return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / 'bridge' / 'win32-python'
        if (candidate / HELPER_NAME).is_file():
            return candidate
    env = (os.environ.get('SGI_WIN32_PYTHON_DIR') or '').strip()
    if env:
        return Path(env).expanduser()
    return None


def helper_exe(hub_root=None):
    folder = helper_dir(hub_root)
    if folder is None:
        return None
    path = folder / HELPER_NAME
    return path if path.is_file() else None


def verify_helper(hub_root=None):
    folder = helper_dir(hub_root)
    if folder is None:
        return {'ok': False, 'reason': 'no_win32_python'}
    meta_path = folder / META_NAME
    if not meta_path.is_file():
        return {'ok': False, 'reason': 'helper_meta_missing'}
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {'ok': False, 'reason': 'helper_meta_invalid'}
    expected = meta.get('files') or {}
    if not expected:
        return {'ok': False, 'reason': 'helper_meta_empty'}
    for name, digest in expected.items():
        path = folder / name
        if not path.is_file():
            return {'ok': False, 'reason': 'helper_missing', 'missing': name}
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return {'ok': False, 'reason': 'helper_mismatch', 'mismatch': name}
    exe = folder / (meta.get('helper_exe') or HELPER_NAME)
    if not exe.is_file():
        return {'ok': False, 'reason': 'no_win32_python'}
    return {'ok': True, 'exe': str(exe), 'version': meta.get('version'), 'arch': meta.get('arch')}


def _appdefaults_header(exe_name):
    return '[Software\\\\Wine\\\\AppDefaults\\\\%s]' % exe_name


def user_reg_path(prefix):
    return Path(prefix).expanduser() / 'user.reg'


def _section_span(text, header):
    start = text.find(header)
    if start < 0:
        return -1, -1
    nxt = text.find('\n[', start + 1)
    end = len(text) if nxt < 0 else nxt
    return start, end


def win81_already_set(prefix, exe_name):
    """True when prefix/user.reg already has AppDefaults\\<exe> Version=win81."""
    path = user_reg_path(prefix)
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    start, end = _section_span(text, _appdefaults_header(Path(exe_name).name))
    if start < 0:
        return False
    section = text[start:end]
    return '"Version"="win81"' in section or '"Version"=str(2):"win81"' in section


def ensure_win81_user_reg(prefix, exe_name):
    """Write Wine user.reg AppDefaults Version=win81. No wineserver required."""
    path = user_reg_path(prefix)
    exe_name = Path(exe_name).name
    if win81_already_set(prefix, exe_name):
        return True
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    header = _appdefaults_header(exe_name)
    start, end = _section_span(text, header)
    stamp = str(int(time.time()))
    body = '%s %s\n#time=0\n"Version"="win81"\n' % (header, stamp)
    if start < 0:
        if text and not text.endswith('\n'):
            text += '\n'
        text += '\n' + body
    else:
        text = text[:start] + body + text[end:].lstrip('\n')
        if not text.endswith('\n'):
            text += '\n'
    try:
        path.write_text(text, encoding='utf-8')
    except OSError:
        return False
    return win81_already_set(prefix, exe_name)


def _wine_set_appdefaults(config, prefix, name):
    wine = Path((config or {}).get('wine') or default_paths().get('wine') or '')
    hub = Path((config or {}).get('hub_root') or '')
    host_py = hub / 'bridge' / 'python' / 'python.exe'
    if not wine.is_file():
        return {'ok': False, 'reason': 'no_wine'}
    if not host_py.is_file():
        return {'ok': False, 'reason': 'no_host_python'}
    code = (
        "import winreg;"
        "k=winreg.CreateKey(winreg.HKEY_CURRENT_USER,"
        r"'Software\\Wine\\AppDefaults\\%s');"
        "winreg.SetValueEx(k,'Version',0,winreg.REG_SZ,'win81');"
        "k.Close()"
    ) % name
    env = wine_env(wine, prefix)
    try:
        result = subprocess.run(
            [str(wine), str(host_py), '-c', code],
            env=env, capture_output=True, text=True, timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        return {'ok': False, 'reason': 'win81_registry'}
    if result.returncode != 0:
        return {'ok': False, 'reason': 'win81_registry', 'detail': (result.stderr or '')[:160]}
    return {'ok': True, 'compat': 'wine-appdefaults-win81'}


def apply_win81(config, prefix, exe_path, live=False):
    """Per-app Windows 8.1. Does not change SANGUO/SANPK or the prefix default.

    sgi-py32 stays skip-if-present so a busy wineserver cannot hang auto-enter.
    live=True also tries wine+python once so a running wineserver picks up a
    newly written key; timeout is fail-open when user.reg already has
    Version=win81.
    """
    exe_path = Path(exe_path)
    name = exe_path.name
    if sys.platform == 'win32':
        import winreg
        key_path = r'Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, str(exe_path), 0, winreg.REG_SZ, 'WIN81RTM')
        winreg.CloseKey(key)
        return {'ok': True, 'compat': 'WIN81RTM'}
    already = win81_already_set(prefix, name)
    if already and not live:
        return {'ok': True, 'compat': 'wine-appdefaults-win81-existing'}
    wrote = already
    if not already:
        wrote = ensure_win81_user_reg(prefix, name)
        if wrote and not live:
            return {'ok': True, 'compat': 'wine-appdefaults-win81-user.reg'}
    wine_result = _wine_set_appdefaults(config, prefix, name)
    if wine_result.get('ok'):
        return wine_result
    if wrote or win81_already_set(prefix, name):
        return {'ok': True, 'compat': 'wine-appdefaults-win81-user.reg', 'live': False}
    return wine_result


def win32_command(config, prefix, script, extra_args=None):
    checked = verify_helper((config or {}).get('hub_root'))
    if not checked.get('ok'):
        return None, None, {'error': checked.get('reason') or 'no_win32_python'}
    exe = Path(checked['exe'])
    extra_args = list(extra_args or [])
    if sys.platform == 'win32':
        env = dict(os.environ)
        cmd = [str(exe), '-X', 'utf8', '-B', str(script), *extra_args]
        return env, cmd, None
    wine = Path((config or {}).get('wine') or default_paths().get('wine') or '')
    if not wine.is_file():
        return None, None, {'error': '找不到 Wine'}
    env = wine_env(wine, prefix)
    cmd = [str(wine), str(exe), '-X', 'utf8', '-B', str(script), *extra_args]
    return env, cmd, None
