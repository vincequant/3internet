"""Raise an existing Hub window by PID. Do not kill game or lobby."""
import os
import subprocess
import sys
from pathlib import Path


def peer_hub_pid(me=None, listing=None):
    me = os.getpid() if me is None else int(me)
    if listing is None:
        try:
            listing = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
        except Exception:
            return None
    for line in listing.splitlines():
        if 'mac_main.py' not in line:
            continue
        lower = line.lower()
        if any(skip in lower for skip in ('grep', 'pgrep', 'awk ', 'rg ')):
            continue
        try:
            pid = int(line.split(None, 1)[0])
        except ValueError:
            continue
        if pid != me:
            return pid
    return None


def raise_script(pid):
    return (
        'tell application "System Events"\n'
        'try\n'
        f'  set p to first process whose unix id is {int(pid)}\n'
        '  set frontmost of p to true\n'
        '  repeat with w in (windows of p)\n'
        '    try\n'
        '      if (name of w as text) contains "全知情报" then\n'
        '        perform action "AXRaise" of w\n'
        '        return "yes"\n'
        '      end if\n'
        '    end try\n'
        '  end repeat\n'
        'end try\n'
        'end tell\n'
        'return "no"\n'
    )


def raise_existing_hub(pid, runner=None):
    if not pid:
        return False
    if runner is None and sys.platform != 'darwin':
        return False
    run = runner or (lambda script: subprocess.run(
        ['osascript', '-e', script], capture_output=True, text=True, timeout=8,
    ))
    try:
        out = run(raise_script(pid))
    except Exception:
        return False
    text = out.stdout if hasattr(out, 'stdout') else out
    return 'yes' in (text or '')


def reload_argv(executable=None, script=None):
    executable = executable or sys.executable
    script = Path(script) if script else Path(__file__).resolve().with_name('mac_main.py')
    return [executable, '-B', str(script)]


def reload_hub(before=None, executable=None, script=None, execv=os.execv):
    """Replace this Hub process with a fresh interpreter. Never touches the game."""
    if before:
        before()
    argv = reload_argv(executable, script)
    execv(argv[0], argv)
