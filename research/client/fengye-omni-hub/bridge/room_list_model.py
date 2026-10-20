"""Audited KOEINM room records and conservative notification policy."""
import struct
import math
import re
import time

def validate_alert_settings(threshold, minutes):
    x=float(threshold); y=float(minutes)
    if not math.isfinite(x) or not x.is_integer() or not 0<=x<=63:
        raise ValueError('X 必须是 0–63 的整数')
    if not math.isfinite(y) or not .1<=y<=1440:
        raise ValueError('Y 必须在 0.1–1440 分钟之间')
    return int(x),y

EMPTY_HOST_HINT = '看不到主机'
LIST_COUNT = re.compile(r'(\d+)\s*/\s*(\d+)')
FULLWIDTH_COUNTS = str.maketrans('０１２３４５６７８９／', '0123456789/')


def parse_list_count(text):
    """Use the last n/8 so a name like 1/2练习 does not hide the real count."""
    matches = LIST_COUNT.findall(str(text).translate(FULLWIDTH_COUNTS))
    if not matches:
        return None
    current, maximum = matches[-1]
    return int(current), int(maximum)


def ui_list_agreement(rooms, ui_hints):
    """Compare decoded rooms with game-select Static titles. No list-item extraction."""
    text = ''.join(ui_hints or ())
    empty_hint = EMPTY_HOST_HINT in text
    if rooms and empty_hint:
        return 'mismatch'
    if (not rooms) and empty_hint:
        return 'empty_agree'
    if rooms and not empty_hint:
        return 'rooms_present'
    return 'unknown'


def listbox_agreement(rooms, items, count=None):
    """Compare KOEINM rooms with ListBox rows. items=None means text unread."""
    rooms = list(rooms or [])
    if count is None and items is not None:
        count = len(items)
    if items is None and count is None:
        return 'unknown'
    if count is not None and (count < 0 or count > 100):
        return 'unknown'
    if count == 0 and not rooms:
        return 'empty_agree'
    if count is not None and count != len(rooms):
        return 'mismatch'
    parsed = []
    for line in items or []:
        pair = parse_list_count(line)
        if pair:
            parsed.append(pair)
    if parsed:
        memory = sorted((int(room['current']), int(room['maximum'])) for room in rooms)
        visible = sorted(parsed)
        if memory != visible:
            return 'mismatch'
        return 'rooms_agree'
    rows = [line for line in (items or []) if line and str(line).strip()]
    names_ok = True
    for room in rooms:
        name = room.get('name') or ''
        host = name[name.find('[')+1:-1] if '[' in name and name.endswith(']') else ''
        if not any((name and name in line) or (host and host in line) for line in rows):
            names_ok = False
            break
    if names_ok and rows:
        return 'rooms_agree'
    if count is not None and count == len(rooms):
        return 'count_agree'
    return 'unknown'


def compare_record(result):
    """Only keep numbered-room or contradictory list evidence."""
    kind = result.get('ui_listbox')
    if kind not in ('rooms_agree', 'count_agree', 'mismatch'):
        return None
    rooms = result.get('rooms') or []
    if kind != 'mismatch' and not rooms:
        return None
    return {
        'observed_at': result.get('observed_at'),
        'status': result.get('status'),
        'ui_listbox': kind,
        'ui_list': result.get('ui_list'),
        'rooms': [{'name': room.get('name'), 'current': room.get('current'),
                   'maximum': room.get('maximum')} for room in rooms],
        'items': result.get('ui_listbox_items'),
        'count': result.get('ui_listbox_count'),
        'layout': result.get('ui_layout'),
        'message': result.get('message'),
    }


def apply_layout_freshness(result):
    """Hidden or contradictory 游戏选择 cannot be treated as a live count.

    Applied in the Wine reader so an already-running observer UI still
    receives cached status and will not alarm.
    """
    if result.get('status') != 'fresh':
        return result
    layout = result.get('ui_layout') or {}
    if layout.get('select_visible') is False:
        value = dict(result)
        value['status'] = 'cached'
        value['message'] = '游戏选择不可见，人数不当作实时，不报警'
        return value
    if result.get('ui_listbox') == 'mismatch':
        value = dict(result)
        value['status'] = 'cached'
        value['message'] = '读到房间但游戏列表人数不一致；未用该结果报警'
        return value
    # Static「看不到主机…右键快捷菜单」is dialog chrome, not an empty-only flag.
    # Trust ListBox when it agrees; only use the Static veto if ListBox was unread.
    box = result.get('ui_listbox')
    if result.get('ui_list') == 'mismatch' and box not in ('rooms_agree', 'count_agree', 'empty_agree'):
        value = dict(result)
        value['status'] = 'cached'
        value['message'] = '读到房间但游戏列表不一致；未用该结果报警'
        return value
    return result


def decode_room(raw):
    if len(raw) != 80:
        raise ValueError('房间记录长度不匹配')
    maximum, current, version = struct.unpack_from('<III', raw, 68)
    if not 1 <= current <= maximum <= 64:
        raise ValueError('房间人数数据不合法')
    def name(part):
        if b'\0' not in part:
            raise ValueError('房间名称未结束')
        return part.split(b'\0')[0].decode('gbk', 'replace')
    room, host = name(raw[4:35]), name(raw[35:66])
    if not room or not host:
        raise ValueError('房间名称为空')
    return {'id':str(struct.unpack_from('<I',raw)[0]), 'name':f'{room}[{host}]',
            'current':current, 'maximum':maximum, 'version':version}

class AlertState:
    def __init__(self, threshold=4, minutes=1):
        self.configure(threshold,minutes)
        self.last_alert = None

    def configure(self, threshold, minutes):
        self.threshold,self.minutes=validate_alert_settings(threshold,minutes)

    def update(self, snapshot, now=None, enabled=True):
        if snapshot.get('status') != 'fresh' or not enabled:
            return []
        if 'observed_at' in snapshot and not 0<=time.time()-snapshot['observed_at']<=45:
            return []
        now=time.monotonic() if now is None else now
        events = [r for r in snapshot['rooms'] if r['current'] > self.threshold]
        if not events or (self.last_alert is not None and now-self.last_alert < self.minutes*60):
            return []
        # One shared cooldown: multiple rooms or fluctuating counts cannot
        # produce more than one alarm within the configured interval.
        self.last_alert=now
        return events
