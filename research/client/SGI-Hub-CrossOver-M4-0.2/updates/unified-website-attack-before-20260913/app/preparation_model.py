"""Read-only prospective formations. No orders, memory writes or skill-bit claims.

Combat: 3.5 0x477b4f/0x477c24/0x477cd0, same as unit_combat.
Morale: cached 军事作战 tutorial, prestige/4 + combat/2 (rounding unverified).
Capacity: sum of selected officers' observed soldiers, limited by current stock;
this is a planning assumption, not a verified sortie dialog prediction.
"""
from collections import Counter
from itertools import combinations
from officer_reference import officer_metrics
from player_view import player_id
from state_extensions import training_progress
from unit_target_attack import BUILD, PARAMS, rnd, span, supported_combat_build

KINDS = {'infantry': ('步兵', '强化步兵', '重装步兵'),
         'cavalry': ('骑兵', '强化骑兵', '重装骑兵'),
         'bow': ('弓兵', '强弓兵', '重装弓兵')}
REQUIRED = {'infantry': None, 'cavalry': '骑马', 'bow': '弓箭'}
COMMON = {'无双', '防御', '奇袭', '收拾', '反计', '天变'}
SPELLS = {'火攻', '落石', '混乱', '天雷', '计谋'}
SIZES = ('小队', '中队', '大队')

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
    ub, bb, uc, bc = PARAMS[name]
    return {'name': name, 'training': degree,
            'unit': [b + rnd(c * degree / 100) for b, c in zip(ub, uc)],
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

def formation(force, kind, generals, bases, known_skills):
    capacity = sum(g['soldiers'] for g in generals)
    soldiers = min(capacity, force['troop_stock'][kind])
    if soldiers <= 0:
        return None
    size = size_index(soldiers); power = combat_power(generals)
    if power is None or not 0 <= power <= 150:
        return None
    skills = set().union(*(known_skills[g['general_id_raw']] for g in generals))
    required = REQUIRED[kind]; qualified = required is None or required in skills
    attack = attack_values(bases['unit'][size], power, qualified)
    siege = attack_values(bases['building'][size], power, qualified)
    lead = generals[0]; leader_power = combat_power([lead])
    leader_size = size_index(min(lead['soldiers'], force['troop_stock'][kind]))
    leader_qualified = required is None or required in known_skills[lead['general_id_raw']]
    baseline = attack_values(bases['unit'][leader_size], leader_power, leader_qualified)
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

def recommend(state, include_field=True, all_candidates=False):
    out = {'rows': [], 'force': None, 'message': '', 'eligible': 0}
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
    pool.sort(key=lambda g: g['general_id_raw'])
    out['eligible'] = len(pool)
    if not pool:
        out['message'] = '没有可计算的所属武将（负伤、身份或统武缺失者不参与）'; return out
    known = {g['general_id_raw']: skills_for(g) for g in pool}
    # Bounded per-kind pool: preserve capacity, combat and skill specialists.
    # Ordinary player rosters are enumerated completely (up to 32 officers).
    for kind in KINDS:
        stock = force.get('troop_stock', {}).get(kind)
        bases = training_bases(kind, force.get('armament_raw', {}).get(kind))
        if not valid(stock, 1) or not bases:
            continue
        candidates = pool
        if len(pool) > 32:
            picked = {}
            for key in (lambda g:g['soldiers'], lambda g:combat_power([g]),
                        lambda g:len(useful_skills(kind, known[g['general_id_raw']]))):
                for g in sorted(pool, key=key, reverse=True)[:10]:picked[g['general_id_raw']] = g
            candidates = list(picked.values())
            out['message'] = '武将较多：按带兵、统武和技能筛选候选，非全局穷举最优'
        rows = []
        for n in (1, 2, 3):
            for group in combinations(candidates, n):
                for leader in group:
                    ordered = [leader] + [g for g in group if g is not leader]
                    row = formation(force, kind, ordered, bases, known)
                    if row:rows.append(row)
        if not rows:continue
        if all_candidates:
            out['rows'].extend(rows)
            continue
        def rank(r):return (min(r['attack']), max(r['attack']), len(useful_skills(kind, set(r['skills']))), -len(r['ids']), r['power'], r['soldiers'])
        best = max(rows, key=rank)
        near = [r for r in rows if min(r['attack']) >= min(best['attack']) * .8]
        complementary = max(near, key=lambda r:(len(useful_skills(kind, set(r['skills']))), *rank(r), len(r['added'])))
        economical = max(rows, key=lambda r:(min(r['attack']) / len(r['ids']), *rank(r)))
        selected = set()
        for label, row in [('攻击优先', best), ('技能互补', complementary), ('省将方案', economical)]:
            key = frozenset(row['ids'])
            if key in selected:continue
            selected.add(key)
            out['rows'].append(dict(row, label=label))
    if not out['rows'] and not out['message']:
        out['message'] = '当前兵种库存或训练数据不足'
    return out
