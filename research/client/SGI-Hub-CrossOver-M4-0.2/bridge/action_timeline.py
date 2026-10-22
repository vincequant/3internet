"""Presentation union of verified packets and explicitly labeled observations.

This never edits evidence, commits orders, or produces training action labels.
Only unique object/operand matches merge; seasonal aggregate changes are notes,
not another counted instruction. Unknown native types stay in packet details.
"""
from copy import deepcopy
import json
from pathlib import Path

from command_display import command_groups, general_name
from state_history import (is_civil_op, is_military_op, military_chip_text,
                           recent_quarter_ops, SEASON_CN)

CARD_NAMES = json.loads((Path(__file__).resolve().parents[1] / 'app' / 'card_catalog.json').read_text(encoding='utf8'))['names']
TROOPS = {0: '步兵', 1: '骑兵', 2: '弓兵', 3: '运输兵'}


def card_name(value):
    return CARD_NAMES.get(str(value), f'卡片#{value}')


def force_name(value, entities):
    names = [r.get('name') for r in entities.get('lords') or []
             if r.get('force_id') == value and r.get('name')]
    return names[0] if len(names) == 1 else f'势力#{value}'


def diplomacy_text(row, entities):
    """Flags are selected cards, not the post-action hand in cards_raw.

    0x43b401/0x4a03da copy selected card vfunc+0x14 into flags.
    0x43b76e/0x4a1692 build subtype1 replies. Flag30 is the Yes reply
    from 0x4a1689; it is an internal response code, not a played card.
    """
    subtype = row.get('subtype')
    if subtype not in (0, 1):
        return None
    flags = row.get('flags_raw') or []
    cards = [c for c in flags if c]
    if subtype == 1:
        reply = '接受' if cards == [30] else '、'.join(card_name(c) if c <= 28 else f'回应#{c}' for c in cards)
        text = '外交回应' + (' '+reply if reply else '')
    else:
        text = '外交 ' + ('、'.join(card_name(c) for c in cards) or '卡片未确认')
    other = row.get('other_raw')
    if type(other) is int and 0 <= other < 32:
        text += ' → ' + force_name(other, entities)
    target = row.get('other2_raw')
    if subtype == 0 and 7 in cards and type(target) is int and target >= 0:
        text += ' · ' + general_name(target, entities.get('generals') or [])
    return text


def sortie_text(row, entities):
    names = [general_name(g, entities.get('generals') or []) for g in row.get('general_ids_raw') or [] if g >= 0]
    text = '出征 '+TROOPS.get(row.get('troop_kind_raw'), '兵种未确认')
    if names:
        text += '（'+'、'.join(names)+'）'
    if type(row.get('soldiers_raw')) is int:
        text += f' · 兵{row["soldiers_raw"]:,}'
    return text


def _sortie_match(row, item, entities):
    if row.get('display_source'):
        return False  # Peer bytes must not acquire this host's state values.
    unit = item.get('unit_snapshot') or {}
    wanted = [g for g in row.get('general_ids_raw') or [] if g >= 0]
    if not wanted:
        return False
    if unit:
        return (wanted == [g for g in unit.get('general_ids') or [] if g is not None and g >= 0]
                and unit.get('owner_raw') == row.get('actor_force_id')
                and unit.get('soldiers_candidate') == row.get('soldiers_raw'))
    # Legacy ledgers retained names but no IDs. Match only exact unique names,
    # never a recycled unit ID or today's force ownership.
    generals = entities.get('generals') or []
    names = [general_name(g, generals) for g in wanted]
    if any(n.startswith('武将#') or sum(g.get('name') == n for g in generals) != 1 for n in names):
        return False
    line = item.get('line') or ''
    return '（'+'、'.join(names)+'）' in line


def _category(row):
    kind, sub = row.get('native_type'), row.get('subtype')
    if kind == 18 and sub == 0:
        return {0:'训练步兵', 1:'训练骑兵', 2:'训练弓兵'}.get(row.get('parameter_raw'))
    if kind == 18 and sub == 2:
        return '布施'
    if kind == 18 and sub == 4:
        return {7:'新建练兵所', 8:'新建牧场', 9:'新建弓工坊'}.get(row.get('parameter_raw'))
    return None


