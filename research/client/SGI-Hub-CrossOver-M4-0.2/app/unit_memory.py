"""Already-decoded field-unit memory fields for display. No new reads."""
from native_unit_rules import attack_pair_text, displays_attack, primary_skill_text

# Guide: each turn eats soldiers/6 rice; a full ration lasts 6 turns, starve from the 7th.
RATION_TURNS = 6


def fmt_mem(value):
    if value is None:
        return '未知'
    if type(value) is int:
        return f'{value:,}'
    return str(value)


def rice_days(soldiers, rice):
    if type(soldiers) is not int or type(rice) is not int:
        return None
    if soldiers <= 0:
        return None
    if rice <= 0:
        return 0.0
    return RATION_TURNS * rice / soldiers


def format_days(days):
    if days is None:
        return None
    if days == 0:
        return '0'
    if abs(days - round(days)) < 1e-9:
        return str(int(round(days)))
    return f'{days:.1f}'


def rice_label(row):
    rice = fmt_mem(row.get('rice_candidate'))
    days = format_days(rice_days(row.get('soldiers_candidate'), row.get('rice_candidate')))
    if days is None:
        return f'{rice} · 天数未知'
    return f'{rice}（约{days}天）'


def attack_label(row):
    if not displays_attack(row):
        return '—'
    return legacy_attack_text(row) or attack_pair_text(row)


def legacy_attack_text(row):
    """An old frame's reference is not a restored native current/full pair."""
    from native_unit_rules import ATTACK_MODEL
    from unit_target_attack import LEGACY_SOURCES
    reference = row.get('legacy_attack_reference') or {}
    value = reference.get('value')
    if (row.get('attack_model') == ATTACK_MODEL
            and row.get('attack_missing_reason') == '技能未存'
            and row.get('native_attack_index') is None
            and row.get('native_attack_index_full_morale') is None
            and reference.get('source') in LEGACY_SOURCES
            and type(value) is int and value >= 0):
        return f'旧参考{value}·技能未存'
    return None


def attack_reference(row):
    """Previous comparison scale; never collapse a native index uncertainty range.

    Infantry/cavalry use the website coefficient, bows the previous client-table
    coefficient. Both scale by formation ability / 150, without native morale or
    an assumed effective skill. This is a reference, not actual target damage.
    """
    import math
    ability = row.get('basic_combat_power')
    components = row.get('target_attack_components') or {}
    values = components.get('reference_unit')
    if (type(ability) is int and 0 <= ability <= 150
            and isinstance(values, list) and len(values) == 1
            and type(values[0]) is int and values[0] >= 0):
        return math.floor(values[0] * ability / 150 + .5)
    value = row.get('website_attack_power')
    if type(value) is int and value >= 0:
        return value
    # Older collectors/replays already stored this single reference in the old
    # field. A native scalar or range must never be relabelled as that scale.
    if row.get('attack_model') or row.get('native_attack_index') is not None:
        return None
    value = row.get('target_attack_unit')
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def memory_line(row):
    heading = '攻击' if legacy_attack_text(row) else '攻击[当前/陆地满士气]'
    attack = ('' if not displays_attack(row) else
              f" · {heading} {attack_label(row)}")
    return (
        f"兵数 {fmt_mem(row.get('soldiers_candidate'))}"
        f" · 粮食 {rice_label(row)}"
        f" · 战力 {fmt_mem(row.get('basic_combat_power'))}"
        f" · 士气 {fmt_mem(row.get('morale'))}"
        f"{attack} · 技能 {skill_label(row)}"
    )


def skill_label(row):
    return primary_skill_text((row or {}).get('effective_skill_mask'))
