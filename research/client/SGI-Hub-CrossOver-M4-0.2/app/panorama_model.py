"""Panorama map: LBM/MBM layers and read-only overlay lists. No game writes."""
import json
import re
from functools import lru_cache
from pathlib import Path

from tactical_terrain import world_pixel

APP = Path(__file__).resolve().parent
WORLD = (101, 202)
LBM_SIZE = (525, 350)
MBM_SIZE = (9744, 4872)
SWITCH_ZOOM = 0.0
MIN_ZOOM = 0.28
MAX_ZOOM = 12.0
DETAIL_ZOOM = 2.0  # 再小就不画练兵所/牧场/陷阱，只留城池和军队
DEFAULT_CENTER = (50.5, 101.0)

RESEARCH = (
    '研究结论（独立于 Hub，不连采集、不写游戏）\n'
    '\n'
    '1. Hub 全景滚轮尽量一直用 SanInet.mbm 原作地面缩放，'
    '不再一缩小就切到 SanInet.lbm 全国示意图。\n'
    '2. 原作地面已经在 SanInet.mbm（9744×4872，48×24 交错菱格）里，'
    'Hub「城周边」已经在用同一套只读贴图。那才是山、路、水、灰地的来源。\n'
    '3. 宫殿、城墙、部队立体模型不在 MBM 里，是游戏实时三维。'
    '只读贴图做不到完整「原作画质」；城标可用已有 2D 原版精灵。\n'
    '4. 可行路线：滚轮全程裁切 MBM；只有倍率低于下限才可能落到 LBM 全国示意。\n'
    '5. 图上城名来自历史截图样本，不是当前对局归属。未做整张 MBM 预烘焙，也未还原三维建筑。'
)

LAYER_HINT = {
    'lbm': '战略底图 SanInet.lbm · 全国示意，再放大只会糊',
    'mbm': '原作地面 SanInet.mbm · 按视野裁切，接近城战地形',
}


def layer_for_zoom(zoom):
    return 'mbm' if float(zoom) >= SWITCH_ZOOM else 'lbm'


def clamp_zoom(zoom):
    return max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))


def min_zoom_inside(view_w, view_h, mbm_size=None):
    """Smallest zoom whose crop still fits inside the active terrain image."""
    view_w = max(1.0, float(view_w))
    view_h = max(1.0, float(view_h))
    mbm_size = mbm_size or MBM_SIZE
    span = 96.0 * 28.0
    return max(MIN_ZOOM, span / mbm_size[0], span * view_h / (view_w * mbm_size[1]))


def clamp_mbm_view(center, zoom, view_w, view_h, mbm_size=None, world=None):
    """Keep the visible terrain inside the active map. Zoom out stops at the edges."""
    mbm_size = mbm_size or MBM_SIZE
    world = world or WORLD
    zoom = max(min_zoom_inside(view_w, view_h, mbm_size), min(MAX_ZOOM, float(zoom)))
    cx, cy = world_pixel(*center)
    cells = max(2.4, 28.0 / zoom)
    scale = max(1.0, float(view_w)) / (96.0 * cells)
    half_w = max(1.0, float(view_w)) / scale / 2.0
    half_h = max(1.0, float(view_h)) / scale / 2.0
    lo_x, hi_x = half_w, mbm_size[0] - half_w
    lo_y, hi_y = half_h, mbm_size[1] - half_h
    cx = mbm_size[0] / 2.0 if lo_x > hi_x else min(max(cx, lo_x), hi_x)
    cy = mbm_size[1] / 2.0 if lo_y > hi_y else min(max(cy, lo_y), hi_y)
    y = (cy - 24.0) / 24.0
    x = (cx - 48.0 - 48.0 * (y % 2)) / 96.0
    return zoom, clamp_center((x, y), world)


def clamp_center(center, world=WORLD, offset=0.5):
    x, y = center
    return (
        max(offset, min(world[0] - 1 + offset, float(x))),
        max(offset, min(world[1] - 1 + offset, float(y))),
    )


def visible_cells(zoom):
    return max(2.4, 28.0 / clamp_zoom(zoom))


