"""P31 row-less join probe: join via OpenSession only, never cmd2.

Stage-1 smoke of the factionless-spectator path. The host application claims
member rows only through type1 (free-row scan state==0 && w4==0 && id==0,
silent drop when none qualifies), so a join without any app-layer registration
must leave every machine's application row table untouched while the DLL still
relays broadcasts to us. No cmd2, no cmd9, no cmd23, no foreign-memory write;
packets are copied to the log then DeletePacket'd; the session is left through
the normal ExitSession path. Uses the existing authenticated P1/P2 relay.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p28_window import Receiver, WM_EVENT, WM_DATA, WM_CHAT
from p20_cmd2_verified_probe import KOEINM, NETHOOK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=3600)
    ap.add_argument('--log', required=True)
    ap.add_argument('--stop-file', help='Owned probe normal-exit request')
    args = ap.parse_args()
    assert 30 <= args.hold <= 86400 and c.sizeof(c.c_void_p) == 4
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('x', encoding='utf-8', buffering=1)
    stacks = path.with_suffix(path.suffix+'.stacks').open('x', encoding='utf-8')
    faulthandler.enable(file=stacks)
    faulthandler.dump_traceback_later(60, repeat=True, file=stacks)

    received_by_type = {}

    def log(event):
        event = dict(event, wall=time.time(), mono=time.monotonic(), wine_pid=os.getpid())
        stream.write(json.dumps(event, ensure_ascii=False)+'\n')
        if event['ev'] == 'received_packet':
            key = 'type_%d' % event.get('type', -1)
            received_by_type[key] = received_by_type.get(key, 0)+1

    root = Path(r'C:\sgi\run-3.5')
    assert hashlib.sha256((root/'3I/Koeinm.dll').read_bytes()).hexdigest() == KOEINM
    assert hashlib.sha256((root/'NetHookCore.dll').read_bytes()).hexdigest() == NETHOOK
    dll = c.WinDLL(str(root/'3I/Koeinm.dll'))
    hook = c.WinDLL(str(root/'NetHookCore.dll'))

    def exp(name, params, result=c.c_int):
        f = getattr(dll, '_NetMsg_'+name)
        f.argtypes, f.restype = params, result
        return f

    start = exp('Start@36', [c.c_uint32]*8+[c.POINTER(c.c_uint32)])
    setdata = exp('SetDataWindow@8', [w.HWND, w.UINT])
    setchat = exp('SetChatWindow@8', [w.HWND, w.UINT])
    getip = exp('GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = exp('OpenSession@20', [c.c_char_p]*3+[c.c_uint32]*2)
    connected = exp('IsConnected@0', [])
    exit_session = exp('ExitSession@0', [])
    end = exp('End@0', [])
    k = c.WinDLL('kernel32')
    k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [w.LPCWSTR], c.c_void_p
    netobj = k.GetModuleHandleW('Koeinm.dll')+0x12170

    def rd32(off):
        return c.c_uint32.from_address(netobj+off).value

    def own_rows():
        ptr = rd32(0x43b8)
        rows = []
        if ptr:
            for i in range(8):
                raw = c.string_at(ptr+0x164*i, 0x60)
                rows.append({'idx': i, 'id': struct.unpack_from('<I', raw)[0],
                    'name': raw[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                    'sA': struct.unpack_from('<I', raw, 0x24)[0],
                    'sB': struct.unpack_from('<I', raw, 0x28)[0],
                    'reconn': struct.unpack_from('<I', raw, 0x34)[0],
                    'failed': struct.unpack_from('<I', raw, 0x38)[0]})
        return rows

    receiver = Receiver(log, exp('DecodeWParam@4', [c.c_uint32]),
                        exp('DeletePacket@4', [c.c_void_p]),
                        exp('AcceptEXIT@4', [c.c_uint32]))
    started = joined = False
    try:
        flag = c.c_uint32()
        log({'ev': 'start_enter', 'dll_sha256': KOEINM, 'hook_loaded': bool(hook._handle),
             'mode': 'rowless_join_capture_only', 'args': vars(args)})
        rc = start(8, 64, 7777, int(receiver.hwnd), WM_EVENT, 78731, 0, 0, c.byref(flag))
        started = rc == 0
        log({'ev': 'start_return', 'rc': rc, 'winsock_flag': flag.value})
        if not started:
            return
        log({'ev': 'window_bindings', 'data_rc': setdata(receiver.hwnd, WM_DATA),
             'chat_rc': setchat(receiver.hwnd, WM_CHAT),
             'event_hwnd': rd32(0x84dc), 'event_msg': rd32(0x84e0),
             'data_hwnd': rd32(0x84e4), 'data_msg': rd32(0x84e8)})
        ip_ptr = c.c_void_p()
        count = getip(c.byref(ip_ptr))
        if not 0 < count <= 32 or not ip_ptr.value:
            log({'ev': 'abort', 'reason': 'no_relay_address'})
            return
        own = c.c_uint32.from_address(ip_ptr.value).value
        log({'ev': 'open_enter', 'own_id': own, 'target': args.target})
        rc = opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                   args.username.encode('gbk'), own, 3000)
        joined = rc == 0
        log({'ev': 'open_return', 'rc': rc})
        receiver.pump()
        if not joined:
            log({'ev': 'verdict', 'branch': 'A2_dll_refused_or_failed',
                 'note': 'OpenSession rc!=0; no row claimed, no cmd2 sent'})
            return
        log({'ev': 'verdict', 'branch': 'A1_dll_accepted_pending_host_watch',
             'rows_own_dll': own_rows(),
             'note': 'Join returned 0. App-layer row claim never happens by '
                     'design (no cmd2). A1 stands if host_watch later shows '
                     'our id as a DLL member and the host app adds no row.'})
        deadline = time.monotonic()+args.hold
        next_check = time.monotonic()
        while time.monotonic() < deadline:
            receiver.pump()
            if args.stop_file and Path(args.stop_file).exists():
                log({'ev': 'stop_requested'})
                break
            if time.monotonic() >= next_check:
                next_check += 10
                log({'ev': 'selfcheck', 'connected': int(connected()), 'rows': own_rows(),
                     'packets': receiver.count, 'release_calls': receiver.freed,
                     'receiver_errors': receiver.errors, 'received_by_type': dict(received_by_type)})
            time.sleep(.02)
        else:
            log({'ev': 'hold_expired'})
    finally:
        # Stop native producers while the owned HWND still exists, then drain.
        if joined:
            log({'ev': 'exit_enter'})
            log({'ev': 'exit_return', 'rc': int(exit_session())})
        if started:
            log({'ev': 'end_enter'})
            log({'ev': 'end_return', 'rc': int(end())})
        receiver.close()
        log({'ev': 'closed', 'packets': receiver.count, 'release_calls': receiver.freed,
             'received_by_type': dict(received_by_type)})
        faulthandler.cancel_dump_traceback_later()
        stream.close()
        stacks.close()


if __name__ == '__main__':
    main()
