"""Force-level camp/train simulator. Opening stocks from archives; four missing nations from website."""
import copy
from training_prediction import COEFF, muldiv, stock_training_base

KINDS = ('infantry', 'cavalry', 'bow')
KIND_CN = {'infantry': '步', 'cavalry': '骑', 'bow': '弓'}
CAMP_CN = {'infantry': '练兵所', 'cavalry': '牧场', 'bow': '弓工坊'}
SEASON_CN = ('春', '夏', '秋', '冬')
NAMES = {
    'infantry': ('步兵', '强化步兵', '重装步兵'),
    'cavalry': ('骑兵', '强化骑兵', '铁骑兵'),
    'bow': ('弓兵', '弩兵', '连弩'),
}
# Archive-measured medians (9 player matches).
CAMP_YIELD = {'infantry': 14165, 'cavalry': 3225, 'bow': 9240}
GOAL_STOCK = 100000
GOAL_STOCK_BY_KIND = {'bow': 100000, 'infantry': 100000, 'cavalry': 100000}
GOAL_BY_KIND = {'bow': 180, 'infantry': 250, 'cavalry': 250}
GOAL_RAW = GOAL_BY_KIND['bow']
COMMANDS_PER_SEASON = 3
START_YEAR = 200
POL = 100
YEAR1_PRE = 0
YEAR1_POST = 3
YEAR1_CIVIL = 0
LATER_PRE = 3
LATER_POST = 3
# 9 player matches, complete force-years only (saw a later year or all four seasons).
YEAR_PACE = {
    'year1': {'n': 38, 'build_mean': 0.58, 'train_mean': 4.29, 'build_median': 0, 'train_median': 4, 'civil_mean': 4.87},
    'later': {'n': 64, 'build_mean': 0.44, 'train_mean': 4.31, 'build_median': 0, 'train_median': 4, 'civil_mean': 4.75},
}
PACE_NOTE = (
    '约束：200春只出兵，不盖营、不训练。200秋冬起最多 3 格盖或练；其后每年最多 6 次（夏天前 3、夏天后 3）。'
    '目标：弓 10 万/原值 180；骑 10 万/原值 250；步 10 万/原值 250。指令数只计建房+训练。'
)

# force_id, name, stock, raw, summer camp, source
OPENING = (
    (0, '魏', (30000, 10000, 20000), (190, 130, 130), (1500, 6500, 1500), 'archive'),
    (1, '赵', (20000, 40000, 0), (101, 150, 0), (4300, 500, 0), 'archive'),
    (2, '韩', (20000, 6000, 30000), (200, 100, 160), (5800, 500, 4000), 'archive'),
    (3, '齐', (40000, 30000, 0), (190, 150, 0), (1600, 3000, 0), 'archive'),
    (4, '楚', (20000, 20000, 20000), (150, 150, 130), (1000, 1500, 1500), 'archive'),
    (5, '燕', (5000, 30000, 0), (50, 180, 0), (4800, 6000, 0), 'archive'),
    (6, '秦', (40000, 5000, 3000), (300, 0, 230), (2100, 1000, 0), 'archive'),
    (7, '晋', (30000, 30000, 0), (180, 150, 0), (1100, 2000, 0), 'archive'),
    (8, '吴', (20000, 2000, 40000), (110, 230, 180), (0, 0, 0), 'website'),
    (9, '越', (10000, 20000, 20000), (130, 150, 130), (1000, 3500, 1500), 'archive'),
    (10, '周', (30000, 20000, 20000), (180, 120, 130), (5700, 1100, 0), 'archive'),
    (11, '宋', (30000, 10000, 20000), (200, 100, 180), (500, 1000, 5800), 'archive'),
    (12, '鲁', (20000, 30000, 0), (150, 180, 0), (1000, 3000, 0), 'archive'),
    (13, '义渠', (20000, 45000, 0), (70, 200, 0), (0, 4000, 0), 'archive'),
    (14, '西凉', (10000, 20000, 20000), (0, 240, 120), (0, 0, 0), 'website'),
    (15, '中山', (30000, 20000, 0), (240, 150, 0), (0, 0, 0), 'website'),
    (16, '代', (20000, 30000, 0), (150, 170, 0), (0, 0, 0), 'website'),
    (17, '蜀', (30000, 10000, 40000), (160, 150, 150), (4200, 500, 4500), 'archive'),
    (18, '巴', (35000, 30000, 0), (150, 150, 0), (3100, 500, 500), 'archive'),
    (19, '南蛮', (30000, 30000, 0), (150, 180, 0), (2000, 3500, 5000), 'archive'),
    (20, '汉', (20000, 20000, 20000), (100, 150, 150), (2000, 9500, 2000), 'archive'),
    (21, '羌', (20000, 30000, 0), (100, 200, 0), (500, 4000, 1000), 'archive'),
)
BY_ID = {row[0]: row for row in OPENING}
BY_NAME = {row[1]: row for row in OPENING}

