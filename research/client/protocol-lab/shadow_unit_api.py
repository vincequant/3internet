#!/usr/bin/env python3
"""Headless unit read/write API for the shadow client (Hub-side editor backend).

Why this exists (2026-10-19): the in-wine card panel (p53_unit_inspector) draws its
skin fine but *all text* is missing inside this Wine build (DrawTextW onto the skin
DIB renders nothing, even with a font the prefix actually has), so the operator
cannot read or edit values there. This CLI is the same logic without any GUI: the
Hub (macOS/Web) asks it for a JSON list of units and posts new values back.

Read path : p53_unit_data.capture_map (map/unit snapshot, read-only)
Write path: p53_unit_inspector.ReadOnlyGame.edit_unit / edit_general
            (verified object type, native clamp, VirtualProtectEx -> write -> readback)

Subcommands (run with the Wine python inside prefix-fengye-shadow):
  list                 -> {"ok":true,"units":[...],"context":{...}}
  set   --addr A --field F --value N
  setgen --gid G --field F --value N
  revert               -> undo the last write recorded in the pending file
  state                -> link/scene/seat snapshot (same fields as shadow_status)

Every write is appended to logs/unit-edit-api.jsonl and the undo record to
unit-edit-pending.json. Values are clamped to the ranges verified in p53_unit_model.
Only the shadow client's own process is touched (never the host or other players).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def log_path() -> Path:
    return HERE.parent / 'logs' / 'unit-edit-api.jsonl'


def pending_path() -> Path:
    return HERE.parent / 'unit-edit-pending.json'


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def append_log(value):
    value = dict(value)
    value.setdefault('wall', time.time())
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + '\n')


def open_reader(bridge, pid=None):
    from p53_unit_inspector import ReadOnlyGame
    return ReadOnlyGame(bridge, pid)


def field_rows(reader, address):
    from p53_unit_model import FIELDS
    rows = []
    for key, meta in FIELDS.items():
        label, offset, fmt, maximum = meta[:4]
        try:
            value = reader.unit_field(address, key)
        except Exception as error:
            rows.append(dict(key=key, label=label, value=None, max=maximum,
                             editable=False, error=repr(error)))
            continue
        rows.append(dict(key=key, label=label, value=value, max=maximum, editable=True))
    return rows


def unit_entry(reader, unit):
    address = int(unit['address'])
    entry = dict(address=hex(address), kind=unit.get('kind'),
                 vtable=unit.get('vtable'), unit_id=unit.get('unit_id'),
                 owner_raw=unit.get('owner_raw'), xy=unit.get('world_xy_raw'),
                 general_ids=unit.get('general_ids'),
                 order_type_raw=unit.get('order_type_raw'),
                 fields=field_rows(reader, address))
    generals = []
    for gid in (unit.get('general_ids') or []):
        if not isinstance(gid, int):
            continue
        try:
            stats = reader.general_stats(gid)
        except Exception as error:
            stats = None
            entry.setdefault('general_errors', []).append(repr(error))
        if stats:
            generals.append(dict(general_id=gid, address=hex(stats['address']),
                                 values=stats['values'], blade_total=stats['blade_total']))
        else:
            generals.append(dict(general_id=gid, address=None, values=None))
    entry['generals'] = generals
    return entry


def cmd_list(args):
    reader = open_reader(args.bridge, args.pid)
    try:
        snapshot = reader.capture()
        units = [unit_entry(reader, u) for u in snapshot.get('units', [])]
        emit(dict(ok=True, readonly=True, editable=True,
                  write_scope='shadow client pid only',
                  identity=reader.identity,
                  context=snapshot.get('context'),
                  units=units, count=len(units), wall=time.time()))
    finally:
        reader.close()


def cmd_set(args):
    reader = open_reader(args.bridge, args.pid)
    try:
        address = int(args.addr, 0)
        record = reader.edit_unit(address, args.field, args.value)
        record['unit_id'] = args.unit_id
        append_log(record)
        pending_path().write_text(json.dumps(dict(
            scope='unit', address=address, field=args.field,
            before=record['before'], at=time.time()), ensure_ascii=False))
        emit(dict(ok=record.get('ok', False), edit=record, wall=time.time()))
    finally:
        reader.close()


def cmd_setgen(args):
    reader = open_reader(args.bridge, args.pid)
    try:
        record = reader.edit_general(args.gid, args.field, args.value)
        append_log(record)
        pending_path().write_text(json.dumps(dict(
            scope='general', general_id=args.gid, field=args.field,
            before=record['before'], at=time.time()), ensure_ascii=False))
        emit(dict(ok=record.get('ok', False), edit=record, wall=time.time()))
    finally:
        reader.close()


def resolve_unit(reader, owner, unit_id, xy=None):
    """Find the live unit object matching a Hub row (owner + unit_id, optional xy)."""
    snapshot = reader.capture()
    best = None
    for unit in snapshot.get('units', []):
        if owner is not None and unit.get('owner_raw') != owner:
            continue
        if unit_id is not None and unit.get('unit_id') != unit_id:
            continue
        if xy and list(unit.get('world_xy_raw') or [])[:2] != list(xy)[:2]:
            continue
        best = unit
        break
    if best is None:
        raise ValueError('找不到该部队（owner=%s unit_id=%s）；先刷新一次' % (owner, unit_id))
    return best


def cmd_set_unit(args):
    reader = open_reader(args.bridge, args.pid)
    try:
        unit = resolve_unit(reader, args.owner, args.unit_id)
        record = reader.edit_unit(int(unit['address']), args.field, args.value)
        record['unit_id'] = unit.get('unit_id')
        record['owner_raw'] = unit.get('owner_raw')
        append_log(record)
        pending_path().write_text(json.dumps(dict(
            scope='unit', address=int(unit['address']), field=args.field,
            before=record['before'], at=time.time()), ensure_ascii=False))
        emit(dict(ok=record.get('ok', False), edit=record, wall=time.time()))
    finally:
        reader.close()


def cmd_revert(args):
    path = pending_path()
    if not path.is_file():
        emit(dict(ok=False, error='no pending write'))
        return 1
    pending = json.loads(path.read_text())
    reader = open_reader(args.bridge, args.pid)
    try:
        if pending['scope'] == 'general':
            record = reader.edit_general(pending['general_id'], pending['field'], pending['before'])
        else:
            record = reader.edit_unit(pending['address'], pending['field'], pending['before'])
        record.update(kind='edit_revert', restored=pending['before'])
        append_log(record)
        path.unlink(missing_ok=True)
        emit(dict(ok=True, edit=record, wall=time.time()))
    finally:
        reader.close()


def cmd_state(args):
    from p53_unit_data import context as read_context
    reader = open_reader(args.bridge, args.pid)
    try:
        ctx = read_context(reader.memory.read)
        emit(dict(ok=True, identity=reader.identity, context=ctx, wall=time.time()))
    finally:
        reader.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--pid', type=int)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    sub.add_parser('state')
    sub.add_parser('revert')
    u = sub.add_parser('set-unit')
    u.add_argument('--owner', type=int, required=True)
    u.add_argument('--unit-id', type=int, required=True)
    u.add_argument('--field', required=True)
    u.add_argument('--value', type=int, required=True)
    p = sub.add_parser('set')
    p.add_argument('--addr', required=True, help='unit address, e.g. 0x4400700')
    p.add_argument('--unit-id', type=int, default=None)
    p.add_argument('--field', required=True)
    p.add_argument('--value', type=int, required=True)
    g = sub.add_parser('setgen')
    g.add_argument('--gid', type=int, required=True)
    g.add_argument('--field', required=True)
    g.add_argument('--value', type=int, required=True)
    args = ap.parse_args(argv)
    try:
        return {'list': cmd_list, 'set': cmd_set, 'set-unit': cmd_set_unit, 'setgen': cmd_setgen,
                'revert': cmd_revert, 'state': cmd_state}[args.cmd](args) or 0
    except Exception as error:
        emit(dict(ok=False, error=repr(error), wall=time.time()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
