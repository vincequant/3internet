"""Immutable, per-force modification provenance, separate from replay frames.

Intent is saved before the first mutation. It is conservative evidence of a
possible modification, not proof that a command succeeded or the peer synced.
Unmarked archives are not certified clean. Opponent actions remain reference
material; interaction with a modified force can still affect them.
"""
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = frozenset(('extend', 'alms', 'infantry', 'cavalry', 'bow', 'auto_x3'))
SIDECAR = 'modification-evidence-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     allow_nan=False).encode('utf8')).hexdigest()


def identity_key(identity):
    return (identity.get('pid'), identity.get('creation_filetime'),
            ntpath.normcase(identity.get('path') or ''))


def context(payload):
    state = payload.get('state') or {}
    meta = state.get('player_identity') or {}
    fid = state.get('player_force_id')
    if (type(fid) is not int or meta.get('status') != 'confirmed'
            or meta.get('force_id') != fid or not meta.get('session_id')):
        raise ValueError('无法确认本局我方势力，未执行修改')
    forces = [r for r in (state.get('entities') or {}).get('lords', []) if r.get('force_id') == fid]
    if len(forces) != 1:
        raise ValueError('本局势力身份不唯一，未执行修改')
    return dict(source_id=payload['source_id'], process=payload['identity'],
                game_build=state['build_sha256'], core_address=state['core_address'],
                player_session_id=meta['session_id'], force_id=fid,
                force_name=forces[0].get('name') or str(fid))


def process_registry_path(ctx, root=ROOT):
    key = dict(source_id=ctx['source_id'], process=list(identity_key(ctx['process'])),
               game_build=ctx['game_build'])
    return Path(root) / 'modification-records' / digest(key)


def registry_path(ctx, root=ROOT):
    # Session IDs are capture identities, not proof of independent matches.
    return process_registry_path(ctx, root) / digest(ctx['player_session_id'])


def immutable_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf8')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('修改标记文件冲突')
        return
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        # Each name is an event UUID; reattaching identical events is harmless.
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()


def archive_path(value):
    if os.name != 'nt' and str(value).lower().startswith('z:\\'):
        return Path(str(value)[2:].replace('\\', '/'))
    return Path(value)


def matches(event, manifest, state):
    meta = state.get('player_identity') or {}
    return (event['source_id'] == manifest.get('source_id')
            and event['game_build'] == manifest.get('game_build')
            and identity_key(event['process']) == identity_key(manifest.get('process') or {})
            and event['player_session_id'] == meta.get('session_id')
            and event['force_id'] == state.get('player_force_id')
            and meta.get('status') == 'confirmed')


def attach(event, directory, manifest, state, frame):
    if not matches(event, manifest, state) or not frame.get('sha256'):
        return False
    # Bind supplementary evidence to one retained original frame, not a guess
    # based on PID alone. Never rewrite manifest/index/frames.
    doc = dict(event=event, event_sha256=digest(event), match_id=manifest['match_id'],
               source_frame_seq=frame['seq'], source_frame_sha256=frame['sha256'])
    path = Path(directory) / SIDECAR / (event['event_id'] + '.json')
    if path.exists(): return True
    immutable_json(path, doc)
    return True


def attach_pending(directory, manifest, state, frame, root=ROOT):
    meta = state.get('player_identity') or {}
    if not meta.get('session_id'): return
    ctx = dict(source_id=manifest.get('source_id'), process=manifest.get('process') or {},
               game_build=manifest.get('game_build'), player_session_id=meta['session_id'])
    for path in registry_path(ctx, root).glob('*.json'):
        event = json.loads(path.read_text(encoding='utf8'))
        attach(event, directory, manifest, state, frame)


