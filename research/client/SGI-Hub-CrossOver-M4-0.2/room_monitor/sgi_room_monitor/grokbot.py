"""Send only to the configured OpenClaw Telegram owner DM. Never to groups."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import default_data_dir, save_json


def openclaw_config_path():
    override = os.environ.get('OPENCLAW_CONFIG')
    if override:
        return Path(override).expanduser()
    return Path.home() / '.openclaw' / 'openclaw.json'


def load_openclaw_channels(path=None):
    path = Path(path or openclaw_config_path())
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return data.get('channels') or {}


def owner_telegram_id(channels=None, configured='owner'):
    channels = channels if channels is not None else load_openclaw_channels()
    telegram = channels.get('telegram') or {}
    if not telegram.get('enabled'):
        raise RuntimeError('OpenClaw Telegram 通道未启用')
    allowed = [str(item) for item in telegram.get('allowFrom') or []]
    if configured and configured != 'owner':
        target = str(configured)
        if target not in allowed:
            raise RuntimeError('目标不在 Telegram 私聊 allowlist，已拒绝发送')
        return target
    if len(allowed) != 1:
        raise RuntimeError('无法唯一确定 Telegram 私聊对象，请在本机 config.grokbot.to 填写 allowlist 中的项')
    return allowed[0]


def send_text(text, config=None, runner=None):
    config = config or {}
    grok = config.get('grokbot') or {}
    if grok.get('allow_groups'):
        raise RuntimeError('禁止向群聊发送监控消息')
    backend = grok.get('backend') or 'openclaw-telegram'
    if backend != 'openclaw-telegram':
        raise RuntimeError(f'未支持的 Grokbot 后端: {backend}')
    target = owner_telegram_id(configured=grok.get('to') or 'owner')
    if not text or not str(text).strip():
        raise RuntimeError('空消息未发送')
    record = {
        'at': time.time(),
        'ok': False,
        'backend': backend,
        'target_kind': 'telegram_dm',
        'error': None,
    }
    try:
        result = (runner or _openclaw_send)(target, str(text).strip())
        record['ok'] = True
        record['result'] = result
    except Exception as error:
        record['error'] = str(error)
        _write_send_log(config, record)
        raise
    _write_send_log(config, record)
    return record


def _openclaw_send(target, text):
    binary = shutil.which('openclaw') or '/opt/homebrew/bin/openclaw'
    if not Path(binary).is_file():
        raise RuntimeError('未找到 openclaw 命令')
    attempts = [
        [binary, 'message', 'send', '--channel', 'telegram', '--target', target, '--message', text],
    ]
    last = None
    for cmd in attempts:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return (result.stdout or '').strip() or 'sent'
        last = (result.stderr or result.stdout or f'exit {result.returncode}').strip()
        if 'unknown' not in last.lower() and 'usage' not in last.lower():
            raise RuntimeError(last[:300])
    raise RuntimeError(last[:300] if last else 'openclaw message send 失败')


def _write_send_log(config, record):
    data_dir = Path((config or {}).get('data_dir') or default_data_dir())
    safe = {key: record[key] for key in record if key != 'result' or not _looks_secret(record.get('result'))}
    path = data_dir / 'send-log.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(safe, ensure_ascii=False) + '\n')
    save_json(data_dir / 'last-send.json', safe)


def _looks_secret(value):
    text = str(value or '')
    return 'token' in text.lower() or 'bot' in text.lower() and ':' in text
