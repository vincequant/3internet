"""Whole-match archive: append-only frames, no ring buffer, no Hub window.

Runs inside the collector process. Replay reads the directory offline.
"""
import collections
import copy
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

from match_opening import (
    KEEP_FORMATS, KEEP_MIN_FRAMES, apply_opening,
    classify_opening, finalize_opening, kept_archive, kept_opening,
)
from state_history import calendar_label, comparable_phase, entity_key, phase_fields, phase_label, phase_round
from replay_training import capture_profile

FORMAT_VERSION = 2
KEYFRAME_EVERY = 30
QUEUE_MAX = 64
INDEX_FLUSH_EVERY = 30
DROP_STATE_KEYS = (
    'history', 'timing', 'limits', 'decode_warnings', 'omniscient_layer_ready',
    'core_projection_divergence',
)
SEAL_ERROR_CLASSES = frozenset({'process_gone'})
SEAL_PHASES = frozenset({'waiting_for_game'})
IDLE_SEAL_S = 300
IDLE_IGNORE_KEYS = (
    'snapshot_id', 'capture_start', 'capture_end', 'decode_warnings',
    'consistency', 'core_projection_divergence', 'clock_candidates',
)
COMPLETE_REASONS = frozenset({
    'process_gone', 'waiting_for_game', 'new_match_same_process', 'source_or_process_changed',
    'idle_timeout',
})
GAP_ERROR_CLASSES = frozenset({
    'transient_inconsistent', 'dead_root', 'map_not_ready', 'unknown',
})
ASSET_NAMES = ('assets/SanInet.lbm', 'assets/SanInet.mbm')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_archive_root():
    env = os.environ.get('SGI_HUB_REPLAY')
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / 'game-archives'


def release_version(root=None):
    path = (root or Path(__file__).resolve().parent.parent) / 'RELEASE.json'
    try:
        return json.loads(path.read_text(encoding='utf8')).get('version')
    except (OSError, ValueError, TypeError):
        return None


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest_json(value):
    return digest_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8'))


_MAP_RESOURCE_CACHE = {}


def map_resources(app_dir=None):
    root = Path(app_dir or Path(__file__).resolve().parent.parent / 'app')
    cache_key = str(root)
    cached = _MAP_RESOURCE_CACHE.get(cache_key)
    if cached:
        return copy.deepcopy(cached)
    rows = []
    for rel in ASSET_NAMES:
        path = root / rel
        item = {'path': rel, 'present': path.is_file()}
        if path.is_file():
            item['bytes'] = path.stat().st_size
            item['sha256'] = digest_bytes(path.read_bytes())
        rows.append(item)
    _MAP_RESOURCE_CACHE[cache_key] = rows
    return copy.deepcopy(rows)


def process_identity(payload, state=None):
    ident = (payload or {}).get('identity') or {}
    if not ident.get('pid') and not ident.get('creation_filetime'):
        ident = ((state or {}).get('identity') or {})
    return {
        'pid': ident.get('pid') if ident.get('pid') is not None else (payload or {}).get('pid'),
        'path': ident.get('path') if ident.get('path') is not None else (payload or {}).get('path'),
        'creation_filetime': ident.get('creation_filetime'),
    }


def match_key(payload, state=None):
    ident = process_identity(payload, state)
    return (
        ident.get('creation_filetime'),
        ident.get('path'),
        ident.get('pid'),
        (payload or {}).get('source_id'),
    )


def phase_of(state):
    if not state:
        return None
    return phase_fields(state.get('clock_candidates'), state.get('phase_candidate'))


def phase_from_record(record):
    record = record or {}
    clock = record.get('clock_candidates')
    if not isinstance(clock, dict):
        clock = (record.get('state') or {}).get('clock_candidates')
    if not isinstance(clock, dict):
        clock = (record.get('delta') or {}).get('clock_candidates')
    return phase_fields(clock, record.get('phase_candidate'))


def note_round(rows, seq, phase):
    year, season = (phase or {}).get('year_u16'), (phase or {}).get('season_u16')
    if not isinstance(year, int) or not isinstance(season, int):
        return rows
    rnd = phase_round(phase)
    if rows and rows[-1].get('year_u16') == year and rows[-1].get('season_u16') == season and rows[-1].get('round_u8') == rnd:
        rows[-1]['last_seq'] = seq
        return rows
    rows.append({
        'year_u16': year,
        'season_u16': season,
        'round_u8': rnd,
        'first_seq': seq,
        'last_seq': seq,
        'label': phase_label({'year_u16': year, 'season_u16': season, 'round_u8': rnd}),
    })
    return rows


def gameplay_fingerprint(state):
    doc = compact_state(state)
    if not doc:
        return None
    for key in IDLE_IGNORE_KEYS:
        doc.pop(key, None)
    return json.dumps(doc, ensure_ascii=False, sort_keys=True)


def clock_age_s(then, now):
    if not then or not now:
        return None
    try:
        return (datetime.fromisoformat(now) - datetime.fromisoformat(then)).total_seconds()
    except (TypeError, ValueError):
        return None


def compact_state(state):
    if not state:
        return None
    doc = {key: copy.deepcopy(value) for key, value in state.items() if key not in DROP_STATE_KEYS}
    entities = doc.get('entities')
    if isinstance(entities, dict):
        cleaned = {}
        for kind, rows in entities.items():
            if not isinstance(rows, list):
                cleaned[kind] = copy.deepcopy(rows)
                continue
            if kind == 'field_units':
                # Retain native counter eligibility when stripping raw bytes.
                from native_unit_rules import raw_bytes
                import struct
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    b = raw_bytes(row)
                    if len(b) >= 0x80:
                        row.update(unit_state_flags_raw=b[0xd], native_order_type_raw=struct.unpack_from('<H', b, 0x7e)[0],
                                   native_order_payload_raw=struct.unpack_from('<I', b, 0x5e)[0])
            cleaned[kind] = [
                {key: value for key, value in row.items() if key not in ('raw_hex',)}
                if isinstance(row, dict) else row
                for row in rows
            ]
        doc['entities'] = cleaned
    clock = doc.get('clock_candidates') or {}
    doc['phase_candidate'] = phase_fields(clock, doc.get('phase_candidate'))
    return doc


def entity_ident(kind, row):
    key = entity_key(kind, row)
    if isinstance(key, tuple):
        return json.dumps(key, ensure_ascii=False, separators=(',', ':'))
    return key


def normalize_state(state):
    return json.loads(json.dumps(compact_state(state), ensure_ascii=False, sort_keys=True))


