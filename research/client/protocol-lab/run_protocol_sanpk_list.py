"""Login main account, StartServer, launch SANPK, report 游戏选择 names. Optional join.

Does not write UserConfig. Never logs token or password.
"""
import json
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
HUB = LAB.parent / 'SGI-Hub-CrossOver-M4-0.2'


def main():
    sys.path.insert(0, str(HUB / 'room_monitor'))
    from sgi_room_monitor.credentials import load_credentials
    from sgi_room_monitor.protocol_session import HallSession
    from sgi_room_monitor.provision import default_paths
    from sgi_room_monitor.sanpk_takeover import try_launch_playable_sanpk

    join_name = 'kwankwan'
    if len(sys.argv) > 1 and sys.argv[1] == '--no-join':
        join_name = ''
    elif len(sys.argv) > 1:
        join_name = sys.argv[1][:40]
    paths = default_paths()
    prefix = paths['main_prefix']
    runtime = json.loads(
        (Path.home() / 'Library/Application Support/SGI-Wine/runtime.json').read_text(encoding='utf-8'))
    creds = load_credentials({
        'main_account_username': runtime.get('main_account_username') or '',
        'hub_root': str(HUB),
    }, prompt=False, kind='main')
    username = (creds.get('username') or '').strip()
    password = creds.get('password') or ''
    if not username or not password:
        print(json.dumps({'ok': False, 'error': 'no_main_creds'}))
        return 2
    session = HallSession()
    report = {'ok': False, 'join_name': join_name or None}
    keep = False
    try:
        login = session.login_and_enter(username, password, line_title='多线2', timeout=12)
        password = None
        creds = None
        report['login'] = {k: login.get(k) for k in
                           ('ok', 'message', 'game_name', 'room_name', 'game_id', 'room_id')}
        if not login.get('ok'):
            print(json.dumps(report, ensure_ascii=False))
            return 2
        takeover = try_launch_playable_sanpk(
            prefix, session=session,
            config={'hub_root': str(HUB), 'wine': str(paths['wine']),
                    'join_name': join_name},
        )
        report['takeover'] = {
            'ok': takeover.get('ok'),
            'reason': takeover.get('reason'),
            'message': takeover.get('message'),
        }
        if not takeover.get('ok'):
            print(json.dumps(report, ensure_ascii=False))
            return 2
        events_path = prefix / 'drive_c/sgi/room_monitor/startserver-events.jsonl'
        deadline = time.monotonic() + 40
        search = None
        joined = None
        while time.monotonic() < deadline:
            try:
                lines = events_path.read_text(encoding='utf-8', errors='replace').splitlines()
            except OSError:
                lines = []
            for line in lines:
                if not line.startswith('{'):
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get('event') == 'game_search':
                    search = {k: row.get(k) for k in
                              ('ok', 'list_count', 'list_names', 'log', 'wait')}
                if row.get('event') == 'game_join':
                    joined = {k: row.get(k) for k in row if k != 'event'}
            if search and (not join_name or joined):
                break
            time.sleep(0.4)
        report['nethook'] = {}
        report['search'] = search
        report['join'] = joined
        try:
            for line in events_path.read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('{'):
                    row = json.loads(line)
                    if row.get('event') in ('nethook_core', 'nethook_window', 'relay', 'cwd'):
                        report['nethook'][row['event']] = {k: row[k] for k in row if k != 'event'}
        except (OSError, json.JSONDecodeError):
            pass
        report['ok'] = bool(search and (search.get('list_count') or 0) > 0)
        keep = bool((joined or {}).get('ok') or report['ok'])
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if keep and takeover.get('proc') is not None:
            try:
                takeover['proc'].wait(timeout=300)
            except Exception:
                pass
        return 0 if keep else 1
    finally:
        if not keep:
            session.close(logout=True)


if __name__ == '__main__':
    raise SystemExit(main())
