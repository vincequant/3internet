"""32-bit helper: original NetHook StartServer, then SANPK /1an.

Grant arrives on stdin as one JSON object. Never print password or token.
Must run as 32-bit Windows Python. Fail-closed on DLL hash mismatch.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


KNOWN = {
    'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
    'NetHookCore.dll': '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4',
    'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88',
    'SANPK.exe': '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2',
    'Koeinm.dll': '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841',
    'GameTool.dll': (
        '9667eff9c13d0307ba92f47d9f148d4f08bce32dd45e40bf606b27f9f2c179f1',
        'd9e6167baec2628e6af5a0532929698921eaf1a0d28054ff00b1774408fb9640',
    ),
}
_IN_GAME_DIR = ('SANPK.exe', 'GameTool.dll', 'Koeinm.dll')

# GameTool.dll DllMain OpenMutexA gate. Handle must outlive Popen SANPK /1an.
_NETHOOK_CLIENT_FLAG = b'NetHookClientRunningFlag'
_HELD_HANDLES = []
_ERROR_ALREADY_EXISTS = 183


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _root_from_cfg(cfg):
    raw = (cfg.get('game_root') or r'C:\sgi\run-3.5').replace('/', '\\')
    return Path(raw)


def _loader_udp_port(root, cfg=None):
    """SANPK reads LoaderUdpPort from UserConfig.ini (this prefix uses 4577)."""
    if cfg and cfg.get('udp_port'):
        try:
            port = int(cfg['udp_port'])
            if 1 <= port <= 65535:
                return port
        except (TypeError, ValueError):
            pass
    path = Path(root) / 'UserConfig.ini'
    if path.is_file():
        raw = path.read_bytes()
        text = None
        for enc in ('gbk', 'gb18030', 'utf-8', 'utf-16'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text:
            for line in text.splitlines():
                if line.strip().startswith('LoaderUdpPort='):
                    try:
                        port = int(line.split('=', 1)[1].strip())
                    except ValueError:
                        break
                    if 1 <= port <= 65535:
                        return port
    return 4576


def _hold_nethook_mutex():
    """CreateMutexA(NULL, FALSE, NetHookClientRunningFlag); keep the handle."""
    k32 = c.WinDLL('kernel32', use_last_error=True)
    k32.CreateMutexA.argtypes = [c.c_void_p, w.BOOL, c.c_char_p]
    k32.CreateMutexA.restype = w.HANDLE
    handle = k32.CreateMutexA(None, False, _NETHOOK_CLIENT_FLAG)
    err = c.get_last_error()
    if not handle:
        return None, err
    _HELD_HANDLES.append(handle)
    return handle, err


def _label(user32, hwnd, cls=False):
    buf = c.create_unicode_buffer(512)
    if cls:
        user32.GetClassNameW(hwnd, buf, 512)
    else:
        user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _visible_windows(user32):
    found = []
    CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    @CB
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        kids = []

        @CB
        def child(ch, __):
            if user32.IsWindowVisible(ch):
                kids.append((int(ch), _label(user32, ch, True), _label(user32, ch)))
            return True

        user32.EnumChildWindows(hwnd, child, 0)
        found.append((int(hwnd), _label(user32, hwnd), kids))
        return True

    user32.EnumWindows(visit, 0)
    return found


def _click(user32, hwnd):
    return bool(user32.PostMessageW(hwnd, 0x00F5, 0, 0))


# Align with room_list_reader: refresh then empty 确定. Do not WM_SETTEXT
# 255.255.255.255 or virtual_ip into Edit 1008 (not a room-list fix).
_SEARCH_CONFIRM = '按【确认】搜寻服务器'
# 「游戏选择」窗口必须真正出现才算等到。上限 60 秒。
_GAME_SELECT_TIMEOUT = 60
_LB_GETCOUNT = 0x018B


_LB_GETTEXT = 0x0189
_LB_GETTEXTLEN = 0x018A
_LB_SETCURSEL = 0x0186


def _game_list_count(user32):
    names = _game_list_names(user32)
    return None if names is None else len(names)


def _game_list_names(user32):
    for _h, title, kids in _visible_windows(user32):
        if title != '游戏选择':
            continue
        for hwnd, cls, _cap in kids:
            if 'listbox' not in cls.lower():
                continue
            n = int(user32.SendMessageW(hwnd, _LB_GETCOUNT, 0, 0) or 0)
            texts = []
            for i in range(min(n, 40)):
                ln = int(user32.SendMessageW(hwnd, _LB_GETTEXTLEN, i, 0) or 0)
                buf = c.create_unicode_buffer(max(ln, 1) + 2)
                user32.SendMessageW(hwnd, _LB_GETTEXT, i, c.cast(buf, c.c_void_p))
                texts.append(buf.value)
            return texts
    return None


def _join_listed_game(user32, needle):
    needle = (needle or '').strip()
    if not needle:
        return {'ok': False, 'reason': 'no_join_name'}
    for _h, title, kids in _visible_windows(user32):
        if title != '游戏选择':
            continue
        list_hwnd = None
        join_hwnd = None
        names = []
        for hwnd, cls, cap in kids:
            if 'listbox' in cls.lower():
                list_hwnd = hwnd
                n = int(user32.SendMessageW(hwnd, _LB_GETCOUNT, 0, 0) or 0)
                for i in range(min(n, 40)):
                    ln = int(user32.SendMessageW(hwnd, _LB_GETTEXTLEN, i, 0) or 0)
                    buf = c.create_unicode_buffer(max(ln, 1) + 2)
                    user32.SendMessageW(hwnd, _LB_GETTEXT, i, c.cast(buf, c.c_void_p))
                    names.append(buf.value)
            if '加入' in cap and 'button' in cls.lower() and '创建' not in cap:
                join_hwnd = hwnd
        if list_hwnd is None or join_hwnd is None:
            return {'ok': False, 'reason': 'no_controls', 'names': names}
        ranked = [i for i, text in enumerate(names) if needle in text]
        if not ranked:
            index = None
        elif len(ranked) == 1:
            index = ranked[0]
        else:
            prefer = next((i for i in ranked if 'kwankwan' in names[i]), ranked[0])
            index = prefer
        if index is None:
            return {'ok': False, 'reason': 'not_listed', 'names': names}
        user32.SendMessageW(list_hwnd, _LB_SETCURSEL, index, 0)
        _click(user32, join_hwnd)
        return {'ok': True, 'index': index, 'name': names[index]}
    return {'ok': False, 'reason': 'no_game_select'}


_CREATE_SUSPENDED = 0x00000004
_MEM_COMMIT_RESERVE = 0x3000
_PAGE_READWRITE = 0x04
_STILL_ACTIVE = 259


class STARTUPINFOW(c.Structure):
    _fields_ = [
        ('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
        ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
        ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),
        ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD),
        ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
        ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),
        ('lpReserved2', c.c_void_p), ('hStdInput', w.HANDLE),
        ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE),
    ]


class PROCESS_INFORMATION(c.Structure):
    _fields_ = [
        ('hProcess', w.HANDLE), ('hThread', w.HANDLE),
        ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD),
    ]


class _Launched:
    def __init__(self, pid, handle):
        self.pid = int(pid)
        self._handle = handle
        self._k32 = c.WinDLL('kernel32', use_last_error=True)
        self._k32.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        self._k32.GetExitCodeProcess.restype = w.BOOL
        self._k32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        self._k32.TerminateProcess.restype = w.BOOL

    def poll(self):
        code = w.DWORD()
        if not self._k32.GetExitCodeProcess(self._handle, c.byref(code)):
            return None
        if int(code.value) == _STILL_ACTIVE:
            return None
        return int(code.value)

    def terminate(self):
        self._k32.TerminateProcess(self._handle, 1)


def _launch_sanpk_with_core(sanpk, cwd, core):
    """Create SANPK suspended, LoadLibrary NetHookCore, then resume. Not a live match."""
    k32 = c.WinDLL('kernel32', use_last_error=True)
    k32.CreateProcessW.argtypes = [
        w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
        c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFOW), c.POINTER(PROCESS_INFORMATION)]
    k32.CreateProcessW.restype = w.BOOL
    k32.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k32.VirtualAllocEx.restype = c.c_void_p
    k32.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k32.WriteProcessMemory.restype = w.BOOL
    k32.GetModuleHandleW.argtypes = [w.LPCWSTR]
    k32.GetModuleHandleW.restype = w.HMODULE
    k32.GetProcAddress.argtypes = [w.HMODULE, c.c_char_p]
    k32.GetProcAddress.restype = c.c_void_p
    k32.CreateRemoteThread.argtypes = [
        w.HANDLE, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    k32.CreateRemoteThread.restype = w.HANDLE
    k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k32.WaitForSingleObject.restype = w.DWORD
    k32.ResumeThread.argtypes = [w.HANDLE]
    k32.ResumeThread.restype = w.DWORD
    k32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k32.TerminateProcess.restype = w.BOOL
    k32.CloseHandle.argtypes = [w.HANDLE]
    k32.CloseHandle.restype = w.BOOL
    si = STARTUPINFOW()
    si.cb = c.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    cmd = c.create_unicode_buffer('"%s" /1an' % sanpk)
    if not k32.CreateProcessW(str(sanpk), cmd, None, None, False, _CREATE_SUSPENDED,
                              None, str(cwd), c.byref(si), c.byref(pi)):
        return None, c.get_last_error()
    load = k32.GetProcAddress(k32.GetModuleHandleW('kernel32.dll'), b'LoadLibraryW')
    blob = (str(core) + '\0').encode('utf-16le')
    remote = k32.VirtualAllocEx(pi.hProcess, None, len(blob), _MEM_COMMIT_RESERVE, _PAGE_READWRITE)
    wrote = c.c_size_t()
    if not load or not remote or not k32.WriteProcessMemory(
            pi.hProcess, remote, blob, len(blob), c.byref(wrote)):
        k32.TerminateProcess(pi.hProcess, 1)
        k32.CloseHandle(pi.hThread)
        k32.CloseHandle(pi.hProcess)
        return None, c.get_last_error()
    tid = w.DWORD()
    thread = k32.CreateRemoteThread(pi.hProcess, None, 0, load, remote, 0, c.byref(tid))
    if thread:
        k32.WaitForSingleObject(thread, 800)
        k32.CloseHandle(thread)
    k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)
    return _Launched(pi.dwProcessId, pi.hProcess), 0


def _search_dialogs(user32, wins=None):
    """Every visible 「按【确认】搜寻服务器」 box with its buttons."""
    if wins is None:
        wins = _visible_windows(user32)
    out = []
    for _h, title, kids in wins:
        if title == _SEARCH_CONFIRM or '搜寻服务器' in title:
            out.append(kids)
    return out


def _answer_search_dialogs(user32, wins=None):
    """Answer every visible search box; the game stacks one per 刷新列表."""
    answered = 0
    for kids in _search_dialogs(user32, wins):
        for hwnd, cls, cap in kids:
            if cap in ('确定', 'OK') and 'button' in cls.lower():
                _click(user32, hwnd)
                answered += 1
                break
    return answered


def _drain_search_dialogs(user32, pump, budget=4.0, idle=1.2):
    """Clear the stack of search boxes.

    A leftover box keeps the 游戏选择 window disabled (the client is frozen
    with 「按【确认】搜寻服务器」 on top), so the helper must not leave one
    behind.  Boxes appear one after another: closing one reveals the next.
    """
    deadline = time.monotonic() + budget
    drained = 0
    last_seen = time.monotonic()
    while time.monotonic() < deadline:
        pump()
        answered = _answer_search_dialogs(user32)
        if answered:
            drained += answered
            last_seen = time.monotonic()
        elif time.monotonic() - last_seen > idle:
            break
        time.sleep(0.08)
    return drained


def _reenable_select(user32):
    """Re-enable 游戏选择 when no modal box is left (same recovery the room
    reader performs); a disabled select window means a frozen client."""
    user32.EnableWindow.argtypes = [w.HWND, w.BOOL]
    user32.EnableWindow.restype = w.BOOL
    for hwnd, title, _kids in _visible_windows(user32):
        if title == '游戏选择':
            user32.EnableWindow(hwnd, True)
            return True
    return False


def _prep_game_search(user32, pump, timeout=_GAME_SELECT_TIMEOUT):
    """Mute-ok, refresh (ONE-SHOT), answer every search box, drain the rest.

    2026-10-21: 刷新列表 used to be clicked every 80 ms until a search box
    appeared.  The game queues one MODAL 「按【确认】搜寻服务器」 box per
    accepted click, so the old loop stacked boxes (observed: 7) and left the
    client frozen with 游戏选择 disabled.  Now: click 刷新列表 at most once
    every 3 s and never after a box has been answered, then drain the stack.
    """
    user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
    user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
    user32.IsWindowVisible.argtypes = [w.HWND]
    user32.EnumWindows.argtypes = [c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM), w.LPARAM]
    user32.EnumChildWindows.argtypes = [w.HWND, c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM), w.LPARAM]
    user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, c.c_void_p]
    user32.SendMessageW.restype = w.LPARAM
    log = []
    deadline = time.monotonic() + timeout
    refreshes = 0
    answered = 0
    next_refresh = 0.0
    while time.monotonic() < deadline:
        pump()
        wins = _visible_windows(user32)
        titles = [title for _h, title, _k in wins]
        for _h, title, kids in wins:
            if '音效' in ' '.join(cap for _c, _cls, cap in kids):
                for hwnd, cls, cap in kids:
                    if cap in ('确定', 'OK') and 'button' in cls.lower():
                        _click(user32, hwnd)
                        log.append('mute_ok')
        hits = _answer_search_dialogs(user32, wins)
        if hits:
            answered += hits
            log.append('search_ok')
        # 刷新列表: one-shot per 3 s, and never once a search box was answered.
        if (not answered and refreshes < 4 and time.monotonic() >= next_refresh
                and not _search_dialogs(user32, wins)):
            for _h, title, kids in wins:
                if title == '游戏选择':
                    for hwnd, cls, cap in kids:
                        if '刷新列表' in cap:
                            _click(user32, hwnd)
                            refreshes += 1
                            next_refresh = time.monotonic() + 3
                            log.append('refresh')
                            break
        if answered:
            # Share the outer deadline (_GAME_SELECT_TIMEOUT, 60s). Do not
            # treat a vanished search dialog as the 游戏选择 window.
            while time.monotonic() < deadline:
                pump()
                titles = [title for _h, title, _k in _visible_windows(user32)]
                names = _game_list_names(user32)
                if names is not None or any(t == '游戏选择' for t in titles):
                    count = len(names) if names else 0
                    drained = _drain_search_dialogs(user32, pump)
                    if drained:
                        log.append('drain:%d' % drained)
                    reenabled = False
                    if not _search_dialogs(user32):
                        reenabled = _reenable_select(user32)
                    return {'ok': True, 'list_count': count, 'log': log,
                            'refreshes': refreshes, 'answered': answered,
                            'drained': drained, 'select_reenabled': reenabled}
                time.sleep(0.08)
            return {'ok': False, 'list_count': 0, 'wait': 'timeout', 'log': log,
                    'refreshes': refreshes, 'answered': answered}
        time.sleep(0.08)
    return {'ok': False, 'log': log, 'refreshes': refreshes, 'answered': answered}


def main():
    if c.sizeof(c.c_void_p) != 4:
        _emit({'ok': False, 'error': 'not_win32'})
        return 2
    _emit({'event': 'spawned', 'ptr': 4})
    cfg = json.load(sys.stdin)
    root = _root_from_cfg(cfg)
    for name, expected in KNOWN.items():
        allowed = expected if isinstance(expected, (tuple, list, set, frozenset)) else (expected,)
        path = root / '3I' / name if name in _IN_GAME_DIR else root / name
        if name in _IN_GAME_DIR and not path.is_file():
            path = root / name
        if name == 'NetHookCore.dll' and not path.is_file():
            path = root / name
        if not path.is_file():
            _emit({'ok': False, 'error': 'missing', 'name': name})
            return 2
        if _digest(path) not in allowed:
            _emit({'ok': False, 'error': 'hash_mismatch', 'name': name})
            return 2
    needed = ('virtual_ip', 'server', 'port', 'game_id', 'user_id', 'username', 'token')
    if any(not cfg.get(key) and cfg.get(key) != 0 for key in needed):
        _emit({'ok': False, 'error': 'grant_incomplete'})
        return 2
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(_kind, _data):
        return 0

    os.chdir(str(root))
    k32 = c.WinDLL('kernel32', use_last_error=True)
    k32.SetDllDirectoryW.argtypes = [c.c_wchar_p]
    k32.SetDllDirectoryW.restype = w.BOOL
    k32.SetDllDirectoryW(str(root))
    _emit({'event': 'cwd', 'cwd': os.getcwd()})
    dll = c.WinDLL(str(root / 'NetHookLoader.dll'))
    dll.InitDll.argtypes = [CB, c.c_ushort]
    dll.InitDll.restype = c.c_int
    # Eight-parameter StartServer recovered from NetHookLoader exports +
    # protocol-lab loader_probe. NetMsg_Start's nine fields belong to Koeinm search.
    dll.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    dll.StartServer.restype = c.c_int
    dll.StopServer.argtypes = []
    dll.FinalDll.argtypes = []
    dll.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    dll.GetSelfUserIpInfo.restype = c.c_int
    udp_port = _loader_udp_port(root, cfg)
    init_rc = dll.InitDll(callback, udp_port)
    _emit({'event': 'init', 'init_rc': init_rc, 'udp_port': udp_port})
    if init_rc != 0:
        _emit({'ok': False, 'error': 'init_failed', 'init_rc': init_rc})
        return 2
    game = None
    try:
        start_rc = dll.StartServer(
            str(cfg['virtual_ip']).encode('ascii'),
            str(cfg['server']).encode('ascii'),
            int(cfg['port']),
            str(root / 'WS2.dll').encode('ascii'),
            int(cfg['game_id']),
            int(cfg['user_id']),
            str(cfg['username']).encode('gbk'),
            str(cfg['token']).encode('gbk'),
        )
        cfg['token'] = None
        _emit({'event': 'startserver', 'start_rc': start_rc})
        if start_rc != 0:
            _emit({'ok': False, 'error': 'startserver_failed', 'start_rc': start_rc})
            return 2
        user32 = c.WinDLL('user32')
        user32.FindWindowA.argtypes = [c.c_char_p, c.c_char_p]
        user32.FindWindowA.restype = w.HWND
        user32.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        user32.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        user32.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
        msg = w.MSG()

        def pump():
            while user32.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(c.byref(msg))
                user32.DispatchMessageW(c.byref(msg))

        ip_info = c.create_string_buffer(16)

        def _relay_ready():
            return dll.GetSelfUserIpInfo(ip_info) == 0

        if cfg.get('launch_sanpk', True):
            sanpk = root / '3I' / 'SANPK.exe'
            if not sanpk.is_file():
                _emit({'ok': False, 'error': 'missing', 'name': 'SANPK.exe'})
                return 2
            mutex, mutex_err = _hold_nethook_mutex()
            if not mutex:
                _emit({'ok': False, 'error': 'mutex_create_failed', 'winerr': mutex_err})
                return 2
            _emit({
                'event': 'mutex_ready',
                'kind': 'nethook_client',
                'already': mutex_err == _ERROR_ALREADY_EXISTS,
            })
            game, launch_err = _launch_sanpk_with_core(
                sanpk, root / '3I', root / 'NetHookCore.dll')
            if game is None:
                game = subprocess.Popen(
                    [str(sanpk), '/1an'],
                    cwd=str(root / '3I'),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _emit({'event': 'sanpk_launched', 'pid': game.pid,
                       'cwd': str(root / '3I'), 'core_inject': False, 'winerr': launch_err})
            else:
                _emit({'event': 'sanpk_launched', 'pid': game.pid,
                       'cwd': str(root / '3I'), 'core_inject': True})
        registered = _relay_ready()
        until = time.monotonic() + 3
        while not registered and time.monotonic() < until:
            pump()
            time.sleep(0.01)
            registered = _relay_ready()
        _emit({'event': 'relay', 'relay_registered': registered})
        if cfg.get('launch_sanpk', True):
            search = _prep_game_search(user32, pump)
            names = _game_list_names(user32)
            payload = dict(search)
            if names is not None:
                payload['list_names'] = names
                payload['list_count'] = len(names)
            _emit({'event': 'game_search', **payload})
            join_name = str(cfg.get('join_name') or '').strip()
            if join_name:
                pump()
                joined = _join_listed_game(user32, join_name)
                _emit({'event': 'game_join', **joined})
        _emit({'ok': True, 'event': 'ready'})
        hold = time.monotonic() + int(cfg.get('hold_seconds') or 180)
        while time.monotonic() < hold:
            pump()
            if game is not None:
                # _Launched has poll() but no returncode. Reading returncode
                # raised AttributeError and the helper exited 1 while SANPK
                # was still up.
                exited = game.poll()
                if exited is not None:
                    _emit({'event': 'sanpk_exited', 'code': exited})
                    break
            time.sleep(0.05)
    finally:
        try:
            dll.StopServer()
            dll.FinalDll()
        except OSError:
            pass
        if game is not None and game.poll() is None:
            game.terminate()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        _emit({'ok': False, 'error': type(sys.exc_info()[1]).__name__})
        sys.exit(1)
