"""Read-only enemy-specific reference comparisons, never damage predictions."""
import json
from functools import lru_cache
from force_relations import at_war, relation_to_player
from player_view import player_id
from preparation_model import recommend, skills_for, valid
from unit_target_attack import supported_combat_build, rnd

SPELL_COUNTERS = {'火攻': '反计', '落石': '反计', '混乱': '收拾', '天雷': '天变', '引诱': '收拾'}


@lru_cache(maxsize=1)
def candidate_cache(serialized, include_field):
    return recommend(json.loads(serialized), include_field, all_candidates=True)


def candidate_state(state):
    entities = state.get('entities', {})
    keys = ('general_id_raw','name','owner_raw','soldiers','attributes','status_code','combat_modifier_flags')
    return dict(build_sha256=state.get('build_sha256'), player_force_id=state.get('player_force_id'),
        player_identity=state.get('player_identity'), entities=dict(
            lords=[f for f in entities.get('lords',[]) if f.get('force_id') == player_id(state)],
            generals=[{k:g[k] for k in keys if k in g} for g in entities.get('generals',[])],
            field_units=[dict(general_ids=u.get('general_ids',[])) for u in entities.get('field_units',[])]))


def targets(state, other=False):
    own = player_id(state)
    if own is None:
        return []
    return [u for u in state.get('entities', {}).get('field_units', [])
            if type(u.get('owner_raw')) is int and u['owner_raw'] != own
            and (at_war(state, u['owner_raw']) or
                 (other and relation_to_player(state, u['owner_raw']) not in (2, 3))) ]


def enemy_attack(unit):
    components = unit.get('target_attack_components', {})
    values = components.get('reference_unit', components.get('unit'))
    power = unit.get('basic_combat_power')
    if not isinstance(values, list) or not values or not valid(power, 0, 150):
        return None
    if not all(valid(v, 0, 10000) for v in values):
        return None
    return [rnd(v * power / 150) for v in values]


def compare(row, enemy):
    if enemy is None:
        return '敌攻击缺参数'
    if min(row['attack']) > max(enemy):
        return '参考攻击严格超过'
    if max(row['attack']) > min(enemy):
        return '仅部分技能情景超过'
    return '未超过（含持平）'


def counter_recommend(state, target, include_field=True):
    result = {'physical': [], 'spells': [], 'message': '', 'enemy_attack': None, 'morale_assumption': '双方满士气100'}
    if not supported_combat_build(state.get('build_sha256')):
        result['message'] = '客户端版本未匹配'; return result
    if not any(u == target for u in targets(state, True)):
        result['message'] = '目标已消失、关系改变或我方身份未确认'; return result
    base = candidate_cache(json.dumps(candidate_state(state), sort_keys=True), include_field)
    result['message'] = base['message']
    attack = result['enemy_attack'] = enemy_attack(target)
    rows = base['rows']
    for kind in ('infantry', 'cavalry', 'bow'):
        candidates = [r for r in rows if r['kind'] == kind]
        if not candidates:
            continue
        winners = [r for r in candidates if attack and min(r['attack']) > max(attack)]
        best = max(candidates, key=lambda r: (min(r['attack']), max(r['attack']), -len(r['ids'])))
        chosen = [('最强参考', best)]
        if winners:
            chosen.insert(0, ('省将超越', min(winners, key=lambda r: (len(r['ids']), r['soldiers'], -min(r['attack'])))))
        seen = set()
        for label, row in chosen:
            if row['ids'] in seen:
                continue
            seen.add(row['ids'])
            result['physical'].append(dict(row, label=label, comparison=compare(row, attack),
                morale=100, enemy_morale=100))
    generals = state.get('entities', {}).get('generals', [])
    known = {g['general_id_raw']: skills_for(g) for g in generals if 'general_id_raw' in g}
    enemy_skills = set()
    for gid in target.get('general_ids', []):
        matches = [g for g in generals if g.get('general_id_raw') == gid
                   and g.get('owner_raw') == target.get('owner_raw') and g.get('status_code') == 2]
        if len(matches) == 1:
            enemy_skills.update(skills_for(matches[0]))
    for spell, counter in SPELL_COUNTERS.items():
        options = []
        for row in rows:
            if row['kind'] != 'infantry' or spell not in row['skills']:
                continue
            casters = [g for g in row['generals'] if spell in known.get(g['general_id_raw'],set())
                       and valid(g.get('attributes', {}).get('intel'), 0, 255)]
            if not casters:
                continue
            caster = max(casters, key=lambda g: g['attributes']['intel'])
            options.append((row, caster))
        if not options:
            continue
        row, caster = max(options, key=lambda p: (p[1]['attributes']['intel'],
            '计谋' in p[0]['skills'], min(p[0]['attack']), -len(p[0]['ids'])))
        result['spells'].append(dict(row, spell=spell, caster=caster['name'],
            intelligence=caster['attributes']['intel'],
            counter=f'资料有{counter}：需过防计判定' if counter in enemy_skills else f'未确认{counter}，不代表没有',
            morale=100, enemy_morale=100))
    return result
