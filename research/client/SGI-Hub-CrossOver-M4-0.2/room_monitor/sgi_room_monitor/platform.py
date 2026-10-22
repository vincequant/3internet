"""OS/Wine/display helpers. Global tasklist is never proof a monitor instance is ready."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def normalize_path(value):
    return str(value or '').replace('\\', '/').lower().rstrip('/')


def kind():
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform == 'darwin':
        return 'macos'
    if sys.platform.startswith('linux'):
        return 'linux'
    return sys.platform


def display_status():
    env_display = os.environ.get('DISPLAY') or ''
    wayland = os.environ.get('WAYLAND_DISPLAY') or ''
    if env_display or wayland:
        return {'ok': True, 'display': env_display or wayland, 'kind': 'existing'}
    if kind() != 'linux':
        return {'ok': True, 'display': None, 'kind': 'not-required'}
    xvfb = shutil.which('Xvfb')
    return {
        'ok': False,
        'display': None,
        'kind': 'missing',
        'xvfb': bool(xvfb),
        'tried': ['DISPLAY', 'WAYLAND_DISPLAY', 'Xvfb'],
        'message': 'Linux 无 DISPLAY。可启动 Xvfb 虚拟桌面后再跑大厅，不是已证实不可行。' if xvfb
        else 'Linux 无 DISPLAY 且未找到 Xvfb。先安装 xvfb 再测虚拟桌面，不要直接宣布技术上不可行。',
    }


def ensure_display(config=None, display=':93'):
    status = display_status()
    if status['ok']:
        return status
    xvfb = shutil.which('Xvfb')
    if not xvfb:
        return status
    data_dir = Path((config or {}).get('data_dir') or '.')
    data_dir.mkdir(parents=True, exist_ok=True)
    log = data_dir / 'xvfb.log'
    proc = subprocess.Popen(
        [xvfb, display, '-screen', '0', '1280x800x24', '-nolisten', 'tcp'],
        stdout=log.open('ab'), stderr=subprocess.STDOUT, start_new_session=True)
    os.environ['DISPLAY'] = display
    mark = data_dir / 'xvfb.json'
    mark.write_text(json.dumps({'pid': proc.pid, 'display': display}, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    return {'ok': True, 'display': display, 'kind': 'xvfb', 'pid': proc.pid}


def windows_processes(name):
    if sys.platform != 'win32':
        return []
    script = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = (result.stdout or '').strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data or [])


def running_in_prefix(prefix, name):
    prefix = str(Path(prefix).expanduser()) if prefix else ''
    if not prefix:
        return False
    if sys.platform == 'win32':
        need = normalize_path(prefix)
        for row in windows_processes(name):
            blob = ' '.join(str(row.get(key) or '') for key in ('ExecutablePath', 'CommandLine'))
            if need and need in normalize_path(blob):
                return True
        return False
    from .provision import prefix_owned_pids
    return any(name.lower() in (row.get('command') or '').lower() for row in prefix_owned_pids(prefix))
