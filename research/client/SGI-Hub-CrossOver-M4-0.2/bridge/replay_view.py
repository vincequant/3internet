"""Cursor-bounded replay analysis. Never reads frames after the selected seq."""
import copy
from replay_training import op_provenance

from game_archive import ArchiveReader, infer_stage, phase_of
from state_history import (
    calendar_label, captured_city_ids, city_names_for_ids, differences, drop_capture_transfer_builds,
    force_heading, is_civil_op, is_military_op, lord_map, military_chip_text, nearby_capture_ids,
    phase_label, phase_round, recent_capture_ids, record_city_captures, short_quarter_label,
    slim, synthesize_force,
)

EVIDENCE_CN = {
    'fact': '事实',
    'observed_change': '观察变化',
    'inferred': '推断',
    'unknown': '未知',
}

STAGE_CN = {
    'observed_unit_motion': '本帧观察到部队位移（军事阶段证据）',
    'observed_unit_presence_change': '本帧观察到部队出现或消失',
    'no_unit_motion': '本帧无部队位移（不能据此断定内政阶段）',
    'units_present_no_motion_sample': '有部队但尚无上一帧可对照',
    'no_field_units': '本帧无出征部队',
    'unknown': '阶段未知',
}


def classify_op(item):
    if not item:
        return 'unknown'
    if item.get('via') == 'pending_hire' or item.get('evidence') == 'fact':
        return 'fact'
    if item.get('command'):
        return 'inferred'
    if item.get('field') or item.get('before') != item.get('after'):
        return 'observed_change'
    return 'unknown'


def decorate_ops(ops):
    out = []
    for item in ops or []:
        row = dict(item)
        evidence = classify_op(row)
        row['evidence'] = evidence
        row['evidence_cn'] = EVIDENCE_CN[evidence]
        row['training_provenance'] = op_provenance(row)
        out.append(row)
    return out


_NOISE_FIELDS = {
    '记录有无', '势力', '粮食', '金钱', '金', '信望', '人口', '归属', '建筑归属',
    '部队坐标', '部队兵数', '步库存', '骑库存', '弓库存', '步训练', '骑训练', '弓训练',
}


def is_replay_command(item):
    if not item:
        return False
    field = str(item.get('field') or '')
    if field in _NOISE_FIELDS:
        return False
    if item.get('command'):
        return True
    return is_civil_op(item) or is_military_op(item)


def command_line_text(item):
    if is_civil_op(item):
        return str(item.get('line') or item.get('field') or '')
    return military_chip_text(item)


def _phase_tuple(item):
    phase = (item or {}).get('phase')
    if isinstance(phase, dict):
        return (phase.get('year_u16'), phase.get('season_u16'), phase_round(phase))
    return (None, None, 0)


def _ledger_key(item):
    year, season, _rnd = _phase_tuple(item)
    return (year, season)


def _phase_for_key(key, item):
    year, season = key
    if year is None and season is None:
        return item.get('phase') if isinstance(item.get('phase'), dict) else None
    return {'year_u16': year, 'season_u16': season}


def _quarter_key_label(key, phase):
    year, season = key
    pretty = calendar_label(year, season)
    if pretty:
        return pretty
    return short_quarter_label(None, _phase_for_key(key, {'phase': phase}) or phase)


def _is_founding_join(item):
    field = str((item or {}).get('field') or '')
    if field not in ('录用', '主动加入'):
        return False
    return item.get('via') != 'pending_hire'


