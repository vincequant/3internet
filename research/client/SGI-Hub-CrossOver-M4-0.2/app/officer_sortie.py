"""Single-officer sortie preview from current troop size. Not engine damage."""
from preparation_model import combat_power, size_index, skills_for, training_bases
from unit_target_attack import rnd, supported_combat_build

KINDS = ('infantry', 'cavalry', 'bow')
KIND_LABEL = {'infantry': '步', 'cavalry': '骑', 'bow': '弓'}
SIZES = ('小队', '中队', '大队')
KIND_SKILL = {'cavalry': '骑马', 'bow': '弓箭'}
AMBUSH_SKILLS = frozenset({'埋伏', '伏兵'})
PINNED_SKILL_NAMES = frozenset({'骑马', '弓箭'}) | AMBUSH_SKILLS
PINNED_SKILL_GROUPS = (
    ('ride', frozenset({'骑马'})),
    ('bow', frozenset({'弓箭'})),
    ('ambush', AMBUSH_SKILLS),
)
ROSTER_KEEP_STATUS = frozenset({0, 1, 2, 4, 6})
WILD_OWNER = 65535
ROSTER_DROP_LABELS = frozenset({'死亡', '未登场', '未命名状态'})
ROSTER_SKILLS = (
    ('ride', '骑', frozenset({'骑马'})),
    ('bow', '弓', frozenset({'弓箭'})),
    ('navy', '水', frozenset({'水军'})),
    ('ambush', '伏', AMBUSH_SKILLS),
)
ROSTER_COLORS = {
    'ride': ('#1f6b45', '#f4fff8'),
    'bow': ('#1f4e86', '#f4f8ff'),
    'navy': ('#0e6e78', '#f3fcfd'),
    'ambush': ('#8a5a00', '#fff8e6'),
}
ALL_SKILLS = '全技能'
AMBUSH_INK = '#8a5a00'
AMBUSH_INK_DARK = '#d4a017'


def kind_skill_flags(officer):
    skills = skills_for(officer)
    return {kind: name in skills for kind, name in KIND_SKILL.items()}


def _skill_parts(skills_text):
    return {part.strip() for part in str(skills_text or '').split(' / ') if part.strip()}


def pinned_skill_flags_from_text(skills_text):
    parts = _skill_parts(skills_text)
    all_on = ALL_SKILLS in parts
    return {key: all_on or bool(parts & names) for key, names in PINNED_SKILL_GROUPS}


def pinned_skill_cells(skills_text):
    flags = pinned_skill_flags_from_text(skills_text)
    return {key: ('●' if on else '—') for key, on in flags.items()}


def wild_city_counts(generals):
    counts = {}
    for officer in generals or []:
        if officer.get('status_code') != 1 or officer.get('owner_raw') != WILD_OWNER:
            continue
        cid = officer.get('location_city_id')
        if type(cid) is not int:
            continue
        counts[cid] = counts.get(cid, 0) + 1
    return counts


def unique_place_ids(places):
    counts = {}
    for place in places or []:
        cid = place.get('city_id')
        if type(cid) is not int:
            continue
        counts[cid] = counts.get(cid, 0) + 1
    return {cid for cid, n in counts.items() if n == 1}


def recruit_share_label(officer, counts, unique_ids):
    """Equal-split hire rate for a wild officer. Employed officers have none."""
    if (officer or {}).get('owner_raw') != WILD_OWNER or (officer or {}).get('status_code') != 1:
        return '—'
    cid = officer.get('location_city_id')
    crowd = counts.get(cid) if type(cid) is int else None
    if crowd is None or cid not in unique_ids or crowd <= 0:
        return '未知'
    return f'{100 / crowd:.1f}%'


def roster_visible(officer, force_ids):
    owner = (officer or {}).get('owner_raw')
    if owner not in force_ids and owner != WILD_OWNER:
        return False
    status = officer.get('status_code')
    if status not in ROSTER_KEEP_STATUS:
        return False
    return officer.get('status_label') not in ROSTER_DROP_LABELS


def roster_skill_flags(officer=None, skills=None):
    if skills is None:
        skills = skills_for(officer)
    elif isinstance(skills, str):
        skills = _skill_parts(skills)
    else:
        skills = set(skills)
    all_on = ALL_SKILLS in skills
    return {key: all_on or bool(skills & names) for key, _title, names in ROSTER_SKILLS}


def roster_skill_cells(flags):
    return {key: title if flags.get(key) else '—' for key, title, _names in ROSTER_SKILLS}


def remaining_skill_text(skills_text):
    parts = [part.strip() for part in str(skills_text or '').split(' / ') if part.strip()]
    if not parts:
        return '—'
    kept = [part for part in parts if part not in PINNED_SKILL_NAMES]
    return ' / '.join(kept) if kept else '—'


def has_ambush_skill(officer):
    skills = skills_for(officer)
    return ALL_SKILLS in skills or bool(skills & AMBUSH_SKILLS)


def resolved_officers(state, general_ids):
    by_id = {}
    for officer in ((state or {}).get('entities') or {}).get('generals') or []:
        by_id.setdefault(officer.get('general_id_raw'), []).append(officer)
    found = []
    for gid in general_ids or []:
        matches = by_id.get(gid) or []
        if len(matches) == 1:
            found.append(matches[0])
    return found


def unit_has_ambush(state, unit):
    return any(has_ambush_skill(officer) for officer in resolved_officers(state, (unit or {}).get('general_ids')))


def taken_soldiers(officer, force, kind):
    soldiers = (officer or {}).get('soldiers')
    if type(soldiers) is not int or soldiers <= 0:
        return None
    stock = ((force or {}).get('troop_stock') or {}).get(kind)
    if type(stock) is int:
        taken = min(soldiers, stock)
        if taken <= 0:
            return None
        return taken, soldiers, stock, stock < soldiers
    return soldiers, soldiers, None, False


def kind_preview(officer, force, kind):
    taken = taken_soldiers(officer, force, kind)
    if not taken:
        return None
    soldiers, capacity, stock, capped = taken
    power = combat_power([officer])
    bases = training_bases(kind, ((force or {}).get('armament_raw') or {}).get(kind))
    size = size_index(soldiers)
    if not bases or power is None or not 0 <= power <= 150:
        return None
    factor = bases['unit'][size]
    if factor is None:
        return None
    return {
        'kind': kind, 'name': bases['name'], 'training': bases['training'],
        'soldiers': soldiers, 'capacity': capacity, 'stock': stock,
        'size': size, 'size_label': SIZES[size], 'power': power,
        'factor': factor, 'attack': rnd(factor * power / 150), 'capped': capped,
    }


def officer_previews(officer, force, state=None):
    if state is not None and not supported_combat_build(state.get('build_sha256')):
        return {kind: None for kind in KINDS}
    return {kind: kind_preview(officer, force, kind) for kind in KINDS}


def format_preview(preview):
    if not preview or preview.get('attack') is None:
        return '—'
    return str(preview['attack'])


def officer_cells(officer, force, state=None):
    previews = officer_previews(officer, force, state)
    return {kind: format_preview(previews[kind]) for kind in KINDS}
