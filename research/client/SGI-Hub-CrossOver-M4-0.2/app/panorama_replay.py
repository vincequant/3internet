"""Independent panorama replay. Reads local archives only; never starts the collector."""
import json
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from dock_icon import apply as apply_dock_icon
from mac_light_theme import apply_light_defaults
from panorama_map import PanoramaMap, maximize, ui_font
from panorama_model import clamp_center, live_objects, object_key, world_xy

APP = Path(__file__).resolve().parent
ROOT = APP.parent
BRIDGE = ROOT / 'bridge'
if str(BRIDGE) not in sys.path:
    sys.path.append(str(BRIDGE))

from game_archive import default_archive_root, list_archives, phase_of, write_demo_archive
from match_opening import listed_archive
from state_history import calendar_label, phase_label, short_quarter_label
from history_review import archive_list_entries
from match_opening import clamp_replay_seq, first_locked_seq, remember_opening_seq
from replay_view import (
    ReplayCursor, command_line_text, filter_forces, force_command_ledger,
    interpolate_units, ledger_fingerprint, select_live_track, track_draw_polylines,
)

BG = '#1b1d18'
BAR = '#2a2c24'
INK = '#efe7cf'
MUTED = '#b7ad8f'
EVIDENCE_FG = {
    'fact': '#c8f0c0',
    'observed_change': '#d7e4f5',
    'inferred': '#f3d48a',
    'unknown': '#c9c3b4',
}
OPS_RAW_TITLE = '原始指令：未捕获'
OPS_RAW_NOTE = '原始指令尚未捕获；不能据此判断没有下令。'
OPS_INFER_TITLE = '状态事实／历史推断（参考）'
OPS_INFER_NOTE = (
    '状态事实／历史推断（参考），由相邻帧变化整理。点一行跳到该帧。'
    '观察记录不能代替原始指令，也不能据此判断没有下令。'
)
OBS_EMPTY = '此窗口未观察到相关变化；不代表没有下令'


def ops_source_header(parent, face):
    """Raw-instruction title plus the separate state/inference caption."""
    raw = tk.Label(parent, text=OPS_RAW_TITLE, bg='#22241d', fg=INK, font=(face, 12, 'bold'))
    note = tk.Label(parent, text=OPS_INFER_NOTE, bg='#22241d', fg=MUTED, wraplength=370,
                    justify='left', font=(face, 10))
    return raw, note


def bind_clickable(text_widget, line, style, on_click):
    start = text_widget.index('end-1c')
    unique = 'hit-' + start.replace('.', '-')
    text_widget.insert('end', line, (style, unique))
    text_widget.tag_bind(unique, '<Button-1>', lambda _e=None: on_click())
    text_widget.tag_configure(unique, underline=False)
    try:
        text_widget.tag_bind(unique, '<Enter>', lambda _e=None: text_widget.configure(cursor='hand2'))
        text_widget.tag_bind(unique, '<Leave>', lambda _e=None: text_widget.configure(cursor=''))
    except tk.TclError:
        pass
    return unique


def demo_path():
    return APP / 'demo_replay_match'