def compute_delta(prev, current):
    """Index-preserving delta. Duplicate entity IDs stay as separate rows."""
    prev = prev or {}
    current = current or {}
    delta = {}
    prev_keys = set(prev) - {'entities'}
    cur_keys = set(current) - {'entities'}
    removed = sorted(prev_keys - cur_keys)
    if removed:
        delta['_removed_fields'] = removed
    for key in sorted(cur_keys):
        if prev.get(key) != current.get(key):
            delta[key] = copy.deepcopy(current.get(key))
    ents = {}
    prev_e = prev.get('entities') or {}
    cur_e = current.get('entities') or {}
    for kind in sorted(set(prev_e) | set(cur_e)):
        old_rows = list(prev_e.get(kind) or [])
        new_rows = list(cur_e.get(kind) or [])
        if old_rows == new_rows:
            continue
        changed = [[index, copy.deepcopy(row)] for index, row in enumerate(new_rows)
                   if index >= len(old_rows) or old_rows[index] != row]
        ents[kind] = {'length': len(new_rows), 'set': changed}
    if ents:
        delta['entities'] = ents
    return delta


def apply_delta_into(state, delta):
    """Mutate `state` to apply a packed delta. Caller owns the object."""
    state = state if state is not None else {}
    for key in delta.get('_removed_fields') or []:
        state.pop(key, None)
    for field, value in delta.items():
        if field in ('entities', '_removed_fields'):
            continue
        state[field] = copy.deepcopy(value)
    entities = state.setdefault('entities', {})
    for kind, change in (delta.get('entities') or {}).items():
        length = change.get('length', 0)
        rows = list(entities.get(kind) or [])
        if length < len(rows):
            rows = rows[:length]
        elif length > len(rows):
            rows = rows + [None] * (length - len(rows))
        for index, row in change.get('set') or []:
            if 0 <= index < length:
                rows[index] = copy.deepcopy(row)
        entities[kind] = rows[:length]
        if length == 0:
            entities[kind] = []
    return state


def apply_delta(base, delta):
    return apply_delta_into(copy.deepcopy(base or {}), delta)


def encode_record(record):
    raw = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    return json.dumps({
        'z': True,
        'sha256': digest_bytes(raw),
        'payload': zlib.compress(raw, 3).hex(),
    }, separators=(',', ':')).encode('utf8') + b'\n'


def decode_line(line):
    if not line or not line.strip():
        return None
    wrapper = json.loads(line)
    if wrapper.get('z'):
        raw = zlib.decompress(bytes.fromhex(wrapper['payload']))
        if wrapper.get('sha256') and digest_bytes(raw) != wrapper['sha256']:
            raise ValueError('frame checksum mismatch')
        return json.loads(raw.decode('utf8'))
    return wrapper


def _unit_xy_rows(state):
    rows = []
    for index, row in enumerate((state or {}).get('entities', {}).get('field_units') or []):
        if not isinstance(row, dict):
            continue
        xy = tuple((row.get('world_xy_raw') or [None, None])[:2])
        rows.append((index, row.get('unit_id'), row.get('owner_raw'), row.get('unit_kind'), xy))
    return rows


def infer_stage(prev, current):
    if not current:
        return 'unknown'
    units_now = _unit_xy_rows(current)
    if not units_now:
        return 'no_field_units'
    if not prev:
        return 'units_present_no_motion_sample'
    units_prev = _unit_xy_rows(prev)
    if any(now[4] != prev[4] for now, prev in zip(units_now, units_prev) if now[:4] == prev[:4]):
        return 'observed_unit_motion'
    now_ids = [(row[1], row[2], row[3], row[4]) for row in units_now]
    prev_ids = [(row[1], row[2], row[3], row[4]) for row in units_prev]
    if now_ids != prev_ids:
        if any(a[3] != b[3] for a, b in zip(now_ids, prev_ids) if a[:3] == b[:3]):
            return 'observed_unit_motion'
        return 'observed_unit_presence_change'
    return 'no_unit_motion'


def started_mid_match(state, saw_pre_live):
    phase = comparable_phase(phase_of(state) or {})
    if not saw_pre_live:
        return True
    if phase is None:
        return True
    return phase[1] != 0


class ArchiveWriter:
    def __init__(self, directory, manifest):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = manifest
        self.manifest.setdefault('training_capture_contract', {
            'schema_version': 1, 'observation_mode': 'omniscient',
            'original_instruction_stream_captured': False,
            'state_difference_is_action_label': False,
            'formal_evaluation_eligible': False,
        })
        self.frames_path = self.directory / 'frames.jsonl'
        self.index_path = self.directory / 'index.json'
        self.manifest_path = self.directory / 'manifest.json'
        self.stream = self.frames_path.open('ab')
        self.index = {
            'format_version': FORMAT_VERSION,
            'frames': [],
            'quarters': [],
            'rounds': [],
            'stages': [],
            'events': [],
            'gaps': [],
            'tail_truncated': False,
        }
        self.last_state = None
        self.last_offset = self.frames_path.stat().st_size
        self.seq = 0
        self.dirty_index = False

    def close_stream(self):
        if self.stream:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            self.stream = None

    def write_manifest(self):
        tmp = self.manifest_path.with_name(self.manifest_path.name + '.tmp')
        tmp.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding='utf8')
        tmp.replace(self.manifest_path)

    def write_index(self):
        tmp = self.index_path.with_name(self.index_path.name + '.tmp')
        tmp.write_text(json.dumps(self.index, ensure_ascii=False), encoding='utf8')
        tmp.replace(self.index_path)
        self.dirty_index = False

    def append_record(self, record):
        data = encode_record(record)
        offset = self.stream.tell()
        self.stream.write(data)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.last_offset = offset + len(data)
        return offset, digest_bytes(data)

    def add_frame(self, kind, state, extra=None):
        self.seq += 1
        phase = phase_of(state) or {}
        record = {
            'kind': kind,
            'seq': self.seq,
            'snapshot_id': None if not state else state.get('snapshot_id'),
            'capture_end': None if not state else state.get('capture_end'),
            'recorded_utc': utc_now(),
            'phase_candidate': phase,
            'stage': infer_stage(self.last_state, state),
            'training_observation': capture_profile(state, {
                **(self.manifest.get('training_context') or {}),
                'synthetic': self.manifest.get('simulated') is True}),
        }
        if extra:
            record.update(extra)
        if kind == 'keyframe':
            record['state'] = state
        elif kind == 'delta':
            record['delta'] = compute_delta(self.last_state, state)
        offset, line_sha = self.append_record(record)
        meta = {
            'seq': self.seq,
            'offset': offset,
            'kind': kind,
            'snapshot_id': record.get('snapshot_id'),
            'capture_end': record.get('capture_end'),
            'year_u16': phase.get('year_u16'),
            'season_u16': phase.get('season_u16'),
            'turn_u16': phase.get('turn_u16'),
            'round_u8': phase.get('round_u8'),
            'stage': record.get('stage'),
            'sha256': line_sha,
        }
        self.index['frames'].append(meta)
        self._note_quarter(phase)
        self._note_round(phase)
        self._note_stage(record.get('stage'))
        self.dirty_index = True
        self.last_state = copy.deepcopy(state) if state else self.last_state
        self.manifest['frame_count'] = self.seq
        self.manifest['last_seq'] = self.seq
        self.manifest['last_snapshot_id'] = record.get('snapshot_id')
        self.manifest['last_capture_end'] = record.get('capture_end')
        if self.seq == 1 or self.seq % INDEX_FLUSH_EVERY == 0:
            self.write_index()
            self.write_manifest()
        return record

    def add_event(self, event):
        event = dict(event)
        event.setdefault('seq', self.seq)
        event.setdefault('recorded_utc', utc_now())
        self.append_record({'kind': 'event', **event})
        self.index['events'].append({
            'seq': event.get('seq'),
            'type': event.get('type'),
            'reason': event.get('reason'),
            'snapshot_id': event.get('snapshot_id'),
        })
        self.dirty_index = True

    def add_gap(self, reason, started=None, ended=None):
        gap = {
            'after_seq': self.seq,
            'reason': reason,
            'started': started or utc_now(),
            'ended': ended,
        }
        self.append_record({'kind': 'gap', **gap})
        self.index['gaps'].append(gap)
        self.dirty_index = True
        return gap

    def _note_quarter(self, phase):
        year, season = phase.get('year_u16'), phase.get('season_u16')
        if not isinstance(year, int) or not isinstance(season, int):
            return
        quarters = self.index['quarters']
        if quarters and quarters[-1]['year_u16'] == year and quarters[-1]['season_u16'] == season:
            quarters[-1]['last_seq'] = self.seq
            return
        quarters.append({
            'year_u16': year, 'season_u16': season,
            'first_seq': self.seq, 'last_seq': self.seq,
            'label': calendar_label(year, season) or f'年{year}·季{season}',
        })

    def _note_round(self, phase):
        note_round(self.index.setdefault('rounds', []), self.seq, phase)

    def _note_stage(self, stage):
        stages = self.index['stages']
        if stages and stages[-1]['stage'] == stage:
            stages[-1]['last_seq'] = self.seq
            return
        stages.append({'stage': stage, 'first_seq': self.seq, 'last_seq': self.seq})


