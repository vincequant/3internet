"""Deterministic list-diff events. No LLM. Disappearance is not a match start."""
import hashlib
import time

from .identity import fingerprint, host_of, occupancy, reused_id, room_name, same_listing
from .states import DEFAULT_COOLDOWN, DEFAULT_MISSING_CYCLES, DEFAULT_THRESHOLD, LIVE, MATCH_UNKNOWN, MATCH_WAITING


def room_record(room, now=None):
    current, maximum = occupancy(room)
    return {
        'id': str(room.get('id') or ''),
        'name': room_name(room),
        'host': host_of(room),
        'display': room.get('name') or f'{room_name(room)}[{host_of(room)}]',
        'current': current,
        'maximum': maximum,
        'version': room.get('version'),
        'fingerprint': fingerprint(room),
        'match_state': MATCH_WAITING,
        'match_state_source': 'game_select_list',
        'seen_at': now,
    }


def index_rooms(rooms, now=None):
    return [room_record(room, now) for room in rooms or []]


def pair_rooms(previous, current):
    prev = list(previous or [])
    used = set()
    pairs = []
    for item in current or []:
        match = None
        for index, old in enumerate(prev):
            if index in used:
                continue
            if same_listing(old, item) and not reused_id(old, item):
                match = index
                break
        if match is None:
            pairs.append((None, item))
        else:
            used.add(match)
            pairs.append((prev[match], item))
    missing = [old for index, old in enumerate(prev) if index not in used]
    return pairs, missing


def diff_events(previous, current, now=None, missing_cycles=DEFAULT_MISSING_CYCLES,
                threshold=DEFAULT_THRESHOLD, miss_counts=None):
    now = time.time() if now is None else now
    miss_counts = dict(miss_counts or {})
    events = []
    pairs, missing = pair_rooms(previous, current)
    alive = set()
    for old, item in pairs:
        key = item['fingerprint']
        alive.add(key)
        miss_counts.pop(key, None)
        if old is None:
            events.append(_event('room_appeared', item, now, extra={
                'current': item['current'], 'maximum': item['maximum'],
            }))
            if item['current'] is not None and item['current'] > threshold:
                events.append(_event('occupancy_threshold', item, now, extra={
                    'from': None, 'to': item['current'], 'threshold': threshold,
                }))
            continue
        if old['current'] != item['current'] or old['maximum'] != item['maximum']:
            events.append(_event('occupancy_changed', item, now, extra={
                'from': old['current'], 'to': item['current'],
                'maximum': item['maximum'],
            }))
            if old['current'] is not None and item['current'] is not None and old['current'] <= threshold < item['current']:
                events.append(_event('occupancy_threshold', item, now, extra={
                    'from': old['current'], 'to': item['current'],
                    'threshold': threshold,
                }))
        if old.get('id') != item.get('id') and room_name(old) == room_name(item) and host_of(old) == host_of(item):
            events.append(_event('room_id_rotated', item, now, extra={'old_id': old.get('id')}))
    for old in missing:
        key = old['fingerprint']
        miss_counts[key] = int(miss_counts.get(key) or 0) + 1
        if miss_counts[key] == missing_cycles:
            events.append(_event('room_missing', old, now, extra={
                'cycles': miss_counts[key],
                'note': '列表中持续消失，不能据此宣称已开局',
            }))
    return events, miss_counts


def data_events(previous_status, current_status, now=None):
    now = time.time() if now is None else now
    events = []
    if previous_status == LIVE and current_status != LIVE:
        events.append({
            'type': 'live_lost', 'at': now, 'key': 'live_lost',
            'message': '监控失去实时数据',
        })
    if previous_status != LIVE and current_status == LIVE and previous_status is not None:
        events.append({
            'type': 'live_recovered', 'at': now, 'key': 'live_recovered',
            'message': '实时数据已恢复',
        })
    return events


def should_emit(event, dedup, now=None, cooldown=DEFAULT_COOLDOWN):
    now = time.time() if now is None else now
    if event.get('type') == 'needs_user':
        cooldown = max(cooldown, 86400)
    key = event_key(event)
    sent = (dedup.get('sent') or {})
    last = sent.get(key)
    if last is not None and now - float(last) < cooldown:
        return False
    if event.get('type') == 'occupancy_threshold':
        room = event.get('fingerprint') or event.get('display')
        last_cross = sent.get(f'threshold-active:{room}')
        if last_cross is not None and now - float(last_cross) < cooldown:
            return False
    return True


def mark_sent(dedup, event, now=None):
    now = time.time() if now is None else now
    sent = dict(dedup.get('sent') or {})
    sent[event_key(event)] = now
    if event.get('type') == 'occupancy_threshold':
        room = event.get('fingerprint') or event.get('display')
        sent[f'threshold-active:{room}'] = now
    dedup['sent'] = sent
    return dedup


def event_key(event):
    if event.get('key'):
        return str(event['key'])
    body = '|'.join([
        str(event.get('type') or ''),
        str(event.get('fingerprint') or event.get('display') or ''),
        str(event.get('from') if 'from' in event else event.get('extra', {}).get('from') or ''),
        str(event.get('to') if 'to' in event else event.get('extra', {}).get('to') or ''),
        str(event.get('cycles') or event.get('extra', {}).get('cycles') or ''),
    ])
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:20]


