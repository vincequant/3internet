"""Pure reconstruction of the verified SANPK 3.5 construction mask.

Source: docs/construction-native-rule-0.2.33.md and its SHA-bound assembly.
This file is shared by the Hub and the read-only Wine helper. No Tk, process,
input, injection, file-writing or network API is used here.

Population/production-cap dialogs are warnings that users can override in the
original game, so they are not hard mask predicates. Native same-kind facility
upgrades are reported separately and remain disabled in the current sender.
"""
import struct

NATIVE_SCHEMA = 'sanpk-native-construction-mask-1'
UNKNOWN_S16 = -32768
CITY_RADIUS = 3
BUILD_TYPES = (6, 7, 8, 9)
BUILD_LABELS = {'陷阱': 6, '兵營': 7, '馬房': 8, '弓房': 9,
                '練兵所': 7, '练兵所': 7, '牧場': 8, '牧场': 8,
                '弓工坊': 9, '建設': 7}


def native_distance(x, y, cx, cy):
    """0x46a0f7, verified against 568 original leaf emulations."""
    return max(abs((2*x+y % 2)-(2*cx+cy % 2)), abs(y-cy))


def native_neighbors(x, y):
    """Four edges from 0x46a3d6 and table 0x506728."""
    if y % 2:
        return ((x+1, y-1), (x, y-1), (x, y+1), (x+1, y+1))
    return ((x, y-1), (x-1, y-1), (x-1, y+1), (x, y+1))


def native_footprint(cx, cy, width, height, radius=CITY_RADIUS):
    """0x46a2a5 set: x-major order, clipped to the active grid."""
    for x in range(max(0, cx-radius), min(width, cx+radius+1)):
        for y in range(max(0, cy-radius), min(height, cy+radius+1)):
            if native_distance(x, y, cx, cy) <= radius:
                yield x, y


def _integer(value, lower=0):
    return type(value) is int and value >= lower


def _xy(row):
    value = row.get('world_xy_raw')
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(type(v) is int for v in value):
        raise ValueError('原始物件座標未知')
    return tuple(value)


def _cells(rows):
    values = rows.keys() if isinstance(rows, dict) else rows or ()
    result = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get('xy')
        if isinstance(value, (tuple, list)) and len(value) == 2 and all(type(v) is int and v >= 0 for v in value):
            result.add(tuple(value))
    return result


def _raw(row, offset, fmt):
    try:
        raw = bytes.fromhex(row.get('raw_hex') or '')
        size = struct.calcsize(fmt)
        return struct.unpack_from(fmt, raw, offset)[0] if len(raw) >= offset+size else None
    except (ValueError, TypeError, struct.error):
        return None


def _relations(lord):
    relations = lord.get('diplomacy_relations')
    if isinstance(relations, list) and len(relations) >= 22:
        return relations
    try:
        raw = bytes.fromhex(lord.get('raw_hex') or '')
        return list(raw[0x32:0x48]) if len(raw) >= 0x48 else None
    except (ValueError, TypeError):
        return None


def _decode_grid(state, build_type):
    grid = state.get('terrain_grid') or {}
    width, height = grid.get('width'), grid.get('height')
    if not _integer(width, 1) or not _integer(height, 1):
        raise ValueError('原始地形網格未知')
    if grid.get('layout') != 'column-major':
        raise ValueError('原始地形／物件表排列未核實')
    count = width*height
    terrain = bytes.fromhex(grid.get('types') or '')
    kind_bytes = bytes.fromhex(grid.get('object_kinds_s16le') or '')
    if len(terrain) != count or len(kind_bytes) != count*2:
        raise ValueError('原始地形／動態物件表不完整')
    kinds = struct.unpack('<%dh' % count, kind_bytes)
    controls = None
    if build_type == 6:
        control_bytes = bytes.fromhex(grid.get('control_forces_s16le') or '')
        if len(control_bytes) != count*2:
            raise ValueError('原始格位控制勢力表不完整')
        controls = struct.unpack('<%dh' % count, control_bytes)
    return terrain, kinds, controls, width, height


