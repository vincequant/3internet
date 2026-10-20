"""Read-only city map; a click highlights and explicit confirmation calls back.

``loader()`` runs on a daemon thread and returns ``ok``, ``cells``,
``occupied`` and ``busy``. A failed read invalidates the whole candidate set.
Only the UI thread touches Tk. Call ``set_city(city, loader=...)`` to reuse a
window for another city; old replies cannot replace the new city's state.
"""
from copy import deepcopy
from datetime import datetime, timezone
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk
from tactical_terrain import shared_terrain, world_pixel
from fengye_battle_panel import ShadowPanorama, prepare_payload, capture_time
from panorama_model import mbm_view, layer_for_zoom

RADIUS = 4
WORLD = (101, 202)
MAP_FILL = '#2d3627'


def cell_set(rows):
    """Accept a coordinate map, coordinate pairs, or native candidate rows."""
    result = set()
    if isinstance(rows, dict):
        rows = rows.keys()
    for row in rows or ():
        value = row.get('xy') if isinstance(row, dict) else row
        try:
            if len(value) != 2:
                continue
            # Unknown/fractional coordinates must not become buildable cells.
            x, y = int(value[0]), int(value[1])
            if x != value[0] or y != value[1]:
                continue
            if 0 <= x < WORLD[0] and 0 <= y < WORLD[1]:
                result.add((x, y))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def city_xy(city):
    xy = city.get('xy') or city.get('world_xy_raw')
    cells = cell_set([xy])
    if len(cells) != 1:
        raise ValueError('城池座標未知，無法選擇建設位置')
    return next(iter(cells))


def nearby_cells(center, radius=RADIUS):
    cx, cy = center
    return [(x, y) for y in range(max(0, cy-radius), min(WORLD[1], cy+radius+1))
            for x in range(max(0, cx-radius), min(WORLD[0], cx+radius+1))]


def cell_vertices(x, y):
    px, py = world_pixel(x, y)
    return ((px, py-24), (px+48, py), (px, py+24), (px-48, py))


def crop_box(center, radius=RADIUS):
    vertices = [point for xy in nearby_cells(center, radius) for point in cell_vertices(*xy)]
    return (min(p[0] for p in vertices), min(p[1] for p in vertices),
            max(p[0] for p in vertices), max(p[1] for p in vertices))


def view_geometry(box, width, height, padding=12):
    left, top, right, bottom = box
    scale = min(max(1, width-2*padding)/(right-left),
                max(1, height-2*padding)/(bottom-top))
    return (scale, (width-(right-left)*scale)/2, (height-(bottom-top)*scale)/2)


def project(point, box, view):
    scale, ox, oy = view
    return ox+(point[0]-box[0])*scale, oy+(point[1]-box[1])*scale


def hit_cell(sx, sy, center, box, view):
    """Resolve the actual staggered 96×48 diamond, including its tips."""
    scale, ox, oy = view
    px, py = (sx-ox)/scale+box[0], (sy-oy)/scale+box[1]
    nearest, distance = None, float('inf')
    for xy in nearby_cells(center):
        x, y = world_pixel(*xy)
        metric = abs(px-x)/48 + abs(py-y)/24
        if metric <= 1.00000001 and metric < distance:
            nearest, distance = xy, metric
    return nearest


def valid_candidates(payload, center):
    """No local guess: only successfully read candidates can be selected."""
    if payload.get('ok') is not True:
        return set(), set(), set()
    occupied = cell_set(payload.get('occupied'))
    busy = cell_set(payload.get('busy'))
    candidates = cell_set(payload.get('cells', payload.get('candidates')))
    candidates &= set(nearby_cells(center))
    return candidates - occupied - busy - {center}, occupied, busy


