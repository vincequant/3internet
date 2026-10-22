"""Local monitor config. Passwords and tokens stay outside the package."""
import json
import os
from pathlib import Path

from .states import DEFAULT_COOLDOWN, DEFAULT_INTERVAL, DEFAULT_MISSING_CYCLES, DEFAULT_THRESHOLD
from .version import VERSION

APP_NAME = 'SGI-Room-Monitor'


def default_data_dir():
    override = os.environ.get('SGI_ROOM_MONITOR_HOME')
    if override:
        return Path(override).expanduser()
    if os.name == 'nt':
        root = Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming')
        return root / APP_NAME
    return Path.home() / 'Library/Application Support' / APP_NAME


def example_config():
    return {
        'version': VERSION,
        'instance_id': 'monitor-1',
        'display_name': '小号监控',
        'host_role': 'both',
        'platform_line': '多线2（主线）',
        'platform_room': '三国对战房',
        'refresh_interval_sec': DEFAULT_INTERVAL,
        'alert_threshold': DEFAULT_THRESHOLD,
        'alert_cooldown_sec': DEFAULT_COOLDOWN,
        'missing_cycles': DEFAULT_MISSING_CYCLES,
        'waiting_only_default': False,
        'hub_root': '',
        'monitor_prefix': '',
        'main_prefix': '',
        'lobby_exe': 'SANGUO.exe',
        'game_exe': 'SANPK.exe',
        'account_username': '',
        'credentials_file': '',
        'bind': '127.0.0.1',
        'port': 18771,
        'grokbot': {
            'backend': 'openclaw-telegram',
            'to': 'owner',
            'allow_groups': False,
        },
    }


def load_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def load_config(data_dir=None):
    data_dir = Path(data_dir or default_data_dir())
    path = data_dir / 'config.json'
    value = example_config()
    stored = load_json(path, {}) or {}
    value.update({key: stored[key] for key in stored if key != 'grokbot'})
    if isinstance(stored.get('grokbot'), dict):
        value['grokbot'].update(stored['grokbot'])
    value['data_dir'] = str(data_dir)
    return value


def config_path(data_dir=None):
    return Path(data_dir or default_data_dir()) / 'config.json'
