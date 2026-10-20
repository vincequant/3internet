"""P34 offline wire, once-only D8 gate and static self-echo branch table.

D8 body reuses the P33 codec vector: own_sync_withdrawal (BE32(8)+BE32(own_id)).
Send channel ABI verified against archived disassembly (SHA-bound, P33 static
snippets): 0x4c80 is one-arg __cdecl GetHostOrSelfID (reads +0x148 is_host,
member returns row1.id); 0x4b60 is four-arg __cdecl reliable submit
(netobj, target_id, buf, len), plain `retl` no stack cleanup. The 24f0
StartSync call site reuses its buf/len slots for both calls; P33 run-123126
proved this channel reaches the host and is ACKed with correct sender/seq.
"""
import time

from p33_wire import own_sync_withdrawal as d8_body  # noqa: F401


RVA_GET_HOST_OR_SELF = 0x4c80
RVA_RELIABLE_SEND = 0x4b60
D8_LENGTH = 8

SEND_CALL_SHAPE = (
    ('0x4c80_get_host_or_self', ('netobj',)),
    ('0x4b60_reliable_submit', ('netobj', 'target_id', 'buf', 'len')),
)


def username_authorized(username, allow_blank_username=False):
    """Display-name gate. Strict single allowed default; an explicit flag may
    additionally admit exactly one ASCII space (blank-name smoke, Session 1)."""
    if username in ('风夜', '待秋至'):
        return True
    return bool(allow_blank_username) and username == ' '


CONTROL_MAX_TEXT = 120


def control_validate(request, done):
    """Validate one hub control request; returns (action, reason).

    action is None when ignored (reason explains why; 'duplicate_id' is the
    silent once-only case). Executed ids are recorded so a request is never
    retried, even after failure — the hub must send a new id to try again.
    """
    if not isinstance(request, dict):
        return None, 'not_a_dict'
    rid = request.get('id')
    if not isinstance(rid, str) or not 0 < len(rid) <= 64:
        return None, 'bad_id'
    if rid in done:
        return None, 'duplicate_id'
    op = request.get('op')
    if op == 'chat':
        text = request.get('text')
        if not isinstance(text, str) or not 0 < len(text) <= CONTROL_MAX_TEXT:
            return None, 'bad_text_length'
        try:
            blob = text.encode('gbk')
        except UnicodeEncodeError:
            return None, 'text_not_gbk'
        return {'id': rid, 'op': 'chat', 'text': text, 'blob': blob}, None
    if op == 'stop':
        return {'id': rid, 'op': 'stop'}, None
    if op == 'd5':
        record = request.get('record')
        if not isinstance(record, dict):
            return None, 'bad_record'
        actor = record.get('actor')
        if not isinstance(actor, int) or isinstance(actor, bool) or not 0 <= actor < 32:
            return None, 'bad_record_field'
        fields = {'actor': actor}
        for key, default in (('subtype', 0), ('operand', 0), ('parameter', 0),
                             ('value', 0), ('extra', 1)):
            value = record.get(key, default)
            if not isinstance(value, int) or isinstance(value, bool) or not -2**31 <= value < 2**31:
                return None, 'bad_record_field'
            fields[key] = value
        if not 0 <= fields['subtype'] <= 255:
            return None, 'bad_record_field'
        return {'id': rid, 'op': 'd5', 'record': fields}, None
    return None, 'unknown_op'


def self_echo_branch(state):
    """Static three-valued table from 3fd0/36e0 disassembly (P34 doc §1)."""
    if not isinstance(state, int):
        raise ValueError('state_int_required')
    if state in (1, 2):
        return ('immediate_type2_31d0_accept_exit_wait'
                '_setevent_84a4_when_departing_own')
    if state in (0, 3, 4):
        return ('queued_84d0_84d4_type2_31d0_at_36e0_round_end')
    raise ValueError('unknown_native_state_%d' % state)


def reliable_send_rc(raw_rc):
    """24f0 wrapper mapping: raw >0 = queued (0 success), else 11 failure."""
    if not isinstance(raw_rc, int):
        raise ValueError('raw_rc_int_required')
    return 0 if raw_rc > 0 else 11


class D8Gate:
    """Once-only reservation; every failure ends the sequence, never retries."""

    def __init__(self):
        self.phase = 'idle'
        self.sent_body = None
        self.raw_rc = None
        self.tx_seq_before = None

    def reserve(self, receipt, own_id, host_id, log_path, now,
                cmd1_acked, completed_rounds):
        if self.phase != 'idle':
            raise ValueError('d8_already_reserved_or_wrong_phase')
        if not d8_authorized(receipt, own_id, host_id, log_path, now):
            return None
        if not cmd1_acked:
            return None
        if not isinstance(completed_rounds, int) or completed_rounds < 1:
            return None
        self.phase = 'reserved'
        return d8_body(own_id)


def d8_authorized(receipt, own_id, host_id, log_path, now):
    """Derived authorization written by the orchestrator from observed facts."""
    if not isinstance(receipt, dict):
        return False
    return (receipt.get('contract') == 'P34'
            and receipt.get('source') == 'p34_derived_authorization'
            and receipt.get('enable_d8') is True
            and receipt.get('cmd1_acked') is True
            and receipt.get('completed_rounds', 0) >= 1
            and receipt.get('own_id') == own_id
            and receipt.get('host_id') == host_id
            and receipt.get('collector_log') == str(log_path)
            and isinstance(receipt.get('observed_wall'), (int, float))
            and 0 <= now-receipt['observed_wall'] <= 600)


def host_withdrawn_receipt(sample, own_id):
    """Host-side sync-list removal observed by the read-only watch."""
    if not isinstance(sample, dict):
        return False
    rows = sample.get('sync_rows') or []
    return all(row.get('id') != own_id for row in rows) and bool(rows)


def worker_stop_reason(sent, observed_abort_rc, fallback_receipt, own_id):
    """Classify a worker exit; honest unknown when no echo/withdrawal evidence.

    sent: D8 was actually sent. observed_abort_rc: any StartSync/EndSync
    returned 11 (84a4 abort event fired by the departing own echo).
    fallback_receipt: fresh host-withdrawn evidence, or None.
    """
    if not sent:
        return 'stopped_before_d8'
    if observed_abort_rc:
        return 'self_echo_abort_acknowledged'
    if fallback_receipt is not None and host_withdrawn_receipt(fallback_receipt, own_id):
        return 'host_withdrawal_confirmed_stop'
    return 'unknown_worker_exit'
