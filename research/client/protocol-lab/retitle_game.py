"""Keep the SANPK main window title suffixed with a display name, for window identification.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" retitle_game.py <display-name> [--interval 2] [--once]

Finds the game's top-level window (class starts with '三国志 Internet', or a top
window whose title contains '三国志Internet联机版3.5') and sets the title to
'三国志Internet联机版3.5【<display-name>】'. Re-applies every <interval> seconds
(the game may reset its caption on screen transitions). Exits after ~30s with no
matching window. Otherwise read-only: it only sets the window caption.
"""
import ctypes as c
import sys
import time
from ctypes import wintypes as w

# wine python 默认 stdout 编码是 cp1252，打印中文会 UnicodeEncodeError 直接崩掉循环；
# 调用方也应带 PYTHONIOENCODING=utf-8（双保险）。
try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass

u32 = c.WinDLL('user32', use_last_error=True)
u32.SetWindowTextW.argtypes = [w.HWND, c.c_wchar_p]
u32.SetWindowTextW.restype = w.BOOL

BASE = '三国志Internet联机版3.5'
CLASS_MARK = '三国志 Internet'


def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    buf = c.create_unicode_buffer(n + 2)
    u32.GetWindowTextW(h, buf, n + 2)
    return buf.value


def cls(h):
    buf = c.create_unicode_buffer(256)
    u32.GetClassNameW(h, buf, 256)
    return buf.value


CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def find_main():
    hits = []

    @CB
    def visit(h, _):
        tl = text(h)
        cl = cls(h)
        if cl.startswith(CLASS_MARK) or BASE in tl:
            hits.append(h)
        return True

    u32.EnumWindows(visit, 0)
    return hits[0] if hits else None


def main():
    if len(sys.argv) < 2:
        print('usage: retitle_game.py <display-name> [--interval 2] [--once]')
        return 2
    name = sys.argv[1]
    interval = 2.0
    if '--interval' in sys.argv:
        interval = float(sys.argv[sys.argv.index('--interval') + 1])
    once = '--once' in sys.argv
    target = '%s【%s】' % (BASE, name)
    misses = 0
    while True:
        h = find_main()
        if h:
            misses = 0
            if text(h) != target:
                u32.SetWindowTextW(h, target)
                print('retitle %#x -> %r' % (h, text(h)), flush=True)
        else:
            misses += 1
            if misses == 1:
                print('main window not found yet', flush=True)
            if misses >= 15:
                print('main window gone, exiting', flush=True)
                return 0
        if once:
            return 0
        time.sleep(interval)


if __name__ == '__main__':
    raise SystemExit(main())
