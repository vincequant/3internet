#!/usr/bin/env python3
"""D: an external Win32 unit inspector with its own click-catching veil.

Inspection stays read-only. The optional edit row writes only this shadow
client's own unit/general fields through a dedicated write handle
(VirtualProtectEx + WriteProcessMemory): value clamped to the verified range,
read back, before/after recorded, one undo. No game calls, messages, hooks or
network APIs, and never another process. Start disarmed. While armed, its own
layered window consumes mouse clicks; it never forwards them to SANPK.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p52_shadow_ui import SANPK_SHA
from p53_unit_data import (capture_map, context, geometry_key, hit_units,
                          inspect_unit, panel_text)
from p53_unit_model import FIELDS as UNIT_FIELDS, UNIT_TYPES

GENERAL_VT = 0x5056f0
GENERAL_FIELDS = {'lead': ('统率', 0x25), 'war': ('武力', 0x26), 'intel': ('智力', 0x27),
                  'pol': ('政治', 0x28), 'cha': ('魅力', 0x29)}


class ReadOnlyGame:
    def __init__(self, bridge, pid=None):
        if Path(os.environ.get('WINEPREFIX', '').rstrip('/\\')).name != 'prefix-fengye-shadow':
            raise ValueError('explicit shadow prefix required')
        os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
        sys.path.insert(0, str(bridge))
        from probe import Memory
        from p51_shadow_inject import find_process
        targets = find_process('SANPK.exe')
        if pid is None:
            if len(targets) != 1:
                raise ValueError('need exactly one shadow SANPK process')
            pid = targets[0][0]
        elif pid not in [row[0] for row in targets]:
            raise ValueError('specified process is not SANPK')
        self.memory = Memory(pid)
        try:
            if hashlib.sha256(Path(self.memory.identity['path']).read_bytes()).hexdigest() != SANPK_SHA:
                raise ValueError('unsupported SANPK SHA')
            self.identity = dict(self.memory.identity, sanpk_sha256=SANPK_SHA,
                                 access_mask='0x410 QUERY_INFORMATION|VM_READ',
                                 write_handle='lazy 0x1F0FFF, first edit only',
                                 write_scope='shadow client pid only')
            self.validate()
        except BaseException:
            self.close(); raise

    def validate(self):
        ticks, _ = self.memory.api.process_times(self.memory.h)
        if (ticks != self.identity['creation_filetime'] or
                self.memory.api.query_path(self.memory.h) != self.identity['path']):
            raise ValueError('process identity changed')

    def _exact(self, address, size):
        data = self.memory.read(address, size)
        if not data or len(data) != size:
            raise ValueError('read failed at ' + hex(address))
        return data

    def _write_context(self):
        if getattr(self, '_wapi', None) is None:
            api = C.WinDLL('kernel32', use_last_error=True)
            api.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
            api.OpenProcess.restype = W.HANDLE
            api.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p,
                                               C.c_size_t, C.POINTER(C.c_size_t)]
            api.WriteProcessMemory.restype = W.BOOL
            api.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t,
                                             W.DWORD, C.POINTER(W.DWORD)]
            api.VirtualProtectEx.restype = W.BOOL
            api.CloseHandle.argtypes = [W.HANDLE]
            self._wapi = api
            self._wh = api.OpenProcess(0x1F0FFF, False, self.identity['pid'])
            if not self._wh:
                raise ValueError('write handle unavailable (%d)' % C.get_last_error())
        return self._wapi, self._wh

    def write_bytes(self, address, data):
        self.validate()
        api, handle = self._write_context()
        payload = bytes(data)
        old = W.DWORD(0)
        if not api.VirtualProtectEx(handle, C.c_void_p(address), len(payload), 0x40, C.byref(old)):
            raise ValueError('VirtualProtectEx RW failed (%d)' % C.get_last_error())
        try:
            buf = C.create_string_buffer(payload, len(payload))
            got = C.c_size_t(0)
            if not api.WriteProcessMemory(handle, C.c_void_p(address), buf, len(payload),
                                          C.byref(got)) or got.value != len(payload):
                raise ValueError('WriteProcessMemory failed (%d/%s)' %
                                 (C.get_last_error(), got.value))
        finally:
            restore = W.DWORD(0)
            api.VirtualProtectEx(handle, C.c_void_p(address), len(payload), old.value,
                                 C.byref(restore))
        self.validate()
        return True

    def unit_field(self, address, field):
        label, offset, fmt, _ = UNIT_FIELDS[field][:4]
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self._exact(address + offset, size))[0]

    def edit_unit(self, address, field, value):
        self.validate()
        label, offset, fmt, maximum = UNIT_FIELDS[field][:4]
        vtable = struct.unpack('<I', self._exact(address, 4))[0]
        if vtable not in UNIT_TYPES:
            raise ValueError('此地址已不是已知部队对象；请重新点图')
        if field == 'morale' and vtable == 0x5099d0:
            maximum = min(maximum, 50)
        size = struct.calcsize(fmt)
        before = struct.unpack(fmt, self._exact(address + offset, size))[0]
        written = max(0, min(int(value), maximum))
        self.write_bytes(address + offset, struct.pack(fmt, written))
        after = struct.unpack(fmt, self._exact(address + offset, size))[0]
        record = dict(kind='unit_edit', scope='unit', address=hex(address), unit_id=None,
                      vtable=hex(vtable), field=field, label=label, before=before,
                      requested=int(value), written=written, after=after,
                      ok=after == written, clamp=[0, maximum], local_only=True)
        self.pending_revert = dict(scope='unit', address=address, field=field, before=before)
        return record

    def walk_generals(self, limit=2048):
        core = context(self.memory.read)['core']
        header = self._exact(core + 0x514, 28)
        head, tail, count = struct.unpack_from('<III', header, 4)
        if count > limit:
            raise ValueError('general container bound')
        node, prev, seen, objects = head, 0, set(), []
        for _ in range(count):
            if node < 0x10000 or node in seen:
                raise ValueError('general list cyclic/short')
            seen.add(node)
            nxt, back, obj = struct.unpack('<III', self._exact(node, 12))
            if back != prev or obj < 0x10000 or obj in objects:
                raise ValueError('general list identity mismatch')
            objects.append(obj)
            prev, node = node, nxt
        if node or prev != tail:
            raise ValueError('general count/tail mismatch')
        return objects

    def general_stats(self, general_id):
        for address in self.walk_generals():
            raw = self._exact(address, 12)
            if struct.unpack_from('<I', raw)[0] != GENERAL_VT:
                continue
            if struct.unpack_from('<H', raw, 10)[0] == general_id:
                values = dict(zip(('lead', 'war', 'intel', 'pol', 'cha'),
                                  self._exact(address + 0x25, 5)))
                return dict(general_id=general_id, address=address, values=values,
                            blade_total=values['lead'] + values['war'])
        return None

    def edit_general(self, general_id, field, value):
        self.validate()
        stats = self.general_stats(general_id)
        if stats is None:
            raise ValueError('武将 %s 不在当前名单；请重新点图' % general_id)
        label, offset = GENERAL_FIELDS[field]
        before = self._exact(stats['address'] + offset, 1)[0]
        written = max(0, min(int(value), 100))
        self.write_bytes(stats['address'] + offset, bytes([written]))
        after = self._exact(stats['address'] + offset, 1)[0]
        if field == 'lead':
            blade_after = after + stats['values']['war']
        elif field == 'war':
            blade_after = stats['values']['lead'] + after
        else:
            blade_after = stats['blade_total']
        record = dict(kind='general_edit', scope='general', general_id=general_id,
                      address=hex(stats['address']), field=field, label=label,
                      before=before, requested=int(value), written=written, after=after,
                      ok=after == written, clamp=[0, 100], local_only=True,
                      blade_total_before=stats['blade_total'], blade_total_after=blade_after)
        self.pending_revert = dict(scope='general', general_id=general_id, field=field,
                                   before=before)
        return record

    def revert_pending(self):
        pending = getattr(self, 'pending_revert', None)
        if not pending:
            raise ValueError('没有可还原的写入')
        if pending['scope'] == 'general':
            record = self.edit_general(pending['general_id'], pending['field'], pending['before'])
        else:
            record = self.edit_unit(pending['address'], pending['field'], pending['before'])
        self.pending_revert = None
        record.update(kind='edit_revert', restored=pending['before'])
        return record

    def geometry(self):
        self.validate()
        return context(self.memory.read)

    def capture(self):
        self.validate()
        result = capture_map(self.memory.read)
        result['identity'] = self.identity
        return result

    def inspect(self, snapshot, row):
        self.validate()
        result = inspect_unit(self.memory.read, snapshot, row)
        self.validate()
        result['identity'] = self.identity
        result['rpm_calls_total'] = self.memory.calls
        result['rpm_bytes_total'] = self.memory.bytes
        return result

    def close(self):
        if getattr(self, '_wh', None) and getattr(self, '_wapi', None):
            try:
                self._wapi.CloseHandle(self._wh)
            except BaseException:
                pass
            self._wh = None
        self.memory.close()



PAINTSTRUCT_X = None


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [('biSize', W.DWORD), ('biWidth', W.LONG), ('biHeight', W.LONG),
                ('biPlanes', W.WORD), ('biBitCount', W.WORD), ('biCompression', W.DWORD),
                ('biSizeImage', W.DWORD), ('biXPelsPerMeter', W.LONG),
                ('biYPelsPerMeter', W.LONG), ('biClrUsed', W.DWORD), ('biClrImportant', W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', W.DWORD * 3)]


class BLENDFUNCTION(C.Structure):
    _fields_ = [('BlendOp', C.c_ubyte), ('BlendFlags', C.c_ubyte),
                ('SourceConstantAlpha', C.c_ubyte), ('AlphaFormat', C.c_ubyte)]


class PAINTSTRUCT(C.Structure):
    _fields_ = [('hdc', W.HDC), ('fErase', W.BOOL), ('rcPaint', W.RECT),
                ('fRestore', W.BOOL), ('fIncUpdate', W.BOOL),
                ('rgbReserved', C.c_ubyte * 32)]


def rgb(r, g, b):
    return (r & 0xff) | ((g & 0xff) << 8) | ((b & 0xff) << 16)


class T:
    CARD = rgb(20, 23, 28)
    TOP = rgb(26, 30, 37)
    BOTTOM = rgb(17, 20, 25)
    BORDER = rgb(48, 55, 66)
    TEXT = rgb(244, 246, 250)
    LABEL = rgb(152, 161, 174)
    SUB = rgb(121, 130, 143)
    DIM = rgb(90, 99, 111)
    HAIR = rgb(35, 40, 48)
    HOVER = rgb(29, 34, 42)
    FIELD = rgb(15, 19, 25)
    ACCENT = rgb(233, 185, 73)
    ACCENT_SOFT = rgb(42, 36, 24)
    BLUE = rgb(76, 141, 255)
    BLUE_SOFT = rgb(24, 36, 58)
    GREEN = rgb(61, 214, 140)
    RED = rgb(255, 90, 82)
    BTN = rgb(35, 41, 53)
    BTN_HOVER = rgb(44, 52, 66)


def native_api():
    if sys.platform != 'win32':
        raise RuntimeError('run the inspector in shadow Wine py32 / Win32')
    u = C.WinDLL('user32', use_last_error=True)
    k = C.WinDLL('kernel32', use_last_error=True)
    g = C.WinDLL('gdi32', use_last_error=True)
    declarations = (
        (u, 'CreateWindowExW', [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
             C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND),
        (u, 'DefWindowProcW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t),
        (u, 'RegisterClassW', [C.c_void_p], W.WORD),
        (u, 'GetClientRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL),
        (u, 'ClientToScreen', [W.HWND, C.POINTER(W.POINT)], W.BOOL),
        (u, 'GetWindowRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL),
        (u, 'GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
        (u, 'GetForegroundWindow', [], W.HWND),
        (u, 'GetAncestor', [W.HWND, W.UINT], W.HWND),
        (u, 'SetWindowPos', [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL),
        (u, 'SetLayeredWindowAttributes', [W.HWND, W.DWORD, C.c_ubyte, W.DWORD], W.BOOL),
        (u, 'UpdateLayeredWindow', [W.HWND, W.HDC, C.POINTER(W.POINT), C.POINTER(W.SIZE),
             W.HDC, C.POINTER(W.POINT), W.DWORD, C.POINTER(BLENDFUNCTION), W.DWORD], W.BOOL),
        (u, 'GetDC', [W.HWND], W.HDC),
        (u, 'ReleaseDC', [W.HWND, W.HDC], C.c_int),
        (u, 'ShowWindow', [W.HWND, C.c_int], W.BOOL),
        (u, 'SetWindowTextW', [W.HWND, W.LPCWSTR], W.BOOL),
        (u, 'GetWindowTextW', [W.HWND, W.LPWSTR, C.c_int], C.c_int),
        (u, 'SendMessageW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t),
        (u, 'PostMessageW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
        (u, 'GetMessageW', [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int),
        (u, 'TranslateMessage', [C.POINTER(W.MSG)], W.BOOL),
        (u, 'DispatchMessageW', [C.POINTER(W.MSG)], C.c_ssize_t),
        (u, 'SetTimer', [W.HWND, C.c_size_t, W.UINT, C.c_void_p], C.c_size_t),
        (u, 'KillTimer', [W.HWND, C.c_size_t], W.BOOL),
        (u, 'DestroyWindow', [W.HWND], W.BOOL),
        (u, 'IsWindow', [W.HWND], W.BOOL),
        (u, 'IsWindowVisible', [W.HWND], W.BOOL),
        (u, 'IsIconic', [W.HWND], W.BOOL),
        (u, 'LoadCursorW', [W.HINSTANCE, C.c_void_p], W.HANDLE),
        (u, 'SetCursor', [W.HANDLE], W.HANDLE),
        (u, 'RegisterHotKey', [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL),
        (u, 'UnregisterHotKey', [W.HWND, C.c_int], W.BOOL),
        (u, 'PostQuitMessage', [C.c_int], None),
        (u, 'InvalidateRect', [W.HWND, C.c_void_p, W.BOOL], W.BOOL),
        (u, 'SetCapture', [W.HWND], W.HWND),
        (u, 'ReleaseCapture', [], W.BOOL),
        (u, 'GetCursorPos', [C.POINTER(W.POINT)], W.BOOL),
        (u, 'SetFocus', [W.HWND], W.HWND),
        (u, 'GetSystemMetrics', [C.c_int], C.c_int),
        (u, 'SetForegroundWindow', [W.HWND], W.BOOL),
        (u, 'MsgWaitForMultipleObjects', [W.DWORD, C.c_void_p, W.BOOL, W.DWORD, W.UINT], W.DWORD),
        (k, 'GetModuleHandleW', [W.LPCWSTR], W.HMODULE),
        (k, 'OpenProcess', [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        (k, 'WriteProcessMemory', [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
             C.POINTER(C.c_size_t)], W.BOOL),
        (k, 'VirtualProtectEx', [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD,
             C.POINTER(W.DWORD)], W.BOOL),
        (k, 'CloseHandle', [W.HANDLE], W.BOOL),
        (g, 'CreateFontW', [C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, W.DWORD, W.DWORD,
             W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.LPCWSTR], W.HANDLE),
        (g, 'CreateSolidBrush', [W.DWORD], W.HANDLE),
        (g, 'CreatePen', [C.c_int, C.c_int, W.DWORD], W.HANDLE),
        (g, 'SelectObject', [W.HDC, W.HANDLE], W.HANDLE),
        (g, 'DeleteObject', [W.HANDLE], W.BOOL),
        (g, 'SetTextColor', [W.HDC, W.DWORD], W.DWORD),
        (g, 'SetBkMode', [W.HDC, C.c_int], C.c_int),
        (u, 'DrawTextW', [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.RECT), W.UINT], C.c_int),
        (g, 'RoundRect', [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int], W.BOOL),
        (g, 'Rectangle', [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int], W.BOOL),
        (g, 'CreateCompatibleDC', [W.HDC], W.HDC),
        (g, 'CreateDIBSection', [W.HDC, C.POINTER(BITMAPINFO), W.UINT,
             C.POINTER(C.c_void_p), W.HANDLE, W.DWORD], W.HBITMAP),
        (g, 'GetStockObject', [C.c_int], W.HANDLE),
        (g, 'AddFontResourceExW', [W.LPCWSTR, W.DWORD, C.c_void_p], C.c_int),
    )
    for dll, name, args, result in declarations:
        fn = getattr(dll, name)
        fn.argtypes = args
        fn.restype = result
    return u, k, g


def sdf_round(x, y, left, top, right, bottom, radius):
    """Signed distance to a rounded rectangle (negative inside)."""
    cx = left + radius; cy = top + radius
    ex = right - radius; ey = bottom - radius
    dx = cx - x if x < cx else (x - ex if x > ex else 0.0)
    dy = cy - y if y < cy else (y - ey if y > ey else 0.0)
    return (dx * dx + dy * dy) ** 0.5 - radius


class Skin:
    """32-bit DIB card: rounded corners, per-pixel alpha and a soft shadow."""

    MARGIN = 18

    def __init__(self, ui, card_w, card_h, radius=14, blur=16, dy=6, strength=0.45):
        self.ui = ui
        self.card_w, self.card_h = card_w, card_h
        m = self.MARGIN
        self.w, self.h = card_w + 2 * m, card_h + 2 * m
        self.rect = (m, m, m + card_w, m + card_h)
        self.radius = radius
        self.bmp, self.dc, self.bits = ui.make_dib(self.w, self.h)
        self.alpha, self.edges = self.build_alpha(radius, blur, dy, strength)

    def build_alpha(self, radius, blur, dy, strength):
        w, h = self.w, self.h
        left, top, right, bottom = self.rect
        alpha = bytearray(w * h)
        edges = []
        inner = (left + radius, top + radius, right - radius, bottom - radius)
        for y in range(h):
            base = y * w
            row_inside = (inner[1] <= y <= inner[3]) if radius else True
            for x in range(w):
                if row_inside and inner[0] <= x <= inner[2]:
                    alpha[base + x] = 255
                    continue
                d = sdf_round(x + 0.5, y + 0.5, left, top, right, bottom, radius)
                cov = 0.0 if d >= 0.5 else (1.0 if d <= -0.5 else 0.5 - d)
                sd = sdf_round(x + 0.5, y + 0.5 - dy, left, top, right, bottom, radius)
                sh = 0.0 if sd <= 0 else max(0.0, 1.0 - sd / blur) ** 2 * strength
                a = int(round(max(cov, sh) * 255))
                if a:
                    alpha[base + x] = a
                    if a < 255:
                        edges.append((base + x, a))
        return alpha, edges

    def begin(self):
        C.memset(self.bits, 0, self.w * self.h * 4)
        return self.dc

    def end(self, hwnd, x, y):
        u = self.ui.u
        raw = bytearray(C.string_at(self.bits, self.w * self.h * 4))
        raw[3::4] = self.alpha
        for off, a in self.edges:
            i = off * 4
            raw[i] = raw[i] * a // 255
            raw[i + 1] = raw[i + 1] * a // 255
            raw[i + 2] = raw[i + 2] * a // 255
        C.memmove(self.bits, bytes(raw), len(raw))
        screen = u.GetDC(0)
        try:
            dst = W.POINT(x, y); size = W.SIZE(self.w, self.h); src = W.POINT(0, 0)
            blend = BLENDFUNCTION(0, 0, 255, 1)
            if not u.UpdateLayeredWindow(hwnd, screen, C.byref(dst), C.byref(size),
                                         self.dc, C.byref(src), 0, C.byref(blend), 2):
                raise ValueError('UpdateLayeredWindow failed (%d)' % C.get_last_error())
        finally:
            u.ReleaseDC(0, screen)


class InspectorUI:
    """Apple-style floating cards: click a unit -> a small card appears next to
    the cursor; click a value -> type a number -> Enter writes (local only)."""

    ROWS = (
        ('soldiers', '兵力', 'unit'),
        ('rice', '兵粮', 'unit'),
        ('morale', '士气', 'unit'),
        ('training', '训练', 'unit'),
        ('lead', '统率', 'general'),
        ('war', '武力', 'general'),
        ('intel', '智力', 'general'),
        ('pol', '政治', 'general'),
        ('cha', '魅力', 'general'),
    )
    CARD_W = 300
    PAD = 16

    @staticmethod
    def _trace(step):
        print('[insp] ' + step, file=sys.stderr, flush=True)

    def __init__(self, reader, emit, u=None, k=None, g=None):
        self._trace('ui init start')
        self.reader, self.emit = reader, emit
        self.u, self.k, self.g = (u, k, g) if u else native_api()
        self.armed = False; self.last_geometry = None; self.selected = None
        self.main = self.overlay = self.card = 0
        self.closed = False; self.hotkey = False
        self.skin_main = None; self.skin_card = None
        self.main_pos = [1100, 80]; self.card_pos = [0, 0]
        self.card_data = None; self.values = {}; self.blade = None
        self.layout = None; self.main_layout = None
        self.hover = None; self.edit = None; self.caret_on = True; self.demo = False
        self.overlay_block = None; self.overlay_shown = None
        self.drag = None; self.status = ('点「开始查阅」，再点地图上的部队。', 'dim')
        self._fonts = {}; self._brushes = {}; self._pens = {}
        self.instance = self.k.GetModuleHandleW(None)
        self.callback_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self.callback = self.callback_type(self.window_proc)
        class WNDCLASS(C.Structure):
            _fields_ = [('style', W.UINT), ('lpfnWndProc', self.callback_type),
                        ('cbClsExtra', C.c_int), ('cbWndExtra', C.c_int),
                        ('hInstance', W.HINSTANCE), ('hIcon', W.HANDLE),
                        ('hCursor', W.HANDLE), ('hbrBackground', W.HANDLE),
                        ('lpszMenuName', W.LPCWSTR), ('lpszClassName', W.LPCWSTR)]
        self.class_name = 'P53CardInspector_' + str(os.getpid())
        cls = WNDCLASS(); cls.lpfnWndProc = self.callback; cls.hInstance = self.instance
        cls.hCursor = self.u.LoadCursorW(None, C.c_void_p(32515))
        cls.lpszClassName = self.class_name
        if not self.u.RegisterClassW(C.byref(cls)):
            raise C.WinError(C.get_last_error())
        self._trace('class registered')
        self.load_font()
        self._trace('font loaded')
        self.main = self.create(0x80088, self.class_name, 'Fengye unit card',
                                0x80000000, self.main_pos[0], self.main_pos[1], 10, 10)
        self.overlay = self.create(0x08080080, self.class_name, 'P53 only · mouse consumer',
                                   0x80000000, 0, 0, 1, 1)
        if not self.u.SetLayeredWindowAttributes(self.overlay, 0, 24, 2):
            raise C.WinError(C.get_last_error())
        self.card = self.create(0x80088, self.class_name, 'Fengye unit card popup',
                                0x80000000, 0, 0, 10, 10)
        self._trace('windows created')
        self.skin_main = Skin(self, 272, 120)
        self._trace('skin main built')
        self.skin_card = Skin(self, self.CARD_W, self.card_height(), radius=14,
                              blur=20, dy=7, strength=0.5)
        self._trace('skin card built')
        self.main_layout = self.build_main_layout()
        self.paint_main()
        self._trace('main painted')
        self.u.ShowWindow(self.main, 5)
        self._trace('main shown')
        self.u.ShowWindow(self.card, 0)
        self.hotkey = bool(self.u.RegisterHotKey(self.main, 1, 0x4006, ord('I')))
        if not self.u.SetTimer(self.main, 1, 250, None):
            raise C.WinError(C.get_last_error())
        self._trace('timer/hotkey done')
        self.emit(dict(kind='inspector_opened', readonly=False, editable=True,
                       write_scope='shadow client pid only', armed=False,
                       identity=reader.identity, hotkey_registered=self.hotkey,
                       ui='apple-card'))

    # ---------- fonts / gdi ----------
    def load_font(self):
        for path in (r'Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\fonts\Hiragino Sans GB.ttc',):
            try:
                self.g.AddFontResourceExW(path, 0x10, None)
            except BaseException:
                pass

    def font(self, size=13, weight=400):
        key = (size, weight)
        if key not in self._fonts:
            self._fonts[key] = self.g.CreateFontW(-size, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0,
                                                  'PingFang SC')
        return self._fonts[key]

    def brush(self, color):
        if color not in self._brushes:
            self._brushes[color] = self.g.CreateSolidBrush(color)
        return self._brushes[color]

    def pen(self, color):
        if color not in self._pens:
            self._pens[color] = self.g.CreatePen(0, 1, color)
        return self._pens[color]

    def fill(self, dc, x, y, w, h, color, radius=0):
        old_brush = self.g.SelectObject(dc, self.brush(color))
        old_pen = self.g.SelectObject(dc, self.g.GetStockObject(8))
        if radius:
            self.g.RoundRect(dc, x, y, x + w, y + h, radius * 2, radius * 2)
        else:
            self.g.Rectangle(dc, x, y, x + w + 1, y + h + 1)
        self.g.SelectObject(dc, old_brush); self.g.SelectObject(dc, old_pen)

    def stroke(self, dc, x, y, w, h, color, radius=0):
        old_brush = self.g.SelectObject(dc, self.g.GetStockObject(5))
        old_pen = self.g.SelectObject(dc, self.pen(color))
        if radius:
            self.g.RoundRect(dc, x, y, x + w, y + h, radius * 2, radius * 2)
        else:
            self.g.Rectangle(dc, x, y, x + w, y + h)
        self.g.SelectObject(dc, old_brush); self.g.SelectObject(dc, old_pen)

    def text(self, dc, value, x, y, w, h, color, font, align=0):
        self.g.SetTextColor(dc, color)
        self.g.SetBkMode(dc, 1)
        old = self.g.SelectObject(dc, font)
        fmt = 0x00000024 | 0x00000800  # SINGLELINE | VCENTER | NOPREFIX
        if align == 1: fmt |= 0x00000002
        elif align == 2: fmt |= 0x00000001
        rect = W.RECT(int(x), int(y), int(x + w), int(y + h))
        self.u.DrawTextW(dc, value, -1, C.byref(rect), fmt)
        self.g.SelectObject(dc, old)

    def make_dib(self, w, h):
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bits = C.c_void_p()
        screen = self.u.GetDC(0)
        try:
            bmp = self.g.CreateDIBSection(screen, C.byref(bmi), 0, C.byref(bits), None, 0)
        finally:
            self.u.ReleaseDC(0, screen)
        if not bmp or not bits.value:
            raise C.WinError(C.get_last_error())
        dc = self.g.CreateCompatibleDC(0)
        self.g.SelectObject(dc, bmp)
        return bmp, dc, bits

    def create(self, extended, cls, title, style, x, y, width, height, parent=0, ident=0):
        hwnd = self.u.CreateWindowExW(extended, cls, title, style, x, y, width, height,
                                      parent, ident, self.instance, None)
        if not hwnd:
            raise C.WinError(C.get_last_error())
        return int(hwnd)

    # ---------- layout ----------
    def card_height(self):
        return 454

    def build_main_layout(self):
        m = Skin.MARGIN
        return dict(
            close=(m + 272 - 38, m + 12, 24, 24),
            button=(m + 16, m + 44, 272 - 32, 34),
            status=(m + 16, m + 88, 272 - 32, 16),
            tag=(m + 272 - 84, m + 88, 68, 16),
        )

    def build_card_layout(self):
        m = Skin.MARGIN
        x0 = m + self.PAD
        inner = self.CARD_W - 2 * self.PAD
        y = m + 16
        lay = dict(items=[], rows=[])
        lay['title'] = (x0, y, inner - 30, 24); y += 24
        lay['sub'] = (x0, y, inner, 16); y += 16 + 12
        lay['close'] = (m + self.CARD_W - 40, m + 14, 24, 24)
        lay['head'] = (m, m, self.CARD_W)
        for group, label in (('unit', '部队'), ('general', '武将')):
            lay['items'].append(dict(kind='section', group=group,
                                     rect=(x0, y, inner, 16), label=label))
            y += 16
            for key, name, scope in self.ROWS:
                if scope != group:
                    continue
                row = dict(kind='row', key=key, label=name, scope=scope,
                           rect=(x0, y, inner, 28))
                lay['rows'].append(row); lay['items'].append(row)
                y += 28
            y += 8
        lay['undo'] = (x0, y + 2, 104, 26)
        lay['done'] = (x0 + inner - 64, y + 2, 64, 26)
        lay['status'] = (x0, y + 32, inner, 14)
        return lay

    # ---------- paint ----------
    def backdrop(self, dc, skin):
        """Calm vertical gradient slab (drawn as bands; no gradients in GDI)."""
        left, top, width, height = skin.rect[0], skin.rect[1], skin.card_w, skin.card_h
        bands = 12
        for i in range(bands):
            y0 = top + height * i // bands
            y1 = top + height * (i + 1) // bands
            t = i / float(bands - 1)
            color = rgb(int(26 - 9 * t), int(30 - 10 * t), int(37 - 12 * t))
            if i == 0:
                self.fill(dc, left, y0, width, y1 - y0 + 14, color, radius=14)
                self.fill(dc, left, y0 + 14, width, y1 - y0, color)
            elif i == bands - 1:
                self.fill(dc, left, y0, width, y1 - y0, color)
                self.fill(dc, left, y1 - 14, width, 14, color, radius=14)
            else:
                self.fill(dc, left, y0, width, y1 - y0, color)

    def paint_main(self):
        skin = self.skin_main
        if not skin: return
        dc = skin.begin(); m = Skin.MARGIN
        self.backdrop(dc, skin)
        self.stroke(dc, skin.rect[0], skin.rect[1], skin.card_w, skin.card_h, T.BORDER, radius=14)
        self.text(dc, '部队查阅', m + 16, m + 12, 170, 24, T.TEXT, self.font(16, 600))
        cx, cy, cw, ch = self.main_layout['close']
        self.text(dc, '×', cx, cy, cw, ch, T.SUB, self.font(15), 2)
        bx, by, bw, bh = self.main_layout['button']
        hot = self.hover == 'main-button'
        if self.armed:
            base = rgb(238, 84, 76) if hot else rgb(226, 72, 64)
            edge = rgb(255, 132, 124)
        else:
            base = rgb(74, 141, 252) if hot else rgb(63, 130, 245)
            edge = rgb(126, 175, 255)
        self.fill(dc, bx, by, bw, bh, base, radius=10)
        self.fill(dc, bx + 12, by + 1, bw - 24, 1, edge)
        self.text(dc, '停止查阅' if self.armed else '开始查阅', bx, by, bw, bh,
                  T.TEXT, self.font(14, 600), 2)
        sx, sy, sw, sh = self.main_layout['status']
        text, kind = self.status
        color = {'dim': T.DIM, 'ok': T.GREEN, 'bad': T.RED, 'accent': T.ACCENT}[kind]
        dot = {'dim': T.DIM, 'ok': T.GREEN, 'bad': T.RED, 'accent': T.ACCENT}[kind]
        self.fill(dc, sx, sy + sh // 2 - 2, 4, 4, dot, radius=2)
        self.text(dc, text, sx + 10, sy, sw - 88, sh, color, self.font(10))
        tx, ty, tw, th = self.main_layout['tag']
        self.text(dc, '仅本机', tx, ty, tw, th, T.DIM, self.font(10), 1)
        skin.end(self.main, self.main_pos[0], self.main_pos[1])
        self.dump_main_bitmap()

    def paint_card(self):
        skin = self.skin_card
        if not skin or not self.card_data: return
        lay = self.layout
        dc = skin.begin(); m = Skin.MARGIN
        self.backdrop(dc, skin)
        self.stroke(dc, skin.rect[0], skin.rect[1], skin.card_w, skin.card_h, T.BORDER, radius=14)
        item = self.card_data
        # header
        self.text(dc, str(item['kind']), *lay['title'], T.TEXT, self.font(17, 600))
        self.text(dc, '#%s' % item['unit_id'], lay['title'][0], lay['title'][1],
                  lay['title'][2], lay['title'][3], T.DIM, self.font(12, 600), 1)
        self.text(dc, '势力 %s   ·   格 %s' % (item['owner'], item['xy']), *lay['sub'],
                  T.SUB, self.font(11))
        self.text(dc, '×', *lay['close'], T.SUB, self.font(14), 2)
        self.fill(dc, m + self.PAD, m + 76, self.CARD_W - 2 * self.PAD, 1, T.HAIR)
        for entry in lay['items']:
            x, y, w, h = entry['rect']
            if entry['kind'] == 'section':
                self.text(dc, entry['label'], x, y, w, h, T.DIM, self.font(10, 600))
                if entry['group'] == 'unit':
                    self.text(dc, '点数值即可修改', x + w - 96, y, 96, h, T.DIM,
                              self.font(9), 1)
                if entry['group'] == 'general' and self.blade is not None:
                    name = (self.card_data or {}).get('general_name') or ''
                    label = ('%s  统武 %s' % (name, self.blade)) if name else ('统武 %s' % self.blade)
                    chip_w = 22 + len(label) * 11
                    self.fill(dc, x + w - chip_w, y - 2, chip_w, 20, T.ACCENT_SOFT, radius=6)
                    self.text(dc, label, x + w - chip_w, y - 2, chip_w, 20, T.ACCENT,
                              self.font(11, 600), 2)
                continue
            key = entry['key']
            info = self.values.get(key) or {}
            active = self.edit is not None and self.edit['index'] == lay['rows'].index(entry)
            if active:
                self.fill(dc, x - 6, y + 2, w + 12, h - 4, T.FIELD, radius=7)
                self.stroke(dc, x - 6, y + 2, w + 12, h - 4, T.BLUE, radius=7)
                text = self.edit['text'] if self.caret_on else self.edit['text'] + ' '
                self.text(dc, text, x + w - 110, y, 104, h, T.TEXT, self.font(14, 600), 1)
                self.text(dc, '输入数字 · 回车确认 · Esc 取消', x + 4, y, w - 120, h,
                          T.DIM, self.font(9))
                continue
            hovered = self.hover == ('row', key) and info.get('editable')
            if self._row_has_next(lay, entry):
                self.fill(dc, x + 2, y + h - 1, w - 4, 1, T.HAIR)
            self.text(dc, entry['label'], x, y, w - 130, h, T.LABEL, self.font(12))
            value = info.get('value')
            chip_x, chip_w = x + w - 116, 116
            if info.get('editable'):
                self.fill(dc, chip_x, y + 2, chip_w, h - 4,
                          rgb(34, 42, 54) if hovered else rgb(26, 31, 39), radius=6)
                if hovered:
                    self.stroke(dc, chip_x, y + 2, chip_w, h - 4, T.BLUE, radius=6)
            color = T.TEXT if info.get('editable') else T.DIM
            self.text(dc, '—' if value is None else str(value), chip_x + 8, y, chip_w - 16, h,
                      color, self.font(14, 600), 1)
        ux, uy, uw, uh = lay['undo']
        has_undo = getattr(self.reader, 'pending_revert', None) is not None
        if self.hover == 'undo' and has_undo:
            self.fill(dc, ux, uy, uw, uh, T.HOVER, radius=7)
        self.text(dc, '还原上一笔', ux, uy, uw, uh,
                  T.LABEL if has_undo else T.DIM, self.font(12, 600), 2)
        dx, dy, dw, dh = lay['done']
        self.fill(dc, dx, dy, dw, dh,
                  T.BTN_HOVER if self.hover == 'done' else T.BTN, radius=7)
        self.text(dc, '完成', dx, dy, dw, dh, T.TEXT, self.font(12, 600), 2)
        text, kind = self.status
        color = {'dim': T.DIM, 'ok': T.GREEN, 'bad': T.RED, 'accent': T.ACCENT}[kind]
        self.text(dc, text, *lay['status'], color, self.font(10))
        skin.end(self.card, self.card_pos[0], self.card_pos[1])
        self.dump_bitmap()

    def dump_bitmap(self):
        prefix = os.environ.get('SGI_P53_DUMP')
        if not prefix or not self.skin_card:
            return
        try:
            skin = self.skin_card
            raw = bytes(C.string_at(skin.bits, skin.w * skin.h * 4))
            with open(prefix + '.raw', 'wb') as handle:
                handle.write(raw)
            with open(prefix + '.json', 'w', encoding='utf-8') as handle:
                json.dump(dict(w=skin.w, h=skin.h, margin=Skin.MARGIN), handle)
        except BaseException:
            pass

    # ---------- state ----------
    def set_status(self, text, kind='dim'):
        self.status = (text, kind)
        self.paint_main()
        if self.card_data:
            self.paint_card()

    def set_armed(self, value):
        if self.demo:
            self.set_status('演示模式：只展示样子，不连接游戏', 'accent')
            return
        self.armed = value
        if not value:
            self.u.ShowWindow(self.overlay, 0); self.last_geometry = None
            self.hide_card()
        self.emit(dict(kind='inspector_armed', armed=value, editable=True))
        self.paint_main()
        if value:
            self.set_status('查阅中 · 点地图上的部队', 'accent')
            self.update_overlay()
        else:
            self.set_status('已停止 · 点「开始查阅」', 'dim')

    def update_overlay(self):
        if not self.armed or self.closed:
            return
        try:
            ctx = self.reader.geometry(); hwnd = ctx['hwnd']
            owner = W.DWORD()
            if (not self.u.IsWindow(hwnd) or not self.u.IsWindowVisible(hwnd) or
                    not self.u.GetWindowThreadProcessId(hwnd, C.byref(owner)) or
                    owner.value != self.reader.identity['pid']):
                raise ValueError('map HWND/process binding changed')
            main = self.u.GetAncestor(hwnd, 2) or hwnd
            foreground = int(self.u.GetForegroundWindow() or 0)
            allowed = (main, self.main, self.overlay, self.card)
            blocked = None
            if self.u.IsIconic(main):
                blocked = 'game minimized'
            elif foreground not in allowed:
                blocked = 'game not foreground'
            elif ctx['mode'] == 0:
                blocked = 'no map view'
            elif not 0 <= ctx['phase'] <= 7:
                blocked = 'phase %r' % ctx['phase']
            elif ctx['modal']:
                blocked = 'modal dialog open'
            if blocked:
                if getattr(self, 'overlay_block', None) != blocked:
                    self.overlay_block = blocked
                    self.emit(dict(kind='overlay_blocked', reason=blocked,
                                   mode=ctx['mode'], phase=ctx['phase'],
                                   modal=ctx['modal'], widgets=ctx['widgets']))
                self.u.ShowWindow(self.overlay, 0); self.last_geometry = None; return
            if getattr(self, 'overlay_block', None) is not None:
                self.overlay_block = None
            rect, point = W.RECT(), W.POINT(0, 0)
            if (not self.u.GetClientRect(hwnd, C.byref(rect)) or
                    not self.u.ClientToScreen(hwnd, C.byref(point)) or
                    rect.right <= 0 or rect.bottom <= 0):
                raise ValueError('map window geometry unavailable')
            self.last_geometry = dict(context=ctx, origin=[point.x, point.y],
                                      size=[rect.right, rect.bottom])
            self.u.SetWindowPos(self.overlay, W.HWND(-1), point.x, point.y,
                                rect.right, rect.bottom, 0x50)
            if not getattr(self, 'overlay_shown', None):
                self.overlay_shown = dict(origin=[point.x, point.y],
                                          size=[rect.right, rect.bottom],
                                          mode=ctx['mode'], phase=ctx['phase'])
                self.emit(dict(kind='overlay_shown', **self.overlay_shown))
            self.u.SetWindowPos(self.main, W.HWND(-1), 0, 0, 0, 0, 0x13)
            if self.card_data:
                self.u.SetWindowPos(self.card, W.HWND(-1), 0, 0, 0, 0, 0x13)
        except (ValueError, OSError) as exc:
            self.set_armed(False)
            self.set_status('查阅已停止：%s' % exc, 'bad')
            self.emit(dict(kind='inspector_error', error=str(exc)))

    def target_alive(self):
        if self.demo:
            return True
        try:
            self.reader.validate()
            return True
        except BaseException:
            return False

    def click(self, x, y):
        if not self.armed or not self.last_geometry:
            return
        if not self.target_alive():
            self.set_armed(False)
            self.set_status('风夜客户端已消失/卡死：请重开一局再武装', 'bad')
            self.hide_card()
            return
        before = self.last_geometry
        self.update_overlay()
        if (not self.last_geometry or self.last_geometry['origin'] != before['origin'] or
                self.last_geometry['size'] != before['size'] or
                geometry_key(self.last_geometry['context']) != geometry_key(before['context'])):
            raise ValueError('map/camera moved; click again')
        if not (0 <= x < before['size'][0] and 0 <= y < before['size'][1]):
            return
        snapshot = self.reader.capture()
        if geometry_key(snapshot['context']) != geometry_key(before['context']):
            raise ValueError('camera/phase changed; click again')
        rows = hit_units(snapshot, [x, y])
        if not rows:
            self.hide_card()
            self.set_status('这一格没有部队，换个格子点', 'dim')
            self.emit(dict(kind='inspector_miss', client_xy=[x, y])); return
        rows.sort(key=lambda r: (r['owner_raw'], r['unit_id'], r['address']))
        index = 0
        keys = [(r['address'], r['unit_id']) for r in rows]
        if self.selected and self.selected[1] in keys:
            index = (keys.index(self.selected[1]) + 1) % len(rows)
        result = self.reader.inspect(snapshot, rows[index])
        result['hit'] = dict(client_xy=[x, y], co_located=len(rows), selected_index=index)
        self.selected = (snapshot, (rows[index]['address'], rows[index]['unit_id']), rows[index])
        self.emit(dict(kind='unit_inspection', **result))
        self.show_card(result, rows[index], x, y, len(rows))

    def show_card(self, result, row, client_x, client_y, co_located):
        unit = result['unit']
        address = unit['address']
        address = int(address, 16) if isinstance(address, str) else int(address)
        gid = next((g for g in (unit.get('general_ids') or []) if g is not None), None)
        general = None
        for entry in (result.get('generals') or []):
            if entry and entry.get('id') == gid:
                general = entry
                break
        self.card_data = dict(address=address, unit_id=unit['unit_id'], kind=unit['kind'],
                              owner=unit.get('owner_name') or unit.get('owner_raw'),
                              xy=unit.get('world_xy_raw'),
                              general_id=gid, general_name=(general or {}).get('name') or '',
                              co_located=co_located)
        self.layout = self.build_card_layout()
        self.refresh_values()
        ox, oy = self.last_geometry['origin']
        screen = W.POINT(client_x + ox + 26, client_y + oy + 18)
        sw = self.u.GetSystemMetrics(0); sh = self.u.GetSystemMetrics(1)
        m = Skin.MARGIN
        x = min(max(0, screen.x), max(0, sw - self.skin_card.w))
        y = min(max(0, screen.y), max(0, sh - self.skin_card.h))
        self.card_pos = [x - m, y - m]
        self.edit = None
        self.paint_card()
        self.u.ShowWindow(self.card, 5)
        self.u.SetWindowPos(self.card, W.HWND(-1), 0, 0, 0, 0, 0x13)
        self.set_status('已读出 · 点数值即可修改', 'accent')

    def show_demo_card(self):
        self.card_data = dict(address=0, unit_id=17, kind='铁骑兵', owner=13,
                              xy=[23, 41], general_id=588, general_name='关羽', co_located=1)
        self.layout = self.build_card_layout()
        self.refresh_values()
        self.card_pos = [self.main_pos[0] + 36, self.main_pos[1] + 168]
        if self.card_pos[1] + self.skin_card.h > self.u.GetSystemMetrics(1):
            self.card_pos[1] = max(0, self.main_pos[1] - self.skin_card.h - 16)
        self.paint_card()
        self.u.ShowWindow(self.card, 5)
        self.u.SetWindowPos(self.card, W.HWND(-1), 0, 0, 0, 0, 0x13)
        self.set_status('演示：点数值可改（示例数据，不写游戏）', 'accent')

    @staticmethod
    def _row_has_next(lay, entry):
        rows = lay['rows']
        index = rows.index(entry)
        if index + 1 >= len(rows):
            return False
        return rows[index + 1]['scope'] == entry['scope']

    def dump_main_bitmap(self):
        prefix = os.environ.get('SGI_P53_DUMP')
        if not prefix or not self.skin_main:
            return
        try:
            skin = self.skin_main
            raw = bytes(C.string_at(skin.bits, skin.w * skin.h * 4))
            with open(prefix + '-main.raw', 'wb') as handle:
                handle.write(raw)
            with open(prefix + '-main.json', 'w', encoding='utf-8') as handle:
                json.dump(dict(w=skin.w, h=skin.h, margin=Skin.MARGIN), handle)
        except BaseException:
            pass

    def hide_card(self):
        self.card_data = None; self.edit = None
        if self.card:
            self.u.ShowWindow(self.card, 0)

    def refresh_values(self):
        values = {}
        data = self.card_data
        for key, label, scope in self.ROWS:
            values[key] = dict(value=None, editable=False, scope=scope, label=label)
        if data:
            for key, label, scope in self.ROWS:
                if scope != 'unit':
                    continue
                try:
                    values[key] = dict(value=self.reader.unit_field(data['address'], key),
                                       editable=True, scope='unit', label=label)
                except BaseException:
                    pass
            stats = None
            if data.get('general_id') is not None:
                try:
                    stats = self.reader.general_stats(data['general_id'])
                except BaseException:
                    stats = None
            if stats:
                for key, label, scope in self.ROWS:
                    if scope != 'general':
                        continue
                    values[key] = dict(value=stats['values'][key], editable=True,
                                       scope='general', label=label)
                self.blade = stats['blade_total']
            else:
                self.blade = None
        self.values = values

    # ---------- interaction ----------
    def start_edit(self, key):
        info = self.values.get(key) or {}
        if not info.get('editable'):
            self.set_status('这一项读不到（武将不在这支部队或对象已变）', 'bad'); return
        index = next(i for i, r in enumerate(self.layout['rows']) if r['key'] == key)
        self.edit = dict(index=index, key=key, text=str(info['value']), fresh=True)
        self.caret_on = True
        self.status = ('输入新数值 · 回车写入 · Esc 取消', 'accent')
        self.paint_card()

    def cancel_edit(self):
        if not self.edit: return
        self.edit = None
        self.set_status('已取消', 'dim')
        self.paint_card()

    def commit_edit(self):
        if not self.edit: return
        key = self.edit['key']; text = self.edit['text'].strip()
        self.edit = None
        if not text:
            self.set_status('没有输入数值', 'dim'); self.paint_card(); return
        try:
            value = int(text, 10)
        except ValueError:
            self.set_status('只能填整数', 'bad'); self.paint_card(); return
        data = self.card_data
        try:
            if key in [r[0] for r in self.ROWS if r[2] == 'unit']:
                record = self.reader.edit_unit(data['address'], key, value)
            else:
                if data.get('general_id') is None:
                    raise ValueError('没有读到这支部队的武将ID')
                record = self.reader.edit_general(data['general_id'], key, value)
        except BaseException as error:
            self.emit(dict(kind='edit_error', error=str(error)))
            self.set_status('写入失败：%s' % error, 'bad'); self.paint_card(); return
        self.emit(record)
        if record.get('blade_total_after') is not None and record['blade_total_after'] != record['blade_total_before']:
            self.set_status('%s %s → %s（统武 %s → %s）' % (
                record['label'], record['before'], record['after'],
                record['blade_total_before'], record['blade_total_after']), 'ok')
        else:
            self.set_status('%s %s → %s（仅本机）' % (record['label'], record['before'],
                                                   record['after']), 'ok')
        self.refresh_values(); self.paint_card()

    def revert_last(self):
        try:
            record = self.reader.revert_pending()
        except BaseException as error:
            self.set_status('没有可还原的写入', 'dim'); self.paint_card(); return
        self.emit(record)
        self.set_status('已还原 %s → %s' % (record['label'], record['after']), 'ok')
        self.refresh_values(); self.paint_card()

    def hit(self, lay, x, y, key):
        if not lay: return False
        box = lay.get(key)
        if not box: return False
        bx, by, bw, bh = box
        return bx <= x <= bx + bw and by <= y <= by + bh

    def card_hit(self, x, y):
        lay = self.layout
        if not lay: return None
        m = Skin.MARGIN
        if not (m <= x <= m + self.CARD_W): return None
        if self.hit(lay, x, y, 'close'): return ('close', None)
        for row in lay['rows']:
            rx, ry, rw, rh = row['rect']
            if rx - 8 <= x <= rx + rw + 8 and ry + 2 <= y <= ry + rh - 2:
                return ('row', row['key'])
        if self.hit(lay, x, y, 'undo'): return ('undo', None)
        if self.hit(lay, x, y, 'done'): return ('done', None)
        return None

    def in_title(self, x, y):
        m = Skin.MARGIN
        for name in ('title', 'sub'):
            box = (self.layout or {}).get(name)
            if box and box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]:
                return True
        return m <= y <= m + 14

    # ---------- messages ----------
    def xy(self, lp):
        return C.c_short(lp & 0xffff).value, C.c_short((lp >> 16) & 0xffff).value

    def window_proc(self, hwnd, msg, wp, lp):
        try:
            if hwnd == self.overlay:
                if msg == 0x21: return 3
                if msg == 0x201:
                    x, y = self.xy(lp); self.click(x, y); return 0
                if msg in (0x202, 0x203, 0x204, 0x205, 0x206, 0x207, 0x208, 0x209, 0x20a, 0x20e):
                    return 0
                if msg == 0x84: return 1
            if hwnd == self.main:
                if msg == 0x312: self.set_armed(not self.armed); return 0
                if msg == 0x200:
                    x, y = self.xy(lp)
                    hot = 'main-button' if self.hit(self.main_layout, x, y, 'button') else None
                    if hot != self.hover:
                        self.hover = hot; self.paint_main()
                    return 0
                if msg == 0x201:
                    x, y = self.xy(lp)
                    if self.hit(self.main_layout, x, y, 'close'):
                        self.close(); return 0
                    if self.hit(self.main_layout, x, y, 'button'):
                        self.set_armed(not self.armed); return 0
                    self.begin_drag(self.main, x, y); return 0
                if msg == 0x202: self.end_drag(); return 0
                if msg == 0x113: return 0
            if hwnd == self.card:
                if msg == 0x200:
                    x, y = self.xy(lp)
                    target = self.card_hit(x, y)
                    hot = ('row', target[1]) if target and target[0] == 'row' else (
                        target[0] if target else None)
                    if hot != self.hover:
                        self.hover = hot; self.paint_card()
                    self.u.SetCursor(self.u.LoadCursorW(None, C.c_void_p(32649)))
                    return 0
                if msg == 0x201:
                    x, y = self.xy(lp)
                    target = self.card_hit(x, y)
                    if target and target[0] == 'close':
                        self.hide_card(); self.set_status('卡片已关闭', 'dim'); return 0
                    if target and target[0] == 'undo':
                        self.revert_last(); return 0
                    if target and target[0] == 'done':
                        self.hide_card(); self.set_status('卡片已关闭', 'dim'); return 0
                    if target and target[0] == 'row':
                        if not (self.edit and self.edit['key'] == target[1]):
                            self.start_edit(target[1])
                        return 0
                    if self.in_title(x, y):
                        self.end_edit_if_open()
                        self.begin_drag(self.card, x, y)
                        return 0
                    return 0
                if msg == 0x202:
                    self.end_drag(); return 0
                if msg == 0x100 and wp == 27:
                    self.end_edit_if_open(); self.hide_card(); return 0
                if msg == 0x102:
                    if self.edit is None: return 0
                    ch = wp & 0xffff
                    if 0x30 <= ch <= 0x39:
                        if self.edit.get('fresh'):
                            self.edit['text'] = ''; self.edit['fresh'] = False
                        if len(self.edit['text']) < 7:
                            self.edit['text'] += chr(ch)
                        self.caret_on = True; self.paint_card()
                    return 0
                if msg == 0x100:
                    if self.edit is None: return 0
                    if wp == 0x0D: self.commit_edit(); return 0
                    if wp == 0x1B: self.cancel_edit(); return 0
                    if wp == 0x08:
                        text = self.edit['text']
                        self.edit['text'] = '' if self.edit.get('fresh') else text[:-1]
                        self.edit['fresh'] = False
                        self.caret_on = True; self.paint_card(); return 0
                    return 0
                if msg in (0x113, 0x0f): return 0
            if msg == 0x0f: return 0
            if msg == 0x10:
                self.close(); return 0
            if msg == 0x113 and self.closed:
                pass
        except BaseException as exc:
            try:
                self.emit(dict(kind='inspector_error', error=str(exc)))
            except BaseException:
                pass
            return 0
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def end_edit_if_open(self):
        if self.edit:
            self.edit = None
            self.paint_card()

    def begin_drag(self, hwnd, x, y):
        point = W.POINT()
        self.u.GetCursorPos(C.byref(point))
        self.drag = dict(hwnd=hwnd, cursor=(point.x, point.y),
                         win=list(self.main_pos if hwnd == self.main else self.card_pos))
        self.u.SetCapture(hwnd)

    def end_drag(self):
        if self.drag:
            self.u.ReleaseCapture()
            self.drag = None

    def drag_to(self):
        if not self.drag: return
        point = W.POINT(); self.u.GetCursorPos(C.byref(point))
        dx = point.x - self.drag['cursor'][0]; dy = point.y - self.drag['cursor'][1]
        pos = [self.drag['win'][0] + dx, self.drag['win'][1] + dy]
        if self.drag['hwnd'] == self.main:
            self.main_pos = pos
            self.paint_main()
        else:
            self.card_pos = pos
            self.paint_card()

    def loop(self):
        message = W.MSG()
        while True:
            rc = self.u.GetMessageW(C.byref(message), None, 0, 0)
            if rc == 0: return
            if rc == -1: raise C.WinError(C.get_last_error())
            if message.message == 0x200 and self.drag:
                self.drag_to()
            if message.message == 0x113:
                self.update_overlay()
                if self.edit:
                    self.caret_on = not self.caret_on
                    self.paint_card()
            self.u.TranslateMessage(C.byref(message))
            self.u.DispatchMessageW(C.byref(message))

    def close(self):
        if self.closed: return
        self.set_armed(False); self.closed = True
        if self.main: self.u.KillTimer(self.main, 1)
        if self.hotkey: self.u.UnregisterHotKey(self.main, 1)
        if self.card: self.u.DestroyWindow(self.card)
        if self.overlay: self.u.DestroyWindow(self.overlay)
        if self.main: self.u.DestroyWindow(self.main)
        self.emit(dict(kind='inspector_closed', editable=True))
        self.u.PostQuitMessage(0)


class DemoReader:
    """Renders the card with sample values; never opens or writes any process."""

    identity = dict(pid=0, path='demo', sanpk_sha256='demo', creation_filetime=0,
                    write_scope='none (demo)')
    pending_revert = None

    def __init__(self):
        self.state = dict(soldiers=8600, rice=43210, morale=84, training=62,
                          lead=82, war=91, intel=64, pol=55, cha=70)

    def unit_field(self, address, key):
        return self.state[key]

    def general_stats(self, gid):
        values = {k: self.state[k] for k in ('lead', 'war', 'intel', 'pol', 'cha')}
        return dict(general_id=gid, address=0, values=values,
                    blade_total=values['lead'] + values['war'])

    def edit_unit(self, address, key, value):
        before = self.state[key]; self.state[key] = value
        return dict(kind='unit_edit', scope='unit', label={'soldiers': '兵力', 'rice': '兵粮',
                    'morale': '士气', 'training': '训练'}[key], field=key, address='0x0',
                    before=before, requested=value, written=value, after=value, ok=True,
                    clamp=[0, 100000], local_only=True)

    def edit_general(self, gid, key, value):
        label = {'lead': '统率', 'war': '武力', 'intel': '智力', 'pol': '政治', 'cha': '魅力'}[key]
        before = self.state[key]; self.state[key] = value
        stats = self.general_stats(gid)
        return dict(kind='general_edit', scope='general', general_id=gid, label=label,
                    field=key, address='0x0', before=before, requested=value, written=value,
                    after=value, ok=True, clamp=[0, 255], local_only=True,
                    blade_total_before=stats['blade_total'],
                    blade_total_after=stats['blade_total'])

    def revert_pending(self):
        raise ValueError('演示模式没有可还原的写入')

    def geometry(self):
        raise ValueError('演示模式不连接游戏')

    def capture(self):
        raise ValueError('演示模式不连接游戏')

    def inspect(self, snapshot, row):
        raise ValueError('演示模式不连接游戏')

    def close(self):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bridge', required=True)
    ap.add_argument('--pid', type=int)
    ap.add_argument('--out', required=True, help='new JSONL evidence file; never a game file')
    ap.add_argument('--snapshot-only', action='store_true')
    ap.add_argument('--demo', action='store_true', help='sample card, no game process')
    args = ap.parse_args()
    if os.environ.get('SGI_P53_DEMO') == '1':
        args.demo = True
    out = Path(args.out)
    if out.exists():
        raise SystemExit('choose a new evidence path; previous captures are preserved')
    with out.open('x', encoding='utf-8') as log:
        def emit(value):
            value = dict(value); value.setdefault('wall', time.time())
            log.write(json.dumps(value, ensure_ascii=False) + '\n'); log.flush()
        if args.demo:
            reader = DemoReader()
        else:
            reader = None
            deadline = time.time() + float(os.environ.get('SGI_P53_WAIT_SECONDS', '90'))
            while reader is None:
                try:
                    reader = ReadOnlyGame(args.bridge, args.pid)
                except (ValueError, OSError) as error:
                    if time.time() >= deadline:
                        raise
                    print('[insp] waiting for a live shadow SANPK: %s' % error,
                          file=sys.stderr, flush=True)
                    time.sleep(2)
        ui = None; mutex = None; mutex_api = None
        try:
            if args.snapshot_only:
                value = reader.capture(); emit(value)
                print(json.dumps(value, ensure_ascii=False))
            else:
                mutex_api = C.WinDLL('kernel32', use_last_error=True)
                mutex_api.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
                mutex_api.CreateMutexW.restype = W.HANDLE
                mutex_api.CloseHandle.argtypes = [W.HANDLE]
                name = 'Local\\SGI.P53Card.%s.%s' % (
                    reader.identity['pid'], reader.identity['creation_filetime'])
                C.set_last_error(0)
                mutex = mutex_api.CreateMutexW(None, False, name)
                if not mutex or C.get_last_error() == 183:
                    raise ValueError('this inspector is already open for that process')
                ui = InspectorUI(reader, emit)
                if os.environ.get('SGI_P53_AUTOARM') == '1':
                    ui.set_armed(True)
                if args.demo:
                    ui.demo = True
                    ui.show_demo_card()
                ui.loop()
        finally:
            if ui: ui.close()
            if mutex: mutex_api.CloseHandle(mutex)
            reader.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='inspector_unavailable', message=str(error)),
                         ensure_ascii=False))
        if sys.platform == 'win32' and '--snapshot-only' not in sys.argv:
            u = C.WinDLL('user32', use_last_error=True)
            u.MessageBoxW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT]
            u.MessageBoxW(None, '部队卡片未启动：\n' + str(error), '风夜 · 部队查阅', 0x40)
        raise SystemExit(2)
