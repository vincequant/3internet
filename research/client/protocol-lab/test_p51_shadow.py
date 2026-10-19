#!/usr/bin/env python3
"""Tests for the P51 shadow agent/injector.

Coverage:
  * Koeinm export parser against both archived builds (golden RVAs).
  * Blob builder layout (offsets locked to the agent assembly).
  * Receipt parser.
  * Unicorn behavioral emulation of the real agent.bin:
      - happy path: exact 0x4B60 call (netobj/target/body), receipt bytes,
        sent flag — and NO unicorn fault (stack discipline check).
      - gates: no trigger file / wrong state / zero own id / target==own.
  * Smoke payload emulation (plumbing payload used before live runs).

Run:  python3 -m unittest test_p51_shadow -v   (venv with capstone+unicorn)
"""
from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p51_shadow_inject as inj  # noqa: E402

EVIDENCE = Path(os.environ.get(
    'P51_EVIDENCE_DIR',
    ROOT.parent.parent / 'protocol-archive/evidence/p50-shadow-phaseb-20261017/agent-build'))

ARCHIVE = ROOT.parent.parent / 'evidence'
KOEINM_ORIGINAL = ARCHIVE / 'network-reconnect-patch-r1-20261012/Koeinm.original.dll'
KOEINM_R2 = ARCHIVE / 'network-reconnect-patch-r2-20261012/Koeinm.reconnect-r2.dll'

OWN = 0x55667788
TARGET = 0x11223344
TICK = 0xDEADBEEF


class TestExportParser(unittest.TestCase):
    def test_golden_rvas_original(self):
        ex = inj.parse_exports(KOEINM_ORIGINAL)
        self.assertEqual(ex['_NetMsg_IsConnected@0'], 0x20B0)
        self.assertEqual(ex['_NetMsg_GetIPAddress@4'], 0x22B0)

    def test_golden_rvas_r2(self):
        ex = inj.parse_exports(KOEINM_R2)
        self.assertEqual(ex['_NetMsg_IsConnected@0'], 0x20B0)
        self.assertEqual(ex['_NetMsg_GetIPAddress@4'], 0x22B0)


class TestBlob(unittest.TestCase):
    def _pointers(self):
        return {'GetFileAttributesA': 0x500001, 'CreateFileA': 0x500002, 'WriteFileA': 0x500003,
                'CloseHandle': 0x500004, 'Sleep': 0x500005, 'GetTickCount': 0x500006,
                'is_connected': 0x500007, 'get_ip': 0x500008, 'submit_4c80': 0x500009,
                'submit_4b60': 0x50000A}

    def test_layout(self):
        blob = inj.build_blob(inj.MAGIC, 0x300000, self._pointers(), 'Z:\\f.flag', 'Z:\\r.bin')
        self.assertEqual(len(blob), inj.BLOB_SIZE)
        self.assertEqual(struct.unpack_from('<I', blob, 0)[0], inj.MAGIC)
        self.assertEqual(struct.unpack_from('<I', blob, 4)[0], 0)
        self.assertEqual(struct.unpack_from('<I', blob, 8)[0], 0x300000)
        for i, key in enumerate(('GetFileAttributesA', 'CreateFileA', 'WriteFileA',
                                 'CloseHandle', 'Sleep', 'GetTickCount',
                                 'is_connected', 'get_ip', 'submit_4c80', 'submit_4b60')):
            self.assertEqual(struct.unpack_from('<I', blob, 0x0C + i * 4)[0], self._pointers()[key], key)
        self.assertTrue(blob[0x34:].startswith(b'Z:\\f.flag\x00'))
        self.assertTrue(blob[0xB4:].startswith(b'Z:\\r.bin\x00'))

    def test_receipt_parser(self):
        raw = struct.pack('<IIIIII', inj.MAGIC2, 1, OWN, TARGET, TICK, 0)
        r = inj.parse_receipt(raw)
        self.assertEqual(r['rc'], 1)
        self.assertEqual(r['own'], OWN)
        self.assertEqual(r['target'], TARGET)
        self.assertEqual(r['tick'], TICK)