def timeline_groups(rows, history, force_id, entities=None):
    """Two lanes, newest season first; numbering is display order, not quota proof."""
    entities = entities or {}
    groups = {}
    def group(lane, calendar):
        return groups.setdefault((lane, calendar), dict(lane=lane, calendar=calendar,
            label=(f'{calendar[0]}年{SEASON_CN[calendar[1]]}' if calendar else '日期未确认'),
            entries=[], automatic_joins=[], responses=[], notes=[]))
    for block in command_groups([r for r in rows if r.get('actor_force_id') == force_id], history):
        if block['lane'] not in ('civil', 'military'):
            continue
        dest = group(block['lane'], block['calendar'])
        for row in sorted(block['rows'], key=lambda r:r.get('observed_at') or ''):
            entry = dict(raw=row, observation=None, evidence='封包')
            if row.get('native_type') == 19 and row.get('subtype') == 1:
                dest['responses'].append(entry)
            else:
                dest['entries'].append(entry)
        dest['automatic_joins'].extend(dict(raw=r, observation=None, evidence='封包') for r in block['automatic_joins'])
    for account in recent_quarter_ops(history or {}, force_id, None):
        phase = account.get('phase') or {}
        y, s = phase.get('year_u16'), phase.get('season_u16')
        calendar = (y, s) if type(y) is int and y > 0 and type(s) is int and s in SEASON_CN else None
        for original in account.get('operations') or []:
            item = deepcopy(original)
            field = item.get('field')
            if not is_civil_op(item) and not is_military_op(item):
                continue
            lane = 'civil' if is_civil_op(item) or field == '出征' else 'military'
            dest = group(lane, calendar)
            if field == '主动加入' or item.get('hire_kind') == '自动加入':
                gid = item.get('general_id', (item.get('target') or {}).get('general_id'))
                hits = [e for e in dest['automatic_joins'] if e['raw'] and not e['raw'].get('display_source')
                        and e['raw'].get('target_raw') == gid and gid is not None]
                if len(hits) == 1:
                    hits[0].update(observation=item, evidence='封包＋观察')
                else:
                    dest['automatic_joins'].append(dict(raw=None, observation=item, evidence='观察'))
                continue
            hits = []
            if field == '出征':
                hits = [e for e in dest['entries'] if e['raw'] and e['raw'].get('native_type') == 16
                        and _sortie_match(e['raw'], item, entities)]
                # Two packet candidates or another observed appearance remain
                # separate; do not hide ambiguity by matching only unused rows.
                if len(hits) == 1 and hits[0]['observation'] is None:
                    hits[0].update(observation=item, evidence='封包＋观察')
                    continue
            elif field == '录用':
                gid = item.get('general_id', (item.get('target') or {}).get('general_id'))
                cid = (item.get('target') or {}).get('city_id')
                hits = [e for e in dest['entries'] if e['raw'] and e['raw'].get('native_type') == 20
                        and not e['raw'].get('display_source')
                        and e['raw'].get('subtype') == 0 and cid is not None
                        and e['raw'].get('target_raw') == cid
                        and ((e['raw'].get('personnel_reference') or {}).get('result') or {}).get('general_id') == gid
                        and gid is not None]
                if len(hits) == 1 and hits[0]['observation'] is None:
                    hits[0].update(observation=item, evidence='封包＋观察')
                    continue
            else:
                hits = [e for e in dest['entries'] if e['raw'] and not e['raw'].get('display_source') and _category(e['raw']) == field]
                if hits:
                    # Quarter observations may span several commands; retain
                    # their before/after once, without inventing another order.
                    dest['notes'].append(item)
                    continue
            entry = dict(raw=None, observation=item, evidence='观察')
            if field == '部队消失' or str(field).startswith(('得', '失')):
                dest['notes'].append(item)
            else:
                dest['entries'].append(entry)
    return sorted(groups.values(), key=lambda g:(g['calendar'] is not None,g['calendar'] or (0,0)), reverse=True)


def observation_text(item, state=None):
    if item.get('field') == '主动加入':
        return '自动加入：'+str(item.get('after') or '')
    return military_chip_text(item, state)
