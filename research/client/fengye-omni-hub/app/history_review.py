"""Read-only archive snapshot for Hub. Does not write the game."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / 'bridge'
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))
if str(ROOT / 'app') not in sys.path:
    sys.path.insert(0, str(ROOT / 'app'))

from game_archive import IDLE_SEAL_S, ArchiveReader, list_archives
from match_opening import clamp_replay_seq, listed_archive
from state_history import (
    annotate_hire_kinds, calendar_label, comparable_phase, default_root, load_journal_history,
    merge_prestige_commands, phase_label, prestige_command_ops,
)

_REPLAY = {'path': None, 'cursor': None}
_PRESTIGE = {'key': None, 'commands': []}


def _parse_utc(text):
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def is_live_recording(row, live_match_id=None, now=None, stale_s=IDLE_SEAL_S):
    """True only for the match still being written. Stuck open files are previous."""
    row = row or {}
    if live_match_id and row.get('match_id') == live_match_id:
        return True
    if not row.get('open'):
        return False
    if row.get('write_error') or row.get('completeness') == 'write_error':
        return False
    if row.get('completeness') not in (None, 'recording', 'mid_start'):
        return True
    stamp = _parse_utc(row.get('last_capture_end'))
    if stamp is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - stamp).total_seconds() < stale_s


def review_archives(root=None, live_match_id=None, now=None):
    """Same set as standalone 历史回放, minus the match still being written."""
    rows = []
    for row in list_archives(root):
        if not listed_archive(row):
            continue
        if is_live_recording(row, live_match_id=live_match_id, now=now):
            continue
        if not (row.get('last_seq') or row.get('frame_count')):
            continue
        rows.append(row)
    return rows


def previous_archive(root=None, live_match_id=None, now=None):
    rows = review_archives(root, live_match_id=live_match_id, now=now)
    return rows[0] if rows else None


def archive_day(row, tz=None):
    """Calendar day used to browse archives.

    Without tz, the day is the date prefix already stored on the stamp (UTC for
    these archives). Pass tz to group by that zone, so a late-evening match lands
    on the local calendar day.
    """
    if tz is not None:
        for key in ('last_capture_end', 'started_utc', 'ended_utc'):
            stamp = _parse_utc((row or {}).get(key))
            if stamp is not None:
                return stamp.astimezone(tz).date().isoformat()
    else:
        for key in ('last_capture_end', 'started_utc', 'ended_utc'):
            text = str((row or {}).get(key) or '')
            if len(text) >= 10 and text[4] == '-' and text[7] == '-':
                return text[:10]
    name = Path(str((row or {}).get('directory') or '')).name
    if len(name) >= 8 and name[:8].isdigit():
        return f'{name[:4]}-{name[4:6]}-{name[6:8]}'
    return '日期未知'


def archive_match_label(row):
    row = row or {}
    if row.get('simulated'):
        head = row.get('demo_label') or row.get('title') or '模拟演示档案'
        if not str(head).startswith('模拟'):
            head = '模拟 · ' + head
    else:
        head = row.get('title') or '开局未定'
    stamp = str(row.get('last_capture_end') or '')
    clock = stamp[11:16] if 'T' in stamp and len(stamp) >= 16 else ''
    phase = f' · {clock}' if clock else ''
    note = ' · 从此处开始' if row.get('started_mid_match') else ''
    return f"{head} · {row.get('frame_count', 0)}帧 · {row.get('completeness') or '?'}{note}{phase}"


def group_archives_by_day(rows, tz=None):
    groups = {}
    order = []
    for row in rows or []:
        day = archive_day(row, tz=tz)
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(row)
    days = [day for day in order if day != '日期未知']
    if '日期未知' in groups:
        days.append('日期未知')
    return [(day, groups[day]) for day in days]


def replay_archive_label(row, tz=None):
    """Match line under a day header. Clock first so a narrow list still shows it."""
    row = row or {}
    if row.get('simulated'):
        head = row.get('demo_label') or row.get('title') or '模拟演示档案'
        if not str(head).startswith('模拟'):
            head = '模拟 · ' + head
    else:
        head = row.get('title') or '开局未定'
    stamp = _parse_utc(row.get('last_capture_end'))
    clock = ''
    if stamp is not None:
        zone = tz if tz is not None else datetime.now().astimezone().tzinfo
        clock = stamp.astimezone(zone).strftime('%H:%M')
    prefix = f'{clock}  ' if clock else ''
    note = ' · 从此处开始' if row.get('started_mid_match') else ''
    from replay_modifications import label
    modification = label(row.get('modification_provenance') or {})
    if modification: note += ' · ' + modification
    return f"{prefix}{head} · {row.get('frame_count', 0)}帧 · {row.get('completeness') or '?'}{note}"


def archive_list_entries(rows, tz=None):
    """Day header, then that day's matches. Headers are not archives."""
    entries = []
    for day, items in group_archives_by_day(rows, tz=tz):
        entries.append({'kind': 'day', 'day': day, 'label': day_label(day, items), 'row': None})
        for row in items:
            entries.append({
                'kind': 'match',
                'day': day,
                'label': replay_archive_label(row, tz=tz),
                'row': row,
            })
    return entries


