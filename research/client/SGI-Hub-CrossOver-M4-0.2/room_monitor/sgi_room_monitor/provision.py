"""Create an isolated monitor Wine prefix. Never copies login, tokens or saves."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import default_data_dir, load_config, save_json
from .version import VERSION

EXCLUDE = (
    'UserConfig.ini', 'UserConfig.before-login-repair.ini',
    'sgi-crash-context.bin',
)
EXCLUDE_DIRS = ('Save', 'save', 'SAVE', 'flight-records')
MONITOR_UDP = 4578
FONT_REPLACEMENTS = {
    'Microsoft Sans Serif': 'Arial Unicode MS',
    'MS Sans Serif': 'Arial Unicode MS',
    'MS Shell Dlg': 'Arial Unicode MS',
    'MS Shell Dlg 2': 'Arial Unicode MS',
    'NSimSun': 'Arial Unicode MS',
    'SimSun': 'Arial Unicode MS',
    'Tahoma': 'Arial Unicode MS',
    '宋体': 'Arial Unicode MS',
}
TEMPLATE = '''[User]
UserName=
Password=
RemberPwd=False
FONT_Name=宋体
FONT_Color=0
FONT_Size=0
FONT_Bold=0
FONT_Italic=0
FONT_Underline=0
FONT_StrikeOut=0
[Settings]
MoveUnitAnime=0
BattleNotifyMsg=1
PlayBGM=0
PlaySE=0
WaveKOEI=0
[Misc]
BeepOnRecvBroad=True
LoaderUdpPort={port}
UseSound=False
SkinIndex=0
SkinHue=0
SkinSaturation=0
[Game]
GameName1001=三国对战房
GameExe1001=./3I\\SANPK.exe
GameParam1001=/1an
[Window]
SmallMapPos=589,137,902,372
MainWndPos=0,0,1280,738,1
'''


def default_paths():
    if sys.platform.startswith('linux'):
        wine_root = Path(os.environ.get('SGI_WINE_ROOT') or (Path.home() / '.local/share/sgi-wine'))
        wine = shutil.which('wine')
        return {
            'wine_root': wine_root,
            'wine': Path(wine) if wine else wine_root / 'bin/wine',
            'main_prefix': Path(os.environ.get('SGI_MAIN_PREFIX') or ''),
            'monitor_prefix': Path(os.environ.get('SGI_MONITOR_PREFIX') or (wine_root / 'prefix-monitor')),
            'font': wine_root / 'fonts/arialuni.ttf',
        }
    if sys.platform == 'win32':
        root = Path(os.environ.get('SGI_GAME_ROOT') or r'C:\sgi\run-3.5')
        return {
            'wine_root': root,
            'wine': None,
            'main_prefix': Path(os.environ.get('SGI_MAIN_PREFIX') or ''),
            'monitor_prefix': Path(os.environ.get('SGI_MONITOR_PREFIX') or (root.parent / 'monitor')),
            'font': None,
        }
    wine_root = Path.home() / 'Library/Application Support/SGI-Wine'
    return {
        'wine_root': wine_root,
        'wine': wine_root / 'runtime-sikarugir10/wswine.bundle/bin/wine',
        'main_prefix': wine_root / 'prefix-sikarugir10',
        'monitor_prefix': wine_root / 'prefix-monitor',
        'font': wine_root / 'prefix-sikarugir10/drive_c/windows/Fonts/arialuni.ttf',
    }


def wine_env(wine, prefix, extra=None):
    env = dict(os.environ)
    env['WINEPREFIX'] = str(Path(prefix).expanduser())
    env['SGI_WINE_BINARY'] = str(wine)
    env['WINEDEBUG'] = '-all'
    env['WINEDEBUGGER'] = ''
    env['WINEDLLOVERRIDES'] = 'winegstreamer=d;winemenubuilder.exe=d'
    env['LANG'] = 'zh_CN.UTF-8'
    env['LC_ALL'] = 'zh_CN.UTF-8'
    libs = []
    wine_root = Path.home() / 'Library/Application Support/SGI-Wine'
    for candidate in (
        wine_root / 'dependency-lib',
        wine_root / 'runtime/Wine Stable.app/Contents/Resources/wine/lib',
        Path(wine).resolve().parent.parent / 'lib',
    ):
        if candidate.is_dir():
            libs.append(str(candidate))
    if libs:
        env['DYLD_FALLBACK_LIBRARY_PATH'] = ':'.join(dict.fromkeys(libs))
    for key in ('CX_BOTTLE', 'CX_ROOT', 'WINESERVER', 'WINELOADER', 'WINEDLLPATH'):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def prefix_owned_pids(prefix):
    prefix = str(Path(prefix).resolve())
    found = []
    listing = subprocess.check_output(['/bin/ps', '-axo', 'pid=,lstart=,command='], text=True, errors='replace')
    for line in listing.splitlines():
        parts = line.strip().split(None, 6)
        if len(parts) < 7:
            continue
        pid, command = parts[0], parts[6]
        if not pid.isdigit():
            continue
        if prefix in command:
            found.append({'pid': int(pid), 'started': ' '.join(parts[1:6]), 'command': command})
            continue
        if not any(name in command for name in ('SANGUO.exe', 'SANPK.exe', 'wineserver')):
            continue
        try:
            cwd = subprocess.check_output(
                ['/usr/sbin/lsof', '-a', '-p', pid, '-d', 'cwd', '-Fn'],
                text=True, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        path = next((row[1:] for row in cwd.splitlines() if row.startswith('n')), '')
        if path.startswith(prefix + '/') or path == prefix:
            found.append({'pid': int(pid), 'started': ' '.join(parts[1:6]), 'command': command, 'cwd': path})
    return found


def file_sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_game(src, dest):
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    skipped = []
    for item in src.iterdir():
        if item.name in EXCLUDE or item.name.endswith('.log'):
            skipped.append(item.name)
            continue
        if item.name in EXCLUDE_DIRS:
            skipped.append(item.name + '/')
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*EXCLUDE, *EXCLUDE_DIRS, '*.log'))
        else:
            shutil.copy2(item, target)
        copied.append(item.name)
    save = dest / '3I' / 'Save'
    if save.is_dir():
        shutil.rmtree(save)
        skipped.append('3I/Save/')
    crash = dest / '3I' / 'sgi-crash-context.bin'
    if crash.is_file():
        crash.unlink()
        skipped.append('3I/sgi-crash-context.bin')
    user = dest / 'UserConfig.ini'
    if user.is_file():
        user.unlink()
        skipped.append('UserConfig.ini')
    return copied, skipped


def apply_cjk_fonts(wine, prefix, env=None):
    """Map 宋体/SimSun/MS Shell Dlg to Arial Unicode MS. Do not copy login keys."""
    env = env or wine_env(wine, prefix)
    prefix = Path(prefix).expanduser()
    font = prefix / 'drive_c/windows/Fonts/arialuni.ttf'
    if not font.is_file():
        return {'ok': False, 'error': '缺少 arialuni.ttf'}
    commands = [
        (r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Fonts',
         'Arial Unicode MS (TrueType)', 'arialuni.ttf'),
        (r'HKCU\Software\Wine\Fonts\External Fonts',
         'Arial Unicode MS (TrueType)', r'C:\windows\Fonts\arialuni.ttf'),
        (r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\FontSubstitutes',
         'MS Shell Dlg', 'Arial Unicode MS'),
        (r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\FontSubstitutes',
         'MS Shell Dlg 2', 'Arial Unicode MS'),
    ]
    for name, dest in FONT_REPLACEMENTS.items():
        commands.append((r'HKCU\Software\Wine\Fonts\Replacements', name, dest))
    failed = []
    for key, value, data in commands:
        result = subprocess.run(
            [str(wine), 'reg', 'add', key, '/v', value, '/t', 'REG_SZ', '/d', data, '/f'],
            env=env, capture_output=True, timeout=40)
        if result.returncode != 0:
            failed.append(value)
    return {'ok': not failed, 'failed': failed, 'mapped': list(FONT_REPLACEMENTS)}


def stop_monitor_wineserver(wine, prefix):
    """Kill only this prefix's wineserver. Never call without WINEPREFIX=monitor."""
    prefix = Path(prefix).expanduser()
    main = default_paths()['main_prefix']
    if prefix.resolve() == Path(main).resolve():
        return {'ok': False, 'error': '拒绝停止主号 wineserver'}
    env = wine_env(wine, prefix)
    server = Path(wine).parent / 'wineserver'
    if server.is_file():
        subprocess.call([str(server), '-k'], env=env)
    time.sleep(1)
    leftover = prefix_owned_pids(prefix)
    return {'ok': leftover == [], 'leftover': leftover}


