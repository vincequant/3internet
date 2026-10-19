import ast
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from p34_wire import (d8_body, self_echo_branch, reliable_send_rc, D8Gate,
                      d8_authorized, host_withdrawn_receipt, worker_stop_reason,
                      SEND_CALL_SHAPE, RVA_GET_HOST_OR_SELF, RVA_RELIABLE_SEND,
                      username_authorized, control_validate)
from p34_sync import participate_d8
from p34_audit import d8_audit
from p34_frames_extract import select as frame_select


NOW = 1000.0


def receipt(own_id=1, host_id=2, wall=NOW-10, rounds=2, **over):
    base = {'contract': 'P34', 'source': 'p34_derived_authorization', 'enable_d8': True,
            'cmd1_acked': True, 'completed_rounds': rounds, 'own_id': own_id,
            'host_id': host_id, 'observed_wall': wall, 'collector_log': 'new/log'}
    base.update(over)
    return base


class WireTests(unittest.TestCase):
    def test_d8_body_matches_p33_codec_vector(self):
        self.assertEqual(d8_body(0x11223344), bytes.fromhex('0000000811223344'))
        self.assertEqual(len(d8_body(1)), 8)

    def test_send_call_shape_is_sha_bound_24f0_pattern(self):
        self.assertEqual(RVA_GET_HOST_OR_SELF, 0x4c80)
        self.assertEqual(RVA_RELIABLE_SEND, 0x4b60)
        self.assertEqual(SEND_CALL_SHAPE, (
            ('0x4c80_get_host_or_self', ('netobj',)),
            ('0x4b60_reliable_submit', ('netobj', 'target_id', 'buf', 'len'))))

    def test_self_echo_branch_static_table(self):
        self.assertEqual(self_echo_branch(1), 'immediate_type2_31d0_accept_exit_wait'
                         '_setevent_84a4_when_departing_own')
        self.assertEqual(self_echo_branch(2), self_echo_branch(1))
        self.assertEqual(self_echo_branch(0), 'queued_84d0_84d4_type2_31d0_at_36e0_round_end')
        for state in (3, 4):
            self.assertEqual(self_echo_branch(state), self_echo_branch(0))
        for state in (5, -1, None, '1'):
            with self.assertRaises(ValueError):
                self_echo_branch(state)

    def test_reliable_send_rc_maps_native_greater_than_zero(self):
        self.assertEqual(reliable_send_rc(1), 0)
        self.assertEqual(reliable_send_rc(0), 11)
        self.assertEqual(reliable_send_rc(-1), 11)
        with self.assertRaises(ValueError):
            reliable_send_rc(None)


class GateTests(unittest.TestCase):
    def test_reservation_requires_full_precondition_set(self):
        gate = D8Gate()
        self.assertIsNone(gate.reserve({}, 1, 2, 'new/log', NOW, True, 2))
        self.assertIsNone(gate.reserve(receipt(), 1, 2, 'new/log', NOW, False, 2))
        self.assertIsNone(gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, 0))
        self.assertIsNone(gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, '2'))
        self.assertEqual(gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, 2),
                         bytes.fromhex('0000000800000001'))
        self.assertEqual(gate.phase, 'reserved')

    def test_once_only_and_identity_binding(self):
        gate = D8Gate()
        self.assertIsNotNone(gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, 1))
        with self.assertRaises(ValueError):
            gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, 1)
        for bad in (dict(receipt(), own_id=3), dict(receipt(), host_id=9),
                    dict(receipt(), collector_log='old/log'), dict(receipt(), contract='P33'),
                    dict(receipt(), source='self_cache'), dict(receipt(), enable_d8=False),
                    dict(receipt(), cmd1_acked=False), dict(receipt(), observed_wall=NOW-601)):
            self.assertIsNone(D8Gate().reserve(bad, 1, 2, 'new/log', NOW, True, 1))
        self.assertIsNone(D8Gate().reserve(receipt(wall=NOW+1), 1, 2, 'new/log', NOW, True, 1))
        self.assertIsNone(D8Gate().reserve(None, 1, 2, 'new/log', NOW, True, 1))

    def test_invalid_receipt_keeps_gate_idle_for_retry(self):
        gate = D8Gate()
        self.assertIsNone(gate.reserve({}, 1, 2, 'new/log', NOW, True, 1))
        self.assertEqual(gate.phase, 'idle')
        self.assertEqual(gate.reserve(receipt(), 1, 2, 'new/log', NOW, True, 1),
                         bytes.fromhex('0000000800000001'))

    def test_host_withdrawn_receipt(self):
        self.assertTrue(host_withdrawn_receipt({'sync_rows': [{'id': 2, 'ready_flag': 1}]}, 1))
        self.assertFalse(host_withdrawn_receipt({'sync_rows': [{'id': 1}]}, 1))
        self.assertFalse(host_withdrawn_receipt({'sync_rows': []}, 1))
        self.assertFalse(host_withdrawn_receipt(None, 1))

    def test_worker_exit_classification(self):
        self.assertEqual(worker_stop_reason(False, False, None, 1), 'stopped_before_d8')
        self.assertEqual(worker_stop_reason(True, True, None, 1), 'self_echo_abort_acknowledged')
        self.assertEqual(worker_stop_reason(True, False,
                       {'sync_rows': [{'id': 2}]}, 1), 'host_withdrawal_confirmed_stop')
        self.assertEqual(worker_stop_reason(True, False, None, 1), 'unknown_worker_exit')
        self.assertEqual(worker_stop_reason(True, False, {'sync_rows': [{'id': 1}]}, 1),
                         'unknown_worker_exit')


