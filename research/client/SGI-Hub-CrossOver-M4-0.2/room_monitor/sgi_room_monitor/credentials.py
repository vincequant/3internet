"""Load secrets from Keychain or a 0600 file. Never log them.

kind='monitor' is the alt-account room watcher (service sgi-room-monitor).
kind='main' is the explicit main-account launcher path (service sgi-main-lobby).
"""
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import default_data_dir

SERVICE = 'sgi-room-monitor'
MAIN_SERVICE = 'sgi-main-lobby'


def credential_path(config, kind='monitor'):
    if kind == 'main':
        raw = (config or {}).get('main_credentials_file')
        if raw:
            return Path(raw).expanduser()
        return Path((config or {}).get('data_dir') or default_main_data_dir()) / 'main-credentials.json'
    raw = (config or {}).get('credentials_file')
    if raw:
        return Path(raw).expanduser()
    return Path((config or {}).get('data_dir') or default_data_dir()) / 'credentials.json'


def default_main_data_dir():
    if sys.platform == 'win32':
        root = Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming')
        return root / 'SGI-Wine'
    return Path.home() / 'Library/Application Support/SGI-Wine'


def service_name(kind='monitor'):
    return MAIN_SERVICE if kind == 'main' else SERVICE


def status(config, kind='monitor'):
    username_key = 'main_account_username' if kind == 'main' else 'account_username'
    username = ((config or {}).get(username_key) or '').strip()
    if kind == 'main' and not username:
        username = _read_main_username(config)
    path = credential_path(config, kind=kind)
    file_user = ''
    file_has_password = False
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8'))
        file_user = (data.get('username') or '').strip()
        file_has_password = bool(data.get('password') or data.get('password_env'))
        username = username or file_user
    keychain = False
    if username:
        keychain = _keychain_has(username, service_name(kind))
    ready = bool(username) and (keychain or file_has_password)
    return {
        'username_set': bool(username),
        'username': username,
        'keychain': keychain,
        'file': path.is_file(),
        'file_has_password': file_has_password,
        'ready': ready,
        'path': str(path),
        'kind': kind,
        'service': service_name(kind),
        'entry': _entry_text(ready, username, keychain, path, kind),
    }


def load_credentials(config, prompt=False, kind='monitor'):
    info = status(config, kind=kind)
    username = info['username']
    password = ''
    if username and info['keychain']:
        password = _keychain_get(username, service_name(kind))
    if not password and info['file']:
        data = json.loads(Path(info['path']).read_text(encoding='utf-8'))
        username = username or data.get('username') or ''
        password = data.get('password') or ''
        if data.get('password_env'):
            password = os.environ.get(data['password_env']) or password
    if prompt and not password:
        label = '主号' if kind == 'main' else '监控小号'
        if not username:
            username = input(label + '用户名: ').strip()
        password = getpass.getpass(label + '密码（不回显、不写日志）: ')
    return {'username': username, 'password': password, 'path': info['path'], 'kind': kind}


def store_interactive(config, kind='monitor'):
    info = status(config, kind=kind)
    label = '主号' if kind == 'main' else '监控小号'
    username = info['username'] or input(label + '用户名: ').strip()
    if not username:
        raise RuntimeError('未输入用户名')
    password = getpass.getpass(label + '密码（写入钥匙串，不回显）: ')
    if not password:
        raise RuntimeError('未输入密码')
    if _keychain_set(username, password, service_name(kind)):
        _remember_username(config, username, kind=kind)
        return {'ok': True, 'store': 'keychain', 'username': username, 'kind': kind,
                'service': service_name(kind)}
    path = credential_path(config, kind=kind)
    path.write_text(json.dumps({'username': username, 'password': password}, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
    path.chmod(0o600)
    _remember_username(config, username, kind=kind)
    return {'ok': True, 'store': 'file', 'username': username, 'path': str(path), 'kind': kind}


def missing_credentials(config, kind='monitor'):
    return not status(config, kind=kind)['ready']


def _remember_username(config, username, kind='monitor'):
    from .config import load_config, save_json
    if kind == 'main':
        _write_main_username(config, username)
        return
    data_dir = (config or {}).get('data_dir') or default_data_dir()
    current = load_config(data_dir)
    current['account_username'] = username
    current.pop('data_dir', None)
    save_json(Path(data_dir) / 'config.json', current)


def _main_meta_path(config):
    raw = (config or {}).get('main_meta')
    if raw:
        return Path(raw).expanduser()
    return default_main_data_dir() / 'main-lobby.json'


def _read_main_username(config):
    path = _main_meta_path(config)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            data = {}
        name = (data.get('main_account_username') or data.get('username') or '').strip()
        if name:
            return name
    runtime = Path((config or {}).get('runtime_file') or '') 
    if not runtime.is_file():
        runtime = default_main_data_dir() / 'runtime.json'
    if runtime.is_file():
        try:
            data = json.loads(runtime.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            data = {}
        return (data.get('main_account_username') or '').strip()
    return ''


def _write_main_username(config, username):
    path = _main_meta_path(config)
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8')) or {}
        except json.JSONDecodeError:
            data = {}
    data['main_account_username'] = username
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    runtime = Path((config or {}).get('runtime_file') or (default_main_data_dir() / 'runtime.json'))
    if runtime.is_file():
        try:
            current = json.loads(runtime.read_text(encoding='utf-8')) or {}
        except json.JSONDecodeError:
            current = {}
        current['main_account_username'] = username
        runtime.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _keychain_has(username, service=SERVICE):
    if sys.platform != 'darwin':
        return False
    result = subprocess.run(
        ['security', 'find-generic-password', '-s', service, '-a', username],
        capture_output=True, text=True)
    return result.returncode == 0


def _keychain_get(username, service=SERVICE):
    if sys.platform != 'darwin':
        return ''
    result = subprocess.run(
        ['security', 'find-generic-password', '-s', service, '-a', username, '-w'],
        capture_output=True, text=True)
    if result.returncode != 0:
        return ''
    return (result.stdout or '').rstrip('\n')


def _keychain_set(username, password, service=SERVICE):
    if sys.platform != 'darwin':
        return False
    result = subprocess.run(
        ['security', 'add-generic-password', '-U', '-s', service, '-a', username, '-w', password],
        capture_output=True, text=True)
    return result.returncode == 0


def _entry_text(ready, username, keychain, path, kind='monitor'):
    label = '主号' if kind == 'main' else '小号'
    command = 'sgi_wine_launcher.py creds-set' if kind == 'main' else 'sgi-room-monitor creds-set'
    service = service_name(kind)
    if ready:
        where = '钥匙串' if keychain else str(path)
        return f'{label}凭据已配置（{where}）。用户名已保存，密码不会打印。'
    return (
        f'{label}凭据待配置。请在本机执行：{command}\n'
        f'会提示用户名和密码；优先写入 macOS 钥匙串服务 {service}。\n'
        f'若钥匙串不可用，写入 {path}（权限 600）。不要把密码发到聊天或提交到仓库。'
    )
