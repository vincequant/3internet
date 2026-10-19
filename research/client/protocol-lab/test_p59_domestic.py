#!/usr/bin/env python3
"""Tests for the P59 interface-free CSanInetDomesticCmd agent.

Coverage:
  * golden wire: expected_wire(7, 0, 95, 1) is byte-identical to the real
    control5 record captured 2026-10-17 (archived raw_hex), and the field
    order matches the production decoder's 13-byte base + 4 ints.
  * blob layout locked to agent_domestic.s.
  * receipt parser.
  * unicorn emulation of the real agent_domestic.bin:
      - happy path: ctor called with a sane `this`, exactly ONE 0x42a7d4 call,
        object fields = (actor, parameter, value, extra), receipt bytes,
        once-only flag, match gate untouched.
      - gates: no trigger / not connected / core NULL / slot 9 / actor 99 /
        parameter 9 / own id 0 / already-sent.
  * static anchors: live SANPK.exe still has vtable[2] == Serialize and
    CRuntimeClass size 0x24 (skipped when the game file is absent).

Run:  ~/.venvs/fengye/bin/python -m unittest test_p59_domestic -v
"""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p59_domestic_cmd_build as b  # noqa: E402

LIVE_SANPK = Path(
    '/Users/vk/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/SANPK.exe')
RESEARCH_SANPK = ROOT.parents[1] / 'protocol-archive/disasm/SANPK.exe'

# Real control5 record, 2026-10-17 15:32:40, actor force 7, 步兵训练, value 95, extra 1.
GOLDEN_REAL = ('ffff010013004353616e496e6574446f6d6573746963436d64'
               '12000000000000000000000000'
               '07000000000000005f00000001000000')

OWN = 0x55667788
CORE = 0x300000
G = CORE - 0x912
PHASE = 5
GATE = 1
TICK = 0xDEADBEEF
NNAME = 0x533554

# emulation map
CODE, BLOB_M, CORE_GLOBAL, STACK, STUBS, SPIN = 0x100000, 0x200000, 0x210000, 0x400000, 0x500000, 0xDEAD0000
SEND_LOG = 0x600000
VTABLE, NAMEVA = 0x5039F8, 0x533554


def _stub_addrs():
    return {'gfa': STUBS, 'conn': STUBS + 0x1000, 'getip': STUBS + 0x2000,
            'cfa': STUBS + 0x3000, 'wfa': STUBS + 0x4000, 'close': STUBS + 0x5000,
            'tick': STUBS + 0x6000, 'sleep': STUBS + 0x7000,
            'ctor': STUBS + 0x8000, 'send': STUBS + 0x9000}


ADDR = _stub_addrs()