ACTIONS = (
    ('train:infantry', '练步'),
    ('train:cavalry', '练骑'),
    ('train:bow', '练弓'),
    ('build:infantry', '盖练兵所'),
    ('build:cavalry', '盖牧场'),
    ('build:bow', '盖弓工坊'),
    ('other', '其他指令'),
)


def pack_kinds(values):
    return {kind: int(values[i]) for i, kind in enumerate(KINDS)}


def troop_label(kind, raw):
    if not isinstance(raw, int) or not 0 <= raw <= 300:
        return '未知'
    tier = 0 if raw < 100 else 1 if raw < 200 else 2
    degree = 100 if raw >= 300 else raw % 100
    return f"{NAMES[kind][tier]} {degree}/100"


def train_gain(kind, stock):
    if not isinstance(stock, int) or stock < 0:
        stock = 0
    stock = min(stock, 2000000)
    base = stock_training_base(stock)
    a, b = COEFF[kind]
    return muldiv(base, a * POL, b * 50)


def mix_recruit(raw, stock, added):
    if not isinstance(added, int) or added <= 0:
        return raw, stock
    incoming = raw * 3 // 5
    new_stock = stock + added
    return (raw * stock + incoming * added) // new_stock, new_stock


def opening_state(force_id=None, name=None):
    row = BY_ID.get(force_id) if force_id is not None else None
    if row is None:
        row = BY_NAME.get(name)
    if row is None:
        return None
    fid, fname, stock, raw, camp, source = row
    return {
        'force_id': fid,
        'name': fname,
        'source': source,
        'year': START_YEAR,
        'season': 0,
        'slot': 0,
        'stock': pack_kinds(stock),
        'raw': pack_kinds(raw),
        'camp': pack_kinds(camp),
        'build': 0,
        'train': 0,
        'other': 0,
        'log': [],
        'reached': {},
    }


def phase_text(state):
    return f"{state['year']}年{SEASON_CN[state['season']]} 第{state['slot'] + 1}/{COMMANDS_PER_SEASON} 指令"


def counts(state):
    return state['build'] + state['train']


def goal_raw(kind):
    return GOAL_BY_KIND[kind]


def goal_stock(kind):
    return GOAL_STOCK_BY_KIND.get(kind, GOAL_STOCK)


def goal_hit(state, kind):
    return state['stock'][kind] >= goal_stock(kind) and state['raw'][kind] >= goal_raw(kind)


def _mark_reached(state, note):
    for kind in KINDS:
        if kind in state['reached'] or not goal_hit(state, kind):
            continue
        state['reached'][kind] = {
            'build': state['build'],
            'train': state['train'],
            'other': state['other'],
            'total': counts(state),
            'year': state['year'],
            'season': state['season'],
            'note': note,
        }


def _advance(state):
    state['slot'] += 1
    if state['slot'] < COMMANDS_PER_SEASON:
        return
    state['slot'] = 0
    state['season'] += 1
    if state['season'] >= 4:
        state['season'] = 0
        state['year'] += 1
    if state['season'] == 1:
        _summer(state)


