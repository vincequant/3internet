"""P53 read-only unit inspection, independent of the game GUI and bridge cache.

Offsets come from the existing bridge plus bounded SANPK 3.5 consumers/setters.
No target calls, target writes, orders, or network APIs. Unknowns stay unknown.
"""
import copy
import struct

UNIT_TYPES = {
    0x508678: '战略部队', 0x508878: '步兵', 0x508a60: '强化步兵',
    0x508c48: '重装步兵', 0x508e30: '骑兵', 0x509018: '强化骑兵',
    0x509200: '铁骑兵', 0x5093e8: '弓兵', 0x5095d0: '强弓兵',
    0x5097b8: '重装弓兵', 0x5099d0: '运输兵', 0x50bdb8: '游荡部队',
}
CORE_VT, VIEW_VT, GENERAL_VT = 0x5053c0, 0x50b730, 0x5056f0
UNIT_SIZE = 168
FIELDS = {
    'soldiers': ('兵力', 0x15, '<I', 100000, '0x477444..0x47746c clamps 0..100000'),
    'rice': ('兵粮', 0x19, '<I', 100000, '0x4779e9..0x477a49 clamps 0..100000'),
    'morale': ('士气', 0x1d, '<B', 100, '0x47750e setter; 0x477d05 consumer; transport max50'),
    'training': ('训练/兵装度', 0x29, '<B', 100,
                 '0x47a9f8/0x47b1f4 coefficient input; current 0x4776b3 bypasses clamp'),
    'move_remaining': ('剩余移动点', 0x20, '<B', 255, '0x430366; NOT full speed'),
}
FIELD_NAMES = ('identity',) + tuple(FIELDS) + ('combat', 'unknown')


def exact(read, address, size):
    if (type(address) is not int or not 0 < size <= 65536
            or not 0x10000 <= address <= 0xffffffff-size):
        raise ValueError('invalid read span')
    data = read(address, size)
    if data is None or len(data) != size:
        raise ValueError('unreadable memory at ' + hex(address))
    return data


def number(read, address):
    return struct.unpack('<I', exact(read, address, 4))[0]


def dimensions_ok(dimensions):
    return (len(dimensions) == 4 and tuple(dimensions[:2]) == (101, 202)
            and all(type(v) is int and 4 <= v <= 256 and v % 2 == 0
                    for v in dimensions[2:]))