class ConstructionPanorama(ShadowPanorama):
    """Keep original world rendering/navigation; clicks only choose a cell."""
    def __init__(self, parent, picker):
        self.picker = picker
        super().__init__(parent, title='建設位置 · 原作全景地圖', detachable=False)
        self.canvas.bind('<Motion>', picker._hover, add='+')
        self.canvas.bind('<Leave>', lambda _event: picker.hover_label.configure(text=''))
        self.fit()

    def fit(self):
        self.center = self.picker.center
        self.zoom = 3.0
        self.request_draw()

    def draw(self, refresh_view=True):
        if self.picker._closed:
            return
        super().draw(refresh_view=refresh_view)
        self.picker._draw_panorama_overlay(self)

    def _release(self, event):
        start = self.drag
        self.drag = None
        if start and abs(event.x-start[0])+abs(event.y-start[1]) <= 8:
            self.picker._click(event)
        return 'break'

    def _double(self, _event):
        # Do not invoke object cards, tours or origin callbacks from this
        # construction surface. Only the explicit footer confirms a choice.
        return 'break'


def construction_candidates(state, actor, cities=(), busy=()):
    """Established radius-4/type-2 rule, from one original Collector sample.

    City ownership/coordinates and object occupancy come from this same raw
    sample. ``cities`` supplies display metadata only; it cannot override raw
    ownership. No Wine probe is launched here.
    """
    try:
        if type(actor) is not int:
            raise ValueError('目標勢力未知')
        grid = state.get('terrain_grid') or {}
        width, height = grid.get('width'), grid.get('height')
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError('原始地形網格未知')
        raw = bytes.fromhex(grid['types'])
        if len(raw) < width*height:
            raise ValueError('原始地形網格不完整')
        entities = state.get('entities') or {}
        occupied = set()
        for kind in ('production_buildings', 'traps', 'cities_and_barriers'):
            rows = entities.get(kind)
            if not isinstance(rows, list):
                raise ValueError('物件容器未知：'+kind)
            for row in rows:
                xy = row.get('world_xy_raw')
                if not isinstance(xy, (list, tuple)) or len(xy) != 2 or any(type(v) is not int for v in xy):
                    raise ValueError('物件位置未知')
                if 0 <= xy[0] < width and 0 <= xy[1] < height:
                    occupied.add(tuple(xy))
        occupied.update(cell_set(busy))
        supplied = {c.get('city_id'): c for c in cities or () if isinstance(c, dict)}
        owned = [c for c in entities['cities_and_barriers'] if c.get('owner_raw') == actor]
        candidates, ranks = {}, {}
        for row in owned:
            cid = row.get('city_id')
            if type(cid) is not int or sum(c.get('city_id') == cid for c in entities['cities_and_barriers']) != 1:
                continue
            cx, cy = row['world_xy_raw']
            if not (0 <= cx < width and 0 <= cy < height):
                continue
            city = dict(supplied.get(cid) or {}, **row)
            city.update(owner=actor, xy=[cx, cy])
            for y in range(max(0, cy-RADIUS), min(height, cy+RADIUS+1)):
                for x in range(max(0, cx-RADIUS), min(width, cx+RADIUS+1)):
                    xy = (x, y)
                    if xy == (cx, cy) or xy in occupied or raw[y*width+x] != 2:
                        continue
                    rank = (abs(x-cx)+abs(y-cy), cid)
                    if xy not in ranks or rank < ranks[xy]:
                        ranks[xy], candidates[xy] = rank, city
        return {'ok': True, 'cells': candidates, 'occupied': occupied,
                'width': width, 'height': height}
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return {'ok': False, 'cells': {}, 'occupied': set(), 'error': str(exc)}


def cell_at_pixel(px, py, width=WORLD[0], height=WORLD[1]):
    """Exact staggered diamond hit without scanning all cities on each motion."""
    y0 = round((py-24)/24)
    matches = []
    for y in range(max(0, y0-2), min(height, y0+3)):
        x0 = round((px-48-48*(y % 2))/96)
        for x in range(max(0, x0-1), min(width, x0+2)):
            tx, ty = world_pixel(x, y)
            distance = abs(px-tx)/48+abs(py-ty)/24
            if distance <= 1.00000001:
                matches.append((distance, y, x))
    if not matches:
        return None
    _distance, y, x = min(matches)
    return x, y


