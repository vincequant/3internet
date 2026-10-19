"""Wine navigation: room watch and a dedicated panorama window. Independent of Hub."""
import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from dock_icon import apply as apply_dock_icon
from mac_light_theme import apply_light_defaults
from quiet_wait_launch import spawn_detached

ROOT = Path(__file__).resolve().parent.parent
APP = Path(__file__).resolve().parent
LOG = ROOT / 'logs' / 'room-watch.jsonl'


def open_room_watch():
    spawn_detached([sys.executable, '-B', str(APP / 'room_watch.py')])


def open_quiet_wait():
    spawn_detached([sys.executable, '-B', str(APP / 'quiet_wait_launch.py')])


def panorama_command(center=None, zoom=None):
    cmd = [sys.executable, '-B', str(APP / 'panorama_map.py')]
    if center is not None:
        cmd += ['--center', f'{float(center[0])},{float(center[1])}']
    if zoom is not None:
        cmd += ['--zoom', str(float(zoom))]
    return cmd


def open_panorama(center=None, zoom=None):
    spawn_detached(panorama_command(center, zoom))


def replay_command(archive=None, demo=False):
    cmd = [sys.executable, '-B', str(APP / 'panorama_replay.py')]
    if demo:
        cmd.append('--demo')
    if archive:
        cmd += ['--archive', str(archive)]
    return cmd


def open_replay(archive=None, demo=False):
    spawn_detached(replay_command(archive, demo))


def hub_command():
    return [sys.executable, '-B', str(APP / 'mac_main.py')]


def open_hub():
    spawn_detached(hub_command())


def quick_control_command():
    return [sys.executable, '-B', str(APP / 'quick_control.py')]


def open_quick_control():
    spawn_detached(quick_control_command())


def latest_watch():
    if not LOG.is_file():
        return '还没有观察日志。点「本机房间人数」或「安静等待」开始。'
    try:
        line = LOG.read_text(encoding='utf-8').splitlines()[-1]
        row = json.loads(line)
    except (OSError, ValueError, IndexError):
        return '观察日志还读不出来。'
    rooms = row.get('rooms') or []
    message = row.get('message') or row.get('status') or '无说明'
    return f"{row.get('status', 'unknown')} · {message}" + (f' · {len(rooms)} 条房间' if rooms else '')


class RoomWatchPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg='#f7f4ea')
        tk.Label(self, text='房间观察', bg='#f7f4ea', fg='#302c22', font=('PingFang SC', 16, 'bold')).pack(anchor='w', padx=20, pady=(18, 6))
        tk.Label(
            self,
            text='已从 Hub 移出，只在 Wine 导航里开。不弹窗抢焦点、不自动入场、不写游戏内存。\n'
                 '安静等待仍要进 SANPK「游戏选择」才能看到 n/8；只登录大厅查不到房间人数。',
            bg='#f7f4ea', fg='#4a3d1d', justify='left', wraplength=720,
        ).pack(anchor='w', padx=20)
        bar = ttk.Frame(self)
        bar.pack(anchor='w', padx=20, pady=16)
        ttk.Button(bar, text='本机房间人数', command=open_room_watch).pack(side='left')
        ttk.Button(bar, text='安静等待', command=open_quiet_wait).pack(side='left', padx=10)
        self.status = tk.StringVar(value=latest_watch())
        tk.Label(self, textvariable=self.status, bg='#f7f4ea', fg='#655020', justify='left', wraplength=720).pack(anchor='w', padx=20, pady=(8, 20))
        self.after(2000, self._tick)

    def _tick(self):
        self.status.set(latest_watch())
        self.after(2000, self._tick)


class PanoramaPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg='#f7f4ea')
        tk.Label(self, text='全景地图', bg='#f7f4ea', fg='#302c22', font=('PingFang SC', 16, 'bold')).pack(anchor='w', padx=20, pady=(18, 6))
        tk.Label(
            self,
            text='独立全景视窗：放大后用原作地面，并叠城关、建筑、部队、陷阱、沿路补给线和首都位置。\n'
                 '补给线跟着原作道路走，不是城与城直线。不是引擎断粮判定。只读采集，不写游戏。已打开则继续用原窗口。',
            bg='#f7f4ea', fg='#4a3d1d', justify='left', wraplength=720,
        ).pack(anchor='w', padx=20)
        ttk.Button(self, text='打开全景视窗', command=open_panorama).pack(anchor='w', padx=20, pady=16)
        ttk.Button(self, text='打开历史回放', command=open_replay).pack(anchor='w', padx=20)
        tk.Label(
            self,
            text='历史回放只读本地整局档案，不启动采集桥，也不需要游戏在线。',
            bg='#f7f4ea', fg='#655020', justify='left', wraplength=720,
        ).pack(anchor='w', padx=20, pady=(8, 16))


def open_window(tab='rooms'):
    root = tk.Tk()
    apply_dock_icon(root, 'wine')
    apply_light_defaults(root)
    root.title('三国志 Wine · 导航')
    root.geometry('960x640')
    root.minsize(720, 480)
    toolbar = ttk.Frame(root, padding=(12, 8))
    toolbar.pack(fill='x')
    # 2026-10-19 用戶裁定：快捷修改面板（改寫遊戲數據）實測無效，入口移除。
    book = ttk.Notebook(root)
    book.pack(fill='both', expand=True)
    rooms = RoomWatchPage(book)
    panorama = PanoramaPage(book)
    book.add(rooms, text='房间观察')
    book.add(panorama, text='全景地图')
    book.select(panorama if tab == 'panorama' else rooms)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Wine navigation')
    parser.add_argument('--tab', choices=('rooms', 'panorama'), default='rooms')
    parser.add_argument('--launch', choices=('rooms', 'quiet', 'panorama', 'replay', 'nav', 'hub', 'quick'))
    args = parser.parse_args(argv)
    if args.launch == 'rooms':
        open_room_watch()
        return
    if args.launch == 'quiet':
        open_quiet_wait()
        return
    if args.launch == 'panorama' or args.tab == 'panorama':
        open_panorama()
        return
    if args.launch == 'replay':
        open_replay()
        return
    if args.launch == 'hub':
        open_hub()
        return
    if args.launch == 'quick':
        parser.error('快捷修改面板已於 2026-10-19 移除（實測改寫遊戲數據無效）')
    if args.launch == 'nav':
        spawn_detached([sys.executable, '-B', str(APP / 'wine_nav.py')])
        return
    open_window(args.tab)


if __name__ == '__main__':
    main()
