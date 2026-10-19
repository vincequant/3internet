"""Main-prefix grok-bot topology. Grant on stdin. Never launches SANPK.

cfg.udp_port is InitDll only (4577 or 4578). Does not write UserConfig.
Never print password or token.
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


MAIN_PREFIX = '/Users/vk/Library/Application Support/SGI-Wine/prefix-sikarugir10'
HASHES = {
    'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
    'NetHookCore.dll': '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4',
    'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88',
    'Koeinm.dll': '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841',
}


def main():
    prefix = os.environ.get('WINEPREFIX') or ''
    if Path(prefix).expanduser().resolve() != Path(MAIN_PREFIX).resolve():
        print(json.dumps({'ok': False, 'error': 'wrong_prefix'}))
        return
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.load(sys.stdin)
    udp_port = int(cfg.get('udp_port') or 0)
    if udp_port not in (4577, 4578):
        print(json.dumps({'ok': False, 'error': 'udp_port'}))
        return
    if int(cfg.get('game_id') or 0) != 1001 or int(cfg.get('room_id') or 0) != 1001:
        print(json.dumps({'ok': False, 'error': 'wrong_line'}))
        return
    if not (cfg.get('username') and cfg.get('virtual_ip') and cfg.get('server')
            and cfg.get('token') and cfg.get('user_id') is not None):
        print(json.dumps({'ok': False, 'error': 'grant_incomplete'}))
        return
    root = Path(r'C:\sgi\run-3.5')
    os.chdir(str(root))
    k32 = c.WinDLL('kernel32', use_last_error=True)
    k32.SetDllDirectoryW.argtypes = [c.c_wchar_p]
    k32.SetDllDirectoryW.restype = w.BOOL
    k32.SetDllDirectoryW(str(root))
    for name, digest in HASHES.items():
        path = root / '3I' / name if name == 'Koeinm.dll' else root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            print(json.dumps({'ok': False, 'error': 'hash_mismatch', 'name': name}))
            return
    callback_events = []
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(_kind, _data):
        callback_events.append(1)
        return 0

    dll = c.WinDLL(str(root / 'NetHookLoader.dll'))
    dll.InitDll.argtypes = [CB, c.c_ushort]
    dll.InitDll.restype = c.c_int
    dll.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    dll.StartServer.restype = c.c_int
    dll.StopServer.argtypes = []
    dll.FinalDll.argtypes = []
    dll.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    dll.GetSelfUserIpInfo.restype = c.c_int
    result = {
        'ok': False,
        'udp_port': udp_port,
        'init_rc': dll.InitDll(callback, udp_port),
        'uses_original_relay_dll': True,
        'launched_sanpk': False,
    }
    if result['init_rc'] != 0:
        print(json.dumps(result, ensure_ascii=True))
        return
    try:
        result['start_rc'] = dll.StartServer(
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
        del cfg
        u = c.WinDLL('user32')
        u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
        msg = w.MSG()

        def pump():
            while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                u.TranslateMessage(c.byref(msg))
                u.DispatchMessageW(c.byref(msg))

        ip_info = c.create_string_buffer(16)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            pump()
            time.sleep(0.02)
            if dll.GetSelfUserIpInfo(ip_info) == 0:
                break
        result['relay_registered'] = dll.GetSelfUserIpInfo(ip_info) == 0
        result['queries'] = []
        probe = Path(__file__).with_name('koeinm_probe.py')
        for _attempt in range(3):
            proc = subprocess.Popen(
                [sys.executable, '-X', 'utf8', str(probe),
                 '--dll', str(root / '3I/Koeinm.dll'),
                 '--target', '255.255.255.255',
                 '--port', '7777', '--app-id', '78731', '--with-nethook'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 5
            while proc.poll() is None and time.monotonic() < deadline:
                pump()
                time.sleep(0.02)
            if proc.poll() is None:
                proc.kill()
            out, _err = proc.communicate()
            rows = []
            for line in out.splitlines():
                if line.startswith('{'):
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            result['queries'].append({'exit': proc.returncode, 'results': rows})
        result['callback_count'] = len(callback_events)
        rooms = []
        for query in result['queries']:
            for row in query.get('results') or []:
                rooms.extend(row.get('rooms') or [])
        result['room_names'] = sorted({(r.get('name'), r.get('host')) for r in rooms if r.get('name')})
        result['ok'] = True
    finally:
        try:
            dll.StopServer()
            dll.FinalDll()
        except OSError:
            pass
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'ok': False, 'error_type': type(sys.exc_info()[1]).__name__}))
        sys.exit(1)
