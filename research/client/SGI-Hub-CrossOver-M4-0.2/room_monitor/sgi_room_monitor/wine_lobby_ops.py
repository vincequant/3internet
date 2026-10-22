"""Operate only this Wine prefix's SANGUO windows. No main-prefix access."""
import ctypes as c
import json
import os
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

u = c.WinDLL('user32', use_last_error=True)
k = c.WinDLL('kernel32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [CB, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, CB, w.LPARAM]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.IsWindowVisible.argtypes = [w.HWND]
u.IsWindowEnabled.argtypes = [w.HWND]
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetWindowLongW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongW.restype = c.c_long
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, c.c_void_p]
u.SendMessageW.restype = w.LPARAM
u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.GetParent.argtypes = [w.HWND]
u.GetParent.restype = w.HWND
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.SetForegroundWindow.argtypes = [w.HWND]
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
k.CloseHandle.argtypes = [w.HANDLE]
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
WM_SETTEXT = 0x000C
WM_GETTEXTLENGTH = 0x000E
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_CHECKED = 1
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SETFOCUS = 0x0007
VK_RETURN = 0x0D
VK_HOME = 0x24
VK_DOWN = 0x28
TVM_GETITEMRECT = 0x1104
TCM_GETCURSEL = 0x130B
TCM_SETCURSEL = 0x130C
SW_SHOW = 5
SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
ES_PASSWORD = 0x20
TVM_GETNEXTITEM = 0x110A
TVM_GETITEMA = 0x110C
TVM_EXPAND = 0x1102
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVGN_ROOT = 0
TVGN_NEXT = 1
TVGN_CHILD = 4
TVGN_CARET = 9
TVE_EXPAND = 2
TVIF_TEXT = 1
TVIF_STATE = 8
TVIF_HANDLE = 0x10
TVIS_SELECTED = 2
LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMTEXTW = 0x1073
OBJID_CLIENT = 0xFFFFFFFC
VT_I4 = 3
VT_EMPTY = 0


class TVITEMW(c.Structure):
    _fields_ = [
        ('mask', w.UINT),
        ('hItem', w.HANDLE),
        ('state', w.UINT),
        ('stateMask', w.UINT),
        ('pszText', c.c_void_p),
        ('cchTextMax', c.c_int),
        ('iImage', c.c_int),
        ('iSelectedImage', c.c_int),
        ('cChildren', c.c_int),
        ('lParam', w.LPARAM),
    ]


class LVITEMW(c.Structure):
    _fields_ = [
        ('mask', w.UINT),
        ('iItem', c.c_int),
        ('iSubItem', c.c_int),
        ('state', w.UINT),
        ('stateMask', w.UINT),
        ('pszText', w.LPWSTR),
        ('cchTextMax', c.c_int),
        ('iImage', c.c_int),
        ('lParam', w.LPARAM),
    ]


class GUID(c.Structure):
    _fields_ = [
        ('Data1', c.c_uint32),
        ('Data2', c.c_uint16),
        ('Data3', c.c_uint16),
        ('Data4', c.c_ubyte * 8),
    ]


class VARIANT(c.Structure):
    _fields_ = [
        ('vt', c.c_uint16),
        ('r1', c.c_uint16),
        ('r2', c.c_uint16),
        ('r3', c.c_uint16),
        ('lVal', c.c_int32),
        ('pad', c.c_byte * 12),
    ]


IID_IACCESSIBLE = GUID(0x618736E0, 0x3C3D, 0x11CF, (0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))

CAPTCHA = ('验证码', '安全验证', '人机验证', '异常登录', '账号异常')
CRASH = ('Access violation', 'access violation', 'comctl32')
LOGIN_BUTTONS = ('登录', '登陆', '确定', '登录(&L)', '确定(&O)')
START_BUTTONS = ('启动游戏',)
LINE_HINTS = ('多线2', '主线')
ROOM_HINTS = ('三国对战房', '游戏房间')


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


def allowed_image(path):
    """Fail-closed: only SANGUO/SANPK, and only under SGI_ALLOWED_IMAGE_ROOT when set."""
    raw = (path or '').replace('/', '\\')
    low = raw.lower()
    if not (low.endswith('\\sanguo.exe') or low.endswith('\\sanpk.exe')):
        return False
    root = (os.environ.get('SGI_ALLOWED_IMAGE_ROOT') or '').replace('/', '\\').strip()
    if not root:
        return True
    return root.lower().rstrip('\\') in low


