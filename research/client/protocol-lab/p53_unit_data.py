"""Typed, bounded reads and exact native map projection for the D inspector.

No ctypes, writes, game calls, window messages, or dependency on game selection.
The caller supplies an uncached read-only reader. Snapshots are double checked,
not claimed to be atomic snapshots of an entire running simulation.
"""
import hashlib
import struct
import time

from p53_hidden_draw_build import GROUPS

UNIT_TYPES = dict(zip(GROUPS['map-unit-sprites'][1], (
    '战略部队', '步兵', '强化步兵', '重装步兵', '骑兵', '强化骑兵',
    '铁骑兵', '弓兵', '强弓兵', '重装弓兵', '运输兵', '游荡部队')))
TRAP_TYPES = {0x50a0f0: '火计', 0x50a1a8: '落石', 0x50a260: '陷阱'}
STATUS = {0: '现役', 1: '在野', 2: '出阵', 3: '未登场', 4: '俘虏', 5: '死亡', 6: '负伤中'}


def exact(read, address, size):
    if type(address) is not int or not 0x10000 <= address <= 0xffffffff-size or not 0 < size <= 0x10000:
        raise ValueError('invalid read span')
    raw = read(address, size)
    if raw is None or len(raw) != size:
        raise ValueError('unreadable span at '+hex(address))
    return raw


def number(read, address, fmt='<I'):
    return struct.unpack(fmt, exact(read, address, struct.calcsize(fmt)))[0]


def text(read, pointer, limit=96):
    """Do not overread a valid short CString across a page boundary."""
    raw = bytearray()
    while len(raw) < limit:
        address = pointer+len(raw)
        count = min(16, limit-len(raw), 4096-(address & 4095))
        chunk = exact(read, address, count)
        if b'\0' in chunk:
            raw.extend(chunk.split(b'\0', 1)[0])
            return raw.decode('gbk', errors='strict')
        raw.extend(chunk)
    raise ValueError('unterminated GBK name')


def walk(read, core, offset, limit, keep):
    header = exact(read, core+offset, 28)
    head, tail, count = struct.unpack_from('<III', header, 4)
    if count > limit:
        raise ValueError('container limit at '+hex(offset))
    previous, node, seen, objects, guards = 0, head, set(), [], []
    for _ in range(count):
        if node in seen or not node:
            raise ValueError('cyclic/short entity list')
        seen.add(node)
        raw = exact(read, node, 12)
        nxt, back, obj = struct.unpack('<III', raw)
        if back != previous:
            raise ValueError('entity list backlink changed')
        guards.append((node, raw))
        value = keep(obj)
        if value is not None:
            objects.append(value)
        previous, node = node, nxt
    if node or previous != tail:
        raise ValueError('entity list tail/count changed')
    if exact(read, core+offset, 28) != header or any(exact(read, a, len(b)) != b for a, b in guards):
        raise ValueError('entity membership changed during read')
    return objects, dict(offset=hex(offset), count=count, header_hex=header.hex())


def context(read):
    core = number(read, 0x53bb30)
    view = number(read, 0x53b930)
    doc = core-0x912
    if (number(read, core) != 0x5053c0 or number(read, doc) != 0x504d40 or
            number(read, view) != 0x50b730 or number(read, view+0x3c) != doc):
        raise ValueError('game/core/view identity mismatch')
    width, height, tw, th = struct.unpack('<4i', exact(read, doc+0xf22, 16))
    if (not 1 <= width <= 2048 or not 1 <= height <= 4096 or
            any(v < 4 or v > 256 or v % 2 for v in (tw, th))):
        raise ValueError('unsupported map projection')
    origin = list(struct.unpack('<2i', exact(read, view+0x54, 8)))
    if min(origin) < 0:
        raise ValueError('negative viewport origin')
    return dict(core=core, document=doc, view=view, hwnd=number(read, view+0x1c),
                dimensions=[width, height, tw, th], origin=origin,
                viewport=list(struct.unpack('<2i', exact(read, view+0x64, 8))),
                mode=number(read, doc+0x68), phase=number(read, doc+0xdea, '<h'),
                modal=number(read, view+0x8da), widgets=number(read, view+0x806),
                clock=exact(read, core+0x4cc, 18).hex())


def geometry_key(value):
    return {key: value[key] for key in ('core', 'document', 'view', 'hwnd',
            'dimensions', 'origin', 'viewport', 'mode', 'phase', 'modal', 'widgets')}


