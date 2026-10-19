#!/usr/bin/env python3
"""SGI direct-connect launcher (per-machine, per-account).

One command brings up a playable SANPK client that is already logged in and
(optionally) inside a listed room -- no manual login screen.

Flow (same proven stack as the shadow launcher):
  existing SANPK -> keep it; existing SANGUO -> use its normal Start button
    without another login/logout, keeping the current account and room/line
  otherwise:
  protocol login (TCP 25001, HallSession, line from config)
    -> grant_for_takeover -> token
    -> stage win32_startserver.py (SANPK hash gate extended for this build)
    -> spawn the hub's win32 python helper in the target prefix
       (original StartServer + relay + launch SANPK -> 游戏选择 window,
        optional --join-name auto-join)
    -> hold the hall session until helper exit / STOP file / hold_seconds.

Files (JSON, both loaded relative to paths given on the command line):
  machine.json:
    {"hub": "...",              # dir containing room_monitor/ and bridge/
     "prefix": "...",           # target wine prefix (the account's game prefix)
     "wine": "...",             # wine binary (runtime-sikarugir10/wswine.bundle/bin/wine)
     "game_root": "C:\\sgi\\run-3.5",
     "line": "多线3（备用）",
     "data_dir": "...",         # logs + STOP file live here (default: machine.json dir)
     "accounts_dir": "...",     # default: <machine.json dir>/accounts
     "hold_seconds": 7200,
     "sanpk_allowed": ["<sha256>", ...]}
  accounts/<name>.json:
    {"username": "...", "password": "...", "join_name": "optional-default"}

Usage:
  python3 direct_connect.py --config machine.json --account dingman \
      [--join-name SGZWLB] [--hold-seconds 7200] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HELPER_SANPK_OLD = ("'SANPK.exe': '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',")
HELPER_SANPK_NEW = ("'SANPK.exe': ('1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',"
                    " 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea',"
                    " '02af252ce082e8682a1616a5a649e94f3497eb4d50c47348d34866ab6804de92'),")
HELPER_KOEINM_OLD = ("'Koeinm.dll': '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841',")
HELPER_KOEINM_NEW = ("'Koeinm.dll': ('629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841', '28476038d67d2f330860d88b3dd0be53594354107cfd26ecb36ddf8512d111d8'),")


def load_json(path, what):
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit('missing %s: %s' % (what, p))
    return json.loads(p.read_text(encoding='utf-8')), p


def reuse_existing_lobby(config, prefix, join_name, log, line=''):
    """Use the lobby's existing session; never log in, log out or replace it."""
    from sgi_room_monitor.lobby_ops import inspect_prefix, run_ops
    from sgi_room_monitor import win32_runtime as wr

    info = inspect_prefix(config, prefix, timeout=10)
    if not info.get('error') and info.get('logged_in') and not info.get('has_start'):
        # An authenticated lobby outside a room needs only tree navigation.
        # A lobby already in a room keeps its current line and membership.
        for title in ('三国对战房', line):
            if not title:
                continue
            run_ops(config, ['--select-tree', title], prefix, timeout=10)
            info = inspect_prefix(config, prefix, timeout=10)
            if info.get('has_start') or info.get('error'):
                break
    if info.get('error') or not info.get('has_start'):
        log(ev='existing_lobby_needs_user', ok=False,
            message=info.get('error') or '大厅尚未进入可启动游戏的房间；请在现有大厅进入房间，不会退出重登。')
        return 2
    log(ev='reuse_lobby', message='沿用现有大厅账号和线路，不重新登录。')
    started = run_ops(config, ['--start-game'], prefix, timeout=10)
    if (started.get('payload') or {}).get('status') != 'clicked':
        log(ev='existing_lobby_start_failed', ok=False,
            message=started.get('error') or '未能点击现有大厅的启动游戏；大厅保持运行。')
        return 2
    # Only finish the ordinary game-list UI. This helper owns no hall session.
    dest = Path(prefix) / 'drive_c/sgi/room_monitor'
    dest.mkdir(parents=True, exist_ok=True)
    source = Path(config['hub_root']) / 'room_monitor/sgi_room_monitor/win32_startserver.py'
    (dest / 'win32_startserver.py').write_bytes(source.read_bytes())
    (dest / 'reuse_lobby_game.py').write_bytes(Path(__file__).with_name('reuse_lobby_game.py').read_bytes())
    env, cmd, early = wr.win32_command(config, prefix, r'C:\sgi\room_monitor\reuse_lobby_game.py')
    if early:
        log(ev='existing_lobby_helper_failed', ok=False, detail=early)
        return 2
    try:
        result = subprocess.run(cmd, env=env, input=json.dumps({'join_name': join_name}),
                                text=True, capture_output=True, timeout=100)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as error:
        log(ev='existing_lobby_helper_failed', ok=False, reason=type(error).__name__)
        return 3
    log(ev='existing_lobby_result', **payload)
    return 0 if result.returncode == 0 and payload.get('ok') else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--account', required=True)
    ap.add_argument('--join-name', default='')
    ap.add_argument('--line', default='', help='hall line title, e.g. 多线2（主线） / 多线3（备用）')
    ap.add_argument('--hold-seconds', type=int, default=0)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    cfg, cfg_path = load_json(args.config, 'config')
    base_dir = cfg_path.parent
    hub = Path(os.path.expanduser(cfg['hub']))
    prefix = Path(os.path.expanduser(cfg['prefix']))
    wine = Path(os.path.expanduser(cfg['wine']))
    game_root = cfg.get('game_root', r'C:\sgi\run-3.5')
    line = args.line.strip() or cfg.get('line', '多线3（备用）')
    data_dir = Path(os.path.expanduser(cfg.get('data_dir') or str(base_dir)))
    accounts_dir = Path(os.path.expanduser(cfg.get('accounts_dir') or str(base_dir / 'accounts')))
    hold_seconds = args.hold_seconds or int(cfg.get('hold_seconds', 7200))
    sanpk_allowed = [s.lower() for s in (cfg.get('sanpk_allowed') or [])]

    (data_dir / 'logs').mkdir(parents=True, exist_ok=True)
    log_path = data_dir / 'logs' / ('direct-%s-%s.jsonl' % (args.account, time.strftime('%Y%m%d-%H%M%S')))

    def log(**kw):
        kw['wall'] = round(time.time(), 3)
        line_j = json.dumps(kw, ensure_ascii=False)
        print(line_j, flush=True)
        with log_path.open('a', encoding='utf-8') as fh:
            fh.write(line_j + '\n')

    # windows-side paths derived from game_root (e.g. C:\sgi\run-3.5)
    g = game_root.replace('/', '\\')
    if not (len(g) > 3 and g[1] == ':'):
        raise SystemExit('game_root must be like C:\\sgi\\run-3.5')
    g_parts = g[3:].split('\\')          # ['sgi', 'run-3.5']
    sgi_win = g[0] + ':\\' + g_parts[0]  # C:\sgi
    sgi_rel = g_parts[0]                 # sgi
    dest_dir = prefix / 'drive_c' / sgi_rel / 'room_monitor'
    script_win = Path(sgi_win + '\\room_monitor\\win32_startserver.py')
    sanpk = prefix / 'drive_c' / Path(g.replace('\\', '/')[3:]) / '3I' / 'SANPK.exe'

    log(ev='start', account=args.account, prefix=str(prefix),
        join_name=args.join_name or None, dry_run=bool(args.dry_run))

    checks = {
        'hub_room_monitor': (hub / 'room_monitor' / 'sgi_room_monitor').is_dir(),
        'hub_win32_python': (hub / 'bridge' / 'win32-python').is_dir(),
        'hub_host_python': (hub / 'bridge' / 'python' / 'python.exe').is_file(),
        'prefix': prefix.is_dir(),
        'wine': wine.is_file(),
        'sanpk': sanpk.is_file(),
    }
    sanpk_sha = hashlib.sha256(sanpk.read_bytes()).hexdigest() if sanpk.is_file() else None
    creds_path = accounts_dir / (args.account + '.json')
    checks['account_file'] = creds_path.is_file()
    log(ev='checks', **checks, sanpk_sha256=sanpk_sha)

    sys.path.insert(0, str(hub / 'room_monitor'))
    game_running = lobby_running = False
    if checks['hub_room_monitor'] and checks['prefix']:
        from sgi_room_monitor.platform import running_in_prefix
        game_running = running_in_prefix(str(prefix), 'SANPK.exe')
        lobby_running = running_in_prefix(str(prefix), 'SANGUO.exe')
    problems = [k for k, v in checks.items() if not v and
                not (k == 'account_file' and (game_running or lobby_running))]
    if sanpk_sha and sanpk_allowed and sanpk_sha.lower() not in sanpk_allowed:
        problems.append('sanpk_not_allowlisted')
    if args.dry_run:
        log(ev='dry_run', ok=not problems, problems=problems)
        return 0 if not problems else 2
    if problems:
        log(ev='abort', reason='checks', problems=problems)
        return 2

    if game_running:
        log(ev='reuse_game', ok=True, message='游戏已在运行，保留现有游戏与大厅，不重复登录。')
        return 0
    creds = json.loads(creds_path.read_text(encoding='utf-8')) if creds_path.is_file() else {}
    join_name = (args.join_name or creds.get('join_name') or '').strip()
    if lobby_running:
        return reuse_existing_lobby({'hub_root': str(hub), 'wine': str(wine)},
                                   prefix, join_name, log, line=line)

    from sgi_room_monitor.protocol_session import HallSession
    from sgi_room_monitor import win32_runtime as wr
    from sgi_room_monitor.win32_runtime import apply_win81, win81_already_set

    session = HallSession()
    res = session.login_and_enter(creds['username'], creds['password'], line_title=line)
    log(ev='login', **{k: res.get(k) for k in (
        'ok', 'submitted', 'stage', 'state', 'message', 'login_verified', 'entered',
        'game_name', 'room_name', 'game_id', 'room_id')})
    if not res.get('ok'):
        log(ev='abort', reason='login', stage=res.get('stage'))
        return 2
    grant = session.grant_for_takeover()
    if not grant or not grant.get('token'):
        log(ev='abort', reason='no_grant')
        session.close(logout=True)
        return 2
    log(ev='grant', virtual_ip=grant.get('virtual_ip'), server=grant.get('server'),
        port=grant.get('port'), game_id=grant.get('game_id'), user_id=grant.get('user_id'))

    config = {'hub_root': str(hub), 'wine': str(wine)}

    # stage the helper (scoped copy; hub install untouched) and make sure this
    # prefix's SANPK build is accepted by the helper's hash gate.
    src = hub / 'room_monitor' / 'sgi_room_monitor' / 'win32_startserver.py'
    script_text = src.read_text(encoding='utf-8')
    if sanpk_sha and sanpk_sha not in script_text:
        if HELPER_SANPK_OLD in script_text:
            script_text = script_text.replace(HELPER_SANPK_OLD, HELPER_SANPK_NEW)
            staged_patch = 'sanpk_hash_extended'
        elif 'df9b5225' in script_text:
            staged_patch = 'already_extended'
        else:
            log(ev='abort', reason='helper_patch_pattern')
            grant.clear()
            session.close(logout=True)
            return 2
        if sanpk_sha not in script_text:
            four = HELPER_SANPK_NEW.replace("),", ", '%s')," % sanpk_sha)
            script_text = script_text.replace(HELPER_SANPK_NEW, four)
            staged_patch = 'sanpk_hash_extended_plus'
    else:
        staged_patch = 'already'
    if HELPER_KOEINM_OLD in script_text:
        script_text = script_text.replace(HELPER_KOEINM_OLD, HELPER_KOEINM_NEW)
        staged_patch = staged_patch + '+koeinm'
    if sanpk_sha and sanpk_sha not in script_text:
        log(ev='abort', reason='sanpk_gate_missing', sanpk_sha256=sanpk_sha)
        grant.clear()
        session.close(logout=True)
        return 2
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / 'win32_startserver.py').write_text(script_text, encoding='utf-8')
    log(ev='helper_staged', patch=staged_patch, sanpk_sha256=sanpk_sha)

    helper = wr.helper_exe(str(hub))
    try:
        compat = apply_win81(config, prefix, helper)
    except Exception as error:
        compat = {'ok': False, 'reason': type(error).__name__}
    log(ev='win81_helper', **(compat or {}))
    try:
        apply_win81(config, prefix, sanpk, live=not win81_already_set(prefix, 'SANPK.exe'))
    except Exception as error:
        log(ev='win81_sanpk_error', error=type(error).__name__)

    env, cmd, early = wr.win32_command(config, prefix, script_win)
    if early:
        log(ev='abort', reason='helper_cmd', detail=early)
        grant.clear()
        session.close(logout=True)
        return 2
    payload = {
        'virtual_ip': grant.get('virtual_ip'), 'server': grant.get('server'),
        'port': grant.get('port'), 'game_id': grant.get('game_id'),
        'user_id': grant.get('user_id'), 'username': grant.get('username'),
        'token': grant.get('token'), 'launch_sanpk': True,
        'game_root': game_root, 'hold_seconds': int(hold_seconds),
    }
    if join_name:
        payload['join_name'] = join_name[:40]
    event_log = dest_dir / 'startserver-events.jsonl'
    event_log.write_text('', encoding='utf-8')
    log_handle = event_log.open('w', encoding='utf-8')
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=log_handle,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=True))
    proc.stdin.close()
    payload['token'] = None
    grant.clear()
    (data_dir / 'helper.pid').write_text(str(proc.pid), encoding='utf-8')
    log(ev='helper_spawned', pid=proc.pid)

    deadline = time.monotonic() + 90
    seen = 0
    ok = False
    join_result = None
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            lines = event_log.read_text(encoding='utf-8').splitlines()
        except OSError:
            lines = []
        while seen < len(lines):
            raw = lines[seen]
            seen += 1
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            name = ev.get('event')
            slim = {k: v for k, v in ev.items() if k in (
                'event', 'ok', 'relay_registered', 'pid', 'core_inject', 'join_name',
                'index', 'name', 'reason', 'list_count')}
            if name == 'game_search' and 'list_names' in ev:
                slim['list_names'] = ev['list_names'][:10]
            if name == 'game_join':
                join_result = ev
            log(helper=slim)
            if name == 'ready':
                ok = True
        if ok or proc.poll() is not None:
            break
    if proc.poll() is not None:
        log(ev='helper_exited', code=proc.returncode)
    log(ev='result', ok=ok, helper_pid=proc.pid, join=join_result)
    if ok:
        (data_dir / 'app.pid').write_text(str(os.getpid()), encoding='utf-8')
        end = time.monotonic() + int(hold_seconds)
        log(ev='hold_started', helper_pid=proc.pid)
        while time.monotonic() < end:
            time.sleep(2)
            if proc.poll() is not None:
                log(ev='helper_gone_during_hold', code=proc.returncode)
                break
            if (data_dir / 'STOP').exists():
                log(ev='stop_file_seen')
                break
        try:
            session.close(logout=True)
        except Exception:
            pass
        log(ev='session_closed')
    else:
        try:
            session.close(logout=True)
        except Exception:
            pass
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main())