def _resume_writer(directory, manifest):
    writer = ArchiveWriter(directory, manifest)
    rebuilt = refresh_index(directory)
    writer.index = rebuilt
    frames = [row for row in rebuilt.get('frames') or [] if row.get('kind') in ('keyframe', 'delta')]
    writer.seq = frames[-1]['seq'] if frames else 0
    writer.manifest['frame_count'] = writer.seq
    if frames:
        reader = ArchiveReader(directory)
        writer.last_state = reader.load_frame(writer.seq)
        reader.close()
    return writer


def _empty_index():
    return {
        'format_version': FORMAT_VERSION,
        'frames': [],
        'quarters': [],
        'rounds': [],
        'stages': [],
        'events': [],
        'gaps': [],
        'tail_truncated': False,
        'seq_rewind_tail': False,
    }


def _ingest_record(index, start, record, last_phase):
    kind = record.get('kind')
    if kind in ('keyframe', 'delta'):
        seq = record.get('seq')
        if index['frames']:
            prev_seq = index['frames'][-1].get('seq')
            if seq is None or (prev_seq is not None and seq <= prev_seq):
                index['seq_rewind_tail'] = True
                index['ignored_from_offset'] = start
                return last_phase, False
        phase = record.get('phase_candidate') or {}
        full = phase_from_record(record)
        season_key = {'year_u16': phase.get('year_u16'), 'season_u16': phase.get('season_u16')}
        index['frames'].append({
            'seq': record.get('seq'),
            'offset': start,
            'kind': kind,
            'snapshot_id': record.get('snapshot_id'),
            'capture_end': record.get('capture_end'),
            'year_u16': phase.get('year_u16'),
            'season_u16': phase.get('season_u16'),
            'turn_u16': full.get('turn_u16'),
            'round_u8': full.get('round_u8'),
            'stage': record.get('stage'),
        })
        if season_key != last_phase:
            index['quarters'].append({
                'year_u16': phase.get('year_u16'),
                'season_u16': phase.get('season_u16'),
                'first_seq': record.get('seq'),
                'last_seq': record.get('seq'),
                'label': calendar_label(phase.get('year_u16'), phase.get('season_u16'))
                          or f"年{phase.get('year_u16')}·季{phase.get('season_u16')}",
            })
            last_phase = season_key
        elif index['quarters']:
            index['quarters'][-1]['last_seq'] = record.get('seq')
        note_round(index.setdefault('rounds', []), record.get('seq'), full)
        if index['stages'] and index['stages'][-1]['stage'] == record.get('stage'):
            index['stages'][-1]['last_seq'] = record.get('seq')
        else:
            index['stages'].append({
                'stage': record.get('stage'),
                'first_seq': record.get('seq'),
                'last_seq': record.get('seq'),
            })
    elif kind == 'event':
        index['events'].append({
            'seq': record.get('seq'),
            'type': record.get('type'),
            'reason': record.get('reason'),
            'snapshot_id': record.get('snapshot_id'),
        })
    elif kind == 'gap':
        index['gaps'].append({
            'after_seq': record.get('after_seq'),
            'reason': record.get('reason'),
            'started': record.get('started'),
            'ended': record.get('ended'),
        })
    return last_phase, True


def _ingest_stream(handle, index, last_phase=None):
    while True:
        start = handle.tell()
        line = handle.readline()
        if not line:
            break
        if not line.endswith(b'\n'):
            index['tail_truncated'] = True
            break
        try:
            record = decode_line(line)
        except (ValueError, json.JSONDecodeError, zlib.error, KeyError):
            index['tail_truncated'] = True
            break
        last_phase, keep = _ingest_record(index, start, record, last_phase)
        if not keep:
            break
    return index


def rebuild_index(directory):
    directory = Path(directory)
    path = directory / 'frames.jsonl'
    index = _empty_index()
    if not path.is_file():
        return index
    with path.open('rb') as handle:
        _ingest_stream(handle, index)
    return index


def _extend_stored_index(path, stored):
    frames = stored.get('frames') or []
    if not frames:
        return None
    last = frames[-1]
    offset = last.get('offset')
    if not isinstance(offset, int) or offset < 0:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < offset:
        return None
    if stored.get('seq_rewind_tail'):
        return stored
    with path.open('rb') as handle:
        handle.seek(offset)
        line = handle.readline()
        if not line:
            return None
        if not line.endswith(b'\n'):
            index = copy.deepcopy(stored)
            index['tail_truncated'] = True
            return index
        record = None
        expected = last.get('sha256')
        if expected:
            if digest_bytes(line) != expected:
                return None
        else:
            try:
                record = decode_line(line)
            except (ValueError, json.JSONDecodeError, zlib.error, KeyError):
                return None
            if record.get('seq') != last.get('seq') or record.get('kind') != last.get('kind'):
                return None
        if handle.tell() >= size:
            return stored
        index = copy.deepcopy(stored)
        index['tail_truncated'] = False
        last_phase = None
        if expected:
            try:
                record = decode_line(line)
            except (ValueError, json.JSONDecodeError, zlib.error, KeyError):
                record = None
        if record:
            last_phase = record.get('phase_candidate')
        if last_phase is None and index.get('quarters'):
            quarter = index['quarters'][-1]
            last_phase = {'year_u16': quarter.get('year_u16'), 'season_u16': quarter.get('season_u16')}
        _ingest_stream(handle, index, last_phase)
        return index


