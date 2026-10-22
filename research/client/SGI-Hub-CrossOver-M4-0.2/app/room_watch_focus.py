"""Return focus after the observer window maps. Mac only; no Win32 foreground calls."""
import json
import os
import re
import subprocess
import sys

RESUME_ENV = 'SGI_ROOM_WATCH_RESUME'

GENERIC_BUNDLES = ('org.python.python', 'com.apple.python')
LOCKED_NAMES = ('loginwindow', 'screensaverengine')
LOCKED_BUNDLES = ('com.apple.loginwindow', 'com.apple.screensaver.engine')
HELPER_NAMES = ('通用控制', 'universal control')
HELPER_BUNDLES = ('com.apple.universalcontrol',)
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20


def apply_win32_noactivate(hwnd, get_long, set_long):
    style = get_long(int(hwnd), GWL_EXSTYLE)
    set_long(int(hwnd), GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
    return True


def parse_lsappinfo(text):
    if not text:
        return None
    pid = re.search(r'"pid"=(\d+)', text)
    if not pid:
        return None
    name = re.search(r'"(?:LSDisplayName|CFBundleName)"="([^"]*)"', text)
    bundle = re.search(r'"CFBundleIdentifier"="([^"]*)"', text)
    return {
        'pid': int(pid.group(1)),
        'name': name.group(1) if name else '',
        'bundle': bundle.group(1) if bundle else '',
    }


def resume_env_value(info):
    if not info or not info.get('pid'):
        return None
    return json.dumps({
        'pid': int(info['pid']),
        'name': info.get('name') or '',
        'bundle': info.get('bundle') or '',
    }, ensure_ascii=False)


def resume_from_env(env=None):
    raw = (env or os.environ).get(RESUME_ENV) or ''
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not value.get('pid'):
        return None
    try:
        pid = int(value['pid'])
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return {
        'pid': pid,
        'name': value.get('name') or '',
        'bundle': value.get('bundle') or '',
    }


def capture_frontmost():
    if sys.platform != 'darwin':
        return None
    try:
        front = subprocess.check_output(['lsappinfo', 'front'], text=True, timeout=2).strip()
        info = subprocess.check_output(
            ['lsappinfo', 'info', '-only', 'name,pid,bundleid', front],
            text=True, timeout=2)
        return parse_lsappinfo(info)
    except Exception:
        return None


def apply_nonactivating_window(root):
    if root is None:
        return False
    if sys.platform == 'darwin':
        try:
            root.tk.call('::tk::unsupported::MacWindowStyle', 'style', root._w,
                         'document', 'closeBox collapseBox noActivates')
            return True
        except Exception:
            return False
    if sys.platform == 'win32':
        try:
            import ctypes
            user32 = ctypes.windll.user32
            get_long = getattr(user32, 'GetWindowLongPtrW', None) or user32.GetWindowLongW
            set_long = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
            return apply_win32_noactivate(root.winfo_id(), get_long, set_long)
        except Exception:
            return False
    return False


def is_self_front(info, self_pid=None):
    if not info:
        return False
    self_pid = os.getpid() if self_pid is None else self_pid
    return info.get('pid') == self_pid


def is_self_or_wine(info, self_pid=None):
    if is_self_front(info, self_pid):
        return True
    if not info:
        return False
    name = (info.get('name') or '').lower()
    bundle = (info.get('bundle') or '').lower()
    return 'wine' in name or 'wine' in bundle


def is_locked_session(info):
    if not info:
        return False
    name = (info.get('name') or '').lower()
    bundle = (info.get('bundle') or '').lower()
    return name in LOCKED_NAMES or bundle in LOCKED_BUNDLES


def is_helper_front(info):
    if not info:
        return False
    name = (info.get('name') or '').lower()
    bundle = (info.get('bundle') or '').lower()
    return name in HELPER_NAMES or bundle in HELPER_BUNDLES


def usable_resume(info, self_pid=None):
    """True if this frontmost app is a later restore target (not us, Wine, or lock)."""
    if not info or not info.get('pid'):
        return False
    try:
        if int(info['pid']) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if is_self_front(info, self_pid) or is_self_or_wine(info, self_pid) or is_locked_session(info):
        return False
    if is_helper_front(info):
        return False
    name = (info.get('name') or '').lower()
    return name not in ('python', 'python3', 'python.app')


def adopt_resume(saved, current=None, self_pid=None, capture=capture_frontmost):
    """If quiet-wait started on the lock screen, remember the first real app after unlock."""
    current = capture() if current is None else current
    if usable_resume(current, self_pid):
        return {
            'pid': int(current['pid']),
            'name': current.get('name') or '',
            'bundle': current.get('bundle') or '',
        }
    if saved and (usable_resume(saved, self_pid) or is_locked_session(saved)):
        return saved
    return None


def activate_pid(pid):
    try:
        subprocess.run(
            ['osascript', '-e',
             f'tell application "System Events" to set frontmost of first process whose unix id is {int(pid)} to true'],
            check=True, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def restore_frontmost(saved, current=None, self_pid=None, activate=activate_pid, stolen_by=is_self_front):
    if sys.platform != 'darwin' or not saved:
        return False
    self_pid = os.getpid() if self_pid is None else self_pid
    if saved.get('pid') == self_pid:
        return False
    if is_locked_session(saved) or is_helper_front(saved) or not usable_resume(saved, self_pid):
        return False
    current = capture_frontmost() if current is None else current
    if is_locked_session(current) or not stolen_by(current, self_pid):
        return False
    if saved.get('pid') and activate(saved['pid']):
        return True
    bundle = saved.get('bundle') or ''
    try:
        if bundle and bundle not in GENERIC_BUNDLES:
            subprocess.run(['open', '-b', bundle], check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if saved.get('name') and saved.get('name', '').lower() not in ('python', 'python3', 'python.app'):
            subprocess.run(['open', '-a', saved['name']], check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        return False
    return False
