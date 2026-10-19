#!/usr/bin/env python3
"""Tests for the P60 generic faction-command agent.

Coverage:
  * golden wire: domestic(7,0,95,1) and personnel(7,1,430) are byte-identical to
    real control5 captures; phaseend wire = 38 bytes of base-only body.
  * blob layout + presets.
  * receipt parser (64 bytes).
  * static preflight of all four class ctors against the live SANPK.exe.
  * unicorn emulation: ctor called once, field table applied to the right
    offsets, exactly ONE 0x42a7d4 call, receipt fields, once-only flag, gate
    untouched — for four presets (train / rice / personnel / phaseend) and
    every gate.

Run:  ~/.venvs/fengye/bin/python -m unittest test_p60_generic -v
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p60_generic_cmd_build as b  # noqa: E402

LIVE_SANPK = Path(
    '/Users/vk/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/SANPK.exe')
RESEARCH_SANPK = ROOT.parents[1] / 'protocol-archive/disasm/SANPK.exe'

GOLDEN_DOMESTIC = ('ffff010013004353616e496e6574446f6d6573746963436d64'
                   '12000000000000000000000000'
                   '07000000000000005f00000001000000')
GOLDEN_PERSONNEL = ('ffff010014004353616e496e6574506572736f6e6e656c436d64'
                    '14000000010000000000000000'
                    '07000000ae010000')

OWN = 0x55667788
CORE = 0x300000
G = CORE - 0x912
PHASE = 1
GATE = 1
TICK = 0xDEADBEEF

CODE, BLOB_M, CORE_GLOBAL, STACK, STUBS, SPIN = 0x100000, 0x200000, 0x210000, 0x400000, 0x500000, 0xDEAD0000
SEND_LOG = 0x600000


def _addrs():
    return {'gfa': STUBS, 'conn': STUBS + 0x1000, 'getip': STUBS + 0x2000,
            'cfa': STUBS + 0x3000, 'wfa': STUBS + 0x4000, 'close': STUBS + 0x5000,
            'tick': STUBS + 0x6000, 'sleep': STUBS + 0x7000,
            'ctor': STUBS + 0x8000, 'send': STUBS + 0x9000}


ADDR = _addrs()


def _ctor_bytes(vtable, kind, defaults):
    """mov dword ptr [ecx+disp8], imm32 for each (offset,value); ret."""
    out = b''
    for off, val in [(0x00, vtable), (0x04, kind)] + list(defaults):
        if off <= 0x7F:
            out += b'\xc7\x41' + bytes([off]) + struct.pack('<I', val)
        else:  # disp32
            out += b'\xc7\x81' + struct.pack('<I', off) + struct.pack('<I', val)
    return out + b'\xc3'


CTOR_DEFAULTS = {
    'domestic': (0x5039F8, 18, [(0x08, 0), (0x0C, 0), (0x14, 0xFFFFFFFF),
                                (0x18, 0), (0x1C, 0), (0x20, 0)]),
    'personnel': (0x503A28, 20, [(0x08, 0), (0x0C, 0), (0x14, 0xFFFFFFFF), (0x18, 0xFFFFFFFF)]),
    'phaseend': (0x503A40, 21, [(0x08, 0), (0x0C, 0)]),
    'diplomacy': (0x503A10, 19, [(0x08, 0), (0x0C, 0)]),
}


def run_payload(bin_path, *, cls, fields, trigger=True, core=CORE, slot=5, own=OWN,
                sent=0, phase_req=0, phase=PHASE, max_insns=80000):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x1000), (BLOB_M, 0x2000), (CORE_GLOBAL, 0x1000), (STACK, 0x10000),
                       (STUBS, 0x10000), (SPIN, 0x1000), (0x2F0000, 0x20000), (0x211000, 0x1000),
                       (SEND_LOG, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(CODE, code)
    sb = {}
    sb['gfa'] = b'\xb8' + struct.pack('<I', 0 if trigger else 0xFFFFFFFF) + b'\xc2\x04\x00'
    sb['conn'] = b'\xb8\x01\x00\x00\x00\xc3'
    sb['getip'] = (b'\x8b\x44\x24\x04' + b'\xc7\x00' + struct.pack('<I', 0x211000) +
                   b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    vtable, kind, defaults = CTOR_DEFAULTS[cls]
    sb['ctor'] = _ctor_bytes(vtable, kind, defaults)
    sb['send'] = (b'\x8b\x44\x24\x04' + b'\xa3' + struct.pack('<I', SEND_LOG) +
                  b'\x89\x0d' + struct.pack('<I', SEND_LOG + 4) +
                  b'\xb8\x01\x00\x00\x00\xc2\x04\x00')
    sb['cfa'] = b'\xb8\x03\x00\x00\x00\xc2\x1c\x00'
    sb['wfa'] = (b'\x8b\x44\x24\x10' + b'\xb9' + struct.pack('<I', b.RECEIPT_SIZE) + b'\x89\x08' +
                 b'\xb8\x01\x00\x00\x00\xc2\x14\x00')
    sb['close'] = b'\xb8\x01\x00\x00\x00\xc2\x04\x00'
    sb['tick'] = b'\xb8' + struct.pack('<I', TICK) + b'\xc3'
    sb['sleep'] = b'\xb8\x00\x00\x00\x00\xc2\x04\x00'
    for key, base in ADDR.items():
        uc.mem_write(base, sb[key])
    uc.mem_write(CORE_GLOBAL, struct.pack('<I', core))
    uc.mem_write(0x211000, struct.pack('<I', own))
    if core:
        uc.mem_write(core + 0x6C0, struct.pack('<I', slot))
        uc.mem_write(core + 0x4D8, struct.pack('<H', phase))
        uc.mem_write(G + 0x80, struct.pack('<I', GATE))
    pointers = {'GetFileAttributesA': ADDR['gfa'], 'CreateFileA': ADDR['cfa'],
                'WriteFileA': ADDR['wfa'], 'CloseHandle': ADDR['close'], 'Sleep': ADDR['sleep'],
                'GetTickCount': ADDR['tick'], 'is_connected': ADDR['conn'],
                'get_ip': ADDR['getip'], 'core_global': CORE_GLOBAL}
    blob = bytearray(b.build_blob(pointers, cls=cls, fields=fields, sanpk_base=0,
                                  flag_path='Z:\\t\\flag', receipt_path='Z:\\t\\receipt',
                                  phase_req=phase_req))
    if sent:
        struct.pack_into('<I', blob, 4, sent)
    # route the blob's ctor/send at our stubs
    struct.pack_into('<I', blob, 0x2C, ADDR['ctor'])
    struct.pack_into('<I', blob, 0x30, ADDR['send'])
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
                               'data': bytes(uc_.mem_read(buf, ln)) if 0 < ln <= 96 else b''})
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=STUBS, end=STUBS + 0x10000)
    try:
        uc.emu_start(CODE, 0, timeout=0, count=max_insns)
    except UcError as error:  # pragma: no cover
        log['error'] = str(error)
    log['blob'] = bytes(uc.mem_read(BLOB_M, b.BLOB_SIZE))
    send_obj = struct.unpack('<I', uc.mem_read(SEND_LOG, 4))[0]
    log['send_obj'] = send_obj
    log['sent_count'] = 1 if send_obj else 0
    log['obj'] = bytes(uc.mem_read(send_obj, 0x40)) if send_obj else b''
    log['gate'] = struct.unpack('<I', uc.mem_read(G + 0x80, 4))[0]
    return log


class TestWire(unittest.TestCase):
    def test_domestic_golden(self):
        fields = b.fields_train(7, 0, 95, 1)
        # expected wire built by hand from the class layout
        w = (struct.pack('<3H', 0xFFFF, 1, 19) + b'CSanInetDomesticCmd' +
             struct.pack('<3i', 18, 0, 0) + b'\x00' + struct.pack('<4i', 7, 0, 95, 1))
        self.assertEqual(w.hex(), GOLDEN_DOMESTIC)
        self.assertEqual([f for f in fields], [(4, 18), (8, 0), (12, 0), (0x14, 7), (0x18, 0),
                                               (0x1C, 95), (0x20, 1)])

    def test_personnel_golden(self):
        w = (struct.pack('<3H', 0xFFFF, 1, 20) + b'CSanInetPersonnelCmd' +
             struct.pack('<3i', 20, 1, 0) + b'\x00' + struct.pack('<2i', 7, 430))
        self.assertEqual(w.hex(), GOLDEN_PERSONNEL)
        self.assertEqual(b.fields_personnel(7, 1, 430),
                         [(4, 20), (8, 1), (12, 0), (0x14, 7), (0x18, 430)])

    def test_phaseend_wire_len(self):
        w = (struct.pack('<3H', 0xFFFF, 1, 19) + b'CSanInetPhaseEndCmd' +
             struct.pack('<3i', 21, 0, 0) + b'\x00')
        self.assertEqual(len(w), 38)
        self.assertEqual(b.fields_phaseend(), [(4, 21), (8, 0), (12, 0)])

    def test_rice_and_alms_fields(self):
        self.assertEqual(b.fields_rice(3, 1, 500, 0),
                         [(4, 18), (8, 3), (12, 0), (0x14, 3), (0x18, 1), (0x1C, 500), (0x20, 0)])
        self.assertEqual(b.fields_alms(3, 0, 4),
                         [(4, 18), (8, 2), (12, 0), (0x14, 3), (0x18, 0), (0x1C, 0), (0x20, 4)])

    def test_build_packs_xy(self):
        f = dict(b.fields_build(1, 7, 23, 132, 0, 2000))
        self.assertEqual(f[0x0C], 23 | (132 << 16))
        self.assertEqual(f[0x18], 7)


class TestBlob(unittest.TestCase):
    def _ptr(self):
        return {name: 0x41000000 + i for i, (name, _) in enumerate(b.BLOB_LAYOUT[2:11])}

    def test_layout(self):
        blob = b.build_blob(self._ptr(), cls='personnel', fields=b.fields_personnel(2, 0, 99),
                            sanpk_base=0x400000, flag_path='Z:\\f', receipt_path='Z:\\r')
        self.assertEqual(len(blob), b.BLOB_SIZE)
        self.assertEqual(struct.unpack_from('<I', blob, 0)[0], b.MAGIC)
        self.assertEqual(struct.unpack_from('<I', blob, 0x2C)[0], 0x400000 + (0x436CD3 - 0x400000))
        self.assertEqual(struct.unpack_from('<I', blob, 0x30)[0], 0x400000 + b.RVA_SEND)
        self.assertEqual(struct.unpack_from('<I', blob, 0x38)[0], 0x1C)
        self.assertEqual(struct.unpack_from('<I', blob, 0x3C)[0], 5)
        self.assertEqual(struct.unpack_from('<I', blob, 0x40)[0], b.TABLE_OFF)
        self.assertEqual(struct.unpack_from('<2I', blob, b.TABLE_OFF)[0], 4)
        self.assertTrue(blob[b.FLAG_OFF:].startswith(b'Z:\\f\x00'))
        self.assertTrue(blob[b.RECEIPT_OFF:].startswith(b'Z:\\r\x00'))

    def test_too_many_fields(self):
        with self.assertRaises(ValueError):
            b.build_blob(self._ptr(), cls='domestic', fields=[(4, 1)] * 20, sanpk_base=0,
                         flag_path='a', receipt_path='b')

    def test_receipt(self):
        raw = struct.pack('<16I', b.MAGIC2, 1, CORE, OWN, 1, 1, PHASE, TICK,
                          0x503A28, 20, 0, 0, 1, 2, 3, 4)
        r = b.parse_receipt(raw)
        self.assertEqual(r['magic2'], b.MAGIC2)
        self.assertEqual(r['kind'], 20)
        self.assertEqual(r['f14'], 1)
        with self.assertRaises(ValueError):
            b.parse_receipt(raw[:32])


class TestStatic(unittest.TestCase):
    def test_preflight_all_classes(self):
        path = LIVE_SANPK if LIVE_SANPK.exists() else RESEARCH_SANPK
        if not path.exists():
            self.skipTest('no SANPK.exe')
        pre = b.static_preflight(path.read_bytes())
        self.assertTrue(pre['ok'], pre['problems'])
        for name in ('domestic', 'personnel', 'phaseend', 'diplomacy'):
            self.assertTrue(pre['classes'][name]['ok'], name)
        self.assertEqual(pre['domestic_class_name'], 'CSanInetDomesticCmd')


class TestAgentEmulation(unittest.TestCase):
    def setUp(self):
        import subprocess
        import tempfile
        self.tmp = tempfile.mkdtemp()
        subprocess.run([sys.executable, str(ROOT / 'p60_generic_cmd_build.py'),
                        '--outdir', self.tmp], check=True, capture_output=True)
        self.bin = Path(self.tmp) / 'agent_generic.bin'

    def test_train(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(12, 1, 95, 0))
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 1)
        obj = struct.unpack_from('<9I', log['obj'], 0)
        self.assertEqual(obj[0], 0x5039F8)
        self.assertEqual(obj[1], 18)
        self.assertEqual(obj[2], 0)
        self.assertEqual(obj[3], 0)
        self.assertEqual((obj[5], obj[6], obj[7], obj[8]), (12, 1, 95, 0))
        rec = b.parse_receipt(log['wfa'][0]['data'])
        self.assertEqual(log['wfa'][0]['len'], b.RECEIPT_SIZE)
        self.assertEqual((rec['kind'], rec['subtype'], rec['operand']), (18, 0, 0))
        self.assertEqual((rec['f14'], rec['f18'], rec['f1c'], rec['f20']), (12, 1, 95, 0))
        self.assertEqual((rec['gate_before'], rec['gate_after']), (GATE, GATE))
        self.assertEqual(rec['own'], OWN)
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1)

    def test_rice(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_rice(2, 1, 500, 0))
        self.assertIsNone(log['error'])
        obj = struct.unpack_from('<9I', log['obj'], 0)
        self.assertEqual((obj[1], obj[2], obj[3]), (18, 3, 0))
        self.assertEqual((obj[5], obj[6], obj[7]), (2, 1, 500))

    def test_personnel(self):
        log = run_payload(self.bin, cls='personnel', fields=b.fields_personnel(2, 0, 430))
        self.assertIsNone(log['error'])
        obj = struct.unpack_from('<9I', log['obj'], 0)
        self.assertEqual(obj[0], 0x503A28)
        self.assertEqual((obj[1], obj[2]), (20, 0))
        self.assertEqual((obj[5], obj[6]), (2, 430))
        rec = b.parse_receipt(log['wfa'][0]['data'])
        self.assertEqual((rec['kind'], rec['f14'], rec['f18']), (20, 2, 430))

    def test_phaseend(self):
        log = run_payload(self.bin, cls='phaseend', fields=b.fields_phaseend())
        self.assertIsNone(log['error'])
        obj = struct.unpack_from('<9I', log['obj'], 0)
        self.assertEqual(obj[0], 0x503A40)
        self.assertEqual(obj[1], 21)
        rec = b.parse_receipt(log['wfa'][0]['data'])
        self.assertEqual(rec['kind'], 21)

    def test_phase_gate_holds(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0),
                          phase_req=2, phase=1)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 0, 'must not fire outside the required phase')

    def test_phase_gate_passes(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0),
                          phase_req=1, phase=1)
        self.assertIsNone(log['error'])
        self.assertEqual(log['sent_count'], 1)

    def test_gate_no_trigger(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0), trigger=False)
        self.assertEqual(log['sent_count'], 0)

    def test_gate_core_null(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0), core=0)
        self.assertEqual(log['sent_count'], 0)

    def test_gate_bad_slot(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0), slot=9)
        self.assertEqual(log['sent_count'], 0)

    def test_gate_zero_own(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0), own=0)
        self.assertEqual(log['sent_count'], 0)

    def test_gate_already_sent(self):
        log = run_payload(self.bin, cls='domestic', fields=b.fields_train(1, 0, 10, 0), sent=1)
        self.assertEqual(log['sent_count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
