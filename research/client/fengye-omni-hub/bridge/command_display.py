"""Compact viewer groups. Calendar correlation is not an order/match binding.

Use the original first-observation timestamp and the source's history windows,
never a force's state changes, action effects, or today's game date. These dates
describe the sampling period only; decoded evidence and training flags stay intact.
"""
from datetime import datetime

SEASONS = ('春', '夏', '秋', '冬')
CIVIL_TYPES = (16, 18, 19, 20)


def display_rows(commands):
    """Presentation only: retain each row's actual source binding.

    A common packet within 90s and the same sampling season is displayed once
    across the explicitly paired sources. This is not execution-count proof.
    Repetitions within either source are not removed by this presentation rule.
    """
    rows=[dict(r,display_binding=commands.get('binding') or {}) for r in commands.get('rows') or []]
    from datetime import timedelta
    primary=list(rows)
    for peer in commands.get('supplemental_sources') or []:
        unmatched=list(primary)
        for row in peer.get('rows') or []:
            stamp=_stamp(row.get('observed_at'));matched=None
            for i,other in enumerate(unmatched):
                other_stamp=_stamp(other.get('observed_at'))
                if (stamp and other_stamp and row.get('raw_sha256')==other.get('raw_sha256')
                        and sampling_calendar(row,{})==sampling_calendar(other,{})
                        and sampling_calendar(row,{}) is not None
                        and abs(stamp-other_stamp)<=timedelta(seconds=90)):
                    matched=i;break
            if matched is not None:unmatched.pop(matched);continue
            rows.append(dict(row,display_binding=peer['binding'],display_source=peer['binding']['source_id']))
    return rows


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def sampling_calendar(row, history):
    """A unique, half-open history interval; ambiguous boundaries stay unknown."""
    retained = row.get('sampling_calendar') or {}
    year, season = retained.get('year_u16'), retained.get('season_u16')
    if (retained.get('basis') == 'sampling_time_correlation'
            and type(year) is int and 1 <= year <= 65535
            and type(season) is int and 0 <= season < 4):
        return year, season
    stamp = _stamp(row.get('observed_at'))
    if stamp is None:
        return None
    windows = list((history or {}).get('quarters') or [])
    current = (history or {}).get('current_quarter')
    if current:
        windows.append(current)
    matches = set()
    boundaries = {}
    for window in windows:
        phase = window.get('phase') or {}
        year, season = phase.get('year_u16'), phase.get('season_u16')
        start, end = _stamp(window.get('from')), _stamp(window.get('to'))
        if (type(year) is not int or not 1 <= year <= 65535
                or type(season) is not int or not 0 <= season < 4
                or start is None or end is None or start >= end):
            continue
        key = (year, season)
        if start <= stamp < end:
            matches.add(key)
        for edge in (start, end):
            if abs((stamp - edge).total_seconds()) < 1.5:
                boundaries.setdefault(edge, set()).add(key)
    # A phase boundary within a season is fine. Around a season transition,
    # capture latency makes either date possible; do not pick the nearer one.
    if any(len(keys) > 1 for keys in boundaries.values()):
        return None
    return next(iter(matches)) if len(matches) == 1 else None


def retain_calendars(commands, history, snapshot_id=None):
    """Keep derived display dates with the observed bytes before history expires."""
    result = dict(commands)
    result['rows'] = []
    for original in commands.get('rows') or []:
        row = dict(original)
        calendar = sampling_calendar(row, history)
        if calendar is not None:
            row['sampling_calendar'] = dict(year_u16=calendar[0], season_u16=calendar[1],
                                            basis='sampling_time_correlation', snapshot_id=snapshot_id)
        result['rows'].append(row)
    return result


def general_name(target, generals=()):
    names = [g.get('name') for g in generals
             if g.get('general_id_raw') == target and g.get('name')]
    return names[0] if len(names) == 1 else f'武将#{target}'


def short_command(row, generals=()):
    kind, subtype = row.get('native_type'), row.get('subtype')
    if kind == 18 and subtype == 4:
        from command_construction import construction, construction_text
        if construction(row):
            return construction_text(row)
    if kind == 19 and subtype in (3, 4):
        return {3: '换外交卡', 4: '外交卡排序'}[subtype]
    if kind == 20:
        if subtype == 0 and row.get('personnel_reference'):
            from command_personnel import personnel_text
            return personnel_text(row, generals)
        action = {0: '录用', 1: '自动加入', 2: '解雇', 5: '加增'}.get(subtype, row.get('action'))
        target = row.get('target_raw', '?')
        name = f'城关#{target}' if subtype == 0 else general_name(target, generals)
        return f'{action} {name}'
    return str(row.get('action') or '未解码指令')


def command_groups(rows, history):
    """Civil/military classification follows proven command types, not effects.

    The decoder supports sortie creation and domestic/diplomacy/personnel packets.
    Do not invent military orders or assign unknown packet types to a lane.
    Personnel subtype 1 is quarterly automatic joining, outside order numbering.
    """
    groups = {}
    for row in rows:
        lane = 'civil' if row.get('native_type') in CIVIL_TYPES else 'unknown'
        calendar = sampling_calendar(row, history)
        group = groups.setdefault((lane, calendar), dict(lane=lane, calendar=calendar,
                                                       rows=[], automatic_joins=[]))
        category = 'automatic_joins' if row.get('native_type') == 20 and row.get('subtype') == 1 else 'rows'
        group[category].append(row)
    for group in groups.values():
        for category in ('rows', 'automatic_joins'):
            group[category].sort(key=lambda r: r.get('observed_at') or '', reverse=True)
        calendar = group['calendar']
        group['label'] = (f'{calendar[0]}年{SEASONS[calendar[1]]}' if calendar else '日期未确认')
    return sorted(groups.values(), key=lambda g: (g['calendar'] is not None, g['calendar'] or (0, 0)), reverse=True)
