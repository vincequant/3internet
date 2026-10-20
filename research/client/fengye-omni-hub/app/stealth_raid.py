"""Stealth raid path for the panorama. Cavalry website MP, avoid enemy vision.

Last turn may enter the target capital's vision; other enemy city/unit vision is
blocked. Grain wagons use the same hidden corridor and stop outside vision.
Not an engine pathfinder.
"""
from heapq import heappop, heappush

from force_relations import allied, at_war
from officer_sortie import ALL_SKILLS, resolved_officers
from panorama_model import (
    CAPITAL_VISION, WORLD, capital_marks, is_capital, tile_axes, vision_cells, vision_radius,
    world_xy,
)
from player_view import player_id
from preparation_model import skills_for
from unit_move import (
    MOVE_POINTS, TERRAIN_COST, enter_cost, move_class, move_overlay_cells, move_points,
    reachable_cells, tile_neighbors, unit_has_navy, unit_size_index,
)

UNIT_VISION = 2
SPY_VISION = 4
SPY_SKILLS = frozenset({'谍报'})
SIZE_NAME = ('小队', '中队', '大队')
SOURCE = (
    '攻略：普通部队视野2格、谍报4格；城都5/城3/关1。骑兵移动同行走格。'
    '末回合才进目标主城视野。埋伏按攻略可在丘陵丛林隐蔽，本路线仍按避开视野计算。'
    '不是引擎逐步验证。'
)
SOURCE_SHORT = '攻略视野2/谍报4，不是引擎逐步验证'


def unit_has_spy(state, unit):
    for officer in resolved_officers(state, (unit or {}).get('general_ids')):
        skills = skills_for(officer)
        if ALL_SKILLS in skills or skills & SPY_SKILLS:
            return True
    return False


def unit_vision_radius(state, unit):
    if type((unit or {}).get('vision_radius')) is int:
        return unit['vision_radius']
    return SPY_VISION if unit_has_spy(state, unit) else UNIT_VISION


def mover_spec(state=None, unit=None, klass='cavalry_horse', size=0, navy=False):
    if unit is not None:
        klass = move_class(state, unit)
        size = unit_size_index(unit)
        navy = unit_has_navy(state, unit)
        points = move_points(state, unit)
    else:
        if size not in (0, 1, 2) or klass not in MOVE_POINTS:
            return None
        points = MOVE_POINTS[klass][size]
        navy = bool(navy)
    if type(points) is not int or points <= 0:
        return None
    return {'klass': klass, 'size': size, 'navy': navy, 'points': points}


def default_cavalry_spec():
    return mover_spec(klass='cavalry_horse', size=0, navy=False)


def default_wagon_spec():
    return mover_spec(klass='wagon', size=0, navy=False)


KIND_CHOICES = (
    ('步兵', 'land'),
    ('骑兵', 'cavalry_horse'),
    ('弓兵', 'land'),
    ('粮草兵', 'wagon'),
)
SPRITE_KIND = {'步兵': '重装步兵', '骑兵': '重装骑兵', '弓兵': '重装弓兵', '粮草兵': '运输兵'}


def kind_spec(label, size=0):
    klass = dict(KIND_CHOICES).get(label)
    spec = mover_spec(klass=klass, size=size, navy=False)
    if spec:
        spec['label'] = label
    return spec


def sim_unit(state, cell, kind_label, size=0):
    """Sidebar troop as a field unit so move tiles and original sprites match the game."""
    spec = kind_spec(kind_label, size) or {}
    row = {
        'unit_id': 'raid-sim',
        'movement_simulation': True,
        'simulated_skill_mask': 1 if spec.get('klass') == 'cavalry_horse' else 0,
        'unit_kind': SPRITE_KIND.get(kind_label, kind_label),
        'owner_raw': player_id(state),
        'size_index': size,
        'world_xy_raw': [int(cell[0]), int(cell[1])],
    }
    if spec.get('klass'):
        row['move_klass'] = spec['klass']
    return row


def raid_reach_cells(state, cell, kind_label, terrain=None):
    if cell is None:
        return []
    origin = (int(cell[0]), int(cell[1]))
    return [item for item in reachable_cells(state, sim_unit(state, origin, kind_label), terrain) if item != origin]


def raid_move_overlay(state, cell, kind_label, terrain=None):
    if cell is None:
        return []
    return move_overlay_cells(state, sim_unit(state, cell, kind_label), terrain)


def field_unit_at(state, row):
    if not row:
        return None
    uid, owner = row.get('unit_id'), row.get('owner_raw')
    for item in ((state or {}).get('entities') or {}).get('field_units') or []:
        if item.get('unit_id') == uid and item.get('owner_raw') == owner:
            return item
    return None


