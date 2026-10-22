"""All-force training and skill comparison. Read-only; does not write the game."""
import math
import tkinter as tk
from tkinter import ttk

from city_talent import lead_war_total, listed_skill_count
from force_relations import ALLY_BACKGROUND, ALLY_FOREGROUND, WAR_BACKGROUND, WAR_FOREGROUND, allied, at_war, force_priority
from force_strength import unit_attack_value
from force_troop_totals import force_troop_sample, unit_kind
from military_summary import troop_info
from player_view import player_id
from preparation_model import training_bases

BG, INK, MUTED = '#f7f4ea', '#302c22', '#675937'
KINDS = ('infantry', 'cavalry', 'bow')
KIND_PREFIX = {'infantry': 'inf', 'cavalry': 'cav', 'bow': 'bow'}
SKILL_COLS = (
    ('ride', '骑', frozenset({'骑马'})),
    ('bow_skill', '弓', frozenset({'弓箭'})),
    ('ambush', '伏', frozenset({'埋伏', '伏兵'})),
)
COLS = [
    ('name', '势力', 70),
    ('best_pol', '练兵效率', 130),
    ('best_blade', '统武', 140),
    ('cav_power', '骑战力', 120),
    ('inf_train', '步训练度', 130),
    ('cav_train', '骑训练度', 130),
    ('bow_train', '弓训练度', 120),
    ('inf_soldiers', '步兵数', 80),
    ('cav_soldiers', '骑兵数', 80),
    ('bow_soldiers', '弓兵数', 80),
    ('unit_count', '部队数', 70),
    ('unit_cav', '最高骑战力', 140),
]
COLS.extend((key, title, 40) for key, title, _names in SKILL_COLS)
NAMED = {'best_pol': 'trainer', 'best_blade': 'blade_name', 'cav_power': 'cav_power_name'}
NOTE = (
    '练兵效率就是该国所属将最高政治（自定义将可超过100），格内写政值与将名；不看库存档位，也不看魅力。'
    '魅力只进外交（政治＋魅力）。'
    '统武是所属将里统率＋武力的最高合计，格内写合计与将名。'
    '点一行后，对方有将超过我方最高统武时列出那些将；我方更高时，列出我方超过对方最高统武的将。'
    '骑战力是统武最高的将单独领骑兵、不计副将，按该国当前骑兵等级和训练度取最高一档攻击系数。'
    '步兵数、骑兵数、弓兵数是城里该兵种加上出征部队的兵数。'
    '部队数是该势力当前出征部队的支数。'
    '最高骑战力是这些部队里骑兵对部队攻击系数的最大值，格内写系数与主将；没有骑兵或系数未算出则空。不是统武推算的单骑战力。'
    '骑/弓/伏是所属将里网站资料具备骑马、弓箭、埋伏或伏兵的人数；全技能计入三项。未同名且五维一致的不计入。'
    '点列头排序，点一行切到该势力。'
)


def owned_officers(state, force_id):
    return [g for g in ((state or {}).get('entities') or {}).get('generals') or [] if g.get('owner_raw') == force_id]


def officer_politics(officer):
    value = (officer or {}).get('attributes', {}).get('pol')
    return value if type(value) is int and 0 <= value <= 255 else None


def trainer(officers):
    best = None
    for officer in officers or []:
        value = officer_politics(officer)
        if value is None:
            continue
        if best is None or value > best['best_pol']:
            best = {'best_pol': value, 'trainer': officer.get('name') or '?'}
    return best or {'best_pol': None, 'trainer': None}


def best_politics(officers):
    return trainer(officers)['best_pol']


SWORD_ID = 18
HORSE_ID = 19
BOOK_ID = 20


def boost_stat(value):
    return math.floor(value * 1.4 + 0.5)


