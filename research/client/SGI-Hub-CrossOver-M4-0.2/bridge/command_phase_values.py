"""Memory values at the input/settlement boundary, shared once per cohort.

These are observed net changes, including consumption/caps/other operations.
They never claim an individual command gain, commitment, or cheat verdict.
"""
from copy import deepcopy
from datetime import timedelta

from command_display import _stamp, sampling_calendar
from command_effects import metrics, _number, KINDS
from scout_location import binding_digest
from state_history import troop_text


def settlement_sample(before, after):
    p, q = before.get('phase_candidate') or {}, after.get('phase_candidate') or {}
    if (p.get('turn_u16') not in (0, 1) or q.get('turn_u16') != 2
            or (p.get('year_u16'), p.get('season_u16')) != (q.get('year_u16'), q.get('season_u16'))):
        return None
    left = {r['force_id']: r for r in (before.get('entities') or {}).get('lords') or []}
    right = {r['force_id']: r for r in (after.get('entities') or {}).get('lords') or []}
    rows = []
    for owner in left.keys() & right.keys():
        for metric in ('gold', 'rice', 'prestige', 'infantry', 'cavalry', 'bow'):
            a, b = left[owner], right[owner]
            if metric in KINDS.values():
                a, b = (a.get('armament_raw') or {}).get(metric), (b.get('armament_raw') or {}).get(metric)
            else:
                a, b = a.get(metric), b.get(metric)
            if type(a) is int and type(b) is int:
                rows.append(dict(owner=owner, metric=metric, before=a, after=b))
    return dict(sample_start=before.get('capture_end'), sample_end=after.get('capture_end'), rows=rows)


def valid_segments(value, limit):
    segments=value.get('segments')
    if segments is None:
        a,b=_stamp(value['sample_start']),_stamp(value['sample_end'])
        return a is not None and b is not None and 0 < (b-a).total_seconds() <= 10
    if not isinstance(segments,list) or not 1 <= len(segments) <= 16:
        return False
    previous=None
    for segment in segments:
        a,b=_stamp(segment.get('sample_start')),_stamp(segment.get('sample_end'))
        if (a is None or b is None or not 0 < (b-a).total_seconds() <= 10
                or any(type(segment.get(k)) is not int or not 0 <= segment[k] <= limit for k in ('before','after'))
                or previous is not None and (previous['after'] != segment['before'] or _stamp(previous['sample_end']) > a)):
            return False
        previous=segment
    return (segments[0]['before']==value['before'] and segments[-1]['after']==value['after']
            and segments[0]['sample_start']==value['sample_start'] and segments[-1]['sample_end']==value['sample_end'])


