#!/usr/bin/env python3
"""P51 shadow client launcher (lab-owned; runs inside the GUI session).

Flow: protocol login as 風夜 (TCP 25001, HallSession) -> grant -> StartServer
helper (hashed official sgi-py32 + win32_startserver.py) -> playable SANPK in
the shadow prefix at the 游戏选择 window -> optional auto-join a listed room
by substring (--join-name). Never retries; only touches prefix-fengye-shadow.

Deployed on vkquant-com at ~/sgi-protocol-lab-20260915/shadow/launch_shadow.py
(launched via VKShadowLauncher.app so wine gets a GUI session). Reuses the
vetted room_monitor stack WITHOUT its stale SANPK-hash gate (current official
build df9b5225 is checked by the lab's own receipts instead).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
HUB = HOME / 'Applications/SGI-Hub'
SHADOW = HOME / 'sgi-protocol-lab-20260915/shadow'
PREFIX = HOME / 'Library/Application Support/SGI-Wine/prefix-fengye-shadow'
WINE = HOME / 'Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine'
GAME_ROOT_WIN = r'C:\sgi\run-3.5'
LINE_TITLE = '多线3（备用）'
SANPK_ALLOWED = (
    '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',  # network hotfix
    'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea',  # current (destructor hotfix)
    '02af252ce082e8682a1616a5a649e94f3497eb4d50c47348d34866ab6804de92',  # shadow nullguard build (2026-10-17)
)
HELPER_SANPK_OLD = ("'SANPK.exe': '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',")
HELPER_SANPK_NEW = ("'SANPK.exe': ('1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',"
                    " 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea',"
                    " '02af252ce082e8682a1616a5a649e94f3497eb4d50c47348d34866ab6804de92'),")
# 2026-10-18 evening: staged-helper patch #2 - capture the shadow SANPK's
# Wine SEH log (first-chance exceptions included) so a future AV can be
# pinned to an exact Eip. Child-only: WINEDEBUG applies to the game process.
HELPER_STDERR_RE = re.compile(
    r"(stdin=subprocess\.DEVNULL,\n)(\s*)"
    r"(stdout=subprocess\.DEVNULL,\n)(\s*)"
    r"(stderr=subprocess\.DEVNULL,\n)(\s*)\)"
)
HELPER_STDERR_REPL = (
    r"\1\2\3\4stderr=open(str(root / '3I' / 'sanpk-stderr.log'), 'ab'),\n"
    r"\4env=dict(os.environ, WINEDEBUG='-all,+seh'),\n\6)"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--join-name', default='')
    ap.add_argument('--hold-seconds', type=int, default=7200)
    args = ap.parse_args()

    (SHADOW / 'logs').mkdir(parents=True, exist_ok=True)
    log_path = SHADOW / 'logs' / ('launch-%s.jsonl' % time.strftime('%Y%m%d-%H%M%S'))

    def log(**kw):
        kw['wall'] = round(time.time(), 3)
        line = json.dumps(kw, ensure_ascii=False)
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as fh:
            fh.write(line + '\n')

    sys.path.insert(0, str(HUB / 'room_monitor'))
    from sgi_room_monitor.protocol_session import HallSession
    from sgi_room_monitor import win32_runtime as wr
    from sgi_room_monitor.win32_runtime import apply_win81, win81_already_set

    creds = json.loads((SHADOW / 'fengye-credentials.json').read_text(encoding='utf-8'))
    log(ev='start', prefix=str(PREFIX), join_name=args.join_name or None)

    session = HallSession()
    res = session.login_and_enter(creds['username'], creds['password'], line_title=LINE_TITLE)
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

    config = {'hub_root': str(HUB), 'wine': str(WINE)}

    src = HUB / 'room_monitor/sgi_room_monitor/win32_startserver.py'
    dest_dir = PREFIX / 'drive_c/sgi/room_monitor'
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Scoped patch of the STAGED copy only (hub install untouched): extend the
    # helper's SANPK hash gate with the current official build (df9b5225).
    script_text = src.read_text(encoding='utf-8')
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
    script_text, n_stderr = HELPER_STDERR_RE.subn(HELPER_STDERR_REPL, script_text, count=1)
    stderr_patch = 'sanpk_stderr_seh' if n_stderr else 'stderr_pattern_missing'
    (dest_dir / 'win32_startserver.py').write_text(script_text, encoding='utf-8')
    sanpk = PREFIX / 'drive_c/sgi/run-3.5/3I/SANPK.exe'
    sanpk_sha = hashlib.sha256(sanpk.read_bytes()).hexdigest()
    log(ev='helper_staged', patch=staged_patch, stderr_patch=stderr_patch,
        sanpk_sha256=sanpk_sha, sanpk_allowed=sanpk_sha in SANPK_ALLOWED)
    if sanpk_sha not in SANPK_ALLOWED:
        log(ev='abort', reason='sanpk_receipt')
        grant.clear()
        session.close(logout=True)
        return 2

    helper = wr.helper_exe(str(HUB))
    try:
        compat = apply_win81(config, PREFIX, helper)
    except Exception as error:
        compat = {'ok': False, 'reason': type(error).__name__}
    log(ev='win81_helper', **(compat or {}))
    sanpk = PREFIX / 'drive_c/sgi/run-3.5/3I/SANPK.exe'
    try:
        apply_win81(config, PREFIX, sanpk, live=not win81_already_set(PREFIX, 'SANPK.exe'))
    except Exception as error:
        log(ev='win81_sanpk_error', error=type(error).__name__)

    env, cmd, early = wr.win32_command(config, PREFIX, Path(r'C:\sgi\room_monitor\win32_startserver.py'))
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
        'game_root': GAME_ROOT_WIN, 'hold_seconds': int(args.hold_seconds),
    }
    if args.join_name:
        payload['join_name'] = args.join_name[:40]
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
    (SHADOW / 'helper.pid').write_text(str(proc.pid), encoding='utf-8')
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
        # Keep the hall session alive for the whole shadow session (the app
        # process holds it; helper holds StartServer independently).
        (SHADOW / 'app.pid').write_text(str(os.getpid()), encoding='utf-8')
        end = time.monotonic() + int(args.hold_seconds)
        log(ev='hold_started', helper_pid=proc.pid)
        while time.monotonic() < end:
            time.sleep(2)
            if proc.poll() is not None:
                log(ev='helper_gone_during_hold', code=proc.returncode)
                break
            if (SHADOW / 'STOP').exists():
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
