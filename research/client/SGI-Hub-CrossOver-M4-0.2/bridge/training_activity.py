"""Count retained training/build records, never verified executions.

Queue re-observations do not multiply counts. For each season/kind, use the
larger of decoded records and filtered state-history records, rather than
adding two views of the same activity. A training interval may contain several
orders; these counts describe the retained record coverage only.
"""
from collections import Counter
import json
import re

from command_display import display_rows, sampling_calendar
from state_history import camp_builds_from_history, recent_quarter_ops

KINDS = ('infantry', 'cavalry', 'bow')
TRAIN_FIELDS = dict(zip(('训练步兵', '训练骑兵', '训练弓兵'), KINDS))
CAMP_KINDS = dict(zip(('练兵所', '牧场', '弓工坊'), KINDS))


def _calendar(phase):
    phase = phase or {}
    year, season = phase.get('year_u16'), phase.get('season_u16')
    return (year, season) if type(year) is int and year > 0 and type(season) is int and 0 <= season < 4 else None


def _building_count(row):
    places = len(row.get('places') or [])
    number = re.search(r'新建\s*(\d+)\s*座', row.get('line') or '')
    return max(places, int(number.group(1)) if number else 1)


def activity_counts(state, force_id):
    """Pure force-filtered totals; reads only the supplied live/replay state."""
    state = state or {}
    history = state.get('history') or {}
    packets, observed = Counter(), Counter()
    seen = set()
    for row in display_rows(state.get('native_command_evidence') or {}):
        if force_id is None or row.get('actor_force_id') != force_id or row.get('native_type') != 18:
            continue
        subtype, parameter = row.get('subtype'), row.get('parameter_raw')
        if subtype == 0 and parameter in (0, 1, 2):
            metric, kind = 'training', KINDS[parameter]
        elif subtype == 4 and parameter in (7, 8, 9):
            metric, kind = 'building', KINDS[parameter - 7]
        else:
            continue
        binding = json.dumps(row.get('display_binding') or {}, sort_keys=True)
        if row.get('queue_entry_hex') and row.get('raw_sha256'):
            key = (binding, row['queue_entry_hex'], row['raw_sha256'])
        else:
            key = (binding, row.get('source_line_sha256') or json.dumps(row, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        packets[(sampling_calendar(row, history), metric, kind)] += 1

    seen = set()
    for block in recent_quarter_ops(history, force_id, None) if force_id is not None else []:
        calendar = _calendar(block.get('phase'))
        for row in block['operations']:
            kind = TRAIN_FIELDS.get(row.get('field'))
            if not kind:
                continue
            key = (calendar, kind, row.get('line'), row.get('before'), row.get('after'))
            if key not in seen:
                observed[(calendar, 'training', kind)] += 1
                seen.add(key)

    seen = set()
    for row in camp_builds_from_history(history):
        kind = CAMP_KINDS.get(row.get('kind'))
        if force_id is None or row.get('owner') != force_id or not kind:
            continue
        calendar = _calendar(row.get('phase'))
        key = (calendar, kind, row.get('seq'), row.get('line'), tuple(row.get('places') or []))
        if key not in seen:
            observed[(calendar, 'building', kind)] += _building_count(row)
            seen.add(key)

    by_kind = {kind: dict(training=0, building=0) for kind in KINDS}
    for kind in KINDS:
        for metric in ('training', 'building'):
            keys = {key for key in packets.keys() | observed.keys() if key[1:] == (metric, kind)}
            dated = sum(max(packets[key], observed[key]) for key in keys if key[0] is not None)
            # Undated bytes may describe an already dated state interval.
            # Preserve the larger coverage without counting that overlap twice.
            by_kind[kind][metric] = max(dated, sum(packets[key] for key in keys),
                                      sum(observed[key] for key in keys))
    return dict(by_kind=by_kind, training=sum(r['training'] for r in by_kind.values()),
                building=sum(r['building'] for r in by_kind.values()), coverage='retained_records')
