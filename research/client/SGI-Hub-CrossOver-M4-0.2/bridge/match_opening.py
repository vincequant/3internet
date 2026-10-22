"""Name a match from the opening settled board, not later war declarations.

Opening alliances mean a player match. Three allies usually means 3v3, because
the other side starts as 通常 and only declares war later. Many leftover
nations after the board settles are treated as a computer test.
"""
import json
from pathlib import Path

ALLY = 3
COMPUTER_FORCE_MIN = 8
PLAYER_FORCE_MAX = 6
KEEP_FORMATS = frozenset({'1v1', '2v2', '3v3'})
KEEP_MIN_FRAMES = 1000
COMPUTER_ABORT_FRAMES = 80
SAMPLE_SEQS = (1, 10, 20, 25, 30, 40, 50, 80)


def listed_archive(row):
    row = row or {}
    if row.get('simulated'):
        return False
    if row.get('match_kind') == 'computer':
        return False
    title = str(row.get('title') or '')
    return not title.startswith('电脑局')


def kept_opening(info, keep_formats=KEEP_FORMATS):
    if keep_formats is None:
        return True
    return (info or {}).get('format') in keep_formats


def kept_archive(info, keep_formats=KEEP_FORMATS, min_frames=KEEP_MIN_FRAMES, seq=None):
    if not kept_opening(info, keep_formats):
        return False
    if min_frames in (None, 0):
        return True
    count = seq if isinstance(seq, int) else ((info or {}).get('frame_count') or (info or {}).get('last_seq') or 0)
    return count >= min_frames


def force_rows(state):
    lords = ((state or {}).get('entities') or {}).get('lords') or []
    return [row for row in lords if isinstance(row.get('force_id'), int)]


def force_name(row):
    name = row.get('name')
    return name if name else f"势力{row.get('force_id')}"


def alliance_groups(lords):
    ids = [row['force_id'] for row in lords]
    names = {row['force_id']: force_name(row) for row in lords}
    adj = {fid: set() for fid in ids}
    for row in lords:
        rels = row.get('diplomacy_relations')
        if not isinstance(rels, list):
            continue
        for other in ids:
            if other == row['force_id'] or not (0 <= other < len(rels)):
                continue
            if rels[other] == ALLY:
                adj[row['force_id']].add(other)
    seen = set()
    groups = []
    for fid in ids:
        if fid in seen:
            continue
        stack = [fid]
        seen.add(fid)
        block = []
        while stack:
            cur = stack.pop()
            block.append(cur)
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        groups.append(sorted(block))
    allied = [group for group in groups if len(group) >= 2]
    leftover = [group[0] for group in groups if len(group) == 1]
    return allied, leftover, names


def classify_opening(state):
    lords = force_rows(state)
    count = len(lords)
    if count == 0:
        return {
            'match_kind': 'unknown',
            'format': None,
            'title': '开局未定',
            'opening_locked': False,
            'opening_force_count': 0,
            'opening_alliances': [],
        }
    allied, leftover, names = alliance_groups(lords)
    if allied:
        if len(allied) == 1 and leftover and len(allied[0]) == len(leftover):
            blocks = [allied[0], leftover]
        elif leftover:
            blocks = allied + [leftover]
        else:
            blocks = allied
        fmt = 'v'.join(str(len(block)) for block in blocks)
        label = ' vs '.join('/'.join(names[fid] for fid in block) for block in blocks)
        return {
            'match_kind': 'player',
            'format': fmt,
            'title': f'玩家局 {fmt} {label}',
            'opening_locked': True,
            'opening_force_count': count,
            'opening_alliances': [[names[fid] for fid in group] for group in allied],
        }
    if count <= PLAYER_FORCE_MAX:
        if count == 2:
            left, right = (force_name(row) for row in lords)
            return {
                'match_kind': 'player',
                'format': '1v1',
                'title': f'玩家局 1v1 {left} vs {right}',
                'opening_locked': True,
                'opening_force_count': count,
                'opening_alliances': [],
            }
        label = '/'.join(force_name(row) for row in lords)
        return {
            'match_kind': 'player',
            'format': f'{count}人',
            'title': f'玩家局 {count}人 {label}',
            'opening_locked': True,
            'opening_force_count': count,
            'opening_alliances': [],
        }
    if count >= COMPUTER_FORCE_MIN:
        return {
            'match_kind': 'computer',
            'format': f'{count}势力',
            'title': f'电脑局 {count}势力',
            'opening_locked': False,
            'opening_force_count': count,
            'opening_alliances': [],
        }
    return {
        'match_kind': 'unknown',
        'format': f'{count}势力',
        'title': f'开局未定 · {count}势力',
        'opening_locked': False,
        'opening_force_count': count,
        'opening_alliances': [],
    }


