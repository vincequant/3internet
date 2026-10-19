"""P32: normal registration/ready, one own cmd1, then passive observation.
No cmd23/seq0, foreign writes, game modification or repeated cmd1.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p28_window import Receiver, WM_EVENT, WM_DATA, WM_CHAT
from p20_cmd2_verified_probe import KOEINM, NETHOOK
from p30_ready import Preparation, CMD9
from p32_protocol import cmd2, FakeExit
from p28_wire import inspect_object


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=7200)
    ap.add_argument('--log', required=True)
    ap.add_argument('--gate-file', help='Fresh read-only host-watch sequence receipt')
    ap.add_argument('--stop-file', help='Owned probe normal-exit request')
    ap.add_argument('--authorization-file', required=True)
    ap.add_argument('--observe-seconds', type=int, default=3600)
    ap.add_argument('--ready', action='store_true', help='One cmd9 after validated cmd7; no sync/game simulation')
    args = ap.parse_args()
    assert 3600 <= args.observe_seconds < args.hold <= 86400
    assert args.gate_file and args.ready and args.username == '风夜'
    assert 30 <= args.hold <= 86400 and c.sizeof(c.c_void_p) == 4
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('x', encoding='utf-8', buffering=1)
    stacks = path.with_suffix(path.suffix+'.stacks').open('x', encoding='utf-8')
    faulthandler.enable(file=stacks)
    faulthandler.dump_traceback_later(60, repeat=True, file=stacks)

    packets = deque()
    counts = Counter()
    post_counts = Counter()
    fake_sent_mono = None
    def log(event):
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

    def drain_sync():
        # Observe this probe's own already-received queue. Never StartSync/EndSync.
        for _ in range(min(max(0, int(getcmdcount())), 64)):
            sender, size = c.c_uint32(), c.c_uint32()
            rc = getcmd(c.byref(sender), None, c.byref(size))
            if rc != 0 or not 0 < size.value <= 65536:
                log({'ev': 'sync_queue_unknown', 'rc': int(rc), 'length': size.value})
                break
            buf = c.create_string_buffer(size.value)
            rc = getcmd(c.byref(sender), buf, c.byref(size))
            if rc != 0:
                log({'ev': 'sync_queue_read_failed', 'rc': int(rc), 'length': size.value})
                break
            raw = buf.raw[:size.value]
            log({'ev': 'sync_command_received', 'type': 'GetCmd', 'sender': sender.value,
                 'length': len(raw), 'raw_hex': raw.hex(),
                 'sha256': hashlib.sha256(raw).hexdigest(), 'object': inspect_object(raw)})

    receiver = Receiver(log, decode, delete, accept)
    started = joined = False
    try:
        flag = c.c_uint32()
        log({'ev': 'start_enter', 'dll_sha256': KOEINM, 'hook_loaded': bool(hook._handle),
             'mode': 'ready_on_valid_cmd7' if args.ready else 'capture_only', 'args': vars(args), 'machine_name_hex': machine.hex(), 'machine_name': machine.decode('gbk', 'replace')})
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
            drain_sync()
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
                blob = fake.reserve(receipt, path, time.monotonic(), rd32(0x8440), connected())
                if blob is not None:
                    fake_sent_mono = time.monotonic()
                    deadline = fake_sent_mono+args.observe_seconds
                    log({'ev': 'send_enter', 'label': 'cmd1', 'own_id': own,
                         'row_index': fake.index, 'direction': 'SendData_broadcast',
                         'native_tx_seq': rd32(0x8440), 'raw_hex': blob.hex(),
                         'sha256': hashlib.sha256(blob).hexdigest(),
                         'authorization': receipt, 'pre_distribution': dict(counts)})
                    rc = send(blob, len(blob))
                    log({'ev': 'send_return', 'label': 'cmd1', 'rc': int(rc), 'no_retry': True})
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
                     'fakeexit_reserved': fake.reserved})
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
        log({'ev': 'closed', 'packets': receiver.count, 'release_calls': receiver.freed})
        faulthandler.cancel_dump_traceback_later()
        stream.close()
        stacks.close()


if __name__ == '__main__':
    main()