def _trap_near_war_unit(cell, control, units, lords, width, height):
    """0x46998d(tile.control,1); None means the needed relation is unknown."""
    if control == -1:
        return False
    if control == UNKNOWN_S16 or control < 0:
        return None
    for neighbor in native_neighbors(*cell):
        if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
            continue
        # Native 0x450102 returns the first matching unit in the core list.
        matches = units.get(neighbor) or []
        if not matches:
            continue
        owner = matches[0].get('owner_raw')
        if owner == control:
            continue
        lord = lords.get(owner)
        relation = _relations(lord) if lord is not None else None
        if relation is None or not 0 <= control < len(relation) or relation[control] not in (0, 1, 2, 3):
            return None
        if relation[control] == 1:
            return True
    return False


def construction_candidates(state, actor, cities=(), busy=(), build_type=7):
    """Verified new-construction candidates keyed by cell; no target is chosen.

    Raw core city order is preserved. The input ``cities`` may supply display
    metadata, never ownership or geometry. Missing native fields stay unknown.
    """
    try:
        if type(actor) is not int or actor < 0 or type(build_type) is not int or build_type not in BUILD_TYPES:
            raise ValueError('建設勢力或類型未知')
        terrain, kinds, controls, width, height = _decode_grid(state, build_type)
        entities = state.get('entities') or {}
        for name in ('lords', 'cities_and_barriers', 'production_buildings', 'traps', 'field_units'):
            if not isinstance(entities.get(name), list) or any(not isinstance(r, dict) for r in entities[name]):
                raise ValueError('原始物件容器未知：'+name)
        actor_lords = [r for r in entities['lords'] if r.get('force_id') == actor]
        if len(actor_lords) != 1 or not _integer(actor_lords[0].get('gold')):
            raise ValueError('目標勢力金幣未知')
        gold = actor_lords[0]['gold']
        lords = {r.get('force_id'): r for r in entities['lords']}
        supplied = {r.get('city_id'): r for r in cities or () if isinstance(r, dict)}
        occupied, units, buildings = set(), {}, {}
        for container in ('cities_and_barriers', 'production_buildings', 'traps', 'field_units'):
            for row in entities[container]:
                xy = _xy(row)
                if 0 <= xy[0] < width and 0 <= xy[1] < height:
                    occupied.add(xy)
                    if container == 'field_units':
                        units.setdefault(xy, []).append(row)
                    if container == 'production_buildings':
                        buildings.setdefault(xy, []).append(row)
        blocked = _cells(busy)
        result = {'ok': True, 'schema': NATIVE_SCHEMA, 'cells': {}, 'occupied': occupied | blocked,
                  'width': width, 'height': height, 'excluded_upgrades': [],
                  'unknown_cells': 0, 'unknown_cities': 0,
                  'city_order_basis': 'captured_core_city_container',
                  'upgrade_disabled_reason': '原版允許同類設施增建；目前送出器未驗證增建，暫不可選'}
        if build_type == 6:
            result['global_trap_quota'] = {
                'status': 'unknown_local_ui_pending',
                'observed_owned_traps': sum(r.get('owner_raw') == actor for r in entities['traps']),
                'observed_owned_cities_and_barriers': sum(r.get('owner_raw') == actor for r in entities['cities_and_barriers']),
                'local_ui_pending': None,
                'limitation': 'doc+0x611+0x1f4 未捕獲；不可用各城 pending 總和代替。位置高亮不代表原版全域待發額度已核定。'}
            result['native_ui_full_equivalence'] = False
        if gold < 2000:
            result['reason'] = '金幣不足 2000，沒有可新增建設的格位'
            return result
        owned_rows = [r for r in entities['cities_and_barriers'] if r.get('owner_raw') == actor]
        own_cities = [r for r in owned_rows if r.get('type') == 'city']
        if any(not _integer(r.get('city_id')) for r in own_cities):
            raise ValueError('城池識別未知')
        for row in own_cities:
            flags = _raw(row, 0x22, '<H')
            if flags is None:
                result['unknown_cities'] += 1
                continue
            if flags & 0x1000:
                continue
            if build_type == 6:
                # Filled from the exact city count getter; do not substitute
                # observed-nearby-trap guesses for its native count semantics.
                trap_count = native_trap_count(row, state)
                if trap_count is None:
                    result['unknown_cities'] += 1
                    continue
                if trap_count >= 5:
                    continue
            cx, cy = _xy(row)
            city = dict(supplied.get(row['city_id']) or {}, **row)
            city.update(owner=actor, xy=[cx, cy])
            for cell in native_footprint(cx, cy, width, height):
                x, y = cell
                index = x*height+y
                code, kind = terrain[index], kinds[index]
                legacy_unknown = (code == 15 and
                    (state.get('terrain_grid') or {}).get('encoding') != 'sanpk-terrain-u8-v2')
                if kind == UNKNOWN_S16 or code == 255 or legacy_unknown:
                    result['unknown_cells'] += 1
                    continue
                if cell in blocked or cell in units:
                    continue
                if kind != -1 or cell in occupied:
                    # Same-kind native upgrades are a separate operation and
                    # are intentionally excluded until the sender is verified.
                    if kind == build_type and build_type in (7, 8, 9):
                        for b in buildings.get(cell) or ():
                            amount = b.get('building_ui_amount')
                            if _integer(amount) and amount < 15000:
                                result['excluded_upgrades'].append({'xy': list(cell), 'city_id': row['city_id'], 'reason': result['upgrade_disabled_reason']})
                    continue
                if build_type == 6:
                    if code not in (0, 1, 2) and not 7 <= code <= 19:
                        continue
                    near_war = _trap_near_war_unit(cell, controls[index], units, lords, width, height)
                    if near_war is None:
                        result['unknown_cells'] += 1
                        continue
                    if near_war:
                        continue
                else:
                    if code not in (0, 1, 2):
                        continue
                    neighbor_kinds = [kinds[nx*height+ny] for nx, ny in native_neighbors(x, y)
                                      if 0 <= nx < width and 0 <= ny < height]
                    if UNKNOWN_S16 in neighbor_kinds:
                        result['unknown_cells'] += 1
                        continue
                    if any(value in (0, 1, 2) for value in neighbor_kinds):
                        continue
                result['cells'].setdefault(cell, city)
        if own_cities and result['unknown_cities'] == len(own_cities):
            raise ValueError('城池原生建設旗標或計數未知')
        # 0x4441e1 builds doc+0x611's city projection by filtering the core
        # container in order (0x4443a9..0x4443e4), without sorting. Click
        # handlers then pick its first in-range row, independently of the
        # city that originally contributed the point to the selectable mask.
        for cell in result['cells']:
            for row in owned_rows:
                if row.get('type') not in ('city', 'barrier'):
                    continue
                radius = CITY_RADIUS if row['type'] == 'city' else 1
                if native_distance(*cell, *_xy(row)) <= radius:
                    city = dict(supplied.get(row.get('city_id')) or {}, **row)
                    city.update(owner=actor, xy=list(_xy(row)))
                    result['cells'][cell] = city
                    break
        result['complete'] = result['unknown_cells'] == 0 and result['unknown_cities'] == 0
        return result
    except (KeyError, TypeError, ValueError, AttributeError, struct.error) as exc:
        return {'ok': False, 'schema': NATIVE_SCHEMA, 'cells': {}, 'occupied': set(), 'error': str(exc)}


def native_trap_count(city, state):
    """0x4349e0: linked traps (0x434240) plus pending DWORD city+0x3b."""
    pending = _raw(city, 0x3b, '<i')
    traps = (state.get('entities') or {}).get('traps')
    if pending is None or pending < 0 or not isinstance(traps, list):
        return None
    count = 0
    for row in traps:
        linked = row.get('raw_16')
        if not _integer(linked) or linked > 65535:
            linked = _raw(row, 0x16, '<H')
        if linked is None:
            return None
        count += linked == city.get('city_id')
    return count+pending
