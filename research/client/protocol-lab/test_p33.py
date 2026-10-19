import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from p33_wire import (start_ready, end_ready, command_batch, timing_batch,
                      own_sync_withdrawal, decode_control, inner63, inspect_inner, elapsed_native)
from p33_sync import RoundGate, participate, sync_authorized
from p33_audit import sync_audit
from p28_wire import inspect_object
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'protocol-archive'))
from sim.m6_wire import inner63 as independent_inner63


class CodecTests(unittest.TestCase):
    def test_exact_native_constructor_vectors(self):
        self.assertEqual(start_ready(), bytes.fromhex('00000001'))
        self.assertEqual(end_ready(0x01020304), bytes.fromhex('0000000201020304'))
        self.assertEqual(command_batch([]), bytes.fromhex('0000000500000000'))
        self.assertEqual(timing_batch([(0x11223344, 9, 2)]),
                         bytes.fromhex('0000000300000001112233440000000900000002'))
        self.assertEqual(own_sync_withdrawal(0x11223344), bytes.fromhex('0000000811223344'))

    def test_roundtrip_and_independent_envelope(self):
        vectors = [start_ready(), end_ready(321), command_batch([]),
                   command_batch([(0x11223344, b'abcd'), (0x55667788, b'X'*2048)]),
                   timing_batch([(0x11223344, 30, 3)]), own_sync_withdrawal(0x11223344)]
        for blob in vectors:
            frame = inner63(blob, 12, 0x11223344, 0x55667788, b'ABCD')
            self.assertEqual(frame, independent_inner63(blob, seq=12, sender=0x11223344,
                                                        target=0x55667788, stamp=b'ABCD'))
            self.assertEqual(inspect_inner(frame)['control'], decode_control(blob))
            self.assertIn('parse_unknown', inspect_object(blob))  # NOT MFC/game cmd1 or2

    def test_all_truncations_and_tails_rejected(self):
        for blob in (start_ready(), end_ready(20), command_batch([(1, b'abc')]),
                     timing_batch([(1, 2, 3)]), own_sync_withdrawal(1)):
            for i in range(len(blob)):
                with self.assertRaises(ValueError):
                    decode_control(blob[:i])
            with self.assertRaises(ValueError):
                decode_control(blob+b'X')

    def test_bounds_and_no_seq0(self):
        for value in (-1, 1<<32, True, '0'):
            with self.assertRaises(ValueError):
                end_ready(value)
        for seq in (0, -1, 1<<32):
            with self.assertRaises(ValueError):
                inner63(start_ready(), seq, 1, 2, b'ABCD')
        with self.assertRaises(ValueError):
            command_batch([(1, b'X'*2049)])
        with self.assertRaises(ValueError):
            command_batch([(1, b'')]*121)
        with self.assertRaises(ValueError):
            timing_batch([(1, 2, 3)]*9)

    def test_elapsed_matches_native_wrap_rule(self):
        self.assertEqual(elapsed_native(100, 105), 5)
        self.assertEqual(elapsed_native(100, 100), 0)
        self.assertEqual(elapsed_native(0xfffffffe, 2), 3)


class Backend:
    def __init__(self, stop, cycles=2, fail_start=False, fail_end=False):
        self.stop, self.cycles = stop, cycles
        self.fail_start, self.fail_end = fail_start, fail_end
        self.current_state = 1
        self.calls = []
        self.clock = 100

    def connected(self):
        return True

    def state(self):
        return self.current_state

    def tick(self):
        self.clock += 3
        return self.clock

    def start(self):
        self.calls.append(('start', None))
        self.current_state = 3
        return 11 if self.fail_start else 0

    def batch(self):
        return [{'sender': 1, 'raw_hex': '616263', 'length': 3}]

    def end(self, ms):
        self.calls.append(('end', ms))
        self.current_state = 1
        if sum(name == 'end' for name, _ in self.calls) >= self.cycles:
            self.stop.set()
        return 11 if self.fail_end else 0


