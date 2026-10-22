"""Parse operator text. Regular refresh never goes through a model."""
import re

from .states import DEFAULT_INTERVAL, DEFAULT_THRESHOLD

COMMANDS = (
    'start', 'list', 'waiting', 'threshold', 'interval',
    'pause', 'resume', 'stop', 'health',
)


def parse_command(text):
    raw = (text or '').strip()
    if not raw:
        return None
    lowered = raw.lower()
    if _any(raw, ('开始监控', '启动监控', 'start monitor', 'start')):
        return {'action': 'start'}
    if _any(raw, ('停止监控', 'stop monitor', 'stop')):
        return {'action': 'stop'}
    if _any(raw, ('暂停监控', 'pause')):
        return {'action': 'pause'}
    if _any(raw, ('恢复监控', '继续监控', 'resume')):
        return {'action': 'resume'}
    if _any(raw, ('健康', 'health', '监控状态', '运行状态')):
        return {'action': 'health'}
    if _any(raw, ('只看等待', '等待中的房间', 'waiting')):
        return {'action': 'waiting'}
    if _any(raw, ('当前列表', '现在几个人', '几个人', '列表', 'list')):
        return {'action': 'list'}
    match = re.search(r'(?:人数提醒|阈值|threshold)\s*(\d+)', raw, re.I)
    if match:
        return {'action': 'threshold', 'value': int(match.group(1))}
    match = re.search(r'(?:刷新间隔|间隔|interval)\s*(\d+)', raw, re.I)
    if match:
        return {'action': 'interval', 'value': int(match.group(1))}
    if lowered in COMMANDS:
        return {'action': lowered}
    return None


def apply_command(command, settings):
    settings = dict(settings or {})
    action = command['action']
    if action == 'threshold':
        value = int(command['value'])
        if not 0 <= value <= 63:
            raise ValueError('人数阈值必须是 0–63')
        settings['alert_threshold'] = value
        settings['threshold_note'] = f'已将人数提醒改为 > {value}'
    elif action == 'interval':
        value = int(command['value'])
        if not 5 <= value <= 600:
            raise ValueError('刷新间隔必须是 5–600 秒')
        settings['refresh_interval_sec'] = value
        settings['interval_note'] = f'已将刷新间隔改为 {value} 秒'
    elif action == 'waiting':
        settings['waiting_only_default'] = True
    elif action == 'list':
        settings['waiting_only_default'] = bool(settings.get('waiting_only_default'))
    settings.setdefault('alert_threshold', DEFAULT_THRESHOLD)
    settings.setdefault('refresh_interval_sec', DEFAULT_INTERVAL)
    settings['last_action'] = action
    return settings


def _any(text, words):
    return any(word in text or word.lower() in text.lower() for word in words)