def _stub_bytes():
    stubs = {}

    def enc_gfa(ret):
        return b'\xb8' + struct.pack('<I', ret) + b'\xc2\x04\x00'
    stubs['gfa'] = enc_gfa(0)
    stubs['gfa_missing'] = enc_gfa(0xFFFFFFFF)
    stubs['conn'] = b'\xb8\x01\x00\x00\x00\xc3'
    stubs['getip'] = (b'\x8b\x44\x24\x04' + b'\xc7\x00' + struct.pack('<I', 0x210000) +
                      b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    stubs['c80'] = b'\xb8' + struct.pack('<I', TARGET) + b'\xc3'
    stubs['c80_own'] = b'\xb8' + struct.pack('<I', OWN) + b'\xc3'
    stubs['c60'] = b'\xb8\x01\x00\x00\x00\xc3'
    stubs['cfa'] = b'\xb8\x03\x00\x00\x00\xc2\x1c\x00'
    stubs['wfa'] = (b'\x8b\x44\x24\x10' + b'\xb9\x18\x00\x00\x00' + b'\x89\x08' +
                    b'\xb8\x01\x00\x00\x00\xc2\x14\x00')
    stubs['close'] = b'\xb8\x01\x00\x00\x00\xc2\x04\x00'
    stubs['tick'] = b'\xb8' + struct.pack('<I', TICK) + b'\xc3'
    stubs['sleep'] = b'\xb8\x00\x00\x00\x00\xc2\x04\x00'
    stubs['acc'] = b'\xb8\x01\x00\x00\x00\xc2\x04\x00'
    return stubs


CODE, BLOB_M, IDS, NETOBJ, STACK, STUBS = 0x100000, 0x200000, 0x210000, 0x300000, 0x400000, 0x500000
SPIN = 0xDEAD0000
ADDR = {'gfa': STUBS, 'conn': STUBS + 0x1000, 'getip': STUBS + 0x2000, 'c80': STUBS + 0x3000,
        'c60': STUBS + 0x4000, 'cfa': STUBS + 0x5000, 'wfa': STUBS + 0x6000,
        'close': STUBS + 0x7000, 'tick': STUBS + 0x8000, 'sleep': STUBS + 0x9000,
        'acc': STUBS + 0xA000}


def run_payload(bin_path, *, trigger=True, state=1, own=OWN, c80_is_own=False, max_insns=80000,
                kind='agent'):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x1000), (BLOB_M, 0x2000), (IDS, 0x1000), (NETOBJ, 0x9000),
                       (STACK, 0x10000), (STUBS, 0x11000), (SPIN, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(CODE, code)
    sb = _stub_bytes()
    for key, base in ADDR.items():
        if key == 'gfa':
            uc.mem_write(base, sb['gfa'] if trigger else sb['gfa_missing'])
        elif key == 'c80':
            uc.mem_write(base, sb['c80_own'] if c80_is_own else sb['c80'])
        else:
            uc.mem_write(base, sb[key])
    uc.mem_write(IDS, struct.pack('<I', own))
    uc.mem_write(NETOBJ + 0x84A8, struct.pack('<I', state))
    if kind == 'acceptexit':
        pointers = {'GetFileAttributesA': ADDR['gfa'], 'CreateFileA': ADDR['cfa'], 'WriteFileA': ADDR['wfa'],
                    'CloseHandle': ADDR['close'], 'Sleep': ADDR['sleep'], 'GetTickCount': ADDR['tick'],
                    'is_connected': ADDR['conn'], 'get_ip': ADDR['getip'], 'accept_exit': ADDR['acc']}
        names = inj.ACCEPTEXIT_POINTER_NAMES
    else:
        pointers = {'GetFileAttributesA': ADDR['gfa'], 'CreateFileA': ADDR['cfa'], 'WriteFileA': ADDR['wfa'],
                    'CloseHandle': ADDR['close'], 'Sleep': ADDR['sleep'], 'GetTickCount': ADDR['tick'],
                    'is_connected': ADDR['conn'], 'get_ip': ADDR['getip'],
                    'submit_4c80': ADDR['c80'], 'submit_4b60': ADDR['c60']}
        names = inj.DEFAULT_POINTER_NAMES
    blob = inj.build_blob(inj.MAGIC, NETOBJ, pointers, 'Z:\\test\\flag', 'Z:\\test\\receipt', names)
    uc.mem_write(BLOB_M, blob)
    esp0 = STACK + 0xF000
    uc.mem_write(esp0, struct.pack('<II', SPIN, BLOB_M))
    uc.mem_write(SPIN, b'\xeb\xfe')  # jmp $ for payload returns
    uc.reg_write(UC_X86_REG_ESP, esp0)

    log = {'c60': [], 'c80': 0, 'cfa': [], 'wfa': [], 'acc': [], 'error': None}

    def on_code(uc_, address, size, data):
        esp = uc_.reg_read(UC_X86_REG_ESP)

        def u32(off):
            return struct.unpack('<I', uc_.mem_read(esp + off, 4))[0]
        if address == ADDR['c60']:
            netobj, target, buf, ln = u32(4), u32(8), u32(12), u32(16)
            body = bytes(uc_.mem_read(buf, ln)) if (ln and ln <= 64 and buf) else b''
            log['c60'].append({'netobj': netobj, 'target': target, 'buf': buf, 'len': ln, 'body': body})
        elif address == ADDR['c80']:
            log['c80'] += 1
        elif address == ADDR['acc']:
            log['acc'].append(u32(4))
        elif address == ADDR['cfa']:
            ptr = u32(4)
            raw = b''
            while len(raw) < 200:
                ch = uc_.mem_read(ptr + len(raw), 1)
                if ch == b'\x00':
                    break
                raw += ch
            log['cfa'].append(raw.decode('latin1'))
        elif address == ADDR['wfa']:
            buf, ln = u32(8), u32(12)
            log['wfa'].append(bytes(uc_.mem_read(buf, ln)) if 0 < ln <= 64 else b'')
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=STUBS, end=STUBS + 0x10000)
    try:
        uc.emu_start(CODE, 0, timeout=0, count=max_insns)
    except UcError as error:
        log['error'] = str(error)
    log['blob'] = bytes(uc.mem_read(BLOB_M, inj.BLOB_SIZE))
    return log