def unit_reach_cells(state, unit, terrain=None):
    origin = world_xy(unit)
    if origin is None:
        return []
    return [item for item in reachable_cells(state, unit, terrain) if item != origin]


def unit_move_overlay(state, unit, terrain=None):
    if world_xy(unit) is None:
        return []
    return move_overlay_cells(state, unit, terrain)


def hostile_force_ids(state, target_id):
    own = player_id(state)
    ids = set()
    if type(target_id) is int and target_id != own:
        ids.add(target_id)
    for lord in ((state or {}).get('entities') or {}).get('lords') or []:
        fid = lord.get('force_id')
        if type(fid) is not int or fid == own:
            continue
        if allied(state, fid):
            continue
        if at_war(state, fid) or fid == target_id:
            ids.add(fid)
    return ids


def _city_vision_radius(state, row):
    radius = vision_radius(state, row)
    if radius > 0:
        return radius
    if row.get('type') == 'barrier':
        return 1
    if is_capital(state, row):
        return CAPITAL_VISION
    return 3 if row.get('type') in (None, 'city') else 0


def enemy_vision_sets(state, hostile_ids, dest_xy=None):
    """Hostile city/unit vision. dest_xy's own city vision is returned separately."""
    other = set()
    dest_vision = set()
    unit_cells = set()
    city_count = 0
    unit_count = 0
    ents = ((state or {}).get('entities') or {})
    dest_row = None
    for row in ents.get('cities_and_barriers') or []:
        owner = row.get('owner_raw')
        if owner not in hostile_ids:
            continue
        xy = world_xy(row)
        if xy is None:
            continue
        radius = _city_vision_radius(state, row)
        if radius <= 0:
            continue
        cells = set(vision_cells(xy, radius))
        if dest_xy is not None and xy == dest_xy:
            dest_vision = cells
            dest_row = row
            continue
        other |= cells
        city_count += 1
    for row in ents.get('field_units') or []:
        owner = row.get('owner_raw')
        if owner not in hostile_ids:
            continue
        xy = world_xy(row)
        if xy is None:
            continue
        unit_cells.add(xy)
        other |= set(vision_cells(xy, unit_vision_radius(state, row)))
        unit_count += 1
    return {
        'other': other,
        'dest': dest_vision,
        'unit_cells': unit_cells,
        'city_count': city_count,
        'unit_count': unit_count,
        'dest_row': dest_row,
    }


def occupying_cells(state, origin=None):
    cells = set()
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        xy = world_xy(row)
        if xy is not None and xy != origin:
            cells.add(xy)
    return cells


def enemy_city_cells(state, owner, dest_xy=None):
    cells = set()
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        xy = world_xy(row)
        if xy is None or xy == dest_xy:
            continue
        if row.get('owner_raw') != owner:
            cells.add(xy)
    return cells


def _cost_fn(state, terrain, navy, cache):
    dummy = {'unit_kind': '骑兵', 'movement_simulation': True,
             'simulated_skill_mask': 4 if navy else 0}

    def cost(cell):
        if cell in cache:
            return cache[cell]
        value = enter_cost(state, cell, terrain, dummy)
        cache[cell] = value
        return value

    return cost


def _dijkstra(origin, cost_fn, blocked, limit=None):
    if origin is None:
        return {}, {}
    spent = {origin: 0}
    parent = {origin: None}
    heap = [(0, origin)]
    while heap:
        cost, cell = heappop(heap)
        if cost != spent.get(cell):
            continue
        if limit is not None and cost > limit:
            continue
        for nxt in tile_neighbors(*cell):
            if nxt in blocked and nxt != origin:
                continue
            step = cost_fn(nxt)
            if step is None:
                continue
            total = cost + step
            if limit is not None and total > limit:
                continue
            if total >= spent.get(nxt, total + 1):
                continue
            spent[nxt] = total
            parent[nxt] = cell
            heappush(heap, (total, nxt))
    return spent, parent


def _reverse_one_turn(goals, cost_fn, blocked, points):
    """Cells from which a goal is reachable in one move. Cost is forward enter-sum."""
    spent = {}
    parent = {}
    heap = []
    for goal in goals:
        spent[goal] = 0
        parent[goal] = None
        heappush(heap, (0, goal))
    while heap:
        cost, cell = heappop(heap)
        if cost != spent.get(cell):
            continue
        if cost >= points:
            continue
        for pred in tile_neighbors(*cell):
            if pred in blocked:
                continue
            step = cost_fn(cell)
            if step is None:
                continue
            total = cost + step
            if total > points:
                continue
            if total >= spent.get(pred, total + 1):
                continue
            spent[pred] = total
            parent[pred] = cell
            heappush(heap, (total, pred))
    return spent, parent