class D8Backend:
    """Fake of this probe's own DLL boundary for offline worker tests."""

    def __init__(self, stop):
        self.stop = stop
        self.state_value = 1
        self.clock = 100
        self.calls = []
        self.abort_pending = False
        self.own_id, self.host_id, self.log_path = 1, 2, 'new/log'
        self.d8_state_at_send = None

    def connected(self):
        return True

    def state(self):
        return self.state_value

    def tick(self):
        self.clock += 3
        return self.clock

    def cmd1_acked(self):
        return True

    def tx_seq(self):
        return 40+len(self.calls)

    def start(self):
        self.calls.append('start')
        if self.abort_pending:
            return 11
        self.state_value = 3
        return 0

    def batch(self):
        return []

    def end(self, ms):
        self.calls.append(('end', ms))
        self.state_value = 1
        return 0

    def send_d8(self, blob):
        self.calls.append(('d8', bytes(blob)))
        self.d8_state_at_send = self.state_value
        self.abort_pending = True
        return 1, self.host_id


class WorkerTests(unittest.TestCase):
    def test_d8_sent_once_between_rounds_then_echo_abort_exits(self):
        stop = threading.Event()
        backend, logs = D8Backend(stop), []
        gate = D8Gate()
        seen = {'sent': False}

        def receipt_reader():
            if seen['sent'] or backend.calls:
                seen['sent'] = True
                return receipt()
            return None

        reason = participate_d8(backend, stop, logs.append, gate, receipt_reader,
                                now=lambda: NOW)
        self.assertEqual(reason, 'self_echo_abort_acknowledged')
        d8s = [c for c in backend.calls if isinstance(c, tuple) and c[0] == 'd8']
        self.assertEqual(len(d8s), 1)
        self.assertEqual(d8s[0][1], bytes.fromhex('0000000800000001'))
        self.assertEqual(backend.d8_state_at_send, 1)
        self.assertEqual(len([r for r in logs if r.get('ev') == 'd8_send_enter']), 1)
        self.assertEqual([r for r in logs if r.get('ev') == 'd8_send_return'][0]['mapped_rc'], 0)
        self.assertEqual([r for r in logs if r.get('ev') == 'worker_exit'][0]['reason'],
                         'self_echo_abort_acknowledged')

    def test_no_receipt_no_d8_and_stop_exits_clean(self):
        stop = threading.Event()
        backend, logs = D8Backend(stop), []
        gate = D8Gate()

        def receipt_reader():
            return None

        def stop_after_two_rounds():
            if len([r for r in logs if r.get('ev') == 'sync_round_complete']) >= 2:
                stop.set()
            return None
        reason = participate_d8(backend, stop, logs.append, gate, stop_after_two_rounds,
                                now=lambda: NOW)
        self.assertEqual(reason, 'stopped_at_round_boundary')
        self.assertEqual([c for c in backend.calls if isinstance(c, tuple) and c[0] == 'd8'], [])
        self.assertEqual(gate.phase, 'idle')
        self.assertEqual(len([r for r in logs if r.get('ev') == 'sync_round_complete']), 2)

    def test_failure_before_d8_never_sends(self):
        stop = threading.Event()
        backend, logs = D8Backend(stop), []
        gate = D8Gate()
        original_start = backend.start

        def start():
            if not any(c == 'start' for c in backend.calls):
                backend.state_value = 2
                return 0
            return original_start()
        backend.start = start
        reason = participate_d8(backend, stop, logs.append, gate,
                                lambda: receipt(), now=lambda: NOW)
        self.assertEqual(reason, 'failure')
        self.assertEqual([c for c in backend.calls if isinstance(c, tuple) and c[0] == 'd8'], [])
        failed = [r for r in logs if r.get('ev') == 'sync_failed'][0]
        self.assertFalse(failed['d8_sent'])

    def test_host_withdrawal_fallback_exits_without_echo(self):
        stop = threading.Event()
        backend, logs = D8Backend(stop), []
        gate = D8Gate()
        backend.abort_pending = False  # no echo ever arrives

        def send_d8(blob):
            backend.calls.append(('d8', bytes(blob)))
            backend.d8_state_at_send = backend.state_value
            return 1, backend.host_id
        backend.send_d8 = send_d8

        def receipt_reader():
            if len([r for r in logs if r.get('ev') == 'sync_round_complete']) >= 1:
                return receipt()
            return None

        def fallback_reader():
            if any(isinstance(c, tuple) and c[0] == 'd8' for c in backend.calls) \
                    and len([r for r in logs if r.get('ev') == 'sync_round_complete']) >= 2:
                return {'sync_rows': [{'id': 2, 'ready_flag': 1}], 'observed_wall': NOW-1}
            return None
        reason = participate_d8(backend, stop, logs.append, gate, receipt_reader,
                                fallback_reader, now=lambda: NOW)
        self.assertEqual(reason, 'host_withdrawal_confirmed_stop')
        self.assertTrue(any(r.get('ev') == 'host_withdrawal_observed' for r in logs))


