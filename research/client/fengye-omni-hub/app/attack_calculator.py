"""Read-only interactive attack calculator in 攻略预判."""
import tkinter as tk
from tkinter import ttk
from attack_calculator_model import calculate, calculation_text, from_unit
from unit_target_attack import PARAMS

BG, FG, GOLD, MUTED = '#f7f4ea', '#302c22', '#8e701c', '#786e56'


class AttackCalculator(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.state = None
        self.units = {}
        self.loading = False
        self.result = None
        self.variables = {}
        self.officers = []
        def label(parent, text, **kw):
            return tk.Label(parent, text=text, bg=BG, fg=FG, anchor='w', **kw)
        label(self, '攻击系数计算器', font=(app.face, 18, 'bold')).pack(fill='x', padx=14, pady=(10, 4))
        self.source_note = label(self, '手动演算；调整参数后立即计算。')
        self.source_note.pack(fill='x', padx=14, pady=4)
        bar = tk.Frame(self, bg=BG);bar.pack(fill='x', padx=14, pady=4)
        label(bar, '所选帧部队：').pack(side='left')
        self.unit_var = tk.StringVar()
        self.unit_combo = ttk.Combobox(bar, textvariable=self.unit_var, state='readonly', width=42)
        self.unit_combo.pack(side='left', fill='x', expand=True)
        self.load_button = ttk.Button(bar, text='载入参数', command=self.load_unit, state='disabled')
        self.load_button.pack(side='left', padx=(8, 0))
        self.answer = label(self, '', font=(app.face, 22, 'bold'))
        self.answer.pack(fill='x', padx=14, pady=(10, 2))
        self.coefficients = label(self, '');self.coefficients.pack(fill='x', padx=14, pady=(0, 8))
        shell = ttk.Panedwindow(self, orient='horizontal');shell.pack(fill='both', expand=True, padx=12, pady=8)
        left_shell = tk.Frame(shell, bg=BG);right = tk.Frame(shell, bg=BG)
        shell.add(left_shell, weight=2);shell.add(right, weight=3)
        self.input_canvas = tk.Canvas(left_shell, bg=BG, highlightthickness=0, width=390, height=400)
        input_scroll = ttk.Scrollbar(left_shell, orient='vertical', command=self.input_canvas.yview)
        self.input_canvas.configure(yscrollcommand=input_scroll.set)
        input_scroll.pack(side='right', fill='y');self.input_canvas.pack(side='left', fill='both', expand=True)
        left = tk.Frame(self.input_canvas, bg=BG)
        window = self.input_canvas.create_window((0,0), window=left, anchor='nw')
        left.bind('<Configure>', lambda _:self.input_canvas.configure(scrollregion=self.input_canvas.bbox('all')))
        self.input_canvas.bind('<Configure>', lambda event:self.input_canvas.itemconfigure(window, width=event.width))
        inputs = tk.LabelFrame(left, text='兵种与状态', bg=BG, fg=FG);inputs.pack(fill='x', padx=4, pady=4)
        specs = [('kind', '兵种', '强化骑兵', tuple(PARAMS)), ('soldiers', '兵数', '12000', (1,100000)),
                 ('training', '本级训练度', '60', (0,100)), ('morale', '当前士气', '75', (0,100)),
                 ('terrain', '当前位置', '陆地', ('陆地','水上'))]
        for row, (key, caption, value, domain) in enumerate(specs):
            label(inputs, caption).grid(row=row, column=0, sticky='w', padx=8, pady=5)
            v = tk.StringVar(value=value);self.variables[key] = v
            if key in ('kind', 'terrain'):
                w = ttk.Combobox(inputs, textvariable=v, values=domain, state='readonly', width=18)
            else:
                w = ttk.Spinbox(inputs, textvariable=v, from_=domain[0], to=domain[1], width=18)
            w.grid(row=row, column=1, sticky='ew', padx=8, pady=5)
            v.trace_add('write', self.changed)
        inputs.columnconfigure(1, weight=1)
        self.horse = tk.BooleanVar(value=True);self.arrow = tk.BooleanVar(value=True)
        self.horse_button = ttk.Checkbutton(inputs, text='编成具有骑马技能', variable=self.horse, command=self.changed)
        self.arrow_button = ttk.Checkbutton(inputs, text='编成具有弓箭技能', variable=self.arrow, command=self.changed)
        self.horse_button.grid(row=5, column=0, columnspan=2, sticky='w', padx=8, pady=4)
        self.arrow_button.grid(row=6, column=0, columnspan=2, sticky='w', padx=8, pady=4)
        label(inputs, '训练度为本级0–100；兵种等级单独选择。', wraplength=350).grid(row=7, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        formation = tk.LabelFrame(left, text='编成武将（填写宝物修正前属性）', bg=BG, fg=FG)
        formation.pack(fill='x', padx=4, pady=6)
        self.count = tk.StringVar(value='1')
        label(formation, '人数').grid(row=0, column=0, padx=5, pady=6)
        ttk.Combobox(formation, textvariable=self.count, values=('1','2','3'), state='readonly', width=5).grid(row=0, column=1, sticky='w')
        for col, title in enumerate(('','统率','武力','统+40%','武+40%')):
            label(formation, title).grid(row=1, column=col, padx=3)
        self.officer_widgets = []
        for i in range(3):
            label(formation, '主将' if i == 0 else f'副将{i}').grid(row=i+2, column=0, padx=5, pady=6)
            record = dict(lead=tk.StringVar(value='80'), war=tk.StringVar(value='80'),
                          lead_bonus=tk.BooleanVar(value=False), war_bonus=tk.BooleanVar(value=False))
            widgets = []
            for col, key in enumerate(('lead','war'), 1):
                w = ttk.Spinbox(formation, textvariable=record[key], from_=0, to=255, width=5)
                w.grid(row=i+2, column=col, padx=3);widgets.append(w)
            for col, key in enumerate(('lead_bonus','war_bonus'), 3):
                w = ttk.Checkbutton(formation, variable=record[key]);w.grid(row=i+2, column=col, padx=3);widgets.append(w)
            for v in record.values():v.trace_add('write', self.changed)
            self.officers.append(record);self.officer_widgets.append(widgets)
        self.count.trace_add('write', self.changed)
        label(left, '水军技能在此攻击系数分支不直接加乘。\n统率与武力支持1–3将，第一行为主将。', wraplength=350).pack(fill='x', padx=8, pady=6)
        label(right, '计算过程', font=(app.face, 13, 'bold')).pack(fill='x', padx=8, pady=4)
        self.details = tk.Text(right, wrap='word', bg=BG, fg=FG, font=(app.face, 12),
                               width=50, height=18, padx=10, pady=8, relief='flat')
        scroll = ttk.Scrollbar(right, orient='vertical', command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set);scroll.pack(side='right', fill='y');self.details.pack(fill='both', expand=True)
        label(self, '指数用于战斗比较的中间步骤；合击、随机、目标条件及最终损兵另算。', wraplength=1000).pack(fill='x', padx=14, pady=(2, 10))
        self.bind('<Configure>', self.resize)
        self.changed()

    def resize(self, event):
        if event.widget is self:
            for widget in (self.source_note,self.coefficients):
                widget.configure(wraplength=max(250,event.width-28))

    def changed(self, *_):
        if self.loading:
            return
        self.source_note.configure(text='手动演算；调整参数后立即计算。', fg=MUTED)
        self.recalculate()

    def recalculate(self):
        kind = self.variables['kind'].get()
        self.horse_button.configure(state='normal' if '骑兵' in kind else 'disabled')
        self.arrow_button.configure(state='normal' if '弓兵' in kind else 'disabled')
        try:
            count = int(self.count.get())
            for i, widgets in enumerate(self.officer_widgets):
                for w in widgets:w.configure(state='normal' if i < count else 'disabled')
            officers = [dict(lead=int(g['lead'].get()), war=int(g['war'].get()),
                             lead_bonus=g['lead_bonus'].get(), war_bonus=g['war_bonus'].get()) for g in self.officers[:count]]
            r = calculate(kind, int(self.variables['soldiers'].get()), int(self.variables['training'].get()),
                          int(self.variables['morale'].get()), officers, self.horse.get(), self.arrow.get(),
                          self.variables['terrain'].get() == '水上')
        except (ValueError, tk.TclError) as exc:
            self.result = None
            self.answer.configure(text='请补全有效参数', fg='#ac2b20');self.coefficients.configure(text='')
            self.set_details(str(exc) if 'invalid literal' not in str(exc) else '兵数、训练度、士气、统率和武力须填写整数。')
            return
        self.result = r
        self.answer.configure(text=f"{r['mode']}指数 [{r['current']}/{r['land_full']}]", fg=GOLD)
        self.coefficients.configure(text=f"当前 / 陆地满士气　·　兵种系数B {r['current_coefficient']} / {r['land_coefficient']}　·　编成能力A {r['ability']}")
        self.set_details(calculation_text(r))

    def set_details(self, text):
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('end',text);self.details.configure(state='disabled')

    def refresh(self, state, force_id):
        self.state = state
        self.units = {}
        entities = (state or {}).get('entities') or {}
        names = {g.get('general_id_raw'):g.get('name') for g in entities.get('generals') or []}
        for i, u in enumerate(entities.get('field_units') or []):
            if u.get('owner_raw') != force_id or (u.get('unit_kind') not in PARAMS and u.get('unit_kind') not in ('铁骑兵','生骑兵','生步兵','弩兵','连弩')):
                continue
            name = u.get('general_names') or u.get('name') or [names[gid] for gid in u.get('general_ids') or [] if names.get(gid)]
            if isinstance(name, list):name = '、'.join(str(v) for v in name)
            key = f"#{u.get('unit_id',i)} · {name} · {u.get('unit_kind')}"
            self.units[key] = u
        self.unit_combo.configure(values=tuple(self.units))
        if self.unit_var.get() not in self.units:self.unit_var.set(next(iter(self.units), ''))
        self.load_button.configure(state='normal' if self.units else 'disabled')

    def load_unit(self):
        u = self.units.get(self.unit_var.get())
        if u is None:
            return
        try:
            values = from_unit(self.state, u)
        except ValueError as exc:
            self.source_note.configure(text=str(exc)+'；手动参数保持不变。', fg='#ac2b20')
            return
        self.loading = True
        try:
            for key in ('kind','soldiers','training','morale'):self.variables[key].set(str(values[key]))
            self.variables['terrain'].set('水上' if values['on_water'] else '陆地')
            self.horse.set(values['horse']);self.arrow.set(values['arrow']);self.count.set(str(len(values['officers'])))
            for widgets, g in zip(self.officers, values['officers']):
                for key, v in g.items():widgets[key].set(v)
        finally:
            self.loading = False
        self.recalculate()
        self.source_note.configure(text=f"已载入所选帧 {self.state.get('snapshot_id') or ''} · {self.unit_var.get()}；调整参数后转为手动演算。", fg=MUTED)