def scan_rounds(directory):
    path = Path(directory) / 'frames.jsonl'
    rows = []
    last = None
    if not path.is_file():
        return rows
    with path.open('rb') as handle:
        while True:
            line = handle.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                break
            try:
                record = decode_line(line)
            except (ValueError, json.JSONDecodeError, zlib.error, KeyError):
                break
            if record.get('kind') not in ('keyframe', 'delta'):
                continue
            phase = phase_from_record(record)
            if last is not None and phase.get('turn_u16') is None:
                phase = {
                    'year_u16': phase.get('year_u16') if phase.get('year_u16') is not None else last.get('year_u16'),
                    'season_u16': phase.get('season_u16') if phase.get('season_u16') is not None else last.get('season_u16'),
                    'turn_u16': last.get('turn_u16'),
                    'round_u8': last.get('round_u8'),
                }
            last = phase
            note_round(rows, record.get('seq'), phase)
    return rows


def ensure_rounds(directory, index, cache_write=True):
    index = index or _empty_index()
    frames = index.get('frames') or []
    last_seq = frames[-1].get('seq') if frames else 0
    rows = index.get('rounds') or []
    if rows and rows[-1].get('last_seq') == last_seq:
        return index
    cache = Path(directory) / 'rounds.json'
    try:
        cached = json.loads(cache.read_text(encoding='utf8')) if cache.is_file() else None
    except (OSError, json.JSONDecodeError):
        cached = None
    if cached and cached.get('last_seq') == last_seq and cached.get('frame_count') == len(frames):
        index['rounds'] = cached.get('rounds') or []
        return index
    rows = scan_rounds(directory)
    index['rounds'] = rows
    if not cache_write:
        return index
    try:
        tmp = cache.with_name(cache.name + '.tmp')
        tmp.write_text(json.dumps({
            'last_seq': last_seq,
            'frame_count': len(frames),
            'rounds': rows,
        }, ensure_ascii=False), encoding='utf8')
        tmp.replace(cache)
    except OSError:
        pass
    return index


def refresh_index(directory, stored=None, cache_write=True):
    directory = Path(directory)
    path = directory / 'frames.jsonl'
    stored_path = directory / 'index.json'
    if stored is None and stored_path.is_file():
        try:
            stored = json.loads(stored_path.read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError):
            stored = None
    if not path.is_file():
        return stored if stored else _empty_index()
    if stored and stored.get('frames'):
        extended = _extend_stored_index(path, stored)
        if extended is not None:
            return ensure_rounds(directory, extended, cache_write=cache_write)
    return ensure_rounds(directory, rebuild_index(directory), cache_write=cache_write)


class ArchiveReader:
    def __init__(self, directory, read_only=False):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / 'manifest.json').read_text(encoding='utf8'))
        self.index = refresh_index(self.directory, cache_write=not read_only)
        self.frames = list(self.index.get('frames') or [])
        self._fh = (self.directory / 'frames.jsonl').open('rb')
        self._cache = {}
        self._keyframe_state = {}
        self._resource_problems = None
        self._seq_state = None

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def frame_count(self):
        return len(self.frames)

    def meta(self, seq):
        if not 1 <= seq <= len(self.frames):
            raise IndexError(seq)
        return self.frames[seq - 1]

    def _read_record(self, seq):
        meta = self.meta(seq)
        self._fh.seek(meta['offset'])
        line = self._fh.readline()
        return decode_line(line)

    def last_keyframe_seq(self, seq):
        for meta in reversed(self.frames[:seq]):
            if meta.get('kind') == 'keyframe':
                return meta['seq']
        raise ValueError('no keyframe at or before %s' % seq)

    def load_frame(self, seq, clone=True):
        state = self._materialize(seq)
        return copy.deepcopy(state) if clone else state

    def _materialize(self, seq):
        if not 1 <= seq <= len(self.frames):
            raise IndexError(seq)
        if self._seq_state and self._seq_state[0] == seq:
            return self._seq_state[1]
        if self._seq_state and self._seq_state[0] + 1 == seq:
            return self._advance_seq(seq)
        return self._rebuild_seq(seq)

    def _install_keyframe(self, seq, state):
        frozen = copy.deepcopy(state)
        self._keyframe_state[seq] = frozen
        working = copy.deepcopy(frozen)
        self._seq_state = (seq, working)
        return working

    def _advance_seq(self, seq):
        record = self._read_record(seq)
        if record.get('kind') == 'keyframe':
            return self._install_keyframe(seq, record['state'])
        apply_delta_into(self._seq_state[1], record.get('delta') or {})
        self._seq_state = (seq, self._seq_state[1])
        return self._seq_state[1]

    def _rebuild_seq(self, seq):
        key_seq = self.last_keyframe_seq(seq)
        if key_seq in self._keyframe_state:
            state = copy.deepcopy(self._keyframe_state[key_seq])
        else:
            record = self._read_record(key_seq)
            state = self._install_keyframe(key_seq, record['state'])
            if key_seq == seq:
                return state
            state = self._seq_state[1]
        for step in range(key_seq + 1, seq + 1):
            record = self._read_record(step)
            if record.get('kind') == 'keyframe':
                state = self._install_keyframe(step, record['state'])
            elif record.get('kind') == 'delta':
                apply_delta_into(state, record.get('delta') or {})
        self._seq_state = (seq, state)
        return state

    def load_all_states(self):
        return [self.load_frame(seq) for seq in range(1, self.frame_count() + 1)]

    def resources_ok(self, app_dir=None):
        if self._resource_problems is not None and app_dir is None:
            return list(self._resource_problems)
        expected = {row['path']: row for row in self.manifest.get('map_resources') or []}
        current = {row['path']: row for row in map_resources(app_dir)}
        problems = []
        for path, row in expected.items():
            have = current.get(path) or {}
            if row.get('present') and not have.get('present'):
                problems.append({'path': path, 'issue': 'missing'})
            elif row.get('sha256') and have.get('sha256') and row['sha256'] != have['sha256']:
                problems.append({'path': path, 'issue': 'hash_mismatch',
                                 'expected': row['sha256'], 'actual': have['sha256']})
        if app_dir is None:
            self._resource_problems = list(problems)
        return problems


