"""Evidence-only P32 verdicts. A last-message slot is sampled, not a capture."""
from collections import Counter


def audit(logs, watched):
    opened = next((r for r in logs if r.get('ev') == 'open_enter'), {})
    own = opened.get('own_id')
    sends = [r for r in logs if r.get('ev') == 'send_enter' and r.get('label') == 'cmd1']
    sent = sends[0] if sends else None
    start = sent['wall'] if sent else None
    samples = [r for r in watched if start is not None and start <= r.get('wall', 0) <= start+60]
    events, beats, present, missing = [], [], [], []
    for sample in samples:
        if 'error' in sample:
            events.append({'wall': sample['wall'], 'kind': 'watch_error', 'detail': sample['error']})
            continue
        hits = [m for m in sample.get('members', []) if str(m.get('id')) == str(own) and m.get('name') == '风夜']
        if hits:
            present.append(sample['wall'])
            if hits[0].get('reconnecting') or hits[0].get('failed'):
                events.append({'wall': sample['wall'], 'kind': 'reconnect_or_failure', 'member': hits[0]})
        else:
            missing.append(sample['wall'])
        raw = bytes.fromhex(sample.get('last_msg_14c', ''))
        # netobj+14c retains INNER bytes (7ab0), sender is the separate slot.
        # Repeated retained values do not establish a newly received heartbeat.
        if raw and raw[0] == 9 and sample.get('last_sender_4150') == own:
            beats.append({'wall': sample['wall'], 'raw_hex': raw.hex()})
    packets = [r for r in logs if r.get('ev') in ('received_packet', 'sync_command_received')]
    before, after = Counter(), Counter()
    for row in packets:
        key = '%s/cmd:%s/len:%s' % (row['ev'], row.get('object', {}).get('cmd', 'unknown'), row['length'])
        (after if start is not None and row['wall'] > start else before)[key] += 1
    latest = max([r.get('wall', 0) for r in logs+watched] or [0])
    elapsed = None if start is None else max(0, latest-start)
    return {'own_id': own, 'cmd1_calls': len(sends), 'cmd1_wall': start,
            'cmd1_send_returns': [r for r in logs if r.get('ev') == 'send_return' and r.get('label') == 'cmd1'],
            'first_60s': {'coverage_seconds': None if start is None else min(60, elapsed),
                         'samples': len(samples), 'present_samples': len(present),
                         'missing_sample_walls': missing, 'reconnect_or_error_events': events,
                         'sampled_inner09': beats,
                         'inner09_distinct_slot_values': len({b['raw_hex'] for b in beats}),
                         'heartbeat_slot_freshness': 'unknown; last slot may retain an old heartbeat',
                         'continuity': 'unknown_between_samples; last-slot polling cannot prove uninterrupted heartbeat'},
            'pre_distribution': dict(before), 'post_distribution': dict(after),
            'post_received_count': sum(after.values()), 'observation_seconds': elapsed,
            'observation_60min_elapsed': elapsed is not None and elapsed >= 3600,
            'host_ui': 'unknown_until_user_report',
            'full_broadcast_coverage': 'unknown; receiver and GetCmd queue are not a complete wire tap'}
