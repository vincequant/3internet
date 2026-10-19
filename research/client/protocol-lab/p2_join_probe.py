"""P2 child probe: NetHookCore-hooked OpenSession to an explicit foreign room.

Mirrors the verified transport_join_probe flow but takes explicit arguments
and never asserts a specific local identity. Runs inside the relay-registered
loader's machine; one bounded hold; clean ExitSession/End.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

KOEINM = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
NETHOOK = '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=20)
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4
    root = Path(r'C:\sgi\run-3.5')
    dllpath = root/'3I/Koeinm.dll'
    assert hashlib.sha256(dllpath.read_bytes()).hexdigest() == KOEINM
    assert hashlib.sha256((root/'NetHookCore.dll').read_bytes()).hexdigest() == NETHOOK
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

    dll = c.WinDLL(str(dllpath))
    hook = c.WinDLL(str(root/'NetHookCore.dll'))
    result = {'transport_loaded': bool(hook._handle), 'snapshots': [], 'notifications': []}

    def export(name, argtypes, restype=c.c_int):
        f = getattr(dll, name)
        f.argtypes = argtypes
        f.restype = restype
        return f

    start = export('_NetMsg_Start@36', [c.c_uint32]*8 + [c.POINTER(c.c_uint32)])
    search = export('_NetMsg_SearchSession@12', [c.c_char_p, w.HWND, w.UINT])
    getip = export('_NetMsg_GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = export('_NetMsg_OpenSession@20', [c.c_char_p, c.c_char_p, c.c_char_p, c.c_uint32, c.c_uint32])
    connected = export('_NetMsg_IsConnected@0', [])
    setdata = export('_NetMsg_SetDataWindow@8', [w.HWND, w.UINT])
    exit_session = export('_NetMsg_ExitSession@0', [])
    end = export('_NetMsg_End@0', [])
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
        result['snapshots'].append({'stage': stage, 'connected': connected(),
            'count': count, 'members': members})

    try:
        flag = c.c_uint32()
        result['start_rc'] = start(8, 64, 7777, 100, 100, 78731, 0, 0, c.byref(flag))
        pump()
        ip_ptr = c.c_void_p()
        ip_count = getip(c.byref(ip_ptr))
        own = None
        if 0 < ip_count <= 20 and ip_ptr.value:
            addresses = list((c.c_uint32*ip_count).from_address(ip_ptr.value))
            result['probe_addresses'] = ['.'.join(str(x) for x in struct.pack('!I', v)) for v in addresses]
            own = addresses[0]
        snapshot('baseline')
        rc = search(args.target.encode('ascii'), None, 0x2403)
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
            result['abort'] = 'no_relay_address'
            return
        setdata(None, 0x2462)
        rc = opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                   args.username.encode('gbk'), own, 3000)
        result['open_session'] = {'rc': rc}
        pump()
        snapshot('after_join')
        if rc == 0:
            deadline = time.monotonic() + args.hold
            last = 0
            while time.monotonic() < deadline:
                pump()
                while u.PeekMessageW(c.byref(msg), None, 0x2462, 0x2462, 1):
                    result['notifications'].append({'wparam': int(msg.wParam), 'has_lparam': bool(msg.lParam)})
                if time.monotonic() - last >= 5:
                    snapshot('held_connection')
                    last = time.monotonic()
                time.sleep(0.05)
    finally:
        result['cleanup'] = {'exit_rc': exit_session(), 'end_rc': end()}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__}))
        sys.exit(1)
