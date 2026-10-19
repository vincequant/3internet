#!/usr/bin/env python3
"""Read-only: why the unit card says "Invalid window handle".

Prints the view-level window handle the inspector trusts, whether Win32 still
accepts it, and every top-level window owned by the game process, so a valid
candidate can be chosen instead of guessing.
"""
import ctypes as c
import json
import os
import struct
import sys

from ctypes import wintypes as W


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from roundprobe import find_sanpk, _win
    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe'}))
        return 1
    h = k.OpenProcess(0x0410, False, pid)

    def rd(addr, n=4):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    def u32(addr):
        raw = rd(addr)
        return struct.unpack('<I', raw)[0] if raw else None

    core = u32(0x53bb30)
    view = u32(0x53b930)
    doc = core - 0x912 if core else None
    view_hwnd = u32(view + 0x1c) if view else None

    user32 = c.WinDLL('user32', use_last_error=True)
    user32.IsWindow.argtypes = [W.HWND]
    user32.IsWindow.restype = W.BOOL
    user32.GetWindowRect.argtypes = [W.HWND, c.POINTER(W.RECT)]
    rect = W.RECT()

    def describe(hwnd):
        if not hwnd:
            return None
        ok = bool(user32.IsWindow(hwnd))
        out = {'hwnd': hex(hwnd), 'is_window': ok}
        if ok:
            if user32.GetWindowRect(hwnd, c.byref(rect)):
                out['rect'] = [rect.left, rect.top, rect.right, rect.bottom]
            owner = W.DWORD()
            user32.GetWindowThreadProcessId(hwnd, c.byref(owner))
            out['pid'] = owner.value
            length = user32.GetWindowTextLengthW(hwnd)
            title = c.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            out['title'] = title.value
            out['visible'] = bool(user32.IsWindowVisible(hwnd))
        return out

    windows = []
    EnumProc = c.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    GW_OWNER, GWL_STYLE = 4, -16
    user32.GetWindowLongW.argtypes = [W.HWND, c.c_int]
    user32.GetWindowLongW.restype = c.c_long

    def on_window(hwnd, _lparam):
        owner = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, c.byref(owner))
        if owner.value == (pid & 0xFFFFFFFF) or owner.value == pid:
            info = describe(int(hwnd)) or {}
            info['owner'] = user32.GetWindowLongW(hwnd, GW_OWNER)
            info['style'] = hex(user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF)
            windows.append(info)
        return True

    user32.EnumWindows(EnumProc(on_window), 0)
    print(json.dumps({'pid': pid, 'core': hex(core) if core else None,
                      'view': hex(view) if view else None,
                      'doc': hex(doc) if doc else None,
                      'view_hwnd': describe(view_hwnd),
                      'windows': windows}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
