"""Serial Wine/Windows list collector. One in-flight refresh at a time."""
import json
import subprocess
import sys
import time
from pathlib import Path

from .evidence import attach_connection
from .identity import host_of, room_name
from .states import CACHE, LIVE, OFFLINE_DATA, READ_FAIL, REFRESHING_DATA
from .store import empty_snapshot, keep_last_good, load_connection

HUB_HINTS = (
    'research/client/SGI-Hub-CrossOver-M4-0.2',
    'SGI-Hub',
)


def find_hub_root(configured=''):
    if configured and Path(configured).is_dir():
        return Path(configured)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / 'bridge/room_list_reader.py').is_file():
            return parent
    return None


def collect(config, refresh=True, previous=None, timeout=40):
    started = time.time()
    hub = find_hub_root(config.get('hub_root') or '')
    if hub is None:
        return _fail('未找到 Hub 读取器', started, previous, config)
    prefix = (config.get('monitor_prefix') or '').strip()
    main = (config.get('main_prefix') or '').strip()
    if prefix and main and Path(prefix).resolve() == Path(main).resolve():
        return _fail('监控 prefix 与主号相同，已停止以免顶掉主号', started, previous, config, needs_user=True)
    if not prefix:
        return _fail('未配置独立 monitor_prefix，拒绝使用全局唯一窗口', started, previous, config, needs_user=True)
    sys.path.insert(0, str(hub / 'bridge'))
    from room_list_probe import probe_command
    cmd, env = probe_command(hub, refresh=refresh, quiet=True, prefix=prefix)
    raw = _run(cmd, env, timeout)
    if raw.get('error'):
        return keep_last_good(_fail(raw['error'], started, previous, config, status=READ_FAIL), previous)
    snapshot = normalize_reader(raw.get('payload') or {}, config, started, refresh)
    snapshot = attach_connection(snapshot, load_connection(config.get('data_dir')), config)
    if snapshot.get('data_status') != LIVE:
        snapshot = keep_last_good(snapshot, previous)
    return snapshot


def normalize_reader(payload, config, started, refresh):
    status = payload.get('status')
    message = payload.get('message') or ''
    rooms = [_public_room(room) for room in payload.get('rooms') or []]
    data_status = LIVE
    if status == 'fresh' and refresh:
        data_status = LIVE
    elif status == 'cached':
        data_status = CACHE
    elif status in ('unavailable', 'waiting_lobby'):
        data_status = OFFLINE_DATA if '未运行' in message or '已离开' in message else READ_FAIL
    else:
        data_status = CACHE
    if payload.get('ui_listbox') == 'mismatch':
        data_status = CACHE
        message = (message + '；列表人数不一致，不当作实时').strip('；')
    snapshot = empty_snapshot(data_status, message)
    snapshot.update({
        'instance_id': config.get('instance_id'),
        'target_line': config.get('platform_line'),
        'target_room': config.get('platform_room'),
        'platform_line': None,
        'platform_room': None,
        'platform_line_source': 'unverified',
        'observed_at': payload.get('observed_at') or started,
        'elapsed_ms': int((time.time() - started) * 1000),
        'rooms': rooms,
        'reader_status': status,
        'ui_listbox': payload.get('ui_listbox'),
        'ui_list': payload.get('ui_list'),
        'exe': payload.get('exe'),
        'match_state': 'unknown',
        'match_state_source': 'unobservable',
        'match_state_note': '已开局状态不可观测',
    })
    snapshot = attach_connection(snapshot, payload.get('connection') or {}, config)
    if snapshot.get('data_status') == LIVE:
        snapshot['last_success_at'] = snapshot['observed_at']
        if not rooms and payload.get('ui_listbox') in ('empty_agree',):
            snapshot['message'] = (message or '列表为空') + '；空列表已与界面核对'
        elif not rooms and payload.get('ui_listbox') not in ('empty_agree', 'rooms_agree', 'count_agree'):
            snapshot['data_status'] = CACHE
            snapshot['message'] = (message or '未读到房间') + '；空结果未核验，不当作 0 人'
    return snapshot


def _public_room(room):
    return {
        'id': str(room.get('id') or ''),
        'name': room_name(room),
        'host': host_of(room),
        'display': room.get('name') or f'{room_name(room)}[{host_of(room)}]',
        'current': room.get('current'),
        'maximum': room.get('maximum'),
        'version': room.get('version'),
        'match_state': 'waiting',
        'match_state_source': 'game_select_list',
    }


def _run(cmd, env, timeout):
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'error': '搜索超时，本轮未标为实时'}
    except OSError as error:
        return {'error': f'无法启动读取器: {error}'}
    text = (result.stdout or '').strip()
    if not text:
        return {'error': (result.stderr or '读取器无输出')[:200]}
    try:
        return {'payload': json.loads(text.splitlines()[-1])}
    except json.JSONDecodeError:
        return {'error': '读取器输出无法解析'}


def _fail(message, started, previous, config, status=READ_FAIL, needs_user=False):
    snapshot = empty_snapshot(status, message)
    snapshot.update({
        'instance_id': config.get('instance_id'),
        'platform_line': config.get('platform_line'),
        'platform_room': config.get('platform_room'),
        'observed_at': started,
        'elapsed_ms': int((time.time() - started) * 1000),
        'needs_user': needs_user,
    })
    return keep_last_good(snapshot, previous)
