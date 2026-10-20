"""Print a listview's client size + item count (for coordinate-based picking)."""
import ctypes as c, json, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
u32.SendMessageW.restype = c.c_ssize_t
u32.SendMessageW.argtypes = [w.HWND, w.UINT, c.c_void_p, c.c_void_p]
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0); b = c.create_unicode_buffer(n+2)
    u32.GetWindowTextW(h, b, n+2); return b.value
def cls(h):
    b = c.create_unicode_buffer(256); u32.GetClassNameW(h, b, 256); return b.value
title = sys.argv[1] if len(sys.argv) > 1 else '剧本选择'
tops = []
@CB
def cb(h, l):
    if u32.IsWindowVisible(h) and title in text(h): tops.append(h)
    return True
u32.EnumWindows(cb, 0)
if not tops: raise SystemExit('no top')
lv = []
@CB
def kid(h, l):
    if cls(h) == 'SysListView32': lv.append(h)
    return True
u32.EnumChildWindows(tops[0], kid, 0)
h = lv[0]
r = w.RECT(); u32.GetClientRect(h, c.byref(r))
n = int(u32.SendMessageW(h, 0x1004, 0, 0))  # LVM_GETITEMCOUNT
sel = int(u32.SendMessageW(h, 0x100C, -1, 2))  # LVM_GETSELECTIONMARK
print(json.dumps({'hwnd': hex(h), 'w': r.right - r.left, 'h': r.bottom - r.top,
                  'count': n, 'selected': sel}))
