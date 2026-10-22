"""Native, read-only training curves sharing the Hub's combat and training formulas."""
import tkinter as tk
from tkinter import ttk
from battle_model import freshness
from player_view import local_projection
from preparation_model import training_bases
from training_prediction import predict_training
from unit_target_attack import supported_combat_build

BG, FG, MUTED = '#f7f4ea', '#302c22', '#786e56'
COLORS = ('#2372a1', '#b85220', '#368049')
KINDS = (('infantry', '步兵'), ('cavalry', '骑兵'), ('bow', '弓兵'))
SIZES = ('小队', '中队', '大队')
ATTACK = {k: tuple(tuple(training_bases(k, raw)['unit']) for raw in range(301)) for k, _ in KINDS}


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
    if metric == '攻击基值':
        return ATTACK[kind]
    values = []
    for raw in range(301):
        p = predict_training(kind, raw, stock, politics, politics)
        values.append(tuple((ATTACK[kind][p['raw_after_min']][s] - ATTACK[kind][raw][s]) * 1000 / p['cost'] for s in range(3)))
    return values


class TrainingCurves(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app; self.raw = {k: None for k, _ in KINDS}; self.stock = {}; self.signature = None
        self.hover = None; self.geometry_by_kind = {}; self.values = {}; self.plots = {}; self.pending = None
        bar = tk.Frame(self, bg=BG); bar.pack(fill='x', padx=8, pady=5)
        tk.Label(bar, text='规模曲线', bg=BG, fg=FG).pack(side='left')
        self.size = tk.StringVar(value='全部')
        for name in ('全部',) + SIZES:
            ttk.Radiobutton(bar, text=name, variable=self.size, value=name, command=self.redraw).pack(side='left', padx=3)
        self.metric = tk.StringVar(value='攻击基值')
        selector = ttk.Combobox(bar, textvariable=self.metric, values=['攻击基值', '每千金保守收益'], state='readonly', width=16)
        selector.pack(side='left', padx=8); selector.bind('<<ComboboxSelected>>', lambda _: self.redraw())
        tk.Label(bar, text='试算有效政治', bg=BG, fg=FG).pack(side='left')
        self.politics = tk.StringVar(value='100')
        spin = ttk.Spinbox(bar, from_=0, to=140, textvariable=self.politics, width=5, command=self.redraw)
        spin.pack(side='left'); spin.bind('<Return>', lambda _: self.redraw()); spin.bind('<FocusOut>', lambda _: self.redraw())
        self.context = tk.Label(self, bg=BG, fg=FG, anchor='w', justify='left')
        self.context.pack(fill='x', padx=8)
        legend = tk.Frame(self, bg=BG); legend.pack(fill='x', padx=8, pady=3)
        for name, color in zip(SIZES, COLORS):
            tk.Label(legend, text='━ ' + name, bg=BG, fg=color).pack(side='left', padx=(0,12))
        tk.Label(legend, text='金色虚线/圆点：当前训练　十字线：鼠标查值', bg=BG, fg=MUTED).pack(side='left')
        area = tk.Frame(self, bg=BG); area.pack(fill='both', expand=True, padx=8)
        for index, (kind, label) in enumerate(KINDS):
            area.rowconfigure(index, weight=1, uniform='training-plots'); area.columnconfigure(0, weight=1)
            canvas = tk.Canvas(area, bg=BG, height=155, highlightthickness=0, cursor='crosshair')
            canvas.grid(row=index, column=0, sticky='nsew'); self.plots[kind] = canvas
            canvas.bind('<Configure>', lambda _: self.schedule())
            canvas.bind('<Motion>', lambda e, k=kind: self.move(k, e))
            canvas.bind('<Leave>', lambda _: self.leave())
        self.note = tk.Label(self, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=1000,
            text='累计训练0–300；100/200换级。小队≤20,000，中队20,001–35,000，大队>35,000。骑弓按对应技能、满士气；基值未乘武将战力，不是伤害。\n每千金按一次练兵的保守增量；库存取当前势力，缺失时假设10万人。有效政治为试算值，实际加成与执行资格待核。')
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

    def selected_sizes(self):
        return range(3) if self.size.get() == '全部' else [SIZES.index(self.size.get())]

    def redraw(self):
        try:
            politics = int(self.politics.get())
            if not 0 <= politics <= 140: raise ValueError
        except ValueError:
            self.politics.set('100'); politics = 100
        metric = self.metric.get(); indices = list(self.selected_sizes())
        for kind, _ in KINDS:
            stock = self.stock.get(kind)
            if type(stock) is not int or not 0 <= stock <= 2000000: stock = 100000
            self.values[kind] = curve_values(kind, metric, politics, stock)
        maximum = max(v[s] for rows in self.values.values() for v in rows for s in indices)
        ceiling = max(1, maximum * 1.1)
        for kind, name in KINDS:
            c = self.plots[kind]; c.delete('all')
            w, h = max(200,c.winfo_width()), max(100,c.winfo_height())
            left, right, top, bottom = 52, w-18, 30, h-43
            self.geometry_by_kind[kind] = (left,right,top,bottom,ceiling)
            x = lambda r: left+(right-left)*r/300
            y = lambda v: bottom-(bottom-top)*v/ceiling
            r = self.raw[kind]
            current = f"当前训练 {r} · 基值 " + '/'.join(str(ATTACK[kind][r][s]) for s in indices) if r is not None else '当前训练未知（不标位置）'
            c.create_text(left, 12, text=name+' · '+current, anchor='w', fill=FG)
            for n in range(5):
                value=ceiling*n/4; yy=y(value)
                c.create_line(left,yy,right,yy,fill='#ded8c9')
                c.create_text(left-5,yy,text=f'{value:.0f}' if ceiling>20 else f'{value:.1f}',anchor='e',fill=MUTED)
            for tick in (0,50,100,150,200,250,300):
                if w<430 and tick%100: continue
                c.create_text(x(tick),bottom+12,text=str(tick),fill=MUTED)
            for tick in (100,200): c.create_line(x(tick),top,x(tick),bottom,fill='#a89d82',dash=(3,4))
            for s in indices:
                coords=[n for raw,v in enumerate(self.values[kind]) for n in (x(raw),y(v[s]))]
                c.create_line(*coords,fill=COLORS[s],width=2,tags=('curve',f'size-{s}'))
            if r is not None:
                xx=x(r);c.create_line(xx,top,xx,bottom,fill='#ac7909',width=2,dash=(5,3),tags='current')
                for s in indices:
                    yy=y(self.values[kind][r][s]);c.create_oval(xx-4,yy-4,xx+4,yy+4,fill='#ac7909',outline=BG,tags='current')
            c.create_text(left,h-9,anchor='w',fill=MUTED,text='横轴：累计训练值　纵轴：'+metric,tags='readout')
        self.draw_hover()

    def move(self, kind, event):
        left,right,top,bottom,ceiling = self.geometry_by_kind[kind]
        if not left<=event.x<=right or not top<=event.y<=bottom:
            self.leave(); return
        raw = max(0,min(300,int((event.x-left)*300/(right-left)+.5)))
        s = min(self.selected_sizes(),key=lambda i:abs(bottom-(bottom-top)*self.values[kind][raw][i]/ceiling-event.y))
        self.hover = (raw, s); self.draw_hover()

    def leave(self):
        self.hover = None; self.draw_hover()

    def draw_hover(self):
        for kind, c in self.plots.items():
            c.delete('hover')
            if self.hover is None:
                c.itemconfigure('readout',text='横轴：累计训练值　纵轴：'+self.metric.get()); continue
            raw, chosen = self.hover
            indices=list(self.selected_sizes());chosen=chosen if chosen in indices else indices[0]
            left,right,top,bottom,ceiling=self.geometry_by_kind[kind]
            xx=left+(right-left)*raw/300;yy=bottom-(bottom-top)*self.values[kind][raw][chosen]/ceiling
            c.create_line(xx,top,xx,bottom,fill=FG,dash=(2,2),tags='hover')
            c.create_line(left,yy,right,yy,fill=FG,dash=(2,2),tags='hover')
            c.create_line(xx-6,yy,xx+6,yy,fill=FG,width=2,tags='hover')
            c.create_line(xx,yy-6,xx,yy+6,fill=FG,width=2,tags='hover')
            detail=' / '.join(f'{SIZES[s]} {self.values[kind][raw][s]:g}' for s in indices)
            c.itemconfigure('readout',text=f'查值：训练 {raw} · {detail}')
