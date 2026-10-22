"""Read-only prospective formations. No orders, memory writes or skill-bit claims.

Combat: 3.5 0x477b4f/0x477c24/0x477cd0, same as unit_combat.
Morale: cached 军事作战 tutorial, prestige/4 + combat/2 (rounding unverified).
Capacity: sum of selected officers' observed soldiers, limited by current stock;
this is a planning assumption, not a verified sortie dialog prediction.
"""
from collections import Counter
from itertools import combinations
from force_relations import at_war
from officer_reference import officer_metrics
from player_view import player_id
from state_extensions import training_progress
from state_history import kind_label
from unit_target_attack import BUILD, PARAMS, client_kind, rnd, span, supported_combat_build, unit_factor

KINDS = {'infantry': ('步兵', '强化步兵', '重装步兵'),
         'cavalry': ('骑兵', '强化骑兵', '铁骑兵'),
         'bow': ('弓兵', '强弓兵', '重装弓兵')}
GRADE_FG = ('#3d4f63', '#d46512', '#6b2d9b')
TIER_KEYS = (
    ('重装步兵', 2), ('重装骑兵', 2), ('重装弓兵', 2), ('铁骑兵', 2), ('连弩', 2),
    ('强化步兵', 1), ('强化骑兵', 1), ('强弓兵', 1), ('弩兵', 1),
    ('轻骑兵', 0), ('生骑兵', 0), ('生步兵', 0),
    ('步兵', 0), ('骑兵', 0), ('弓兵', 0),
)
REQUIRED = {'infantry': None, 'cavalry': '骑马', 'bow': '弓箭'}
COMMON = {'无双', '防御', '奇袭', '收拾', '反计', '天变'}
SPELLS = {'火攻', '落石', '混乱', '天雷', '计谋'}
SIZES = ('小队', '中队', '大队')

STOCK_MAX = 10_000_000
ATTACK_TARGET_MAX = 100000

def valid(n, lo=0, hi=100000):
    return type(n) is int and lo <= n <= hi

def size_index(soldiers):
    return int(soldiers > 20000) + int(soldiers > 35000)

def training_bases(kind, raw):
    degree = training_progress(raw)
    if kind not in KINDS or degree is None:
        return None
    tier = 0 if raw < 100 else 1 if raw < 200 else 2
    name = KINDS[kind][tier]
    ub, bb, uc, bc = PARAMS[client_kind(name)]
    return {'name': name, 'training': degree,
            'unit': [unit_factor(name,s,degree) for s in range(3)],
            'building': [b + rnd(c * degree / 100) for b, c in zip(bb, bc)]}