class EmbeddedConstructionPanorama(ShadowPanorama):
    """The main-page original map with an explicit construction selection."""
    def __init__(self, parent, picker):
        self.picker = picker
        super().__init__(parent, title='原作全景地圖', detachable=False)
        self.canvas.configure(height=250, width=800)
        self.canvas.bind('<Motion>', picker._hover, add='+')
        self.canvas.bind('<Leave>', lambda _event: picker.hover_label.configure(text=''))

    def draw(self, refresh_view=True):
        if self.picker._closed:
            return
        super().draw(refresh_view=refresh_view)
        self.picker._draw_overlay()

    def _release(self, event):
        if not self.picker.build_label:
            return super()._release(event)
        start = self.drag
        self.drag = None
        if start and abs(event.x-start[0])+abs(event.y-start[1]) <= 8:
            self.picker._click(event)
        return 'break'

    def _double(self, event):
        if not self.picker.build_label:
            return super()._double(event)
        return 'break'


class EmbeddedConstructionMap(tk.Frame):
    """Main-page map. Only explicit confirmation calls ``on_select(city,x,y)``.

    ``set_context`` runs on the Tk thread using the command panel's shared
    background snapshot. It performs bounded local geometry only; there are no
    subprocesses, network requests, additional readers, or child windows.
    """
    max_age_seconds = 15

    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.on_select = on_select
        self.build_label = None
        self.actor = None
        self.selected = None
        self.candidates = {}
        self._closed = False
        self._confirming = False
        self._known = False
        self._payload = {}
        self._game_scope = None
        self._context = None
        self._local_pending = set()
        self._pending_samples = {}
        self._width, self._height = WORLD
        self.panorama = EmbeddedConstructionPanorama(self, self)
        # A bounded requested height leaves the parent command timeline visible.
        self.panorama.configure(height=320)
        self.panorama.pack_propagate(False)
        self.panorama.pack(fill='both', expand=True)
        self.canvas = self.panorama.canvas
        footer = ttk.Frame(self)
        footer.pack(side='bottom', fill='x', pady=(4, 2))
        # Reserve the explicit confirmation row before the expanding map.
        # On a short command page the map may shrink; the action must remain
        # visible rather than being packed outside the available height.
        self.panorama.pack_forget()
        self.panorama.pack(fill='both', expand=True)
        self.selection_label = ttk.Label(footer, text='選建設種類後，在原地圖選綠框位置')
        self.selection_label.pack(side='left')
        self.hover_label = ttk.Label(footer, text='')
        self.hover_label.pack(side='left', padx=14)
        self.confirm_button = ttk.Button(footer, text='確認位置並加入隊列', state='disabled', command=self._confirm)
        self.confirm_button.pack(side='right')
        self.use_button = self.confirm_button
        self.bind('<Destroy>', self._destroyed, add='+')

    def _destroyed(self, event):
        if event.widget is self:
            self._closed = True

    @staticmethod
    def _scope(payload):
        if payload.get('game_key'):
            return ('game_key', payload['game_key'])
        state = payload.get('state') or {}
        identity = state.get('identity') or {}
        if identity:
            return ('observed_source', payload.get('source_prefix'), identity.get('pid'),
                    identity.get('creation_filetime'), identity.get('path'), state.get('core_address'))
        return None

    def _fresh(self):
        captured = capture_time(self._payload)
        if captured is None:
            return False
        age = (datetime.now(timezone.utc)-captured).total_seconds()
        return -2 <= age <= self.max_age_seconds

    def set_context(self, build_label, actor, cities, payload, busy=()):
        if self._closed:
            return
        payload = payload if isinstance(payload, dict) else {}
        scope = self._scope(payload)
        game_changed = scope is not None and scope != self._game_scope
        if game_changed:
            self._local_pending.clear()
            self._pending_samples.clear()
            self._game_scope = scope
        context = (build_label or None, actor, self._game_scope)
        if context != self._context:
            self.selected = None
        self._context = context
        self.build_label, self.actor = build_label or None, actor
        self._payload = payload
        self._known = False
        self.candidates = {}
        try:
            display = prepare_payload(payload)
            self.panorama.update_state(display, lists=False, immediate=False, refresh_view=False)
            if game_changed:
                self.panorama.fit()
            if self.build_label:
                if not self._fresh():
                    raise ValueError('觀測時間未知或已過期，等待新地圖')
                # Once the shared service reports a pending cell, it owns the
                # reservation. Later cancellation can then release it normally.
                observed_busy = cell_set(busy)
                sample = (payload['state'].get('snapshot_id'), payload['state'].get('capture_end'))
                captured = capture_time(payload)
                for xy in tuple(self._local_pending):
                    submitted_sample, submitted_at = self._pending_samples.get(xy, (None, float('inf')))
                    # A shared busy snapshot takes over immediately. A newer
                    # post-submit game sample plus a current empty busy list
                    # also releases a command cancelled before it was polled.
                    if xy in observed_busy or (sample != submitted_sample and captured is not None and captured.timestamp() > submitted_at):
                        self._local_pending.discard(xy)
                        self._pending_samples.pop(xy, None)
                computed = construction_candidates(payload['state'], actor, cities,
                    observed_busy | self._local_pending)
                if not computed['ok']:
                    raise ValueError(computed['error'])
                self._width, self._height = computed['width'], computed['height']
                self.candidates = computed['cells']
                self._known = True
                text = '%s · 可選 %d 格 · 單擊只選位置，確認後才加入隊列' % (self.build_label, len(self.candidates))
            else:
                text = '選建設種類後，在原圖點綠框；滾輪縮放、拖曳／WASD 平移'
            self.panorama.status.set(text)
        except Exception as exc:
            self.panorama.status.set('資料未知／過期 · '+str(exc))
        if self.selected not in self.candidates:
            self.selected = None
        self._update_selection()
        self.panorama.draw(refresh_view=False)

    def _event_cell(self, event):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        box, scale = mbm_view(self.panorama.center, self.panorama.zoom, width, height)
        return cell_at_pixel(box[0]+self.canvas.canvasx(event.x)/scale,
                             box[1]+self.canvas.canvasy(event.y)/scale,
                             self._width, self._height)

    def _hover(self, event):
        xy = self._event_cell(event)
        if not self.build_label or xy is None:
            text = ''
        else:
            city = self.candidates.get(xy)
            text = '%s,%s · %s' % (*xy, (city.get('name') or '己方城池') if city else '不可選／未知')
        self.hover_label.configure(text=text)

    def _click(self, event):
        if not self.build_label:
            return 'break'
        if not self._known or not self._fresh():
            self._known = False
            self.candidates.clear()
            self.selected = None
            self.panorama.status.set('資料未知／過期，等待新地圖後再選址')
        else:
            xy = self._event_cell(event)
            self.selected = xy if xy in self.candidates else None
        self._update_selection()
        self._draw_overlay()
        return 'break'

    def _update_selection(self):
        city = self.candidates.get(self.selected)
        if city:
            text = '%s · %s · 位置 %s,%s' % (self.build_label, city.get('name') or '己方城池', *self.selected)
        elif self.build_label:
            text = '%s：滾輪放大後點綠框，再確認入隊' % self.build_label
        else:
            text = '選建設種類後，在原地圖選綠框位置'
        self.selection_label.configure(text=text)
        self.confirm_button.configure(state='normal' if self._known and city and not self._confirming else 'disabled')

    def _draw_overlay(self):
        if self._closed:
            return
        canvas, page = self.canvas, self.panorama
        canvas.delete('build-pick')
        if not self.build_label or not self._known:
            return
        width, height = canvas.winfo_width(), canvas.winfo_height()
        layer = layer_for_zoom(page.zoom)
        for xy in self.candidates:
            points = [coordinate for p in cell_vertices(*xy)
                      for coordinate in page._project_mbm(*p, width, height, layer)]
            if max(points[::2]) < 0 or min(points[::2]) > width or max(points[1::2]) < 0 or min(points[1::2]) > height:
                continue
            selected = xy == self.selected
            canvas.create_polygon(points, fill='', outline='#ffe35c' if selected else '#65bd76',
                                  width=3 if selected else 1, tags=('build-pick', 'build-selected' if selected else 'build-candidate'))
        if self.selected is not None:
            px, py = page._project(*self.selected, width, height, layer)
            label = '%s,%s' % self.selected
            canvas.create_text(px+1, py-29, text=label, fill='#172018', tags='build-pick')
            canvas.create_text(px, py-30, text=label, fill='#fff099', tags='build-pick')

    def _confirm(self):
        if self._closed or self._confirming or not self._known:
            return False
        if not self._fresh():
            self._known = False
            self.candidates.clear()
            self.selected = None
            self.panorama.status.set('資料未知／過期，等待新地圖後再選址')
            self._update_selection()
            self._draw_overlay()
            return False
        xy = self.selected
        city = self.candidates.get(xy)
        if city is None:
            return False
        context = self._context
        self._confirming = True
        self._update_selection()
        try:
            accepted = self.on_select(deepcopy(city), *xy) is True
        except Exception as exc:
            self.panorama.status.set('未加入隊列：'+str(exc))
            accepted = False
        finally:
            self._confirming = False
        if accepted and self._context == context:
            self._local_pending.add(xy)
            state = self._payload.get('state') or {}
            self._pending_samples[xy] = ((state.get('snapshot_id'), state.get('capture_end')),
                                         datetime.now(timezone.utc).timestamp())
            self.candidates.pop(xy, None)
            self.selected = None
        if not self._closed:
            self._update_selection()
            self._draw_overlay()
        return accepted