def day_label(day, rows):
    n = len(rows or [])
    return f'{day} · {n}局'


def _archive_span(directory, reader=None):
    manifest = (reader.manifest if reader is not None else {}) or {}
    if reader is None:
        path = Path(directory) / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
    count = int(manifest.get('frame_count') or manifest.get('last_seq') or 0)
    if reader is not None and count <= 0:
        count = reader.frame_count()
    start = manifest.get('opening_first_seq')
    if not isinstance(start, int) or start < 1:
        start = 1
    if count < 1:
        count = 1
    return start, count


def archive_time_nodes(directory):
    """Season (and opening/end) jump points. Reads index.json; does not decode frames."""
    path = Path(directory)
    start, count = _archive_span(path)
    index = {}
    idx_path = path / 'index.json'
    if idx_path.is_file():
        try:
            index = json.loads(idx_path.read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError, TypeError):
            index = {}
    nodes = []
    seen = set()

    def add(seq, label, kind, *, force=False):
        seq = clamp_replay_seq(seq, start, count)
        if seq in seen and not force:
            return
        if not force:
            seen.add(seq)
        nodes.append({'seq': seq, 'label': label, 'kind': kind})

    add(start, '开局', 'opening')
    rows = index.get('quarters') or []
    if not rows:
        rows = index.get('rounds') or []
    for row in rows:
        first = row.get('first_seq') or row.get('last_seq')
        if not isinstance(first, int) or first < start:
            continue
        pretty = calendar_label(row.get('year_u16'), row.get('season_u16'))
        rnd = row.get('round_u8')
        if pretty and rnd in (0, 1, 2):
            label = f'{pretty} 第{rnd + 1}回合'
        else:
            label = pretty or str(row.get('label') or f'帧{first}')
        add(first, label, 'quarter')
    add(count, '末帧', 'end', force=True)
    nodes.sort(key=lambda item: (item['seq'], 0 if item['kind'] != 'end' else 1))
    return nodes


def archive_season_nodes(directory):
    """One jump per calendar season, at that season's first frame. Rounds stay inside the season."""
    nodes = []
    seen = set()
    for node in archive_time_nodes(directory):
        if node.get('kind') != 'quarter':
            continue
        label = str(node.get('label') or '')
        key = label.split(' 第', 1)[0]
        if not key or key in seen:
            continue
        seen.add(key)
        nodes.append({'seq': node['seq'], 'label': key, 'kind': 'season'})
    return nodes


