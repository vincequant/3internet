"""Put stdin text on the Wine Windows clipboard. Does not touch the game."""
import ctypes
from ctypes import wintypes as W
import sys

from win_clipboard import unicode_clipboard

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def put(text):
    data = unicode_clipboard(text)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GlobalAlloc.argtypes = [W.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = W.HGLOBAL
    kernel.GlobalLock.argtypes = [W.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [W.HGLOBAL]
    kernel.GlobalUnlock.restype = W.BOOL
    kernel.GlobalFree.argtypes = [W.HGLOBAL]
    kernel.GlobalFree.restype = W.HGLOBAL
    user.OpenClipboard.argtypes = [W.HWND]
    user.OpenClipboard.restype = W.BOOL
    user.EmptyClipboard.argtypes = []
    user.EmptyClipboard.restype = W.BOOL
    user.SetClipboardData.argtypes = [W.UINT, W.HANDLE]
    user.SetClipboardData.restype = W.HANDLE
    user.CloseClipboard.argtypes = []
    user.CloseClipboard.restype = W.BOOL
    handle = kernel.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        locked = kernel.GlobalLock(handle)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(locked, data, len(data))
        kernel.GlobalUnlock(handle)
        if not user.OpenClipboard(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not user.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user.SetClipboardData(CF_UNICODETEXT, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None
        finally:
            user.CloseClipboard()
    finally:
        if handle:
            kernel.GlobalFree(handle)


def main():
    text = sys.stdin.buffer.read().decode('utf-8')
    put(text)
    print('ok', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
