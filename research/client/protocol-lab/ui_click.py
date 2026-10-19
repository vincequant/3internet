"""Click a button (by caption substring) on the SANPK main window via PostMessage BM_CLICK.

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" ui_click.py <caption> [--dry]

--dry only lists candidates; otherwise clicks the first visible match.
"""
import ctypes as c
import sys
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u32.PostMessageW.restype = w.BOOL


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
    if len(sys.argv) < 2:
        print('usage: ui_click.py <caption> [--dry]')
        return 2
    caption = sys.argv[1]
    dry = '--dry' in sys.argv
    hits = []
    tops = []

    @CB
    def visit(h, l):
        if u32.IsWindowVisible(h):
            tops.append(h)
        return True

    u32.EnumWindows(visit, 0)
    for t in tops:
        kids = []

        @CB
        def ch(h, l):
            kids.append(h)
            return True

        u32.EnumChildWindows(t, ch, 0)
        for k in kids:
            if 'button' not in cls(k).lower():
                continue
            cap = text(k)
            if caption in cap and u32.IsWindowVisible(k):
                hits.append((k, int(u32.GetDlgCtrlID(k)), cap, text(t)))

    out = []
    for h, cid, cap, parent in hits:
        out.append('candidate hwnd=%#x id=%d cap=%r parent=%r' % (h, cid, cap, parent))
    print('\n'.join(out) if out else 'no candidates for %r' % caption)
    if not hits:
        return 2
    if dry:
        return 0
    h = hits[0][0]
    ok = u32.PostMessageW(h, 0xF5, 0, 0)  # BM_CLICK
    print('clicked hwnd=%#x cap=%r ok=%s' % (h, hits[0][2], bool(ok)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
