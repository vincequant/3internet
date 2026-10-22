"""Remaining-point reach using verified native entry costs; path rules are estimates."""
from functools import lru_cache
from heapq import heappop, heappush

from force_troop_totals import unit_kind
from panorama_model import WORLD, assigned_owner, tile_axes, vision_overlay_cells, world_xy
from native_unit_rules import (HORSE, NAVY, TERRAIN_ENCODING, native_build,
                               remaining_move, terrain_entry_cost, unit_skill_mask)

# 三国志联机网·军事作战「部队的移动力与地形消耗」（2026-09-13 页）。
MOVE_POINTS = {
    'land': (12, 10, 8),
    'cavalry': (16, 13, 10),
    'cavalry_horse': (18, 15, 12),
    'navy': (10, 10, 10),
    'wagon': (14, 14, 14),
}
TERRAIN_COST = {
    '道路': 2,
    '平地': 3,
    '丘陵森林': 5,
    '河川': 2,
    '桥梁': 4,
    '山岳': 6,
}
# Collector marks 4/6 as on_water (0x469f6f cell+0x0a). 15 = unread cell.
WATER_TYPES = {4, 6}
UNKNOWN_TERRAIN = 15
# Majority map from live 101×202 dump vs MBM. 2 mixed, stay on pixels.
# 3 洛阳南灰岩：小地图常判平地/路，游戏不能走。贴城关且像素不是灰岩的草坡
# （虎牢南坡 (54,83)）按平地，否则骑兵出不了关。7 函谷/虎牢是路。
# 城格引擎不是 7–14 时不走路价（襄阳 type 0 屋顶）。
# 4 平原沙滩仍要黄沙例外。
ENGINE_KIND = {
    1: '丘陵森林',
    3: '山岳',
    4: '河川',
    6: '河川',
    7: '道路',
    8: '道路',
    9: '道路',
    10: '道路',
    11: '道路',
    12: '道路',
    13: '道路',
    14: '道路',
}
SOURCE = '攻略：三国志联机网军事作战 · 地形消耗参考，不是引擎逐步验证'


def city_hp_text(row):
    defense = (row or {}).get('defense')
    if isinstance(defense, (list, tuple)) and len(defense) == 2:
        if all(type(value) is int for value in defense):
            return f'生命值 {defense[0]}/{defense[1]}'
    if type(defense) is int:
        return f'生命值 {defense}'
    return '生命值 未解析'


def city_morale_text(row):
    """City +0x47. Setter 0x434d76 clamps 0..100. Barriers are 64 bytes and have no field."""
    if (row or {}).get('type') == 'barrier':
        return None
    morale = (row or {}).get('morale')
    if type(morale) is int and 0 <= morale <= 100:
        return f'士气 {morale}'
    return '士气 未解析'


def city_marker_text(row):
    morale = city_morale_text(row)
    hp = city_hp_text(row)
    if not morale:
        return hp
    return f'{hp} · {morale}'


def lighten_rgb(rgb, amount):
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
        return (200, 200, 180)
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(int(channel + (255 - channel) * amount) for channel in rgb)


def unit_size_index(unit):
    size = (unit or {}).get('size_index')
    if size in (0, 1, 2):
        return size
    soldiers = (unit or {}).get('soldiers_candidate')
    if type(soldiers) is int:
        return int(soldiers > 20000) + int(soldiers > 35000)
    return 0


def plains_steps(points):
    if type(points) is not int or points < 0:
        return None
    return points // TERRAIN_COST['平地']


def cheap_steps(points):
    if type(points) is not int or points < 0:
        return None
    return points // TERRAIN_COST['道路']


def website_skill_names(officer):
    from officer_reference import officer_metrics
    info = officer_metrics(officer)
    text = info.get('skills') or ''
    if text in ('未匹配', '网站技能空表'):
        return set()
    return {part for part in text.split(' / ') if part}


def unit_skill_names(state, unit):
    from officer_sortie import resolved_officers
    names = set()
    for officer in resolved_officers(state, (unit or {}).get('general_ids')):
        names |= website_skill_names(officer)
    return names


