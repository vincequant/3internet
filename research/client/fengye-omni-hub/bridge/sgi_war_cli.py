"""Read-only CLI for Hub archives or the private remote war API. Never starts the collector."""
import argparse
import json
import os
import sys
from pathlib import Path

from game_archive import default_archive_root
from replay_query import MatchQuery, current_match, list_matches
from war_sync import WarReader, load_read_config

APP = Path(__file__).resolve().parent.parent / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
from stealth_raid import raid_plans_payload, state_for_raid


def emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write('\n')


def local_query(args):
    if args.cmd == 'matches':
        emit({'ok': True, 'matches': list_matches(args.root), 'current': current_match(args.root)})
        return
    current = current_match(args.root)
    directory = args.archive or current.get('directory')
    if not directory:
        emit({'ok': False, 'error': 'no_archive'})
        return
    query = MatchQuery(directory)
    try:
        if args.cmd == 'summary':
            emit(query.summary(seq=args.seq))
        elif args.cmd == 'latest':
            emit(query.latest_snapshot(before_seq=args.before_seq))
        elif args.cmd == 'snapshot':
            if args.capture_end:
                emit(query.snapshot_at_capture(args.capture_end))
            else:
                emit(query.latest_snapshot(before_seq=args.seq))
        elif args.cmd == 'events':
            emit(query.events(start_seq=args.start, end_seq=args.end, entity=args.entity,
                              owner=args.owner, evidence=args.evidence, limit=args.limit))
        elif args.cmd == 'track':
            emit(query.unit_track(args.unit_id, generation=args.generation,
                                  start_seq=args.start, end_seq=args.end))
        elif args.cmd == 'force':
            emit(query.force_detail(args.force_id, seq=args.seq))
        elif args.cmd == 'city':
            emit(query.city_detail(args.city_id, seq=args.seq))
        elif args.cmd == 'general':
            emit(query.general_detail(args.general_id, seq=args.seq))
        elif args.cmd == 'unit':
            emit(query.unit_detail(args.unit_id, seq=args.seq, generation=args.generation))
        elif args.cmd == 'raid':
            view = query.latest_snapshot(before_seq=args.seq)
            emit(_raid_from_view(view, args))
        else:
            emit({'ok': False, 'error': 'unknown_command'})
    finally:
        query.close()


def remote_query(args, cfg):
    reader = WarReader(cfg['url'], cfg['token'])
    if args.cmd == 'matches':
        emit(reader.get('/api/sgi-war/matches'))
        return
    match_id = args.match_id
    if not match_id:
        listing = reader.get('/api/sgi-war/matches')
        rows = listing.get('matches') or []
        live = [row for row in rows if not row.get('test_fixture')]
        pick = (live or rows)
        match_id = listing.get('default_match_id') or (pick[0]['match_id'] if pick else None)
    if not match_id:
        emit({'ok': False, 'error': 'no_remote_match'})
        return
    q = []
    if args.seq:
        q.append('seq=%s' % args.seq)
    if args.capture_end:
        q.append('capture_end=%s' % args.capture_end)
    if args.start is not None:
        q.append('from=%s' % args.start)
    if args.end is not None:
        q.append('to=%s' % args.end)
    if args.limit:
        q.append('limit=%s' % args.limit)
    if args.unit_id is not None:
        q.append('unit_id=%s' % args.unit_id)
    suffix = ('?' + '&'.join(q)) if q else ''
    if args.cmd == 'latest':
        emit(reader.get('/api/sgi-war/matches/%s/latest' % match_id))
    elif args.cmd == 'summary':
        emit(reader.get('/api/sgi-war/matches/%s/summary%s' % (match_id, suffix)))
    elif args.cmd == 'snapshot':
        emit(reader.get('/api/sgi-war/matches/%s/snapshot%s' % (match_id, suffix)))
    elif args.cmd == 'events':
        emit(reader.get('/api/sgi-war/matches/%s/events%s' % (match_id, suffix)))
    elif args.cmd == 'track':
        emit(reader.get('/api/sgi-war/matches/%s/track%s' % (match_id, suffix)))
    elif args.cmd in ('force', 'city', 'general', 'unit'):
        ident = {'force': args.force_id, 'city': args.city_id,
                 'general': args.general_id, 'unit': args.unit_id}[args.cmd]
        if ident is None:
            emit({'ok': False, 'error': 'missing_%s_id' % args.cmd})
            return
        extra = ('?seq=%s' % args.seq) if args.seq else ''
        emit(reader.get('/api/sgi-war/matches/%s/%s/%s%s' % (match_id, args.cmd, ident, extra)))
    elif args.cmd == 'raid':
        snap = reader.get('/api/sgi-war/matches/%s/snapshot%s' % (match_id, suffix))
        emit(_raid_from_view(snap, args))
    else:
        emit({'ok': False, 'error': 'unknown_command'})