class StateTests(unittest.TestCase):
    def test_once_each_phase_and_preserved_commands(self):
        stop = threading.Event()
        b, logs = Backend(stop, cycles=3), []
        participate(b, stop, logs.append)
        self.assertEqual(b.calls, [('start', None), ('end', 3)]*3)
        self.assertEqual(len([r for r in logs if r['ev'] == 'sync_batch_accepted']), 3)
        self.assertEqual([r['records'][0]['raw_hex'] for r in logs if r['ev'] == 'sync_batch_accepted'], ['616263']*3)
        self.assertFalse(any(r['ev'] == 'sync_failed' for r in logs))
        self.assertEqual(len([r for r in logs if r['ev'] == 'sync_round_complete']), 3)

    def test_failures_never_retry(self):
        for kwargs, expected in (({'fail_start': True}, [('start', None)]),
                                 ({'fail_end': True}, [('start', None), ('end', 3)])):
            stop = threading.Event()
            b, logs = Backend(stop, **kwargs), []
            participate(b, stop, logs.append)
            self.assertEqual(b.calls, expected)
            self.assertEqual(len([r for r in logs if r['ev'] == 'sync_failed']), 1)

    def test_wrong_initial_state_no_call(self):
        stop = threading.Event()
        b, logs = Backend(stop), []
        b.current_state = 2
        participate(b, stop, logs.append)
        self.assertEqual(b.calls, [])
        self.assertEqual(logs[0]['ev'], 'sync_failed')

    def test_gate_reserves_before_native_and_refuses_duplicates(self):
        gate = RoundGate()
        self.assertEqual(gate.claim_start(), 1)
        with self.assertRaises(ValueError):
            gate.claim_start()
        with self.assertRaises(ValueError):
            gate.claim_end()
        gate.batch_received()
        gate.claim_end()
        with self.assertRaises(ValueError):
            gate.claim_end()
        gate.finished()
        self.assertEqual(gate.claim_start(), 2)

    def test_live_approval_and_P_state_bound_to_run(self):
        report = {'contract': 'P33', 'enable_minimal_sync': True, 'user_report': '已点开局',
                  'own_id': 1, 'host_id': 2, 'collector_log': 'new/log'}
        effect = {'own_id': 1, 'host_id': 2, 'P_state': 2, 'source': 'p32_app_rows_read', 'observed_wall': 100}
        self.assertTrue(sync_authorized(report, effect, 1, 2, 'new/log', 101))
        for bad in (dict(report, contract='P32'), dict(report, enable_minimal_sync=False),
                    dict(report, own_id=3), dict(report, collector_log='old/log'), {}):
            self.assertFalse(sync_authorized(bad, effect, 1, 2, 'new/log', 101))
        for bad in (dict(effect, P_state=0), dict(effect, observed_wall=80),
                    dict(effect, source='self_cache'), dict(effect, own_id=9), {}):
            self.assertFalse(sync_authorized(report, bad, 1, 2, 'new/log', 101))


class PreparationTests(unittest.TestCase):
    def test_defaults_make_no_experiment(self):
        folder = Path(__file__).resolve().parent
        for name in ('p33_sync_probe.py', 'p33_sync_orchestrate.py'):
            r = subprocess.run([sys.executable, str(folder/name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['state'], 'prepared_only')

    def test_launch_without_consent_fails_before_process_discovery(self):
        import p33_sync_orchestrate as module
        with mock.patch.object(sys, 'argv', ['p33_sync_orchestrate.py', '--launch']), \
             mock.patch.object(module.subprocess, 'check_output', side_effect=AssertionError('must not inspect/launch')):
            with self.assertRaisesRegex(ValueError, 'Phase3_user_approval_required'):
                module.main()

    def test_incremental_tail_handles_partial_multibyte_line(self):
        from p33_sync_orchestrate import Tail
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'live'
            tail = Tail(p)
            self.assertEqual(tail.read(), [])
            blob = json.dumps({'text': '风夜'}, ensure_ascii=False).encode('utf-8')+b'\n'
            p.write_bytes(blob[:-3])
            self.assertEqual(tail.read(), [])
            with p.open('ab') as f:
                f.write(blob[-3:])
            self.assertEqual(tail.read(), [{'text': '风夜'}])
            self.assertEqual(tail.read(), [])

    def test_ready_sampling_does_not_invent_flip_or_complete_coverage(self):
        logs = [{'ev': 'open_enter', 'own_id': 1}, {'ev': 'sync_batch_accepted', 'round': 1}]
        result = sync_audit(logs, [])['native_sync']
        self.assertIsNone(result['ready1_first_sample'])
        self.assertEqual(result['StartSync_accepted_batches'], 1)
        self.assertEqual(result['received_control5_slot_samples'], 0)

    def test_user_UI_report_must_match_current_identity_and_log(self):
        logs = [{'ev': 'open_enter', 'own_id': 1}]
        report = {'source': 'user_report', 'own_id': 1, 'host_id': 2,
                  'collector_log': 'new/log', 'can_enter_commands': True, 'raw_text': '能进入指令阶段'}
        self.assertEqual(sync_audit(logs, [], report, 2, 'new/log')['native_sync']['user_command_phase_report'], report)
        for invalid in (dict(report, own_id=3), dict(report, source='native_inference'),
                        dict(report, collector_log='old/log'), dict(report, can_enter_commands='yes')):
            self.assertIsNone(sync_audit(logs, [], invalid, 2, 'new/log')['native_sync']['user_command_phase_report'])

    def test_python38_syntax(self):
        for p in Path(__file__).resolve().parent.glob('p33*.py'):
            ast.parse(p.read_text(), filename=str(p), feature_version=(3, 8))


if __name__ == '__main__':
    unittest.main()