def force_has_wuyue(state, unit):
    owner = (unit or {}).get('owner_raw')
    for force in ((state or {}).get('entities') or {}).get('lords') or []:
        if force.get('force_id') != owner:
            continue
        hand = force.get('hand_cards') or {}
        for slot in hand.get('slots') or []:
            if slot.get('card_id') == 25 or slot.get('name') == '吴越春秋':
                return True
    return False


def unit_has_navy(state, unit):
    if (unit or {}).get('movement_simulation') is True:
        return bool((unit.get('simulated_skill_mask') or 0) & NAVY)
    if native_build(state):
        mask = unit_skill_mask(state, unit)
        return bool(mask is not None and mask & NAVY)
    name = str((unit or {}).get('unit_kind') or '')
    if '水' in name or '船' in name or '舟' in name:
        return True
    skills = unit_skill_names(state, unit)
    return '水军' in skills or '全技能' in skills or force_has_wuyue(state, unit)


def unit_has_horse(state, unit):
    if (unit or {}).get('movement_simulation') is True:
        return bool((unit.get('simulated_skill_mask') or 0) & HORSE)
    if native_build(state):
        mask = unit_skill_mask(state, unit)
        return bool(mask is not None and mask & HORSE)
    skills = unit_skill_names(state, unit)
    return '骑马' in skills or '全技能' in skills


def move_class(state, unit):
    forced = (unit or {}).get('move_klass')
    if forced in MOVE_POINTS:
        return forced
    name = str((unit or {}).get('unit_kind') or '')
    if '粮' in name or '运输' in name:
        return 'wagon'
    if '水' in name or '船' in name or '舟' in name:
        return 'navy'
    kind = unit_kind(unit)
    if kind == 'cavalry' or '骑' in name:
        return 'cavalry_horse' if unit_has_horse(state, unit) else 'cavalry'
    return 'land'


def move_points(state, unit):
    if native_build(state) and (unit or {}).get('movement_simulation') is not True:
        return remaining_move(state, unit)
    size = unit_size_index(unit)
    if size is None:
        return None
    return MOVE_POINTS[move_class(state, unit)][size]


def tile_neighbors(x, y, world=WORLD):
    cu, cv = tile_axes(x, y)
    cells = []
    for du, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        u, v = cu + du, cv + dv
        ny = u + v
        nx = (u - v) // 2
        if 0 <= nx < world[0] and 0 <= ny < world[1]:
            cells.append((nx, ny))
    return cells


@lru_cache(maxsize=1)
def road_cells():
    from city_roads import load_road_edges, mbm_to_world
    cells = set()
    for edge in load_road_edges():
        for point in edge.get('path') or []:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                continue
            try:
                wx, wy = mbm_to_world(point[0], point[1])
                cell = (int(round(wx)), int(round(wy)))
            except (TypeError, ValueError):
                continue
            if 0 <= cell[0] < WORLD[0] and 0 <= cell[1] < WORLD[1]:
                cells.add(cell)
    return cells


def decode_terrain_grid(state):
    grid = (state or {}).get('terrain_grid') or {}
    width, height, types = grid.get('width'), grid.get('height'), grid.get('types')
    if not isinstance(types, str) or not _known_terrain(width, height):
        return None
    try:
        raw = bytes.fromhex(types)
    except ValueError:
        return None
    if len(raw) != width * height:
        return None
    return raw, width, height


def terrain_type_at(state, cell):
    grid = decode_terrain_grid(state)
    if grid:
        raw, width, height = grid
        x, y = cell
        if not (0 <= x < width and 0 <= y < height):return None
        code = raw[x * height + y]
        # Old collectors replaced both failed reads and codes >15 with 15.
        if code == 15 and (state.get('terrain_grid') or {}).get('encoding') != TERRAIN_ENCODING:
            return None
        return code
    for row in ((state or {}).get('entities') or {}).get('field_units') or []:
        if world_xy(row) == cell and type(row.get('terrain_type_raw')) is int:
            return row.get('terrain_type_raw')
    return None