def children(hwnd):
    rows = []

    @CB
    def visit(ch, _):
        r = w.RECT()
        u.GetWindowRect(ch, c.byref(r))
        rows.append({
            'hwnd': int(ch),
            'class': label(ch, True),
            'title': label(ch),
            'visible': bool(u.IsWindowVisible(ch)),
            'enabled': bool(u.IsWindowEnabled(ch)),
            'style': int(u.GetWindowLongW(ch, -16)),
            'rect': [r.left, r.top, r.right, r.bottom],
            'parent': int(u.GetParent(ch) or 0),
        })
        return True

    u.EnumChildWindows(hwnd, visit, 0)
    return rows


def _exe_windows(suffix):
    rows = []

    @CB
    def visit(hwnd, _):
        pid = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        path = image_path(pid.value)
        if not path.lower().endswith(suffix):
            return True
        if not allowed_image(path):
            return True
        rows.append({
            'hwnd': int(hwnd),
            'pid': pid.value,
            'class': label(hwnd, True),
            'title': label(hwnd),
            'visible': bool(u.IsWindowVisible(hwnd)),
            'path': path,
            'children': children(hwnd),
        })
        return True

    u.EnumWindows(visit, 0)
    return rows


def sanguo_windows():
    return _exe_windows('\\sanguo.exe')


def sanpk_windows():
    return _exe_windows('\\sanpk.exe')


def titles_of(rows):
    texts = []
    for row in rows:
        if row.get('title'):
            texts.append(row['title'])
        for ch in row.get('children') or []:
            if ch.get('title'):
                texts.append(ch['title'])
    return texts


def captcha(rows):
    text = ' '.join(titles_of(rows))
    for marker in CAPTCHA + CRASH:
        if marker in text:
            return marker
    return None


def _vtbl(iface):
    return c.cast(c.cast(iface, c.POINTER(c.c_void_p))[0], c.POINTER(c.c_void_p))


def acc_item_names(hwnd):
    """Read Delphi TTreeView labels via MSAA. TVM_GETITEMW is empty from 64-bit Wine Python to 32-bit SANGUO."""
    names = []
    try:
        ole32 = c.windll.ole32
        oleacc = c.windll.oleacc
        oleaut32 = c.windll.oleaut32
        ole32.CoInitialize(None)
        iface = c.c_void_p()
        hr = oleacc.AccessibleObjectFromWindow(hwnd, OBJID_CLIENT, c.byref(IID_IACCESSIBLE), c.byref(iface))
        if hr != 0 or not iface.value:
            return names
        count_fn = c.WINFUNCTYPE(c.c_long, c.c_void_p, c.POINTER(c.c_long))(_vtbl(iface.value)[8])
        name_fn = c.WINFUNCTYPE(c.c_long, c.c_void_p, VARIANT, c.POINTER(c.c_void_p))(_vtbl(iface.value)[10])
        n = c.c_long(0)
        if count_fn(iface.value, c.byref(n)) != 0:
            return names
        for index in range(1, int(n.value) + 1):
            var = VARIANT()
            var.vt = VT_I4
            var.lVal = index
            bstr = c.c_void_p()
            if name_fn(iface.value, var, c.byref(bstr)) != 0 or not bstr.value:
                names.append('')
                continue
            names.append(c.wstring_at(bstr.value))
            oleaut32.SysFreeString(bstr)
        release = c.WINFUNCTYPE(c.c_ulong, c.c_void_p)(_vtbl(iface.value)[2])
        release(iface.value)
    except (OSError, ValueError, AttributeError, TypeError):
        return names
    return names


def tree_text(hwnd, item):
    caret = u.SendMessageW(hwnd, TVM_GETNEXTITEM, TVGN_CARET, 0)
    selected = bool(item and caret and int(item) == int(caret))
    # 64-bit Wine Python must not send TVM_GETITEM* into 32-bit comctl32.
    if c.sizeof(c.c_void_p) != 4:
        return '', selected
    buf = c.create_unicode_buffer(512)
    info = TVITEMW()
    info.mask = TVIF_TEXT | TVIF_STATE
    info.hItem = item
    info.stateMask = TVIS_SELECTED
    info.pszText = c.cast(buf, c.c_void_p)
    info.cchTextMax = len(buf)
    u.SendMessageW(hwnd, TVM_GETITEMW, 0, c.byref(info))
    return buf.value, selected or bool(info.state & TVIS_SELECTED)


def walk_tree(hwnd, item, depth=0):
    rows = []
    while item:
        u.SendMessageW(hwnd, TVM_EXPAND, TVE_EXPAND, item)
        text, selected = tree_text(hwnd, item)
        child = u.SendMessageW(hwnd, TVM_GETNEXTITEM, TVGN_CHILD, item)
        rows.append({'text': text, 'selected': selected, 'depth': depth, 'handle': int(item)})
        if child:
            rows.extend(walk_tree(hwnd, child, depth + 1))
        item = u.SendMessageW(hwnd, TVM_GETNEXTITEM, TVGN_NEXT, item)
    return rows