class TestAgentEmulation(unittest.TestCase):
    def test_happy_path(self):
        log = run_payload(EVIDENCE / 'agent.bin')
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 1, 'exactly one reliable submit')
        call = log['c60'][0]
        self.assertEqual(call['netobj'], NETOBJ)
        self.assertEqual(call['target'], TARGET)
        self.assertEqual(call['len'], 8)
        self.assertEqual(call['body'], struct.pack('>II', 8, OWN))
        self.assertEqual(log['c80'], 1)
        self.assertTrue(log['cfa'] and log['cfa'][0].endswith('receipt'))
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', inj.MAGIC2, 1, OWN, TARGET, TICK, 0))
        sent = struct.unpack_from('<I', log['blob'], 4)[0]
        self.assertEqual(sent, 1)

    def test_gate_no_trigger(self):
        log = run_payload(EVIDENCE / 'agent.bin', trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 0)
        self.assertEqual(log['c80'], 0)
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 0)

    def test_gate_wrong_state(self):
        log = run_payload(EVIDENCE / 'agent.bin', state=2)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 0)

    def test_gate_zero_own(self):
        log = run_payload(EVIDENCE / 'agent.bin', own=0)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 0)

    def test_gate_target_equals_own(self):
        log = run_payload(EVIDENCE / 'agent.bin', c80_is_own=True)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 0)

    def test_smoke_payload(self):
        log = run_payload(EVIDENCE / 'smoke.bin', max_insns=5000)
        self.assertIsNone(log['error'])
        self.assertTrue(log['cfa'])
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], log['blob'][:16])

    def test_acceptexit_happy(self):
        log = run_payload(EVIDENCE / 'agent_acceptexit.bin', kind='acceptexit')
        self.assertIsNone(log['error'])
        self.assertEqual(log['acc'], [OWN], 'AcceptEXIT(own) exactly once')
        self.assertEqual(log['c60'], [], 'no reliable submit in this variant')
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', 0x33474853, 1, OWN, 0, TICK, 0))
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1)

    def test_acceptexit_gates(self):
        no_trigger = run_payload(EVIDENCE / 'agent_acceptexit.bin', kind='acceptexit', trigger=False)
        self.assertIsNone(no_trigger['error'])
        self.assertEqual(no_trigger['acc'], [])
        disconnected = run_payload(EVIDENCE / 'agent_acceptexit.bin', kind='acceptexit', own=0)
        self.assertIsNone(disconnected['error'])
        self.assertEqual(disconnected['acc'], [])


ROUNDS_D_DEFAULT = Path(os.environ.get(
    'P51_ROUNDS_D_BIN',
    ROOT.parent.parent / 'protocol-archive/evidence/p51-rounds-d-20261018/agent-build/agent_rounds_d.bin'))

R_CODE, R_BLOB, R_COREM, R_CORE, R_NETOBJ, R_STUBS, R_STACK, R_SPIN = (
    0x100000, 0x200000, 0x3FF000, 0x400000, 0x600000, 0x700000, 0x900000, 0x950000)


