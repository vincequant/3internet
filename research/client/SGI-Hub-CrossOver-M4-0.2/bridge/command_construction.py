"""Source-bound construction city references; no nearest-city or result guess.

Domestic subtype 4 stores the linked city ID in value_raw: SANPK df9b5225
0x4a7d42..47 (facilities), 0x4a820e..12 (fire/rock/trap placement).
"""
from copy import deepcopy

from command_display import _stamp
from native_command_evidence import CONSTRUCTION_ACTIONS
from network_payloads import SANPK_BUILD
from scout_location import MAPS, binding_digest, point


def construction(row):
    return (row.get('native_type') == 18 and row.get('subtype') == 4
            and row.get('parameter_raw') in CONSTRUCTION_ACTIONS)


def valid_construction(row, ref, binding):
    try:
        world = MAPS[ref['map_id']]
        city = ref['city']
        start, end = _stamp(row['observed_at']), _stamp(ref['captured_at'])
        return (construction(row) and ref['schema'] == 'construction-city-reference-1'
                and binding.get('build') == SANPK_BUILD
                and ref['basis'] == 'source_state_reference'
                and ref['binding_sha256'] == binding_digest(binding)
                and ref['actor_force_id'] == row['actor_force_id']
                and ref['target_xy'] == row['target_xy_raw'] and point(ref['target_xy'],world)
                and type(city['city_id']) is int and 0 <= city['city_id'] < 65536
                and city['city_id'] == row['value_raw']
                and city['type'] in ('city','barrier') and point(city['world_xy_raw'],world)
                and type(city['owner_raw']) is int and 0 <= city['owner_raw'] <= 65535
                and type(city['name']) is str and 0 < len(city['name']) <= 64
                and type(ref['snapshot_id']) is str and 0 < len(ref['snapshot_id']) <= 128
                and start is not None and end is not None and start <= end)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def retain_construction(commands, state):
    out = deepcopy(commands)
    bound, state = out.get('binding') or {}, state or {}
    identity, spec = state.get('identity') or {}, state.get('scenario_map') or {}
    world = MAPS.get(spec.get('id'))
    if (identity.get('pid') != bound.get('pid')
            or identity.get('creation_filetime') != bound.get('created')
            or identity.get('path') != bound.get('image')
            or state.get('build_sha256') != bound.get('build')
            or spec.get('known') is not True or world != (spec.get('width'),spec.get('height'))):
        return out
    cities = (state.get('entities') or {}).get('cities_and_barriers') or []
    for row in out.get('rows') or []:
        if not construction(row) or valid_construction(row,row.get('construction_reference'),bound):
            continue
        matches = [c for c in cities if c.get('city_id') == row.get('value_raw')]
        if len(matches) != 1:
            continue
        ref = dict(schema='construction-city-reference-1', basis='source_state_reference',
                   binding_sha256=binding_digest(bound), actor_force_id=row['actor_force_id'],
                   target_xy=deepcopy(row.get('target_xy_raw')), map_id=spec['id'],
                   snapshot_id=state.get('snapshot_id'), captured_at=state.get('capture_end'),
                   city={k:deepcopy(matches[0].get(k)) for k in ('city_id','name','type','owner_raw','world_xy_raw')})
        if valid_construction(row,ref,bound):
            row['construction_reference'] = ref
    return out


def construction_text(row):
    city = (row.get('construction_reference') or {}).get('city') or {}
    cid = row.get('value_raw')
    name = city.get('name') or (f'城池#{cid}' if type(cid) is int and cid >= 0 else '城池未确认')
    return f'{row["action"]} {name}'
