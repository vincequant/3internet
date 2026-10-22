#!/bin/sh
# Run on Grok Bot's computer (IBGateway). No passwords, no game start, no wineserver -k.
set -eu
python3 - <<'PY'
import json, os, shutil, socket, subprocess, sys
from pathlib import Path

def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=8).strip()
    except Exception as error:
        return ''

procs = []
try:
    text = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True, errors='replace')
    for line in text.splitlines():
        if any(name in line for name in ('SANGUO.exe', 'SANPK.exe', 'wineserver', 'Xvfb', 'sgi-room-monitor')):
            procs.append(line.strip()[:240])
except Exception:
    pass

report = {
    'hostname': socket.gethostname(),
    'uname': run(['uname', '-a']),
    'user': run(['id']),
    'display': os.environ.get('DISPLAY') or '',
    'wayland': os.environ.get('WAYLAND_DISPLAY') or '',
    'wine': shutil.which('wine') or '',
    'wine_version': run(['wine', '--version']) if shutil.which('wine') else '',
    'python': sys.version.split()[0],
    'xvfb': shutil.which('Xvfb') or '',
    'sgi_room_monitor': shutil.which('sgi-room-monitor') or '',
    'has_game_tree': any((Path.home() / rel).is_file() for rel in (
        '.local/share/sgi-wine/prefix-monitor/drive_c/sgi/run-3.5/SANGUO.exe',
        'sgi/run-3.5/SANGUO.exe',
    )),
    'processes': procs[:20],
}
print(json.dumps(report, ensure_ascii=False, indent=2))
PY
