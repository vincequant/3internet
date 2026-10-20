"""Append-only journal of raw player-slot observations, including pre-selection.

This is not an identity database. Force values and source_metadata stay raw.
A capture session is not a match id. Machine-local files are not a release.
"""
import hashlib
import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'player-observation-1'
RESEARCHED_BUILD = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
MAX_AGE_S = 5.0
MAX_SLOTS = 8
MAX_RECORD_BYTES = 64 * 1024
MAX_SEGMENT_BYTES = 4 * 1024 * 1024
USER_LOW = 0x10000
USER_HIGH = 0x80000000
ALLOWED_PHASES = ('live', 'waiting_for_player')


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    raise TypeError('now must be a datetime')


def _age_s(capture_end, now):
    if not isinstance(capture_end, str) or not capture_end:
        return None
    try:
        end = datetime.fromisoformat(capture_end)
    except ValueError:
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    try:
        return (now - end).total_seconds()
    except (TypeError, ValueError):
        return None


def _parse_core(core):
    if type(core) is not str or len(core) < 3 or core[:2].lower() != '0x':
        return None
    try:
        value = int(core, 16)
    except ValueError:
        return None
    if value < USER_LOW or value >= USER_HIGH:
        return None
    return value


def _binding(identity, core):
    if not isinstance(identity, dict):
        return None
    pid = identity.get('pid')
    path = identity.get('path')
    created = identity.get('creation_filetime')
    if type(pid) is not int or pid <= 0 or type(path) is not str or not path or type(created) is not int or created <= 0:
        return None
    address = _parse_core(core)
    if address is None:
        return None
    return (pid, path, created, address)


def _layout_verified(layout, build):
    return (isinstance(layout, dict) and layout.get('verified') is True
            and build == RESEARCHED_BUILD and layout.get('build_sha256') == build)


def _slots_ok(slots):
    if not isinstance(slots, list) or len(slots) > MAX_SLOTS:
        return False
    seen = set()
    for row in slots:
        if not isinstance(row, dict):
            return False
        index = row.get('slot')
        if type(index) is not int or index < 0 or index > 7 or index in seen:
            return False
        seen.add(index)
    return True


def _reject(observed, now):
    if not isinstance(observed, dict):
        return 'missing_snapshot'
    if observed.get('error'):
        return 'error'
    if observed.get('phase') not in ALLOWED_PHASES:
        return 'phase'
    snap = observed.get('state')
    if not isinstance(snap, dict):
        return 'missing_snapshot'
    age = _age_s(snap.get('capture_end'), now)
    if age is None or age < 0 or age > MAX_AGE_S:
        return 'stale'
    if snap.get('coherence') is False:
        return 'incoherent'
    consistent = (snap.get('consistency') or {}).get('root_headers_and_clock_unchanged')
    if consistent is not True:
        return 'incoherent'
    build = snap.get('build_sha256')
    core_layout = _layout_verified(snap.get('player_slots_layout'), build)
    lobby_layout = _layout_verified(snap.get('lobby_player_slots_layout'), build)
    core_ok = core_layout and _slots_ok(snap.get('player_slots'))
    lobby_ok = lobby_layout and _slots_ok(snap.get('lobby_player_slots'))
    if not core_ok and not lobby_ok:
        return 'slots' if core_layout or lobby_layout else 'layout'
    identity = snap.get('identity') or {}
    if not isinstance(identity, dict):
        return 'binding'
    pid = identity.get('pid')
    path = identity.get('path')
    created = identity.get('creation_filetime')
    if type(pid) is not int or pid <= 0 or type(path) is not str or not path or type(created) is not int or created <= 0:
        return 'binding'
    if _parse_core(snap.get('core_address')) is None:
        return 'core'
    return None


def _record_bytes(record):
    try:
        return len((json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))
    except (TypeError, ValueError):
        return None


