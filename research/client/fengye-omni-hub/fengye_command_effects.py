"""Conservative, read-only observation of train/build effects.

A local function return code is deliberately irrelevant here. These helpers
compare two original Collector snapshots bound to the same known process/core.
They report an observed state change, not native command or causal evidence.
No source/run identity is invented when Collector did not capture one.
"""
from copy import deepcopy
from datetime import datetime
import json
import math

TROOPS = {0: ('infantry', '步兵'), 1: ('cavalry', '騎兵'), 2: ('bow', '弓兵')}
BUILDINGS = {7: ('production_buildings', 'parade_ground', '兵營'),
             8: ('production_buildings', 'horse_farm', '馬房'),
             9: ('production_buildings', 'bow_studio', '弓房'),
             6: ('traps', 'trap', '陷阱')}
OPTIONAL_BINDINGS = ('source_id', 'source_pid', 'source_prefix', 'run_id', 'game_id',
                     'session_id', 'run_identity', 'game_identity')


def _integer(value, low=0, high=None):
    return type(value) is int and value >= low and (high is None or value <= high)


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is not None:
            return stamp.timestamp()
    except (TypeError, ValueError, AttributeError, OverflowError):
        pass
    return None


def _target(job):
    params = dict(job, **(job.get('params') or {}))
    actor = params.get('actor')
    if not _integer(actor, 0, 65534):
        raise ValueError('目標勢力未知')
    target = {'preset': job.get('preset'), 'actor': actor, 'job_id': job.get('id')}
    if target['preset'] == 'train':
        troop, value = params.get('troop'), params.get('value')
        if type(troop) is not int or troop not in TROOPS or value != 75 or type(value) is not int:
            raise ValueError('只核驗步／騎／弓固定值 75 的練兵')
        target.update(troop=troop, value=value)
    elif target['preset'] == 'build':
        kind = params.get('build_type')
        if type(kind) is not int or kind not in BUILDINGS:
            raise ValueError('只核驗兵營／馬房／弓房／陷阱')
        if not all(_integer(params.get(key), 0, 65534) for key in ('city', 'x', 'y')):
            raise ValueError('建設城池或格位未知')
        target.update(build_type=kind, city=params['city'], x=params['x'], y=params['y'])
    else:
        raise ValueError('此指令不支援效果核驗')
    return target


def _binding(state):
    identity = state.get('identity') or {}
    if not (_integer(identity.get('pid'), 1) and _integer(identity.get('creation_filetime'), 1)
            and isinstance(identity.get('path'), str) and identity['path']):
        raise ValueError('遊戲進程身分未知')
    core, build = state.get('core_address'), state.get('build_sha256')
    try:
        if not isinstance(core, str) or not core.startswith('0x') or int(core, 16) <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('遊戲核心身分未知')
    if not isinstance(build, str) or len(build) != 64 or any(c not in '0123456789abcdefABCDEF' for c in build):
        raise ValueError('遊戲版本身分未知')
    binding = {'identity': {key: identity[key] for key in ('pid', 'path', 'creation_filetime')},
               'core_address': core, 'build_sha256': build, 'schema': state.get('schema')}
    for key in OPTIONAL_BINDINGS:
        if state.get(key) is not None:
            binding[key] = deepcopy(state[key])
        if identity.get(key) is not None:
            binding['identity.'+key] = deepcopy(identity[key])
    if 'source_pid' in binding and binding['source_pid'] != identity['pid']:
        raise ValueError('來源 PID 與 Collector 進程不一致')
    # Scenario and roster are additional continuity guards, not invented game
    # IDs. Capital, resources and player_context are mutable and are not used.
    if state.get('scenario_map') is not None:
        binding['scenario_map'] = deepcopy(state['scenario_map'])
    lords = (state.get('entities') or {}).get('lords')
    if isinstance(lords, list):
        roster = [(r.get('force_id'), r.get('ruler_general_id'), r.get('name')) for r in lords]
        binding['roster'] = sorted(roster, key=lambda row: json.dumps(row, ensure_ascii=False))
    return binding


