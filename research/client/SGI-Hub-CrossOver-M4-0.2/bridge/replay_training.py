"""Offline training provenance. Observed changes are never original commands."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def capture_profile(state, context=None):
    """The current collector reads state, not an all-force instruction stream."""
    state = state or {}
    context = context or {}
    forces = ((state.get('entities') or {}).get('lords') or [])
    return {
        'schema_version': 1, 'observation_mode': 'omniscient',
        'game_build_sha256': state.get('build_sha256'),
        'snapshot_id': state.get('snapshot_id'), 'capture_end': state.get('capture_end'),
        'coverage': state.get('coverage') or {},
        'synthetic': state.get('simulated') is True or context.get('synthetic') is True,
        'scenario': context.get('scenario'), 'computer': context.get('computer'),
        'ruleset_id': context.get('ruleset_id'),
        'ruleset_confirmed': context.get('ruleset_confirmed') is True,
        'original_instruction_stream_captured': False,
        'decision_boundary_confirmed': False,
        'per_force_instruction_coverage': [
            {'force_id': row['force_id'], 'coverage': 'not_captured',
             'raw_instruction_count': None, 'absence_means_no_command': False}
            for row in forces if type(row.get('force_id')) is int],
        'action_labels_from_state_differences_allowed': False,
        'formal_evaluation_eligible': False,
    }


def op_provenance(item):
    # Even a fact (e.g. pending ownership) is a state fact, not a captured input.
    return {'source': 'state_difference', 'native_instruction_captured': False,
            'action_training_eligible': False,
            'reason': 'No original input/decoded instruction witness is attached to this event.'}


def read_capture_config(root):
    """Machine-local opt-in; never part of the published source bundle."""
    path = Path(root) / 'training-capture.local.json'
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(doc, dict), 'training capture config must be an object')
    require(type(doc.get('enabled')) is bool, 'training capture enabled must be boolean')
    if not doc['enabled']:
        return None
    require(doc.get('observation_mode') == 'omniscient', 'unsupported training observation mode')
    require(type(doc.get('ruleset_confirmed')) is bool, 'explicit ruleset confirmation required')
    require(doc.get('computer') in (None, 'weak', 'normal', 'strong', 'unknown'), 'invalid computer level')
    for key in ('ruleset_id', 'scenario'):
        require(doc.get(key) is None or isinstance(doc[key], str), 'invalid training domain')
    require(not doc['ruleset_confirmed'] or bool(doc.get('ruleset_id')),
            'confirmed ruleset requires an identifier')
    return {k: doc.get(k) for k in ('observation_mode', 'ruleset_id', 'ruleset_confirmed', 'scenario', 'computer')}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def supplement(dataset, archive):
    """Attach hash-bound externally audited transitions; never amend old frames.

    Semantic verification remains the producer's responsibility. This importer
    verifies retained source hashes and game identity, not arbitrary witnesses.
    Such records are normal-input evidence, not all-force raw instruction logs.
    """
    dataset, archive = Path(dataset).resolve(), Path(archive).resolve()
    source = json.loads((dataset / 'manifest.json').read_text())
    manifest = json.loads((archive / 'manifest.json').read_text())
    from replay_modifications import summary, require_training_force
    provenance = summary(archive)
    require(source.get('schema_version') == 2
            and source.get('status') == 'audited_development_transitions_only'
            and source.get('formal_evaluation_eligible') is False, 'not an audited development dataset')
    require(manifest.get('simulated') is False, 'cannot attach real data to a simulated archive')
    require(sha(dataset / 'transitions.jsonl') == source['transitions_sha256'], 'transition hash mismatch')
    rows = [json.loads(line) for line in (dataset / 'transitions.jsonl').read_text().splitlines()]
    require(0 < len(rows) <= 1000 and len(rows) == source['accepted'] and len({r['sample_id'] for r in rows}) == len(rows),
            'transition count/duplicate mismatch')
    process = manifest.get('process') or {}
    for row in rows:
        require(row.get('synthetic') is False and row.get('observation_mode') == 'omniscient'
                and row.get('scope') == 'development_smoke_only'
                and row.get('formal_evaluation_eligible') is False, 'invalid transition scope')
        require(row['game_build_sha256'] == manifest['game_build'], 'archive build mismatch')
        require(row['task'] in ('recruit_ownership', 'wandering_transition'), 'unsupported audited task')
        require(len(row['evidence']) == (4 if row['task']=='recruit_ownership' else 3), 'missing source references')
        require(all(type(v) in (int, float) and math.isfinite(v) for v in row['features'].values()),
                'invalid transition features')
        for ref in row['evidence']:
            require(sha(ref['path']) == ref['sha256'], 'original evidence hash changed')
        proof = json.loads(Path(row['evidence'][1]['path']).read_text())
        episode = json.loads(Path(row['evidence'][2]['path']).read_text())
        cfg = episode['config']
        require_training_force(provenance, cfg.get('player_force_id'))
        require(episode.get('synthetic') is False and cfg['episode_id'] == row['episode_id']
                and cfg['game_id'] == row['game_id'] and cfg['game_build_sha256'] == row['game_build_sha256'],
                'source episode binding mismatch')
        identity = proof['ui_report']['inspector']['identity']
        require(identity['pid'] == process.get('pid')
                and identity['creation_filetime'] == process.get('creation_filetime')
                and identity['sha256'] == manifest['game_build'], 'archive process/build mismatch')
        require(proof.get('read_only') is True and proof.get('game_command_sent') is False,
                'outcome witness must be independent read-only evidence')
        binding = 'submission_sha256' if row['task']=='recruit_ownership' else 'transaction_sha256'
        require(proof.get(binding) == row['evidence'][0]['sha256'], 'outcome transaction binding mismatch')
        if row['task']=='recruit_ownership':
            require(proof.get('yes_mouse_receipt_verified') is True
                    and proof.get('paid_order_settlement_observed') is True
                    and proof.get('side_effect_unknown') is False, 'recruit outcome unresolved')
            value = row['outcome']['ownership_acquired']
            require(type(value) is int and value in (0,1), 'invalid ownership target')
            require((value==0 and proof.get('outcome')=='paid_attempt_no_hire'
                     and proof.get('recruitment_ownership_transition_verified') is False)
                    or (value==1 and proof.get('outcome') in ('hired','acquired_owner_not_standby')
                        and proof.get('recruitment_ownership_transition_verified') is True), 'target differs from outcome proof')
        else:
            require(proof.get('movement_verified') is True and proof.get('normal_input_receipt_verified') is True
                    and proof.get('phase_settlement_verified') is True
                    and row['outcome']['position_after']==proof['to_tile']
                    and row['outcome']['phase_after']==proof['phase_after'], 'movement outcome unresolved/mismatched')
        require(timestamp(proof.get('checked_at')) is not None, 'outcome timestamp missing')
    dest = archive / 'training-evidence-v1'
    dest.mkdir(exist_ok=False)
    (dest / 'transitions.jsonl').write_bytes((dataset / 'transitions.jsonl').read_bytes())
    report = {
        'format': 'sgi-external-audited-transitions-1', 'rows': len(rows),
        'source_manifest_sha256': sha(dataset / 'manifest.json'),
        'transitions_sha256': sha(dest / 'transitions.jsonl'),
        'proof_level': 'external_semantic_audit_with_source_hash_checks',
        'original_instruction_stream_captured': False,
        'formal_evaluation_eligible': False, 'original_frames_modified': False,
        'semantic_validator': 'research.ai.offline_training.transition_dataset',
        'source_references_portable': False,
    }
    write_json(dest / 'manifest.json', report)
    return report


def annotation_summary(archive, capture_end):
    """Only expose outcomes already observed by the selected replay timestamp."""
    dest = Path(archive) / 'training-evidence-v1'
    result = {'audited_transitions_available_at_cursor': 0,
              'native_instruction_count': 0, 'missing_or_changed_evidence': 0,
              'formal_evaluation_eligible': False}
    if not (dest / 'manifest.json').exists():
        return result
    manifest = json.loads((dest / 'manifest.json').read_text())
    require(manifest['format'] == 'sgi-external-audited-transitions-1'
            and sha(dest / 'transitions.jsonl') == manifest['transitions_sha256'], 'annotation hash mismatch')
    cutoff = timestamp(capture_end)
    if cutoff is None:
        return result
    for line in (dest / 'transitions.jsonl').read_text().splitlines():
        row = json.loads(line)
        try:
            require(all(sha(ref['path']) == ref['sha256'] for ref in row['evidence']), 'source changed')
            proof = json.loads(Path(row['evidence'][1]['path']).read_text())
            checked = timestamp(proof.get('checked_at'))
            require(checked is not None, 'outcome time unknown')
        except (OSError, ValueError, KeyError, TypeError):
            result['missing_or_changed_evidence'] += 1
            continue
        if checked <= cutoff:
            result['audited_transitions_available_at_cursor'] += 1
    return result


def export_observations(archive, destination, first=1, last=None, max_frames=250, force_id=None):
    """Frozen bounded state pairs for research, not inferred action labels."""
    from game_archive import ArchiveReader
    from replay_view import change_to_event
    from state_history import differences, slim
    archive = Path(archive).resolve()
    reader = ArchiveReader(archive, read_only=True)
    try:
        from replay_modifications import summary, training_policy, require_training_force
        provenance = summary(archive, reader)
        if force_id is not None:
            require_training_force(provenance, force_id)
        count = len(reader.frames)
        last = count if last is None else last
        require(type(first) is int and type(last) is int and 1 <= first < last <= count
                and type(max_frames) is int and 2 <= max_frames <= 1000
                and last - first + 1 <= max_frames, 'invalid/unbounded frame range')
        rows = []
        context = {**(reader.manifest.get('training_context') or {}),
                   'synthetic': reader.manifest.get('simulated') is True}
        for seq in range(first + 1, last + 1):
            before, after = reader.load_frame(seq - 1), reader.load_frame(seq)
            force_ids = [r['force_id'] for r in (before.get('entities') or {}).get('lords', [])
                         if type(r.get('force_id')) is int]
            if force_id is not None:
                require(force_id in force_ids, 'requested training force missing from replay')
            policy = training_policy(provenance, force_ids)
            before_time, after_time = timestamp(before.get('capture_end')), timestamp(after.get('capture_end'))
            require(before_time is not None and after_time is not None and before_time < after_time,
                    'unknown/reversed state chronology')
            require(before.get('build_sha256') == after.get('build_sha256')
                    and before.get('identity') == after.get('identity'), 'state identity/build changed')
            rows.append({'schema_version': 1, 'task': 'observational_state_transition',
                         'match_id': reader.manifest['match_id'], 'before_seq': seq - 1, 'after_seq': seq,
                         'before_frame_sha256': reader.frames[seq - 2].get('sha256'),
                         'after_frame_sha256': reader.frames[seq - 1].get('sha256'),
                         'observation_mode': 'omniscient', 'features': {'state_before': before},
                         'targets': {'observed_state_after': after},
                         'observed_changes': [change_to_event(d, seq, slim(after), slim(before))
                                              for d in differences(slim(before), slim(after))],
                         'action': None, 'action_label_known': False,
                         'single_action_causal_transition_verified': False,
                         'capture_profile': capture_profile(before, context),
                         'gap_risk': bool(reader.index.get('gaps')) or reader.manifest.get('started_mid_match') is True,
                         'formal_evaluation_eligible': False})
            # Audit metadata stays outside decision-time features. Original
            # observations remain intact for opponent/context reference.
            rows[-1]['training_force_policy'] = policy
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=False)
        (dest / 'observations.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows), encoding='utf-8')
        report = {'format': 'sgi-observational-training-export-1', 'archive': str(archive),
                  'match_id': reader.manifest['match_id'], 'pairs': len(rows), 'first_seq': first, 'last_seq': last,
                  'source_manifest_sha256_at_read': sha(archive / 'manifest.json'),
                  'observations_sha256': sha(dest / 'observations.jsonl'),
                  'action_label_count': 0, 'ruleset_confirmed': context.get('ruleset_confirmed') is True,
                  'formal_evaluation_eligible': False, 'game_command_sent': False,
                  'synthetic': reader.manifest.get('simulated') is True,
                  'source_open_at_export': reader.manifest.get('open'),
                  'modification_provenance': provenance,
                  'training_force_policy': policy,
                  'requested_reference_force_id': force_id,
                  'note': 'No expert, causal-action, reward or terminal labels inferred from state differences.'}
        write_json(dest / 'manifest.json', report)
        return report
    finally:
        reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    exp = modes.add_parser('export')
    exp.add_argument('archive', type=Path)
    exp.add_argument('output', type=Path)
    exp.add_argument('--first', type=int, default=1)
    exp.add_argument('--last', type=int)
    exp.add_argument('--max-frames', type=int, default=250)
    exp.add_argument('--force-id', type=int, help='reject a modified force; other forces remain reference only')
    attach = modes.add_parser('supplement')
    attach.add_argument('dataset', type=Path)
    attach.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        report = (supplement(args.dataset, args.archive) if args.mode == 'supplement'
                  else export_observations(args.archive, args.output, args.first, args.last, args.max_frames, args.force_id))
        print(json.dumps(report, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
