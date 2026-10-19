"""Post a double-click at (x,y) to the first child of class <cls> under title <sub>."""
import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0); b = c.create_unicode_buffer(n+2)
    u32.GetWindowTextW(h, b, n+2); return b.value
def cls(h):
    b = c.create_unicode_buffer(256); u32.GetClassNameW(h, b, 256); return b.value
title, klass, x, y = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
tops = []
@CB
def top_cb(h, l):
    if u32.IsWindowVisible(h) and title in text(h): tops.append(h)
    return True
u32.EnumWindows(top_cb, 0)
if not tops: raise SystemExit('no top window')
kids = []
@CB
def kid_cb(h, l):
    if cls(h) == klass: kids.append(h)
    return True
u32.EnumChildWindows(tops[0], kid_cb, 0)
if not kids: raise SystemExit('no child')
h = kids[0]
lp = (y << 16) | (x & 0xFFFF)
for m, wp in ((0x0201, 1), (0x0202, 0), (0x0203, 1), (0x0202, 0)):
    u32.PostMessageW(h, m, wp, lp)
print('posted dblclick to %s class=%s at %d,%d' % (hex(h), klass, x, y))