def _snapshot(state, containers):
    if not isinstance(state, dict) or state.get('schema') != 'astra-sgi-core-2' or state.get('readonly') is not True:
        raise ValueError('需要原始唯讀 Collector 快照')
    if (state.get('consistency') or {}).get('root_headers_and_clock_unchanged') is not True:
        raise ValueError('取樣期間結構／時鐘不穩定')
    start, end = _stamp(state.get('capture_start')), _stamp(state.get('capture_end'))
    if start is None or end is None or end < start or not state.get('snapshot_id'):
        raise ValueError('快照時間或識別未知')
    entities, coverage = state.get('entities') or {}, state.get('coverage') or {}
    for kind in containers:
        rows, meta = entities.get(kind), coverage.get(kind) or {}
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError('%s 容器未知' % kind)
        if meta.get('structurally_valid') is not True or meta.get('count') != len(rows):
            raise ValueError('%s 容器覆蓋未核實' % kind)
    return {'snapshot_id': state['snapshot_id'], 'capture_start': state['capture_start'],
            'capture_end': state['capture_end'], 'start': start, 'end': end}


def _lord(state, actor):
    matches = [row for row in state['entities']['lords'] if row.get('force_id') == actor]
    if len(matches) != 1:
        raise ValueError('目標勢力資料未知或重複')
    return matches[0]


def _xy(row):
    value = row.get('world_xy_raw')
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(_integer(v) for v in value):
        return tuple(value)
    return None


def _object(row):
    fields = ('type', 'trap_kind', 'owner_raw', 'world_xy_raw', 'linked_city_id',
              'object_id_candidate', 'trap_id', 'address', 'building_ui_amount')
    return {key: deepcopy(row[key]) for key in fields if key in row}


def _observe(target, state):
    lord = _lord(state, target['actor'])
    gold = lord.get('gold') if _integer(lord.get('gold')) else None
    if target['preset'] == 'train':
        kind, _ = TROOPS[target['troop']]
        raw = (lord.get('armament_raw') or {}).get(kind)
        if not _integer(raw, 0, 300):
            raise ValueError('目標兵種累積訓練值未知')
        return {'actor': target['actor'], 'troop': kind, 'training_raw': raw, 'gold': gold}
    xy = (target['x'], target['y'])
    cities = [row for row in state['entities']['cities_and_barriers'] if row.get('city_id') == target['city']]
    if len(cities) != 1 or cities[0].get('owner_raw') != target['actor']:
        raise ValueError('建設城池不屬於目標勢力或身分未知')
    occupants = []
    for kind in ('cities_and_barriers', 'production_buildings', 'traps'):
        for row in state['entities'][kind]:
            location = _xy(row)
            if location is None:
                raise ValueError('%s 物件位置未知，無法核實格位佔用' % kind)
            if location == xy:
                occupants.append(dict(_object(row), container=kind))
    return {'actor': target['actor'], 'city': target['city'], 'xy': list(xy),
            'gold': gold, 'objects': occupants}


def capture_effect_baseline(job, state):
    """Freeze source-bound facts before dispatch; ``ok=False`` is not usable."""
    try:
        target = _target(job)
        containers = ['lords'] if target['preset'] == 'train' else ['lords', 'cities_and_barriers', 'production_buildings', 'traps']
        sample = _snapshot(state, containers)
        binding = _binding(state)
        observation = _observe(target, state)
        return {'ok': True, 'version': 1, 'target': target, 'binding': binding,
                'sample': sample, 'observation': observation}
    except (TypeError, ValueError, KeyError) as exc:
        return {'ok': False, 'version': 1, 'error': str(exc)}