def _rebuild(parent, end):
    if end not in parent:
        return []
    path = []
    cell = end
    while cell is not None:
        path.append(cell)
        cell = parent.get(cell)
    path.reverse()
    return path


def _rebuild_reverse(parent, start, goals):
    if start not in parent:
        return []
    path = []
    cell = start
    seen = set()
    while cell is not None and cell not in seen:
        path.append(cell)
        seen.add(cell)
        if cell in goals:
            return path
        cell = parent.get(cell)
    return path if path and path[-1] in goals else []


def split_turns(path, points, cost_fn):
    if not path:
        return []
    turns = []
    current = [path[0]]
    remain = points
    for cell in path[1:]:
        step = cost_fn(cell)
        if step is None:
            break
        if step > remain:
            turns.append(current)
            current = [current[-1], cell]
            remain = points - step
            if remain < 0:
                remain = 0
        else:
            current.append(cell)
            remain -= step
    if current:
        turns.append(current)
    return turns


def attack_cells(dest, cost_fn, blocked):
    cells = []
    for nb in tile_neighbors(*dest):
        if nb in blocked:
            continue
        if cost_fn(nb) is None:
            continue
        cells.append(nb)
    if cells:
        return cells
    if dest not in blocked and cost_fn(dest) is not None:
        return [dest]
    return []


def _terrain_kind_name(state, cell, terrain):
    from unit_move import terrain_kind
    dummy = {'unit_kind': '骑兵'}
    return terrain_kind(state, cell, terrain)


def tile_distance(a, b):
    if a is None or b is None:
        return 10 ** 9
    au, av = tile_axes(*a)
    bu, bv = tile_axes(*b)
    return abs(au - bu) + abs(av - bv)


def cell_walkable(state, cell, terrain=None):
    return enter_cost(state, cell, terrain) is not None


def city_ring_cells(state, city, terrain=None):
    """Walkable neighbor cells around a city (at most four)."""
    xy = world_xy(city)
    if xy is None:
        return []
    return [nb for nb in tile_neighbors(*xy) if cell_walkable(state, nb, terrain)]


def walk_ring_cells(state, cell, terrain=None):
    if cell is None:
        return []
    return [nb for nb in tile_neighbors(*cell) if cell_walkable(state, nb, terrain)]


def city_ring_cell(state, city, terrain=None):
    """First walkable neighbor of a city; units leave onto the ring, not the city tile."""
    cells = city_ring_cells(state, city, terrain)
    if cells:
        return cells[0]
    xy = world_xy(city)
    return xy if xy is not None and cell_walkable(state, xy, terrain) else None


def own_cities(state):
    own = player_id(state)
    if own is None:
        return []
    rows = []
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if row.get('type') not in (None, 'city'):
            continue
        if row.get('owner_raw') == own and world_xy(row):
            rows.append(row)
    return rows


def origin_watched(state, origin, hostile_ids):
    if origin is None:
        return False
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        if row.get('owner_raw') not in hostile_ids:
            continue
        xy = world_xy(row)
        if xy is None:
            continue
        if tile_distance(xy, origin) <= UNIT_VISION:
            return True
        if origin in vision_cells(xy, unit_vision_radius(state, row)):
            return True
    return False


def _dest_city_row(state, mark):
    cid = (mark or {}).get('city_id')
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if row.get('city_id') == cid:
            return row
    return None


