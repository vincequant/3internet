"""Passive sampling of an already joined local SANPK process.

One worker owns its read-only handle and journal. It never connects to a room,
calls game functions, consumes queues, writes game memory, or sends input.
Queue observations provide partial evidence, not decoded action labels.
"""
import ctypes
import hashlib
import os
import stat
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from network_payloads import (
    DIRECTORY_NAME, SANPK_BUILD, MAX_SESSION_BYTES, NetworkPayloadObserver,
    PayloadJournal, _binding_fields, _identity_matches, _in_range, _module_ok,
    resolve_network_module,
)

MAX_EXE_BYTES = 16 * 1024 * 1024
MAX_DIRECTORY_BYTES = 1024 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 4096
MAX_DIRECTORY_DEPTH = 4
INTERVAL_S = 0.020
BACKOFF_S = 5.0
MAX_AGE_S = 4.0


def _utcnow():
    return datetime.now(timezone.utc)


def _core(value):
    if type(value) is int:
        return value
    if type(value) is str and len(value) <= 16:
        try:
            return int(value, 0)
        except ValueError:
            pass
    return None


def _desired(payload, now):
    """Copy only bounded binding fields, never retain the world snapshot."""
    if not isinstance(payload, dict) or payload.get('error'):
        return None, 'no_current_snapshot'
    phase = payload.get('phase')
    if phase not in ('live', 'waiting_for_player'):
        return None, 'phase'
    if phase == 'live' and payload.get('fresh') is not True:
        return None, 'not_fresh'
    state = payload.get('state')
    if not isinstance(state, dict):
        return None, 'no_current_snapshot'
    consistency = state.get('consistency')
    if not isinstance(consistency, dict) or consistency.get('root_headers_and_clock_unchanged') is not True:
        return None, 'incoherent'
    when = state.get('capture_end')
    if type(when) is not str or len(when) > 128:
        return None, 'capture_time'
    try:
        end = datetime.fromisoformat(when)
        if end.tzinfo is None:
            return None, 'capture_time'
        age = (now - end).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return None, 'capture_time'
    if not -1 <= age <= MAX_AGE_S:
        return None, 'stale'
    identity, nested = payload.get('identity'), state.get('identity')
    if not isinstance(identity, dict) or not isinstance(nested, dict):
        return None, 'identity'
    if any(identity.get(key) != nested.get(key) for key in ('pid', 'path', 'creation_filetime')):
        return None, 'identity'
    image = identity.get('path')
    if type(image) is not str or len(image) > 32768 or image.replace('\\', '/').rsplit('/', 1)[-1].lower() != 'sanpk.exe':
        return None, 'image'
    core = _core(state.get('core_address'))
    if payload.get('core_address') is not None and _core(payload['core_address']) != core:
        return None, 'core_mismatch'
    binding = _binding_fields({
        'pid': identity.get('pid'), 'created': identity.get('creation_filetime'),
        'image': image, 'core': core, 'build': state.get('build_sha256'),
        'source_id': payload.get('source_id'),
    })
    if binding is None:
        return None, 'binding'
    return {'binding': binding, 'capture_end': end, 'phase': phase}, None


def directory_bytes(directory, entry_limit=MAX_DIRECTORY_ENTRIES):
    """Bounded metadata scan of our journal directory; no deletion or links."""
    directory = Path(directory)
    try:
        mode = directory.lstat().st_mode
    except FileNotFoundError:
        return 0
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise ValueError('quota_unknown: journal root is not a regular directory')
    # Wine can expose a host symlink as an ordinary Windows file/directory.
    # Final-path resolution still reveals the alias. Canonicalize the parent
    # first so ordinary Mac ancestors such as /var -> /private/var are fine.
    expected = directory.parent.resolve(strict=True) / directory.name
    directory = directory.resolve(strict=True)
    if os.path.normcase(str(expected)) != os.path.normcase(str(directory)):
        raise ValueError('quota_unknown: aliased journal root')
    stack, total, entries = [(directory, 0)], 0, 0
    while stack:
        path, depth = stack.pop()
        if depth > MAX_DIRECTORY_DEPTH:
            raise ValueError('quota_unknown: directory depth limit')
        with os.scandir(path) as listing:
            for entry in listing:
                entries += 1
                if entries > entry_limit:
                    raise ValueError('quota_unknown: entry limit')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError('quota_unknown: symbolic link')
                resolved = Path(entry.path).resolve(strict=True)
                if os.path.normcase(str(resolved)) != os.path.normcase(entry.path):
                    raise ValueError('quota_unknown: aliased entry')
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
                elif stat.S_ISDIR(info.st_mode):
                    stack.append((Path(entry.path), depth + 1))
                else:
                    raise ValueError('quota_unknown: nonregular file')
    return total


