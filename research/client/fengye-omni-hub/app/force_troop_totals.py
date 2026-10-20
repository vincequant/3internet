"""Warehouse + field + city-officer soldiers. Training is still national raw."""
import sys
from pathlib import Path
_bridge = Path(__file__).resolve().parent.parent / 'bridge'
if str(_bridge) not in sys.path:
    sys.path.insert(0, str(_bridge))
from state_history import calendar_label, phase_fields, phase_label, troop_text, training_progress

KINDS = ('infantry', 'cavalry', 'bow')
KIND_CN = {'infantry': '步', 'cavalry': '骑', 'bow': '弓'}
CITY_STATUS = 0
FIELD_STATUS = 2
KIND_ALIASES = {
    'infantry': 'infantry', 'cavalry': 'cavalry', 'bow': 'bow',
    '步兵': 'infantry', '强化步兵': 'infantry', '重装步兵': 'infantry',
    '骑兵': 'cavalry', '强化骑兵': 'cavalry', '重装骑兵': 'cavalry', '铁骑兵': 'cavalry', '铁骑': 'cavalry',
    '弓兵': 'bow', '弩兵': 'bow', '强弓兵': 'bow', '连弩': 'bow', '重装弓兵': 'bow',
}


def unit_kind(row):
    name = (row or {}).get('unit_kind')
    if name in KIND_ALIASES:
        return KIND_ALIASES[name]
    if not isinstance(name, str):
        return None
    if '骑' in name:
        return 'cavalry'
    if '弓' in name or '弩' in name:
        return 'bow'
    if '步' in name:
        return 'infantry'
    return None


def _int(value):
    return value if isinstance(value, int) and value >= 0 else None


def field_soldiers(state, force_id):
    totals = dict.fromkeys(KINDS, 0)
    known = False
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        if row.get('owner_raw') != force_id:
            continue
        kind = unit_kind(row)
        soldiers = _int(row.get('soldiers_candidate'))
        if kind is None or soldiers is None:
            continue
        totals[kind] += soldiers
        known = True
    return totals if known or any(totals.values()) else dict.fromkeys(KINDS, 0)


def field_other_soldiers(state, force_id):
    total = 0
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        if row.get('owner_raw') != force_id:
            continue
        if unit_kind(row) is not None:
            continue
        soldiers = _int(row.get('soldiers_candidate'))
        if soldiers:
            total += soldiers
    return total


def field_general_ids(state, force_id):
    ids = set()
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        if row.get('owner_raw') != force_id:
            continue
        for gid in row.get('general_ids') or []:
            if isinstance(gid, int):
                ids.add(gid)
    return ids


def city_officer_soldiers(state, force_id):
    deployed = field_general_ids(state, force_id)
    total = 0
    for row in ((state or {}).get('entities') or {}).get('generals') or []:
        if row.get('owner_raw') != force_id:
            continue
        if row.get('status_code') != CITY_STATUS or row.get('general_id_raw') in deployed:
            continue
        soldiers = _int(row.get('soldiers'))
        if soldiers:
            total += soldiers
    return total


def warehouse_stock(force):
    stock = (force or {}).get('troop_stock') or {}
    return {kind: _int(stock.get(kind)) for kind in KINDS}


def force_lord(state, force_id):
    for row in ((state or {}).get('entities') or {}).get('lords') or []:
        if row.get('force_id') == force_id:
            return row
    return None


def add_optional(left, right):
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def force_troop_sample(state, force_id):
    lord = force_lord(state, force_id) or {}
    warehouse = warehouse_stock(lord)
    field = field_soldiers(state, force_id)
    city = city_officer_soldiers(state, force_id)
    raw = lord.get('armament_raw') or {}
    sample = {
        'force_id': force_id,
        'name': lord.get('name'),
        'city': city,
        'field_other': field_other_soldiers(state, force_id),
        'kinds': {},
    }
    for kind in KINDS:
        store = warehouse.get(kind)
        out = field.get(kind) or 0
        sample['kinds'][kind] = {
            'warehouse': store,
            'field': out,
            'total': add_optional(store, out),
            'raw': raw.get(kind) if isinstance(raw.get(kind), int) else None,
            'text': troop_text(kind, raw.get(kind)),
            'degree': training_progress(raw.get(kind)),
        }
    return sample


def troop_series_point(state):
    phase = phase_fields((state or {}).get('clock_candidates'), (state or {}).get('phase_candidate'))
    forces = {}
    for row in ((state or {}).get('entities') or {}).get('lords') or []:
        fid = row.get('force_id')
        if isinstance(fid, int):
            forces[str(fid)] = force_troop_sample(state, fid)
    return {
        'label': phase_label(phase),
        'year': phase.get('year_u16'),
        'season': phase.get('season_u16'),
        'round': phase.get('round_u8'),
        'forces': forces,
    }


def season_key(point):
    year, season = (point or {}).get('year'), (point or {}).get('season')
    if isinstance(year, int) and isinstance(season, int):
        return (year, season)
    return None


def is_military_round(point):
    label = (point or {}).get('label') or ''
    if '内政' in label:
        return False
    if '回合' in label:
        return True
    rnd = (point or {}).get('round')
    season = (point or {}).get('season')
    if isinstance(rnd, int) and not (season == 0 and rnd == 0):
        return True
    return False


def prefer_season_point(new, old):
    new_military = is_military_round(new)
    old_military = is_military_round(old)
    if old_military and not new_military:
        return True
    if not old_military and not new_military:
        return True
    return False


def season_chart_label(point):
    pretty = calendar_label((point or {}).get('year'), (point or {}).get('season'))
    if pretty:
        return pretty
    return (point or {}).get('label') or '季未知'


SUMMER_SEASON = 1


def seasons_until_next_summer(year, season):
    """Seasons strictly after (year, season), stopping at the next summer."""
    if not isinstance(year, int) or season not in (0, 1, 2, 3):
        return []
    out = []
    y, s = year, season
    for _ in range(4):
        s += 1
        if s > 3:
            s = 0
            y += 1
        out.append({'year': y, 'season': s, 'label': calendar_label(y, s)})
        if s == SUMMER_SEASON:
            break
    return out


def _same_season(left, right):
    key = season_key(left)
    if key is not None:
        return season_key(right) == key
    return (left or {}).get('label') == (right or {}).get('label')


def append_troop_series(series, point):
    rows = list(series or [])
    if not point or not point.get('forces'):
        return rows
    for index, row in enumerate(rows):
        if _same_season(row, point):
            if prefer_season_point(point, row):
                rows[index] = point
            return rows[-120:]
    rows.append(point)
    rows.sort(key=lambda row: season_key(row) or (10 ** 9, 10 ** 9))
    return rows[-120:]


def merge_troop_series(*groups):
    merged = []
    for group in groups:
        for point in group or []:
            merged = append_troop_series(merged, point)
    return merged


def samples_for_force(series, force_id):
    key = str(force_id)
    out = []
    for point in series or []:
        sample = (point.get('forces') or {}).get(key)
        if not sample:
            continue
        out.append({
            'label': season_chart_label(point),
            'year': point.get('year'),
            'season': point.get('season'),
            **sample,
        })
    return out
