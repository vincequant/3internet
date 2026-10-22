"""Popup: panorama zoomed to one field unit, page through that force's army."""
import tkinter as tk

from force_unit_tour import (
    UNIT_TOUR_ZOOM, force_field_units, page_key_delta, step_index,
    tour_caption, tour_title, unit_page_index,
)
from native_city_map import CityLocator
import shadow_unit_edit

EDIT_BG = '#eee8d5'
EDIT_FG = '#4a3d1d'


class ForceUnitPager:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.geometry('720x520')
        self.win.minsize(520, 360)
        self.win.protocol('WM_DELETE_WINDOW', self.hide)
        self.state = None
        self.units = []
        self.index = 0
        bar = tk.Frame(self.win, bg='#eee8d5')
        bar.pack(fill='x')
        tk.Button(bar, text='上一支', command=lambda: self.step(-1), bg='#d4d0c0', padx=10).pack(side='left', padx=6, pady=6)
        tk.Button(bar, text='下一支', command=lambda: self.step(1), bg='#d4d0c0', padx=10).pack(side='left', padx=2, pady=6)
        self.caption = tk.StringVar(value='点对方部队后在此翻页')
        tk.Label(bar, textvariable=self.caption, bg='#eee8d5', fg='#4a3d1d', anchor='w',
                 font=('Microsoft YaHei', 10)).pack(side='left', fill='x', expand=True, padx=8)
        self._build_edit_bar(self.win)
        self.locator = CityLocator(self.win)
        self.locator.zoom = UNIT_TOUR_ZOOM
        self.locator.pack(fill='both', expand=True)
        hint = tk.Label(
            self.win, text='默认全国大地图。← 上一支　→ 下一支。WASD 仍可平移。',
            bg='#eee8d5', fg='#786c50', font=('Microsoft YaHei', 8), anchor='w',
        )
        hint.pack(fill='x', padx=8, pady=(0, 6))
        self._bind_page_keys(self.win, bar, self.locator, self.locator.canvas)
        self.win.bind('<Prior>', lambda _e=None: self.step(-1))
        self.win.bind('<Next>', lambda _e=None: self.step(1))
        self.win.bind('<Escape>', lambda _e=None: self.hide())

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def mapped(self):
        if not self.alive():
            return False
        try:
            return bool(self.win.winfo_ismapped())
        except tk.TclError:
            return False

    def hide(self):
        if self.alive():
            self.win.withdraw()

    def show(self, state, record):
        keep_zoom = self.mapped()
        self.state = state
        force_id = None if not record else record.get('owner_raw')
        self.units = force_field_units(state, force_id)
        self.index = unit_page_index(self.units, record)
        self._apply(recenter=True, keep_zoom=keep_zoom)
        if self.alive():
            self.win.deiconify()
            self.win.lift()
            self.win.after(40, lambda: self.win.focus_force())

    def _bind_page_keys(self, *widgets):
        def on_key(event):
            delta = page_key_delta(getattr(event, 'keysym', ''))
            if not delta:
                return
            self.step(delta)
            return 'break'
        for widget in widgets:
            widget.bind('<Left>', on_key)
            widget.bind('<Right>', on_key)

    def step(self, delta):
        if not self.units:
            return
        self.index = step_index(len(self.units), self.index, delta)
        self._apply(recenter=True, keep_zoom=True)

    def update_state(self, state):
        current = self.units[self.index] if self.units and 0 <= self.index < len(self.units) else None
        self.state = state
        force_id = None if not current else current.get('owner_raw')
        self.units = force_field_units(state, force_id)
        self.index = unit_page_index(self.units, current)
        self._apply(recenter=False, keep_zoom=True)

    def _apply(self, recenter=True, keep_zoom=False):
        if not self.alive():
            return
        self.win.title(tour_title(self.state, self.units, self.index))
        self.caption.set(tour_caption(self.state, self.units, self.index))
        self._sync_edit()
        if self.state is not None:
            self.locator.update_state(self.state)
        if not self.units:
            self.locator.clear_target('该势力本帧无出征部队')
            return
        self.locator.focus_entity(
            'field_units', self.units[self.index],
            recenter=recenter, keep_zoom=keep_zoom, default_zoom=UNIT_TOUR_ZOOM,
        )


    # ---------- value editing (风夜影子客户端，仅本机） ----------
    def _editable(self):
        try:
            from connection import CONNECTION
            selected = CONNECTION.cfg.get('selected_source')
        except Exception:
            selected = ''
        return shadow_unit_edit.source_is_shadow(selected) and shadow_unit_edit.available()

    def _build_edit_bar(self, parent):
        self.edit_status = tk.StringVar(value='')
        self.edit_vars = {}
        self._recent = {}          # field -> (value, wall) 写入后 10 秒内不让旧快照盖回去
        self.lock_status = tk.StringVar(value='士气未锁定')
        frame = tk.Frame(parent, bg=EDIT_BG)
        frame.pack(fill='x', padx=8, pady=(0, 4))
        self.edit_frame = frame
        row = tk.Frame(frame, bg=EDIT_BG)
        row.pack(fill='x')
        for key, label, limit in shadow_unit_edit.UNIT_FIELDS:
            cell = tk.Frame(row, bg=EDIT_BG)
            cell.pack(side='left', padx=(0, 10))
            tk.Label(cell, text='%s≤%s' % (label, limit), bg=EDIT_BG, fg=EDIT_FG,
                     font=('Microsoft YaHei', 8)).pack(anchor='w')
            var = tk.StringVar()
            tk.Entry(cell, textvariable=var, width=9,
                     font=('Microsoft YaHei', 10)).pack(side='left')
            tk.Button(cell, text='写入', padx=6,
                      command=lambda k=key: self._write_field(k)).pack(side='left', padx=(3, 0))
            self.edit_vars[key] = var
        tk.Button(row, text='还原上一笔', padx=8, command=self._revert).pack(side='left', padx=(8, 0))

        lock = tk.Frame(frame, bg=EDIT_BG)
        lock.pack(fill='x', pady=(3, 0))
        tk.Label(lock, text='士气锁定（维持不跌）', bg=EDIT_BG, fg=EDIT_FG,
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=(0, 6))
        self.lock_var = tk.StringVar(value='')
        tk.Entry(lock, textvariable=self.lock_var, width=6,
                 font=('Microsoft YaHei', 10)).pack(side='left')
        tk.Button(lock, text='锁定', padx=8, command=self._lock_morale).pack(side='left', padx=(4, 2))
        tk.Button(lock, text='解锁', padx=8, command=self._unlock_morale).pack(side='left', padx=(0, 8))
        tk.Label(lock, textvariable=self.lock_status, bg=EDIT_BG, fg='#786c50',
                 font=('Microsoft YaHei', 8)).pack(side='left')
        tk.Label(frame, textvariable=self.edit_status, bg=EDIT_BG, fg='#786c50',
                 font=('Microsoft YaHei', 8), anchor='w').pack(fill='x')

    def _current(self):
        if not self.units or not (0 <= self.index < len(self.units)):
            return None
        return self.units[self.index]

    def _unit_values(self, row):
        return {
            'soldiers': row.get('soldiers_candidate'),
            'rice': row.get('rice_candidate', row.get('rice')),
            'morale': row.get('morale'),
            'training': row.get('training', row.get('armament_degree_raw')),
        }

    def _sync_edit(self):
        import time as _time
        row = self._current()
        values = self._unit_values(row or {})
        now = _time.time()
        for key, var in self.edit_vars.items():
            recent = self._recent.get(key)
            if recent and now - recent[1] < 10:
                # 刚写过：先用我们写入并回读确认的值，等游戏快照追上再交还
                var.set(str(recent[0]))
                continue
            value = values.get(key)
            var.set('' if value is None else str(value))
        if self.lock_var.get() == '' and values.get('morale') is not None:
            self.lock_var.set(str(values['morale']))
        if not self._editable():
            self.edit_status.set('改值仅对「风夜（影子）」数据源生效，当前数据源不是它')
        elif row is None:
            self.edit_status.set('本帧没有可改的部队')
        else:
            self.edit_status.set('改值只写风夜这台本机；写完回读确认')
        self._sync_lock_status()

    def _sync_lock_status(self):
        row = self._current()
        status = shadow_unit_edit.morale_lock_status()
        if status.get('running'):
            mine = (row and status.get('owner') == row.get('owner_raw')
                    and status.get('unit_id') == row.get('unit_id'))
            self.lock_status.set(('本支部队锁定在 %s' % status.get('value')) if mine
                                 else ('锁定了别支部队（owner %s / #%s = %s）'
                                       % (status.get('owner'), status.get('unit_id'), status.get('value'))))
        else:
            self.lock_status.set('士气未锁定')

    def _write_field(self, field):
        import time as _time
        row = self._current()
        if not self._editable() or row is None:
            self.edit_status.set('当前不可改值')
            return
        var = self.edit_vars.get(field)
        try:
            value = int(str(var.get()).strip())
        except Exception:
            self.edit_status.set('请输入整数')
            return
        result = shadow_unit_edit.write_unit_field(
            row.get('owner_raw'), row.get('unit_id'), field, value)
        if result.get('ok'):
            edit = result.get('edit') or {}
            after = edit.get('after')
            var.set(str(after))
            self._recent[field] = (after, _time.time())
            self.edit_status.set('已写入 %s：%s → %s（仅本机；游戏内数值可能稍后才刷新）' % (
                edit.get('label', field), edit.get('before'), after))
        else:
            self.edit_status.set('写入失败：%s' % (result.get('error') or '未知'))

    def _lock_morale(self):
        row = self._current()
        if not self._editable() or row is None:
            self.edit_status.set('当前不可锁定')
            return
        try:
            value = int(str(self.lock_var.get()).strip())
        except Exception:
            self.edit_status.set('锁定值要填整数（0–100）')
            return
        result = shadow_unit_edit.morale_lock_start(
            row.get('owner_raw'), row.get('unit_id'), value)
        if result.get('ok'):
            self.lock_status.set('已锁定士气 %s（每 0.8 秒回写）' % result.get('value'))
            self.edit_status.set('士气锁定已启动')
        else:
            self.edit_status.set('锁定失败：%s' % (result.get('error') or '未知'))

    def _unlock_morale(self):
        result = shadow_unit_edit.morale_lock_stop()
        self.lock_status.set('士气未锁定')
        self.edit_status.set('已解除士气锁定' if result.get('ok') else
                             '解除失败：%s' % (result.get('error') or '未知'))

    def _revert(self):
        if not self._editable():
            return
        result = shadow_unit_edit.revert_last()
        if result.get('ok'):
            edit = result.get('edit') or {}
            self.edit_status.set('已还原：%s → %s' % (edit.get('field'), edit.get('after')))
            self._recent.clear()
            self._sync_edit()
        else:
            self.edit_status.set('还原失败：%s' % (result.get('error') or '未知'))


def show_force_unit_pager(parent, state, record, holder=None):
    pager = None if holder is None else getattr(holder, 'unit_pager', None)
    if pager is None or not pager.alive():
        pager = ForceUnitPager(parent)
        if holder is not None:
            holder.unit_pager = pager
    pager.show(state, record)
    return pager
