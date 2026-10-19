#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P37b: same-name (forged display name) ghost join — launch only.

Launch block copied from the proven p37_rename_demo.py (2026-10-16 01:12 SUCCESS):
read-only row watchers + the p1/p2 ghost chain with --username <forged name>.
This variant stops after the join: no chat injection, no trigger, ghost holds.

Stop: pkill -f p1_directed_probe ; pkill -f p2_loader_host ; pkill -f p37_chat_probe
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path.home()
lab = home / 'sgi-protocol-lab-20260915'


def wine_env():
    sys.path.insert(0, str(home / 'Library/Application Support/SGI-Room-Monitor/opt'))
    from sgi_room_monitor.provision import wine_env as we  # noqa: E402
    wine = str(home / 'Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine')
    env = we(wine, str(home / 'Library/Application Support/SGI-Wine/prefix-sikarugir10'))
    env['SGI_BRIDGE_Z'] = r'Z:\Users\vk\sgi-protocol-lab-20260915\bridge'
    return wine, env


def spawn_probe(script, args, out, err):
    wine, env = wine_env()
    return subprocess.Popen(
        [wine, str(lab / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8', script] + args,
        stdout=open(out, 'w'), stderr=open(err, 'w'), env=env, cwd=str(lab),
        start_new_session=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host-pid', type=int, required=True)
    ap.add_argument('--host-name', default='风云')
    ap.add_argument('--host-ip', required=True, help='房主 session id 的大端展開 10.x.y.z')
    ap.add_argument('--username', required=True, help='幽靈註冊的顯示名（可任意=偽造）')
    ap.add_argument('--host-wait', type=float, default=5.0)
    ap.add_argument('--loader-script', default='p2_loader_host.py',
                    help='p2_loader_host.py（預設）或 p39c2_loader_host.py（會 dump ctx/b_port）')
    ap.add_argument('--ctx-file', default='',
                    help='p39c2_loader_host 的 P39C2_CTX_FILE 本地路徑（自動轉 Z:）')
    ap.add_argument('--tag', default=time.strftime('%H%M%S'))
    args = ap.parse_args()
    ev = lab / ('evidence/p37b-samename-' + args.tag)
    ev.mkdir(parents=True, exist_ok=True)
    (ev / 'config.json').write_text(json.dumps(vars(args), ensure_ascii=False))

    for pat in ('p1_directed_probe', 'p2_loader_host', 'p37_chat_probe'):
        subprocess.run(['pkill', '-f', pat], capture_output=True)
    time.sleep(2)
    trig = lab / 'trigger-p37'
    if trig.exists():
        trig.unlink()

    row_watch = spawn_probe('p37_row_watch.py',
                            [str(args.host_pid), '2', '3600', str(ev / 'row_watch.jsonl')],
                            ev / 'row_watch.out', ev / 'row_watch.err')
    host_watch = spawn_probe('p33_host_watch.py',
                             [str(args.host_pid), '--interval', '2', '--duration', '3600',
                              '--out', str(ev / 'watch.jsonl')],
                             ev / 'watch.out', ev / 'watch.err')

    child_args = ['--host-pid', str(args.host_pid), '--host-name', args.host_name,
                  '--chat-texts', 'fy-ctl', '--join-retries', '30',
                  '--host-wait', str(args.host_wait),
                  '--username', args.username,
                  '--trigger', r'Z:\Users\vk\sgi-protocol-lab-20260915\trigger-p37']
    env = dict(os.environ, P2_CHILD_SCRIPT='p37_chat_probe.py',
               P2_CHILD_ARGS_JSON=json.dumps(child_args),
               P2_CHILD_STDERR=str(ev / 'child-stderr.log'))
    if args.ctx_file:
        z = 'Z:' + args.ctx_file.replace('/', '\\')
        env['P39C2_CTX_FILE'] = z
        env['P39C2_TABLE_LOG'] = z + '.table.jsonl'
        env['P2_CTX_FILE'] = z
    driver = subprocess.Popen(
        ['python3', str(lab / 'p1_directed_probe.py'),
         '--credentials', str(lab / 'query-credentials.fengye.json'),
         '--line', '多线3', '--target', args.host_ip,
         '--loader-script', args.loader_script, '--session-name', 'SGZWLB',
         '--hold-seconds', '5400', '--loader-timeout', '5700'],
        stdout=open(ev / 'driver.json', 'w'), stderr=open(ev / 'driver.err', 'w'),
        env=env, cwd=str(lab), start_new_session=True)

    print(json.dumps({'ev': str(ev), 'row_watch': row_watch.pid,
                      'host_watch': host_watch.pid, 'driver': driver.pid}))


if __name__ == '__main__':
    main()