def mbm_view(center, zoom, view_w, view_h):
    """Return (pixel_box, scale) for a viewport crop of SanInet.mbm."""
    cx, cy = world_pixel(*center)
    cells = visible_cells(zoom)
    width = max(1, int(view_w))
    height = max(1, int(view_h))
    scale = width / (96 * cells)
    left = int(cx - width / scale / 2)
    top = int(cy - height / scale / 2)
    box = (left, top, left + int(width / scale) + 1, top + int(height / scale) + 1)
    return box, scale


def catalog_cities(palette=None):
    """Unique city positions from the historical screenshot palette. Not live ownership."""
    if palette is None:
        palette = json.loads((APP / 'game_palette.json').read_text(encoding='utf-8'))
    cities = {}
    for entry in palette.get('colors', {}).values():
        for sample in entry.get('samples', []):
            cid = sample.get('city_id')
            xy = sample.get('world_xy')
            name = sample.get('city_name')
            if type(cid) is not int or not isinstance(xy, (list, tuple)) or len(xy) != 2:
                continue
            if not all(type(v) in (int, float) for v in xy):
                continue
            if not (0 <= xy[0] < WORLD[0] and 0 <= xy[1] < WORLD[1]):
                continue
            cities[cid] = {'city_id': cid, 'name': name or f'#{cid}', 'world_xy': (int(xy[0]), int(xy[1]))}
    return sorted(cities.values(), key=lambda row: row['city_id'])


_POINT_QUERY = re.compile(r'^(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)$')


def parse_map_point(query):
    """Accept '52,124' or '52.5，124.5' as a world cell. Not a city name."""
    text = (query or '').strip()
    match = _POINT_QUERY.fullmatch(text)
    if not match:
        return None
    return (float(match.group(1)), float(match.group(2)))


