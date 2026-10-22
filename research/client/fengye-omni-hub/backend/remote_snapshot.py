"""One-shot remote reader; optionally search through an existing relay.
optionally writes one hub control request for a running p34 probe.

Executed with `python3 -` over SSH. No login, room join, memory writes,
trigger writes, or persistent process. Only --search sends a normal room query.
Only --control writes a single validated request file for the probe to poll.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


def json_file(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def json_lines(path, cap=131072):
    try:
        with path.open('rb') as f:
            size = path.stat().st_size
            head = f.read(min(size, cap))
            if size > cap:
                f.seek(max(cap, size - cap))
                tail = f.read(cap)
            else:
                tail = b''
        rows = []
        seen = set()
        for line in (head + b'\n' + tail).splitlines():
            try:
                row = json.loads(line)
                key = line
                if isinstance(row, dict) and key not in seen:
                    rows.append(row)
                    seen.add(key)
            except ValueError:
                pass
        return rows
    except OSError:
        return []


def processes():
    result = []
    raw = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True)
    names = {'p21_orchestrate.py': 'orchestrator', 'p25_orchestrate.py': 'orchestrator',
             'p29_receive_orchestrate.py': 'orchestrator', 'p34_d8_orchestrate.py': 'orchestrator',
             'p42_prestart_d8_run.py': 'orchestrator',
             'p1_directed_probe.py': 'driver', 'p2_loader_host.py': 'relay',
             'p39c2_loader_host.py': 'relay',
             'p20_cmd2_verified_probe.py': 'ghost', 'p24_cmd2_featureless_probe.py': 'ghost',
             'p28_receive_probe.py': 'ghost', 'p34_d8_probe.py': 'ghost',
             'p42_prestart_d8_probe.py': 'ghost', 'p43_prestart_d8_probe.py': 'ghost',
             'fengye_hub_room_probe.py': 'session',
             # 2026-10-21 sticky：大廳不動，只有狀態讀取（大廳階段）與每局採集器。
             'shadow_status.py': 'driver', 'shadow_session_rec.py': 'driver',
             'p4_host_watch.py': 'watch', 'p33_host_watch.py': 'watch'}
    for line in raw.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        argv = [a.strip('"') for a in shlex.split(parts[2], posix=False)]
        scripts = [Path(a.replace('\\', '/')).name for a in argv]
        role = next((names[n] for n in scripts if n in names), None)
        if not role:
            continue
        row = {'pid': int(parts[0]), 'parent_pid': int(parts[1]), 'role': role}
        for flag, key in (('--line', 'line'), ('--target', 'target'), ('--session-name', 'session')):
            if flag in argv and argv.index(flag) + 1 < len(argv):
                row[key] = argv[argv.index(flag) + 1]
        result.append(row)
    return result


def latest_run(lab):
    """Pick the newest chain pointer inside evidence/ (p42/p34 first, legacy kept).

    Returns (run_path, pointer_state, pointer_source). A pointer only selects
    which run directory is read; freshness is judged from the run's own data.
    """
    root = (lab / 'evidence').resolve()
    found = []
    for source in ('p42-prestart-d8-20261016', 'p34-d8-invisible-20261015',
                   'p27-start-preflight-20261015'):
        active = json_file(lab / 'evidence' / source / 'active-run.json', {})
        evidence = active.get('evidence')
        if not evidence:
            continue
        candidate = Path(evidence).resolve()
        if root not in candidate.parents:
            continue
        wall = active.get('wall')
        found.append((wall if isinstance(wall, (int, float)) else 0, candidate,
                      active.get('state'), source))
    if found:
        found.sort(key=lambda item: item[0])
        _, candidate, state, source = found[-1]
        return candidate, state, source
    return (lab / 'evidence/p20-verified-restart-20261014').resolve(), None, 'legacy_fallback'


def collector_path(run, identity):
    # Identity is evidence, not permission to read an arbitrary file. Reject
    # absolute paths, traversal and symlinks escaping this specific run.
    name = identity.get('collector_log', 'p20_live.jsonl')
    if name not in ('p20_live.jsonl', 'p28_live.jsonl', 'p34_live.jsonl', 'p42_live.jsonl'):
        return None
    path = (run / name).resolve()
    return path if path.parent == run.resolve() else None


def counter(rows, key, fallback=0):
    values = [r[key] for r in rows if isinstance(r.get(key), int)
              and not isinstance(r[key], bool) and r[key] >= 0]
    return max(values) if values else fallback


def start_snapshot_faction(logs):
    """Return only named row facts from the latest complete cmd7 snapshot.

    Missing/unmatched data never means an unbound member. ID and freshness
    are checked separately by the local presenter against the host watch.
    """
    complete = [r for r in logs if r.get('ev') == 'received_packet'
                and isinstance(r.get('object'), dict) and r['object'].get('cmd') == 7
                and r['object'].get('class_name') == 'CSanInetInitGameData'
                and isinstance(r.get('snapshot'), dict)
                and isinstance(r['snapshot'].get('rows'), list)
                and len(r['snapshot']['rows']) == 8
                and isinstance(r.get('length'), int)
                and r['snapshot'].get('consumed') == r['length']]
    if not complete:
        return {}
    packet = complete[-1]
    rows = [r for r in packet['snapshot']['rows'] if isinstance(r, dict)
            and isinstance(r.get('name_e'), dict)
            and r['name_e'].get('gbk_display') == '风夜']
    if len(rows) != 1:
        return {}
    row = rows[0]
    binding = row.get('binding46')
    if not isinstance(binding, int) or isinstance(binding, bool) or not -1 <= binding <= 0xffffffff:
        return {}
    # The wire decoder preserves DWORDs unsigned; native -1 is the sentinel.
    if binding == 0xffffffff:
        binding = -1
    label = (row.get('text4c') or {}).get('gbk_display')
    return {'observed_at': packet.get('wall'), 'member_id': row.get('id'),
            'binding46': binding, 'faction_name': label if isinstance(label, str) else None,
            'source': 'cmd7_snapshot'}


P34_FRAME_CAP = 80
CONTROL_TEXT_MAX = 120


def write_control(lab, payload):
    """Write one hub control request into the current p34 run directory.

    Validates the payload, requires a running p34 probe, and atomically
    replaces hub-control.json. This function never executes game actions; the
    probe polls the file and applies once-only semantics by request id.
    """
    if not isinstance(payload, dict):
        return {'error': 'bad_payload'}
    rid = payload.get('id')
    if not isinstance(rid, str) or not 0 < len(rid) <= 64:
        return {'error': 'bad_id'}
    op = payload.get('op')
    request = {'id': rid, 'op': op}
    if op == 'chat':
        text = payload.get('text')
        if not isinstance(text, str) or not 0 < len(text) <= CONTROL_TEXT_MAX:
            return {'error': 'bad_text'}
        try:
            text.encode('gbk')
        except UnicodeEncodeError:
            return {'error': 'text_not_gbk'}
        request['text'] = text
    elif op != 'stop':
        return {'error': 'unknown_op'}
    run, state, source = latest_run(lab)
    if not ((run / 'p34_live.jsonl').exists() or (run / 'p42_live.jsonl').exists()):
        return {'error': 'no_p34_run'}
    try:
        raw = subprocess.check_output(['ps', '-axo', 'command='], text=True)
    except (OSError, subprocess.SubprocessError):
        return {'error': 'ps_unavailable'}
    if all(name not in raw for name in ('p34_d8_probe.py', 'p42_prestart_d8_probe.py',
                                        'p43_prestart_d8_probe.py')):
        return {'error': 'probe_not_running'}
    path = run / 'hub-control.json'
    temp = run / 'hub-control.json.tmp'
    temp.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)
    return {'status': 'sent', 'id': rid, 'op': op, 'run': run.name}


def p34_binding(value):
    """Wire decoder keeps DWORDs unsigned; native -1 is the unbound sentinel."""
    return -1 if value == 0xffffffff else value


def p34_snapshot_block(packet):
    rows = []
    for row in (packet.get('snapshot') or {}).get('rows', []):
        if not isinstance(row, dict):
            continue
        rows.append({'i': row.get('index'), 'id': row.get('id'), 'w4': row.get('w4'),
                     'name': (row.get('name_e') or {}).get('gbk_display'),
                     'state42': row.get('state42'),
                     'binding46': p34_binding(row.get('binding46')),
                     'faction': (row.get('text4c') or {}).get('gbk_display')})
    return {'observed_at': packet.get('wall'),
            'cmd': (packet.get('object') or {}).get('cmd'), 'rows': rows}


def p34_chat_text(raw_hex):
    """Best-effort text from a type-3 local-delivery payload; never invented.

    Live sample (2026-10-16, run-115248): the payload is the GBK message plus
    trailing NUL bytes (b'hi\\x00'). Wire-shaped frames carry the text after
    the all-ones broadcast marker. Unknown shapes return None, never a guess.
    """
    try:
        data = bytes.fromhex(str(raw_hex or ''))
    except ValueError:
        return None
    candidates = []
    stripped = data.rstrip(b'\x00')
    if stripped:
        candidates.append(stripped)
    idx = data.find(b'\xff\xff\xff\xff')
    if idx >= 0 and idx + 4 < len(data):
        tail = data[idx + 4:].split(b'\x00')[0]
        if tail:
            candidates.append(tail)
    for tail in candidates:
        if not 0 < len(tail) <= 160:
            continue
        try:
            text = tail.decode('gbk')
        except UnicodeDecodeError:
            continue
        if text.strip() and all(ch.isprintable() or ch == '\u3000' for ch in text):
            return text
    return None


def p34_intel(run, identity, logs, pointer_state, pointer_source):
    """Bounded read-only digest of one p34 run for the local hub.

    Reads only files already inside the run directory plus the loaded log.
    Raw payloads are truncated to one display line; process pointers and
    machine paths are never collected.
    """
    summary = json_file(run / 'summary.json', {}) or {}
    registration = json_file(run / 'registration-receipt.json', {}) or {}
    gate = json_file(run / 'register-gate.json', {}) or {}
    fakeexit = json_file(run / 'fakeexit-effect.json', {}) or {}
    sent = json_file(run / 'd8-sent-receipt.json', {}) or json_file(run / 'p42-d8-sent.json', {}) or {}
    effect = json_file(run / 'd8-effect.json', {}) or {}
    withdrawn = json_file(run / 'host-withdrawn.json', {}) or {}
    control_result = json_file(run / 'hub-control-result.json', {}) or {}
    control_request = json_file(run / 'hub-control.json', {}) or {}
    frames = []
    chat_messages = []
    snapshots = {'initial': None, 'start': None}
    sync_nonempty = []
    notifications = {}
    sync_rounds = 0
    d8_enter = d8_return = cmd1_ack = None
    health = None
    listen_started = None
    for row in logs:
        ev = row.get('ev')
        if ev == 'received_packet':
            obj = row.get('object') or {}
            frames.append({'wall': row.get('wall'), 'type': row.get('type'),
                           'cmd': obj.get('cmd'), 'cls': obj.get('class_name'),
                           'len': row.get('length'),
                           'sha8': str(row.get('sha256') or '')[:12]})
            snap = row.get('snapshot')
            if (isinstance(snap, dict) and len(snap.get('rows') or []) == 8
                    and snap.get('consumed') == row.get('length')
                    and obj.get('class_name') == 'CSanInetInitGameData'
                    and obj.get('cmd') in (3, 7)):
                block = p34_snapshot_block(row)
                if obj.get('cmd') == 3:
                    snapshots['initial'] = block
                else:
                    snapshots['start'] = block
            if row.get('type') == 3:
                message = p34_chat_text(row.get('raw_hex'))
                if message:
                    chat_messages.append({'wall': row.get('wall'), 'text': message,
                                          'sender': row.get('sender')})
        elif ev == 'sync_round_complete':
            sync_rounds += 1
        elif ev == 'native_slot_observed':
            inner = row.get('inner') or {}
            control = inner.get('control') or {}
            slot_kind = control.get('control_cmd')
            if slot_kind == 3:
                sync_rounds += 1
            elif slot_kind == 5:
                slot_records = []
                for record in control.get('records') or []:
                    if not isinstance(record, dict):
                        continue
                    raw_hex = str(record.get('raw_hex') or '')
                    try:
                        sha8 = hashlib.sha256(bytes.fromhex(raw_hex)).hexdigest()[:12]
                    except ValueError:
                        sha8 = None
                    slot_records.append({'sender': record.get('sender'),
                                         'len': record.get('length'), 'sha8': sha8,
                                         'raw': raw_hex[:240]})
                if slot_records:
                    sync_nonempty.append({'wall': row.get('wall'), 'round': inner.get('seq'),
                                          'records': slot_records})
        elif ev == 'sync_batch_accepted' and row.get('count'):
            records = [{'sender': r.get('sender'), 'len': r.get('length'),
                        'sha8': str(r.get('sha256') or '')[:12],
                        'raw': str(r.get('raw_hex') or '')[:240]}
                       for r in row.get('records', []) if isinstance(r, dict)]
            sync_nonempty.append({'wall': row.get('wall'), 'round': row.get('round'),
                                  'records': records})
        elif ev == 'notification':
            key = row.get('message')
            notifications[key] = notifications.get(key, 0) + 1
        elif ev in ('d8_send_enter', 'd8_prestart_send_enter'):
            d8_enter = row
        elif ev in ('d8_send_return', 'd8_prestart_send_return'):
            d8_return = row
        elif ev == 'cmd1_ack_observed':
            cmd1_ack = row
        elif ev == 'send_return' and row.get('label') == 'cmd1' and cmd1_ack is None:
            cmd1_ack = row
        elif ev == 'health_sample':
            health = {k: row.get(k) for k in
                      ('wall', 'connected', 'packets', 'release_calls', 'receiver_errors',
                       'tx_seq', 'native_state', 'd8_seconds', 'last_activity_age',
                       'observe_remaining', 'log_bytes')}
        elif ev == 'passive_listen_started':
            listen_started = row.get('wall')
    # 2026-10-16：聊天補發言者——用開局快照（cmd3/cmd7）的 id→名對照解析。
    seat_names = {}
    for key in ('start', 'initial'):
        block = snapshots.get(key) or {}
        for seat in block.get('rows') or []:
            if seat.get('id') and seat.get('name'):
                seat_names[seat.get('id')] = seat.get('name')
    for message in chat_messages:
        message['sender_name'] = seat_names.get(message.get('sender'))
    d8_wall = (d8_return or {}).get('wall') or sent.get('wall')
    if not isinstance(d8_wall, (int, float)):
        d8_wall = None
    cmd1_wall = (cmd1_ack or {}).get('wall')
    if not isinstance(cmd1_wall, (int, float)):
        cmd1_wall = None
    observe = identity.get('observe_seconds')
    anchor = d8_wall if d8_wall is not None else cmd1_wall
    end_wall = (anchor + observe) if anchor is not None and isinstance(observe, (int, float)) else None
    received_after_d8 = None
    if d8_wall is not None:
        received_after_d8 = sum(1 for f in frames if isinstance(f.get('wall'), (int, float))
                                and f['wall'] >= d8_wall)
    trims = frames[-P34_FRAME_CAP:]
    last = trims[-1] if trims else {}
    return {
        'run_name': run.name,
        'pointer_state': pointer_state,
        'pointer_source': pointer_source,
        'registration_verified': bool(summary.get('registered_verified')) or bool(registration.get('own_id')),
        'registered': {'own_id': (registration.get('own_id') or sent.get('own_id')
                                  or gate.get('own_id')),
                       'machine_name': registration.get('machine_name') or next(
                           (r.get('machine_name') for r in logs if r.get('ev') == 'start_enter'), None),
                       'w4': (registration.get('row') or {}).get('w4'),
                       'row_state': (registration.get('row') or {}).get('state'),
                       'pending_2723': (registration.get('row') or {}).get('pending_2723')},
        'fakeexit': {'P_state': fakeexit.get('P_state'),
                     'observed_wall': fakeexit.get('observed_wall')},
        'd8': {'sent_once': sum(1 for r in logs
                                if r.get('ev') in ('d8_send_return', 'd8_prestart_send_return')) == 1,
               'sent_wall': d8_wall,
               'body_hex': (d8_enter or {}).get('body_hex') or (d8_enter or {}).get('raw_hex'),
               'raw_rc': (d8_return or sent).get('raw_rc'),
               'mapped_rc': (d8_return or {}).get('mapped_rc'),
               'target': (d8_return or {}).get('target'),
               'effect': ({'row_present': effect.get('row_present'),
                           'unknown': effect.get('unknown'),
                           'observed_wall': effect.get('observed_wall')} if effect else None),
               'withdrawn': ({'observed_wall': withdrawn.get('observed_wall'),
                              'consecutive_absent_samples': withdrawn.get('consecutive_absent_samples')}
                             if withdrawn else None)},
        'window': {'anchor_wall': anchor, 'observe_seconds': observe,
                   'end_wall': end_wall,
                   'anchored_by': 'd8' if d8_wall is not None else ('cmd1' if cmd1_wall is not None else None)},
        'longrun': {'long_run': bool(identity.get('long_run')),
                    'health_seconds': identity.get('health_seconds'),
                    'tail_seconds': identity.get('tail_seconds'),
                    'listen_started_wall': listen_started,
                    'health': health,
                    'end_reason': summary.get('end_reason'),
                    'tail_recorded': bool(summary.get('post_exit_tail_written'))},
        'counters': {'received': len(frames),
                     'released': counter(logs, 'release_calls'),
                     'errors': counter(logs, 'receiver_errors',
                                       sum(1 for r in logs if r.get('ev') == 'receiver_error')),
                     'rounds': sync_rounds,
                     'received_after_d8': received_after_d8,
                     'last_packet_wall': last.get('wall'),
                     'last_packet_cmd': last.get('cmd')},
        'snapshots': snapshots,
        'frames': trims,
        'sync': {'rounds': sync_rounds, 'nonempty': sync_nonempty[-40:]},
        'notifications': {'wm_event': notifications.get(34048, 0),
                          'wm_data': notifications.get(34049, 0),
                          'wm_chat': notifications.get(34050, 0)},
        'control': {
            'last_result': ({'id': control_result.get('id'), 'op': control_result.get('op'),
                             'rc': control_result.get('rc'), 'wall': control_result.get('wall'),
                             'chars': control_result.get('chars')}
                            if isinstance(control_result.get('id'), str) else None),
            'pending': ({'id': control_request.get('id'), 'op': control_request.get('op')}
                        if isinstance(control_request.get('id'), str)
                        and control_request.get('id') != control_result.get('id') else None),
            'events': [{'ev': r.get('ev'), 'wall': r.get('wall'),
                        'request_id': r.get('request_id'), 'text': r.get('text'),
                        'rc': r.get('rc'), 'reason': r.get('reason')}
                       for r in logs if str(r.get('ev', '')).startswith('control_')][-8:],
        },
        'chat': {'wm_chat_count': notifications.get(34050, 0),
                 'type3_frames': sum(1 for f in frames if f.get('type') == 3),
                 'messages': chat_messages[-10:]},
    }


def hub_session(lab):
    """The hub's own current session pointer; only this session is shown.

    Older research runs (evidence/…/active-run.json) are deliberately not
    consulted: the live views must reflect the game the user is currently in.
    """
    home = (lab / 'fengye-hub-session').resolve()
    pointer = json_file(home / 'active.json', {}) or {}
    directory = pointer.get('directory')
    if not isinstance(directory, str) or not directory:
        return None
    path = Path(directory).resolve()
    if home not in path.parents or not path.is_dir():
        return None
    return {'path': path, 'pointer': pointer}


def status_block(session):
    """Read the shadow's status.json (written by shadow_status.py).

    Raw fields only: the presenter turns them into player-facing words.
    Missing or stale files stay None instead of being backfilled.
    """
    raw = json_file(session['path'] / 'status.json', None)
    if not isinstance(raw, dict):
        return None
    wall = raw.get('wall')
    raw['age'] = round(time.time() - wall, 1) if isinstance(wall, (int, float)) else None
    return raw


def session_intel(session, chain):
    """Current-session digest in the same shape the hub presenter expects.

    Reads only this session's own records: state.json (the probe's own session
    state) and packets.jsonl (what this session actually received). Missing
    observations stay unknown; nothing is backfilled from other runs.
    """
    path = session['path']
    pointer = session['pointer']
    state = json_file(path / 'state.json', {}) or {}
    packets = json_lines(path / 'packets.jsonl', cap=512 * 1024)
    packets.sort(key=lambda r: r.get('wall', 0))
    frames = []
    chat_messages = []
    snapshots = {'initial': None, 'start': None}
    sync_nonempty = []
    notifications = {}
    sync_rounds = 0
    d8_body = None
    for row in packets:
        ev = row.get('ev')
        if ev == 'received_packet':
            obj = row.get('object') or {}
            frames.append({'wall': row.get('wall'), 'type': row.get('type'),
                           'cmd': obj.get('cmd'), 'cls': obj.get('class_name'),
                           'len': row.get('length'),
                           'sha8': str(row.get('sha256') or '')[:12]})
            snap = row.get('snapshot')
            if (isinstance(snap, dict) and len(snap.get('rows') or []) == 8
                    and snap.get('consumed') == row.get('length')
                    and obj.get('class_name') == 'CSanInetInitGameData'
                    and obj.get('cmd') in (3, 7)):
                block = p34_snapshot_block(row)
                if obj.get('cmd') == 3:
                    snapshots['initial'] = block
                else:
                    snapshots['start'] = block
            if row.get('type') == 3:
                message = p34_chat_text(row.get('raw_hex'))
                if message:
                    chat_messages.append({'wall': row.get('wall'), 'text': message,
                                          'sender': row.get('sender')})
        elif ev == 'native_slot_observed':
            inner = row.get('inner') or {}
            control = inner.get('control') or {}
            slot_kind = control.get('control_cmd')
            if slot_kind == 3:
                sync_rounds += 1
            elif slot_kind == 5:
                slot_records = []
                for record in control.get('records') or []:
                    if not isinstance(record, dict):
                        continue
                    raw_hex = str(record.get('raw_hex') or '')
                    try:
                        sha8 = hashlib.sha256(bytes.fromhex(raw_hex)).hexdigest()[:12]
                    except ValueError:
                        sha8 = None
                    slot_records.append({'sender': record.get('sender'),
                                         'len': record.get('length'), 'sha8': sha8,
                                         'raw': raw_hex[:240]})
                if slot_records:
                    sync_nonempty.append({'wall': row.get('wall'), 'round': inner.get('seq'),
                                          'records': slot_records})
        elif ev == 'notification':
            key = row.get('message')
            notifications[key] = notifications.get(key, 0) + 1
        elif ev == 'd8_enter':
            d8_body = row.get('body_hex')
    # 聊天補發言者——用本局開局快照（cmd3/cmd7）的 id→名對照解析。
    seat_names = {}
    for key in ('start', 'initial'):
        block = snapshots.get(key) or {}
        for seat in block.get('rows') or []:
            if seat.get('id') and seat.get('name'):
                seat_names[seat.get('id')] = seat.get('name')
    # 2026-10-17：沒有開局快照時的聊天名字回退——房主 ID → 房間列表中的房主名、
    # 本端 ID → 暱稱；有快照時快照優先（setdefault 不覆蓋）。
    _ch = state.get('channel') or {}
    _sel = state.get('selected_room') if isinstance(state.get('selected_room'), dict) else {}
    if _ch.get('host_id') and isinstance(_sel.get('host'), str) and _sel.get('host'):
        seat_names.setdefault(_ch['host_id'], _sel['host'])
    if _ch.get('own_id') and isinstance(state.get('nickname'), str) and state.get('nickname'):
        seat_names.setdefault(_ch['own_id'], state['nickname'])
    for message in chat_messages:
        message['sender_name'] = seat_names.get(message.get('sender'))
    channel = state.get('channel') or {}
    register = state.get('register') or {}
    d8 = state.get('d8') or {}
    selected = state.get('selected_room') if isinstance(state.get('selected_room'), dict) else {}
    last_result = state.get('last_result') if isinstance(state.get('last_result'), dict) else {}
    room_query = state.get('room_query') if isinstance(state.get('room_query'), dict) else {}
    room_query_out = None
    if room_query.get('observed_at') is not None or room_query.get('rooms'):
        # 本局會話自己的查房結果（SearchSession through owned relay），
        # 不再顯示其他局或歷史快取的房間列表。
        room_query_out = {'observed_at': room_query.get('observed_at'),
                          'rooms': room_query.get('rooms') if isinstance(room_query.get('rooms'), list) else [],
                          'query_status': room_query.get('status') if isinstance(room_query.get('status'), str) else 'unconfirmed_empty',
                          'rc': room_query.get('rc'),
                          'source': 'session SearchSession（本局會話自己的查房）',
                          'line_verified': False,
                          'error': room_query.get('error')}
    observed = state.get('observed_at') if isinstance(state.get('observed_at'), (int, float)) else None
    d8_sent = bool(state.get('ghost_withdrawn') and d8)
    d8_wall = d8.get('wall') if (d8_sent and isinstance(d8.get('wall'), (int, float))) else None
    received_after_d8 = None
    if d8_wall is not None:
        received_after_d8 = sum(1 for f in frames if isinstance(f.get('wall'), (int, float))
                                and f['wall'] >= d8_wall)
    received = state.get('received') if isinstance(state.get('received'), int) else len(frames)
    released = state.get('released') if isinstance(state.get('released'), int) else None
    errors = state.get('receiver_errors') if isinstance(state.get('receiver_errors'), int) else None
    last = frames[-1] if frames else {}
    alive = any(isinstance(row, dict) and row.get('role') == 'driver'
                and row.get('pid') == pointer.get('pid') for row in chain)
    fresh = bool(alive and observed is not None and 0 <= time.time() - observed <= 20)
    control_events = []
    for row in packets:
        if row.get('ev') == 'room_control_result':
            control_events.append({'ev': 'room_control_result', 'wall': row.get('wall'),
                                   'text': row.get('op'), 'rc': row.get('rc'),
                                   'reason': row.get('detail') or row.get('error')})
    event_rows = []
    for row in packets[-20:]:
        ev = row.get('ev')
        if ev == 'received_packet':
            event_rows.append({'ev': 'received_packet', 'wall': row.get('wall'),
                               'cmd': (row.get('object') or {}).get('cmd')})
        elif ev == 'room_control_result':
            event_rows.append({'ev': 'roomctl:' + str(row.get('op')), 'wall': row.get('wall'),
                               'rc': row.get('rc')})
    return {
        'run_name': path.name,
        'pointer_state': pointer.get('state'),
        'pointer_source': 'hub_session',
        'registration_verified': bool(state.get('ghost_registered')),
        'registered': {'own_id': channel.get('own_id'),
                       'machine_name': register.get('machine_name'),
                       'w4': None, 'row_state': None, 'pending_2723': None},
        'fakeexit': {},
        'd8': {'sent_once': d8_sent, 'sent_wall': d8_wall,
               'body_hex': d8_body if d8_sent else None,
               'raw_rc': d8.get('raw_rc') if d8_sent else None,
               'target': d8.get('target') if d8_sent else None,
               'fast': bool(d8.get('fast')) if d8_sent else False,
               'effect': None, 'withdrawn': None},
        'window': {'anchor_wall': d8_wall, 'observe_seconds': None, 'end_wall': None,
                   'anchored_by': 'd8' if d8_wall is not None else None},
        'longrun': {},
        'counters': {'received': received, 'released': released, 'errors': errors,
                     'rounds': sync_rounds, 'received_after_d8': received_after_d8,
                     'last_packet_wall': last.get('wall'), 'last_packet_cmd': last.get('cmd')},
        'snapshots': snapshots,
        'frames': frames[-P34_FRAME_CAP:],
        'sync': {'rounds': sync_rounds, 'nonempty': sync_nonempty[-40:]},
        'notifications': {'wm_event': notifications.get(34048, 0),
                          'wm_data': notifications.get(34049, 0),
                          'wm_chat': notifications.get(34050, 0)},
        'control': {'last_result': ({'id': last_result.get('id'), 'op': last_result.get('op'),
                                     'rc': last_result.get('rc'),
                                     'wall': last_result.get('wall')}
                                    if isinstance(last_result.get('id'), str) else None),
                    'pending': None,
                    'events': control_events[-8:]},
        'chat': {'wm_chat_count': notifications.get(34050, 0),
                 'type3_frames': sum(1 for f in frames if f.get('type') == 3),
                 'messages': chat_messages[-10:]},
        'live_probe': False,
        'session': {'alive': alive, 'fresh': fresh,
                    'phase': state.get('phase') if isinstance(state.get('phase'), str) else 'unknown',
                    'connected': bool(state.get('connected')),
                    'nickname': state.get('nickname') if isinstance(state.get('nickname'), str) else None,
                    'room_name': selected.get('session_name') if isinstance(selected.get('session_name'), str) else None,
                    'virtual_ip': selected.get('virtual_ip') if isinstance(selected.get('virtual_ip'), str) else None,
                    'room_id': selected.get('room_id') if isinstance(selected.get('room_id'), str) else None,
                    'ghost_registered': bool(state.get('ghost_registered')),
                    'ghost_withdrawn': bool(state.get('ghost_withdrawn')),
                    'host_init_wait': bool(state.get('host_init_wait')),
                    'exit_seen_wall': state.get('exit_seen_wall') if isinstance(state.get('exit_seen_wall'), (int, float)) else None,
                    'observed_at': observed,
                    'started_at': pointer.get('started_at') if isinstance(pointer.get('started_at'), (int, float)) else None,
                    'driver_pid': pointer.get('pid'),
                    'line': pointer.get('line') if isinstance(pointer.get('line'), str) else None,
                    'error': state.get('error') if isinstance(state.get('error'), str) else None},
        'events': event_rows,
        'member_names': {str(key): value for key, value in seat_names.items()},
        'start_snapshot_faction': start_snapshot_faction(packets),
        'room_query': room_query_out,
        'source_sha256': state.get('binary_sha256') if isinstance(state.get('binary_sha256'), dict) else {},
    }


def search_existing_relay(lab, chain):
    drivers = [p for p in chain if p['role'] == 'driver']
    relays = [p for p in chain if p['role'] == 'relay']
    ghosts = [p for p in chain if p['role'] == 'ghost']
    if len(drivers) != 1 or len(relays) != 1 or len(ghosts) != 1:
        return {'error': '需唯一的现有风夜中继链；未重新登录', 'query_status': 'unavailable'}
    if drivers[0].get('line') != '多线3' or relays[0]['parent_pid'] != drivers[0]['pid']:
        return {'error': '当前中继线路未核实为多线3；未执行搜索', 'query_status': 'unavailable'}
    rt = json_file(Path.home() / 'Library/Application Support/SGI-Wine/runtime.json', {})
    prefix = Path.home() / 'Library/Application Support/SGI-Wine/prefix-monitor'
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG='-all',
               DYLD_FALLBACK_LIBRARY_PATH=rt.get('dependency_lib', ''))
    command = [rt['wine'], str(lab / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8',
               str(lab / 'koeinm_probe.py'), '--dll', r'C:\sgi\run-3.5\3I\Koeinm.dll',
               '--target', '255.255.255.255', '--port', '7777', '--app-id', '78731', '--with-nethook']
    try:
        proc = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        results = [json.loads(s) for s in proc.stdout.splitlines() if s.startswith('{')]
        result = next((r for r in reversed(results) if 'query_status' in r), {})
        if proc.returncode or result.get('start_rc') != 0 or result.get('search_rc') != 0:
            return {'error': '现有中继搜索未成功；未重登或加入房间', 'query_status': 'unavailable'}
        return {'observed_at': result.get('observed_at'), 'line': '多线3',
                'query_status': result['query_status'], 'rooms': result.get('rooms', []),
                'source': 'SearchSession through existing relay', 'opensession_join': False,
                'line_verified': True}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return {'error': '现有中继搜索超时或不可用；未重新登录', 'query_status': 'unavailable'}


def snapshot(lab, search=False):
    """Read only the hub's current session; absent data stays absent.

    Legacy research runs are never consulted here: the views must reflect the
    game the user is currently in, and nothing else (2026-10-17 user
    requirement). Every key below is always present so the local presenter can
    distinguish "no session" from "old cached payload".
    """
    chain = processes()
    session = hub_session(lab)
    session_block = None
    p34_payload = None
    session_room_query = None
    ghost_log = {}
    events = []
    member_names = {}
    host = {}
    run_name = None
    source_sha256 = {}
    status = None
    line = next((p.get('line') for p in chain if p.get('role') == 'driver'), None)
    if session:
        digest = session_intel(session, chain)
        session_block = digest.pop('session')
        events = digest.pop('events')
        member_names = digest.pop('member_names')
        source_sha256 = digest.pop('source_sha256')
        start_faction = digest.pop('start_snapshot_faction')
        session_room_query = digest.pop('room_query')
        p34_payload = digest
        counters = p34_payload.get('counters') or {}
        host = {'virtual_ip': session_block.get('virtual_ip'),
                'session': session_block.get('room_name'),
                'source': 'hub_session',
                'observed_at': session_block.get('observed_at')}
        ghost_log = {
            'mode': 'hub_room_session',
            'registration': 'verified' if session_block.get('ghost_registered') else 'unknown',
            'last_log_at': session_block.get('observed_at'),
            'packet_count': counters.get('received'),
            'release_calls': counters.get('released'),
            'receiver_errors': counters.get('errors'),
            'last_packet_at': counters.get('last_packet_wall'),
            'last_cmd': counters.get('last_packet_cmd'),
            'watchdog_started_at': None, 'cmd23_attempts': None, 'cmd23_returns': None,
            'cmd9_attempts': None, 'cmd9_returns': None, 'start_command_received_at': None,
            'start_snapshot': start_faction, 'automatic_ready': False,
        }
        run_name = p34_payload.get('run_name')
        status = status_block(session)
        line = session_block.get('line') or line
    else:
        driver = next((p for p in chain if p.get('role') == 'driver'), {})
        if driver.get('target') and driver.get('session'):
            host = {'virtual_ip': driver.get('target'), 'session': driver.get('session'),
                    'source': 'current_driver', 'observed_at': time.time()}
    queried_at = time.time()
    payload = {'queried_at': queried_at, 'source_kind': 'remote_readonly',
               'host_watch': None, 'activity': {}, 'member_names': member_names,
               'chain': chain, 'ghost_log': ghost_log, 'events': events[-20:],
               'p34': p34_payload, 'session': session_block, 'status': status,
               'host': host, 'line': line,
               'run_name': run_name, 'source_sha256': source_sha256}
    if search and session is None:
        payload['room_query'] = search_existing_relay(lab, chain)
    else:
        # 房間列表同樣只綁定當前會話自己的查房結果；沒有會話就不顯示。
        payload['room_query'] = session_room_query if session else None
    return payload


if __name__ == '__main__':
    try:
        lab = Path.home() / 'sgi-protocol-lab-20260915'
        control = next((a for a in sys.argv[1:] if a.startswith('--control=')), None)
        if control is not None:
            payload = json.loads(base64.urlsafe_b64decode(control.split('=', 1)[1]).decode('utf-8'))
            print(json.dumps(write_control(lab, payload), ensure_ascii=False))
        else:
            print(json.dumps(snapshot(lab, '--search' in sys.argv), ensure_ascii=False))
    except Exception as exc:
        # Exception messages can contain command data. Return only its type.
        print(json.dumps({'error': '远端状态读取失败', 'error_type': type(exc).__name__}))
        sys.exit(2)
