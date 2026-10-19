"""Click a child control by dialog-control id under a top window (BM_CLICK)."""
import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0); b = c.create_unicode_buffer(n+2)
    u32.GetWindowTextW(h, b, n+2); return b.value
title, want = sys.argv[1], int(sys.argv[2])
tops = []
@CB
def cb(h, l):
    if u32.IsWindowVisible(h) and title in text(h): tops.append(h)
    return True
u32.EnumWindows(cb, 0)
if not tops: raise SystemExit('no top')
seen = []
@CB
def kid(h, l):
    if u32.GetDlgCtrlID(h) == want:
        seen.append(h)
    return True
u32.EnumChildWindows(tops[0], kid, 0)
if not seen: raise SystemExit('no child with id %d' % want)
for h in seen:
    u32.PostMessageW(h, 0x00F5, 0, 0)  # BM_CLICK
print('clicked id=%d hwnd=%s caption=%r' % (want, hex(seen[0]), text(seen[0])))
