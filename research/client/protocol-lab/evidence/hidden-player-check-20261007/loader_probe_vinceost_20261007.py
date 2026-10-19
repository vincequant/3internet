"""Original relay DLL in a disposable process; grant arrives on stdin only."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    assert os.environ.get('WINEPREFIX') == '/Users/vkquant/Library/Application Support/SGI-Wine/prefix-monitor'
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.load(sys.stdin)
    assert cfg['username'] == 'vinceost' and cfg['game_id'] == 1001 and isinstance(cfg['room_id'], int) and cfg['room_id'] > 0
    root = Path(r'C:\sgi\run-3.5')
    hashes = {'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
              'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88'}
    for name, digest in hashes.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
    callback_events = []
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)
    @CB
    def callback(kind, data):
        callback_events.append(1)  # No addresses, pointer contents or session data logged.
        return 0
    dll = c.WinDLL(str(root/'NetHookLoader.dll'))
    dll.InitDll.argtypes = [CB, c.c_ushort]
    dll.InitDll.restype = c.c_int
    dll.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                               c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    dll.StartServer.restype = c.c_int
    dll.StopServer.argtypes = []
    dll.FinalDll.argtypes = []
    dll.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    dll.GetSelfUserIpInfo.restype = c.c_int
    result = {'init_rc': dll.InitDll(callback, 4578), 'uses_original_relay_dll': True}
    if result['init_rc'] != 0:
        print(json.dumps(result));return
    try:
        result['start_rc'] = dll.StartServer(cfg['virtual_ip'].encode('ascii'),
            cfg['server'].encode('ascii'), cfg['port'], str(root/'WS2.dll').encode('ascii'),
            cfg['game_id'], cfg['user_id'], cfg['username'].encode('gbk'), cfg['token'].encode('gbk'))
        del cfg
        u = c.WinDLL('user32')
        u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
        msg = w.MSG()
        def pump():
            while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
        ip_info = c.create_string_buffer(16)
        until = time.monotonic()+5
        while time.monotonic() < until:
            pump();time.sleep(0.02)
            if dll.GetSelfUserIpInfo(ip_info) == 0:
                break
        result['relay_registered'] = dll.GetSelfUserIpInfo(ip_info) == 0
        result['queries'] = []
        for attempt in range(3):
            proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).with_name('koeinm_probe.py')),
                '--dll', str(root/'3I/Koeinm.dll'), '--target', '255.255.255.255',
                '--port', '7777', '--app-id', '78731', '--with-nethook'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic()+5
            while proc.poll() is None and time.monotonic() < deadline:
                pump();time.sleep(0.02)
            if proc.poll() is None:
                proc.kill()
            out, _ = proc.communicate()
            result['queries'].append({'exit': proc.returncode,
                'results': [json.loads(line) for line in out.splitlines() if line.startswith('{')]})
        result['callback_count'] = len(callback_events)
    finally:
        dll.StopServer();dll.FinalDll()
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__}));sys.exit(1)