def record_intent(bound, native_state, action, payload, native_force_id, root=ROOT, *, attach_archives=True):
    from quick_control_model import binding
    if action not in ACTIONS or payload.get('fresh') is not True or payload.get('error') or binding(payload) != bound:
        raise ValueError('修改来源与当前游戏实例不符，未执行修改')
    ctx = context(payload)
    if native_force_id != ctx['force_id'] or native_state['document'] != bound['core'] - 0x912:
        raise ValueError('修改目标势力或游戏对象改变，未执行修改')
    event = dict(schema_version=1, event_id=uuid.uuid4().hex, **ctx,
                 action=action, stage='before_mutation_intent', success=None,
                 recorded_at=datetime.now(timezone.utc).isoformat(),
                 capture_end=payload['state']['capture_end'], snapshot_id=payload['state'].get('snapshot_id'),
                 native_phase=native_state.get('phase'),
                 exclude_entire_replay=False, exclude_force_action_training=True)
    # If this fails, the native caller must abort before any write.
    immutable_json(registry_path(ctx, root) / (event['event_id'] + '.json'), event)
    attached = []
    if not attach_archives:
        # The recorder attaches the durable registry event with attach_pending
        # on its next frame. Do not scan growing archives inside a 1s deadline.
        return dict(kind='modification_recorded', event=event, attached_match_ids=[],
                    note=f'我方{ctx["force_name"]}已记录修改使用标记；回放将在下一采样帧关联。')
    from game_archive import ArchiveReader
    for key in ('replay_archive', 'training_archive'):
        status = payload.get(key) or {}
        if not status.get('recording') or not status.get('directory'): continue
        directory = archive_path(status['directory'])
        # Only local archive stores may receive supplementary files.
        allowed_roots={ (Path(root) / name).resolve() for name in ('game-archives', 'training-archives') }
        if Path(root)==ROOT:
            from game_archive import default_archive_root
            allowed_roots.add(default_archive_root().resolve())
        if directory.resolve().parent not in allowed_roots:
            raise ValueError('回放目录不属于本机，未执行修改')
        with ArchiveReader(directory, read_only=True) as reader:
            if reader.manifest.get('match_id') != status.get('match_id'):
                raise ValueError('当前回放身份改变，未执行修改')
            if reader.frames and attach(event, directory, reader.manifest,
                                         reader.load_frame(len(reader.frames)), reader.frames[-1]):
                attached.append(reader.manifest['match_id'])
    return dict(kind='modification_recorded', event=event, attached_match_ids=attached,
                note=f'我方{ctx["force_name"]}已记录修改使用标记；仅排除我方行动训练，对方保留参考。')


