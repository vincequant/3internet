"""Separate sampled wire facts, user UI reports and static expectations.

Every sampled claim keeps its unknowns: slot sampling can miss frames, sync
rows are 1-second snapshots, and a missing row is not asserted as proof of
any earlier state.
"""
from collections import Counter


def d8_audit(logs, watched, ui_report=None, host_id=None, collector_log=None):
    own = next((r.get('own_id') for r in logs if r.get('ev') == 'open_enter'), None)
    sends = [r for r in logs if r.get('ev') == 'd8_send_return']
    send_enter = [r for r in logs if r.get('ev') == 'd8_send_enter']
    workers = [r for r in logs if r.get('ev') == 'worker_exit']
    d8_mono = sends[-1]['mono'] if sends else None
    d8_wall = sends[-1]['wall'] if sends else None
    echo_exits = [r for r in logs if r.get('ev') == 'accept_exit'
                  and d8_mono is not None and r['mono'] >= d8_mono]
    type2_after = [r for r in logs if r.get('ev') == 'notification' and r.get('type') == 2
                   and d8_mono is not None and r['mono'] >= d8_mono]

    before_sync, after_sync = [], []
    for sample in watched:
        rows = sample.get('sync_rows') or []
        hit = any(row['id'] == own for row in rows)
        if not rows:
            continue
        if d8_wall is None or sample['wall'] <= d8_wall:
            before_sync.append((sample['wall'], hit))
        else:
            after_sync.append((sample['wall'], hit))
    withdrawn_after = bool(after_sync) and all(not hit for _, hit in after_sync)
    still_present_after = bool(after_sync) and any(hit for _, hit in after_sync)

    packets_after = Counter()
    for r in logs:
        if r.get('ev') == 'received_packet' and d8_mono is not None and r['mono'] >= d8_mono:
            packets_after['type:%s' % r['type']] += 1

    report = None
    if (isinstance(ui_report, dict) and ui_report.get('source') == 'user_report'
            and ui_report.get('own_id') == own and own is not None
            and ui_report.get('host_id') == host_id and host_id is not None
            and ui_report.get('collector_log') == collector_log
            and isinstance(ui_report.get('row_visible'), bool)
            and isinstance(ui_report.get('raw_text'), str)):
        report = ui_report

    return {'d8': {
        'own_id': own,
        'd8_send_attempts': len(send_enter),
        'd8_send_returns': [{'raw_rc': s['raw_rc'], 'mapped_rc': s.get('mapped_rc'),
                             'target': s.get('target'),
                             'native_tx_seq_after': s.get('native_tx_seq_after')}
                            for s in sends],
        'd8_sent_exactly_once': len(send_enter) == 1 and len(sends) == 1,
        'self_echo_accept_exit_events': [{'member_id': r.get('member_id'), 'rc': r.get('rc')}
                                         for r in echo_exits],
        'type2_notifications_after_d8': len(type2_after),
        'worker_exits': [{'reason': w.get('reason'), 'd8_sent': w.get('d8_sent'),
                          'echo_abort_observed': w.get('echo_abort_observed')} for w in workers],
        'host_sync_list_before_d8': before_sync[-3:],
        'host_sync_list_after_d8': after_sync[-3:],
        'host_withdrawal_observed': withdrawn_after if after_sync else None,
        'host_still_lists_ghost': still_present_after if after_sync else None,
        'received_packets_after_d8_by_type': dict(packets_after),
        'broadcast_continuity_after_d8': ('observed' if packets_after else
                                          'unknown_or_silent_window'),
        'user_ui_row_report': report,
        'user_report_missing_is_unknown': True,
        'sample_note': 'slot/1s sampling can miss frames; absence of evidence is not evidence of absence'}}