@lru_cache(maxsize=1)
def _road_named_cities():
    from city_roads import ROADS_PATH, mbm_to_world
    try:
        data = json.loads(ROADS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ()
    found = {}
    for edge in data.get('edges') or []:
        path = edge.get('path') or []
        if len(path) < 1:
            continue
        for cid_key, name_key, index in (('a', 'a_name', 0), ('b', 'b_name', -1)):
            name = (edge.get(name_key) or '').strip()
            if not name:
                continue
            try:
                px, py = path[index]
                wx, wy = mbm_to_world(px, py)
            except (TypeError, ValueError, IndexError):
                continue
            cell = (int(round(wx)), int(round(wy)))
            if not (0 <= cell[0] < WORLD[0] and 0 <= cell[1] < WORLD[1]):
                continue
            cid = edge.get(cid_key)
            found[name] = {
                'city_id': cid if type(cid) is int else None,
                'name': name,
                'world_xy': cell,
                'source': 'roads',
            }
    return tuple(found.values())


def named_city_places(state=None):
    """Live city names first, then historical palette, then road-table names."""
    by_name = {}

    def add(name, xy, city_id=None, source='catalog'):
        name = (name or '').strip()
        if not name or not xy or len(xy) != 2:
            return
        try:
            cell = (int(xy[0]), int(xy[1]))
        except (TypeError, ValueError):
            return
        if not (0 <= cell[0] < WORLD[0] and 0 <= cell[1] < WORLD[1]):
            return
        row = {'name': name, 'world_xy': cell, 'city_id': city_id, 'source': source}
        if source == 'live' or name not in by_name:
            by_name[name] = row

    for row in catalog_cities():
        add(row.get('name'), row.get('world_xy'), row.get('city_id'), 'catalog')
    for row in _road_named_cities():
        add(row.get('name'), row.get('world_xy'), row.get('city_id'), 'roads')
    for row in (state or {}).get('entities', {}).get('cities_and_barriers') or []:
        add(row.get('name'), world_xy(row), row.get('city_id'), 'live')
    return sorted(by_name.values(), key=lambda item: item['name'])


def search_city_places(query, state=None):
    """Rank exact name, prefix, substring, then numeric city_id."""
    text = (query or '').strip()
    if not text:
        return []
    places = named_city_places(state)
    exact = [row for row in places if row['name'] == text]
    if exact:
        return exact
    prefix = [row for row in places if row['name'].startswith(text)]
    if prefix:
        return sorted(prefix, key=lambda row: (len(row['name']), row['name']))
    contain = [row for row in places if text in row['name']]
    if contain:
        return sorted(contain, key=lambda row: (len(row['name']), row['name']))
    if text.isdigit():
        city_id = int(text)
        return [row for row in places if row.get('city_id') == city_id]
    return []


def world_xy(row, world=WORLD):
    point = row.get('world_xy_raw')
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    if not all(type(value) is int for value in point):
        return None
    if not (0 <= point[0] < world[0] and 0 <= point[1] < world[1]):
        return None
    return (point[0], point[1])


def object_key(kind, row):
    field = {'城关': 'city_id', '建筑': 'object_id_candidate', '陷阱': 'trap_id', '部队': 'unit_id'}[kind]
    return (kind, row.get('type'), row.get(field))


def live_objects(state):
    if not state:
        return []
    entities = state.get('entities') or {}
    rows = []
    for kind, source in (
        ('城关', 'cities_and_barriers'),
        ('建筑', 'production_buildings'),
        ('陷阱', 'traps'),
        ('部队', 'field_units'),
    ):
        for row in entities.get(source) or []:
            if world_xy(row):
                rows.append((kind, row))
    return rows


def box_from_corners(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def in_world_box(xy, box, pad=0.55):
    if not xy or not box or len(box) != 4:
        return False
    x, y = xy[0] + 0.5, xy[1] + 0.5
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def units_in_view(state, box, war_only=False):
    rows = []
    for kind, row in live_objects(state):
        if kind != '部队' or not show_overlay(state, kind, row, war_only):
            continue
        if in_world_box(world_xy(row), box):
            rows.append(row)
    return rows


def sort_view_units(state, rows, center):
    from force_relations import at_war
    from player_view import player_id
    own = player_id(state)
    cx, cy = center if center else DEFAULT_CENTER

    def key(row):
        xy = world_xy(row) or (0, 0)
        owner = row.get('owner_raw')
        rank = 0 if owner == own else 1 if at_war(state, owner) else 2
        return (rank, (xy[0] + 0.5 - cx) ** 2 + (xy[1] + 0.5 - cy) ** 2, row.get('unit_id') or 0)

    return sorted(rows, key=key)


def view_unit_line(state, row):
    names = {force.get('force_id'): force.get('name') or '?'
             for force in (state or {}).get('entities', {}).get('lords') or []}
    owner = names.get(row.get('owner_raw'), '?')
    soldiers = row.get('soldiers_candidate')
    troop = f'{soldiers:,}' if type(soldiers) is int else '?'
    return f"{owner} · {object_label(state, '部队', row)} · 兵{troop}"


def show_kind_at_zoom(kind, zoom):
    if kind in ('建筑', '陷阱', 'production_buildings', 'traps') and float(zoom) < DETAIL_ZOOM:
        return False
    return True


def show_overlay(state, kind, row, war_only):
    if not war_only:
        return True
    from force_relations import at_war
    from player_view import player_id
    owner = row.get('owner_raw')
    own = player_id(state)
    return owner == own or at_war(state, owner)


def opponent_brief(state):
    if not state:
        return '尚无采集。进入对局后叠城关、建筑、部队、陷阱。'
    from force_relations import at_war
    from player_view import player_id
    if player_id(state) is None:
        return '我方身份未确认，交战高亮暂不可用。已采集对象仍会叠在图上。'
    wars = [force for force in state.get('entities', {}).get('lords', []) if at_war(state, force.get('force_id'))]
    units = [row for kind, row in live_objects(state) if kind == '部队' and at_war(state, row.get('owner_raw'))]
    cities = [row for kind, row in live_objects(state) if kind == '城关' and at_war(state, row.get('owner_raw'))]
    if not wars:
        return '当前没有标记为「与我军战争」的势力。图上仍显示全部已采集对象。'
    names = '、'.join(force.get('name') or f"#{force.get('force_id')}" for force in wars)
    return f'交战：{names} · 部队 {len(units)} · 城关 {len(cities)}'


def object_label(state, kind, row):
    if kind == '城关':
        return row.get('name') or f"城关 #{row.get('city_id')}"
    if kind == '建筑':
        return {'parade_ground': '练兵所', 'horse_farm': '牧场', 'bow_studio': '弓工坊'}.get(row.get('type'), '建筑')
    if kind == '陷阱':
        return row.get('trap_kind') or '陷阱'
    if kind == '部队':
        from map_unit_labels import unit_label
        return unit_label(state, row)
    return kind


CITY_VISION = 3  # 普通城：四邻接最短步数 3（原作 0x46a2a5）
CAPITAL_VISION = 5
BARRIER_VISION = 1


def tile_axes(x, y):
    """Offset rows -> square tile axes; one step projects to (±48, 24)."""
    return x + (y + 1) // 2, -x + y // 2


def vision_radius(state, row):
    kind = row.get('type')
    if kind == 'barrier':
        return BARRIER_VISION
    if kind not in (None, 'city'):
        return 0
    if is_capital(state, row):
        return CAPITAL_VISION
    return CITY_VISION


def vision_cells(center, radius=CITY_VISION, world=WORLD):
    """Original four-neighbour range: 1 + 2*r*(r+1) cells before clipping.

    Verified against SANPK 0x46a2a5. In tile axes this is Manhattan distance,
    not Chebyshev; diagonally skipping across a corner costs two steps.
    """
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        return []
    if not all(type(value) is int for value in center):
        return []
    if type(radius) is not int or radius < 0:
        return []
    cu, cv = tile_axes(*center)
    cells = []
    for u in range(cu - radius, cu + radius + 1):
        reach = radius - abs(u - cu)
        for v in range(cv - reach, cv + reach + 1):
            y = u + v
            x = (u - v) // 2
            if 0 <= x < world[0] and 0 <= y < world[1]:
                cells.append((x, y))
    return sorted(cells, key=lambda cell: (cell[1], cell[0]))


def vision_overlay_cells(state, war_only=False):
    """Owned cities and barriers: square-tile vision in force color. Not barracks."""
    owned = {}
    centers = set()
    for row in city_sites(state):
        if not assigned_owner(row.get('owner_raw')):
            continue
        radius = vision_radius(state, row)
        if radius <= 0:
            continue
        if not show_overlay(state, '城关', row, war_only):
            continue
        xy = world_xy(row)
        if xy is None:
            continue
        centers.add(xy)
        owner = row.get('owner_raw')
        for cell in vision_cells(xy, radius):
            owned.setdefault(cell, owner)
    return [{'cell': cell, 'owner_raw': owner, 'center': cell in centers} for cell, owner in owned.items()]


def cell_diamond(wx, wy):
    """One SanInet.mbm walkable cell: 96×48 2:1 rhombus centered on world_pixel."""
    px, py = world_pixel(wx, wy)
    return ((px - 48, py), (px, py - 24), (px + 48, py), (px, py + 24))


def _mbm_to_image(px, py, box, size):
    left, top, right, bottom = box
    width, height = size
    return (
        (px - left) * width / max(1, right - left),
        (py - top) * height / max(1, bottom - top),
    )


def overlay_force_diamonds(image, diamonds, alpha=78, mbm_box=None):
    """Fill terrain rhombi, then draw each shared grid edge once."""
    from PIL import Image, ImageDraw
    if image is None or not diamonds:
        return image
    base = image.convert('RGBA')
    veil = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(veil)
    size = base.size
    edges = {}
    for item in diamonds:
        rgb = item.get('rgb')
        if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
            continue
        if any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
            continue
        cell = item.get('cell')
        if cell is not None and len(cell) == 2:
            points = cell_diamond(*cell)
        else:
            points = item.get('points') or ()
        if len(points) < 3:
            continue
        if mbm_box is not None:
            xy = [_mbm_to_image(px, py, mbm_box, size) for px, py in points]
        else:
            xy = list(points)
        xy = [(int(round(x)), int(round(y))) for x, y in xy]
        if item.get('alpha') is not None:
            fill_a = min(170, max(20, int(item['alpha'])))
        else:
            fill_a = min(96, max(36, int(alpha) - (0 if item.get('center') else 10)))
        draw.polygon(xy, fill=(*rgb, fill_a))
        edge_rgba = item.get('edge') or (245, 235, 200, 145)
        for a, b in zip(xy, xy[1:] + xy[:1]):
            edges[tuple(sorted((a, b)))] = tuple(edge_rgba)
    # Draw after all fills so a neighbour cannot erase its shared boundary.
    for edge, color in sorted(edges.items()):
        draw.line(edge, fill=color, width=1)
    return Image.alpha_composite(base, veil)


def paint_mbm_vision(terrain, box, dest_w, dest_h, items, alpha=78):
    """Project MBM tile corners onto the resized terrain; keep grid lines one pixel.

    The resized image always represents `box`, including the margin outside
    SanInet.mbm. City sprites use that same box. Clipping the mip to the
    file and stretching it to the window pulls the diamonds off the cities
    once the view is zoomed out.
    """
    dest_w = max(1, int(dest_w))
    dest_h = max(1, int(dest_h))
    if terrain is None:
        return None
    image = terrain.crop_to(box, dest_w, dest_h)
    if not items or image is None:
        return image
    left, top, right, bottom = map(int, box)
    return overlay_force_diamonds(image, items, alpha=alpha, mbm_box=(left, top, right, bottom))


def sprite_size(kind, zoom, scale=None):
    city = kind in ('城关', 'city', 'cities_and_barriers', 'barrier')
    if float(zoom) < SWITCH_ZOOM or scale is None:
        return 22 if city else 16
    frac = 0.82 if city else 0.62
    return max(28, min(120, int(96 * float(scale) * frac)))


def nearest_city(point, cities, max_cells=1.6):
    x, y = point
    best = None
    best_d = max_cells
    for city in cities:
        cx, cy = city['world_xy']
        distance = max(abs(cx + 0.5 - x), abs(cy + 0.5 - y))
        if distance <= best_d:
            best, best_d = city, distance
    return best


def assigned_owner(owner):
    return type(owner) is int and 0 <= owner < 22


def city_sites(state, world=WORLD):
    rows = []
    if not state:
        return rows
    for row in (state.get('entities') or {}).get('cities_and_barriers') or []:
        if type(row.get('city_id')) is not int or world_xy(row, world) is None:
            continue
        rows.append(row)
    return rows


def supply_lines(state, edges=None):
    if edges is None:
        from city_roads import load_road_edges
        edges = load_road_edges()
    cities = {row.get('city_id'): row for row in city_sites(state)}
    lines = []
    for edge in edges:
        left = cities.get(edge.get('a'))
        right = cities.get(edge.get('b'))
        path = edge.get('path')
        if left is None or right is None or not isinstance(path, list) or len(path) < 2:
            continue
        if any(not isinstance(point, (list, tuple)) or len(point) != 2 for point in path):
            continue
        owner = left.get('owner_raw')
        same = assigned_owner(owner) and owner == right.get('owner_raw')
        lines.append({
            'path': [tuple(point) for point in path],
            'a_xy': world_xy(left),
            'b_xy': world_xy(right),
            'a_id': left.get('city_id'),
            'b_id': right.get('city_id'),
            'owner_raw': owner if same else None,
            'same_owner': same,
        })
    return lines


def capital_marks(state):
    marks = []
    if not state:
        return marks
    cities = {row.get('city_id'): row for row in city_sites(state)}
    for force in (state.get('entities') or {}).get('lords') or []:
        city = cities.get(force.get('capital_city_id'))
        if city is None:
            continue
        xy = world_xy(city)
        if xy is None:
            continue
        marks.append({
            'force_id': force.get('force_id'),
            'force_name': force.get('name') or f"#{force.get('force_id')}",
            'city_id': city.get('city_id'),
            'city_name': city.get('name') or f"#{city.get('city_id')}",
            'world_xy': xy,
            'owner_raw': city.get('owner_raw'),
        })
    return marks


def is_capital(state, row):
    if type(row.get('city_id')) is not int or not state:
        return False
    return any(force.get('capital_city_id') == row.get('city_id') for force in (state.get('entities') or {}).get('lords') or [])