def summary(directory, reader=None, root=ROOT):
    from game_archive import ArchiveReader
    directory = Path(directory)
    manifest = reader.manifest if reader else json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
    ctx = dict(source_id=manifest.get('source_id'), process=manifest.get('process') or {},
               game_build=manifest.get('game_build'))
    if not (directory / SIDECAR).exists() and not process_registry_path(ctx, root).exists():
        return dict(schema_version=1, excluded_training_force_ids=[], modified_forces=[], event_count=0,
                    evidence_sha256=digest([]), evidence_errors=[manifest['modification_provenance_error']]
                    if manifest.get('modification_provenance_error') else [], scope='force_actions_entire_match',
                    exclude_entire_replay=False, opponent_reference_allowed=True, unmarked_means_clean=False,
                    success_or_peer_sync_proven=False)
    own_reader = reader is None
    reader = reader or ArchiveReader(directory, read_only=True)
    events, errors = {}, ([manifest['modification_provenance_error']]
                          if manifest.get('modification_provenance_error') else [])
    try:
        docs = []
        for path in (Path(directory) / SIDECAR).glob('*.json'):
            try:
                doc = json.loads(path.read_text(encoding='utf8')); event = doc['event']
                seq = doc['source_frame_seq']; frame = reader.meta(seq)
                reader._fh.seek(frame['offset'])
                actual_sha = hashlib.sha256(reader._fh.readline()).hexdigest()
                if (doc['event_sha256'] != digest(event) or doc['match_id'] != reader.manifest['match_id']
                        or doc['source_frame_sha256'] != frame.get('sha256')
                        or actual_sha != doc['source_frame_sha256']
                        or not matches(event, reader.manifest, reader.load_frame(seq))):
                    raise ValueError('修改标记来源不符')
                docs.append(event)
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                errors.append(str(error))
        # Old running collectors can continue without a restart. The immutable
        # local registry supplies marks until the new recorder attaches them.
        if reader.frames:
            for seq in {1, len(reader.frames)}:
                state = reader.load_frame(seq)
                meta = state.get('player_identity') or {}
                if not meta.get('session_id'): continue
                ctx = dict(source_id=reader.manifest.get('source_id'), process=reader.manifest.get('process') or {},
                           game_build=reader.manifest.get('game_build'), player_session_id=meta['session_id'])
                for path in registry_path(ctx, root).glob('*.json'):
                    try:
                        event = json.loads(path.read_text(encoding='utf8'))
                        if matches(event, reader.manifest, state): docs.append(event)
                    except (OSError, ValueError, KeyError, TypeError) as error: errors.append(str(error))
        for event in docs:
            if (event.get('schema_version') != 1 or event.get('action') not in ACTIONS
                    or type(event.get('force_id')) is not int
                    or event.get('exclude_force_action_training') is not True):
                errors.append('修改标记格式异常'); continue
            events[event['event_id']] = event
        forces = sorted({e['force_id'] for e in events.values()})
        names = {e['force_id']: e.get('force_name') or str(e['force_id']) for e in events.values()}
        return dict(schema_version=1, excluded_training_force_ids=forces,
                    modified_forces=[dict(force_id=fid, name=names[fid]) for fid in forces],
                    event_count=len(events), evidence_sha256=digest(sorted(events.values(), key=lambda e:e['event_id'])),
                    evidence_errors=errors, scope='force_actions_entire_match',
                    exclude_entire_replay=False, opponent_reference_allowed=True,
                    unmarked_means_clean=False, success_or_peer_sync_proven=False)
    finally:
        if own_reader: reader.close()


def training_policy(provenance, force_ids):
    excluded = provenance['excluded_training_force_ids']
    return dict(excluded_training_force_ids=excluded,
                reference_force_ids=[fid for fid in force_ids if fid not in excluded],
                exclude_entire_replay=False, opponent_reference_allowed=True,
                force_attribution_required_for_action_training=True,
                evidence_errors=provenance['evidence_errors'],
                note='Modified force actions are excluded for the whole match. Other forces remain reference material; clean/expert/native-action status is unproven.')


def require_training_force(provenance, force_id):
    if force_id is not None and type(force_id) is not int:
        raise ValueError('行动所属势力标识无效')
    if provenance['evidence_errors']:
        raise ValueError('修改标记证据异常，暂停行动训练导入')
    if provenance['excluded_training_force_ids'] and type(force_id) is not int:
        raise ValueError('有修改标记的回放必须确认行动所属势力')
    if force_id in provenance['excluded_training_force_ids']:
        raise ValueError('该势力使用过修改功能，排除本局我方行动训练样本')


def label(provenance):
    if provenance.get('evidence_errors'): return '修改标记证据异常，训练待核对'
    forces = provenance.get('modified_forces') or []
    if not forces: return ''
    return '我方' + '、'.join(f'{r["name"]}(势力{r["force_id"]})' for r in forces) + '使用过外挂；仅排除该势力行动训练，对方保留参考'


def current_label(payload, root=ROOT):
    ctx = context(payload)
    events = [json.loads(p.read_text(encoding='utf8')) for p in registry_path(ctx, root).glob('*.json')]
    if any(e.get('force_id') == ctx['force_id'] and e.get('action') in ACTIONS for e in events):
        return label({'modified_forces':[{'force_id':ctx['force_id'],'name':ctx['force_name']}]})
    return '本局暂无本程序修改标记；未标记不代表已验证干净。'