def choose_origin_city(state, dest_row, terrain=None, cost_cache=None, mover=None):
    dest = world_xy(dest_row)
    cities = own_cities(state)
    if dest is None or not cities:
        return None, {
            'ok': False,
            'error': '目标主城坐标未解析。' if dest is None else '没有我方城可作起点。',
        }
    hostile = hostile_force_ids(state, dest_row.get('owner_raw'))
    ranked = sorted(cities, key=lambda row: tile_distance(world_xy(row), dest))[:8]
    cache = cost_cache if cost_cache is not None else {}
    plans = []
    for city in ranked:
        origin = world_xy(city)
        plan = plan_stealth_raid(state, origin, dest_row, terrain, cavalry=mover, cost_cache=cache)
        plan['origin_city'] = city
        plan['origin_name'] = city.get('name') or f"({origin[0]},{origin[1]})"
        plan['watched'] = origin_watched(state, origin, hostile)
        plan['distance'] = tile_distance(origin, dest)
        plans.append(plan)

    def score(plan):
        if not plan.get('ok'):
            return (9, 1, 1, 999, plan.get('distance') or 10 ** 9)
        return (
            1 if plan.get('watched') else 0,
            1 if plan.get('exposed') else 0,
            plan.get('arrive_calendar') or 999,
            plan.get('distance') or 10 ** 9,
        )

    nearest = plans[0]
    if nearest.get('ok') and not nearest.get('watched') and not nearest.get('exposed'):
        faster = [
            plan for plan in plans[1:]
            if plan.get('ok') and not plan.get('watched') and not plan.get('exposed')
            and (plan.get('arrive_calendar') or 999) <= (nearest.get('arrive_calendar') or 999) - 2
        ]
        if faster:
            pick = min(faster, key=score)
            saved = nearest['arrive_calendar'] - pick['arrive_calendar']
            pick['origin_reason'] = f"次近{pick['origin_name']}更方便，少{saved}回"
            return world_xy(pick['origin_city']), pick
        nearest['origin_reason'] = f"最近城 {nearest['origin_name']}"
        return world_xy(nearest['origin_city']), nearest
    pick = min(plans, key=score)
    if pick.get('ok') and pick.get('watched') is False and nearest.get('watched'):
        pick['origin_reason'] = f"最近{nearest['origin_name']}周边有敌，改从{pick['origin_name']}出发"
    elif pick.get('ok') and pick.get('watched'):
        pick['origin_reason'] = f"{pick['origin_name']}周边有敌军，仍是当前最好"
    elif pick.get('ok'):
        pick['origin_reason'] = f"从{pick['origin_name']}出发"
    else:
        pick['origin_reason'] = pick.get('error') or '算不出路线'
    if pick.get('ok'):
        pick['brief'] = format_raid_brief(pick)
        pick['detail'] = format_raid_detail(pick)
    return world_xy(pick.get('origin_city')) if pick.get('origin_city') else None, pick


def raid_targets(state):
    own = player_id(state)
    rows = []
    for mark in capital_marks(state):
        if mark.get('force_id') == own:
            continue
        rows.append({
            'force_id': mark.get('force_id'),
            'force_name': mark.get('force_name') or '?',
            'city_name': mark.get('city_name') or '?',
            'turns': None,
            'origin_name': '',
            'reason': '',
            'ok': False,
            'plan': None,
            'war': at_war(state, mark.get('force_id')),
        })
    rows.sort(key=lambda row: (0 if row.get('war') else 1, row.get('force_id') or 99))
    return rows


def raid_board(state, terrain=None):
    own = player_id(state)
    rows = []
    cache = {}
    for mark in capital_marks(state):
        if mark.get('force_id') == own:
            continue
        dest_row = _dest_city_row(state, mark)
        if dest_row is None:
            rows.append({
                'force_id': mark.get('force_id'),
                'force_name': mark.get('force_name') or '?',
                'city_name': mark.get('city_name') or '?',
                'turns': None,
                'origin_name': '',
                'reason': '首都未解析',
                'ok': False,
                'plan': None,
                'war': at_war(state, mark.get('force_id')),
            })
            continue
        _origin, plan = choose_origin_city(state, dest_row, terrain, cost_cache=cache)
        rows.append({
            'force_id': mark.get('force_id'),
            'force_name': mark.get('force_name') or '?',
            'city_name': mark.get('city_name') or dest_row.get('name') or '?',
            'turns': plan.get('arrive_calendar') if plan.get('ok') else None,
            'cavalry_turns': plan.get('cavalry_turns'),
            'origin_name': plan.get('origin_name') or '',
            'reason': plan.get('origin_reason') or plan.get('error') or '',
            'ok': bool(plan.get('ok')),
            'plan': plan,
            'war': at_war(state, mark.get('force_id')),
        })
    rows.sort(key=lambda row: (0 if row.get('war') else 1, 0 if row.get('ok') else 1, row.get('turns') or 999, row.get('force_id') or 99))
    return rows


def resolve_raid_endpoints(state, selected_kind=None, selected_row=None, focus_force_id=None):
    own = player_id(state)
    origin = None
    origin_unit = None
    dest_row = None
    if selected_kind == '部队' and selected_row is not None:
        xy = world_xy(selected_row)
        if xy is not None and (own is None or selected_row.get('owner_raw') == own):
            origin, origin_unit = xy, selected_row
    if selected_kind == '城关' and selected_row is not None:
        if own is not None and selected_row.get('owner_raw') == own and origin is None:
            origin = world_xy(selected_row)
        elif own is None or selected_row.get('owner_raw') != own:
            dest_row = selected_row
    if origin is None and own is not None:
        for mark in capital_marks(state):
            if mark.get('force_id') == own:
                origin = mark.get('world_xy')
                break
    if origin is None and own is not None:
        for row in ((state or {}).get('entities') or {}).get('field_units') or []:
            if row.get('owner_raw') == own and world_xy(row):
                origin, origin_unit = world_xy(row), row
                break
    if dest_row is None:
        target_id = focus_force_id if type(focus_force_id) is int and focus_force_id != own else None
        marks = capital_marks(state)
        if target_id is not None:
            dest_row = next((
                row for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []
                if row.get('city_id') == next((m['city_id'] for m in marks if m.get('force_id') == target_id), None)
            ), None)
        if dest_row is None:
            war_marks = [m for m in marks if at_war(state, m.get('force_id'))]
            pick = war_marks[0] if war_marks else None
            if pick is None:
                pick = next((m for m in marks if m.get('force_id') != own), None)
            if pick is not None:
                dest_row = next((
                    row for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []
                    if row.get('city_id') == pick.get('city_id')
                ), None)
    return origin, origin_unit, dest_row


