"""Independent maximized panorama: original terrain plus live overlays. Read-only."""
import queue
import sys
import threading
import time
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from PIL import Image, ImageTk

from city_tactical import fmt
from dock_icon import apply as apply_dock_icon
from force_relations import at_war
from mac_light_theme import apply_light_defaults
from map_navigation import bind_arrows, bind_pointer_wheel, bind_zoom_keys, move_center, navigation_bar
from map_unit_labels import label_box, raise_label, unit_label_ink
from trap_state import trap_city_ids
from unit_memory import memory_line
from native_unit_rules import displays_attack
from unit_special_chance import special_details
from native_city_map import map_viewport, state_force_rgb
from original_sprites import OriginalSprites
from city_roads import mbm_to_world, path_for_layer
from panorama_model import (
    DEFAULT_CENTER, DETAIL_ZOOM, LAYER_HINT, MIN_ZOOM, SWITCH_ZOOM, WORLD, box_from_corners,
    capital_marks, cell_diamond, clamp_center, clamp_zoom, is_capital, layer_for_zoom,
    live_objects, mbm_view, object_key, object_label, opponent_brief, overlay_force_diamonds,
    paint_mbm_vision, show_kind_at_zoom, show_overlay, sort_view_units, sprite_size, supply_lines,
    clamp_mbm_view,
    parse_map_point, search_city_places, units_in_view, view_unit_line,
    vision_overlay_cells, world_xy,
)
from unit_move import city_marker_text, lighten_rgb, move_brief, move_overlay_cells
from player_view import player_id
from stealth_raid import SPRITE_KIND, format_raid_brief, plan_stealth_raid, resolve_raid_endpoints
from recruitment_summary import city_card_text, cities_over_produce, cities_over_produce_score
from tactical_terrain import Terrain, shared_terrain, world_pixel

_SHARED_LBM = None
_SHARED_LBM_MISSING = False


def shared_lbm():
    global _SHARED_LBM, _SHARED_LBM_MISSING
    if _SHARED_LBM is not None:
        return _SHARED_LBM
    if _SHARED_LBM_MISSING:
        return None
    try:
        _SHARED_LBM = Image.open(APP / 'assets' / 'SanInet.lbm').convert('RGB')
        return _SHARED_LBM
    except (OSError, ValueError):
        _SHARED_LBM_MISSING = True
        return None

APP = Path(__file__).resolve().parent
ROOT = APP.parent
BG = '#1b1d18'
INK = '#efe7cf'
MUTED = '#b7ad8f'
BAR = '#2a2c24'
PRODUCE_RINGS = (
    ('infantry', '步', '#8a6a2a'),
    ('cavalry', '骑', '#c45a18'),
    ('bow', '弓', '#368049'),
)
SCORE_RING = ('score', '总分', '#d4a017')


def ui_font(root):
    families = set(tkfont.families(root))
    for name in ('PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti', 'Microsoft YaHei'):
        if name in families:
            return name
    return 'TkDefaultFont'


def tk_pixels(widget, value):
    """Tk 9 Canvas.cget('width') can be '10c'; winfo_fpixels converts screen units."""
    if value in (None, '', 0, '0'):
        return 0
    try:
        return max(0, int(round(float(widget.winfo_fpixels(str(value))))))
    except (tk.TclError, TypeError, ValueError, AttributeError):
        try:
            return max(0, int(round(float(str(value)))))
        except ValueError:
            return 0


def maximize(root):
    root.update_idletasks()
    try:
        root.state('zoomed')
    except tk.TclError:
        pass
    root.geometry(f'{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0')


def acquire_lock(path=None):
    path = Path(path or ROOT / 'logs' / 'panorama.lock')
    path.parent.mkdir(exist_ok=True)
    stream = path.open('a+b')
    try:
        if sys.platform == 'win32':
            import msvcrt
            stream.seek(0)
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        stream.close()
        return None
    return stream


