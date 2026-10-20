"""Slim live Hub document for the iPad page. No raw memory, no terrain grid."""
import sys
from pathlib import Path

TIER_NAMES = {
    'infantry': ('步兵', '强化步兵', '重装步兵'),
    'cavalry': ('骑兵', '强化骑兵', '铁骑兵'),
    'bow': ('弓兵', '弩兵', '连弩'),
}
KEEP_STATUS = {0, 1, 2, 4, 6}
CONFIRMED = {'verified', 'confirmed', 'user_confirmed'}
KIND_LABEL = {'重装骑兵': '铁骑兵'}


def kind_label(name):
    if not isinstance(name, str):
        return name or '部队'
    return KIND_LABEL.get(name, name)


def _tier(kind, raw):
    if not isinstance(raw, int) or not 0 <= raw <= 300:
        return None
    step = 0 if raw < 100 else 1 if raw < 200 else 2
    progress = 100 if raw >= 300 else raw % 100
    return {'name': TIER_NAMES[kind][step], 'progress': progress, 'raw': raw}


def _line(op):
    text = str((op or {}).get('line') or '')
    if '重装骑兵' in text:
        text = text.replace('重装骑兵', '铁骑兵')
    return text


def _force_ops(block, limit=40):
    rows = []
    for force in (block or {}).get('forces') or []:
        ops = []
        for op in (force.get('operations') or [])[:limit]:
            line = _line(op)
            field = op.get('field') or ''
            if not line and not field:
                continue
            ops.append({'field': field, 'line': line})
        if ops:
            rows.append({'owner': force.get('owner'), 'operations': ops})
    return rows


def _cards(lord):
    slots = ((lord or {}).get('hand_cards') or {}).get('slots') or []
    rows = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        cid = slot.get('card_id')
        if cid is None:
            continue
        rows.append({
            'id': cid,
            'name': slot.get('name') or slot.get('card_name') or '',
        })
    return rows


def _boost(value):
    return int(value * 1.4 + 0.5)


def _peaks(officers, cards):
    ids = {row.get('id') for row in cards or []}
    rows = []
    for officer in officers:
        lead, war, pol = officer.get('lead'), officer.get('war'), officer.get('pol')
        combat = isinstance(lead, int) and isinstance(war, int)
        rows.append({
            'name': officer.get('name') or '?',
            'lead': lead if combat else None,
            'war': war if combat else None,
            'pol': pol if isinstance(pol, int) else None,
            'lead_boost': False,
            'war_boost': False,
            'pol_boost': False,
        })

    def lift(key, flag, present):
        if not present:
            return
        known = [row for row in rows if row[key] is not None]
        if not known:
            return
        top = max(row[key] for row in known)
        for row in known:
            if row[key] == top:
                row[key] = _boost(row[key])
                row[flag] = True

    lift('lead', 'lead_boost', 18 in ids)
    lift('war', 'war_boost', 19 in ids)
    lift('pol', 'pol_boost', 20 in ids)
    blade = None
    politics = None
    for row in rows:
        if row['lead'] is not None:
            total = row['lead'] + row['war']
            boosted = row['lead_boost'] or row['war_boost']
            if blade is None or (total, boosted) > (blade['value'], blade['boosted']):
                blade = {'value': total, 'name': row['name'], 'boosted': boosted}
        if row['pol'] is not None and (politics is None or (row['pol'], row['pol_boost']) > (politics['value'], politics['boosted'])):
            politics = {'value': row['pol'], 'name': row['name'], 'boosted': row['pol_boost']}
    return blade, politics


def _summer(cities, force_id):
    out = {}
    for kind in ('infantry', 'cavalry', 'bow'):
        known = 0
        missing = 0
        for city in cities:
            if city.get('type') != 'city' or city.get('owner_raw') != force_id:
                continue
            value = ((city.get('recruitment_capacity') or {}).get('amounts') or {}).get(kind)
            if isinstance(value, int) and value >= 0:
                known += value
            else:
                missing += 1
        out[kind] = {'known': known, 'missing': missing}
    return out


