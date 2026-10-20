"""風雲本機控制（omni hub 內建版）：直連登入／退出／勢力切換。

只使用本機路徑與本機遊戲（prefix-sikarugir10）；不讀玩家記憶體情報、不碰遠端。
staging（collector-bridge + fengyun_setforce.py）在 ~/sgi-direct-connect 下，
首次使用時自動就位（來源：本 repo 的 SGI-Hub bridge 與 fengyun-console）。
"""
from __future__ import annotations

import json
import importlib.util
import os
import plistlib
import shutil
import signal
import subprocess
import time
from pathlib import Path

HOME = Path.home()
HUB_ROOT = Path(__file__).resolve().parent.parent


def _read_mapping(path, plist=False):
    try:
        value = plistlib.loads(path.read_bytes()) if plist else json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# Reuse this Mac's existing launcher configuration, including its account.
LAUNCHER_INFO = _read_mapping(HOME / 'Library/Application Support/SGI-Wine/三国志 Wine.app/Contents/Info.plist', plist=True)
DIRECT_ROOT = Path(LAUNCHER_INFO.get('SGIDirectConnectRoot') or HOME / 'sgi-direct-connect')
ACCOUNT = LAUNCHER_INFO.get('SGIDirectConnectAccount') or 'fengyun'
DISPLAY_NAME = LAUNCHER_INFO.get('SGIDirectConnectDisplayName') or '風雲'
LAUNCHER_SCRIPT = Path(LAUNCHER_INFO.get('SGILauncherScript') or HOME / 'Applications/SGI-Game/scripts/sgi_wine_launcher.py')
LAUNCHER_PYTHON = LAUNCHER_INFO.get('SGIPythonInterpreter') or '/usr/bin/python3'
MACHINE = _read_mapping(DIRECT_ROOT / 'machine.json')
LOCAL_HUB = Path(MACHINE.get('hub_root') or MACHINE.get('hub') or LAUNCHER_INFO.get('SGIHubRoot') or HUB_ROOT.parent / 'SGI-Hub-CrossOver-M4-0.2')
RUN_SH = DIRECT_ROOT / 'run.sh'
PREFIX = Path(MACHINE.get('prefix') or HOME / 'Library/Application Support/SGI-Wine/prefix-sikarugir10')
WINE = Path(MACHINE.get('wine') or HOME / 'Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine')
WINESERVER = HOME / 'Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wineserver'
PY32 = LOCAL_HUB / 'bridge/win32-python/sgi-py32.exe'
BRIDGE_STAGE = DIRECT_ROOT / 'collector-bridge'
SETFORCE_STAGE = DIRECT_ROOT / 'fengyun_setforce.py'
SETFORCE_SRC = HUB_ROOT.parent / 'fengyun-console' / 'fengyun_setforce.py'
BRIDGE_SRC = LOCAL_HUB / 'bridge'
LOG_DIR = HUB_ROOT / 'data' / 'local-logs'

WINE_BRIDGE = 'Z:' + str(BRIDGE_STAGE).replace('/', '\\')
WINE_SETFORCE = 'Z:' + str(SETFORCE_STAGE).replace('/', '\\')
WINE_STATE = 'Z:' + str(DIRECT_ROOT / 'logs/fengyun-setforce-state.json').replace('/', '\\')


