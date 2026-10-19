"""Probe: is there a visible top-level window whose title contains <substr>?

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" win_probe.py <substr>

exit 0 when found, 1 otherwise. Read-only.
"""
import ctypes as c
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)


def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    buf = c.create_unicode_buffer(n + 2)
    u32.GetWindowTextW(h, buf, n + 2)
    return buf.value


CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
sub = sys.argv[1] if len(sys.argv) > 1 else ''
found = [False]


@CB
def visit(h, _):
    if u32.IsWindowVisible(h) and sub in text(h):
        found[0] = True
    return True


u32.EnumWindows(visit, 0)
sys.exit(0 if found[0] else 1)