def season_neighbors_from(seasons, seq):
    """Previous and next season. A frame inside a season stays in that season."""
    seasons = list(seasons or [])
    index = None
    if isinstance(seq, int):
        for i, node in enumerate(seasons):
            if node['seq'] <= seq:
                index = i
            else:
                break
    prev_node = seasons[index - 1] if isinstance(index, int) and index > 0 else None
    if index is None:
        next_node = seasons[0] if seasons else None
    elif index + 1 < len(seasons):
        next_node = seasons[index + 1]
    else:
        next_node = None
    return prev_node, next_node


def season_neighbors(directory, seq):
    return season_neighbors_from(archive_season_nodes(directory), seq)


def load_archive_frame(directory, seq=None):
    with ArchiveReader(directory) as reader:
        start, count = _archive_span(directory, reader)
        if reader.frame_count() <= 0:
            raise ValueError('档案没有帧')
        if seq is None:
            seq = count
        seq = clamp_replay_seq(seq, start, count)
        state = reader.load_frame(seq)
        return {
            'state': state,
            'seq': seq,
            'frame_count': count,
            'meta': reader.meta(seq),
            'manifest': dict(reader.manifest),
            'directory': str(reader.directory),
        }


def load_last_frame(directory):
    return load_archive_frame(directory, None)


def troop_series_from_archive(directory, until_seq=None):
    from force_troop_totals import append_troop_series, troop_series_point
    series = []
    with ArchiveReader(directory) as reader:
        seqs = []
        rows = reader.index.get('quarters') or []
        if not rows:
            rows = reader.index.get('rounds') or []
        for row in rows:
            seq = row.get('first_seq') or row.get('last_seq')
            if isinstance(seq, int):
                seqs.append(seq)
        count = reader.frame_count()
        if count:
            seqs.append(count)
        if isinstance(until_seq, int):
            seqs = [item for item in seqs if item <= until_seq]
            seqs.append(until_seq)
        for seq in sorted({item for item in seqs if 1 <= item <= count}):
            series = append_troop_series(series, troop_series_point(reader.load_frame(seq, clone=False)))
    return series


def archive_filetime(directory, state=None):
    manifest = {}
    path = Path(directory) / 'manifest.json' if directory else None
    if path is not None and path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding='utf8'))
        except (OSError, json.JSONDecodeError, TypeError):
            manifest = {}
    filetime = (manifest.get('process') or {}).get('creation_filetime')
    if filetime is None:
        filetime = ((state or {}).get('identity') or {}).get('creation_filetime')
    return filetime


