"""Read-only training curves; website calculator for step/ride, ability 100."""
import math
import tkinter as tk
from tkinter import ttk
from battle_model import freshness
from player_view import local_projection
from state_extensions import training_progress
from training_prediction import predict_training
from unit_target_attack import rnd, supported_combat_build, unit_factor

BG, FG, MUTED = '#f7f4ea', '#302c22', '#786e56'
SEAL, SEAL_EDGE, GOLD = '#b11a1a', '#6e0f0f', '#c9a227'
CURRENT, CURRENT_EDGE = '#1e5aa8', '#0f2f5c'
COLORS = ('#2372a1', '#b85220', '#368049')
KINDS = (('infantry', '步兵'), ('cavalry', '骑兵'), ('bow', '弓兵'))
NAMES = {'infantry': ('步兵','强化步兵','重装步兵'), 'cavalry': ('骑兵','强化骑兵','铁骑兵'), 'bow': ('弓兵','强弓兵','重装弓兵')}
SIZES = ('小队', '中队', '大队')
METRIC = '攻击力参考（战力100）'
SEAL_FACE = ('Songti SC', 'STSong', 'Kaiti SC', 'STKaiti', 'Microsoft YaHei', 'serif')

def calculator_attack(kind, raw, size):
    if kind not in NAMES or size not in (0,1,2):
        return None
    degree = training_progress(raw)
    if degree is None:
        return None
    name = NAMES[kind][0 if raw < 100 else 1 if raw < 200 else 2]
    factor = unit_factor(name, size, degree)
    if factor is None:
        return None
    return rnd(factor * 100 / 150)


def tier_name(kind, raw):
    if kind not in NAMES or type(raw) is not int or not 0 <= raw <= 300:
        return dict(KINDS).get(kind, '未知')
    return NAMES[kind][0 if raw < 100 else 1 if raw < 200 else 2]


def attack_banner(kind, size, raw=None, hover=None):
    current_point = raw if type(raw) is int and 0 <= raw <= 300 else None
    hover_point = hover if type(hover) is int and 0 <= hover <= 300 else None
    return {
        'name': tier_name(kind, current_point if current_point is not None else 300),
        'current': calculator_attack(kind, current_point, size) if current_point is not None else None,
        'current_point': current_point,
        'hover': calculator_attack(kind, hover_point, size) if hover_point is not None else None,
        'full': calculator_attack(kind, 300, size),
    }


_seal_family = None

def seal_font(size, weight='bold'):
    global _seal_family
    if _seal_family is None:
        try:
            from tkinter import font as tkfont
            have = set(tkfont.families())
            _seal_family = next((name for name in SEAL_FACE if name in have), 'serif')
        except Exception:
            _seal_family = 'serif'
    return (_seal_family, size, weight)

ATTACK = {k: tuple(tuple(calculator_attack(k,raw,size) for size in range(3)) for raw in range(301)) for k,_ in KINDS}


def current_training(state, force):
    """Prefer confirmed local projection; never substitute zero for unknown data."""
    if not force or not supported_combat_build((state or {}).get('build_sha256')):
        return {k: None for k, _ in KINDS}, {}, '当前训练未核定'
    local = local_projection(state, force['force_id'])
    source = local if local is not None else force
    values = source.get('armament_raw', {})
    raw = {k: v if type(v := values.get(k)) is int and 0 <= v <= 300 else None for k, _ in KINDS}
    return raw, source.get('troop_stock', {}), '操作层' if local is not None else '势力层'


def curve_values(kind, metric, politics, stock):
    if metric == METRIC:
        return ATTACK[kind]
    values = []
    for raw in range(301):
        p = predict_training(kind, raw, stock, politics, politics)
        values.append(tuple((ATTACK[kind][p['raw_after_min']][s] - ATTACK[kind][raw][s]) * 1000 / p['cost'] for s in range(3)))
    return values


class LogScale:
    """Fit displayed values in transformed space; preserve real-value readouts."""
    def __init__(self, values, zero_safe=False):
        self.zero_safe = zero_safe
        self.label = '对数纵轴 log(1+收益)' if zero_safe else '对数纵轴'
        transformed = [self.forward(v) for v in values]
        lo, hi = min(transformed), max(transformed)
        padding = max((hi-lo)*.06, .02)
        self.lo = max(0,lo-padding) if zero_safe else lo-padding
        self.hi = hi+padding

    def forward(self, value):
        return math.log1p(value) if self.zero_safe else math.log(value)

    def inverse(self, value):
        return math.expm1(value) if self.zero_safe else math.exp(value)

    def fraction(self, value):
        return (self.forward(value)-self.lo)/(self.hi-self.lo)

    def tick(self, fraction):
        return self.inverse(self.lo+(self.hi-self.lo)*fraction)