class ReadOnlyMemory:
    """Independent 0x410 handle, bounded reads, and scalar failure counters."""
    def __init__(self, binding, api=None, read_file=None, read_process=None):
        from probe import WindowsProcessApi
        self.api = api or WindowsProcessApi()
        self.h = None
        self.identity = None
        self.calls = self.bytes = self.read_failures = 0
        self._read_process = read_process
        try:
            self.h = self.api.open_process(binding['pid'])
            path = self.api.query_path(self.h)
            created, when = self.api.process_times(self.h)
            self.identity = {'pid': binding['pid'], 'path': path,
                             'creation_filetime': created, 'created_utc': when}
            if not _identity_matches(self, binding):
                raise ValueError('process_identity_changed')
            if read_file is None:
                file = Path(path)
                if not 0 < file.stat().st_size <= MAX_EXE_BYTES:
                    raise ValueError('executable_size')
                with file.open('rb') as handle:
                    data = handle.read(MAX_EXE_BYTES + 1)
            else:
                data = read_file(path)
            if not isinstance(data, bytes) or not 0 < len(data) <= MAX_EXE_BYTES:
                raise ValueError('executable_size')
            if hashlib.sha256(data).hexdigest() != SANPK_BUILD:
                raise ValueError('unsupported_executable')
        except Exception:
            self.close()
            raise

    def read(self, address, size):
        self.calls += 1
        if not _in_range(address, size) or size > 8192 or not self.h:
            self.read_failures += 1
            return None
        try:
            if self._read_process is not None:
                data = self._read_process(self.h, address, size)
            else:
                from probe import kernel
                buffer = ctypes.create_string_buffer(size)
                got = ctypes.c_size_t()
                ok = kernel().ReadProcessMemory(self.h, ctypes.c_void_p(address), buffer,
                                                size, ctypes.byref(got))
                data = buffer.raw if ok and got.value == size else None
            if not isinstance(data, bytes) or len(data) != size:
                raise ValueError('short_read')
            self.bytes += size
            return data
        except Exception:
            self.read_failures += 1
            return None

    def close(self):
        handle, self.h = self.h, None
        if handle:
            self.api.close_handle(handle)


