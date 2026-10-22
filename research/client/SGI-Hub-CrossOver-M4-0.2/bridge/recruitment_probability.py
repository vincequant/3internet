"""Native recruitment thresholds and a separately labelled random-order model.

Evidence: quick-recruit-rules-20261005. No website affinity fallback, writes,
or inferred commands. RNG uniformity/independence is an assumption, not evidence.
"""
import math
from collections import Counter
from functools import lru_cache

BUILD = '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2'
SUPPORTED_BUILDS = (BUILD, 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea')
INPUT_VERSION = 'native_recruit_4687df_4688cf_v1'


def threshold(prestige, target, ruler):
    if not all(type(x) is int for x in (prestige, target, ruler)):
        return None
    if not (0 <= prestige <= 200 and 0 <= target <= 255 and 0 <= ruler <= 255):
        return None
    distance = min(abs(target-ruler), abs(target+ruler-150))
    # Windows MulDiv rounds positive results to nearest, including halves up.
    return (prestige * max(15, 150-distance) + 150) // 300


@lru_cache(maxsize=32)
def _quadrature(n):
    """Gauss-Legendre on [0,1], positive weights; exact for degree < 2*n.

    Avoid alternating polynomial coefficients, which lose precision for large
    pools. No dependency on numpy, so the same model runs on Mac and Windows.
    """
    nodes = []
    for i in range(1, (n+1)//2+1):
        z = math.cos(math.pi*(i-.25)/(n+.5))
        for _ in range(40):
            p0, p1 = 1., z
            for k in range(2, n+1):
                p0, p1 = p1, ((2*k-1)*z*p1-(k-1)*p0)/k
            derivative = n*(z*p1-p0)/(z*z-1)
            step = p1/derivative
            z -= step
            if abs(step) < 2e-15:
                break
        else:
            raise ArithmeticError('quadrature failed to converge')
        weight = 1/((1-z*z)*derivative*derivative)
        nodes.append(((1-z)/2, weight))
        if len(nodes) < n and abs(z) > 1e-14:
            nodes.append(((1+z)/2, weight))
    return tuple(nodes)


def random_order_chances(probabilities):
    """P(i first success) = p_i integral product(j != i)(1-t*p_j) dt.

    All candidates must be provided, including those with p=0. Assumes uniform
    shuffle and independent, uniform success draws; does not cover rival orders.
    """
    ps = list(probabilities)
    if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in ps):
        raise ValueError('probabilities must be finite and in 0..1')
    if not ps:
        return [], 1.
    result = [0.] * len(ps)
    for t, weight in _quadrature((len(ps)+1)//2):
        prefix = [1.]
        for p in ps:
            prefix.append(prefix[-1]*(1-t*p))
        suffix = 1.
        for i in range(len(ps)-1, -1, -1):
            result[i] += weight*ps[i]*prefix[i]*suffix
            suffix *= 1-t*ps[i]
    return result, math.prod(1-p for p in ps)


def city_probabilities(state, city_id, force_id):
    """Use one snapshot's typed pool, prestige and ruler; unknown stays unknown."""
    entities = state.get('entities') or {}
    generals = entities.get('generals') or []
    pool = [g for g in generals if g.get('status_code') == 1 and g.get('location_city_id') == city_id]
    rows = {g.get('general_id_raw'): {'threshold': None, 'chance': None, 'excluded': None} for g in pool}
    result = {'rows': rows, 'pool_count': len(pool), 'reason': '', 'prestige': None,
              'force_name': None, 'none_chance': None, 'model': 'uniform_shuffle_independent_uniform_draws'}
    def unknown(reason):
        result['reason'] = reason
        return result
    if state.get('build_sha256') not in SUPPORTED_BUILDS:
        return unknown('该版本的招揽规则尚未核准')
    if state.get('consistency', {}).get('root_headers_and_clock_unchanged') is not True:
        return unknown('当前采集不一致')
    places = [c for c in entities.get('cities_and_barriers', []) if c.get('city_id') == city_id]
    if type(city_id) is not int or len(places) != 1 or places[0].get('type') != 'city':
        return unknown('城池身份未确认')
    coverage = state.get('coverage', {}).get('generals', {})
    if coverage.get('structurally_valid') is not True or coverage.get('count') != len(generals):
        return unknown('武将容器覆盖未确认')
    gids = [g.get('general_id_raw') for g in generals]
    identities = Counter(gids)
    if any(type(g.get('general_id_raw')) is not int or identities[g['general_id_raw']] != 1 for g in pool):
        return unknown('武将身份缺失或重复')
    if any(type(g.get('status_code')) is not int or
           (g.get('status_code') == 1 and type(g.get('location_city_id')) is not int) for g in generals):
        return unknown('在野候选所在地未完整确认')
    lords = [f for f in entities.get('lords', []) if type(force_id) is int and f.get('force_id') == force_id]
    if len(lords) != 1:
        return unknown('我方势力未确认')
    lord = lords[0]
    rulers = [g for g in generals if g.get('general_id_raw') == lord.get('ruler_general_id')]
    ruler = rulers[0] if len(rulers) == 1 else None
    prestige = lord.get('prestige')
    result.update(prestige=prestige, force_name=lord.get('name'))
    if ruler is None or ruler.get('recruitment_input_verification') != INPUT_VERSION:
        return unknown('君主招揽关系值未采集；请更新采集桥')
    b = ruler.get('relation_byte_2e')
    if threshold(prestige, b, b) is None:
        return unknown('民望或君主招揽关系值无效')
    complete = True
    for g in pool:
        row = rows[g['general_id_raw']]
        exclusion = g.get('excluded_ruler_word_42')
        if g.get('recruitment_input_verification') != INPUT_VERSION or type(exclusion) is not int or not 0 <= exclusion <= 65535:
            complete = False
            continue
        row['excluded'] = exclusion == lord.get('ruler_general_id')
        row['threshold'] = 0 if row['excluded'] else threshold(prestige, g.get('relation_byte_2e'), b)
        complete &= row['threshold'] is not None
    if not complete:
        return unknown('部分招揽输入未确认；整体估算暂缺')
    chances, none = random_order_chances([min(100, rows[g['general_id_raw']]['threshold'])/100 for g in pool])
    for g, chance in zip(pool, chances):
        rows[g['general_id_raw']]['chance'] = chance
    result['none_chance'] = none
    return result
