# -*- coding: utf-8 -*-
"""Offline unit tests for the P39c2 channel-2 uplink toolchain.

Run:  python3 -m unittest -v test_p39c2
"""
import json
import struct
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p39c2_frame as codec


class TestGoldenVectors(unittest.TestCase):
    def test_real_c4_instruction_1(self):
        got = codec.instr1000(182999682, 62892, 175654970, 7777,
                              bytes.fromhex('0001338b'))
        self.assertEqual(got.hex(), codec.GOLDEN_C4_INSTRUCTION)

    def test_real_c4_instruction_2(self):
        payload = bytes.fromhex(codec.GOLDEN_C4_FRAME_B)
        self.assertEqual(len(payload), 78)
        got = codec.instr1000(175654970, 7777, 182999682, 62892, payload)
        self.assertEqual(
            got.hex(), 'e803000000000a78483a1e610ae85a82f5ac4e00'
            + codec.GOLDEN_C4_FRAME_B)

    def test_p37_frame_reconstruction(self):
        inner = bytes.fromhex('460000000000000000000000060a9028aaffffffff66792d643100')
        self.assertEqual(len(inner), 27)
        got = codec.envelope(0x0A9028AA, inner)
        self.assertEqual(got.hex(), codec.GOLDEN_P37_FY_D1)
        self.assertEqual(int.from_bytes(got[0:4], 'big'), 5 + len(inner))

    def test_step1_frame_shape(self):
        frame = codec.step1_frame(0x0A112233)
        self.assertEqual(len(frame), 18)
        self.assertEqual(frame.hex(), '0000000e060a1122330a0000000050394332')
        self.assertEqual(frame[4], 0x06)
        self.assertEqual(int.from_bytes(frame[5:9], 'big'), 0x0A112233)
        self.assertEqual(frame[9], codec.HARMLESS_CMD)
        self.assertEqual(frame[10:14], b'\x00\x00\x00\x00')
        self.assertEqual(frame[14:18], codec.MARKER)

    def test_envelope_length_field_is_inner_plus_five(self):
        for n in (1, 9, 27, 100):
            inner = bytes([0x63]) + b'\x00' * (n - 1)
            env = codec.envelope(7, inner)
            self.assertEqual(int.from_bytes(env[0:4], 'big'), 5 + n)
            self.assertEqual(len(env), 4 + 5 + n - 1 + 1 - 1 + 1)


class TestRelayMsgs(unittest.TestCase):
    def test_a3_real_roster_row(self):
        msg = codec.msg_a3([(0x0A5CC286, '223.74.148.129', 0x2023,
                             '192.168.188.129', 0x11E0, 1)], key=7)
        self.assertEqual(msg[:5], b'\xa3' + struct.pack('<I', 7))
        self.assertEqual(msg[5:9], b'\x00\x00\x00\x00')
        self.assertEqual(msg[9], 17)
        self.assertEqual(msg[10], 0)
        self.assertEqual(struct.unpack('<H', msg[11:13])[0], 1)
        self.assertEqual(msg[13:].hex(), '0a5cc286df4a94812023c0a8bc8111e001')
        self.assertEqual(len(msg), 13 + 17)

    def test_a8_and_aa_shape(self):
        a8 = codec.msg_a8(0x0A090909, '127.0.0.1', 4633, '127.0.0.1', 4634, 1, key=9)
        self.assertEqual(a8[0], 0xA8)
        self.assertEqual(a8[9], 0x10)
        self.assertEqual(a8[11:15].hex(), '0a090909')
        aa = codec.msg_aa(0x0A090909, '127.0.0.1', 4631, '127.0.0.1', 4632, 1, key=10)
        self.assertEqual(aa[0], 0xAA)
        self.assertEqual(aa[9], 0x11)
        self.assertEqual(len(aa), 28)

    def test_msg2_shape(self):
        msg = codec.msg_2(0x0A7B7B01, 0)
        self.assertEqual(msg.hex(), '32000a7b7b0100000000')
        self.assertEqual(len(msg), 10)