class AuditTests(unittest.TestCase):
    def logs(self):
        return [
            {'ev': 'open_enter', 'own_id': 1, 'mono': 1, 'wall': 1},
            {'ev': 'cmd1_ack_observed', 'mono': 5, 'wall': 5},
            {'ev': 'sync_round_complete', 'round': 1, 'mono': 6, 'wall': 6},
            {'ev': 'd8_send_enter', 'mono': 7, 'wall': 7, 'body_hex': '0000000800000001'},
            {'ev': 'd8_send_return', 'mono': 8, 'wall': 8, 'raw_rc': 1, 'mapped_rc': 0,
             'target': 2, 'native_tx_seq_after': 41},
            {'ev': 'notification', 'type': 2, 'mono': 9, 'wall': 9},
            {'ev': 'accept_exit', 'mono': 9.5, 'wall': 9, 'member_id': 1, 'rc': 0},
            {'ev': 'worker_exit', 'reason': 'self_echo_abort_acknowledged', 'mono': 10,
             'wall': 10, 'd8_sent': True, 'echo_abort_observed': True},
            {'ev': 'received_packet', 'type': 4, 'mono': 11, 'wall': 11},
        ]

    def test_full_chain_counts_and_bindings(self):
        watched = [
            {'wall': 6, 'mono': 6, 'sync_rows': [{'id': 1, 'ready_flag': 1}]},
            {'wall': 20, 'mono': 20, 'sync_rows': [{'id': 2, 'ready_flag': 1}]},
        ]
        ui = {'source': 'user_report', 'own_id': 1, 'host_id': 2, 'collector_log': 'new/log',
              'row_visible': False, 'raw_text': '玩家列表已无风夜'}
        result = d8_audit(self.logs(), watched, ui, 2, 'new/log')['d8']
        self.assertTrue(result['d8_sent_exactly_once'])
        self.assertEqual(result['d8_send_returns'][0]['mapped_rc'], 0)
        self.assertEqual(result['self_echo_accept_exit_events'], [{'member_id': 1, 'rc': 0}])
        self.assertTrue(result['host_withdrawal_observed'])
        self.assertFalse(result['host_still_lists_ghost'])
        self.assertEqual(result['received_packets_after_d8_by_type'], {'type:4': 1})
        self.assertEqual(result['user_ui_row_report'], ui)
        self.assertEqual(result['worker_exits'][0]['reason'], 'self_echo_abort_acknowledged')

    def test_missing_report_and_no_d8_are_unknown_not_invented(self):
        result = d8_audit(self.logs(), [], None, 2, 'new/log')['d8']
        self.assertIsNone(result['user_ui_row_report'])
        self.assertTrue(result['user_report_missing_is_unknown'])
        empty = d8_audit([{'ev': 'open_enter', 'own_id': 1, 'mono': 1, 'wall': 1}], [], None, 2, 'x')['d8']
        self.assertFalse(empty['d8_sent_exactly_once'])
        self.assertIsNone(empty['host_withdrawal_observed'])
        self.assertEqual(empty['broadcast_continuity_after_d8'], 'unknown_or_silent_window')

    def test_ui_report_binding_rejects_identity_mismatch(self):
        ui = {'source': 'user_report', 'own_id': 9, 'host_id': 2, 'collector_log': 'new/log',
              'row_visible': False, 'raw_text': 'x'}
        self.assertIsNone(d8_audit(self.logs(), [], ui, 2, 'new/log')['d8']['user_ui_row_report'])
        ui2 = {'source': 'user_report', 'own_id': 1, 'host_id': 2, 'collector_log': 'new/log',
               'row_visible': 'no', 'raw_text': 'x'}
        self.assertIsNone(d8_audit(self.logs(), [], ui2, 2, 'new/log')['d8']['user_ui_row_report'])


