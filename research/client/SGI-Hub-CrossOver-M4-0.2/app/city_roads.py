"""Static MBM road polylines between cities. Read-only; not an engine cut-supply table."""
import json
from collections import deque
from functools import lru_cache
from pathlib import Path

from tactical_terrain import Terrain, world_pixel

APP = Path(__file__).resolve().parent
ROADS_PATH = APP / 'city_roads.json'
SCALE = 2
IDENTITY = 'SanInet.mbm-road-follow-2'


def mbm_to_world(px, py):
    y = (py - 24) / 24.0
    x = (px - 48 - 48 * (y % 2)) / 96.0
    return (x, y)


def world_pixel_f(x, y):
    return (48 + 96 * x + 48 * (y % 2), 24 + 24 * y)


def rdp(points, epsilon):
    if len(points) <= 2:
        return list(points)
    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    best_i, best_d = 0, 0.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        dist = abs(dy * (px - start[0]) - dx * (py - start[1])) / length
        if dist > best_d:
            best_i, best_d = i, dist
    if best_d <= epsilon:
        return [start, end]
    return rdp(points[:best_i + 1], epsilon)[:-1] + rdp(points[best_i:], epsilon)


def road_indices(palette):
    chosen = set()
    for index in range(256):
        red, green, blue = palette[index * 3:index * 3 + 3]
        if red >= 215 and green >= 200 and 130 <= blue <= 220 and abs(red - green) <= 35 and (red + green) / 2 - blue >= 12 and green <= red + 15:
            chosen.add(index)
    return chosen


def _mask(terrain):
    road = road_indices(terrain.palette)
    width, height = 9744 // SCALE, 4872 // SCALE
    mask = [bytearray(width) for _ in range(height)]
    data = terrain.data
    for tile_y in range(203):
        for tile_x in range(203):
            block = data[(tile_y * 203 + tile_x) * 1152:(tile_y * 203 + tile_x) * 1152 + 1152]
            for raw_y in range(24):
                row = block[raw_y * 48:(raw_y + 1) * 48]
                pixel_y = tile_y * 24 + (23 - raw_y)
                my = pixel_y // SCALE
                if my >= height:
                    continue
                for raw_x, index in enumerate(row):
                    if index in road:
                        mx = (tile_x * 48 + raw_x) // SCALE
                        if mx < width:
                            mask[my][mx] = 1
    return mask, width, height


def _dilate(mask, width, height):
    out = [bytearray(row) for row in mask]
    for y, row in enumerate(mask):
        for x, bit in enumerate(row):
            if not bit:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < width and 0 <= yy < height:
                        out[yy][xx] = 1
    return out


def _shortest(mask, width, height, start, goal):
    if start is None or goal is None:
        return None
    if start == goal:
        return [start]
    queue = deque([start])
    prev = {start: None}
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    while queue:
        x, y = queue.popleft()
        for dx, dy in steps:
            nxt = (x + dx, y + dy)
            if not (0 <= nxt[0] < width and 0 <= nxt[1] < height) or not mask[nxt[1]][nxt[0]] or nxt in prev:
                continue
            prev[nxt] = (x, y)
            if nxt == goal:
                return list(reversed(_walk(prev, nxt)))
            queue.append(nxt)
    return None


def _snap(mask, width, height, mx, my, radius=40):
    if 0 <= mx < width and 0 <= my < height and mask[my][mx]:
        return (mx, my)
    for rad in range(1, radius + 1):
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                if max(abs(dx), abs(dy)) != rad:
                    continue
                xx, yy = mx + dx, my + dy
                if 0 <= xx < width and 0 <= yy < height and mask[yy][xx]:
                    return (xx, yy)
    return None


def _walk(prev, point):
    path = []
    while point is not None:
        path.append(point)
        point = prev.get(point)
    return path


LBM_SIMPLIFY = 64


def _simplify_bucket(layer, zoom):
    if layer == 'lbm':
        return 'lbm'
    if zoom is None or float(zoom) >= 3.0:
        return 'mbm'
    if float(zoom) >= 2.0:
        return 'mbm-2'
    if float(zoom) >= 1.0:
        return 'mbm-1'
    return 'mbm-0'


@lru_cache(maxsize=2048)
def _path_cached(points, bucket):
    if bucket == 'lbm':
        return tuple(rdp(points, LBM_SIMPLIFY))
    if bucket == 'mbm':
        return points
    epsilon = 16 if bucket == 'mbm-2' else 32 if bucket == 'mbm-1' else 64
    return tuple(rdp(points, epsilon))


def path_for_layer(path, layer, zoom=None):
    """National view flattens slight bends; close-up keeps the road pixels."""
    points = tuple((int(point[0]), int(point[1])) for point in path)
    return list(_path_cached(points, _simplify_bucket(layer, zoom)))


def stride(points, step):
    if len(points) <= 2 or step <= 1:
        return list(points)
    out = list(points[::step])
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def extract_road_edges(cities, terrain=None):
    terrain = terrain or Terrain()
    raw, width, height = _mask(terrain)
    mask = _dilate(raw, width, height)
    sites = []
    snaps = {}
    for city in cities:
        xy = city.get('world_xy_raw')
        if type(city.get('city_id')) is not int or not isinstance(xy, (list, tuple)) or len(xy) != 2:
            continue
        px, py = world_pixel(xy[0], xy[1])
        mx, my = px // SCALE, py // SCALE
        snap = _snap(raw, width, height, mx, my, radius=60) or _snap(mask, width, height, mx, my, radius=60)
        if snap:
            sites.append((city, snap))
            snaps[city['city_id']] = snap
    label = {}
    queue = deque()
    for city, snap in sites:
        if snap in label:
            continue
        label[snap] = city['city_id']
        queue.append(snap)
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    while queue:
        x, y = queue.popleft()
        owner = label[(x, y)]
        for dx, dy in steps:
            xx, yy = x + dx, y + dy
            if not (0 <= xx < width and 0 <= yy < height) or not mask[yy][xx] or (xx, yy) in label:
                continue
            label[(xx, yy)] = owner
            queue.append((xx, yy))
    meetings = set()
    for (x, y), left in label.items():
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            right = label.get((x + dx, y + dy))
            if right is None or right == left:
                continue
            meetings.add((left, right) if left < right else (right, left))
    id_to_city = {city['city_id']: city for city, _ in sites}
    edges = []
    for left, right in sorted(meetings):
        if left not in id_to_city or right not in id_to_city:
            continue
        path = _shortest(raw, width, height, snaps[left], snaps[right])
        if path is None:
            path = _shortest(mask, width, height, snaps[left], snaps[right])
        if not path:
            continue
        pixels = stride(
            [(mx * SCALE + 1, my * SCALE + 1) for mx, my in path],
            2,
        )
        edges.append({
            'a': left,
            'b': right,
            'a_name': id_to_city[left].get('name'),
            'b_name': id_to_city[right].get('name'),
            'path': [list(point) for point in pixels],
        })
    edges.sort(key=lambda row: (row['a'], row['b']))
    return {
        'identity': IDENTITY,
        'scale': SCALE,
        'edges': edges,
    }


@lru_cache(maxsize=1)
def load_road_edges():
    if not ROADS_PATH.is_file():
        return []
    try:
        doc = json.loads(ROADS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    edges = doc.get('edges') if isinstance(doc, dict) else None
    if not isinstance(edges, list):
        return []
    return edges


def write_road_edges(doc, path=None):
    path = Path(path or ROADS_PATH)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    load_road_edges.cache_clear()
    return path
