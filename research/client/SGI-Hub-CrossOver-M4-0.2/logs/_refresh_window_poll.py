"""One-shot SANPK window visibility poll. No clicks, hide, or audio."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bridge'))
from room_list_reader import (
    CONFIRM, NETHOOK_TITLE, TITLE, k, label, open_game, u, windows,
)


def sample(hwnd, pid):
    vis_confirm = vis_untitled = vis_select = vis_hook = False
    titles = []
    for top in windows(pid, visible_only=False):
        name = label(top)
        cls = label(top, True)
        vis = bool(u.IsWindowVisible(top))
        titles.append([name, vis, cls])
        if name == CONFIRM:
            vis_confirm = vis
        if cls == '#32770' and not name and top != hwnd:
            vis_untitled = vis_untitled or vis
        if name == TITLE:
            vis_select = vis
        if name == NETHOOK_TITLE:
            vis_hook = vis
    return {
        'vis_confirm': vis_confirm,
        'vis_untitled': vis_untitled,
        'vis_select': vis_select,
        'vis_hook': vis_hook,
        'titles': titles,
    }


def main():
    hwnd, pid, handle = open_game()
    try:
        started = time.monotonic()
        samples = []
        flicker = []
        counts = {'confirm': 0, 'untitled': 0, 'select': 0, 'hook': 0}
        while time.monotonic() - started < 16:
            row = sample(hwnd, pid)
            row['t'] = round(time.monotonic() - started, 3)
            if row['vis_confirm']:
                counts['confirm'] += 1
            if row['vis_untitled']:
                counts['untitled'] += 1
            if row['vis_select']:
                counts['select'] += 1
            if row['vis_hook']:
                counts['hook'] += 1
            compact = {k: row[k] for k in ('t', 'vis_confirm', 'vis_untitled', 'vis_select', 'vis_hook')}
            samples.append(compact)
            if row['vis_confirm'] or row['vis_untitled']:
                flicker.append({'t': row['t'], 'titles': row['titles']})
            time.sleep(0.08)
        print(json.dumps({
            'status': 'refresh_window_poll',
            'pid': pid,
            'samples': len(samples),
            'any_confirm_visible': counts['confirm'] > 0,
            'any_untitled_visible': counts['untitled'] > 0,
            'any_select_visible': counts['select'] > 0,
            'any_nethook_visible': counts['hook'] > 0,
            'confirm_true_count': counts['confirm'],
            'untitled_true_count': counts['untitled'],
            'flicker': flicker,
            'first': samples[0] if samples else None,
            'last': samples[-1] if samples else None,
        }, ensure_ascii=False))
    finally:
        k.CloseHandle(handle)


if __name__ == '__main__':
    main()
