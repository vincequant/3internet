"""Restore PlayBGM from Setting.ini. Never delete music files or guess defaults."""
import os
import re
import sys
from pathlib import Path

WINDOWS_SETTING = Path(r'C:\sgi\run-3.5\3I\Setting.ini')


def decode_ini(raw):
    for encoding in ('gbk', 'utf-8-sig', 'utf-8'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError('无法解码 Setting.ini')


def read_play_bgm(path):
    text, encoding = decode_ini(Path(path).read_bytes())
    match = re.search(r'(?m)^PlayBGM\s*=\s*(\d+)\s*$', text)
    if not match:
        raise ValueError('Setting.ini 没有 PlayBGM')
    value = int(match.group(1))
    if value not in (0, 1):
        raise ValueError('PlayBGM 不是可恢复的 0/1')
    return value, text, encoding


def write_play_bgm(path, value):
    if value not in (0, 1):
        raise ValueError('只能写入 PlayBGM=0 或 1')
    path = Path(path)
    text, encoding = decode_ini(path.read_bytes())
    new, count = re.subn(r'(?m)^(PlayBGM\s*=\s*)\d+(\s*)$', rf'\g<1>{value}\2', text, count=1)
    if count != 1:
        raise ValueError('无法唯一改写 PlayBGM')
    temp = path.with_name(path.name + '.room-watch-tmp')
    temp.write_bytes(new.encode(encoding))
    temp.replace(path)
    return value


def known_game_exe():
    env = os.environ.get('SGI_GAME_EXE')
    if env:
        return env
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))
        from connection import local_config
        return (local_config() or {}).get('game_path')
    except Exception:
        return None


def setting_candidates(exe_path=None, prefix=None):
    found = []
    for item in (exe_path, known_game_exe()):
        if item:
            found.append(Path(item).with_name('Setting.ini'))
    if prefix:
        found.append(Path(prefix) / 'drive_c/sgi/run-3.5/3I/Setting.ini')
    if sys.platform == 'win32':
        found.append(WINDOWS_SETTING)
    seen = set()
    unique = []
    for path in found:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def resolve_setting_ini(exe_path=None, prefix=None):
    for path in setting_candidates(exe_path, prefix):
        if path.is_file():
            return path
    raise FileNotFoundError('找不到游戏 Setting.ini')


_HELPERS = (
    'python', 'room_watch', 'sgi_wine_process_watch', 'quiet_wait_launch',
    'pgrep', 'egrep', 'fgrep', 'grep', 'awk',
)


def command_is_game(command, name):
    text = command.strip()
    if not text or name not in text:
        return False
    lower = text.lower()
    if any(token in lower for token in _HELPERS):
        return False
    if text == name or text.endswith('/' + name) or text.endswith('\\' + name):
        return True
    return bool(re.search(r'[\\/]' + re.escape(name) + r'(?:\s|$)', text))


def process_commands():
    import subprocess
    if sys.platform == 'win32':
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        return [line.split(',')[0].strip('"') for line in result.stdout.splitlines() if line.strip()]
    result = subprocess.check_output(['/bin/ps', '-axo', 'command='], text=True, errors='replace')
    return result.splitlines()


def sanpk_running(commands=None):
    commands = process_commands() if commands is None else commands
    return any(command_is_game(item, 'SANPK.exe') for item in commands)


def sanguo_running(commands=None):
    commands = process_commands() if commands is None else commands
    return any(command_is_game(item, 'SANGUO.exe') for item in commands)


def waiting_status(sanpk_alive, lobby_alive):
    if sanpk_alive:
        return None
    if lobby_alive:
        return '等待从大厅进入游戏选择；未启动 SANPK，不探窗口、不抢焦点'
    return '对战平台未运行。请先打开大厅，再进游戏选择。未代为启动、不探窗口。'


def should_restore_audio_on_exit(stored, sanpk_alive):
    if stored.get('quiet_launch') and not sanpk_alive:
        return False
    return True