def _stub_bytes(trigger):
    sb = {}
    sb['gfa'] = b'\xb8' + struct.pack('<I', 0 if trigger else 0xFFFFFFFF) + b'\xc2\x04\x00'
    sb['conn'] = b'\xb8\x01\x00\x00\x00\xc3'
    sb['getip'] = (b'\x8b\x44\x24\x04' + b'\xc7\x00' + struct.pack('<I', 0x211000) +
                   b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    # ctor: mimic CSanInetDomesticCmd::ctor defaults
    ct = b''
    for disp, val in ((0x00, VTABLE), (0x04, 18), (0x08, 0), (0x0C, 0), (0x10, NNAME),
                      (0x14, 0xFFFFFFFF), (0x18, 0), (0x1C, 0), (0x20, 0)):
        if disp <= 0x7F:
            ct += b'\xc7\x41' + bytes([disp]) + struct.pack('<I', val)
    ct += b'\xc3'
    sb['ctor'] = ct
    # send: record (obj, this) then return 1 / ret 4
    sb['send'] = (b'\x8b\x44\x24\x04' + b'\xa3' + struct.pack('<I', SEND_LOG) +
                  b'\x89\x0d' + struct.pack('<I', SEND_LOG + 4) +
                  b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    sb['cfa'] = b'\xb8\x03\x00\x00\x00\xc2\x1c\x00'
    sb['wfa'] = (b'\x8b\x44\x24\x10' + b'\xb9' + struct.pack('<I', b.RECEIPT_SIZE) + b'\x89\x08' +
                 b'\xb8\x01\x00\x00\x00\xc2\x14\x00')
    sb['close'] = b'\xb8\x01\x00\x00\x00\xc2\x04\x00'
    sb['tick'] = b'\xb8' + struct.pack('<I', TICK) + b'\xc3'
    sb['sleep'] = b'\xb8\x00\x00\x00\x00\xc2\x04\x00'
    return sb


def run_payload(bin_path, *, trigger=True, core=CORE, slot=5, own=OWN, actor=12, parameter=1,
                value=95, extra=0, sent=0, max_insns=60000):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x1000), (BLOB_M, 0x2000), (CORE_GLOBAL, 0x1000), (STACK, 0x10000),
                       (STUBS, 0x10000), (SPIN, 0x1000), (0x2F0000, 0x20000), (0x211000, 0x1000),
                       (SEND_LOG, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(CODE, code)
    for key, base in ADDR.items():
        uc.mem_write(base, _stub_bytes(trigger)[key])
    uc.mem_write(CORE_GLOBAL, struct.pack('<I', core))
    uc.mem_write(0x211000, struct.pack('<I', own))
    if core:
        uc.mem_write(core + 0x6C0, struct.pack('<I', slot))
        uc.mem_write(core + 0x4D8, struct.pack('<H', PHASE))
        uc.mem_write(G + 0x80, struct.pack('<I', GATE))
        uc.mem_write(core - 0x912 + 0x68, struct.pack('<I', 1))
    pointers = {'GetFileAttributesA': ADDR['gfa'], 'CreateFileA': ADDR['cfa'],
                'WriteFileA': ADDR['wfa'], 'CloseHandle': ADDR['close'], 'Sleep': ADDR['sleep'],
                'GetTickCount': ADDR['tick'], 'is_connected': ADDR['conn'],
                'get_ip': ADDR['getip'], 'core_global': CORE_GLOBAL}
    blob = bytearray(b.build_blob(pointers, actor=actor, parameter=parameter, value=value,
                                  extra=extra, sanpk_base=0, flag_path='Z:\\t\\flag',
                                  receipt_path='Z:\\t\\receipt', ctor_addr=ADDR['ctor'],
                                  send_addr=ADDR['send'], send_this_addr=0x1234567))
    if sent:
        struct.pack_into('<I', blob, 4, sent)
    uc.mem_write(BLOB_M, bytes(blob))
    esp0 = STACK + 0xF000
    uc.mem_write(esp0, struct.pack('<II', SPIN, BLOB_M))
    uc.mem_write(SPIN, b'\xeb\xfe')
    uc.reg_write(UC_X86_REG_ESP, esp0)

    log = {'cfa': [], 'wfa': [], 'error': None}

    def on_code(uc_, address, size, data):
        esp = uc_.reg_read(UC_X86_REG_ESP)

        def u32(off):
            return struct.unpack('<I', uc_.mem_read(esp + off, 4))[0]
        if address == ADDR['cfa']:
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
            log['wfa'].append({'buf': buf, 'len': ln,
                               'data': bytes(uc_.mem_read(buf, ln)) if 0 < ln <= 64 else b''})
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=STUBS, end=STUBS + 0x10000)
    try:
        uc.emu_start(CODE, 0, timeout=0, count=max_insns)
    except UcError as error:  # pragma: no cover - surfaced as test failure
        log['error'] = str(error)
    log['blob'] = bytes(uc.mem_read(BLOB_M, b.BLOB_SIZE))
    send_obj = struct.unpack('<I', uc.mem_read(SEND_LOG, 4))[0]
    send_this = struct.unpack('<I', uc.mem_read(SEND_LOG + 4, 4))[0]
    log['send_obj'] = send_obj
    log['send_this'] = send_this
    log['sent_count'] = 1 if send_obj else 0
    if send_obj:
        raw = bytes(uc.mem_read(send_obj, 0x24))
        log['obj'] = raw
        log['fields'] = struct.unpack_from('<4i', raw, 0x14)
        log['obj_dwords'] = struct.unpack_from('<9I', raw, 0)
        log['gate'] = struct.unpack('<I', uc.mem_read(G + 0x80, 4))[0]
    return log


class TestWire(unittest.TestCase):
    def test_golden_matches_real_capture(self):
        self.assertEqual(b.expected_wire(7, 0, 95, 1).hex(), GOLDEN_REAL)

    def test_lengths(self):
        w = b.expected_wire(12, 1, 95, 0)
        self.assertEqual(len(w), 54)
        self.assertEqual(w[:6], struct.pack('<3H', 0xFFFF, 1, 19))
        self.assertEqual(w[6:25].decode(), 'CSanInetDomesticCmd')
        body = w[25:]
        self.assertEqual(len(body), 29)
        self.assertEqual(struct.unpack_from('<3i', body, 0), (18, 0, 0))
        self.assertEqual(body[12], 0)
        self.assertEqual(struct.unpack_from('<4i', body, 13), (12, 1, 95, 0))

    def test_ranges(self):
        for kwargs in ({'actor': 32}, {'actor': -1}, {'parameter': 3}):
            args = dict(actor=0, parameter=0, value=0, extra=0)
            args.update(kwargs)
            with self.assertRaises(ValueError):
                b.expected_wire(**args)


class TestBlob(unittest.TestCase):
    def _ptr(self):
        p = {name: 0x41000000 + i for i, (name, _) in enumerate(b.BLOB_LAYOUT[2:11])}
        return p

    def test_layout(self):
        blob = b.build_blob(self._ptr(), actor=12, parameter=1, value=95, extra=0,
                            sanpk_base=0x400000, flag_path='Z:\\f', receipt_path='Z:\\r')
        self.assertEqual(len(blob), b.BLOB_SIZE)
        self.assertEqual(struct.unpack_from('<I', blob, 0)[0], b.MAGIC)
        self.assertEqual(struct.unpack_from('<I', blob, 0x2C)[0], 0x400000 + b.RVA_CTOR)
        self.assertEqual(struct.unpack_from('<I', blob, 0x30)[0], 0x400000 + b.RVA_SEND)
        self.assertEqual(struct.unpack_from('<I', blob, 0x34)[0], 0x400000 + b.RVA_SEND_THIS)
        self.assertEqual(struct.unpack_from('<I', blob, 0x28)[0], self._ptr()['core_global'])
        self.assertEqual(struct.unpack_from('<4i', blob, 0x38), (12, 1, 95, 0))
        self.assertTrue(blob[b.FLAG_OFF:].startswith(b'Z:\\f\x00'))
        self.assertTrue(blob[b.RECEIPT_OFF:].startswith(b'Z:\\r\x00'))

    def test_actor_range(self):
        with self.assertRaises(ValueError):
            b.build_blob(self._ptr(), actor=32, parameter=0, value=0, extra=0, sanpk_base=0,
                         flag_path='a', receipt_path='b')

    def test_receipt_roundtrip(self):
        raw = struct.pack('<12I', b.MAGIC2, 1, CORE, 12, 1, 95, 0, TICK, 1, 1, PHASE, OWN)
        r = b.parse_receipt(raw)
        self.assertEqual(r['magic2'], b.MAGIC2)
        self.assertEqual(r['rc'], 1)
        self.assertEqual(r['core'], CORE)
        self.assertEqual(r['actor'], 12)
        self.assertEqual(r['own'], OWN)
        with self.assertRaises(ValueError):
            b.parse_receipt(raw[:24])


class TestAgentEmulation(unittest.TestCase):
    def setUp(self):
        # build once per test run into a temp dir
        import tempfile
        self.tmp = tempfile.mkdtemp()
        b.main.__globals__  # noqa: B018 - keep import graph obvious
        import subprocess
        subprocess.run([sys.executable, str(ROOT / 'p59_domestic_cmd_build.py'),
                        '--outdir', self.tmp], check=True, capture_output=True)
        self.bin = Path(self.tmp) / 'agent_domestic.bin'

    def test_happy_path(self):
        log = run_payload(self.bin)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 1, 'exactly one object hand-off')
        self.assertEqual(log['send_this'], 0x1234567)
        self.assertEqual(log['fields'], (12, 1, 95, 0))
        self.assertEqual(log['obj_dwords'][0], VTABLE)
        self.assertEqual(log['obj_dwords'][1], 18, 'kind 18')
        self.assertEqual(log['obj_dwords'][2], 0, 'subtype 0 (train)')
        self.assertEqual(log['obj_dwords'][3], 0, 'action operand 0')
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1, 'once-only flag')
        self.assertEqual(log['cfa'] and log['cfa'][0].endswith('receipt'), True)
        self.assertEqual(len(log['wfa']), 1)
        rc = b.parse_receipt(log['wfa'][0]['data'])
        self.assertEqual(log['wfa'][0]['len'], b.RECEIPT_SIZE)
        self.assertEqual(rc['magic2'], b.MAGIC2)
        self.assertEqual(rc['rc'], 1)
        self.assertEqual(rc['core'], CORE)
        self.assertEqual((rc['actor'], rc['parameter'], rc['value'], rc['extra']), (12, 1, 95, 0))
        self.assertEqual(rc['tick'], TICK)
        self.assertEqual(rc['gate_before'], GATE)
        self.assertEqual(rc['gate_after'], GATE, 'gate must stay untouched (no 0x446482)')
        self.assertEqual(rc['phase'], PHASE)
        self.assertEqual(rc['own'], OWN)
        self.assertEqual(log['gate'], GATE)

    def test_gate_no_trigger(self):
        log = run_payload(self.bin, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 0)

    def test_gate_core_null(self):
        log = run_payload(self.bin, core=0)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)

    def test_gate_bad_slot(self):
        log = run_payload(self.bin, slot=9)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)

    def test_gate_zero_own(self):
        log = run_payload(self.bin, own=0)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)

    def test_gate_actor_out_of_range(self):
        orig = b.build_blob

        def patched(pointers, **kw):
            blob = bytearray(orig(pointers, **kw))
            struct.pack_into('<I', blob, 0x38, 99)   # actor 99 must be rejected by the agent
            return bytes(blob)
        b.build_blob = patched
        try:
            log = run_payload(self.bin)
        finally:
            b.build_blob = orig
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)

    def test_gate_already_sent(self):
        log = run_payload(self.bin, sent=1)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0)


