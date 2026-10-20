"""Enemy selector with separate physical and strategy formation recommendations."""
import json
import tkinter as tk
from tkinter import ttk
from battle_model import freshness
from counter_model import targets, counter_recommend
from preparation_model import span

BG = '#f7f4ea'


class CounterPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app; self.signature = None; self.options = []; self.records = {}
        bar = tk.Frame(self, bg=BG); bar.pack(fill='x', padx=8, pady=5)
        self.other = tk.BooleanVar(value=False); self.include = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text='含其他非盟约势力（非宣战）', variable=self.other, command=self.refresh, bg=BG).pack(side='left')
        tk.Checkbutton(bar, text='含出阵将（须回城重编）', variable=self.include, command=self.refresh, bg=BG).pack(side='left')
        self.target = ttk.Combobox(self, state='readonly', width=80)
        self.target.pack(fill='x', padx=8); self.target.bind('<<ComboboxSelected>>', lambda _=None: self.calculate())
        self.status = tk.Label(self, bg=BG, anchor='w', justify='left', wraplength=650)
        self.status.pack(fill='x', padx=8, pady=5)
        note = tk.Label(self, bg=BG, fg='#786e56', anchor='w', justify='left', wraplength=650,
            text='对部队攻击按网站计算器；弓兵缺参数。双方统一按满士气100对决，忽略当前及出场士气，不以士气筛选或排序。攻击比较未计地形、防御和宝物，不是扣血或胜率；对手其余参数取当前快照。各行是独立备选，不能重复用将同时出兵。')
        note.pack(fill='x', padx=8, pady=5)
        book = ttk.Notebook(self); book.pack(fill='both', expand=True, padx=6)
        self.trees = []
        for title, special in [('攻击克敌', [('result','攻击对比',170)]),
                               ('计谋克敌', [('spell','计谋',70), ('caster','施术将 / 智力（个体）',160), ('counter','敌方防计',240)])]:
            frame = tk.Frame(book, bg=BG); book.add(frame, text=title)
            cols = special + [('troop','兵种',85), ('leader','主将',85), ('deputies','副将',150),
                             ('soldiers','拟带兵≈',85), ('attack','攻击力（计算器）',130), ('condition','重编条件',200)]
            tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show='headings', height=7)
            for key, label, width in cols:
                tree.heading(key, text=label); tree.column(key, width=width, stretch=False)
            order=[c[0] for c in cols];order.remove('attack');order.insert(1,'attack');tree.configure(displaycolumns=order)
            tree.grid(row=0, column=0, sticky='nsew')
            for orient, row, col, command in [('vertical',0,1,tree.yview), ('horizontal',1,0,tree.xview)]:
                scroll = ttk.Scrollbar(frame, orient=orient, command=command)
                scroll.grid(row=row, column=col, sticky='ns' if orient=='vertical' else 'ew')
                tree.configure(**{('yscrollcommand' if orient=='vertical' else 'xscrollcommand'):scroll.set})
            frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
            tree.bind('<<TreeviewSelect>>', lambda _=None, t=tree: self.details(t))
            self.trees.append(tree)
        self.detail = tk.Text(self, height=6, wrap='word', bg=BG, relief='flat')
        self.detail.pack(fill='x', padx=8, pady=5); self.detail.configure(state='disabled')
        self.bind('<Configure>', lambda e: [w.configure(wraplength=max(250,e.width-24)) for w in (note,self.status)])

    def refresh(self):
        state = self.app.doc or {}
        signature = json.dumps([state.get('entities'), state.get('build_sha256'), state.get('player_identity'),
                                state.get('player_force_id'), self.other.get(), self.include.get()], sort_keys=True)
        if signature == self.signature:
            return
        self.signature = signature
        index = self.target.current()
        previous = self.options[index] if 0 <= index < len(self.options) else {}
        self.options = targets(state, self.other.get())
        forces = {f['force_id']: f.get('name','?') for f in state.get('entities',{}).get('lords',[])}
        self.target['values'] = [f"{forces.get(u.get('owner_raw'),'?')} · 部队{u.get('unit_id')} · {u.get('unit_kind')} · 兵{u.get('soldiers_candidate','?')} · 将ID{u.get('general_ids',[])}" for u in self.options]
        if self.options:
            selected = next((i for i,u in enumerate(self.options) if (u.get('owner_raw'),u.get('unit_id')) == (previous.get('owner_raw'),previous.get('unit_id'))),0)
            self.target.current(selected)
        else:
            self.target.set('无已确认战争目标；可勾选其他非盟约势力查看')
        self.calculate()

    def calculate(self):
        for tree in self.trees:
            tree.delete(*tree.get_children())
        self.records = {}; self.set_detail('')
        index = self.target.current()
        if not 0 <= index < len(self.options):
            self.status.config(text='没有可推荐的敌方已出场部队'); return
        state = self.app.doc or {}; result = counter_recommend(state, self.options[index], self.include.get())
        self.status.config(text=f"{freshness(state)} · 网站参考尺度（不同于地图攻指） · 双方满士气100 · 敌对部队攻击参考：{span(result['enemy_attack']) if result['enemy_attack'] else '缺参数'} · 攻击方案 {len(result['physical'])} · 计谋方案 {len(result['spells'])}\n{result['message']}")
        for tree, key in zip(self.trees, ('physical','spells')):
            for i,r in enumerate(result[key]):
                values = ([r['comparison']] if key=='physical' else
                          [r['spell'],f"{r['caster']} / {r['intelligence']}",r['counter']])
                values += [r['troop'],r['generals'][0]['name'],' / '.join(g['name'] for g in r['generals'][1:]) or '—',
                           f"{r['soldiers']:,}",span(r['attack']),
                           '须回城：'+'/'.join(r['returning']) if r['returning'] else '同城/行动/粮草待核']
                iid=str(i); tree.insert('', 'end', iid=iid, values=values); self.records[(tree,iid)]=r
        if result['physical']:
            self.trees[0].selection_set('0'); self.details(self.trees[0])
        else:
            self.set_detail(result['message'] or '无可计算攻击编组。计谋标签为空表示没有已匹配技能的可用候选，不等于游戏中绝对不可施法。')

    def set_detail(self, text):
        self.detail.config(state='normal'); self.detail.delete('1.0','end'); self.detail.insert('1.0',text); self.detail.config(state='disabled')

    def details(self, tree):
        selected=tree.selection()
        if not selected: return
        r=self.records.get((tree,selected[0]))
        if not r: return
        self.set_detail(r['reason']+'\n双方统一按满士气100对决；不比较当前士气或恢复时间。'+
            '\n攻击严格超过按我方范围下限 > 敌方范围上限；持平不算超过。满士气同值不提供先手优势，未模拟行动顺序或实际伤害。'+
            '\n计谋按步兵、资料技能与个体智力筛选；不是已验证部队施术智力或成功率。地形、距离、天气、行动与指令是否可用需在游戏确认；未发现防计不代表没有。'+
            '\n'+('须回城重编：'+ '/'.join(r['returning']) if r['returning'] else '出兵集结与粮草仍需游戏确认。'))
