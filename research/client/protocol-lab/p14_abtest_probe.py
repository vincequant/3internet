"""P14 A/B interop probe (child): deliver M6 cmd15 blob to host via SendData.

Static ground truth (M6): cmd15 is base-class shaped (builder 0x43765d ->
0x4359e7); host lobby consumer 0x4659d4 displays object CString.
Blob built offline per sim/m6_wire.py encode_object (same bytes as
disasm/m6-templates.json synthetic grammar).  Outer label spoofing and
member-row state from p8-p12 remain available if needed.

Flow: join -> read own DLL send counter (+0x8440) and host row gate (+0x28
in our own member table, host row 1) -> align counter to gate+1 -> send
cmd15 blob via exported _NetMsg_SendData@8 -> host SANPK should DISPLAY
the string in its lobby chat window (A/B positive feedback).
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
BLOB = bytes.fromhex(
    'ffff010011004353616e496e6574436d644f626a656374'
    '0f00000000000000000000000e70696e672d6d362d616274657374')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=30)
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
              'args': {k: v for k, v in vars(args).items()},
              'blob_len': len(BLOB), 'blob_sha256': hashlib.sha256(BLOB).hexdigest()}
    if not base:
        result['abort'] = 'no_module_base'
        print(json.dumps(result))
        return

    netobj_addr = base + 0x12170
    netobj = c.c_void_p(netobj_addr)

    def export(name, argtypes, restype=c.c_int):
        f = getattr(dll, name)
        f.argtypes = argtypes
        f.restype = restype
        return f

    start = export('_NetMsg_Start@36', [c.c_uint32]*8 + [c.POINTER(c.c_uint32)])
    getip = export('_NetMsg_GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = export('_NetMsg_OpenSession@20', [c.c_char_p, c.c_char_p, c.c_char_p, c.c_uint32, c.c_uint32])
    setdata = export('_NetMsg_SetDataWindow@8', [w.HWND, w.UINT])
    senddata = export('_NetMsg_SendData@8', [c.c_char_p, c.c_int])
    sendcmd = export('_NetMsg_SendCmd@8', [c.c_char_p, c.c_int])
    exit_session = export('_NetMsg_ExitSession@0', [])
    end = export('_NetMsg_End@0', [])

    host_id = struct.unpack('!I', pysocket.inet_aton(args.target))[0]

    def rd32(rva):
        v = c.c_uint32()
        c.memmove(c.byref(v), c.c_void_p(netobj_addr + rva), 4)
        return v.value

    def wr32(rva, val):
        c.memmove(c.c_void_p(netobj_addr + rva), struct.pack('<I', val), 4)

    def member_ids():
        ptr = c.c_uint32()
        c.memmove(c.byref(ptr), c.c_void_p(netobj_addr + 0x43b8), 4)
        rows = []
        if ptr.value:
            for i in range(4):
                rid = c.c_uint32()
                c.memmove(c.byref(rid), c.c_void_p(ptr.value + 0x164 * i), 4)
                name = (c.c_char * 16).from_address(ptr.value + 0x164 * i + 4)
                rows.append({'idx': i, 'id': hex(rid.value),
                             'name': name.value.decode('gbk', 'replace')})
        return rows

    def host_gate_seq():
        ptr = c.c_uint32()
        c.memmove(c.byref(ptr), c.c_void_p(netobj_addr + 0x43b8), 4)
        if not ptr.value:
            return None
        # host row = index 1 (row0 = self after join)
        seq = c.c_uint32()
        c.memmove(c.byref(seq), c.c_void_p(ptr.value + 0x164 * 1 + 0x28), 4)
        return seq.value

    try:
        flag = c.c_uint32()
        result['start_rc'] = start(8, 64, 7777, 100, 100, 78731, 0, 0, c.byref(flag))
        pump()
        ip_ptr = c.c_void_p()
        ip_count = getip(c.byref(ip_ptr))
        own = None
        if 0 < ip_count <= 20 and ip_ptr.value:
            addresses = list((c.c_uint32*ip_count).from_address(ip_ptr.value))
            own = addresses[0]
        if not own:
            result['abort'] = 'no_relay_address'
            return
        result['own_id'] = own
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
        result['rows_after_join'] = member_ids()
        gate = host_gate_seq()
        ctr = rd32(0x8440)
        result['gate_host_seq28'] = hex(gate or 0)
        result['dll_send_ctr_8440'] = ctr
        # align our send counter so next reliable seq passes the host gate:
        # gate requires seq == host_row+0x28+1 after p12 advanced it
        aligned = ((gate or 0) + 1) & 0xffffffff
        wr32(0x8440, aligned)
        result['ctr_set_to'] = aligned

        rc = int(senddata(BLOB, len(BLOB)))
        result['cmd15_senddata_rc'] = rc
        pump(); time.sleep(args.phase_gap)
        rc2 = int(senddata(BLOB, len(BLOB)))
        result['cmd15_senddata_rc2'] = rc2
        pump(); time.sleep(args.phase_gap)

        # also try cmd9(a=0) shape? not in this run: keep single-variable A/B
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