def valid_phase_value(row, value, binding):
    try:
        start, end, opening = (_stamp(value[k]) for k in ('sample_start', 'sample_end', 'window_from'))
        stamp = _stamp(row['observed_at'])
        calendar = sampling_calendar(row, {})
        metric = value['metric']
        limit = 300 if metric in KINDS.values() else 200 if metric == 'prestige' else 2**31-1
        ids = value['members']
        return (value['basis'] == 'state_settlement_net_observation'
                and value['binding_sha256'] == binding_digest(binding)
                and value['owner'] == row['actor_force_id']
                and calendar == (value['year'], value['season'])
                and metric in metrics(row)
                and start is not None and end is not None and opening is not None and stamp is not None
                and opening <= start < end and opening <= stamp <= end
                and 0 < (end-start).total_seconds() <= 21600 and valid_segments(value,limit)
                and 0 < (end-opening).total_seconds() <= 21600
                and all(type(value[k]) is int and 0 <= value[k] <= limit for k in ('before', 'after'))
                and isinstance(ids, list) and 1 <= len(ids) <= 512
                and len(set(ids)) == len(ids) and row['source_line_sha256'] in ids
                and all(type(s) is str and len(s) == 64 and all(c in '0123456789abcdef' for c in s) for s in ids))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def retain_phase_values(commands, history):
    out = deepcopy(commands)
    rows, binding = out.get('rows') or [], out.get('binding') or {}
    for row in rows:
        row['phase_changes'] = [v for v in row.get('phase_changes') or [] if valid_phase_value(row, v, binding)]
    windows = list((history or {}).get('quarters') or []) + [(history or {}).get('current_quarter') or {}]
    for w in windows:
        phase, after = w.get('phase') or {}, w.get('phase_after') or {}
        calendar = phase.get('year_u16'), phase.get('season_u16')
        if (phase.get('turn_u16') not in (0, 1) or after.get('turn_u16') != 2
                or calendar != (after.get('year_u16'), after.get('season_u16'))):
            continue
        opening, ending = _stamp(w.get('from')), _stamp(w.get('to'))
        if opening is None or ending is None:
            continue
        observed = []
        sample = w.get('settlement_sample') or {}
        for v in sample.get('rows') or []:
            observed.append(dict(v, sample_start=sample.get('sample_start'), sample_end=sample.get('sample_end')))
        # Add input-period transitions too: trade costs can be applied before
        # the final boundary. Chain matching before/after observations, never
        # add the final payment to every packet or include pre-command income.
        for c in (history or {}).get('recent_changes') or []:
            end=_stamp(c.get('time'))
            if c.get('entity') != 'lords' or end is None or not opening < end <= ending:
                continue
            gap=c.get('gap_seconds')
            if type(gap) not in (int,float) or not 0 < gap <= 10:
                continue
            metric=c.get('kind') if c.get('metric')=='training' else {'信望':'prestige','金钱':'gold','粮食':'rice'}.get(c.get('field'))
            observed.append(dict(owner=c.get('owner'),metric=metric,
                                 before=_number(c.get('raw_before') if metric in KINDS.values() else c.get('before')),
                                 after=_number(c.get('raw_after') if metric in KINDS.values() else c.get('after')),
                                 sample_start=(end-timedelta(seconds=gap)).isoformat(),sample_end=c['time']))
        buckets={}
        for v in observed:
            buckets.setdefault((v['owner'],v['metric']),{})[(v['sample_end'],v['before'],v['after'])]=v
        for (owner,metric), observations in buckets.items():
            peers=[r for r in rows if r.get('actor_force_id')==owner and metric in metrics(r)
                   and sampling_calendar(r,history)==calendar and _stamp(r.get('observed_at')) is not None
                   and opening <= _stamp(r['observed_at']) <= ending]
            if not peers:
                continue
            first=min(_stamp(r['observed_at']) for r in peers)
            candidates=sorted((v for v in observations.values() if first <= _stamp(v['sample_end']) <= ending),key=lambda v:_stamp(v['sample_end']))
            boundary=[v for v in candidates if _stamp(v['sample_end'])==ending]
            if len(boundary)!=1:
                continue
            chain=[boundary[0]]
            for v in (reversed(candidates) if metric in ('gold','rice') else ()):
                if _stamp(v['sample_end']) >= _stamp(chain[0]['sample_end']):
                    continue
                if v['after'] != chain[0]['before'] or _stamp(v['sample_end']) > _stamp(chain[0]['sample_start']):
                    break
                chain.insert(0,v)
            # Bound response/cache size. The final boundary is still a valid
            # observed net value if a longer input history cannot be retained.
            if len(chain)>16:chain=[boundary[0]]
            value=dict(boundary[0],basis='state_settlement_net_observation',binding_sha256=binding_digest(binding),
                       year=calendar[0],season=calendar[1],window_from=w['from'],
                       members=sorted(r['source_line_sha256'] for r in peers),
                       before=chain[0]['before'],sample_start=chain[0]['sample_start'],
                       segments=[{k:v[k] for k in ('before','after','sample_start','sample_end')} for v in chain])
            for row in peers:
                if valid_phase_value(row,value,binding):
                    row['phase_changes']=[a for a in row['phase_changes'] if a['metric']!=metric]+[deepcopy(value)]
    return out


def phase_summaries(rows, binding):
    groups = {}
    for row in rows:
        for v in row.get('phase_changes') or []:
            if not valid_phase_value(row, v, binding):
                continue
            key = tuple(v['members']), v['sample_end']
            g = groups.setdefault(key, dict(values={}, actions=set()))
            g['values'][v['metric']] = v
            g['actions'].add(row.get('action') or '指令')
    out = []
    for (ids, _), group in groups.items():
        parts = []
        for metric, v in group['values'].items():
            a,b = v['before'],v['after']
            if metric in KINDS.values():
                parts.append(f'{troop_text(metric,a)}→{troop_text(metric,b)}（{b-a:+d}）')
            else:
                name = {'gold':'金','rice':'粮','prestige':'信望'}[metric]
                parts.append(f'{name} {a:,}→{b:,}（{b-a:+d}）')
        actions = '／'.join(sorted(group['actions']))
        resource_title = {frozenset({'gold'}):'阶段金钱', frozenset({'rice'}):'阶段粮食',
                          frozenset({'gold','rice'}):'阶段金粮'}
        title = resource_title.get(frozenset(group['values']), f'{actions} {len(ids)}笔')
        out.append(title+' · 观测净值：'+'；'.join(parts))
    return out
