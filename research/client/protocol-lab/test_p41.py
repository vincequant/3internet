#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P41 leave-frame builder tests — golden vectors from live captures.

Run: python3 test_p41.py -v
"""
import unittest
import zlib

import p41_leave_frame as p41


class TestLeaveFrame(unittest.TestCase):

    def test_golden_wire_matches_capture(self):
        frame = p41.build_leave_wire(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2)
        self.assertEqual(frame.hex(), p41.GOLDEN_LEAVE_WIRE_HEX)

    def test_all_five_captured_instances(self):
        for name, tag2, payload_hex in p41.CAPTURED_INSTANCES:
            got = p41.build_leave_payload(p41.GOLDEN_SESSION_ID, tag2)
            self.assertEqual(got.hex(), payload_hex, name)

    def test_crc_matches_every_instance(self):
        for name, tag2, payload_hex in p41.CAPTURED_INSTANCES:
            blob = bytes.fromhex(payload_hex)
            crc = zlib.crc32(blob[2:], 0xFFFFFFFF) & 0xFF
            self.assertEqual(blob[1], crc, name)

    def test_golden_lengths(self):
        payload = p41.build_leave_payload(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2)
        frame = p41.build_leave_wire(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2)
        self.assertEqual(len(payload), p41.PAYLOAD_LEN)
        self.assertEqual(len(frame), p41.WIRE_LEN)
        self.assertEqual(frame[15:], payload)

    def test_session_id_appears_twice(self):
        frame = p41.build_leave_wire(0x0AA802D6, p41.GOLDEN_TAG2)
        self.assertEqual(frame[5:9], bytes.fromhex('0aa802d6'))
        self.assertEqual(frame[23:27], bytes.fromhex('0aa802d6'))

    def test_instr1000_shape(self):
        instr = p41.build_leave_instr1000(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2)
        # LE32(1000) 01 01 addr1 port1 addr2 port2 LE16(4) body
        self.assertEqual(instr[:4], (1000).to_bytes(4, 'little'))
        self.assertEqual(instr[4:6], b'\x01\x01')
        self.assertEqual(instr[6:10], p41.GOLDEN_SESSION_ID.to_bytes(4, 'big'))
        self.assertEqual(instr[10:12], p41.GOLDEN_TAG2.to_bytes(2, 'big'))
        self.assertEqual(instr[12:16], b'\xff\xff\xff\xff')
        self.assertEqual(instr[16:18], b'\x1e\x61')
        self.assertEqual(instr[18:20], b'\x04\x00')
        self.assertEqual(instr[20:], p41.BODY4)
        self.assertEqual(len(instr), 24)

    def test_instr1000_unicast_flags(self):
        instr = p41.build_leave_instr1000(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2,
                                          target=0x0A7B7B01, deliver_port=7777,
                                          flag4=0, flag5=0)
        self.assertEqual(instr[4:6], b'\x00\x00')
        self.assertEqual(instr[12:16], b'\x0a\x7b\x7b\x01')

    def test_parse_roundtrip(self):
        frame = p41.build_leave_wire(0x0AA802D6, 0x1234)
        info = p41.parse_leave_wire(frame)
        self.assertEqual(info['session_id'], 0x0AA802D6)
        self.assertEqual(info['target'], 0xffffffff)
        self.assertEqual(info['deliver_port'], 7777)
        self.assertEqual(info['tag2'], '1234')
        self.assertEqual(info['body4'], '0001338b')

    def test_parse_rejects_corruption(self):
        frame = bytearray(p41.build_leave_wire(p41.GOLDEN_SESSION_ID, p41.GOLDEN_TAG2))
        frame[16] ^= 0xFF          # break crc
        with self.assertRaises(ValueError):
            p41.parse_leave_wire(bytes(frame))
        with self.assertRaises(ValueError):
            p41.parse_leave_wire(b'\x00' * 10)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            p41.build_leave_payload(p41.GOLDEN_SESSION_ID, tag2=0x10000)
        with self.assertRaises(ValueError):
            p41.build_leave_payload(-1)
        with self.assertRaises(ValueError):
            p41.build_leave_payload(p41.GOLDEN_SESSION_ID, body=b'\x00')


if __name__ == '__main__':
    unittest.main(verbosity=2)
