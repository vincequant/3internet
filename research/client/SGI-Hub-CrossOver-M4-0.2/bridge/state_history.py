"""Observe force stocks, training and barracks. Inference is never an action fact."""
import json
from datetime import datetime
from pathlib import Path

KINDS = ('infantry', 'cavalry', 'bow')
KIND_CN = {'infantry': '步', 'cavalry': '骑', 'bow': '弓'}
TIER_NAMES = {
    'infantry': ('步兵', '强化步兵', '重装步兵'),
    'cavalry': ('骑兵', '强化骑兵', '铁骑兵'),
    'bow': ('弓兵', '弩兵', '连弩'),
}
# Vtable label 重装骑兵 is the same tier the training screen calls 铁骑兵.
KIND_LABEL = {'重装骑兵': '铁骑兵'}


def kind_label(name):
    if not isinstance(name, str):
        return name
    return KIND_LABEL.get(name, name)


def kind_line(text):
    if not isinstance(text, str) or '重装骑兵' not in text:
        return text
    return text.replace('重装骑兵', '铁骑兵')


def relabel_field_units(state):
    """Show 铁骑兵 on units already decoded under the vtable name."""
    units = ((state or {}).get('entities') or {}).get('field_units') or []
    for row in units:
        if not isinstance(row, dict):
            continue
        labeled = kind_label(row.get('unit_kind'))
        if labeled != row.get('unit_kind'):
            row['unit_kind'] = labeled
    return state
BUILDING_CN = {
    'parade_ground': '练兵所',
    'horse_farm': '牧场',
    'bow_studio': '弓工坊',
}
LORD_FIELDS = ('force_id', 'name', 'gold', 'rice', 'prestige', 'troop_stock', 'armament_raw', 'training_progress')
CITY_FIELDS = ('city_id', 'name', 'type', 'owner_raw', 'population', 'morale', 'world_xy_raw')
BUILDING_FIELDS = ('object_id_candidate', 'type', 'owner_raw', 'world_xy_raw', 'building_ui_amount', 'linked_city_id')
UNIT_FIELDS = ('unit_id', 'unit_kind', 'owner_raw', 'soldiers_candidate', 'world_xy_raw', 'general_ids',
               'terrain_type_raw', 'on_water', 'target_attack_unit', 'website_attack_power',
               'training_degree', 'armament_degree_raw', 'attack_verification', 'training_verification',
               'attack_model','native_attack_index','native_attack_index_full_morale',
               'target_attack_full_morale','basic_combat_power','morale','size_index',
               'move_remaining_raw','movement_verification','effective_skill_mask')
GENERAL_FIELDS = ('general_id_raw', 'name', 'owner_raw', 'status_code', 'location_city_id', 'soldiers')
WILD_OWNER = 65535
PENDING_HIRE_STATUS = 9
HIRE_NOTE = '内政录用：军事阶段前就能看到结果。教程为同城随机录取，下达前不能点名预知是谁'
JOIN_NOTE = '在野将在军事阶段后转入；录用类指令记入内政栏'
CAPTURE_BUILDING_GRACE_FRAMES = 16


def default_root():
    env = __import__('os').environ.get('SGI_HUB_HISTORY')
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / 'history-data'


def training_progress(raw):
    return (100 if raw >= 300 else raw % 100) if isinstance(raw, int) and 0 <= raw <= 300 else None


def troop_text(kind, raw):
    degree = training_progress(raw)
    if degree is None or kind not in TIER_NAMES:
        return '未知'
    tier = 0 if raw < 100 else 1 if raw < 200 else 2
    return f'{TIER_NAMES[kind][tier]} {degree}/100'


SEASON_CN = {0: '春', 1: '夏', 2: '秋', 3: '冬'}


def _digits_after(text, token):
    at = str(text or '').find(token)
    if at < 0:
        return None
    digits = ''
    for ch in str(text)[at + len(token):]:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def _year_from_text(text):
    text = str(text or '')
    at = text.find('年')
    if at < 0:
        return None
    before = ''
    for ch in reversed(text[:at]):
        if ch.isdigit():
            before = ch + before
        elif before:
            break
    if before:
        return int(before)
    after = ''
    for ch in text[at + 1:]:
        if ch.isdigit():
            after += ch
        elif after:
            break
    return int(after) if after else None


def calendar_label(year, season):
    if not isinstance(year, int) or not isinstance(season, int):
        return None
    name = SEASON_CN.get(season)
    return f'{year}年{name}' if name else f'{year}年季{season}'


def clock_turn_u16(clock):
    if not isinstance(clock, dict):
        return None
    turn = clock.get('turn_u16')
    if isinstance(turn, int):
        return turn
    raw = clock.get('raw_hex')
    if not raw:
        return None
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(data) < 14:
        return None
    return int.from_bytes(data[12:14], 'little')


