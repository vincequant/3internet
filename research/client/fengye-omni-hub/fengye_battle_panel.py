"""Live shadow-only battlefield, sharing the original panorama and artwork.

No player bridge/API connection is started here. Background work never touches
Tk widgets. Collector data and pure display derivations are kept separate.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
for _folder in (ROOT / 'app', ROOT / 'bridge'):
    if str(_folder) not in sys.path:
        sys.path.append(str(_folder))

from panorama_map import PanoramaMap
from unit_combat import enrich_unit_combat
from unit_memory import attack_label

SHADOW_PREFIX = 'prefix-fengye-shadow'


def shown(value):
    return '—' if value is None else str(value)


def capture_time(payload):
    value = payload.get('captured_at') or (payload.get('state') or {}).get('capture_end')
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when
    except ValueError:
        return None


def prepare_payload(payload):
    """Validate provenance before deriving a display of this exact snapshot."""
    if not isinstance(payload, dict):
        raise ValueError('讀取未完成')
    if not payload.get('ok'):
        raise ValueError(str(payload.get('error') or '讀取未完成'))
    if payload.get('source_prefix') != SHADOW_PREFIX:
        raise ValueError('未取得風夜資料來源')
    raw = payload.get('state')
    if not isinstance(raw, dict) or not isinstance(raw.get('entities'), dict):
        raise ValueError('風夜完整地圖資料尚未就緒')
    if raw.get('readonly') is not True:
        raise ValueError('風夜資料未標示唯讀來源')
    display = copy.deepcopy(raw)
    enrich_unit_combat(display)
    return display


def lock_viewport(canvas):
    """The original map camera owns movement; Tk's scroll origin stays fixed."""
    inset = sum(canvas.winfo_pixels(canvas.cget(key))
                for key in ('borderwidth', 'highlightthickness'))
    canvas.configure(scrollregion=(inset, inset,
                                   max(inset, canvas.winfo_width() - inset),
                                   max(inset, canvas.winfo_height() - inset)), confine=True)
    canvas.xview_moveto(0)
    canvas.yview_moveto(0)


class ShadowPanorama(PanoramaMap):
    """Original renderer, with source ownership and lifecycle hooks changed."""
    def _build(self):
        super()._build()
        # The original renderer and its data layers stay intact. This viewer
        # needs a compact toolbar, without opponent/production filters.
        bar = self.winfo_children()[0]
        for widget in bar.winfo_children():
            if isinstance(widget, tk.Checkbutton):
                if widget.cget('text') != '文字':
                    widget.pack_forget()
            elif isinstance(widget, tk.Button):
                widget.configure(fg='#203440', bg='#e7e0c9', activeforeground='#203440',
                                 activebackground='#d4c89a', disabledforeground='#657985')
        if self._side_btn is not None:
            self._side_btn.pack_forget()
        self.layers['陷阱'].set(True)
        # navigation_bar creates the five movement/reset buttons first.
        holder = self.canvas.master
        map_area = holder.master
        nav = next((w for w in map_area.winfo_children() if w is not holder), None)
        if nav is not None:
            for widget in nav.winfo_children()[5:]:
                widget.pack_forget()

    def __init__(self, parent, detached_callback=None, **kwargs):
        self._detached_callback = detached_callback
        super().__init__(parent, **kwargs)
        self.canvas.configure(takefocus=True)
        self.canvas.bind('<Configure>', self._configure_viewport, add='+')
        self.canvas.bind('<Map>', self._configure_viewport, add='+')
        self.canvas.bind('<Enter>', lambda _e: self.canvas.focus_set(), add='+')
        self.fit()

    def _configure_viewport(self, _event=None):
        lock_viewport(self.canvas)

    def open_detached(self):
        if self._detached_callback:
            return self._detached_callback(self)

    def draw(self, refresh_view=True):
        # Traps are always visible in this viewer; only text is user-toggleable.
        self.layers['陷阱'].set(True)
        lock_viewport(self.canvas)
        return super().draw(refresh_view=refresh_view)