def _efficiency(stock):
    if not isinstance(stock, int) or stock < 0:
        return None
    percent = max(50, 100 - (stock * 5 + 50000) // 100000 * 10)
    return percent


def _after_summer(kind, raw, stock, added):
    if not isinstance(raw, int) or not 0 <= raw <= 300:
        return None
    if not isinstance(stock, int) or stock < 0 or not isinstance(added, int) or added < 0:
        return None
    incoming = raw * 3 // 5
    if added == 0:
        new_raw, new_stock = raw, stock
    else:
        new_stock = stock + added
        new_raw = (raw * stock + incoming * added) // new_stock
    tier = _tier(kind, new_raw)
    if not tier:
        return None
    return '%s · %s %s/100' % (f'{new_stock:,}', tier['name'], tier['progress'])


def _near_trap(traps, xy, radius=3):
    if not xy:
        return False
    for trap in traps:
        point = (trap or {}).get('world_xy_raw') or []
        if len(point) < 2 or any(type(value) is not int for value in point[:2]):
            continue
        if max(abs(point[0] - xy[0]), abs(point[1] - xy[1])) <= radius:
            return True
    return False


def _player(state):
    ident = (state or {}).get('player_identity') or {}
    ctx = (state or {}).get('player_context') or {}
    status = ident.get('status') or ctx.get('status') or 'unknown'
    force_id = ident.get('force_id')
    if force_id is None:
        force_id = ctx.get('force_id')
    confirmed = status in CONFIRMED and force_id is not None
    return {
        'status': status,
        'force_id': force_id if confirmed else None,
        'confirmed': confirmed,
    }


def hub_live_document(payload):
    """Build the document posted to /api/sgi-war/live from a collector /api/state body."""
    payload = payload or {}
    state = payload.get('state') if isinstance(payload.get('state'), dict) else payload
    if not isinstance(state, dict) or not state.get('snapshot_id'):
        return None
    ents = state.get('entities') or {}
    history = state.get('history') or {}
    names = {}
    officers = []
    for row in ents.get('generals') or []:
        gid = row.get('general_id_raw')
        if gid is not None and row.get('name'):
            names[gid] = row.get('name')
        if row.get('status_code') not in KEEP_STATUS:
            continue
        attrs = row.get('attributes') or {}
        officers.append({
            'id': gid,
            'name': row.get('name'),
            'owner': row.get('owner_raw'),
            'status': row.get('status_label'),
            'status_code': row.get('status_code'),
            'city': row.get('location_city_name'),
            'city_id': row.get('location_city_id'),
            'soldiers': row.get('soldiers'),
            'lead': attrs.get('lead'),
            'war': attrs.get('war'),
            'intel': attrs.get('intel'),
            'pol': attrs.get('pol'),
            'cha': attrs.get('cha'),
        })
    forces = []
    for lord in ents.get('lords') or []:
        arm = lord.get('armament_raw') or {}
        forces.append({
            'force_id': lord.get('force_id'),
            'name': lord.get('name'),
            'color': lord.get('color_index_raw'),
            'gold': lord.get('gold'),
            'rice': lord.get('rice'),
            'prestige': lord.get('prestige'),
            'stock': lord.get('troop_stock') or {},
            'training': {
                'infantry': _tier('infantry', arm.get('infantry')),
                'cavalry': _tier('cavalry', arm.get('cavalry')),
                'bow': _tier('bow', arm.get('bow')),
            },
            'cards': _cards(lord),
            'relations': list(lord.get('diplomacy_relations') or []),
            'ruler_id': lord.get('ruler_general_id'),
            'capital_id': lord.get('capital_city_id'),
            'summer': _summer(ents.get('cities_and_barriers') or [], lord.get('force_id')),
            'after': {
                kind: _after_summer(kind, arm.get(kind), (lord.get('troop_stock') or {}).get(kind),
                                    _summer(ents.get('cities_and_barriers') or [], lord.get('force_id'))[kind]['known'])
                for kind in ('infantry', 'cavalry', 'bow')
            },
            'efficiency': {
                kind: _efficiency((lord.get('troop_stock') or {}).get(kind))
                for kind in ('infantry', 'cavalry', 'bow')
            },
        })
    capitals = {lord.get('capital_city_id') for lord in ents.get('lords') or []}
    traps = ents.get('traps') or []
    cities = []
    scenario = state.get('scenario_map') if isinstance(state.get('scenario_map'), dict) else {}
    max_x, max_y = 101, 202
    if scenario.get('known'):
        try:
            max_x, max_y = int(scenario['width']), int(scenario['height'])
        except (TypeError, ValueError, KeyError):
            max_x, max_y = 101, 202
    for city in ents.get('cities_and_barriers') or []:
        xy = city.get('world_xy_raw') or []
        point = [xy[0], xy[1]] if len(xy) >= 2 else None
        if point:
            max_x = max(max_x, point[0])
            max_y = max(max_y, point[1])
        cities.append({
            'id': city.get('city_id'),
            'name': city.get('name'),
            'type': city.get('type'),
            'owner': city.get('owner_raw'),
            'population': city.get('population'),
            'morale': city.get('morale'),
            'recruit': city.get('recruitment_capacity'),
            'xy': point,
            'art': 1 if city.get('city_art_variant_flag') else 0,
            'capital': city.get('city_id') in capitals,
            'traps': city.get('type') != 'barrier' and _near_trap(traps, point),
        })
    units = []
    for unit in ents.get('field_units') or []:
        xy = unit.get('world_xy_raw') or []
        point = [xy[0], xy[1]] if len(xy) >= 2 else None
        if point:
            max_x = max(max_x, point[0])
            max_y = max(max_y, point[1])
        people = []
        for gid in unit.get('general_ids') or []:
            if names.get(gid):
                people.append(names[gid])
        units.append({
            'id': unit.get('unit_id'),
            'kind': kind_label(unit.get('unit_kind')),
            'owner': unit.get('owner_raw'),
            'xy': point,
            'soldiers': unit.get('soldiers_candidate'),
            'morale': unit.get('morale'),
            'generals': people,
            'water': unit.get('on_water') is True,
            'attack': unit.get('target_attack_unit'),
            'attack_model': unit.get('attack_model'),
            'move_remaining': unit.get('move_remaining_raw'),
        })
    quarters = []
    for block in (history.get('quarters') or [])[-8:]:
        quarters.append({
            'label': block.get('label'),
            'phase': block.get('phase'),
            'closed': True,
            'forces': _force_ops(block),
        })
    current = history.get('current_quarter')
    if isinstance(current, dict):
        quarters.append({
            'label': current.get('label'),
            'phase': current.get('phase'),
            'closed': False,
            'current': True,
            'forces': _force_ops(current),
        })
    city_names = {row['id']: row.get('name') for row in cities}
    for force in forces:
        fid = force.get('force_id')
        own_units = [row for row in units if row.get('owner') == fid]
        attacks = [row.get('attack') for row in own_units if isinstance(row.get('attack'), int)]
        own_officers = [row for row in officers if row.get('owner') == fid]
        blade, politics = _peaks(own_officers, force.get('cards'))
        force.update(
            ruler=names.get(force.get('ruler_id')),
            capital=city_names.get(force.get('capital_id')),
            city_count=sum(1 for row in cities if row.get('owner') == fid and row.get('type') == 'city'),
            officer_count=sum(1 for row in officers if row.get('owner') == fid),
            unit_count=len(own_units),
            attack_sum=sum(attacks) if attacks else None,
            best_blade=None if blade is None else {
                'name': blade['name'],
                'value': blade['value'],
                'boosted': blade['boosted'],
            },
            best_politics=None if politics is None else {
                'name': politics['name'],
                'value': politics['value'],
                'boosted': politics['boosted'],
            },
        )
    doc = {
        'snapshot_id': state.get('snapshot_id'),
        'capture_end': state.get('capture_end'),
        'fresh': payload.get('fresh'),
        'phase': payload.get('phase'),
        'snapshot_age_s': payload.get('snapshot_age_s'),
        'release_version': payload.get('release_version'),
        'source_id': payload.get('source_id'),
        'phase_label': history.get('phase_label') or (current or {}).get('label'),
        'player': _player(state),
        'forces': forces,
        'quarters': quarters,
        'cities': cities,
        'units': units,
        'officers': officers,
        'bounds': {'max_x': max_x, 'max_y': max_y},
        'scenario_map': {
            'id': scenario.get('id'),
            'name': scenario.get('name'),
            'width': scenario.get('width'),
            'height': scenario.get('height'),
        } if scenario.get('id') else None,
    }
    _attach_library(doc, state)
    return doc


def _repo_paths():
    root = Path('/Users/vk/Documents/Coding/三国志internet/research/client/SGI-Hub-CrossOver-M4-0.2')
    for folder in (root / 'bridge', root / 'app'):
        text = str(folder)
        if folder.is_dir() and text not in sys.path:
            sys.path.insert(0, text)


def _attach_library(doc, state):
    """Force comparison and officer skills, using the same Hub functions."""
    try:
        _repo_paths()
        from city_talent import summarize as city_talent
        from force_compare import exceed_player, summarize
        from officer_sortie import (
            recruit_share_label, roster_skill_flags, unique_place_ids, wild_city_counts,
        )
    except Exception:
        return
    generals = ((state or {}).get('entities') or {}).get('generals') or []
    by_id = {row.get('general_id_raw'): row for row in generals}
    places = ((state or {}).get('entities') or {}).get('cities_and_barriers') or []
    counts = wild_city_counts(generals)
    unique = unique_place_ids(places)
    for officer in doc.get('officers') or []:
        source = by_id.get(officer.get('id')) or {}
        flags = roster_skill_flags(source)
        officer['skills'] = [key for key, on in flags.items() if on]
        officer['wild_n'] = counts.get(officer.get('city_id')) if officer.get('status_code') == 1 else None
        officer['hire'] = recruit_share_label(source, counts, unique)
    rows = []
    for row in summarize(state):
        rows.append({
            'force_id': row.get('force_id'),
            'name': row.get('name'),
            'tag': row.get('tag'),
            'pol': None if row.get('best_pol') is None else '%s %s' % (row['best_pol'], row.get('trainer') or ''),
            'blade': None if row.get('best_blade') is None else '%s %s' % (row['best_blade'], row.get('blade_name') or ''),
            'cav': None if row.get('cav_power') is None else '%s %s' % (row['cav_power'], row.get('cav_power_name') or ''),
            'inf_train': row.get('inf_train'),
            'cav_train': row.get('cav_train'),
            'bow_train': row.get('bow_train'),
            'inf_n': row.get('inf_soldiers'),
            'cav_n': row.get('cav_soldiers'),
            'bow_n': row.get('bow_soldiers'),
            'units': row.get('unit_count'),
            'note': exceed_player(state, row.get('force_id')),
        })
    doc['compare'] = rows
    talent_rows, talent_meta = city_talent(state)
    doc['city_talent'] = {
        'total': talent_meta.get('total'),
        'hidden': talent_meta.get('hidden_barriers'),
        'unlocated': talent_meta.get('unlocated'),
        'rows': [{
            'name': row.get('name'),
            'owner': row.get('owner'),
            'owner_id': (row.get('city') or {}).get('owner_raw'),
            'total': row.get('total'),
            'ride': row.get('ride'),
            'bow': row.get('bow'),
            'navy': row.get('navy'),
            'ambush': row.get('ambush'),
            'blade': row.get('blade'),
            'blade_avg': row.get('blade_avg'),
            'pol': row.get('pol'),
            'blades': row.get('blades'),
        } for row in talent_rows],
    }