def check_effect(job, baseline, state):
    """Confirm only a fresh observed numeric/object change on the same source.

    Callers must serialize overlapping commands for the same actor/troop (or
    build cell); otherwise one observed change cannot be attributed per job.
    """
    result = {'confirmed': False, 'summary': '', 'before': None, 'after': None,
              'evidence': {'kind': 'observed_state_change', 'native_command_proof': False,
                           'causal_attribution': 'not_proven',
                           'limitation': '只確認同來源前後觀測；不是原始指令或因果證明。Collector 無獨立局ID時不補造；同進程／核心重用仍有識別限制。'}}
    if not isinstance(baseline, dict) or baseline.get('ok') is not True:
        result['summary'] = '送出前基準未知，不能確認完成'
        return result
    result['before'] = deepcopy(baseline.get('observation'))
    current = capture_effect_baseline(job, state)
    if not current.get('ok'):
        result['summary'] = '等待可核驗資料：'+current.get('error', '未知')
        return result
    result['after'] = deepcopy(current['observation'])
    if current['target'] != baseline.get('target'):
        result['summary'] = '指令目標已變更，不能共用基準'
        return result
    if current['binding'] != baseline.get('binding'):
        result['summary'] = '來源進程、核心或已知局身分變更，不能跨局核驗'
        return result
    old, new = baseline.get('sample') or {}, current['sample']
    if (new['snapshot_id'] == old.get('snapshot_id') or
            not isinstance(old.get('end'), (int, float)) or new['start'] <= old['end']):
        result['summary'] = '尚未取得晚於送出前基準的新快照'
        return result
    receipt_at = job.get('receipt_at')
    if receipt_at is not None:
        if (type(receipt_at) not in (int, float) or not math.isfinite(receipt_at) or
                new['start'] <= receipt_at):
            # A shared in-flight read may have started before the native send
            # was observed. Wait for a genuinely later sample, never use it as
            # this command's completed effect. This still proves observation,
            # not causal attribution or original input evidence.
            result['summary'] = '等待下令回報之後取得的新快照，尚未確認完成'
            return result
    result['evidence'].update(binding=deepcopy(current['binding']), before_sample=deepcopy(old), after_sample=deepcopy(new))
    target, before, after = current['target'], result['before'], result['after']
    if not isinstance(before, dict):
        result['summary'] = '送出前基準不完整'
        return result
    if target['preset'] == 'train':
        raw = before.get('training_raw')
        if not _integer(raw, 0, 300):
            result['summary'] = '送出前訓練值未知'
            return result
        actual = after['training_raw']
        expected = min(300, raw+30)
        result['evidence'].update(field='entities.lords.armament_raw.'+TROOPS[target['troop']][0],
                                  observed_delta=actual-raw, rule='fixed value75; +30 capped at300',
                                  required_after=expected)
        if raw == 300:
            result['summary'] = '訓練值已達 300，未觀測到增加，不能確認完成'
        elif actual == expected and actual > raw:
            result['confirmed'] = True
            result['summary'] = '已觀測%s累積訓練值 %s → %s（+%s）' % (TROOPS[target['troop']][1], raw, actual, actual-raw)
        else:
            result['summary'] = '等待%s訓練變化：%s → %s；單靠金幣變化不確認' % (TROOPS[target['troop']][1], raw, actual)
    else:
        if before.get('objects'):
            result['summary'] = '送出前目標格已有物件，不能當作本次新建'
            return result
        container, kind, label = BUILDINGS[target['build_type']]
        rows = after['objects']
        matches = [row for row in rows if row.get('container') == container
                   and row.get('type') == kind and row.get('owner_raw') == target['actor']
                   and (row.get('trap_kind') == '陷阱' if target['build_type'] == 6 else row.get('linked_city_id') == target['city'])]
        if len(matches) == 1 and len(rows) == 1:
            result['confirmed'] = True
            result['summary'] = '已觀測新%s：勢力 %s，位置 %s,%s' % (label, target['actor'], target['x'], target['y'])
            result['evidence'].update(container=container, new_object=deepcopy(matches[0]))
        else:
            result['summary'] = '尚未觀測到同格、同勢力、同種類的新%s' % label
    if before.get('gold') is not None and after.get('gold') is not None:
        result['evidence']['gold_change'] = {'before': before['gold'], 'after': after['gold'], 'sufficient_alone': False}
    return result