def plan_stealth_raid(state, origin, dest_row, terrain=None, cavalry=None, wagon=None, origin_unit=None, cost_cache=None):
    if origin is None or dest_row is None:
        return {'ok': False, 'error': '未确认起点或目标主城。点我方部队/城，再点敌方首都。'}
    dest = world_xy(dest_row)
    if dest is None:
        return {'ok': False, 'error': '目标主城坐标未解析。'}
    own = player_id(state)
    if own is None:
        return {'ok': False, 'error': '未确认我方，不能算偷袭。'}
    target_id = dest_row.get('owner_raw')
    if target_id == own:
        return {'ok': False, 'error': '目标是我方城，请点敌方首都。'}
    if cavalry is None and origin_unit is not None:
        cavalry = mover_spec(state, origin_unit)
        if cavalry and cavalry['klass'] not in ('cavalry', 'cavalry_horse'):
            cavalry = default_cavalry_spec()
    cavalry = cavalry or default_cavalry_spec()
    wagon = wagon or default_wagon_spec()
    if not cavalry or not wagon:
        return {'ok': False, 'error': '骑兵或粮车移动力未解析。'}
    hostile = hostile_force_ids(state, target_id)
    vision = enemy_vision_sets(state, hostile, dest)
    cache = cost_cache if cost_cache is not None else {}
    cost_fn = _cost_fn(state, terrain, cavalry['navy'], cache)
    occupied = occupying_cells(state, origin)
    cities = enemy_city_cells(state, own, dest)
    other_vision = set(vision['other'])
    dest_vision = set(vision['dest']) or set(vision_cells(dest, _city_vision_radius(state, dest_row)))
    hidden_blocked = occupied | cities | other_vision | dest_vision
    # 末回合允许走进都城视野；与都城视野重叠的敌兵视野不再封死邻格。
    dash_blocked = occupied | cities | (other_vision - dest_vision)
    goals = attack_cells(dest, cost_fn, dash_blocked)
    if not goals:
        return {'ok': False, 'error': '主城邻格被占满或不能走，无法抵城。'}
    dash_spent, dash_parent = _reverse_one_turn(goals, cost_fn, dash_blocked, cavalry['points'])
    staging_cells = [
        cell for cell, paid in dash_spent.items()
        if cell not in dest_vision and cell not in other_vision and cell not in occupied
        and cell not in cities and cost_fn(cell) is not None
    ]
    names = {
        lord.get('force_id'): lord.get('name') or f"#{lord.get('force_id')}"
        for lord in ((state or {}).get('entities') or {}).get('lords') or []
    }
    dest_name = dest_row.get('name') or f"#{dest_row.get('city_id')}"
    dest_force = names.get(target_id, '敌方')
    hidden_spent, hidden_parent = _dijkstra(origin, cost_fn, hidden_blocked)
    reachable_staging = [cell for cell in staging_cells if cell in hidden_spent]
    exposed = False
    hidden_path = []
    dash_path = []
    staging = None
    if origin in dest_vision or origin in other_vision:
        if origin in dash_spent and origin not in other_vision:
            staging = origin
            hidden_path = [origin]
            dash_path = _rebuild_reverse(dash_parent, origin, set(goals))
        elif origin in other_vision:
            return {
                'ok': False,
                'error': f'起点 ({origin[0]},{origin[1]}) 已在敌方部队/其他城视野内，无法在不被看到的情况下出发。',
            }
    if staging is None and reachable_staging:
        def staging_key(cell):
            kind = _terrain_kind_name(state, cell, terrain)
            hill = 0 if kind == '丘陵森林' else 1
            return (hidden_spent[cell], hill, dash_spent.get(cell, 99), cell)
        staging = min(reachable_staging, key=staging_key)
        hidden_path = _rebuild(hidden_parent, staging)
        dash_path = _rebuild_reverse(dash_parent, staging, set(goals))
    if not hidden_path or not dash_path:
        # Fallback: may walk inside dest vision for more than one turn.
        exposed_blocked = occupied | cities | other_vision
        exposed_spent, exposed_parent = _dijkstra(origin, cost_fn, exposed_blocked)
        goal = min((cell for cell in goals if cell in exposed_spent), key=exposed_spent.get, default=None)
        if goal is None:
            return {
                'ok': False,
                'error': f'到{dest_force}·{dest_name}没有避开敌视野的路（地形/敌军挡住）。',
            }
        full = _rebuild(exposed_parent, goal)
        exposed = True
        hidden_path, dash_path = _split_exposed(full, dest_vision)
        staging = hidden_path[-1] if hidden_path else origin
    if hidden_path and dash_path and hidden_path[-1] == dash_path[0]:
        full_path = hidden_path + dash_path[1:]
    else:
        full_path = hidden_path + dash_path
    already = len(hidden_path) <= 1 and not exposed
    hidden_chunks = split_turns(hidden_path, cavalry['points'], cost_fn) if len(hidden_path) > 1 else []
    dash_chunks = split_turns(dash_path, cavalry['points'], cost_fn) if len(dash_path) > 1 else []
    # 集结格停步，余下移动力不带进主城视野。
    cav_turns = dash_chunks if already else hidden_chunks + dash_chunks
    wagon_chunks = split_turns(hidden_path, wagon['points'], cost_fn) if len(hidden_path) > 1 else []
    hidden_turn_count = 0 if already else len(hidden_chunks)
    cavalry_turns = len(cav_turns)
    wagon_turn_count = 0 if already else len(wagon_chunks)
    arrive_calendar = cavalry_turns if already else 1 + cavalry_turns
    staging_kind = _terrain_kind_name(state, staging, terrain) if staging else ''
    plan = {
        'ok': True,
        'exposed': exposed,
        'already_in_range': already,
        'origin': origin,
        'dest': dest,
        'dest_name': dest_name,
        'dest_force': dest_force,
        'dest_force_id': target_id,
        'staging': staging,
        'staging_kind': staging_kind,
        'hidden_path': hidden_path,
        'dash_path': dash_path,
        'full_path': full_path,
        'cavalry': cavalry,
        'wagon': wagon,
        'cavalry_turns': cavalry_turns,
        'hidden_turns': hidden_turn_count,
        'dash_turns': len(dash_chunks),
        'wagon_turns': wagon_turn_count,
        'arrive_calendar': arrive_calendar,
        'cavalry_turn_cells': [turn[-1] for turn in cav_turns],
        'wagon_turn_cells': [turn[-1] for turn in wagon_chunks],
        'vision_units': vision['unit_count'],
        'vision_cities': vision['city_count'] + (1 if dest_vision else 0),
        'goals': goals,
        'source': SOURCE,
    }
    plan['brief'] = format_raid_brief(plan)
    plan['detail'] = format_raid_detail(plan)
    return plan


