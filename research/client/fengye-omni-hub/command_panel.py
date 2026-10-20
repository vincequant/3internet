"""Immediate command buttons, live read-only values and a durable job timeline."""
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from build_picker import EmbeddedConstructionMap
from command_presentation import (BUILD_CHOICES, TRAIN_CHOICES, STATUS, action_text,
                                  actor_text, progress_text, job_detail)
from fengye_diagnostics import report

BG, INK, MUTED, ACCENT = '#f3f6fa', '#203440', '#657985', '#286a72'
OTHER = {'cancelled', 'error', 'send_failed'}


def shown(value):
    return '未知' if value is None else str(value)


class CommandPanel(tk.Frame):
    refresh_seconds = 3.0

    def __init__(self, parent, service, on_snapshot=None, readonly=False, autostart=True, on_error=None):
        super().__init__(parent, bg=BG)
        self.service, self.on_snapshot, self.readonly = service, on_snapshot, readonly
        self.on_read_error = on_error
        self.snapshot = {}
        self.forces = []
        self.city_id = None
        self.build_type = None
        self.picker = None
        self._closed = False
        self._busy = False
        self._next_read = 0
        self._results = queue.Queue()
        self._last_rows = {}
        self._jobs = {}
        self._auto = autostart and not readonly
        self._after = None
        self._build()
        self.bind('<Destroy>', self._destroyed, add='+')
        self._tick()

    def _label(self, parent, text, bold=False):
        return tk.Label(parent, text=text, bg=BG, fg=ACCENT if bold else INK,
                        font=('', 12, 'bold') if bold else ('', 11), anchor='w')

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill='x', padx=16, pady=(8, 0))
        self._label(top, '勢力').pack(side='left')
        self.force_box = ttk.Combobox(top, width=28, state='readonly')
        self.force_box.pack(side='left', padx=8)
        self.force_box.bind('<<ComboboxSelected>>', self._force_changed)
        self.refresh_button = ttk.Button(top, text='立即讀取', command=self.refresh)
        self.live = self._label(top, '正在讀取風夜資料…')
        self.live.pack(side='left', padx=12)
        rows = tk.Frame(self, bg=BG)
        rows.pack(fill='x', padx=16, pady=(10, 4))
        self._label(rows, '練兵', True).pack(side='left', padx=(0, 10))
        self.train_buttons = {}
        for troop, text in TRAIN_CHOICES:
            button = ttk.Button(rows, text=text, width=11, command=lambda t=troop: self.train(t))
            button.pack(side='left', padx=4)
            self.train_buttons[troop] = button
        self.values = self._label(rows, '訓練度：—　金：—')
        self.values.pack(side='left', padx=14)
        build = tk.Frame(self, bg=BG)
        build.pack(fill='x', padx=16, pady=4)
        self._label(build, '建設', True).pack(side='left', padx=(0, 10))
        self.build_buttons = {}
        for kind, text in BUILD_CHOICES:
            button = ttk.Button(build, text=text, width=11, command=lambda k=kind: self.build(k))
            button.pack(side='left', padx=4)
            self.build_buttons[kind] = button
        self._label(build, '選種類 → 地圖點淡藍高亮 → 確認入隊').pack(side='left', padx=14)
        self.map_view = EmbeddedConstructionMap(self, self._confirm_build)
        self.map_view.pack(fill='both', expand=True, padx=16, pady=(4, 6))
        self.note = self._label(self, '完成後顯示實際訓練值或新增建物；尚未確認生效的指令會保留進度。')
        self.note.configure(fg=ACCENT, wraplength=1080, justify='left')
        self.note.pack(fill='x', padx=16, pady=(0, 8))
        tools = tk.Frame(self, bg=BG)
        self._queue_tools = tools
        self._queue_visible = True
        tools.pack(fill='x', padx=16, pady=4)
        self.count = self._label(tools, '指令隊列', True)
        self.count.pack(side='left')
        self.queue_toggle = ttk.Button(tools, text='收合隊列，放大地圖', command=self._toggle_queue)
        self.queue_toggle.pack(side='left', padx=12)
        self.cancel_button = ttk.Button(tools, text='撤回選中的未處理指令', command=self.cancel_selected)
        self.cancel_button.pack(side='right')
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='x', padx=16, pady=4)
        self.tabs.bind('<<NotebookTabChanged>>', lambda _e: self._show_detail())
        self.tables = {}
        self.pages = {}
        for key, title in (('active', '處理中'), ('completed', '已完成'), ('other', '已撤回／未完成')):
            page = ttk.Frame(self.tabs)
            self.tabs.add(page, text=title)
            tree = ttk.Treeview(page, columns=('time', 'actor', 'action', 'status', 'note'),
                                show='headings', height=3, selectmode='browse')
            for col, label, width in (('time', '加入時間', 85), ('actor', '玩家・勢力', 145),
                                      ('action', '指令／位置', 200), ('status', '處理狀態', 150),
                                      ('note', '進度／實際變化', 420)):
                tree.heading(col, text=label)
                tree.column(col, width=width, minwidth=60, stretch=True)
            scroll = ttk.Scrollbar(page, command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            tree.pack(fill='both', expand=True)
            tree.bind('<<TreeviewSelect>>', lambda _e: self._show_detail())
            tree.bind('<Delete>', lambda _e: self.cancel_selected())
            self.tables[key], self.pages[key] = tree, page
        self.details = tk.Text(self, height=2, wrap='word', bg='white', fg=INK,
                               state='disabled', relief='flat', padx=10, pady=6)
        self.details.pack(fill='x', padx=16, pady=(4, 12))
        # Reserve the timeline before giving the remaining space to the map.
        # Tk pack otherwise clips later siblings on a 1280x928 laptop window.
        for widget in (self.map_view, self.note, tools, self.tabs, self.details):
            widget.pack_forget()
        self.details.pack(side='bottom', fill='x', padx=16, pady=(4, 8))
        self.tabs.pack(side='bottom', fill='x', padx=16, pady=4)
        tools.pack(side='bottom', fill='x', padx=16, pady=4)
        self.note.pack(side='bottom', fill='x', padx=16, pady=(2, 4))
        self.map_view.pack(fill='both', expand=True, padx=16, pady=(4, 6))
        if self.readonly:
            for b in list(self.train_buttons.values()) + list(self.build_buttons.values()):
                b.configure(state='disabled')
            self.cancel_button.configure(state='disabled')

    def selected_force(self):
        index = self.force_box.current()
        return self.forces[index] if 0 <= index < len(self.forces) else None

    def _force_changed(self, _event=None):
        self.city_id = None
        self._render_map()
        self._render_values()

    def _render_values(self):
        force = self.selected_force() or {}
        arm = force.get('armament_raw') or force.get('armament') or {}
        # Display provided fields only; no guessed training values.
        values = '／'.join(shown(arm.get(k)) for k in ('infantry', 'cavalry', 'bow'))
        self.values.configure(text='訓練度 步／騎／弓：%s　金：%s' % (values, shown(force.get('gold'))))

    def _owned_cities(self):
        force = self.selected_force() or {}
        return [c for c in self.snapshot.get('cities', []) if c.get('owner') == force.get('force_id')]

    def _render_map(self):
        force = self.selected_force() or {}
        self.map_view.set_context(
            dict(BUILD_CHOICES).get(self.build_type) if self.build_type is not None and not self.readonly else None,
            force.get('force_id'), self._owned_cities(),
            self.snapshot.get('_battle_payload') or {},
            busy=self.snapshot.get('_busy_cells') or [])

    def train(self, troop):
        self._enqueue({'preset': 'train', 'troop': troop, 'value': 75, 'extra': 0})

    def build(self, kind):
        if self.readonly:
            return
        self.build_type = kind
        self._set_queue_visible(False)
        self._render_map()
        self.note.configure(text='建設%s：在大地圖點選淡藍高亮位置，再按「確認位置並加入隊列」。' %
                            dict(BUILD_CHOICES)[kind])

    def _toggle_queue(self):
        self._set_queue_visible(not self._queue_visible)

    def _set_queue_visible(self, visible):
        self._queue_visible = bool(visible)
        if visible:
            self.details.pack(side='bottom', fill='x', padx=16, pady=(4, 8), before=self._queue_tools)
            self.tabs.pack(side='bottom', fill='x', padx=16, pady=4, before=self._queue_tools)
        else:
            self.details.pack_forget()
            self.tabs.pack_forget()
        self.queue_toggle.configure(text='收合隊列，放大地圖' if visible else '展開指令隊列')

    def _confirm_build(self, city, x, y):
        if self.readonly or self.build_type is None:
            return
        force = self.selected_force() or {}
        if city.get('owner', city.get('owner_raw')) != force.get('force_id'):
            self.note.configure(text='城池已不屬於所選勢力，請重新選址。')
            return
        return self._enqueue({'preset': 'build', 'build_type': self.build_type,
                       'city': city['city_id'], 'city_name': city.get('name') or '未知城池',
                       'x': x, 'y': y, 'extra': 2000})

    def _enqueue(self, params):
        force = self.selected_force()
        if self.readonly:
            return
        if force is None:
            self.note.configure(text='請等候讀到勢力資料。')
            return
        payload = dict(params, prefix='prefix-fengye-shadow', actor=force['force_id'],
                       actor_label=self.force_box.get(), auto_slot=True)
        result = self.service.submit(payload, info=self.snapshot, execute=True)
        if result.get('ok'):
            self._set_queue_visible(True)
        self.render_jobs()
        if not result.get('ok'):
            self.note.configure(text='沒有加入：%s' % result.get('error', '未知原因'))
            return False
        job = result.get('job') or {}
        self.note.configure(text='已加入：%s。下方可即時查看進度；尚未發送時可撤回。' % action_text(job, self.snapshot))
        self.tabs.select(self.pages['active'])
        tree = self.tables['active']
        if tree.exists(job.get('id', '')):
            tree.selection_set(job['id'])
            tree.see(job['id'])
            self._show_detail()
        return True

    def cancel_selected(self):
        if self.readonly:
            return
        tree = self._selected_tree()
        selection = tree.selection()
        if not selection:
            self.note.configure(text='請先選中要撤回的指令。')
            return
        result = self.service.cancel(selection[0])
        self.note.configure(text='已撤回，沒有送出。' if result.get('ok') else
                            '無法撤回：%s' % result.get('error', '已開始發送'))
        self.render_jobs()

    def _selected_tree(self):
        current = self.tabs.select()
        return next((self.tables[k] for k, p in self.pages.items() if str(p) == str(current)),
                    self.tables['active'])

    def _show_detail(self):
        tree = self._selected_tree()
        selection = tree.selection()
        selected = self._jobs.get(selection[0]) if selection else None
        can_cancel = bool(selected and selected.get('status') in (
            'held', 'pending', 'validating', 'waiting_phase_exit', 'waiting_effect'))
        self.cancel_button.configure(state='normal' if can_cancel and not self.readonly else 'disabled')
        text = job_detail(self._jobs[selection[0]], self.snapshot) if selection and selection[0] in self._jobs else '選中一筆指令可查看完整處理過程。'
        if self.details.get('1.0', 'end-1c') != text:
            pos = self.details.yview()
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('1.0', text)
            self.details.configure(state='disabled')
            self.details.yview_moveto(pos[0])

    def render_jobs(self):
        previous_tree = self._selected_tree()
        previous_selection = previous_tree.selection()
        tracked = previous_selection[0] if previous_selection else None
        view = self.service.jobs_view()
        game_key = view.get('current_game_key')
        jobs = [j for j in (view.get('current_jobs', view.get('jobs')) or [])
                if game_key and j.get('game_key') == game_key and not j.get('legacy')
                and not str(j.get('status', '')).startswith('legacy_')]
        self._jobs = {j['id']: j for j in jobs}
        wanted = {key: [] for key in self.tables}
        for job in jobs:
            status = job.get('status')
            key = 'completed' if status == 'completed' else ('other' if status in OTHER else 'active')
            wanted[key].append(job['id'])
            try:
                added_at = datetime.fromtimestamp(job['created']).strftime('%H:%M:%S')
            except (ValueError, TypeError, KeyError, OSError, OverflowError):
                added_at = '時間未知'
            vals = (added_at,
                    actor_text(job, self.snapshot), action_text(job, self.snapshot),
                    STATUS.get(status, '狀態待確認'), progress_text(job, self.snapshot))
            tree = self.tables[key]
            if tree.exists(job['id']):
                if tree.item(job['id'], 'values') != tuple(str(v) for v in vals):
                    tree.item(job['id'], values=vals)
            else:
                tree.insert('', 'end', iid=job['id'], values=vals)
        for key, tree in self.tables.items():
            remove = [i for i in tree.get_children() if i not in wanted[key]]
            if remove:
                tree.delete(*remove)
            self.tabs.tab(self.pages[key], text={'active': '處理中', 'completed': '已完成',
                                                'other': '已撤回／未完成'}[key] + ' (%d)' % len(wanted[key]))
        if tracked in self._jobs:
            destination = next((key for key, rows in wanted.items() if tracked in rows), None)
            if destination and self.tables[destination] is not previous_tree:
                self.tabs.select(self.pages[destination])
                self.tables[destination].selection_set(tracked)
                self.tables[destination].see(tracked)
        self.count.configure(text='指令隊列　處理中 %d　已確認完成 %d' %
                                  (len(wanted['active']), len(wanted['completed'])))
        warning = view.get('history_error')
        if warning and warning != getattr(self, '_history_warning', None):
            self.note.configure(text='部分本機記錄未能讀取或保存；請留意各筆指令的實際處理結果。')
        self._history_warning = warning
        self._show_detail()

    def refresh(self):
        if self._closed or self._busy or self.readonly:
            return False
        self._busy = True
        self.refresh_button.configure(state='disabled')
        def work():
            try:
                data = dict(self.service.targets(refresh=True))
                if data.get('ok'):
                    battle = self.service.battlefield()
                    if battle.get('game_key') == data.get('game_key'):
                        data['_battle_payload'] = battle
                        data['_busy_cells'] = list(self.service.busy_build_cells())
            except Exception as exc:
                report('command-read', exc)
                data = {'ok': False, 'error': str(exc)}
            self._results.put(data)
        threading.Thread(target=work, name='command-live-read', daemon=True).start()
        return True

    def _apply_snapshot(self, data):
        force = self.selected_force()
        fid = force.get('force_id') if force else None
        self.snapshot = data
        self.forces = list(data.get('forces') or [])
        players = {s.get('force_id'): s.get('nickname') for s in data.get('player_slots', [])}
        values = ['%s・%s' % (players.get(f['force_id']) or '未知玩家', f.get('name') or '未知勢力')
                  for f in self.forces]
        self.force_box.configure(values=values)
        index = next((i for i, f in enumerate(self.forces) if f.get('force_id') == fid), 0)
        if values:
            self.force_box.current(index)
        self._render_map()
        self._render_values()
        self.live.configure(text='自動讀取 · %s · %s' %
                                  (data.get('phase_text') or '未知', datetime.now().strftime('%H:%M:%S')))
        if self.on_snapshot:
            self.on_snapshot(data)

    def _tick(self):
        if self._closed:
            return
        try:
            while not self._results.empty():
                data = self._results.get_nowait()
                self._busy = False
                self._next_read = time.monotonic() + self.refresh_seconds
                self.refresh_button.configure(state='normal')
                if data.get('ok'):
                    self._apply_snapshot(data)
                else:
                    self.live.configure(text='等待開局資料；正在自動讀取。')
                    self.map_view.set_context(None, None, [], {})
                    if self.on_read_error:
                        self.on_read_error()
            self.render_jobs()
        except Exception as exc:
            report('command-display', exc)
            self.live.configure(text='資料更新暫時中斷，正在自動重試。')
            if self.on_read_error:
                self.on_read_error()
        finally:
            if not self._closed:
                try:
                    if self._auto and not self._busy and time.monotonic() >= self._next_read:
                        self.refresh()
                except Exception as exc:
                    report('command-refresh-schedule', exc)
                finally:
                    self._after = self.after(250, self._tick)

    def _destroyed(self, event):
        if event.widget is not self:
            return
        self._closed = True
        if self._after:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
        if self.picker and self.picker.winfo_exists():
            self.picker.destroy()