def _summer(state):
    bits = []
    for kind in KINDS:
        added = state['camp'][kind]
        before_raw, before_stock = state['raw'][kind], state['stock'][kind]
        state['raw'][kind], state['stock'][kind] = mix_recruit(before_raw, before_stock, added)
        if added:
            bits.append(
                f"{KIND_CN[kind]}+{added:,} {before_raw}→{state['raw'][kind]} 库存{before_stock:,}→{state['stock'][kind]:,}"
            )
    line = f"{state['year']}年夏 收兵 " + ('；'.join(bits) if bits else '无新增')
    state['log'].append(line)
    _mark_reached(state, line)


def apply_action(state, action):
    state = copy.deepcopy(state)
    kind = None
    if action.startswith('train:') or action.startswith('build:'):
        kind = action.split(':', 1)[1]
        if kind not in KINDS:
            raise ValueError(action)
    label = dict(ACTIONS).get(action, action)
    when = phase_text(state)
    if action.startswith('train:'):
        gain = train_gain(kind, state['stock'][kind])
        raw0 = state['raw'][kind]
        state['raw'][kind] = min(300, raw0 + gain)
        state['train'] += 1
        note = f"{when} {label} {raw0}→{state['raw'][kind]}（+{state['raw'][kind] - raw0}，库存{state['stock'][kind]:,}）"
    elif action.startswith('build:'):
        add = CAMP_YIELD[kind]
        state['camp'][kind] += add
        state['build'] += 1
        note = f"{when} {label} +{add:,} 夏募→{state['camp'][kind]:,}"
    elif action == 'other':
        state['other'] += 1
        note = f"{when} {label}"
    else:
        raise ValueError(action)
    state['log'].append(note)
    _mark_reached(state, note)
    _advance(state)
    return state


def _simulate_cap(kind, stock, raw, camp, max_builds, prefer_build, max_years=24):
    need = goal_raw(kind)
    target = goal_stock(kind)
    yield_n = CAMP_YIELD[kind]
    cmds = builds = trains = 0
    plan = []
    if stock >= target and raw >= need:
        return {'ok': True, 'build': 0, 'train': 0, 'total': 0, 'years': 0,
                'stock': stock, 'raw': raw, 'camp': camp, 'plan': ['开局已达标']}

    def done():
        return stock >= target and raw >= need

    def spend(slots, label):
        nonlocal stock, raw, camp, cmds, builds, trains
        b0, t0 = builds, trains
        for _ in range(slots):
            if done():
                break
            remaining = target - stock
            need_camp = stock < target and builds < max_builds and camp < max(remaining, 1)
            need_train = raw < 300 and (raw < need or stock < target)
            build_now = need_camp and (prefer_build or not need_train)
            train_now = need_train and (not prefer_build or not need_camp)
            if build_now:
                camp += yield_n
                builds += 1
                cmds += 1
            elif train_now:
                raw = min(300, raw + train_gain(kind, stock))
                trains += 1
                cmds += 1
            else:
                break
        db, dt = builds - b0, trains - t0
        if db or dt:
            plan.append(f"{label} 盖{db}练{dt} →库存{stock:,} 原值{raw} 夏募{camp:,}")
        return done()

    for year_i in range(max_years):
        year = START_YEAR + year_i
        pre, post = (YEAR1_PRE, YEAR1_POST) if year_i == 0 else (LATER_PRE, LATER_POST)
        if spend(pre, f"{year}年春"):
            return {'ok': True, 'build': builds, 'train': trains, 'total': cmds,
                    'years': year_i, 'year': year, 'stock': stock, 'raw': raw,
                    'camp': camp, 'plan': plan}
        raw, stock = mix_recruit(raw, stock, camp)
        plan.append(f"{year}年夏收兵 库存{stock:,} 原值{raw}")
        if done():
            return {'ok': True, 'build': builds, 'train': trains, 'total': cmds,
                    'years': year_i, 'year': year, 'stock': stock, 'raw': raw,
                    'camp': camp, 'plan': plan}
        if spend(post, f"{year}年秋冬"):
            return {'ok': True, 'build': builds, 'train': trains, 'total': cmds,
                    'years': year_i, 'year': year, 'stock': stock, 'raw': raw,
                    'camp': camp, 'plan': plan}
    return {'ok': False}


