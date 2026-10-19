"""A single serialized native sync worker, with offline-testable API boundary."""
from p33_wire import start_ready, end_ready, elapsed_native


def start_report_authorized(report, own_id, host_id, log_path):
    if not isinstance(report, dict):
        return False
    return (report.get('contract') == 'P33' and report.get('enable_minimal_sync') is True
            and report.get('user_report') == '已点开局' and report.get('own_id') == own_id
            and report.get('host_id') == host_id and report.get('collector_log') == str(log_path))


def sync_authorized(report, effect, own_id, host_id, log_path, now):
    """Bind live consent and read-only P-state receipt to this run and member."""
    if not isinstance(effect, dict):
        return False
    return (start_report_authorized(report, own_id, host_id, log_path)
            and effect.get('own_id') == own_id and effect.get('host_id') == host_id
            and effect.get('P_state') == 2 and effect.get('source') == 'p32_app_rows_read'
            and isinstance(effect.get('observed_wall'), (int, float))
            and 0 <= now-effect['observed_wall'] <= 15)


class RoundGate:
    def __init__(self):
        self.round = 0
        self.phase = 'idle'

    def claim_start(self):
        if self.phase != 'idle':
            raise ValueError('start_already_reserved_or_wrong_phase')
        self.round += 1
        self.phase = 'start_reserved'
        return self.round

    def batch_received(self):
        if self.phase != 'start_reserved':
            raise ValueError('batch_without_start')
        self.phase = 'batch'

    def claim_end(self):
        if self.phase != 'batch':
            raise ValueError('end_already_reserved_or_no_batch')
        self.phase = 'end_reserved'

    def finished(self):
        if self.phase != 'end_reserved':
            raise ValueError('completion_without_end')
        self.phase = 'idle'


def participate(backend, stop, emit):
    """Run on ONE worker thread. Main thread owns HWND/message pumping.

    Backend is this probe's own DLL. Every call is reserved before execution;
    failure ends the worker; there is no API retry or fabricated game action.
    """
    gate = RoundGate()
    try:
        while not stop.is_set():
            if not backend.connected() or backend.state() != 1:
                raise ValueError('start_requires_connected_native_idle_state1')
            cycle = gate.claim_start()
            emit({'ev': 'sync_api_enter', 'phase': 'start', 'round': cycle,
                  'expected_control_hex': start_ready().hex(),
                  'evidence_type': 'API_argument_and_static_expected_bytes; not_wire_capture'})
            rc = int(backend.start())
            emit({'ev': 'sync_api_return', 'phase': 'start', 'round': cycle,
                  'rc': rc, 'native_state': backend.state()})
            if stop.is_set():
                break
            if rc != 0 or backend.state() != 3:
                raise ValueError('start_failed_or_state3_not_observed')
            gate.batch_received()
            before = backend.tick()
            records = backend.batch()
            emit({'ev': 'sync_batch_accepted', 'round': cycle, 'count': len(records),
                  'records': records, 'evidence_type': 'own_native_StartSync_return_and_GetCmd_queue'})
            duration = elapsed_native(before, backend.tick())
            if stop.is_set():
                break
            if backend.state() != 3:
                raise ValueError('end_requires_native_batch_state3')
            gate.claim_end()
            emit({'ev': 'sync_api_enter', 'phase': 'end', 'round': cycle,
                  'processing_ms': duration, 'expected_control_hex': end_ready(duration).hex(),
                  'evidence_type': 'measured_own_processing_time; not_game_state_checksum'})
            rc = int(backend.end(duration))
            emit({'ev': 'sync_api_return', 'phase': 'end', 'round': cycle,
                  'rc': rc, 'native_state': backend.state()})
            if rc != 0 or backend.state() != 1:
                if stop.is_set():
                    break
                raise ValueError('end_failed_or_state1_not_observed')
            gate.finished()
            emit({'ev': 'sync_round_complete', 'round': cycle})
    except Exception as e:
        emit({'ev': 'sync_failed', 'error': type(e).__name__, 'detail': str(e),
              'round': gate.round, 'phase': gate.phase, 'no_retry': True})
    finally:
        emit({'ev': 'sync_worker_stopped', 'rounds_started': gate.round, 'phase': gate.phase})