def _fill_tree_texts(hwnd, items):
    if any((row.get('text') or '').strip() for row in items):
        return items
    names = acc_item_names(hwnd)
    if names:
        for row, name in zip(items, names):
            if name and not row.get('text'):
                row['text'] = name
        if any((row.get('text') or '').strip() for row in items):
            return items
    return _fill_tree_texts_from_memory(hwnd, items)


def _rpm(proc, addr, size):
    if not addr:
        return b''
    buf = (c.c_ubyte * size)()
    got = c.c_size_t()
    if not k.ReadProcessMemory(proc, addr, buf, size, c.byref(got)):
        return b''
    return bytes(buf[:got.value])


def _fill_tree_texts_from_memory(hwnd, items):
    """Read-only Wine TREEITEM pszText. Fail-closed on hash or layout mismatch."""
    from tree_node_read import label_from_item, parse_tree_item, verify_sanguo
    if c.sizeof(c.c_void_p) != 4 or not items:
        return items
    pid = w.DWORD()
    u.GetWindowThreadProcessId(hwnd, c.byref(pid))
    if not verify_sanguo(Path(image_path(pid.value))):
        return items
    proc = k.OpenProcess(0x410, False, pid.value)
    if not proc:
        return items
    try:
        mapped = []
        for row in items:
            handle = int(row.get('handle') or 0)
            blob = _rpm(proc, handle, 64)
            parsed = parse_tree_item(blob)
            if parsed is None:
                return items
            text = label_from_item(blob, _rpm(proc, parsed['text_ptr'], 160))
            if not text:
                return items
            mapped.append((row, text))
        if len(mapped) != len(items):
            return items
        for row, text in mapped:
            row['text'] = text
    finally:
        k.CloseHandle(proc)
    return items


def tree_items(rows):
    found = []
    for row in rows:
        for ch in row.get('children') or []:
            if 'tree' not in ch['class'].lower() or not ch.get('hwnd'):
                continue
            root = u.SendMessageW(ch['hwnd'], TVM_GETNEXTITEM, TVGN_ROOT, 0)
            items = walk_tree(ch['hwnd'], root)
            items = _fill_tree_texts(ch['hwnd'], items)
            found.append({'hwnd': ch['hwnd'], 'class': ch['class'], 'visible': ch['visible'],
                          'items': items})
    return found


def list_items(rows):
    found = []
    for row in rows:
        for ch in row.get('children') or []:
            if 'listview' not in ch['class'].lower() or not ch.get('hwnd'):
                continue
            count = int(u.SendMessageW(ch['hwnd'], LVM_GETITEMCOUNT, 0, 0) or 0)
            found.append({'class': ch['class'], 'visible': ch['visible'], 'count': count, 'items': []})
    return found


def _lparam_xy(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)


def activate_tab(title):
    """Bring a Delphi TTabSheet to front. Tree clicks do nothing on a hidden page."""
    wanted = (title or '').strip()
    if not wanted:
        return {'status': 'needs_user', 'message': '缺少页签名'}
    for row in sanguo_windows():
        if row.get('class') == 'TMainForm':
            u.ShowWindow(row['hwnd'], SW_RESTORE)
            u.SetForegroundWindow(row['hwnd'])
        sheets = [ch for ch in row.get('children') or []
                  if (ch.get('title') or '').strip() == wanted
                  and 'tab' in (ch.get('class') or '').lower()]
        if len(sheets) != 1:
            continue
        sheet = sheets[0]
        parent = u.GetParent(sheet['hwnd'])
        siblings = [ch for ch in row.get('children') or []
                    if 'tab' in (ch.get('class') or '').lower()
                    and u.GetParent(ch['hwnd']) == parent]
        index = next((i for i, ch in enumerate(siblings) if ch['hwnd'] == sheet['hwnd']), 0)
        if parent:
            u.SendMessageW(parent, TCM_SETCURSEL, index, 0)
        u.ShowWindow(sheet['hwnd'], SW_SHOW)
        u.PostMessageW(sheet['hwnd'], BM_CLICK, 0, 0)
        return {'status': 'clicked', 'title': wanted, 'index': index}
    return {'status': 'needs_user', 'message': '未唯一找到页签 ' + wanted}


