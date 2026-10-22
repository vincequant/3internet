"""Prepare PlayBGM=0 before launch, then open lobby + observer. Never restarts a live game."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from room_watch_audio import command_is_game, known_game_exe, read_play_bgm, resolve_setting_ini, write_play_bgm
from room_watch_settings import read_file, update as update_settings

MAC_LAUNCHER = Path.home() / 'Library/Application Support/SGI-Wine/三国志 Wine.app'


def wine_prefix():
    try:
        from connection import local_config
        runtime = (local_config() or {}).get('wine_runtime') or {}
        return runtime.get('prefix')
    except Exception:
        return None


def process_commands():
    if sys.platform == 'win32':
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        return [line.split(',')[0].strip('"') for line in result.stdout.splitlines() if line.strip()]
    result = subprocess.check_output(['/bin/ps', '-axo', 'command='], text=True, errors='replace')
    return result.splitlines()


def command_is_observer(item):
    text = item or ''
    if 'room_watch.py' not in text:
        return False
    lower = text.lower()
    if any(marker in lower for marker in ('quiet_wait_launch.py', 'pgrep', 'awk ', '/bin/ps', 'rg ', 'grep ')):
        return False
    return 'python' in lower


def running_roles(commands=None):
    commands = process_commands() if commands is None else commands
    return {
        'sanpk': any(command_is_game(item, 'SANPK.exe') for item in commands),
        'lobby': any(command_is_game(item, 'SANGUO.exe') for item in commands),
        'observer': any(command_is_observer(item) for item in commands),
    }


def plan(roles, platform=None):
    platform = sys.platform if platform is None else platform
    if roles.get('observer'):
        return {
            'prepare': False, 'launch_lobby': False, 'watch': False, 'mode': 'already_open',
            'message': '本机已有观察窗口，请使用原窗口。未改音频、未再开一份。',
        }
    if roles.get('sanpk'):
        return {
            'prepare': False, 'launch_lobby': False, 'watch': True, 'mode': 'observe_existing',
            'message': '当前游戏在运行，未改音频、未重启。请用已有观察窗，或等你退出后再用安静等待启动。',
        }
    return {
        'prepare': True,
        'launch_lobby': platform == 'darwin' and not roles.get('lobby'),
        'watch': True, 'mode': 'quiet_wait',
        'message': '已在启动前关闭 PlayBGM。从大厅进入游戏后应无背景乐；警报仍走观察器。这不是仅大厅查询。',
    }


def notify_already_running():
    title = '房间人数观察'
    text = '本机已有观察窗口，请使用原窗口。'
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(
                ['osascript', '-e', f'display notification "{text}" with title "{title}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x00000040)
    except Exception:
        pass


def prepare_quiet_launch(settings_path, ini_path):
    current, _, _ = read_play_bgm(ini_path)
    stored = read_file(settings_path)
    if stored.get('audio_original') not in (0, 1):
        update_settings(settings_path, audio_original=current)
    write_play_bgm(ini_path, 0)
    update_settings(settings_path, audio_muted=True, quiet_launch=True,
                    audio_restore_written=False, audio_restore_heard=False)
    return read_file(settings_path).get('audio_original', current)


def launch_lobby():
    if not MAC_LAUNCHER.is_dir():
        return '找不到原生启动器，请用你平时的入口从大厅进游戏。音频已按安静等待写好。'
    subprocess.Popen(['open', str(MAC_LAUNCHER), '--args', '--launch-lobby'])
    return '已打开原生对战平台启动器。'


def spawn_detached(args, cwd=None):
    cwd = Path(cwd or ROOT)
    log = cwd / 'logs' / 'room-watch-spawn.log'
    log.parent.mkdir(exist_ok=True)
    stream = log.open('ab')
    env = os.environ.copy()
    try:
        from room_watch_focus import capture_frontmost, resume_env_value
        encoded = resume_env_value(capture_frontmost())
        if encoded:
            env['SGI_ROOM_WATCH_RESUME'] = encoded
    except Exception:
        pass
    kwargs = {
        'args': args,
        'cwd': str(cwd),
        'env': env,
        'stdout': stream,
        'stderr': subprocess.STDOUT,
        'start_new_session': True,
    }
    if sys.platform == 'win32':
        kwargs['creationflags'] = 0x00000008 | 0x00000200
    return subprocess.Popen(**kwargs)


def open_watch(quiet_wait):
    args = [sys.executable, '-B', str(ROOT / 'app/room_watch.py')]
    if quiet_wait:
        args.append('--quiet-wait')
    return spawn_detached(args)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = '--dry-run' in argv
    settings_path = ROOT / 'room-watch.local.json'
    roles = running_roles()
    step = plan(roles)
    result = dict(step, roles=roles, dry_run=dry)
    if dry:
        print(result['message'])
        return result
    if step['mode'] == 'already_open':
        notify_already_running()
        print(step['message'])
        return result
    if step['prepare']:
        ini = resolve_setting_ini(exe_path=known_game_exe(), prefix=wine_prefix())
        result['audio_original'] = prepare_quiet_launch(settings_path, ini)
        result['play_bgm'] = read_play_bgm(ini)[0]
    if step['launch_lobby']:
        result['lobby'] = launch_lobby()
    if step['watch']:
        open_watch(True)
    print(step['message'])
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('安静等待未启动：' + str(error), file=sys.stderr)
        sys.exit(1)
