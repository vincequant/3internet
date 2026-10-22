"""One-shot evidence for 1.1.138. Does not start the collector or Grok."""
import json
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bridge'))
from replay_query import MatchQuery
from sgi_war_cli import main as cli_main
from war_server import serve
from war_sync import WarReader, WarUploader

DEMO = ROOT / 'app' / 'demo_replay_match'


def capture_cli(argv):
    from io import StringIO
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = cli_main(argv)
    finally:
        sys.stdout = old
    return code, json.loads(buf.getvalue())


def main():
    evidence = {
        'version': '1.1.138',
        'simulated_demo': True,
        'live_hook_enabled': False,
        'note': '演示档案一致性与本地私有接口；运行中桥未切本版，不能当连续分析可靠。',
    }
    query = MatchQuery(DEMO)
    try:
        t0 = time.perf_counter()
        local = query.latest_snapshot()
        latest_s = time.perf_counter() - t0
        t1 = time.perf_counter()
        summary = query.summary()
        summary_s = time.perf_counter() - t1
        t2 = time.perf_counter()
        events = query.events(start_seq=1, end_seq=14, end_inclusive=True, limit=200)
        events_s = time.perf_counter() - t2
        t3 = time.perf_counter()
        track = query.unit_track(7)
        track_s = time.perf_counter() - t3
        code, cli = capture_cli(['summary', '--demo'])
        code2, cli_latest = capture_cli(['latest', '--demo'])
        code3, cli_track = capture_cli(['track', '--demo', '--unit-id', '7'])
        evidence['cli_exit'] = [code, code2, code3]
        evidence['local'] = {
            'match_id': local['match_id'],
            'seq': local['seq'],
            'snapshot_id': local['snapshot_id'],
            'capture_end': local['capture_end'],
            'omniscient': local['omniscient'],
            'visual_interpolation': local['visual_interpolation'],
            'player_identity': local['player_identity'],
            'force_count': summary['data']['force_count'],
            'event_total': events['data']['total'],
            'track_found': track['data']['found'],
            'track_samples': sum(len(row.get('samples') or []) for row in track['data']['tracks']),
            'latest_seconds': round(latest_s, 4),
            'summary_seconds': round(summary_s, 4),
            'events_seconds': round(events_s, 4),
            'track_seconds': round(track_s, 4),
        }
        evidence['cli_matches_query'] = {
            'summary_match_id': cli['match_id'] == local['match_id'],
            'summary_seq': cli['seq'] == local['seq'],
            'latest_snapshot_id': cli_latest['snapshot_id'] == local['snapshot_id'],
            'track_found': cli_track['data']['found'] is True,
            'guessed_false': cli['player_identity']['guessed'] is False,
        }
        store_server = serve('127.0.0.1', 0, 'write-secret', 'read-secret')
        thread = threading.Thread(target=store_server.serve_forever, daemon=True)
        thread.start()
        host, port = store_server.server_address
        base = 'http://127.0.0.1:%s' % port
        try:
            uploader = WarUploader(base + '/api/sgi-war/ingest', 'write-secret')
            uploader.offer_query(query, history=True)
            t4 = time.perf_counter()
            flush = uploader.flush()
            upload_s = time.perf_counter() - t4
            t5 = time.perf_counter()
            remote = WarReader(base, 'read-secret').get(
                '/api/sgi-war/matches/%s/latest' % local['match_id'])
            remote_s = time.perf_counter() - t5
            remote_events = WarReader(base, 'read-secret').get(
                '/api/sgi-war/matches/%s/events?from=1&to=15' % local['match_id'])
            denied = None
            try:
                WarReader(base, 'wrong').get('/api/sgi-war/matches')
            except urllib.error.HTTPError as error:
                denied = error.code
                error.close()
            evidence['remote'] = {
                'match_id': remote.get('match_id'),
                'seq': remote.get('seq'),
                'snapshot_id': remote.get('snapshot_id'),
                'same_match': remote.get('match_id') == local['match_id'],
                'same_seq': remote.get('seq') == local['seq'],
                'same_snapshot': remote.get('snapshot_id') == local['snapshot_id'],
                'same_state_snapshot': (remote.get('state') or {}).get('snapshot_id') == local['data'].get('snapshot_id'),
                'flush_ok': any(row.get('ok') for row in flush),
                'bytes_sent': uploader.bytes_sent,
                'uploads': uploader.uploads,
                'upload_seconds': round(upload_s, 4),
                'remote_latest_seconds': round(remote_s, 4),
                'remote_event_count': len(remote_events.get('events') or []),
                'unauthorized_read': denied,
            }
        finally:
            store_server.shutdown()
            store_server.server_close()
    finally:
        query.close()
    out = Path(__file__).with_name('war-query-verify-1.1.138.json')
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'wrote': str(out), 'same_snapshot': evidence['remote']['same_snapshot'],
                      'unauthorized_read': evidence['remote']['unauthorized_read']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