def _activate_tree_item(hwnd, handle, index=None):
    u.SendMessageW(hwnd, TVM_SELECTITEM, TVGN_CARET, handle)
    u.SendMessageW(hwnd, TVM_ENSUREVISIBLE, 0, handle)
    u.SendMessageW(hwnd, WM_SETFOCUS, 0, 0)
    u.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
    u.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)
    row = 18
    x = 72
    y = (int(index) * row + row // 2) if index is not None else 10
    lp = _lparam_xy(x, y)
    u.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    u.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    u.PostMessageW(hwnd, WM_LBUTTONDBLCLK, 1, lp)
    u.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    return {'x': x, 'y': y}


def _tree_text(text):
    return (text or '').replace('\u3000', ' ').strip()


def _tree_item_key(hwnd, item, index):
    handle = item.get('handle')
    if handle:
        return (int(hwnd or 0), int(handle))
    return (int(hwnd or 0), _tree_text(item.get('text')), item.get('depth'), index)


def collect_tree_matches(trees, name):
    """Exact title first, then a single substring hit. Dedupes duplicate hwnd/handle."""
    wanted = _tree_text(name)
    exact, partial, seen = [], [], set()
    for tree in trees or []:
        hwnd = tree.get('hwnd')
        for index, item in enumerate(tree.get('items') or []):
            text = _tree_text(item.get('text'))
            if not text:
                continue
            key = _tree_item_key(hwnd, item, index)
            if key in seen:
                continue
            seen.add(key)
            row = dict(item)
            row['hwnd'] = hwnd
            row['index'] = index
            row['text'] = text
            try:
                from tree_node_read import parent_label
                row['parent'] = parent_label(tree.get('items') or [], index)
            except ImportError:
                row['parent'] = ''
            if text == wanted:
                exact.append(row)
            elif wanted and wanted in text:
                partial.append(row)
    if len(exact) == 1:
        return exact[0], exact, partial
    if len(exact) > 1:
        try:
            from tree_node_read import pick_unique_line
            picked = pick_unique_line(exact)
        except ImportError:
            picked = None
        if picked:
            return picked, exact, partial
    if not exact and len(partial) == 1:
        return partial[0], exact, partial
    return None, exact, partial


def dump_tree_texts(trees):
    dumped = []
    for tree in trees or []:
        dumped.append([_tree_text(item.get('text')) for item in (tree.get('items') or [])])
    return dumped


def pick_empty_tree_index(items, names):
    """Choose a line node when TTreeView labels cannot be read."""
    depth1 = [i for i, item in enumerate(items or []) if item.get('depth') == 1]
    wanted = ' '.join(names or [])
    if '多线2' in wanted and len(depth1) >= 2:
        return depth1[1]
    if depth1:
        return depth1[0]
    return None


def select_tree(names):
    from tree_node_read import line_entered, result_driven_indices
    activate_tab('游戏房间')
    rows = sanguo_windows()
    trees = tree_items(rows)
    last_exact, last_partial = [], []
    for name in names:
        match, last_exact, last_partial = collect_tree_matches(trees, name)
        if match and match.get('hwnd') and match.get('handle') is not None:
            click = _activate_tree_item(match['hwnd'], match['handle'], match.get('index'))
            return {'status': 'clicked', 'title': match.get('text'), **click}
    driven = _select_until_entered(trees, names, result_driven_indices, line_entered)
    if driven.get('status') == 'clicked':
        return driven
    return {
        'status': 'needs_user',
        'message': '未唯一找到房间树节点',
        'wanted': list(names),
        'tree_texts': dump_tree_texts(trees),
        'exact_hits': len(last_exact),
        'partial_hits': len(last_partial),
    }


def _select_until_entered(trees, names, index_fn, entered_fn):
    candidates = [tree for tree in trees or [] if len(tree.get('items') or []) > 1]
    if len(candidates) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到游戏房间树'}
    items = candidates[0]['items']
    hwnd = candidates[0]['hwnd']
    for index in index_fn(items, names):
        item = items[index]
        click = _activate_tree_item(hwnd, item['handle'], index)
        time.sleep(0.9)
        if entered_fn(inspect()):
            return {'status': 'clicked', 'title': item.get('text') or '', 'index': index,
                    'depth': item.get('depth'), 'fallback': 'result_driven', **click}
    return {'status': 'needs_user', 'message': '索引回退未能进入目标线路'}


def _select_line_by_depth(trees, names):
    """When labels are unreadable, enter the first depth-1 node on the room tree.

    多线2 is the second child of 三国对战房 on the current hall layout
    (depth 0 room, depth 1 lines). Prefer that index when asking for 多线2.
    """
    candidates = [tree for tree in trees or [] if len(tree.get('items') or []) > 1]
    if len(candidates) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到游戏房间树'}
    items = candidates[0]['items']
    index = pick_empty_tree_index(items, names)
    if index is None:
        return {'status': 'needs_user', 'message': '房间树没有线路节点'}
    item = items[index]
    click = _activate_tree_item(candidates[0]['hwnd'], item['handle'], index)
    return {'status': 'clicked', 'title': item.get('text') or '', 'index': index,
            'depth': item.get('depth'), 'fallback': 'depth1', **click}


def select_tree_index(index):
    rows = sanguo_windows()
    trees = [tree for tree in tree_items(rows) if len(tree.get('items') or []) > 1]
    if len(trees) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到游戏房间树',
                'tree_sizes': [len(t.get('items') or []) for t in tree_items(rows)]}
    items = trees[0]['items']
    try:
        index = int(index)
    except (TypeError, ValueError):
        return {'status': 'needs_user', 'message': '树节点序号无效'}
    if index < 0 or index >= len(items):
        return {'status': 'needs_user', 'message': '树节点序号超出范围', 'count': len(items)}
    item = items[index]
    click = _activate_tree_item(trees[0]['hwnd'], item['handle'], index)
    return {'status': 'clicked', 'index': index, 'title': item.get('text'),
            'depth': item.get('depth'), **click}


