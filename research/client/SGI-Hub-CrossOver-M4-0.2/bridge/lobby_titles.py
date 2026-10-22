"""Read-only SANGUO window titles. No posted input, no list-item text, no writes."""
import ctypes as c
import json
import time
from ctypes import wintypes as w

u = c.WinDLL('user32', use_last_error=True)
k = c.WinDLL('kernel32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [CB, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, CB, w.LPARAM]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.IsWindowVisible.argtypes = [w.HWND]
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
k.CloseHandle.argtypes = [w.HANDLE]


def label(hwnd, cls=False):
    buf = c.create_unicode_buffer(512)
    (u.GetClassNameW if cls else u.GetWindowTextW)(hwnd, buf, len(buf))
    return buf.value


def image_path(pid):
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return ''
    buf = c.create_unicode_buffer(32768)
    n = w.DWORD(len(buf))
    ok = k.QueryFullProcessImageNameW(handle, 0, buf, c.byref(n))
    k.CloseHandle(handle)
    return buf.value if ok else ''


def snapshot():
    rows = []

    @CB
    def visit(hwnd, _):
        pid = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        path = image_path(pid.value)
        if not path.lower().endswith('\\sanguo.exe'):
            return True
        children = []

        @CB
        def child(ch, __):
            children.append({
                'class': label(ch, True),
                'title': label(ch),
                'visible': bool(u.IsWindowVisible(ch)),
            })
            return True

        u.EnumChildWindows(hwnd, child, 0)
        rows.append({
            'pid': pid.value,
            'class': label(hwnd, True),
            'title': label(hwnd),
            'visible': bool(u.IsWindowVisible(hwnd)),
            'path': path,
            'children': children,
        })
        return True

    u.EnumWindows(visit, 0)
    titles = []
    for row in rows:
        if row['title']:
            titles.append(row['title'])
        for ch in row['children']:
            if ch['title']:
                titles.append(ch['title'])
    classes = {}
    for row in rows:
        classes[row['class']] = classes.get(row['class'], 0) + 1
        for ch in row['children']:
            classes[ch['class']] = classes.get(ch['class'], 0) + 1
    return {
        'status': 'lobby_titles',
        'observed_at': time.time(),
        'windows': rows,
        'titles': titles,
        'classes': classes,
        'has_sgzwlb': any('SGZWLB' in item for item in titles),
        'has_game_select': any(item == '游戏选择' for item in titles),
        'has_listview': any(name in classes for name in ('SysListView32', 'TListView', 'TFrameGameList')),
        'message': '只读大厅窗口标题；未取 ListView 项、未点击、未改内存',
    }


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=False))