def _fingerprint(record):
    body = {
        'phase': record.get('phase'),
        'binding': record.get('target'),
        'core_address': record.get('core_address'),
        'build_sha256': record.get('build_sha256'),
        'player_slots': record.get('player_slots'),
        'player_slots_layout': record.get('player_slots_layout'),
        'lobby_player_slots': record.get('lobby_player_slots'),
        'lobby_player_slots_layout': record.get('lobby_player_slots_layout'),
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


class PlayerObservationJournal:
    def __init__(self, root=None, max_segment_bytes=MAX_SEGMENT_BYTES):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent.parent / 'player-observations'
        self.max_segment_bytes = max_segment_bytes
        self._lock = threading.Lock()
        self._fp = None
        self._binding = None
        self._session = None
        self._segment = 0
        self._path = None
        self._handle = None
        self._size = 0
        self._records = 0
        self._last_kind = None
        self._last_phase = None
        self._gapped = False
        self._seen_observation = False
        self.write_error = None

    def public_status(self):
        with self._lock:
            return {
                'enabled': True,
                'schema': SCHEMA,
                'directory_name': 'player-observations',
                'capture_session_id': self._session,
                'segment': self._segment or None,
                'records': self._records,
                'last_kind': self._last_kind,
                'last_phase': self._last_phase,
                'gapped': self._gapped,
                'write_error': self.write_error,
                'attribution_not_final': True,
                'stable_account_id_verified': False,
                'native_command_captured': False,
            }

    def close(self):
        try:
            with self._lock:
                self._close_handle()
        except Exception as error:
            self.write_error = str(error)

    def ingest(self, observed, now=None):
        try:
            moment = _now(now)
        except Exception as error:
            self.write_error = str(error)
            return
        try:
            with self._lock:
                self._ingest(observed, moment)
        except Exception as error:
            self.write_error = str(error)

    def _flags(self):
        return {
            'schema': SCHEMA,
            'attribution_not_final': True,
            'stable_account_id_verified': False,
            'native_command_captured': False,
            'force_selection_confirmed': False,
            'capture_session_is_match_id': False,
            'capture_session_id': self._session,
        }

    def _gap(self, now, reason):
        if self._seen_observation and not self._gapped and self._session:
            if self._write(dict(self._flags(), kind='player_observation_gap', reason=reason,
                                observed_at=now.isoformat())):
                self._gapped = True

    def _ingest(self, observed, now):
        reason = _reject(observed, now)
        if reason:
            self._gap(now, reason)
            return
        snap = observed['state']
        identity = snap['identity']
        binding = _binding(identity, snap.get('core_address'))
        if binding != self._binding:
            self._close_handle()
            self._binding = binding
            self._session = str(uuid.uuid4())
            self._segment = 0
            self._path = None
            self._size = 0
            self._fp = None
            self._gapped = False
            self._seen_observation = False
        record = dict(self._flags(), kind='player_slot_observation',
                      phase=observed.get('phase'), fresh=observed.get('fresh'),
                      snapshot_id=snap.get('snapshot_id'),
                      capture_start=snap.get('capture_start'), capture_end=snap.get('capture_end'),
                      source_id=observed.get('source_id'), runtime_id=observed.get('runtime_id'),
                      release_version=observed.get('release_version'),
                      target={'pid': identity['pid'], 'path': identity['path'],
                              'creation_filetime': identity['creation_filetime']},
                      core_address=snap.get('core_address'), build_sha256=snap.get('build_sha256'),
                      player_slots=deepcopy(snap.get('player_slots')),
                      player_slots_layout=deepcopy(snap.get('player_slots_layout')),
                      lobby_player_slots=deepcopy(snap.get('lobby_player_slots')),
                      lobby_player_slots_layout=deepcopy(snap.get('lobby_player_slots_layout')))
        encoded = _record_bytes(record)
        if encoded is None or encoded > MAX_RECORD_BYTES:
            self._gap(now, 'too_large')
            self.write_error = 'record exceeds %d bytes' % MAX_RECORD_BYTES
            return
        fp = _fingerprint(record)
        if fp == self._fp and not self._gapped:
            return
        if self._write(record):
            self._fp = fp
            self._gapped = False
            self._seen_observation = True

    def _write(self, record):
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n'
            data = line.encode('utf-8')
            if len(data) > MAX_RECORD_BYTES or len(data) > MAX_SEGMENT_BYTES:
                self.write_error = 'record exceeds %d bytes' % MAX_RECORD_BYTES
                return False
            if self._handle is None or (self._size and self._size + len(data) > self.max_segment_bytes):
                self._open_next()
            self._handle.write(line)
            self._handle.flush()
            self._size += len(data)
            self._records += 1
            self._last_kind = record.get('kind')
            self._last_phase = record.get('phase')
            self.write_error = None
            return True
        except Exception as error:
            self.write_error = str(error)
            return False

    def _open_next(self):
        self._close_handle()
        directory = self.root / hashlib.sha256(repr(self._binding).encode('utf-8')).hexdigest()[:20]
        directory.mkdir(parents=True, exist_ok=True)
        while True:
            self._segment += 1
            path = directory / ('%s-seg-%04d.jsonl' % (self._session, self._segment))
            if not path.exists():
                break
        self._path = path
        self._handle = path.open('a', encoding='utf-8')
        self._size = path.stat().st_size

    def _close_handle(self):
        handle = self._handle
        self._handle = None
        if handle is not None:
            handle.close()
