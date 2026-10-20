"""Prospective player-only formations, with explicit comparison and conditions."""
import json
import tkinter as tk
from tkinter import ttk
from battle_model import freshness
from player_view import player_id
from preparation_model import GRADE_FG, recommend, SIZES, span

BG = '#f7f4ea'
FG = '#302c22'

class PreparationPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app; self.signature = None; self.rows = {}; self.result = {}
        bar = tk.Frame(self, bg=BG); bar.pack(fill='x', padx=8, pady=5)
        self.include_field = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text='含出阵将（须回城重编）', variable=self.include_field,
                       command=self.refresh, bg=BG, fg=FG).pack(side='left')
        tk.Label(bar, text='主将', bg=BG, fg=FG).pack(side='left', padx=(14, 4))
        self.leader_var = tk.StringVar()
        self.leader_ids = []
        self.leader_box = ttk.Combobox(bar, textvariable=self.leader_var, width=22, state='readonly')
        self.leader_box.pack(side='left')
        self.leader_box.bind('<<ComboboxSelected>>', lambda _e=None: self.refresh())
        tk.Label(bar, text='敌军部队攻击', bg=BG, fg=FG).pack(side='left', padx=(14, 4))
        self.target = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.target, width=8)
        entry.pack(side='left')
        entry.bind('<Return>', lambda _e=None: self.refresh())
        tk.Button(bar, text='按此将配兵', command=self.refresh, bg=BG).pack(side='left', padx=6)
        self.status = tk.Label(self, bg=BG, fg=FG, anchor='w', justify='left', wraplength=650)
        self.status.pack(fill='x', padx=8)
        self.note = tk.Label(self, text='主将按单出部队攻击力从高到低排。先选主将，再填敌军攻击。行底：绿已过、黄可训或加副将、红过不了。兵种字色：基础灰、强化橙、重装/铁骑紫。弓暂不推荐。',
                             bg=BG, fg='#786e56', justify='left', anchor='w', wraplength=650)
        self.note.pack(fill='x', padx=8, pady=5)
        frame = tk.Frame(self, bg=BG); frame.pack(fill='both', expand=True, padx=6)
        columns = [('role','部队',120), ('troop','兵种',90), ('leader','主将',85),
                   ('deputies','副将',155), ('soldiers','拟带兵≈',85), ('size','规模',55),
                   ('morale','出兵士气≈',85), ('power','编组战力*',85), ('attack','部队攻击力*',130),
                   ('versus','训练',320),
                   ('siege','攻城攻击≈',95), ('reason','相对主将单出：收益 / 代价',420),
                   ('condition','重编条件',220)]
        face = getattr(self.app, 'face', None) or 'PingFang SC'
        style = ttk.Style(self)
        style.configure('Prep.Treeview', background=BG, fieldbackground=BG, foreground=FG, font=(face, 11))
        style.map('Prep.Treeview', background=[], foreground=[])
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', height=7, style='Prep.Treeview')
        for key, title, width in columns:
            self.tree.heading(key, text=title); self.tree.column(key, width=width, minwidth=45, stretch=False)
        order=[c[0] for c in columns];order.remove('attack');order.insert(order.index('troop')+1,'attack')
        order.remove('versus');order.insert(order.index('attack')+1,'versus');self.tree.configure(displaycolumns=order)
        self.tree.grid(row=0, column=0, sticky='nsew')
        y = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview); y.grid(row=0, column=1, sticky='ns')
        x = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview); x.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        self.tree.tag_configure('ready', background='#d5f1d5')
        self.tree.tag_configure('train', background='#fff0bd')
        self.tree.tag_configure('fail', background='#f8d6d3')
        for grade, color in enumerate(GRADE_FG):
            self.tree.tag_configure(f'grade{grade}', foreground=color)
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.details = tk.Text(self, height=9, wrap='word', bg=BG, fg=FG, relief='flat', font=(face, 10))
        self.details.pack(fill='x', padx=8, pady=5); self.details.configure(state='disabled')
        self.bind('<Configure>', lambda e: [label.configure(wraplength=max(250,e.width-24)) for label in (self.note,self.status)])

    def selected_leader_id(self):
        labels = list(self.leader_box.cget('values') or ())
        try:
            index = labels.index(self.leader_var.get())
        except ValueError:
            return None
        return self.leader_ids[index] if 0 <= index < len(self.leader_ids) else None

    def load_leaders(self, leaders):
        prev_id = self.selected_leader_id()
        labels, ids = [], []
        for row in leaders or []:
            attack = row.get('attack')
            kind = {'infantry': '步', 'cavalry': '骑'}.get(row.get('attack_kind'))
            if type(attack) is int and kind:
                labels.append(f"{row.get('name') or '?'} {attack}（{kind}）")
            else:
                labels.append(f"{row.get('name') or '?'}（{row.get('soldiers') or 0:,}）")
            ids.append(row.get('id'))
        self.leader_ids = ids
        self.leader_box.configure(values=labels)
        if prev_id in ids:
            self.leader_var.set(labels[ids.index(prev_id)])
        else:
            self.leader_var.set('')

    def refresh(self):
        state = self.app.doc or {}; fid = player_id(state); entities = state.get('entities', {})
        signature = json.dumps([fid, state.get('build_sha256'), state.get('player_identity'),
                                [f for f in entities.get('lords',[]) if f.get('force_id') == fid],
                                entities.get('generals',[]),
                                [f.get('diplomacy_relations') for f in entities.get('lords',[]) if f.get('force_id')==fid],
                                [u.get('general_ids',[]) for u in entities.get('field_units',[])],
                                [(u.get('owner_raw'),u.get('unit_id'),u.get('unit_kind'),u.get('size_index'),
                                  u.get('website_attack_power'),u.get('basic_combat_power'),
                                  u.get('target_attack_components'))
                                 for u in entities.get('field_units',[])],
                                self.include_field.get(), self.target.get(), self.selected_leader_id()], sort_keys=True, ensure_ascii=False)
        if signature != self.signature:
            selection = self.tree.selection()
            previous = self.rows.get(selection[0]) if selection else None
            key = (previous['kind'], previous['ids'], previous['label']) if previous else None
            self.result = recommend(state, self.include_field.get(), target=self.target.get(),
                                    leader_id=self.selected_leader_id())
            self.load_leaders(self.result.get('leaders'))
            self.signature = signature
            self.tree.delete(*self.tree.get_children()); self.rows = {}
            chosen = None
            for i, r in enumerate(self.result['rows']):
                iid = str(i); self.rows[iid] = r
                condition = ('须回城：' + '/'.join(r['returning'])) if r['returning'] else '现役；集结/出兵条件待核'
                values = (r['label'], r['troop'], r['generals'][0]['name'],
                          ' / '.join(g['name'] for g in r['generals'][1:]) or '—',
                          f"{r['soldiers']:,}", SIZES[r['size']],
                          f"{r['morale']:.1f}" if r['morale'] is not None else '未知',
                          r['power'], span(r['attack']), r.get('versus') or '—', span(r['siege']), r['reason'], condition)
                band = r.get('band') if r.get('band') in ('ready', 'train', 'fail') else 'fail'
                grade = r.get('grade') if r.get('grade') in (0, 1, 2) else 0
                self.tree.insert('', 'end', iid=iid, values=values, tags=(band, f'grade{grade}'))
                if (r['kind'],r['ids'],r['label']) == key:chosen = iid
            if self.rows:
                self.tree.selection_set(chosen or next(iter(self.rows))); self.show_details()
            else:self.set_details(self.result['message'])
        force = self.result.get('force') or {}
        self.status.configure(text=f"我军 {force.get('name','未确认')} · {freshness(state)} · 候选 {self.result.get('eligible',0)} 将 · 绿已过 / 黄可训或加副将 / 红过不了\n" + self.result.get('message',''))

    def set_details(self, text):
        self.details.configure(state='normal'); self.details.delete('1.0','end'); self.details.insert('1.0',text); self.details.configure(state='disabled')

    def show_details(self, _event=None):
        selected = self.tree.selection()
        if not selected or selected[0] not in self.rows:return
        r = self.rows[selected[0]]; f = self.result['force']
        skills = ' / '.join(r['skills']) or '暂无核定技能资料'
        lines = [r['reason'], '本页为网站参考尺度，不能直接与地图攻击指数比较。']
        if r.get('versus'):
            lines.append(r['versus'] + ' 网站口径对照，不含防御、地形、士气，不是实战胜负。')
        lines += [
                 f"带兵合计 {r['capacity']:,}，现有库存 {f['troop_stock'][r['kind']]:,} → 拟带 {r['soldiers']:,}（估算）。小队≤20,000；中队20,001–35,000；大队>35,000。",
                 f"出兵士气参考＝信望 {f.get('prestige','未知')}÷4＋战力 {r['power']}÷2，上限100；游戏取整待核。出阵后的实际士气见‘部队’标签。",
                 f"训练按当前势力 {r['training']}/100；对部队攻击为网站（基础＋规模＋武装加成）×战斗能力÷150参考，不含敌防御、地形、士气和宝物，非实际扣血。",
                 '编成技能（同名且五维一致的网站资料）：' + skills]
        if r['unknown']:lines.append('技能未核定：'+'/'.join(r['unknown'])+'；不能据此判断无技能。')
        if r['required']:
            lines.append(('按资料具备' if r['qualified'] else '未确认')+r['required']+'；；网站攻击公式不额外做技能折半，攻城范围仍为独立静态参考。')
        if r['kind'] == 'infantry':
            lines.append('步兵互补考虑火攻、落石、混乱、天雷和计谋；实际可用仍受地形与战场条件限制。')
        else:lines.append('骑/弓方案不把步兵主动计谋计入收益；优先兵种技能与防护互补，携带计谋将不视为解锁骑兵计谋。')
        if set(r['skills']) & {'无双','防御','奇袭'}:
            lines.append('原版核对：奇袭按双方最高智力判定，最高25%；无双在允许时受击触发12.5%，该次防守士气项×1.5；均非固定25%攻击加成。')
        lines.append('条件：'+('、'.join(r['returning'])+'须回城重编；' if r['returning'] else '')+'所属不等于已集结；同城、行动与粮草需在游戏出兵画面确认。')
        lines.append('士气/技能依据：sanguoyouxi.vip/xsjc/军事作战.htm；容量为规划假设，技能不是实时内存位。')
        self.set_details('\n'.join(lines))