def force_command_ledger(events, lords=None, force_ids=None, opening_seq=1, quarters_per_force=0):
    """Group inferred commands by living force, one season block with 内政+军事."""
    wanted = set(force_ids) if force_ids else None
    living = []
    seen = set()
    for row in lords or []:
        fid = row.get('force_id')
        if fid is None or fid in seen:
            continue
        if wanted is not None and fid not in wanted:
            continue
        seen.add(fid)
        name = row.get('name') or f'势力{fid}'
        living.append({'owner': fid, 'name': name, 'heading': force_heading(name, False)})
    by_owner = {row['owner']: [] for row in living}
    for item in events or []:
        if not is_replay_command(item):
            continue
        seq = item.get('seq') or 0
        if opening_seq and seq < opening_seq:
            continue
        if _phase_tuple(item)[1] == 0 and _is_founding_join(item):
            continue
        owner = item.get('owner')
        if owner not in by_owner:
            continue
        by_owner[owner].append(item)
    out = []
    for row in living:
        buckets = {}
        order = []
        for item in by_owner[row['owner']]:
            key = _ledger_key(item)
            bucket = buckets.get(key)
            if bucket is None:
                phase = _phase_for_key(key, item)
                bucket = {
                    'phase': phase,
                    'label': _quarter_key_label(key, phase),
                    'civil': [],
                    'military': [],
                }
                buckets[key] = bucket
                order.append(key)
            if is_civil_op(item):
                bucket['civil'].append(item)
            else:
                bucket['military'].append(item)
        grouped = [buckets[key] for key in order]
        if isinstance(quarters_per_force, int) and quarters_per_force > 0:
            grouped = grouped[-quarters_per_force:]
        grouped.sort(key=lambda q: (
            (q.get('phase') or {}).get('year_u16') or 0,
            (q.get('phase') or {}).get('season_u16') or 0,
        ))
        recent = grouped
        out.append({
            **row,
            'quarters': recent,
            'command_count': sum(len(q['civil']) + len(q['military']) for q in recent),
        })
    return out


def history_command_events(history):
    if not history:
        return []
    if history.get('events'):
        return list(history.get('events') or [])
    out = []
    accounts = list(history.get('quarters') or [])
    if history.get('current_quarter'):
        accounts.append(history['current_quarter'])
    for account in accounts:
        for force in account.get('forces') or []:
            for item in force.get('operations') or []:
                row = dict(item)
                row.setdefault('owner', force.get('owner'))
                row.setdefault('name', force.get('name'))
                row.setdefault('phase', account.get('phase'))
                out.append(row)
    return out


def ledger_fingerprint(ledger):
    return tuple(
        (row.get('owner'), row.get('name'), row.get('command_count'),
         tuple((q.get('label'),
                len(q.get('civil') or []), len(q.get('military') or []),
                (q['civil'][-1].get('seq') if q.get('civil') else None),
                (q['military'][-1].get('seq') if q.get('military') else None))
               for q in row.get('quarters') or []))
        for row in ledger or []
    )


def _xy(row):
    point = (row or {}).get('world_xy_raw') or []
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return [point[0], point[1]]
    return None


def locate_target(state, change):
    """Never guess the first of several same-kind hits."""
    attached = change.get('target')
    if attached and (
        attached.get('unit_id') is not None
        or attached.get('city_id') is not None
        or attached.get('object_id_candidate') is not None
        or attached.get('locatable') is False
        or attached.get('disappeared')
    ):
        return copy.deepcopy(attached)
    entity = change.get('entity')
    owner = change.get('owner')
    name = change.get('name')
    target = {'kind': entity, 'name': name, 'owner': owner, 'locatable': False}
    ents = (state or {}).get('entities') or {}
    if entity == 'field_units':
        wanted = attached.get('unit_id') if attached else change.get('unit_id')
        rows = list(ents.get('field_units') or [])
        if wanted is not None:
            hits = [row for row in rows if row.get('unit_id') == wanted]
        else:
            hits = [row for row in rows if row.get('owner_raw') == owner and row.get('unit_kind') == name]
        if len(hits) == 1:
            target.update(unit_id=hits[0].get('unit_id'), world_xy_raw=_xy(hits[0]), locatable=True)
        else:
            target['identity_uncertain'] = True
    elif entity == 'cities_and_barriers':
        wanted = (attached or {}).get('city_id')
        hits = [row for row in ents.get('cities_and_barriers') or []
                if (wanted is not None and row.get('city_id') == wanted) or (wanted is None and row.get('name') == name)]
        if len(hits) == 1:
            target.update(city_id=hits[0].get('city_id'), world_xy_raw=_xy(hits[0]), locatable=True)
        else:
            target['identity_uncertain'] = True
    elif entity == 'production_buildings':
        wanted = (attached or {}).get('object_id_candidate')
        hits = [row for row in ents.get('production_buildings') or []
                if wanted is not None and row.get('object_id_candidate') == wanted]
        if len(hits) == 1:
            target.update(world_xy_raw=_xy(hits[0]), linked_city_id=hits[0].get('linked_city_id'),
                          object_id_candidate=hits[0].get('object_id_candidate'), locatable=True)
        else:
            target['identity_uncertain'] = True
    return target


