"""Interactive camp/train simulator on the 攻略预判 tab."""
import tkinter as tk
from tkinter import ttk
from recruitment_summary import annual_recruitment
from training_sim import (
    ACTIONS, BY_ID, CAMP_CN, CAMP_YIELD, KIND_CN, KINDS,
    OPENING, PACE_NOTE, SEASON_CN, apply_action, format_best_table,
    from_live_force, goal_hit, goal_raw, goal_stock, opening_state, phase_text, project_goal,
    troop_label,
)

BG, FG, MUTED, TITLE = '#f7f4ea', '#302c22', '#786e56', '#8e701c'
GOAL_NOTE = '弓10万/180，骑10万/250，步10万/250。200春只出兵；200秋冬起才盖或练。'


class TrainingSimPanel(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.history = []
        self.state = opening_state(0)
        self.kind = tk.StringVar(value='bow')
        self.force = tk.StringVar(value='魏')
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        self.face = face
        top = tk.Frame(self, bg=BG)
        top.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(top, text='盖营练兵模拟', bg=BG, fg=TITLE, font=(face, 16, 'bold')).pack(side='left')
        tk.Label(top, text=GOAL_NOTE, bg=BG, fg=MUTED, font=(face, 11)).pack(side='left', padx=12)
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill='x', padx=10, pady=4)
        tk.Label(bar, text='势力', bg=BG, fg=FG).pack(side='left')
        names = [row[1] for row in OPENING]
        box = ttk.Combobox(bar, textvariable=self.force, values=names, state='readonly', width=8)
        box.pack(side='left', padx=4)
        box.bind('<<ComboboxSelected>>', lambda _=None: self.reset_opening())
        tk.Label(bar, text='目标兵种', bg=BG, fg=FG).pack(side='left', padx=(12, 4))
        for kind, label in KIND_CN.items():
            tk.Radiobutton(bar, text=label, value=kind, variable=self.kind, bg=BG, fg=FG,
                           selectcolor='#eee9d9', command=self.refresh, font=(face, 11)).pack(side='left')
        tk.Button(bar, text='开局重置', command=self.reset_opening, bg=BG, fg=FG).pack(side='left', padx=8)
        tk.Button(bar, text='读当前采集', command=self.load_live, bg=BG, fg=FG).pack(side='left')
        tk.Button(bar, text='撤销', command=self.undo, bg=BG, fg=FG).pack(side='left', padx=8)
        self.proj = tk.Label(self, bg='#eee0c4', fg='#6b3f12', anchor='w', justify='left',
                             wraplength=920, font=(face, 13, 'bold'))
        self.proj.pack(fill='x', padx=10, pady=4)
        self.status = tk.Label(self, bg=BG, fg=FG, anchor='w', justify='left', wraplength=920, font=(face, 12))
        self.status.pack(fill='x', padx=10)
        self.board = tk.Label(self, bg=BG, fg=FG, anchor='w', justify='left', font=(face, 12))
        self.board.pack(fill='x', padx=10, pady=4)
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill='x', padx=10, pady=4)
        for action, label in ACTIONS:
            tk.Button(btns, text=label, command=lambda a=action: self.act(a), bg=BG, fg=FG, width=10).pack(side='left', padx=3)
        self.pace = tk.Label(self, text=PACE_NOTE, bg=BG, fg=MUTED, anchor='w', justify='left',
                             wraplength=920, font=(face, 10))
        self.pace.pack(fill='x', padx=10)
        tk.Label(self, text='每季 3 次指令。「其他」占一格但不算建房/训练。夏天按已建营加兵并摊薄。营值中位：练兵所 14165、牧场 3225、弓工坊 9240。撞城人口帽未模拟。',
                 bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=920, font=(face, 10)).pack(fill='x', padx=10)
        log_box = tk.Frame(self, bg=BG)
        log_box.pack(fill='both', expand=True, padx=10, pady=6)
        self.log = tk.Text(log_box, wrap='word', bg=BG, fg=FG, font=(face, 11), height=12, relief='flat')
        scroll = ttk.Scrollbar(log_box, orient='vertical', command=self.log.yview)
        scroll.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)
        self.log.configure(yscrollcommand=scroll.set)
        self._table = format_best_table()
        self.bind('<Configure>', self._resize)
        self.refresh()

    def _resize(self, event):
        wrap = max(240, event.width - 24)
        self.proj.configure(wraplength=wrap)
        self.status.configure(wraplength=wrap)
        self.pace.configure(wraplength=wrap)

    def reset_opening(self):
        row = BY_ID.get(next((fid for fid, r in BY_ID.items() if r[1] == self.force.get()), 0), OPENING[0])
        self.force.set(row[1])
        self.history = []
        self.state = opening_state(row[0])
        self.refresh()

    def load_live(self):
        app = self.app
        doc = getattr(app, 'doc', None) or {}
        fid = getattr(app, 'sel', None)
        force = next((f for f in (doc.get('entities') or {}).get('lords') or [] if f.get('force_id') == fid), None)
        state = from_live_force(force, annual_recruitment(doc, fid) if force else None)
        if not state:
            self.status.configure(text='没有可用的当前采集，仍用开局。')
            return
        self.force.set(state['name'] if state['name'] in [r[1] for r in OPENING] else self.force.get())
        self.history = []
        self.state = state
        self.refresh()

    def act(self, action):
        self.history.append(self.state)
        self.state = apply_action(self.state, action)
        self.refresh()

    def undo(self):
        if not self.history:
            return
        self.state = self.history.pop()
        self.refresh()

    def refresh(self):
        s = self.state
        kind = self.kind.get()
        if kind not in KINDS:
            kind = 'bow'
            self.kind.set(kind)
        target = goal_raw(kind)
        proj = project_goal(s, kind)
        hit = s['reached'].get(kind)
        if hit:
            proj_text = (
                f"已达成 {KIND_CN[kind]} {goal_stock(kind)//10000}万 / 原值{target}：建房 {hit['build']} + 训练 {hit['train']} = {hit['total']} 次"
                f"（另有其他 {hit['other']} 次，{hit['year']}年{SEASON_CN[hit['season']]}）"
            )
        elif proj.get('ok'):
            proj_text = (
                f"{s['name']}练{KIND_CN[kind]}最少 {proj['total']} 次（盖{proj['build']}+练{proj['train']}），"
                f"约 {proj['year']}年。目标 {goal_stock(kind)//10000}万 / 原值{target}。"
                f" 已用建房 {s['build']}、训练 {s['train']}、其他 {s['other']}。"
            )
        else:
            proj_text = '推算未达成。'
        src = {'archive': '开局来自玩家存档', 'website': '开局夏募未采到，营从 0 计', 'live': '当前采集'}.get(s.get('source'), '')
        self.proj.configure(text=proj_text)
        self.status.configure(text=f"{s['name']} · {phase_text(s)} · {src}")
        lines = []
        for k in KINDS:
            mark = ' ←目标' if k == kind else ''
            done = ' 已达标' if goal_hit(s, k) else ''
            lines.append(
                f"{KIND_CN[k]}  {s['stock'][k]:,}  {troop_label(k, s['raw'][k])}  原值{s['raw'][k]}  "
                f"下次夏募 {s['camp'][k]:,}  盖一座+{CAMP_YIELD[k]:,}{mark}{done}"
            )
        self.board.configure(text='\n'.join(lines))
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.insert('end', self._table + '\n\n')
        self.log.insert('end', '\n'.join(s['log']) or '还没点指令。每季三次，点「其他」表示这格用在录用/出征等。')
        self.log.config(state='disabled')
        self.log.see('end')