class LinearScale:
    """Fit one series to the full plot height; keep real-value readouts."""
    def __init__(self, values):
        lo, hi = min(values), max(values)
        span = hi - lo
        padding = max(span * .08, 1 if span == 0 else span * .08)
        self.lo, self.hi = lo - padding, hi + padding
        self.label = '线性纵轴'

    def fraction(self, value):
        return (value - self.lo) / (self.hi - self.lo)

    def tick(self, fraction):
        return self.lo + (self.hi - self.lo) * fraction


class TrainingCurves(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app; self.raw = {k: None for k, _ in KINDS}; self.stock = {}; self.signature = None
        self.hover = None; self.geometry = None; self.values = {}; self.pending = None
        bar = tk.Frame(self, bg=BG); bar.pack(fill='x', padx=8, pady=5)
        tk.Label(bar, text='兵种', bg=BG, fg=FG).pack(side='left')
        self.kind = tk.StringVar(value='infantry')
        for key, label in KINDS:
            ttk.Radiobutton(bar, text=label, variable=self.kind, value=key, command=self.redraw).pack(side='left', padx=3)
        tk.Label(bar, text='规模', bg=BG, fg=FG).pack(side='left', padx=(12, 0))
        self.size = tk.StringVar(value='小队')
        for name in SIZES:
            ttk.Radiobutton(bar, text=name, variable=self.size, value=name, command=self.redraw).pack(side='left', padx=3)
        self.metric = tk.StringVar(value=METRIC)
        selector = ttk.Combobox(bar, textvariable=self.metric, values=[METRIC, '每千金保守收益'], state='readonly', width=26)
        selector.pack(side='left', padx=8); selector.bind('<<ComboboxSelected>>', lambda _=None: self.redraw())
        tk.Label(bar, text='试算有效政治', bg=BG, fg=FG).pack(side='left')
        self.politics = tk.StringVar(value='100')
        spin = ttk.Spinbox(bar, from_=0, to=140, textvariable=self.politics, width=5, command=self.redraw)
        spin.pack(side='left'); spin.bind('<Return>', lambda _=None: self.redraw()); spin.bind('<FocusOut>', lambda _=None: self.redraw())
        self.context = tk.Label(self, bg=BG, fg=FG, anchor='w', justify='left')
        self.context.pack(fill='x', padx=8)
        legend = tk.Frame(self, bg=BG); legend.pack(fill='x', padx=8, pady=3)
        tk.Label(legend, text='金色虚线/圆点：当前训练　十字线：鼠标查值　切换兵种和规模只画这一张', bg=BG, fg=MUTED).pack(side='left')
        area = tk.Frame(self, bg=BG); area.pack(fill='both', expand=True, padx=8)
        area.rowconfigure(0, weight=1); area.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(area, bg=BG, height=360, highlightthickness=0, cursor='crosshair')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.canvas.bind('<Configure>', lambda _=None: self.schedule())
        self.canvas.bind('<Motion>', self.move)
        self.canvas.bind('<Leave>', lambda _=None: self.leave())
        self.note = tk.Label(self, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=1000,
            text='与部队攻击同一套网站计算器，战力固定100。小队满武装：重装步153、铁骑167。曲线上方大字：当前攻击力蓝色、满训朱红。横轴累计0–300，100/200换兵种，武装用本级余数（300记为100）。弓兵无网站参数，仍用原表。\n单图线性纵轴按当前兵种和规模拉满高度。每千金收益用同一攻击值；库存缺失时假设10万人，有效政治为假设值。')
        self.note.pack(fill='x', padx=8, pady=4)
        self.bind('<Configure>', lambda e: self.note.configure(wraplength=max(240,e.width-20)))
        self.redraw()

    def schedule(self):
        if self.pending is None:
            self.pending = self.after_idle(self.scheduled)

    def scheduled(self):
        self.pending = None; self.redraw()

    def refresh(self, state, force):
        raw, stock, source = current_training(state, force)
        text = f"当前势力：{(force or {}).get('name','未选择')} · {source} · {freshness(state or {})}"
        self.context.configure(text=text)
        signature = (tuple(raw.items()), tuple((k,stock.get(k)) for k,_ in KINDS))
        if signature != self.signature:
            self.signature = signature; self.raw = raw; self.stock = stock; self.redraw()

    def selected(self):
        kind = self.kind.get() if self.kind.get() in dict(KINDS) else 'infantry'
        size = SIZES.index(self.size.get()) if self.size.get() in SIZES else 0
        return kind, size

    def redraw(self):
        try:
            politics = int(self.politics.get())
            if not 0 <= politics <= 140: raise ValueError
        except ValueError:
            self.politics.set('100'); politics = 100
        metric = self.metric.get(); kind, size = self.selected()
        for key, _ in KINDS:
            stock = self.stock.get(key)
            if type(stock) is not int or not 0 <= stock <= 2000000: stock = 100000
            self.values[key] = curve_values(key, metric, politics, stock)
        series = [row[size] for row in self.values[kind]]
        scale = LinearScale(series) if metric == METRIC else LogScale(series, True)
        c = self.canvas; c.delete('all')
        w, h = max(240, c.winfo_width()), max(220, c.winfo_height())
        left, right, top, bottom = 56, w-22, 118, h-46
        self.geometry = (left, right, top, bottom, scale)
        x = lambda r: left+(right-left)*r/300
        y = lambda v: bottom-(bottom-top)*scale.fraction(v)
        r = self.raw[kind]
        name = dict(KINDS)[kind]
        current = f"当前{tier_name(kind, r)} · 训练 {r} · {metric.split('（')[0]} {series[r]:g}" if r is not None else '当前训练未知（不标位置）'
        c.create_text(left, 16, text=f'{name} · {SIZES[size]} · {current} · {scale.label}', anchor='w', fill=FG)
        for n in range(5):
            value = scale.tick(n/4); yy = y(value)
            c.create_line(left, yy, right, yy, fill='#ded8c9')
            c.create_text(left-5, yy, text=f'{value:.0f}' if metric==METRIC else f'{value:.2f}', anchor='e', fill=MUTED)
        for tick in (0, 50, 100, 150, 200, 250, 300):
            if w < 430 and tick % 100: continue
            c.create_text(x(tick), bottom+12, text=str(tick), fill=MUTED)
        for tick in (100, 200):
            c.create_line(x(tick), top, x(tick), bottom, fill='#a89d82', dash=(3, 4))
        coords = [n for raw, v in enumerate(series) for n in (x(raw), y(v))]
        c.create_line(*coords, fill=COLORS[size], width=2, tags='curve')
        if r is not None:
            xx = x(r)
            c.create_line(xx, top, xx, bottom, fill='#ac7909', width=2, dash=(5, 3), tags='current')
            yy = y(series[r])
            c.create_oval(xx-4, yy-4, xx+4, yy+4, fill='#ac7909', outline=BG, tags='current')
        c.create_text(left, h-10, anchor='w', fill=MUTED, text='横轴：累计训练值　纵轴：'+metric, tags='readout')
        self.draw_hover()

    def _paint_seal(self, x, y, value, caption, big, fill, edge):
        c = self.canvas
        c.create_text(x+2, y+2, text=f'{value:g}', anchor='n', fill=edge, font=seal_font(big), tags='seal')
        c.create_text(x, y, text=f'{value:g}', anchor='n', fill=fill, font=seal_font(big), tags='seal')
        c.create_text(x, y-2, text=caption, anchor='s', fill=GOLD, font=seal_font(14), tags='seal')

    def _draw_seal(self):
        c = self.canvas
        c.delete('seal')
        kind, size = self.selected()
        info = attack_banner(kind, size, self.raw.get(kind), self.hover)
        if info['full'] is None:
            return
        w = max(240, c.winfo_width())
        y = 38
        big = 40 if w < 560 else 46
        gap = 108 if w < 560 else 128
        self._paint_seal(w-56, y, info['full'], '满训', big, SEAL, SEAL_EDGE)
        if info['current'] is not None and info['current_point'] != 300:
            self._paint_seal(w-56-gap, y, info['current'], f"当前 {info['name']}", big, CURRENT, CURRENT_EDGE)

    def move(self, event):
        if self.geometry is None:
            return
        left, right, top, bottom, _ = self.geometry
        if not left<=event.x<=right or not top<=event.y<=bottom:
            self.leave(); return
        raw = max(0, min(300, int((event.x-left)*300/(right-left)+.5)))
        self.hover = raw; self.draw_hover()

    def leave(self):
        self.hover = None; self.draw_hover()

    def draw_hover(self):
        c = self.canvas
        c.delete('hover')
        if self.hover is None or self.geometry is None:
            if self.geometry is not None:
                c.itemconfigure('readout', text='横轴：累计训练值　纵轴：'+self.metric.get())
            self._draw_seal(); return
        raw = self.hover
        kind, size = self.selected()
        left, right, top, bottom, scale = self.geometry
        value = self.values[kind][raw][size]
        xx = left+(right-left)*raw/300
        yy = bottom-(bottom-top)*scale.fraction(value)
        c.create_line(xx, top, xx, bottom, fill=FG, dash=(2, 2), tags='hover')
        c.create_line(left, yy, right, yy, fill=FG, dash=(2, 2), tags='hover')
        c.create_line(xx-6, yy, xx+6, yy, fill=FG, width=2, tags='hover')
        c.create_line(xx, yy-6, xx, yy+6, fill=FG, width=2, tags='hover')
        c.itemconfigure('readout', text=f'查值：{tier_name(kind, raw)} · {SIZES[size]} · 训练 {raw} · {value:g}')
        self._draw_seal()