def change_to_event(change, seq, after_state, prev_state=None):
    line = change.get('line')
    if not line:
        line = f"{change.get('name') or ''} {change.get('field') or ''} {change.get('before')}→{change.get('after')}".strip()
    target = change.get('target') or locate_target(after_state if after_state and not (change.get('target') or {}).get('disappeared') else prev_state, change)
    item = {
        'seq': seq,
        'observation_seq': seq,
        'before_seq': None if prev_state is None else seq - 1,
        'after_seq': seq,
        'type': change.get('field'),
        'field': change.get('field'),
        'entity': change.get('entity'),
        'name': change.get('name'),
        'owner': change.get('owner'),
        'before': change.get('before'),
        'after': change.get('after'),
        'note': change.get('interpretation') or change.get('note'),
        'line': line,
        'command': bool(change.get('command')),
        'via': change.get('via'),
        'kind': change.get('kind'),
        'places': list(change.get('places') or []),
        'target': target,
        'derivation': 'inferred_command' if change.get('command') else 'adjacent_snapshot_diff',
        'phase': (after_state or {}).get('phase_candidate') if after_state else change.get('phase'),
        'stage': infer_stage(prev_state, after_state) if after_state and prev_state else None,
    }
    return decorate_ops([item])[0]


def _gap_after_set(gaps):
    return {row.get('after_seq') for row in (gaps or []) if row.get('after_seq') is not None}


def _sample_from_unit(seq, row):
    point = (row.get('world_xy_raw') or [None, None])[:2]
    return {
        'seq': seq,
        'world_xy_raw': list(point),
        'owner_raw': row.get('owner_raw'),
        'unit_kind': row.get('unit_kind'),
        'soldiers_candidate': row.get('soldiers_candidate'),
    }


def _append_track_sample(tracks, key, sample, gap=None):
    entry = tracks.setdefault(key, {'segments': []})
    segs = entry['segments']
    if not segs or gap:
        segs.append({'samples': [], 'gap_before': gap})
    segs[-1]['samples'].append(sample)


def unit_generation_tracks(states, gaps=None):
    """Split reused unit_id values and start a new segment after a recorded gap."""
    live = {}
    gen = {}
    tracks = {}
    broken = _gap_after_set(gaps)
    gap_by_after = {row.get('after_seq'): row for row in (gaps or [])}
    for seq, state in enumerate(states, 1):
        now = {}
        for row in (state.get('entities') or {}).get('field_units') or []:
            uid = row.get('unit_id')
            if uid is None:
                continue
            now[uid] = row
        for uid in list(live):
            if uid not in now:
                live.pop(uid, None)
        gap = gap_by_after.get(seq - 1) if (seq - 1) in broken else None
        for uid, row in now.items():
            prev = live.get(uid)
            if prev is None:
                gen[uid] = gen.get(uid, 0) + 1
            elif prev.get('owner_raw') != row.get('owner_raw') or prev.get('unit_kind') != row.get('unit_kind'):
                gen[uid] = gen.get(uid, 0) + 1
            key = (uid, gen.get(uid, 1))
            _append_track_sample(tracks, key, _sample_from_unit(seq, row), gap)
            live[uid] = row
    return tracks


def track_segments(entry):
    if not entry:
        return []
    if isinstance(entry, list):
        return [{'samples': entry, 'gap_before': None}]
    return list(entry.get('segments') or [])


def clip_track_entry(entry, seq):
    segs = []
    for segment in track_segments(entry):
        samples = [row for row in segment.get('samples') or [] if row.get('seq', 0) <= seq]
        if samples:
            segs.append({**segment, 'samples': samples})
    return {'segments': segs}


def select_live_track(tracks, seq, unit_id, generation=None):
    """Pick the generation present at seq. Never default to matches[0] of an old life."""
    matches = []
    for key, entry in tracks.items():
        uid, gen = key[0], key[1]
        if uid != unit_id:
            continue
        if generation is not None and gen != generation:
            continue
        clipped = clip_track_entry(entry, seq)
        samples = [row for seg in clipped['segments'] for row in seg.get('samples') or []]
        if not samples:
            continue
        matches.append({
            'unit_id': uid,
            'generation': gen,
            'segments': clipped['segments'],
            'samples': samples,
            'live_at_seq': any(row.get('seq') == seq for row in samples),
        })
    live = [row for row in matches if row['live_at_seq']]
    chosen = live if generation is None and live else matches
    if generation is not None:
        chosen = [row for row in chosen if row['generation'] == generation]
    if len(chosen) != 1:
        for row in chosen:
            row['identity_uncertain'] = True
        return chosen
    chosen[0]['identity_uncertain'] = False
    return chosen


