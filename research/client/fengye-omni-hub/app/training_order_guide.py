"""Per-force minimum-command build/train sequence for 攻略预判."""
import tkinter as tk
from tkinter import ttk
from training_sim import OPENING, format_force_order

BG, FG, MUTED, TITLE = '#f7f4ea', '#302c22', '#786e56', '#8e701c'


class TrainingOrderGuide(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        self.app = app
        self.force = tk.StringVar(value='魏')
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        top = tk.Frame(self, bg=BG)
        top.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(top, text='训练顺序技巧', bg=BG, fg=TITLE, font=(face, 16, 'bold')).pack(side='left')
        tk.Label(top, text='200春只出兵。骑10万/250，弓10万/180，步10万/250。',
                 bg=BG, fg=MUTED, font=(face, 11)).pack(side='left', padx=12)
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill='x', padx=10, pady=4)
        tk.Label(bar, text='势力', bg=BG, fg=FG).pack(side='left')
        box = ttk.Combobox(bar, textvariable=self.force, values=[row[1] for row in OPENING],
                           state='readonly', width=8)
        box.pack(side='left', padx=4)
        box.bind('<<ComboboxSelected>>', lambda _=None: self.render())
        box_frame = tk.Frame(self, bg=BG)
        box_frame.pack(fill='both', expand=True, padx=10, pady=6)
        self.text = tk.Text(box_frame, wrap='word', bg=BG, fg=FG, font=(face, 12), padx=12, pady=10, relief='flat')
        scroll = ttk.Scrollbar(box_frame, orient='vertical', command=self.text.yview)
        scroll.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure('title', font=(face, 15, 'bold'), foreground=TITLE)
        self.text.tag_configure('section', font=(face, 12, 'bold'))
        self.text.tag_configure('muted', foreground=MUTED)
        self.render()

    def set_force(self, name):
        if name and name in [row[1] for row in OPENING] and name != self.force.get():
            self.force.set(name)
            self.render()

    def render(self):
        name = self.force.get() or '魏'
        body = format_force_order(name=name)
        t = self.text
        t.config(state='normal')
        t.delete('1.0', 'end')
        lines = body.split('\n')
        if lines:
            t.insert('end', lines[0] + '\n', 'title')
            rest = '\n'.join(lines[1:])
            t.insert('end', rest)
        t.config(state='disabled')
        t.yview_moveto(0)
