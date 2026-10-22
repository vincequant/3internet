"""遠端實驗室通道：一發式 SSH 執行（實驗室按鈕的 arm / stop / status）。

獨立模組：不進 backend/server.py，維持 omni hub 與 web hub 的
server.py／remote_snapshot.py 逐位元組一致釘子（tests 釘住）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess


def local_lab_root():
    """本機模式：data/config.json 有 local_lab 就代表實驗室在這台 Mac。"""
    try:
        cfg = json.loads((pathlib.Path(__file__).resolve().parent.parent
                          / 'data' / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    root = cfg.get('local_lab')
    return pathlib.Path(root).expanduser() if isinstance(root, str) and root else None


def lab_remote(host, script_text, timeout=360, runner=subprocess.run):
    """Run one lab shell script (stdin = bash).

    2026-10-21：本機模式（config 有 local_lab）時直接在這台 Mac 跑，
    不再 SSH 到 vkquant-com——否則面板按鈕會操作到另一台機器。
    One shot per call; the UI never auto-retries.
    """
    root = local_lab_root()
    if root is not None:
        try:
            result = runner(['bash', '-s'], input=script_text, capture_output=True,
                            text=True, timeout=timeout, cwd=str(root))
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('本機實驗室執行失敗或逾時') from None
        return {'rc': result.returncode, 'stdout': (result.stdout or '')[-6000:],
                'stderr': (result.stderr or '')[-2000:], 'where': 'local'}
    if not host:
        raise RuntimeError('尚未配置 vkquant Mac 的 SSH 地址')
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectionAttempts=1',
               '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=4', host, 'bash -s']
    try:
        result = runner(command, input=script_text, capture_output=True,
                        text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('无法连接 vkquant Mac 或执行超时') from None
    return {'rc': result.returncode, 'stdout': (result.stdout or '')[-6000:],
            'stderr': (result.stderr or '')[-2000:]}