class PayloadCapture:
    def __init__(self, root=None, *, memory_factory=None, module_resolver=None,
                 observer_factory=None, journal_factory=None, clock=None,
                 monotonic=None, interval=INTERVAL_S, max_session_bytes=MAX_SESSION_BYTES,
                 max_directory_bytes=MAX_DIRECTORY_BYTES):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        self._factory = memory_factory or ReadOnlyMemory
        self._resolve = module_resolver or resolve_network_module
        self._observe = observer_factory or NetworkPayloadObserver
        self._journal_factory = journal_factory or PayloadJournal
        self._clock, self._monotonic = clock or _utcnow, monotonic or time.monotonic
        self._interval = max(0.020, float(interval))
        for budget in (max_session_bytes, max_directory_bytes):
            if type(budget) is not int or budget <= 0:
                raise ValueError('positive byte budget required')
        self._session_budget = min(max_session_bytes, MAX_SESSION_BYTES)
        self._directory_budget = min(max_directory_bytes, MAX_DIRECTORY_BYTES)
        self._fake = any(item is not None for item in (memory_factory, module_resolver, observer_factory, journal_factory))
        self._lock = threading.Lock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = None
        self._owner = None
        self._desired = None
        self._desired_reason = 'no_current_snapshot'
        self._revision = 0
        self._closed = False
        self._memory = self._observer = self._journal = self._module = self._binding = None
        self._retry_key = None
        self._retry_at = 0
        self._retry_phase = 'backoff'
        self._unknown_run = 0
        self._polls = self._partials = self._unknowns = self._discarded = self._errors = 0
        self._last_error = None
        self._last_journal = self._last_module = self._last_binding = None
        self._last_reader = None
        self._status = {}
        self._publish('waiting')

    def start(self):
        with self._lock:
            if self._closed or self._thread is not None:
                return
            if self._owner is not None:
                raise RuntimeError('synchronous step cannot be mixed with start')
            thread = threading.Thread(target=self._run, name='sgi-payload-sample', daemon=True)
            self._thread = thread
        try:
            thread.start()
        except Exception as error:
            self._last_error = str(error)[:200]
            self._publish('stopped', self._last_error)

    def update(self, payload):
        try:
            desired, reason = _desired(payload, self._clock())
        except Exception:
            desired, reason = None, 'invalid_snapshot'
        with self._lock:
            if self._closed:
                return
            old = self._desired['binding'] if self._desired else None
            new = desired['binding'] if desired else None
            if old != new:
                self._revision += 1
            self._desired, self._desired_reason = desired, reason
        if old != new:
            self._wake.set()

    def public_status(self):
        with self._lock:
            return deepcopy(self._status)

    def _publish(self, phase, error=None, shutdown_pending=False):
        journal = self._journal.public_status() if self._journal else None
        status = {
            'enabled': True, 'phase': phase, 'error': error, 'last_error': self._last_error,
            'directory_name': DIRECTORY_NAME, 'binding': deepcopy(self._binding),
            'last_binding': deepcopy(self._last_binding), 'module': deepcopy(self._last_module),
            'journal': journal, 'last_journal': deepcopy(self._last_journal),
            'reader': ({name: getattr(self._memory, name, None) for name in ('calls', 'bytes', 'read_failures')}
                       if self._memory else deepcopy(self._last_reader)),
            'polls': self._polls, 'partial_polls': self._partials, 'unknown_polls': self._unknowns,
            'discarded_polls': self._discarded, 'errors': self._errors,
            'interval_s': self._interval, 'interval_is_soft': True,
            'max_session_bytes': self._session_budget, 'max_directory_bytes': self._directory_budget,
            'shutdown_pending': shutdown_pending, 'fake': self._fake,
            'coverage': 'partial', 'completeness': 'unknown', 'read_only': True,
            'no_target_calls': True, 'absence_means_no_command': False,
            'action_training_eligible': False, 'capture_session_is_match_id': False,
        }
        with self._lock:
            self._status = status

    def _finish(self):
        journal, memory = self._journal, self._memory
        self._journal = self._memory = self._observer = self._module = None
        if self._binding:
            self._last_binding = dict(self._binding)
        self._binding = None
        try:
            if journal is not None:
                journal.close()
                self._last_journal = journal.public_status()
        finally:
            if memory is not None:
                self._last_reader = {name: getattr(memory, name, None) for name in ('calls', 'bytes', 'read_failures')}
                memory.close()

    def _fail(self, key, error, phase='backoff'):
        self._errors += 1
        self._last_error = str(error)[:200]
        self._retry_key, self._retry_at = key, self._monotonic() + BACKOFF_S
        self._retry_phase = phase
        try:
            self._finish()
        except Exception as closing:
            self._last_error += '; close: ' + str(closing)[:100]
        self._publish(phase, self._last_error)

    def step(self):
        """Single-owner synchronous step, also used by deterministic tests."""
        ident = threading.get_ident()
        if self._owner is None:
            self._owner = ident
        if self._owner != ident:
            raise RuntimeError('payload resources belong to another thread')
        with self._lock:
            desired, reason, revision = self._desired, self._desired_reason, self._revision
        if self._stop.is_set() or self._closed:
            self._finish()
            self._publish('stopped')
            return
        if desired is not None:
            age = (self._clock() - desired['capture_end']).total_seconds()
            if not -1 <= age <= MAX_AGE_S:
                desired, reason = None, 'stale'
        if desired is None:
            self._finish()
            self._publish('waiting', reason)
            return
        binding = desired['binding']
        key = tuple(binding.items())
        if self._binding is not None and self._binding != binding:
            self._finish()
        if self._retry_key != key:
            self._retry_key, self._retry_at = key, 0
        if self._monotonic() < self._retry_at:
            self._publish(self._retry_phase, self._last_error)
            return
        try:
            if self._memory is None:
                used = directory_bytes(self.root / DIRECTORY_NAME)
                remaining = self._directory_budget - used
                if remaining <= 0:
                    self._fail(key, 'directory_quota_exceeded', 'quota')
                    return
                self._memory = self._factory(binding)
                if not _identity_matches(self._memory, binding):
                    raise ValueError('process_identity_changed')
                self._binding = dict(binding)
                self._module = self._resolve(self._memory)
                if _module_ok(self._module) is None:
                    raise ValueError('network_module_unknown')
                self._module = dict(self._module)
                if self._fake:
                    self._module['fake'] = True
                self._last_module = {name: self._module.get(name) for name in ('base', 'path', 'sha256', 'status', 'fake')}
                self._observer = self._observe(self._memory, binding, self._module)
                self._journal = self._journal_factory(self.root, binding,
                                                      max_session_bytes=min(remaining, self._session_budget))
                self._unknown_run = 0
            poll = self._observer.poll()
            self._polls += 1
            with self._lock:
                latest, latest_revision = self._desired, self._revision
            expired = latest is None or not -1 <= (self._clock() - latest['capture_end']).total_seconds() <= MAX_AGE_S
            stopping = self._stop.is_set() or self._closed
            if revision != latest_revision or expired or stopping:
                self._discarded += 1
                reason = 'capture_stopped_during_poll' if stopping else 'binding_revoked_during_poll'
                gap = dict(poll, status='unknown', events=[], gaps=[{'reason': reason}])
                self._journal.ingest(gap, self._module)
                self._finish()
                self._publish('stopped' if stopping else 'waiting', reason)
                return
            self._journal.ingest(poll, self._module)
            saved = self._journal.public_status()
            if saved.get('quota_exceeded'):
                self._fail(key, 'session_quota_exceeded', 'quota')
                return
            if saved.get('write_error'):
                self._fail(key, 'journal_write_error: ' + str(saved['write_error']))
                return
            status = poll.get('status')
            self._partials += status == 'partial'
            self._unknowns += status == 'unknown'
            self._unknown_run = self._unknown_run + 1 if status == 'unknown' else 0
            if self._unknown_run >= 3:
                self._fail(key, 'observer_unknown: ' + str(poll.get('reason')))
                return
            self._publish('sampling', 'observer_unknown' if status == 'unknown' else None)
        except Exception as error:
            self._fail(key, error)

    def _run(self):
        try:
            while not self._stop.is_set():
                self.step()
                self._wake.wait(self._interval)
                self._wake.clear()
        except Exception as error:
            self._last_error = str(error)[:200]
        finally:
            try:
                self._finish()
            except Exception as error:
                self._last_error = str(error)[:200]
            self._publish('stopped', self._last_error)

    def close(self):
        with self._lock:
            self._closed = True
            thread = self._thread
        self._stop.set()
        self._wake.set()
        if thread is not None and thread.ident is not None and thread is not threading.current_thread():
            thread.join(2)
        if thread is not None and thread.is_alive():
            # Never close a handle that the worker may still be reading.
            with self._lock:
                self._status.update(phase='stopping', shutdown_pending=True)
        elif self._owner in (None, threading.get_ident()):
            self._finish()
            self._publish('stopped', self._last_error)
