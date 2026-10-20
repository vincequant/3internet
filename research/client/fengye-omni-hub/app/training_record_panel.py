"""Force-tab time series: one stock chart and one training chart per kind."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from force_troop_totals import (
    KINDS, KIND_CN, merge_troop_series, samples_for_force, seasons_until_next_summer,
    troop_series_point,
)
from military_summary import troop_info
from opening_troop_routes import opening_route_note
from recruitment_summary import annual_recruitment, predicted_after_summer
from training_activity import activity_counts

BG = '#f7f4ea'
INK = '#302c22'
MUTED = '#756443'
COLORS = {'infantry': '#8a6a2a', 'cavalry': '#b85220', 'bow': '#368049'}
TAB_NAMES = (('infantry', '步兵'), ('cavalry', '骑兵'), ('bow', '弓兵'))
TIER_LINES = ((100, '#e07018'), (200, '#7a3cb8'))


class TrainingRecordPanel(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.samples = []
        self.series = []
        self.session = None
        self.force_id = None
        self.hover = None
        self.geometry = {}
        self.pending = None
        self.canvases = {}
        self.forecast_labels = []
        self.forecast = {}
        self.activity_counts = {}
        self.kind_activity = {}
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        self.headline = tk.Label(self, bg=BG, fg=INK, anchor='w', justify='left', wraplength=720, font=(face, 13, 'bold'))
        self.headline.pack(fill='x', padx=10, pady=(0, 4))
        self.sub = tk.Label(self, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=720, font=(face, 10))
        self.sub.pack(fill='x', padx=10)
        self.activity = tk.Label(self, bg=BG, fg=INK, anchor='w', justify='left',
                                 wraplength=720, font=(face, 11, 'bold'))
        self.activity.pack(fill='x', padx=10, pady=(4, 0))
        self.kind_book = ttk.Notebook(self)
        self.kind_book.pack(fill='both', expand=True, padx=6, pady=4)
        for kind, title in TAB_NAMES:
            page = tk.Frame(self.kind_book, bg=BG)
            self.kind_book.add(page, text=title)
            label = tk.Label(page, bg=BG, fg=COLORS[kind], anchor='w', font=(face, 10))
            label.pack(fill='x', padx=8, pady=(4, 0))
            self.kind_activity[kind] = label
            charts = tk.Frame(page, bg=BG)
            charts.pack(fill='both', expand=True)
            stock = tk.Canvas(charts, bg=BG, highlightthickness=0, width=1, height=1)
            train = tk.Canvas(charts, bg=BG, highlightthickness=0, width=1, height=1)
            stock.pack(side='left', fill='both', expand=True, padx=(0, 4), pady=4)
            train.pack(side='left', fill='both', expand=True, padx=(4, 0), pady=4)
            self.canvases[kind + '-stock'] = stock
            self.canvases[kind + '-train'] = train
            stock.bind('<Configure>', lambda _e=None: self.schedule())
            train.bind('<Configure>', lambda _e=None: self.schedule())
            stock.bind('<Motion>', lambda event, k=kind + '-stock': self.move(event, k))
            train.bind('<Motion>', lambda event, k=kind + '-train': self.move(event, k))
            stock.bind('<Leave>', lambda _e=None, k=kind + '-stock': self.leave(k))
            train.bind('<Leave>', lambda _e=None, k=kind + '-train': self.leave(k))
        self.kind_book.bind('<<NotebookTabChanged>>', lambda _e=None: self.schedule())
        self.bind('<Configure>', self._on_resize)

    def _select_kind_tab(self, note):
        text = note or ''
        if '练骑' in text:
            index = 1
        elif '练弓' in text:
            index = 2
        else:
            index = 0
        try:
            self.kind_book.select(index)
        except tk.TclError:
            pass

    def _on_resize(self, event):
        wrap = max(240, event.width - 24)
        self.headline.configure(wraplength=wrap)
        self.sub.configure(wraplength=wrap)
        self.activity.configure(wraplength=wrap)

    def update_activity(self, force_id, state):
        self.activity_counts = activity_counts(state, force_id)
        self.activity.config(text=f"累计记录：训练 {self.activity_counts['training']} 次 · 盖兵营 {self.activity_counts['building']} 次")
        camps = {'infantry': '练兵所', 'cavalry': '牧场', 'bow': '弓工坊'}
        for kind, title in TAB_NAMES:
            counts = self.activity_counts['by_kind'][kind]
            self.kind_activity[kind].config(text=f"{title}累计：训练 {counts['training']} 次 · 盖{camps[kind]} {counts['building']} 次")

    def update_force(self, force, state):
        fid = (force or {}).get('force_id')
        changed = fid != self.force_id
        self.force_id = fid
        self.update_activity(fid, state)
        if changed:
            self._select_kind_tab(opening_route_note(force))
        session = ((state or {}).get('player_identity') or {}).get('session_id')
        if session != self.session:
            self.session = session
            self.series = []
        history = (state or {}).get('history') or {}
        live = troop_series_point(state)
        self.series = merge_troop_series(
            self.series, history.get('troop_series'), [live],
        )
        self.samples = samples_for_force(self.series, fid)
        live_rows = samples_for_force([live], fid)
        current = live_rows[-1] if live_rows else (self.samples[-1] if self.samples else None)
        self.forecast_labels, self.forecast = self._forecast(current, state)
        if current is None:
            self.headline.config(text='尚无该势力练兵记录')
            self.sub.config(text='')
        else:
            bits = []
            for kind in KINDS:
                row = current['kinds'][kind]
                total = row.get('total')
                info = troop_info(kind, row.get('raw'))
                bits.append(
                    f"{KIND_CN[kind]} {total:,}（仓{row.get('warehouse') or 0:,}+征{row.get('field') or 0:,}）"
                    f" · {info['name']} {info['training']}/100" if isinstance(total, int) and info['training'] is not None
                    else f"{KIND_CN[kind]} 未知")
            city = current.get('city') or 0
            other = current.get('field_other') or 0
            if other:
                bits.append(f'出城未分种 {other:,}')
            self.headline.config(text='　'.join(bits))
            self.sub.config(text=f"城中现役将带兵 {city:,}（无兵种，不计入左图） · {(current.get('label') or '')}")
        self.redraw()

    def schedule(self):
        if self.pending is None:
            self.pending = self.after_idle(self._redraw_idle)

    def _redraw_idle(self):
        self.pending = None
        self.redraw()

    def kind_values(self, kind, field):
        out = []
        for sample in self.samples:
            row = sample['kinds'][kind]
            out.append(row.get('total') if field == 'stock' else row.get('raw'))
        return out

    def _forecast(self, current, state):
        if not current:
            return [], {}
        year, season = current.get('year'), current.get('season')
        if not isinstance(year, int) or season not in (0, 1, 2, 3):
            live = troop_series_point(state)
            year, season = live.get('year'), live.get('season')
        seasons = seasons_until_next_summer(year, season)
        if not seasons:
            return [], {}
        rec = annual_recruitment(state, self.force_id) if state is not None else {}
        kinds = {}
        for kind in KINDS:
            row = (current.get('kinds') or {}).get(kind) or {}
            pred = predicted_after_summer(row, (rec.get(kind) or {}).get('known'))
            kinds[kind] = {
                'stock': [pred['stock'] if item['season'] == 1 else row.get('total') for item in seasons],
                'train': [pred['raw'] if item['season'] == 1 else row.get('raw') for item in seasons],
            }
        return [item['label'] for item in seasons], kinds

    def redraw(self):
        labels = [row.get('label') or '' for row in self.samples]
        axis = labels + self.forecast_labels
        for kind in KINDS:
            name = KIND_CN[kind]
            color = COLORS[kind]
            forecast = self.forecast.get(kind) or {}
            self._draw(
                self.canvases[kind + '-stock'], kind + '-stock', axis, len(labels),
                self.kind_values(kind, 'stock'), forecast.get('stock') or [],
                0, None, name + ' 库存+出征', color,
            )
            self._draw(
                self.canvases[kind + '-train'], kind + '-train', axis, len(labels),
                self.kind_values(kind, 'train'), forecast.get('train') or [],
                0, 300, name + ' 训练原值', color, TIER_LINES,
            )

    def _canvas_size(self, canvas):
        w, h = canvas.winfo_width(), canvas.winfo_height()
        return max(200, w if w > 2 else 320), max(90, h if h > 2 else 110)

    def _left_margin(self, canvas, ticks):
        face = getattr(self.app, 'face', 'PingFang SC') if self.app is not None else 'PingFang SC'
        font = tkfont.Font(root=canvas, font=(face, 10))
        width = max(font.measure(f'{tick:,.0f}') for tick in ticks)
        return max(56, width + 12)

    def _draw(self, canvas, key, labels, actual_n, values, forecast, y_min, y_max, title, color, refs=()):
        canvas.delete('all')
        w, h = self._canvas_size(canvas)
        known = [v for v in list(values) + list(forecast) if isinstance(v, int)]
        if y_max is None:
            hi = max(known) if known else 1
            pad = max(hi * 0.08, 1)
            y_min, y_max = 0, hi + pad
        span = max(y_max - y_min, 1)
        ticks = [y_min + span * n / 2 for n in range(3)]
        left = self._left_margin(canvas, ticks)
        right, top, bottom = w - 12, 28, h - 22
        if bottom - top < 20:
            bottom = top + 20
        self.geometry[key] = (left, right, top, bottom, y_min, y_max, labels)
        canvas.create_rectangle(0, 0, w, h, fill=BG, outline=BG)
        canvas.configure(scrollregion=(0, 0, w, h))
        head = title
        if self.forecast_labels:
            last = forecast[-1] if forecast else None
            shown = f'{last:,}' if isinstance(last, int) else '—'
            head = f'{title}  预{self.forecast_labels[-1]} {shown}'
        canvas.create_text(left, 10, text=head, anchor='w', fill=color)
        x = lambda i, n: left if n <= 1 else left + (right - left) * i / (n - 1)
        y = lambda v: bottom - (bottom - top) * ((v - y_min) / span)
        for value in ticks:
            yy = y(value)
            canvas.create_line(left, yy, right, yy, fill='#ded8c9')
            canvas.create_text(left - 6, yy, text=f'{value:,.0f}', anchor='e', fill=MUTED)
        for ref in refs:
            if isinstance(ref, (tuple, list)) and len(ref) >= 2:
                value, ref_color = ref[0], ref[1]
            else:
                value, ref_color = ref, '#a89d82'
            canvas.create_line(left, y(value), right, y(value), fill=ref_color)
        count = len(labels)
        pts = []
        for i, value in enumerate(values):
            if not isinstance(value, int):
                continue
            pts.extend((x(i, count), y(value)))
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=2)
        elif len(pts) == 2:
            canvas.create_oval(pts[0] - 3, pts[1] - 3, pts[0] + 3, pts[1] + 3, fill=color, outline=BG)
        dash = []
        if pts:
            dash.extend(pts[-2:])
        for i, value in enumerate(forecast):
            if not isinstance(value, int):
                continue
            dash.extend((x(actual_n + i, count), y(value)))
        if len(dash) >= 4:
            canvas.create_line(*dash, fill=color, width=2, dash=(5, 4))
        elif len(dash) == 2:
            canvas.create_oval(dash[0] - 3, dash[1] - 3, dash[0] + 3, dash[1] + 3, fill=color, outline=BG)
        if count:
            canvas.create_text(left, h - 8, text=labels[0], anchor='w', fill=MUTED)
            canvas.create_text(right, h - 8, text=labels[-1], anchor='e', fill=MUTED)
        if self.hover is not None and 0 <= self.hover < count:
            xx = x(self.hover, count)
            canvas.create_line(xx, top, xx, bottom, fill=INK, dash=(2, 2))
            if self.hover < actual_n:
                value = values[self.hover] if self.hover < len(values) else None
            else:
                index = self.hover - actual_n
                value = forecast[index] if 0 <= index < len(forecast) else None
            shown = f'{value:,}' if isinstance(value, int) else '—'
            prefix = '预 ' if self.hover >= actual_n else ''
            canvas.create_text(right, 10, text=f'{prefix}{labels[self.hover]}　{shown}', anchor='e', fill=INK)

    def move(self, event, key):
        box = self.geometry.get(key)
        if not box:
            return
        left, right, top, bottom, *_rest, labels = box
        if not labels:
            return
        if not (left <= event.x <= right and top <= event.y <= bottom):
            self.leave(key)
            return
        count = len(labels)
        if count <= 1:
            index = 0
        else:
            index = int(round((event.x - left) * (count - 1) / (right - left)))
            index = max(0, min(count - 1, index))
        if self.hover != index:
            self.hover = index
            self.redraw()

    def leave(self, key):
        if self.hover is not None:
            self.hover = None
            self.redraw()
