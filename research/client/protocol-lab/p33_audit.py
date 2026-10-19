"""Distinguish sampled host-ready, owned API completion and actual slot bytes."""
from collections import Counter


def sync_audit(logs, watched, user_report=None, host_id=None, collector_log=None):
    own = next((r.get('own_id') for r in logs if r.get('ev') == 'open_enter'), None)
    flips = []
    for sample in watched:
        for row in sample.get('sync_rows') or []:
            if row['id'] == own and row['ready_flag'] == 1:
                flips.append({'observed_wall': sample['wall'], 'source': 'host_watch_sync_row',
                              'native_state': sample.get('native_sync_state_84a8')})
    complete = [r for r in logs if r.get('ev') == 'sync_round_complete']
    accepted = [r for r in logs if r.get('ev') == 'sync_batch_accepted']
    slots = [r for r in logs if r.get('ev') == 'native_slot_observed'
             and r.get('inner', {}).get('control', {}).get('control_cmd') == 5]
    phases = Counter((r['round'], r['phase']) for r in logs if r.get('ev') == 'sync_api_enter')
    report = None
    if (isinstance(user_report, dict) and user_report.get('source') == 'user_report'
            and user_report.get('own_id') == own and own is not None
            and user_report.get('host_id') == host_id and host_id is not None
            and user_report.get('collector_log') == collector_log
            and isinstance(user_report.get('can_enter_commands'), bool)
            and isinstance(user_report.get('raw_text'), str)):
        report = user_report
    return {'native_sync': {
        'ready1_first_sample': flips[0] if flips else None,
        'ready1_sample_count': len(flips), 'ready1_unsampled_is_unknown': True,
        'StartSync_accepted_batches': len(accepted),
        'received_control5_slot_samples': len(slots),
        'completed_StartSync_EndSync_cycles': len(complete),
        'latest_complete_round': complete[-1]['round'] if complete else None,
        'duplicate_API_calls_by_round_phase': [list(k)+[n] for k, n in phases.items() if n > 1],
        'failures': [r for r in logs if r.get('ev') == 'sync_failed'],
        'batch_capture_note': 'StartSync return+GetCmd are native observations; control5 bytes are separately sampled; no complete wire-coverage claim',
        'user_command_phase_report': report,
        'user_report_missing_is_unknown': True}}