def boosted_peaks(officers, card_ids):
    """Apply 倚天剑/赤兔马/孙子兵法 to the highest lead, war, or politics, then take the new peaks."""
    ids = set(card_ids or ())
    rows = []
    for officer in officers or []:
        attrs = (officer or {}).get('attributes') or {}
        lead, war, pol = attrs.get('lead'), attrs.get('war'), attrs.get('pol')
        combat = type(lead) is int and type(war) is int and 0 <= lead <= 255 and 0 <= war <= 255
        politics = type(pol) is int and 0 <= pol <= 255
        rows.append({
            'name': officer.get('name') or '?',
            'lead': lead if combat else None,
            'war': war if combat else None,
            'pol': pol if politics else None,
            'lead_boost': False,
            'war_boost': False,
            'pol_boost': False,
        })
    def lift(key, flag, present):
        if not present:
            return
        known = [row for row in rows if row[key] is not None]
        if not known:
            return
        top = max(row[key] for row in known)
        for row in known:
            if row[key] == top:
                row[key] = boost_stat(row[key])
                row[flag] = True
    lift('lead', 'lead_boost', SWORD_ID in ids)
    lift('war', 'war_boost', HORSE_ID in ids)
    lift('pol', 'pol_boost', BOOK_ID in ids)
    blade = None
    for row in rows:
        if row['lead'] is None:
            continue
        total = row['lead'] + row['war']
        boosted = row['lead_boost'] or row['war_boost']
        if blade is None or (total, boosted) > (blade['value'], blade['boosted']):
            blade = {'value': total, 'name': row['name'], 'boosted': boosted}
    politics = None
    for row in rows:
        if row['pol'] is None:
            continue
        if politics is None or (row['pol'], row['pol_boost']) > (politics['value'], politics['boosted']):
            politics = {'value': row['pol'], 'name': row['name'], 'boosted': row['pol_boost']}
    return {
        'blade': None if blade is None else blade['value'],
        'blade_name': None if blade is None else blade['name'],
        'blade_boosted': False if blade is None else blade['boosted'],
        'pol': None if politics is None else politics['value'],
        'pol_name': None if politics is None else politics['name'],
        'pol_boosted': False if politics is None else politics['boosted'],
    }


def solo_ability(officer):
    """One general's combat ability. Deputies are not folded in."""
    attrs = (officer or {}).get('attributes') or {}
    lead, war = attrs.get('lead'), attrs.get('war')
    if type(lead) is not int or type(war) is not int or not (0 <= lead <= 255 and 0 <= war <= 255):
        return None
    flags = (officer or {}).get('combat_modifier_flags')
    if type(flags) is int and 0 <= flags <= 255:
        if flags & 0x10:
            lead += lead * 2 // 5
        if flags & 0x20:
            war += war * 2 // 5
    return (max(10, lead) + war) // 2


def cavalry_strike(ability, raw):
    bases = training_bases('cavalry', raw)
    if ability is None or not bases:
        return None
    factor = max((value for value in bases['unit'] if type(value) is int), default=None)
    if factor is None:
        return None
    return math.floor(ability * factor / 150 + 0.5)


def peak_cavalry(officers, raw):
    ceiling = blade_officer(officers)['best_blade']
    if ceiling is None:
        return {'cav_power': None, 'cav_power_name': None}
    best = None
    for officer in officers or []:
        if lead_war_total(officer) != ceiling:
            continue
        value = cavalry_strike(solo_ability(officer), raw)
        if value is None:
            continue
        if best is None or value > best['cav_power']:
            best = {'cav_power': value, 'cav_power_name': officer.get('name') or '?'}
    return best or {'cav_power': None, 'cav_power_name': None}


def blade_officer(officers):
    best = None
    for officer in officers or []:
        value = lead_war_total(officer)
        if value is None:
            continue
        if best is None or value > best['best_blade']:
            best = {'best_blade': value, 'blade_name': officer.get('name') or '?'}
    return best or {'best_blade': None, 'blade_name': None}


def training_text(kind, raw):
    info = troop_info(kind, raw)
    if info['training'] is None:
        return None
    return f"{info['name']} {info['training']}/100"


def field_units(state, force_id):
    return [row for row in ((state or {}).get('entities') or {}).get('field_units') or []
            if row.get('owner_raw') == force_id]


def unit_lead_name(state, unit):
    inputs = (unit or {}).get('combat_inputs') or []
    if inputs and inputs[0].get('name'):
        return inputs[0]['name']
    ids = [gid for gid in ((unit or {}).get('general_ids') or []) if isinstance(gid, int)]
    if not ids:
        return None
    for officer in ((state or {}).get('entities') or {}).get('generals') or []:
        if officer.get('general_id_raw') == ids[0]:
            return officer.get('name')
    return None


