import ctypes as c, sys
from ctypes import wintypes as w
u32 = c.WinDLL('user32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    b = c.create_unicode_buffer(n + 2); u32.GetWindowTextW(h, b, n + 2); return b.value
def cls(h):
    b = c.create_unicode_buffer(256); u32.GetClassNameW(h, b, 256); return b.value
target = sys.argv[1] if len(sys.argv) > 1 else ''
def cb(h, l):
    t = text(h)
    print('%s\t%s\tid=%s\t%s' % (hex(h), cls(h), u32.GetDlgCtrlID(h), t))
    return True
if target:
    u32.EnumChildWindows(int(target, 16), CB(cb), 0)
else:
    u32.EnumWindows(CB(cb), 0)
