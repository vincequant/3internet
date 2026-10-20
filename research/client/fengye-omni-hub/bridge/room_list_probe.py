"""Build the Wine/Windows reader command. Does not import the Hub UI."""
import os
import sys
from pathlib import Path


def probe_flags(refresh=False, quiet=False, reveal=False, inspect=False,
                prefix=None, pid=None, exe=None):
    extra = []
    if prefix:
        extra.extend(['--prefix', str(prefix)])
    if pid is not None:
        extra.extend(['--pid', str(int(pid))])
    if exe:
        extra.extend(['--exe', str(exe)])
    if inspect:
        extra.append('--inspect')
        return extra
    if quiet:
        extra.append('--quiet')
    if reveal:
        extra.append('--reveal')
    if refresh:
        extra.append('--refresh')
    return extra


def probe_command(root, refresh=False, quiet=False, reveal=False, inspect=False,
                  prefix=None, pid=None, exe=None):
    root = Path(root)
    reader = root / 'bridge/room_list_reader.py'
    extra = probe_flags(refresh, quiet, reveal, inspect, prefix, pid, exe)
    if sys.platform == 'win32':
        python = root / 'bridge/python/python.exe'
        cmd = [str(python) if python.exists() else sys.executable, '-X', 'utf8', '-B', str(reader)]
        cmd.extend(extra)
        return cmd, os.environ.copy()
    sys.path.insert(0, str(root / 'app'))
    from bridge_autostart import configure_local_runtime, bridge_command
    configure_local_runtime(root)
    cmd, _ = bridge_command(root)
    argv = 'sys.argv=[str(p)]' + ''.join(f'+[{flag!r}]' for flag in extra)
    cmd = cmd[:-2] + [
        '-c',
        'import runpy,sys; from pathlib import Path; '
        'p=Path(sys.executable).resolve().parent.parent/"room_list_reader.py"; '
        + argv + '; runpy.run_path(str(p),run_name="__main__")',
    ]
    env = os.environ.copy()
    env['WINEDEBUG'] = '-all'
    if prefix:
        env['WINEPREFIX'] = str(Path(prefix).expanduser())
    return cmd, env
