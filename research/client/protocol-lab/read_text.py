"""Read the text of a control (e.g. the RichEdit message log) in a top window.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" read_text.py <top-title-substr> <class-substr> [tail-chars]

Finds the first visible top window whose title contains <top-title-substr>,
then the first child whose class contains <class-substr>, and prints the last
<tail-chars> (default 800) characters of its text via WM_GETTEXT.
Read-only.
"""
import ctypes as c
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
u32.SendMessageW.restype = c.c_ssize_t

CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def text(h):
    n = int(u32.GetWindowTextLengthW(h) or 0)
    buf = c.create_unicode_buffer(n + 2)
    u32.GetWindowTextW(h, buf, n + 2)
    return buf.value


def cls(h):
    buf = c.create_unicode_buffer(256)
    u32.GetClassNameW(h, buf, 256)
    return buf.value


def main():
    t_sub = sys.argv[1]
    c_sub = sys.argv[2].lower()
    tail_n = int(sys.argv[3]) if len(sys.argv) > 3 else 800
    tops = []

    @CB
    def visit(h, _):
        if u32.IsWindowVisible(h) and t_sub in text(h):
            tops.append(h)
        return True

    u32.EnumWindows(visit, 0)
    if not tops:
        print('top window not found: %r' % t_sub)
        return 2
    top = tops[0]
    kids = []

    @CB
    def ch(h, _):
        kids.append(h)
        return True

    u32.EnumChildWindows(top, ch, 0)
    for k in kids:
        if c_sub in cls(k).lower():
            buf = c.create_unicode_buffer(65536)
            u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
            u32.SendMessageW.restype = c.c_ssize_t
            n = int(u32.SendMessageW(k, 0x000D, 65534, c.cast(buf, c.c_void_p).value) or 0)
            s = buf.value
            print('--- control %#x [%s] len=%d ---' % (k, cls(k), n))
            print(s[-tail_n:])
            return 0
    print('control with class containing %r not found in %r' % (c_sub, t_sub))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
