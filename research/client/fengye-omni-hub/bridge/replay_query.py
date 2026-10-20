"""Read-only omniscient match queries. Never writes archives or starts the collector."""
from datetime import datetime, timezone

from game_archive import ArchiveReader, default_archive_root, list_archives, phase_of
from replay_view import ReplayCursor, select_live_track, track_draw_polylines
from state_history import phase_label
from replay_training import capture_profile, annotation_summary

CONFIRMED_PLAYER = frozenset({'verified', 'confirmed', 'user_confirmed'})


def _parse_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def player_identity(state):
    ctx = (state or {}).get('player_context') or {}
    status = ctx.get('status')
    confirmed = status in CONFIRMED_PLAYER and ctx.get('force_id') is not None
    return {
        'status': status or 'unknown',
        'force_id': ctx.get('force_id') if confirmed else None,
        'confirmed': bool(confirmed),
        'guessed': False,
        'note': None if confirmed else '我方身份未确认，只提供全局情报，不猜测我方。',
    }


def freshness_of(capture_end, now=None, stale_after_s=8.0, gaps=None):
    now = now or datetime.now(timezone.utc).timestamp()
    captured = _parse_time(capture_end)
    age = None if captured is None else max(0.0, now - captured)
    stale = None if age is None else age > stale_after_s
    unknown_drop = any((gap.get('dropped_count') is None) and gap.get('reason')
                       for gap in (gaps or []))
    return {
        'capture_end': capture_end,
        'age_s': None if age is None else round(age, 3),
        'stale': stale,
        'stale_after_s': stale_after_s,
        'interrupt': bool(gaps),
        'dropped_count_unknown': bool(unknown_drop),
    }


