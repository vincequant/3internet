"""Offline tests for p38_wire against live-captured golden frames.

Golden vectors: p33 run-123126 host receive slot (research/protocol-archive/
evidence/p33-dll-sync-20261015/run-123126/host_watch.jsonl) and the P37 chat
frame (p37-chat-20261015/wire-frames.txt). No network, no native calls.
"""
import struct
import unittest

import p38_wire as w
from p33_wire import inner63 as ctrl_inner63, decode_control

# --- golden vectors (hex as captured; complete unless marked prefix) ---
G_JOIN = '01000000010000000053475a574c42'                      # 22B prefix, 84B total
G_EXIT = '060000000800000000b7e7d2b9'                          # 13B prefix
G_HB = '09000000000b000000'                                    # 9B complete
G_ACK = '580000000300000007'                                   # 9B complete
G_D1 = '630000000700000000000000040ad1895e0a8da84100000001'    # 25B complete
G_D2 = '630000000600000000000000080ad1895e0a8da8410000000200000000'  # 29B complete
G_D7_PREFIX = ('630000000400000000000000300ad1895effffffff'
               '000000070000000000000024ffff0100110043')      # 39B prefix of 69B
G_TEXT_P37 = ('00000020060a9028aa460000000000000000000000060a9028aa'
              'ffffffff66792d643100')                           # 36B complete


def h(s):
    return bytes.fromhex(s)


class TestGolden(unittest.TestCase):
    def test_join_prefix(self):
        d = w.parse_inner(h(G_JOIN))
        self.assertEqual(d['cmd'], 1)
        self.assertEqual(d['seq'], 1)
        self.assertEqual(d['stamp_hex'], '00000000')
        self.assertEqual(d['rest'][:6], b'SGZWLB')

    def test_exit_prefix(self):
        d = w.parse_inner(h(G_EXIT))
        self.assertEqual(d['cmd'], 6)
        self.assertEqual(d['seq'], 8)

    def test_heartbeat(self):
        d = w.inspect(h(G_HB))
        self.assertEqual(d['cmd'], 9)
        self.assertEqual(d['seq'], 0)  # header only; +5..8 unassigned on wire

    def test_ack(self):
        d = w.inspect(h(G_ACK))
        self.assertEqual(d['cmd'], 0x58)
        self.assertEqual(d['ack_seq'], 3)

    def test_d1(self):
        d = w.inspect(h(G_D1))
        self.assertEqual((d['cmd'], d['seq'], d['body_len'], d['control']),
                         (0x63, 7, 4, 1))
        self.assertEqual(d['sender'], 0x0AD1895E)
        self.assertEqual(d['target'], 0x0A8DA841)
        self.assertEqual(d['body_hex'], '00000001')

    def test_d2(self):
        d = w.inspect(h(G_D2))
        self.assertEqual((d['seq'], d['body_len'], d['control']), (6, 8, 2))
        self.assertEqual(d['body_hex'], '0000000200000000')

    def test_d7_prefix(self):
        d = w.inspect(h(G_D7_PREFIX))
        self.assertEqual((d['cmd'], d['seq'], d['body_len']), (0x63, 4, 0x30))
        self.assertEqual(d['target'], 0xFFFFFFFF)
        self.assertEqual((d['control'], d['d7_target'], d['d7_len']), (7, 0, 0x24))

    def test_text_frame_p37_golden(self):
        built = w.outer(w.frame_text(0x0A9028AA, 0xFFFFFFFF, b'fy-d1'), 0x0A9028AA)
        self.assertEqual(built, h(G_TEXT_P37))
        d = w.inspect(w.parse_outer(built)['inner'])
        self.assertEqual((d['sender'], d['target'], d['text']),
                         (0x0A9028AA, 0xFFFFFFFF, b'fy-d1'))


class TestRoundTrip(unittest.TestCase):
    def test_outer(self):
        f = w.probe_frame(0x54, 0x0AD1895E)
        o = w.outer(f, 0x0A8DA841)
        p = w.parse_outer(o)
        self.assertEqual(p['label'], 0x0A8DA841)
        self.assertEqual(p['inner'], f)

    def test_record(self):
        r = w.record(7, 12, b'FENGYE', 0x0AD1895E)
        self.assertEqual(len(r), w.RECORD_LEN)
        self.assertEqual(r[0], 7)
        self.assertEqual(struct.unpack_from('>I', r, 1)[0], 12)
        self.assertEqual(r[9:15], b'FENGYE')
        self.assertEqual(struct.unpack_from('>I', r, 0x28)[0], 0x0AD1895E)

    def test_exit_frame_shape(self):
        r = w.exit_frame(3, b'FENGYE')
        self.assertEqual(r[0], 6)
        self.assertEqual(len(r), w.RECORD_LEN)
        self.assertEqual(w.inspect(r)['name'], 'FENGYE')

    def test_d1_via_control(self):
        body = ctrl_inner63(b'\x00\x00\x00\x01', 9, 0x0AD1895E, 0x0A8DA841,
                            b'\x00\x00\x00\x00')
        self.assertEqual(w.wrap_data(b'\x00\x00\x00\x01', 9, 0x0AD1895E,
                                     0x0A8DA841), body)
        f = w.inspect(body)
        self.assertEqual(f['control'], 1)

    def test_d7_roundtrip(self):
        obj = b'\xff\xff\x01\x00\x02\x00AB'
        body = w.d7(0, obj)
        self.assertEqual(body[:4], b'\x00\x00\x00\x07')
        f = w.inspect(w.wrap_data(body, 1, 0x11, 0x22))
        self.assertEqual((f['control'], f['d7_target'], f['d7_len']), (7, 0, len(obj)))

    def test_d4_roundtrip(self):
        f = w.inspect(w.wrap_data(w.d4(b'\x00\x00\x00\x15' * 2), 2, 0x11, 0x22))
        self.assertEqual(f['control'], 4)
        self.assertEqual(f['d4_len'], 8)


class TestBounds(unittest.TestCase):
    def test_d7_cap(self):
        with self.assertRaises(ValueError):
            w.d7(0, b'x' * (w.APP_DATA_CAP + 1))

    def test_text_cap(self):
        with self.assertRaises(ValueError):
            w.frame_text(1, 2, b'x' * 128)

    def test_record_code(self):
        with self.assertRaises(ValueError):
            w.record(3, 1, b'', 1)

    def test_record_name(self):
        with self.assertRaises(ValueError):
            w.record(7, 1, b'x' * 40, 1)

    def test_probe_cmd(self):
        with self.assertRaises(ValueError):
            w.probe_frame(0x53, 1)

    def test_outer_parse_bad(self):
        with self.assertRaises(ValueError):
            w.parse_outer(b'\x00' * 16)


if __name__ == '__main__':
    unittest.main()