def track_upto(tracks, seq, unit_id, generation=None):
    return select_live_track(tracks, seq, unit_id, generation=generation)


def _empty_account(phase, closed, player_force_id=None, first_seq=None):
    label = phase_label(phase) + ('（已过季）' if closed else '（进行中）')
    return {
        'phase': phase, 'label': label, 'closed': closed,
        'forces': [], 'rows': [], 'founding': False,
        'first_seq': first_seq, 'last_seq': first_seq,
    }


def _force_slot(account, owner, name, player_force_id=None):
    for force in account['forces']:
        if force.get('owner') == owner:
            return force
    force = {
        'owner': owner, 'name': name or f'势力{owner}',
        'heading': force_heading(name or f'势力{owner}', owner == player_force_id),
        'operations': [],
    }
    account['forces'].append(force)
    return force


def history_upto(states, player_force_id=None):
    """Append-only quarter ledger. Reversed later changes do not erase earlier ops."""
    if not states:
        return {'quarters': [], 'current_quarter': None, 'recent_changes': [], 'events': []}
    events = event_index(states)
    by_seq = {}
    for event in events:
        by_seq.setdefault(event.get('seq'), []).append(event)
    quarters = []
    current = _empty_account(slim(states[0]).get('phase_candidate'), False, player_force_id, first_seq=1)
    names = {}
    recent = []
    prev = None
    for seq, state in enumerate(states, 1):
        now = slim(state)
        for row in now.get('entities', {}).get('lords') or []:
            if row.get('force_id') is not None:
                names[row.get('force_id')] = row.get('name')
        if prev is not None and prev.get('phase_candidate') != now.get('phase_candidate'):
            current['closed'] = True
            current['last_seq'] = seq - 1
            current['label'] = phase_label(current.get('phase')) + '（已过季）'
            quarters.append(current)
            current = _empty_account(now.get('phase_candidate'), False, player_force_id, first_seq=seq)
        if current.get('first_seq') is None:
            current['first_seq'] = seq
        current['last_seq'] = seq
        for event in by_seq.get(seq, []):
            recent.append(event)
            owner = event.get('owner')
            name = names.get(owner) or event.get('name')
            force = _force_slot(current, owner, name, player_force_id)
            force['operations'].append(event)
        prev = now
    return {
        'quarters': quarters,
        'current_quarter': current,
        'recent_changes': recent[-200:],
        'events': events,
        'phase_label': phase_label((states[-1] or {}).get('phase_candidate') or phase_of(states[-1])),
    }


def _command_events(prev, now, seq, captured_at=None, lookahead=False):
    events = []
    ids = set(lord_map(prev)) | set(lord_map(now))
    captured_at = captured_at if captured_at is not None else {}
    pick_ids = nearby_capture_ids if lookahead else recent_capture_ids
    for fid in sorted(item for item in ids if item is not None):
        force = synthesize_force(
            prev, now, fid, ignore_city_ids=pick_ids(fid, captured_at, seq),
        )
        for item in force.get('operations') or []:
            row = dict(item)
            row.setdefault('owner', fid)
            row.setdefault('name', force.get('name'))
            events.append(change_to_event(row, seq, now, prev))
    return events


def event_index(states):
    slims = [slim(state) for state in states]
    captured_at = {}
    prev = None
    for seq, now in enumerate(slims, 1):
        if prev is not None:
            record_city_captures(prev, now, seq, captured_at)
        prev = now
    events = []
    prev = None
    for seq, now in enumerate(slims, 1):
        if prev is not None:
            for row in differences(prev, now):
                events.append(change_to_event(row, seq, now, prev))
            events.extend(_command_events(prev, now, seq, captured_at, lookahead=True))
        prev = now
    return events


def filter_forces(state, force_ids):
    if not force_ids:
        return state
    wanted = set(force_ids)
    ents = (state or {}).get('entities') or {}
    filtered = dict(ents)
    if 'lords' in ents:
        filtered['lords'] = [row for row in ents.get('lords') or [] if row.get('force_id') in wanted]
    for kind in ('field_units', 'production_buildings', 'traps', 'generals'):
        if kind in ents:
            filtered[kind] = [row for row in ents.get(kind) or []
                              if row.get('owner_raw') in wanted or row.get('force_id') in wanted]
    return {**(state or {}), 'entities': filtered}


