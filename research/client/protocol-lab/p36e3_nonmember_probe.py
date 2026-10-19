"""P36-E3 nonmember listen probe: transport attached, NO session join.

Runs as the P1/P2 relay child. Calls only Start@36 + window bindings and then
listens: owned-HWND notifications, native receive-slot sampling (0x14c), and
selfchecks. There is NO OpenSession, NO cmd2/cmd9/cmd1/D8 and NO uplink of any
kind. Question under test: without a game session, does the relay route room
frames to a registered transport endpoint, and is there any room-level trace.
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
    ap.add_argument('--target', required=False)
    ap.add_argument('--session-name', required=False)
    ap.add_argument('--username', required=False)
    ap.add_argument('--hold', type=int, default=900)
    ap.add_argument('--log', required=False)
    ap.add_argument('--stop-file', required=False)
    args = ap.parse_args()
    if not all((args.target, args.session_name, args.username, args.log)):
        raise ValueError('explicit_live_run_paths_required')
    assert 30 <= args.hold <= 86400 and c.sizeof(c.c_void_p) == 4
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('x', encoding='utf-8', buffering=1)
    stacks = path.with_suffix(path.suffix+'.stacks').open('x', encoding='utf-8')
    faulthandler.enable(file=stacks)
    faulthandler.dump_traceback_later(60, repeat=True, file=stacks)

    def log(event):
        event = dict(event, wall=time.time(), mono=time.monotonic(), wine_pid=os.getpid())
        stream.write(json.dumps(event, ensure_ascii=False)+'\n')

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
    hostid = exp('GetHostID@0', [], c.c_uint32)
    decode = exp('DecodeWParam@4', [c.c_uint32])
    delete = exp('DeletePacket@4', [c.c_void_p])
    accept = exp('AcceptEXIT@4', [c.c_uint32])
    connected = exp('IsConnected@0', [])
    end = exp('End@0', [])
    k = c.WinDLL('kernel32')
    k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [w.LPCWSTR], c.c_void_p
    netobj = k.GetModuleHandleW('Koeinm.dll')+0x12170

    def rd32(off):
        return c.c_uint32.from_address(netobj+off).value

    receiver = Receiver(log, decode, delete, accept)
    started = False
    last_slot_key = None
    try:
        flag = c.c_uint32()
        log({'ev': 'start_enter', 'dll_sha256': KOEINM, 'hook_loaded': bool(hook._handle),
             'mode': 'nonmember_listen_only', 'args': vars(args),
             'no_session': True, 'no_uplink': True})
        rc = start(8, 120, 7777, int(receiver.hwnd), WM_EVENT, 78731, 0, 0, c.byref(flag))
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
        own = c.c_uint32.from_address(ip_ptr.value).value if 0 < count <= 32 and ip_ptr.value else None
        log({'ev': 'relay_address', 'count': count, 'own_id': own, 'target': args.target,
             'session_name': args.session_name})
        deadline = time.monotonic()+args.hold
        next_check = time.monotonic()
        while time.monotonic() < deadline:
            receiver.pump()
            slot_size = c.c_int32.from_address(netobj+0x414c).value
            slot_sender = rd32(0x4150)
            if 0 < slot_size <= 0x4000:
                raw_slot = c.string_at(netobj+0x14c, slot_size)
                key = (slot_sender, raw_slot)
                if key != last_slot_key:
                    last_slot_key = key
                    log({'ev': 'native_slot_observed', 'sender_slot': slot_sender,
                         'length': slot_size, 'raw_hex': raw_slot.hex(),
                         'sha256': hashlib.sha256(raw_slot).hexdigest(),
                         'evidence_type': 'sampled_owned_receive_slot; possible_missed_frames'})
            if args.stop_file and Path(args.stop_file).exists():
                log({'ev': 'stop_requested'})
                break
            if time.monotonic() >= next_check:
                next_check += 10
                log({'ev': 'selfcheck', 'connected': int(connected()), 'packets': receiver.count,
                     'release_calls': receiver.freed, 'receiver_errors': receiver.errors,
                     'host_id': int(hostid()), 'tx_seq': rd32(0x8440)})
            time.sleep(.02)
        else:
            log({'ev': 'hold_expired'})
    finally:
        if started:
            log({'ev': 'end_enter'})
            log({'ev': 'end_return', 'rc': int(end())})
        receiver.close()
        log({'ev': 'closed', 'packets': receiver.count, 'release_calls': receiver.freed})
        faulthandler.cancel_dump_traceback_later()
        stream.close()
        stacks.close()


if __name__ == '__main__':
    main()
