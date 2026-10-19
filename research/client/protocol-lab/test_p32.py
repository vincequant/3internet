import json
from pathlib import Path
import struct
import sys
import unittest

from p32_protocol import cmd1, cmd2, FakeExit
from p32_audit import audit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'protocol-archive'))
from sim.m6_wire import ArchiveReader
from sim.m7_wire import encode_registration, decode_registration


class WireTests(unittest.TestCase):
    def test_registration_matches_independent_codec(self):
        for machine in (b'VKQUANT-COM', b'HOST', b'X'*254):
            blob = cmd2(machine)
            self.assertEqual(blob, encode_registration(b=2, text=machine))
            decoded = decode_registration(blob)
            self.assertEqual(decoded['text']['raw'], machine)
            self.assertEqual(decoded['b'], 2)

    def test_exit_matches_archived_native_template(self):
        reference = Path(__file__).resolve().parents[2]/'protocol-archive/disasm/m6-cmd1.blob'
        self.assertEqual(cmd1(2, 0x11223344), reference.read_bytes())
        for index in range(8):
            blob = cmd1(index, 0xffffffff-index)
            reader = ArchiveReader(blob)
            obj = reader.object()
            self.assertEqual(obj['cmd'], 1)
            self.assertEqual(obj['a'], index)
            self.assertEqual(obj['b'], 0xffffffff-index)

    def test_bounds(self):
        for machine in (b'', b'X'*255, b'A\0B', 'HOST'):
            with self.assertRaises(ValueError):
                cmd2(machine)
        for i, own in ((-1, 1), (8, 1), (1, 0), (1, 1<<32)):
            with self.assertRaises(ValueError):
                cmd1(i, own)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.g = FakeExit(123, 456, '风夜')
        self.receipt = {'own_id': 123, 'host_id': 456, 'collector_log': 'run/log',
                        'user_report': '已点开局', 'reported_wall': 100}
        self.snap = {'snapshot': {'rows': [{'id': 123, 'name_e': {'gbk_display': '风夜'},
                                          'state42': 0, 'index': 4}]}}
        self.start = {'sender': 456, 'object': {'cmd': 10, 'derived_tail_length': 0}, 'mono': 10}

    def arm(self):
        self.g.snapshot(self.snap)
        self.g.ready_seq = 3
        self.g.observe(self.start)

    def reserve(self, **kwargs):
        args = dict(receipt=self.receipt, log_path='run/log', now=13, tx_seq=4, connected=True)
        args.update(kwargs)
        return self.g.reserve(**args)

    def test_requires_all_preconditions_and_no_retry(self):
        self.assertIsNone(self.reserve())
        self.arm()
        for kwargs in ({'connected': False}, {'tx_seq': 3}, {'now': 11}, {'receipt': {}},
                       {'log_path': 'old-run/log'}, {'receipt': dict(self.receipt, own_id=999)},
                       {'receipt': dict(self.receipt, user_report='已建房')}):
            self.assertIsNone(self.reserve(**kwargs))
        self.assertEqual(self.reserve(), cmd1(4, 123))
        self.assertIsNone(self.reserve())  # even if the native call later fails

    def test_foreign_start_cannot_arm(self):
        self.g.snapshot(self.snap)
        self.g.ready_seq = 3
        self.g.observe(dict(self.start, sender=999))
        self.assertIsNone(self.reserve())

    def test_start_before_ready_cannot_arm(self):
        self.g.snapshot(self.snap)
        self.g.observe(self.start)
        self.g.ready_seq = 3
        self.assertIsNone(self.reserve())

    def test_cancel_and_identity_mismatch(self):
        self.arm()
        self.g.observe({'sender': 456, 'object': {'cmd': 11, 'derived_tail_length': 0}})
        self.assertIsNone(self.reserve())
        for rows in ([], self.snap['snapshot']['rows']*2,
                     [dict(self.snap['snapshot']['rows'][0], id=999)],
                     [dict(self.snap['snapshot']['rows'][0], state42=2)]):
            with self.assertRaises(ValueError):
                FakeExit(123, 456, '风夜').snapshot({'snapshot': {'rows': rows}})


class AuditTests(unittest.TestCase):
    def test_empty_is_unknown(self):
        verdict = audit([], [])
        self.assertIsNone(verdict['own_id'])
        self.assertEqual(verdict['post_received_count'], 0)
        self.assertFalse(verdict['observation_60min_elapsed'])

    def test_inner09_is_inner_byte_not_outer_header(self):
        logs = [{'ev': 'open_enter', 'own_id': 123, 'wall': 1},
                {'ev': 'send_enter', 'label': 'cmd1', 'wall': 10}]
        samples = [{'wall': t, 'members': [], 'last_msg_14c': '09'+'00'*39,
                    'last_sender_4150': 123} for t in (15, 20)]
        v = audit(logs, samples)['first_60s']
        self.assertEqual(len(v['sampled_inner09']), 2)
        self.assertEqual(v['inner09_distinct_slot_values'], 1)
        self.assertTrue(v['heartbeat_slot_freshness'].startswith('unknown'))

    def test_reconnect_and_post_packets_preserved(self):
        logs = [{'ev': 'open_enter', 'own_id': 123, 'wall': 1},
                {'ev': 'send_enter', 'label': 'cmd1', 'wall': 10},
                {'ev': 'received_packet', 'wall': 12, 'length': 36, 'object': {'cmd': 25}},
                {'ev': 'sync_command_received', 'wall': 15, 'length': 90, 'object': {'cmd': 16}}]
        samples = [{'wall': 20, 'members': [{'name': '风夜', 'id': '123', 'reconnecting': 1}]},
                   {'wall': 30, 'members': []}]
        verdict = audit(logs, samples)
        self.assertEqual(verdict['post_received_count'], 2)
        self.assertEqual(verdict['first_60s']['missing_sample_walls'], [30])
        self.assertEqual(len(verdict['first_60s']['reconnect_or_error_events']), 1)
        self.assertIn('unknown_between_samples', verdict['first_60s']['continuity'])


if __name__ == '__main__':
    unittest.main()