def _unit_match_key(row):
    return (row.get('unit_id'), row.get('owner_raw'), row.get('unit_kind'))


def interpolate_units(before, after, t):
    """Lerp coordinates only. Attributes, membership and ownership stay at `before`."""
    if not before:
        return copy.deepcopy(after)
    t = max(0.0, min(1.0, float(t)))
    doc = copy.deepcopy(before)
    old_rows = list((before.get('entities') or {}).get('field_units') or [])
    new_rows = list((after.get('entities') or {}).get('field_units') or []) if after else []
    new_by = {}
    for row in new_rows:
        key = _unit_match_key(row)
        if key[0] is None or key in new_by:
            continue
        new_by[key] = row
    mixed = []
    for left in old_rows:
        item = copy.deepcopy(left)
        right = new_by.get(_unit_match_key(left))
        if right and left.get('owner_raw') == right.get('owner_raw') and left.get('unit_kind') == right.get('unit_kind'):
            a, b = _xy(left), _xy(right)
            if a and b and None not in a + b:
                item['world_xy_raw'] = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
                item['interpolated'] = True
        mixed.append(item)
    doc.setdefault('entities', {})['field_units'] = mixed
    doc['visual_interpolation'] = True
    return doc


def _account_span(account):
    first, last = account.get('first_seq'), account.get('last_seq')
    seqs = [item.get('seq') for force in account.get('forces') or []
            for item in force.get('operations') or [] if item.get('seq')]
    if first is None and seqs:
        first = min(seqs)
    if last is None and seqs:
        last = max(seqs)
    return first, last


def clip_history(history, seq):
    if not history:
        return {'quarters': [], 'current_quarter': None, 'recent_changes': [], 'events': []}
    accounts = [row for row in (history.get('quarters') or []) if row]
    if history.get('current_quarter'):
        accounts.append(history['current_quarter'])
    closed = []
    current = None
    for account in accounts:
        first, last = _account_span(account)
        if first is None:
            first = 1
        if last is None:
            last = first
        if last < seq:
            closed.append(_clip_account(account, seq))
            continue
        if first <= seq:
            current = _clip_account(account, seq)
            current['closed'] = False
            current['label'] = phase_label(current.get('phase')) + '（进行中）'
        break
    if current is None:
        current = _empty_account((accounts[0] or {}).get('phase') if accounts else None, False, first_seq=seq)
    events = [row for row in history.get('events') or [] if row.get('seq', 0) <= seq]
    return {
        'quarters': closed,
        'current_quarter': current,
        'recent_changes': events[-200:],
        'events': events,
        'phase_label': phase_label((current or {}).get('phase')),
    }


def _clip_account(account, seq):
    if not account:
        return _empty_account(None, False)
    out = dict(account)
    forces = []
    for force in account.get('forces') or []:
        ops = [item for item in force.get('operations') or [] if item.get('seq', 0) <= seq]
        if ops:
            forces.append({**force, 'operations': ops})
    out['forces'] = forces
    return out


def _freeze(row, keys):
    values = []
    for key in keys:
        value = (row or {}).get(key)
        if isinstance(value, dict):
            value = tuple(sorted((str(item), value[item]) for item in value))
        elif isinstance(value, list):
            value = tuple(value)
        values.append(value)
    return tuple(values)


def command_stamp(state):
    """Fields the quarter ledger diffs. Unchanged frames can be skipped."""
    state = state or {}
    ents = state.get('entities') or {}
    clock = state.get('phase_candidate') or state.get('clock_candidates') or {}
    phase = (clock.get('year_u16'), clock.get('season_u16'), clock.get('round_u8'), clock.get('turn_u16'))
    return (
        phase,
        tuple(_freeze(row, ('force_id', 'name', 'gold', 'rice', 'prestige', 'troop_stock', 'armament_raw'))
              for row in ents.get('lords') or []),
        tuple(_freeze(row, ('general_id_raw', 'name', 'owner_raw', 'status_code', 'location_city_id'))
              for row in ents.get('generals') or []),
        tuple(_freeze(row, ('city_id', 'name', 'owner_raw', 'population'))
              for row in ents.get('cities_and_barriers') or []),
        tuple(_freeze(row, ('object_id_candidate', 'type', 'owner_raw', 'building_ui_amount', 'linked_city_id', 'world_xy_raw'))
              for row in ents.get('production_buildings') or []),
        tuple(_freeze(row, ('unit_id', 'owner_raw', 'unit_kind', 'soldiers_candidate', 'world_xy_raw', 'general_ids'))
              for row in ents.get('field_units') or []),
    )


