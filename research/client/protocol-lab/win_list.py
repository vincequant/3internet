"""List visible top-level windows (title/class/rect) in the target prefix. Read-only.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" win_list.py [filter-substr]
"""
import ctypes as c
import json
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
u32.GetWindowTextLengthW.restype = c.c_int
u32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u32.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]


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
sub = sys.argv[1] if len(sys.argv) > 1 else ''
out = []


@CB
def visit(h, _):
    if not u32.IsWindowVisible(h):
        return True
    t = text(h)
    if sub and sub not in t:
        return True
    r = w.RECT()
    try:
        u32.GetWindowRect(h, c.byref(r))
        rect = [r.left, r.top, r.right, r.bottom]
    except Exception:
        rect = None
    out.append({'hwnd': int(h), 'title': t, 'class': cls(h), 'rect': rect,
                'enabled': bool(u32.IsWindowEnabled(h)),
                'modal': bool(u32.GetWindowLongW(h, -16) & 0x10000000)})
    return True


u32.EnumWindows(visit, 0)
print(json.dumps(out, ensure_ascii=False))