class UsernamePolicyTests(unittest.TestCase):
    def test_default_policy_only_allows_fengye(self):
        self.assertTrue(username_authorized('风夜'))
        self.assertFalse(username_authorized(' '))
        self.assertFalse(username_authorized(''))
        self.assertFalse(username_authorized('指挥家'))

    def test_blank_flag_admits_exactly_single_space(self):
        self.assertTrue(username_authorized(' ', True))
        self.assertFalse(username_authorized('', True))
        self.assertFalse(username_authorized('  ', True))
        self.assertFalse(username_authorized('风夜 ', True))
        self.assertTrue(username_authorized('风夜', True))


class ControlTests(unittest.TestCase):
    def test_chat_validated_gbk_and_bounded(self):
        done = set()
        action, reason = control_validate({'id': 'a1', 'op': 'chat', 'text': '你好'}, done)
        self.assertIsNone(reason)
        self.assertEqual(action['op'], 'chat')
        self.assertEqual(action['blob'], '你好'.encode('gbk'))
        for bad in ({'id': 'b1', 'op': 'chat', 'text': ''},
                    {'id': 'b2', 'op': 'chat', 'text': 'x' * 121},
                    {'id': 'b3', 'op': 'chat', 'text': '𝕏'},
                    {'id': 'b4', 'op': 'chat'},
                    {'id': 'b5', 'op': 'explode'},
                    {'op': 'chat', 'text': 'x'},
                    {'id': '', 'op': 'stop'},
                    {'id': 'x' * 65, 'op': 'stop'},
                    'not-a-dict'):
            self.assertIsNone(control_validate(bad, set())[0], bad)

    def test_d5_record_validated_and_bounded(self):
        action, reason = control_validate(
            {'id': 'd1', 'op': 'd5', 'record': {'actor': 5, 'parameter': 1, 'value': 99}}, set())
        self.assertIsNone(reason)
        self.assertEqual(action['record'], {'actor': 5, 'subtype': 0, 'operand': 0,
                                            'parameter': 1, 'value': 99, 'extra': 1})
        for bad in ({'id': 'd2', 'op': 'd5'},
                    {'id': 'd3', 'op': 'd5', 'record': 'x'},
                    {'id': 'd4', 'op': 'd5', 'record': {'actor': 32}},
                    {'id': 'd5', 'op': 'd5', 'record': {'actor': -1}},
                    {'id': 'd6', 'op': 'd5', 'record': {'actor': True}},
                    {'id': 'd7', 'op': 'd5', 'record': {'actor': 1, 'parameter': 'x'}},
                    {'id': 'd8', 'op': 'd5', 'record': {'actor': 1, 'subtype': 256}}):
            self.assertIsNone(control_validate(bad, set())[0], bad)

    def test_once_only_ids_are_never_retried(self):
        done = set()
        first, reason = control_validate({'id': 'r1', 'op': 'chat', 'text': 'a'}, done)
        self.assertIsNotNone(first)
        done.add(first['id'])
        again, reason = control_validate({'id': 'r1', 'op': 'chat', 'text': 'a'}, done)
        self.assertIsNone(again)
        self.assertEqual(reason, 'duplicate_id')
        stop, reason = control_validate({'id': 'r2', 'op': 'stop'}, done)
        self.assertEqual(stop['op'], 'stop')