def inspect():
    rows = sanguo_windows()
    games = sanpk_windows()
    game_titles = titles_of(games)
    return {
        'status': 'inspect',
        'windows': [{'class': r['class'], 'title': r['title'], 'visible': r['visible'],
                     'pid': r['pid'], 'children': [
                         {'class': c['class'], 'title': c['title'], 'visible': c['visible'],
                          'enabled': c['enabled'], 'password': bool(c['style'] & ES_PASSWORD),
                          'rect': c.get('rect')}
                         for c in r['children']
                     ]} for r in rows],
        'titles': titles_of(rows) + game_titles,
        'login': any(r['class'] == 'TLoginForm' for r in rows),
        'logged_in': any('当前用户' in (r.get('title') or '') for r in rows),
        'has_start': any(c.get('title') in START_BUTTONS for r in rows for c in r.get('children') or []),
        'has_login_button': any(c.get('title') == '登录' and c.get('visible') and c.get('enabled')
                                for r in rows for c in r.get('children') or []),
        'already_logged_in': any('用户已经登录' in t for t in titles_of(rows)),
        'captcha': captcha(rows),
        'trees': [] if captcha(rows) else tree_items(rows),
        'lists': [] if captcha(rows) else list_items(rows),
        'sanpk_running': bool(games),
        'game_select': any((r.get('title') or '') == '游戏选择' for r in games),
        'game_windows': [{'class': r['class'], 'title': r['title'], 'visible': r['visible'],
                          'pid': r['pid']} for r in games],
    }


def load_creds():
    path = Path(os.environ.get('SGI_MONITOR_CRED_FILE') or '')
    if not path.is_file():
        return '', ''
    data = json.loads(path.read_text(encoding='utf-8'))
    return (data.get('username') or '').strip(), data.get('password') or ''


def login_once():
    rows = sanguo_windows()
    blocked = captcha(rows)
    if blocked:
        return {'status': 'needs_user', 'message': '需要本人处理：' + blocked}
    forms = [r for r in rows if r['class'] == 'TLoginForm' and r['visible']]
    if len(forms) != 1:
        if any('当前用户' in (r.get('title') or '') for r in rows):
            return {'status': 'logged_in', 'message': '已在登录后界面'}
        return {'status': 'needs_user', 'message': '未唯一找到登录窗'}
    form = forms[0]
    edits = [c for c in form['children'] if 'edit' in c['class'].lower() and c['visible'] and c['enabled']]
    user_edits = [c for c in edits if not (c['style'] & ES_PASSWORD)]
    pass_edits = [c for c in edits if c['style'] & ES_PASSWORD]
    if len(user_edits) != 1 or len(pass_edits) != 1:
        return {'status': 'needs_user', 'message': '登录框布局不匹配'}
    username, password = load_creds()
    if username and password:
        user_buf = c.create_unicode_buffer(username)
        pass_buf = c.create_unicode_buffer(password)
        if not u.SendMessageW(user_edits[0]['hwnd'], WM_SETTEXT, 0, c.cast(user_buf, c.c_void_p)):
            return {'status': 'needs_user', 'message': '无法写入用户名'}
        u.SendMessageW(pass_edits[0]['hwnd'], WM_SETTEXT, 0, c.cast(pass_buf, c.c_void_p))
        if not u.SendMessageW(user_edits[0]['hwnd'], WM_GETTEXTLENGTH, 0, 0):
            return {'status': 'needs_user', 'message': '用户名未写入'}
    else:
        user_len = int(u.SendMessageW(user_edits[0]['hwnd'], WM_GETTEXTLENGTH, 0, 0) or 0)
        pass_len = int(u.SendMessageW(pass_edits[0]['hwnd'], WM_GETTEXTLENGTH, 0, 0) or 0)
        if user_len < 1 or pass_len < 1:
            return {'status': 'needs_user',
                    'message': '请在大厅登录窗登录。未配置钥匙串凭据，不会自动填密码。'}
    buttons = [c for c in form['children'] if 'button' in c['class'].lower() and c['visible']
               and c['enabled'] and any(c['title'] == name or name in c['title'] for name in LOGIN_BUTTONS)]
    if len(buttons) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到登录按钮',
                'buttons': [c['title'] for c in form['children'] if 'button' in c['class'].lower()]}
    if not u.PostMessageW(buttons[0]['hwnd'], BM_CLICK, 0, 0):
        return {'status': 'needs_user', 'message': '登录按钮不可用'}
    return {'status': 'submitted', 'message': '已提交一次登录，不重试'}


