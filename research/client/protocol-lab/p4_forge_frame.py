"""P4 wire-frame forge probe (child of p2_loader_host).

Reads relay config via the parent, then:
  1. loads Koeinm + NetHookCore (hash-asserted), NetMsg_Start, own address
  2. OpenSession join against --target (the verified P2 path)
  3. control frame: NetMsg_Chat('p4ctl') over the game's own channel
  4. opens an additional raw hooked TCP socket to --target:7777 and writes
     candidate frames shaped per the receiver-side parser (0x10009520):
        wire   = htonl(5+len(payload)) + outer_type + htonl(sender) + payload
        payload= inner_type + htonl(seq) + zero pad, total >= 9 bytes
  5. holds --hold seconds with periodic IsConnected snapshots

Read-only vs game memory; all crafted bytes leave via the socket only.
Usage (argv from p2_loader_host): --target IP --session-name S --username U
      --hold N [--phases chat,o4i6,o6i6,o4i63] [--seq 0] [--sender-id N]
      [--payload-size 9]
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

KOEINM = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
NETHOOK = '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'


class SockAddr(c.Structure):
    _fields_ = [('family', c.c_ushort), ('port', c.c_ushort),
                ('ip', c.c_uint32), ('padding', c.c_char*8)]


class FdSet(c.Structure):
    _fields_ = [('count', c.c_uint), ('array', c.c_uint*64)]


class Timeval(c.Structure):
    _fields_ = [('sec', c.c_long), ('usec', c.c_long)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=20)
    ap.add_argument('--phases', default='chat,o4i6,o6i6,o4i63')
    ap.add_argument('--seq', type=lambda x: int(x, 0), default=0)
    ap.add_argument('--sender-id', type=lambda x: int(x, 0), default=0,
                    help='0 = use own virtual IP integer')
    ap.add_argument('--payload-size', type=int, default=9)
    ap.add_argument('--join-wait', type=int, default=3)
    ap.add_argument('--phase-gap', type=float, default=2.5)
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4
    root = c.c_char_p  # noqa: F841 (kept for parity with p3)
    dllpath = r'C:\sgi\run-3.5\3I\Koeinm.dll'
    import pathlib
    dllpath_p = pathlib.Path(dllpath)
    assert hashlib.sha256(dllpath_p.read_bytes()).hexdigest() == KOEINM
    assert hashlib.sha256(pathlib.Path(r'C:\sgi\run-3.5\NetHookCore.dll').read_bytes()).hexdigest() == NETHOOK
    u = c.WinDLL('user32')
    u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    msg = w.MSG()

    def pump():
        while u.PeekMessageW(c.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(c.byref(msg))
            u.DispatchMessageW(c.byref(msg))

    dll = c.WinDLL(dllpath)
    hook = c.WinDLL(r'C:\sgi\run-3.5\NetHookCore.dll')
    result = {'transport_loaded': bool(hook._handle), 'snapshots': [], 'frames': [],
              'args': {k: v for k, v in vars(args).items()}, 'python': sys.version}

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

    ws = c.WinDLL('ws2_32')
    ws.WSAGetLastError.restype = c.c_int
    ws.select.argtypes = [c.c_int, c.POINTER(FdSet), c.POINTER(FdSet),
                          c.POINTER(FdSet), c.POINTER(Timeval)]

    def build_frame(outer, sender, payload):
        return (struct.pack('!I', 5 + len(payload)) + bytes([outer])
                + struct.pack('!I', sender) + payload)

    def build_payload(inner, seq, size):
        p = bytes([inner]) + struct.pack('!I', seq)
        return p + b'\x00'*max(0, size - len(p))

    def raw_tcp_frames(sender, plan, gap):
        sock = ws.socket(2, 1, 6)  # AF_INET, SOCK_STREAM, IPPROTO_TCP
        entry = {'socket': int(sock)}
        if sock in (0, 0xFFFFFFFF):
            entry['error'] = 'socket_create'
            return entry
        dst = SockAddr()
        dst.family = 2
        dst.port = pysocket.htons(7777)
        dst.ip = struct.unpack('<I', pysocket.inet_aton(args.target))[0]
        FIONBIO = 0x8004667e
        nb = c.c_uint32(1)
        ws.ioctlsocket(sock, FIONBIO, c.byref(nb))
        rc = ws.connect(sock, c.byref(dst), 16)
        err = ws.WSAGetLastError()
        entry['connect_rc'] = int(rc)
        if rc != 0 and err not in (0, 10035, 10036):
            entry['connect_error'] = err
            ws.closesocket(sock)
            return entry
        if rc != 0:
            wset, tv = FdSet(0, (c.c_uint*64)()), Timeval(8, 0)
            wset.count, wset.array[0] = 1, sock
            ready = ws.select(0, None, c.byref(wset), None, c.byref(tv))
            entry['select_ready'] = int(ready)
            if ready != 1:
                entry['error'] = 'connect_timeout'
                ws.closesocket(sock)
                return entry
        nb.value = 0
        ws.ioctlsocket(sock, FIONBIO, c.byref(nb))
        entry['connected'] = True
        entry['sent'] = []
        for tag, outer, sender_id, inner, seq in plan:
            frame = build_frame(outer, sender_id, build_payload(inner, seq, args.payload_size))
            sent = ws.send(sock, c.create_string_buffer(frame), len(frame), 0)
            entry['sent'].append({'tag': tag, 'outer': outer, 'inner': hex(inner),
                                  'sender': sender_id, 'seq': seq,
                                  'hex': frame.hex(), 'sent': int(sent)})
            pump()
            time.sleep(gap)
        return entry

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
        result['own_id_used'] = own_id
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
        phases = args.phases.split(',')
        if 'chat' in phases:
            chat_rc = chat(b'p4ctl')
            result['chat_rc'] = int(chat_rc)
            pump()
            time.sleep(args.phase_gap)
            snapshot('after_chat')
        plans = {
            'o4i6': [('o4i6', 4, own_id, 0x06, args.seq)],
            'o6i6': [('o6i6', 6, own_id, 0x06, args.seq)],
            'o4i63': [('o4i63', 4, own_id, 0x63, args.seq)],
            'o4i1': [('o4i1', 4, own_id, 0x01, args.seq)],
            'spoof': [('spoof', 4, args.sender_id or 0, 0x06, args.seq)],
        }
        plan = []
        for name in phases:
            plan.extend(plans.get(name, []))
        if plan:
            result['raw'] = raw_tcp_frames(own_id, plan, args.phase_gap)
        result['loop_deadline_in'] = args.hold
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
