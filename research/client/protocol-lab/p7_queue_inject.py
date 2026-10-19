"""P7 queue-inject probe (child): deliver forged frames via 0x100060b0.

Ground truth from p6: client channel list is EMPTY (0x10002df0 unusable);
real chat rides the message queue. 0x100060b0(netobj, buf) parses
buf[+9]=len(<=0x80), buf[+0xd]=sender, buf[+0x11]=target, buf[+0x15]=data
and queues {sender,len,data} into the receive path -- full sender control.

Phases:
  chat    : NetMsg_Chat reference capture
  q46     : 0x100060b0 with observed 27B chat layout (X=88010044, text p7ctl)
  q06     : same layout, data = inner [0x06][seq=0][pad] -> expect host +0x2c=1
  q06spoof: same, sender field = host id (spoof test for A-path kick)
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
X_FIELD = bytes.fromhex('88010044')  # observed on every real chat frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=20)
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
    result = {'transport_loaded': bool(hook._handle), 'module_base': hex(base or 0),
              'args': {k: v for k, v in vars(args).items()}}
    if not base:
        result['abort'] = 'no_module_base'
        print(json.dumps(result))
        return

    netobj_addr = base + 0x12170
    inject = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_char_p)(base + 0x60b0)

    def export(name, argtypes, restype=c.c_int):
        f = getattr(dll, name)
        f.argtypes = argtypes
        f.restype = restype
        return f

    start = export('_NetMsg_Start@36', [c.c_uint32]*8 + [c.POINTER(c.c_uint32)])
    getip = export('_NetMsg_GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = export('_NetMsg_OpenSession@20', [c.c_char_p, c.c_char_p, c.c_char_p, c.c_uint32, c.c_uint32])
    setdata = export('_NetMsg_SetDataWindow@8', [w.HWND, w.UINT])
    chat = export('_NetMsg_Chat@4', [c.c_char_p])
    exit_session = export('_NetMsg_ExitSession@0', [])
    end = export('_NetMsg_End@0', [])

    host_id = struct.unpack('!I', pysocket.inet_aton(args.target))[0]

    def qbuf(sender, target, data):
        body = bytes([0x46]) + b'\x00'*4 + X_FIELD + struct.pack('!I', len(data))
        body += struct.pack('!I', sender) + struct.pack('!I', target) + data + b'\x00'
        return body

    def run(tag, sender, target, data):
        buf = qbuf(sender, target, data)
        pump()
        rc = inject(c.c_void_p(netobj_addr), buf)
        result.setdefault('injects', []).append(
            {'tag': tag, 'sender': sender, 'target': hex(target & 0xffffffff),
             'rc': int(rc), 'len': len(data), 'buf': buf.hex()})
        pump()
        time.sleep(args.phase_gap)

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
        result['own_id'] = own
        result['host_id'] = host_id
        setdata(None, 0x2462)
        rc = opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                   args.username.encode('gbk'), own, 3000)
        result['open_session'] = {'rc': rc}
        pump()
        if rc != 0:
            result['abort'] = 'join_failed'
            return
        time.sleep(args.join_wait)
        pump()
        result['chat_rc'] = int(chat(b'p7ctl'))
        time.sleep(args.phase_gap)
        run('q46', own, 0xffffffff, b'p7q46\x00')
        run('q06', own, 0xffffffff, bytes([0x06]) + struct.pack('!I', 0) + b'\x00'*4)
        run('q06spoof', host_id, 0xffffffff, bytes([0x06]) + struct.pack('!I', 0) + b'\x00'*4)
        deadline = time.monotonic() + args.hold
        while time.monotonic() < deadline:
            pump()
            time.sleep(0.05)
    finally:
        result['cleanup'] = {'exit_rc': exit_session(), 'end_rc': end()}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__, 'detail': str(e)[:200]}))
        sys.exit(1)