class BuildPicker(tk.Toplevel):
    """An explicit local terrain choice, with singleflight three-second reads."""
    refresh_seconds = 3.0

    def __init__(self, parent, city, build_label, on_select, loader):
        center = city_xy(city)
        super().__init__(parent)
        self.city = dict(city)
        self.center = center
        self.build_label = str(build_label)
        self.on_select, self.loader = on_select, loader
        self.selected = None
        self.candidates, self.occupied, self.busy = set(), set(), set()
        self._closed = False
        self._selection_used = False
        self._generation = 0
        self._serial = 0
        self._active = None
        self._known = False
        self._results = queue.Queue()
        self._next_read = 0.0
        self._poll_id = None
        self._photo = None
        self._terrain = None
        self._terrain_error = ''
        self.panorama = None
        self._panorama_mode = False
        self._display_state = None
        self.geometry('1180x760')
        self.minsize(900, 620)
        self.transient(parent.winfo_toplevel())
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.heading = ttk.Label(self, font=('', 15, 'bold'))
        self.heading.pack(anchor='w', padx=14, pady=(14, 6))
        ttk.Label(self, text='單擊只選位置；確認後才加入隊列。可用原版滾輪縮放、拖曳／WASD 平移。').pack(anchor='w', padx=14)
        legend = ttk.Frame(self)
        legend.pack(fill='x', padx=14, pady=6)
        for text, color in (('細綠框：可選', '#2b873b'), ('淡紅框：已有物件', '#a34f4f'),
                            ('淡橙框：已排隊／處理中', '#b27633')):
            tk.Label(legend, text=text, fg=color).pack(side='left', padx=(0, 14))
        self.map_area = tk.Frame(self, bg=MAP_FILL)
        self.map_area.pack(fill='both', expand=True, padx=14)
        self.canvas = tk.Canvas(self.map_area, bg=MAP_FILL, highlightthickness=0, takefocus=False)
        self._fallback_canvas = self.canvas
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self._draw)
        self.canvas.bind('<Button-1>', self._click)
        self.canvas.bind('<Motion>', self._hover)
        self.canvas.bind('<Leave>', lambda _event: self.hover_label.configure(text=''))
        # Consume all wheel variants: inherited panorama class handlers must
        # never scroll this independent, fixed city crop.
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>', '<TouchpadScroll>'):
            try:
                self.canvas.bind(sequence, lambda _event: 'break')
            except tk.TclError:
                pass
        self.status = ttk.Label(self, text='正在讀取城周邊可建格…', wraplength=930)
        self.status.pack(anchor='w', padx=14, pady=(8, 4))
        footer = ttk.Frame(self)
        footer.pack(fill='x', padx=14, pady=(2, 14))
        self.selection_label = ttk.Label(footer, text='尚未選位置')
        self.selection_label.pack(side='left')
        self.hover_label = ttk.Label(footer, text='')
        self.hover_label.pack(side='left', padx=16)
        self.use_button = ttk.Button(footer, text='確認位置並加入隊列', command=self._use, state='disabled')
        self.use_button.pack(side='right')
        ttk.Button(footer, text='取消', command=self.destroy).pack(side='right', padx=8)
        self.retry_button = ttk.Button(footer, text='重新讀取', command=self.refresh)
        self.retry_button.pack(side='right')
        self._update_heading()
        self.refresh()
        self._poll_id = self.after(40, self._poll)

    def _update_heading(self):
        name = self.city.get('name') or ('城池 #%s' % self.city.get('city_id', '?'))
        self.title('%s · 選擇建設位置' % name)
        self.heading.configure(text='%s · %s（城中心 %s,%s）' % (name, self.build_label, *self.center))

    def set_city(self, city, loader=None):
        """Change city; pass its matching zero-argument loader at the same time."""
        center = city_xy(city)
        self._generation += 1
        self.city, self.center = dict(city), center
        if loader is not None:
            self.loader = loader
        self.selected = None
        self.candidates, self.occupied, self.busy = set(), set(), set()
        self._known = False
        self._terrain = None
        self._display_state = None
        if self.panorama is not None:
            self.panorama.state = None
            self.panorama.fit()
        self._next_read = 0
        self._update_heading()
        self.status.configure(text='正在讀取新城池；舊城池的回覆將忽略…')
        self._update_selection()
        self._draw()
        self.refresh()

    def refresh(self):
        if self._closed or self._active is not None:
            return False
        self._serial += 1
        token = (self._generation, self._serial)
        self._active = token
        self.retry_button.configure(state='disabled')
        self.use_button.configure(state='disabled')
        loader, box = self.loader, crop_box(self.center)
        need_terrain = self._terrain is None
        def read():
            try:
                payload = loader()
                if not isinstance(payload, dict):
                    raise ValueError('可建格來源沒有回傳狀態')
            except Exception as exc:
                payload = {'ok': False, 'error': str(exc)}
            display, display_error = None, ''
            if payload.get('state') is not None:
                try:
                    display = prepare_payload(payload)
                except Exception as exc:
                    display_error = str(exc)
            terrain, terrain_error = None, ''
            if need_terrain and display is None:
                try:
                    terrain = shared_terrain().crop(box)
                except Exception as exc:
                    terrain_error = str(exc)
            self._results.put((token, payload, terrain, terrain_error, display, display_error))
        threading.Thread(target=read, daemon=True, name='fengye-build-cells').start()
        return True

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                token, payload, terrain, terrain_error, display, display_error = self._results.get_nowait()
                if token == self._active:
                    self._active = None
                    self.retry_button.configure(state='normal')
                if token[0] != self._generation:
                    continue
                self.candidates, self.occupied, self.busy = valid_candidates(payload, self.center)
                self._known = payload.get('ok') is True
                if display is not None:
                    self._show_panorama(display)
                elif display_error or self._panorama_mode:
                    self._known = False
                    self.candidates = set()
                    display_error = display_error or '完整風夜地圖未知，保留最後畫面'
                if terrain is not None:
                    self._terrain = terrain
                self._terrain_error = terrain_error
                invalidated = self.selected is not None and self.selected not in self.candidates
                if invalidated:
                    self.selected = None
                if self._known:
                    text = '可選 %d 格 · 每 3 秒自動更新 · %s' % (len(self.candidates), time.strftime('%H:%M:%S'))
                    if invalidated:
                        text += '；原選取格已不可用，請重選'
                else:
                    self.selected = None
                    text = '位置未知，暫不能選擇：%s。請重新讀取。' % (payload.get('error') or '讀取未成功')
                if display_error:
                    text += '；' + display_error
                elif terrain_error:
                    text += '；原地形未載入：' + terrain_error
                if self.panorama is not None:
                    self.panorama.status.set(text if self._known else '資料已過期／未知 · '+text)
                self.status.configure(text=text)
                self._next_read = time.monotonic()+self.refresh_seconds
                self._update_selection()
                self._draw()
        except queue.Empty:
            pass
        if self._active is None and time.monotonic() >= self._next_read:
            self.refresh()
        self._poll_id = self.after(40, self._poll)

    def _show_panorama(self, display):
        focus_city = self._display_state is None
        self._display_state = display
        if self.panorama is None:
            self.panorama = ConstructionPanorama(self.map_area, self)
        if not self._panorama_mode:
            self._fallback_canvas.pack_forget()
            self.panorama.pack(fill='both', expand=True)
            self.canvas = self.panorama.canvas
            self._panorama_mode = True
        self.panorama.update_state(display, lists=False, immediate=False, refresh_view=False)
        if focus_city:
            self.panorama.fit()

    def _draw(self, _event=None):
        if self._closed:
            return
        if self._panorama_mode:
            self.panorama.draw(refresh_view=False)
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 4 or height < 4:
            return
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.canvas.delete('all')
        box = crop_box(self.center)
        view = view_geometry(box, width, height)
        scale, ox, oy = view
        if self._terrain is not None:
            from PIL import Image
            image = self._terrain.resize((max(1, round((box[2]-box[0])*scale)),
                                          max(1, round((box[3]-box[1])*scale))), Image.Resampling.NEAREST)
            self._photo = ImageTk.PhotoImage(image, master=self)
            self.canvas.create_image(ox, oy, image=self._photo, anchor='nw')
        self._draw_outlines(self.canvas, lambda p: project(p, box, view))
        if self._terrain is None:
            self.canvas.create_text(width/2, 16, text='原地形載入中…' if not self._terrain_error else '原地形未知；僅顯示已核實格位',
                                    fill='white', anchor='n')

    def _draw_panorama_overlay(self, page):
        canvas = page.canvas
        canvas.delete('build-pick')
        width, height = canvas.winfo_width(), canvas.winfo_height()
        layer = layer_for_zoom(page.zoom)
        self._draw_outlines(canvas, lambda p: page._project_mbm(*p, width, height, layer))

    def _draw_outlines(self, canvas, project_point):
        # The original sprites, terrain, roads and supply remain uncovered.
        # No opaque/stippled board and no labels on every candidate square.
        cells = (self.candidates if self._known else set()) | self.occupied | self.busy
        if self.selected is not None:
            cells = cells | {self.selected}
        cells &= set(nearby_cells(self.center))
        for xy in sorted(cells):
            if xy == self.selected:
                outline, thick, tag = '#ffe35c', 3, 'build-selected'
            elif xy in self.occupied:
                outline, thick, tag = '#b18d86', 1, 'build-occupied'
            elif xy in self.busy:
                outline, thick, tag = '#c6a57d', 1, 'build-busy'
            else:
                outline, thick, tag = '#65bd76', 1, 'build-candidate'
            points = [coordinate for p in cell_vertices(*xy) for coordinate in project_point(p)]
            canvas.create_polygon(points, fill='', outline=outline, width=thick, tags=('build-pick', tag))
        if self.selected is not None:
            px, py = project_point(world_pixel(*self.selected))
            label = '選取 %s,%s' % self.selected
            canvas.create_text(px+1, py-30+1, text=label, fill='#152018', font=('', 12, 'bold'), tags='build-pick')
            canvas.create_text(px, py-30, text=label, fill='#fff099', font=('', 12, 'bold'), tags='build-pick')

    def _event_cell(self, event):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self._panorama_mode:
            box, scale = mbm_view(self.panorama.center, self.panorama.zoom, width, height)
            view = (scale, 0, 0)
        else:
            box = crop_box(self.center)
            view = view_geometry(box, width, height)
        return hit_cell(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), self.center, box, view)

    def _hover(self, event):
        xy = self._event_cell(event)
        if xy is None:
            text = ''
        else:
            state = '可選' if self._known and xy in self.candidates else '已有物件' if xy in self.occupied else '已排隊' if xy in self.busy else '非候選／未知'
            text = '游標：%s,%s · %s' % (*xy, state)
        self.hover_label.configure(text=text)

    def _click(self, event):
        xy = self._event_cell(event)
        if self._known and xy in self.candidates:
            self.selected = xy
            self._update_selection()
            self._draw()
        elif xy is not None:
            self.status.configure(text='此格已有物件／已排隊，或沒有可建證據；請點綠色格。')
        return 'break'

    def _update_selection(self):
        text = ('已選位置：%s,%s' % self.selected) if self.selected else '尚未選位置'
        self.selection_label.configure(text=text)
        self.use_button.configure(state='normal' if self._known and self.selected in self.candidates and self._active is None else 'disabled')

    def _use(self):
        if self._closed or self._selection_used or self._active is not None or not self._known or self.selected not in self.candidates:
            return
        self._selection_used = True
        self.on_select(*self.selected)
        self.destroy()

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
        super().destroy()
