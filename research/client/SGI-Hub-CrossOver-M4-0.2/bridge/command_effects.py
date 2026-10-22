"""Display-only state/packet correlation, never settlement or training labels.

One metric observation must match exactly one packet within the same short
sampling interval. Net seasonal gains are not evidence of a single action.
The red badge means an operand exceeds a conservative native envelope, not
proof of a particular tool, execution count, or server result.
"""
from copy import deepcopy
from datetime import timedelta
import math

from command_display import _stamp, sampling_calendar, short_command
from state_history import troop_text

KINDS = {0: 'infantry', 1: 'cavalry', 2: 'bow'}
RED = '#b11a1a'


def metrics(row):
    if row.get('native_type') != 18:
        return ()
    subtype = row.get('subtype')
    if subtype == 2:
        return ('prestige',)
    if subtype == 0 and row.get('parameter_raw') in KINDS:
        return (KINDS[row['parameter_raw']],)
    if subtype == 3 and row.get('parameter_raw') in (0, 1):
        return ('gold', 'rice')
    if subtype == 4 and row.get('parameter_raw') in (4, 5, 6, 7, 8, 9):
        return ('gold',)
    return ()


def _number(value):
    if type(value) is int:
        return value
    if type(value) is str:
        try:
            return int(value.replace(',', ''))
        except ValueError:
            pass
    return None


def valid_change(row, change):
    if not isinstance(change, dict) or change.get('basis') != 'state_sample_correlation':
        return False
    start, end = _stamp(row.get('observed_at')), _stamp(change.get('sample_end'))
    gap = change.get('gap_seconds')
    if (start is None or end is None or type(gap) not in (int, float)
            or not math.isfinite(gap) or not 0 < gap <= 3
            or not end-timedelta(seconds=gap) <= start <= end
            or change.get('metric') not in metrics(row)):
        return False
    before, after = change.get('before'), change.get('after')
    metric = change['metric']
    limit = 300 if metric in KINDS.values() else 200 if metric == 'prestige' else 2**31-1
    if any(type(v) is not int or not 0 <= v <= limit for v in (before, after)) or before == after:
        return False
    upper, stock, stock_after = change.get('politics_upper'), change.get('stock_before'), change.get('stock_after')
    return ((upper is None or type(upper) is int and 0 <= upper <= 357)
            and (stock is None or type(stock) is int and 0 <= stock <= 2000000)
            and (stock_after is None or type(stock_after) is int and 0 <= stock_after <= 2000000))


def retain_effects(commands, history):
    result = deepcopy(commands)
    rows = result.get('rows') or []
    for row in rows:
        row['state_changes'] = [c for c in row.get('state_changes', []) if valid_change(row, c)]
    observations = {}
    for change in (history or {}).get('recent_changes') or []:
        if change.get('entity') != 'lords':
            continue
        metric = (change.get('kind') if change.get('metric') == 'training' else
                  {'信望': 'prestige', '金钱': 'gold', '粮食': 'rice'}.get(change.get('field')))
        if metric is None:
            continue
        training = metric in KINDS.values()
        sample = dict(basis='state_sample_correlation', metric=metric,
                      before=_number(change.get('raw_before' if training else 'before')),
                      after=_number(change.get('raw_after' if training else 'after')),
                      sample_end=change.get('time'), gap_seconds=change.get('gap_seconds'),
                      politics_upper=change.get('training_politics_upper_before'),
                      stock_before=change.get('training_stock_before'),
                      stock_after=change.get('training_stock_after'))
        key = (change.get('owner'), metric, sample['sample_end'], sample['before'], sample['after'])
        observations[key] = (change, sample)
    candidates = []
    for change, sample in observations.values():
        phase = change.get('phase') or {}
        calendar = phase.get('year_u16'), phase.get('season_u16')
        matches = [index for index, row in enumerate(rows)
                   if row.get('actor_force_id') == change.get('owner')
                   and sampling_calendar(row, history) == calendar and valid_change(row, sample)]
        if len(matches) == 1:
            candidates.append((matches[0], sample))
    for index, sample in candidates:
        # Two observed transitions in the same packet interval remain ambiguous.
        if sum(i == index and c['metric'] == sample['metric'] for i, c in candidates) != 1:
            continue
        rows[index]['state_changes'] = [c for c in rows[index]['state_changes'] if c['metric'] != sample['metric']]
        rows[index]['state_changes'].append(sample)
    return result


