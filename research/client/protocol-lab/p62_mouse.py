"""Real mouse double-click at client coords of a listview (SetCursorPos + mouse_event)."""
import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0); b = c.create_unicode_buffer(n+2)
    u32.GetWindowTextW(h, b, n+2); return b.value
def cls(h):
    b = c.create_unicode_buffer(256); u32.GetClassNameW(h, b, 256); return b.value
title, klass, cx, cy = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
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
    if cls(h) == klass: lv.append(h)
    return True
u32.EnumChildWindows(tops[0], kid, 0)
if not lv: raise SystemExit('no child')
h = lv[0]
pt = w.POINT(cx, cy)
u32.ClientToScreen(h, c.byref(pt))
u32.SetCursorPos(pt.x, pt.y)
clicks = 1 if '--single' in sys.argv[5:] else 2
for _ in range(clicks):
    u32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    u32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
print('clicked screen %d,%d (client %d,%d)' % (pt.x, pt.y, cx, cy))