def dismiss_prompt():
    rows = sanguo_windows()
    markers = ('提示信息', '登录失败') + CRASH
    buttons = []
    for row in rows:
        if not row['visible']:
            continue
        blob = ' '.join([row.get('title') or ''] + [c.get('title') or '' for c in row['children']])
        if not any(marker in blob for marker in markers):
            continue
        for ch in row['children']:
            if ch['visible'] and ch['enabled'] and ch['title'] in ('确定', 'OK', 'Ok'):
                buttons.append(ch)
    if not buttons:
        for row in rows:
            if not row['visible'] or row.get('class') == 'TMainForm':
                continue
            for ch in row['children']:
                if ch['visible'] and ch['enabled'] and ch['title'] in ('确定', 'OK', 'Ok'):
                    buttons.append(ch)
    if len(buttons) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到提示确定按钮', 'titles': titles_of(rows)}
    u.PostMessageW(buttons[0]['hwnd'], BM_CLICK, 0, 0)
    return {'status': 'clicked', 'title': buttons[0]['title']}


def check_force_login():
    rows = sanguo_windows()
    boxes = []
    for row in rows:
        if row['class'] != 'TLoginForm' or not row['visible']:
            continue
        for ch in row['children']:
            if ch['visible'] and ch['enabled'] and ch['title'] == '强制登录':
                boxes.append(ch)
    if len(boxes) != 1:
        return {'status': 'needs_user', 'message': '未唯一找到强制登录'}
    hwnd = boxes[0]['hwnd']
    checked = int(u.SendMessageW(hwnd, BM_GETCHECK, 0, 0) or 0)
    if checked != BST_CHECKED:
        u.SendMessageW(hwnd, BM_CLICK, 0, 0)
        time.sleep(0.2)
    checked = int(u.SendMessageW(hwnd, BM_GETCHECK, 0, 0) or 0)
    return {'status': 'checked' if checked == BST_CHECKED else 'unchecked',
            'title': '强制登录', 'checked': checked == BST_CHECKED}


