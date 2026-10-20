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
from fengye_diagnostics import report
from force_card_art import ForceCardArtwork
from force_strength import format_average
from native_city_map import state_force_rgb

SHADOW_PREFIX = 'prefix-fengye-shadow'


def shown(value):
    return '—' if value is None else str(value)


def force_intel_values(state, lord):
    """Observed counts and verified attack sum; an absent container is unknown."""
    entities = state.get('entities') or {}
    fid = lord.get('force_id')
    units = [u for u in entities.get('field_units') or [] if u.get('owner_raw') == fid]
    cities = [c for c in entities.get('cities_and_barriers') or [] if c.get('owner_raw') == fid]
    known = [u['native_attack_index'] for u in units
             if type(u.get('native_attack_index')) in (int, float)]
    if 'field_units' not in entities:
        total, count = '—', '—'
    elif not units:
        total, count = '0', '0'
    else:
        count = str(len(units))
        total = format_average(sum(known)) if known else '—'
        if len(known) != len(units):
            total += '（%s/%s已知）' % (len(known), len(units))
    return (shown(lord.get('name')), shown(lord.get('prestige')), count, total,
            shown(lord.get('gold')), shown(lord.get('rice')),
            str(len(cities)) if 'cities_and_barriers' in entities else '—')


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
        self.on_error = None
        self.status_var = tk.StringVar(value='準備讀取風夜戰場…')
        bar = tk.Frame(self, bg='#edf1ef')
        bar.pack(fill='x')
        self.refresh_button = ttk.Button(bar, text='立即讀取', command=self.refresh)
        ttk.Label(bar, textvariable=self.status_var).pack(side='left', padx=8)
        self.panorama = ShadowPanorama(self, title='風夜全景地圖', detachable=True,
                                      detached_callback=self._open_detached)
        self.panorama.pack(fill='both', expand=True)
        self.map = self.panorama
        bottom = tk.PanedWindow(self, orient='horizontal', bg='#d2d5cd', sashwidth=6)
        bottom.pack(side='bottom', fill='x', padx=6, pady=(4, 6), before=self.panorama)
        self.forces = self._table(bottom, '勢力基礎情報', (
            ('force', '勢力', 70), ('prestige', '信望值', 55), ('units', '部隊數', 55),
            ('strength', '總戰力', 120), ('gold', '金', 80), ('rice', '米', 85), ('cities', '城', 40)))
        self.forces.configure(show='tree headings', height=2,
                              displaycolumns=('prestige', 'units', 'strength', 'gold', 'rice', 'cities'),
                              style='FengyeForces.Treeview')
        self.forces.heading('#0', text='勢力顏色／名稱 · 手牌（遊戲原圖）')
        scale = getattr(self.root, 'sgi_ui_scale', 1.)
        self.forces.column('#0', width=round(304*scale), minwidth=round(294*scale), stretch=False)
        ttk.Style(self).configure('FengyeForces.Treeview', rowheight=round(58*scale))
        self.force_art = ForceCardArtwork(self.root)
        self._force_photos = {}
        self._force_lords = {}
        self.force_hint = tk.StringVar(value='指向勢力查看手牌；總戰力為已知部隊攻擊指數之和，非實際傷害。')
        self.force_hint_label = ttk.Label(self, textvariable=self.force_hint)
        self.force_hint_label.pack(side='bottom', fill='x', padx=8, pady=(0, 4), before=bottom)
        self.forces.bind('<Motion>', self._force_hover)
        self.forces.bind('<<TreeviewSelect>>', self._refresh_force_art)
        self.units = self._table(bottom, '部隊（點選定位）', (
            ('owner', '勢力', 75), ('kind', '兵種', 100), ('xy', '座標', 80),
            ('soldiers', '兵力', 75), ('attack', '攻擊指數', 90), ('morale', '士氣', 50)))
        self.units.configure(height=4)
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
        horizontal = ttk.Scrollbar(box, orient='horizontal', command=tree.xview)
        horizontal.pack(side='bottom', fill='x', before=tree)
        tree.configure(xscrollcommand=horizontal.set)
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
                report('battle-read', exc)
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
                    report('battle-display', exc)
                    self.last_error = '地圖顯示失敗：%s' % exc
            if self.last_error and self.on_error:
                self.on_error()
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
            text += ' · 暫未讀到新資料，保留上次畫面；恢復後會自動更新。'
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
        self._force_lords = {}
        for index, lord in enumerate(lords):
            fid = lord.get('force_id')
            key = 'force-%s-%s' % (fid, index)
            self._force_lords[key] = lord
            force_rows.append((key, force_intel_values(state, lord)))
        self._replace_rows(self.forces, force_rows)
        self._refresh_force_art()
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

    def _refresh_force_art(self, _event=None):
        state = self.display_state or {}
        selected = set(self.forces.selection())
        photos = {}
        for key, lord in self._force_lords.items():
            # Artwork derives a bitmap only. It neither starts a source nor
            # writes derived card/identity values into the Collector snapshot.
            display = dict(lord, name=lord.get('name') or '未知勢力')
            hand = display.get('hand_cards')
            if not isinstance(hand, dict) or not isinstance(hand.get('slots'), list):
                display.pop('hand_cards', None)
            elif not all(isinstance(row, dict) and 'card_id' in row for row in hand['slots']):
                display.pop('hand_cards', None)
            color = state_force_rgb(state, lord.get('force_id'))
            photo = self.force_art.row(display, color, key in selected, show_cards=True)
            photos[key] = photo
            self.forces.item(key, image=photo)
        self._force_photos = photos

    def _force_hover(self, event):
        lord = self._force_lords.get(self.forces.identify_row(event.y))
        if lord is None:
            return
        slots = (lord.get('hand_cards') or {}).get('slots') or []
        names = '／'.join(shown(row.get('name')) for row in slots if isinstance(row, dict))
        self.force_hint.set('%s：%s' % (shown(lord.get('name')), names or '手牌未知'))

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
