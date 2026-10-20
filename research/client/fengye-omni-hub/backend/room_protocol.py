"""Validation shared by the native UI and the one-shot room controller."""
import ipaddress
import time


def nickname(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('暱稱不可留空或含控制字元')
    try:
        encoded = value.encode('gbk')
    except UnicodeEncodeError:
        raise ValueError('暱稱含 GBK 無法表示的字元') from None
    if len(encoded) > 30:
        raise ValueError('暱稱最多 30 個 GBK 位元組（約 15 個中文字）')
    return value


def request(value):
    if not isinstance(value, dict) or value.get('op') not in (
            'status', 'start', 'search', 'join', 'leave', 'stop', 'register', 'd8'):
        raise ValueError('未知房間操作')
    out = {'op': value['op']}
    if value['op'] == 'start':
        line = value.get('line', '多线3')
        if line not in ('多线2', '多线3'):
            raise ValueError('線路名稱無效')
        out['line'] = line
    if value['op'] == 'join':
        out['nickname'] = nickname(value.get('nickname'))
        try:
            rid = int(value.get('room_id'))
            if not 0 < rid < 2**32:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('房間識別碼無效') from None
        out['room_id'] = str(rid)
        out['virtual_ip'] = str(ipaddress.IPv4Address(rid))
        if value.get('quick') is True:
            out['quick'] = True
    return out


def reserve_join(payload, state, now=None):
    """Bind one join to a recent real SearchSession reply, never typed IPs."""
    now = time.time() if now is None else now
    query = state.get('room_query') or {}
    observed = query.get('observed_at')
    if not isinstance(observed, (float, int)) or not 0 <= now-observed <= 60:
        raise ValueError('房間列表已過期，請先重新整理')
    if state.get('connected') or state.get('phase') not in ('lobby',):
        raise ValueError('請先退出目前房間')
    hits = [r for r in query.get('rooms', []) if str(r.get('id')) == payload['room_id']]
    if len(hits) != 1:
        raise ValueError('選定房間不在目前列表')
    room = hits[0]
    name = room.get('name')
    if not isinstance(name, str) or not name or len(name.encode('gbk')) > 30:
        raise ValueError('房間名稱無效')
    current, maximum = room.get('current'), room.get('maximum')
    if isinstance(current, int) and isinstance(maximum, int) and current >= maximum:
        raise ValueError('房間已滿')
    return dict(payload, session_name=name, host=room.get('host'))