def season_round(turn):
    if not isinstance(turn, int) or turn < 0:
        return 0
    return min(2, turn // 2)


def phase_fields(clock=None, phase=None):
    clock = clock if isinstance(clock, dict) else {}
    phase = phase if isinstance(phase, dict) else {}
    year = phase.get('year_u16')
    season = phase.get('season_u16')
    if year is None:
        year = clock.get('year_u16')
    if season is None:
        season = clock.get('season_u16')
    turn = clock_turn_u16(clock)
    if turn is None:
        turn = clock_turn_u16(phase)
    out = {'year_u16': year, 'season_u16': season}
    if turn is not None:
        out['turn_u16'] = turn
        out['round_u8'] = season_round(turn)
    elif isinstance(phase.get('round_u8'), int):
        out['round_u8'] = min(2, max(0, phase['round_u8']))
    return out


def phase_round(phase):
    if not isinstance(phase, dict):
        return 0
    if isinstance(phase.get('round_u8'), int):
        return min(2, max(0, phase['round_u8']))
    turn = clock_turn_u16(phase)
    if turn is not None:
        return season_round(turn)
    return 0


def phase_label(phase):
    if not isinstance(phase, dict):
        return '季度未知'
    pretty = calendar_label(phase.get('year_u16'), phase.get('season_u16'))
    if not pretty:
        return '季度未知'
    rnd = phase_round(phase) if ('round_u8' in phase or 'turn_u16' in phase or phase.get('raw_hex')) else None
    season = phase.get('season_u16')
    if season == 0 and (rnd is None or rnd == 0):
        return pretty + ' · 内政'
    if rnd is not None:
        return f'{pretty} 第{rnd + 1}回合'
    return pretty


def comparable_phase(phase):
    if not isinstance(phase, dict):
        return None
    year, season = phase.get('year_u16'), phase.get('season_u16')
    if isinstance(year, int) and isinstance(season, int):
        return (year, season, phase_round(phase))
    return None


def identity_key(state):
    ident = state.get('identity') or {}
    return {'creation_filetime': ident.get('creation_filetime'), 'path': ident.get('path')}


def _num(value):
    return f'{value:,}' if isinstance(value, int) else ('—' if value is None else str(value))


def _training_map(row):
    raw = row.get('armament_raw') or {}
    progress = row.get('training_progress')
    if isinstance(progress, dict):
        return progress
    return {kind: training_progress(raw.get(kind)) for kind in KINDS}


def _pick(row, fields):
    out = {key: row.get(key) for key in fields}
    if 'armament_raw' in fields:
        out['training_progress'] = _training_map(row)
    return out


def slim(state):
    clock = state.get('clock_candidates') or {}
    entities = state.get('entities') or {}
    lords = [{**_pick(row, LORD_FIELDS), 'record': row.get('container_index', index)}
             for index, row in enumerate(entities.get('lords') or [])]
    for lord in lords:
        owned = [g for g in entities.get('generals') or [] if g.get('owner_raw') == lord['force_id']]
        politics = [(g.get('attributes') or {}).get('pol') for g in owned]
        # Include every owned officer and a possible 40% book bonus. Custom
        # officers can exceed100; incomplete stats never create a tighter cap.
        lord['training_politics_upper'] = ((max(politics)*14+5)//10
            if politics and all(type(p) is int and 0 <= p <= 255 for p in politics) else None)
    cities = [{**_pick(row, CITY_FIELDS), 'record': row.get('container_index', index)}
              for index, row in enumerate(entities.get('cities_and_barriers') or [])]
    buildings = [{**_pick(row, BUILDING_FIELDS), 'record': row.get('container_index', index)}
                 for index, row in enumerate(entities.get('production_buildings') or [])]
    units = [{**_pick(row, UNIT_FIELDS), 'record': row.get('container_index', index)}
             for index, row in enumerate(entities.get('field_units') or [])]
    generals = [{**_pick(row, GENERAL_FIELDS), 'record': row.get('container_index', index)}
                for index, row in enumerate(entities.get('generals') or [])]
    out = {
        'snapshot_id': state.get('snapshot_id'),
        'capture_end': state.get('capture_end'),
        'build_sha256': state.get('build_sha256'),
        'movement_rules': state.get('movement_rules'),
        'identity': identity_key(state),
        'phase_candidate': phase_fields(clock, state.get('phase_candidate')),
        'entities': {
            'lords': lords,
            'cities_and_barriers': cities,
            'production_buildings': buildings,
            'field_units': units,
            'generals': generals,
        },
    }
    grid = state.get('terrain_grid')
    if isinstance(grid, dict) and isinstance(grid.get('types'), str):
        out['terrain_grid'] = {
            'width': grid.get('width'),
            'height': grid.get('height'),
            'types': grid.get('types'),
            'source': grid.get('source'),
            'encoding': grid.get('encoding'),
            'unknown_code': grid.get('unknown_code'),
            'readonly': True,
        }
    return out


def entity_key(kind, row):
    if kind == 'lords':
        return row.get('force_id')
    if kind == 'cities_and_barriers':
        return row.get('city_id')
    if kind == 'field_units':
        return row.get('unit_id')
    if kind == 'generals':
        return row.get('general_id_raw')
    return (row.get('type'), row.get('object_id_candidate'), tuple(row.get('world_xy_raw') or []))


def _xy_list(row):
    point = _xy(row)
    return list(point) if point else None


def entity_diff_target(kind, left, right):
    row = right or left or {}
    target = {
        'kind': kind,
        'present_after': right is not None,
        'world_xy_before': _xy_list(left),
        'world_xy_after': _xy_list(right),
        'world_xy_raw': _xy_list(right or left),
        'locatable': True,
    }
    if kind == 'field_units':
        uid = row.get('unit_id')
        target.update(unit_id=uid, unit_kind=row.get('unit_kind'), owner=row.get('owner_raw'))
        if right is None:
            target['disappeared'] = True
            target['world_xy_raw'] = _xy_list(left)
        if uid is None:
            target['locatable'] = False
            target['identity_uncertain'] = True
    elif kind == 'cities_and_barriers':
        target['city_id'] = row.get('city_id')
        if target['city_id'] is None:
            target['locatable'] = False
            target['identity_uncertain'] = True
    elif kind == 'production_buildings':
        target.update(
            object_id_candidate=row.get('object_id_candidate'),
            linked_city_id=row.get('linked_city_id'),
            building_type=row.get('type'),
            owner=row.get('owner_raw'),
        )
        if row.get('object_id_candidate') is None and not target.get('world_xy_raw'):
            target['locatable'] = False
            target['identity_uncertain'] = True
    elif kind == 'lords':
        target['force_id'] = row.get('force_id')
    return target


def _change(entity, name, owner, field, before, after, interpretation, **extra):
    item = {
        'entity': entity, 'name': name, 'owner': owner, 'field': field,
        'before': before, 'after': after, 'interpretation': interpretation,
        'flat': before == after,
    }
    item.update(extra)
    return item


def implied_recruit_raw(stock0, raw0, stock1, raw1):
    if not all(isinstance(value, int) for value in (stock0, raw0, stock1, raw1)):
        return None
    added = stock1 - stock0
    if added <= 0:
        return None
    return (raw1 * stock1 - raw0 * stock0) / added


def military_note(stock0, raw0, stock1, raw1, boundary=False):
    notes = []
    if isinstance(stock0, int) and isinstance(stock1, int) and stock1 != stock0:
        notes.append(f'库存{stock1 - stock0:+,}')
    deg0, deg1 = training_progress(raw0), training_progress(raw1)
    if deg0 is not None and deg1 is not None and deg1 != deg0:
        notes.append(f'训练{deg0}→{deg1}')
    elif isinstance(raw0, int) and isinstance(raw1, int) and raw1 != raw0:
        notes.append(f'武装原值{raw0}→{raw1}')
    implied = implied_recruit_raw(stock0, raw0, stock1, raw1)
    if implied is not None and (raw0 != raw1 or stock0 != stock1):
        notes.append(f'若按存量加权混合，隐含新兵原值约{implied:.0f}')
        if abs(implied - 180) <= 3:
            notes.append('接近教程夏季新兵180')
    stock_up = isinstance(stock0, int) and isinstance(stock1, int) and stock1 > stock0
    train_down = None
    if deg0 is not None and deg1 is not None:
        train_down = deg1 < deg0
    elif isinstance(raw0, int) and isinstance(raw1, int):
        train_down = raw1 < raw0
    if stock_up and train_down:
        notes.append('库存增加且训练下降，符合新兵摊薄')
    if (isinstance(raw0, int) and isinstance(raw1, int) and raw1 > raw0) or (deg0 is not None and deg1 is not None and deg1 > deg0):
        notes.append('训练上升，可能练兵所训练')
    if not notes:
        return '本季观察基线，尚未看到增减'
    notes.append('不能从净变化唯一反推指令')
    if boundary:
        notes.append('含跨季间隔，不一定全是本季指令')
    return '；'.join(notes)


def building_stats(snapshot, force_id, building_type):
    rows = [row for row in snapshot['entities'].get('production_buildings', [])
            if row.get('owner_raw') == force_id and row.get('type') == building_type]
    amounts = [row.get('building_ui_amount') for row in rows if isinstance(row.get('building_ui_amount'), int)]
    return {'count': len(rows), 'amount': sum(amounts) if amounts else (0 if rows else None)}


def lord_map(snapshot):
    return {row.get('force_id'): row for row in snapshot['entities'].get('lords', []) if row.get('force_id') is not None}


def city_names(snapshot):
    return {row.get('city_id'): row.get('name') for row in snapshot['entities'].get('cities_and_barriers', [])
            if row.get('city_id') is not None}


def building_label(row, names):
    kind = BUILDING_CN.get(row.get('type'), row.get('type') or '生产建筑')
    city = names.get(row.get('linked_city_id'))
    xy = row.get('world_xy_raw') or []
    place = city or (','.join(map(str, xy)) if xy else '位置未知')
    return f'{kind}·{place}'


def census_rows(baseline, current, boundary=False):
    out = []
    names = {**{fid: row.get('name') for fid, row in lord_map(baseline).items()},
             **{fid: row.get('name') for fid, row in lord_map(current).items()}}
    force_ids = sorted({fid for fid in list(lord_map(baseline)) + list(lord_map(current)) if fid is not None},
                       key=lambda fid: (names.get(fid) is None, str(names.get(fid) or ''), fid))
    cities = city_names(current) or city_names(baseline)
    for fid in force_ids:
        before = lord_map(baseline).get(fid)
        after = lord_map(current).get(fid)
        name = names.get(fid) or f'势力{fid}'
        if before is None or after is None:
            out.append(_change('lords', name, fid, '势力记录',
                               '无' if before is None else '有', '有' if after else '无',
                               '势力记录出现或消失；不能单独证明灭国或新建'))
            continue
        for kind in KINDS:
            stock0 = (before.get('troop_stock') or {}).get(kind)
            stock1 = (after.get('troop_stock') or {}).get(kind)
            raw0 = (before.get('armament_raw') or {}).get(kind)
            raw1 = (after.get('armament_raw') or {}).get(kind)
            label = KIND_CN[kind]
            note = military_note(stock0, raw0, stock1, raw1, boundary)
            out.append(_change('lords', name, fid, f'{label}库存', _num(stock0), _num(stock1), note,
                               kind=kind, metric='stock'))
            out.append(_change('lords', name, fid, f'{label}训练',
                               troop_text(kind, raw0) if isinstance(raw0, int) else '未知',
                               troop_text(kind, raw1) if isinstance(raw1, int) else '未知',
                               note, kind=kind, metric='training', raw_before=raw0, raw_after=raw1))
        for building_type, label in BUILDING_CN.items():
            left = building_stats(baseline, fid, building_type)
            right = building_stats(current, fid, building_type)
            text0 = '—' if left['count'] == 0 and left['amount'] is None else f"{left['count']}座/{_num(left['amount'])}"
            text1 = '—' if right['count'] == 0 and right['amount'] is None else f"{right['count']}座/{_num(right['amount'])}"
            if left == right and left['count'] == 0:
                interpretation = '本季观察基线，尚无此类建筑'
            elif right['count'] > left['count']:
                interpretation = f'新增{label}记录，可能建兵营；不能单独证明刚建完'
            elif right['count'] < left['count']:
                interpretation = f'{label}记录减少；可能拆除、易主或容器回收'
            elif right['amount'] != left['amount']:
                interpretation = f'{label}产能变化；可能扩建或损伤'
            else:
                interpretation = '本季观察基线，建筑座数未变'
            out.append(_change('production_buildings', name, fid, label, text0, text1, interpretation,
                               metric='building', building_type=building_type))
    return out


def differences(before, after):
    out = []
    city = city_names(after) or city_names(before)
    names = {row.get('force_id'): row.get('name') for row in after['entities'].get('lords', [])}
    names.update({row.get('force_id'): row.get('name') for row in before['entities'].get('lords', [])})
    for kind, rows in after['entities'].items():
        if kind == 'generals':
            continue
        old = {entity_key(kind, row): row for row in before['entities'].get(kind, [])}
        new = {entity_key(kind, row): row for row in rows}
        for ident in old.keys() | new.keys():
            left, right = old.get(ident), new.get(ident)
            row = right or left
            owner = row.get('force_id', row.get('owner_raw'))
            if kind == 'lords':
                label = row.get('name') or names.get(owner) or str(ident)
            elif kind == 'production_buildings':
                label = building_label(row, city)
            else:
                label = row.get('name') or row.get('unit_kind') or str(ident)
            target = entity_diff_target(kind, left, right)
            if left is None or right is None:
                out.append(_change(kind, label, owner, '记录有无',
                                   None if left is None else '有', None if right is None else '有',
                                   presence_note(kind, left, right), target=target))
                continue
            if kind == 'lords':
                out.extend(lord_diffs(left, right, label, owner, target=target))
            elif kind == 'production_buildings':
                out.extend(building_diffs(left, right, label, owner, city, target=target))
            elif kind == 'cities_and_barriers':
                if left.get('owner_raw') != right.get('owner_raw'):
                    out.append(_change(kind, label, owner, '归属',
                                       names.get(left.get('owner_raw'), left.get('owner_raw')),
                                       names.get(right.get('owner_raw'), right.get('owner_raw')),
                                       '城关归属变化；募兵与兵营收益可能随之改变', target=target))
                if left.get('population') != right.get('population'):
                    out.append(_change(kind, label, owner, '人口',
                                       _num(left.get('population')), _num(right.get('population')),
                                       '人口变化，影响募兵帽；不是库存', target=target))
            elif kind == 'field_units':
                if _xy(left) != _xy(right):
                    out.append(_change(kind, label, owner, '部队坐标',
                                       format_xy(_xy(left)), format_xy(_xy(right)),
                                       '观察到部队位移', target=target))
                if left.get('soldiers_candidate') != right.get('soldiers_candidate'):
                    out.append(_change(kind, label, owner, '部队兵数',
                                       _num(left.get('soldiers_candidate')), _num(right.get('soldiers_candidate')),
                                       '出征部队兵数变化；可能损耗或改编', target=target))
    return annotate(out, before, after)


def presence_note(kind, left, right):
    if kind == 'production_buildings':
        row = right or left
        label = BUILDING_CN.get(row.get('type'), '生产建筑')
        if right and not left:
            amount = row.get('building_ui_amount')
            extra = f'，产能{_num(amount)}' if isinstance(amount, int) else ''
            return f'新增{label}记录{extra}，可能建兵营；不能单独证明刚建完'
        return f'{label}记录消失；可能拆除、易主或容器回收'
    if kind == 'field_units':
        return '出征部队出现或消失；库存变化需对照势力层，不能单独证明出兵或覆灭'
    if kind == 'lords':
        return '势力记录出现或消失；不能单独证明灭国或新建'
    return '记录出现或消失；具体指令未确认'


def lord_diffs(left, right, name, owner, target=None):
    out = []
    for kind in KINDS:
        stock0 = (left.get('troop_stock') or {}).get(kind)
        stock1 = (right.get('troop_stock') or {}).get(kind)
        raw0 = (left.get('armament_raw') or {}).get(kind)
        raw1 = (right.get('armament_raw') or {}).get(kind)
        label = KIND_CN[kind]
        note = military_note(stock0, raw0, stock1, raw1)
        if stock0 != stock1:
            out.append(_change('lords', name, owner, f'{label}库存', _num(stock0), _num(stock1), note,
                               kind=kind, metric='stock', target=target))
        if raw0 != raw1 or _training_map(left).get(kind) != _training_map(right).get(kind):
            bounds = (left.get('training_politics_upper'),right.get('training_politics_upper'))
            upper = max(50,*bounds) if all(type(v) is int for v in bounds) else None
            out.append(_change('lords', name, owner, f'{label}训练',
                               troop_text(kind, raw0) if isinstance(raw0, int) else '未知',
                               troop_text(kind, raw1) if isinstance(raw1, int) else '未知',
                               note, kind=kind, metric='training', raw_before=raw0, raw_after=raw1, target=target,
                               training_politics_upper_before=upper,
                               training_stock_before=(left.get('troop_stock') or {}).get(kind),
                               training_stock_after=(right.get('troop_stock') or {}).get(kind)))
    for field, title, text in (
        ('gold', '金钱', '金钱变化；练兵、建设、买卖米等均可能，不能唯一反推'),
        ('rice', '粮食', '粮食变化；收获、交易、运输或消耗待核'),
        ('prestige', '信望', '信望变化；具体来源未确认'),
    ):
        if left.get(field) != right.get(field):
            out.append(_change('lords', name, owner, title, _num(left.get(field)), _num(right.get(field)), text,
                               target=target))
    return out


def building_diffs(left, right, name, owner, cities, target=None):
    out = []
    if left.get('building_ui_amount') != right.get('building_ui_amount'):
        label = BUILDING_CN.get(right.get('type'), '生产建筑')
        out.append(_change('production_buildings', name, owner, f'{label}产能',
                           _num(left.get('building_ui_amount')), _num(right.get('building_ui_amount')),
                           f'{label}产能变化；可能扩建或损伤', target=target))
    if left.get('owner_raw') != right.get('owner_raw'):
        out.append(_change('production_buildings', name, owner, '建筑归属',
                           left.get('owner_raw'), right.get('owner_raw'),
                           '生产建筑归属变化；可能易主', target=target))
    if left.get('linked_city_id') != right.get('linked_city_id'):
        out.append(_change('production_buildings', name, owner, '关联城',
                           cities.get(left.get('linked_city_id'), left.get('linked_city_id')),
                           cities.get(right.get('linked_city_id'), right.get('linked_city_id')),
                           '建筑关联城市变化', target=target))
    return out


def annotate(changes, before, after):
    gold = {}
    for row in changes:
        if row.get('entity') == 'lords' and row.get('field') == '金钱':
            try:
                gold[row.get('owner')] = int(str(row['after']).replace(',', '')) < int(str(row['before']).replace(',', ''))
            except (TypeError, ValueError):
                pass
    for row in changes:
        if row.get('metric') == 'training' and gold.get(row.get('owner')) and '训练上升' in row['interpretation']:
            row['interpretation'] = row['interpretation'] + '；同观察金钱减少，符合练兵花费'
        if row.get('field') == '记录有无' and row.get('entity') == 'field_units' and row.get('after') == '有':
            owner = row.get('owner')
            stock_down = any(item.get('owner') == owner and item.get('metric') == 'stock'
                             and isinstance(item.get('before'), str) and isinstance(item.get('after'), str)
                             and item['before'] != '—' and item['after'] != '—'
                             and _parse_int(item['after']) < _parse_int(item['before'])
                             for item in changes)
            if stock_down:
                row['interpretation'] = row['interpretation'] + '；同观察库存减少，符合出兵'
    return changes


def _parse_int(text):
    try:
        return int(str(text).replace(',', '').replace('—', ''))
    except ValueError:
        return 0


def snapshot_line(lord, snapshot, fid):
    if not lord:
        return '无此势力'
    parts = []
    raws = lord.get('armament_raw') or {}
    stocks = lord.get('troop_stock') or {}
    for kind in KINDS:
        stock, raw = stocks.get(kind), raws.get(kind)
        piece = f'{KIND_CN[kind]}{_num(stock)}'
        if isinstance(raw, int):
            piece += ' ' + troop_text(kind, raw)
        parts.append(piece)
    for building_type, label in BUILDING_CN.items():
        stats = building_stats(snapshot, fid, building_type)
        if stats['count']:
            parts.append(f"{label}{stats['count']}座/{_num(stats['amount'])}")
    if isinstance(lord.get('gold'), int):
        parts.append('金' + _num(lord['gold']))
    return ' · '.join(parts)


def city_owner_ops(before, after, fid):
    old = {row.get('city_id'): row for row in before['entities'].get('cities_and_barriers', [])}
    new = {row.get('city_id'): row for row in after['entities'].get('cities_and_barriers', [])}
    ops = []
    for cid in old.keys() | new.keys():
        left, right = old.get(cid), new.get(cid)
        name = (right or left).get('name') or f'城{cid}'
        kind = '关隘' if (right or left).get('type') == 'barrier' else '城'
        left_owner = None if left is None else left.get('owner_raw')
        right_owner = None if right is None else right.get('owner_raw')
        if left_owner != fid and right_owner == fid:
            ops.append(digest_item(
                f'得{kind} {name}', '得' + kind, '无', name,
                f'观察到{kind}{name}归属转入', command=True))
        elif left_owner == fid and right_owner != fid:
            ops.append(digest_item(
                f'失{kind} {name}', '失' + kind, name, '无',
                f'观察到{kind}{name}归属转出', command=True))
    return ops


def unit_count(snapshot, fid):
    return sum(1 for row in snapshot['entities'].get('field_units', []) if row.get('owner_raw') == fid)


def _xy(row):
    point = (row or {}).get('world_xy_raw') or []
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return (point[0], point[1])
    return None


def format_xy(point):
    return '' if point is None else f'({point[0]},{point[1]})'


def general_names(snapshot):
    return {row.get('general_id_raw'): row.get('name')
            for row in snapshot.get('entities', {}).get('generals', [])
            if row.get('general_id_raw') is not None and row.get('name')}


def unit_display(row, names):
    kind = kind_label((row or {}).get('unit_kind')) or '部队'
    uid = (row or {}).get('unit_id')
    label = f'{kind}#{uid}' if uid is not None else kind
    people = [names.get(gid) for gid in ((row or {}).get('general_ids') or []) if names.get(gid)]
    if people:
        label += f'（{"、".join(people)}）'
    return label


def near_city_suffix(point, snapshot, max_dist=2):
    if point is None:
        return ''
    best = None
    for city in snapshot.get('entities', {}).get('cities_and_barriers', []):
        other = _xy(city)
        name = city.get('name')
        if other is None or not name:
            continue
        dist = abs(other[0] - point[0]) + abs(other[1] - point[1])
        if best is None or dist < best[0]:
            best = (dist, name)
    if best and best[0] <= max_dist:
        return f' 近{best[1]}'
    return ''


def unit_command_ops(before, after, fid):
    names = {**general_names(before), **general_names(after)}
    old = {row.get('unit_id'): row for row in before['entities'].get('field_units', [])
           if row.get('owner_raw') == fid and row.get('unit_id') is not None}
    new = {row.get('unit_id'): row for row in after['entities'].get('field_units', [])
           if row.get('owner_raw') == fid and row.get('unit_id') is not None}
    ops = []
    for uid in sorted(old.keys() | new.keys(), key=lambda value: (isinstance(value, str), value)):
        left, right = old.get(uid), new.get(uid)
        target = {
            'kind': 'field_units',
            'unit_id': uid,
            'world_xy_raw': list(_xy(right or left) or []),
        }
        if left is None:
            point = _xy(right)
            where = format_xy(point)
            line = f'出征 {unit_display(right, names)} 出现于 {where}' + near_city_suffix(point, after)
            ops.append(digest_item(line, '出征', '', where, '观察到部队出现', command=True, target=target,
                                   unit_snapshot=dict(right), observed_at=after.get('capture_end'),
                                   snapshot_id=after.get('snapshot_id')))
        elif right is None:
            ops.append(digest_item(
                f'部队消失 {unit_display(left, names)}', '部队消失',
                format_xy(_xy(left)), '', '观察到部队消失', command=True, target=target))
        elif _xy(left) != _xy(right):
            start, end = format_xy(_xy(left)), format_xy(_xy(right))
            line = f'部队移动 {unit_display(right, names)} {start} → {end}' + near_city_suffix(_xy(right), after)
            ops.append(digest_item(line, '部队移动', start, end, '观察到部队位移', command=True, target=target))
    return ops


def officer_command_ops(before, after, fid):
    cities = city_names(after) or city_names(before)
    old = {row.get('general_id_raw'): row for row in before['entities'].get('generals', [])
           if row.get('general_id_raw') is not None}
    new = {row.get('general_id_raw'): row for row in after['entities'].get('generals', [])
           if row.get('general_id_raw') is not None}
    ops = []
    for gid in sorted(old.keys() | new.keys(), key=lambda value: (isinstance(value, str), value)):
        left, right = old.get(gid), new.get(gid)
        if left is None or right is None:
            continue
        if left.get('owner_raw') is None and left.get('status_code') is None:
            continue
        name = right.get('name') or left.get('name') or f'将{gid}'
        city_id = right.get('location_city_id')
        if city_id is None:
            city_id = left.get('location_city_id')
        city = cities.get(city_id)
        target = {'kind': 'cities_and_barriers', 'city_id': city_id, 'general_id': gid}
        if right.get('owner_raw') == fid and left.get('owner_raw') != fid:
            if right.get('status_code') == PENDING_HIRE_STATUS:
                ops.append(hire_op(name, city, gid, city_id))
            elif left.get('owner_raw') == WILD_OWNER or left.get('status_code') == 1:
                ops.append(join_op(name, city, gid, city_id))
            elif left.get('status_code') == 4:
                ops.append(digest_item(
                    f'俘虏归顺 {name}', '俘虏归顺', '俘虏', name,
                    '观察到俘虏归属转入；不是主动点名录用',
                    command=True, target=target, general_id=gid))
    return ops


def building_rows(snapshot, fid, building_type):
    return [row for row in snapshot['entities'].get('production_buildings', [])
            if row.get('owner_raw') == fid and row.get('type') == building_type]


def building_key(row):
    return (row.get('object_id_candidate'), tuple(row.get('world_xy_raw') or []), row.get('linked_city_id'))


def city_owners(state):
    out = {}
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        cid = row.get('city_id')
        if cid is not None:
            out[cid] = row.get('owner_raw')
    return out


def captured_city_ids(before, after, fid):
    old_owner = city_owners(before)
    gained = set()
    for cid, owner in city_owners(after).items():
        if owner == fid and old_owner.get(cid) != fid:
            gained.add(cid)
    return gained


def record_city_captures(prev, now, seq, captured_at):
    """Remember when each force first took a city. Keys are (force_id, city_id)."""
    old = city_owners(prev)
    for cid, owner in city_owners(now).items():
        if owner is None or owner == WILD_OWNER:
            continue
        if old.get(cid) != owner:
            captured_at[(owner, cid)] = seq
    return captured_at


def recent_capture_ids(fid, captured_at, seq, grace=CAPTURE_BUILDING_GRACE_FRAMES):
    if not captured_at or not isinstance(seq, int):
        return set()
    return {cid for (owner, cid), at in captured_at.items()
            if owner == fid and isinstance(at, int) and 0 <= seq - at <= grace}


def nearby_capture_ids(fid, captured_at, seq, grace=CAPTURE_BUILDING_GRACE_FRAMES):
    if not captured_at or not isinstance(seq, int):
        return set()
    return {cid for (owner, cid), at in captured_at.items()
            if owner == fid and isinstance(at, int) and abs(seq - at) <= grace}


def city_names_for_ids(state, city_ids):
    wanted = set(city_ids or ())
    names = set()
    for row in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if row.get('city_id') in wanted and row.get('name'):
            names.add(row.get('name'))
    return names


def is_capture_transfer_build(item, gained_ids, gained_names, cap_seq, grace=CAPTURE_BUILDING_GRACE_FRAMES):
    if not str((item or {}).get('field') or '').startswith('新建'):
        return False
    ev_seq = (item or {}).get('seq') or 0
    if not isinstance(ev_seq, int) or not isinstance(cap_seq, int):
        return False
    if ev_seq > cap_seq or cap_seq - ev_seq > grace:
        return False
    if (item or {}).get('owner') is None:
        return False
    city_id = ((item or {}).get('target') or {}).get('city_id')
    if city_id in (gained_ids or ()):
        return True
    line = str((item or {}).get('line') or '')
    places = list((item or {}).get('places') or [])
    if '：' not in line and not places:
        return True
    for name in gained_names or ():
        if name and (name in line or name in places):
            return True
    return False


def drop_capture_transfer_builds(events, fid, gained_ids, gained_names, cap_seq,
                                 grace=CAPTURE_BUILDING_GRACE_FRAMES):
    out = []
    for item in events or []:
        if item.get('owner') != fid:
            out.append(item)
            continue
        if is_capture_transfer_build(item, gained_ids, gained_names, cap_seq, grace):
            continue
        out.append(item)
    return out


CAMP_BUILD_KIND = {
    '新建练兵所': '练兵所',
    '新建牧场': '牧场',
    '新建弓工坊': '弓工坊',
}


def is_camp_build_op(item):
    return str((item or {}).get('field') or '') in CAMP_BUILD_KIND


def camp_build_place_text(item):
    places = [name for name in ((item or {}).get('places') or []) if name]
    if places:
        return place_list(places)
    line = str((item or {}).get('line') or '')
    if '：' in line:
        return line.split('：', 1)[1].strip()
    return '地点未标'


def camp_build_record(item, when=None, seq=None, label=None):
    field = (item or {}).get('field')
    phase = (item or {}).get('phase')
    return {
        'owner': (item or {}).get('owner'),
        'name': (item or {}).get('name'),
        'field': field,
        'kind': CAMP_BUILD_KIND.get(field, field),
        'line': (item or {}).get('line') or field,
        'places': list((item or {}).get('places') or []),
        'place': camp_build_place_text(item),
        'when': when or (item or {}).get('when'),
        'phase': phase,
        'label': label or (item or {}).get('label') or phase_label(phase or {}),
        'seq': (item or {}).get('seq') if (item or {}).get('seq') is not None else seq,
    }


def camp_builds_from_ops(ops, owner=None, name=None, phase=None, label=None):
    rows = []
    for item in ops or []:
        if not is_camp_build_op(item):
            continue
        row = dict(item)
        if owner is not None:
            row.setdefault('owner', owner)
        if name:
            row.setdefault('name', name)
        if phase is not None:
            row.setdefault('phase', phase)
        rows.append(camp_build_record(row, label=label or row.get('label')))
    return rows


def camp_builds_from_history(history):
    history = history or {}
    if history.get('camp_builds'):
        return list(history.get('camp_builds') or [])
    rows = []
    accounts = list(history.get('quarters') or [])
    if history.get('current_quarter'):
        accounts.append(history['current_quarter'])
    for account in accounts:
        if not account:
            continue
        for force in account.get('forces') or []:
            rows.extend(camp_builds_from_ops(
                force.get('operations'),
                owner=force.get('owner'),
                name=force.get('name'),
                phase=account.get('phase'),
                label=account.get('label'),
            ))
    return rows


def encode_captured_at(captured_at):
    out = {}
    for (owner, cid), seq in (captured_at or {}).items():
        out[f'{owner}:{cid}'] = seq
    return out


def decode_captured_at(payload):
    out = {}
    for key, seq in (payload or {}).items():
        try:
            owner_text, cid_text = str(key).split(':', 1)
            owner, cid = int(owner_text), int(cid_text)
        except (TypeError, ValueError):
            continue
        if isinstance(seq, int):
            out[(owner, cid)] = seq
    return out


def building_existed_before(before, row, building_type):
    oid = row.get('object_id_candidate')
    xy = tuple(row.get('world_xy_raw') or [])
    for old in (before.get('entities') or {}).get('production_buildings', []) or []:
        if old.get('type') != building_type:
            continue
        if oid not in (None, '') and old.get('object_id_candidate') == oid:
            return True
        old_xy = tuple(old.get('world_xy_raw') or [])
        if xy and old_xy == xy:
            return True
    return False


def added_building_places(before, after, fid, building_type, ignore_city_ids=None):
    names = city_names(after) or city_names(before)
    ignore = set(ignore_city_ids or ())
    old = {building_key(row) for row in building_rows(before, fid, building_type)}
    places = []
    for row in building_rows(after, fid, building_type):
        if building_key(row) in old:
            continue
        if row.get('linked_city_id') in ignore:
            continue
        if building_existed_before(before, row, building_type):
            continue
        place = names.get(row.get('linked_city_id')) or (','.join(map(str, row.get('world_xy_raw') or [])) if row.get('world_xy_raw') else None)
        if place:
            places.append(place)
    return places


def signed_delta(before, after):
    if not isinstance(before, int) or not isinstance(after, int):
        return ''
    delta = after - before
    if delta < 0:
        return f'（−{_num(-delta)}）'
    return f'（+{_num(delta)}）'


def place_list(places):
    counts = {}
    order = []
    for place in places:
        if place not in counts:
            order.append(place)
            counts[place] = 0
        counts[place] += 1
    parts = []
    for place in order:
        n = counts[place]
        if n == 1:
            parts.append(place)
        elif n == 2:
            parts.append(f'{place}（两座）')
        else:
            parts.append(f'{place}（{n}座）')
    return '、'.join(parts)


def digest_item(line, field, before, after, note, **extra):
    item = {'op': field, 'field': field, 'before': before, 'after': after, 'note': note, 'line': line}
    item.update(extra)
    return item


def force_heading(name, player):
    return f'{name}（你这边）' if player else name


def format_force_digest(force):
    heading = force.get('heading') or force.get('name') or '势力'
    lines = [item.get('line') for item in force.get('operations') or [] if item.get('line')]
    if not lines:
        return heading + '\n本季尚无建营、训练、录用或部队移动'
    return heading + '\n' + '\n'.join(lines)


def format_quarter_digest(account, player_force_id=None):
    blocks = [account.get('label') or phase_label(account.get('phase'))]
    for force in account.get('forces') or []:
        if player_force_id is not None:
            force = dict(force)
            force['heading'] = force_heading(force.get('name'), force.get('owner') == player_force_id)
        if force.get('flat'):
            continue
        blocks.append(format_force_digest(force))
    if len(blocks) == 1:
        blocks.append('本季各方尚未看到建营、训练、录用或部队移动')
    return '\n\n'.join(blocks)


def synthesize_force(before, after, fid, boundary=False, player_force_id=None, founding=False,
                    ignore_city_ids=None):
    lords_b, lords_a = lord_map(before), lord_map(after)
    left, right = lords_b.get(fid), lords_a.get(fid)
    name = (right or left or {}).get('name') or f'势力{fid}'
    ops = []
    if left is None or right is None:
        ops.append(digest_item(
            f"{'出现' if left is None else '消失'}：{snapshot_line(right or left, after if right else before, fid)}",
            '势力', '无' if left is None else '有', '有' if right else '无',
            '势力记录出现或消失；不能单独证明灭国或新建'))
        return _force_account(fid, name, left, right, before, after, ops, boundary, player_force_id)
    gained = captured_city_ids(before, after, fid)
    ignore = set(gained)
    ignore.update(cid for cid in (ignore_city_ids or ()) if cid is not None)
    for building_type, label in BUILDING_CN.items():
        places = added_building_places(before, after, fid, building_type, ignore_city_ids=ignore)
        added = len(places)
        if added <= 0:
            if ignore:
                continue
            bstat, astat = building_stats(before, fid, building_type), building_stats(after, fid, building_type)
            added = (astat['count'] - bstat['count']) if isinstance(astat['count'], int) and isinstance(bstat['count'], int) else 0
            if added <= 0:
                continue
        where = place_list(places)
        line = f'新建 {added} 座{label}' + (f'：{where}' if where else '')
        note = f'已有城上新出现的{label}，判为建设指令；随得城转入或得城后不久才见到的营不记新建'
        ops.append(digest_item(line, '新建' + label, '', where or f'+{added}', note, places=places, command=True))
    for kind in KINDS:
        stock0 = (left.get('troop_stock') or {}).get(kind)
        stock1 = (right.get('troop_stock') or {}).get(kind)
        raw0 = (left.get('armament_raw') or {}).get(kind)
        raw1 = (right.get('armament_raw') or {}).get(kind)
        train_up = isinstance(raw0, int) and isinstance(raw1, int) and raw1 > raw0
        if train_up:
            ops.append(digest_item(
                f'训练{KIND_CN[kind]}兵 {troop_text(kind, raw0)} → {troop_text(kind, raw1)}',
                '训练' + KIND_CN[kind] + '兵',
                troop_text(kind, raw0), troop_text(kind, raw1),
                '训练上升，判为练兵指令；夏季自动增兵不记入指令', kind=kind, command=True))
    ops.extend(city_owner_ops(before, after, fid))
    if not founding:
        ops.extend(officer_command_ops(before, after, fid))
    ops.extend(unit_command_ops(before, after, fid))
    return _force_account(fid, name, left, right, before, after, ops, boundary, player_force_id)


def _force_account(fid, name, left, right, before, after, ops, boundary, player_force_id=None):
    summary = format_force_digest({'heading': force_heading(name, fid == player_force_id), 'operations': ops})
    if boundary and ops:
        summary += '\n含跨季间隔，不一定全是本季指令'
    return {
        'owner': fid, 'name': name, 'heading': force_heading(name, fid == player_force_id),
        'operations': ops, 'summary': summary, 'digest': summary,
        'before_text': ops[0]['before'] if ops else '尚无操作',
        'after_text': ops[0]['after'] if ops else '尚无操作',
        'status_text': snapshot_line(right or left, after if right else before, fid),
        'flat': not ops,
    }


def quarter_account(before, after, closed=False, player_force_id=None, founding=False):
    names = {**{fid: row.get('name') for fid, row in lord_map(before).items()},
             **{fid: row.get('name') for fid, row in lord_map(after).items()}}
    force_ids = sorted({fid for fid in list(lord_map(before)) + list(lord_map(after)) if fid is not None},
                       key=lambda fid: (0 if fid == player_force_id else 1, names.get(fid) is None, str(names.get(fid) or ''), fid))
    forces = [synthesize_force(before, after, fid, closed, player_force_id, founding) for fid in force_ids]
    phase = before.get('phase_candidate')
    label = phase_label(phase) + ('（已过季）' if closed else '（进行中）')
    rows = []
    for force in forces:
        for item in force['operations']:
            rows.append(_change(
                'quarter', force['heading'], force['owner'], item['field'],
                item['before'], item['after'], item['note'],
                when=label, phase=phase, metric='operation', flat=False,
                kind=item.get('kind'), line=item.get('line'), target=item.get('target'),
            ))
    return {
        'phase': phase, 'phase_after': after.get('phase_candidate'), 'label': label,
        'closed': closed, 'from': before.get('capture_end'), 'to': after.get('capture_end'),
        'forces': forces, 'rows': rows, 'digest': format_quarter_digest(
            {'label': label, 'phase': phase, 'forces': forces}, player_force_id),
        'actions_verified': False, 'founding': bool(founding),
    }


def quarter_ledger(before, after):
    return quarter_account(before, after, closed=True)


def format_when(snapshot):
    stamp = (snapshot.get('capture_end') or '')[:19].replace('T', ' ')
    return f"{stamp} · {phase_label(snapshot.get('phase_candidate'))}".strip(' ·')


def banner_text(current, quarters, force_count):
    line = (f"{phase_label(current.get('phase_candidate'))}进行中 · 已封存{len(quarters)}季"
            f' · 正在记{force_count}个势力的操作（含敌方）')
    if quarters:
        last = quarters[-1]
        changed = [force for force in last.get('forces', []) if not force.get('flat')]
        bits = [f"{force['name']}：{force['summary']}" for force in changed[:6]]
        extra = f"等{len(changed)}国" if len(changed) > 6 else ''
        return line + f"\n最近封存{last.get('label')}{extra}： " + '；'.join(bits)
    return line + '\n过季会把该季各方建营、训练、录用、得城和部队移动结成操作账并保留。夏季自动增兵不记入指令。'


def is_auto_recruit_op(item):
    field = str((item or {}).get('field') or '')
    line = str((item or {}).get('line') or '')
    return field.startswith('募') or line.startswith('募')


def command_ops(ops):
    return [item for item in (ops or []) if not is_auto_recruit_op(item)]


def hire_op(name, city, gid, city_id):
    place = f'：{city}' if city else ''
    return digest_item(
        f'录用 {name}{place}', '录用', '在野', name, HIRE_NOTE, command=True,
        target={'kind': 'cities_and_barriers', 'city_id': city_id, 'general_id': gid},
        general_id=gid, via='pending_hire')


def join_op(name, city, gid, city_id):
    place = f'：{city}' if city else ''
    return digest_item(
        f'加入 {name}{place}', '主动加入', '在野', name, JOIN_NOTE, command=False,
        target={'kind': 'cities_and_barriers', 'city_id': city_id, 'general_id': gid},
        general_id=gid, via='owner_change')


def pending_hire_ops(snapshot, fid):
    cities = city_names(snapshot)
    ops = []
    for row in (snapshot.get('entities') or {}).get('generals', []) or []:
        if row.get('owner_raw') != fid or row.get('status_code') != PENDING_HIRE_STATUS:
            continue
        gid = row.get('general_id_raw')
        name = row.get('name') or f'将{gid}'
        city_id = row.get('location_city_id')
        ops.append(hire_op(name, cities.get(city_id), gid, city_id))
    return ops


def recorded_hires(accounts):
    keys = set()
    for account in accounts or []:
        if not account:
            continue
        for force in account.get('forces') or []:
            for item in force.get('operations') or []:
                if item.get('field') in ('录用', '主动加入'):
                    keys.add((force.get('owner'), item.get('general_id'), item.get('after')))
    return keys


def is_founding_account(account):
    return bool(account and account.get('founding'))


def mark_opening_founding(quarters):
    if not quarters:
        return
    first = quarters[0]
    if first.get('founding') is None:
        phase = comparable_phase(first.get('phase'))
        first['founding'] = bool(phase and phase[1] == 0)
    for later in quarters[1:]:
        if later.get('founding') is None:
            later['founding'] = False


def drop_founding_joins(ops):
    out = []
    for item in ops or []:
        if item.get('field') in ('录用', '主动加入') and item.get('via') != 'pending_hire':
            continue
        out.append(item)
    return out


def refresh_account(account, player_force_id=None):
    if not account:
        return account
    founding = is_founding_account(account)
    account['founding'] = founding
    for force in account.get('forces') or []:
        ops = command_ops(force.get('operations'))
        if founding:
            ops = drop_founding_joins(ops)
        force['operations'] = ops
        force['flat'] = not force['operations']
        heading = force_heading(force.get('name'), force.get('owner') == player_force_id)
        force['heading'] = heading
        force['summary'] = format_force_digest({**force, 'heading': heading})
        force['digest'] = force['summary']
        if force['operations']:
            force['before_text'] = force['operations'][0].get('before')
            force['after_text'] = force['operations'][0].get('after')
        else:
            force['before_text'] = '尚无操作'
            force['after_text'] = '尚无操作'
    rows = []
    phase = account.get('phase')
    label = account.get('label') or phase_label(phase)
    for force in account.get('forces') or []:
        for item in force.get('operations') or []:
            rows.append(_change(
                'quarter', force.get('heading') or force.get('name'), force.get('owner'), item['field'],
                item.get('before'), item.get('after'), item.get('note'),
                when=label, phase=phase, metric='operation', flat=False,
                kind=item.get('kind'), line=item.get('line'), target=item.get('target'),
            ))
    account['rows'] = rows
    account['digest'] = format_quarter_digest(account, player_force_id)
    return account


def attach_pending_hires(account, snapshot, already=None, player_force_id=None):
    if not account or not snapshot or is_founding_account(account):
        return False
    already = set(already or ())
    changed = False
    for force in account.get('forces') or []:
        fid = force.get('owner')
        added = []
        for item in pending_hire_ops(snapshot, fid):
            key = (fid, item.get('general_id'), item.get('after'))
            if key in already:
                continue
            added.append(item)
            already.add(key)
        if not added:
            continue
        force['operations'] = added + command_ops(force.get('operations'))
        changed = True
    if changed:
        refresh_account(account, player_force_id)
    return changed


def generals_schema_upgrade(prev, current):
    old = ((prev or {}).get('entities') or {}).get('generals') or []
    new = ((current or {}).get('entities') or {}).get('generals') or []
    if not new:
        return False
    if not old:
        return True
    return old[0].get('owner_raw') is None and new[0].get('owner_raw') is not None


def annotate_hire_kinds(history, classes):
    """Mark 募将 (pending, arrives next season) separately from same-round 自动加入."""
    by_id = {}
    by_name = {}
    for row in classes or []:
        fid = row.get('force_id')
        kind = row.get('kind')
        if row.get('general_id') is not None:
            by_id[(fid, row.get('general_id'))] = kind
        if row.get('name'):
            by_name[(fid, row.get('name'))] = kind
    accounts = [row for row in (history or {}).get('quarters') or [] if row]
    current = (history or {}).get('current_quarter')
    if current:
        accounts.append(current)
    for account in accounts:
        for force in account.get('forces') or []:
            fid = force.get('owner')
            for op in force.get('operations') or []:
                if op.get('field') not in ('录用', '主动加入'):
                    continue
                gid = op.get('general_id') or (op.get('target') or {}).get('general_id')
                kind = by_id.get((fid, gid)) or by_name.get((fid, op.get('after')))
                if kind not in ('募将', '自动加入'):
                    kind = '募将' if op.get('field') == '录用' else '自动加入'
                op['hire_kind'] = kind
    return history


def is_civil_op(item):
    field = str((item or {}).get('field') or '')
    return field in ('录用', '主动加入', '布施', '赠绿卡') or field.startswith('新建') or field.startswith('训练')


def is_military_op(item):
    field = str((item or {}).get('field') or '')
    return field in ('出征', '部队移动', '部队消失', '俘虏归顺') or field.startswith('得') or field.startswith('失')


def _round_from_text(text):
    at = str(text or '').find('第')
    if at < 0:
        return None
    digits = ''
    for ch in str(text)[at + 1:]:
        if ch.isdigit():
            digits += ch
        elif digits:
            return int(digits) - 1 if '回合' in str(text)[at:] else None
    return None


def short_quarter_label(label, phase=None):
    text = str(label or '')
    if isinstance(phase, dict) and calendar_label(phase.get('year_u16'), phase.get('season_u16')):
        return phase_label(phase)
    year = _year_from_text(text)
    season = _digits_after(text, '季候选')
    if season is None:
        season = _digits_after(text, '季')
    if season is None:
        for idx, name in SEASON_CN.items():
            if name in text:
                season = idx
                break
    pretty = calendar_label(year, season)
    if pretty:
        if '内政' in text:
            return pretty + ' · 内政'
        rnd = _round_from_text(text)
        if rnd is not None:
            return f'{pretty} 第{rnd + 1}回合'
        return pretty
    return text.replace('（已过季）', '').replace('（进行中）', '').strip() or '—'


def sortie_has_ambush(unit, state=None):
    """True only when a readable skill source includes 伏兵. Unknown stays false."""
    from native_unit_rules import AMBUSH, general_skill_mask
    unit = unit or {}
    mask = unit.get('effective_skill_mask')
    known = False
    ambush = False
    if type(mask) is int and 0 <= mask <= 0xffffffff:
        known = True
        ambush = bool(mask & AMBUSH)
    else:
        ids = [gid for gid in unit.get('general_ids') or [] if type(gid) is int and gid >= 0]
        generals = ((state or {}).get('entities') or {}).get('generals') or []
        for gid in ids:
            matches = [row for row in generals if row.get('general_id_raw') == gid]
            if len(matches) != 1:
                continue
            value = general_skill_mask(matches[0])
            if type(value) is not int:
                continue
            known = True
            ambush = ambush or bool(value & AMBUSH)
    if ambush:
        return True
    if known or not state:
        return False
    try:
        from officer_sortie import unit_has_ambush
    except ImportError:
        return False
    return bool(unit_has_ambush(state, unit))


def _snapshot_skill_mask(unit, state):
    from native_unit_rules import general_skill_mask
    ids = [gid for gid in (unit or {}).get('general_ids') or [] if type(gid) is int and gid >= 0]
    if not ids:
        return None
    generals = ((state or {}).get('entities') or {}).get('generals') or []
    mask = 0
    for gid in ids:
        matches = [row for row in generals if row.get('general_id_raw') == gid]
        if len(matches) != 1:
            return None
        value = general_skill_mask(matches[0])
        if type(value) is not int:
            return None
        mask |= value
    return mask


def _snapshot_ability(unit, state):
    ids = [gid for gid in (unit or {}).get('general_ids') or [] if type(gid) is int and gid >= 0]
    generals = ((state or {}).get('entities') or {}).get('generals') or []
    values = []
    for gid in ids:
        matches = [row for row in generals if row.get('general_id_raw') == gid]
        if len(matches) != 1:
            return None
        attrs = matches[0].get('attributes') or {}
        lead, war = attrs.get('lead'), attrs.get('war')
        if type(lead) is not int or type(war) is not int or not 0 <= lead <= 255 or not 0 <= war <= 255:
            return None
        word = matches[0].get('combat_modifier_flags_word')
        flags = matches[0].get('combat_modifier_flags')
        if type(flags) is not int and type(word) is int and 0 <= word <= 65535:
            flags = word & 255
        if type(flags) is not int or not 0 <= flags <= 255:
            flags = 0
        lead += lead * 2 // 5 if flags & 0x10 else 0
        war += war * 2 // 5 if flags & 0x20 else 0
        values.append((lead, war))
    if not 1 <= len(values) <= 3:
        return None
    lead = values[0][0] if len(values) == 1 else (values[0][0] + sum(v[0] for v in values[1:]) // (len(values) - 1)) // 2
    return (max(10, lead) + sum(v[1] for v in values) // len(values)) // 2


def full_morale_attack(unit, state=None):
    """Land, morale-100 native index. Unknown stays absent."""
    unit = unit or {}
    direct = unit.get('native_attack_index_full_morale')
    if type(direct) is int and direct >= 0:
        return str(direct)
    stored = unit.get('target_attack_full_morale')
    if type(stored) is str and stored not in ('', '缺参数', '—'):
        parts = stored.split('–')
        if parts and all(part.isdecimal() for part in parts):
            return stored
    from unit_target_attack import BOW, client_factor, client_kind
    from native_unit_rules import ARROW, HORSE, attack_index, proficiency_values
    kind = unit.get('unit_kind')
    name = client_kind(kind)
    soldiers = unit.get('soldiers_candidate')
    size = unit.get('size_index')
    if size not in (0, 1, 2):
        size = int(soldiers > 20000) + int(soldiers > 35000) if type(soldiers) is int and 0 <= soldiers <= 100000 else None
    training = unit.get('training_degree')
    if type(training) is not int:
        training = unit.get('armament_degree_raw')
    if size not in (0, 1, 2) or type(training) is not int or not 0 <= training <= 100:
        return None
    base = client_factor(kind, size, training)
    if base is None:
        return None
    required = ARROW if name in BOW else HORSE if name and '骑兵' in name else None
    mask = unit.get('effective_skill_mask')
    if type(mask) is not int:
        mask = _snapshot_skill_mask(unit, state)
    ability = unit.get('basic_combat_power')
    if type(ability) is not int:
        ability = _snapshot_ability(unit, state)
    if type(ability) is not int or not 0 <= ability <= 357:
        return None
    values = [attack_index(coef, ability, 100) for coef in proficiency_values(base, required, mask if type(mask) is int else None)]
    if not values or any(value is None for value in values):
        return None
    low, high = min(values), max(values)
    return str(low) if low == high else f'{low}–{high}'


def military_chip_text(item, state=None):
    item = item or {}
    line = str(item.get('line') or item.get('field') or '')
    field = str(item.get('field') or '')
    if field == '出征':
        body = line[2:].strip() if line.startswith('出征') else line
        text = '出征 ' + body.split(' 出现于')[0].strip()
        unit = item.get('unit_snapshot') or {}
        attack = unit.get('target_attack_unit')
        training = unit.get('training_degree')
        if training is None:
            training = unit.get('armament_degree_raw')
        from native_unit_rules import displays_attack
        full = full_morale_attack(unit, state)
        if full:
            text += f' · 满士气攻击{full}'
        elif displays_attack(unit) and attack not in (None, '', '—', '缺参数'):
            text += f' · 攻击{attack}'
        if type(training) is int and 0 <= training <= 100:
            text += f' · 训练{training}/100'
        if sortie_has_ambush(unit, state):
            text += ' · [伏兵]'
    elif field == '部队移动' and ' (' in line:
        text = line.split(' (', 1)[0]
    else:
        text = line
    return kind_line(text)


def recent_quarter_ops(history, force_id, limit=3):
    if not isinstance(history, dict):
        return []
    accounts = list(history.get('quarters') or [])
    current = history.get('current_quarter')
    if current:
        accounts.append(current)
    out = []
    for account in accounts:
        force = next((row for row in account.get('forces') or [] if row.get('owner') == force_id), None)
        ops = command_ops((force or {}).get('operations'))
        key = comparable_phase(account.get('phase'))
        if out and key is not None and comparable_phase(out[-1].get('phase')) == key:
            seen = {(item.get('field'), item.get('line')) for item in out[-1]['operations']}
            for item in ops:
                sig = (item.get('field'), item.get('line'))
                if sig not in seen:
                    out[-1]['operations'].append(item)
                    seen.add(sig)
            continue
        out.append({
            'label': account.get('label') or '',
            'phase': account.get('phase'),
            'closed': account.get('closed'),
            'operations': ops,
        })
    return out if limit is None else out[-limit:]


HIRE_FIELDS = ('录用', '主动加入')
GREEN_CARD_IDS = (12, 13, 14)
GREEN_CARD_NAMES = {12: '援助金钱', 13: '援助军粮', 14: '援助士兵'}
ALMS_MIN = 5
ALMS_MAX = 10
ALLY_RELATION = 3


def hire_quarter_lanes(history, force_id):
    """Every recorded quarter for one force, recruitment only."""
    out = []
    for block in recent_quarter_ops(history, force_id, limit=None):
        ops = block.get('operations') or []
        out.append({
            'label': block.get('label') or '',
            'short': short_quarter_label(block.get('label'), block.get('phase')),
            'phase': block.get('phase'),
            'closed': block.get('closed'),
            'hires': [item for item in ops if item.get('field') in HIRE_FIELDS],
        })
    return out


def _hand_ids(lord):
    return [slot.get('card_id') for slot in (((lord or {}).get('hand_cards') or {}).get('slots') or [])]


def _green_ids(lord):
    return [cid for cid in _hand_ids(lord) if cid in GREEN_CARD_IDS]


def _lost_green_names(before, after):
    from collections import Counter
    before_ids, after_ids = _green_ids(before), _green_ids(after)
    if len(after_ids) >= len(before_ids):
        return []
    lost = Counter(before_ids) - Counter(after_ids)
    names = []
    for cid, count in sorted(lost.items()):
        names.extend([GREEN_CARD_NAMES.get(cid, f'绿卡{cid}')] * count)
    return names


def _relations(lord):
    values = (lord or {}).get('diplomacy_relations')
    return values if isinstance(values, list) else []


def forces_allied(lords, left_id, right_id):
    if left_id == right_id or left_id is None or right_id is None:
        return False
    by_id = {lord.get('force_id'): lord for lord in lords or []}
    left, right = by_id.get(left_id), by_id.get(right_id)
    if left is None or right is None:
        return False
    left_rel, right_rel = _relations(left), _relations(right)
    return (
        (isinstance(right_id, int) and right_id < len(left_rel) and left_rel[right_id] == ALLY_RELATION)
        or (isinstance(left_id, int) and left_id < len(right_rel) and right_rel[left_id] == ALLY_RELATION)
    )


def _alliance_groups(lords):
    ids = [lord.get('force_id') for lord in lords or [] if lord.get('force_id') is not None]
    parent = {fid: fid for fid in ids}

    def find(fid):
        while parent[fid] != fid:
            parent[fid] = parent[parent[fid]]
            fid = parent[fid]
        return fid

    for left in ids:
        for right in ids:
            if left < right and forces_allied(lords, left, right):
                parent[find(right)] = find(left)
    groups = {}
    for fid in ids:
        groups.setdefault(find(fid), []).append(fid)
    return list(groups.values())


def _alms_line(before, after):
    if not isinstance(before, int) or not isinstance(after, int):
        return None
    delta = after - before
    if delta < ALMS_MIN:
        return None
    note = '，超过单次施舍 5–10，可能连续' if delta > ALMS_MAX else ''
    return f'布施：信望 {before} → {after}（+{delta}{note}）'


def prestige_command_ops(before_lords, after_lords):
    """1v1 prestige rise is 布施. With allies, a lost green card plus their rise is 赠绿卡."""
    before_by = {lord.get('force_id'): lord for lord in before_lords or [] if lord.get('force_id') is not None}
    after_by = {lord.get('force_id'): lord for lord in after_lords or [] if lord.get('force_id') is not None}
    explained = set()
    ops = []
    for group in _alliance_groups(list(after_by.values())):
        if len(group) < 2:
            continue
        givers = []
        gainers = []
        for fid in group:
            before, after = before_by.get(fid), after_by.get(fid)
            if before is None or after is None:
                continue
            names = _lost_green_names(before, after)
            if names:
                givers.append((fid, after.get('name') or before.get('name'), names))
            old, new = before.get('prestige'), after.get('prestige')
            if isinstance(old, int) and isinstance(new, int) and new > old:
                gainers.append((fid, after.get('name') or before.get('name'), old, new))
        if not givers or not gainers:
            continue
        recipients = [row for row in gainers if any(row[0] != giver[0] for giver in givers)]
        if len(givers) == 1 and len(recipients) == 1:
            giver_id, giver_name, card_names = givers[0]
            recv_id, recv_name, old, new = recipients[0]
            gift = '、'.join(card_names)
            ops.append(digest_item(
                f'赠绿卡 {gift} 给{recv_name}：信望 {old} → {new}（+{new - old}）',
                '赠绿卡', old, new, '少了绿卡，且同盟信望上升；不是引擎日志',
                command=True, owner=giver_id, name=giver_name,
            ))
            ops.append(digest_item(
                f'同盟绿卡：{giver_name}赠{gift}，信望 {old} → {new}（+{new - old}）',
                '赠绿卡', old, new, '同盟少了绿卡，同时本方信望上升；不是引擎日志',
                command=True, owner=recv_id, name=recv_name,
            ))
            explained.add(recv_id)
            continue
        giver_text = '、'.join(row[1] or '?' for row in givers)
        recv_text = '、'.join(f"{row[1]}+{row[3] - row[2]}" for row in recipients or gainers)
        for giver_id, giver_name, card_names in givers:
            ops.append(digest_item(
                f'赠绿卡 {"、".join(card_names)}：同盟信望上升（{recv_text}，未能逐张对应）',
                '赠绿卡', '', recv_text, '同季少了绿卡且同盟信望上升；对应关系不唯一',
                command=True, owner=giver_id, name=giver_name,
            ))
        for recv_id, recv_name, old, new in recipients or gainers:
            ops.append(digest_item(
                f'同盟绿卡：{giver_text}少了绿卡，信望 {old} → {new}（+{new - old}，未能逐张对应）',
                '赠绿卡', old, new, '同盟少了绿卡且本方信望上升；对应关系不唯一',
                command=True, owner=recv_id, name=recv_name,
            ))
            explained.add(recv_id)
    if len(after_by) != 2:
        return ops
    for fid, after in after_by.items():
        if fid in explained:
            continue
        before = before_by.get(fid)
        if before is None:
            continue
        line = _alms_line(before.get('prestige'), after.get('prestige'))
        if not line:
            continue
        ops.append(digest_item(
            line, '布施', before.get('prestige'), after.get('prestige'),
            '1v1 信望上涨按施舍还原，单次资料为 +5 至 +10；不是引擎日志',
            command=True, owner=fid, name=after.get('name') or before.get('name'),
        ))
    return ops


def merge_prestige_commands(history, commands):
    """Attach inferred 布施 / 赠绿卡 onto the quarter they were observed in."""
    history = history or {}
    grouped = {}
    for item in commands or []:
        grouped.setdefault(comparable_phase(item.get('phase')), []).append(item)
    accounts = [row for row in (history.get('quarters') or []) if row]
    current = history.get('current_quarter')
    if current:
        accounts.append(current)
    quarters = history.setdefault('quarters', [])
    for phase_key, items in grouped.items():
        if phase_key is None:
            continue
        account = next((row for row in accounts if comparable_phase(row.get('phase')) == phase_key), None)
        if account is None:
            sample = next((item.get('phase') for item in items if isinstance(item.get('phase'), dict)), None)
            account = {'phase': sample, 'label': phase_label(sample), 'closed': False, 'forces': []}
            quarters.append(account)
            accounts.append(account)
        forces = account.setdefault('forces', [])
        for item in items:
            owner = item.get('owner')
            force = next((row for row in forces if row.get('owner') == owner), None)
            if force is None:
                force = {'owner': owner, 'name': item.get('name'), 'operations': []}
                forces.append(force)
            ops = force.setdefault('operations', [])
            if any(op.get('field') == item.get('field') and op.get('line') == item.get('line') for op in ops):
                continue
            ops.append(item)
    return history


def load_journal_history(filetime, view_phase, *, include_same_phase=False, root=None):
    """Closed quarter ledger recorded while collecting. Later quarters stay out."""
    if filetime is None:
        return None
    folder = (Path(root) if root is not None else default_root()) / str(filetime)
    path = folder / 'quarters.jsonl'
    if not path.is_file():
        return None
    view = comparable_phase(view_phase)
    quarters = []
    current = None
    try:
        lines = path.read_text(encoding='utf8').splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            account = json.loads(line)
        except json.JSONDecodeError:
            continue
        phase = comparable_phase(account.get('phase'))
        if view is None or phase is None:
            continue
        if phase < view:
            quarters.append(account)
        elif phase == view and include_same_phase and current is None:
            current = account
    return {'quarters': quarters, 'current_quarter': current, 'source': 'journal'}


def split_quarter_lanes(history, force_id, limit=3):
    out = []
    for block in recent_quarter_ops(history, force_id, limit):
        ops = block.get('operations') or []
        out.append({
            'label': block.get('label') or '',
            'short': short_quarter_label(block.get('label'), block.get('phase')),
            'phase': block.get('phase'),
            'closed': block.get('closed'),
            'civil': [item for item in ops if is_civil_op(item)],
            'military': [item for item in ops if is_military_op(item)],
        })
    return out


def decorate(rows, snapshot):
    when = format_when(snapshot)
    out = []
    for row in rows:
        item = dict(row)
        item.setdefault('time', snapshot.get('capture_end'))
        item.setdefault('when', when)
        item.setdefault('phase', snapshot.get('phase_candidate'))
        out.append(item)
    return out


def attach_history(payload, journal):
    if not payload.get('state'):
        return payload
    result = dict(payload)
    doc = dict(payload['state'])
    identity = payload.get('player_identity') or {}
    doc['history'] = journal.observe(doc, session=identity.get('session_id'),
                                    player_force_id=payload.get('player_force_id'))
    result['state'] = doc
    return result


class History:
    def __init__(self, root):
        self.root = Path(root)
        self.prev = None
        self.baseline = None
        self.recent = []
        self.last_quarter = None
        self.quarters = []
        self.troop_series = []
        self.camp_builds = []
        self.captured_at = {}
        self.observe_seq = 0
        self.identity = None

    def directory(self, ident):
        stamp = ident.get('creation_filetime')
        name = str(stamp) if stamp not in (None, '') else 'unknown'
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def observe(self, state, session=None, player_force_id=None):
        self.player_force_id = player_force_id
        current = slim(state)
        ident = current['identity']
        directory = self.directory(ident)
        if self.identity != ident:
            self.prev = None
            self.baseline = None
            self.recent = []
            self.last_quarter = None
            self.quarters = []
            self.troop_series = []
            self.camp_builds = []
            self.captured_at = {}
            self.observe_seq = 0
            self.identity = ident
            self._resume(directory, ident, current)
            self._sanitize_accounts()
            if not self.troop_series and self.baseline:
                self._note_troop_series(self.baseline)
        if self.prev is None:
            self.prev = current
            self.baseline = current
            self.observe_seq = max(self.observe_seq, 1)
            self._note_troop_series(current)
            self.save(directory, current)
            return self.summary(current, session, player_force_id)
        previous_phase = comparable_phase(self.prev['phase_candidate'])
        current_phase = comparable_phase(current['phase_candidate'])
        if previous_phase and current_phase and current_phase < previous_phase:
            self._archive(directory, 'rollback')
            self.prev = current
            self.baseline = current
            self.recent = []
            self.last_quarter = None
            self.quarters = []
            self.troop_series = []
            self.camp_builds = []
            self.captured_at = {}
            self.observe_seq = 1
            self._note_troop_series(current)
            self.save(directory, current)
            return self.summary(current, session, player_force_id)
        if self.baseline is None:
            self.baseline = self.prev
        changes = differences(self.prev, current)
        if previous_phase is not None and current_phase is not None:
            boundary = previous_phase != current_phase
        else:
            boundary = self.prev['phase_candidate'] != current['phase_candidate']
        if changes or boundary:
            gap = _gap_seconds(self.prev.get('capture_end'), current.get('capture_end'))
            event = {
                'from': self.prev.get('capture_end'), 'to': current.get('capture_end'),
                'phase_before': self.prev['phase_candidate'], 'phase_after': current['phase_candidate'],
                'phase_boundary_candidate': boundary, 'sampling_gap_seconds': gap,
                'changes': changes, 'action_sequence_verified': False,
            }
            with (directory / 'changes.jsonl').open('a', encoding='utf8') as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + '\n')
            when = format_when(current)
            for item in changes:
                self.recent.append({**item, 'time': current.get('capture_end'), 'when': when,
                                    'phase': current['phase_candidate'], 'gap_seconds': gap,
                                    'sample_start': self.prev.get('capture_end'),
                                    'phase_before': self.prev['phase_candidate'],
                                    'phase_after': current['phase_candidate']})
            self.recent = self.recent[-800:]
            if boundary:
                opening = comparable_phase((self.baseline or self.prev).get('phase_candidate'))
                founding = not self.quarters and opening is not None and opening[1] == 0
                closed = quarter_account(self.baseline or self.prev, current, closed=True,
                                        player_force_id=player_force_id, founding=founding)
                from command_phase_values import settlement_sample
                sample = settlement_sample(self.prev, current)
                if sample is not None:
                    closed['settlement_sample'] = sample
                self.last_quarter = closed
                self.quarters.append(closed)
                self.quarters = self.quarters[-80:]
                with (directory / 'quarters.jsonl').open('a', encoding='utf8') as handle:
                    handle.write(json.dumps(closed, ensure_ascii=False) + '\n')
                for item in closed['rows']:
                    self.recent.append({**item, 'time': current.get('capture_end'),
                                        'when': item.get('when') or when,
                                        'phase': closed.get('phase'), 'gap_seconds': gap})
                self.recent = self.recent[-800:]
                self.baseline = current
            self.save(directory, current)
        repaired = self._repair_hires(current)
        built = self._note_camp_builds(self.prev, current)
        if repaired or generals_schema_upgrade(self.prev, current):
            self.save(directory, current)
        self.prev = current
        if self._note_troop_series(current) or built:
            self.save(directory, current)
        return self.summary(current, session, player_force_id)

    def _resume(self, directory, ident, current):
        checkpoint = directory / 'last.json'
        if not checkpoint.is_file():
            return
        try:
            old = json.loads(checkpoint.read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError):
            return
        if old.get('identity_key') != ident:
            return
        saved = old.get('current')
        if not isinstance(saved, dict):
            return
        old_phase = comparable_phase((saved.get('phase_candidate') or {}))
        now_phase = comparable_phase(current['phase_candidate'])
        if old_phase and now_phase and now_phase < old_phase:
            return
        self.prev = saved
        self.baseline = old.get('baseline') or saved
        self.recent = list(old.get('recent') or [])
        self.last_quarter = old.get('last_quarter')
        self.quarters = list(old.get('quarters') or [])
        self.troop_series = list(old.get('troop_series') or [])
        self.camp_builds = list(old.get('camp_builds') or [])
        self.captured_at = decode_captured_at(old.get('captured_at'))
        self.observe_seq = old.get('observe_seq') or 0
        if self.last_quarter and not self.quarters:
            self.quarters = [self.last_quarter]
        self._sanitize_accounts()

    def _sanitize_accounts(self):
        changed = False
        player = getattr(self, 'player_force_id', None)
        mark_opening_founding(self.quarters)
        if self.last_quarter:
            match = next((row for row in self.quarters if row.get('label') == self.last_quarter.get('label')), None)
            if match is not None:
                self.last_quarter['founding'] = bool(match.get('founding'))
        for account in self.quarters:
            before = [item.get('line') for force in account.get('forces') or []
                      for item in force.get('operations') or []]
            refresh_account(account, player)
            after = [item.get('line') for force in account.get('forces') or []
                     for item in force.get('operations') or []]
            if before != after:
                changed = True
        if self.last_quarter:
            before = [item.get('line') for force in self.last_quarter.get('forces') or []
                      for item in force.get('operations') or []]
            refresh_account(self.last_quarter, player)
            after = [item.get('line') for force in self.last_quarter.get('forces') or []
                     for item in force.get('operations') or []]
            if before != after:
                changed = True
            for index, account in enumerate(self.quarters):
                if account.get('label') == self.last_quarter.get('label'):
                    self.quarters[index] = self.last_quarter
                    break
        return changed

    def _repair_hires(self, current):
        changed = self._sanitize_accounts()
        if not self.last_quarter:
            return changed
        already = recorded_hires(list(self.quarters) + [self.last_quarter])
        if attach_pending_hires(self.last_quarter, current, already, getattr(self, 'player_force_id', None)):
            changed = True
            for index, account in enumerate(self.quarters):
                if account.get('label') == self.last_quarter.get('label'):
                    self.quarters[index] = self.last_quarter
                    break
        return changed

    def _archive(self, directory, reason):
        checkpoint = directory / 'last.json'
        if checkpoint.is_file():
            stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
            checkpoint.replace(directory / f'last-{reason}-{stamp}.json')

    def save(self, directory, current):
        payload = {
            'identity_key': self.identity,
            'current': current,
            'baseline': self.baseline,
            'recent': self.recent[-400:],
            'last_quarter': self.last_quarter,
            'quarters': self.quarters[-80:],
            'troop_series': self.troop_series[-120:],
            'camp_builds': self.camp_builds[-400:],
            'captured_at': encode_captured_at(self.captured_at),
            'observe_seq': self.observe_seq,
        }
        tmp = directory / 'last.tmp'
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf8')
        tmp.replace(directory / 'last.json')

    def summary(self, current, session, player_force_id=None):
        opening = comparable_phase((self.baseline or current).get('phase_candidate'))
        founding = not self.quarters and opening is not None and opening[1] == 0
        current_account = quarter_account(self.baseline or current, current, closed=False,
                                         player_force_id=player_force_id, founding=founding)
        quarter_rows = []
        digests = []
        for account in self.quarters:
            quarter_rows.extend(account.get('rows') or [])
            if account.get('digest'):
                digests.append(account['digest'])
        quarter_rows.extend(current_account.get('rows') or [])
        quarter_rows = [row for row in quarter_rows if not is_auto_recruit_op(row)]
        if current_account.get('digest'):
            digests.append(current_account['digest'])
        census = census_rows(self.baseline or current, current)
        nets = [row for row in current_account.get('rows') or [] if not row.get('flat')]
        return {
            'player_session_id': session,
            'recording_since': (self.baseline or current).get('capture_end'),
            'phase_candidate': current.get('phase_candidate'),
            'phase_label': phase_label(current.get('phase_candidate')),
            'phase_label_verified': False,
            'coverage': '按年/季候选为每个势力封存操作账；不是完整指令日志',
            'banner': banner_text(current, self.quarters, len(lord_map(current))),
            'digest': '\n\n————\n\n'.join(digests),
            'census_rows': decorate(census, current),
            'quarter_rows': quarter_rows,
            'quarters': self.quarters,
            'current_quarter': current_account,
            'recent_changes': decorate(list(reversed(self.recent)), current),
            'phase_net_changes': decorate(nets, current),
            'last_quarter': self.last_quarter,
            'troop_series': self.troop_series[-120:],
            'camp_builds': self.camp_builds[-400:],
            'actions_verified': False,
            'phase_boundary_note': '跨季间隔内变化可能分属两季，不会全部归给新季',
        }

    def _note_troop_series(self, state):
        import sys
        app = Path(__file__).resolve().parent.parent / 'app'
        if str(app) not in sys.path:
            sys.path.insert(0, str(app))
        try:
            from force_troop_totals import append_troop_series, troop_series_point
        except ImportError:
            return False
        point = troop_series_point(state)
        if self.troop_series and self.troop_series[-1] == point:
            return False
        self.troop_series = append_troop_series(self.troop_series, point)
        return True

    def _note_camp_builds(self, prev, current):
        self.observe_seq = (self.observe_seq or 0) + 1
        seq = self.observe_seq
        changed = False
        ids = set(lord_map(prev)) | set(lord_map(current))
        when = format_when(current)
        label = phase_label(current.get('phase_candidate'))
        for fid in ids:
            if fid is None:
                continue
            acc = synthesize_force(
                prev, current, fid,
                ignore_city_ids=recent_capture_ids(fid, self.captured_at, seq),
            )
            for item in acc.get('operations') or []:
                if not is_camp_build_op(item):
                    continue
                self.camp_builds.append(camp_build_record(
                    {**item, 'owner': fid, 'name': acc.get('name'),
                     'phase': current.get('phase_candidate'), 'seq': seq},
                    when=when, label=label,
                ))
                changed = True
        for fid in ids:
            if fid is None:
                continue
            gained = captured_city_ids(prev, current, fid)
            if not gained:
                continue
            names = city_names_for_ids(current, gained)
            before = len(self.camp_builds)
            self.camp_builds = drop_capture_transfer_builds(
                self.camp_builds, fid, gained, names, seq,
            )
            if len(self.camp_builds) != before:
                changed = True
        record_city_captures(prev, current, seq, self.captured_at)
        self.camp_builds = self.camp_builds[-400:]
        return changed


def _gap_seconds(before, after):
    if not before or not after:
        return None
    try:
        return (datetime.fromisoformat(after) - datetime.fromisoformat(before)).total_seconds()
    except ValueError:
        return None
