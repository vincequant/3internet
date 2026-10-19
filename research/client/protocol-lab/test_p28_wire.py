import struct
import unittest
import json
from pathlib import Path
from p28_wire import inspect_object, inspect_packet, decode_snapshot


def base(text=b'\0', tail=b'', name=b'CSanInetCmdObject'):
    return b'\xff\xff'+struct.pack('<HH', 1, len(name))+name+struct.pack('<III', 7, 1, 2)+text+tail


class WireTests(unittest.TestCase):
    def test_derived_tail_is_unknown(self):
        r = inspect_object(base(b'\x03abc', b'\x99\x88', b'CSanInetInitGameData'))
        self.assertEqual((r['cmd'], r['a'], r['b']), (7, 1, 2))
        self.assertEqual(r['text_hex'], '616263')
        self.assertEqual(r['derived_tail_length'], 2)
        self.assertNotIn('ready', r)

    def test_all_truncations_are_retained_unknown(self):
        data = base(b'\x03abc')
        for n in range(len(data)):
            self.assertIn('parse_unknown', inspect_object(data[:n]))

    def test_unknown_class_does_not_invent_command(self):
        r = inspect_object(base(name=b'Unrecognized'))
        self.assertIn('parse_unknown', r)
        self.assertNotIn('cmd', r)

    def test_unicode_bytes_preserved(self):
        r = inspect_object(base(b'\xff\xfe\xff\x01\x2d\x4e'))
        self.assertTrue(r['text_wide'])
        self.assertEqual(r['text_hex'], '2d4e')

    def test_host_order_header_inline_payload(self):
        data = base()
        r = inspect_packet(struct.pack('<III', 123, 456, len(data))+data, 4)
        self.assertEqual((r['sender'], r['target'], r['raw_hex']), (123, 456, data.hex()))

    def test_bad_size_and_scalar_refused(self):
        for raw, kind in [(b'\0'*11, 4), (struct.pack('<III', 1, 2, 0x1801), 4),
                          (struct.pack('<III', 1, 2, 0), 1),
                          (struct.pack('<III', 1, 2, 2)+b'a', 3)]:
            with self.assertRaises(ValueError):
                inspect_packet(raw, kind)

    def test_actual_snapshot_against_independent_row_read(self):
        path = Path(__file__).resolve().parents[2]/'protocol-archive/evidence/p28-window-receive-20261015/run-090744/p28_live.jsonl'
        r = next(json.loads(l) for l in path.read_text().splitlines()
                 if json.loads(l)['ev'] == 'received_packet')
        self.assertEqual(r['sha256'], 'e645bb72f49521206ae0c52f1a9cc2a3a571794d580c9c0b690f952dcb1c8c3f')
        data = bytes.fromhex(r['raw_hex'])
        snap = decode_snapshot(data, inspect_object(data)['base_end'])
        self.assertEqual(snap['consumed'], len(data))
        self.assertEqual(len(snap['rows']), 8)
        self.assertEqual([(x['w4'], x['name_e']['gbk_display']) for x in snap['rows'][:2]],
                         [(2, '丁满'), (1, '风夜')])
        self.assertEqual(snap['rows'][0]['text_a']['gbk_display'], 'VKQUANT-COM')
        self.assertTrue(all(x['id'] == 0 for x in snap['rows'][2:]))
        for n in range(39, len(data)):
            with self.assertRaises(ValueError):
                decode_snapshot(data[:n], 39)
        with self.assertRaises(ValueError):
            decode_snapshot(data+b'\0', 39)


if __name__ == '__main__':
    unittest.main()