def _event(kind, room, now, extra=None):
    extra = extra or {}
    value = {
        'type': kind,
        'at': now,
        'id': room.get('id'),
        'name': room.get('name'),
        'host': room.get('host'),
        'display': room.get('display'),
        'fingerprint': room.get('fingerprint'),
        'current': room.get('current'),
        'maximum': room.get('maximum'),
        'match_state': MATCH_UNKNOWN if kind == 'room_missing' else MATCH_WAITING,
        'match_state_source': 'unobservable' if kind == 'room_missing' else 'game_select_list',
    }
    value.update(extra)
    return value


def _count(value):
    return '?' if value is None else str(value)


def format_summary(snapshot, events=None, threshold=DEFAULT_THRESHOLD, first=False,
                   waiting_only=False):
    line = snapshot.get('observed_line') or snapshot.get('platform_line') or '未核验线路'
    room = snapshot.get('observed_room') or snapshot.get('platform_room') or ''
    stamp = _clock(snapshot.get('observed_at') or snapshot.get('last_success_at'))
    rows = list(snapshot.get('rooms') or [])
    if waiting_only:
        rows = [item for item in rows if item.get('match_state') == MATCH_WAITING or item.get('current') is not None]
    status = snapshot.get('data_status') or snapshot.get('status')
    source = snapshot.get('platform_line_source') or 'unverified'
    parts = [f'{line} · {stamp}：']
    if room:
        parts = [f'{line} / {room} · {stamp}：']
    if source == 'config_unverified' or snapshot.get('connection_verified') is False:
        parts.append('线路尚未用大厅树核验，不是连接证据。')
    if status != LIVE:
        parts.append(f'当前不是实时列表（{status}）')
        if snapshot.get('last_success_at'):
            parts.append(f'最近成功刷新：{_clock(snapshot["last_success_at"], seconds=True)}。')
        if snapshot.get('message'):
            parts.append(snapshot['message'])
        text = ''.join(parts[:1]) + ' '.join(parts[1:])
        if first:
            text += f'\n默认人数提醒：人数 > {threshold}（含房主）。可回复「设置人数提醒 5」修改。'
        return text.strip()
    parts.append(f'发现{len(rows)}个等待房间。')
    if events:
        for event in events:
            if event['type'] == 'room_appeared':
                parts.append(f'{event["display"]} {event["current"]}/{event["maximum"]} 新出现。')
            elif event['type'] == 'occupancy_changed':
                parts.append(f'{event["display"]} {event["from"]}/{event.get("maximum") or event["maximum"]} → {event["to"]}/{event.get("maximum") or event["maximum"]}。')
            elif event['type'] == 'occupancy_threshold':
                parts.append(f'{event["display"]} {event.get("from") or "?"} → {event["to"]}/{event.get("maximum") or ""}，已达到提醒条件；人数含房主。')
            elif event['type'] == 'room_missing':
                parts.append(f'{event["display"]} 已从列表持续消失；已开局状态不可观测。')
            elif event['type'] in ('live_lost', 'live_recovered'):
                parts.append(event.get('message') or event['type'])
    elif rows:
        for item in rows:
            current = item.get('current')
            maximum = item.get('maximum')
            label = item.get('display') or item.get('name')
            parts.append(f'{label} {_count(current)}/{_count(maximum)}。')
    else:
        parts.append('列表为空（已与界面核对为空，且已核验目标线路，不是读取失败）。')
    if snapshot.get('last_success_at') or snapshot.get('observed_at'):
        parts.append(f'最近成功刷新：{_clock(snapshot.get("last_success_at") or snapshot.get("observed_at"), seconds=True)}。')
    parts.append('人数含房主。已开局状态不可观测。')
    if snapshot.get('platform_online') is not None:
        parts.append(f'平台房间在线 {snapshot["platform_online"]}（不是对局人数）。')
    if first:
        parts.append(f'默认人数提醒：人数 > {threshold}。可回复「设置人数提醒 N」修改。')
    return ''.join(parts[:1]) + ' '.join(parts[1:])


def format_list(snapshot, waiting_only=False):
    return format_summary(snapshot, events=None, first=False, waiting_only=waiting_only)


def format_brief(snapshot):
    """One paragraph for Grok Bot.app. Failures are not empty rooms."""
    status = snapshot.get('data_status') or 'unknown'
    verified = snapshot.get('connection_verified')
    rooms = snapshot.get('rooms') or []
    line = snapshot.get('observed_line') or snapshot.get('platform_line') or '未核验线路'
    message = snapshot.get('message') or ''
    if status != LIVE or verified is False:
        return (
            f'未读到实时列表（{status}）。connection_verified={verified}。{message}'
            ' 这不是「没有房间」，禁止用游戏选择截图下结论。'
        )
    if not rooms:
        return f'已核验 {line} 的游戏选择，列表为空（已与界面核对）。人数含房主。已开局不可观测。'
    bits = [f'已核验 {line}，{len(rooms)} 个等待房间：']
    for room in rooms:
        bits.append(
            f"{room.get('display') or room.get('name')} "
            f"{_count(room.get('current'))}/{_count(room.get('maximum'))}"
        )
    bits.append('人数含房主。已开局不可观测。')
    return ' '.join(bits)


def _clock(value, seconds=False):
    if not value:
        return '--:--'
    stamp = time.localtime(float(value))
    return time.strftime('%H:%M:%S' if seconds else '%H:%M', stamp)