def _split_exposed(full, dest_vision):
    if not full:
        return [], []
    idx = 0
    for i, cell in enumerate(full):
        if cell in dest_vision:
            idx = i
            break
        idx = i
    if idx <= 0:
        return [full[0]], full
    return full[:idx + 1], full[idx:]


def format_raid_brief(plan):
    if not plan.get('ok'):
        return plan.get('error') or '无法计算偷袭路线'
    cav = plan['cavalry']
    size = SIZE_NAME[cav['size']] if cav['size'] in (0, 1, 2) else '未知规模'
    dest = f"{plan['dest_force']}·{plan['dest_name']}"
    label = cav.get('label') or ('骑马骑兵' if cav.get('klass') == 'cavalry_horse' else size)
    reason = plan.get('origin_reason')
    prefix = (reason + ' · ') if reason else ''
    if plan.get('already_in_range'):
        return (
            f'{prefix}偷袭{dest}：{label}移动力{cav["points"]} · '
            f'起点已在冲城距离内，{plan["cavalry_turns"]}回冲入主城邻格 · {SOURCE_SHORT}'
        )
    extra = '需在主城视野内多走，不是完全隐秘 · ' if plan.get('exposed') else ''
    return (
        f'{prefix}偷袭{dest}：{label}移动力{cav["points"]} · '
        f'{extra}隐秘{plan["hidden_turns"]}回后末回合冲城 · '
        f'粮车{plan["wagon"]["points"]}点{plan["wagon_turns"]}回先行，'
        f'骑兵下回出发第{plan["arrive_calendar"]}回抵达 · '
        f'绕开敌视野{plan["vision_units"]}支/{plan["vision_cities"]}城 · {SOURCE_SHORT}'
    )