def run_rounds(bin_path, *, queue=0, max_rounds=200, consume=True, trigger=True, max_insns=800000):
    """Unicorn emulation of a rounds agent with the D-variant queue gate.

    The spawner stub (registered via the blob fn_d pointer) emulates the client
    driver D finishing: f6bc := 2 and, when consume=True, the queued-batch count
    [netobj+0x84b4] decreases by one. Sleep/GetTickCount return immediately/constant.
    """
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((R_CODE, 0x1000), (R_BLOB, 0x2000), (R_COREM, 0x2000),
                       (R_NETOBJ, 0x9000), (R_STUBS, 0x20000), (R_STACK, 0x10000),
                       (R_SPIN, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(R_CODE, code)
    sb = _stub_bytes()
    gfa, cfa, wfa, close, sleep, tick, spawn = (R_STUBS + i * 0x1000 for i in range(7))
    uc.mem_write(gfa, sb['gfa'] if trigger else sb['gfa_missing'])
    uc.mem_write(cfa, sb['cfa'])
    uc.mem_write(wfa, b'\xb8\x01\x00\x00\x00\xc2\x14\x00')       # WriteFileA -> 1, ret 20
    uc.mem_write(close, sb['close'])
    uc.mem_write(sleep, sb['sleep'])
    uc.mem_write(tick, sb['tick'])
    uc.mem_write(spawn, b'\xb8\x00\x00\x00\x00\xc3')             # spawner -> 0
    uc.mem_write(R_NETOBJ + 0x84B4, struct.pack('<I', queue))
    f6bc = R_CORE + 0x6BC
    uc.mem_write(f6bc, struct.pack('<I', 0))
    pointers = {'GetFileAttributesA': gfa, 'CreateFileA': cfa, 'WriteFileA': wfa,
                'SetEvent': close, 'Sleep': sleep, 'GetTickCount': tick}
    blob = inj.build_rounds_blob(inj.MAGIC, R_NETOBJ, R_CORE, spawn, pointers,
                                 'Z:\\test\\flag', 'Z:\\test\\receipt', max_rounds)
    uc.mem_write(R_BLOB, blob)
    esp0 = R_STACK + 0xF000
    uc.mem_write(esp0, struct.pack('<II', R_SPIN, R_BLOB))
    uc.mem_write(R_SPIN, b'\xeb\xfe')
    uc.reg_write(UC_X86_REG_ESP, esp0)

    log = {'events': [], 'spawns': 0, 'error': None}

    def on_code(uc_, address, size, data):
        esp = uc_.reg_read(UC_X86_REG_ESP)

        def u32(off):
            return struct.unpack('<I', uc_.mem_read(esp + off, 4))[0]
        if address == wfa:
            buf, ln = u32(8), u32(12)          # [esp]=ret addr; args start at +4
            if 0 < ln <= 64:
                log['events'].append(struct.unpack('<6I', bytes(uc_.mem_read(buf, ln))))
        elif address == spawn:
            log['spawns'] += 1
            uc_.mem_write(f6bc, struct.pack('<I', 2))
            if consume:
                q = struct.unpack('<I', uc_.mem_read(R_NETOBJ + 0x84B4, 4))[0]
                if q:
                    uc_.mem_write(R_NETOBJ + 0x84B4, struct.pack('<I', q - 1))
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=R_STUBS, end=R_STUBS + 0x20000)
    try:
        uc.emu_start(R_CODE, 0, timeout=0, count=max_insns)
    except UcError as error:
        log['error'] = str(error)
    from unicorn.x86_const import UC_X86_REG_EIP as _EIP
    log['pc'] = uc.reg_read(_EIP)
    log['blob_head'] = struct.unpack('<IIII', bytes(uc.mem_read(R_BLOB, 16)))
    log['queue_mem'] = struct.unpack('<I', bytes(uc.mem_read(R_NETOBJ + 0x84B4, 4)))[0]
    log['f6bc_mem'] = struct.unpack('<I', bytes(uc.mem_read(R_CORE + 0x6BC, 4)))[0]
    log['rows'] = log['events']                                  # full 6-u32 rows
    log['events'] = [row[2] for row in log['rows']]              # event column
    return log


class TestRoundsAgentD(unittest.TestCase):
    """Queue-gated variant (agent_rounds_d.bin): anti-spin + progress accounting."""

    def test_queue_gate_never_fires_when_idle(self):
        # The 15:16 spin state: done flag flaps while nothing is queued.
        log = run_rounds(ROUNDS_D_DEFAULT, queue=0)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 0, 'no spawn may happen with an empty queue')
        self.assertEqual(log['events'], [])

    def test_follows_and_consumes_backlog(self):
        log = run_rounds(ROUNDS_D_DEFAULT, queue=3)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 3)
        self.assertEqual(log['events'], [0, 2, 0, 2, 0, 2])

    def test_no_progress_trips_guard(self):
        log = run_rounds(ROUNDS_D_DEFAULT, queue=2, consume=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 8, 'guard trips after 8 no-progress cycles')
        self.assertEqual(log['events'], [0, 5] * 8 + [6])
        self.assertEqual(log['spawns'], log['events'].count(0))

    def test_finished_after_max_rounds(self):
        log = run_rounds(ROUNDS_D_DEFAULT, queue=5, max_rounds=2)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 2)
        self.assertEqual(log['events'], [0, 2, 0, 2, 3])

    def test_no_trigger_waits(self):
        log = run_rounds(ROUNDS_D_DEFAULT, queue=3, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 0)
        self.assertEqual(log['events'], [])


