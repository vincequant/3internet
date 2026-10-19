import unittest
from login_protocol import Frames, Reader, Transport, encode, login_body, transform, wrap


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


if __name__ == '__main__':
    unittest.main()
