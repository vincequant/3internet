"""Upload Hub picker time-node snapshots for battlefield review. No tokens on stdout."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]

from history_review import archive_time_nodes, review_archives
from replay_query import MatchQuery
from war_sync import WarUploader, load_write_config


def unique_nodes(directory):
    seen = set()
    rows = []
    for item in archive_time_nodes(directory):
        seq = item.get('seq')
        if not isinstance(seq, int) or seq in seen:
            continue
        seen.add(seq)
        rows.append(item)
    return rows


def main():
    cfg = load_write_config()
    if not cfg:
        print(json.dumps({'ok': False, 'error': 'missing_write_config'}, ensure_ascii=False))
        return 2
    archives = review_archives()
    # Upload the dialog selection last so the remote default is 中山 vs 南蛮 if present.
    prefer = '6880a13b'
    archives.sort(key=lambda row: 1 if str(row.get('match_id') or '').startswith(prefer) else 0)
    uploader = WarUploader(cfg['url'], cfg['token'], timeout=90)
    report = {'ok': True, 'matches': [], 'accepted': 0, 'duplicate': 0, 'failed': 0, 'bytes': 0}
    started = time.perf_counter()
    for row in archives:
        match = {
            'match_id': row.get('match_id'),
            'title': row.get('title'),
            'frame_count': row.get('frame_count') or row.get('last_seq'),
            'nodes': [],
        }
        query = MatchQuery(row['directory'])
        try:
            for node in unique_nodes(row['directory']):
                item = {'label': node.get('label'), 'seq': node.get('seq')}
                try:
                    payload = uploader.pack_snapshot(query, seq=node['seq'])
                    result = uploader._post(payload)
                except Exception as error:
                    item.update({'ok': False, 'error': str(error)[:200]})
                    report['failed'] += 1
                    match['nodes'].append(item)
                    continue
                item['ok'] = bool(result.get('ok'))
                item['action'] = result.get('action') or result.get('error')
                item['remote_seq'] = payload.get('seq')
                if result.get('ok') and result.get('action') == 'duplicate':
                    report['duplicate'] += 1
                elif result.get('ok'):
                    report['accepted'] += 1
                else:
                    report['failed'] += 1
                    item['error'] = str(result.get('error') or 'upload_failed')[:200]
                match['nodes'].append(item)
        finally:
            query.close()
        report['matches'].append(match)
        print(json.dumps({
            'progress': match['title'] or match['match_id'],
            'nodes': len(match['nodes']),
            'failed': sum(1 for item in match['nodes'] if not item.get('ok')),
        }, ensure_ascii=False), flush=True)
    report['bytes'] = uploader.bytes_sent
    report['seconds'] = round(time.perf_counter() - started, 1)
    out = ROOT / 'logs' / 'upload-review-20260921.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({
        'ok': report['failed'] == 0,
        'accepted': report['accepted'],
        'duplicate': report['duplicate'],
        'failed': report['failed'],
        'bytes': report['bytes'],
        'seconds': report['seconds'],
        'matches': len(report['matches']),
        'report': str(out),
    }, ensure_ascii=False))
    return 0 if report['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
