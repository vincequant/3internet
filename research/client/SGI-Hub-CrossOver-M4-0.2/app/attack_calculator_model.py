"""Manual/same-frame attack calculator using the verified SANPK arithmetic.

No game calls, memory writes, archive changes or future-frame lookup.
"""
from native_unit_rules import ARROW, HORSE, attack_index, raw_bytes, unit_skill_mask
from unit_target_attack import BOW, PARAMS, WATER_BASES, client_factor, client_kind, supported_combat_build


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name}须为{low}–{high}的整数')
    return value


def calculate(kind, soldiers, training, morale, officers, horse=True, arrow=True, on_water=False):
    kind = client_kind(kind)
    if kind not in PARAMS:
        raise ValueError('请选择已核实的步兵、骑兵或弓兵类型')
    integer(soldiers, '兵数', 1, 100000)
    integer(training, '本级训练度', 0, 100)
    integer(morale, '士气', 0, 100)
    if any(type(v) is not bool for v in (horse, arrow, on_water)):
        raise ValueError('技能及水陆选项须明确选择')
    if not isinstance(officers, (tuple, list)) or not 1 <= len(officers) <= 3:
        raise ValueError('编成须为1–3名武将，第一名为主将')
    effective = []
    for i, officer in enumerate(officers, 1):
        lead = integer(officer.get('lead'), f'第{i}将统率', 0, 255)
        war = integer(officer.get('war'), f'第{i}将武力', 0, 255)
        for key in ('lead_bonus', 'war_bonus'):
            if type(officer.get(key, False)) is not bool:
                raise ValueError('宝物修正须明确选择')
        effective.append(dict(
            lead=lead + (lead * 2 // 5 if officer.get('lead_bonus') else 0),
            war=war + (war * 2 // 5 if officer.get('war_bonus') else 0)))
    lead = effective[0]['lead'] if len(effective) == 1 else (
        effective[0]['lead'] + sum(g['lead'] for g in effective[1:]) // (len(effective) - 1)) // 2
    lead = max(10, lead)
    war = sum(g['war'] for g in effective) // len(effective)
    ability = (lead + war) // 2
    size = int(soldiers > 20000) + int(soldiers > 35000)
    base, _, multipliers, _ = PARAMS[kind]
    before_skill = client_factor(kind, size, training)
    required = '弓箭' if kind in BOW else ('骑马' if '骑兵' in kind else None)
    skilled = arrow if kind in BOW else horse
    land = before_skill // 2 if required and not skilled else before_skill
    current = WATER_BASES[size] if on_water and kind not in BOW else land
    composition = ability * 80 // 100 + 20
    spirit = morale + morale // 2
    return dict(kind=kind, soldiers=soldiers, training=training, morale=morale,
                effective=effective, lead=lead, war=war, ability=ability, size=size,
                base=base[size], multiplier=multipliers[size], before_skill=before_skill,
                required=required, skilled=skilled, land_coefficient=land,
                current_coefficient=current, composition=composition, spirit=spirit,
                current=attack_index(current, ability, morale),
                land_full=attack_index(land, ability, 100), on_water=on_water,
                mode='远射' if kind in BOW else '近战')


def from_unit(state, unit):
    """Import only raw inputs present in the supplied current/replay frame."""
    if not supported_combat_build((state or {}).get('build_sha256')):
        raise ValueError('所选帧客户端版本未匹配，不能载入')
    mask = unit_skill_mask(state, unit)
    if mask is None:
        raise ValueError('所选帧编成或原始技能不完整，不能载入')
    generals = (state.get('entities') or {}).get('generals') or []
    officers = []
    for gid in unit.get('general_ids') or []:
        if gid is None:
            continue
        g = next(g for g in generals if g.get('general_id_raw') == gid)
        b = raw_bytes(g)
        flags = b[0x44] if len(b) > 0x44 else g.get('combat_modifier_flags')
        if type(flags) is not int:
            word = g.get('combat_modifier_flags_word')
            flags = word & 255 if type(word) is int and 0 <= word <= 65535 else None
        integer(flags, '武将修正位', 0, 255)
        attrs = g.get('attributes') or {}
        officers.append(dict(lead=attrs.get('lead'), war=attrs.get('war'),
                             lead_bonus=bool(flags & 0x10), war_bonus=bool(flags & 0x20)))
    b = raw_bytes(unit)
    water = unit.get('on_water')
    if type(water) is not bool:
        code = unit.get('terrain_type_raw')
        water = code in (4, 6) if type(code) is int and 0 <= code <= 29 else None
    if water is None:
        raise ValueError('所选帧缺少水陆状态，不能载入')
    inputs = dict(kind=client_kind(unit.get('unit_kind')), soldiers=unit.get('soldiers_candidate'),
                  training=b[0x29] if len(b) > 0x29 else unit.get('armament_degree_raw'),
                  morale=b[0x1d] if len(b) > 0x1d else unit.get('raw_1d'),
                  officers=officers, horse=bool(mask & HORSE), arrow=bool(mask & ARROW), on_water=water)
    calculate(**inputs)  # All-or-nothing: never turn a missing input into zero.
    return inputs


def calculation_text(r):
    lines = ['1. 编成统武与能力']
    for i, g in enumerate(r['effective'], 1):
        lines.append(f"   {'主将' if i == 1 else '副将' + str(i-1)}有效统率 {g['lead']}，武力 {g['war']}")
    lines += [f"   编成统率 L={r['lead']}；编成武力 W={r['war']}",
              f"   A=⌊(L+W)/2⌋={r['ability']}",
              f"   C=⌊A×80/100⌋+20={r['composition']}", '',
              '2. 兵种、训练与技能',
              f"   {('小队','中队','大队')[r['size']]}：{r['soldiers']:,}兵",
              f"   B₀={r['base']}+四舍五入({r['multiplier']}×{r['training']}/100)={r['before_skill']}"]
    if r['required']:
        lines.append(f"   {'有' if r['skilled'] else '无'}{r['required']}：陆地B={r['land_coefficient']}" +
                     ('（先向下取整B₀/2）' if not r['skilled'] else ''))
    else:
        lines.append(f"   陆地B={r['land_coefficient']}")
    if r['on_water'] and r['mode'] == '近战':
        lines.append(f"   水上近战另取规模B={r['current_coefficient']}；此项不读训练、骑马或水军")
    elif r['on_water']:
        lines.append('   水上远射保留弓兵系数及弓箭技能分支')
    lines += ['', '3. 士气与攻击指数',
              f"   S={r['morale']}+⌊{r['morale']}/2⌋={r['spirit']}",
              f"   当前Q=四舍五入({r['current_coefficient']}×{r['composition']}×{r['spirit']}/4000)={r['current']}",
              f"   陆地满士气Q=四舍五入({r['land_coefficient']}×{r['composition']}×150/4000)={r['land_full']}", '',
              '每一步按原版整数顺序取整；正数四舍五入，恰好半数时向上。',
              '兵数≤20,000 / ≤35,000 / >35,000分三档；同档兵数不直接按比例乘攻击。']
    if r['mode'] == '远射':
        lines += ['', '这是弓兵远射指数，不能与步骑近战指数直接判断短兵相接胜负。']
    return '\n'.join(lines)
