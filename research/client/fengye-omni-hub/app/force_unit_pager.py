"""Popup: panorama zoomed to one field unit, page through that force's army."""
import tkinter as tk

from force_unit_tour import (
    UNIT_TOUR_ZOOM, force_field_units, page_key_delta, step_index,
    tour_caption, tour_title, unit_page_index,
)
from native_city_map import CityLocator


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
        if self.state is not None:
            self.locator.update_state(self.state)
        if not self.units:
            self.locator.clear_target('该势力本帧无出征部队')
            return
        self.locator.focus_entity(
            'field_units', self.units[self.index],
            recenter=recenter, keep_zoom=keep_zoom, default_zoom=UNIT_TOUR_ZOOM,
        )


def show_force_unit_pager(parent, state, record, holder=None):
    pager = None if holder is None else getattr(holder, 'unit_pager', None)
    if pager is None or not pager.alive():
        pager = ForceUnitPager(parent)
        if holder is not None:
            holder.unit_pager = pager
    pager.show(state, record)
    return pager
