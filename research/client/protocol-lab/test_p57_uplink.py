#!/usr/bin/env python3
"""Tests for the P57 uplink agent (agent_uplink.bin).

The agent submits ONE caller-supplied payload through the verified reliable path
(0x4C80 GetHostOrSelfID -> 0x4B60 submit) and writes an 'SHG7' receipt. It is the
"forge one command as ourselves" tool: no seat change, no retries.

Run:  ~/.venvs/fengye/bin/python -m unittest test_p57_uplink -v
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p51_shadow_inject as inj  # noqa: E402
from test_p51_shadow import ADDR, BLOB_M, CODE, IDS, NETOBJ, OWN, SPIN, STACK, STUBS, TARGET, TICK  # noqa: E402

BUILD = Path(__file__).resolve().parents[2] / 'protocol-archive/evidence/p57-uplink-inject-20261019/build'
AGENT = BUILD / 'agent_uplink.bin'
BCAST = BUILD / 'agent_bcast.bin'

# frozen template: the real CSanInetUnitNetCmdCreate the host rebroadcast at
# 2026-10-19 07:21:20, with only soldiers/rice replaced by 54321.
CREATE_TEMPLATE = bytes.fromhex(
    'ffff010018004353616e496e6574556e69744e6574436d6443726561746510000000'
    '000000000000000000010000008000ffffffff31d4000031d400000b000300ffffffffffff')


def run_uplink(bin_path, payload, *, trigger=True, own=OWN, host_is_own=False, max_insns=120000,
               spoof_id=None):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UcError
    from unicorn.x86_const import UC_X86_REG_ESP
    import test_p51_shadow as H
    code = Path(bin_path).read_bytes()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x1000), (BLOB_M, 0x2000), (IDS, 0x1000), (NETOBJ, 0x9000),
                       (STACK, 0x10000), (STUBS, 0x11000), (SPIN, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(CODE, code)
    sb = H._stub_bytes()
    for key, base in ADDR.items():
        if key == 'gfa':
            uc.mem_write(base, sb['gfa'] if trigger else sb['gfa_missing'])
        elif key == 'c80':
            uc.mem_write(base, sb['c80_own'] if host_is_own else sb['c80'])
        else:
            uc.mem_write(base, sb[key])
    uc.mem_write(IDS, struct.pack('<I', own))
    pointers = {'GetFileAttributesA': ADDR['gfa'], 'CreateFileA': ADDR['cfa'], 'WriteFileA': ADDR['wfa'],
                'CloseHandle': ADDR['close'], 'Sleep': ADDR['sleep'], 'GetTickCount': ADDR['tick'],
                'is_connected': ADDR['conn'], 'get_ip': ADDR['getip'],
                'submit_4c80': ADDR['c80'], 'submit_4b60': ADDR['c60']}
    blob = inj.build_uplink_blob(inj.MAGIC, NETOBJ, pointers, payload, 'Z:\\test\\flag', 'Z:\\test\\receipt',
                                 spoof_id)
    uc.mem_write(BLOB_M, blob)
    esp0 = STACK + 0xF000
    uc.mem_write(esp0, struct.pack('<II', SPIN, BLOB_M))
    uc.mem_write(SPIN, b'\xeb\xfe')
    uc.reg_write(UC_X86_REG_ESP, esp0)

    log = {'c60': [], 'c80': 0, 'wfa': [], 'error': None}

    def on_code(uc_, address, size, data):
        esp = uc_.reg_read(UC_X86_REG_ESP)

        def u32(off):
            return struct.unpack('<I', uc_.mem_read(esp + off, 4))[0]
        if address == ADDR['c60']:
            log.setdefault('ids_at_send', []).append(
                struct.unpack('<I', uc_.mem_read(IDS, 4))[0])
            netobj, target, buf, ln = u32(4), u32(8), u32(12), u32(16)
            body = bytes(uc_.mem_read(buf, ln)) if (ln and ln <= 256 and buf) else b''
            log['c60'].append({'netobj': netobj, 'target': target, 'len': ln, 'body': body})
        elif address == ADDR['c80']:
            log['c80'] += 1
        elif address == ADDR['wfa']:
            buf, ln = u32(8), u32(12)
            log['wfa'].append(bytes(uc_.mem_read(buf, ln)) if 0 < ln <= 64 else b'')
        return True

    uc.hook_add(UC_HOOK_CODE, on_code, begin=STUBS, end=STUBS + 0x10000)
    try:
        uc.emu_start(CODE, 0, timeout=0, count=max_insns)
    except UcError as error:
        log['error'] = str(error)
    log['blob'] = bytes(uc.mem_read(BLOB_M, inj.UPLINK_BLOB_SIZE))
    log['ids_after'] = struct.unpack('<I', uc.mem_read(IDS, 4))[0]
    return log


class TestUplinkAgent(unittest.TestCase):
    def test_build_present(self):
        self.assertTrue(AGENT.exists(), 'run p51_shadow_agent_build.py first')

    def test_one_shot_exact_payload(self):
        log = run_uplink(AGENT, CREATE_TEMPLATE)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 1, 'exactly one reliable submit')
        call = log['c60'][0]
        self.assertEqual(call['netobj'], NETOBJ)
        self.assertEqual(call['target'], TARGET)
        self.assertEqual(call['len'], len(CREATE_TEMPLATE))
        self.assertEqual(call['body'], CREATE_TEMPLATE, 'bytes on the wire must equal the payload')
        self.assertEqual(log['c80'], 1)
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', 0x37474853, 1, OWN, TARGET, TICK, len(CREATE_TEMPLATE)))
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1)

    def test_no_trigger_no_send(self):
        log = run_uplink(AGENT, CREATE_TEMPLATE, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])

    def test_host_is_self_no_send(self):
        log = run_uplink(AGENT, CREATE_TEMPLATE, host_is_own=True)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])

    def test_zero_own_no_send(self):
        log = run_uplink(AGENT, CREATE_TEMPLATE, own=0)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])

    def test_template_decodes_as_create(self):
        sys.path.insert(0, str(ROOT.parent / 'SGI-Hub-CrossOver-M4-0.2/bridge'))
        import native_command_evidence as N
        row = N.decode(CREATE_TEMPLATE)
        self.assertEqual(row['native_class'], 'CSanInetUnitNetCmdCreate')
        self.assertEqual(row['actor_force_id'], 0)
        self.assertEqual(row['soldiers_raw'], 54321)
        self.assertEqual(row['rice_raw'], 54321)
        self.assertEqual(row['action'], '出征')


SPOOF = BUILD / 'agent_spoof.bin'


class TestSpoofAgent(unittest.TestCase):
    """agent_spoof: swaps the local id for one send, then restores it at once."""

    def test_build_present(self):
        self.assertTrue(SPOOF.exists(), 'run p51_shadow_agent_build.py first')

    def test_identity_swapped_only_during_send(self):
        spoof = 0x11223344
        log = run_uplink(SPOOF, CREATE_TEMPLATE, spoof_id=spoof)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 1, 'exactly one send')
        call = log['c60'][0]
        self.assertEqual(call['target'], 0xFFFFFFFF)
        self.assertEqual(call['body'], CREATE_TEMPLATE)
        self.assertEqual(log['ids_at_send'], [spoof], 'frame carried the spoofed id')
        self.assertEqual(log['ids_after'], OWN, 'own id restored after the send')
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', 0x39474853, 1, OWN, spoof, TICK,
                                                    len(CREATE_TEMPLATE)))

    def test_no_trigger_identity_untouched(self):
        log = run_uplink(SPOOF, CREATE_TEMPLATE, spoof_id=0xABCDEF, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])
        self.assertEqual(log['ids_after'], OWN)


class TestBroadcastAgent(unittest.TestCase):
    """agent_bcast calls 0x100023a0(netobj, -1, buf, len) = SendData (all members).

    This is the P57-B2 route: reach the other clients directly instead of asking
    the host to relay, so no sync-list membership is required.
    """

    def test_build_present(self):
        self.assertTrue(BCAST.exists(), 'run p51_shadow_agent_build.py first')

    def test_one_shot_broadcast(self):
        log = run_uplink(BCAST, CREATE_TEMPLATE)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 1, 'exactly one broadcast')
        call = log['c60'][0]
        self.assertEqual(call['netobj'], NETOBJ)
        self.assertEqual(call['target'], 0xFFFFFFFF, 'target must be broadcast (-1)')
        self.assertEqual(call['len'], len(CREATE_TEMPLATE))
        self.assertEqual(call['body'], CREATE_TEMPLATE)
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', 0x38474853, 1, OWN, 0xFFFFFFFF, TICK,
                                                    len(CREATE_TEMPLATE)))
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1)

    def test_no_trigger_no_send(self):
        log = run_uplink(BCAST, CREATE_TEMPLATE, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])


if __name__ == '__main__':
    unittest.main()
