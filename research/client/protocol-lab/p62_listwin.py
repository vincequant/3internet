import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    b = c.create_unicode_buffer(n + 2); u32.GetWindowTextW(h, b, n + 2); return b.value
def cls(h):
    b = c.create_unicode_buffer(256); u32.GetClassNameW(h, b, 256); return b.value
def cb(h, l):
    if u32.IsWindowVisible(h):
        t = text(h)
        if t:
            print('%s\t%s\t%s' % (hex(h), cls(h), t))
    return True
u32.EnumWindows(CB(cb), 0)