def format_raid_detail(plan):
    if not plan.get('ok'):
        return plan.get('error') or '无法计算偷袭路线'
    cav = plan['cavalry']
    size = SIZE_NAME[cav['size']] if cav['size'] in (0, 1, 2) else '未知规模'
    ox, oy = plan['origin']
    dx, dy = plan['dest']
    sx, sy = plan.get('staging') or plan['origin']
    horse = '骑马' if cav.get('klass') == 'cavalry_horse' else '无骑马'
    lines = [f"目标 {plan['dest_force']} 首都 {plan['dest_name']} ({dx},{dy})"]
    if plan.get('origin_reason'):
        lines.append(plan['origin_reason'])
    lines.append(f"起点 ({ox},{oy}) · 集结 ({sx},{sy}) {plan.get('staging_kind') or ''}".rstrip())
    lines.append(f'骑兵默认埋伏+{horse}{size} 移动力{cav["points"]}')
    lines.append(f"粮车（伏兵）移动力{plan['wagon']['points']}，先走隐秘段，不进主城视野")
    if plan.get('already_in_range'):
        lines.append(f"起点已在冲城距离内，骑兵 {plan['cavalry_turns']} 回抵达邻格")
    else:
        lines.append(
            f"粮车先行 {plan['wagon_turns']} 回到集结格；下回派 3 支骑兵沿同路，"
            f"再 {plan['cavalry_turns']} 回，日历第 {plan['arrive_calendar']} 回抵城邻格"
        )
        lines.append('三支骑兵同路错格，不要叠在一格。')
    if plan.get('exposed'):
        lines.append('警告：没法完全避开目标主城视野，末段会提前被都城看到。')
    lines.append(
        f"避开敌出征 {plan['vision_units']} 支（普通2格/谍报4格）和其城关视野；"
        f"末回合才进 {plan['dest_name']} 都城视野。"
    )
    ticks = plan.get('cavalry_turn_cells') or []
    if ticks:
        shown = '、'.join(f'{i+1}回({x},{y})' for i, (x, y) in enumerate(ticks[:12]))
        if len(ticks) > 12:
            shown += '…'
        lines.append('骑兵停步：' + shown)
    lines.append(SOURCE)
    return '\n'.join(lines)


CONFIRMED_CTX = ('verified', 'confirmed', 'user_confirmed')


def raid_player_id(state):
    own = player_id(state)
    if own is not None:
        return own
    ctx = (state or {}).get('player_context') or {}
    if ctx.get('status') in CONFIRMED_CTX and type(ctx.get('force_id')) is int:
        return ctx['force_id']
    return None


def state_for_raid(state):
    own = raid_player_id(state)
    if own is None or state is None:
        return state
    out = dict(state)
    out['player_force_id'] = own
    ident = dict(out.get('player_identity') or {})
    ident['status'] = 'confirmed'
    ident['force_id'] = own
    out['player_identity'] = ident
    return out


def _discovery_of(plan):
    if not plan.get('ok'):
        return plan.get('error') or '算不出'
    if plan.get('watched'):
        return '起点周边有敌军视野'
    if plan.get('exposed'):
        return '隐秘段不够，末段会提前被都城看到'
    if plan.get('already_in_range'):
        return '已在冲城距离，容易被都城看到'
    return '隐秘接近，末回合才进都城视野'


def compact_raid_plan(plan, state=None):
    city = plan.get('origin_city')
    dest = plan.get('dest')
    origin = plan.get('origin')
    return {
        'ok': bool(plan.get('ok')),
        'dest_force_id': plan.get('dest_force_id'),
        'dest_force': plan.get('dest_force'),
        'dest_name': plan.get('dest_name'),
        'dest_city_id': plan.get('dest_city_id'),
        'dest_xy': list(dest) if dest else None,
        'origin_city_id': None if not city else city.get('city_id'),
        'origin_name': plan.get('origin_name') or '',
        'origin_xy': list(origin) if origin else None,
        'sortie_cells': [list(cell) for cell in city_ring_cells(state, city)] if state and city else [],
        'staging': list(plan['staging']) if plan.get('staging') else None,
        'staging_kind': plan.get('staging_kind') or '',
        'arrive_calendar': plan.get('arrive_calendar'),
        'hidden_turns': plan.get('hidden_turns'),
        'dash_turns': plan.get('dash_turns'),
        'cavalry_turns': plan.get('cavalry_turns'),
        'wagon_turns': plan.get('wagon_turns'),
        'distance': plan.get('distance'),
        'watched': bool(plan.get('watched')),
        'exposed': bool(plan.get('exposed')),
        'already_in_range': bool(plan.get('already_in_range')),
        'war': bool(plan.get('war')),
        'discovery': _discovery_of(plan),
        'reason': plan.get('origin_reason') or plan.get('error') or '',
        'brief': plan.get('brief') or format_raid_brief(plan),
        'cavalry_turn_cells': [list(cell) for cell in (plan.get('cavalry_turn_cells') or [])[:8]],
        'error': None if plan.get('ok') else (plan.get('error') or '算不出路线'),
    }