class ReplayApp:
    def __init__(self, root, archive=None):
        self.root = root
        self.face = ui_font(root)
        self.cursor = None
        self.playing = False
        self.follow = tk.BooleanVar(value=False)
        self.interpolate = tk.BooleanVar(value=False)
        self.speed = tk.DoubleVar(value=1.0)
        self.force_filter = tk.StringVar(value='全部势力')
        self.clock = tk.StringVar(value='未打开档案')
        self.banner = tk.StringVar(value='打开本地整局档案。不启动游戏，不启动采集桥。')
        self.selected_unit = None
        self.archives = []
        self._list_rows = []
        self._ignore_pick = False
        self._opening = False
        self._ignore_scrub = False
        self._scrub_job = None
        self._ops_seq = None
        self._ops_key = None
        self._force_names = None
        self._opening_seq = 1
        self._catchup_job = None
        apply_light_defaults(root)
        root.title('全景回放 · 整局档案')
        root.configure(bg=BG)
        root.minsize(1100, 720)
        self._build()
        maximize(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        path = Path(archive) if archive else None
        self.refresh_list()
        if path and (path / 'manifest.json').is_file() and not self._is_demo(path):
            self.open_path(path)
        elif self.archives:
            self.open_path(self.archives[0]['directory'])

    def _build(self):
        top = tk.Frame(self.root, bg=BAR)
        top.pack(fill='x')
        tk.Label(top, text='独立全景回放', bg=BAR, fg=INK, font=(self.face, 16, 'bold')).pack(side='left', padx=12, pady=8)
        tk.Button(top, text='打开档案…', command=self.choose, bg='#3d3f34', fg=INK, relief='flat', padx=10).pack(side='left')
        tk.Button(top, text='刷新列表', command=self.refresh_list, bg='#3d3f34', fg=INK, relief='flat', padx=10).pack(side='left', padx=4)
        tk.Label(top, textvariable=self.clock, bg=BAR, fg='#d8c27a', font=(self.face, 11)).pack(side='right', padx=12)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True)
        left = tk.Frame(body, bg='#22241d', width=280)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        tk.Label(left, text='对局档案', bg='#22241d', fg=INK, font=(self.face, 12, 'bold')).pack(anchor='w', padx=10, pady=(10, 2))
        self.listbox = tk.Listbox(left, bg='#2c2f26', fg=INK, selectbackground='#6a5520', relief='flat', font=(self.face, 11))
        self.listbox.pack(fill='both', expand=True, padx=8, pady=6)
        self.listbox.bind('<<ListboxSelect>>', self._pick_archive)
        self.listbox.bind('<Double-Button-1>', self._pick_archive)
        tk.Label(left, text='季度  [上一 ]下一', bg='#22241d', fg=INK, font=(self.face, 12, 'bold')).pack(anchor='w', padx=10)
        self.jumps = tk.Listbox(left, bg='#2c2f26', fg=INK, selectbackground='#3d5a7a', relief='flat', font=(self.face, 10), height=12)
        self.jumps.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.jumps.bind('<<ListboxSelect>>', self._pick_jump)
        self.jumps.bind('<Double-Button-1>', self._pick_jump)
        self.jump_targets = []

        mid = tk.Frame(body, bg=BG)
        mid.pack(side='left', fill='both', expand=True)
        self.map = PanoramaMap(mid, title='回放地图')
        self.map.pack(fill='both', expand=True)
        self.map.status.set('离线回放')
        self.map.after_draw = self._draw_tracks
        self._track = None

        right = tk.Frame(body, bg='#22241d', width=400)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        tk.Label(right, textvariable=self.banner, bg='#22241d', fg='#e4c56a', wraplength=370, justify='left',
                 font=(self.face, 11)).pack(fill='x', padx=10, pady=(10, 4))
        self.ops_raw_title, self.ops_infer_note = ops_source_header(right, self.face)
        self.ops_raw_title.pack(anchor='w', padx=10)
        self.ops_infer_note.pack(fill='x', padx=10, pady=(0, 4))
        self.ops = tk.Text(right, bg='#2c2f26', fg=INK, relief='flat', font=(self.face, 11), wrap='word', height=18)
        self.ops.pack(fill='both', expand=True, padx=8, pady=8)
        self.ops.bind('<Key>', lambda _e=None: 'break')
        self.ops.bind('<<Paste>>', lambda _e=None: 'break')
        for tag, color in EVIDENCE_FG.items():
            self.ops.tag_configure(tag, foreground=color)
        self.ops.tag_configure('head', foreground='#ffe9a3', font=(self.face, 11, 'bold'))
        self.ops.tag_configure('force', foreground='#ffe9a3', font=(self.face, 12, 'bold'))
        self.ops.tag_configure('quarter', foreground='#c4b48a', font=(self.face, 10))
        self.ops.tag_configure('lane', foreground='#8fb0d8')
        self.ops.tag_configure('empty', foreground='#8a8474')

        bottom = tk.Frame(self.root, bg=BAR)
        bottom.pack(fill='x')
        for text, cmd in (('从头', self.restart), ('上一季 [', lambda: self._step_quarter(-1)),
                          ('上一帧', lambda: self.step(-1)), ('播放/暂停', self.toggle),
                          ('下一帧', lambda: self.step(1)), ('下一季 ]', lambda: self._step_quarter(1))):
            tk.Button(bottom, text=text, command=cmd, bg='#3d3f34', fg=INK, relief='flat', padx=8).pack(side='left', padx=3, pady=6)
        self.root.bind('<KeyPress-bracketleft>', lambda e: self._step_quarter(-1, e))
        self.root.bind('<KeyPress-bracketright>', lambda e: self._step_quarter(1, e))
        tk.Label(bottom, text='速度', bg=BAR, fg=MUTED).pack(side='left', padx=(12, 2))
        ttk.Combobox(bottom, textvariable=self.speed, values=(0.5, 1, 2, 4, 8), width=5, state='readonly').pack(side='left')
        tk.Checkbutton(bottom, text='跟随所选部队', variable=self.follow, bg=BAR, fg=INK, selectcolor=BAR,
                       activebackground=BAR).pack(side='left', padx=8)
        tk.Checkbutton(bottom, text='视觉插值（非事实）', variable=self.interpolate, bg=BAR, fg='#f3d48a',
                       selectcolor=BAR, activebackground=BAR, command=self.render).pack(side='left')
        tk.Label(bottom, text='势力', bg=BAR, fg=MUTED).pack(side='left', padx=(10, 2))
        self.force_box = ttk.Combobox(bottom, textvariable=self.force_filter, values=('全部势力',), width=12, state='readonly')
        self.force_box.pack(side='left')
        self.force_box.bind('<<ComboboxSelected>>', lambda _e=None: self.render(heavy=False))
        self.timeline = tk.Scale(bottom, from_=1, to=1, orient='horizontal', bg=BAR, fg=INK, troughcolor='#3d3f34',
                                 highlightthickness=0, command=self._scrub, showvalue=False)
        self.timeline.pack(side='left', fill='x', expand=True, padx=10)
        self.timeline.bind('<ButtonRelease-1>', self._scrub_commit)

    def _is_demo(self, path):
        path = Path(path)
        if path.resolve() == demo_path().resolve():
            return True
        try:
            data = json.loads((path / 'manifest.json').read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(data.get('simulated'))

    def _current_dir(self):
        if not self.cursor:
            return None
        return Path(self.cursor.reader.directory)

    def _list_zone(self):
        return datetime.now().astimezone().tzinfo

    def refresh_list(self):
        current = self._current_dir()
        self.archives = [row for row in list_archives() if listed_archive(row)]
        entries = archive_list_entries(self.archives, tz=self._list_zone())
        self._list_rows = []
        self._ignore_pick = True
        try:
            self.listbox.delete(0, 'end')
            selected = None
            for entry in entries:
                self.listbox.insert('end', entry['label'])
                index = self.listbox.size() - 1
                self._list_rows.append(entry['row'])
                if entry['kind'] == 'day':
                    self.listbox.itemconfig(index, fg='#d8c27a')
                elif current and Path(entry['row']['directory']) == current:
                    selected = index
            if selected is not None:
                self.listbox.selection_set(selected)
                self.listbox.activate(selected)
                self.listbox.see(selected)
        finally:
            self.root.after_idle(self._clear_ignore_pick)

    def _keep_open_selection(self):
        current = self._current_dir()
        self._ignore_pick = True
        try:
            self.listbox.selection_clear(0, 'end')
            if current is None:
                return
            for index, row in enumerate(self._list_rows):
                if row and Path(row['directory']) == current:
                    self.listbox.selection_set(index)
                    self.listbox.activate(index)
                    return
        finally:
            self.root.after_idle(self._clear_ignore_pick)

    def _clear_ignore_pick(self):
        self._ignore_pick = False

    def choose(self):
        path = filedialog.askdirectory(title='选择整局档案目录（含 manifest.json）', initialdir=str(default_archive_root()))
        if path and not self._is_demo(path):
            self.open_path(path)

    def _pick_archive(self, _=None):
        if self._ignore_pick or self._opening:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        row = self._list_rows[index] if index < len(self._list_rows) else None
        if not row:
            self._keep_open_selection()
            return
        path = row['directory']
        if self._current_dir() and Path(path) == self._current_dir():
            return
        self.banner.set('正在打开档案…')
        self._opening = True
        self.root.after_idle(lambda: self._open_later(path))

    def _open_later(self, path):
        try:
            self.open_path(path)
        finally:
            self._opening = False

    def open_path(self, path):
        path = Path(path)
        if self._is_demo(path):
            self.banner.set('模拟演示档案已从列表拿掉，只打开真实对局。')
            return
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        self.playing = False
        self._cancel_catchup()
        self._ops_key = None
        self._ops_seq = None
        self.map._ops_from_replay = True
        self.map._force_ledger = None
        self.map.focus_force_id = None
        self.cursor = ReplayCursor(path)
        n = max(1, self.cursor.frame_count())
        start = first_locked_seq(path, reader=self.cursor.reader) or 1
        if start > 1:
            remember_opening_seq(path, start)
        self._opening_seq = start
        if self._scrub_job:
            self.root.after_cancel(self._scrub_job)
            self._scrub_job = None
        self._ignore_scrub = True
        try:
            self.timeline.configure(from_=start, to=n)
            self.timeline.set(start)
        finally:
            self._ignore_scrub = False
        self._seek(start)
        self._mark_current(path)
        self._fill_jumps()
        self.render(heavy=False)
        self._schedule_catchup()

    def _seek(self, seq):
        if not self.cursor:
            return
        self.cursor.seek(clamp_replay_seq(seq, self._opening_seq, self.cursor.frame_count()))

    def _mark_current(self, path):
        path = Path(path)
        self._ignore_pick = True
        try:
            self.listbox.selection_clear(0, 'end')
            for index, row in enumerate(self.archives):
                if Path(row['directory']) == path:
                    self.listbox.selection_set(index)
                    self.listbox.activate(index)
                    self.listbox.see(index)
                    break
        finally:
            self.root.after_idle(self._clear_ignore_pick)

    def _jump_rows(self):
        if not self.cursor:
            return []
        rows = self.cursor.reader.index.get('quarters') or []
        return rows or (self.cursor.reader.index.get('rounds') or [])

    def _quarter_jump_label(self, row):
        pretty = calendar_label(row.get('year_u16'), row.get('season_u16'))
        if pretty:
            return pretty
        label = str(row.get('label') or '')
        if label:
            return label.replace(' · 内政', '').split(' 第')[0]
        return short_quarter_label(row.get('label'), row)

    def _fill_jumps(self):
        self._ignore_pick = True
        try:
            self.jumps.delete(0, 'end')
            self.jump_targets = []
            if not self.cursor:
                return
            start = getattr(self, '_opening_seq', 1) or 1
            seen = set()
            entries = []

            def add_jump(seq, label):
                seq = clamp_replay_seq(seq, start, self.cursor.frame_count())
                if seq in seen:
                    return
                seen.add(seq)
                entries.append((seq, label))

            title = (self.cursor.manifest() or {}).get('title') or '开局收束'
            quarters = []
            for row in self._jump_rows():
                last = row.get('last_seq') or 0
                if last and last < start:
                    continue
                first = max(start, row.get('first_seq') or start)
                quarters.append((first, self._quarter_jump_label(row)))
            if start not in {seq for seq, _ in quarters}:
                add_jump(start, title)
            for first, label in quarters:
                add_jump(first, label)
            for row in self.cursor.reader.index.get('gaps') or []:
                after = row.get('after_seq') or start
                if after < start:
                    continue
                add_jump(after, f"缺口 {row.get('reason')}")
            for row in self.cursor.reader.index.get('events') or []:
                seq = row.get('seq') or start
                if seq < start:
                    continue
                add_jump(seq, f"事件 {row.get('type') or row.get('reason')}")
            entries.sort(key=lambda item: item[0])
            for seq, label in entries:
                self.jump_targets.append(seq)
                self.jumps.insert('end', label)
            self._sync_jumps()
        finally:
            self.root.after_idle(self._clear_ignore_pick)

    def _sync_jumps(self):
        if not self.cursor or not self.jump_targets:
            return
        seq = self.cursor.seq
        index = 0
        for i, target in enumerate(self.jump_targets):
            if target <= seq:
                index = i
            else:
                break
        self._ignore_pick = True
        try:
            self.jumps.selection_clear(0, 'end')
            self.jumps.selection_set(index)
            self.jumps.activate(index)
            self.jumps.see(index)
        finally:
            self.root.after_idle(self._clear_ignore_pick)

    def _pick_jump(self, _=None):
        if self._ignore_pick:
            return
        selection = self.jumps.curselection()
        if not selection or not self.cursor:
            return
        seq = self.jump_targets[selection[0]]
        self._seek(seq)
        self.render(heavy=False)
        self._schedule_catchup()

    def _scrub(self, value):
        if self._ignore_scrub or not self.cursor:
            return
        seq = clamp_replay_seq(value, self._opening_seq, self.cursor.frame_count())
        self._seek(seq)
        self.clock.set(f'帧 {seq}/{self.cursor.frame_count()}')
        if self._scrub_job:
            self.root.after_cancel(self._scrub_job)
        self._scrub_job = self.root.after(70, self._scrub_commit)

    def _scrub_commit(self, _=None):
        if self._scrub_job:
            self.root.after_cancel(self._scrub_job)
            self._scrub_job = None
        if self.cursor:
            self.render(heavy=False)
            self._schedule_catchup()

    def restart(self):
        if self.cursor:
            self._seek(self._opening_seq)
            self.render(heavy=False)
            self._schedule_catchup()

    def step(self, delta):
        if not self.cursor:
            return
        self._seek(self.cursor.seq + delta)
        self.render(heavy=False)
        if not self.playing:
            self._schedule_catchup()

    def _quarter_starts(self):
        start = getattr(self, '_opening_seq', 1) or 1
        n = self.cursor.frame_count() if self.cursor else 1
        seqs = []
        seen = set()
        for row in self._jump_rows():
            first = max(start, row.get('first_seq') or start)
            first = clamp_replay_seq(first, start, n)
            if first in seen:
                continue
            seen.add(first)
            seqs.append(first)
        if start not in seen:
            seqs.insert(0, start)
        return seqs

    def _step_quarter(self, delta, event=None):
        widget = getattr(event, 'widget', None)
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            return
        if not self.cursor:
            return
        seqs = self._quarter_starts()
        if not seqs:
            return
        current = self.cursor.seq
        if delta < 0:
            earlier = [seq for seq in seqs if seq < current]
            target = earlier[-1] if earlier else seqs[0]
        else:
            later = [seq for seq in seqs if seq > current]
            target = later[0] if later else seqs[-1]
        self.playing = False
        self._seek(target)
        self.render(heavy=False)
        self._schedule_catchup()
        return 'break'

    def toggle(self):
        self.playing = not self.playing
        if self.playing:
            self._cancel_catchup()
            self._tick_play()
        else:
            self.render(heavy=False)
            self._schedule_catchup()

    def _tick_play(self):
        if not self.playing or not self.cursor:
            return
        if self.cursor.seq >= self.cursor.frame_count():
            self.playing = False
            self.render(heavy=False)
            self._schedule_catchup()
            return
        speed = max(0.5, float(self.speed.get() or 1))
        self._seek(self.cursor.seq + (1 if speed <= 1 else int(speed)))
        self.render(heavy=False)
        self.root.after(max(16, int(1000 / speed)), self._tick_play)

    def _force_ids(self):
        text = self.force_filter.get()
        if not text or text == '全部势力' or not self.cursor:
            return None
        state = self.cursor.frame_state(clone=False)
        for row in (state or {}).get('entities', {}).get('lords') or []:
            if row.get('name') == text:
                return [row.get('force_id')]
        return None

    def render(self, heavy=True):
        if not self.cursor or self.cursor.frame_count() <= 0:
            self.clock.set('档案无完整帧')
            return
        if not heavy:
            self._render_light()
            return
        want_track = self._selected_unit_id() is not None
        view = self.cursor.view(include_tracks=want_track, include_history=True, include_events=True)
        raw = view.get('state') or self.cursor.frame_state()
        from unit_combat import enrich_unit_combat
        enrich_unit_combat(raw)
        names = ['全部势力'] + [row.get('name') or f"#{row.get('force_id')}"
                                for row in (raw or {}).get('entities', {}).get('lords') or []]
        if names != self._force_names:
            self._force_names = names
            self.force_box.configure(values=names)
        display = raw
        if self.interpolate.get() and 1 < view['seq'] < view['frame_count'] and not self._gap_after(view['seq']):
            nxt = self.cursor.frame_state(view['seq'] + 1)
            display = interpolate_units(raw, nxt, 0.35)
        force_ids = self._force_ids()
        if force_ids:
            display = filter_forces(display, force_ids)
        problems = view.get('resource_problems') or []
        if problems:
            self.map.terrain = None
            self.map.lbm = None
            self.map.terrain_error = '地图资源与档案不一致，已停用底图：' + '；'.join(
                f"{row['path']} {row['issue']}" for row in problems
            )
            self.map._terrain_key = None
        if self.follow.get() and self.map.selected:
            self.map.state = display
            kind, row = self.map._selected_row()
            if row is not None and kind == '部队':
                xy = world_xy(row)
                self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
        self.map.update_state(display, lists=heavy, immediate=heavy)
        if view.get('first_frame_note'):
            self.map.detail.set(view['first_frame_note'])
        gap = ' · 有缺口' if view.get('gaps') else ''
        mid = ' · 从此处开始记录' if view.get('started_mid_match') else ''
        sim = ' · 模拟演示' if view.get('simulated') else ''
        interp = ' · 视觉插值（非事实）' if display.get('visual_interpolation') else ''
        self.clock.set(
            f"帧 {view['seq']}/{view['frame_count']} · {view.get('phase_label')} · {view.get('stage_cn')}{gap}{mid}{sim}{interp}"
        )
        if heavy:
            banner = []
            from replay_modifications import summary, label
            modification = label(summary(self.cursor.reader.directory, self.cursor.reader))
            if modification:
                banner.append('本局审核标记（不作为决策前特征）：'+modification+'。')
            if getattr(self, '_opening_seq', 1) > 1:
                banner.append(
                    f'前 {self._opening_seq - 1} 帧还是全国 22 势力未收束，已跳到第 {self._opening_seq} 帧的'
                    f'{(self.cursor.manifest() or {}).get("title") or "开局"}。'
                )
            if view.get('simulated'):
                banner.append('这是模拟演示档案，不是真实对局。')
            if view.get('started_mid_match'):
                banner.append('记录从中途开始，前面的对局不在本档案中。')
            if view.get('tail_truncated'):
                banner.append('档案尾部曾截断，只回放到最后完整帧。')
            if view.get('completeness') == 'write_error':
                banner.append('当时写入失败，完整性不能当作完整。')
            dropped = self.cursor.manifest().get('dropped_frames') or 0
            if dropped:
                banner.append(f'记录时可见丢帧 {dropped}。')
            banner.append('无数据不等于没有下令或没有行动。选定帧不会混入后来才知道的事件。')
            self.banner.set(' '.join(banner))
            self._refresh_ops(view)
        selected = self._selected_unit_id()
        self._track = None
        if selected is not None:
            matches = select_live_track(view.get('tracks') or {}, view['seq'], selected)
            live = [row for row in matches if row.get('live_at_seq')]
            chosen = live[0] if len(live) == 1 else (matches[0] if len(matches) == 1 else None)
            if chosen is not None:
                self._track = chosen
            if len(live) != 1:
                self.map.detail.set('部队 ID 曾复用或本帧无法唯一定位，未串接旧代轨迹。')
        self._stamp_timeline(view['seq'])
        self._sync_jumps()

    def _render_light(self):
        raw = self.cursor.frame_state()
        if raw is None:
            return
        from unit_combat import enrich_unit_combat
        enrich_unit_combat(raw)
        display = raw
        force_ids = self._force_ids()
        if force_ids:
            display = filter_forces(raw, force_ids)
        self.map.update_state(display, lists=False, immediate=True, refresh_view=not self.playing)
        phase = phase_of(raw) or {}
        self.clock.set(f"帧 {self.cursor.seq}/{self.cursor.frame_count()} · {phase_label(phase)}")
        self._stamp_timeline(self.cursor.seq)
        self._sync_jumps()

    def _stamp_timeline(self, seq):
        self._ignore_scrub = True
        try:
            self.timeline.set(seq)
        finally:
            self._ignore_scrub = False

    def _cancel_catchup(self):
        if self._catchup_job:
            self.root.after_cancel(self._catchup_job)
            self._catchup_job = None

    def _schedule_catchup(self):
        if self.playing or not self.cursor:
            return
        self._cancel_catchup()
        self._catchup_job = self.root.after(20, self._catchup_ops)

    def _catchup_ops(self):
        self._catchup_job = None
        if not self.cursor or self.playing:
            return
        target = self.cursor.seq
        n = 0
        while n < 8 and self.cursor._ready < target:
            self.cursor._consume(self.cursor._ready + 1)
            n += 1
        if self.cursor._ready < target:
            self._catchup_job = self.root.after(1, self._catchup_ops)
            return
        view = self.cursor.view(include_tracks=False, include_history=True, include_events=True)
        self._refresh_ops(view)

    def _gap_after(self, seq):
        return any((row.get('after_seq') or 0) == seq for row in (self.cursor.reader.index.get('gaps') or []))

    def _selected_unit_id(self):
        kind, row = self.map._selected_row() if self.map.selected else (None, None)
        if kind == '部队' and row:
            return row.get('unit_id')
        return None

    def _draw_tracks(self, w, h, layer):
        if not self._track:
            return
        for line in track_draw_polylines(self._track):
            points = [self.map._project(xy[0], xy[1], w, h, layer) for xy in line['points']]
            if line.get('marker_only') and points:
                x, y = points[0]
                self.map.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, outline='#f3d48a', tags='replay-track')
            elif len(points) >= 2:
                flat = [coord for point in points for coord in point]
                self.map.canvas.create_line(*flat, fill='#f3d48a', width=2, dash=(5, 3), tags='replay-track')

    def _ops_ledger(self, view):
        lords = ((view.get('state') or {}).get('entities') or {}).get('lords') or []
        return force_command_ledger(
            view.get('events') or [],
            lords,
            force_ids=self._force_ids(),
            opening_seq=getattr(self, '_opening_seq', 1),
            quarters_per_force=0,
        )

    def _refresh_ops(self, view):
        ledger = self._ops_ledger(view)
        key = (ledger_fingerprint(ledger), bool(view.get('gaps')))
        if key == self._ops_key:
            return
        self._ops_key = key
        self._ops_seq = view.get('seq')
        self.map.set_force_commands(ledger, self._goto_item)
        self._fill_ops(view, ledger)

    def _fill_ops(self, view, ledger=None):
        self.ops.delete('1.0', 'end')
        self.ops.insert('end', OPS_RAW_TITLE + '\n', 'head')
        self.ops.insert('end', OPS_RAW_NOTE + '\n', 'unknown')
        self.ops.insert('end', OPS_INFER_TITLE + '\n', 'head')
        ledger = list(ledger if ledger is not None else self._ops_ledger(view))
        if not ledger:
            self.ops.insert('end', '本帧还没有可对照的势力。\n' + OBS_EMPTY + '\n', 'unknown')
        for block in ledger:
            self.ops.insert('end', (block.get('heading') or block.get('name') or '势力') + '\n', 'force')
            quarters = block.get('quarters') or []
            if not quarters:
                self.ops.insert('end', '  ' + OBS_EMPTY + '\n', 'empty')
            for account in reversed(quarters):
                self.ops.insert('end', '  ' + short_quarter_label(account.get('label'), account.get('phase')) + '\n', 'quarter')
                self._fill_lane(account.get('civil') or [], '内政观察')
                self._fill_lane(account.get('military') or [], '军事观察')
            self.ops.insert('end', '\n')
        if view.get('gaps'):
            self.ops.insert('end', '数据缺口\n', 'head')
            for gap in view['gaps']:
                self.ops.insert('end', f"帧{gap.get('after_seq')} 后：{gap.get('reason')}\n", 'unknown')

    def _fill_lane(self, items, title, limit=24):
        if not items:
            self.ops.insert('end', f'    {title} —\n', 'empty')
            return
        shown = items[-limit:]
        skipped = len(items) - len(shown)
        if skipped:
            self.ops.insert('end', f'    {title} 另有更早 {skipped} 条\n', 'empty')
        else:
            self.ops.insert('end', f'    {title}\n', 'lane')
        for item in shown:
            ev = item.get('evidence') or 'inferred'
            evidence_label = item.get('evidence_cn') or {'fact':'事实','observed_change':'观察变化','inferred':'推断'}.get(ev,'未知')
            line = f"    [{evidence_label}] 帧{item.get('seq') or '?'} {command_line_text(item)}\n"
            bind_clickable(self.ops, line, ev, lambda it=item: self._goto_item(it))

    def _select_target(self, target, state):
        if not target:
            return
        if target.get('locatable') is False and target.get('world_xy_raw'):
            xy = target['world_xy_raw']
            self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
            self.map.detail.set('无法唯一定位对象，只移到最后已知坐标。')
            return
        if target.get('disappeared') and target.get('world_xy_raw'):
            xy = target['world_xy_raw']
            self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
            self.map.detail.set('对象已从本帧消失，定位最后已知位置；消失不等于覆灭。')
            return
        if not state:
            return
        if target.get('kind') == 'field_units' and target.get('unit_id') is not None:
            for kind, row in live_objects(state):
                if kind == '部队' and row.get('unit_id') == target.get('unit_id'):
                    self.map.selected = object_key(kind, row)
                    xy = world_xy(row)
                    self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
                    return
        if target.get('city_id') is not None:
            for kind, row in live_objects(state):
                if kind == '城关' and row.get('city_id') == target.get('city_id'):
                    self.map.selected = object_key(kind, row)
                    xy = world_xy(row)
                    self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
                    return

    def _goto_item(self, item):
        if not self.cursor:
            return
        if item.get('seq'):
            self._seek(item['seq'])
        self._select_target(item.get('target') or {}, self.cursor.frame_state(clone=False))
        self.render(heavy=False)
        self._schedule_catchup()

    def close(self):
        self.playing = False
        self._cancel_catchup()
        if self.cursor:
            self.cursor.close()
        self.root.destroy()


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='SGI panorama replay')
    parser.add_argument('--archive', help='archive directory with manifest.json')
    parser.add_argument('--demo', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    archive = args.archive
    if args.demo:
        path = demo_path()
        if not (path / 'manifest.json').is_file():
            write_demo_archive(path)
        archive = str(path)
    root = tk.Tk()
    apply_dock_icon(root, 'map')
    app = ReplayApp(root, archive)
    try:
        root.mainloop()
    finally:
        app.playing = False


if __name__ == '__main__':
    main()
