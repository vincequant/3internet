"""Hub-side bridge to the shadow client's unit editor (2026-10-19).

Purpose: the operator wants to change numbers from the 全知情报 window (the popup
that opens when clicking a field unit), because the in-Wine card panel cannot draw
any text in this Wine build.

Design notes
- Only ever touches the *shadow* (风夜) client on this Mac: the selected data source
  must look like 风夜/影子, and the backend runs with prefix-fengye-shadow.
- One wine subprocess per write (~1–2 s); no GUI clients are started or killed.
- Writes are clamped/verified/read back by tools/shadow_unit_api.py and logged to
  shadow/logs/unit-edit-api.jsonl; "revert" undoes the last write.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

LAB = Path.home() / 'sgi-fengye-lab'
SHADOW = LAB / 'shadow'
WINE = Path.home() / 'Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine'
PY32 = LAB / 'python32/python.exe'
PREFIX = Path.home() / 'Library/Application Support/SGI-Wine/prefix-fengye-shadow'
API_Z = r'Z:\Users\vk\sgi-fengye-lab\shadow\tools\shadow_unit_api.py'
BRIDGE_Z = r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge'

UNIT_FIELDS = (
    ('soldiers', '兵力', 100000),
    ('rice', '兵粮', 100000),
    ('morale', '士气', 100),
    ('training', '训练', 100),
)
GENERAL_FIELDS = (
    ('lead', '统率'), ('war', '武力'), ('intel', '智力'), ('pol', '政治'), ('cha', '魅力'),
)


def source_is_shadow(selected_source):
    text = str(selected_source or '')
    return ('风夜' in text) or ('風夜' in text) or ('影子' in text)


def available():
    return API_Z.split('\\')[-1] and (SHADOW / 'tools' / 'shadow_unit_api.py').is_file() and PY32.is_file()


def _run(args, timeout=90):
    env = dict(os.environ)
    env.update({'WINEPREFIX': str(PREFIX), 'WINEDEBUG': '-all',
                'DYLD_FALLBACK_LIBRARY_PATH': str(Path.home() / 'Library/Application Support/SGI-Wine/dependency-lib')})
    env.pop('DYLD_LIBRARY_PATH', None)
    cmd = [str(WINE), str(PY32), '-X', 'utf8', API_Z, '--bridge', BRIDGE_Z] + [str(a) for a in args]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': '写值后端超时'}
    for line in reversed((done.stdout or '').splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            text = str(parsed.get('error') or '')
            if 'need exactly one shadow SANPK' in text:
                parsed.update(orphan=True,
                              error='风夜客户端与 wine server 失联（孤儿进程）：请重新一键内测')
            return parsed
    blob = (done.stdout or '') + (done.stderr or '')
    if 'need exactly one shadow SANPK' in blob:
        return {'ok': False, 'error': '风夜客户端与 wine server 失联（孤儿进程）：请重新一键内测'}
    return {'ok': False, 'error': '后端无 JSON 回覆'}


def write_unit_field(owner, unit_id, field, value):
    return _run(['set-unit', '--owner', int(owner), '--unit-id', int(unit_id),
                 '--field', field, '--value', int(value)])


def write_general(general_id, field, value):
    return _run(['setgen', '--gid', int(general_id), '--field', field, '--value', int(value)])


def revert_last():
    return _run(['revert'])


# ---------- 士气锁定 ----------
MORALE_STATE = SHADOW / 'morale-lock.json'
MORALE_STATE_Z = r'Z:\Users\vk\sgi-fengye-lab\shadow\morale-lock.json'
MORALE_LOG_Z = r'Z:\Users\vk\sgi-fengye-lab\shadow\logs\morale-lock.jsonl'


def morale_lock_status():
    """Read the locker state file; fresh (<8s) means the keeper is alive."""
    import time as _time
    try:
        data = json.loads(MORALE_STATE.read_text(encoding='utf-8'))
    except Exception:
        return {'running': False}
    age = _time.time() - float(data.get('started_at') or 0)
    return {'running': age < 8 or MORALE_STATE.stat().st_mtime > _time.time() - 15,
            'age': age, **{k: data.get(k) for k in ('owner', 'unit_id', 'value', 'pid')}}


def morale_lock_start(owner, unit_id, value):
    if not available():
        return {'ok': False, 'error': '找不到后端脚本'}
    try:
        value = max(0, min(int(value), 100))
    except Exception:
        return {'ok': False, 'error': '锁定值需为 0–100 的整数'}
    morale_lock_stop()
    import time as _time
    _time.sleep(0.4)
    env = dict(os.environ)
    env.update({'WINEPREFIX': str(PREFIX), 'WINEDEBUG': '-all'})
    cmd = [str(WINE), str(PY32), '-X', 'utf8', r'Z:\Users\vk\sgi-fengye-lab\shadow\tools\shadow_morale_lock.py',
           '--bridge', BRIDGE_Z, '--owner', str(int(owner)), '--unit-id', str(int(unit_id)),
           '--value', str(value), '--interval', '0.8', '--seconds', '7200',
           '--state', MORALE_STATE_Z, '--log', MORALE_LOG_Z]
    log_path = SHADOW / 'logs' / 'morale-lock-run.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(log_path, 'a', encoding='utf-8')
        subprocess.Popen(cmd, stdout=handle, stderr=handle, env=env,
                         start_new_session=True, close_fds=True)
    except Exception as error:
        return {'ok': False, 'error': repr(error)}
    _time.sleep(2.5)
    state = morale_lock_status()
    if state.get('running') and state.get('value') == value:
        return {'ok': True, 'value': value, 'state': state}
    return {'ok': False, 'error': '锁定进程未起来（看 shadow/logs/morale-lock-run.log）', 'state': state}


def morale_lock_stop():
    try:
        if MORALE_STATE.exists():
            MORALE_STATE.unlink()
    except Exception as error:
        return {'ok': False, 'error': repr(error)}
    return {'ok': True}
