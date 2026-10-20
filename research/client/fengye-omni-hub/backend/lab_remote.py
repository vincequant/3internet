"""遠端實驗室通道：一發式 SSH 執行（實驗室按鈕的 arm / stop / status）。

獨立模組：不進 backend/server.py，維持 omni hub 與 web hub 的
server.py／remote_snapshot.py 逐位元組一致釘子（tests 釘住）。
"""
from __future__ import annotations

import subprocess


def lab_remote(host, script_text, timeout=360, runner=subprocess.run):
    """Run one lab shell script on the remote Mac over SSH (stdin = bash).

    One shot per call; the UI never auto-retries.
    """
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
