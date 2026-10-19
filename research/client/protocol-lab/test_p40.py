import unittest

from p40_d5_inject import (D5Gate, GOLDEN_RECORDS, d5_authorized, d5_body,
                           domestic_record, modify_golden, parse_golden,
                           verify_record)

NOW = 1000.0


class GoldenTests(unittest.TestCase):
    def test_retained_records_rebuild_byte_identical(self):
        expected_fields = [
            {'actor': 17, 'parameter': 0, 'value': 79, 'extra': 1, 'subtype': 0, 'operand': 0},
            {'actor': 17, 'parameter': 1, 'value': 86, 'extra': 1, 'subtype': 0, 'operand': 0},
            {'actor': 17, 'parameter': 0, 'value': 73, 'extra': 1, 'subtype': 0, 'operand': 0},
        ]
        for hexed, fields in zip(GOLDEN_RECORDS, expected_fields):
            raw = bytes.fromhex(hexed)
            self.assertEqual(parse_golden(raw), fields)
            self.assertEqual(domestic_record(**fields), raw)
            self.assertEqual(modify_golden(raw), raw)


class RecordTests(unittest.TestCase):
    def test_roundtrip_and_field_bounds(self):
        raw = domestic_record(actor=5, parameter=2, value=120, extra=1)
        fields = verify_record(raw)
        self.assertEqual(fields['actor'], 5)
        self.assertEqual(fields['parameter'], 2)
        self.assertEqual(fields['value'], 120)
        self.assertEqual(domestic_record(**fields), raw)
        for bad in ({'actor': -1}, {'actor': 32}, {'actor': True}, {'actor': '1'},
                    {'subtype': -1}, {'subtype': 256}, {'parameter': 'x'},
                    {'value': 2**31}, {'extra': None}, {'operand': 2**31}):
            with self.assertRaises(ValueError):
                domestic_record(**dict({'actor': 1}, **bad))
        with self.assertRaises(ValueError):
            verify_record(raw[:-1])
        with self.assertRaises(ValueError):
            verify_record(b'PRIVATE_VALUE')

    def test_modify_golden_stable_and_strict(self):
        raw = bytes.fromhex(GOLDEN_RECORDS[0])
        changed = modify_golden(raw, parameter=1, value=99)
        self.assertEqual(parse_golden(changed)['parameter'], 1)
        self.assertEqual(parse_golden(changed)['value'], 99)
        self.assertEqual(len(changed), 54)
        with self.assertRaises(ValueError):
            modify_golden(raw, token='PRIVATE_VALUE')


class D5BodyTests(unittest.TestCase):
    def test_body_roundtrip_and_gate_once_only(self):
        record = bytes.fromhex(GOLDEN_RECORDS[1])
        body = d5_body(123, record)
        from p33_wire import decode_control
        decoded = decode_control(body)
        self.assertEqual(decoded['control_cmd'], 5)
        self.assertEqual(decoded['records'][0]['sender'], 123)
        self.assertEqual(decoded['records'][0]['raw_hex'], record.hex())
        with self.assertRaises(ValueError):
            d5_body(0, record)
        with self.assertRaises(ValueError):
            d5_body(123, b'short')
        gate = D5Gate()
        self.assertEqual(gate.reserve(123, record), body)
        self.assertEqual(gate.phase, 'reserved')
        with self.assertRaises(ValueError):
            gate.reserve(123, record)
        gate.mark_sent(1)
        self.assertEqual(gate.phase, 'sent')
        with self.assertRaises(ValueError):
            gate.mark_sent(1)

    def test_authorization_receipt_is_fresh_and_bound(self):
        receipt = {'contract': 'P40', 'enable_d5': True, 'test_game_confirmed': True,
                   'own_id': 123, 'host_id': 456, 'observed_wall': NOW - 10,
                   'note': 'PRIVATE_VALUE'}
        self.assertTrue(d5_authorized(receipt, 123, 456, NOW))
        for bad in (None, {}, dict(receipt, contract='P34'), dict(receipt, enable_d5=False),
                    dict(receipt, test_game_confirmed=False), dict(receipt, own_id=9),
                    dict(receipt, host_id=9), dict(receipt, observed_wall=NOW - 601),
                    dict(receipt, observed_wall=NOW + 1)):
            self.assertFalse(d5_authorized(bad, 123, 456, NOW))


if __name__ == '__main__':
    unittest.main()