def peak_unit_cavalry(state, units):
    """Highest cavalry attack coefficient among this force's field units."""
    best = None
    for unit in units or []:
        if unit_kind(unit) != 'cavalry':
            continue
        value = unit_attack_value(unit)
        if value is None:
            continue
        if best is None or value > best['value']:
            best = {'value': value, 'name': unit_lead_name(state, unit)}
    if best is None:
        return {'unit_cav': None, 'unit_cav_name': None}
    shown = int(best['value']) if best['value'] == int(best['value']) else best['value']
    return {'unit_cav': shown, 'unit_cav_name': best['name']}


def summarize(state):
    entities = (state or {}).get('entities') or {}
    rows = []
    for force in entities.get('lords') or []:
        fid = force.get('force_id')
        officers = owned_officers(state, fid)
        raws = force.get('armament_raw') or {}
        pick = trainer(officers)
        edge = blade_officer(officers)
        cavalry = peak_cavalry(officers, raws.get('cavalry'))
        row = {
            'force_id': fid,
            'name': force.get('name') or '?',
            'best_pol': pick['best_pol'],
            'trainer': pick['trainer'],
            'best_blade': edge['best_blade'],
            'blade_name': edge['blade_name'],
            'cav_power': cavalry['cav_power'],
            'cav_power_name': cavalry['cav_power_name'],
            'tag': ('player' if fid == player_id(state) else
                    'war' if at_war(state, fid) else
                    'ally' if allied(state, fid) else 'other'),
        }
        units = field_units(state, fid)
        cavalry_peak = peak_unit_cavalry(state, units)
        row['unit_count'] = len(units)
        row['unit_cav'] = cavalry_peak['unit_cav']
        row['unit_cav_name'] = cavalry_peak['unit_cav_name']
        sample = force_troop_sample(state, fid)
        for kind in KINDS:
            row[f'{KIND_PREFIX[kind]}_train'] = training_text(kind, raws.get(kind))
            kind_row = sample['kinds'][kind]
            store, out = kind_row['warehouse'], kind_row['field'] or 0
            row[f'{KIND_PREFIX[kind]}_soldiers'] = None if store is None and not out else (store or 0) + out
        for key, _title, names in SKILL_COLS:
            row[key] = listed_skill_count(officers, names)
        rows.append(row)
    return rows


def _sort_key(row, key):
    value = row.get(key)
    if key == 'name':
        return (0, str(value or ''), row.get('force_id') or 0)
    if value is None:
        return (0, 0, row.get('force_id') or 0)
    if type(value) is str:
        return (1, value, row.get('force_id') or 0)
    return (1, value, row.get('force_id') or 0)


def _ahead(officers, ceiling):
    found = []
    for officer in officers:
        value = lead_war_total(officer)
        if value is not None and value > ceiling:
            found.append((value, officer.get('name') or '?'))
    found.sort(key=lambda item: (-item[0], item[1]))
    return found


def _mark(value, name):
    return f'{value} {name}' if name else str(value)


def exceed_player(state, force_id):
    """Name the generals on the side whose 统武 is strictly higher."""
    own = player_id(state)
    if own is None:
        return '未确认我方，不能比较统武。'
    ours = blade_officer(owned_officers(state, own))
    ceiling, ceiling_name = ours['best_blade'], ours['blade_name']
    if ceiling is None:
        return '我方没有可算的统武。'
    mark = _mark(ceiling, ceiling_name)
    if force_id == own:
        return f'当前是我方。最高统武 {mark}'
    if force_id is None:
        return f'我方最高统武 {mark}。点一个势力，列出统武更高的一侧。'
    ahead = _ahead(owned_officers(state, force_id), ceiling)
    if ahead:
        listed = '、'.join(f'{value} {name}' for value, name in ahead)
        return f'超过我方最高统武 {mark}：{listed}'
    theirs = blade_officer(owned_officers(state, force_id))
    their_ceiling, their_name = theirs['best_blade'], theirs['blade_name']
    if their_ceiling is None:
        return f'对方没有可算的统武。我方最高统武 {mark}'
    their_mark = _mark(their_ceiling, their_name)
    ours_ahead = _ahead(owned_officers(state, own), their_ceiling)
    if not ours_ahead:
        return f'没有将超过对方最高统武 {their_mark}'
    listed = '、'.join(f'{value} {name}' for value, name in ours_ahead)
    return f'我方超过对方最高统武 {their_mark}：{listed}'