def world_to_pixel(x, y, dimensions):
    """Original 4986dd tile origin, before camera subtraction (no game call)."""
    _, _, tw, th = dimensions
    return [tw*x + (tw//2 if y & 1 else 0), th*y//2]


def native_hit(px, py, dimensions, clamp=True):
    """Exact 498591 staggered-diamond hit calculation for nonnegative pixels.

    Using 498694's rectangular approximation would choose wrong units near
    diagonal tile boundaries. This port is compared against 498591 in Unicorn.
    """
    width, height, tw, th = dimensions
    if any(type(v) is not int for v in (px, py)) or min(px, py) < 0:
        return None
    halfw, halfh = tw//2, th//2
    ix, rx = divmod(px, halfw)
    iy, ry = divmod(py, halfh)
    x, y = ix//2, iy
    slope = th*rx//tw
    if ix & 1:
        threshold = halfh-slope if iy & 1 else slope
        if ry < threshold:
            y -= 1
    elif iy & 1:
        if ry >= slope:
            x -= 1
        else:
            y -= 1
    elif ry < halfh-slope:
        x -= 1; y -= 1
    if not clamp and not (0 <= x < width and 0 <= y < height):
        return None
    return [max(0, min(width-1, x)), max(0, min(height-1, y))]


def hit_units(snapshot, client_xy):
    ctx = snapshot['context']
    point = [client_xy[i]+ctx['origin'][i] for i in (0, 1)]
    cell = native_hit(*point, ctx['dimensions'], clamp=False)
    return [row for row in snapshot['units'] if row['world_xy_raw'] == cell]


def decode_unit(address, raw):
    if len(raw) != 168:
        raise ValueError('unit size mismatch')
    vt = struct.unpack_from('<I', raw)[0]
    if vt not in UNIT_TYPES:
        raise ValueError('unsupported unit class')
    ids = struct.unpack_from('<3H', raw, 0xf)
    return dict(address=address, vtable=hex(vt), kind=UNIT_TYPES[vt],
                unit_id=struct.unpack_from('<H', raw, 0xa)[0],
                owner_raw=struct.unpack_from('<H', raw, 8)[0],
                world_xy_raw=list(struct.unpack_from('<2h', raw, 4)),
                general_ids=[None if v == 65535 else v for v in ids],
                soldiers_candidate=struct.unpack_from('<I', raw, 0x15)[0],
                rice_candidate=struct.unpack_from('<I', raw, 0x19)[0],
                move_remaining_raw=raw[0x20], armament_degree_raw=raw[0x29],
                state_flags_raw=raw[0xd], raw_1d=raw[0x1d], raw_1e=raw[0x1e],
                order_type_raw=struct.unpack_from('<H', raw, 0x7e)[0],
                order_payload_raw=struct.unpack_from('<I', raw, 0x5e)[0],
                raw_hex=raw.hex(), sha256=hashlib.sha256(raw).hexdigest(),
                verification='static_layout; live_field_alignment_pending')


def capture_map(read):
    started = time.perf_counter(); ctx = context(read)
    core = ctx['core']
    def unit(obj):
        return decode_unit(obj, exact(read, obj, 168))
    units, unit_header = walk(read, core, 0x534, 4096, unit)
    def trap(obj):
        raw = exact(read, obj, 24); vt = struct.unpack_from('<I', raw)[0]
        if vt not in TRAP_TYPES:
            raise ValueError('unsupported trap class')
        return dict(address=obj, kind=TRAP_TYPES[vt],
                    world_xy_raw=list(struct.unpack_from('<2h', raw, 4)),
                    owner_raw=struct.unpack_from('<H', raw, 8)[0], raw_hex=raw.hex())
    traps, trap_header = walk(read, core, 0x5b4, 1024, trap)
    if geometry_key(context(read)) != geometry_key(ctx):
        raise ValueError('camera/phase changed during capture')
    return dict(schema='p53-unit-map-1', readonly=True, wall=time.time(),
                context=ctx, units=units, traps=traps,
                containers=[unit_header, trap_header],
                capture_ms=1000*(time.perf_counter()-started),
                consistency='membership/camera checked; mutable fields not globally atomic')


def inspect_unit(read, snapshot, selected):
    """Fresh membership/identity verification; never inspect an old raw pointer."""
    fresh = capture_map(read)
    ctx = fresh['context']; core = ctx['core']
    if geometry_key(ctx) != geometry_key(snapshot['context']):
        raise ValueError('viewport/phase changed; click again')
    rows = [row for row in fresh['units'] if (row['address'], row['unit_id'], row['owner_raw'], row['vtable']) ==
            (selected['address'], selected['unit_id'], selected['owner_raw'], selected['vtable'])]
    if len(rows) != 1 or rows[0]['world_xy_raw'] != selected['world_xy_raw']:
        raise ValueError('unit moved/disappeared/reused; click again')
    row = rows[0]; wanted = {v for v in row['general_ids'] if v is not None}
    generals = {}
    def general(obj):
        header = exact(read, obj, 24)
        if struct.unpack_from('<I', header)[0] != 0x5056f0:
            raise ValueError('general class mismatch')
        gid = struct.unpack_from('<H', header, 10)[0]
        if gid not in wanted:
            return None
        if gid in generals:
            raise ValueError('ambiguous general ID')
        raw = exact(read, obj, 96)
        names = [text(read, struct.unpack_from('<I', raw, offset)[0]) for offset in (12, 16, 20)]
        if exact(read, obj, 96) != raw:
            raise ValueError('general changed during capture')
        state = struct.unpack_from('<H', raw, 0x21)[0]
        value = dict(id=gid, address=obj, name=names[0]+names[1], courtesy_name=names[2],
                     portrait_id=struct.unpack_from('<h', raw, 28)[0],
                     soldiers=struct.unpack_from('<H', raw, 35)[0],
                     attributes=dict(zip(('统率', '武力', '智力', '政治', '魅力'), raw[37:42])),
                     skill_mask_raw=struct.unpack_from('<I', raw, 0x2a)[0],
                     status=STATUS.get(state, '未定状态'), status_raw=state,
                     city_id=struct.unpack_from('<h', raw, 0x34)[0],
                     raw_hex=raw.hex(), verification='existing_general_layout; GUI_alignment_pending')
        generals[gid] = value
        return value
    _, general_header = walk(read, core, 0x514, 2048, general)
    def named(obj, vt, kind):
        raw = exact(read, obj, 16)
        if struct.unpack_from('<I', raw)[0] not in vt:
            raise ValueError(kind+' class mismatch')
        oid = struct.unpack_from('<H', raw, 10 if kind == 'city' else 8)[0]
        pointer = struct.unpack_from('<I', raw, 12 if kind == 'city' else 10)[0]
        name = text(read, pointer)
        if exact(read, obj, 16) != raw:
            raise ValueError(kind+' identity changed')
        return oid, name
    forces, _ = walk(read, core, 0x4f4, 128, lambda a: named(a, {0x506660}, 'force'))
    cities, _ = walk(read, core, 0x554, 256, lambda a: named(a, {0x503688, 0x5037d0}, 'city'))
    if len(dict(forces)) != len(forces) or len(dict(cities)) != len(cities):
        raise ValueError('ambiguous force/city identity')
    city_names = dict(cities)
    for value in generals.values():
        value['city_name'] = city_names.get(value['city_id'])
    raw = bytes.fromhex(row['raw_hex'])
    if exact(read, row['address'], 168) != raw or geometry_key(context(read)) != geometry_key(ctx):
        raise ValueError('unit/viewport changed while reading attributes')
    return dict(schema='p53-unit-inspection-1', wall=time.time(), readonly=True,
                context=ctx, unit=dict(row, owner_name=dict(forces).get(row['owner_raw'])),
                generals=[generals.get(gid) if gid is not None else None for gid in row['general_ids']],
                missing_general_ids=sorted(wanted-set(generals)),
                general_container=general_header,
                consistency='selected unit/context double-read; not whole-world atomic',
                live_acceptance=False)


def panel_text(value):
    row = value['unit']
    lines = ['部队属性 · 只读', '%s #%s  %s（势力 %s）' %
             (row['kind'], row['unit_id'], row.get('owner_name') or '名称未读', row['owner_raw']),
             '坐标 %s  |  %s' % (row['world_xy_raw'], time.strftime('%H:%M:%S', time.localtime(value['wall']))),
             '兵数 %s   兵粮 %s' % (row['soldiers_candidate'], row['rice_candidate']),
             '剩余移动 %s   兵装度 %s' % (row['move_remaining_raw'], row['armament_degree_raw']),
             '兵数/粮/移动/兵装：静态布局值，待新局画面对照',
             '指令原值 %s  参数 0x%08x' % (row['order_type_raw'], row['order_payload_raw']),
             '状态原值 0x%02x' % row['state_flags_raw'],
             '+1d/+1e：未定（0x%02x / 0x%02x）' % (row['raw_1d'], row['raw_1e']), '']
    for index, (gid, general) in enumerate(zip(row['general_ids'], value['generals'])):
        lines.append('武将 %d · %s' % (index+1, '空' if gid is None else '#'+str(gid)))
        if general:
            lines += ['%s  字 %s' % (general['name'], general['courtesy_name'] or '—'),
                      '  '.join('%s %d' % (k, v) for k, v in general['attributes'].items()),
                      '带兵 %s  状态 %s（%s）' % (general['soldiers'], general['status'], general['status_raw']),
                      '所在城 %s（%s）' % (general['city_name'] or '未定/无', general['city_id']),
                      '技能掩码 0x%08x  肖像ID %s' % (general['skill_mask_raw'], general['portrait_id'])]
        elif gid is not None:
            lines.append('未捕获此武将；不补造属性')
        lines.append('')
    lines += ['数值为点击时快照；刷新会重新核对身份与坐标。', '未定字段不推断士气、训练度或战斗力。']
    return '\r\n'.join(lines)
