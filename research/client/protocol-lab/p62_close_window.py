"""Gracefully close the top-level window whose title contains <substr> (WM_CLOSE)."""
import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
sub = sys.argv[1]
found = []
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    b = c.create_unicode_buffer(n + 2); u32.GetWindowTextW(h, b, n + 2); return b.value
def cb(h, l):
    if u32.IsWindowVisible(h):
        t = text(h)
        if sub in t and '#' not in t:
            found.append((h, t))
    return True
u32.EnumWindows(CB(cb), 0)
for h, t in found:
    ok = u32.PostMessageW(h, 0x0010, 0, 0)
    print('WM_CLOSE %s %r ok=%s' % (hex(h), t, bool(ok)))
if not found:
    print('no window matching %r' % sub)
    raise SystemExit(1)