def list_archives(root=None):
    root = Path(root or default_archive_root())
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.iterdir(), reverse=True):
        manifest = path / 'manifest.json'
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError):
            continue
        data = dict(data)
        data['directory'] = str(path)
        if not data.get('opening_locked') or not data.get('title'):
            from match_opening import ensure_archive_title
            data = ensure_archive_title(path, data)
            data['directory'] = str(path)
        from replay_modifications import summary
        data['modification_provenance'] = summary(path)
        rows.append(data)
    return rows


CONTROL_OPS = frozenset({'open', 'seal', 'discard', 'gap', 'event', 'stop'})


class GameArchiveRecorder:
    """Ingest-thread session machine; writer only persists already-decided ops."""

    def __init__(self, root=None, app_dir=None, queue_max=QUEUE_MAX, keyframe_every=KEYFRAME_EVERY,
                 clock=None, fs_check=None, idle_seal_s=IDLE_SEAL_S, keep_formats=KEEP_FORMATS,
                 keep_min_frames=None, training_context=None):
        self.root = Path(root or default_archive_root())
        self.app_dir = Path(app_dir) if app_dir else Path(__file__).resolve().parent.parent / 'app'
        self.queue_max = queue_max
        self.keyframe_every = keyframe_every
        self.clock = clock or utc_now
        self.fs_check = fs_check
        self.idle_seal_s = idle_seal_s
        self.keep_formats = keep_formats
        self.keep_min_frames = keep_min_frames
        self.training_context = copy.deepcopy(training_context)
        self._q_lock = threading.Lock()
        self._pending = collections.deque()
        self._frame_depth = 0
        self._wake = threading.Event()
        self.apply_gate = threading.Event()
        self.apply_gate.set()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='sgi-game-archive')
        self.lock = threading.Lock()
        self.writer = None
        self.session_open = False
        self.session_key = None
        self.session_match_id = None
        self.session_mid = False
        self.current_key = None
        self.saw_pre_live = False
        self.open_gap = None
        self.dropped_frames = 0
        self.match_dropped = 0
        self.overflow_visible = 0
        self.write_error = None
        self.last_snapshot_id = None
        self.last_capture_end = None
        self.last_phase = None
        self.last_change_at = None
        self.last_gameplay_fp = None
        self.idle_sealed_fp = None
        self.idle_sealed_key = None
        self.seen_ids = set()
        self.related = []
        self.status = {
            'recording': False,
            'match_id': None,
            'directory': None,
            'title': None,
            'seq': 0,
            'dropped_frames': 0,
            'write_error': None,
            'completeness': None,
            'started_mid_match': False,
            'queue_depth': 0,
            'open': False,
        }
        self.thread.start()

    def pending_empty(self):
        with self._q_lock:
            return not self._pending

    def queue_depth(self):
        with self._q_lock:
            return len(self._pending)

    def pending_ops(self):
        with self._q_lock:
            return [item.get('op') for item in self._pending]

    def public_status(self):
        with self._q_lock:
            depth = len(self._pending)
            dropped = self.dropped_frames
        with self.lock:
            data = dict(self.status)
            data['queue_depth'] = depth
            data['dropped_frames'] = dropped
            data['write_error'] = self.write_error
            return data

    def ingest(self, payload):
        try:
            self._ingest(payload)
        except Exception as error:
            with self.lock:
                self.write_error = self.write_error or ('ingest: ' + str(error))
                self.status['write_error'] = self.write_error

    def _enqueue(self, item):
        overflow = False
        with self._q_lock:
            op = item.get('op')
            if op not in CONTROL_OPS and self._frame_depth >= self.queue_max:
                self.dropped_frames += 1
                self.match_dropped += 1
                self.overflow_visible += 1
                overflow = True
            else:
                self._pending.append(item)
                if op not in CONTROL_OPS:
                    self._frame_depth += 1
                self._wake.set()
        if overflow:
            with self.lock:
                self.status['dropped_frames'] = self.dropped_frames
                self.status['overflow'] = True
            return False
        return True

    def _maybe_idle_seal(self):
        if not self.session_open or self.last_change_at is None:
            return False
        age = clock_age_s(self.last_change_at, self.clock())
        if age is None or age < self.idle_seal_s:
            return False
        self._seal_session('idle_timeout')
        return True

    def _should_keep(self, info):
        return kept_opening(info, self.keep_formats)

    def _should_start(self, state):
        info = classify_opening(state)
        if self.training_context is not None:
            return bool(info.get('opening_force_count'))
        return bool(info.get('opening_locked') and self._should_keep(info))

    def _abort_session(self, reason='not_kept_format'):
        if not self.session_open:
            return
        self._enqueue({
            'op': 'discard', 'reason': reason, 'match_id': self.session_match_id,
        })
        self.session_open = False
        self.session_key = None
        self.current_key = None
        self.idle_sealed_fp = None
        self.idle_sealed_key = None
        self._reset_ingest_cursor(keep_session=False)
        with self.lock:
            self.status['open'] = False

    def _keep_or_abort(self, state):
        # A kept opening (1v1/2v2/3v3) must not be aborted when 策反 adds a lord.
        if self.session_open:
            return True
        info = classify_opening(state)
        if info.get('opening_locked') and not self._should_keep(info):
            self._abort_session('not_kept_format')
            return False
        return True

    def _ingest(self, payload):
        payload = payload or {}
        if self.session_open:
            self._maybe_idle_seal()
        state = compact_state(payload.get('state'))
        phase = payload.get('phase')
        error_class = payload.get('error_class')
        key = match_key(payload, state)
        if phase in ('waiting_for_game', 'map_not_ready', 'waiting_for_player') and not state:
            self.saw_pre_live = True
        ident_present = any(part is not None and part != '' for part in key)
        process_changed = (
            self.session_open
            and self.session_key is not None
            and ident_present
            and key != self.session_key
        )
        if process_changed and state and state.get('snapshot_id'):
            self._seal_session('source_or_process_changed')
            if not self._should_start(state):
                return
            self._open_session(payload, state, key)
            self._remember_frame(state)
            self._enqueue_frame(state, payload)
            self._keep_or_abort(state)
            return
        if error_class in SEAL_ERROR_CLASSES or (phase in SEAL_PHASES and self.session_open):
            if self.session_open:
                self._seal_session(error_class or phase)
            self.saw_pre_live = True
            return
        if not state or not state.get('snapshot_id'):
            if self.session_open and (error_class in GAP_ERROR_CLASSES or phase in (
                'recovering', 'map_not_ready', 'error',
            )):
                self._enqueue({'op': 'gap', 'reason': error_class or phase or 'unknown_interrupt'})
            return
        snap_id = state.get('snapshot_id')
        capture_end = state.get('capture_end')
        if snap_id in self.seen_ids:
            self._maybe_idle_seal()
            return
        now_phase = comparable_phase(phase_of(state) or {})
        rolled_back = (
            self.last_phase is not None and now_phase is not None
            and now_phase < self.last_phase
        )
        if self.last_capture_end and capture_end and capture_end < self.last_capture_end and not rolled_back:
            self._enqueue({'op': 'event', 'type': 'out_of_order',
                           'reason': 'capture_end_before_last', 'snapshot_id': snap_id})
            return
        if self.session_open and rolled_back:
            self._seal_session('new_match_same_process')
            if not self._should_start(state):
                return
            self._open_session(payload, state, key)
            self._remember_frame(state)
            self._enqueue_frame(state, payload)
            self._keep_or_abort(state)
            return
        fp = gameplay_fingerprint(state)
        if not self.session_open:
            if (self.idle_sealed_fp and fp == self.idle_sealed_fp
                    and ident_present and key == self.idle_sealed_key):
                return
            if not self._should_start(state):
                return
            self._open_session(payload, state, key)
        self._remember_frame(state)
        self._enqueue_frame(state, payload)
        if not self._keep_or_abort(state):
            return
        self._maybe_idle_seal()

    def _enqueue_frame(self, state, payload):
        self._enqueue({
            'op': 'frame', 'state': state, 'payload': payload,
            'dropped_before': self.match_dropped,
        })

    def _open_session(self, payload, state, key):
        related = self.session_match_id
        match_id = str(uuid.uuid4())
        self.session_open = True
        self.session_key = key
        self.session_match_id = match_id
        self.session_mid = started_mid_match(state, self.saw_pre_live)
        self.current_key = key
        self.match_dropped = 0
        with self.lock:
            self.write_error = None
            self.status['open'] = True
            self.status['match_id'] = match_id
            self.status['recording'] = True
            self.status['write_error'] = None
        self._reset_ingest_cursor(keep_session=True)
        self.last_change_at = self.clock()
        self.last_gameplay_fp = gameplay_fingerprint(state)
        self.idle_sealed_fp = None
        self.idle_sealed_key = None
        self._enqueue({
            'op': 'open', 'payload': payload, 'state': state,
            'match_id': match_id, 'related_from': related,
        })

    def _seal_session(self, reason):
        if not self.session_open:
            return
        if reason == 'idle_timeout':
            self.idle_sealed_fp = self.last_gameplay_fp
            self.idle_sealed_key = self.session_key
        else:
            self.idle_sealed_fp = None
            self.idle_sealed_key = None
        self._enqueue({
            'op': 'seal', 'reason': reason, 'match_id': self.session_match_id,
            'dropped': self.match_dropped, 'started_mid_match': self.session_mid,
        })
        self.session_open = False
        self.session_key = None
        self.current_key = None
        self._reset_ingest_cursor(keep_session=False)
        with self.lock:
            self.status['open'] = False

    def _remember_frame(self, state):
        self.seen_ids.add(state.get('snapshot_id'))
        self.last_snapshot_id = state.get('snapshot_id')
        self.last_capture_end = state.get('capture_end')
        self.last_phase = comparable_phase(phase_of(state) or {})
        fp = gameplay_fingerprint(state)
        if fp != self.last_gameplay_fp:
            self.last_change_at = self.clock()
            self.last_gameplay_fp = fp

    def _reset_ingest_cursor(self, keep_session=False):
        self.last_snapshot_id = None
        self.last_capture_end = None
        self.last_phase = None
        self.seen_ids = set()
        if not keep_session:
            self.current_key = None
            self.last_change_at = None
            self.last_gameplay_fp = None

    def last_state_phase(self):
        with self.lock:
            writer = self.writer
        if not writer or not writer.last_state:
            return None
        return comparable_phase(phase_of(writer.last_state) or {})

    def _completeness_for_seal(self):
        mid = bool(self.session_mid)
        if self.write_error:
            return 'write_error'
        if self.match_dropped:
            return 'interrupted'
        if mid:
            return 'mid_start'
        return 'complete'

    def close(self, reason='collector_stop'):
        if self.session_open:
            self._seal_session(reason if reason != 'write_failed' else 'write_failed')
        self._enqueue({'op': 'stop'})
        self.stop.set()
        self._wake.set()
        self.apply_gate.set()
        self.thread.join(3)
        if self.writer:
            try:
                self.writer.close_stream()
            except Exception:
                pass
            self.writer = None

    def _pop_pending(self):
        with self._q_lock:
            if not self._pending:
                self._wake.clear()
                return None
            item = self._pending.popleft()
            if item.get('op') not in CONTROL_OPS:
                self._frame_depth = max(0, self._frame_depth - 1)
            return item

    def _run(self):
        while not self.stop.is_set() or not self.pending_empty():
            item = self._pop_pending()
            if item is None:
                self._wake.wait(0.2)
                if self.session_open:
                    self._maybe_idle_seal()
                continue
            if item.get('op') == 'stop':
                break
            self.apply_gate.wait()
            try:
                self._apply(item)
            except OSError as error:
                self._note_write_error(str(error))
            except Exception as error:
                self._note_write_error(self.write_error or str(error))

    def _apply(self, item):
        op = item.get('op')
        if op == 'open':
            self._open(item['payload'], item['state'], item.get('related_from'),
                       match_id=item.get('match_id'))
        elif op == 'frame':
            self._frame(item['state'], item.get('payload') or {},
                        dropped_before=item.get('dropped_before') or 0)
        elif op == 'gap':
            self._gap(item.get('reason') or 'unknown_interrupt')
        elif op == 'event':
            if self.writer:
                self.writer.add_event(item)
        elif op == 'seal':
            self._seal(item.get('reason') or 'unknown_interrupt',
                       dropped=item.get('dropped'),
                       started_mid_match=item.get('started_mid_match'))
        elif op == 'discard':
            self._discard_session(item.get('reason') or 'not_kept_format')

    def _disk_ready(self):
        if self.fs_check:
            self.fs_check(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _open(self, payload, state, related_from=None, match_id=None):
        if self.writer:
            self._seal('superseded')
        self._disk_ready()
        ident = process_identity(payload, state)
        match_id = match_id or str(uuid.uuid4())
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        pid = ident.get('pid') if ident.get('pid') is not None else 'na'
        directory = self.root / f'{stamp}-pid{pid}-{match_id[:8]}'
        mid = started_mid_match(state, self.saw_pre_live)
        version = payload.get('release_version') or release_version(self.root.parent)
        manifest = {
            'format_version': FORMAT_VERSION,
            'open': True,
            'match_id': match_id,
            'collector_version': version,
            'game_build': state.get('build_sha256'),
            'schema': state.get('schema'),
            'source_id': payload.get('source_id'),
            'runtime_id': payload.get('runtime_id'),
            'process': ident,
            'player_session_id_at_open': (state.get('player_identity') or {}).get('session_id'),
            'started_utc': self.clock(),
            'ended_utc': None,
            'end_reason': None,
            'completeness': 'mid_start' if mid else 'recording',
            'started_mid_match': mid,
            'first_frame_note': '从此处开始记录' if mid else None,
            'map_resources': map_resources(self.app_dir),
            'related_match_ids': ([related_from] if related_from else []),
            'simulated': bool(payload.get('simulated') or state.get('simulated')),
            'frame_count': 0,
            'last_seq': 0,
            'last_snapshot_id': None,
            'dropped_frames': 0,
            'write_error': None,
        }
        if self.training_context is not None:
            manifest['training_context'] = copy.deepcopy(self.training_context)
            manifest['recording_purpose'] = 'training_research'
        writer = ArchiveWriter(directory, manifest)
        writer.write_manifest()
        writer.write_index()
        self.writer = writer
        self.current_key = match_key(payload, state)
        self.open_gap = None
        with self.lock:
            self.status.update({
                'recording': True, 'match_id': match_id, 'directory': str(directory),
                'title': manifest.get('title'),
                'seq': 0, 'open': True, 'completeness': manifest['completeness'],
                'started_mid_match': mid, 'write_error': None,
            })

    def _note_write_error(self, message):
        self.write_error = message
        if self.writer:
            self.writer.manifest['write_error'] = message
            self.writer.manifest['completeness'] = 'write_error'
            try:
                self.writer.write_manifest()
            except OSError:
                pass
        with self.lock:
            self.status['write_error'] = message
            self.status['completeness'] = 'write_error'

    def _frame(self, state, payload, dropped_before=0):
        if self.writer is None:
            if not self._should_start(state):
                return
            self._open(payload, state)
        if self.writer is None:
            return
        if self.open_gap:
            self.writer.add_event({
                'type': 'gap_closed', 'reason': self.open_gap.get('reason'),
                'started': self.open_gap.get('started'),
            })
            self.open_gap = None
        need_key = (
            self.writer.seq == 0
            or self.writer.seq % self.keyframe_every == 0
            or phase_of(self.writer.last_state) != phase_of(state)
        )
        kind = 'keyframe' if need_key else 'delta'
        if kind == 'delta' and self.writer.last_state is not None:
            delta = compute_delta(self.writer.last_state, state)
            encoded = json.dumps(delta, ensure_ascii=False, separators=(',', ':'))
            full = json.dumps(state, ensure_ascii=False, separators=(',', ':'))
            if len(encoded) * 2 > len(full):
                kind = 'keyframe'
        extra = {}
        if self.writer.seq == 0 and self.writer.manifest.get('started_mid_match'):
            extra['first_frame_note'] = '从此处开始记录'
        if dropped_before:
            extra['dropped_before'] = dropped_before
            if not self.writer.manifest.get('overflow_gap_recorded'):
                self.writer.add_gap('queue_overflow')
                self.writer.manifest['overflow_gap_recorded'] = True
        self.writer.add_frame(kind, state, extra)
        from replay_modifications import attach_pending
        try:
            attach_pending(self.writer.directory, self.writer.manifest, state,
                           self.writer.index['frames'][-1], self.root.parent)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Keep original observations; provenance errors are a separate
            # training gate, never grounds to invent or lose replay frames.
            self.writer.manifest['modification_provenance_error'] = str(error)
            self.writer.write_manifest()
        if not self.writer.manifest.get('opening_locked'):
            info = classify_opening(state)
            if apply_opening(self.writer.manifest, info) or self.writer.seq == 1:
                try:
                    self.writer.write_manifest()
                except OSError:
                    pass
        if self.writer.manifest.get('opening_locked') and not self._should_keep(self.writer.manifest):
            self._discard_session('not_kept_format')
            return
        with self.lock:
            self.status['seq'] = self.writer.seq
            self.status['recording'] = True
            self.status['title'] = self.writer.manifest.get('title')

    def _gap(self, reason):
        if self.writer is None:
            return
        if self.open_gap and self.open_gap.get('reason') == reason:
            return
        self.open_gap = self.writer.add_gap(reason)
        with self.lock:
            self.status['last_gap'] = reason

    def _discard_session(self, reason='not_kept_format'):
        writer = self.writer
        if writer is None:
            return
        directory = writer.directory
        try:
            writer.close_stream()
        except Exception:
            pass
        self.writer = None
        self.current_key = None
        self.open_gap = None
        try:
            shutil.rmtree(directory)
        except OSError:
            pass
        with self.lock:
            self.status.update({
                'recording': False, 'open': False, 'directory': None,
                'title': None, 'completeness': 'discarded',
                'end_reason': reason, 'seq': 0,
            })

    def _seal(self, reason, completeness=None, dropped=None, started_mid_match=None):
        if self.writer is None:
            return
        writer = self.writer
        write_error = writer.manifest.get('write_error')
        dropped_n = 0 if dropped is None else dropped
        mid = writer.manifest.get('started_mid_match') if started_mid_match is None else started_mid_match
        if write_error:
            tag = 'write_error'
        elif writer.seq <= 0 or dropped_n:
            tag = 'interrupted'
        elif mid:
            tag = 'mid_start'
        elif reason in COMPLETE_REASONS:
            tag = 'complete'
        else:
            tag = 'interrupted'
        writer.manifest['open'] = False
        writer.manifest['ended_utc'] = self.clock()
        writer.manifest['end_reason'] = reason
        writer.manifest['completeness'] = tag
        if not writer.manifest.get('opening_locked'):
            apply_opening(writer.manifest, finalize_opening(classify_opening(writer.last_state), sealed=True))
        if not kept_archive(writer.manifest, self.keep_formats, self.keep_min_frames, seq=writer.seq):
            reason = 'too_short' if kept_opening(writer.manifest, self.keep_formats) else 'not_kept_format'
            self._discard_session(reason)
            return
        writer.manifest['dropped_frames'] = dropped_n
        writer.manifest['write_error'] = write_error
        writer.manifest['last_seq'] = writer.seq
        writer.manifest['frame_count'] = writer.seq
        writer.manifest.pop('overflow_gap_recorded', None)
        if writer.last_state:
            writer.manifest['last_snapshot_id'] = writer.last_state.get('snapshot_id')
            writer.manifest['last_capture_end'] = writer.last_state.get('capture_end')
        writer.write_index()
        writer.write_manifest()
        writer.close_stream()
        with self.lock:
            self.status.update({
                'recording': False, 'open': False, 'completeness': tag,
                'end_reason': reason, 'seq': writer.seq,
                'write_error': write_error,
            })
        self.writer = None
        self.current_key = None
        self.open_gap = None


def wait_recorder(recorder, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if recorder.pending_empty():
            time.sleep(0.02)
            if recorder.pending_empty():
                return
        time.sleep(0.02)


def payload_from_state(state, phase='live', error_class=None, source_id='local',
                       release='1.1.142', extra=None):
    ident = (state or {}).get('identity') or {}
    data = {
        'phase': phase,
        'error_class': error_class,
        'fresh': phase == 'live' and state is not None,
        'error': None if phase == 'live' else (error_class or phase),
        'source_id': source_id,
        'runtime_id': 'default',
        'release_version': release,
        'identity': ident,
        'pid': ident.get('pid'),
        'path': ident.get('path'),
        'state': state,
    }
    if extra:
        data.update(extra)
    return data


def build_demo_state(seq, year=200, season=1, filetime=9001, pid=4242, move=0, extra_units=None):
    x = 50 + move
    lords = [
        {'force_id': 0, 'name': '演示魏', 'gold': 10000 + seq, 'rice': 20000, 'prestige': 50,
         'troop_stock': {'infantry': 12000, 'cavalry': 8000, 'bow': 4000},
         'armament_raw': {'infantry': 120, 'cavalry': 40, 'bow': 10},
         'color_index_raw': 1, 'capital_city_id': 1},
        {'force_id': 1, 'name': '演示吴', 'gold': 8000, 'rice': 15000, 'prestige': 40,
         'troop_stock': {'infantry': 9000, 'cavalry': 2000, 'bow': 5000},
         'armament_raw': {'infantry': 90, 'cavalry': 20, 'bow': 30},
         'color_index_raw': 2, 'capital_city_id': 2},
    ]
    cities = [
        {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
         'population': 80000, 'world_xy_raw': [50, 100]},
        {'city_id': 2, 'name': '江陵', 'type': 'city', 'owner_raw': 1,
         'population': 60000, 'world_xy_raw': [52, 124]},
    ]
    buildings = [
        {'type': 'parade_ground', 'owner_raw': 0, 'building_ui_amount': 8000,
         'world_xy_raw': [51, 100], 'linked_city_id': 1, 'object_id_candidate': 11},
    ]
    units = [
        {'unit_id': 7, 'unit_kind': 'cavalry', 'owner_raw': 0, 'soldiers_candidate': 2400,
         'world_xy_raw': [x, 101], 'general_ids': [3], 'rice_candidate': 2400},
    ]
    if extra_units:
        units.extend(extra_units)
    generals = [
        {'general_id_raw': 3, 'name': '演示将', 'owner_raw': 0, 'status_code': 2,
         'location_city_id': 1, 'soldiers': 2400, 'attributes': {'lead': 80, 'war': 70, 'intel': 40, 'pol': 30, 'cha': 50}},
        {'general_id_raw': 9, 'name': '在野甲', 'owner_raw': 65535, 'status_code': 1,
         'location_city_id': 1, 'attributes': {'lead': 60, 'war': 60, 'intel': 60, 'pol': 60, 'cha': 60}},
    ]
    return {
        'schema': 'astra-sgi-core-2',
        'simulated': True,
        'snapshot_id': f'DEMO{year}{season}{seq:04d}',
        'capture_end': f'2026-09-16T0{season}:00:{seq:02d}+00:00',
        'identity': {'pid': pid, 'path': r'C:\sgi\run-3.5\3I\SANPK.exe', 'creation_filetime': filetime},
        'build_sha256': 'demo-build-not-a-real-sha',
        'player_context': {'force_id': 0, 'slot': 0, 'status': 'verified', 'source': 'demo'},
        'clock_candidates': {'year_u16': year, 'season_u16': season},
        'phase_candidate': {'year_u16': year, 'season_u16': season},
        'entities': {
            'lords': lords,
            'cities_and_barriers': cities,
            'production_buildings': buildings,
            'field_units': units,
            'generals': generals,
            'traps': [],
        },
        'current_local_projection': {'gold': 10000 + seq, 'rice': 20000, 'player_force_id': 0},
    }


def write_packed_archive(directory, states, *, seal_reason='process_gone', completeness='complete',
                         started_mid_match=False, simulated=False, extra_manifest=None,
                         keyframe_every=KEYFRAME_EVERY):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('frames.jsonl', 'index.json'):
        existing = directory / name
        if existing.exists():
            existing.unlink()
    first = states[0]
    ident = (first.get('identity') or {})
    manifest = {
        'format_version': FORMAT_VERSION,
        'open': False,
        'match_id': extra_manifest.get('match_id') if extra_manifest and extra_manifest.get('match_id') else str(uuid.uuid4()),
        'collector_version': release_version(),
        'game_build': first.get('build_sha256'),
        'schema': first.get('schema'),
        'source_id': 'demo' if simulated else 'local',
        'runtime_id': 'default',
        'process': ident,
        'started_utc': first.get('capture_end'),
        'ended_utc': states[-1].get('capture_end'),
        'end_reason': seal_reason,
        'completeness': completeness,
        'started_mid_match': started_mid_match,
        'first_frame_note': '从此处开始记录' if started_mid_match else None,
        'map_resources': map_resources(),
        'related_match_ids': [],
        'simulated': simulated,
        'frame_count': 0,
        'last_seq': 0,
        'last_snapshot_id': None,
        'dropped_frames': 0,
        'write_error': None,
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    writer = ArchiveWriter(directory, manifest)
    prev_phase = None
    for index, state in enumerate(states):
        phase = phase_of(state)
        kind = 'keyframe' if (index == 0 or (index % keyframe_every) == 0 or phase != prev_phase) else 'delta'
        extra = {}
        if index == 0 and started_mid_match:
            extra['first_frame_note'] = '从此处开始记录'
        writer.add_frame(kind, compact_state(state), extra)
        prev_phase = phase
    writer.manifest['open'] = False
    writer.manifest['end_reason'] = seal_reason
    writer.manifest['completeness'] = completeness
    writer.manifest['frame_count'] = writer.seq
    writer.manifest['last_seq'] = writer.seq
    if writer.last_state:
        writer.manifest['last_snapshot_id'] = writer.last_state.get('snapshot_id')
        writer.manifest['last_capture_end'] = writer.last_state.get('capture_end')
    opening = None
    for state in states:
        opening = classify_opening(state)
        if opening.get('opening_locked'):
            break
    apply_opening(writer.manifest, finalize_opening(opening or classify_opening(writer.last_state), sealed=True))
    writer.write_index()
    writer.write_manifest()
    writer.close_stream()
    return directory


def write_demo_archive(directory):
    """Labeled simulated match: two quarters, unit motion, then seal."""
    directory = Path(directory)
    frames = []
    for seq in range(6):
        frames.append(build_demo_state(seq, year=200, season=0, move=0))
    for seq in range(6, 14):
        state = build_demo_state(seq, year=200, season=1, move=seq - 6)
        if seq == 8:
            state['entities']['generals'][1] = dict(
                state['entities']['generals'][1], owner_raw=0, status_code=9,
            )
        if seq == 10:
            state['entities']['production_buildings'].append({
                'type': 'horse_farm', 'owner_raw': 0, 'building_ui_amount': 5000,
                'world_xy_raw': [52, 101], 'linked_city_id': 1, 'object_id_candidate': 22,
            })
        frames.append(state)
    return write_packed_archive(
        directory, frames, simulated=True, started_mid_match=False,
        extra_manifest={'demo_label': '模拟演示档案，不是真实对局', 'simulated': True},
    )