def _save_hwnd_bmp(hwnd, path):
    gdi = c.WinDLL('gdi32')
    rc = w.RECT()
    if not u.GetWindowRect(hwnd, c.byref(rc)):
        return {'status': 'error', 'message': '无窗口矩形'}
    width = max(1, rc.right - rc.left)
    height = max(1, rc.bottom - rc.top)
    hdc = u.GetDC(0)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, width, height)
    old = gdi.SelectObject(mem, bmp)
    SRCCOPY = 0x00CC0020
    printed = gdi.BitBlt(mem, 0, 0, width, height, hdc, rc.left, rc.top, SRCCOPY)
    if not printed:
        printed = u.PrintWindow(hwnd, mem, 2) or u.PrintWindow(hwnd, mem, 0)
    class BITMAPINFOHEADER(c.Structure):
        _fields_ = [
            ('biSize', w.DWORD), ('biWidth', c.c_long), ('biHeight', c.c_long),
            ('biPlanes', w.WORD), ('biBitCount', w.WORD), ('biCompression', w.DWORD),
            ('biSizeImage', w.DWORD), ('biXPelsPerMeter', c.c_long),
            ('biYPelsPerMeter', c.c_long), ('biClrUsed', w.DWORD), ('biClrImportant', w.DWORD),
        ]
    header = BITMAPINFOHEADER()
    header.biSize = 40
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 24
    stride = ((width * 3 + 3) // 4) * 4
    pixels = (c.c_ubyte * (stride * height))()
    gdi.GetDIBits(mem, bmp, 0, height, pixels, c.byref(header), 0)
    gdi.SelectObject(mem, old)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    u.ReleaseDC(0, hdc)
    file_size = 14 + 40 + stride * height
    with open(path, 'wb') as fh:
        fh.write(b'BM')
        fh.write(file_size.to_bytes(4, 'little'))
        fh.write((0).to_bytes(4, 'little'))
        fh.write((54).to_bytes(4, 'little'))
        fh.write(c.string_at(c.byref(header), 40))
        fh.write(bytes(pixels))
    return {'status': 'saved', 'path': str(path), 'width': width, 'height': height, 'printed': bool(printed)}


def capture_lobby():
    dest_dir = Path(r'C:\sgi\room_monitor')
    dest_dir.mkdir(parents=True, exist_ok=True)
    rows = sanguo_windows()
    shots = []
    for row in rows:
        if row.get('class') == 'TMainForm' and row.get('visible'):
            shots.append({'kind': 'main', **_save_hwnd_bmp(row['hwnd'], dest_dir / 'lobby-main.bmp')})
        for ch in row.get('children') or []:
            if ch.get('class') == 'TTreeView' and ch.get('visible') and ch.get('hwnd'):
                name = 'tree-%s.bmp' % ch['hwnd']
                shots.append({'kind': 'tree', 'hwnd': ch['hwnd'],
                              **_save_hwnd_bmp(ch['hwnd'], dest_dir / name)})
    return {'status': 'captured', 'shots': shots, 'acc': [
        {'hwnd': ch['hwnd'], 'names': acc_item_names(ch['hwnd'])}
        for row in rows for ch in row.get('children') or []
        if ch.get('class') == 'TTreeView' and ch.get('hwnd')
    ]}


def _is_tab_sheet(control):
    cls = ((control or {}).get('class') or '').lower()
    return 'tab' in cls and 'pagecontrol' not in cls


def _is_page_control(control):
    return 'pagecontrol' in ((control or {}).get('class') or '').lower()


def _is_room_sheet(control):
    title = ((control or {}).get('title') or '').replace('\u3000', ' ').strip()
    return title == '游戏房间' or title.startswith('游戏房间')


def _hwnd_map(rows):
    mapping = {}
    for row in rows or []:
        hwnd = row.get('hwnd')
        if hwnd:
            mapping[int(hwnd)] = row
        for ch in row.get('children') or []:
            ch_hwnd = ch.get('hwnd')
            if ch_hwnd:
                mapping[int(ch_hwnd)] = ch
    return mapping


def _walk_ancestors(control, mapping):
    seen = set()
    parent = (control or {}).get('parent')
    while parent:
        parent = int(parent)
        if parent in seen:
            break
        seen.add(parent)
        node = mapping.get(parent)
        if node is None:
            break
        yield node
        parent = node.get('parent')


def _sheet_of(control, mapping):
    if _is_tab_sheet(control):
        return control
    for node in _walk_ancestors(control, mapping):
        if _is_tab_sheet(node):
            return node
    return None


def _page_of(control, mapping):
    if _is_page_control(control):
        return control
    for node in _walk_ancestors(control, mapping):
        if _is_page_control(node):
            return node
    return None


def _tab_groups(rows):
    groups = []
    for row in rows or []:
        buckets = {}
        for ch in row.get('children') or []:
            if _is_tab_sheet(ch):
                buckets.setdefault(int(ch.get('parent') or 0), []).append(ch)
        groups.extend(buckets.items())
    return groups


def annotate_current_tabs(rows, cur_sel=None):
    """Mark TTabSheet.current from TCM_GETCURSEL, else the unique visible sibling."""
    for parent, sheets in _tab_groups(rows):
        cur_hwnd = None
        assigned = False
        idx = cur_sel(parent) if callable(cur_sel) else None
        try:
            idx = int(idx) if idx is not None else None
        except (TypeError, ValueError):
            idx = None
        vis = [sheet for sheet in sheets if sheet.get('visible')]
        if idx is not None and 0 <= idx < len(sheets):
            cur_hwnd = sheets[idx].get('hwnd')
            assigned = True
        elif len(vis) == 1:
            cur_hwnd = vis[0].get('hwnd')
            assigned = True
        elif not any('current' in sheet for sheet in sheets):
            cur_hwnd = None
            assigned = True
        if assigned:
            for sheet in sheets:
                sheet['current'] = bool(cur_hwnd and sheet.get('hwnd') == cur_hwnd)
    return rows


def _tcm_cur_sel(parent):
    if not parent:
        return None
    idx = int(u.SendMessageW(parent, TCM_GETCURSEL, 0, 0) or -1)
    return idx if idx >= 0 else None


def _on_room_page(control, mapping):
    sheet = _sheet_of(control, mapping)
    if sheet is not None:
        return _is_room_sheet(sheet)
    page = _page_of(control, mapping)
    page_hwnd = int((page or {}).get('hwnd') or 0)
    if not page_hwnd:
        return False
    for node in mapping.values():
        if _is_tab_sheet(node) and int(node.get('parent') or 0) == page_hwnd and _is_room_sheet(node):
            return True
    return False


def _on_hidden_tab(control, mapping):
    """True when an ancestor TTabSheet is not the current/visible page.

    Delphi/Wine often leaves child TButton.visible=True on hidden sheets.
    """
    sheet = _sheet_of(control, mapping)
    if sheet is None:
        return False
    if sheet.get('current') is True:
        return False
    if sheet.get('visible') is False:
        return True
    if sheet.get('current') is False:
        return True
    return False


def collect_named_controls(rows, names):
    names = tuple(names or ())
    found, seen = [], set()
    for row in rows or []:
        if not row.get('visible'):
            continue
        for ch in row.get('children') or []:
            if ch.get('title') not in names:
                continue
            if _is_tab_sheet(ch) or _is_page_control(ch):
                continue
            key = ch.get('hwnd')
            if key:
                key = int(key)
                if key in seen:
                    continue
                seen.add(key)
            found.append(ch)
    return found


def pick_named_control(rows, names):
    """Pick one enabled control, or None.

    0 remaining -> None (needs_user).
    Hidden-tab / disabled copies are ignored.
    For 启动游戏, prefer the 游戏房间 page when two front hits remain.
    Two truly front, enabled, visible hits with no unique room page -> None (fail-closed).
    """
    annotate_current_tabs(rows)
    mapping = _hwnd_map(rows)
    names = tuple(names or ())
    prefer_room = '启动游戏' in names
    enabled = [ch for ch in collect_named_controls(rows, names) if ch.get('enabled')]
    candidates = [ch for ch in enabled if not _on_hidden_tab(ch, mapping)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if prefer_room:
        room = [ch for ch in candidates if _on_room_page(ch, mapping)]
        if len(room) == 1:
            return room[0]
        if room:
            candidates = room
    current = []
    for ch in candidates:
        sheet = _sheet_of(ch, mapping)
        if sheet is None or sheet.get('current'):
            current.append(ch)
    if len(current) == 1:
        return current[0]
    if current:
        candidates = current
    if len(candidates) == 1:
        return candidates[0]
    return None


def click_named(names):
    rows = sanguo_windows()
    blocked = captcha(rows)
    if blocked:
        return {'status': 'needs_user', 'message': '需要本人处理：' + blocked}
    annotate_current_tabs(rows, _tcm_cur_sel)
    picked = pick_named_control(rows, names)
    if not picked or not picked.get('hwnd'):
        return {'status': 'needs_user', 'message': '未唯一找到按钮 ' + '/'.join(names),
                'titles': titles_of(rows)}
    if not u.PostMessageW(picked['hwnd'], BM_CLICK, 0, 0):
        return {'status': 'needs_user', 'message': '按钮不可用'}
    return {'status': 'clicked', 'title': picked['title']}


if __name__ == '__main__':
    action = 'inspect'
    click_title = ''
    args = sys.argv[1:]
    if '--login' in args:
        action = 'login'
    elif '--start-game' in args:
        action = 'start'
    elif '--dismiss' in args:
        action = 'dismiss'
    elif '--force' in args:
        action = 'force'
    elif '--shot' in args:
        action = 'shot'
    elif '--select-index' in args:
        action = 'tree-index'
        idx = args.index('--select-index')
        click_title = args[idx + 1] if idx + 1 < len(args) else ''
    elif '--select-tree' in args:
        action = 'tree'
        idx = args.index('--select-tree')
        click_title = args[idx + 1] if idx + 1 < len(args) else ''
    elif '--click' in args:
        action = 'click'
        idx = args.index('--click')
        click_title = args[idx + 1] if idx + 1 < len(args) else ''
    try:
        if action == 'login':
            result = login_once()
        elif action == 'start':
            result = click_named(START_BUTTONS)
        elif action == 'dismiss':
            result = dismiss_prompt()
        elif action == 'force':
            result = check_force_login()
        elif action == 'shot':
            result = capture_lobby()
        elif action == 'tree':
            result = select_tree((click_title,)) if click_title else {'status': 'needs_user', 'message': '缺少树节点'}
        elif action == 'tree-index':
            result = select_tree_index(click_title) if click_title != '' else {'status': 'needs_user', 'message': '缺少树序号'}
        elif action == 'click':
            result = click_named((click_title,)) if click_title else {'status': 'needs_user', 'message': '缺少点击标题'}
        else:
            result = inspect()
    except Exception as error:
        result = {'status': 'error', 'message': str(error)}
    print(json.dumps(result, ensure_ascii=False))
