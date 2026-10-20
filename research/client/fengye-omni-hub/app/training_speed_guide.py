"""Archive-measured training speed; static reference, not a live predictor."""
import tkinter as tk

BG, FG, MUTED = '#f7f4ea', '#302c22', '#786e56'
TITLE = '#8e701c'

# 9 player archives, 2026-09-20. Capture-transfer camps excluded.
# Training: gold matched one train cost, then scaled back to 1万以下 (100%).
CAMPS = (
    ('练兵所', 10, 14165, 12963, 8870, 15000),
    ('牧场', 34, 3225, 3233, 2480, 3930),
    ('弓工坊', 20, 9240, 9082, 4820, 15000),
)
TRAIN_FULL = (
    ('弓', 16, 20.0, 20.3),
    ('骑', 15, 32.0, 31.1),
    ('步', 4, 49.5, 47.2),
)
BOW = (
    ('1万以下', '100%', 20),
    ('1–3万', '90%', 18),
    ('3–5万', '80%', 16),
    ('5–7万', '70%', 14),
    ('7–9万', '60%', 12),
    ('9万以上', '50%', 10),
)

HEAD = '盖营与练兵实测'
LEAD = (
    '盖一座营夏天多募：练兵所中位 1.42 万，弓工坊 9240，牧场 3225。'
    '一次训练去掉库存比例（按 1 万以下 100%）：弓 +20，骑 +32，步约 +50。'
    '仓库 9 万以上把训练数字对半用。'
)
SECTIONS = (
    ('盖一座营，夏天多募多少人',
     '练兵所 10 次，中位 1.42 万（8870–15000）。牧场 34 次，中位 3225（2480–3930），没有一次到 6000。'
     '弓工坊 20 次，中位 9240（4820–15000），满 15000 仅 1 次。'
     '64 座新建里只有 1 座练兵所撞帽溢了 1310。冲十万大约：步 7 座、弓 11 座、骑 31 座。'),
    ('一次训练（已折回 100%）',
     '弓干净 16 次中位 +20，和公式政治 100 一致。骑 15 次中位 +32（约 1.5 倍）。步只有 4 次，中位 +50（约 2 倍，样本少）。'
     '金：不到 100 花 1000，100–199 花 1500，200 以上花 2000。'),
    ('十万弓、弩兵 80',
     '仓库空时练到 300 再收兵约 14–15 次。一万练到 180 再收九万回补约 17 次。囤十万再练约 18 次。'
     '前期原值 0 没有摊薄；要明显更省，得在人少时练到 300。'),
    ('依据',
     '9 局玩家 1v1/3v3。得城随城转入的营不算。训练只取金币对得上一次花费的单次，再按库存档位折回 100%。'
     '完整势力年：第一年盖 0.58 练 4.29，之后盖 0.44 练 4.31。'),
)


class TrainingSpeedGuide(tk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG)
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        box = tk.Frame(self, bg=BG)
        box.pack(fill='both', expand=True, padx=10, pady=5)
        self.text = tk.Text(box, wrap='word', bg=BG, fg=FG, font=(face, 12), padx=12, pady=10, relief='flat')
        scroll = tk.Scrollbar(box, orient='vertical', command=self.text.yview)
        scroll.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure('title', font=(face, 17, 'bold'), foreground=TITLE)
        self.text.tag_configure('section', font=(face, 12, 'bold'))
        self.text.tag_configure('muted', foreground=MUTED)
        self._render()

    def _render(self):
        t = self.text
        t.config(state='normal')
        t.delete('1.0', 'end')
        t.insert('end', HEAD + '\n\n', 'title')
        t.insert('end', LEAD + '\n\n')
        t.insert('end', '盖一座营\n', 'section')
        for label, n, mid, avg, lo, hi in CAMPS:
            t.insert('end', f'  {label} · {n}次 · 中位 {mid:,} · 平均 {avg:,.0f} · {lo:,}–{hi:,}\n')
        t.insert('end', '\n一次训练（已折回 100%）\n', 'section')
        for label, n, mid, avg in TRAIN_FULL:
            t.insert('end', f'  {label} · {n}次干净 · 中位 +{mid:g} · 平均 +{avg:g}\n')
        t.insert('end', '\n弓折回各库存档（100% 按 +20）\n', 'section')
        for label, pct, gain in BOW:
            t.insert('end', f'  {label} · {pct} · 一次约 +{gain}\n')
        t.insert('end', '\n')
        for heading, body in SECTIONS:
            t.insert('end', heading + '\n', 'section')
            t.insert('end', body + '\n\n')
        t.insert('end', '连弩移动射击减半。练到 300 是为了夏天新兵落在 180，不是为了把十万弓变成连弩。\n', 'muted')
        t.config(state='disabled')
        t.yview_moveto(0)
