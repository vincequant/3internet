"""Private in-process war-state store and HTTP adapter. Isolated from /tk."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from replay_query import freshness_of, player_identity
from war_sync import READ_HEADER, WRITE_HEADER

MAX_BODY = 8 * 1024 * 1024


def _state_of(payload):
    if not payload:
        return None
    return payload.get('state') or payload.get('data')


def _envelope(payload, data, extra=None):
    state = _state_of(payload)
    body = {
        'ok': data is not None,
        'found': data is not None,
        'match_id': None if not payload else payload.get('match_id'),
        'seq': None if not payload else payload.get('seq'),
        'snapshot_id': None if not payload else payload.get('snapshot_id'),
        'capture_end': None if not payload else payload.get('capture_end'),
        'freshness': freshness_of(None if not payload else payload.get('capture_end'),
                                  gaps=None if not payload else payload.get('gaps')),
        'gaps': [] if not payload else list(payload.get('gaps') or []),
        'completeness': None if not payload else payload.get('completeness'),
        'omniscient': True,
        'visual_interpolation': False,
        'simulated': bool(payload and payload.get('simulated')),
        'test_fixture': bool(payload and payload.get('test_fixture')),
        'player_identity': player_identity(state),
        'data': data,
    }
    if extra:
        body.update(extra)
    return body


def summary_data(state):
    ents = (state or {}).get('entities') or {}
    lords = list(ents.get('lords') or [])
    return {
        'force_count': len(lords),
        'city_count': len(ents.get('cities_and_barriers') or []),
        'unit_count': len(ents.get('field_units') or []),
        'general_count': len(ents.get('generals') or []),
        'building_count': len(ents.get('production_buildings') or []),
        'forces': [{'force_id': row.get('force_id'), 'name': row.get('name'),
                    'gold': row.get('gold'), 'rice': row.get('rice'),
                    'prestige': row.get('prestige')} for row in lords],
        'evidence': 'fact',
        'note': '全知快照摘要，未裁成我方视野。',
    }


def track_from_snapshots(snapshots, unit_id):
    samples = []
    for seq in sorted(snapshots):
        state = _state_of(snapshots[seq])
        units = ((state or {}).get('entities') or {}).get('field_units') or []
        hits = [row for row in units if row.get('unit_id') == unit_id]
        if len(hits) != 1:
            continue
        row = hits[0]
        samples.append({
            'seq': seq,
            'snapshot_id': snapshots[seq].get('snapshot_id'),
            'xy': (row.get('world_xy_raw') or [None, None])[:2],
            'owner': row.get('owner_raw'),
            'kind': row.get('unit_kind'),
            'interpolated': False,
        })
    return {'tracks': [{'unit_id': unit_id, 'samples': samples, 'interpolated': False}],
            'found': bool(samples), 'evidence': 'observed_change'}


class WarStore:
    def __init__(self):
        self.matches = {}
        self.keys = set()

    def ingest(self, payload):
        if not isinstance(payload, dict):
            return {'ok': False, 'error': 'invalid_json_object'}
        match_id = payload.get('match_id')
        kind = payload.get('kind')
        key = payload.get('idempotency_key')
        if not match_id or not kind:
            return {'ok': False, 'error': 'missing_match_or_kind'}
        if key and key in self.keys:
            return {'ok': True, 'action': 'duplicate', 'match_id': match_id}
        incoming_test = bool(payload.get('test_fixture') or payload.get('simulated'))
        existing = self.matches.get(match_id)
        if existing and bool(existing.get('test_fixture')) != incoming_test:
            return {'ok': False, 'error': 'test_live_isolation',
                    'note': '测试对局与真实对局不能互相覆盖。'}
        slot = self.matches.setdefault(match_id, {
            'match_id': match_id,
            'snapshots': {},
            'events': [],
            'gaps': [],
            'latest_seq': 0,
            'test_fixture': incoming_test,
            'simulated': bool(payload.get('simulated')),
        })
        seq = payload.get('seq') or 0
        if kind == 'snapshot' and payload.get('state') is not None:
            previous = slot['snapshots'].get(seq)
            if previous is None or seq >= (slot.get('latest_seq') or 0):
                slot['snapshots'][seq] = payload
            elif seq not in slot['snapshots']:
                slot['snapshots'][seq] = payload
            else:
                slot['snapshots'][seq] = payload
            if seq >= (slot.get('latest_seq') or 0):
                slot['latest_seq'] = seq
                slot['latest'] = payload
        elif kind == 'events':
            have = {(item.get('match_id'), item.get('seq'), item.get('field'), item.get('entity'),
                     json.dumps(item.get('target') or {}, sort_keys=True))
                    for item in slot['events']}
            for item in payload.get('events') or []:
                sign = (item.get('match_id'), item.get('seq'), item.get('field'), item.get('entity'),
                        json.dumps(item.get('target') or {}, sort_keys=True))
                if sign not in have:
                    slot['events'].append(item)
                    have.add(sign)
            slot['events'].sort(key=lambda row: row.get('seq') or 0)
        elif kind == 'gap':
            slot['gaps'].append(payload.get('gap') or payload)
        if key:
            self.keys.add(key)
        return {'ok': True, 'action': 'accepted', 'match_id': match_id, 'seq': seq}

    def list_matches(self):
        rows = []
        for match_id, slot in self.matches.items():
            latest = slot.get('latest') or {}
            rows.append({
                'match_id': match_id,
                'latest_seq': slot.get('latest_seq'),
                'capture_end': latest.get('capture_end'),
                'completeness': latest.get('completeness'),
                'simulated': bool(slot.get('simulated') or latest.get('simulated')),
                'test_fixture': bool(slot.get('test_fixture')),
            })
        return rows

    def latest(self, match_id):
        slot = self.matches.get(match_id)
        if not slot or not slot.get('latest'):
            return {'ok': False, 'found': False, 'match_id': match_id}
        return {'ok': True, 'found': True, **slot['latest']}

    def snapshot(self, match_id, seq=None, capture_end=None):
        slot = self.matches.get(match_id)
        if not slot:
            return {'ok': False, 'found': False, 'match_id': match_id}
        if seq is not None:
            payload = slot['snapshots'].get(int(seq))
            if not payload:
                return {'ok': False, 'found': False, 'reason': 'missing_seq'}
            return {'ok': True, 'found': True, **payload}
        if capture_end:
            hit = None
            for item_seq, payload in sorted(slot['snapshots'].items()):
                capture = payload.get('capture_end')
                if capture and str(capture) <= str(capture_end):
                    hit = payload
                elif capture and str(capture) > str(capture_end):
                    break
            if hit is None:
                return {'ok': False, 'found': False, 'reason': 'before_first_frame'}
            return {'ok': True, 'found': True, 'did_not_select_future': True, **hit}
        return self.latest(match_id)

    def events(self, match_id, start_seq=None, end_seq=None, offset=0, limit=100):
        slot = self.matches.get(match_id)
        if not slot:
            return {'ok': False, 'found': False, 'match_id': match_id}
        rows = list(slot.get('events') or [])
        if start_seq is not None:
            rows = [row for row in rows if (row.get('seq') or 0) >= int(start_seq)]
        if end_seq is not None:
            rows = [row for row in rows if (row.get('seq') or 0) < int(end_seq)]
        page = rows[offset:offset + limit]
        latest = slot.get('latest') or {}
        return _envelope(latest, {
            'events': page, 'total': len(rows), 'offset': offset, 'limit': limit,
            'sorted_by': 'observation_seq_asc',
        }, extra={'gaps': list(slot.get('gaps') or [])})

    def summary(self, match_id, seq=None):
        payload = self.snapshot(match_id, seq=seq)
        if not payload.get('found'):
            return payload
        return _envelope(payload, summary_data(_state_of(payload)))

    def entity(self, match_id, kind, ident, seq=None):
        payload = self.snapshot(match_id, seq=seq)
        if not payload.get('found'):
            return payload
        state = _state_of(payload) or {}
        ents = state.get('entities') or {}
        if kind == 'force':
            rows = [row for row in ents.get('lords') or [] if row.get('force_id') == ident]
            key = 'force'
        elif kind == 'city':
            rows = [row for row in ents.get('cities_and_barriers') or [] if row.get('city_id') == ident]
            key = 'city'
        elif kind == 'general':
            rows = [row for row in ents.get('generals') or [] if row.get('general_id_raw') == ident]
            key = 'general'
        else:
            rows = [row for row in ents.get('field_units') or [] if row.get('unit_id') == ident]
            key = 'unit'
        if len(rows) != 1:
            return _envelope(payload, {'items': rows, 'evidence': 'fact'}, extra={
                'found': bool(rows), 'identity_uncertain': len(rows) != 1,
            })
        return _envelope(payload, {key: rows[0], 'evidence': 'fact'})

    def track(self, match_id, unit_id):
        slot = self.matches.get(match_id)
        if not slot:
            return {'ok': False, 'found': False, 'match_id': match_id}
        latest = slot.get('latest') or {}
        return _envelope(latest, track_from_snapshots(slot.get('snapshots') or {}, unit_id))


def make_handler(store, write_token, read_token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def _deny(self, code, error):
            body = json.dumps({'ok': False, 'error': error}).encode('utf8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _ok(self, payload, code=200):
            body = json.dumps(payload, ensure_ascii=False).encode('utf8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/api/sgi-war/ingest':
                return self._deny(404, 'not_found')
            if self.headers.get(WRITE_HEADER) != write_token:
                return self._deny(401, 'unauthorized_write')
            if self.headers.get(READ_HEADER):
                return self._deny(403, 'read_token_cannot_write')
            length = int(self.headers.get('Content-Length') or 0)
            if not 0 < length <= MAX_BODY:
                return self._deny(413, 'invalid_size')
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode('utf8'))
            except ValueError:
                return self._deny(400, 'invalid_json')
            self._ok(store.ingest(payload))

        def do_GET(self):
            parsed = urlparse(self.path)
            if self.headers.get(READ_HEADER) != read_token:
                return self._deny(401, 'unauthorized_read')
            if self.headers.get(WRITE_HEADER):
                return self._deny(403, 'write_token_cannot_read')
            if parsed.path == '/api/sgi-war/matches':
                return self._ok({'ok': True, 'matches': store.list_matches()})
            parts = parsed.path.strip('/').split('/')
            if len(parts) >= 4 and parts[0] == 'api' and parts[1] == 'sgi-war' and parts[2] == 'matches':
                match_id = parts[3]
                query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                seq = int(query['seq']) if query.get('seq') else None
                if len(parts) == 4 or (len(parts) == 5 and parts[4] == 'latest'):
                    return self._ok(store.latest(match_id))
                if len(parts) == 5 and parts[4] == 'summary':
                    return self._ok(store.summary(match_id, seq=seq))
                if len(parts) == 5 and parts[4] == 'snapshot':
                    return self._ok(store.snapshot(match_id, seq=seq, capture_end=query.get('capture_end')))
                if len(parts) == 5 and parts[4] == 'events':
                    start = int(query['from']) if query.get('from') else None
                    end = int(query['to']) if query.get('to') else None
                    offset = int(query.get('offset') or 0)
                    limit = int(query.get('limit') or 100)
                    return self._ok(store.events(match_id, start_seq=start, end_seq=end,
                                                 offset=offset, limit=limit))
                if len(parts) == 5 and parts[4] == 'track':
                    return self._ok(store.track(match_id, int(query['unit_id'])))
                if len(parts) == 6 and parts[4] in ('force', 'city', 'general', 'unit'):
                    ident = int(parts[5])
                    return self._ok(store.entity(match_id, parts[4], ident, seq=seq))
            return self._deny(404, 'not_found')

    return Handler


def serve(host, port, write_token, read_token, store=None):
    store = store or WarStore()
    server = ThreadingHTTPServer((host, port), make_handler(store, write_token, read_token))
    server.store = store
    return server