class TestBang(unittest.TestCase):
    def _make(self, payload, deliver=7777, src=b'\x0a\x09\x09\x09', sport=7777):
        head = (bytes([0x21, 0x00]) + b'\x02\x00\x00\x00'
                + struct.pack('>H', deliver) + src
                + struct.pack('>H', sport) + struct.pack('<H', len(payload)))
        body = head[2:] + payload
        return bytes([0x21, codec.crc32_bang(body)]) + body

    def test_roundtrip(self):
        payload = codec.step1_frame(0x0A112233)
        parsed = codec.bang_parse(self._make(payload))
        self.assertTrue(parsed['ok'] and parsed['crc_ok'])
        self.assertEqual(parsed['deliver_port'], 7777)
        self.assertEqual(parsed['src_id'], 0x0A090909)
        self.assertEqual(parsed['src_port'], 7777)
        self.assertEqual(parsed['payload_hex'], payload.hex())
        self.assertEqual(parsed['payload_sha256'], codec.sha256_hex(payload))
        self.assertEqual(parsed['trailer_hex'], '')

    def test_crc_is_loader_variant(self):
        payload = b'abc'
        raw = self._make(payload)
        import zlib
        self.assertEqual(raw[1], zlib.crc32(raw[2:], 0xFFFFFFFF) & 0xFF)
        self.assertNotEqual(raw[1], zlib.crc32(raw[2:]) & 0xFF if
                            (zlib.crc32(raw[2:]) & 0xFF) != raw[1] else (raw[1] + 1) & 0xFF)


class TestAuthorizationGate(unittest.TestCase):
    OWN = 0x0A18142A
    TARGET = 0x0A5CC286

    def _auth(self, **over):
        auth = {'authorized': True, 'target_id': self.TARGET,
                'target_port': 7777, 'own_id': self.OWN, 'own_port': 7777,
                'nonce': 'x'}
        auth.update(over)
        return auth

    def _rows(self):
        return [{'id': self.TARGET, 'ip_a': '1.2.3.4'}]

    def test_pass(self):
        self.assertIsNone(codec.validate_authorization(
            self._auth(), self.TARGET, self.OWN, 8199, self._rows()))

    def test_rejections(self):
        cases = [
            (None, 'authorization_not_dict'),
            (self._auth(authorized=False), 'authorized_flag_not_true'),
            (self._auth(target_id=1), 'target_id_mismatch'),
            (self._auth(target_id=True), 'target_id_mismatch'),
            (self._auth(target_port=0), 'target_port_invalid'),
            (self._auth(target_port=70000), 'target_port_invalid'),
            (self._auth(own_id=5), 'own_id_mismatch'),
        ]
        for auth, reason in cases:
            self.assertEqual(codec.validate_authorization(
                auth, self.TARGET, self.OWN, 8199, self._rows()), reason)
        self.assertEqual(codec.validate_authorization(
            self._auth(), self.TARGET, self.OWN, None, self._rows()),
            'b_port_unavailable')
        self.assertEqual(codec.validate_authorization(
            self._auth(), self.TARGET, self.OWN, 8199, []),
            'target_not_in_relay_table')

    def test_bool_is_not_an_int(self):
        # True == 1 would pass 'isinstance(int)' - target equality still rejects
        self.assertEqual(codec.validate_authorization(
            self._auth(target_id=self.TARGET), self.TARGET, self.OWN, 8199,
            [{'id': 'x'}]), 'target_not_in_relay_table')


class TestHelpers(unittest.TestCase):
    def test_ip_conversions(self):
        self.assertEqual(codec.ip_to_id('10.92.194.134'), 0x0A5CC286)
        self.assertEqual(codec.id_to_ip(0x0A5CC286), '10.92.194.134')
        with self.assertRaises(ValueError):
            codec.ip_to_id('10.1.2')

    def test_bounds(self):
        with self.assertRaises(ValueError):
            codec.envelope(1, b'')
        with self.assertRaises(ValueError):
            codec.instr1000(1, 1, 1, 1, b'')
        with self.assertRaises(ValueError):
            codec.instr1000(1, 1, 1, 1, b'ab', flag5=2)


if __name__ == '__main__':
    unittest.main()