def round_closed_at(directory, seq, phase):
    """True when this frame is the last stored frame of its year/season/round."""
    if not directory or not isinstance(seq, int):
        return False
    want = comparable_phase(phase)
    if want is None:
        return False
    idx = Path(directory) / 'index.json'
    if not idx.is_file():
        return False
    try:
        index = json.loads(idx.read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    match = None
    for row in index.get('rounds') or []:
        if comparable_phase(row) == want:
            match = row
    last = (match or {}).get('last_seq')
    return isinstance(last, int) and seq >= last


def collect_prestige_commands(directory, until_seq=None):
    """One pass over archive frames. Cached beside the collection journal when that folder exists."""
    from game_archive import ArchiveReader
    path = str(Path(directory).resolve())
    with ArchiveReader(directory) as reader:
        count = reader.frame_count()
        filetime = archive_filetime(directory)
        cache_path = None
        if filetime is not None:
            folder = default_root() / str(filetime)
            if folder.is_dir():
                cache_path = folder / 'prestige-commands.json'
        key = (path, count)
        if _PRESTIGE.get('key') == key and 'hires' in _PRESTIGE:
            commands = _PRESTIGE['commands']
        else:
            cached = _read_prestige_cache(cache_path, count)
            if cached is None:
                commands, hires = _scan_prestige_commands(reader)
                _write_prestige_cache(cache_path, count, commands, hires)
            else:
                commands, hires = cached
            _PRESTIGE['key'] = key
            _PRESTIGE['commands'] = commands
            _PRESTIGE['hires'] = hires
    if isinstance(until_seq, int):
        commands = [item for item in commands if (item.get('seq') or 0) <= until_seq]
    return commands


def collect_hire_classes(directory, until_seq=None):
    """募将 is status 9 this season; 自动加入 is a same-frame wild-to-active change."""
    collect_prestige_commands(directory, until_seq)
    rows = list(_PRESTIGE.get('hires') or [])
    if isinstance(until_seq, int):
        rows = [item for item in rows if (item.get('seq') or 0) <= until_seq]
    return rows


def _read_prestige_cache(path, frame_count):
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if payload.get('frame_count') != frame_count or 'hires' not in payload:
        return None
    commands, hires = payload.get('commands'), payload.get('hires')
    if not isinstance(commands, list) or not isinstance(hires, list):
        return None
    return commands, hires


def _write_prestige_cache(path, frame_count, commands, hires):
    if path is None:
        return
    try:
        path.write_text(json.dumps({
            'frame_count': frame_count,
            'commands': commands,
            'hires': hires,
        }, ensure_ascii=False), encoding='utf8')
    except OSError:
        return


def _prestige_view(lord):
    """Copy the fields the next in-place frame would overwrite."""
    lord = lord or {}
    slots = ((lord.get('hand_cards') or {}).get('slots') or [])
    cards = []
    for slot in slots:
        if isinstance(slot, dict) and slot.get('card_id') is not None:
            cards.append({'card_id': slot.get('card_id')})
    rel = lord.get('diplomacy_relations')
    phase_rel = list(rel) if isinstance(rel, list) else []
    return {
        'force_id': lord.get('force_id'),
        'name': lord.get('name'),
        'prestige': lord.get('prestige'),
        'hand_cards': {'slots': cards},
        'diplomacy_relations': phase_rel,
    }


def _hire_event(gid, name, owner, status, city_id, previous, phase, seq, seen):
    if seq <= 1 or not previous or not isinstance(owner, int) or owner == 65535:
        return None
    old_owner, old_status = previous
    key = (owner, gid)
    if status == 9 and old_status != 9 and key not in seen:
        seen.add(key)
        return {'kind': '募将', 'force_id': owner, 'general_id': gid, 'name': name,
                'city_id': city_id, 'phase': phase, 'seq': seq}
    if status == 0 and old_status == 1 and old_owner != owner and key not in seen:
        return {'kind': '自动加入', 'force_id': owner, 'general_id': gid, 'name': name,
                'city_id': city_id, 'phase': phase, 'seq': seq}
    return None


def _scan_prestige_commands(reader):
    previous = None
    generals = {}
    recruited = set()
    found = []
    hires = []
    for seq in range(1, reader.frame_count() + 1):
        state = reader.load_frame(seq, clone=False)
        lords = [_prestige_view(lord) for lord in (state.get('entities') or {}).get('lords') or []]
        phase = state.get('phase_candidate')
        phase = dict(phase) if isinstance(phase, dict) else None
        if previous is not None:
            for item in prestige_command_ops(previous, lords):
                found.append({**item, 'seq': seq, 'phase': phase})
        previous = lords
        for general in (state.get('entities') or {}).get('generals') or []:
            gid = general.get('general_id_raw')
            if gid is None:
                continue
            owner, status = general.get('owner_raw'), general.get('status_code')
            event = _hire_event(
                gid, general.get('name'), owner, status, general.get('location_city_id'),
                generals.get(gid), phase, seq, recruited,
            )
            if event:
                hires.append(event)
            generals[gid] = (owner, status)
    return found, hires


def replay_command_history(directory, seq):
    from replay_view import ReplayCursor, clip_history
    path = str(Path(directory).resolve())
    cursor = _REPLAY.get('cursor')
    if _REPLAY.get('path') != path or cursor is None:
        if cursor is not None:
            cursor.close()
        cursor = ReplayCursor(path)
        _REPLAY['path'] = path
        _REPLAY['cursor'] = cursor
    cursor.ensure_ledger(seq if isinstance(seq, int) else cursor.frame_count())
    history = clip_history({
        'quarters': cursor._history.get('quarters'),
        'current_quarter': cursor._current,
        'events': cursor._events,
    }, cursor._ready)
    history.pop('events', None)
    history['source'] = 'replay'
    return history


def attach_frame_history(state, directory=None, until_seq=None, journal_root=None):
    doc = copy.deepcopy(state) if state else {}
    try:
        from force_troop_totals import append_troop_series, troop_series_point
        series = troop_series_from_archive(directory, until_seq=until_seq) if directory else []
        series = append_troop_series(series, troop_series_point(doc))
    except Exception:
        series = []
    history = dict(doc.get('history') or {})
    history['troop_series'] = series
    phase = doc.get('phase_candidate')
    ledger = load_journal_history(
        archive_filetime(directory, doc), phase,
        include_same_phase=round_closed_at(directory, until_seq, phase),
        root=journal_root,
    )
    if ledger is None and directory:
        try:
            ledger = replay_command_history(directory, until_seq)
        except Exception:
            ledger = None
    if ledger:
        history['quarters'] = ledger.get('quarters') or []
        history['current_quarter'] = ledger.get('current_quarter')
        history['recent_changes'] = ledger.get('recent_changes') or []
        if directory:
            try:
                merge_prestige_commands(history, collect_prestige_commands(directory, until_seq))
                annotate_hire_kinds(history, collect_hire_classes(directory, until_seq))
            except Exception:
                pass
        if ledger.get('source') == 'journal':
            history['banner'] = '只读历史。变化列出到这一帧的各季内政和军事。1v1 信望上涨按布施，同盟少绿卡且对方信望上升按赠绿卡。不是引擎日志。'
        else:
            history['banner'] = '只读历史。变化和人才由相邻帧推断，只到这一帧。不是引擎日志。'
    else:
        history['banner'] = '只读历史。没有找到这局的逐季指令账，变化和人才先空着。'
    doc['history'] = history
    return doc


def attach_last_frame_history(state, directory=None):
    return attach_frame_history(state, directory)


def review_archive(archive, root=None, seq=None):
    if archive is None:
        raise ValueError('没有可选取的历史回放存档。')
    if isinstance(archive, (str, Path)):
        directory = Path(archive)
        target = directory.resolve() if directory.exists() else directory
        lookup = root or directory.parent
        row = next((item for item in list_archives(lookup)
                    if Path(item['directory']).resolve() == target
                    or Path(item['directory']) == directory), None)
        if row is None:
            row = {'directory': str(directory)}
    else:
        row = archive
        directory = row.get('directory')
        if not directory:
            raise ValueError('没有可选取的历史回放存档。')
    nodes = archive_time_nodes(directory)
    if seq is None and nodes:
        seq = nodes[-1]['seq']
    bundle = load_archive_frame(directory, seq)
    matches = [item['label'] for item in nodes if item['seq'] == bundle['seq']]
    label = matches[-1] if matches else None
    if bundle['seq'] == bundle['frame_count']:
        label = '末帧'
    bundle['node_label'] = label or f"帧{bundle['seq']}"
    bundle['archive'] = row
    bundle['state'] = attach_frame_history(bundle['state'], directory, until_seq=bundle['seq'])
    return bundle


def review_bundle(root=None, live_match_id=None, now=None):
    archive = previous_archive(root, live_match_id=live_match_id, now=now)
    if archive is None:
        raise ValueError('没有可选取的历史回放存档。')
    return review_archive(archive, root=root)


def status_line(bundle):
    manifest = (bundle or {}).get('manifest') or {}
    state = (bundle or {}).get('state') or {}
    title = manifest.get('title') or manifest.get('match_id') or '未标题'
    phase = phase_label(state.get('phase_candidate'))
    seq = bundle.get('seq') or 0
    count = bundle.get('frame_count') or 0
    node = bundle.get('node_label') or ('末帧' if seq == count else f'帧{seq}')
    return f'只读历史 · {node} {seq}/{count} · {title} · {phase}'
