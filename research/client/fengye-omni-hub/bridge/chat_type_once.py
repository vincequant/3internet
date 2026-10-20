"""Type one stdin line into the focused in-game chat edit. Does not press Enter."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time
import urllib.request

# Wine starts this file with only the bridge directory on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from chat_type import WM_CHAR, gbk_units, require_chat_target
from quick_control_model import binding
from quick_control_native import Native

STATE_URL = 'http://127.0.0.1:8769/api/state'


def type_line(native, text, is_foreground, sleep, timeout=4.0):
    units = gbk_units(text)
    deadline = time.monotonic() + timeout
    while not is_foreground():
        if time.monotonic() >= deadline:
            raise ValueError('四秒内没有点回游戏，未打进聊天')
        sleep(0.05)
    state = native.capture()
    hwnd = require_chat_target(state)
    if native.owner(hwnd) != native.bound['pid'] or not is_foreground():
        raise ValueError('游戏窗口已不在前面，未打进聊天')
    post = native.u.PostMessageA
    try:
        post.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        post.restype = W.BOOL
    except (AttributeError, TypeError):
        pass
    for byte in units:
        if not post(hwnd, WM_CHAR, byte, 1):
            raise C.WinError(C.get_last_error())
        sleep(0.008)
    return len(units)


def main():
    text = sys.stdin.buffer.read().decode('utf-8')
    with urllib.request.urlopen(STATE_URL, timeout=8) as response:
        bound = binding(json.load(response))
    native = Native(bound, exclusive=False)
    try:
        count = type_line(
            native, text,
            lambda: native.owner(native.u.GetForegroundWindow()) == bound['pid'],
            time.sleep,
        )
    finally:
        native.close()
    print(json.dumps({'ok': True, 'bytes': count}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
