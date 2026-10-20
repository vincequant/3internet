"""WASD invokes SANPK's original scroll handlers, never unit orders."""
import ctypes as C
from ctypes import wintypes as W
import time

PAN_KEYS = {'w': (0x115, 0), 'a': (0x114, 0),
            's': (0x115, 1), 'd': (0x114, 1)}
HOTKEY_IDS = {100 + i: key for i, key in enumerate(PAN_KEYS)}


class GUIThreadInfo(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('flags', W.DWORD),
                ('hwndActive', W.HWND), ('hwndFocus', W.HWND),
                ('hwndCapture', W.HWND), ('hwndMenuOwner', W.HWND),
                ('hwndMoveSize', W.HWND), ('hwndCaret', W.HWND), ('rcCaret', W.RECT)]


def pan_plan(state, key, foreground, focus, gui_flags=0):
    if key not in PAN_KEYS:
        raise ValueError('未知画面方向')
    if (foreground != state['main_hwnd'] or focus != state['hwnd'] or gui_flags
            or state.get('ending') or state.get('native_dialogs')
            or not 1 <= state.get('phase', 0) <= 5
            or any(state.get(k) for k in ('modal', 'widget_count', 'map_mode', 'map_widget',
                                         'strategy_dialog', 'recruit_dialog'))):
        raise ValueError('画面移动仅在游戏主地图置前且无输入框／弹窗时生效')
    message, code = PAN_KEYS[key]
    return dict(hwnd=state['hwnd'], message=message, wparam=code, lparam=0)


class ViewPan:
    def __init__(self, native, emit):
        self.n = native; self.emit = emit; self.registered = set()
        self.context = None; self.next_probe = 0; self.last_report = None
        native.u.GetGUIThreadInfo.argtypes = [W.DWORD, C.POINTER(GUIThreadInfo)]
        native.u.GetGUIThreadInfo.restype = W.BOOL
        native.u.GetAsyncKeyState.argtypes = [C.c_int]
        native.u.GetAsyncKeyState.restype = C.c_short

    def focus(self, foreground):
        pid = W.DWORD()
        thread = self.n.u.GetWindowThreadProcessId(foreground, C.byref(pid))
        if pid.value != self.n.bound['pid'] or not thread:
            raise ValueError('当前前台不是绑定游戏')
        info = GUIThreadInfo(); info.cbSize = C.sizeof(info)
        if not self.n.u.GetGUIThreadInfo(thread, C.byref(info)):
            raise ValueError('无法核对游戏键盘焦点')
        return int(info.hwndFocus or 0), int(info.flags)

    def allowed(self, state):
        foreground = int(self.n.u.GetForegroundWindow() or 0)
        focus, flags = self.focus(foreground)
        # Shift/Ctrl/Alt/Win combinations remain available for native shortcuts.
        if any(self.n.u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5b, 0x5c)):
            raise ValueError('组合键不用于画面移动')
        return foreground, focus, flags

    def update(self, enabled):
        desired = False
        try:
            if enabled and self.n.owner(self.n.u.GetForegroundWindow()) == self.n.bound['pid']:
                now = time.monotonic()
                if now >= self.next_probe or self.context is None:
                    self.context = self.n.capture(); self.next_probe = now + .1
                # Re-read transient custom dialog flags even between full probes.
                current = dict(self.context)
                for key, off in [('modal', 0x8da), ('widget_count', 0x806),
                                 ('map_mode', 0x948), ('strategy_dialog', 0x9b8),
                                 ('recruit_dialog', 0x9d0), ('map_widget', 0x950)]:
                    current[key] = self.n.number(current['view'] + off)
                pan_plan(current, 'w', *self.allowed(current)); desired = True
        except (ValueError, OSError):
            self.context = None
        if not desired:
            self.close()
        else:
            for ident, key in HOTKEY_IDS.items():
                if ident not in self.registered and self.n.u.RegisterHotKey(None, ident, 0, ord(key.upper())):
                    self.registered.add(ident)
        status = tuple(HOTKEY_IDS[i] for i in sorted(self.registered))
        if status != self.last_report:
            self.last_report = status
            self.emit(dict(kind='map_keys', active=list(status), expected=list(PAN_KEYS)))

    def execute(self, key):
        state = self.n.capture()
        plan = pan_plan(state, key, *self.allowed(state))
        if self.n.owner(plan['hwnd']) != self.n.bound['pid']:
            raise ValueError('游戏地图窗口已改变')
        self.emit(dict(kind='view_pan_intent', key=key, plan=plan,
                       viewport=state.get('viewport'), game_order=False))
        ok = self.n.u.PostMessageW(plan['hwnd'], plan['message'], plan['wparam'], plan['lparam'])
        self.emit(dict(kind='view_pan_receipt', key=key, posted=bool(ok), game_order=False))
        if not ok:
            raise C.WinError(C.get_last_error())
        return dict(status='view_pan_posted', note='已发送画面滚动', game_order=False)

    def close(self):
        for ident in self.registered:
            self.n.u.UnregisterHotKey(None, ident)
        self.registered.clear()
