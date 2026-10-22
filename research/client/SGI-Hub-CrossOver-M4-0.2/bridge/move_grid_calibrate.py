"""行走格标定工具：从游戏截图逐格提取移动网格，与 Hub 算法输出做精确差集。

用法（详见 MOVE-GRID-CALIBRATION.md）：
    python3 move_grid_calibrate.py SCREENSHOT.png SNAPSHOT.json UNIT_ID \\
        [--anchor-cell X,Y] [--move UID:X,Y ...] [--threshold 0.10]

- SCREENSHOT.png：游戏原生截图（选中部队、网格可见）。
- SNAPSHOT.json：history-data/<identity>/last.json（要与截图同一时刻；部队若已再动，
  用 --move 按 changes.jsonl 回放到截图时刻的位置）。
- UNIT_ID：被选中部队的 unit_id。
- --anchor-cell：截图里红/品红图标（ENTER、攻击标）所在的世界格，如南皮 70,38。
  不给锚点时退回自由拟合+平移匹配（可靠性下降，结果仅供参考）。

输出：晶格比例、逐格分数矩阵、hub多画/hub漏画清单及差格地形。
判读要点：部队/建筑/图标所在格的分数是脏数据（精灵与血条污染），先排除再下结论。
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app')]

from tactical_terrain import Terrain  # noqa: E402
import unit_move as um  # noqa: E402

KIND = {'平地': '平', '道路': '路', '河川': '水', '山岳': '山', '丘陵森林': '丘', '桥梁': '桥', '未知': '?'}


def dots_mask(a):
    """画格内的青色点阵判别：对草地 0.00、画格 0.2+（11:51 标定）。

    海面 B-R>90 排除；河岸/蓝旗用 R>=110 排除；过亮蓝(边框线)用 B<=235 单独处理。"""
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (B - R >= 12) & (B - R <= 70) & (G >= 140) & (R >= 110) & (B <= 235)


def find_icon(a, xmin=0, xmax=10**6, ymin=0, ymax=10**6):
    """红/品红图标（ENTER、攻击标）质心。多个图标时用范围参数挑簇。"""
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    red = (R > 200) & (G < 90) & (B < 160)
    ys, xs = np.nonzero(red)
    m = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
    if m.sum() < 50:
        return None
    return float(xs[m].mean()), float(ys[m].mean())


def world_px(cell):
    x, y = cell
    return 48 + 96 * x + 48 * (y % 2), 24 + 24 * y


def extract(a, anchor_screen, anchor_cell, span=((56, 82), (20, 50))):
    """锚定晶格：screen = world_px*S - off。对 S 与图标偏移做小范围联合搜索。"""
    H, W = a.shape[:2]
    mask = dots_mask(a)
    ii = np.zeros((H + 1, W + 1), dtype=np.int64)
    ii[1:, 1:] = mask.cumsum(0).cumsum(1)

    def frac(cx, cy, hw, hh):
        x0, x1, y0, y1 = int(cx - hw), int(cx + hw), int(cy - hh), int(cy + hh)
        if x0 < 0 or y0 < 0 or x1 >= W or y1 >= H:
            return None
        s = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
        return s / ((x1 - x0) * (y1 - y0))

    wpx, wpy = world_px(anchor_cell)
    ax, ay = anchor_screen
    best = None
    for S in np.arange(1.50, 2.10, 0.02):
        for dx in range(-16, 17, 4):
            for dy in range(-14, 15, 4):
                offx, offy = wpx * S - (ax + dx), wpy * S - (ay + dy)
                hw, hh = int(24 * S), int(11 * S)
                score = 0
                for y in range(span[1][0] + 4, span[1][1] - 4):
                    for x in range(span[0][0] + 4, span[0][1] - 4):
                        px, py = world_px((x, y))
                        f = frac(px * S - offx, py * S - offy, hw, hh)
                        if f is not None and f > 0.10:
                            score += min(f, 0.3)
                if best is None or score > best[0]:
                    best = (score, S, offx, offy)
    _, S, offx, offy = best
    hw, hh = int(24 * S), int(11 * S)
    scores = {}
    for y in range(*span[1]):
        for x in range(*span[0]):
            px, py = world_px((x, y))
            f = frac(px * S - offx, py * S - offy, hw, hh)
            if f is not None:
                scores[(x, y)] = round(float(f), 3)
    return S, scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('screenshot')
    ap.add_argument('snapshot')
    ap.add_argument('unit_id', type=int)
    ap.add_argument('--anchor-cell', help='锚点图标所在世界格 X,Y（如 70,38）')
    ap.add_argument('--icon-x-min', type=int, default=0)
    ap.add_argument('--icon-x-max', type=int, default=10**6)
    ap.add_argument('--icon-y-min', type=int, default=0)
    ap.add_argument('--icon-y-max', type=int, default=10**6)
    ap.add_argument('--move', action='append', default=[],
                    help='回放部队位置 UID:X,Y（可多次），按 changes.jsonl 回放到截图时刻')
    ap.add_argument('--threshold', type=float, default=0.10)
    args = ap.parse_args()

    data = json.loads(Path(args.snapshot).read_text())
    cur = copy.deepcopy(data.get('current') or data)
    for spec in args.move:
        uid, xy = spec.split(':')
        x, y = xy.split(',')
        for u in cur['entities']['field_units']:
            if u.get('unit_id') == int(uid):
                u['world_xy_raw'] = [int(x), int(y)]
    unit = next(u for u in cur['entities']['field_units'] if u.get('unit_id') == args.unit_id)
    origin = um.world_xy(unit)
    terrain = Terrain()
    reach = um.reachable_cells(cur, unit, terrain)
    painted = {i['cell'] for i in um.move_overlay_cells(cur, unit, terrain)} - {origin}

    im = Image.open(args.screenshot).convert('RGB')
    a = np.asarray(im).astype(int)
    if not args.anchor_cell:
        print('未给 --anchor-cell：仅输出 Hub 结果，请人工比对。painted=%d' % len(painted))
        for c in sorted(painted):
            print(' ', c, KIND[um.terrain_kind(cur, c, terrain)], '剩MP', reach.get(c))
        return
    anchor_cell = tuple(int(v) for v in args.anchor_cell.split(','))
    icon = find_icon(a, args.icon_x_min, args.icon_x_max, args.icon_y_min, args.icon_y_max)
    if icon is None:
        print('未找到红色图标锚点，退出。可用 --icon-*-min/max 缩小范围。')
        return
    S, scores = extract(a, icon, anchor_cell)
    game = {c for c, f in scores.items() if f >= args.threshold}
    known = set(scores)

    # 脏格：部队、建筑、城、锚点格（精灵/血条/图标污染判分）
    dirty = {origin}
    for u in cur['entities']['field_units']:
        c = um.world_xy(u)
        if c:
            dirty.add(c)
    for key in ('production_buildings', 'cities_and_barriers'):
        for r in cur['entities'].get(key) or []:
            c = um.world_xy(r)
            if c:
                dirty.add(c)
    dirty.add(anchor_cell)

    hub = painted & known - dirty
    gm = game - dirty
    print('晶格 S=%.2f 已知格=%d 游戏画=%d hub画(可比)=%d' % (S, len(known), len(gm), len(hub)))
    print('hub多画:', [(c, KIND[um.terrain_kind(cur, c, terrain)], '剩MP', reach.get(c))
                     for c in sorted(hub - gm)])
    print('hub漏画:', [(c, KIND[um.terrain_kind(cur, c, terrain)], '分数', scores.get(c))
                     for c in sorted(gm - hub)])
    print('分数矩阵（* = hub画）:')
    ys = sorted({y for _, y in known})
    xs = sorted({x for x, _ in known})
    for y in ys:
        row = []
        for x in xs:
            f = scores.get((x, y))
            mark = '*' if (x, y) in painted else ' '
            row.append(' . ' if f is None else ('%2.0f%s' % (min(f * 99, 99), mark)))
        print('%2d' % y, ' '.join(row))


if __name__ == '__main__':
    main()