def cdiv(a, b):
    """x86 IDIV truncates toward zero (not Python's negative floor division)."""
    return (abs(a) // b) * (-1 if a < 0 else 1)


def native_tile(world, dimensions):
    """Exact 0x498591 diamond test, including equality and edge clamping.

    0x498694 is only the coarse rectangular row conversion. Using it alone
    mis-selects points around the sloping edges of the visible diamonds.
    """
    if not dimensions_ok(dimensions):
        raise ValueError('unsupported projection')
    width, height, tw, th = dimensions
    wx, wy = world
    if any(type(v) is not int or not -0x100000 <= v <= 0x100000 for v in world):
        raise ValueError('unbounded world point')
    qx, qy = cdiv(wx, tw//2), cdiv(wy, th//2)
    rx, ry = wx - qx*(tw//2), wy - qy*(th//2)
    x, y = cdiv(qx, 2), qy
    slope = cdiv(th*rx, tw)
    if qx & 1:
        if ry < (th//2 - slope if qy & 1 else slope):
            y -= 1
    elif qy & 1:
        if ry < slope:
            y -= 1
        else:
            x -= 1
    elif ry < th//2 - slope:
        x -= 1
        y -= 1
    return [min(max(x, 0), width-1), min(max(y, 0), height-1)]


def screen_to_tile(point, origin, dimensions, client_size):
    if (any(type(v) is not int for v in (*point, *origin, *client_size))
            or not all(0 <= v <= 65535 for v in origin)
            or not all(0 < v <= 65535 for v in client_size)
            or not all(0 <= p < s for p, s in zip(point, client_size))):
        raise ValueError('point outside the map client')
    world = [p+o for p, o in zip(point, origin)]
    if not dimensions_ok(dimensions):
        raise ValueError('unsupported projection')
    w, h, tw, th = dimensions
    if not (0 <= world[0] < (w+1)*tw and 0 <= world[1] < (h+1)*th//2):
        raise ValueError('point outside projection extent')
    return native_tile(world, dimensions)


def decode_unit(address, raw):
    if len(raw) != UNIT_SIZE:
        raise ValueError('unit record length')
    vt, x, y, owner, uid = struct.unpack_from('<IhhHH', raw)
    if vt not in UNIT_TYPES or not (0 <= x < 101 and 0 <= y < 202):
        raise ValueError('unsupported unit class/coordinates')
    values, originals = {}, {}
    for key, (_, offset, fmt, maximum, _) in FIELDS.items():
        value = struct.unpack_from(fmt, raw, offset)[0]
        originals[key] = value
        # Only transport overrides +0x9c to 0x47c102 (50); wandering uses 100.
        if key == 'morale' and vt == 0x5099d0:
            maximum = 50
        values[key] = value if value <= maximum else None
    return dict(address=hex(address), vtable=hex(vt), unit_kind=UNIT_TYPES[vt],
                unit_id=uid, owner_raw=owner, world_xy_raw=[x, y],
                general_ids=[None if n == 65535 else n for n in struct.unpack_from('<3H', raw, 0xf)],
                values=values, raw_values=originals, raw_unknown={'1e': raw[0x1e], '1f': raw[0x1f]},
                raw_hex=raw.hex(), verification='static_and_historical_samples; new_shadow_GUI_pending')


def walk(read, core, offset, limit):
    """Collector's doubly linked container contract, without a page cache."""
    address = core + offset
    header = exact(read, address, 28)
    head, tail, count = struct.unpack_from('<III', header, 4)
    if count > limit:
        raise ValueError('container safety bound')
    node, previous, seen, objects, guards = head, 0, set(), [], [(address, header)]
    for _ in range(count):
        if node < 0x10000 or node in seen:
            raise ValueError('short/cyclic list')
        seen.add(node)
        raw = exact(read, node, 12)
        nxt, back, obj = struct.unpack('<III', raw)
        if back != previous or obj < 0x10000 or obj in objects:
            raise ValueError('invalid backlink/object identity')
        guards.append((node, raw)); objects.append(obj)
        previous, node = node, nxt
    if node or previous != tail:
        raise ValueError('container count/tail mismatch')
    return objects, guards


def inspect_click(read, click, enrich=None):
    """No owner/faction filter. Co-located units are returned together.

    Root/clock/list/identities/selected records are double-read. This is a
    bounded coherent observation, not an atomic whole-world or click-time dump.
    """
    core, view, doc = (click[k] for k in ('core', 'view', 'document'))
    if (number(read, core) != CORE_VT or number(read, doc) != 0x504d40 or number(read, view) != VIEW_VT
            or number(read, 0x53b930) != view or number(read, 0x53bb30) != core
            or number(read, view+0x3c) != doc or doc+0x912 != core
            or number(read, view+0x1c) != click['hwnd']):
        raise ValueError('view/document/core/window binding changed')
    roots = [(a, exact(read, a, n)) for a, n in (
        (core, 4), (doc, 4), (view, 4), (0x53b930, 4), (0x53bb30, 4),
        (view+0x3c, 4), (view+0x1c, 4), (doc+0xf22, 16), (core+0x4d0, 12))]
    if (list(struct.unpack('<4i', roots[-2][1])) != click['dimensions']
            or roots[-1][1].hex() != click['clock_hex']):
        raise ValueError('projection/round changed since click')
    tile = screen_to_tile(click['point'], click['origin'], click['dimensions'], click['client_size'])
    objects, guards = walk(read, core, 0x534, 4096)
    units, identities = [], []
    for obj in objects:
        raw = exact(read, obj, 12); identities.append((obj, raw))
        vt, x, y = struct.unpack_from('<Ihh', raw)
        if vt not in UNIT_TYPES:
            raise ValueError('unknown unit vtable; inspection unavailable')
        if [x, y] == tile:
            if len(units) >= 32:
                raise ValueError('too many units in tile')
            full = exact(read, obj, UNIT_SIZE)
            if full[:12] != raw:
                raise ValueError('unit changed while reading')
            row = decode_unit(obj, full)
            units.append(row); guards.append((obj, full))
    # Only read generals needed by hit units; still validate the complete list.
    generals = []
    if enrich is not None and units:
        ids = {i for u in units for i in u['general_ids'] if i is not None}
        general_objects, more = walk(read, core, 0x514, 2048); guards.extend(more)
        found = set()
        for obj in general_objects:
            ident = exact(read, obj, 12); identities.append((obj, ident))
            if struct.unpack_from('<I', ident)[0] != GENERAL_VT:
                raise ValueError('general vtable mismatch')
            gid = struct.unpack_from('<H', ident, 10)[0]
            if gid not in ids:
                continue
            if gid in found:
                raise ValueError('duplicate general identity')
            found.add(gid); raw = exact(read, obj, 0x46)
            if raw[:12] != ident:
                raise ValueError('general changed while reading')
            generals.append(dict(general_id_raw=gid, owner_raw=struct.unpack_from('<H', raw, 8)[0],
                status_code=struct.unpack_from('<H', raw, 0x21)[0],
                attributes=dict(zip(('lead','war','intel','pol','cha'), raw[0x25:0x2a])),
                combat_modifier_flags_word=struct.unpack_from('<H', raw, 0x44)[0],
                raw_hex=raw.hex()))
            guards.append((obj, raw))
        terrain_guards = []
        grid = exact(read, core+0x5fc, 28); terrain_guards.append((core+0x5fc, grid))
        data = struct.unpack_from('<I', grid, 4)[0]
        width, height = struct.unpack_from('<II', grid, 20)
        if (width, height) == (101, 202) and data >= 0x10000:
            cellptr_addr = data + 4*(tile[0]*height+tile[1])
            cellptr = exact(read, cellptr_addr, 4); terrain_guards.append((cellptr_addr, cellptr))
            cell = struct.unpack('<I', cellptr)[0]
            if cell >= 0x10000:
                terrain = exact(read, cell+10, 1); terrain_guards.append((cell+10, terrain))
                if terrain[0] <= 29:
                    for row in units:
                        row.update(terrain_type_raw=terrain[0], on_water=terrain[0] in (4, 6))
        guards.extend(terrain_guards)
        enrich_rows(units, generals, enrich)
    # No persistent cache: each guard is actually read again from the process.
    if any(exact(read, a, len(raw)) != raw for a, raw in roots+guards+identities):
        raise ValueError('world changed during inspection; click again')
    return dict(schema='p53-unit-observation-1', tile=tile, units=units, generals=generals,
                click=copy.deepcopy(click), coherent=True, local_preview=False,
                limitation='double-read bounded observation; not atomic click-time state')


def enrich_rows(units, generals, enrich):
    # Reuse the verified bridge's pure rules, not native game function calls.
    for row in units:
        row.update(soldiers_candidate=row['values']['soldiers'], rice_candidate=row['values']['rice'],
                   raw_1d=row['raw_values']['morale'], armament_degree_raw=row['raw_values']['training'],
                   move_remaining_raw=row['raw_values']['move_remaining'])
    state = dict(build_sha256='df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea',
                 entities=dict(field_units=units, generals=generals))
    enrich(state)


def preview(observation, overrides, enrich=None):
    """Change the panel's private byte copy only. No read/write callback exists."""
    if len(observation['units']) != 1:
        raise ValueError('preview requires exactly one hit unit')
    if not overrides:
        return copy.deepcopy(observation)
    result = copy.deepcopy(observation); row = result['units'][0]
    raw = bytearray.fromhex(row['raw_hex'])
    for key, value in overrides.items():
        if key not in FIELDS or type(value) is not int:
            raise ValueError('unsupported preview field')
        _, offset, fmt, maximum, _ = FIELDS[key]
        if key == 'morale' and int(row['vtable'], 16) == 0x5099d0:
            maximum = 50
        if not 0 <= value <= maximum:
            raise ValueError('preview value outside verified range')
        struct.pack_into(fmt, raw, offset, value)
    row.update(decode_unit(int(row['address'],16), bytes(raw)))
    if enrich is not None:
        enrich_rows([row], result['generals'], enrich)
    result.update(local_preview=True, preview_overrides=dict(overrides),
                  source_units=copy.deepcopy(observation['units']))
    return result


def parse_preview(text):
    result = {}
    if not text.strip():
        return result
    for token in text.split(','):
        key, value = token.strip().split('=')
        key = key.strip()
        if key in result:
            raise ValueError('duplicate preview field')
        result[key] = int(value.strip(), 10)
    return result


def panel_text(observation, fields=('identity',)):
    if set(fields) - set(FIELD_NAMES):
        raise ValueError('unknown display element')
    if observation.get('error'):
        return '观察不可用：'+observation['error']+'\r\n没有沿用旧数值；请重新点击。'
    lines = ['风夜 · 部队只读信息', '格子 %s · 命中 %s 支（不按归属过滤）' %
             (observation['tile'], len(observation['units']))]
    if observation.get('local_preview'):
        lines += ['【本地预览】只改面板副本；主机状态更新会覆盖；不发送指令。']
    else:
        lines += ['来源：当前客户端只读观察；新局目视核对尚未完成。']
    if not observation['units']:
        lines.append('此格未读到部队；未代选邻格。')
    for row in observation['units']:
        lines += ['', '#%s · %s · 势力原始ID %s' %
                  (row['unit_id'], row['unit_kind'], row['owner_raw']),
                  '坐标 %s · 武将ID %s' % (row['world_xy_raw'], row['general_ids'])]
        for key in fields:
            if key in FIELDS:
                label = FIELDS[key][0]; value = row['values'][key]
                lines.append('%s：%s' % (label, value if value is not None else
                                         '未知（原始值 %s 越界）' % row['raw_values'][key]))
            elif key == 'combat':
                for label, name in (('编成基本能力','basic_combat_power'),
                                    ('当前攻击指数（中间量，非伤害）','native_attack_index'),
                                    ('陆地满士气攻击指数','native_attack_index_full_morale')):
                    value = row.get(name)
                    lines.append('%s：%s' % (label, value if value is not None else '未知'))
                lines.append('防御/完整伤害：未定位独立属性字段，保持未知')
            elif key == 'unknown':
                lines.append('+1e/+1f 原始字节：%s（语义未定，不叫训练/速度）' % row['raw_unknown'])
    return '\r\n'.join(lines)
