"""Pure SANPK 3.5 memory/rule components. Unknown evidence stays unknown.

Evidence: research/reports/MAP_ATTACK_MOVEMENT_ACCURACY_20261011.md.
No website officer matching, GUI imports, target calls or memory writes.
"""
import struct

ATTACK_MODEL = 'sanpk-3.5-attack-index-v1'
TERRAIN_ENCODING = 'sanpk-terrain-u8-v2'
UNKNOWN_TERRAIN = 255
HORSE, ARROW, NAVY = 1, 2, 4
AMBUSH, RAID, WUSHUANG = 0x20, 0x40, 0x80
# Original general-list columns (0x42d02f..0x42d242), not reference names.
PRIMARY_SKILLS = ((HORSE, '骑', '骑马'), (ARROW, '弓', '弓箭'),
                  (NAVY, '水', '水军'), (AMBUSH, '伏', '伏兵'),
                  (RAID, '奇', '奇袭'), (WUSHUANG, '无双', '无双'))


def primary_skill_text(mask, full=False):
    if type(mask) is not int or not 0 <= mask <= 0xffffffff:
        return '技能未知'
    return (' / ' if full else ' ').join(
        long if full else short for bit, short, long in PRIMARY_SKILLS
        if mask & bit and (full or bit != WUSHUANG)
    ) or '无主要技能'


def displays_attack(unit):
    return (unit or {}).get('unit_kind') not in {
        '弓兵', '强弓兵', '重装弓兵', '弩兵', '连弩', '运输兵', '粮仓兵', '粮仓'}


def native_build(state):
    from unit_target_attack import supported_combat_build
    return supported_combat_build((state or {}).get('build_sha256'))


def raw_bytes(row):
    try:
        return bytes.fromhex((row or {}).get('raw_hex') or '')
    except (TypeError, ValueError):
        return b''


def general_skill_mask(row):
    """0x45c739: general+0x2a OR treasure skill from WORD general+0x44."""
    b = raw_bytes(row)
    if len(b) >= 0x46:
        mask = struct.unpack_from('<I', b, 0x2a)[0]
        flags = struct.unpack_from('<H', b, 0x44)[0]
    else:
        mask = (row or {}).get('skill_mask_raw')
        flags = (row or {}).get('combat_modifier_flags_word')
    if type(mask) is not int or not 0 <= mask <= 0xffffffff:
        return None
    if type(flags) is not int or not 0 <= flags <= 0xffff:
        return None
    return mask | ((flags >> 7) & NAVY)


def unit_skill_mask(state, unit):
    """0x47868e: union every assigned general; missing/ambiguous != skill absent."""
    if not native_build(state):
        return None
    ids = [g for g in (unit or {}).get('general_ids') or [] if g is not None]
    if (not 1 <= len(ids) <= 3 or any(type(g) is not int or g < 0 for g in ids)
            or len(set(ids)) != len(ids)):
        return None
    mask = 0
    generals = ((state or {}).get('entities') or {}).get('generals') or []
    for gid in ids:
        matches = [g for g in generals if g.get('general_id_raw') == gid]
        if len(matches) != 1:
            return None
        g = matches[0]
        if g.get('owner_raw') != (unit or {}).get('owner_raw') or g.get('status_code') != 2:
            return None
        value = general_skill_mask(g)
        if value is None:
            return None
        mask |= value
    return mask


def boat_sprite(state, unit):
    """0x4771bc water animation: navy adds124 to original frame base1953."""
    mask = unit_skill_mask(state, unit) if state is not None else (unit or {}).get('effective_skill_mask')
    return 'warship.png' if type(mask) is int and mask & NAVY else 'boat.png'


def remaining_move(state, unit):
    """0x430366 uses BYTE unit+0x20, including zero after movement."""
    if not native_build(state):
        return None
    b = raw_bytes(unit)
    value = b[0x20] if len(b) > 0x20 else (unit or {}).get('move_remaining_raw')
    return value if type(value) is int and 0 <= value <= 255 else None


def attack_index(coefficient, ability, morale):
    """0x456269 intermediate, NOT final damage: positive-domain MulDiv rounding."""
    if any(type(n) is not int for n in (coefficient, ability, morale)):
        return None
    if not (0 <= coefficient <= 10000 and 0 <= ability <= 357 and 0 <= morale <= 100):
        return None
    composition = ability * 80 // 100 + 20
    spirit = morale + morale // 2
    return (coefficient * composition * spirit + 2000) // 4000


def attack_pair_text(unit):
    """Current terrain/morale / land morale-100 native indices, never a guessed proficiency range."""
    unit = unit or {}
    if unit.get('attack_model') != ATTACK_MODEL:
        return '[未知/未知]'
    values = [unit.get(key) for key in ('native_attack_index',
                                      'native_attack_index_full_morale')]
    return '[' + '/'.join(str(v) if type(v) is int and v >= 0 else '未知'
                          for v in values) + ']'


def proficiency_values(base, required, mask):
    if required is None:
        return [base]
    if mask is None:
        return sorted(set([base // 2, base]))
    return [base if mask & required else base // 2]


def terrain_entry_cost(code, kind, mask, mountain_setting):
    """0x469621/0x46967e entry component only; not a complete pathfinder."""
    if type(code) is not int or not 0 <= code <= 29:
        return None
    if code >= 24:
        return None
    if code in (0, 5):
        return 3
    if code in (1, 2):
        return 5
    if code == 3:
        # +0xc8: heavy infantry returns 1; other verified land classes return 0.
        return 6 if type(mountain_setting) is int and mountain_setting != 0 and kind == '重装步兵' else None
    if code in (4, 6):
        # +0xc4 returns 1 for the verified combat/wagon classes, not all objects.
        allowed = {'步兵', '生步兵', '强化步兵', '重装步兵', '骑兵', '生骑兵',
                   '强化骑兵', '重装骑兵', '铁骑兵', '弓兵', '强弓兵', '弩兵',
                   '重装弓兵', '连弩', '运输兵'}
        if kind not in allowed or mask is None:
            return None
        return 2 if mask & NAVY else 8
    if code in (18, 19):
        return 4
    return 2