class MatchQuery:
    def __init__(self, directory):
        self.cursor = ReplayCursor(directory)
        self.directory = str(directory)

    def close(self):
        self.cursor.close()

    def manifest(self):
        from replay_modifications import summary
        reader = self.cursor.reader
        return dict(self.cursor.manifest(), modification_provenance=summary(reader.directory, reader))

    def match_id(self):
        return self.manifest().get('match_id')

    def _state(self, seq):
        if not seq:
            return None
        return self.cursor.frame_state(seq)

    def _meta(self, seq):
        return self.cursor.meta(seq) if seq else {}

    def _gaps_touching(self, seq):
        return [row for row in self.cursor.reader.index.get('gaps') or []
                if (row.get('after_seq') or 0) < (seq or 0)]

    def envelope(self, data, seq=None, extra=None, now=None):
        meta = self._meta(seq) if seq else {}
        state = self._state(seq) if seq else None
        gaps = self._gaps_touching(seq) if seq else list(self.cursor.reader.index.get('gaps') or [])
        if self.cursor.reader.index.get('seq_rewind_tail'):
            gaps = list(gaps) + [{'reason': 'seq_rewind_tail', 'dropped_count': None,
                                  'note': '档案尾部出现序号回绕，已截断，未并入上一局。'}]
        capture = meta.get('capture_end') or (None if not state else state.get('capture_end'))
        try:
            annotations = annotation_summary(self.directory, capture)
        except (ValueError, KeyError, TypeError, OSError) as error:
            annotations = {'audited_transitions_available_at_cursor': 0,
                           'native_instruction_count': 0, 'formal_evaluation_eligible': False,
                           'annotation_error': str(error)}
        body = {
            'ok': data is not None,
            'match_id': self.match_id(),
            'seq': seq,
            'snapshot_id': meta.get('snapshot_id') or (None if not state else state.get('snapshot_id')),
            'capture_end': capture,
            'recorded_utc': None,
            'game_clock': phase_of(state) if state else None,
            'phase_label': phase_label(phase_of(state) or {}) if state else '季度未知',
            'freshness': freshness_of(capture, now=now, gaps=gaps),
            'gaps': gaps,
            'completeness': self.manifest().get('completeness'),
            'end_reason': self.manifest().get('end_reason'),
            'omniscient': True,
            'visual_interpolation': False,
            'player_identity': player_identity(state),
            'data': data,
            'training_capture': capture_profile(state, {
                **(self.manifest().get('training_context') or {}),
                'synthetic': self.manifest().get('simulated') is True}),
            'training_annotations': annotations,
            'modification_provenance': self.manifest().get('modification_provenance'),
            'modification_annotation_is_decision_feature': False,
        }
        if extra:
            body.update(extra)
        return body

    def latest_seq(self, before_seq=None):
        frames = self.cursor.reader.frames
        if not frames:
            return 0
        last = frames[-1].get('seq') or len(frames)
        if before_seq is None:
            return last
        return self.cursor.clamp(min(int(before_seq), last))

    def latest_snapshot(self, *, before_seq=None, now=None):
        n = self.cursor.frame_count()
        if n <= 0:
            return self.envelope(None, extra={'found': False, 'reason': 'empty_archive',
                                              'cursor_kind': 'archive_latest'})
        if before_seq is None:
            seq = n
            kind = 'archive_latest'
        else:
            seq = self.cursor.clamp(before_seq)
            kind = 'historical_cursor'
        return self.envelope(self._state(seq), seq, extra={'found': True, 'cursor_kind': kind}, now=now)

    def snapshot_at_capture(self, when, now=None):
        frames = self.cursor.reader.frames
        if not frames:
            return self.envelope(None, extra={'found': False, 'reason': 'empty_archive',
                                              'cursor_kind': 'capture_time'})
        first = frames[0].get('capture_end')
        if when is None:
            return self.envelope(None, extra={'found': False, 'reason': 'missing_time',
                                              'cursor_kind': 'capture_time'})
        if first and str(when) < str(first):
            return self.envelope(None, extra={
                'found': False, 'reason': 'before_first_frame',
                'first_capture_end': first, 'cursor_kind': 'capture_time',
            })
        hit = None
        for meta in frames:
            capture = meta.get('capture_end')
            if capture is not None and str(capture) <= str(when):
                hit = meta
            elif capture is not None and str(capture) > str(when):
                break
        if hit is None:
            return self.envelope(None, extra={'found': False, 'reason': 'no_frame_at_or_before',
                                              'cursor_kind': 'capture_time'})
        seq = hit['seq']
        stale_after = None
        idx = seq - 1
        if idx + 1 < len(frames):
            nxt = frames[idx + 1].get('capture_end')
            stale_after = {'next_capture_end': nxt, 'chose_future': False}
        return self.envelope(self._state(seq), seq, extra={
            'found': True, 'cursor_kind': 'capture_time',
            'requested_capture_end': when,
            'hit_capture_end': hit.get('capture_end'),
            'did_not_select_future': True,
            'neighbors': stale_after,
        }, now=now)

    def summary(self, seq=None, now=None):
        view = self.latest_snapshot(before_seq=seq, now=now)
        state = view.get('data')
        if not state:
            return view
        ents = state.get('entities') or {}
        lords = list(ents.get('lords') or [])
        cities = list(ents.get('cities_and_barriers') or [])
        units = list(ents.get('field_units') or [])
        generals = list(ents.get('generals') or [])
        buildings = list(ents.get('production_buildings') or [])
        view['data'] = {
            'phase_label': view.get('phase_label'),
            'force_count': len(lords),
            'city_count': len(cities),
            'unit_count': len(units),
            'general_count': len(generals),
            'building_count': len(buildings),
            'forces': [{'force_id': row.get('force_id'), 'name': row.get('name'),
                        'gold': row.get('gold'), 'rice': row.get('rice'),
                        'prestige': row.get('prestige')} for row in lords],
            'evidence': 'fact',
            'note': '全知快照摘要，未裁成我方视野。',
        }
        return view

    def _require_seq(self, seq=None):
        return self.latest_seq(seq)

    def force_detail(self, force_id, seq=None, now=None):
        seq = self._require_seq(seq)
        state = self._state(seq)
        if not state:
            return self.envelope(None, seq, extra={'found': False})
        lords = [row for row in (state.get('entities') or {}).get('lords') or []
                 if row.get('force_id') == force_id]
        if not lords:
            return self.envelope(None, seq, extra={'found': False, 'reason': 'unknown_force'})
        cities = [row for row in (state.get('entities') or {}).get('cities_and_barriers') or []
                  if row.get('owner_raw') == force_id]
        units = [row for row in (state.get('entities') or {}).get('field_units') or []
                 if row.get('owner_raw') == force_id]
        generals = [row for row in (state.get('entities') or {}).get('generals') or []
                    if row.get('owner_raw') == force_id]
        return self.envelope({
            'force': lords[0], 'cities': cities, 'units': units, 'generals': generals,
            'evidence': 'fact',
        }, seq, now=now)

    def city_detail(self, city_id, seq=None, now=None):
        seq = self._require_seq(seq)
        state = self._state(seq)
        rows = [row for row in (state or {}).get('entities', {}).get('cities_and_barriers') or []
                if row.get('city_id') == city_id]
        if len(rows) != 1:
            return self.envelope(None, seq, extra={'found': False, 'identity_uncertain': len(rows) > 1})
        return self.envelope({'city': rows[0], 'evidence': 'fact'}, seq, now=now)

    def general_detail(self, general_id, seq=None, now=None):
        seq = self._require_seq(seq)
        state = self._state(seq)
        rows = [row for row in (state or {}).get('entities', {}).get('generals') or []
                if row.get('general_id_raw') == general_id]
        if len(rows) != 1:
            return self.envelope({'generals': rows, 'evidence': 'fact'}, seq, extra={
                'found': bool(rows), 'identity_uncertain': len(rows) != 1,
                'note': '将领 ID 可能重复，未猜选第一条。',
            }, now=now)
        return self.envelope({'general': rows[0], 'evidence': 'fact'}, seq, now=now)

    def unit_detail(self, unit_id, seq=None, generation=None, now=None):
        seq = self._require_seq(seq)
        state = self._state(seq)
        rows = [row for row in (state or {}).get('entities', {}).get('field_units') or []
                if row.get('unit_id') == unit_id]
        if len(rows) != 1:
            return self.envelope(None, seq, extra={'found': False, 'identity_uncertain': len(rows) > 1})
        view = self.cursor.view(seq)
        tracks = select_live_track(view.get('tracks') or {}, seq, unit_id, generation=generation)
        return self.envelope({
            'unit': rows[0], 'tracks': tracks, 'evidence': 'fact',
        }, seq, now=now)

    def events(self, start_seq=None, end_seq=None, start_capture=None, end_capture=None,
               start_inclusive=True, end_inclusive=False, offset=0, limit=100,
               entity=None, owner=None, evidence=None, now=None):
        cutoff = self.latest_seq(end_seq)
        self.cursor.seek(cutoff or 1)
        view = self.cursor.view(cutoff) if cutoff else {'events': []}
        rows = []
        for index, item in enumerate(view.get('events') or []):
            seq = item.get('seq') or 0
            if start_seq is not None:
                if start_inclusive and seq < start_seq:
                    continue
                if not start_inclusive and seq <= start_seq:
                    continue
            if end_seq is not None:
                if end_inclusive and seq > end_seq:
                    continue
                if not end_inclusive and seq >= end_seq:
                    continue
            if entity and item.get('entity') != entity:
                continue
            if owner is not None and item.get('owner') != owner:
                continue
            if evidence and item.get('evidence') != evidence:
                continue
            if start_capture or end_capture:
                meta = self._meta(seq)
                capture = meta.get('capture_end')
                if start_capture and capture and str(capture) < str(start_capture):
                    continue
                if end_capture and capture and str(capture) > str(end_capture):
                    continue
            event = dict(item)
            event['event_index'] = index
            event['match_id'] = self.match_id()
            event['observation_seq'] = event.get('observation_seq') or seq
            rows.append(event)
        page = rows[offset:offset + limit]
        return self.envelope({
            'events': page,
            'total': len(rows),
            'offset': offset,
            'limit': limit,
            'start_inclusive': start_inclusive,
            'end_inclusive': end_inclusive,
            'sorted_by': 'observation_seq_asc',
            'note': '只返回查询截止前已观察到的事件。',
        }, cutoff or None, now=now)

    def unit_track(self, unit_id, generation=None, start_seq=None, end_seq=None, now=None):
        seq = self.latest_seq(end_seq)
        if seq <= 0:
            return self.envelope(None, extra={'found': False})
        view = self.cursor.view(seq)
        matches = select_live_track(view.get('tracks') or {}, seq, unit_id, generation=generation)
        for row in matches:
            if start_seq:
                segs = []
                for segment in row.get('segments') or []:
                    samples = [item for item in segment.get('samples') or [] if item.get('seq', 0) >= start_seq]
                    if samples:
                        segs.append({**segment, 'samples': samples})
                row['segments'] = segs
                row['samples'] = [item for seg in segs for item in seg.get('samples') or []]
            row['polylines'] = track_draw_polylines(row)
            row['interpolated'] = False
        return self.envelope({
            'tracks': matches,
            'found': bool(matches),
            'interpolated': False,
        }, seq, now=now)


def list_matches(root=None):
    rows = []
    for item in list_archives(root):
        rows.append({
            'match_id': item.get('match_id'),
            'directory': item.get('directory'),
            'open': item.get('open'),
            'completeness': item.get('completeness'),
            'frame_count': item.get('frame_count'),
            'last_seq': item.get('last_seq'),
            'last_capture_end': item.get('last_capture_end'),
            'started_utc': item.get('started_utc'),
            'simulated': item.get('simulated'),
            'source_id': item.get('source_id'),
            'process': item.get('process'),
        })
    return rows


def current_match(root=None, recorder_status=None):
    if recorder_status and recorder_status.get('open') and recorder_status.get('directory'):
        return {'kind': 'recording', 'match_id': recorder_status.get('match_id'),
                'directory': recorder_status.get('directory')}
    rows = list_matches(root)
    opened = [row for row in rows if row.get('open')]
    if opened:
        return {'kind': 'open_archive', **opened[0]}
    if rows:
        return {'kind': 'latest_archive', **rows[0]}
    return {'kind': 'none', 'match_id': None, 'directory': None, 'root': str(root or default_archive_root())}


def query_match(directory):
    return MatchQuery(directory)
