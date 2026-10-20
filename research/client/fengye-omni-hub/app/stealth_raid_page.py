"""Raid tab: panorama map, place a troop on a city ring, user walks, count turns."""
import copy
import tkinter as tk
from panorama_map import PanoramaMap
from player_view import player_id
from panorama_model import capital_marks, clamp_center, world_xy
from state_history import calendar_label, kind_label, phase_fields
from stealth_raid import (
    KIND_CHOICES, SPRITE_KIND, cell_walkable, city_ring_cells, field_unit_at,
    kind_spec, own_cities, raid_move_overlay, raid_reach_cells,
    unit_move_overlay, unit_reach_cells,
)

BG = '#1b1d18'
INK = '#efe7cf'
MUTED = '#b7ad8f'
BAR = '#2a2c24'
WELL = '#22241d'


def _force_name(state, fid):
    for lord in ((state or {}).get('entities') or {}).get('lords') or []:
        if lord.get('force_id') == fid:
            return lord.get('name') or '?'
    return '?'


class StealthRaidPage(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.cities = []
        self._sig = None
        self.sortie_city = None
        self.ring = []
        self.unit_cell = None
        self.pending = None
        self.control = None
        self.live_key = None
        self._live_home = {}
        self.moves = []
        self.log = []
        self.frozen = None
        self._capital_marks = []
        self._capital_sync = False
        face = getattr(app, 'face', None)
        self.hint = tk.StringVar(value='快捷模式：点己方城出兵或点己方部队，再沿移动格连续走，每走一格算一回。骑/步/弓用三级建模。点列表跳主城。')
        top = tk.Frame(self, bg=BAR)
        top.pack(fill='x', padx=8, pady=(8, 4))
        self._side_btn = tk.Button(
            top, text='折叠状态栏', command=self.toggle_side,
            bg='#e7e0c9', fg='#302c22', activebackground='#d4c89a',
            activeforeground='#302c22', highlightbackground='#2a2c24',
            relief='raised', borderwidth=1, padx=12,
        )
        self._side_btn.pack(side='left', padx=(0, 8))
        tk.Label(
            top, textvariable=self.hint, bg=BAR, fg='#e4c56a', anchor='w',
            justify='left', font=(face, 11), wraplength=860,
        ).pack(side='left', fill='x', expand=True)
        body = tk.PanedWindow(
            self, orient='horizontal', sashwidth=8, bg='#3d3f34',
            sashrelief='raised', opaqueresize=False,
        )
        body.pack(fill='both', expand=True)
        self.map = PanoramaMap(body, title='偷袭主城', mode='raid')
        self.map.on_pick_origin = self._from_map_city
        self.map.on_pick_cell = self._from_map_cell
        self.map.on_pick_unit = self._from_map_unit
        side = tk.Frame(self, bg=WELL, width=300)
        body.add(self.map, stretch='always', minsize=420)
        body.add(side, stretch='never', minsize=260)
        self._body = body
        self._side = side
        self._side_open = True
        tk.Label(side, text='我方势力', bg=WELL, fg=INK, anchor='w', font=(face, 12, 'bold')).pack(fill='x', padx=10, pady=(10, 2))
        self.own_text = tk.StringVar(value='未锁定')
        tk.Label(
            side, textvariable=self.own_text, bg=WELL, fg='#ffe27a', anchor='w',
            font=(face, 13, 'bold'),
        ).pack(fill='x', padx=10, pady=(0, 4))
        self.freeze_text = tk.StringVar(value='')
        tk.Label(
            side, textvariable=self.freeze_text, bg=WELL, fg='#9ecbff', anchor='w',
            justify='left', font=(face, 11), wraplength=280,
        ).pack(fill='x', padx=10, pady=(0, 2))
        self.follow_slot = tk.Frame(side, bg=WELL)
        self.follow_slot.pack(fill='x', padx=10, pady=(0, 8))
        self.follow_btn = tk.Button(
            self.follow_slot, text='跟随实时', command=self.follow_live,
            bg='#e7e0c9', fg='#302c22',
        )
        tk.Label(side, text='各势力主城', bg=WELL, fg=INK, anchor='w', font=(face, 12, 'bold')).pack(fill='x', padx=10, pady=(4, 2))
        self.capitals = getattr(tk, 'Listbox')(
            side, bg='#2c2f26', fg=INK, selectbackground='#6a5520', height=7,
            font=(face, 11), relief='flat', exportselection=False,
        )
        self.capital_box = self.capitals
        self.capitals.pack(fill='x', padx=10, pady=(0, 6))
        self.capitals.bind('<<ListboxSelect>>', self._jump_capital)
        tk.Label(side, text='出兵种类', bg=WELL, fg=INK, anchor='w', font=(face, 12, 'bold')).pack(fill='x', padx=10, pady=(4, 2))
        kinds = tk.Frame(side, bg=WELL)
        kinds.pack(fill='x', padx=10, pady=(0, 6))
        self.kind_var = tk.StringVar(value='骑兵')
        for label, _klass in KIND_CHOICES:
            tk.Radiobutton(
                kinds, text=label, value=label, variable=self.kind_var,
                command=self._paint, bg=WELL, fg=INK, selectcolor='#3d3f34',
                activebackground=WELL, activeforeground=INK, font=(face, 11),
            ).pack(side='left', padx=2)
        self.place_text = tk.StringVar(value='未出兵')
        tk.Label(side, textvariable=self.place_text, bg=WELL, fg=INK, anchor='w', font=(face, 11)).pack(fill='x', padx=10, pady=(8, 2))
        sim = tk.Frame(side, bg=WELL)
        sim.pack(fill='x', padx=10, pady=(4, 4))
        tk.Button(sim, text='重来', command=self._reset, bg='#e7e0c9', fg='#302c22').pack(side='left')
        tk.Button(sim, text='上一回', command=self._prev, bg='#e7e0c9', fg='#302c22').pack(side='left', padx=6)
        self.sim_text = tk.StringVar(value='点己方城')
        tk.Label(
            side, textvariable=self.sim_text, bg=WELL, fg='#ffe27a', anchor='w',
            justify='left', font=(face, 12, 'bold'), wraplength=280,
        ).pack(fill='x', padx=10, pady=(4, 4))
        self.log_box = tk.Text(
            side, height=10, bg='#2c2f26', fg=INK, relief='flat', font=(face, 10),
            wrap='word',
        )
        self.log_box.pack(fill='both', expand=True, padx=10, pady=(0, 12))
        self.log_box.bind('<Key>', lambda _e=None: 'break')
        side.bind('<Configure>', self._wrap)
        self._fill_capitals()
        self._paint()

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
                body.add(side, stretch='never', minsize=260)
            except tk.TclError:
                pass
            body.after_idle(self._place_side_sash)
        elif not self._side_open and shown:
            try:
                body.forget(side)
            except tk.TclError:
                pass
        if btn is not None:
            btn.config(text='折叠状态栏' if self._side_open else '展开状态栏')

    def _place_side_sash(self):
        body = getattr(self, '_body', None)
        side = getattr(self, '_side', None)
        if body is None or side is None or not self._side_open:
            return
        try:
            body.update_idletasks()
            width = body.winfo_width()
            if width > 280 and len(body.panes()) >= 2:
                body.sash_place(0, max(200, width - 300), 0)
        except tk.TclError:
            pass

    def _wrap(self, event=None):
        width = max(200, (event.width if event else 280) - 24)
        self.log_box.configure(width=max(20, width // 8))

    def _kind(self):
        return self.kind_var.get() or '骑兵'

    def _reviewing(self):
        return bool(getattr(self.app, 'review', None))

    def _freeze_label(self, state):
        phase = phase_fields((state or {}).get('clock_candidates'), (state or {}).get('phase_candidate'))
        cal = calendar_label(phase.get('year_u16'), phase.get('season_u16'))
        snap = (state or {}).get('snapshot_id')
        bits = ['已锁本帧']
        if cal:
            bits.append(cal)
        if snap is not None and snap != '':
            bits.append(f'snapshot {snap}')
        return ' · '.join(bits)

    def _show_freeze_chrome(self):
        if self.frozen is None or self._reviewing():
            self.freeze_text.set('')
            self.follow_btn.pack_forget()
            return
        self.freeze_text.set(self._freeze_label(self.frozen))
        if not self.follow_btn.winfo_manager():
            self.follow_btn.pack(anchor='w')

    def _freeze_if_needed(self):
        if self.frozen is not None or self._reviewing():
            return
        state = self.map.state
        if not state:
            return
        self.frozen = copy.deepcopy(state)
        self._live_home = {
            (row.get('owner_raw'), row.get('unit_id')): tuple(row.get('world_xy_raw') or ())
            for row in ((self.frozen.get('entities') or {}).get('field_units') or [])
        }
        self.map.update_state(self.frozen, lists=False, immediate=False, refresh_view=False)
        self._show_freeze_chrome()

    def unfreeze(self):
        self.frozen = None
        self._live_home = {}
        self._show_freeze_chrome()
        self.sortie_city = None
        self.ring = []
        self.unit_cell = None
        self.pending = None
        self.control = None
        self.live_key = None
        self.moves = []
        self.log = []
        self._sig = None
        self.sim_text.set('点己方城或己方部队')
        self.place_text.set('未出兵')

    def follow_live(self):
        if self._reviewing():
            return
        self.unfreeze()
        live = getattr(self.app, 'doc', None)
        self.refresh(live)

    def refresh(self, state):
        reviewing = self._reviewing()
        if reviewing:
            archive = (getattr(self.app, 'review', None) or {}).get('state')
            use = archive if archive is not None else state
            if self.frozen is not None:
                self.frozen = None
                self._show_freeze_chrome()
                self._sig = None
        elif self.frozen is not None:
            self.map.update_state(self.frozen, lists=False, immediate=False, refresh_view=False)
            self._show_freeze_chrome()
            self._fill_capitals()
            self._paint()
            return
        else:
            use = state
        sig = None if not use else (use.get('snapshot_id'), player_id(use))
        self.map.update_state(use, lists=False, immediate=False, refresh_view=False)
        self._fill_capitals()
        if sig == self._sig:
            return
        same_player = (
            self._sig is not None and sig is not None and self._sig[1] == sig[1]
            and player_id(use) is not None
        )
        self._sig = sig
        own = player_id(use)
        if own is None:
            self.own_text.set('未锁定')
            self.cities = []
            self.hint.set('未确认我方。地图仍是全景，先在顶栏锁定我方。点列表跳主城。')
            return
        self.own_text.set(f'{_force_name(use, own)}（已锁定）')
        self.cities = own_cities(use)
        if same_player:
            self._paint()
            return
        self.sortie_city = None
        self.ring = []
        self.unit_cell = None
        self.pending = None
        self.control = None
        self.live_key = None
        self.moves = []
        self.log = []
        self.hint.set(f'我方 {_force_name(use, own)}。点己方城出兵，或点己方部队移动。点列表跳主城。')
        self.sim_text.set('点己方城或己方部队')
        self.place_text.set('未出兵')
        self._paint()

    def _live_unit(self):
        if not self.live_key:
            return None
        owner, uid = self.live_key
        return field_unit_at(self.map.state, {'owner_raw': owner, 'unit_id': uid})

    def _current_moves(self):
        if self.control == 'live' and self.live_key:
            owner, uid = self.live_key
            return [row for row in self.moves
                    if row.get('control') == 'live' and row.get('owner') == owner and row.get('unit_id') == uid]
        if self.unit_cell is not None:
            return [row for row in self.moves if row.get('control') == 'sim']
        return []

    def _turn_count(self):
        return len(self._current_moves())

    def _unit_label(self, unit=None):
        if unit is not None:
            return kind_label(unit.get('unit_kind')) or '部队'
        if self.control == 'live':
            found = self._live_unit()
            if found is not None:
                return kind_label(found.get('unit_kind')) or '部队'
        return kind_label(SPRITE_KIND.get(self._kind(), self._kind()))

    def _select_sim(self, cell):
        self.control = 'sim'
        self.live_key = None
        self.unit_cell = cell
        self.pending = None
        self.ring = raid_reach_cells(self.map.state, cell, self._kind(), self.map.terrain)

    def _select_live(self, row):
        found = field_unit_at(self.map.state, row) or row
        xy = world_xy(found)
        if xy is None:
            return None
        self.control = 'live'
        self.live_key = (found.get('owner_raw'), found.get('unit_id'))
        self.pending = None
        self.ring = unit_reach_cells(self.map.state, found, self.map.terrain)
        return found

    def _move_selected(self, cell):
        cell = (int(cell[0]), int(cell[1]))
        if self.control == 'live':
            unit = self._live_unit()
            if unit is None:
                return False
            origin = world_xy(unit)
            if origin is None:
                return False
            unit['world_xy_raw'] = [cell[0], cell[1]]
            self.moves.append({
                'control': 'live', 'unit_id': unit.get('unit_id'), 'owner': unit.get('owner_raw'),
                'from': origin, 'to': cell, 'kind': unit.get('unit_kind'),
            })
            self.ring = unit_reach_cells(self.map.state, unit, self.map.terrain)
            self._show_turn(cell, kind_label(unit.get('unit_kind')) or '部队')
            return True
        if self.unit_cell is None:
            return False
        origin = tuple(self.unit_cell)
        self.moves.append({
            'control': 'sim', 'from': origin, 'to': cell, 'kind': self._kind(),
        })
        self.unit_cell = cell
        self.pending = None
        self.ring = raid_reach_cells(self.map.state, cell, self._kind(), self.map.terrain)
        self._show_turn(cell, kind_label(SPRITE_KIND.get(self._kind(), self._kind())))
        return True

    def _show_turn(self, cell, name):
        n = self._turn_count()
        self.place_text.set(f'{name} 已走 {n} 回 · ({cell[0]},{cell[1]})')
        self.sim_text.set(f'{name} 第 {n} 回 · ({cell[0]},{cell[1]})，可继续点格走')

    def _city_from_mark(self, mark):
        cid = (mark or {}).get('city_id')
        if cid is None:
            return None
        for row in ((self.map.state or {}).get('entities') or {}).get('cities_and_barriers') or []:
            if row.get('city_id') == cid:
                return row
        return None

    def _highlight_capital(self, city_id):
        if city_id is None:
            return
        for index, mark in enumerate(self._capital_marks):
            if mark.get('city_id') == city_id:
                self._capital_sync = True
                try:
                    self.capitals.selection_clear(0, 'end')
                    self.capitals.selection_set(index)
                    self.capitals.activate(index)
                    self.capitals.see(index)
                except tk.TclError:
                    pass
                finally:
                    self._capital_sync = False
                return

    def _fill_capitals(self):
        selected_id = None
        try:
            cur = self.capitals.curselection()
        except tk.TclError:
            cur = ()
        if cur and cur[0] < len(self._capital_marks):
            selected_id = self._capital_marks[cur[0]].get('city_id')
        elif self.sortie_city:
            selected_id = self.sortie_city.get('city_id')
        self._capital_marks = []
        try:
            self.capitals.configure(state='normal')
            self.capitals.delete(0, 'end')
        except tk.TclError:
            return
        state = self.map.state
        pid = player_id(state)
        marks = sorted(capital_marks(state), key=lambda mark: mark.get('force_id') != pid)
        if not marks:
            try:
                self.capitals.configure(state='disabled')
            except tk.TclError:
                pass
            return
        for mark in marks:
            xy = mark.get('world_xy') or (None, None)
            own = pid is not None and mark.get('force_id') == pid
            prefix = '★ ' if own else ''
            self._capital_marks.append(mark)
            self.capitals.insert('end', f"{prefix}{mark.get('force_name') or '?'}  {mark.get('city_name') or '?'}  ({xy[0]},{xy[1]})")
            if own:
                self.capitals.itemconfig(self.capitals.size() - 1, background='#4a3d18', selectbackground='#6a5520')
        if selected_id is not None:
            self._highlight_capital(selected_id)

    def _jump_capital(self, mark=None):
        if self._capital_sync:
            return
        if isinstance(mark, dict) and mark.get('world_xy') is not None:
            target = mark
        else:
            selection = self.capitals.curselection()
            if not selection:
                return
            index = selection[0]
            if index >= len(self._capital_marks):
                return
            target = self._capital_marks[index]
        xy = target.get('world_xy')
        if xy and len(xy) >= 2:
            self.map.center = clamp_center((xy[0] + 0.5, xy[1] + 0.5))
            painter = getattr(self.map, 'draw', None)
            if not callable(painter):
                painter = getattr(self.map, 'request_draw', None)
            if callable(painter):
                painter()
        own = player_id(self.map.state)
        if own is None or target.get('owner_raw') != own:
            return
        row = self._city_from_mark(target)
        if row is not None:
            self._from_map_city(row)

    def _pick_capital(self, _=None):
        return self._jump_capital(_)

    def _from_map_city(self, row):
        own = player_id(self.map.state)
        if own is None or not row or row.get('owner_raw') != own:
            return
        self.sortie_city = row
        self.control = 'place'
        self.live_key = None
        self.ring = city_ring_cells(self.map.state, row, self.map.terrain)
        self._freeze_if_needed()
        self.pending = None
        name = row.get('name') or '?'
        self.sim_text.set(f'{name}周边 {len(self.ring)} 格，点一格放{self._kind()}')
        self.place_text.set(f'出兵城 {name}')
        self._highlight_capital(row.get('city_id'))
        self._paint()

    def _from_map_unit(self, row):
        own = player_id(self.map.state)
        if own is None or not row or row.get('owner_raw') != own:
            return
        self._freeze_if_needed()
        found = self._select_live(row)
        if found is None:
            return
        xy = world_xy(found)
        name = kind_label(found.get('unit_kind')) or '部队'
        n = self._turn_count()
        self.sim_text.set(f'{name} 已走 {n} 回 · ({xy[0]},{xy[1]})，点格继续走')
        self.place_text.set(f'{name} 已走 {n} 回 · ({xy[0]},{xy[1]})')
        self._paint()

    def _from_map_cell(self, cell):
        cell = (int(cell[0]), int(cell[1]))
        if player_id(self.map.state) is None:
            return
        if self.unit_cell is not None and cell == tuple(self.unit_cell):
            self._select_sim(self.unit_cell)
            shown = kind_label(SPRITE_KIND.get(self._kind(), self._kind()))
            n = self._turn_count()
            self.sim_text.set(f'{shown} 已走 {n} 回 · ({cell[0]},{cell[1]})，点格继续走')
            self._paint()
            return
        placing = self.control == 'place' or (self.control is None and self.unit_cell is None)
        if placing:
            if cell not in set(self.ring):
                if not self.ring:
                    self.sim_text.set('先点己方城或己方部队')
                    return
                self.sim_text.set('请点亮着的周边格放兵')
                return
            if not cell_walkable(self.map.state, cell, self.map.terrain):
                self.sim_text.set(f'({cell[0]},{cell[1]}) 不能落脚')
                return
            self._freeze_if_needed()
            self._select_sim(cell)
            shown = kind_label(SPRITE_KIND.get(self._kind(), self._kind()))
            city = (self.sortie_city or {}).get('name') or ''
            self.place_text.set(f'{shown} 已走 0 回 · 在{city}旁 ({cell[0]},{cell[1]})')
            self.sim_text.set(f'已放{shown}。沿移动格连续走，每格一回')
            self._paint()
            return
        if cell not in set(self.ring):
            self.sim_text.set('点当前部队移动范围内的格子')
            return
        self._freeze_if_needed()
        if not self._move_selected(cell):
            return
        self._paint()

    def _prev(self):
        if self.moves:
            last = self.moves.pop()
            origin = last['from']
            if last.get('control') == 'live':
                unit = field_unit_at(self.map.state, {
                    'unit_id': last.get('unit_id'), 'owner_raw': last.get('owner'),
                })
                if unit is not None:
                    unit['world_xy_raw'] = [origin[0], origin[1]]
                    self._select_live(unit)
                    self._show_turn(origin, kind_label(unit.get('unit_kind')) or '部队')
            else:
                self._select_sim(origin)
                self._show_turn(origin, kind_label(SPRITE_KIND.get(self._kind(), self._kind())))
            self._paint()
            return
        self.sim_text.set('没有上一回')

    def _restore_live_homes(self):
        units = ((self.map.state or {}).get('entities') or {}).get('field_units') or []
        for row in units:
            home = self._live_home.get((row.get('owner_raw'), row.get('unit_id')))
            if home and len(home) == 2:
                row['world_xy_raw'] = [home[0], home[1]]

    def _reset(self):
        self._restore_live_homes()
        self.unit_cell = None
        self.pending = None
        self.control = 'place' if self.sortie_city else None
        self.live_key = None
        self.moves = []
        self.log = []
        if self.sortie_city:
            self.ring = city_ring_cells(self.map.state, self.sortie_city, self.map.terrain)
            name = (self.sortie_city or {}).get('name') or '?'
            self.sim_text.set(f'{name}周边 {len(self.ring)} 格，点一格放兵')
            self.place_text.set(f'出兵城 {name}')
        else:
            self.ring = []
            self.sim_text.set('点己方城或己方部队')
            self.place_text.set('未出兵')
        self._paint()

    def _paint(self):
        spec = kind_spec(self._kind())
        mp = spec['points'] if spec else '?'
        steps = self._current_moves()
        name = self._unit_label()
        lines = [f'{name} 已走 {len(steps)} 回']
        for i, row in enumerate(steps, 1):
            src, dst = row['from'], row['to']
            lines.append(f'第{i}回 ({src[0]},{src[1]}) → ({dst[0]},{dst[1]})')
        self.log_box.delete('1.0', 'end')
        if steps:
            self.log_box.insert('end', '\n'.join(lines))
        elif self.unit_cell or self.control == 'live':
            self.log_box.insert('end', f'{name} 已走 0 回。移动力{mp}。点移动格连续走，每格一回。')
        else:
            self.log_box.insert('end', '快捷模式。点城出兵或点己方部队，沿移动格连续走，每格算一回。')
        live = self._live_unit() if self.control == 'live' else None
        if live is not None:
            self.ring = unit_reach_cells(self.map.state, live, self.map.terrain)
            move_cells = unit_move_overlay(self.map.state, live, self.map.terrain)
            ring = []
        elif self.unit_cell is not None:
            self.ring = raid_reach_cells(self.map.state, self.unit_cell, self._kind(), self.map.terrain)
            move_cells = raid_move_overlay(self.map.state, self.unit_cell, self._kind(), self.map.terrain)
            ring = []
        else:
            move_cells = []
            ring = list(self.ring)
        self.map.show_raid(
            {
                'ok': True,
                'ring': ring,
                'move_cells': move_cells,
                'sim_cell': self.unit_cell,
                'pending': self.pending,
                'sim_kind': self._kind(),
                'brief': '',
            },
            sim_cell=self.unit_cell,
            immediate=True,
        )