def ensure_staging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (DIRECT_ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    if not BRIDGE_STAGE.exists() and BRIDGE_SRC.exists():
        shutil.copytree(BRIDGE_SRC, BRIDGE_STAGE, ignore=shutil.ignore_patterns('__pycache__'))
    if not SETFORCE_STAGE.exists() and SETFORCE_SRC.exists():
        shutil.copy2(SETFORCE_SRC, SETFORCE_STAGE)


def wine_env():
    env = dict(os.environ)
    env['WINEPREFIX'] = str(PREFIX)
    env['WINEDEBUG'] = '-all'
    env['DYLD_FALLBACK_LIBRARY_PATH'] = str(HOME / 'Library/Application Support/SGI-Wine/dependency-lib')
    for key in ('DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'DYLD_INSERT_LIBRARIES'):
        env.pop(key, None)
    return env


def helper_pid():
    try:
        pid = int((DIRECT_ROOT / 'helper.pid').read_text().strip())
    except Exception:
        return 0
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return 0


def sanpk_pid():
    try:
        spec = importlib.util.spec_from_file_location('fengye_game_launcher', LAUNCHER_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pids = module.running_programs(PREFIX, ('SANPK.exe',))
        return pids[0] if pids else 0
    except Exception:
        return 0


def status():
    return {'helper_pid': helper_pid(), 'sanpk_pid': sanpk_pid(),
            'stop_file': (DIRECT_ROOT / 'STOP').exists(),
            'staging': BRIDGE_STAGE.exists() and PY32.exists()}


FLOW_LOG_GLOB = 'direct-' + ACCOUNT + '-*.jsonl'
ABORT_LABELS = {'login': '登入', 'checks': '環境檢查', 'no_grant': '取線路失敗',
                'helper_cmd': '助手啟動失敗', 'sanpk_gate_missing': '客戶端檢查失敗'}


def _parse_events(path):
    events = []
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return events


def _flow_facts(events):
    facts = {'last_ev': None, 'login_ok': None, 'login_message': None, 'rooms': None,
             'abort_reason': None, 'session_pid': None}
    for event in events:
        helper = event.get('helper') if isinstance(event.get('helper'), dict) else None
        if helper is not None:
            if helper.get('event') == 'game_search':
                facts['rooms'] = [str(v) for v in (helper.get('list_names') or [])]
            continue
        ev = event.get('ev')
        if not ev:
            continue
        facts['last_ev'] = ev
        if ev == 'login':
            facts['login_ok'] = event.get('ok')
            facts['login_message'] = event.get('message')
        elif ev == 'abort':
            facts['abort_reason'] = event.get('reason')
        elif ev == 'helper_spawned' and isinstance(event.get('pid'), int):
            facts['session_pid'] = event['pid']
        elif ev in ('result', 'hold_started') and isinstance(event.get('helper_pid'), int):
            facts['session_pid'] = event['helper_pid']
    return facts


def live_status():
    """本機風雲的明白狀態：現行會話（helper.pid 對號）優先，其次最新一次嘗試的結果。

    state: not_started / logging_in / holding / already_logged / aborted /
           stopping / exited / running_unknown
    """
    base = status()
    info = {'state': 'not_started', 'headline': '未啟動——按「登入大廳→進遊戲」',
            'detail': '', 'alive': bool(base['sanpk_pid']), 'helper_pid': base['helper_pid'],
            'sanpk_pid': base['sanpk_pid'], 'log': None, 'log_age': None, 'rooms': [],
            'login_message': None, 'display_name': DISPLAY_NAME}
    try:
        logs = sorted((DIRECT_ROOT / 'logs').glob(FLOW_LOG_GLOB),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:24]
    except OSError:
        logs = []
    if not logs:
        if info['alive']:
            info.update(state='running_unknown', headline='偵測到遊戲進程（流程日誌缺失）')
        return info
    newest = logs[0]
    info['log'] = str(newest)
    try:
        info['log_age'] = round(time.time() - newest.stat().st_mtime, 1)
    except OSError:
        pass
    if base['helper_pid']:
        for log in logs:
            facts = _flow_facts(_parse_events(log))
            if facts['session_pid'] == base['helper_pid'] and facts['last_ev'] in ('hold_started', 'result'):
                rooms = facts['rooms'] or []
                detail = '房間列表：' + ('、'.join(rooms) if rooms else '（暫未查到——房主建房後就在遊戲選擇裡）')
                if facts['login_message']:
                    detail = facts['login_message'] + '。' + detail
                info.update(state='holding',
                            headline='✅ 風雲已在線（遊戲選擇·駐留中）——不用重複登入，直接用遊戲窗口',
                            detail=detail, rooms=rooms, login_message=facts['login_message'],
                            log=str(log))
                return info
        info.update(state='holding', headline='✅ 風雲已在線（駐留中）——不用重複登入，直接用遊戲窗口')
        return info
    if info['alive']:
        info.update(state='running_unknown', headline='偵測到遊戲進程（未見駐留助手對應）——見下方明細')
        return info
    facts = _flow_facts(_parse_events(newest))
    last_ev = facts['last_ev']
    if facts['rooms'] is not None:
        info['rooms'] = facts['rooms']
    if facts['login_message']:
        info['login_message'] = facts['login_message']
    fresh_log = info['log_age'] is not None and info['log_age'] <= 25
    stale_note = ''
    if info['log_age'] is not None and info['log_age'] > 600:
        stale_note = '（這是 {} 分鐘前的記錄）'.format(int(info['log_age'] // 60))
    if last_ev in ('session_closed', 'helper_exited', 'helper_gone_during_hold'):
        info.update(state='exited', headline='⭘ 已下線（會話已結束）', detail=stale_note)
    elif last_ev == 'stop_file_seen':
        info.update(state='stopping', headline='⏳ 正在下線…', detail=stale_note)
    elif (last_ev == 'abort' and facts['login_ok'] is False and facts['login_message']
          and '已经登录' in facts['login_message']):
        info.update(state='already_logged',
                    headline='⚠ 風雲帳號已登錄（伺服器回「已登入」，未重複送出密碼）',
                    detail='多半是同機已有另一個窗口或桌面按鈕把風雲開著。直接去用即可；'
                           '要重開先在遊戲端退出，或在遊戲登入畫面勾「強制登錄」。' + stale_note)
    elif last_ev == 'abort':
        info.update(state='aborted',
                    headline='⚠ 登入中止（{}）'.format(ABORT_LABELS.get(facts['abort_reason'],
                                                                        facts['abort_reason'] or '未詳')),
                    detail=(facts['login_message'] or '')[:200] + stale_note)
    elif last_ev in ('hold_started', 'result'):
        info.update(state='exited', headline='⭘ 已下線（此前駐留會話已結束）', detail=stale_note)
        if info['rooms']:
            info['detail'] = (info['detail'] + ' 上次房間列表：' + '、'.join(info['rooms'])).strip()
    elif fresh_log:
        info.update(state='logging_in', headline='⏳ 登入中……（幾秒後自動顯示結果）',
                    detail=(facts['login_message'] or ''))
    elif info['log_age'] is not None:
        info.update(state='not_started', headline='未啟動——按「登入大廳→進遊戲」', detail=stale_note)
    return info


def login(line='多线3（备用）'):
    live = live_status()
    if live.get('state') == 'holding':
        return {'status': 'already_online', 'message': live.get('headline'),
                'detail': live.get('detail'), 'rooms': live.get('rooms'), **status()}
    ensure_staging()
    args = ['/bin/bash', str(RUN_SH), ACCOUNT, '--line', line]
    log_path = LOG_DIR / ('login-%s.jsonl' % time.strftime('%Y%m%d-%H%M%S'))
    with log_path.open('w', encoding='utf-8') as handle:
        proc = subprocess.Popen(args, cwd=str(DIRECT_ROOT), stdout=handle,
                                stderr=subprocess.STDOUT, start_new_session=True)
    return {'status': 'started', 'pid': proc.pid, 'log': str(log_path), **status()}


def exit_soft():
    (DIRECT_ROOT / 'STOP').touch()
    time.sleep(1.5)
    pid = helper_pid()
    killed = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except OSError:
            pass
    time.sleep(1.5)
    return {'status': 'exited', 'helper_pid': pid, 'sigterm': killed, **status()}


def force_kill():
    try:
        result = subprocess.run([str(LAUNCHER_PYTHON), '-B', str(LAUNCHER_SCRIPT), 'game-stop'],
                                capture_output=True, text=True, timeout=30)
    except Exception as error:
        return {'status': 'error', 'error': str(error)}
    if result.returncode:
        return {'status': 'error', 'error': '遊戲尚未確認結束，請更新狀態。', **status()}
    return {'status': 'killed', 'lobby_preserved': True, **status()}


def setforce(mode, slot=None):
    ensure_staging()
    args = [str(WINE), str(PY32), WINE_SETFORCE, '--bridge', WINE_BRIDGE, '--state', WINE_STATE]
    if mode == 'read':
        args.append('--read')
    elif mode == 'restore':
        args.append('--restore')
    else:
        args += ['--slot', str(int(slot))]
    try:
        proc = subprocess.run(args, env=wine_env(), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': 'timeout（wine 掃描超時）'}
    payload = None
    for line in reversed((proc.stdout or '').strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if payload is None:
        return {'status': 'error', 'rc': proc.returncode,
                'error': (proc.stderr or proc.stdout or 'no output')[-300:]}
    return {'status': 'ok', 'rc': proc.returncode, **payload}
