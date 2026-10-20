"""Choose a SANPK/SANGUO window by instance identity. HWND/PID alone are never enough."""
import os
from pathlib import Path


def normalize_path(value):
    return str(value or '').replace('\\', '/').lower().rstrip('/')


def _same_prefix(left, right):
    if not left or not right:
        return False
    if normalize_path(left) == normalize_path(right):
        return True
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _blob(candidate):
    return ' '.join(str(candidate.get(key) or '') for key in
                    ('exe_win', 'exe_unix', 'command', 'prefix'))


def matches_target(candidate, target):
    if not target:
        return True
    if target.get('pid') is not None and int(candidate.get('pid') or 0) != int(target['pid']):
        return False
    if target.get('hwnd') is not None and int(candidate.get('hwnd') or 0) != int(target['hwnd']):
        return False
    if target.get('title') and candidate.get('title') != target['title']:
        return False
    if target.get('class') and candidate.get('class') != target['class']:
        return False
    exe = target.get('exe')
    if exe:
        text = normalize_path(_blob(candidate))
        need = normalize_path(exe)
        if need not in text and need.split('/')[-1] not in text:
            return False
        if ('/' in need.strip('/')) and need not in text:
            return False
    prefix = target.get('prefix')
    if prefix and normalize_path(prefix) not in normalize_path(_blob(candidate)):
        # Wine reader only sees C:\sgi\...; the Mac bottle is in WINEPREFIX, not the PE path.
        if not _same_prefix(os.environ.get('WINEPREFIX'), prefix):
            return False
    return True


def choose_instances(candidates, target=None):
    return [item for item in candidates if matches_target(item, target)]


def identity_alive(saved, live):
    """Re-check a previously chosen window. Numbers may be reused."""
    if not saved or not live:
        return False
    if live.get('title') != saved.get('title'):
        return False
    if saved.get('class') and live.get('class') != saved.get('class'):
        return False
    if int(saved.get('pid') or 0) == int(live.get('pid') or 0) and int(saved.get('hwnd') or 0) == int(live.get('hwnd') or 0):
        hint = {key: saved[key] for key in ('exe', 'prefix') if saved.get(key)}
        return matches_target(live, hint) if hint else True
    hint = {}
    if saved.get('exe') or saved.get('exe_unix') or saved.get('exe_win'):
        hint['exe'] = saved.get('exe') or saved.get('exe_unix') or saved.get('exe_win')
    if saved.get('prefix'):
        hint['prefix'] = saved['prefix']
    if not hint:
        return False
    return matches_target(live, hint)


def parse_target_argv(argv):
    target = {}
    args = [str(item) for item in argv]
    skip = {'--refresh', '--quiet', '--reveal', '--inspect'}
    index = 0
    while index < len(args):
        item = args[index]
        if item in skip:
            index += 1
            continue
        if item.startswith('--prefix='):
            target['prefix'] = item.split('=', 1)[1]
        elif item.startswith('--pid='):
            target['pid'] = int(item.split('=', 1)[1])
        elif item.startswith('--exe='):
            target['exe'] = item.split('=', 1)[1]
        elif item == '--prefix' and index + 1 < len(args):
            target['prefix'] = args[index + 1]
            index += 1
        elif item == '--pid' and index + 1 < len(args):
            target['pid'] = int(args[index + 1])
            index += 1
        elif item == '--exe' and index + 1 < len(args):
            target['exe'] = args[index + 1]
            index += 1
        index += 1
    return target or None
