"""P16 cmd2-registration probe (child): complete ghost registration, then
fire cmd23 after trigger.

Static ground truth (M7a/M7b/M7c):
- cmd2 is a DERIVED class "CSanInetGetInitCmdData" (schema 1, 22-byte name);
  the host consumer 0x465c0d reads +14/+15, so a base-class-only blob is NOT
  a sufficient example. Minimal 43B template (a=b=byte=0, empty text/extra)
  from disasm/m7-templates.json case "minimal".
- Host 465c0d: matches row by packet.sender==L+6 (written by type1 at join),
  then writes GetUserName(sender) output into L+0e. The NAME COMES FROM THE
  HOST'S OWN DLL MEMBER TABLE - the blob fields barely matter.
- Pending predicate (resource 2723 start gate): L+42==0 AND L+6!=0 AND
  first byte of CString(L+0e)==0. cmd2 fills L+0e from GetUserName -> cleared.
- After registration the host sends cmd3 snapshot to sender + broadcasts row.

Sequence: join -> align gate -> send cmd2 blob once -> hold until trigger
file appears (host operator starts the game) -> fire-delay -> align gate ->
fire cmd23 minimal blob (a=b=0; inert parking if D+78==0, ExitSession if
D+78!=0 per M6d) -> adaptive retry up to --max-fires, stop on session death.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
import socket as pysocket
import struct
import sys
import time
from pathlib import Path

KOEINM = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
NETHOOK = '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'
CMD2_BLOB = bytes.fromhex(
    'ffff010016004353616e496e6574476574496e6974436d6444617461'
    '020000000000000000000000000000')
CMD2_SHA = 'eed2183d450f05c0c58f7eecd1bc0a71e05e656c66195c19a46bb419a9fc323a'
CMD23_BLOB = bytes.fromhex(
    'ffff010011004353616e496e6574436d644f626a656374'
    '17000000000000000000000000')
CMD23_SHA = '689e19da75e318d2aa69863df6cf48b75fac58bcd23adc5a4522931a414cba95'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True)
    ap.add_argument('--session-name', required=True)
    ap.add_argument('--username', required=True)
    ap.add_argument('--hold', type=int, default=600)
    ap.add_argument('--join-wait', type=int, default=3)
    ap.add_argument('--trigger', default=os.environ.get('TRIGGER_PATH', ''))
    ap.add_argument('--fire-delay', type=float, default=15.0)
    ap.add_argument('--max-fires', type=int, default=3)
    ap.add_argument('--fire-gap', type=float, default=8.0)
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4
    assert hashlib.sha256(CMD2_BLOB).hexdigest() == CMD2_SHA
    assert hashlib.sha256(CMD23_BLOB).hexdigest() == CMD23_SHA
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
              'cmd2_len': len(CMD2_BLOB), 'cmd2_sha256': CMD2_SHA,
              'cmd23_len': len(CMD23_BLOB), 'cmd23_sha256': CMD23_SHA}
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
    exit_session = export('_NetMsg_ExitSession@0', [])
    end = export('_NetMsg_End@0', [])

    def rd32(rva):
        v = c.c_uint32()
        c.memmove(c.byref(v), c.c_void_p(netobj_addr + rva), 4)
        return v.value

    def wr32(rva, val):
        c.memmove(c.c_void_p(netobj_addr + rva), struct.pack('<I', val), 4)

    def member_snapshot():
        ptr = c.c_uint32()
        c.memmove(c.byref(ptr), c.c_void_p(netobj_addr + 0x43b8), 4)
        rows = []
        if ptr.value:
            for i in range(4):
                rid = c.c_uint32()
                c.memmove(c.byref(rid), c.c_void_p(ptr.value + 0x164 * i), 4)
                seq = c.c_uint32()
                c.memmove(c.byref(seq), c.c_void_p(ptr.value + 0x164 * i + 0x28), 4)
                tick = c.c_uint32()
                c.memmove(c.byref(tick), c.c_void_p(ptr.value + 0x164 * i + 0x4c), 4)
                name = (c.c_char * 16).from_address(ptr.value + 0x164 * i + 4)
                rows.append({'idx': i, 'id': hex(rid.value), 'seq28': seq.value,
                             'tick4c': tick.value,
                             'name': name.value.decode('gbk', 'replace')})
        return rows

    def host_gate_seq():
        ptr = c.c_uint32()
        c.memmove(c.byref(ptr), c.c_void_p(netobj_addr + 0x43b8), 4)
        if not ptr.value:
            return None
        seq = c.c_uint32()
        c.memmove(c.byref(seq), c.c_void_p(ptr.value + 0x164 * 1 + 0x28), 4)
        return seq.value

    def session_alive():
        rows = member_snapshot()
        return len(rows) > 1 and rows[1]['id'] != '0x0', rows

    def fire(blob, label, fired):
        alive, rows = session_alive()
        if not alive:
            return None, rows
        gate = host_gate_seq()
        aligned = ((gate or 0) + 1) & 0xffffffff
        wr32(0x8440, aligned)
        t0 = time.monotonic()
        rc = int(senddata(blob, len(blob)))
        pump()
        return {'ev': 'fired', 'label': label, 'fire': fired, 'rc': rc,
                'gate': gate, 'ctr_set': aligned,
                'dt': round(time.monotonic() - t0, 3)}, rows

    events = []
    log = lambda ev: (events.append(ev), print(json.dumps(ev), flush=True))

    try:
        flag = c.c_uint32()
        result['start_rc'] = start(8, 64, 7777, 100, 100, 78731, 0, 0, c.byref(flag))
        pump()
        ip_ptr = c.c_void_p()
        ip_count = getip(c.byref(ip_ptr))
        own = None
        if 0 < ip_count <= 20 and ip_ptr.value:
            addresses = list((c.c_uint32 * ip_count).from_address(ip_ptr.value))
            own = addresses[0]
        if not own:
            result['abort'] = 'no_relay_address'
            print(json.dumps(result))
            return
        result['own_id'] = own
        setdata(None, 0x2462)
        rc = opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                   args.username.encode('gbk'), own, 3000)
        result['open_session'] = {'rc': rc}
        pump()
        if rc != 0:
            result['abort'] = 'join_failed'
            print(json.dumps(result))
            return
        time.sleep(args.join_wait)
        pump()
        result['rows_after_join'] = member_snapshot()
        log({'ev': 'joined', 'rows': result['rows_after_join']})

        # phase 0: register (cmd2) immediately after join, while still in lobby
        reg, rows = fire(CMD2_BLOB, 'cmd2', 1)
        if reg is None:
            log({'ev': 'session_dead_before_register', 'rows': rows})
        else:
            pump(); time.sleep(2.0); pump()
            reg['rows_after'] = member_snapshot()
            log(reg)

        # phase 1: wait for trigger (host operator starts the game)
        waited = 0.0
        fired = 0
        trigger_logged = False
        while waited < args.hold:
            pump()
            trigger_hit = bool(args.trigger) and os.path.exists(args.trigger)
            if trigger_hit and not trigger_logged:
                trigger_logged = True
                log({'ev': 'trigger_seen', 'trigger': args.trigger})
            if not trigger_hit:
                time.sleep(0.5)
                waited += 0.5
                continue
            if waited < args.fire_delay:
                time.sleep(0.5)
                waited += 0.5
                continue
            fired += 1
            ev, rows = fire(CMD23_BLOB, 'cmd23', fired)
            if ev is None:
                log({'ev': 'session_dead_before_fire', 'fire': fired, 'rows': rows})
                break
            pump(); time.sleep(1.0); pump()
            ev['rows_after'] = member_snapshot()
            log(ev)
            if fired >= args.max_fires:
                break
            gap_end = time.monotonic() + args.fire_gap
            died = False
            while time.monotonic() < gap_end:
                pump()
                time.sleep(0.5)
                a2, r2 = session_alive()
                if not a2:
                    died = True
                    break
            if died:
                log({'ev': 'session_dead_after_fire', 'fire': fired,
                     'rows': member_snapshot()})
                break
            waited += args.fire_gap
        else:
            log({'ev': 'hold_expired' + ('_without_trigger' if not args.trigger else ''),
                 'fires': fired, 'waited': waited})

        tail_end = time.monotonic() + 10
        while time.monotonic() < tail_end:
            pump()
            time.sleep(1.0)
        log({'ev': 'tail_rows', 'rows': member_snapshot()})
    finally:
        try:
            result['cleanup'] = {'exit_rc': exit_session(), 'end_rc': end()}
        except Exception as e:  # noqa
            result['cleanup'] = {'error': str(e)[:100]}
        result['events'] = events
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__, 'detail': str(e)[:200]}))
        sys.exit(1)