ROUNDS_E_DEFAULT = Path(os.environ.get(
    'P51_ROUNDS_E_BIN',
    ROOT.parent.parent / 'protocol-archive/evidence/p51-rounds-e-20261018/agent-build/agent_rounds_e.bin'))

R_CLOCK = R_STUBS + 0x18000


def run_rounds_e(bin_path, *, mode='progress', max_rounds=50, trigger=True, max_insns=3000000):
    """Emulation of the effect-verified variant E with a virtual clock.

    modes: progress (round completes with a phase step, f6bc 1->2)
           missed   (f6bc 1->0 with a phase step: the missed-2 case)
           noop     (f6bc 1->2 without progress; rx bumps so the gate reopens)
           one_progress_then_noop (first cycle progresses; then one no-op)
           stuck    (f6bc stays 1: the abort -> fuse path)
    """
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((R_CODE, 0x1000), (R_BLOB, 0x2000), (R_COREM, 0x2000),
                       (R_NETOBJ, 0x9000), (R_STUBS, 0x20000), (R_STACK, 0x10000),
                       (R_SPIN, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(R_CODE, code)
    sb = _stub_bytes()
    gfa, cfa, wfa, setev, sleep, tick, spawn = (R_STUBS + i * 0x1000 for i in range(7))
    uc.mem_write(gfa, sb['gfa'] if trigger else sb['gfa_missing'])
    uc.mem_write(cfa, sb['cfa'])
    uc.mem_write(wfa, b'\xb8\x01\x00\x00\x00\xc2\x14\x00')
    uc.mem_write(setev, b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    uc.mem_write(sleep, b'\xb8\x00\x00\x00\x00\xc2\x04\x00')
    uc.mem_write(tick, b'\xa1' + struct.pack('<I', R_CLOCK) + b'\xc3')
    uc.mem_write(spawn, b'\xb8\x00\x00\x00\x00\xc3')
    uc.mem_write(R_CLOCK, struct.pack('<I', 1000))
    uc.mem_write(R_NETOBJ + 0x8444, struct.pack('<I', 0))
    f6bc = R_CORE + 0x6BC
    uc.mem_write(f6bc, struct.pack('<I', 1 if mode == 'prewait_stuck' else 0))
    uc.mem_write(R_CORE + 0x4D0, struct.pack('<I', 0x00C80000))
    uc.mem_write(R_CORE + 0x4D4, struct.pack('<I', 0))
    pointers = {'GetFileAttributesA': gfa, 'CreateFileA': cfa, 'WriteFileA': wfa,
                'SetEvent': setev, 'Sleep': sleep, 'GetTickCount': tick}
    blob = inj.build_rounds_blob(inj.MAGIC, R_NETOBJ, R_CORE, spawn, pointers,
                                 'Z:\\test\\flag', 'Z:\\test\\receipt', max_rounds)
    uc.mem_write(R_BLOB, blob)
    esp0 = R_STACK + 0xF000
    uc.mem_write(esp0, struct.pack('<II', R_SPIN, R_BLOB))
    uc.mem_write(R_SPIN, b'\xeb\xfe')
    uc.reg_write(UC_X86_REG_ESP, esp0)

    log = {'events': [], 'spawns': 0, 'setevents': 0, 'error': None}
    st = {'sleeps_in_round': 0}

    def clock():
        return struct.unpack('<I', uc.mem_read(R_CLOCK, 4))[0]

    def bump_rx():
        rx = struct.unpack('<I', uc.mem_read(R_NETOBJ + 0x8444, 4))[0]
        uc.mem_write(R_NETOBJ + 0x8444, struct.pack('<I', rx + 1))

    def step_round():
        v = struct.unpack('<I', uc.mem_read(R_CORE + 0x4D4, 4))[0]
        uc.mem_write(R_CORE + 0x4D4, struct.pack('<I', v + 1))

    def on_code(u, address, size, data):
        esp = u.reg_read(UC_X86_REG_ESP)

        def u32(off):
            return struct.unpack('<I', u.mem_read(esp + off, 4))[0]
        if address == wfa:
            buf, ln = u32(8), u32(12)
            if 0 < ln <= 64:
                log['events'].append(struct.unpack('<6I', bytes(u.mem_read(buf, ln)))[2])
        elif address == spawn:
            log['spawns'] += 1
            st['sleeps_in_round'] = 0
            u.mem_write(f6bc, struct.pack('<I', 1))
            if mode == 'ghost0':          # worker never signals: premature-0 case
                u.mem_write(f6bc, struct.pack('<I', 0))
        elif address == setev:
            log['setevents'] += 1
        elif address == sleep:
            u.mem_write(R_CLOCK, struct.pack('<I', (clock() + u32(4)) & 0xFFFFFFFF))
            st['sleeps_in_round'] += 1
            n = st['sleeps_in_round']
            if mode == 'progress' and n == 1:
                u.mem_write(f6bc, struct.pack('<I', 2))
                step_round()
            elif mode == 'missed' and n == 2:
                u.mem_write(f6bc, struct.pack('<I', 0))
                step_round()
            elif mode == 'noop' and n == 1:
                u.mem_write(f6bc, struct.pack('<I', 2))
                bump_rx()
            elif mode == 'one_progress_then_noop' and n == 1:
                u.mem_write(f6bc, struct.pack('<I', 2))
                if log['spawns'] == 1:
                    step_round()
            elif mode == 'prewait_stuck':
                if struct.unpack('<I', u.mem_read(f6bc, 4))[0] == 0:
                    u.mem_write(f6bc, struct.pack('<I', 1))  # re-stick after a force-clear
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=R_STUBS, end=R_STUBS + 0x20000)
    try:
        uc.emu_start(R_CODE, 0, timeout=0, count=max_insns)
    except UcError as error:
        log['error'] = str(error)
    return log


class TestRoundsAgentE(unittest.TestCase):
    """Effect-verified variant E (agent_rounds_e.bin)."""

    def test_progress_follows_and_finishes(self):
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='progress', max_rounds=3)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 3)
        self.assertEqual(log['events'], [0, 2, 0, 2, 0, 2, 3])

    def test_missed_done_still_completes(self):
        # The 15:41 live hang: f6bc cleared to 0 without a visible 2.
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='missed', max_rounds=1)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 1)
        self.assertEqual(log['events'], [0, 2, 3])

    def test_gate_blocks_after_noop_until_new_frames(self):
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='one_progress_then_noop', max_rounds=50)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 2, 'no new frames -> no further fires')
        self.assertEqual(log['events'], [0, 2, 0, 5])

    def test_noop_backoff_until_fuse(self):
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='noop', max_rounds=50)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 6)
        self.assertEqual(log['events'], [0, 5] * 6 + [6])

    def test_stuck_aborts_then_fuse(self):
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='stuck', max_rounds=50)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 3)
        self.assertEqual(log['setevents'], 3, 'SetEvent(0x84A4) per aborted round')
        self.assertEqual(log['events'], [0, 7, 0, 7, 0, 7, 6])

    def test_premature_zero_is_not_a_completion(self):
        # f6bc==0 right after the spawn (worker never signalled): never accepted
        # as done -> abort path -> fuse. This was the 15:59 double-spawn wedge.
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='ghost0', max_insns=3000000)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 3)
        self.assertEqual(log['setevents'], 3)
        self.assertEqual(log['events'], [0, 7, 0, 7, 0, 7, 6])

    def test_prewait_retries_then_idle(self):
        # f6bc stuck at 1 from the start: 5 prewait timeouts, then idle (no spawn).
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='prewait_stuck', max_insns=3000000)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 0)
        self.assertEqual(log['events'], [4, 4, 4, 4, 4])

    def test_no_trigger_stays_idle(self):
        log = run_rounds_e(ROUNDS_E_DEFAULT, mode='progress', trigger=False, max_insns=200000)
        self.assertIsNone(log['error'])
        self.assertEqual(log['spawns'], 0)
        self.assertEqual(log['events'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
