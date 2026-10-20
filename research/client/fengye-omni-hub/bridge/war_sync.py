"""Bounded live upload plus disk-cursor history. Queue overflow is not catch-up."""
import collections
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

WRITE_HEADER = 'X-SGI-War-Write-Token'
READ_HEADER = 'X-SGI-War-Read-Token'
USER_AGENT = 'sgi-war-uploader/0.1'
LATEST_KIND = 'snapshot'
EVENTS_KIND = 'events'
GAP_KIND = 'gap'
CURSOR_NAME = 'upload-cursor.json'
EVENTS_BATCH = 20
CONFIG_DIR = Path.home() / '.config' / 'sgi-war'

_uploader = None
_uploader_lock = threading.Lock()


def idempotency_key(match_id, kind, seq, digest):
    return '%s:%s:%s:%s' % (match_id, kind, seq, digest[:16])


def digest_payload(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def load_env_file(path):
    values = {}
    path = Path(path) if path else None
    if not path or not path.is_file():
        return values
    for line in path.read_text(encoding='utf8').splitlines():
        text = line.strip()
        if not text or text.startswith('#') or '=' not in text:
            continue
        key, value = text.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_config_path():
    return Path(os.environ.get('SGI_WAR_WRITE_ENV') or CONFIG_DIR / 'write.env')


def read_config_path():
    return Path(os.environ.get('SGI_WAR_READ_ENV') or CONFIG_DIR / 'read.env')


def load_write_config():
    file_vals = load_env_file(write_config_path())
    url = os.environ.get('SGI_WAR_UPLOAD_URL') or file_vals.get('SGI_WAR_UPLOAD_URL')
    token = os.environ.get('SGI_WAR_WRITE_TOKEN') or file_vals.get('SGI_WAR_WRITE_TOKEN')
    if not url or not token:
        return None
    return {'url': url, 'token': token}


def load_read_config():
    file_vals = load_env_file(read_config_path())
    url = os.environ.get('SGI_WAR_READ_URL') or file_vals.get('SGI_WAR_READ_URL')
    token = os.environ.get('SGI_WAR_READ_TOKEN') or file_vals.get('SGI_WAR_READ_TOKEN')
    if not url or not token:
        return None
    return {'url': url.rstrip('/'), 'token': token}


class WarUploadCursor:
    """Persistent ack pointer. Restart resumes from disk, not from memory queue."""

    empty = {
        'match_id': None,
        'acked_seq': 0,
        'gaps': [],
        'lost_gaps': [],
        'queue_full_waits': 0,
        'last_error': None,
        'last_flush_utc': None,
    }

    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / CURSOR_NAME

    def load(self):
        if not self.path.is_file():
            return dict(self.empty)
        try:
            data = json.loads(self.path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            return dict(self.empty)
        out = dict(self.empty)
        out.update(data if isinstance(data, dict) else {})
        return out

    def save(self, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


class WarSyncQueue:
    """In-flight buffer only. Full rejects new history; disk cursor remains the backlog."""

    def __init__(self, history_max=8):
        self.history_max = history_max
        self.lock = threading.Lock()
        self.latest = None
        self.history = collections.deque()
        self.dropped_history = 0
        self.rejected_full = 0

    def offer_latest(self, item):
        with self.lock:
            self.latest = item
            return True

    def offer_history(self, item):
        with self.lock:
            if len(self.history) >= self.history_max:
                self.rejected_full += 1
                return False
            self.history.append(item)
            return True

    def pop_batch(self):
        with self.lock:
            latest = self.latest
            self.latest = None
            history = list(self.history)
            self.history.clear()
            return latest, history

    def space(self):
        with self.lock:
            return self.history_max - len(self.history)


class WarUploader:
    def __init__(self, url, write_token, queue=None, timeout=8):
        self.url = url
        self.write_token = write_token
        self.queue = queue or WarSyncQueue()
        self.timeout = timeout
        self.lock = threading.Lock()
        self.seen = set()
        self.last_error = None
        self.bytes_sent = 0
        self.uploads = 0
        self.archive_dir = None
        self.live_match_id = None
        self.flush_seconds = 0.0
        self.collect_offer_seconds = 0.0

    def pack_snapshot(self, query, seq=None, extra=None):
        view = query.latest_snapshot(before_seq=seq)
        match_id = view.get('match_id')
        seq = view.get('seq')
        manifest = query.manifest()
        payload = {
            'kind': LATEST_KIND,
            'match_id': match_id,
            'seq': seq,
            'snapshot_id': view.get('snapshot_id'),
            'capture_end': view.get('capture_end'),
            'completeness': view.get('completeness'),
            'title': manifest.get('title'),
            'format': manifest.get('format'),
            'match_kind': manifest.get('match_kind'),
            'player_identity': view.get('player_identity'),
            'freshness': view.get('freshness'),
            'gaps': view.get('gaps'),
            'state': view.get('data'),
            'omniscient': True,
            'visual_interpolation': False,
            'simulated': bool(manifest.get('simulated')),
            'test_fixture': bool((extra or {}).get('test_fixture') or manifest.get('test_fixture')
                                 or manifest.get('simulated')),
        }
        if extra:
            payload.update({key: extra[key] for key in extra if key != 'test_fixture'})
        digest = digest_payload({key: payload[key] for key in payload if not str(key).startswith('_')})
        payload['idempotency_key'] = idempotency_key(match_id, LATEST_KIND, seq, digest)
        return payload

    def pack_events(self, query, start_seq, end_seq, extra=None):
        view = query.events(start_seq=start_seq, end_seq=end_seq, end_inclusive=True, limit=500)
        payload = {
            'kind': EVENTS_KIND,
            'match_id': view.get('match_id'),
            'seq': view.get('seq'),
            'snapshot_id': view.get('snapshot_id'),
            'capture_end': view.get('capture_end'),
            'events': (view.get('data') or {}).get('events') or [],
            'visual_interpolation': False,
            'simulated': bool(query.manifest().get('simulated')),
            'test_fixture': bool((extra or {}).get('test_fixture') or query.manifest().get('simulated')),
        }
        digest = digest_payload(payload)
        payload['idempotency_key'] = idempotency_key(
            payload['match_id'], EVENTS_KIND, '%s-%s' % (start_seq, end_seq), digest)
        return payload

    def pack_gap(self, match_id, gap):
        payload = {
            'kind': GAP_KIND,
            'match_id': match_id,
            'seq': gap.get('after_seq') or gap.get('seq') or 0,
            'gap': gap,
            'visual_interpolation': False,
        }
        digest = digest_payload(payload)
        payload['idempotency_key'] = idempotency_key(match_id, GAP_KIND, payload['seq'], digest)
        return payload

    def pack_observed(self, observed, match_id, seq=None):
        state = observed.get('state')
        payload = {
            'kind': LATEST_KIND,
            'match_id': match_id,
            'seq': seq,
            'snapshot_id': None if not state else state.get('snapshot_id'),
            'capture_end': None if not state else state.get('capture_end'),
            'completeness': 'recording',
            'player_identity': {
                'status': ((state or {}).get('player_context') or {}).get('status') or 'unknown',
                'force_id': None,
                'confirmed': False,
                'guessed': False,
            },
            'state': state,
            'source_id': observed.get('source_id'),
            'omniscient': True,
            'visual_interpolation': False,
            'simulated': False,
            'test_fixture': False,
        }
        ctx = (state or {}).get('player_context') or {}
        if ctx.get('status') in ('verified', 'confirmed', 'user_confirmed'):
            payload['player_identity']['force_id'] = ctx.get('force_id')
            payload['player_identity']['confirmed'] = True
        digest = digest_payload(payload)
        payload['idempotency_key'] = idempotency_key(
            match_id or 'unknown', LATEST_KIND, seq if seq is not None else payload.get('snapshot_id') or 'none',
            digest)
        return payload

    def offer_live(self, observed, status):
        started = time.perf_counter()
        match_id = None if not status else status.get('match_id')
        seq = None if not status else status.get('seq')
        directory = None if not status else status.get('directory')
        if directory:
            self.archive_dir = directory
        self.live_match_id = match_id
        self.queue.offer_latest(self.pack_observed(observed, match_id, seq=seq))
        self.collect_offer_seconds += time.perf_counter() - started

    def offer_query(self, query, history=False, test_fixture=False):
        extra = {'test_fixture': test_fixture}
        snap = self.pack_snapshot(query, extra=extra)
        self.queue.offer_latest(snap)
        self.archive_dir = query.directory
        self.live_match_id = query.match_id()
        if history and snap.get('seq'):
            self.refill_from_archive(test_fixture=test_fixture)

    def refill_from_archive(self, test_fixture=False):
        if not self.archive_dir:
            return
        from replay_query import MatchQuery
        query = MatchQuery(self.archive_dir)
        try:
            cursor = WarUploadCursor(self.archive_dir)
            state = cursor.load()
            match_id = query.match_id()
            if state.get('match_id') and state['match_id'] != match_id:
                state['lost_gaps'] = list(state.get('lost_gaps') or [])
                state['lost_gaps'].append({
                    'reason': 'cursor_match_changed',
                    'previous_match_id': state.get('match_id'),
                    'acked_seq': state.get('acked_seq'),
                    'dropped_count': None,
                    'note': '游标对局已变，未把上一局未确认批次并入新局。',
                })
                state['acked_seq'] = 0
                state['gaps'] = []
            state['match_id'] = match_id
            latest = query.latest_seq()
            archive_gaps = list(query.cursor.reader.index.get('gaps') or [])
            if query.cursor.reader.index.get('seq_rewind_tail'):
                archive_gaps.append({'reason': 'seq_rewind_tail', 'after_seq': latest, 'dropped_count': None})
            known = {(row.get('reason'), row.get('after_seq')) for row in (state.get('gaps') or [])}
            for gap in archive_gaps:
                sign = (gap.get('reason'), gap.get('after_seq'))
                if sign in known:
                    continue
                packed = self.pack_gap(match_id, gap)
                packed['_cursor_ack_seq'] = state.get('acked_seq') or 0
                packed['_gap_record'] = gap
                if not self.queue.offer_history(packed):
                    state['queue_full_waits'] = (state.get('queue_full_waits') or 0) + 1
                    cursor.save(state)
                    return
                state.setdefault('gaps', []).append(gap)
            start = (state.get('acked_seq') or 0) + 1
            extra = {'test_fixture': test_fixture or bool(query.manifest().get('simulated'))}
            while start <= latest and self.queue.space() >= 2:
                end = min(latest, start + EVENTS_BATCH - 1)
                snap = self.pack_snapshot(query, seq=end, extra=extra)
                snap['_cursor_ack_seq'] = end
                ev = self.pack_events(query, start, end, extra=extra)
                ev['_cursor_ack_seq'] = end
                if not self.queue.offer_history(snap):
                    state['queue_full_waits'] = (state.get('queue_full_waits') or 0) + 1
                    break
                if not self.queue.offer_history(ev):
                    state['queue_full_waits'] = (state.get('queue_full_waits') or 0) + 1
                    break
                start = end + 1
            cursor.save(state)
        finally:
            query.close()

    def _ack(self, seq):
        if not self.archive_dir or not seq:
            return
        cursor = WarUploadCursor(self.archive_dir)
        state = cursor.load()
        state['acked_seq'] = max(int(state.get('acked_seq') or 0), int(seq))
        state['last_error'] = None
        state['last_flush_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        cursor.save(state)

    def _note_error(self, message):
        self.last_error = message
        if not self.archive_dir:
            return
        cursor = WarUploadCursor(self.archive_dir)
        state = cursor.load()
        state['last_error'] = message
        cursor.save(state)

    def flush(self):
        started = time.perf_counter()
        self.refill_from_archive()
        latest, history = self.queue.pop_batch()
        results = []
        if latest:
            results.append(self._post(self._public(latest)))
        failed = False
        leftover = []
        for item in history:
            if failed:
                leftover.append(item)
                continue
            ack = item.get('_cursor_ack_seq')
            gap = item.get('_gap_record')
            result = self._post(self._public(item))
            results.append(result)
            if result.get('ok'):
                if ack:
                    self._ack(ack)
            else:
                failed = True
                leftover.append(item)
        for item in leftover:
            if not self.queue.offer_history(item):
                # Still on disk via un-acked cursor. Do not invent a silent drop.
                if self.archive_dir:
                    cursor = WarUploadCursor(self.archive_dir)
                    state = cursor.load()
                    state['queue_full_waits'] = (state.get('queue_full_waits') or 0) + 1
                    cursor.save(state)
        self.flush_seconds += time.perf_counter() - started
        return results

    def _public(self, payload):
        return {key: value for key, value in payload.items() if not str(key).startswith('_')}

    def _post(self, payload):
        key = payload.get('idempotency_key')
        with self.lock:
            if key in self.seen:
                return {'ok': True, 'action': 'duplicate', 'idempotency_key': key}
        body = json.dumps(payload, ensure_ascii=False).encode('utf8')
        req = urllib.request.Request(
            self.url, data=body, method='POST',
            headers={
                'Content-Type': 'application/json',
                WRITE_HEADER: self.write_token,
                'User-Agent': USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode('utf8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
            self._note_error(str(error))
            kind = payload.get('kind')
            if kind == LATEST_KIND:
                self.queue.offer_latest(payload)
            else:
                self.queue.offer_history(payload)
            return {'ok': False, 'error': str(error)}
        self.bytes_sent += len(body)
        self.uploads += 1
        if data.get('ok') and key:
            with self.lock:
                self.seen.add(key)
        return data


class WarReader:
    def __init__(self, base, read_token, timeout=8):
        self.base = base.rstrip('/')
        self.read_token = read_token
        self.timeout = timeout

    def get(self, path):
        req = urllib.request.Request(
            self.base + path, method='GET',
            headers={READ_HEADER: self.read_token, 'User-Agent': USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode('utf8'))


def get_shared_uploader():
    global _uploader
    cfg = load_write_config()
    if not cfg:
        return None
    with _uploader_lock:
        if _uploader is None:
            _uploader = WarUploader(cfg['url'], cfg['token'])

            def _flush():
                while True:
                    try:
                        _uploader.flush()
                    except Exception:
                        pass
                    time.sleep(3)

            threading.Thread(target=_flush, daemon=True, name='sgi-war-upload').start()
        return _uploader
