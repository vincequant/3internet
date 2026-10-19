"""P34 serialized native worker: P33 bridge rounds plus once-only D8 uplink.

One thread owns every native call. The D8 is sent inline between rounds
(state==1) on the same thread that would call StartSync, mirroring the 24f0
pattern. The worker's own echo is expected to fire the native abort event
(84a4) so a later StartSync/EndSync returns 11 — that return is the
acknowledged self-echo, not a failure.
"""
from p33_sync import RoundGate
from p34_wire import host_withdrawn_receipt, reliable_send_rc


def participate_d8(backend, stop, emit, gate, receipt_reader, fallback_reader=None,
                   now=None):
    """Run on ONE worker thread. Main thread owns HWND/message pumping.

    backend: this probe's own DLL (connected/state/start/end/batch/send_d8/
    tx_seq/cmd1_acked/own_id/host_id/log_path). gate: D8Gate; the D8
    authorization receipt comes from receipt_reader (fresh, file-bound).
    fallback_reader yields a fresh host-withdrawal receipt or None. now is
    injectable for offline tests.
    """
    if now is None:
        import time
        now = time.time
    gate_ = RoundGate()
    saw_abort = [False]
    fallback_seen = [False]

    def finish(reason):
        emit({'ev': 'worker_exit', 'reason': reason,
              'd8_sent': gate.phase == 'sent',
              'echo_abort_observed': saw_abort[0]})
        return reason

    try:
        while not stop.is_set():
            if not backend.connected() or backend.state() != 1:
                if gate.phase == 'sent':
                    raise ValueError('post_d8_native_state_not_idle_state1')
                raise ValueError('start_requires_connected_native_idle_state1')
            cycle = gate_.claim_start()
            emit({'ev': 'sync_api_enter', 'phase': 'start', 'round': cycle})
            rc = int(backend.start())
            emit({'ev': 'sync_api_return', 'phase': 'start', 'round': cycle, 'rc': rc})
            if rc == 11:
                saw_abort[0] = True
                break
            if stop.is_set():
                break
            if rc != 0 or backend.state() != 3:
                raise ValueError('start_failed_or_state3_not_observed')
            gate_.batch_received()
            before = backend.tick()
            records = backend.batch()
            emit({'ev': 'sync_batch_accepted', 'round': cycle, 'count': len(records),
                  'records': records})
            duration = backend.tick()-before
            if stop.is_set():
                break
            if backend.state() != 3:
                raise ValueError('end_requires_native_batch_state3')
            gate_.claim_end()
            rc = int(backend.end(duration))
            emit({'ev': 'sync_api_return', 'phase': 'end', 'round': cycle, 'rc': rc})
            if rc == 11:
                saw_abort[0] = True
                break
            if rc != 0 or backend.state() != 1:
                raise ValueError('end_failed_or_state1_not_observed')
            gate_.finished()
            emit({'ev': 'sync_round_complete', 'round': cycle})
            if gate.phase == 'idle':
                receipt = receipt_reader()
                if receipt is not None:
                    body = gate.reserve(receipt, backend.own_id, backend.host_id,
                                        str(backend.log_path), now(),
                                        backend.cmd1_acked(), gate_.round)
                    if body is not None:
                        emit({'ev': 'd8_send_enter', 'round': cycle,
                              'body_hex': body.hex(), 'native_tx_seq': backend.tx_seq()})
                        raw_rc, target = backend.send_d8(body)
                        gate.phase = 'sent'
                        gate.raw_rc = raw_rc
                        gate.sent_round = cycle
                        emit({'ev': 'd8_send_return', 'round': cycle, 'raw_rc': raw_rc,
                              'mapped_rc': reliable_send_rc(raw_rc), 'target': target,
                              'native_tx_seq_after': backend.tx_seq(),
                              'self_echo_expected':
                                  'immediate_branch_on_echo; host_queues_until_36e0',
                              'no_retry': True})
            if gate.phase == 'sent' and fallback_reader is not None:
                candidate = fallback_reader()
                if candidate is not None and host_withdrawn_receipt(candidate, backend.own_id):
                    fallback_seen[0] = True
                    emit({'ev': 'host_withdrawal_observed',
                          'observed_wall': candidate.get('observed_wall')})
                    break
    except Exception as e:
        emit({'ev': 'sync_failed', 'error': type(e).__name__, 'detail': str(e),
              'round': gate_.round, 'phase': gate_.phase, 'no_retry': True,
              'd8_sent': gate.phase == 'sent', 'echo_abort_observed': saw_abort[0]})
        return 'failure'
    if gate.phase == 'sent' and saw_abort[0]:
        return finish('self_echo_abort_acknowledged')
    if fallback_seen[0]:
        return finish('host_withdrawal_confirmed_stop')
    return finish('stopped_at_round_boundary')