class PanoramaMap(tk.Frame):
    def __init__(self, parent, title='全景视窗', detachable=False, mode='full'):
        super().__init__(parent, bg=BG)
        self.face = ui_font(parent.winfo_toplevel())
        self.title_text = title
        self.detachable = detachable
        self.mode = 'raid' if mode == 'raid' else 'full'
        self.slim = self.mode == 'raid'
        self.zoom = MIN_ZOOM if self.slim else 6.0
        self.center = DEFAULT_CENTER
        self.world = WORLD
        self.scenario_id = 'china'
        self.scenario_name = '大地图'
        self.state = None
        self.lbm = None
        self.terrain = None
        self.terrain_error = ''
        self.photo = None
        self.selected = None
        self.hits = []
        self.drag = None
        names = ('补给线', '首都', '城关', '建筑', '部队', '陷阱', '文字')
        shown = ('首都', '城关', '部队', '文字') if self.slim else names
        self.layers = {name: tk.BooleanVar(value=name in shown) for name in names}
        self.war_only = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='正在连接只读采集…')
        self.brief = tk.StringVar(value=opponent_brief(None))
        self.detail = tk.StringVar(value='点图上的城关、建筑、部队或陷阱查看对手状态。')
        self.city_query = tk.StringVar()
        self.city_hint = tk.StringVar(value='搜城名或坐标，例如 江陵 或 52,124')
        self.search_mark = None
        self._search_hits = []
        self._search_index = 0
        self._search_text = ''
        self.raid_on = False
        self.raid_plan = None
        self._force_ledger = None
        self._ops_from_replay = False
        self.on_force_op = None
        self.focus_force_id = None
        self.capital_force_ids = []
        self._view_sig = None
        self.view_unit_keys = []
        self._load_assets()
        self._build()
        self.sprites = OriginalSprites(self.canvas)
        self.on_pick_origin = None
        self.on_pick_cell = None
        self.on_pick_unit = None
        self.on_tour_unit = None
        self.canvas.bind('<Configure>', lambda _=None: self.request_draw())
        bind_pointer_wheel(self.canvas, self._wheel)
        bind_pointer_wheel(self, self._wheel)
        self.canvas.bind('<ButtonPress-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        bind_arrows(self.canvas, self.pan)
        bind_arrows(self, self.pan)
        bind_zoom_keys(self.canvas, self._wheel_delta)
        bind_zoom_keys(self, self._wheel_delta)
        self.canvas.bind('<Double-1>', self._double)
        if not self.slim:
            self.after(80, self.draw)

    def open_detached(self):
        from wine_nav import open_panorama
        open_panorama(self.center, self.zoom if self.zoom >= SWITCH_ZOOM else 6.)

    def _load_assets(self):
        self.lbm = shared_lbm()
        try:
            self.terrain = shared_terrain(warmup=True)
        except (OSError, ValueError) as error:
            self.terrain_error = str(error)

    def _build(self):
        bar = tk.Frame(self, bg=BAR)
        bar.pack(fill='x')
        tk.Label(bar, text=self.title_text, bg=BAR, fg=INK, font=(self.face, 16, 'bold')).pack(side='left', padx=12, pady=8)
        tk.Label(bar, textvariable=self.status, bg=BAR, fg=MUTED, font=(self.face, 11)).pack(side='left', padx=8)
        if self.detachable and not self.slim:
            tk.Button(
                bar, text='独立大地图', command=self.open_detached,
                bg='#e7e0c9', fg='#302c22', activebackground='#d4c89a',
                activeforeground='#302c22', highlightbackground='#2a2c24',
                relief='raised', borderwidth=1, padx=12,
            ).pack(side='left', padx=6)
        self._side_btn = None
        if not self.slim:
            self._side_btn = tk.Button(
                bar, text='展开对手状态', command=self.toggle_side,
                bg='#e7e0c9', fg='#302c22', activebackground='#d4c89a',
                activeforeground='#302c22', highlightbackground='#2a2c24',
                relief='raised', borderwidth=1, padx=12,
            )
            self._side_btn.pack(side='left', padx=6)
        tk.Label(bar, text='滚轮或 -/=', bg=BAR, fg=MUTED, font=(self.face, 10)).pack(side='right', padx=8)
        for text, command in (('全图', self.fit), ('－', lambda: self.change_zoom(-0.5)), ('＋', lambda: self.change_zoom(0.5))):
            tk.Button(bar, text=text, command=command, bg='#3d3f34', fg=INK, relief='flat', padx=10).pack(side='right', padx=3, pady=6)
        if not self.slim:
            for name in reversed(tuple(self.layers)):
                tk.Checkbutton(bar, text=name, variable=self.layers[name], command=self.draw, bg=BAR, fg=INK, selectcolor=BAR, activebackground=BAR, activeforeground=INK).pack(side='right', padx=2)
            tk.Checkbutton(bar, text='只看交战/我方', variable=self.war_only, command=self.draw, bg=BAR, fg='#e7c27a', selectcolor=BAR, activebackground=BAR).pack(side='right', padx=8)
        self.layer = tk.StringVar()
        tk.Label(bar, textvariable=self.layer, bg=BAR, fg='#d8c27a', font=(self.face, 10)).pack(side='right', padx=10)
        if self.slim:
            map_area = tk.Frame(self, bg=BG)
            map_area.pack(fill='both', expand=True)
            self._body = None
            self._side_open = False
            side = None
        else:
            body = tk.PanedWindow(self, orient='horizontal', sashwidth=8, bg='#3d3f34',
                                  sashrelief='raised', opaqueresize=False)
            body.pack(fill='both', expand=True)
            map_area = tk.Frame(body, bg=BG)
            side = tk.Frame(self, bg='#22241d', width=420)
            body.add(map_area, stretch='always', minsize=360)
            self._body = body
            self._side_open = False
        nav = navigation_bar(map_area, self.pan, self.fit)
        nav.pack(fill='x')
        if not self.slim:
            ttk.Label(nav, text='对方势力').pack(side='left', padx=(12, 4))
            self.opponent = tk.StringVar(value='不圈部队')
            self.opponent_ids = {}
            self.opponent_box = ttk.Combobox(nav, textvariable=self.opponent, state='readonly', width=10)
            self.opponent_box.pack(side='left')
            self.opponent_box.bind('<<ComboboxSelected>>', lambda _e=None: self.draw())
            ttk.Label(nav, text='城池').pack(side='left', padx=(16, 4))
            entry = ttk.Entry(nav, textvariable=self.city_query, width=14)
            entry.pack(side='left')
            entry.bind('<Return>', self.go_city)
            ttk.Button(nav, text='定位', command=self.go_city).pack(side='left', padx=4)
            ttk.Label(nav, text='可产圈 >').pack(side='left', padx=(16, 4))
            self.produce_vars = {}
            for kind, label, color in PRODUCE_RINGS:
                ttk.Label(nav, text=label).pack(side='left')
                var = tk.StringVar()
                self.produce_vars[kind] = var
                box = ttk.Entry(nav, textvariable=var, width=6)
                box.pack(side='left', padx=(2, 8))
                box.bind('<KeyRelease>', lambda _e=None: self.draw())
                box.bind('<Return>', lambda _e=None: self.draw())
            ttk.Label(nav, text='总分(步1骑3弓1)>').pack(side='left', padx=(8, 2))
            self.produce_vars[SCORE_RING[0]] = tk.StringVar()
            score_box = ttk.Entry(nav, textvariable=self.produce_vars[SCORE_RING[0]], width=6)
            score_box.pack(side='left', padx=(2, 8))
            score_box.bind('<KeyRelease>', lambda _e=None: self.draw())
            score_box.bind('<Return>', lambda _e=None: self.draw())
        else:
            self.produce_vars = {}
        ttk.Label(nav, textvariable=self.city_hint).pack(side='left', padx=8)
        holder = tk.Frame(map_area, bg=BG)
        holder.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(holder, bg='#68724e', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self._side = side
        if self.slim:
            return
        side.bind('<Configure>', self._side_wrap)
        tk.Label(side, text='对手状态', bg='#22241d', fg=INK, font=(self.face, 13, 'bold'), anchor='w').pack(fill='x', padx=12, pady=(12, 4))
        self._brief_label = tk.Label(side, textvariable=self.brief, bg='#22241d', fg='#e4c56a', wraplength=376, justify='left', anchor='w', font=(self.face, 11))
        self._brief_label.pack(fill='x', padx=12)
        tk.Label(side, text='各军首都（点势力看指令和部队）', bg='#22241d', fg=MUTED, anchor='w', font=(self.face, 10)).pack(fill='x', padx=12, pady=(10, 2))
        self.capitals = tk.Listbox(side, bg='#2c2f26', fg=INK, selectbackground='#6a5520', height=8, font=(self.face, 11), relief='flat')
        self.capitals.pack(fill='x', padx=12)
        self.capitals.bind('<<ListboxSelect>>', self._pick_capital)
        style = ttk.Style(self)
        style.configure('Panorama.TNotebook', background='#22241d', borderwidth=0)
        style.configure('Panorama.TNotebook.Tab', background='#2c2f26', foreground='#efe7cf', padding=(8, 4))
        style.map('Panorama.TNotebook.Tab', background=[('selected', '#5a4a20')], foreground=[('selected', '#ffe9a3')])
        tabs = ttk.Notebook(side, style='Panorama.TNotebook')
        tabs.pack(fill='both', expand=True, padx=8, pady=(10, 0))
        self.side_tabs = tabs
        ops_tab = tk.Frame(tabs, bg='#22241d')
        force_tab = tk.Frame(tabs, bg='#22241d')
        view_tab = tk.Frame(tabs, bg='#22241d')
        war_tab = tk.Frame(tabs, bg='#22241d')
        tabs.add(ops_tab, text='指令')
        tabs.add(force_tab, text='该势力部队')
        tabs.add(view_tab, text='本视野部队')
        tabs.add(war_tab, text='交战部队')
        self._ops_hint = tk.Label(ops_tab, text='点上方势力后只看该国。建设/训练/录用/出征由相邻帧推断，不是引擎指令日志。',
                 bg='#22241d', fg=MUTED, wraplength=376, justify='left', font=(self.face, 9))
        self._ops_hint.pack(fill='x', padx=4, pady=(6, 2))
        self.force_ops = tk.Text(ops_tab, bg='#2c2f26', fg=INK, relief='flat', font=(self.face, 10), wrap='word')
        self.force_ops.pack(fill='both', expand=True, padx=4, pady=(0, 8))
        self.force_ops.bind('<Key>', lambda _e=None: 'break')
        self.force_ops.bind('<<Paste>>', lambda _e=None: 'break')
        self.force_ops.tag_configure('force', foreground='#ffe9a3', font=(self.face, 11, 'bold'))
        self.force_ops.tag_configure('quarter', foreground='#c4b48a')
        self.force_ops.tag_configure('civil', foreground='#e8d6a8')
        self.force_ops.tag_configure('military', foreground='#9ec0e8')
        self.force_ops.tag_configure('empty', foreground='#8a8474')
        self.force_ops.tag_configure('inferred', foreground='#f3d48a')
        self.force_ops.tag_configure('fact', foreground='#c8f0c0')
        self.force_ops.tag_configure('observed_change', foreground='#d7e4f5')
        self.force_ops.tag_configure('unknown', foreground='#c9c3b4')
        self.force_unit_hint = tk.StringVar(value='点上方势力后列出该国全部出征部队；点部队弹出定位图，可翻页')
        tk.Label(force_tab, textvariable=self.force_unit_hint, bg='#22241d', fg=MUTED,
                 font=(self.face, 9), anchor='w').pack(fill='x', padx=4, pady=(6, 2))
        self.force_units = tk.Listbox(force_tab, bg='#2c2f26', fg=INK, selectbackground='#6a5520',
                                      font=(self.face, 10), relief='flat')
        self.force_units.pack(fill='both', expand=True, padx=4, pady=(0, 8))
        self.force_units.bind('<<ListboxSelect>>', self._pick_force_unit)
        self.force_unit_keys = []
        self.view_hint = tk.StringVar(value='拖到覆盖范围后列出该范围内部队')
        tk.Label(view_tab, textvariable=self.view_hint, bg='#22241d', fg=MUTED,
                 font=(self.face, 9), anchor='w').pack(fill='x', padx=4, pady=(6, 2))
        self.view_units = tk.Listbox(view_tab, bg='#2c2f26', fg=INK, selectbackground='#6a5520',
                                     font=(self.face, 10), relief='flat')
        self.view_units.pack(fill='both', expand=True, padx=4, pady=(0, 8))
        self.view_units.bind('<<ListboxSelect>>', self._pick_view_unit)
        self.view_unit_keys = []
        self._view_sig = None
        self.war_power = tk.StringVar(value='各势力总战力按出征部队攻击指数相加，不是实伤。')
        self._war_label = tk.Label(war_tab, textvariable=self.war_power, bg='#22241d', fg='#e4c56a',
                 wraplength=376, justify='left', anchor='nw', font=(self.face, 10))
        self._war_label.pack(fill='x', padx=4, pady=(6, 2))
        self.enemies = tk.Listbox(war_tab, bg='#2c2f26', fg=INK, selectbackground='#6a3b2a',
                                  font=(self.face, 11), relief='flat')
        self.enemies.pack(fill='both', expand=True, padx=4, pady=(0, 8))
        self.enemies.bind('<<ListboxSelect>>', self._pick_enemy)
        tk.Label(side, text='选中对象', bg='#22241d', fg=MUTED, anchor='w', font=(self.face, 10)).pack(fill='x', padx=12, pady=(10, 2))
        self._detail_label = tk.Label(side, textvariable=self.detail, bg='#22241d', fg=INK, wraplength=376, justify='left', anchor='nw', font=(self.face, 11))
        self._detail_label.pack(fill='x', padx=12, pady=(0, 12))

    def toggle_side(self):
        self._side_open = not self._side_open
        self._apply_side()

    def _apply_side(self):
        body = getattr(self, '_body', None)
        side = getattr(self, '_side', None)
        btn = getattr(self, '_side_btn', None)
        if body is None or side is None:
            return
        try:
            panes = [str(pane) for pane in body.panes()]
        except tk.TclError:
            panes = []
        shown = str(side) in panes
        if self._side_open and not shown:
            try:
                body.add(side, stretch='never', minsize=400)
            except tk.TclError:
                pass
            body.after_idle(self._place_side_sash)
        elif not self._side_open and shown:
            try:
                body.forget(side)
            except tk.TclError:
                pass
        if btn is not None:
            btn.config(text='折叠对手状态' if self._side_open else '展开对手状态')

    def _place_side_sash(self):
        body = getattr(self, '_body', None)
        side = getattr(self, '_side', None)
        if body is None or side is None or not self._side_open:
            return
        try:
            body.update_idletasks()
            width = body.winfo_width()
            if width > 280 and len(body.panes()) >= 2:
                body.sash_place(0, max(200, width - 400), 0)
        except tk.TclError:
            pass

    def _side_wrap(self, event=None):
        widget = event.widget if event is not None else getattr(self, '_side', None)
        if widget is None or widget is not getattr(self, '_side', None):
            return
        width = max(220, widget.winfo_width() - 24)
        for label in (getattr(self, '_brief_label', None), getattr(self, '_ops_hint', None),
                      getattr(self, '_war_label', None), getattr(self, '_detail_label', None)):
            if label is not None:
                label.configure(wraplength=width)

    def show_raid(self, plan, sim_cell=None, immediate=False):
        self.raid_on = bool(plan)
        if plan and sim_cell:
            plan = dict(plan)
            plan['sim_cell'] = tuple(sim_cell)
        elif plan:
            plan = dict(plan)
            if sim_cell is None:
                plan.pop('sim_cell', None)
        self.raid_plan = plan
        if plan and plan.get('brief'):
            self.city_hint.set(format_raid_brief(plan))
        if immediate:
            self.draw(refresh_view=False)
        else:
            self.request_draw()

    def _apply_scenario(self, state):
        try:
            from scenario_maps import file_for, identify_detail
            spec, source = identify_detail(state)
        except Exception:
            return
        if spec['id'] == self.scenario_id:
            return
        self.scenario_id = spec['id']
        self.scenario_name = spec['name']
        self.world = (spec['width'], spec['height'])
        self.center = (self.world[0] / 2, self.world[1] / 2)
        self.zoom = MIN_ZOOM
        self.terrain_error = ''
        try:
            if spec['id'] == 'china':
                self.lbm = shared_lbm()
                self.terrain = shared_terrain()
            else:
                overview = file_for(spec, 'overview')
                mbm = file_for(spec, 'mbm')
                self.lbm = Image.open(overview).convert('RGB') if overview else None
                self.terrain = Terrain(str(mbm), size=tuple(spec['pixel'])) if mbm else None
                if self.terrain is None:
                    self.terrain_error = '缺少 ' + spec['mbm']
        except (OSError, ValueError) as error:
            self.terrain = None
            self.terrain_error = str(error)
        how = {'memory': '内存网格', 'cities': '城名对照'}.get(source, '默认')
        self.status.set(f"当前剧本地图：{spec['name']} {spec['width']}×{spec['height']}（{how}）")

    def update_state(self, state, lists=True, immediate=True, refresh_view=None):
        self.state = state
        self._apply_scenario(state)
        if self.slim:
            self._refresh_view = False
            if immediate:
                self.draw(refresh_view=False)
            else:
                self.request_draw()
            return
        if lists and getattr(self, 'capitals', None) is not None:
            self.brief.set(opponent_brief(state))
            self._fill_enemies()
            self._fill_force_units()
            if self._ops_from_replay:
                self._fill_capitals()
                self._paint_force_ops(self._force_ledger)
            else:
                self._fill_force_ops_from_state()
        if self.selected:
            kind, row = self._selected_row()
            if row is None:
                self.selected = None
                self.detail.set('原对象已消失或标识不唯一。')
            else:
                self.detail.set(self._describe(kind, row))
        self._refresh_view = lists if refresh_view is None else refresh_view
        if immediate:
            self.draw(refresh_view=self._refresh_view)
        else:
            self.request_draw()

    def _command_text(self, item):
        bridge = str(ROOT / 'bridge')
        if bridge not in sys.path:
            sys.path.append(bridge)
        from replay_view import command_line_text
        return command_line_text(item)

    def set_force_commands(self, ledger, on_click=None):
        self._ops_from_replay = True
        self._force_ledger = list(ledger or [])
        self.on_force_op = on_click
        self._paint_force_ops(self._force_ledger)
        if self.state:
            self._fill_capitals()
            self._fill_force_units()

    def _fill_force_ops_from_state(self):
        bridge = str(ROOT / 'bridge')
        if bridge not in sys.path:
            sys.path.append(bridge)
        from replay_view import force_command_ledger, history_command_events
        history = (self.state or {}).get('history') or {}
        lords = ((self.state or {}).get('entities') or {}).get('lords') or []
        ledger = force_command_ledger(history_command_events(history), lords)
        self._force_ledger = ledger
        self._paint_force_ops(ledger)
        self._fill_capitals()

    def _visible_ledger(self, ledger):
        rows = list(ledger or [])
        if self.focus_force_id is None:
            return rows
        return [row for row in rows if row.get('owner') == self.focus_force_id]

    def _paint_force_ops(self, ledger):
        from state_history import short_quarter_label
        box = self.force_ops
        box.delete('1.0', 'end')
        rows = self._visible_ledger(ledger)
        if self.focus_force_id is None:
            box.insert('end', '点上方齐、周等势力后，这里只显示该国指令。\n', 'empty')
        if not rows:
            if self.focus_force_id is not None:
                name = next((lord.get('name') for lord in ((self.state or {}).get('entities') or {}).get('lords') or []
                             if lord.get('force_id') == self.focus_force_id), '该势力')
                box.insert('end', name + '\n', self._force_name_tag(self.focus_force_id))
                box.insert('end', '  尚无建设/训练/录用/出征/移动。无数据 ≠ 没有下令。\n', 'empty')
            return
        for block in rows:
            box.insert('end', (block.get('heading') or block.get('name') or '势力') + '\n',
                       self._force_name_tag(block.get('owner') or self.focus_force_id))
            quarters = block.get('quarters') or []
            if not quarters:
                box.insert('end', '  内政 —\n', 'empty')
                continue
            for account in reversed(quarters):
                box.insert('end', '  ' + short_quarter_label(account.get('label'), account.get('phase')) + '\n', 'quarter')
                civil = account.get('civil') or []
                if civil:
                    for item in civil:
                        self._bind_force_op(box, f"  内政  {self._command_text(item)}\n", item, 'civil')
                else:
                    box.insert('end', '  内政 —\n', 'empty')
                military = account.get('military') or []
                shown = military[-24:]
                skipped = len(military) - len(shown)
                if skipped:
                    box.insert('end', f'  军事 另有更早 {skipped} 条\n', 'empty')
                if shown:
                    for item in shown:
                        self._bind_force_op(box, f"  军事  {self._command_text(item)}\n", item, 'military')
                elif not skipped:
                    box.insert('end', '  军事 —\n', 'empty')
            box.insert('end', '\n')

    def _bind_force_op(self, box, line, item, style):
        start = box.index('end-1c')
        unique = 'op-' + start.replace('.', '-')
        box.insert('end', line, (style, item.get('evidence') or 'inferred', unique))
        box.tag_bind(unique, '<Button-1>', lambda _e=None, it=item: self._click_force_op(it))
        try:
            box.tag_bind(unique, '<Enter>', lambda _e=None: box.configure(cursor='hand2'))
            box.tag_bind(unique, '<Leave>', lambda _e=None: box.configure(cursor=''))
        except tk.TclError:
            pass

    def _click_force_op(self, item):
        if self.on_force_op:
            self.on_force_op(item)
            return
        target = (item or {}).get('target') or {}
        city_id = target.get('city_id')
        if city_id is None:
            return
        for kind, row in live_objects(self.state or {}):
            if kind == '城关' and row.get('city_id') == city_id:
                self.selected = object_key(kind, row)
                xy = world_xy(row)
                self.center = (xy[0] + 0.5, xy[1] + 0.5)
                self.detail.set(self._describe(kind, row))
                self.draw()
                return

    def _fill_capitals(self):
        self.capital_keys = []
        self.capital_force_ids = []
        self.capitals.delete(0, 'end')
        if not self.state:
            return
        pid = player_id(self.state)
        marks = sorted(capital_marks(self.state), key=lambda m: m.get('force_id') != pid)
        for mark in marks:
            city = next((row for kind, row in live_objects(self.state) if kind == '城关' and row.get('city_id') == mark['city_id']), None)
            if city is None:
                continue
            self.capital_keys.append(object_key('城关', city))
            self.capital_force_ids.append(mark.get('force_id'))
            x, y = mark['world_xy']
            own = mark.get('force_id') == pid and pid is not None
            prefix = '★ ' if own else ''
            self.capitals.insert('end', f"{prefix}{mark['force_name']}  {mark['city_name']}  ({x},{y})")
            ink = self._rgb(mark.get('force_id'))
            style = {'foreground': ink, 'selectforeground': ink}
            if own:
                style.update(background='#4a3d18', selectbackground='#6a5520')
            self.capitals.itemconfig(self.capitals.size() - 1, **style)

    def go_city(self, _=None):
        query = (self.city_query.get() or '').strip()
        point = parse_map_point(query)
        if point:
            self.center = clamp_center((point[0] + (0.5 if point[0] == int(point[0]) else 0),
                                       point[1] + (0.5 if point[1] == int(point[1]) else 0)))
            self.zoom = max(self.zoom, 4.0)
            self.search_mark = {'name': f'{int(point[0])},{int(point[1])}', 'world_xy': (int(point[0]), int(point[1]))}
            self.city_hint.set(f'已定位坐标 ({self.search_mark["world_xy"][0]},{self.search_mark["world_xy"][1]})')
            self.draw()
            return 'break'
        if query != self._search_text:
            self._search_hits = search_city_places(query, self.state)
            self._search_text = query
            self._search_index = 0
        if not self._search_hits:
            self.search_mark = None
            self.city_hint.set('没有匹配的城池。可输入城名、城ID，或 52,124')
            return 'break'
        hit = self._search_hits[self._search_index % len(self._search_hits)]
        self._search_index += 1
        x, y = hit['world_xy']
        self.center = (x + 0.5, y + 0.5)
        self.zoom = max(self.zoom, 4.0)
        self.search_mark = hit
        live = next((row for kind, row in live_objects(self.state or {}) if kind == '城关' and (
            (type(hit.get('city_id')) is int and row.get('city_id') == hit['city_id']) or row.get('name') == hit['name']
        )), None)
        if live:
            self.selected = object_key('城关', live)
            self.detail.set(self._describe('城关', live))
        extra = f' · {self._search_index}/{len(self._search_hits)}，回车下一条' if len(self._search_hits) > 1 else ''
        self.city_hint.set(f'{hit["name"]}  ({x},{y}){extra}')
        self.draw()
        return 'break'

    def toggle_raid(self):
        if self.raid_on and self.raid_plan:
            self.raid_on = False
            self.raid_plan = None
            self.city_hint.set('已关掉偷袭路线')
            self.draw()
            return
        self.raid_on = True
        self._compute_raid(show_card=True)

    def _compute_raid(self, show_card=True, draw=True):
        kind, row = self._selected_row()
        origin, origin_unit, dest_row = resolve_raid_endpoints(
            self.state, kind, row, self.focus_force_id,
        )
        plan = plan_stealth_raid(
            self.state, origin, dest_row, self.terrain, origin_unit=origin_unit,
        )
        self.raid_plan = plan
        self.city_hint.set(format_raid_brief(plan))
        if plan.get('ok') and plan.get('staging'):
            sx, sy = plan['staging']
            self.center = (sx + 0.5, sy + 0.5)
            self.zoom = max(self.zoom, 3.0)
        if show_card:
            self._show_raid_card(plan)
        if draw:
            self.draw()

    def _show_raid_card(self, plan):
        title = '偷袭主城路线' if plan.get('ok') else '偷袭路线算不出'
        body = plan.get('detail') or plan.get('error') or format_raid_brief(plan)
        win = getattr(self, '_raid_card', None)
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self)
            win.title('偷袭主城')
            win.configure(bg='#22241d')
            win.transient(self.winfo_toplevel())
            self._raid_card = win
            self._raid_card_title = tk.Label(
                win, bg='#22241d', fg='#ffe9a3', font=(self.face, 14, 'bold'), anchor='w',
            )
            self._raid_card_title.pack(fill='x', padx=14, pady=(12, 4))
            self._raid_card_body = tk.Label(
                win, bg='#22241d', fg='#efe7cf', justify='left', anchor='nw', font=(self.face, 11),
            )
            self._raid_card_body.pack(fill='both', expand=True, padx=14, pady=(0, 10))
            tk.Button(
                win, text='关闭', command=win.destroy,
                bg='#e7e0c9', fg='#302c22', activeforeground='#302c22',
            ).pack(pady=(0, 12))
            win.bind('<Escape>', lambda _e=None: win.destroy())
        self._raid_card_title.config(text=title)
        self._raid_card_body.config(text=body)
        win.deiconify()
        win.lift()

    def _pick_capital(self, _=None):
        selection = self.capitals.curselection()
        if not selection:
            return
        index = selection[0]
        self.selected = self.capital_keys[index]
        if index < len(self.capital_force_ids):
            self.focus_force_id = self.capital_force_ids[index]
        self._paint_force_ops(self._force_ledger)
        self._fill_force_units()
        try:
            self.side_tabs.select(0)
        except tk.TclError:
            pass
        kind, row = self._selected_row()
        if row is None:
            return
        xy = world_xy(row)
        self.center = (xy[0] + 0.5, xy[1] + 0.5)
        self.zoom = max(self.zoom, 4.0)
        self.detail.set(self._describe(kind, row))
        if self.raid_on and not self.slim:
            self._compute_raid(show_card=False, draw=False)
        self.draw()

    def _visible_box(self, w, h):
        return box_from_corners((
            self._world_at(0, 0),
            self._world_at(w, 0),
            self._world_at(0, h),
            self._world_at(w, h),
        ))

    def _refresh_view_units(self, w, h):
        if self.slim or getattr(self, 'view_units', None) is None:
            return
        from officer_sortie import AMBUSH_INK_DARK, unit_has_ambush
        rows = []
        if not self.layers['部队'].get():
            sig = ('hidden',)
            lines, keys, hint = ['已关闭部队层'], [], '勾选上方「部队」后列出本视野'
        elif not self.state:
            sig = ('empty',)
            lines, keys, hint = ['尚无采集'], [], '进入对局后列出覆盖范围内部队'
        else:
            box = self._visible_box(w, h)
            rows = sort_view_units(self.state, units_in_view(self.state, box, self.war_only.get()), self.center)
            keys = [object_key('部队', row) for row in rows]
            lines = [view_unit_line(self.state, row) for row in rows] or ['本视野无部队']
            hint = f'覆盖 {len(rows)} 支' + (' · 只看交战/我方' if self.war_only.get() else '')
            sig = (tuple(keys), tuple(lines), hint, tuple(unit_has_ambush(self.state, row) for row in rows))
        if sig == self._view_sig:
            return
        self._view_sig = sig
        self.view_unit_keys = keys
        self.view_hint.set(hint)
        self.view_units.delete(0, 'end')
        for index, line in enumerate(lines):
            self.view_units.insert('end', line)
            if index < len(rows):
                row = rows[index]
                ink = AMBUSH_INK_DARK if unit_has_ambush(self.state, row) else self._rgb(row.get('owner_raw'))
                self.view_units.itemconfig(index, fg=ink)

    def _pick_view_unit(self, _=None):
        selection = self.view_units.curselection()
        if not selection or selection[0] >= len(self.view_unit_keys):
            return
        self.selected = self.view_unit_keys[selection[0]]
        kind, row = self._selected_row()
        if row is None:
            return
        xy = world_xy(row)
        self.center = (xy[0] + 0.5, xy[1] + 0.5)
        self.zoom = max(self.zoom, 6.0)
        self.detail.set(self._describe(kind, row))
        self._open_unit_tour(row)
        self.draw()

    def _fill_force_units(self):
        from officer_sortie import AMBUSH_INK_DARK, unit_has_ambush
        self.force_units.delete(0, 'end')
        self.force_unit_keys = []
        if self.focus_force_id is None:
            self.force_unit_hint.set('点上方势力后列出该国全部出征部队')
            self.force_units.insert('end', '尚未选择势力')
            return
        name = next((lord.get('name') for lord in ((self.state or {}).get('entities') or {}).get('lords') or []
                     if lord.get('force_id') == self.focus_force_id), '该势力')
        rows = [row for kind, row in live_objects(self.state or {})
                if kind == '部队' and row.get('owner_raw') == self.focus_force_id]
        self.force_unit_hint.set(f'{name}  {len(rows)} 支出征部队')
        if not rows:
            self.force_units.insert('end', f'{name} 本帧无出征部队')
            return
        for row in rows:
            self.force_unit_keys.append(object_key('部队', row))
            self.force_units.insert('end', view_unit_line(self.state, row))
            ink = AMBUSH_INK_DARK if unit_has_ambush(self.state, row) else self._rgb(row.get('owner_raw'))
            self.force_units.itemconfig(self.force_units.size() - 1, fg=ink)

    def _pick_force_unit(self, _=None):
        selection = self.force_units.curselection()
        if not selection or selection[0] >= len(self.force_unit_keys):
            return
        self.selected = self.force_unit_keys[selection[0]]
        kind, row = self._selected_row()
        if row is None:
            return
        xy = world_xy(row)
        self.center = (xy[0] + 0.5, xy[1] + 0.5)
        self.zoom = max(self.zoom, 6.0)
        self.detail.set(self._describe(kind, row))
        self._open_unit_tour(row)
        self.draw()

    def _fill_enemies(self):
        from force_strength import force_attack_rows
        from officer_sortie import AMBUSH_INK_DARK, unit_has_ambush
        self.enemy_keys = []
        self.enemies.delete(0, 'end')
        if not self.state:
            self.war_power.set('各势力总战力按出征部队攻击指数相加，不是实伤。')
            return
        lines = [row['line'] for row in force_attack_rows(self.state)]
        self.war_power.set('各势力总战力（出征部队攻击指数之和，不是实伤）\n' + ('\n'.join(lines) if lines else '尚无势力'))
        for kind, row in live_objects(self.state):
            if kind != '部队' or not at_war(self.state, row.get('owner_raw')):
                continue
            self.enemy_keys.append(object_key(kind, row))
            self.enemies.insert('end', object_label(self.state, kind, row))
            ink = AMBUSH_INK_DARK if unit_has_ambush(self.state, row) else self._rgb(row.get('owner_raw'))
            self.enemies.itemconfig(self.enemies.size() - 1, fg=ink)

    def _pick_enemy(self, _=None):
        selection = self.enemies.curselection()
        if not selection:
            return
        self.selected = self.enemy_keys[selection[0]]
        kind, row = self._selected_row()
        if row is None:
            return
        xy = world_xy(row)
        self.center = (xy[0] + 0.5, xy[1] + 0.5)
        self.zoom = max(self.zoom, 6.0)
        self.detail.set(self._describe(kind, row))
        self._open_unit_tour(row)
        self.draw()

    def _open_unit_tour(self, row):
        if self.slim or not row:
            return
        callback = getattr(self, 'on_tour_unit', None)
        if callable(callback):
            callback(row)
            return
        from force_unit_pager import show_force_unit_pager
        show_force_unit_pager(self.winfo_toplevel(), self.state, row)

    def _selected_row(self):
        if not self.selected or not self.state:
            return None, None
        matches = [(kind, row) for kind, row in live_objects(self.state) if object_key(kind, row) == self.selected]
        return matches[0] if len(matches) == 1 else (None, None)

    def _describe(self, kind, row):
        xy = world_xy(row)
        owner = next((force.get('name') for force in self.state.get('entities', {}).get('lords', []) if force.get('force_id') == row.get('owner_raw')), '未分配')
        war = '交战' if at_war(self.state, row.get('owner_raw')) else ('我方' if row.get('owner_raw') == player_id(self.state) else '其他')
        text = f'{kind} · {object_label(self.state, kind, row)}\n坐标 {xy} · {owner} · {war}'
        if kind == '城关':
            text += f"\n{city_marker_text(row)} · 人口 {fmt(row.get('population'))} · 开发 {fmt(row.get('development'))} · 商业 {fmt(row.get('commerce'))}"
            text += f'\n{city_card_text(self.state, row)}'
            if is_capital(self.state, row):
                text += f'\n首都位置 ({xy[0]},{xy[1]}) · {owner}'
        if kind == '部队':
            text += '\n'+memory_line(row)
            if displays_attack(row):
                text += f" · 攻城 {fmt(row.get('target_attack_building'))}"
            text += '\n'+special_details(self.state,row)
            text += f'\n{move_brief(self.state, row)}'
        if kind == '建筑':
            text += f"\n对象ID {fmt(row.get('object_id_candidate'))} · 建成状态/等级尚未解析"
        if kind == '陷阱':
            text += ' · 独立只读对象；所属城市字段尚待核定'
        return text

    def _show_city_card(self, row):
        if not row:
            return
        name = object_label(self.state, '城关', row)
        body = self._describe('城关', row)
        win = getattr(self, '_city_card', None)
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self)
            win.title('城池资料')
            win.configure(bg='#22241d')
            win.transient(self.winfo_toplevel())
            self._city_card = win
            self._city_card_title = tk.Label(win, bg='#22241d', fg='#ffe9a3', font=(self.face, 14, 'bold'), anchor='w')
            self._city_card_title.pack(fill='x', padx=14, pady=(12, 4))
            self._city_card_body = tk.Label(win, bg='#22241d', fg='#efe7cf', justify='left', anchor='nw', font=(self.face, 11))
            self._city_card_body.pack(fill='both', expand=True, padx=14, pady=(0, 10))
            tk.Button(
                win, text='关闭', command=win.destroy,
                bg='#e7e0c9', fg='#302c22', activeforeground='#302c22',
            ).pack(pady=(0, 12))
            win.bind('<Escape>', lambda _e=None: win.destroy())
        self._city_card_title.config(text=name)
        self._city_card_body.config(text=body)
        win.deiconify()
        win.lift()

    def request_draw(self):
        if getattr(self, '_draw_job', None):
            return
        self._draw_job = self.after(16, self._flush_draw)

    def _flush_draw(self):
        self._draw_job = None
        self.draw(refresh_view=getattr(self, '_refresh_view', True))

    def fit(self):
        self.zoom = MIN_ZOOM
        self.center = DEFAULT_CENTER
        self.request_draw()

    def _sync_opponents(self):
        box = getattr(self, 'opponent_box', None)
        if box is None:
            return
        lords = ((self.state or {}).get('entities') or {}).get('lords') or []
        options = ['不圈部队']
        ids = {}
        for lord in lords:
            name = lord.get('name') or '?'
            label = name if name not in ids else '%s#%s' % (name, lord.get('force_id'))
            options.append(label)
            ids[label] = lord.get('force_id')
        self.opponent_ids = ids
        if tuple(box.cget('values')) != tuple(options):
            box.configure(values=options)
        if self.opponent.get() not in options:
            self.opponent.set('不圈部队')

    def _keep_inside(self):
        width = self.canvas.winfo_width() if getattr(self, 'canvas', None) else 1
        height = self.canvas.winfo_height() if getattr(self, 'canvas', None) else 1
        if width < 8 or height < 8:
            return
        size = getattr(self.terrain, 'size', None)
        self.zoom, self.center = clamp_mbm_view(self.center, self.zoom, width, height, size, self.world)

    def pan(self, dx, dy):
        self.center = move_center(self.center, dx, dy, max(0.4, 10 / self.zoom), self.world, 0.5)
        self._keep_inside()
        self.request_draw()

    def change_zoom(self, delta, screen=None):
        old = self.zoom
        before = self._world_at(*screen) if screen is not None else None
        self.zoom = clamp_zoom(self.zoom + delta)
        if before is not None and self.zoom != old:
            after = self._world_at(*screen)
            self.center = clamp_center((
                self.center[0] + (before[0] - after[0]),
                self.center[1] + (before[1] - after[1]),
            ), self.world)
        self._keep_inside()
        self.request_draw()

    def _wheel(self, event, sx=None, sy=None):
        from map_navigation import wheel_direction_from_event
        direction = wheel_direction_from_event(event)
        if not direction:
            return
        now = time.monotonic()
        if now - getattr(self, '_wheel_at', 0) < 0.04:
            return
        self._wheel_at = now
        if sx is None:
            sx, sy = getattr(event, 'x', 0), getattr(event, 'y', 0)
        self.change_zoom(0.5 * direction, (sx, sy))

    def _wheel_delta(self, direction):
        self.change_zoom(0.5 * direction)

    def _press(self, event):
        self.canvas.focus_set()
        self.drag = (event.x, event.y, self.center)

    def _drag(self, event):
        if not self.drag:
            return
        x0, y0, origin = self.drag
        width = max(1, self.canvas.winfo_width())
        cells = 28 / self.zoom if layer_for_zoom(self.zoom) == 'mbm' else self.world[0] / self.zoom
        self.center = clamp_center((
            origin[0] - (event.x - x0) / width * cells,
            origin[1] - (event.y - y0) / max(1, self.canvas.winfo_height()) * (cells * self.world[1] / self.world[0]),
        ), self.world)
        self.request_draw()

    def _raid_click(self, event):
        hit = self._hit(event.x, event.y)
        if hit:
            self.selected = hit
            kind, row = self._selected_row()
            if kind == '部队' and row and row.get('owner_raw') == player_id(self.state) and callable(self.on_pick_unit):
                self.on_pick_unit(row)
                return
            if kind == '城关' and row and callable(self.on_pick_origin):
                self.on_pick_origin(row)
                return
        if not callable(self.on_pick_cell):
            return
        point = self._world_at(event.x, event.y)
        cell = (int(point[0]), int(point[1]))
        if 0 <= cell[0] < self.world[0] and 0 <= cell[1] < self.world[1]:
            self.on_pick_cell(cell)

    def _release(self, event):
        start = self.drag
        self.drag = None
        if not start or abs(event.x - start[0]) + abs(event.y - start[1]) > 8:
            return
        if self.slim:
            self._raid_click(event)
            return
        hit = self._hit(event.x, event.y)
        if hit:
            self.selected = hit
            kind, row = self._selected_row()
            if row:
                if kind == '城关' and callable(self.on_pick_origin):
                    # 2026-10-19: 外部指令面板的「在地圖上選城池」掛在此處（單擊城池即回傳）。
                    self.on_pick_origin(row)
                self.detail.set(self._describe(kind, row))
            self.draw()
            return
        point = self._world_at(event.x, event.y)
        for kind, row in live_objects(self.state) if self.state else []:
            if kind != '城关':
                continue
            xy = world_xy(row)
            if max(abs(xy[0] + 0.5 - point[0]), abs(xy[1] + 0.5 - point[1])) <= 1.2:
                self.center = (xy[0] + 0.5, xy[1] + 0.5)
                self.zoom = max(self.zoom, 6.0)
                self.selected = object_key(kind, row)
                self.detail.set(self._describe(kind, row))
                self.draw()
                return

    def _double(self, event):
        if self.slim:
            hit = self._hit(event.x, event.y)
            if not hit:
                return
            self.selected = hit
            kind, row = self._selected_row()
            if kind == '城关' and row and callable(self.on_pick_origin):
                self.on_pick_origin(row)
            return
        hit = self._hit(event.x, event.y)
        if not hit:
            return
        self.selected = hit
        kind, row = self._selected_row()
        if kind == '城关' and row:
            self._show_city_card(row)
        elif kind == '部队' and row:
            self._open_unit_tour(row)

    def _hit(self, x, y):
        limit = max(28, sprite_size('城关', self.zoom) // 2)
        nearby = [(px, py, key) for px, py, key in self.hits if (px - x) ** 2 + (py - y) ** 2 <= limit ** 2]
        if not nearby:
            return None
        nearby.sort(key=lambda item: (item[0] - x) ** 2 + (item[1] - y) ** 2)
        keys = [item[2] for item in nearby]
        return keys[(keys.index(self.selected) + 1) % len(keys)] if self.selected in keys else keys[0]

    def _world_at(self, sx, sy):
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        if layer_for_zoom(self.zoom) == 'mbm':
            box, scale = mbm_view(self.center, self.zoom, w, h)
            px, py = box[0] + sx / scale, box[1] + sy / scale
            best, best_d = self.center, 10 ** 9
            for y in range(max(0, int(self.center[1]) - 8), min(self.world[1], int(self.center[1]) + 9)):
                for x in range(max(0, int(self.center[0]) - 8), min(self.world[0], int(self.center[0]) + 9)):
                    tx, ty = world_pixel(x, y)
                    distance = (tx - px) ** 2 + (ty - py) ** 2
                    if distance < best_d:
                        best, best_d = (x + 0.5, y + 0.5), distance
            return best
        ox, oy, vw, vh = map_viewport(w, h)
        return (
            self.center[0] + (sx - w / 2) / vw * self.world[0] / self.zoom,
            self.center[1] + (sy - h / 2) / vh * self.world[1] / self.zoom,
        )

    def _project(self, x, y, w, h, layer):
        if layer == 'lbm':
            ox, oy, vw, vh = map_viewport(w, h)
            return (
                w / 2 + (x + 0.5 - self.center[0]) * vw * self.zoom / self.world[0],
                h / 2 + (y + 0.5 - self.center[1]) * vh * self.zoom / self.world[1],
            )
        box, scale = mbm_view(self.center, self.zoom, w, h)
        px, py = world_pixel(x, y)
        return ((px - box[0]) * scale, (py - box[1]) * scale)

    def _overlay_fingerprint(self):
        ents = (self.state or {}).get('entities') or {}
        units = tuple(
            (row.get('unit_id'), tuple((row.get('world_xy_raw') or [None, None])[:2]),
             row.get('owner_raw'), row.get('unit_kind'), row.get('on_water'),
             row.get('morale'), row.get('native_attack_index'),
             row.get('native_attack_index_full_morale'), row.get('effective_skill_mask'),
             row.get('target_attack_unit'), row.get('attack_model'),
             row.get('unit_state_flags_raw'), row.get('native_order_type_raw'),
             row.get('native_order_payload_raw'), tuple(row.get('general_ids') or ()))
            for row in ents.get('field_units') or []
        )
        assigned = {gid for row in ents.get('field_units') or [] for gid in row.get('general_ids') or []}
        generals = tuple((g.get('general_id_raw'), g.get('name'), g.get('owner_raw'),
                          g.get('status_code'), (g.get('attributes') or {}).get('intel'),
                          g.get('skill_mask_raw'), g.get('combat_modifier_flags_word'), g.get('raw_hex'))
                         for g in ents.get('generals') or [] if g.get('general_id_raw') in assigned)
        relations = tuple((g.get('force_id'), tuple(g.get('diplomacy_relations') or ()))
                          for g in ents.get('lords') or [])
        cities = tuple(
            (row.get('city_id'), row.get('owner_raw'), tuple((row.get('world_xy_raw') or [None, None])[:2]))
            for row in ents.get('cities_and_barriers') or []
        )
        layers = tuple((key, bool(var.get())) for key, var in self.layers.items())
        war = bool(self.war_only.get()) if hasattr(self, 'war_only') else False
        mark = None
        if self.search_mark:
            mark = (self.search_mark.get('name'), tuple(self.search_mark.get('world_xy') or ()))
        produce = tuple((kind, self._produce_threshold(kind)) for kind, _label, _color in PRODUCE_RINGS)
        produce += ((SCORE_RING[0], self._produce_threshold(SCORE_RING[0])),)
        raid = None
        if self.raid_on and self.raid_plan:
            raid = (
                bool(self.raid_plan.get('ok')),
                tuple(self.raid_plan.get('full_path') or ()),
                tuple(self.raid_plan.get('staging') or ()),
                tuple(self.raid_plan.get('ring') or ()),
                tuple((item.get('cell') if isinstance(item, dict) else item) for item in (self.raid_plan.get('move_cells') or ())),
                self.raid_plan.get('arrive_calendar'),
                tuple(self.raid_plan.get('sim_cell') or ()),
                tuple(self.raid_plan.get('pending') or ()),
                self.raid_plan.get('sim_kind'),
            )
        return (units, generals, relations, ((self.state or {}).get('combat_rules') or {}).get('flags_raw'),
                cities, layers, war, self.selected, mark, produce, raid)

    def draw(self, refresh_view=True):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 8:
            w = tk_pixels(c, c.cget('width'))
        if h < 8:
            h = tk_pixels(c, c.cget('height'))
        if w < 8 or h < 8:
            return
        self._keep_inside()
        self._sync_opponents()
        layer = layer_for_zoom(self.zoom)
        detail = '滚轮放大看路线格' if self.slim else (
            '远景只显示城池和军队' if self.zoom < DETAIL_ZOOM else '菱格视野 都5/城3/关1 · 点城看生命值与士气 · 点部队看前进格'
        )
        self.layer.set(f'{LAYER_HINT[layer]} · 倍率 {self.zoom:g} · WASD 移动 · 滚轮或 -/= 缩放 · {detail}')
        ranges = None
        if layer == 'mbm':
            if self.slim and self.raid_on:
                ranges = self._raid_overlay_items()
            elif not self.slim:
                ranges = self._range_overlay_items()
        terrain_key = (
            layer, round(self.center[0], 4), round(self.center[1], 4), float(self.zoom), w, h,
            tuple((item['cell'], item['rgb'], item.get('alpha')) for item in (ranges or ())),
            bool(self.war_only.get()) if hasattr(self, 'war_only') else False,
        )
        reuse = terrain_key == getattr(self, '_terrain_key', None) and self.photo is not None
        overlay_key = self._overlay_fingerprint()
        overlay_same = overlay_key == getattr(self, '_overlay_key', None)
        extra = getattr(self, 'after_draw', None)
        if reuse and overlay_same:
            if refresh_view:
                self._refresh_view_units(w, h)
            if extra:
                c.delete('replay-track')
                extra(w, h, layer)
            raise_label(c, getattr(self, 'unit_labels', {}).get(self.selected))
            return
        if reuse:
            c.delete('ov')
            c.delete('replay-track')
        else:
            c.delete('all')
            if layer == 'mbm' and self.terrain:
                box, scale = mbm_view(self.center, self.zoom, w, h)
                view = paint_mbm_vision(self.terrain, box, w, h, ranges)
                self.photo = ImageTk.PhotoImage(view, master=c)
                self._terrain_key = terrain_key
                c.create_image(0, 0, image=self.photo, anchor='nw', tags='terrain')
            elif self.lbm is not None:
                ox, oy, vw, vh = map_viewport(w, h)
                dx, dy = self.world[0] / self.zoom / 2, self.world[1] / self.zoom / 2
                sx, sy = self.lbm.width / self.world[0], self.lbm.height / self.world[1]
                box = ((self.center[0] - dx) * sx, (self.center[1] - dy) * sy, (self.center[0] + dx) * sx, (self.center[1] + dy) * sy)
                view = self.lbm.transform((max(1, round(vw)), max(1, round(vh))), Image.Transform.EXTENT, box, resample=Image.Resampling.BILINEAR)
                if not self.slim:
                    view = overlay_force_diamonds(view, self._city_vision_diamonds(w, h, layer, None, None), alpha=56)
                self.photo = ImageTk.PhotoImage(view, master=c)
                self._terrain_key = terrain_key
                c.create_image(ox, oy, image=self.photo, anchor='nw', tags='terrain')
            else:
                c.create_text(w / 2, 24, text='底图不可用：' + (self.terrain_error or '缺少 SanInet.lbm / SanInet.mbm'), fill=INK)
        self.hits = []
        self.unit_labels = {}
        if not self.slim:
            self._draw_supply(w, h, layer)
        self._draw_objects(w, h, layer)
        if not self.slim:
            self._draw_produce_rings(w, h, layer)
        self._draw_capitals(w, h, layer)
        if not self.slim:
            self._draw_search_mark(w, h, layer)
        self._draw_raid_route(w, h, layer)
        self._overlay_key = overlay_key
        if refresh_view:
            self._refresh_view_units(w, h)
        if extra and not self.slim:
            extra(w, h, layer)
        raise_label(c, self.unit_labels.get(self.selected))

    def _rgb(self, owner):
        return '#' + ''.join(f'{value:02x}' for value in state_force_rgb(self.state, owner))

    def _force_name_tag(self, owner):
        tag = 'force' if owner is None else f'force_{owner}'
        self.force_ops.tag_configure(tag, foreground=self._rgb(owner), font=(self.face, 11, 'bold'))
        return tag

    def _project_mbm(self, px, py, w, h, layer, box=None, scale=None):
        if layer == 'mbm':
            if box is None:
                box, scale = mbm_view(self.center, self.zoom, w, h)
            return ((px - box[0]) * scale, (py - box[1]) * scale)
        wx, wy = mbm_to_world(px, py)
        return self._project(wx, wy, w, h, layer)

    def _city_vision_items(self):
        if not self.state or not self.layers['城关'].get():
            return []
        sig = (
            (self.state or {}).get('snapshot_id'),
            bool(self.war_only.get()) if hasattr(self, 'war_only') else False,
        )
        if sig == getattr(self, '_vision_sig', None) and hasattr(self, '_vision_items'):
            return self._vision_items
        items = []
        for item in vision_overlay_cells(self.state, self.war_only.get()):
            rgb = state_force_rgb(self.state, item.get('owner_raw'))
            items.append({'cell': item['cell'], 'rgb': rgb, 'center': item.get('center')})
        self._vision_sig = sig
        self._vision_items = items
        return items

    def _move_overlay_items(self):
        # 跟游戏移动预览同款浅蓝行走格；与所在城视野同色势力时再浅一档。
        kind, row = self._selected_row()
        if kind != '部队' or row is None or not self.layers['部队'].get():
            return []
        sig = ((self.state or {}).get('snapshot_id'), row.get('unit_id'), world_xy(row), row.get('unit_kind'), row.get('size_index'))
        if sig == getattr(self, '_move_sig', None) and hasattr(self, '_move_items'):
            return self._move_items
        items = []
        for item in move_overlay_cells(self.state, row, self.terrain):
            same = bool(item.get('same_as_city'))
            items.append({
                'cell': item['cell'],
                'rgb': (80, 185, 230) if same else (50, 165, 220),
                'center': item.get('center'),
                'alpha': 140 if same else 160,
                'edge': (30, 120, 195, 240),
            })
        self._move_sig = sig
        self._move_items = items
        return items

    def _raid_overlay_items(self):
        """Same cyan rhombus tiles as the game move preview / city sortie ring."""
        plan = self.raid_plan if self.raid_on else None
        if not plan:
            return []
        pending = tuple(plan.get('pending') or ())
        items = []
        move = plan.get('move_cells') or []
        if move:
            for row in move:
                if isinstance(row, dict):
                    cell = tuple(row.get('cell') or ())
                    same = bool(row.get('same_as_city'))
                else:
                    cell = (int(row[0]), int(row[1]))
                    same = False
                if len(cell) != 2:
                    continue
                items.append({
                    'cell': cell,
                    'rgb': (80, 185, 230) if same else (50, 165, 220),
                    'alpha': 140 if same else 160,
                    'edge': (30, 120, 195, 240),
                })
        else:
            for cell in plan.get('ring') or []:
                items.append({
                    'cell': (int(cell[0]), int(cell[1])),
                    'rgb': (50, 165, 220),
                    'alpha': 160,
                    'edge': (30, 120, 195, 240),
                })
        if pending:
            for item in items:
                if tuple(item['cell']) == pending:
                    item['rgb'] = (255, 214, 90)
                    item['alpha'] = 150
                    item['edge'] = (230, 180, 40, 250)
                    break
        return items

    def _range_overlay_items(self):
        return list(self._city_vision_items()) + self._move_overlay_items()

    def _city_vision_diamonds(self, w, h, layer, box, scale):
        if layer == 'mbm':
            return []
        diamonds = []
        for item in self._range_overlay_items():
            points = [self._project_mbm(px, py, w, h, layer, box, scale) for px, py in cell_diamond(*item['cell'])]
            ox, oy, vw, vh = map_viewport(w, h)
            points = [(x - ox, y - oy) for x, y in points]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            if max(xs) < -8 or min(xs) > w + 8 or max(ys) < -8 or min(ys) > h + 8:
                continue
            diamonds.append({
                'points': points, 'rgb': item['rgb'], 'center': item.get('center'),
                'alpha': item.get('alpha'),
            })
        return diamonds

    def _draw_supply(self, w, h, layer):
        if not self.state or not self.layers['补给线'].get():
            return
        box = scale = None
        if layer == 'mbm':
            box, scale = mbm_view(self.center, self.zoom, w, h)
        width = 3 if layer == 'lbm' else max(3, int(self.zoom * 0.45))
        for line in supply_lines(self.state):
            path = path_for_layer(line['path'], layer, self.zoom)
            points = [self._project_mbm(px, py, w, h, layer, box, scale) for px, py in path]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            if max(xs) < -40 or min(xs) > w + 40 or max(ys) < -40 or min(ys) > h + 40:
                continue
            color = self._rgb(line['owner_raw']) if line['same_owner'] else '#f4efe2'
            stroke = width if line['same_owner'] else max(1, width - 1)
            flat = [value for point in points for value in point]
            self.canvas.create_line(*flat, fill='#2a2c24', width=stroke + 2, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags='ov')
            self.canvas.create_line(*flat, fill=color, width=stroke, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags='ov')

    def _draw_raid_route(self, w, h, layer):
        plan = self.raid_plan if self.raid_on else None
        if not plan:
            return
        ring = plan.get('ring') or []
        move = plan.get('move_cells') or []
        if not plan.get('ok') and not ring and not move and not plan.get('sim_cell'):
            return
        hidden = plan.get('hidden_path') or []
        dash = plan.get('dash_path') or []
        width = 3 if layer == 'lbm' else max(3, int(self.zoom * 0.5))

        def stroke(cells, color):
            if len(cells) < 2:
                return
            points = [self._project(x, y, w, h, layer) for x, y in cells]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            if max(xs) < -40 or min(xs) > w + 40 or max(ys) < -40 or min(ys) > h + 40:
                return
            flat = [value for point in points for value in point]
            self.canvas.create_line(
                *flat, fill='#2a2c24', width=width + 2, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags='ov',
            )
            self.canvas.create_line(
                *flat, fill=color, width=width, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags='ov',
            )

        stroke(hidden, '#d4a017')
        stroke(dash, '#ffe27a')
        staging = plan.get('staging')
        if staging:
            x, y = self._project(*staging, w, h, layer)
            if -80 <= x <= w + 80 and -80 <= y <= h + 80:
                self.canvas.create_oval(
                    x - 10, y - 10, x + 10, y + 10, outline='#ffe27a', width=2, tags='ov',
                )
                self.canvas.create_text(
                    x, y - 18, text='集结', fill='#ffe27a', font=(self.face, 10, 'bold'), tags='ov',
                )
        dest = plan.get('dest')
        if dest:
            x, y = self._project(*dest, w, h, layer)
            if -80 <= x <= w + 80 and -80 <= y <= h + 80:
                self.canvas.create_text(
                    x, y + 20, text='偷袭', fill='#ffe27a', font=(self.face, 10, 'bold'), tags='ov',
                )
        sim = plan.get('sim_cell')
        if sim:
            x, y = self._project(*sim, w, h, layer)
            if -80 <= x <= w + 80 and -80 <= y <= h + 80:
                scale = mbm_view(self.center, self.zoom, w, h)[1] if layer == 'mbm' else None
                size = sprite_size('部队', self.zoom, scale)
                kind = plan.get('sim_kind') or '骑兵'
                row = {
                    'unit_kind': SPRITE_KIND.get(kind, kind),
                    'owner_raw': player_id(self.state),
                    'world_xy_raw': list(sim),
                    'size_index': 0,
                }
                sprite = self.sprites.image(row, size, self.state) if self.sprites else None
                if sprite:
                    self.canvas.create_image(x, y - 4, image=sprite, tags='ov')
                else:
                    color = self._rgb(row.get('owner_raw'))
                    self.canvas.create_polygon(
                        x, y - 12, x - 10, y + 6, x + 10, y + 6,
                        fill=color, outline='#1d2418', tags='ov',
                    )
                flag = self.sprites.flag(self.state, row.get('owner_raw'), max(14, size // 2)) if self.sprites else None
                if flag:
                    self.canvas.create_image(x + size // 2 + 4, y - size // 2, image=flag, tags='ov')
        for index, cell in enumerate(plan.get('cavalry_turn_cells') or []):
            x, y = self._project(*cell, w, h, layer)
            if not (-40 <= x <= w + 40 and -40 <= y <= h + 40):
                continue
            self.canvas.create_text(
                x + 12, y - 8, text=str(index + 1),
                fill='#fff6da', font=(self.face, 9, 'bold'), tags='ov',
            )

    def _draw_search_mark(self, w, h, layer):
        mark = self.search_mark
        if not mark:
            return
        x, y = self._project(*mark['world_xy'], w, h, layer)
        if not (-80 <= x <= w + 80 and -80 <= y <= h + 80):
            return
        self.canvas.create_oval(x - 18, y - 18, x + 18, y + 18, outline='#ffe27a', width=3, tags='ov')
        self.canvas.create_text(
            x, y - 28, text=mark.get('name') or '定位',
            fill='#ffe27a', font=(self.face, 12, 'bold'), tags='ov',
        )

    def _produce_threshold(self, kind):
        var = (getattr(self, 'produce_vars', None) or {}).get(kind)
        if var is None:
            return None
        text = (var.get() or '').strip().replace(',', '').replace('，', '')
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None
        return value if value >= 0 else None

    def _draw_produce_rings(self, w, h, layer):
        if not self.state:
            return
        for index, (kind, _label, color) in enumerate(PRODUCE_RINGS):
            threshold = self._produce_threshold(kind)
            if threshold is None:
                continue
            radius = max(14, min(40, int(12 + self.zoom * 3))) + index * 6
            for city in cities_over_produce(self.state, kind, threshold):
                xy = world_xy(city)
                if not xy:
                    continue
                x, y = self._project(*xy, w, h, layer)
                if not (-60 <= x <= w + 60 and -60 <= y <= h + 60):
                    continue
                self.canvas.create_oval(
                    x - radius, y - radius, x + radius, y + radius,
                    outline=color, width=3, tags='ov',
                )
        score_cut = self._produce_threshold(SCORE_RING[0])
        if score_cut is not None:
            radius = max(16, min(46, int(14 + self.zoom * 3))) + 18
            for city in cities_over_produce_score(self.state, score_cut):
                xy = world_xy(city)
                if not xy:
                    continue
                x, y = self._project(*xy, w, h, layer)
                if not (-60 <= x <= w + 60 and -60 <= y <= h + 60):
                    continue
                self.canvas.create_oval(
                    x - radius, y - radius, x + radius, y + radius,
                    outline=SCORE_RING[2], width=3, tags='ov',
                )

    def _draw_capitals(self, w, h, layer):
        if not self.state or not self.layers['首都'].get():
            return
        for mark in capital_marks(self.state):
            x, y = self._project(*mark['world_xy'], w, h, layer)
            if not (-50 <= x <= w + 50 and -50 <= y <= h + 50):
                continue
            color = self._rgb(mark.get('force_id'))
            radius = 20 if self.slim else 16
            self.canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                outline='#1d2418', width=4, tags='ov',
            )
            self.canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                outline=color, width=3, tags='ov',
            )
            if self.layers['文字'].get():
                self.canvas.create_text(
                    x, y + 16,
                    text=f"首都 · {mark['force_name']} · {mark['city_name']}",
                    fill='#ffe9a3', font=(self.face, 10, 'bold'), tags='ov',
                )
                self.canvas.create_text(
                    x, y + 30,
                    text=f"({mark['world_xy'][0]},{mark['world_xy'][1]})",
                    fill='#d8c27a', font=(self.face, 9), tags='ov',
                )

    def _draw_objects(self, w, h, layer):
        if not self.state:
            return
        trap_cities = trap_city_ids(self.state)
        scale = mbm_view(self.center, self.zoom, w, h)[1] if layer == 'mbm' else None
        grouped = defaultdict(list)
        for kind, row in live_objects(self.state):
            if kind in self.layers and not self.layers[kind].get():
                continue
            if not show_kind_at_zoom(kind, self.zoom):
                continue
            if not show_overlay(self.state, kind, row, self.war_only.get()):
                continue
            xy = world_xy(row, self.world)
            if not xy:
                continue
            grouped[xy].append((kind, row))
        for xy, rows in grouped.items():
            x, y = self._project(*xy, w, h, layer)
            if not (-40 <= x <= w + 40 and -40 <= y <= h + 40):
                continue
            for i, (kind, row) in enumerate(rows):
                px = x + (i - (len(rows) - 1) / 2) * 22
                key = object_key(kind, row)
                self.hits.append((px, y, key))
                size = sprite_size(kind, self.zoom, scale)
                color = self._rgb(row.get('owner_raw'))
                foe = getattr(self, 'opponent_ids', {}).get(self.opponent.get()) if getattr(self, 'opponent', None) else None
                if kind == '部队' and foe is not None and row.get('owner_raw') == foe:
                    ring = size + 8
                    self.canvas.create_oval(px - ring, y - ring, px + ring, y + ring, outline='#e23b3b', width=3, tags='ov')
                if key == self.selected:
                    self.canvas.create_oval(px - size, y - size, px + size, y + size, outline='#ffe27a', width=3, tags='ov')
                    if kind == '城关':
                        self.canvas.create_text(
                            px, y - size - 12, text=city_marker_text(row),
                            fill='#ffe27a', font=(self.face, 12, 'bold'), tags='ov',
                        )
                sprite = self.sprites.image(row, size, self.state) if self.sprites else None
                if sprite is None and self.sprites and kind == '部队' and row.get('unit_kind') in ('铁骑兵', '铁骑'):
                    sprite = self.sprites.image({**row, 'unit_kind': '重装骑兵'}, size, self.state)
                if sprite:
                    self.canvas.create_image(px, y - 4, image=sprite, tags='ov')
                elif kind == '部队':
                    self.canvas.create_polygon(px, y - 12, px - 10, y + 6, px + 10, y + 6, fill=color, outline='#1d2418', tags='ov')
                else:
                    self.canvas.create_oval(px - 4, y - 4, px + 4, y + 4, fill='#f3e6a6', outline='#3b341f', tags='ov')
                if kind == '城关' and row.get('city_id') in trap_cities:
                    ring = size + 12
                    self.canvas.create_oval(px - ring, y - ring, px + ring, y + ring, outline='#e23b3b', width=3, tags='ov')
                flag = self.sprites.flag(self.state, row.get('owner_raw'), max(14, size // 2)) if self.sprites else None
                if flag:
                    self.canvas.create_image(px + size // 2 + 4, y - size // 2, image=flag, tags='ov')
                if self.layers['文字'].get() and (layer == 'mbm' or kind == '城关'):
                    label = object_label(self.state, kind, row)
                    if kind == '城关' and is_capital(self.state, row):
                        label = '都·' + label
                    if kind == '部队':
                        self.unit_labels[key] = label_box(self.canvas, px, y + size // 2 + 6, label, color, ink=unit_label_ink(self.state, row), tags='ov')
                    else:
                        self.canvas.create_text(px + 8, y - size // 2 - 4, text=label, anchor='w', fill='#fff6da', font=(self.face, 10), tags='ov')


class PanoramaApp:
    def __init__(self, root):
        self.root = root
        self.stop = threading.Event()
        self.inbox = queue.Queue()
        self.last_sig = None
        apply_light_defaults(root)
        root.title('全景视窗 · 对手状态')
        root.configure(bg=BG)
        root.minsize(960, 640)
        self.page = PanoramaMap(root)
        self.page.pack(fill='both', expand=True)
        maximize(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self._poll, daemon=True, name='panorama-api-reader').start()
        root.after(200, self._tick)

    def _poll(self):
        from portable_client import poll
        poll(self)

    def _tick(self):
        try:
            while True:
                payload = self.inbox.get_nowait()
                from portable_client import invalidate_player, status_text
                if payload.get('fresh') is not True:
                    payload['fresh'] = False
                if payload.get('state'):
                    doc = payload['state'] if payload.get('fresh') else invalidate_player(payload['state'])
                    signature = (
                        doc.get('snapshot_id'),
                        tuple((object_key(kind, row), world_xy(row), row.get('owner_raw'), row.get('soldiers_candidate'), row.get('defense'), row.get('morale'))
                              for kind, row in live_objects(doc)),
                    )
                    if signature != self.last_sig:
                        self.last_sig = signature
                        self.page.update_state(doc)
                text, _ = status_text(payload, payload.get('state') or self.page.state)
                self.page.status.set(text)
        except queue.Empty:
            pass
        if not self.stop.is_set():
            self.root.after(250, self._tick)

    def close(self):
        self.stop.set()
        self.root.destroy()


def attach_collector():
    try:
        from connection import CONNECTION
        if CONNECTION.remote:
            return 'remote'
        if sys.platform == 'win32':
            from service_startup import ensure_service
            return ensure_service(
                'http://127.0.0.1:8769/health', 'sgi-crossover-bridge-1',
                [sys.executable, '-B', str(ROOT / 'bridge/windows_bridge.py')],
                ROOT, ROOT / 'logs/native-bridge.log',
            ).get('mode', 'started')
        from bridge_autostart import ensure_bridge
        return ensure_bridge(ROOT).get('mode', 'started')
    except Exception as error:
        return str(error)


def parse_view(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='SGI panorama')
    parser.add_argument('--center', help='world x,y')
    parser.add_argument('--zoom', type=float)
    args = parser.parse_args(argv)
    center = None
    if args.center:
        x, y = args.center.split(',')
        center = (float(x), float(y))
    return center, args.zoom


def apply_view(page, center=None, zoom=None):
    if center is not None:
        page.center = clamp_center(center)
    if zoom is not None:
        page.zoom = clamp_zoom(zoom)


def main(argv=None):
    lock = acquire_lock()
    if lock is None:
        print('本机已有全景视窗，请使用原窗口。')
        return
    center, zoom = parse_view(argv)
    attach_collector()
    root = tk.Tk()
    apply_dock_icon(root, 'map')
    app = PanoramaApp(root)
    apply_view(app.page, center, zoom)
    try:
        root.mainloop()
    finally:
        app.stop.set()
        lock.close()


if __name__ == '__main__':
    main()