def raid_plans_payload(state, dest_force_id=None, origin_city_id=None, limit=3):
    """Compact raid advisor for MCP/CLI. No full path. Default 3, max 8."""
    limit = 8 if type(limit) is not int else max(1, min(8, limit))
    use = state_for_raid(state)
    own = raid_player_id(use)
    payload = {
        'reply_contract': {
            'default_max_lines': 8,
            'expand_only_on_followup': True,
            'no_tables_unless_asked': True,
            'no_ascii_maps_unless_asked': True,
        },
        'player_confirmed': own is not None,
        'player_force_id': own,
        'terrain_grid': isinstance((use or {}).get('terrain_grid'), dict),
        'mover': {'cavalry_points': 18, 'wagon_points': 14, 'label': '骑马骑兵小队'},
        'source': SOURCE,
        'evidence': 'inferred',
        'note': '按敌视野和地形网格估隐秘路，不是引擎逐步验证。Hub 界面不再现场算这条路。',
    }
    if own is None:
        payload.update({'recommended': None, 'plans': [], 'error': '未确认我方，只提供全局情报，不算出兵城。'})
        return payload
    marks = [mark for mark in capital_marks(use) if mark.get('force_id') != own and not allied(use, mark.get('force_id'))]
    if type(dest_force_id) is int:
        marks = [mark for mark in marks if mark.get('force_id') == dest_force_id]
    if not marks:
        payload.update({
            'recommended': None,
            'plans': [],
            'error': '指定势力没有可解析的都城，或是同盟。' if type(dest_force_id) is int else '没有可偷袭的都城。',
        })
        return payload
    rows = []
    cache = {}
    forced = origin_city_id if type(origin_city_id) is int else None
    for mark in marks:
        dest_row = _dest_city_row(use, mark)
        if dest_row is None:
            continue
        if forced is not None:
            city = next((row for row in own_cities(use) if row.get('city_id') == forced), None)
            origin = world_xy(city) if city else None
            plan = plan_stealth_raid(use, origin, dest_row, cost_cache=cache)
            plan['origin_city'] = city
            plan['origin_name'] = (city or {}).get('name') or ''
            plan['watched'] = origin_watched(use, origin, hostile_force_ids(use, dest_row.get('owner_raw')))
            plan['distance'] = tile_distance(origin, world_xy(dest_row))
            plan['war'] = at_war(use, dest_row.get('owner_raw'))
            plan['dest_city_id'] = dest_row.get('city_id')
            if plan.get('ok'):
                plan['brief'] = format_raid_brief(plan)
            rows.append(compact_raid_plan(plan, use))
            rows[-1]['dest_city_id'] = dest_row.get('city_id')
            continue
        cities = sorted(own_cities(use), key=lambda item: tile_distance(world_xy(item), world_xy(dest_row)))[:8]
        scored = []
        for city in cities:
            extra = plan_stealth_raid(use, world_xy(city), dest_row, cost_cache=cache)
            extra['origin_city'] = city
            extra['origin_name'] = city.get('name') or ''
            extra['watched'] = origin_watched(use, world_xy(city), hostile_force_ids(use, dest_row.get('owner_raw')))
            extra['distance'] = tile_distance(world_xy(city), world_xy(dest_row))
            extra['war'] = at_war(use, dest_row.get('owner_raw'))
            extra['dest_city_id'] = dest_row.get('city_id')
            if extra.get('ok'):
                extra['brief'] = format_raid_brief(extra)
            scored.append(compact_raid_plan(extra, use))
        scored.sort(key=lambda item: (
            0 if item.get('ok') else 1,
            1 if item.get('watched') else 0,
            1 if item.get('exposed') else 0,
            item.get('arrive_calendar') or 999,
            item.get('distance') or 10 ** 9,
        ))
        take = limit if type(dest_force_id) is int else 1
        rows.extend(scored[:take])
    rows.sort(key=lambda item: (
        0 if item.get('war') else 1,
        0 if item.get('ok') else 1,
        1 if item.get('watched') else 0,
        1 if item.get('exposed') else 0,
        item.get('arrive_calendar') or 999,
        item.get('distance') or 10 ** 9,
    ))
    plans = rows[:limit]
    payload.update({
        'dest_count': len(marks),
        'recommended': next((row for row in plans if row.get('ok')), plans[0] if plans else None),
        'plans': plans,
        'rejected': [row for row in rows if not row.get('ok')][:3],
    })
    return payload