def write_userconfig(dest, port=MONITOR_UDP):
    path = dest / 'UserConfig.ini'
    path.write_bytes(TEMPLATE.format(port=int(port)).encode('gb18030'))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def provision(config=None, start_lobby=False):
    paths = default_paths()
    wine, main, monitor = paths['wine'], paths['main_prefix'], paths['monitor_prefix']
    report = {
        'version': VERSION,
        'ok': False,
        'wine': str(wine),
        'main_prefix': str(main),
        'monitor_prefix': str(monitor),
        'udp_port': MONITOR_UDP,
        'started_lobby': False,
        'main_before': prefix_owned_pids(main),
    }
    if not wine.is_file():
        report['error'] = '找不到 Wine 可执行文件'
        return report
    if not (main / 'system.reg').is_file():
        report['error'] = '主号 prefix 不完整，拒绝以其为复制源'
        return report
    if monitor.resolve() == main.resolve():
        report['error'] = '监控 prefix 不能与主号相同'
        return report
    game_src = main / 'drive_c/sgi/run-3.5'
    if not (game_src / 'SANGUO.exe').is_file() or not (game_src / '3I/SANPK.exe').is_file():
        report['error'] = '主号游戏目录缺少大厅或 SANPK'
        return report
    monitor.mkdir(parents=True, exist_ok=True)
    env = wine_env(wine, monitor)
    if not (monitor / 'system.reg').is_file():
        boot = subprocess.run([str(wine), 'wineboot', '-u'], env=env, capture_output=True, text=True, timeout=180)
        if boot.returncode != 0 or not (monitor / 'system.reg').is_file():
            report['error'] = 'wineboot 未生成独立 system.reg'
            report['wineboot_code'] = boot.returncode
            return report
    if not (monitor / 'system.reg').is_file():
        report['error'] = 'wineboot 未生成独立 system.reg'
        return report
    dest = monitor / 'drive_c/sgi/run-3.5'
    copied, skipped = copy_game(game_src, dest)
    write_userconfig(dest, MONITOR_UDP)
    font_src, font_dst = paths['font'], monitor / 'drive_c/windows/Fonts/arialuni.ttf'
    if font_src.is_file():
        font_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(font_src, font_dst)
        report['font'] = 'arialuni.ttf'
    report['cjk_fonts'] = apply_cjk_fonts(wine, monitor, env)
    sanpk = dest / '3I/SANPK.exe'
    main_sanpk = game_src / '3I/SANPK.exe'
    report.update({
        'copied': copied,
        'skipped': skipped,
        'sanpk_sha256': file_sha256(sanpk),
        'sanpk_matches_main': file_sha256(sanpk) == file_sha256(main_sanpk),
        'userconfig_has_password': _userconfig_has_password(dest / 'UserConfig.ini'),
        'save_present': (dest / '3I/Save').exists(),
    })
    version = subprocess.check_output([str(wine), '--version'], env=env, text=True, timeout=30).strip()
    report['wine_version'] = version
    main_after = prefix_owned_pids(main)
    report['main_after'] = main_after
    report['main_pids_unchanged'] = _pids(report['main_before']) == _pids(main_after)
    if start_lobby:
        report.update(_smoke_lobby(wine, monitor, dest, env))
    else:
        server = Path(wine).parent / 'wineserver'
        if server.is_file():
            subprocess.call([str(server), '-k'], env=env)
        report['monitor_wineserver_stopped'] = prefix_owned_pids(monitor) == []
    report['ok'] = bool(report['sanpk_matches_main'] and report['main_pids_unchanged']
                        and not report['userconfig_has_password'] and not report['save_present'])
    _write_report(report)
    _update_config(config, monitor, main)
    return report