def min_commands(kind, force_id=None, name=None, state=None, max_years=24):
    """Fewest build+train commands to hit the kind's stock and training target.

    200 spring is sortie-only. 200 autumn/winter: up to 3 civil actions.
    Later years: 3 before summer, 3 after.
    """
    if kind not in KINDS:
        raise ValueError(kind)
    if state is None:
        state = opening_state(force_id=force_id, name=name)
    if not state:
        return {'ok': False}
    stock, raw, camp = state['stock'][kind], state['raw'][kind], state['camp'][kind]
    best = None
    for max_builds in range(0, 16):
        for prefer_build in (True, False):
            row = _simulate_cap(kind, stock, raw, camp, max_builds, prefer_build, max_years=max_years)
            if not row.get('ok'):
                continue
            if best is None or row['total'] < best['total'] or (
                row['total'] == best['total'] and row['years'] < best['years']
            ):
                best = row
    return best or {'ok': False}


def project_goal(state, kind):
    """Minimum build+train under the 3-then-6 yearly civil cap."""
    row = min_commands(kind, state=state)
    if not row.get('ok'):
        return {'ok': False, 'build': None, 'train': None, 'total': None}
    return {
        'ok': True,
        'build': row['build'],
        'train': row['train'],
        'other': 0,
        'total': row['total'],
        'year': row.get('year', state['year']),
        'season': 1,
        'stock': row['stock'],
        'raw': row['raw'],
    }


def best_table():
    rows = []
    for fid, name, *_rest in OPENING:
        item = {'force_id': fid, 'name': name}
        for kind in KINDS:
            item[kind] = min_commands(kind, force_id=fid)
        rows.append(item)
    return rows


def _cell(row):
    if not row or not row.get('ok'):
        return '—'
    return f"{row['total']}(盖{row['build']}练{row['train']})"


def format_best_table(rows=None):
    rows = rows or best_table()
    lines = [
        '最少指令（200春只出兵；弓10万/180，骑10万/250，步10万/250）',
        f"{'势力':<4} {'弓':<14} {'骑':<14} {'步':<14}",
    ]
    for row in rows:
        lines.append(f"{row['name']:<4} {_cell(row['bow']):<14} {_cell(row['cavalry']):<14} {_cell(row['infantry']):<14}")
    return '\n'.join(lines)


_STAR_CACHE = None


def _star_index():
    global _STAR_CACHE
    if _STAR_CACHE is not None:
        return _STAR_CACHE
    table = best_table()
    uniq = {}
    lookup = {}
    names = {}
    for kind in KINDS:
        uniq[kind] = sorted({row[kind]['total'] for row in table if row[kind].get('ok')})
    for row in table:
        names[row['name']] = row['force_id']
        for kind in KINDS:
            if row[kind].get('ok'):
                lookup[(row['force_id'], kind)] = row[kind]['total']
    _STAR_CACHE = {'uniq': uniq, 'lookup': lookup, 'names': names}
    return _STAR_CACHE


def kind_stars(kind, force_id=None, name=None):
    """1–3 stars from how few commands this force needs vs the other 21, same kind."""
    if kind not in KINDS:
        return 0
    idx = _star_index()
    fid = force_id if (force_id, kind) in idx['lookup'] else idx['names'].get(name)
    total = idx['lookup'].get((fid, kind))
    if total is None:
        return 0
    uniq = idx['uniq'][kind]
    place = uniq.index(total)
    n = len(uniq)
    if place < n / 3:
        return 3
    if place < 2 * n / 3:
        return 2
    return 1


