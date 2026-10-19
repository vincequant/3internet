"""Automate the SANPK '游戏选择' browser (list / create / join).

usage (under the target prefix):
  WINEPREFIX=... "$WINE" "$P32" game_browser.py list
  WINEPREFIX=... "$WINE" "$P32" game_browser.py create <host-name>
  WINEPREFIX=... "$WINE" "$P32" game_browser.py join <substring> [--fallback <sub2>]

Reads the room list (LB_* messages), posts BM_CLICK to the browser buttons.
For create: clicks 创建游戏, waits for the 请输入【主机名称】 dialog, sets the
Edit text (WM_SETTEXT verified by WM_GETTEXT, with a WM_CHAR fallback), confirms.
For join: refresh list, pick the first item containing <substring> (or fallback),
LB_SETCURSEL + 加入游戏.
Prints one JSON line with the result. Read-only otherwise (no game files touched).
"""
import ctypes as c
import json
import sys
import time
from ctypes import wintypes as w

u32 = c.WinDLL('user32', use_last_error=True)
u32.SendMessageW.restype = c.c_ssize_t
u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u32.PostMessageW.restype = w.BOOL

BM_CLICK = 0x00F5
LB_GETCOUNT = 0x018B
LB_GETTEXTLEN = 0x018A
LB_GETTEXT = 0x0189
LB_SETCURSEL = 0x0186
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_CHAR = 0x0102

BROWSER_TITLE = '游戏选择'
ID_CREATE = 1005
ID_JOIN = 1024
ID_REFRESH = 1006
ID_LISTBOX = 1007
ID_DIALOG_OK = 1


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


def children(h):
    kids = []

    @CB
    def ch(hw, _):
        kids.append(hw)
        return True

    u32.EnumChildWindows(h, ch, 0)
    return kids


def top_windows():
    tops = []

    @CB
    def visit(h, _):
        if u32.IsWindowVisible(h):
            tops.append(h)
        return True

    u32.EnumWindows(visit, 0)
    return tops


def find_top(sub):
    for t in top_windows():
        if sub in text(t):
            return t
    return None


def find_child(h, cid=None, cls_sub=None, cap_sub=None):
    for k in children(h):
        if cid is not None and int(u32.GetDlgCtrlID(k)) != cid:
            continue
        if cls_sub is not None and cls_sub.lower() not in cls(k).lower():
            continue
        if cap_sub is not None and cap_sub not in text(k):
            continue
        return k
    return None


def click(h):
    if not h:
        return False
    return bool(u32.PostMessageW(h, BM_CLICK, 0, 0))


def read_list(lb):
    n = int(u32.SendMessageW(lb, LB_GETCOUNT, 0, 0) or 0)
    items = []
    for i in range(n):
        ln = int(u32.SendMessageW(lb, LB_GETTEXTLEN, i, 0) or 0)
        buf = c.create_unicode_buffer(ln + 2)
        u32.SendMessageW(lb, LB_GETTEXT, i, c.cast(buf, c.c_void_p).value)
        items.append(buf.value)
    return items


def sm_text(h, value):
    """WM_SETTEXT with a wchar pointer argtype."""
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, c.c_wchar_p]
    u32.SendMessageW.restype = c.c_ssize_t
    r = u32.SendMessageW(h, WM_SETTEXT, 0, value)
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = c.c_ssize_t
    return r


def get_text_ctrl(h):
    buf = c.create_unicode_buffer(256)
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = c.c_ssize_t
    u32.SendMessageW(h, WM_GETTEXT, 255, c.cast(buf, c.c_void_p).value)
    return buf.value


def set_edit(ed, value):
    sm_text(ed, value)
    rb = get_text_ctrl(ed)
    if rb == value:
        return 'wm_settext', rb
    rb = text(ed)
    if rb == value:
        return 'wm_settext_gwt', rb
    u32.SetFocus(ed)
    for chv in value:
        u32.SendMessageW(ed, WM_CHAR, ord(chv), 0)
    rb = get_text_ctrl(ed)
    if rb == value:
        return 'wm_char', rb
    rb = text(ed)
    return 'wm_char_partial', rb