def _known_terrain(width, height):
    if width == WORLD[0] and height == WORLD[1]:
        return True
    try:
        from scenario_maps import by_size
    except Exception:
        return False
    return by_size(width, height) is not None


def _mbm_rgb_at(terrain, px, py):
    tx, ty = int(px) // 48, int(py) // 24
    tiles_x = getattr(terrain, 'tiles_x', 203)
    tiles_y = getattr(terrain, 'tiles_y', 203)
    if not (0 <= tx < tiles_x and 0 <= ty < tiles_y):
        return None
    try:
        tile = terrain.tile(tx, ty)
        return tile.getpixel((min(47, int(px) % 48), min(23, int(py) % 24)))
    except Exception:
        return None


def _mbm_samples(terrain, cell):
    if terrain is None:
        return []
    from panorama_model import cell_diamond
    from tactical_terrain import world_pixel
    cx, cy = world_pixel(*cell)
    points = [(cx, cy)]
    for vx, vy in cell_diamond(*cell):
        points.append(((cx + vx) / 2, (cy + vy) / 2))
    samples = []
    for px, py in points:
        rgb = _mbm_rgb_at(terrain, px, py)
        if rgb:
            samples.append(rgb)
    return samples


def _road_shape_frac(terrain, cell, win=144):
    """全分辨率窗口内做连通域分析：只有细长（跨格延伸且两次腐蚀即碎）的

    路色组件才算路，返回其占格内菱形面积的比例。干草沙斑要么团块（腐蚀
    存活）要么散点（延伸不足），全被排除（2026-09-17 三步兵场景标定）。"""
    from collections import deque
    from tactical_terrain import world_pixel
    cx, cy = world_pixel(*cell)
    x0, y0 = int(cx - win), int(cy - win // 2)
    width, height = 2 * win, win
    mask = [[False] * width for _ in range(height)]
    for j in range(height):
        for i in range(width):
            rgb = _mbm_rgb_at(terrain, x0 + i, y0 + j)
            if rgb and classify_mbm(rgb) == '道路':
                mask[j][i] = True
    seen = [[False] * width for _ in range(height)]
    def in_diamond(i, j):
        return abs(x0 + i - cx) / 48 + abs(y0 + j - cy) / 24 <= 1.0
    dia_px = 48 * 24 * 2
    good = 0
    for j in range(height):
        for i in range(width):
            if not mask[j][i] or seen[j][i]:
                continue
            comp = []
            queue = deque([(i, j)])
            seen[j][i] = True
            while queue:
                a, b = queue.popleft()
                comp.append((a, b))
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    na, nb = a + da, b + db
                    if 0 <= na < width and 0 <= nb < height and mask[nb][na] and not seen[nb][na]:
                        seen[nb][na] = True
                        queue.append((na, nb))
            xs = [a for a, _ in comp]
            ys = [b for _, b in comp]
            extent = max(max(xs) - min(xs), (max(ys) - min(ys)) * 2)
            cells = set(comp)
            eroded = {p for p in cells
                      if (p[0] + 1, p[1]) in cells and (p[0] - 1, p[1]) in cells
                      and (p[0], p[1] + 1) in cells and (p[0], p[1] - 1) in cells}
            eroded2 = {p for p in eroded
                       if (p[0] + 1, p[1]) in eroded and (p[0] - 1, p[1]) in eroded
                       and (p[0], p[1] + 1) in eroded and (p[0], p[1] - 1) in eroded}
            thin = (len(eroded2) / len(comp)) if comp else 1.0
            if extent >= 90 and thin < 0.45:
                good += sum(1 for a, b in comp if in_diamond(a, b))
    return good / dia_px


def road_fraction(terrain, cell):
    """菱形格内 (道路证据占比, 河川色占比)（缓存在 terrain 上）。

    道路只认细长连通线（_road_shape_frac ≥2%）。干草沙斑与路色完全重叠，
    暖色（R-G≥10）兜底会把团块沙斑当成路，蓟南侧因此多画两格（2026-09-17
    司马错@蓟南）。临水格（水色≥3%）由调用方否决。polyline 折线抄近角、
    纯色占比、暖色兜底都已废弃。"""
    if terrain is None:
        return 0.0, 0.0
    cache = getattr(terrain, '_road_frac_cache', None)
    if cache is None:
        cache = {}
        terrain._road_frac_cache = cache
    if cell in cache:
        return cache[cell]
    from tactical_terrain import world_pixel
    cx, cy = world_pixel(*cell)
    total = road = water = 0
    for dy in range(-22, 23, 2):
        for dx in range(-46, 47, 4):
            if abs(dx) / 48 + abs(dy) / 24 > 1.0:
                continue
            rgb = _mbm_rgb_at(terrain, cx + dx, cy + dy)
            if not rgb:
                continue
            total += 1
            kind = classify_mbm(rgb)
            if kind == '道路':
                road += 1
            elif kind == '河川':
                water += 1
    water_frac = (water / total) if total else 0.0
    if not total or (road / total) < 0.02:
        frac = (0.0, water_frac)
        cache[cell] = frac
        return frac
    frac = (_road_shape_frac(terrain, cell), water_frac)
    cache[cell] = frac
    return frac


def bank_sand_sample(rgb):
    """河岸黄沙：R/G 高、B 低。晋阳东岸 (50,45)(50,48) 含水像素但游戏可走。"""
    if not rgb or len(rgb) < 3:
        return False
    red, green, blue = rgb[:3]
    return red >= 150 and green >= 140 and blue <= 140 and red + green >= 2 * blue + 20


def hill_sample(rgb):
    """深橄榄绿丘陵地样本：比平原草色暗且绿仍占优（图二西北无格带取样标定）。"""
    if not rgb or len(rgb) < 3:
        return False
    red, green, blue = rgb[:3]
    return green <= 172 and red + green + blue <= 430 and green >= blue


def classify_mbm(rgb):
    if not rgb or len(rgb) < 3:
        return None
    red, green, blue = rgb[:3]
    if blue >= 85 and blue > red + 12 and blue >= green:
        return '河川'
    if red >= 200 and green >= 185 and 110 <= blue <= 230 and abs(red - green) <= 40 and (red + green) / 2 - blue >= 8:
        return '道路'
    if red + green + blue < 140:
        return '山岳'
    return '平地'


def _touches_settlement(state, cell):
    """四邻是否有城或关。虎牢南坡贴着关城，洛阳南灰岩不贴洛阳。"""
    nbs = set(tile_neighbors(*cell))
    if not nbs:
        return False
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if world_xy(row) in nbs:
            return True
    return False


def _is_settlement(state, cell):
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if world_xy(row) == cell:
            return True
    return False


def terrain_kind(state, cell, terrain=None):
    code = terrain_type_at(state, cell)
    if native_build(state):
        if code in (0,5):return '平地'
        if code in (1,2):return '丘陵森林'
        if code == 3:return '山岳'
        if code in (4,6):return '河川'
        if code in (18,19):return '桥梁'
        if type(code) is int and (7 <= code <= 17 or 20 <= code <= 23):return '道路'
        return '未知'
    samples = _mbm_samples(terrain, cell)
    kinds = [classify_mbm(rgb) for rgb in samples]
    sand = any(bank_sand_sample(rgb) for rgb in samples)
    mapped = ENGINE_KIND.get(code) if type(code) is int else None
    # 平原沙滩 (70,56) 引擎是 4，游戏可走；黄沙例外优先于 4/6。
    if mapped == '河川' and not sand:
        return '河川'
    if mapped == '山岳':
        # 同码灰岩不能走；贴城关的草坡（虎牢 (54,83) hill<3）按平地出关。
        hills = sum(1 for rgb in samples if hill_sample(rgb)) if samples else 0
        if samples and hills < 3 and _touches_settlement(state, cell):
            return '平地'
        return '山岳'
    if mapped and mapped != '河川':
        return mapped
    # 引擎非水面码压过 MBM 假河：寿春河面在小地图上是青绿，五点水色不够，
    # 但公孙瓒所在格 (73,98) 会被 MBM 判成河川。15 是采集失败，仍走像素。
    engine_land = type(code) is int and code != UNKNOWN_TERRAIN and code not in WATER_TYPES
    if mapped == '河川' and sand:
        engine_land = True
    # 两点河川即算水面（江陵南岸水格只有 2/5）；黄沙岸除外（晋阳东岸）。
    if not engine_land and kinds and kinds.count('河川') >= 2 and not sand:
        return '河川'
    # 道路只认细长连通线；polyline / 五点采样 / 暖色兜底都会把干草沙斑当路。
    road_frac, water_frac = road_fraction(terrain, cell)
    # 致密水色≥25% 且无黄沙 → 河川。黄沙只救「能不能走」，不给路价 2，
    # 否则江陵岸线被当成细路，骑兵沿水多走出一截。
    if not engine_land and water_frac >= 0.25 and not sand:
        return '河川'
    if (road_frac >= 0.02 and water_frac < 0.03) or (
            terrain is None and kinds.count('道路') >= 2):
        # 引擎 7–14 已在上面当路。城格 type 0 的屋顶/穿城路像素不要走路价 2，
        # 否则襄阳进城剩太多，12 点步兵会多踩一格灰岩坡；弓兵从邻格上坡仍可走。
        engine_non_road = (
            type(code) is int and code != UNKNOWN_TERRAIN and code not in range(7, 15)
        )
        if not (engine_non_road and _is_settlement(state, cell)):
            return '道路'
    if kinds and kinds.count('山岳') >= 2:
        return '山岳'
    if samples and sum(1 for rgb in samples if hill_sample(rgb)) >= 3:
        return '丘陵森林'
    if not engine_land:
        for row in ((state or {}).get('entities') or {}).get('field_units') or []:
            if world_xy(row) == cell and row.get('on_water') is True:
                return '河川'
    return '平地'


def enter_cost(state, cell, terrain=None, unit=None):
    if native_build(state):
        code = terrain_type_at(state, cell)
        setting = (state.get('movement_rules') or {}).get('mountain_enabled_raw')
        mask = unit_skill_mask(state, unit)
        if (unit or {}).get('movement_simulation') is True:
            value = unit.get('simulated_skill_mask')
            mask = value if type(value) is int and 0 <= value <= 7 else None
        return terrain_entry_cost(code, (unit or {}).get('unit_kind'),
                                  mask, setting)
    kind = terrain_kind(state, cell, terrain)
    if kind == '山岳':
        return None
    if kind == '河川' and unit is not None and not unit_has_navy(state, unit):
        return None
    return TERRAIN_COST[kind]


def blocked_cells(state, unit):
    """Cells the unit cannot enter or pass: other units, enemy cities/barriers."""
    origin = world_xy(unit)
    owner = (unit or {}).get('owner_raw')
    ents = ((state or {}).get('entities') or {})
    blocked = set()
    for row in ents.get('field_units') or []:
        cell = world_xy(row)
        if cell is not None and cell != origin:
            blocked.add(cell)
    for row in ents.get('cities_and_barriers') or []:
        cell = world_xy(row)
        if cell is not None and row.get('owner_raw') != owner:
            blocked.add(cell)
    return blocked


def building_cells(state):
    """练兵所/牧场等生产建筑：格上不画网格，但部队可以穿行（11:51 三步兵场景标定）。"""
    cells = set()
    for row in (((state or {}).get('entities') or {}).get('production_buildings')) or []:
        cell = world_xy(row)
        if cell is not None:
            cells.add(cell)
    return cells


def zoc_cells(state, unit):
    """敌军控制区：敌部队四邻格，走进即止，不能借道去敌后。"""
    owner = (unit or {}).get('owner_raw')
    ents = ((state or {}).get('entities') or {})
    zone = set()
    for row in ents.get('field_units') or []:
        cell = world_xy(row)
        if cell is None or row.get('owner_raw') == owner:
            continue
        zone.update(tile_neighbors(*cell))
    return zone


def own_city_cells(state, unit):
    """己方城关：可穿行（城在范围中间时对岸仍有格），格上不画（游戏显示 ENTER）。"""
    owner = (unit or {}).get('owner_raw')
    ents = ((state or {}).get('entities') or {})
    cells = set()
    for row in ents.get('cities_and_barriers') or []:
        cell = world_xy(row)
        if cell is not None and row.get('owner_raw') == owner:
            cells.add(cell)
    return cells


def stop_cells(state, unit):
    """不再把己方城当停步。平原海岸场景城在范围正中，对岸仍有行走格。"""
    return set()


def reachable_cells(state, unit, terrain=None):
    origin = world_xy(unit)
    points = move_points(state, unit)
    if origin is None or points is None:
        return {}
    blocked = blocked_cells(state, unit)
    zone = zoc_cells(state, unit)
    best = {origin: points}
    heap = [(0, origin)]
    spent = {origin: 0}
    while heap:
        cost, cell = heappop(heap)
        if cost != spent.get(cell):
            continue
        if cell != origin and cell in zone:
            continue  # 敌方控制区：可达即停，不再外扩。己方城可穿行。
        for nxt in tile_neighbors(*cell):
            if nxt in blocked:
                continue
            step = enter_cost(state, nxt, terrain, unit)
            if step is None:
                continue
            total = cost + step
            if total > points or total >= spent.get(nxt, points + 1):
                continue
            spent[nxt] = total
            best[nxt] = points - total
            heappush(heap, (total, nxt))
    return best


def move_brief(state, unit, reach=None):
    if native_build(state):
        points = remaining_move(state, unit)
        if points is None:return '剩余移动点未采集 · 移动范围未生成'
        cells = reach if reach is not None else reachable_cells(state, unit)
        missing = ' · 山地开关未采集' if (state.get('movement_rules') or {}).get('mountain_enabled_raw') is None else ''
        return (f'剩余移动点 {points} · 预计可达 {max(0,len(cells)-1)} 格 · 原生地形成本'
                +missing+'；占位、控制区及水陆转换尚未完整核实')
    size = unit_size_index(unit)
    points = move_points(state, unit)
    klass = move_class(state, unit)
    labels = {
        'land': '步/弓',
        'cavalry': '骑（无骑马）',
        'cavalry_horse': '骑（骑马）',
        'navy': '水军',
        'wagon': '粮车',
    }
    size_name = ('小队', '中队', '大队')[size] if size in (0, 1, 2) else '未知规模'
    if points is None:
        return f'前进距离未解析 · {SOURCE}'
    cells = reach if reach is not None else reachable_cells(state, unit)
    steps = plains_steps(points)
    cheap = cheap_steps(points)
    water = '有水军可下水' if unit_has_navy(state, unit) else '无水军水面不通行'
    return (
        f"前进 {labels[klass]}{size_name} 移动力{points} · 平地{steps}格（÷3）"
        f" · 道路{cheap}格（÷2）· {water} · 实画 {len(cells)} 格 · {SOURCE}"
    )


def move_overlay_cells(state, unit, terrain=None):
    reach = reachable_cells(state, unit, terrain)
    origin = world_xy(unit)
    owner = (unit or {}).get('owner_raw')
    unpainted = own_city_cells(state, unit) | building_cells(state)
    city_owner = {item['cell']: item['owner_raw'] for item in vision_overlay_cells(state)}
    items = []
    for cell, remain in reach.items():
        if cell == origin or cell in unpainted:
            continue  # 原点、己方城（ENTER）、建筑格可走但不画。
        same = assigned_owner(owner) and city_owner.get(cell) == owner
        items.append({
            'cell': cell,
            'owner_raw': owner,
            'center': cell == origin,
            'same_as_city': same,
            'remain': remain,
        })
    return items