def star_glyph(count):
    count = max(0, min(3, int(count or 0)))
    return '★' * count + '☆' * (3 - count)


def advantage_kind(force_id=None, name=None):
    st = opening_state(force_id=force_id, name=name)
    if not st:
        return None
    fid = st['force_id']
    scored = []
    for kind in KINDS:
        row = min_commands(kind, force_id=fid)
        if not row.get('ok'):
            continue
        scored.append((kind_stars(kind, force_id=fid), -row['total'], kind))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][2]


def _human_plan_line(kind, line):
    camp = CAMP_CN[kind]
    verb = {'infantry': '练步', 'cavalry': '练骑', 'bow': '练弓'}[kind]
    if '夏收兵' in line or '夏 收兵' in line:
        return line.replace('年夏收兵', '夏：收兵')
    if '盖' not in line:
        return line
    label, _, rest = line.partition(' 盖')
    try:
        b = int(rest.split('练', 1)[0])
        t = int(rest.split('练', 1)[1].split()[0])
    except (ValueError, IndexError):
        return line
    bits = []
    if b:
        bits.append(f'盖{b}座{camp}')
    if t:
        bits.append(f'{verb}{t}次')
    when = label.replace('年春', '春').replace('年秋冬', '秋冬')
    extra = ''
    if '秋冬' in when and when.startswith('200'):
        extra = '。200春只出兵'
    return when + '：' + '，'.join(bits) + extra


def format_kind_order(kind, row):
    if not row or not row.get('ok'):
        return '没有算出路径。'
    lines = list(row.get('plan') or [])
    if not lines:
        return f"最少 {row['total']} 次（盖{row['build']}练{row['train']}）。"
    return '\n'.join(_human_plan_line(kind, line) for line in lines)


def format_force_order(force_id=None, name=None):
    st = opening_state(force_id=force_id, name=name)
    if not st:
        return '没有这个势力的开局。'
    adv = advantage_kind(force_id=st['force_id'])
    head = (
        f"{st['name']}训练顺序（200春只出兵；其后每年最多6次盖或练）\n"
        f"弓 10万/180，骑 10万/250，步 10万/250。星是相对其他势力，不是自家哪条最便宜。\n"
    )
    blocks = [head]
    order = [adv] + [k for k in KINDS if k != adv] if adv else list(KINDS)
    for kind in order:
        row = min_commands(kind, force_id=st['force_id'])
        mark = ' · 相对优势' if kind == adv else ''
        stars = star_glyph(kind_stars(kind, force_id=st['force_id']))
        if not row.get('ok'):
            blocks.append(f"{KIND_CN[kind]} {stars}{mark}\n  未算出\n")
            continue
        blocks.append(
            f"{KIND_CN[kind]} {stars}{mark} · 最少 {row['total']} 次（盖{row['build']}练{row['train']}）· {row.get('year', '')}年达标\n"
            + format_kind_order(kind, row)
            + '\n'
        )
    return '\n'.join(blocks)


def from_live_force(force, recruit=None):
    if not force:
        return None
    stock = force.get('troop_stock') or {}
    raw = force.get('armament_raw') or {}
    camp = {}
    for kind in KINDS:
        if not isinstance(stock.get(kind), int) or not isinstance(raw.get(kind), int):
            return None
        known = (recruit or {}).get(kind) or {}
        camp[kind] = known.get('known') if isinstance(known.get('known'), int) else 0
    return {
        'force_id': force.get('force_id'),
        'name': force.get('name') or '当前',
        'source': 'live',
        'year': START_YEAR,
        'season': 0,
        'slot': 0,
        'stock': {k: stock[k] for k in KINDS},
        'raw': {k: raw[k] for k in KINDS},
        'camp': camp,
        'build': 0,
        'train': 0,
        'other': 0,
        'log': [],
        'reached': {},
    }
