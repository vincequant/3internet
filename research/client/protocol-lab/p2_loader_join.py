"""P2 uninvited OpenSession: original DLL join to a foreign room, own grant.

Runs after StartServer on the probe's own relay identity. Sequence: identity,
directed search confirmation, OpenSession to the explicit target, member-table
snapshots of THIS probe session only, bounded hold, clean exit. Evidence only.
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


def main():
    assert os.environ.get('WINEPREFIX') == '/Users/vkquant/Library/Application Support/SGI-Wine/prefix-monitor'
    assert c.sizeof(c.c_void_p) == 4
    cfg = json.load(sys.stdin)
    for key in ('username', 'virtual_ip', 'server', 'port', 'game_id', 'user_id', 'token', 'search_target', 'session_name'):
        assert cfg.get(key), f'missing {key}'
    hold_seconds = int(cfg.get('hold_seconds', 20))
    root = Path(r'C:\sgi\run-3.5')
    hashes = {'NetHookLoader.dll': '11e598eb1239fa57ccbb05e652274e281f168330596f4f4769426ace466d666a',
              'WS2.dll': '79177c75b068acf3b52654e3ad6d63ee70ab2bfac7a38a53a43eca79f4801b88'}
    for name, digest in hashes.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
    dllpath = root/'3I/Koeinm.dll'
    assert hashlib.sha256(dllpath.read_bytes()).hexdigest() == '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
    assert hashlib.sha256((root/'NetHookCore.dll').read_bytes()).hexdigest() == '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'
    u = c.WinDLL('user32')
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    k = c.WinDLL('kernel32')
    k.GlobalFree.argtypes = [c.c_void_p]
    k.GlobalFree.restype = c.c_void_p
    msg = w.MSG()
    u.PeekMessageW(c.byref(msg), None, 0, 0, 0)

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    loader = c.WinDLL(str(root/'NetHookLoader.dll'))
    loader.InitDll.argtypes = [c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32), c.c_ushort]
    loader.InitDll.restype = c.c_int
    loader.StartServer.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
                                   c.c_uint32, c.c_uint32, c.c_char_p, c.c_char_p]
    loader.StartServer.restype = c.c_int
    loader.StopServer.argtypes = []
    loader.FinalDll.argtypes = []
    loader.GetSelfUserIpInfo.argtypes = [c.c_void_p]
    loader.GetSelfUserIpInfo.restype = c.c_int
    CB = c.WINFUNCTYPE(c.c_int, c.c_uint32, c.c_uint32)

    @CB
    def callback(kind, data):
        return 0

    result = {'init_rc': loader.InitDll(callback, 4578), 'uses_original_relay_dll': True,
              'target': cfg['search_target'], 'session_name': cfg['session_name']}
    if result['init_rc'] != 0:
        print(json.dumps(result))
        return
    dll = c.WinDLL(str(dllpath))
    start = getattr(dll, '_NetMsg_Start@36')
    start.argtypes = [c.c_uint32]*8 + [c.POINTER(c.c_uint32)]
    start.restype = c.c_int
    search = getattr(dll, '_NetMsg_SearchSession@12')
    search.argtypes = [c.c_char_p, w.HWND, w.UINT]
    search.restype = c.c_int
    getip = getattr(dll, '_NetMsg_GetIPAddress@4')
    getip.argtypes = [c.POINTER(c.c_void_p)]
    getip.restype = c.c_int
    opens = getattr(dll, '_NetMsg_OpenSession@20')
    opens.argtypes = [c.c_char_p, c.c_char_p, c.c_char_p, c.c_uint32, c.c_uint32]
    opens.restype = c.c_int
    connected = getattr(dll, '_NetMsg_IsConnected@0')
    connected.restype = c.c_int
    setdata = getattr(dll, '_NetMsg_SetDataWindow@8')
    setdata.argtypes = [w.HWND, w.UINT]
    exit_session = getattr(dll, '_NetMsg_ExitSession@0')
    end = getattr(dll, '_NetMsg_End@0')
    end.restype = c.c_int
    base = dll._handle + 0x12170

    def snapshot(stage):
        count = c.c_uint32.from_address(base+0x43bc).value
        ptr = c.c_uint32.from_address(base+0x43b8).value
        members = []
        if count and ptr:
            for i in range(min(count, 8)):
                raw = c.string_at(ptr + i*0x164, 35)
                members.append({'id': str(struct.unpack_from('<I', raw)[0]),
                                'name': raw[4:35].split(b'\0')[0].decode('gbk', 'replace')})
        result.setdefault('snapshots', []).append({'stage': stage, 'connected': connected(),
            'count': count, 'members': members})

    try:
        result['start_rc'] = loader.StartServer(cfg['virtual_ip'].encode('ascii'),
            cfg['server'].encode('ascii'), cfg['port'], str(root/'WS2.dll').encode('ascii'),
            cfg['game_id'], cfg['user_id'], cfg['username'].encode('gbk'), cfg['token'].encode('gbk'))
        ip_info = c.create_string_buffer(16)
        until = time.monotonic()+5
        while time.monotonic() < until:
            pump()
            time.sleep(0.02)
            if loader.GetSelfUserIpInfo(ip_info) == 0:
                break
        result['relay_registered'] = loader.GetSelfUserIpInfo(ip_info) == 0
        result['start_game_rc'] = start(8, 64, 7777, 100, 100, 78731, 0, 0, c.byref(c.c_uint32()))
        pump()
        ip_ptr = c.c_void_p()
        ip_count = getip(c.byref(ip_ptr))
        own = None
        if 0 < ip_count <= 20 and ip_ptr.value:
            addresses = list((c.c_uint32*ip_count).from_address(ip_ptr.value))
            result['probe_addresses'] = ['.'.join(str(x) for x in struct.pack('!I', v)) for v in addresses]
            own = addresses[0]
        snapshot('baseline')
        rc = search(cfg['search_target'].encode('ascii'), None, 0x2403)
        pump()
        found = []
        while u.PeekMessageW(c.byref(msg), None, 0x2403, 0x2403, 1):
            if msg.wParam == 5 and msg.lParam:
                raw = c.string_at(msg.lParam, 80)
                found.append({'id': str(struct.unpack_from('<I', raw)[0]),
                    'name': raw[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                    'host': raw[35:66].split(b'\0')[0].decode('gbk', 'replace')})
                k.GlobalFree(c.c_void_p(msg.lParam))
        result['directed_search'] = {'rc': rc, 'rooms': found}
        if not own:
            result['abort'] = 'no_own_address'
            return
        setdata(None, 0x2462)
        rc = opens(cfg['search_target'].encode('ascii'), cfg['session_name'].encode('gbk'),
                   cfg['username'].encode('gbk'), own, 3000)
        result['open_session'] = {'rc': rc, 'only_transport_handshake': True}
        pump()
        snapshot('after_join')
        if rc == 0:
            deadline = time.monotonic() + hold_seconds
            last = 0
            while time.monotonic() < deadline:
                pump()
                if time.monotonic() - last >= 5:
                    snapshot('held_connection')
                    last = time.monotonic()
                time.sleep(0.05)
    finally:
        result['cleanup'] = {'exit_rc': exit_session(), 'end_rc': end()}
        try:
            loader.StopServer()
            loader.FinalDll()
        except Exception:
            pass
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        import struct
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__}))
        sys.exit(1)
