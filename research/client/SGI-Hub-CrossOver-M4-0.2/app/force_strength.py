"""Observed five-stat totals and field-unit attack sums. Not engine damage or win chance."""
KEYS = ('lead', 'war', 'intel', 'pol', 'cha')


def five_stat_total(officer):
    attrs = (officer or {}).get('attributes') or {}
    values = [attrs.get(key) for key in KEYS]
    if any(type(value) not in (int, float) for value in values):
        return None
    return sum(values)


def top_five_stat_average(officers, limit=10):
    totals = sorted((total for total in (five_stat_total(officer) for officer in officers or []) if total is not None), reverse=True)
    if not totals:
        return None
    picked = totals[:limit]
    return sum(picked) / len(picked)


def unit_attack_value(unit):
    value = (unit or {}).get('target_attack_unit')
    if type(value) in (int, float):
        return float(value)
    if type(value) is not str:
        return None
    text = value.replace(',', '').strip()
    if not text or text in ('缺参数', '研究中', '—', '未知') or text.startswith('基值'):
        return None
    for sep in ('–', '-'):
        if sep in text:
            parts = text.split(sep)
            if len(parts) != 2:
                return None
            try:
                return (float(parts[0]) + float(parts[1])) / 2
            except ValueError:
                return None
    try:
        return float(text)
    except ValueError:
        return None


def unit_attack_values(units):
    return [value for value in (unit_attack_value(unit) for unit in units or []) if value is not None]


def unit_attack_total(units):
    values = unit_attack_values(units)
    return sum(values) if values else None


def unit_attack_average(units):
    values = unit_attack_values(units)
    return sum(values) / len(values) if values else None


def format_average(value):
    if value is None:
        return '—'
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else f'{rounded:.1f}'


def force_field_units(state, force_id):
    return [row for row in ((state or {}).get('entities') or {}).get('field_units') or []
            if row.get('owner_raw') == force_id]


def format_force_attack_line(name, units):
    return (f"{name}  总战力 {format_average(unit_attack_total(units))}"
            f"  {len(units or [])}队  均{format_average(unit_attack_average(units))}")


def force_attack_rows(state, force_ids=None):
    wanted = set(force_ids) if force_ids else None
    rows = []
    for lord in ((state or {}).get('entities') or {}).get('lords') or []:
        fid = lord.get('force_id')
        if fid is None or (wanted is not None and fid not in wanted):
            continue
        units = force_field_units(state, fid)
        name = lord.get('name') or f'势力{fid}'
        rows.append({
            'force_id': fid,
            'name': name,
            'unit_count': len(units),
            'total': unit_attack_total(units),
            'average': unit_attack_average(units),
            'line': format_force_attack_line(name, units),
        })
    return rows
