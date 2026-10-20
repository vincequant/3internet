"""Order and captions for paging one force's field units. Read-only."""
from panorama_model import MIN_ZOOM, live_objects, object_label, view_unit_line, world_xy


def force_field_units(state, force_id):
    if force_id is None:
        return []
    rows = []
    for kind, row in live_objects(state or {}):
        if kind == '部队' and row.get('owner_raw') == force_id:
            rows.append(row)
    return rows


def unit_page_index(units, record):
    if not record:
        return 0
    want = record.get('unit_id')
    for index, row in enumerate(units):
        if row.get('unit_id') == want:
            return index
    return 0


def step_index(count, index, delta):
    if count <= 0:
        return 0
    return (int(index) + int(delta)) % count


CITY_LOCATOR_ZOOM = 6.0
UNIT_TOUR_ZOOM = MIN_ZOOM


def retained_locator_zoom(current_zoom, keep_zoom, default=UNIT_TOUR_ZOOM):
    if keep_zoom and current_zoom:
        return float(current_zoom)
    return float(default)


def page_key_delta(keysym):
    if keysym == 'Right':
        return 1
    if keysym == 'Left':
        return -1
    return 0


def tour_caption(state, units, index):
    if not units:
        return '该势力本帧无出征部队'
    index = max(0, min(index, len(units) - 1))
    row = units[index]
    xy = world_xy(row)
    coord = f'({xy[0]},{xy[1]})' if xy else '坐标未解析'
    line = view_unit_line(state, row)
    return f'{index + 1}/{len(units)}  {line}  {coord}'


def tour_title(state, units, index):
    if not units:
        return '势力部队定位'
    row = units[max(0, min(index, len(units) - 1))]
    names = {force.get('force_id'): force.get('name') or '?'
             for force in (state or {}).get('entities', {}).get('lords') or []}
    owner = names.get(row.get('owner_raw'), '势力')
    return f'{owner}部队定位 · {index + 1}/{len(units)} · {object_label(state, "部队", row)}'
