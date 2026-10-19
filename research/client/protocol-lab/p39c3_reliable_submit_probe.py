# -*- coding: utf-8 -*-
"""P39c3 reliable-submit probe (child, Wine): E3 non-member listener + ONE
native reliable submit, gated, never retried.

Based on p36e3_nonmember_probe.py (same Start@36 / window / slot machinery;
no OpenSession, no cmd2/cmd9/cmd1/D8, no other uplink of any kind). Adds the
P34-proven "24f0 pattern" ABI on the same netobj:

  0x4b60  four-arg __cdecl (netobj, target_id, buf, len) reliable submit
  0x4c80  one-arg  __cdecl (netobj) GetHostOrSelfID

The subject of the experiment: what a *sessionless* Koeinm does with a
reliable submit - whether anything is emitted at all and of which wire class.
Pre/post native state is logged (connected / state +0x84a8 / tx_seq +0x8440 /
host_id); the call itself is logged before and after; a crash is contained by
the already-open log stream (single call, no retry).

Gate: --submit-gate <path>; fires once, --submit-delay seconds after a
successful Start, when the gate file exists (json accepts {"target": int,
"body_hex": "<optional>"}). Default body = BE32(9) + BE32(own_id) - an
undefined control class the host-side dispatcher drops (no effect); the
delivery itself stays observable in the receive-slot if it lands.
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

RVA_GET_HOST_OR_SELF = 0x4C80
RVA_RELIABLE_SEND = 0x4B60
HARMLESS_D = 9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=False)
    ap.add_argument('--session-name', required=False)
    ap.add_argument('--username', required=False)
    ap.add_argument('--hold', type=int, default=900)
    ap.add_argument('--log', required=False)
    ap.add_argument('--stop-file', required=False)
    ap.add_argument('--submit-gate', required=True)
    ap.add_argument('--submit-delay', type=float, default=8.0)
    args = ap.parse_args()
    if not all((args.target, args.session_name, args.username, args.log)):
        raise ValueError('explicit_live_run_paths_required')
    assert 30 <= args.hold <= 86400 and c.sizeof(c.c_void_p) == 4
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('x', encoding='utf-8', buffering=1)
    stacks = path.with_suffix(path.suffix + '.stacks').open('x', encoding='utf-8')
    faulthandler.enable(file=stacks)
    faulthandler.dump_traceback_later(60, repeat=True, file=stacks)

    def log(event):
        event = dict(event, wall=time.time(), mono=time.monotonic(),
                     wine_pid=os.getpid())
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    root = Path(r'C:\sgi\run-3.5')
    assert hashlib.sha256((root / '3I/Koeinm.dll').read_bytes()).hexdigest() == KOEINM
    assert hashlib.sha256((root / 'NetHookCore.dll').read_bytes()).hexdigest() == NETHOOK
    dll = c.WinDLL(str(root / '3I/Koeinm.dll'))
    hook = c.WinDLL(str(root / 'NetHookCore.dll'))

    def exp(name, params, result=c.c_int):
        f = getattr(dll, '_NetMsg_' + name)
        f.argtypes, f.restype = params, result
        return f

    start = exp('Start@36', [c.c_uint32]*8 + [c.POINTER(c.c_uint32)])
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
    dll_base = k.GetModuleHandleW('Koeinm.dll')
    assert dll_base, 'koeinm_module_handle_missing'
    netobj = dll_base + 0x12170

    def rd32(off):
        return c.c_uint32.from_address(netobj + off).value

    receiver = Receiver(log, decode, delete, accept)
    started = False
    last_slot_key = None
    fired = False
    submit_receipt = None
    gate_path = Path(args.submit_gate)
    try:
        flag = c.c_uint32()
        log({'ev': 'start_enter', 'dll_sha256': KOEINM, 'hook_loaded': bool(hook._handle),
             'mode': 'reliable_submit_probe', 'args': vars(args),
             'no_session': True, 'submit_max_calls': 1})
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
        log({'ev': 'relay_address', 'count': count, 'own_id': own,
             'target': args.target, 'session_name': args.session_name})
        deadline = time.monotonic() + args.hold
        next_check = time.monotonic()
        submit_at = time.monotonic() + max(0.0, args.submit_delay)
        while time.monotonic() < deadline:
            receiver.pump()
            slot_size = c.c_int32.from_address(netobj + 0x414c).value
            slot_sender = rd32(0x4150)
            if 0 < slot_size <= 0x4000:
                raw_slot = c.string_at(netobj + 0x14c, slot_size)
                key = (slot_sender, raw_slot)
                if key != last_slot_key:
                    last_slot_key = key
                    log({'ev': 'native_slot_observed', 'sender_slot': slot_sender,
                         'length': slot_size, 'raw_hex': raw_slot.hex(),
                         'sha256': hashlib.sha256(raw_slot).hexdigest(),
                         'evidence_type': 'sampled_owned_receive_slot; possible_missed_frames'})
            if not fired and time.monotonic() >= submit_at and gate_path.exists():
                fired = True
                try:
                    gate = json.loads(gate_path.read_text(encoding='utf-8'))
                except (OSError, ValueError) as error:
                    gate = {'gate_error': type(error).__name__}
                target = int(gate.get('target') or 0)
                body_hex = gate.get('body_hex')
                if body_hex:
                    body = bytes.fromhex(body_hex)
                else:
                    body = struct.pack('>I', HARMLESS_D) + struct.pack('>I', own or 0)
                log({'ev': 'submit_pre', 'connected': int(connected()),
                     'state_84a8': rd32(0x84a8), 'tx_seq': rd32(0x8440),
                     'host_id': int(hostid()), 'own_id': own, 'target': target,
                     'body_hex': body.hex(), 'gate': gate,
                     'call_shape': '0x4c80(netobj); 0x4b60(netobj,target,buf,len)'})
                gor = None
                try:
                    get_or_self = c.CFUNCTYPE(c.c_int, c.c_void_p)(dll_base + RVA_GET_HOST_OR_SELF)
                    gor = int(get_or_self(netobj))
                    log({'ev': 'submit_get_or_self', 'value': gor, 'hex': hex(gor & 0xFFFFFFFF)})
                except Exception as error:  # noqa: BLE001 - evidence over honesty
                    log({'ev': 'submit_get_or_self_exception',
                         'detail': type(error).__name__})
                buf = c.create_string_buffer(body, len(body))
                try:
                    reliable = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32,
                                           c.c_char_p, c.c_int)(dll_base + RVA_RELIABLE_SEND)
                    raw_rc = int(reliable(netobj, target, buf, len(body)))
                    submit_receipt = {'raw_rc': raw_rc, 'target': target,
                                      'len': len(body), 'body_hex': body.hex(),
                                      'gor': gor}
                    log({'ev': 'submit_call_return', 'raw_rc': raw_rc})
                except Exception as error:  # noqa: BLE001
                    submit_receipt = {'exception': type(error).__name__}
                    log({'ev': 'submit_call_exception', 'detail': type(error).__name__})
                log({'ev': 'submit_post', 'connected': int(connected()),
                     'state_84a8': rd32(0x84a8), 'tx_seq': rd32(0x8440),
                     'slot_len': c.c_int32.from_address(netobj + 0x414c).value,
                     'receipt': submit_receipt})
            if args.stop_file and Path(args.stop_file).exists():
                log({'ev': 'stop_requested'})
                break
            if time.monotonic() >= next_check:
                next_check += 10
                log({'ev': 'selfcheck', 'connected': int(connected()),
                     'packets': receiver.count, 'release_calls': receiver.freed,
                     'receiver_errors': receiver.errors,
                     'host_id': int(hostid()), 'tx_seq': rd32(0x8440),
                     'submit_fired': fired, 'submit_receipt': submit_receipt})
            time.sleep(.02)
        else:
            log({'ev': 'hold_expired'})
    finally:
        if started:
            log({'ev': 'end_enter'})
            log({'ev': 'end_return', 'rc': int(end())})
        receiver.close()
        log({'ev': 'closed', 'packets': receiver.count, 'release_calls': receiver.freed,
             'submit_fired': fired, 'submit_receipt': submit_receipt})
        faulthandler.cancel_dump_traceback_later()
        stream.close()
        stacks.close()


if __name__ == '__main__':
    main()