def _cell(value, key, row=None):
    if key == 'unit_cav':
        if value is None:
            return '—'
        name = (row or {}).get('unit_cav_name')
        return f'{value} {name}' if name else value
    if key in NAMED:
        if value is None:
            return '未知'
        name = (row or {}).get(NAMED[key])
        return f'{value} {name}' if name else value
    if value is None:
        return '未知' if key.endswith('_train') else '—'
    if key.endswith('_soldiers') and type(value) is int:
        return f'{value:,}'
    return value


class ForceCompare(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.rows = {}
        self.order = None
        self.busy = False
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        self.note = tk.Label(self, text=NOTE, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=1050, font=(face, 10))
        self.note.pack(fill='x', padx=8, pady=(8, 4))
        box = tk.Frame(self, bg=BG)
        box.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(box, columns=[k for k, _, _ in COLS], show='headings')
        for key, title, width in COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort(k))
            self.tree.column(key, width=width, stretch=False)
        y = ttk.Scrollbar(box, command=self.tree.yview)
        x = ttk.Scrollbar(box, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        x.pack(side='bottom', fill='x')
        y.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.above = tk.Label(self, text='', bg=BG, fg=INK, anchor='w', justify='left', wraplength=1050, font=(face, 12))
        self.above.pack(fill='x', padx=8, pady=(6, 8))
        self.tree.tag_configure('player', background='#f4df96', foreground='#85291c')
        self.tree.tag_configure('war', background=WAR_BACKGROUND, foreground=WAR_FOREGROUND)
        self.tree.tag_configure('ally', background=ALLY_BACKGROUND, foreground=ALLY_FOREGROUND)
        self.tree.bind('<<TreeviewSelect>>', self.choose)
        self.bind('<Configure>', lambda e: (
            self.note.configure(wraplength=max(240, e.width - 24)),
            self.above.configure(wraplength=max(240, e.width - 24)),
        ))

    def sort(self, key):
        self.order = (key, not self.order[1] if self.order and self.order[0] == key else True)
        self.refresh()

    def refresh(self):
        if not getattr(self.app, 'doc', None):
            return
        rows = summarize(self.app.doc)
        if self.order:
            key, reverse = self.order
            rows.sort(key=lambda row: _sort_key(row, key), reverse=reverse)
        else:
            rows.sort(key=lambda row: (force_priority(self.app.doc, row.get('force_id')), row.get('force_id') or 0))
        self.busy = True
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        selected = None
        for row in rows:
            iid = str(row['force_id'])
            vals = [_cell(row[k], k, row) for k, _, _ in COLS]
            self.tree.insert('', 'end', iid=iid, values=vals, tags=(row['tag'],))
            self.rows[iid] = row
            if row['force_id'] == getattr(self.app, 'sel', None):
                selected = iid
        if selected:
            self.tree.selection_set(selected)
            self.tree.see(selected)
        self.above.configure(text=exceed_player(self.app.doc, getattr(self.app, 'sel', None)))
        self.busy = False

    def choose(self, _=None):
        if self.busy or not getattr(self.app, 'doc', None):
            return
        selection = self.tree.selection()
        if not selection:
            return
        try:
            fid = int(selection[0])
        except (TypeError, ValueError):
            return
        if fid == getattr(self.app, 'sel', None):
            return
        self.app.sel = fid
        if hasattr(self.app, 'refresh_force_art'):
            self.app.refresh_force_art()
        if hasattr(self.app, 'force_tree') and self.app.force_tree.exists(str(fid)):
            self.app.force_tree.selection_set(str(fid))
        if hasattr(self.app, 'render_detail'):
            self.app.render_detail()