def _smoke_lobby(wine, monitor, dest, env):
    lobby = dest / 'SANGUO.exe'
    proc = subprocess.Popen([str(wine), str(lobby)], env=env, cwd=str(dest),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    owned = prefix_owned_pids(monitor)
    identity = {
        'started_lobby': True,
        'launcher_pid': proc.pid,
        'monitor_owned': owned,
    }
    server = Path(wine).parent / 'wineserver'
    if server.is_file():
        subprocess.call([str(server), '-k'], env=env)
    time.sleep(1)
    leftover = prefix_owned_pids(monitor)
    identity['monitor_after_stop'] = leftover
    identity['monitor_stopped_clean'] = leftover == []
    return identity


def _userconfig_has_password(path):
    if not path.is_file():
        return False
    text = path.read_bytes().decode('gb18030', 'replace')
    for line in text.splitlines():
        if line.startswith('Password=') and line.split('=', 1)[1].strip():
            return True
    return False


def _pids(rows):
    return sorted(item['pid'] for item in rows or [])


def _write_report(report):
    data_dir = default_data_dir()
    save_json(data_dir / 'prefix-report.json', report)


def _update_config(config, monitor, main):
    data_dir = default_data_dir()
    current = dict(config or load_config(data_dir))
    current['monitor_prefix'] = str(monitor)
    current['main_prefix'] = str(main)
    current.pop('data_dir', None)
    save_json(data_dir / 'config.json', current)
