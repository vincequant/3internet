#!/usr/bin/env python3
"""Capture the SANPK main window to a BMP via GDI (run under the target prefix's wine py32).

Usage: winshot.py <out.bmp>   (auto-picks the largest visible non-infrastructure window)
"""
import ctypes as c
import struct
import sys

from ctypes import wintypes as w

user32 = c.WinDLL('user32', use_last_error=True)
gdi32 = c.WinDLL('gdi32', use_last_error=True)

SKIP = ('tooltips_class32', 'IME', 'Wine IME', 'NetHookCoreWindow2012')


class RECT(c.Structure):
    _fields_ = [('left', c.c_long), ('top', c.c_long), ('right', c.c_long), ('bottom', c.c_long)]


out = sys.argv[1] if len(sys.argv) > 1 else r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\logs\winshot.bmp'
cands = []
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def cb(hwnd, lp):
    if not user32.IsWindowVisible(hwnd):
        return True
    name = c.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, 256)
    if name.value in SKIP:
        return True
    rc = RECT()
    if not user32.GetWindowRect(hwnd, c.byref(rc)):
        return True
    area = max(0, rc.right - rc.left) * max(0, rc.bottom - rc.top)
    if area > 100 * 100:
        cands.append((area, hwnd, rc, name.value))
    return True


user32.EnumWindows(CB(cb), 0)
if not cands:
    print('no candidate window')
    sys.exit(1)
cands.sort(key=lambda t: -t[0])
area, hwnd, rc, cls = cands[0]
wdt = rc.right - rc.left
hgt = rc.bottom - rc.top
print('window %s class=%r size=%dx%d' % (hex(hwnd), cls.encode('ascii', 'replace'), wdt, hgt))

hwndDC = user32.GetWindowDC(hwnd)
memDC = gdi32.CreateCompatibleDC(hwndDC)
bmp = gdi32.CreateCompatibleBitmap(hwndDC, wdt, hgt)
gdi32.SelectObject(memDC, bmp)
ok1 = user32.PrintWindow(hwnd, memDC, 2)
ok2 = user32.PrintWindow(hwnd, memDC, 0)
ok3 = gdi32.BitBlt(memDC, 0, 0, wdt, hgt, hwndDC, 0, 0, 0x00CC0020)  # SRCCOPY
print('PrintWindow(2)=%d PrintWindow(0)=%d BitBlt=%d' % (ok1, ok2, ok3))


class BMIH(c.Structure):
    _fields_ = [('biSize', w.DWORD), ('biWidth', c.c_long), ('biHeight', c.c_long),
                ('biPlanes', w.WORD), ('biBitCount', w.WORD), ('biCompression', w.DWORD),
                ('biSizeImage', w.DWORD), ('biXPelsPerMeter', c.c_long), ('biYPelsPerMeter', c.c_long),
                ('biClrUsed', w.DWORD), ('biClrImportant', w.DWORD)]


stride = ((wdt * 3 + 3) // 4) * 4
bi = BMIH()
bi.biSize = c.sizeof(bi)
bi.biWidth = wdt
bi.biHeight = -hgt  # top-down
bi.biPlanes = 1
bi.biBitCount = 24
bi.biCompression = 0
buf = c.create_string_buffer(stride * hgt)
got = gdi32.GetDIBits(memDC, bmp, 0, hgt, buf, c.byref(bi), 0)
print('GetDIBits rows=%d' % got)
hdr = struct.pack('<2sIHHI', b'BM', 14 + 40 + len(buf), 0, 0, 14 + 40)
info = struct.pack('<IiiHHIIiiII', 40, wdt, hgt, 1, 24, 0, 0, 0, 0, 0, 0)
open(out, 'wb').write(hdr + info + buf.raw)
print('saved', out)