class BattlePanel(tk.Frame):
    def __init__(self, parent, service, root=None, poll_ms=3000, autostart=True):
        super().__init__(parent, bg='#f1f3f7')
        self.root = root or self.winfo_toplevel()
        self.service = service
        self.poll_ms = max(250, int(poll_ms))
        self.inbox = queue.Queue()
        self.raw_state = None
        self.display_state = None
        self.last_payload = None
        self.last_error = None
        self.last_capture_at = None
        self._running = False
        self._disposed = False
        self._inflight = False
        self._next = None
        self._pump_id = None
        self._detached = []
        self.on_state = None
        self.status_var = tk.StringVar(value='準備讀取風夜戰場…')
        bar = tk.Frame(self, bg='#edf1ef')
        bar.pack(fill='x')
        self.refresh_button = ttk.Button(bar, text='立即讀取', command=self.refresh)
        self.refresh_button.pack(side='left', padx=8, pady=5)
        ttk.Label(bar, textvariable=self.status_var).pack(side='left', padx=8)
        self.panorama = ShadowPanorama(self, title='風夜全景地圖', detachable=True,
                                      detached_callback=self._open_detached)
        self.panorama.pack(fill='both', expand=True)
        self.map = self.panorama
        bottom = tk.PanedWindow(self, orient='horizontal', bg='#d2d5cd', sashwidth=6)
        bottom.pack(fill='x', padx=6, pady=(4, 6))
        self.forces = self._table(bottom, '勢力基礎情報', (
            ('force', '勢力', 110), ('gold', '金', 85), ('rice', '米', 90),
            ('cities', '城', 45), ('units', '部隊', 50)))
        self.units = self._table(bottom, '部隊（點選定位）', (
            ('owner', '勢力', 75), ('kind', '兵種', 100), ('xy', '座標', 80),
            ('soldiers', '兵力', 75), ('attack', '攻擊指數', 90), ('morale', '士氣', 50)))
        self.units.bind('<<TreeviewSelect>>', self._pick_unit)
        self._unit_rows = {}
        self.bind('<Destroy>', self._destroy_event, add='+')
        self._pump_id = self.after(60, self._pump)
        if autostart:
            self.start()

    @staticmethod
    def _table(parent, label, columns):
        box = ttk.LabelFrame(parent, text=label)
        parent.add(box, minsize=300, stretch='always')
        tree = ttk.Treeview(box, columns=[col[0] for col in columns], show='headings', height=4)
        for key, text, width in columns:
            tree.heading(key, text=text)
            tree.column(key, width=width, minwidth=35, anchor='w')
        tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def start(self):
        if self._disposed:
            return False
        self._running = True
        return self.refresh()

    def stop(self):
        self._running = False
        if self._next is not None:
            self.after_cancel(self._next)
            self._next = None

    def refresh(self):
        if self._disposed or self._inflight:
            return False
        if self._next is not None:
            self.after_cancel(self._next)
            self._next = None
        self._inflight = True
        self.refresh_button.configure(state='disabled')
        self._status(reading=True)

        def work():
            try:
                payload = self.service.battlefield()
                display = prepare_payload(payload)
                item = (payload, display, None)
            except Exception as exc:
                item = (None, None, '%s: %s' % (type(exc).__name__, exc))
            self.inbox.put(item)

        threading.Thread(target=work, daemon=True, name='fengye-battle-reader').start()
        return True

    def _pump(self):
        self._pump_id = None
        if self._disposed:
            return
        try:
            payload, display, error = self.inbox.get_nowait()
        except queue.Empty:
            pass
        else:
            self._inflight = False
            self.refresh_button.configure(state='normal')
            self.last_error = error
            if error is None:
                self.last_payload = payload
                self.raw_state = payload['state']
                self.display_state = display
                self.last_capture_at = capture_time(payload)
                try:
                    self.panorama.update_state(display)
                    self._fill_tables(display)
                    for win, page in tuple(self._detached):
                        if win.winfo_exists():
                            page.update_state(display)
                    if self.on_state:
                        self.on_state(payload)
                except Exception as exc:
                    self.last_error = '地圖顯示失敗：%s' % exc
            if self._running:
                self._next = self.after(self.poll_ms, self.refresh)
        self._status(reading=self._inflight)
        self._pump_id = self.after(100, self._pump)

    def _status(self, reading=False):
        when = self.last_capture_at
        if when is None:
            if self.raw_state is not None:
                text = '已讀取 · 觀測時間未知'
            else:
                text = '讀取中…' if reading else '尚無可用戰場資料'
        else:
            age = max(0, (datetime.now(timezone.utc) - when).total_seconds())
            stale = bool(self.last_error) or age > max(15, self.poll_ms / 1000 * 3)
            entities = (self.raw_state or {}).get('entities') or {}
            counts = '勢力 %d · 城關 %d · 部隊 %d' % tuple(len(entities.get(key) or [])
                for key in ('lords', 'cities_and_barriers', 'field_units'))
            text = '%s · %s · %s' % (
                '資料已過期' if stale else ('讀取中' if reading else '持續讀取'),
                when.astimezone().strftime('%H:%M:%S'), counts)
        if self.last_error:
            text += ' · ' + self.last_error
        self.status_var.set(text)
        self.panorama.status.set(text)
        for win, page in tuple(self._detached):
            if win.winfo_exists():
                page.status.set(text)

    def _fill_tables(self, state):
        entities = state.get('entities') or {}
        lords = entities.get('lords') or []
        cities = entities.get('cities_and_barriers') or []
        units = entities.get('field_units') or []
        names = {row.get('force_id'): row.get('name') for row in lords}
        force_rows = []
        for index, lord in enumerate(lords):
            fid = lord.get('force_id')
            key = 'force-%s-%s' % (fid, index)
            force_rows.append((key, (shown(lord.get('name')),
                shown(lord.get('gold')), shown(lord.get('rice')),
                sum(row.get('owner_raw') == fid for row in cities),
                sum(row.get('owner_raw') == fid for row in units))))
        self._replace_rows(self.forces, force_rows)
        self._unit_rows = {}
        unit_rows = []
        for index, row in enumerate(units):
            key = 'unit-%s' % row.get('unit_id', index)
            if key in self._unit_rows:
                key += '-%s' % index
            self._unit_rows[key] = row
            xy = row.get('world_xy_raw')
            coords = ','.join(map(str, xy)) if isinstance(xy, (list, tuple)) else '—'
            unit_rows.append((key, (shown(names.get(row.get('owner_raw'))),
                shown(row.get('unit_kind')), coords, shown(row.get('soldiers_candidate')),
                attack_label(row).replace('未知', '—'), shown(row.get('morale')))))
        self._replace_rows(self.units, unit_rows)

    @staticmethod
    def _replace_rows(tree, rows):
        """Update stable rows in place so continuous reads do not jump the table."""
        wanted = {key for key, _values in rows}
        for key in tree.get_children():
            if key not in wanted:
                tree.delete(key)
        for index, (key, values) in enumerate(rows):
            if tree.exists(key):
                tree.item(key, values=values)
                tree.move(key, '', index)
            else:
                tree.insert('', index, iid=key, values=values)

    def _pick_unit(self, _event=None):
        selection = self.units.selection()
        row = self._unit_rows.get(selection[0]) if selection else None
        xy = (row or {}).get('world_xy_raw')
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            return
        from panorama_model import object_key
        self.panorama.center = tuple(xy)
        self.panorama.zoom = max(3.0, self.panorama.zoom)
        self.panorama.selected = object_key('部队', row)
        self.panorama.detail.set(self.panorama._describe('部队', row))
        self.panorama.request_draw()

    def _open_detached(self, original=None):
        original = original or self.panorama
        win = tk.Toplevel(self.root)
        win.title('風夜全景地圖 · 同步戰場')
        win.geometry('1280x820')
        page = ShadowPanorama(win, title='風夜全景地圖', detachable=False)
        page.pack(fill='both', expand=True)
        page.center, page.zoom = original.center, original.zoom
        for name, var in original.layers.items():
            page.layers[name].set(var.get())
        page.war_only.set(original.war_only.get())
        if self.display_state:
            page.update_state(self.display_state)
        self._detached.append((win, page))
        def close():
            self._detached[:] = [(w, p) for w, p in self._detached if w is not win]
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', close)
        self._status(reading=self._inflight)
        return win

    def redraw(self):
        self.panorama.request_draw()

    def fit(self):
        self.panorama.fit()

    def _destroy_event(self, event):
        if event.widget is self:
            self.dispose()

    def dispose(self):
        if self._disposed:
            return
        self.stop()
        self._disposed = True
        if self._pump_id is not None:
            self.after_cancel(self._pump_id)
            self._pump_id = None
        for win, _page in tuple(self._detached):
            if win.winfo_exists():
                win.destroy()
        self._detached.clear()
