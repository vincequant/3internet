"""Display-only, source-bound scout map references. Never action/result labels."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from network_payloads import SANPK_BUILD

MAPS = {'china': (101, 202), 'southeast': (69, 106),
        'south': (101, 106), 'central': (55, 127)}
SCOUT_RADIUS = 4  # SANPK df9b5225: 450ad7 -> 466e5c -> 466e74 -> 46a2a5
NEAR_CITY_STEPS = 5  # Naming convenience, independent of scout coverage.


def binding_digest(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()


def point(value, world=(101, 202)):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) is int for n in value)
            and all(0 <= n < limit for n, limit in zip(value, world)))


def scout(row):
    return row.get('native_type') == 18 and row.get('subtype') == 8


def steps(a, b):
    # Original staggered rows -> square axes, four-neighbour distance.
    def axes(p):
        x, y = p
        return x + (y + 1) // 2, -x + y // 2
    return sum(abs(x-y) for x, y in zip(axes(a), axes(b)))


def scout_cells(center, world=(101, 202)):
    """Native four-neighbour radius, clipped to this scenario's own grid."""
    if not point(center,world):
        return []
    x, y = center
    r = SCOUT_RADIUS
    return [(a,b) for b in range(max(0,y-r),min(world[1],y+r+1))
            for a in range(max(0,x-r),min(world[0],x+r+1)) if steps(center,(a,b))<=r]


def valid_reference(row, ref, binding):
    try:
        world = MAPS[ref['map_id']]
        if (not scout(row) or ref['schema'] != 'scout-map-reference-1'
                or binding.get('build') != SANPK_BUILD
                or ref['binding_sha256'] != binding_digest(binding)
                or ref['target_xy'] != row['target_xy_raw']
                or not point(ref['target_xy'], world)
                or ref['basis'] != 'source_state_reference'
                or type(ref['snapshot_id']) is not str or len(ref['snapshot_id']) > 128
                or datetime.fromisoformat(ref['captured_at']).tzinfo is None
                or datetime.fromisoformat(ref['captured_at']) < datetime.fromisoformat(row['observed_at'])):
            return False
        cities, forces = ref['cities'], ref['forces']
        if not isinstance(cities, list) or len(cities) > 8 or not isinstance(forces, list) or len(forces) > 8:
            return False
        ids = set()
        for city in cities:
            if (type(city['city_id']) is not int or not 0 <= city['city_id'] < 65536
                    or city['city_id'] in ids or city['type'] != 'city'
                    or not point(city['world_xy_raw'], world)
                    or type(city['owner_raw']) is not int or not 0 <= city['owner_raw'] <= 65535
                    or type(city['name']) is not str or not 0 < len(city['name']) <= 64):
                return False
            ids.add(city['city_id'])
        ids = set()
        for force in forces:
            if (type(force['force_id']) is not int or not 0 <= force['force_id'] < 32
                    or force['force_id'] in ids or type(force['capital_city_id']) is not int
                    or type(force['name']) is not str or not 0 < len(force['name']) <= 64):
                return False
            ids.add(force['force_id'])
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def retain_locations(commands, state):
    """First available same-source snapshot is a reference, not issue-time state."""
    state = state or {}
    result = deepcopy(commands)
    bound = result.get('binding') or {}
    identity = (state or {}).get('identity') or {}
    if (identity.get('pid') != bound.get('pid')
            or identity.get('creation_filetime') != bound.get('created')
            or identity.get('path') != bound.get('image')
            or state.get('build_sha256') != bound.get('build')):
        return result
    spec = (state or {}).get('scenario_map') or {}
    world = MAPS.get(spec.get('id'))
    if not bound or spec.get('known') is not True or world != (spec.get('width'), spec.get('height')):
        return result
    entities = (state or {}).get('entities') or {}
    cities = entities.get('cities_and_barriers') or []
    for row in result.get('rows', []):
        if not scout(row) or valid_reference(row, row.get('scout_reference'), bound):
            continue
        xy = row.get('target_xy_raw')
        if not point(xy, world):
            continue
        candidates = [c for c in cities if c.get('type') == 'city' and point(c.get('world_xy_raw'), world)]
        # Ambiguous IDs/coordinates are excluded rather than arbitrarily named.
        candidates = [c for c in candidates if sum(d.get('city_id') == c.get('city_id') for d in candidates) == 1]
        candidates.sort(key=lambda c: (steps(xy, c['world_xy_raw']), c['city_id']))
        selected = [{k:c.get(k) for k in ('city_id','type','name','owner_raw','world_xy_raw')} for c in candidates[:8]]
        owners = {c['owner_raw'] for c in selected}
        forces = [{k:f.get(k) for k in ('force_id','name','capital_city_id')}
                  for f in entities.get('lords', []) if f.get('force_id') in owners]
        ref = dict(schema='scout-map-reference-1', binding_sha256=binding_digest(bound),
                   basis='source_state_reference', target_xy=list(xy), map_id=spec['id'],
                   snapshot_id=state.get('snapshot_id'), captured_at=state.get('capture_end'),
                   cities=selected, forces=forces)
        if valid_reference(row, ref, bound):
            row['scout_reference'] = ref
    return result


def location_text(row, binding):
    xy = row.get('target_xy_raw')
    ref = row.get('scout_reference')
    fallback = ','.join(map(str, xy)) if point(xy) else '坐标未确认'
    if not valid_reference(row, ref, binding):
        return fallback
    ranked = sorted((steps(xy,c['world_xy_raw']), c['city_id'], c) for c in ref['cities'])
    if not ranked or ranked[0][0] > NEAR_CITY_STEPS or (len(ranked)>1 and ranked[0][0] == ranked[1][0]):
        return fallback
    distance, _, city = ranked[0]
    owners = [f for f in ref['forces'] if f['force_id'] == city['owner_raw']]
    name = city['name']
    if len(owners) == 1:
        owner = owners[0]
        name = owner['name'] + ('都' if owner['capital_city_id'] == city['city_id'] else '·') + name
    return name + ('附近' if distance else '')
