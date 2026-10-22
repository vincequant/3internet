import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sgi_room_monitor.login_protocol import (
    Frames, Reader, Transport, encode, login_body, member_directory,
    pack_string, transform, wrap,
)


def _user_record(user_id=9, name='tester', vip='10.0.0.2'):
    return (struct.pack('<I', user_id) + pack_string(name) + pack_string('')
            + struct.pack('<I', 0) + pack_string('') + struct.pack('<6I', 0, 0, 0, 0, 0, 0)
            + pack_string(vip) + struct.pack('<B', 0))


class ProtocolTests(unittest.TestCase):
    def test_transport_stream(self):
        p = encode(0x2001, 1, bytes(range(256)))
        wire = wrap(p)
        decoder = Transport()
        self.assertEqual(decoder.feed(wire[:7]), [])
        self.assertEqual(decoder.feed(wire[7:] + wire), [(101, 1, p)]*2)
        wire = bytearray(wire)
        wire[2] ^= 1
        with self.assertRaises(ValueError):
            Transport().feed(wire)

    def test_obfuscation_vectors(self):
        for plain, wire in [(b'', b''), (b'a', b'a'),
                            (bytes([1, 2]), bytes([5, 3])),
                            (bytes([1, 2, 3]), bytes([7, 5, 4]))]:
            self.assertEqual(transform(plain), wire)
            self.assertEqual(transform(wire, True), plain)

    def test_stream_split_and_combined_packets(self):
        bodies = [bytes(range(256)), b'x', b'', b'abc']
        wire = b''.join(encode(0x2001+i, i+1, b) for i, b in enumerate(bodies))
        parser, output = Frames(), []
        for byte in wire:
            output.extend(parser.feed(bytes([byte])))
        self.assertEqual([r[2] for r in output], bodies)

    def test_corruption_rejected(self):
        for offset in [0, 12, 16, 20]:
            wire = bytearray(encode(0x2001, 1, b'abc'))
            wire[offset] ^= 1
            with self.assertRaises(ValueError):
                Frames().feed(wire)

    def test_auth_shape(self):
        r = Reader(login_body('example', 'password'))
        self.assertEqual(r.string(), 'example')
        self.assertEqual(r.string(), '5F4DCC3B5AA765D61D8327DEB882CF99')
        self.assertEqual(r.number('B'), 0)
        self.assertEqual(r.number(), 393218)
        self.assertEqual(r.number(), 6)
        self.assertEqual(r.number(), 3)
        self.assertEqual(r.number('B'), 0)
        self.assertEqual(r.number(), 0xffffffff)
        self.assertEqual(r.pos, len(r.body))

    def test_member_directory_vector(self):
        body = (struct.pack('<II', 88, 2)
                + _user_record(9, 'alice', '10.0.0.2')
                + _user_record(10, 'bob', '10.0.0.3')
                + struct.pack('<B', 0))
        listing = member_directory(body)
        self.assertEqual(listing['room_id'], 88)
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['flag'], 0)
        self.assertEqual(listing['users'][0]['id'], 9)
        self.assertEqual(listing['users'][0]['name'], 'alice')
        self.assertEqual(listing['users'][1]['name'], 'bob')
        self.assertEqual(listing['users'][0]['s2c'], '10.0.0.2')

    def test_member_directory_rejects_trailing_and_huge_count(self):
        body = struct.pack('<II', 88, 1) + _user_record() + struct.pack('<B', 0) + b'\x00'
        with self.assertRaises(ValueError):
            member_directory(body)
        huge = struct.pack('<II', 88, 201)
        with self.assertRaises(ValueError):
            member_directory(huge)


if __name__ == '__main__':
    unittest.main()
