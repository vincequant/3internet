"""Live snapshot and last-good cache are separate files."""
import time
from pathlib import Path

from .config import load_json, save_json
from .states import CACHE, LIVE, OFFLINE_DATA, READ_FAIL, REFRESHING_DATA


def paths(data_dir):
    root = Path(data_dir)
    return {
        'live': root / 'live.json',
        'cache': root / 'cache.json',
        'dedup': root / 'dedup.json',
        'health': root / 'health.json',
        'events': root / 'events.jsonl',
        'lock': root / 'service.lock',
        'control': root / 'control.json',
        'connection': root / 'connection.json',
    }


def empty_snapshot(status=OFFLINE_DATA, message='', **extra):
    value = {
        'data_status': status,
        'rooms': [],
        'observed_at': None,
        'last_success_at': None,
        'message': message,
        'platform_online': None,
        'platform_online_source': 'unavailable',
        'match_state': 'unknown',
        'match_state_source': 'unobservable',
        'match_state_note': '已开局状态不可观测',
    }
    value.update(extra)
    return value


def write_live(data_dir, snapshot):
    save_json(paths(data_dir)['live'], snapshot)


def write_cache(data_dir, snapshot):
    if snapshot.get('data_status') == LIVE and snapshot.get('rooms') is not None:
        save_json(paths(data_dir)['cache'], snapshot)


def read_live(data_dir):
    return load_json(paths(data_dir)['live'], empty_snapshot())


def read_cache(data_dir):
    return load_json(paths(data_dir)['cache'])


def keep_last_good(current, previous):
    """Failed or contradictory reads keep the last good rooms; never become 0."""
    if current.get('data_status') == LIVE and current.get('rooms') is not None:
        return current
    kept = dict(current)
    source = previous if previous and previous.get('rooms') is not None else None
    if source:
        kept['rooms'] = list(source.get('rooms') or [])
        kept['last_success_at'] = source.get('last_success_at') or source.get('observed_at')
        kept['cache_from'] = source.get('observed_at')
        if kept.get('data_status') == LIVE:
            kept['data_status'] = CACHE
        if not kept.get('message'):
            kept['message'] = '沿用最近一次有效快照，本轮未当作实时人数'
    elif kept.get('data_status') == LIVE:
        kept['data_status'] = READ_FAIL
        kept['rooms'] = []
        kept['message'] = kept.get('message') or '尚无有效快照'
    return kept


def append_event(data_dir, event):
    path = paths(data_dir)['events']
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(__import__('json').dumps(event, ensure_ascii=False) + '\n')


def load_dedup(data_dir):
    return load_json(paths(data_dir)['dedup'], {'sent': {}}) or {'sent': {}}


def save_dedup(data_dir, value):
    save_json(paths(data_dir)['dedup'], value)


def write_health(data_dir, value):
    value = dict(value)
    value['updated_at'] = time.time()
    save_json(paths(data_dir)['health'], value)


def read_health(data_dir):
    return load_json(paths(data_dir)['health'], {})


def save_connection(data_dir, evidence):
    value = dict(evidence or {})
    value['saved_at'] = time.time()
    save_json(paths(data_dir)['connection'], value)
    return value


def load_connection(data_dir):
    if not data_dir:
        return {}
    return load_json(paths(data_dir)['connection'], {}) or {}


def acquire_lock(data_dir):
    path = paths(data_dir)['lock']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            old = int((load_json(path) or {}).get('pid') or 0)
        except Exception:
            old = 0
        if old and _pid_alive(old):
            raise RuntimeError(f'监控已在运行 pid={old}')
    save_json(path, {'pid': os_getpid()})
    return path


def release_lock(data_dir, force=False):
    path = paths(data_dir)['lock']
    try:
        stored = load_json(path) or {}
        if force or int(stored.get('pid') or 0) == os_getpid():
            path.unlink()
    except Exception:
        return


def os_getpid():
    return __import__('os').getpid()


def _pid_alive(pid):
    try:
        __import__('os').kill(int(pid), 0)
        return True
    except OSError:
        return False