class FramesExtractTests(unittest.TestCase):
    def test_select_keeps_known_classes_only(self):
        self.assertEqual(frame_select({'ev': 'received_packet', 'type': 3}),
                         'local_delivery_type3')
        self.assertEqual(frame_select({'ev': 'received_packet', 'type': 4,
                                       'object': {'cmd': 6}}), 'broadcast_cmd_6')
        self.assertEqual(frame_select({'ev': 'received_packet', 'type': 4,
                                       'object': {'cmd': 11}}), 'broadcast_cmd_11')
        self.assertIsNone(frame_select({'ev': 'received_packet', 'type': 4,
                                        'object': {'cmd': 3}}))
        self.assertIsNone(frame_select({'ev': 'received_packet', 'type': 4,
                                        'object': {'parse_unknown': 'x'}}))
        self.assertEqual(frame_select({'ev': 'sync_command_received'}), 'sync_batch')
        self.assertIsNone(frame_select({'ev': 'selfcheck'}))

    def test_extract_end_to_end_on_synthetic_log(self):
        import tempfile
        folder = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)/'live.jsonl'
            out = Path(tmp)/'frames.jsonl'
            events = [
                {'ev': 'received_packet', 'type': 3, 'wall': 1, 'sender': 7,
                 'length': 4, 'raw_hex': '4601020304', 'sha256': 'aa'},
                {'ev': 'received_packet', 'type': 4, 'object': {'cmd': 7},
                 'wall': 2, 'sender': 2, 'length': 9, 'raw_hex': 'ff', 'sha256': 'bb'},
                {'ev': 'received_packet', 'type': 4, 'object': {'cmd': 3},
                 'wall': 3, 'sender': 2, 'length': 9, 'raw_hex': 'cc', 'sha256': 'dd'},
                {'ev': 'sync_command_received', 'wall': 4, 'sender': 9, 'length': 5,
                 'raw_hex': '6301', 'sha256': 'ee'},
                {'ev': 'selfcheck', 'wall': 5},
            ]
            log.write_text('\n'.join(json.dumps(e) for e in events)+'\n', encoding='utf-8')
            r = subprocess.run([sys.executable, str(folder/'p34_frames_extract.py'),
                                str(log), '--out', str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            rows = [json.loads(x) for x in out.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([x['why'] for x in rows],
                             ['local_delivery_type3', 'broadcast_cmd_7', 'sync_batch'])
            self.assertEqual(rows[0]['raw_hex'], '4601020304')


class DefaultsTests(unittest.TestCase):
    def test_defaults_make_no_experiment(self):
        folder = Path(__file__).resolve().parent
        for name in ('p34_d8_probe.py', 'p34_d8_orchestrate.py'):
            r = subprocess.run([sys.executable, str(folder/name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['state'], 'prepared_only')

    def test_probe_prepared_only_accepts_blank_flag(self):
        folder = Path(__file__).resolve().parent
        r = subprocess.run([sys.executable, str(folder/'p34_d8_probe.py'),
                            '--allow-blank-username'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['state'], 'prepared_only')

    def test_launch_without_consent_fails_before_process_discovery(self):
        import p34_d8_orchestrate as module
        with mock.patch.object(sys, 'argv', ['p34_d8_orchestrate.py', '--launch']), \
             mock.patch.object(module.subprocess, 'check_output', side_effect=AssertionError('must not inspect/launch')):
            with self.assertRaisesRegex(ValueError, 'Phase3_user_approval_required'):
                module.main()

    def test_launch_with_blank_ghost_name_still_needs_consent_first(self):
        import p34_d8_orchestrate as module
        with mock.patch.object(sys, 'argv',
                ['p34_d8_orchestrate.py', '--launch', '--ghost-name', ' ']), \
             mock.patch.object(module.subprocess, 'check_output',
                side_effect=AssertionError('must not inspect/launch')):
            with self.assertRaisesRegex(ValueError, 'Phase3_user_approval_required'):
                module.main()

    def test_python38_syntax(self):
        folder = Path(__file__).resolve().parent
        for p in list(folder.glob('p34*.py')) + list(folder.glob('p40*.py')):
            ast.parse(p.read_text(), filename=str(p), feature_version=(3, 8))


if __name__ == '__main__':
    unittest.main()