def finalize_opening(info, sealed=False):
    info = dict(info or classify_opening({}))
    if info.get('opening_locked'):
        return info
    if sealed and info.get('match_kind') == 'computer':
        info['opening_locked'] = True
        info['title'] = info.get('title') or f"电脑局 {info.get('opening_force_count') or '?'}势力"
    return info


def apply_opening(manifest, info):
    if not info:
        return False
    before = {key: manifest.get(key) for key in
              ('title', 'match_kind', 'format', 'opening_locked', 'opening_force_count', 'opening_alliances')}
    manifest['title'] = info.get('title')
    manifest['match_kind'] = info.get('match_kind')
    manifest['format'] = info.get('format')
    manifest['opening_locked'] = bool(info.get('opening_locked'))
    manifest['opening_force_count'] = info.get('opening_force_count')
    manifest['opening_alliances'] = info.get('opening_alliances') or []
    after = {key: manifest.get(key) for key in before}
    return before != after


def archive_label(row):
    if row.get('simulated'):
        head = row.get('demo_label') or row.get('title') or '模拟演示档案'
        if not str(head).startswith('模拟'):
            head = '模拟 · ' + head
    else:
        head = row.get('title') or '开局未定'
    phase = ''
    if row.get('last_capture_end'):
        phase = ' · ' + str(row.get('last_capture_end'))[:19].replace('T', ' ')
    note = ' · 从此处开始' if row.get('started_mid_match') else ''
    return f"{head} · {row.get('frame_count', 0)}帧 · {row.get('completeness') or '?'}{note}{phase}"


def first_locked_seq(directory, reader=None):
    from game_archive import ArchiveReader
    path = Path(directory)
    own = reader is None
    try:
        if own:
            reader = ArchiveReader(path)
        try:
            count = reader.frame_count()
            if count <= 0:
                return None
            stored = reader.manifest.get('opening_first_seq')
            if isinstance(stored, int) and 1 <= stored <= count:
                if classify_opening(reader.load_frame(stored, clone=False)).get('opening_locked'):
                    return stored
            samples = [seq for seq in SAMPLE_SEQS if 1 <= seq <= count]
            if count not in samples:
                samples.append(count)
            prev = 1
            locked_at = None
            for seq in samples:
                if classify_opening(reader.load_frame(seq, clone=False)).get('opening_locked'):
                    locked_at = seq
                    break
                prev = seq
            if locked_at is None:
                return None
            lo, hi = prev, locked_at
            while lo < hi:
                mid = (lo + hi) // 2
                if classify_opening(reader.load_frame(mid, clone=False)).get('opening_locked'):
                    hi = mid
                else:
                    lo = mid + 1
            return lo
        finally:
            if own:
                reader.close()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def clamp_replay_seq(seq, start, count):
    start = 1 if not start else int(start)
    count = 1 if not count else int(count)
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        seq = start
    return max(start, min(count, seq))


def remember_opening_seq(directory, seq):
    path = Path(directory) / 'manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf8'))
        if data.get('opening_first_seq') == seq:
            return data
        data['opening_first_seq'] = seq
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
        tmp.replace(path)
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def opening_from_archive(directory, sealed=False):
    from game_archive import ArchiveReader
    path = Path(directory)
    best = classify_opening({})
    try:
        with ArchiveReader(path) as reader:
            count = reader.frame_count()
            seqs = [seq for seq in SAMPLE_SEQS if 1 <= seq <= count]
            if count and count not in seqs:
                seqs.append(count)
            for seq in seqs:
                info = classify_opening(reader.load_frame(seq))
                if info.get('opening_locked'):
                    return info
                if info.get('opening_force_count'):
                    best = info
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return finalize_opening(best, sealed=sealed)


def ensure_archive_title(directory, data=None):
    path = Path(directory)
    manifest_path = path / 'manifest.json'
    if data is None:
        data = json.loads(manifest_path.read_text(encoding='utf8'))
    if data.get('opening_locked') and data.get('title'):
        return data
    info = opening_from_archive(path, sealed=not data.get('open'))
    if apply_opening(data, info):
        try:
            tmp = manifest_path.with_name(manifest_path.name + '.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
            tmp.replace(manifest_path)
        except OSError:
            pass
    return data


def purge_unkept_archives(root=None, keep_formats=KEEP_FORMATS, min_frames=KEEP_MIN_FRAMES):
    from game_archive import default_archive_root, list_archives
    root = Path(root or default_archive_root())
    removed = []
    for row in list_archives(root):
        if kept_archive(row, keep_formats, min_frames):
            continue
        path = Path(row['directory'])
        try:
            import shutil
            shutil.rmtree(path)
        except OSError:
            continue
        if not path.exists():
            removed.append(str(path))
    return removed