class ReplayCursor:
    def __init__(self, directory):
        self.reader = ArchiveReader(directory)
        self.seq = 1 if self.reader.frame_count() else 0
        self._ready = 0
        self._prev_slim = None
        self._events = []
        self._tracks = {}
        self._track_live = {}
        self._track_gen = {}
        self._history = {'quarters': [], 'current_quarter': None, 'recent_changes': [], 'events': []}
        self._current = None
        self._names = {}
        self._captured_at = {}
        self._stamp = None

    def close(self):
        self.reader.close()

    def manifest(self):
        return self.reader.manifest

    def frame_count(self):
        return self.reader.frame_count()

    def clamp(self, seq):
        n = self.frame_count()
        if n <= 0:
            return 0
        return max(1, min(n, int(seq)))

    def seek(self, seq):
        self.seq = self.clamp(seq)
        return self.seq

    def step(self, delta):
        return self.seek(self.seq + delta)

    def frame_state(self, seq=None, clone=True):
        seq = self.seq if seq is None else self.clamp(seq)
        if seq <= 0:
            return None
        return self.reader.load_frame(seq, clone=clone)

    def meta(self, seq=None):
        seq = self.seq if seq is None else self.clamp(seq)
        if seq <= 0:
            return {}
        return self.reader.meta(seq)

    def states_upto(self, seq=None):
        seq = self.seq if seq is None else self.clamp(seq)
        return [self.reader.load_frame(index) for index in range(1, seq + 1)]

    def ensure_ledger(self, seq):
        seq = self.clamp(seq)
        while self._ready < seq:
            self._consume(self._ready + 1, tracks=False)

    def _consume(self, seq, tracks=True):
        state = self.reader.load_frame(seq, clone=False)
        if not tracks:
            stamp = command_stamp(state)
            if stamp == self._stamp and self._prev_slim is not None and self._current is not None:
                self._current['last_seq'] = seq
                self._ready = seq
                self._history['current_quarter'] = self._current
                return
            self._stamp = stamp
        now = slim(state)
        for row in now.get('entities', {}).get('lords') or []:
            if row.get('force_id') is not None:
                self._names[row.get('force_id')] = row.get('name')
        if self._current is None:
            self._current = _empty_account(now.get('phase_candidate'), False, first_seq=seq)
        if self._prev_slim is not None and self._prev_slim.get('phase_candidate') != now.get('phase_candidate'):
            self._current['closed'] = True
            self._current['last_seq'] = seq - 1
            self._current['label'] = phase_label(self._current.get('phase')) + '（已过季）'
            self._history['quarters'].append(self._current)
            self._current = _empty_account(now.get('phase_candidate'), False, first_seq=seq)
        if self._current.get('first_seq') is None:
            self._current['first_seq'] = seq
        self._current['last_seq'] = seq
        if self._prev_slim is not None:
            incoming = _command_events(self._prev_slim, now, seq, self._captured_at)
            record_city_captures(self._prev_slim, now, seq, self._captured_at)
            for event in incoming:
                self._events.append(event)
                force = _force_slot(self._current, event.get('owner'),
                                    self._names.get(event.get('owner')) or event.get('name'))
                force['operations'].append(event)
            self._purge_capture_builds(self._prev_slim, now, seq)
        if tracks:
            self._advance_tracks(seq, state)
        self._prev_slim = now
        self._ready = seq
        self._history['current_quarter'] = self._current
        self._history['events'] = self._events
        self._history['recent_changes'] = self._events[-200:]
        self._history['phase_label'] = phase_label(now.get('phase_candidate'))

    def _purge_capture_builds(self, prev, now, seq):
        ids = set(lord_map(prev)) | set(lord_map(now))
        dropped = False
        for fid in ids:
            if fid is None:
                continue
            gained = captured_city_ids(prev, now, fid)
            if not gained:
                continue
            names = city_names_for_ids(now, gained)
            before = len(self._events)
            self._events = drop_capture_transfer_builds(self._events, fid, gained, names, seq)
            if len(self._events) != before:
                dropped = True
            if self._current:
                for force in self._current.get('forces') or []:
                    if force.get('owner') != fid:
                        continue
                    force['operations'] = drop_capture_transfer_builds(
                        force.get('operations'), fid, gained, names, seq,
                    )
            for account in self._history.get('quarters') or []:
                for force in account.get('forces') or []:
                    if force.get('owner') != fid:
                        continue
                    force['operations'] = drop_capture_transfer_builds(
                        force.get('operations'), fid, gained, names, seq,
                    )
        if dropped:
            self._history['events'] = self._events
            self._history['recent_changes'] = self._events[-200:]

    def _gap_before(self, seq):
        for gap in self.reader.index.get('gaps') or []:
            if gap.get('after_seq') == seq - 1:
                return gap
        return None

    def _advance_tracks(self, seq, state):
        now = {}
        for row in (state.get('entities') or {}).get('field_units') or []:
            uid = row.get('unit_id')
            if uid is None:
                continue
            now[uid] = row
        for uid in list(self._track_live):
            if uid not in now:
                self._track_live.pop(uid, None)
        gap = self._gap_before(seq)
        for uid, row in now.items():
            prev = self._track_live.get(uid)
            if prev is None:
                self._track_gen[uid] = self._track_gen.get(uid, 0) + 1
            elif prev.get('owner_raw') != row.get('owner_raw') or prev.get('unit_kind') != row.get('unit_kind'):
                self._track_gen[uid] = self._track_gen.get(uid, 0) + 1
            key = (uid, self._track_gen.get(uid, 1))
            _append_track_sample(self._tracks, key, _sample_from_unit(seq, row), gap)
            self._track_live[uid] = row

    def _ensure(self, seq):
        while self._ready < seq:
            self._consume(self._ready + 1)

    def view(self, seq=None, force_ids=None, include_tracks=True, include_history=True, include_events=True):
        seq = self.seq if seq is None else self.clamp(seq)
        if seq <= 0:
            return {'seq': 0, 'frame_count': 0, 'state': None, 'history': {}, 'events': [], 'tracks': {}}
        if include_history or include_events or include_tracks:
            self._ensure(seq)
        state = self.frame_state(seq, clone=True)
        meta = self.meta(seq)
        if include_history:
            history = clip_history({
                **self._history,
                'current_quarter': self._current,
                'events': self._events,
            }, seq)
        else:
            history = {'quarters': [], 'current_quarter': None, 'recent_changes': [], 'events': []}
        tracks = {}
        if include_tracks:
            for key, entry in self._tracks.items():
                clipped = clip_track_entry(entry, seq)
                if clipped.get('segments'):
                    tracks[key] = clipped
        gaps = [row for row in self.reader.index.get('gaps') or []
                if (row.get('after_seq') or 0) < seq]
        if force_ids:
            state = filter_forces(state, force_ids)
        note = None
        if self.reader.manifest.get('started_mid_match') and seq == 1:
            note = self.reader.manifest.get('first_frame_note') or '从此处开始记录'
        return {
            'seq': seq,
            'frame_count': self.frame_count(),
            'state': state,
            'meta': meta,
            'stage': meta.get('stage'),
            'stage_cn': STAGE_CN.get(meta.get('stage'), STAGE_CN['unknown']),
            'phase': phase_of(state),
            'phase_label': phase_label(phase_of(state) or {}),
            'history': history,
            'events': [row for row in self._events if row.get('seq', 0) <= seq] if include_events else [],
            'tracks': tracks,
            'gaps': gaps,
            'started_mid_match': bool(self.reader.manifest.get('started_mid_match')),
            'first_frame_note': note,
            'simulated': bool(self.reader.manifest.get('simulated')),
            'completeness': self.reader.manifest.get('completeness'),
            'end_reason': self.reader.manifest.get('end_reason'),
            'tail_truncated': bool(self.reader.index.get('tail_truncated')),
            'resource_problems': self.reader.resources_ok(),
            'match_id': self.reader.manifest.get('match_id'),
        }


def track_draw_polylines(track):
    """One polyline per segment. Gap ends are not joined."""
    lines = []
    for segment in (track or {}).get('segments') or []:
        points = [row.get('world_xy_raw') for row in segment.get('samples') or []
                  if isinstance(row.get('world_xy_raw'), (list, tuple)) and len(row['world_xy_raw']) >= 2]
        if points:
            lines.append({
                'points': points,
                'gap_before': segment.get('gap_before'),
                'marker_only': len(points) < 2,
            })
    return lines
