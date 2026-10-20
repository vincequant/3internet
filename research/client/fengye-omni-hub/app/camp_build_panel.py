"""Force-tab ledger: construction times for 练兵所 / 牧场 / 弓工坊, excluding capture transfers."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

BG = '#f7f4ea'
INK = '#302c22'
MUTED = '#756443'
WELL = '#eee0c4'

COLS = (
    ('when', '时间', 240),
    ('kind', '种类', 80),
    ('place', '地点', 180),
    ('line', '记录', 380),
)


def rows_for_force(history, force_id):
    bridge = str(Path(__file__).resolve().parent.parent / 'bridge')
    if bridge not in sys.path:
        sys.path.append(bridge)
    from state_history import camp_builds_from_history
    rows = []
    for item in camp_builds_from_history(history):
        if force_id is not None and item.get('owner') != force_id:
            continue
        rows.append(item)
    return rows


class CampBuildPanel(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.rows = []
        self.busy = False
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        self.note = tk.Label(
            self, bg=WELL, fg='#6b3f12', anchor='w', justify='left', wraplength=720, font=(face, 11),
            text='只记本局已过滤后的建营：练兵所、牧场、弓工坊。占城随城转入的营不进表。时间取观察到该营出现的季度/回合。')
        self.note.pack(fill='x', padx=8, pady=(8, 4))
        self.headline = tk.Label(self, bg=BG, fg=INK, anchor='w', justify='left', font=(face, 13, 'bold'))
        self.headline.pack(fill='x', padx=10, pady=(0, 4))
        box = tk.Frame(self, bg=BG)
        box.pack(fill='both', expand=True, padx=6, pady=4)
        self.tree = ttk.Treeview(box, columns=[key for key, _title, _w in COLS], show='headings', selectmode='browse')
        for key, title, width in COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key == 'line')
        y = ttk.Scrollbar(box, command=self.tree.yview)
        x = ttk.Scrollbar(box, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        x.pack(side='bottom', fill='x')
        y.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.bind('<Configure>', lambda event: self.note.configure(wraplength=max(240, event.width - 24)))

    def update_force(self, force, state):
        fid = (force or {}).get('force_id')
        history = (state or {}).get('history') or {}
        self.rows = rows_for_force(history, fid)
        counts = {'练兵所': 0, '牧场': 0, '弓工坊': 0}
        for item in self.rows:
            kind = item.get('kind')
            if kind in counts:
                counts[kind] += 1
        if not self.rows:
            self.headline.config(text='尚无该势力建营记录（不含占城带营）')
        else:
            bits = [f"{name}{counts[name]}" for name in ('练兵所', '牧场', '弓工坊') if counts[name]]
            self.headline.config(text=f"建营 {len(self.rows)} 条 · " + ' · '.join(bits) + '（不含占城带营）')
        self.busy = True
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.rows):
            self.tree.insert('', 'end', iid=str(index), values=(
                item.get('when') or item.get('label') or '',
                item.get('kind') or '',
                item.get('place') or '地点未标',
                item.get('line') or item.get('field') or '',
            ))
        self.busy = False
