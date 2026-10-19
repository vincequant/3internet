"""Is the window responsive? SendMessageTimeout(WM_NULL) probe. Read-only.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" win_hung.py [substr]
"""
import ctypes as c
import json
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002


def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    buf = c.create_unicode_buffer(n + 2)
    u32.GetWindowTextW(h, buf, n + 2)
    return buf.value


CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
sub = sys.argv[1] if len(sys.argv) > 1 else ''
rows = []


@CB
def visit(h, _):
    if not u32.IsWindowVisible(h):
        return True
    t = text(h)
    if sub and sub not in t:
        return True
    res = c.c_size_t(0)
    r = u32.SendMessageTimeoutW(h, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, 1500, c.byref(res))
    rows.append({'hwnd': int(h), 'title': t, 'responsive': bool(r), 'err': 0 if r else c.get_last_error()})
    return True


u32.EnumWindows(visit, 0)
print(json.dumps(rows, ensure_ascii=False))
