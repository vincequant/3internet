"""P6 channel forge probe (child): dump own member table + channel list, then
forge with the ids that actually exist.

Ground truth steps, all inside our own probe process (no cross-process writes):
  dump  : netobj[0]; member rows (+0x00 id, +0x04 name, +0x2c/+0x30/+0x34);
          channel list at netobj+0x20 (node->0 socket, node->4 id, node->8 next)
  forge : writer 0x10002df0(netobj, node_id, inner, len) for EVERY discovered
          channel id, inner = [0x06][seq=0][pad4] -> host gate bypass -> +0x2c
  chat  : NetMsg_Chat reference (known-good delivery)
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

    def u32(addr):
        return struct.unpack('<I', (c.c_char*4).from_address(addr).raw)[0]

    def read(addr, n):
        return (c.c_char*n).from_address(addr).raw

    writer = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_char_p, c.c_uint32)(
        base + 0x2df0)

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

    host_id = struct.unpack('!I', pysocket.inet_aton(args.target))[0]
    inner06 = bytes([0x06]) + struct.pack('!I', 0) + b'\x00'*4

    def dump_channels(tag):
        d = {'tag': tag}
        try:
            d['netobj0_own_id'] = u32(netobj_addr)
            d['flag_148_is_host'] = u32(netobj_addr + 0x148)
            table, count = u32(netobj_addr + 0x43b8), u32(netobj_addr + 0x43bc)
            d['member_count'] = count
            rows = []
            if table and count:
                raw = read(table, min(count, 8)*0x164)
                for i in range(min(count, 8)):
                    row = raw[i*0x164:(i+1)*0x164]
                    rows.append({'i': i, 'id': struct.unpack_from('<I', row, 0)[0],
                                 'name': row[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                                 'c2c': struct.unpack_from('<I', row, 0x2c)[0],
                                 'c30': struct.unpack_from('<I', row, 0x30)[0],
                                 'c34': struct.unpack_from('<I', row, 0x34)[0]})
            d['members'] = rows
            nodes, head, guard = [], u32(netobj_addr + 0x20), 0
            while head and guard < 16:
                guard += 1
                nodes.append({'socket': u32(head), 'id': u32(head + 4)})
                head = u32(head + 8)
            d['channels'] = nodes
        except Exception as e:
            d['error'] = f'{type(e).__name__}: {e}'
        result.setdefault('dumps', []).append(d)
        return d

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
        dump_channels('after_join')
        result['chat_rc'] = int(chat(b'p6ctl'))
        pump()
        time.sleep(args.phase_gap)
        after_chat = dump_channels('after_chat')
        candidates = [(n['id'], n['socket']) for n in after_chat.get('channels', [])]
        result['forge_attempts'] = []
        for cid, sock in candidates:
            rc = writer(c.c_void_p(netobj_addr), cid, inner06, len(inner06))
            result['forge_attempts'].append({'id': cid, 'socket': sock, 'rc': int(rc),
                                             'data': inner06.hex()})
            pump()
            time.sleep(args.phase_gap)
        deadline = time.monotonic() + args.hold
        while time.monotonic() < deadline:
            pump()
            time.sleep(0.05)
        dump_channels('before_leave')
    finally:
        result['cleanup'] = {'exit_rc': exit_session(), 'end_rc': end()}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__, 'detail': str(e)[:200]}))
        sys.exit(1)
