"""Read-only conditional probabilities from SANPK r6 native predicates.

Evidence: UNIT_SKILLS_SPECIAL_CHANCE_1.1.325_20261011.md. Uses this frame only.
Nominal R(n) probabilities, not RNG-state prediction, damage or victory odds.
"""
import struct
from native_unit_rules import RAID, WUSHUANG, general_skill_mask, native_build, raw_bytes, unit_skill_mask

# Dispatcher 0x456475: first passing gate stops the sequence, even if countered.
# Effect bindings: fire event9, rock10, confusion12, lightning11.
SPELLS = (('火攻', 0x200, 0x800, 2), ('落石', 0x400, 0x800, 2),
          ('混乱', 0x4000, 0x10000, 3), ('天雷', 0x1000, 0x2000, 4))
INFANTRY = {'步兵', '生步兵', '强化步兵', '重装步兵'}


def integer(value, maximum=255):
    return type(value) is int and 0 <= value <= maximum


def intelligence(general):
    b = raw_bytes(general)
    value = b[0x27] if len(b) > 0x27 else (general.get('attributes') or {}).get('intel')
    return value if integer(value) else None


def assigned_generals(state, unit):
    if unit_skill_mask(state, unit) is None:
        return None
    by_id = {g.get('general_id_raw'): g for g in (state.get('entities') or {}).get('generals') or []}
    return [by_id[gid] for gid in unit.get('general_ids') or [] if gid is not None]


def skilled_general(generals, bit):
    """0x477875 selects highest intelligence >0 among holders of this skill."""
    if generals is None:
        return None, False
    selected, maximum = None, 0
    for g in generals:
        mask = general_skill_mask(g)
        if mask is None:
            return None, False
        if mask & bit:
            value = intelligence(g)
            if value is None:
                return None, False
            if value > maximum:
                selected, maximum = g, value
    return selected, True


def raid_percent(attacker_intel, target_intel):
    if not integer(attacker_intel) or not integer(target_intel):
        return None
    return max(0, min(10, 10 + attacker_intel - target_intel)) * 2.5


def counter_pass_percent(caster_intel, defender_intel):
    """0x4567dd; morale argument is unused. No counter -> 100%."""
    if not integer(caster_intel) or not integer(defender_intel):
        return None
    difference = caster_intel - defender_intel
    return (100 if difference > 40 else 75 if difference >= 20 else
            50 if difference > -20 else 25 if difference >= -40 else 0)


def native_distance(left, right):
    """0x46a0f7 offset-row diamond coordinates; radius3 contains 25 cells."""
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 or
           any(type(v) is not int or v < 0 for v in p) for p in (left, right)):
        return None
    return max(abs(2 * left[0] + left[1] % 2 - 2 * right[0] - right[1] % 2),
               abs(left[1] - right[1]))


def enemies(state, left, right):
    """0x4682ac: war in EITHER lord's relation row; never player-relative."""
    if left == right or right == 65535:
        return False
    if not integer(left, 21) or not integer(right, 21):
        return None
    lords = (state.get('entities') or {}).get('lords') or []
    values = []
    for own, other in ((left, right), (right, left)):
        found = [f for f in lords if f.get('force_id') == own]
        relation = found[0].get('diplomacy_relations') if len(found) == 1 else None
        values.append(relation[other] if isinstance(relation, list) and other < len(relation) else None)
    if 1 in values:
        return True
    return False if all(integer(v, 3) for v in values) else None


def counter_eligible(unit):
    if unit.get('unit_kind') == '游荡部队':
        return False
    b = raw_bytes(unit)
    flags = b[0xd] if len(b) > 0xd else unit.get('unit_state_flags_raw')
    order = struct.unpack_from('<H', b, 0x7e)[0] if len(b) >= 0x80 else unit.get('native_order_type_raw')
    payload = struct.unpack_from('<I', b, 0x5e)[0] if len(b) >= 0x62 else unit.get('native_order_payload_raw')
    if integer(flags) and flags & 15 == 2:
        return False
    if order == 2 and payload == 0:
        return False
    if not integer(flags) or not integer(order, 65535) or (order == 2 and not integer(payload, 0xffffffff)):
        return None
    return True


