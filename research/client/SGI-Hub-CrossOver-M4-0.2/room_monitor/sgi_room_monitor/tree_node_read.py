"""Read-only Wine TREEITEM → UTF-16 label. No process writes.

Captured against hashed SANGUO (4029e2…294e). Fail-closed if the
64-byte item blob does not match the Wine comctl32 callback layout.
"""
import hashlib
import re
import struct


SANGUO_SHA256 = '4029e2a414f9b2d4e09be16c5d78685d90ac37bf2a5aa701af64398d1e294eee'
ITEM_SIZE = 64
TEXT_PTR_OFF = 24
CALLBACK_OFF = 40
CALLBACK_MASK = 65534  # 0xFFFE, TVIF_TEXT callback
COUNT_SUFFIX = re.compile(r'\(\d+\)$')


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sanguo(path):
    if path is None or not getattr(path, 'is_file', lambda: False)():
        return False
    return file_digest(path) == SANGUO_SHA256


def parse_tree_item(blob):
    """Parse one Wine 32-bit TREEITEM. Returns None if layout is unexpected."""
    if not blob or len(blob) < ITEM_SIZE:
        return None
    dwords = list(struct.unpack_from('<16I', blob))
    parent, nxt, child = dwords[0], dwords[1], dwords[2]
    text_ptr = dwords[TEXT_PTR_OFF // 4]
    callback = dwords[CALLBACK_OFF // 4]
    if callback != CALLBACK_MASK:
        return None
    if text_ptr < 0x10000:
        return None
    for link in (parent, nxt, child):
        if link and link < 0x10000:
            return None
    return {
        'parent': parent,
        'next': nxt,
        'child': child,
        'text_ptr': text_ptr,
        'callback': callback,
    }


def decode_tree_label(raw):
    """UTF-16LE C string; strip lobby '(n)' occupant suffix."""
    if not raw:
        return ''
    if raw.startswith(b'\xff\xfe'):
        raw = raw[2:]
    text = raw.decode('utf-16le', errors='strict').split('\x00', 1)[0]
    return COUNT_SUFFIX.sub('', text).replace('\u3000', ' ').strip()


def label_from_item(blob, text_bytes):
    parsed = parse_tree_item(blob)
    if parsed is None:
        return None
    try:
        return decode_tree_label(text_bytes)
    except (UnicodeDecodeError, ValueError):
        return None


def result_driven_indices(items, names):
    """Prefer depth-2 lines (多线2 lives here), then depth-1 rooms."""
    wanted = ' '.join(names or [])
    depth2 = [i for i, item in enumerate(items or []) if item.get('depth') == 2]
    depth1 = [i for i, item in enumerate(items or []) if item.get('depth') == 1]
    if '多线2' in wanted and depth2:
        return depth2 + [i for i in depth1 if i not in depth2]
    return depth2 + depth1


def parent_label(items, index):
    depth = (items[index] or {}).get('depth')
    if depth is None:
        return ''
    for pos in range(index - 1, -1, -1):
        if (items[pos] or {}).get('depth', 99) < depth:
            return ((items[pos] or {}).get('text') or '').strip()
    return ''


def pick_unique_line(matches, room_hint='三国对战房'):
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None
    selected = [row for row in matches if row.get('selected')]
    if len(selected) == 1:
        return selected[0]
    hinted = [row for row in matches if room_hint and room_hint in (row.get('parent') or '')]
    if len(hinted) == 1:
        return hinted[0]
    return None


def line_entered(info):
    """Observable hall result after a tree click. No tree text required."""
    if not info:
        return False
    if info.get('has_start') or info.get('game_select'):
        return True
    for title in info.get('titles') or []:
        text = title or ''
        if '启动游戏' in text:
            return True
        if '多线2' in text:
            return True
        if text.startswith('房间用户(') and text not in ('房间用户(0)', '房间用户'):
            return True
    return False
