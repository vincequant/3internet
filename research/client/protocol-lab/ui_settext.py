"""Set text on an Edit control inside a dialog found by title substring.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" ui_settext.py <dialog-title-substr> <text>
"""
import ctypes as c
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
WM_SETTEXT = 0x000C


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


def main():
    if len(sys.argv) < 3:
        print('usage: ui_settext.py <dialog-title-substr> <text>')
        return 2
    tsub, value = sys.argv[1], sys.argv[2]
    tops = []

    @CB
    def visit(h, l):
        if u32.IsWindowVisible(h):
            tops.append(h)
        return True

    u32.EnumWindows(visit, 0)
    for t in tops:
        if tsub not in text(t):
            continue
        kids = []

        @CB
        def ch(h, l):
            kids.append(h)
            return True

        u32.EnumChildWindows(t, ch, 0)
        for k in kids:
            if cls(k).lower() == 'edit':
                u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, c.c_wchar_p]
                u32.SendMessageW.restype = c.c_ssize_t
                u32.SendMessageW(k, WM_SETTEXT, 0, value)
                print('set %r on edit hwnd=%#x parent=%r readback=%r'
                      % (value, k, text(t), text(k)))
                return 0
        print('no Edit found in %r (%#x)' % (text(t), t))
    print('no dialog matching %r' % tsub)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