def dismiss_search_dialogs():
    """Click 确定/OK on '搜寻服务器' progress dialogs (and mute-ok if it pops)."""
    hits = 0
    for t in top_windows():
        cap = text(t)
        if '搜寻' in cap or '搜索中' in cap or '音效' in cap:
            for k in children(t):
                if 'button' not in cls(k).lower():
                    continue
                kc = text(k)
                if kc in ('确定', 'OK', '确认'):
                    click(k)
                    hits += 1
    return hits


def wait_for_list(b, timeout=10.0):
    """Poll the listbox while dismissing search dialogs; return (items, dismissed)."""
    deadline = time.time() + timeout
    dismissed = 0
    items = []
    while time.time() < deadline:
        dismissed += dismiss_search_dialogs()
        lb = find_child(b, cid=ID_LISTBOX)
        items = read_list(lb) if lb else []
        if items:
            break
        time.sleep(0.4)
    return items, dismissed


def cmd_list():
    dismiss_search_dialogs()
    time.sleep(0.3)
    b = find_top(BROWSER_TITLE)
    if not b:
        return {'ok': False, 'error': 'browser not found'}
    click(find_child(b, cid=ID_REFRESH))
    items, dismissed = wait_for_list(b)
    return {'ok': True, 'items': items, 'dismissed': dismissed}


def cmd_create(name):
    b = find_top(BROWSER_TITLE)
    if not b:
        return {'ok': False, 'error': 'browser not found'}
    if not click(find_child(b, cid=ID_CREATE)):
        return {'ok': False, 'error': 'create button not found'}
    dlg = None
    for _ in range(30):
        dlg = find_top('请输入')
        if dlg:
            break
        time.sleep(0.2)
    if not dlg:
        return {'ok': False, 'error': 'name dialog not found'}
    ed = find_child(dlg, cls_sub='edit')
    if not ed:
        return {'ok': False, 'error': 'edit control not found'}
    mode, rb = set_edit(ed, name)
    ok = find_child(dlg, cid=ID_DIALOG_OK) or find_child(dlg, cap_sub='确定')
    click(ok)
    time.sleep(2.0)
    return {'ok': True, 'name': name, 'set_mode': mode, 'readback': rb,
            'browser_gone': find_top(BROWSER_TITLE) is None,
            'dialog_gone': find_top('请输入') is None,
            'tops': [text(t) for t in top_windows()]}


def cmd_join(sub, fallback):
    dismiss_search_dialogs()
    time.sleep(0.3)
    b = find_top(BROWSER_TITLE)
    if not b:
        return {'ok': False, 'error': 'browser not found'}
    click(find_child(b, cid=ID_REFRESH))
    items, _dismissed = wait_for_list(b)
    lb = find_child(b, cid=ID_LISTBOX)
    idx = None
    for i, it in enumerate(items):
        if sub in it:
            idx = i
            break
    if idx is None and fallback:
        for i, it in enumerate(items):
            if fallback in it:
                idx = i
                break
    if idx is None:
        return {'ok': False, 'error': 'no matching room', 'items': items}
    u32.SendMessageW(lb, LB_SETCURSEL, idx, 0)
    time.sleep(0.3)
    if not click(find_child(b, cid=ID_JOIN)):
        return {'ok': False, 'error': 'join button not found', 'items': items}
    time.sleep(1.5)
    return {'ok': True, 'picked': items[idx], 'items': items,
            'browser_gone': find_top(BROWSER_TITLE) is None,
            'tops': [text(t) for t in top_windows()]}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'ok': False, 'error': 'usage: list|create <name>|join <sub> [--fallback X]'}))
        return 2
    cmd = sys.argv[1]
    if cmd == 'list':
        res = cmd_list()
    elif cmd == 'create':
        res = cmd_create(sys.argv[2])
    elif cmd == 'join':
        fallback = ''
        if '--fallback' in sys.argv:
            fallback = sys.argv[sys.argv.index('--fallback') + 1]
        res = cmd_join(sys.argv[2], fallback)
    else:
        res = {'ok': False, 'error': 'unknown cmd %r' % cmd}
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