def _raid_limit(args):
    value = args.limit
    if value is None or value == 100:
        return 3
    return value


def _raid_from_view(view, args):
    if not view or view.get('ok') is False:
        return view or {'ok': False, 'error': 'no_snapshot'}
    state = view.get('state') or view.get('data')
    ident = view.get('player_identity') or {}
    if state and ident.get('confirmed') and ident.get('force_id') is not None:
        state = dict(state)
        state['player_force_id'] = ident.get('force_id')
        state['player_identity'] = {'status': 'confirmed', 'force_id': ident.get('force_id')}
        ctx = dict(state.get('player_context') or {})
        ctx.setdefault('force_id', ident.get('force_id'))
        ctx.setdefault('status', 'verified')
        state['player_context'] = ctx
        state = state_for_raid(state)
    body = raid_plans_payload(
        state,
        dest_force_id=args.dest_force_id,
        origin_city_id=args.origin_city_id,
        limit=_raid_limit(args),
    )
    body.update({
        'ok': True,
        'found': True,
        'match_id': view.get('match_id'),
        'seq': view.get('seq'),
        'snapshot_id': view.get('snapshot_id'),
        'capture_end': view.get('capture_end'),
        'completeness': view.get('completeness'),
        'player_identity': ident or body.get('player_identity'),
    })
    return body


def build_parser():
    parser = argparse.ArgumentParser(
        description='SGI war-state read-only query. 远端密钥只从 ~/.config/sgi-war/read.env 或环境变量读取。')
    parser.add_argument('cmd', choices=[
        'matches', 'summary', 'latest', 'snapshot', 'events', 'track',
        'force', 'city', 'general', 'unit', 'raid',
    ])
    parser.add_argument('--root', default=os.environ.get('SGI_HUB_REPLAY') or str(default_archive_root()))
    parser.add_argument('--archive')
    parser.add_argument('--demo', action='store_true',
                        help='use bundled app/demo_replay_match (simulated, not a live match)')
    parser.add_argument('--local', action='store_true', help='force local archive even if remote config exists')
    parser.add_argument('--remote', help='remote base URL; default comes from protected read.env')
    parser.add_argument('--match-id')
    parser.add_argument('--seq', type=int)
    parser.add_argument('--before-seq', type=int)
    parser.add_argument('--capture-end')
    parser.add_argument('--start', type=int)
    parser.add_argument('--end', type=int)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--entity')
    parser.add_argument('--owner', type=int)
    parser.add_argument('--evidence')
    parser.add_argument('--unit-id', type=int)
    parser.add_argument('--generation', type=int)
    parser.add_argument('--force-id', type=int)
    parser.add_argument('--dest-force-id', type=int)
    parser.add_argument('--origin-city-id', type=int)
    parser.add_argument('--city-id', type=int)
    parser.add_argument('--general-id', type=int)
    return parser


def resolve_read(args):
    cfg = load_read_config() or {}
    url = args.remote or cfg.get('url')
    token = cfg.get('token')
    if not url or not token:
        return None
    return {'url': url.rstrip('/'), 'token': token}


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.demo and not args.archive:
        args.archive = str(Path(__file__).resolve().parent.parent / 'app' / 'demo_replay_match')
    remote = None if args.local or args.demo or args.archive else resolve_read(args)
    if args.remote and not args.local and not args.demo and not args.archive:
        remote = resolve_read(args)
        if not remote:
            emit({'ok': False, 'error': 'missing_read_config',
                  'note': '在 ~/.config/sgi-war/read.env 写入 SGI_WAR_READ_URL 与 SGI_WAR_READ_TOKEN，权限 0600。不要把密钥写进命令行。'})
            return 2
    if remote:
        remote_query(args, remote)
        return 0
    local_query(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
