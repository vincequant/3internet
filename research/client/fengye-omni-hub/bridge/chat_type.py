"""Plan WM_CHAR bytes for SANPK's in-game chat edit.

The match client is an ANSI window and does not import GetClipboardData,
so Ctrl+V never inserts text there. The focused edit consumes WM_CHAR.
This plan never includes Enter, so it does not send the chat line.
"""
WM_CHAR = 0x102
MAX_BYTES = 120


def gbk_units(text):
    if type(text) is not str or not text.strip():
        raise ValueError('没有可打进聊天的文字')
    if any(ch in text for ch in '\r\n\t'):
        raise ValueError('一次只打一行，不代按发送')
    try:
        raw = text.encode('gbk')
    except UnicodeEncodeError as error:
        raise ValueError('这一行有聊天框无法表示的字，未输入') from error
    if len(raw) > MAX_BYTES:
        raise ValueError(f'这一行有 {len(raw)} 字节，聊天一次最多 {MAX_BYTES}，未输入')
    if any(byte in (0x0d, 0x0a, 0x1b) for byte in raw):
        raise ValueError('这一行含有控制符，未输入')
    return list(raw)


def require_chat_target(state):
    """Refuse every known non-chat widget. An idle map has no widget."""
    if not isinstance(state, dict):
        raise ValueError('读不到游戏窗口，未打进聊天')
    if state.get('ending') or state.get('native_dialogs'):
        raise ValueError('游戏弹窗开着，未打进聊天')
    if (state.get('confirmation_typed') or state.get('recruit_visible')
            or state.get('strategy_dialog') or state.get('recruit_dialog')):
        raise ValueError('当前是指令确认或招揽窗口，未打进聊天')
    if state.get('map_mode') or state.get('map_widget'):
        raise ValueError('地图菜单开着，未打进聊天')
    if not state.get('widget_count'):
        raise ValueError('请先打开游戏聊天输入框，再点回游戏')
    hwnd = state.get('hwnd')
    if type(hwnd) is not int or hwnd <= 0:
        raise ValueError('找不到游戏画面，未打进聊天')
    return hwnd


def char_messages(hwnd, text):
    require_chat_target({'hwnd': hwnd, 'widget_count': 1})
    return [(hwnd, WM_CHAR, byte) for byte in gbk_units(text)]
