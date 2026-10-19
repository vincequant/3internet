"""An owned hidden Win32 HWND, native notifications and exact packet release.

No hooks, foreign memory, game launch, login or network calls. The caller
supplies the native DecodeWParam/DeletePacket/AcceptEXIT exports.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import struct

from p28_wire import inspect_packet

WM_EVENT, WM_DATA, WM_CHAT = 0x8500, 0x8501, 0x8502


class Receiver:
    def __init__(self, log, decode, delete, accept_exit):
        self.log, self.decode, self.delete = log, decode, delete
        self.accept_exit = accept_exit
        self.count = self.freed = self.errors = 0
        self.u = c.WinDLL('user32', use_last_error=True)
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.GetModuleHandleW.argtypes = [w.LPCWSTR]
        self.k.GetModuleHandleW.restype = w.HMODULE
        callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT,
                                      w.WPARAM, w.LPARAM)

        class WNDCLASS(c.Structure):
            _fields_ = [('style', w.UINT), ('lpfnWndProc', callback_type),
                        ('cbClsExtra', c.c_int), ('cbWndExtra', c.c_int),
                        ('hInstance', w.HINSTANCE), ('hIcon', w.HICON),
                        ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH),
                        ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR)]

        self.u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.u.DefWindowProcW.restype = c.c_ssize_t
        self.u.RegisterClassW.argtypes = [c.POINTER(WNDCLASS)]
        self.u.RegisterClassW.restype = w.ATOM
        self.u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR,
            w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU,
            w.HINSTANCE, c.c_void_p]
        self.u.CreateWindowExW.restype = w.HWND
        self.u.DestroyWindow.argtypes = [w.HWND]
        self.u.DestroyWindow.restype = w.BOOL
        self.u.UnregisterClassW.argtypes = [w.LPCWSTR, w.HINSTANCE]
        self.u.UnregisterClassW.restype = w.BOOL
        self.u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        self.u.PeekMessageW.restype = w.BOOL
        self.u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        self.u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
        self.u.DispatchMessageW.restype = c.c_ssize_t
        self.u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.u.PostMessageW.restype = w.BOOL
        self.instance = self.k.GetModuleHandleW(None)
        self.class_name = 'SGI_P28_OWNED_%d' % os.getpid()

        def proc(hwnd, msg, wp, lp):
            if msg not in (WM_EVENT, WM_DATA, WM_CHAT):
                return self.u.DefWindowProcW(hwnd, msg, wp, lp)
            try:
                kind = int(self.decode(wp))
                low = wp & 0xffff
                self.log({'ev': 'notification', 'message': msg, 'wparam': wp,
                          'type': kind, 'lparam': lp & 0xffffffff})
                # A known data/chat notification owns a heap packet, even if
                # its old session tag is rejected. Other LPs are scalar IDs.
                if low in (3, 4) and lp:
                    ptr = lp & 0xffffffff
                    try:
                        if kind not in (3, 4):
                            self.log({'ev': 'stale_packet_dropped', 'type': low})
                        else:
                            header = c.string_at(ptr, 12)
                            size = struct.unpack_from('<I', header, 8)[0]
                            cap = 0x1800 if kind == 4 else 128
                            if size > cap:
                                raise ValueError('native_packet_length_bound')
                            packet = inspect_packet(header + c.string_at(ptr+12, size), kind)
                            self.count += 1
                            self.log(dict(packet, ev='received_packet', type=kind,
                                          packet_index=self.count))
                    finally:
                        rc = int(self.delete(c.c_void_p(ptr)))
                        self.freed += 1
                        self.log({'ev': 'packet_release', 'pointer': ptr, 'rc': rc,
                                  'release_calls': self.freed})
                elif kind == 2:
                    rc = int(self.accept_exit(lp & 0xffffffff))
                    self.log({'ev': 'accept_exit', 'member_id': lp & 0xffffffff, 'rc': rc})
            except Exception as exc:
                self.errors += 1
                self.log({'ev': 'receiver_error', 'error': type(exc).__name__,
                          'detail': str(exc)[:160]})
            return 0

        self.callback = callback_type(proc)  # strong reference for HWND lifetime
        wc = WNDCLASS()
        wc.lpfnWndProc = self.callback
        wc.hInstance = self.instance
        wc.lpszClassName = self.class_name
        if not self.u.RegisterClassW(c.byref(wc)):
            raise c.WinError(c.get_last_error())
        # Message-only window: no visible UI or interaction with other windows.
        self.hwnd = self.u.CreateWindowExW(0, self.class_name, '', 0, 0, 0,
            0, 0, w.HWND(-3), None, self.instance, None)
        if not self.hwnd:
            self.u.UnregisterClassW(self.class_name, self.instance)
            raise c.WinError(c.get_last_error())
        self.log({'ev': 'owned_window_created', 'hwnd': int(self.hwnd)})

    def pump(self, cap=256):
        msg = w.MSG()
        for _ in range(cap):
            if not self.u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                break
            self.u.TranslateMessage(c.byref(msg))
            self.u.DispatchMessageW(c.byref(msg))

    def close(self):
        self.pump()
        self.u.DestroyWindow(self.hwnd)
        self.u.UnregisterClassW(self.class_name, self.instance)
        self.hwnd = None