def _operand_anomaly(row):
    if row.get('native_type') != 18:
        return ''
    if row.get('subtype') == 2 and type(row.get('extra_raw')) is int:
        gain = row['extra_raw'] + 5
        # Documentation gives 5–10; use the wider bound conservatively.
        if not 5 <= gain <= 10:
            return f'施舍加值参数{gain}超出原版单次5–10'
    if row.get('subtype') == 0 and row.get('parameter_raw') in KINDS:
        politics = row.get('value_raw')
        changes = [c for c in row.get('state_changes', []) if valid_change(row, c)]
        upper = next((c['politics_upper'] for c in changes if c.get('politics_upper') is not None), 357)
        if type(politics) is int and politics > upper:
            return f'训练政治参数{politics}超出采样前后所属将保守上限{upper}' if changes and upper != 357 else f'训练政治参数{politics}超出保守上限357'
    return ''


def anomaly_reason(row):
    reason = _operand_anomaly(row)
    if reason:
        return reason
    for change in row.get('state_changes', []):
        if not valid_change(row, change):
            continue
        before, after = change['before'], change['after']
        if change['metric'] == 'prestige' and after-before > 10:
            return f'观测信望增加{after-before}超出单次10；可能漏采连续施令或其他来源，未确认外挂'
        if change['metric'] in KINDS.values():
            stock, upper = change.get('stock_before'), change.get('politics_upper')
            if stock is None or stock != change.get('stock_after') or upper is None:
                continue
            muldiv = lambda a,b,c: (a*b+c//2)//c
            base = max(5,10-muldiv(stock,5,100000))
            a,b = {'infantry':(2,1),'cavalry':(3,2),'bow':(1,1)}[change['metric']]
            maximum = min(300-before,muldiv(base+1,a*max(50,upper),b*50))
            if after-before > maximum:
                return f'观测训练增加{after-before}超出单次保守上限{maximum}；可能漏采连续施令，未确认外挂'
    return ''


def badge_text(row):
    return '外挂' if _operand_anomaly(row) else '疑似外挂' if anomaly_reason(row) else ''


def effect_text(row, generals=()):
    text = short_command(row, generals)
    if not metrics(row):
        return text
    if row.get('phase_changes'):
        return text
    parts = []
    for change in row.get('state_changes', []):
        if not valid_change(row, change):
            continue
        metric, before, after = change['metric'], change['before'], change['after']
        if metric in KINDS.values():
            parts.append(f'{troop_text(metric,before)}→{troop_text(metric,after)}（{after-before:+d}，观测）')
        else:
            name = {'prestige': '信望', 'gold': '金', 'rice': '粮'}[metric]
            parts.append(f'{name} {before:,}→{after:,}（{after-before:+d}，观测）')
    if parts:
        return text + ' ' + '；'.join(parts)
    if row.get('subtype') == 2:
        gain = row.get('extra_raw')
        return text + (f' +{gain+5}参数 · 数值未确认' if type(gain) is int else ' · 数值未确认')
    if row.get('subtype') == 0:
        return text + f' 政治{row.get("value_raw", "?")} · 数值未确认'
    return text + ' · 数值未确认'


def force_badges(state):
    """Badges cover only packet observations inside this source history window."""
    history = (state or {}).get('history') or {}
    windows = list(history.get('quarters') or []) + [history.get('current_quarter') or {}]
    windows = [(_stamp(w.get('from')), _stamp(w.get('to'))) for w in windows]
    commands = retain_effects((state or {}).get('native_command_evidence') or {}, history)
    result = {}
    for row in commands.get('rows', []):
        badge, stamp = badge_text(row), _stamp(row.get('observed_at'))
        if (badge and stamp is not None
                and any(start is not None and end is not None and start <= stamp <= end for start,end in windows)):
            fid = row['actor_force_id']
            if result.get(fid) != '外挂':result[fid] = badge
    return result


def abnormal_force_ids(state):
    return set(force_badges(state))
