"""P33 prepared-only by default. Explicit Phase 3 enables own DLL sync.
Normal cmd2/cmd9, one own cmd1; zero game actions or foreign writes.
"""
from collections import Counter, deque
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
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p28_window import Receiver, WM_EVENT, WM_DATA, WM_CHAT
from p20_cmd2_verified_probe import KOEINM, NETHOOK
from p30_ready import Preparation, CMD9
from p32_protocol import cmd2, FakeExit
from p28_wire import inspect_object
from p33_wire import inspect_inner
from p33_sync import participate, sync_authorized, start_report_authorized


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=False)
    ap.add_argument('--session-name', required=False)
    ap.add_argument('--username', required=False)
    ap.add_argument('--hold', type=int, default=7200)
    ap.add_argument('--log', required=False)
    ap.add_argument('--gate-file', help='Fresh read-only host-watch sequence receipt')
    ap.add_argument('--stop-file', help='Owned probe normal-exit request')
    ap.add_argument('--authorization-file', required=False)
    ap.add_argument('--observe-seconds', type=int, default=3600)
    ap.add_argument('--ready', action='store_true', help='One cmd9 after validated cmd7; no sync/game simulation')
    ap.add_argument('--execute', action='store_true', help='ONLY after explicit Phase3 approval; default exits without native calls')
    ap.add_argument('--sync-effect-file')
    args = ap.parse_args()
    if not args.execute:
        print(json.dumps({'state': 'prepared_only', 'native_calls': 0, 'join': False, 'sync': False}))
        return
    if not all((args.target, args.session_name, args.username, args.log, args.authorization_file, args.sync_effect_file)):
        raise ValueError('explicit_live_run_paths_required')
    assert 3600 <= args.observe_seconds < args.hold <= 86400
    assert args.gate_file and args.ready and args.username == '风夜'
    assert 30 <= args.hold <= 86400 and c.sizeof(c.c_void_p) == 4
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('x', encoding='utf-8', buffering=1)
    stacks = path.with_suffix(path.suffix+'.stacks').open('x', encoding='utf-8')
    faulthandler.enable(file=stacks)
    faulthandler.dump_traceback_later(60, repeat=True, file=stacks)

    log_lock = threading.RLock()
    worker_stop = threading.Event()
    worker_failed = threading.Event()
    worker = None
    worker_started = False
    cmd1_seq = None
    cmd1_rc = None
    last_slot_key = None
    packets = deque()
    counts = Counter()
    post_counts = Counter()
    fake_sent_mono = None
    def log(event):
        with log_lock:
            event = dict(event, wall=time.time(), mono=time.monotonic(), wine_pid=os.getpid())
            stream.write(json.dumps(event, ensure_ascii=False)+'\n')
            if event['ev'] in ('received_packet', 'sync_command_received'):
                key = 'type:%s/cmd:%s/len:%s' % (event['type'], event.get('object', {}).get('cmd', 'unknown'), event['length'])
                counts[key] += 1
                if fake_sent_mono is not None:
                    post_counts[key] += 1
                if event['ev'] == 'received_packet' and event['type'] == 4:
                    packets.append(event)
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
    send = exp('SendData@8', [c.c_char_p, c.c_int])
    sendto = exp('SendDataTo@12', [c.c_uint32, c.c_char_p, c.c_int])
    startsync = exp('StartSync@0', [])
    endsync = exp('EndSync@4', [c.c_uint32])
    getcmd = exp('GetCmd@12', [c.POINTER(c.c_uint32), c.c_void_p, c.POINTER(c.c_uint32)])
    getcmdcount = exp('GetCmdCount@0', [])
    hostid = exp('GetHostID@0', [], c.c_uint32)
    decode = exp('DecodeWParam@4', [c.c_uint32])
    delete = exp('DeletePacket@4', [c.c_void_p])
    accept = exp('AcceptEXIT@4', [c.c_uint32])
    connected = exp('IsConnected@0', [])
    exit_session = exp('ExitSession@0', [])
    end = exp('End@0', [])
    k = c.WinDLL('kernel32')
    k.GetTickCount.argtypes, k.GetTickCount.restype = [], c.c_uint32
    k.SetEvent.argtypes, k.SetEvent.restype = [w.HANDLE], w.BOOL
    k.GetComputerNameA.argtypes, k.GetComputerNameA.restype = [c.c_char_p, c.POINTER(w.DWORD)], w.BOOL
    machine_buffer = c.create_string_buffer(256)
    machine_size = w.DWORD(256)
    if not k.GetComputerNameA(machine_buffer, c.byref(machine_size)):
        raise c.WinError()
    machine = machine_buffer.raw[:machine_size.value]
    CMD2_BLOB = cmd2(machine)
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

    def read_sync_batch():
        records = []
        # Worker exclusively drains this probe's just-received native batch.
        count = int(getcmdcount())
        if not 0 <= count <= 120:
            raise ValueError('native_batch_count_bound')
        for _ in range(count):
            sender, size = c.c_uint32(), c.c_uint32()
            rc = getcmd(c.byref(sender), None, c.byref(size))
            if rc != 0 or not 0 < size.value <= 65536:
                log({'ev': 'sync_queue_unknown', 'rc': int(rc), 'length': size.value})
                raise ValueError('native_queue_size_query_failed')
            buf = c.create_string_buffer(size.value)
            rc = getcmd(c.byref(sender), buf, c.byref(size))
            if rc != 0:
                log({'ev': 'sync_queue_read_failed', 'rc': int(rc), 'length': size.value})
                raise ValueError('native_queue_pop_failed')
            raw = buf.raw[:size.value]
            record = {'ev': 'sync_command_received', 'type': 'GetCmd', 'sender': sender.value,
                 'length': len(raw), 'raw_hex': raw.hex(),
                 'sha256': hashlib.sha256(raw).hexdigest(), 'object': inspect_object(raw)}
            records.append(record)
            log(record)
        if getcmdcount() != 0:
            raise ValueError('native_batch_not_fully_drained')
        return records

    class OwnBackend:
        connected = staticmethod(lambda: bool(connected()))
        state = staticmethod(lambda: rd32(0x84a8))
        tick = staticmethod(k.GetTickCount)
        start = staticmethod(startsync)
        end = staticmethod(endsync)
        batch = staticmethod(read_sync_batch)

    def worker_log(event):
        log(event)
        if event['ev'] == 'sync_failed':
            worker_failed.set()

    receiver = Receiver(log, decode, delete, accept)
    started = joined = False
    try:
        flag = c.c_uint32()
        log({'ev': 'start_enter', 'dll_sha256': KOEINM, 'hook_loaded': bool(hook._handle),
             'mode': 'p33_live_own_native_sync_after_approved_fakeexit', 'args': vars(args), 'machine_name_hex': machine.hex(), 'machine_name': machine.decode('gbk', 'replace')})
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
            return
        log({'ev': 'joined', 'rows': own_rows()})
        def load_scenario(index):
            if not 1 <= index <= 99:
                raise ValueError('scenario_index_bound')
            name = 'sndata%02d.s6i' % index
            source = root/'3I/snr'/name
            if not source.is_file() or not 0 < source.stat().st_size <= 2*1024*1024:
                raise ValueError('scenario_size_or_file')
            return source.read_bytes(), name
        prep = Preparation(own, int(hostid()), args.username, load_scenario)
        fake = FakeExit(own, int(hostid()), args.username)
        # Mandatory normal registration reads the HOST's receive gate from the existing watch,
        # avoiding the unrelated gate in our own member table.
        seq = 0
        if args.gate_file:
            log({'ev': 'waiting_host_gate', 'own_id': own})
            limit = time.monotonic()+25
            receipt = None
            while time.monotonic() < limit:
                receiver.pump()
                try:
                    candidate = json.loads(Path(args.gate_file).read_text(encoding='utf-8'))
                    if (candidate['own_id'] == own and candidate['host_id'] == own_rows()[1]['id']
                            and 0 <= time.time()-candidate['observed_at'] <= 10
                            and candidate['next_seq'] == candidate['host_sB']+1
                            and 1 <= candidate['next_seq'] <= 0xffffffff):
                        receipt = candidate
                        break
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                time.sleep(.02)
            if receipt is None:
                log({'ev': 'abort', 'reason': 'no_fresh_host_gate'})
                return
            seq = receipt['next_seq']
            log({'ev': 'host_gate_receipt', **receipt})
        c.c_uint32.from_address(netobj+0x8440).value = seq  # OWN DLL only
        log({'ev': 'send_enter', 'label': 'cmd2', 'ctr_set': seq,
             'raw_hex': CMD2_BLOB.hex(), 'sha256': hashlib.sha256(CMD2_BLOB).hexdigest()})
        rc = send(CMD2_BLOB, len(CMD2_BLOB))
        log({'ev': 'send_return', 'label': 'cmd2', 'rc': rc})
        deadline = time.monotonic()+args.hold
        next_check = time.monotonic()
        while time.monotonic() < deadline:
            receiver.pump()
            # Bounded OWN last-slot observation. It can miss frames; it is not a wire tap.
            slot_size = c.c_int32.from_address(netobj+0x414c).value
            slot_sender = rd32(0x4150)
            if 0 < slot_size <= 0x4000:
                raw_slot = c.string_at(netobj+0x14c, slot_size)
                key = (slot_sender, raw_slot)
                if key != last_slot_key and raw_slot[0] == 0x63:
                    last_slot_key = key
                    try:
                        parsed_slot = inspect_inner(raw_slot)
                    except ValueError:
                        parsed_slot = {'unknown_control_or_incomplete_slot': True}
                    log({'ev': 'native_slot_observed', 'sender_slot': slot_sender,
                         'length': slot_size, 'raw_hex': raw_slot.hex(),
                         'sha256': hashlib.sha256(raw_slot).hexdigest(), 'inner': parsed_slot,
                         'evidence_type': 'sampled_owned_receive_slot; possible_missed_frames'})
            while packets:
                packet = packets.popleft()
                decision = prep.accept(packet)
                fake.observe(packet)
                log(decision)
                if decision['ev'] == 'ready_once' and args.ready:
                    fake.snapshot(packet)
                    # Normal native reliable sequence; no reset to seq0.
                    seq_now = rd32(0x8440)
                    if not connected() or seq_now < seq+1:
                        log({'ev': 'ready_not_sent', 'reason': 'registration_ack_not_observed', 'tx_seq': seq_now})
                        continue
                    target = int(hostid())
                    log({'ev': 'send_enter', 'label': 'cmd9', 'target': target,
                         'native_tx_seq': seq_now, 'prepared_sha256': decision['sha256'],
                         'raw_hex': CMD9.hex(), 'sha256': hashlib.sha256(CMD9).hexdigest()})
                    rc = sendto(target, CMD9, len(CMD9))
                    log({'ev': 'send_return', 'label': 'cmd9', 'rc': int(rc)})
                    if rc == 0:
                        fake.ready_seq = seq_now
                    else:
                        fake.cancelled = True
            if not fake.reserved:
                try:
                    receipt = json.loads(Path(args.authorization_file).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    receipt = {}
                if not start_report_authorized(receipt, own, int(hostid()), path):
                    receipt = {}
                blob = fake.reserve(receipt, path, time.monotonic(), rd32(0x8440), connected())
                if blob is not None:
                    fake_sent_mono = time.monotonic()
                    deadline = fake_sent_mono+args.observe_seconds
                    log({'ev': 'send_enter', 'label': 'cmd1', 'own_id': own,
                         'row_index': fake.index, 'direction': 'SendData_broadcast',
                         'native_tx_seq': rd32(0x8440), 'raw_hex': blob.hex(),
                         'sha256': hashlib.sha256(blob).hexdigest(),
                         'authorization': receipt, 'pre_distribution': dict(counts)})
                    cmd1_seq = rd32(0x8440)
                    rc = send(blob, len(blob))
                    cmd1_rc = int(rc)
                    log({'ev': 'send_return', 'label': 'cmd1', 'rc': int(rc), 'no_retry': True})
            if fake.reserved and not worker_started and cmd1_rc == 0 and rd32(0x8440) > cmd1_seq:
                try:
                    approval = json.loads(Path(args.authorization_file).read_text(encoding='utf-8'))
                    effect = json.loads(Path(args.sync_effect_file).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    approval, effect = {}, {}
                if sync_authorized(approval, effect, own, int(hostid()), path, time.time()):
                    deadline = time.monotonic()+args.observe_seconds
                    worker_started = True  # irreversible reservation before thread/native calls
                    log({'ev': 'sync_worker_starting', 'own_id': own, 'effect': effect})
                    worker = threading.Thread(target=participate,
                        args=(OwnBackend(), worker_stop, worker_log), name='P33-owned-sync', daemon=True)
                    worker.start()
            if fake.reserved and not worker_started and time.monotonic()-fake_sent_mono > 45:
                log({'ev': 'sync_preflight_failed', 'reason': 'no_fresh_effect_or_cmd1_ACK_within45s', 'no_retry': True})
                break
            if worker_failed.is_set():
                log({'ev': 'stop_due_to_sync_failure', 'no_retry': True})
                break
            if args.stop_file and Path(args.stop_file).exists():
                log({'ev': 'stop_requested'})
                break
            if time.monotonic() >= next_check:
                next_check += 10
                log({'ev': 'selfcheck', 'connected': int(connected()), 'rows': own_rows(),
                     'packets': receiver.count, 'release_calls': receiver.freed,
                     'receiver_errors': receiver.errors, 'tx_seq': rd32(0x8440),
                     'distribution': dict(counts), 'post_cmd1_distribution': dict(post_counts),
                     'post_cmd1_seconds': (None if fake_sent_mono is None else time.monotonic()-fake_sent_mono),
                     'fakeexit_reserved': fake.reserved, 'native_sync_state': rd32(0x84a8),
                     'sync_worker_alive': bool(worker and worker.is_alive())})
            time.sleep(.02)
        else:
            log({'ev': 'hold_expired'})
    finally:
        worker_stop.set()
        if worker and worker.is_alive():
            # 3af2/4077 signal this abort event; 3290/3540 wait on it. OWN handle only.
            abort_handle = rd32(0x84a4)
            released = bool(k.SetEvent(w.HANDLE(abort_handle))) if abort_handle else False
            log({'ev': 'own_sync_abort_event', 'handle': abort_handle, 'set_ok': released})
            worker.join(timeout=5)
            if worker.is_alive():
                log({'ev': 'shutdown_failure', 'reason': 'owned_native_worker_not_released'})
                raise RuntimeError('cannot_unload_own_DLL_with_active_sync_worker')
        # Stop native producers while the owned HWND still exists, then drain.
        if joined:
            log({'ev': 'exit_enter'})
            log({'ev': 'exit_return', 'rc': int(exit_session())})
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
