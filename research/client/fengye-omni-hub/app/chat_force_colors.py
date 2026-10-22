"""聊天顯示用：把「名字（勢力）」與訊息文字配上該勢力的遊戲配色。

勢力顏色來自 `app/game_palette.json`（原作調色盤，22 家）。部分顏色（晋、南蛮、
西凉…）在白色底上太亮，`readable()` 會把它壓暗到可讀；查不到勢力就回 None，
呼叫端用一般墨色，不猜。
"""
from __future__ import annotations

import json
from pathlib import Path

PALETTE_FILE = Path(__file__).resolve().parent / 'game_palette.json'
MIN_TEXT_LUMINANCE = 0.42     # 白底文字：亮度上限（超過就壓暗）


def _load_palette(path=None):
    try:
        data = json.loads(Path(path or PALETTE_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    palette = {}
    for entry in (data.get('colors') or {}).values():
        if not isinstance(entry, dict):
            continue
        name, rgb = entry.get('name'), entry.get('rgb')
        if (isinstance(name, str) and name and isinstance(rgb, (list, tuple))
                and len(rgb) == 3 and all(type(v) is int and 0 <= v <= 255 for v in rgb)):
            palette[name] = tuple(rgb)
    return palette


FORCE_RGB = _load_palette()


def force_rgb(name):
    """勢力名稱 → (r,g,b)；沒有這家就回 None。"""
    if not isinstance(name, str):
        return None
    return FORCE_RGB.get(name.strip())


def luminance(rgb):
    r, g, b = (v / 255.0 for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable(rgb, limit=MIN_TEXT_LUMINANCE):
    """白底可讀：太亮的顏色按比例壓暗，暗色原樣保留。"""
    if not rgb:
        return None
    lum = luminance(rgb)
    if lum <= limit or lum <= 0:
        return tuple(rgb)
    scale = limit / lum
    # 用 int() 向下取整：四捨五入會讓亮度剛好超過上限。
    return tuple(max(0, min(255, int(v * scale))) for v in rgb)


def hexcolor(rgb):
    if not rgb:
        return None
    return '#%02x%02x%02x' % tuple(rgb)


def sender_factions(p34):
    """member id → (名字, 勢力名)，取自開局/初始名單（`p34.snapshots`）。

    聊天封包只有 sender id 與昵稱；勢力名要從同一份名單的 `faction` 欄位對回來。
    """
    table = {}
    snapshots = (p34 or {}).get('snapshots') or {}
    for key in ('start', 'initial'):
        rows = (snapshots.get(key) or {}).get('rows') or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            seat = row.get('id')
            if not seat or seat in table:
                continue
            table[seat] = (row.get('name'), row.get('faction'))
        if table:
            break
    return table


def time_text(wall):
    """與 native_window.wall_text 相同格式（mm-dd HH:MM:SS）。"""
    from datetime import datetime
    if not isinstance(wall, (int, float)):
        return '—'
    try:
        return datetime.fromtimestamp(wall).strftime('%m-%d %H:%M:%S')
    except (OSError, ValueError, OverflowError):
        return '—'


def chat_parts(message, store, factions):
    """一條聊天 → (時間戳, 名字（勢力）, 內文, 顏色 hex 或 None)。

    讀不到勢力就只顯示名字、顏色回 None（呼叫端用一般墨色）；讀不到遊戲時間就寫
    「回合未記錄」，都不補造。
    """
    message = message or {}
    wall = message.get('wall')
    when = store.get('%.3f' % wall) if isinstance(wall, (int, float)) else None
    stamp = '%s · %s' % (time_text(wall), when) if when else '%s · 回合未記錄' % time_text(wall)
    name, faction = (factions or {}).get(message.get('sender')) or (None, None)
    name = message.get('sender_name') or name or '—'
    faction = (faction or '').strip() or None
    label = '%s（%s）' % (name, faction) if faction else name
    text = str(message.get('text') or '—')
    return stamp, label, text, hexcolor(readable(force_rgb(faction)))
