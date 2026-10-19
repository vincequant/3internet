"""Finish game selection after the existing lobby's normal Start button.

Run under that prefix's Win32 Python. Owns no session or game process; exiting
this UI helper must never terminate the lobby or SANPK.
"""
import ctypes as c
import json
import sys


def main():
    import win32_startserver as ui
    cfg = json.load(sys.stdin)
    user32 = c.WinDLL('user32', use_last_error=True)
    search = ui._prep_game_search(user32, lambda: None, timeout=75)
    ready = any(title == '游戏选择' for _hwnd, title, _kids in ui._visible_windows(user32))
    result = {'ok': bool(search.get('ok') and ready), 'lobby_preserved': True,
              'search': search}
    if result['ok'] and cfg.get('join_name'):
        result['join'] = ui._join_listed_game(user32, cfg['join_name'])
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result['ok'] else 3


if __name__ == '__main__':
    sys.exit(main())
