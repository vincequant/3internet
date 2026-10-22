"""Scenario atlases the Hub can draw.

City and unit coordinates stay in the scenario's own grid. big_origin only
records how a regional grid sits on the 101×202 atlas; nothing rewrites
world_xy_raw from it. South and 中原 have no verified origin.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parent

# Pixel size of an MBM is (96*width+48, 24*height+24). The SBM minimap is (3*width, height).
MAPS = (
    {
        'id': 'china',
        'name': '大地图',
        'width': 101,
        'height': 202,
        'mbm': 'SanInet.mbm',
        'overview': 'SanInet.lbm',
        'pixel': (9744, 4872),
        'big_origin': (0, 0),
    },
    {
        'id': 'southeast',
        'name': '东南',
        'width': 69,
        'height': 106,
        'mbm': 'SEast.mbm',
        'overview': 'SEast.sbm',
        'pixel': (6672, 2568),
        'big_origin': (32, 96),
    },
    {
        'id': 'south',
        'name': '南方',
        'width': 101,
        'height': 106,
        'mbm': 'South.mbm',
        'overview': 'South.sbm',
        'pixel': (9744, 2568),
        'big_origin': None,
    },
    {
        'id': 'central',
        'name': '中原',
        'width': 55,
        'height': 127,
        'mbm': 'Chugen.mbm',
        'overview': 'Chugen.sbm',
        'pixel': (5328, 3072),
        'big_origin': None,
    },
)

_BY_SIZE = {(item['width'], item['height']): item for item in MAPS}
_BY_ID = {item['id']: item for item in MAPS}
_PALETTE = None


def by_size(width, height):
    try:
        return _BY_SIZE.get((int(width), int(height)))
    except (TypeError, ValueError):
        return None


def by_id(map_id):
    return _BY_ID.get(map_id)


def file_for(spec, kind):
    """Return the MBM or overview file, preferring copies shipped with the Hub."""
    name = spec['mbm'] if kind == 'mbm' else spec['overview']
    folders = [
        APP / 'assets' / 'maps',
        APP / 'assets',
        Path.home() / 'Library/Application Support/SGI-Wine/prefix-sikarugir10/drive_c/sgi/run-3.5/3I',
        Path.home() / 'Library/Application Support/CrossOver/Bottles/SanguoInternet/drive_c/sgi/run-3.5/3I',
        Path('D:/Coding/sanguo-internet/run-3.5/3I'),
    ]
    for folder in folders:
        path = folder / name
        if path.is_file():
            return path
    return None


def _palette_xy():
    global _PALETTE
    if _PALETTE is not None:
        return _PALETTE
    index = {}
    try:
        data = json.loads((APP / 'game_palette.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        _PALETTE = index
        return index
    for color in (data.get('colors') or {}).values():
        for sample in color.get('samples') or []:
            name = sample.get('city_name')
            xy = sample.get('world_xy')
            if name and name not in index and isinstance(xy, list) and len(xy) >= 2:
                index[name] = (int(xy[0]), int(xy[1]))
    _PALETTE = index
    return index


def _points(state):
    cities = ((state or {}).get('entities') or {}).get('cities_and_barriers') or []
    points = []
    for city in cities:
        xy = city.get('world_xy_raw')
        if not isinstance(xy, (list, tuple)) or len(xy) < 2:
            continue
        try:
            points.append((city.get('name'), int(xy[0]), int(xy[1])))
        except (TypeError, ValueError):
            continue
    return points


def match_cities(state):
    """Pick a map when several named cities share one verified big-map offset."""
    palette = _palette_xy()
    points = _points(state)
    deltas = []
    for name, x, y in points:
        big = palette.get(name)
        if big:
            deltas.append((big[0] - x, big[1] - y))
    if len(deltas) < 8 or len(set(deltas)) != 1:
        return None
    origin = deltas[0]
    for spec in MAPS:
        if spec['big_origin'] != origin:
            continue
        if all(0 <= x < spec['width'] and 0 <= y < spec['height'] for _, x, y in points):
            return spec
    return None


def identify_detail(state):
    """Return (map, source). Memory size wins. City names are the fallback."""
    state = state or {}
    published = state.get('scenario_map') if isinstance(state.get('scenario_map'), dict) else {}
    if published.get('known'):
        spec = by_size(published.get('width'), published.get('height'))
        if spec:
            return spec, 'memory'
    grid = state.get('terrain_grid') if isinstance(state.get('terrain_grid'), dict) else {}
    spec = by_size(grid.get('width'), grid.get('height'))
    if spec:
        return spec, 'memory'
    guessed = match_cities(state)
    if guessed:
        return guessed, 'cities'
    return _BY_ID['china'], 'default'


def identify(state):
    return identify_detail(state)[0]
