"""風夜操控台：新功能資料通道（F1，2026-10-18 定）。

每個函數組一段遠端 shell 腳本，交給既有 lab_remote() 一發執行，回傳解析後
結構。除 session_op（需 confirm=True，且只轉發實驗室既有工具）外全部只讀。

不進 backend/server.py，維持 omni hub 與 web hub 的 server.py / remote_snapshot.py
逐位元組一致釘子；由 server 的路由或 UI 直接調用本模組。
"""
from __future__ import annotations

import json
import time

from backend.lab_remote import lab_remote

SHADOW = '~/sgi-protocol-lab-20260915/shadow'
ENV = ('cd ' + SHADOW + ' && source ./_env.sh && '
       'export WINEPREFIX="$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow"')


def _run(host, script, timeout=120, runner=None):
    kwargs = {'timeout': timeout}
    if runner is not None:
        kwargs['runner'] = runner
    return lab_remote(host, script, **kwargs)


def resident_check(host, runner=None):
    """常駐驅動狀態：installed/main_tid/blob 與全部計數。"""
    script = (ENV + ' && "$WINE" "$P32" tools/p51_shadow_inject.py --mode resident '
              '--resident-action check --state "$Z\\\\inject-state-resident.json" | tail -1\n')
    out = _run(host, script, 90, runner)
    try:
        return {'ok': True, 'data': json.loads(out['stdout'].strip().splitlines()[-1])}
    except (ValueError, IndexError):
        return {'ok': False, 'raw': out}


def lag_tail(host, n=60, runner=None):
    """lag 曲線尾段（每行含 host/shadow 同字段與 lag_4d0/4d4/4d6）。"""
    script = 'tail -n %d %s/logs/lagwatch.jsonl 2>/dev/null\n' % (int(n), SHADOW)
    out = _run(host, script, 60, runner)
    rows = []
    for line in out['stdout'].splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return {'ok': True, 'rows': rows}


def stall_tail(host, n=40, runner=None):
    """凍結/RX 預警日誌尾段。"""
    script = 'tail -n %d %s/logs/stall-watchdog.log 2>/dev/null\n' % (int(n), SHADOW)
    out = _run(host, script, 60, runner)
    return {'ok': True, 'lines': out['stdout'].splitlines()}


def chat_search(host, text, runner=None):
    """在風夜已收流裡做全幀字串檢索（正對照已知可用）。"""
    safe = text.replace('"', '').replace('\\', '')[:64]
    script = ('cd %s && /usr/bin/python3 tools/chat_text_probe.py "%s"\n' % (SHADOW, safe))
    out = _run(host, script, 90, runner)
    try:
        return {'ok': True, 'data': json.loads(out['stdout'])}
    except ValueError:
        return {'ok': False, 'raw': out}


def session_op(host, target_name, confirm=False, runner=None):
    """成員會話操作：只轉發實驗室既有 d2_* 編排器；需 confirm=True。

    confirm=True 時在遠端寫一份 D2 形狀的新鮮批准（kick_confirmed），再拉起
    既有編排器（一幀、不重試）。回傳其 stdout 尾段供 UI 顯示。
    """
    if confirm is not True:
        raise RuntimeError('confirm_required')
    name = str(target_name).replace('"', '').replace('\\', '')[:24]
    if not name:
        raise RuntimeError('target_name_required')
    approval = json.dumps({'contract': 'D2', 'kick_confirmed': True,
                           'departing_id': 0, 'confirmed_wall': time.time(),
                           'source': 'hub-confirm'})
    script = ('cd ~/sgi-protocol-lab-20260915 && '
              'printf %s > /tmp/d2-approval.json && '
              'python3 d2_kick_run.py --ghost-name 风夜 --kick-target-name "%s" '
              '--live-authorization /tmp/d2-approval.json --launch 2>&1 | tail -6\n'
              % (json.dumps(approval), name))
    out = _run(host, script, 300, runner)
    return {'ok': out['rc'] == 0, 'stdout': out['stdout'][-2000:], 'rc': out['rc']}


def archive_run(host, subdir, runner=None):
    """一鍵歸檔某個 evidence 子目錄（tar.gz + sha256sums）。"""
    safe = str(subdir).replace('"', '').replace('\\', '').replace('/', '')[:80]
    script = ('cd %s && /usr/bin/python3 tools/archive_evidence.py "%s"\n' % (SHADOW, safe))
    out = _run(host, script, 300, runner)
    return {'ok': out['rc'] == 0, 'stdout': out['stdout'][-600:]}