def combat_power(generals):
    values = []
    for g in generals:
        a = g.get('attributes', {}); flags = g.get('combat_modifier_flags')
        if not valid(flags, 0, 255) or not all(valid(a.get(k), 0, 255) for k in ('lead', 'war')):
            return None
        values.append((a['lead'] + (a['lead'] * 2 // 5 if flags & 0x10 else 0),
                       a['war'] + (a['war'] * 2 // 5 if flags & 0x20 else 0)))
    if not 1 <= len(values) <= 3:
        return None
    lead = values[0][0] if len(values) == 1 else (values[0][0] + sum(v[0] for v in values[1:]) // (len(values)-1)) // 2
    return (max(10, lead) + sum(v[1] for v in values) // len(values)) // 2

def skills_for(g):
    m = officer_metrics(g)
    return set(m['skills'].split(' / ')) - {'网站技能空表'} if m['current_diplomacy'] is not None else set()

def useful_skills(kind, skills):
    return skills & (COMMON | (SPELLS | {'攻城'} if kind == 'infantry' else {REQUIRED[kind]}))

def attack_values(base, power, qualified):
    return [rnd(v * power / 150) for v in ([base] if qualified else [base // 2, base])]

def reference_attack(kind, raw, size, power):
    bases = training_bases(kind, raw)
    if not bases or size not in (0, 1, 2) or not valid(power, 0, 150):
        return None
    factor = bases['unit'][size]
    return None if factor is None else rnd(factor * power / 150)

def unit_reference_attack(unit):
    components = (unit or {}).get('target_attack_components', {})
    values = components.get('reference_unit', components.get('unit'))
    power = (unit or {}).get('basic_combat_power')
    if isinstance(values, list) and values and valid(power, 0, 150) and all(valid(v, 0, 10000) for v in values):
        return [rnd(v * power / 150) for v in values]
    fallback = (unit or {}).get('website_attack_power')
    return [fallback] if valid(fallback, 0, 10000) else None

def war_enemy_ceiling(state):
    own = player_id(state)
    if own is None:
        return None
    names = {f.get('force_id'): f.get('name') or '?' for f in (state or {}).get('entities', {}).get('lords', [])}
    best = None
    for u in (state or {}).get('entities', {}).get('field_units', []):
        if not at_war(state, u.get('owner_raw')):
            continue
        attack = unit_reference_attack(u)
        if not attack:
            continue
        value = max(attack)
        if best is None or value > best['value']:
            shown = kind_label(u.get('unit_kind')) or '部队'
            label = f"{names.get(u.get('owner_raw'), '?')} · {shown} #{u.get('unit_id', '?')}"
            best = {'value': value, 'label': label, 'unit': u}
    return best

def lowest_training_to_beat(kind, size, power, target, raw_from=0):
    if not valid(target, 0, ATTACK_TARGET_MAX) or size not in (0, 1, 2) or not valid(power, 0, 150):
        return None
    start = raw_from if valid(raw_from, 0, 300) else 0
    for raw in range(start, 301):
        attack = reference_attack(kind, raw, size, power)
        if attack is not None and attack > target:
            bases = training_bases(kind, raw)
            return {'raw': raw, 'attack': attack, 'training': bases['training'], 'name': bases['name']}
    top = reference_attack(kind, 300, size, power)
    bases = training_bases(kind, 300)
    return {'raw': None, 'attack': top, 'training': None if not bases else bases['training'],
            'name': None if not bases else bases['name']}


def training_to_beat(kind, raw_now, size, power, target):
    if not valid(raw_now, 0, 300) or not valid(target, 0, ATTACK_TARGET_MAX):
        return None
    current = reference_attack(kind, raw_now, size, power)
    if current is not None and current > target:
        return None
    step = lowest_training_to_beat(kind, size, power, target, raw_now + 1)
    if not step or step.get('raw') is None:
        return step
    return step if step['raw'] > raw_now else None

def parse_target(text):
    if text is None:
        return None
    raw = str(text).strip().replace(',', '').replace('，', '')
    if not raw:
        return None
    try:
        value = int(float(raw))
    except ValueError:
        return None
    return value if 0 <= value <= ATTACK_TARGET_MAX else None


def beats(row, target):
    return valid(target, 0, ATTACK_TARGET_MAX) and bool(row.get('attack')) and min(row['attack']) > target


def step_is_downgrade(row, step):
    if not step or step.get('raw') is None:
        return False
    now_name = row.get('troop') or ''
    dest_name = step.get('name') or ''
    if now_name and dest_name and troop_tier(dest_name) < troop_tier(now_name):
        return True
    now_train = row.get('training')
    dest_train = step.get('training')
    if now_name and dest_name == now_name and valid(now_train, 0, 100) and valid(dest_train, 0, 100):
        return dest_train < now_train
    return False


def current_step(row, raw_now=None):
    name = row.get('troop')
    train = row.get('training')
    attack = min(row['attack']) if row.get('attack') else None
    return {
        'raw': raw_now if valid(raw_now, 0, 300) else None,
        'attack': attack,
        'training': train,
        'name': name,
        'already': True,
    }


def reach_band(row, target):
    if beats(row, target):
        return 'ready'
    step = row.get('training_step')
    if row.get('source') != 'short' and step and step.get('raw') is not None:
        return 'train'
    return 'fail'


def troop_tier(name):
    text = name or ''
    for key, tier in TIER_KEYS:
        if key in text:
            return tier
    return 0


def planned_troop(row):
    step = row.get('training_step') or {}
    return step.get('name') or row.get('troop') or row.get('label') or ''


def row_grade(row):
    return troop_tier(planned_troop(row))


def names_of(row):
    return ' / '.join(g.get('name', '?') for g in row.get('generals', []))


def grade_short(step):
    if not step or step.get('raw') is None:
        return None
    if step['raw'] == 0:
        return '未训'
    return f"{step['name']} {step['training']}"


def grade_label(step):
    short = grade_short(step)
    if short is None or short == '未训':
        return short
    return f'{short}/100'


def current_grade(row):
    name = row.get('troop')
    train = row.get('training')
    if name and train is not None:
        return f'{name} {train}'
    return name or '?'


def destination_unit(row, step):
    if step_is_downgrade(row, step) or (step or {}).get('already'):
        name = row.get('troop') or ''
    else:
        name = (step or {}).get('name') or row.get('troop') or ''
    size = row.get('size')
    return f'{name}{SIZES[size]}' if size in (0, 1, 2) else name


def training_path_text(row, step):
    now = current_grade(row)
    dest = grade_short(step)
    extra = ' · 加副将凑中队' if row.get('size', 0) > row.get('leader_size', 0) else ''
    if dest is None:
        return f'{now} >> 满级也过不了'
    if dest == '未训':
        return f'{now} >> 未训就够{extra}'
    if (step or {}).get('already') or step_is_downgrade(row, step):
        return f'{now} >> 已过{extra}'
    return f'{now} >> 去到 {dest}{extra}'


def versus_current(target, row, step=None):
    return training_path_text(row, step)


def versus_training(target, row, step):
    return training_path_text(row, step)


def pick_styles(rows):
    if not rows:
        return []
    def rank(r):
        return (min(r['attack']), max(r['attack']), len(useful_skills(r['kind'], set(r['skills']))),
                -len(r['ids']), r['power'], r['soldiers'])
    best = max(rows, key=rank)
    near = [r for r in rows if min(r['attack']) >= min(best['attack']) * .8]
    complementary = max(near, key=lambda r: (len(useful_skills(r['kind'], set(r['skills']))), *rank(r), len(r['added'])))
    economical = max(rows, key=lambda r: (min(r['attack']) / len(r['ids']), *rank(r)))
    picked, seen = [], set()
    for label, row in (('攻击优先', best), ('技能互补', complementary), ('省将方案', economical)):
        key = frozenset(row['ids'])
        if key in seen:
            continue
        seen.add(key)
        picked.append(dict(row, label=label, source='current'))
    return picked


def pick_training(rows, raw_now, target):
    scored = []
    for row in rows:
        step = training_to_beat(row['kind'], raw_now, row['size'], row['power'], target)
        if not step:
            continue
        scored.append((step['raw'] is None, step['raw'] if step['raw'] is not None else 999,
                       len(row['ids']), -(step['attack'] or 0), row['ids'], row, step))
    scored.sort()
    picked, seen = [], set()
    for _, raw, _ids, _atk, _key, row, step in scored:
        key = frozenset(row['ids'])
        if key in seen:
            continue
        seen.add(key)
        item = dict(row, label=destination_unit(row, step), source='training',
                    training_step=step, versus=training_path_text(row, step))
        item['band'] = reach_band(item, target)
        item['grade'] = row_grade(item)
        picked.append(item)
        if len(picked) == 3:
            break
    return picked


def annotate_candidate(row, raw_now, target):
    if beats(row, target):
        floor = lowest_training_to_beat(row['kind'], row['size'], row['power'], target)
        if floor and floor.get('raw') == 0:
            step = floor
        else:
            step = current_step(row, raw_now)
    else:
        step = training_to_beat(row['kind'], raw_now, row['size'], row['power'], target)
        if not step or step.get('raw') is None:
            return None
    item = dict(row, training_step=step, versus=training_path_text(row, step),
                label=destination_unit(row, step), source='leader')
    item['band'] = reach_band(item, target)
    item['grade'] = row_grade(item)
    return item


def option_label(row, step):
    unit = destination_unit(row, step) if step and step.get('name') else f"{row.get('troop') or ''}{SIZES[row['size']] if row.get('size') in (0, 1, 2) else ''}"
    return ('单出 ' if len(row.get('ids') or ()) == 1 else '加副将 ') + unit


def short_row(row, top, target, prefix='单出'):
    item = dict(row, source='short', band='fail',
                label=f'{prefix} {row["troop"]}{SIZES[row["size"]]}（满级{top}不过）',
                versus=f'{current_grade(row)} >> 满级 {top}，过不了 {target}')
    item['grade'] = row_grade(item)
    return item


def fit_leader(force, leader, deputies, known, target):
    rows = []
    extras = []
    dept = list(deputies)
    if len(dept) > 14:
        dept = sorted(dept, key=lambda g: (g.get('soldiers') or 0, combat_power([g]) or 0), reverse=True)[:12]
    for kind in ('infantry', 'cavalry'):
        stock = force.get('troop_stock', {}).get(kind)
        raw_now = (force.get('armament_raw') or {}).get(kind)
        bases = training_bases(kind, raw_now)
        if not valid(stock, 1, STOCK_MAX) or not bases:
            continue
        formed = []
        solo = formation(force, kind, [leader], bases, known)
        if solo:
            formed.append(solo)
        for deputy in dept:
            row = formation(force, kind, [leader, deputy], bases, known)
            if row:
                formed.append(row)
        for left, right in combinations(dept, 2):
            row = formation(force, kind, [leader, left, right], bases, known)
            if row:
                formed.append(row)
        reachable = []
        for row in formed:
            item = annotate_candidate(row, raw_now, target)
            if item:
                item['label'] = option_label(item, item.get('training_step'))
                reachable.append(item)
        solo_hit = next((item for item in reachable if len(item['ids']) == 1), None)
        if reachable:
            def score(item):
                step = item.get('training_step') or {}
                return (len(item['ids']), 0 if beats(item, target) else 1,
                        step.get('raw') or 0, item['soldiers'], item['ids'])
            best = min(reachable, key=score)
            if solo_hit:
                rows.append(solo_hit)
            if best is not solo_hit:
                rows.append(best)
            if solo and solo_hit is None:
                top = reference_attack(kind, 300, solo['size'], solo['power'])
                if top is not None:
                    extras.append(short_row(solo, top, target, '单出'))
        else:
            hit = kind_ceiling(formed)
            if hit:
                extras.append(short_row(hit[0], hit[1], target, '单出' if len(hit[0]['ids']) == 1 else '加副将'))
    return rows + extras


def pack_units(pool_by_kind, target, stock, limit=3):
    cands = []
    for kind, (rows, raw_now) in pool_by_kind.items():
        for row in rows:
            item = annotate_candidate(row, raw_now, target)
            if item:
                cands.append(item)
    orders = (
        ('cavalry', 'infantry', 'infantry'),
        ('infantry', 'cavalry', 'infantry'),
        ('infantry', 'infantry', 'cavalry'),
        ('infantry', 'infantry', 'infantry'),
        ('cavalry', 'cavalry', 'infantry'),
        ('cavalry', 'infantry', 'cavalry'),
    )

    def run(order):
        used, left, picked = set(), dict(stock), []
        for kind in order:
            choice = None
            for row in cands:
                if row['kind'] != kind or set(row['ids']) & used:
                    continue
                if row['soldiers'] > left.get(kind, 0):
                    continue
                step = row['training_step'] or {}
                need = 0 if beats(row, target) else (step.get('raw') or 999)
                key = (need, row['soldiers'], len(row['ids']), -min(row['attack']), row['ids'])
                if choice is None or key < choice[0]:
                    choice = (key, row)
            if choice:
                row = choice[1]
                used |= set(row['ids'])
                left[kind] = left.get(kind, 0) - row['soldiers']
                picked.append(row)
                if len(picked) == limit:
                    break
        return picked

    def score(picked):
        kinds = len({row['kind'] for row in picked})
        train = sum((row.get('training_step') or {}).get('raw') or 0 for row in picked)
        return (len(picked), kinds, -train)

    best = []
    for order in orders:
        picked = run(order)
        if score(picked) > score(best):
            best = picked
    return [dict(row, label=f"{i} {row['label']}") for i, row in enumerate(best, 1)]


def kind_ceiling(rows):
    best = None
    for row in rows:
        top = reference_attack(row['kind'], 300, row['size'], row['power'])
        if top is None:
            continue
        key = (top, row['size'], -len(row['ids']), row['ids'])
        if best is None or key > best[0]:
            best = (key, row, top)
    return None if not best else (best[1], best[2])

def advise_gap(kind, raw_now, row, ceiling, pool):
    if not ceiling:
        return '当前无宣战出场部队，没有压过门槛'
    value, label = ceiling['value'], ceiling['label']
    mine = min(row['attack']) if row.get('attack') else None
    if mine is not None and mine > value:
        return f'已高于敌军最高参考 {value}（{label}）'
    same = training_to_beat(kind, raw_now, row['size'], row['power'], value)
    now = [r for r in pool if r['kind'] == kind and r.get('ids') != row.get('ids')
           and r.get('attack') and min(r['attack']) > value]
    bits = []
    if now:
        pick = min(now, key=lambda r: (len(r['ids']), -min(r['attack'])))
        bits.append(f'当前训练改配 {names_of(pick)}，参考攻击 {span(pick["attack"])}')
    if same and same['raw'] is not None:
        bits.append(f'同编制再训到 {grade_short(same)}')
    if not now:
        best = None
        for r in pool:
            if r['kind'] != kind or r.get('ids') == row.get('ids'):
                continue
            step = training_to_beat(kind, raw_now, r['size'], r['power'], value)
            if not step or step['raw'] is None:
                continue
            if same and same['raw'] is not None and step['raw'] >= same['raw']:
                continue
            key = (step['raw'], len(r['ids']), -step['attack'])
            if best is None or key < best[0]:
                best = (key, r, step)
        if best:
            _, pick, step = best
            bits.append(f'改配 {names_of(pick)}，再训到 {grade_short(step)}')
    if bits:
        return f'未超过敌军最高参考 {value}（{label}）。' + '；'.join(bits) + '。'
    top = same['attack'] if same else None
    extra = f'满级参考 {top}，' if top is not None else ''
    return f'未超过敌军最高参考 {value}（{label}）。{extra}满级也过不了'

def formation(force, kind, generals, bases, known_skills):
    if any(v is None for v in bases['unit']):return None
    capacity = sum(g['soldiers'] for g in generals)
    soldiers = min(capacity, force['troop_stock'][kind])
    if soldiers <= 0:
        return None
    size = size_index(soldiers); power = combat_power(generals)
    if power is None or not 0 <= power <= 150:
        return None
    skills = set().union(*(known_skills[g['general_id_raw']] for g in generals))
    required = REQUIRED[kind]; qualified = required is None or required in skills
    attack = attack_values(bases['unit'][size], power, True)
    siege = attack_values(bases['building'][size], power, qualified)
    lead = generals[0]; leader_power = combat_power([lead])
    leader_size = size_index(min(lead['soldiers'], force['troop_stock'][kind]))
    leader_qualified = required is None or required in known_skills[lead['general_id_raw']]
    baseline = attack_values(bases['unit'][leader_size], leader_power, True)
    added = useful_skills(kind, skills - known_skills[lead['general_id_raw']])
    prestige = force.get('prestige')
    morale = min(100, max(0, prestige / 4 + power / 2)) if valid(prestige, 0, 1000) else None
    returning = [g['name'] for g in generals if g.get('status_code') == 2]
    unknown = [g['name'] for g in generals if officer_metrics(g)['current_diplomacy'] is None]
    notes = []
    if size > leader_size:
        notes.append(SIZES[leader_size] + '→' + SIZES[size])
    notes.append(f'战力 {leader_power}→{power}（{power-leader_power:+d}）')
    notes.append('攻击 ' + span(baseline) + '→' + span(attack))
    if added:
        notes.append('副将补 ' + '/'.join(sorted(added)))
    if capacity > soldiers:
        notes.append('受现有库存限制')
    return {'kind': kind, 'troop': bases['name'], 'generals': generals,
            'ids': tuple(g['general_id_raw'] for g in generals), 'capacity': capacity,
            'soldiers': soldiers, 'size': size, 'power': power, 'morale': morale,
            'attack': attack, 'siege': siege, 'baseline': baseline,
            'leader_power': leader_power, 'leader_size': leader_size,
            'skills': sorted(skills), 'added': sorted(added), 'unknown': unknown,
            'qualified': qualified, 'required': required, 'returning': returning,
            'reason': '；'.join(notes), 'training': bases['training']}

KIND_SHORT = {'infantry': '步', 'cavalry': '骑'}

def leader_solo_attacks(force, leader, known):
    attacks = {}
    for kind in ('infantry', 'cavalry'):
        stock = force.get('troop_stock', {}).get(kind)
        bases = training_bases(kind, (force.get('armament_raw') or {}).get(kind))
        if not valid(stock, 1, STOCK_MAX) or not bases:
            continue
        row = formation(force, kind, [leader], bases, known)
        if row and row.get('attack'):
            attacks[kind] = min(row['attack'])
    return attacks

def rank_leaders(force, pool, known):
    ranked = []
    for g in pool:
        attacks = leader_solo_attacks(force, g, known)
        if attacks:
            kind = max(attacks, key=attacks.get)
            attack = attacks[kind]
        else:
            kind, attack = None, 0
        ranked.append({
            'id': g['general_id_raw'],
            'name': g.get('name') or '?',
            'soldiers': g.get('soldiers') or 0,
            'attack': attack,
            'attack_kind': kind,
            'attacks': attacks,
        })
    ranked.sort(key=lambda row: (-row['attack'], -row['soldiers'], row['name'], row['id']))
    return ranked

def recommend(state, include_field=True, all_candidates=False, target=None, leader_id=None):
    out = {'rows': [], 'force': None, 'message': '', 'eligible': 0, 'enemy': None}
    fid = player_id(state)
    if fid is None:
        out['message'] = '我方身份未确认，暂不推荐'; return out
    if not supported_combat_build(state.get('build_sha256')):
        out['message'] = '客户端版本未匹配，暂不计算攻击推荐'; return out
    entities = state.get('entities', {})
    forces = [f for f in entities.get('lords', []) if f.get('force_id') == fid]
    if len(forces) != 1:
        out['message'] = '我方势力记录缺失或不唯一'; return out
    force = out['force'] = forces[0]
    all_g = entities.get('generals', [])
    counts = Counter(g.get('general_id_raw') for g in all_g)
    deployed = {gid for u in entities.get('field_units', []) for gid in u.get('general_ids', []) if gid is not None}
    pool = [g for g in all_g if g.get('owner_raw') == fid
            and valid(g.get('general_id_raw')) and counts[g['general_id_raw']] == 1
            and g.get('status_code') in ((0, 2) if include_field else (0,))
            and (include_field or g['general_id_raw'] not in deployed)
            and valid(g.get('soldiers'), 1) and combat_power([g]) is not None]
    # Include field occupancy even when a transient status byte says otherwise.
    pool = [dict(g, status_code=2) if g['general_id_raw'] in deployed else g for g in pool]
    if not pool:
        out['leaders'] = []
        out['eligible'] = 0
        out['message'] = '没有可计算的所属武将（负伤、身份或统武缺失者不参与）'; return out
    known = {g['general_id_raw']: skills_for(g) for g in pool}
    out['leaders'] = rank_leaders(force, pool, known)
    out['eligible'] = len(pool)
    # Bounded per-kind pool: preserve capacity, combat and skill specialists.
    # Ordinary player rosters are enumerated completely (up to 32 officers).
    out['message'] = '步/骑对部队用网站计算器。弓兵无网站参数，仍用原表基值，暂不列入攻击推荐。'
    parsed = None if all_candidates else parse_target(target)
    if all_candidates:
        for kind in ('infantry', 'cavalry'):
            stock = force.get('troop_stock', {}).get(kind)
            bases = training_bases(kind, force.get('armament_raw', {}).get(kind))
            if not valid(stock, 1, STOCK_MAX) or not bases:
                continue
            candidates = pool
            if len(pool) > 32:
                picked = {}
                for key in (lambda g:g['soldiers'], lambda g:combat_power([g]),
                            lambda g:len(useful_skills(kind, known[g['general_id_raw']]))):
                    for g in sorted(pool, key=key, reverse=True)[:10]:picked[g['general_id_raw']] = g
                candidates = list(picked.values())
                out['message'] += ' 武将较多：按带兵、统武和技能筛选候选，非全局穷举最优'
            for n in (1, 2, 3):
                for group in combinations(candidates, n):
                    for lead in group:
                        ordered = [lead] + [g for g in group if g is not lead]
                        row = formation(force, kind, ordered, bases, known)
                        if row:
                            out['rows'].append(row)
        if not out['rows'] and '库存或训练' not in out['message']:
            out['message'] += ' 当前兵种库存或训练数据不足' if out['message'] else '当前兵种库存或训练数据不足'
        return out
    if parsed is None:
        out['message'] += ' 请先选主将，再填写敌军部队攻击。'
        return out
    if leader_id is None:
        out['message'] += ' 请先选主将，再按敌军攻击配这名主将的步/骑。'
        return out
    leader = next((g for g in pool if g.get('general_id_raw') == leader_id), None)
    if leader is None:
        out['message'] += ' 所选主将不在可出名单。'
        return out
    out['enemy'] = {'value': parsed, 'label': '填写数值'}
    out['leader'] = {'id': leader_id, 'name': leader.get('name') or '?'}
    out['message'] += f' 主将 {leader.get("name") or "?"}，对照 {parsed}。能单出则单出；小队不够再加副将凑中队。'
    deputies = [g for g in pool if g.get('general_id_raw') != leader_id]
    fitted = fit_leader(force, leader, deputies, known, parsed)
    out['rows'] = fitted
    if not fitted and '库存或训练' not in out['message']:
        out['message'] += ' 这名主将下步/骑满级也过不了（网站口径）。'
    elif any(row.get('source') == 'short' for row in fitted):
        out['message'] += ' 标了「不过」的兵种：单出或加副将满训仍过不了。'
    return out
