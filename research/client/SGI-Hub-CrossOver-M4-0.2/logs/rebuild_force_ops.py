"""Rebuild inferred force-ops from player archives. Capture-transfer camps are not 新建."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bridge'), str(ROOT / 'app')]

from force_strength import force_attack_rows
from game_archive import ArchiveReader, list_archives
from match_opening import first_locked_seq, listed_archive
from replay_view import ReplayCursor, command_line_text, is_replay_command
from state_history import is_civil_op, is_military_op, phase_label, phase_round


def city_map(state):
    names = {row.get('force_id'): row.get('name') or f"势力{row.get('force_id')}"
             for row in ((state.get('entities') or {}).get('lords') or [])}
    out = {}
    for city in ((state.get('entities') or {}).get('cities_and_barriers') or []):
        owner = city.get('owner_raw')
        label = names.get(owner, str(owner))
        out.setdefault(label, []).append(city.get('name') or f"城{city.get('city_id')}")
    return out


def dump_archive(path, opening_seq):
    ReplayCursor._advance_tracks = lambda self, seq, state: None
    cur = ReplayCursor(path)
    try:
        n = cur.frame_count()
        cur._ensure(n)
        last = cur.frame_state(n, clone=False)
        manifest = cur.manifest()
        by_owner = {}
        for item in cur._events:
            if not is_replay_command(item):
                continue
            seq = item.get('seq') or 0
            if opening_seq and seq < opening_seq:
                continue
            owner = item.get('owner')
            if owner is None:
                continue
            phase = item.get('phase') or {}
            lane = 'civil' if is_civil_op(item) else ('military' if is_military_op(item) else 'other')
            by_owner.setdefault(owner, {
                'name': item.get('name'),
                'owner': owner,
                'fields': Counter(),
                'ops': [],
            })
            field = item.get('field')
            by_owner[owner]['fields'][field] += 1
            if item.get('name'):
                by_owner[owner]['name'] = item.get('name')
            by_owner[owner]['ops'].append({
                'seq': seq,
                'label': phase_label(phase),
                'lane': lane,
                'field': field,
                'line': command_line_text(item),
                'year': phase.get('year_u16'),
                'season': phase.get('season_u16'),
                'round': phase_round(phase),
            })
        lords = ((last.get('entities') or {}).get('lords') or [])
        forces = []
        for lord in lords:
            fid = lord.get('force_id')
            block = by_owner.get(fid) or {
                'name': lord.get('name'), 'owner': fid, 'fields': Counter(), 'ops': [],
            }
            forces.append({
                'name': lord.get('name') or block['name'],
                'owner': fid,
                'count': len(block['ops']),
                'fields': dict(block['fields']),
                'ops': block['ops'],
            })
        return {
            'opening': opening_seq,
            'frames': n,
            'title': manifest.get('title'),
            'match_id': manifest.get('match_id'),
            'attack': [row['line'] for row in force_attack_rows(last)],
            'cities': city_map(last),
            'forces': forces,
        }
    finally:
        cur.close()


def main():
    out_dir = ROOT / 'logs'
    written = []
    for row in list_archives(ROOT / 'game-archives'):
        if not listed_archive(row):
            continue
        path = Path(row['directory'])
        print('rebuild', row.get('title'), flush=True)
        with ArchiveReader(path) as reader:
            locked = first_locked_seq(path, reader)
        data = dump_archive(path, locked)
        match = (data.get('match_id') or path.name.split('-')[-1])[:8]
        dest = out_dir / f'force-ops-{match}.json'
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
        written.append(str(dest))
        civil = {}
        for force in data['forces']:
            kinds = Counter(op['field'] for op in force['ops'] if op.get('lane') == 'civil')
            civil[force['name']] = dict(kinds)
        print('  civil', civil, flush=True)
    print('wrote', written)


if __name__ == '__main__':
    main()