def unit_name(state, unit):
    ids = unit.get('general_ids') or []
    first = ids[0] if ids else None
    found = [g for g in (state.get('entities') or {}).get('generals') or []
             if first is not None and g.get('general_id_raw') == first]
    return (found[0].get('name') if len(found) == 1 else None) or f"部队#{unit.get('unit_id', '?')}"


def special_preview(state, unit):
    result = {'spells': [], 'targets': [], 'raid': [], 'percent': None,
              'reason': '', 'wushuang_percent': None, 'wushuang_conditional': False}
    if not native_build(state):
        result['reason'] = '版本未核定'
        return result
    generals = assigned_generals(state, unit)
    mask = unit_skill_mask(state, unit)
    if generals is None or mask is None:
        result['reason'] = '编成技能未存'
        return result
    if mask & WUSHUANG:
        flags = (state.get('combat_rules') or {}).get('flags_raw')
        result['wushuang_conditional'] = not integer(flags, 0xffffffff)
        result['wushuang_percent'] = 0 if integer(flags, 0xffffffff) and flags & 2 else 12.5
    targets, target_unknown = [], False
    for other in (state.get('entities') or {}).get('field_units') or []:
        if other is unit or other.get('owner_raw') == unit.get('owner_raw'):
            continue
        distance = native_distance(unit.get('world_xy_raw'), other.get('world_xy_raw'))
        war = enemies(state, unit.get('owner_raw'), other.get('owner_raw'))
        if war is False or (distance is not None and distance > 3):
            continue
        if war is None or distance is None:
            target_unknown = True
            continue
        targets.append(other)
    result['targets'] = [{'unit_id': t.get('unit_id'), 'name': unit_name(state, t),
                          'xy': t.get('world_xy_raw')} for t in targets]
    if mask & RAID:
        values = [intelligence(g) for g in generals]
        own_intel = max(values) if all(v is not None for v in values) else None
        for other in targets:
            if other.get('unit_kind') == '游荡部队':
                continue
            gs = assigned_generals(state, other)
            values = [intelligence(g) for g in gs] if gs is not None else [None]
            enemy_intel = max(values) if all(v is not None for v in values) else None
            result['raid'].append({'unit_id': other.get('unit_id'), 'name': unit_name(state, other),
                                   'own_intel': own_intel, 'enemy_intel': enemy_intel,
                                   'percent': raid_percent(own_intel, enemy_intel)})
    if unit.get('unit_kind') not in INFANTRY:
        result['reason'] = '该兵种无主动特殊'
        return result
    if not mask & 0x5600:
        result['reason'] = '无主动特殊技能'
        return result
    morale = unit.get('morale')
    if not integer(morale, 100):
        result['reason'] = '士气未存'
        return result
    if morale < 30:
        result.update(percent=0, reason='士气不足30')
        return result
    bonus = 0
    for g in generals:
        b = raw_bytes(g)
        flags = struct.unpack_from('<H', b, 0x44)[0] if len(b) >= 0x46 else g.get('combat_modifier_flags_word')
        if not integer(flags, 65535):
            result['reason'] = '施放修正未存'
            return result
        if flags & 0x100:
            bonus = 10
    if 'field_units' not in (state.get('entities') or {}):
        target_unknown = True
    if target_unknown:
        result['reason'] = '周边坐标或外交关系未存'
        return result
    if not targets:
        result.update(percent=0, reason='范围内无交战敌队')
        return result
    remaining, total, known = 1., 0., True
    for name, bit, counter_bit, divisor in SPELLS:
        caster, valid = skilled_general(generals, bit)
        if not valid:
            result['reason'] = '施放将智力未存'
            return result
        if caster is None:
            continue
        cast = min(50, intelligence(caster) // divisor + bonus)
        defender, defense_unit, defense_known = None, None, True
        for other in targets:
            eligibility = counter_eligible(other)
            if eligibility is False:
                continue
            gs = assigned_generals(state, other)
            candidate, valid = skilled_general(gs, counter_bit)
            if not valid or (candidate is not None and eligibility is None):
                defense_known = False
            elif candidate is not None and (defender is None or intelligence(candidate) > intelligence(defender)):
                defender, defense_unit = candidate, other
        passed = (100 if defender is None else counter_pass_percent(intelligence(caster), intelligence(defender))) if defense_known else None
        contribution = remaining * cast * passed / 100 if passed is not None else None
        result['spells'].append({'name': name, 'caster': caster.get('name'), 'intel': intelligence(caster),
                                 'cast_percent': cast, 'counter_pass_percent': passed,
                                 'defender': defender.get('name') if defender else None,
                                 'defender_intel': intelligence(defender) if defender else None,
                                 'defender_unit_id': defense_unit.get('unit_id') if defense_unit else None,
                                 'percent': contribution})
        if contribution is None and remaining * cast > 0:
            known = False
        elif contribution is not None:
            total += contribution
        # Counter failure consumes the attempt; only CAST failure falls through.
        remaining *= 1 - cast / 100
    result['percent'] = total if known else None
    result['reason'] = '' if known else '敌队防计或行动状态未存'
    return result


def personal_special_percent(intel, mask, bonus=0):
    """One general alone: the four spells chain, and counter pass stays 100%.

    No holder of those bits is 0. Missing intel or skill word stays unknown.
    """
    if not integer(intel) or type(mask) is not int or not 0 <= mask <= 0xffffffff or bonus not in (0, 10):
        return None
    remaining, total = 1.0, 0.0
    for _name, bit, _counter, divisor in SPELLS:
        if not mask & bit:
            continue
        cast = min(50, intel // divisor + bonus)
        total += remaining * cast
        remaining *= 1 - cast / 100
    return total


def percent_text(value):
    return '未知' if value is None else f'{value:.2f}'.rstrip('0').rstrip('.') + '%'


def special_brief(state, unit):
    p = special_preview(state, unit)
    parts = []
    if p['spells'] or p['reason'] not in ('该兵种无主动特殊', '无主动特殊技能'):
        parts.append('特殊' + percent_text(p['percent']))
    if p['raid']:
        parts.append('奇袭' + '/'.join(dict.fromkeys(percent_text(r['percent']) for r in p['raid'])))
    return ' · '.join(parts) or '—'


def special_details(state, unit):
    p = special_preview(state, unit)
    lines = ['特殊成功率：' + percent_text(p['percent']) + (f"（{p['reason']}）" if p['reason'] else '')]
    if p['targets']:
        lines.append('当前作用范围内敌队：' + '、'.join(t['name'] for t in p['targets']))
    for s in p['spells']:
        defense = (f"{s['defender']} 智{s['defender_intel']}（部队#{s['defender_unit_id']}）"
                   if s['defender'] else '无已知对应防计将')
        lines.append(f"{s['name']}：{s['caster']} 智{s['intel']} · 施放{percent_text(s['cast_percent'])}"
                     f" · 防计通过{percent_text(s['counter_pass_percent'])} · 本次贡献{percent_text(s['percent'])}；{defense}")
    if p['spells']:
        lines.append('成功率为发动并通过防计；依火攻、落石、混乱、天雷顺序判定。天雷命中对象另有随机性，可波及自身。')
    for r in p['raid']:
        lines.append(f"奇袭 → {r['name']}：{percent_text(r['percent'])}（我方最高智{r['own_intel']} / 敌方最高智{r['enemy_intel']}）")
    if p['wushuang_percent'] is not None:
        lines.append('无双受击触发：' + percent_text(p['wushuang_percent']) +
                     ('（本帧未存房间开关，按允许触发计算）' if p['wushuang_conditional'] else ''))
    lines.append('按本帧坐标和编成计算；奇袭须实际选中该对手，特殊能否下令以游戏菜单为准。')
    return '\n'.join(lines)
