"""State upgrades need lobby/game evidence. Process names and config are not enough."""
from .states import (
    GAME_STARTING, LIST_WINDOW_READY, LOBBY_LOGGED_IN, LOGGED_OUT, LOGGING_IN,
    READ_FAIL, ROOM_CONNECTED, VALID_EMPTY, VALID_NONEMPTY,
)


def selected_texts(info):
    found = []
    for tree in info.get('trees') or []:
        for item in tree.get('items') or []:
            text = (item.get('text') or '').strip()
            if item.get('selected') and text:
                found.append(text)
    return found


def _contains(text, wanted):
    if not wanted or not text:
        return False
    return wanted in text or text in wanted


def connection_evidence(info, config=None):
    config = config or {}
    target_line = (config.get('platform_line') or '').strip()
    target_room = (config.get('platform_room') or '').strip()
    selected = selected_texts(info)
    titles = list(info.get('titles') or [])
    observed_line = next((text for text in selected if _contains(text, target_line) or '多线2' in text), None)
    observed_room = next((text for text in selected if _contains(text, target_room) or '对战房' in text), None)
    if not observed_line:
        observed_line = next((text for text in titles if '多线2' in text or _contains(text, target_line)), None)
    if not observed_room:
        observed_room = next((text for text in titles if '对战房' in text or _contains(text, target_room)), None)
    game_select = bool(info.get('game_select'))
    in_game_room = bool(info.get('has_start')) and any('房间用户' in (text or '') for text in titles)
    connected = bool(observed_line and (not target_line or _contains(observed_line, target_line) or '多线2' in observed_line))
    if in_game_room:
        connected = True
    return {
        'target_line': target_line,
        'target_room': target_room,
        'selected': selected,
        'observed_line': observed_line,
        'observed_room': observed_room,
        'logged_in': bool(info.get('logged_in') or info.get('has_start')),
        'game_select': game_select,
        'sanpk_running': bool(info.get('sanpk_running')),
        'in_game_room': in_game_room,
        'target_connected': connected,
        'list_window_ready': game_select,
        'source': 'lobby_tree_and_game_select' if observed_line else (
            'start_button_and_room_users' if in_game_room else 'lobby_tree_and_game_select'),
    }


def lifecycle_state(info, config=None):
    ev = connection_evidence(info, config)
    if ev['list_window_ready'] and ev['target_connected']:
        return LIST_WINDOW_READY, ev
    if ev['list_window_ready'] and not ev['target_connected']:
        return GAME_STARTING, ev
    if ev['target_connected']:
        return ROOM_CONNECTED, ev
    if ev['sanpk_running'] and not ev['list_window_ready']:
        return GAME_STARTING, ev
    if ev['logged_in']:
        return LOBBY_LOGGED_IN, ev
    if info.get('login') or info.get('has_login_button'):
        return LOGGING_IN if info.get('login_submitted') else LOGGED_OUT, ev
    return LOGGED_OUT, ev


def classify_list(snapshot):
    """Blank screenshot/list is not a valid empty result without connection evidence."""
    rooms = snapshot.get('rooms') or []
    verified = bool(snapshot.get('connection_verified'))
    ui = snapshot.get('ui_listbox')
    status = snapshot.get('data_status')
    if status in (READ_FAIL,):
        return READ_FAIL
    if not verified:
        if not rooms:
            return READ_FAIL
        return snapshot.get('data_status')
    if not rooms and ui in ('empty_agree',):
        return VALID_EMPTY
    if rooms:
        return VALID_NONEMPTY
    return READ_FAIL


def attach_connection(snapshot, evidence, config=None):
    config = config or {}
    evidence = dict(evidence or {})
    snapshot = dict(snapshot)
    snapshot['target_line'] = evidence.get('target_line') or config.get('platform_line')
    snapshot['target_room'] = evidence.get('target_room') or config.get('platform_room')
    snapshot['observed_line'] = evidence.get('observed_line')
    snapshot['observed_room'] = evidence.get('observed_room')
    snapshot['connection_verified'] = bool(evidence.get('target_connected') and evidence.get('list_window_ready'))
    snapshot['connection_source'] = evidence.get('source') or 'unverified'
    if snapshot['observed_line']:
        snapshot['platform_line'] = snapshot['observed_line']
        snapshot['platform_line_source'] = 'lobby_tree'
    else:
        snapshot['platform_line'] = snapshot.get('target_line')
        snapshot['platform_line_source'] = 'config_unverified'
    if snapshot['observed_room']:
        snapshot['platform_room'] = snapshot['observed_room']
        snapshot['platform_room_source'] = 'lobby_tree'
    else:
        snapshot['platform_room'] = snapshot.get('target_room')
        snapshot['platform_room_source'] = 'config_unverified'
    if not snapshot['connection_verified']:
        extra = '尚未核验已进入目标线路并出现游戏选择，空白窗不能当有效空列表'
        message = snapshot.get('message') or ''
        if extra not in message:
            snapshot['message'] = (message + '；' + extra).strip('；')
        if not snapshot.get('rooms') and snapshot.get('data_status') not in (READ_FAIL,):
            snapshot['data_status'] = READ_FAIL
    return snapshot
