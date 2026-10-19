"""P24 featureless-registration probe (child): join, then send a cmd2 that
makes the host application row byte-identical to a real client's row.

Why: p24_rowdetail on host PID 680 (2026-10-14) showed the only row-level
difference between the protocol ghost and real clients is L+4 (w4) 1 vs 2
and L+0a empty vs computer name. Both come from the cmd2 payload: empty
text forces w4=1 (465c64/6a/6c), while real clients send text=<machine
name> (丁满->VKQUANT-COM, 风云->VKQUANT) and b=2. This probe therefore
sends cmd2 with b=2 and text=GetComputerNameA at runtime, so the registered
row carries the same fields a normal join would have produced.

Everything from p20 is kept (seq0 bypass, host-side verification loop,
trigger->cmd23). New:
  --join-retries n   retry OpenSession every second (n attempts) instead of
                     aborting on the first failure, so the ghost can knock
                     before the host application is fully up
  --host-wait s      wait for the host app to be verifiable before the
                     first cmd2 (host row lookup in its DLL member table)
Blob validated offline against sim/m7_wire.py (encode/decode round-trip;
minimal blob reproduced byte-exactly before mutation).
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
MINIMAL_PREFIX = bytes.fromhex(
    'ffff010016004353616e496e6574476574496e6974436d6444617461'
    '020000000000000000000000000000')[:40]
CMD2_SHA = 'eed2183d450f05c0c58f7eecd1bc0a71e05e656c66195c19a46bb419a9fc323a'


def build_cmd2_blob(text):
    """cmd2 (CSanInetGetInitCmdData) with b=2 and text=<machine name>.

    Wire per m7-registration-wire.md: class declaration (28 bytes) +
    LE32(cmd=2) + LE32(a=0) + LE32(b=2) + BYTE(len)+text + BYTE + empty
    CString(extra). The prefix through b is byte-identical to the verified
    p20 minimal blob; only the text segment and b differ, matching what a
    real client sends from the room screen (G+cc 3/4 -> G+de text, b=2).
    """
    assert 0 < len(text) < 0xff
    return (MINIMAL_PREFIX
            + struct.pack('<III', 2, 0, 2)
            + bytes([len(text)]) + text + bytes([0, 0]))
CMD23_BLOB = bytes.fromhex(
    'ffff010011004353616e496e6574436d644f626a656374'
    '17000000000000000000000000')
CMD23_SHA = '689e19da75e318d2aa69863df6cf48b75fac58bcd23adc5a4522931a414cba95'

ROW = 0x87


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
    ap.add_argument('--host-pid', type=int, default=0)
    ap.add_argument('--verify-interval', type=float, default=3.0)
    ap.add_argument('--max-cmd2', type=int, default=12)
    ap.add_argument('--seq-zero-rounds', type=int, default=6)
    ap.add_argument('--join-retries', type=int, default=30)
    ap.add_argument('--host-wait', type=float, default=600.0)
    args = ap.parse_args()
    assert c.sizeof(c.c_void_p) == 4
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
              'cmd23_len': len(CMD23_BLOB), 'cmd23_sha256': CMD23_SHA}
    if not base:
        result['abort'] = 'no_module_base'
        print(json.dumps(result))
        return

    k32b = c.WinDLL('kernel32')
    nbuf = c.create_string_buffer(64)
    nsize = w.DWORD(64)
    k32b.GetComputerNameA(nbuf, c.byref(nsize))
    machine = nbuf.value.split(b'\x00', 1)[0]
    if not machine:
        result['abort'] = 'no_computer_name'
        print(json.dumps(result))
        return
    CMD2_BLOB = build_cmd2_blob(machine)
    assert CMD2_BLOB[:40] == MINIMAL_PREFIX and len(CMD2_BLOB) == 40 + 4 + 1 + len(machine) + 2
    result['cmd2_machine'] = machine.decode('gbk', 'replace')
    result['cmd2_len'] = len(CMD2_BLOB)
    result['cmd2_sha256'] = hashlib.sha256(CMD2_BLOB).hexdigest()

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
            for i in range(8):
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

    def fire(blob, label, fired, next_seq=None):
        alive, rows = session_alive()
        if not alive:
            return None, rows
        gate = host_gate_seq()
        # next_seq semantics: the exact BE32(seq) to stamp into the inner63.
        # None -> legacy own-table gate+1 alignment; 0 -> seq0 bypass
        # (7cc0 accepts seq==0 without row lookup, per m6 message-flow).
        aligned = (next_seq if next_seq is not None
                   else ((gate or 0) + 1) & 0xffffffff)
        wr32(0x8440, aligned)
        t0 = time.monotonic()
        rc = int(senddata(blob, len(blob)))
        pump()
        return {'ev': 'fired', 'label': label, 'fire': fired, 'rc': rc,
                'gate': gate, 'ctr_set': aligned,
                'dt': round(time.monotonic() - t0, 3)}, rows

    # ---- host-side read-only verification (bridge probe.Memory) ----
    verifier = {'ready': False}

    def init_verifier():
        if verifier['ready'] or not args.host_pid:
            return
        try:
            bridge = Path(r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge')
            assert (bridge/'probe.py').exists()
            sys.path.insert(0, str(bridge))
            os.environ['SGI_GAME_EXE'] = r'C:\sgi\run-3.5\3I\SANPK.exe'
            from probe import Memory  # noqa
            verifier['Memory'] = Memory
            verifier['ready'] = True
        except Exception as e:  # noqa
            verifier['error'] = str(e)[:200]

    def psapi_module_base(m, name_lower):
        psapi = c.WinDLL('psapi')
        psapi.EnumProcessModulesEx.argtypes = [c.c_void_p, c.POINTER(c.c_void_p),
                                               c.c_uint32, c.POINTER(c.c_uint32), c.c_uint32]
        psapi.GetModuleFileNameExW.argtypes = [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_uint32]
        modules = (c.c_void_p*512)()
        needed = c.c_uint32()
        if not psapi.EnumProcessModulesEx(m.h, modules, c.sizeof(modules),
                                          c.byref(needed), 3):
            return None
        for item in modules[:needed.value // c.sizeof(c.c_void_p)]:
            name = c.create_unicode_buffer(1024)
            psapi.GetModuleFileNameExW(m.h, item, name, len(name))
            if name.value.lower().endswith('\\' + name_lower):
                return item
        return None

    def u32_at(m, addr):
        b = m.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None

    def dec(b):
        return b.split(b'\x00', 1)[0].decode('gbk', 'replace') if b else ''

    def read_cstr(m, ptr, cap=96):
        if not ptr:
            return ''
        raw = m.read(ptr, cap)
        return dec(raw) if raw else ''

    def host_snapshot():
        """Read-only host state: dll table (with our sB) + app rows (strong anchor).

        v2: the outgoing frame seq must equal the HOST's sB for OUR row (+0x28
        of the 0x164-stride netobj row) + 1 -- NOT our own table's row-1 sB
        (that is the host->ghost receive gate; the two directions differ, which
        is why every p16-era send was rejected at 7cc0). App-row verification
        anchors on the row whose CString decodes to the host's own name, then
        walks the 8 stride-0x87 rows (same logic as p19 v3).
        """
        if not args.host_pid:
            return {'error': 'no_host_pid'}
        init_verifier()
        if not verifier['ready']:
            return {'error': 'verifier_init_failed', 'detail': verifier.get('error')}
        Memory = verifier['Memory']
        try:
            m = Memory(args.host_pid)
        except Exception as e:  # noqa
            return {'error': 'memory_open_failed', 'detail': str(e)[:200]}
        try:
            m.load()
            kbase = psapi_module_base(m, 'koeinm.dll')
            if not kbase:
                return {'error': 'host_koeinm_not_found'}
            netobj = kbase + 0x12170
            tptr = u32_at(m, netobj + 0x43b8)
            dll_rows = []
            own_sB = None
            if tptr:
                for i in range(8):
                    buf = m.read(tptr + 0x164 * i, 0x50)
                    if buf:
                        rid = struct.unpack_from('<I', buf, 0)[0]
                        nm = dec(buf[4:20])
                        sB = struct.unpack_from('<I', buf, 0x28)[0]
                        dll_rows.append({'id': rid, 'name': nm, 'sB': sB})
            own = next((r for r in dll_rows if r['name'] == args.username and r['id']), None)
            out = {'dll_rows': dll_rows}
            if not own:
                out['error'] = 'own_dll_row_not_found'
                return out
            out['own_sB'] = own['sB']
            # app rows: anchor on rows whose (id, CString name) pair matches the
            # dll table, host-name row = index 0
            anchors = []
            for r in dll_rows:
                if not r['id'] or not r['name']:
                    continue
                for a in m.find(struct.pack('<I', r['id']), limit=2000):
                    base = a - 6
                    buf = m.read(base, 0x50)
                    if buf is None:
                        continue
                    if struct.unpack_from('<I', buf, 6)[0] != r['id']:
                        continue
                    if struct.unpack_from('<I', buf, 0x42)[0] > 2:
                        continue
                    nameptr = struct.unpack_from('<I', buf, 0x0e)[0]
                    if nameptr and dec(m.read(nameptr, 16) or b'') == r['name']:
                        anchors.append((r['name'], base))
            host_anchor = next((b for nm, b in anchors if nm == '丁满'), None)
            if host_anchor is None:
                out['error'] = 'host_app_row_not_found'
                out['anchors'] = [(nm, hex(b)) for nm, b in anchors[:4]]
                return out
            rows = []
            own_row = None
            for i in range(8):
                base_i = host_anchor + i * ROW
                buf = m.read(base_i, ROW)
                if buf is None:
                    rows.append({'i': i, 'error': 'read_failed'})
                    continue
                rid = struct.unpack_from('<I', buf, 6)[0]
                nameptr = struct.unpack_from('<I', buf, 0x0e)[0]
                nm = read_cstr(m, nameptr)
                state = struct.unpack_from('<I', buf, 0x42)[0]
                w4b = m.read(base_i + 4, 2)
                row = {'i': i, 'id': rid, 'name': nm, 'state': state,
                       'w4': struct.unpack('<H', w4b)[0] if w4b else None}
                rows.append(row)
                if rid == own['id']:
                    own_row = row
            out['app_rows'] = rows
            if own_row is None:
                out['error'] = 'own_app_row_not_found'
                return out
            out['own_app_row'] = own_row
            out['registered'] = len(own_row['name'] or '') > 0
            return out
        finally:
            m.close()

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
        rc = None
        for attempt in range(max(1, args.join_retries)):
            rc = int(opens(args.target.encode('ascii'), args.session_name.encode('gbk'),
                           args.username.encode('gbk'), own, 3000))
            result['open_session'] = {'rc': rc, 'attempt': attempt + 1}
            log({'ev': 'open_session', **result['open_session']})
            pump()
            if rc == 0:
                break
            time.sleep(1.0)
        if rc != 0:
            result['abort'] = 'join_failed'
            print(json.dumps(result))
            return
        time.sleep(args.join_wait)
        pump()
        result['rows_after_join'] = member_snapshot()
        log({'ev': 'joined', 'rows': result['rows_after_join']})

        # host-wait: hold registration until the host application is
        # verifiable, so a pre-seat join never burns cmd2 attempts into
        # a not-yet-present host
        host_waited = 0.0
        while args.host_pid and host_waited < args.host_wait:
            pre = host_snapshot()
            if isinstance(pre, dict) and pre.get('own_sB') is not None:
                break
            pump()
            time.sleep(2.0)
            host_waited += 2.0
        log({'ev': 'host_wait_done', 'waited': host_waited})

        # phase 0: register (cmd2) with host-side verification loop.
        # Attempts 1..seq_zero_rounds stamp seq=0 (7cc0 bypass, empirically
        # validated by p9 u06); later attempts fall back to host sB+1.
        registered = False
        attempt = 0
        while attempt < args.max_cmd2 and not registered:
            attempt += 1
            snap = host_snapshot()
            host_sB = snap.get('own_sB') if isinstance(snap, dict) else None
            if attempt <= args.seq_zero_rounds:
                next_seq, mode = 0, 'zero'
            elif host_sB is not None:
                next_seq, mode = host_sB + 1, 'host_sB+1'
            else:
                next_seq, mode = None, 'legacy_own_gate'
            reg, rows = fire(CMD2_BLOB, 'cmd2', attempt, next_seq)
            if reg is None:
                log({'ev': 'session_dead_before_register', 'attempt': attempt,
                     'rows': rows})
                break
            reg['attempt'] = attempt
            reg['mode'] = mode
            reg['next_seq'] = next_seq
            reg['host_sB'] = host_sB
            pump()
            deadline = time.monotonic() + args.verify_interval
            while time.monotonic() < deadline:
                pump()
                time.sleep(0.25)
            chk = host_snapshot()
            reg['host_check'] = chk
            log(reg)
            if chk.get('registered'):
                registered = True
        if registered:
            log({'ev': 'registered', 'attempts': attempt})
        else:
            log({'ev': 'register_unverified', 'attempts': attempt})

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
            pre = host_snapshot()
            hsB = pre.get('own_sB') if isinstance(pre, dict) else None
            ev, rows = fire(CMD23_BLOB, 'cmd23', fired,
                            (hsB + 1) if hsB is not None else None)
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
