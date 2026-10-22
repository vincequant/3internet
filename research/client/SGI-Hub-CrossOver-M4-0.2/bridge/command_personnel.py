"""Source-state city names and pending-hire observations, never raw outcomes.

Ordinary recruitment targets a city. Only a unique pending_hire observation in
the same input window is paired; voluntary joins and later seasons are excluded.
"""
from copy import deepcopy

from command_display import _stamp, sampling_calendar
from scout_location import binding_digest
from network_payloads import SANPK_BUILD


def ordinary(row):
    return row.get('native_type') == 20 and row.get('subtype') == 0


def valid_personnel(row, ref, binding):
    try:
        if (not ordinary(row) or ref['schema'] != 'personnel-state-reference-1'
                or binding.get('build') != SANPK_BUILD
                or ref['binding_sha256'] != binding_digest(binding)
                or ref['basis'] != 'source_state_reference'
                or ref['actor_force_id'] != row['actor_force_id']
                or ref['city_id'] != row['target_raw']
                or type(ref['city_id']) is not int or not 0 <= ref['city_id'] < 65536
                or type(ref['city_name']) is not str or not 0 < len(ref['city_name']) <= 64
                or type(ref['snapshot_id']) is not str or not 0 < len(ref['snapshot_id']) <= 128
                or _stamp(ref['captured_at']) is None
                or _stamp(row['observed_at']) is None
                or _stamp(ref['captured_at']) < _stamp(row['observed_at'])):
            return False
        result = ref.get('result')
        if result is None:
            return True
        calendar = sampling_calendar(row, {})
        start, end = _stamp(result['window_from']), _stamp(result['observed_by'])
        return (result['basis'] == 'pending_hire_state_observation'
                and calendar == (result['year'], result['season'])
                and start is not None and end is not None
                and start <= _stamp(row['observed_at']) <= end <= _stamp(ref['captured_at'])
                and 0 < (end-start).total_seconds() <= 21600
                and type(result['general_id']) is int and 0 <= result['general_id'] < 65536
                and type(result['name']) is str and 0 < len(result['name']) <= 64)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def retain_personnel(commands, state):
    out = deepcopy(commands)
    bound = out.get('binding') or {}
    identity = (state or {}).get('identity') or {}
    if (identity.get('pid') != bound.get('pid')
            or identity.get('creation_filetime') != bound.get('created')
            or identity.get('path') != bound.get('image')
            or (state or {}).get('build_sha256') != bound.get('build')):
        return out
    history = state.get('history') or {}
    rows = out.get('rows') or []
    cities = (state.get('entities') or {}).get('cities_and_barriers') or []
    windows = list(history.get('quarters') or []) + [history.get('current_quarter') or {}]
    for row in rows:
        if not ordinary(row):
            continue
        old = row.get('personnel_reference')
        if valid_personnel(row, old, bound) and old.get('result'):
            continue
        matches = [c for c in cities if c.get('city_id') == row.get('target_raw') and c.get('name')]
        if len(matches) != 1:
            continue
        ref = deepcopy(old) if valid_personnel(row,old,bound) else dict(schema='personnel-state-reference-1', basis='source_state_reference',
                   binding_sha256=binding_digest(bound), actor_force_id=row['actor_force_id'], city_id=row['target_raw'],
                   city_name=matches[0]['name'], snapshot_id=state.get('snapshot_id'),
                   captured_at=state.get('capture_end'))
        candidates = {}
        stamp = _stamp(row.get('observed_at'))
        calendar = sampling_calendar(row, history)
        for w in windows:
            start, end = _stamp(w.get('from')), _stamp(w.get('to'))
            phase = w.get('phase') or {}
            if (stamp is None or start is None or end is None or not start <= stamp < end
                    or calendar != (phase.get('year_u16'), phase.get('season_u16'))):
                continue
            peers = [r for r in rows if ordinary(r) and r.get('actor_force_id') == row.get('actor_force_id')
                     and r.get('target_raw') == row.get('target_raw')
                     and _stamp(r.get('observed_at')) is not None and start <= _stamp(r['observed_at']) < end]
            if len(peers) != 1:
                continue
            for force in w.get('forces') or []:
                if force.get('owner') != row.get('actor_force_id'):
                    continue
                for op in force.get('operations') or []:
                    if (op.get('via') != 'pending_hire' or op.get('field') != '录用'
                            or (op.get('target') or {}).get('city_id') != row['target_raw']):
                        continue
                    result = dict(basis='pending_hire_state_observation',
                                  general_id=op.get('general_id'), name=op.get('after'),
                                  year=calendar[0], season=calendar[1],
                                  window_from=w['from'], observed_by=w['to'])
                    candidates[(result['general_id'], result['name'])] = result
        if len(candidates) == 1:
            ref['result'] = next(iter(candidates.values()))
            ref.update(snapshot_id=state.get('snapshot_id'),captured_at=state.get('capture_end'))
        if valid_personnel(row, ref, bound):
            row['personnel_reference'] = ref
        elif valid_personnel(row, old, bound):
            row['personnel_reference'] = deepcopy(old)
    return out


def hired_officer(result, generals):
    gid = result.get('general_id')
    rows = list(generals or ())
    found = [g for g in rows if type(gid) is int and g.get('general_id_raw') == gid]
    if len(found) == 1:
        officer = dict(found[0])
        if result.get('name'):
            officer['name'] = result['name']
        return officer
    named = [g for g in rows if result.get('name') and g.get('name') == result.get('name')]
    if len(named) == 1:
        return named[0]
    return {'name': result.get('name') or '未知'}


def personnel_text(row, generals=()):
    ref = row.get('personnel_reference') or {}
    name = ref.get('city_name') or f'城关#{row.get("target_raw", "?")}'
    result = ref.get('result')
    if not result:
        return f'录用 {name} · 未观察到结果'
    from officer_reference import recruit_title
    return f'录用 {name} → {recruit_title(hired_officer(result, generals))}（观测）'