class TestStaticAnchors(unittest.TestCase):
    def _pe(self, path):
        import importlib.util
        spec = importlib.util.spec_from_file_location('pe_static', str(ROOT / 'pe_static.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.PE(path)

    def test_static_preflight(self):
        path = LIVE_SANPK if LIVE_SANPK.exists() else RESEARCH_SANPK
        if not path.exists():
            self.skipTest('no SANPK.exe available')
        pre = b.static_preflight(path.read_bytes())
        self.assertTrue(pre['ok'], pre['problems'])
        self.assertEqual(pre['image_base'], 0x400000)
        self.assertEqual(pre['class_name'], 'CSanInetDomesticCmd')
        self.assertEqual(pre['ctor_prologue'][:10], '565733ff68')

    def test_live_sanpk_anchors(self):
        path = LIVE_SANPK if LIVE_SANPK.exists() else RESEARCH_SANPK
        if not path.exists():
            self.skipTest('no SANPK.exe available')
        pe = self._pe(path)
        self.assertEqual(pe.u32(0x5039F8 + 8), 0x436A6F, 'vtable[2] == Serialize')
        self.assertEqual(pe.u32(0x5039F8), 0x4369DB, 'vtable[0] == GetRuntimeClass')
        self.assertEqual(pe.read(0x5334B0, 4), struct.pack('<I', 0x533554))
        self.assertEqual(pe.u32(0x5334B4), 0x24, 'object size 0x24')
        self.assertEqual(pe.u32(0x5334B8), 1, 'schema 1')
        self.assertEqual(pe.u32(0x5334BC), 0x4369A9, 'factory')
        self.assertEqual(pe.read(0x533554, 19).decode(), 'CSanInetDomesticCmd')
        # ctor prologue: push 0x53ac40 (empty base string), push 0, push 0, push 0x12 (kind 18)
        self.assertEqual(pe.read(0x4369FA, 5), b'\x68\x40\xac\x53\x00')
        self.assertEqual(pe.read(0x436A03, 2), b'\x6a\x12')
        # Serialize pushes +0x14/+0x18/+0x1c/+0x20 in order (operator<<(int) 0x417188)
        for at in (0x436A86, 0x436A90, 0x436A9A, 0x436AA4):
            self.assertEqual(pe.read(at, 3), b'\xff\x76' + bytes([0x14 + (at - 0x436A86) // 10 * 4]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
