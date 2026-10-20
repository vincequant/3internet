"""View-only recovery of frozen sortie stats from verified local archive frames.

The original ledgers/archives are never written. An appearance frame must match the
source process, core, build, timestamp, owner, unit ID, position and old display
name. The unit must be absent in the immediately preceding frame. No current
unit value, recycled ID or later appearance is used to fill an old instruction.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from native_command_evidence import _binding
from state_history import UNIT_FIELDS, general_names, unit_display


class SortieObservations:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[1])
        self.cache = {}
        self.windows = {}

    def attach(self, payload):
        if payload.get('fresh') is not True or not payload.get('state'):
            return payload
        try:
            bound = _binding(payload)
        except (KeyError, TypeError, ValueError):
            return payload
        history = payload['state'].get('history') or {}
        result = None
        accounts = list(history.get('quarters') or []) + [history.get('current_quarter')]
        for index, account in enumerate(accounts):
            if not account:
                continue
            for fi, force in enumerate(account.get('forces') or []):
                for oi, item in enumerate(force.get('operations') or []):
                    if item.get('field') != '出征' or item.get('unit_snapshot'):
                        continue
                    key = json.dumps([bound, account.get('from'), force.get('owner'), item], sort_keys=True)
                    recovered = self.cache.get(key)
                    if recovered is None:
                        recovered = self._find(bound, account, force.get('owner'), item)
                        if recovered:self.cache[key] = recovered
                    if not recovered:
                        continue
                    if result is None:
                        result = deepcopy(payload)
                    h = result['state']['history']
                    dest = h['quarters'][index] if index < len(history.get('quarters') or []) else h['current_quarter']
                    dest['forces'][fi]['operations'][oi].update(deepcopy(recovered))
        return result or payload

    def _find(self, bound, account, owner, item):
        target = item.get('target') or {}
        end, start = account.get('to'), account.get('from')
        if not end or not start or not start < end or target.get('unit_id') is None:
            return None
        window_key = json.dumps([bound, start, end], sort_keys=True)
        if window_key not in self.windows:
            self.windows[window_key] = self._scan(bound, start, end)
            if len(self.windows)>64:self.windows.pop(next(iter(self.windows)))
        hits = [h for h in self.windows[window_key]
                if h['unit_snapshot'].get('unit_id') == target['unit_id']
                and h['unit_snapshot'].get('owner_raw') == owner
                and h['unit_snapshot'].get('world_xy_raw') == target.get('world_xy_raw')
                and str(item.get('line') or '').startswith('出征 ' + h['display_name'] + ' ')]
        if hits and all(h['unit_snapshot'] == hits[0]['unit_snapshot'] and h['snapshot_id'] == hits[0]['snapshot_id'] for h in hits):
            return {k:v for k,v in hits[0].items() if k != 'display_name'}
        return None

    def _scan(self, bound, start, end):
        from game_archive import ArchiveReader
        hits = []
        for folder in ('game-archives', 'training-archives'):
            for manifest_path in (self.root / folder).glob('*/manifest.json'):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
                    process = manifest.get('process') or {}
                    if (manifest.get('source_id') != bound['source_id'] or
                        process.get('pid') != bound['pid'] or process.get('creation_filetime') != bound['created'] or
                        process.get('path') != bound['image']):
                        continue
                    with ArchiveReader(manifest_path.parent, read_only=True) as reader:
                        for meta in reader.frames:
                            if not start < str(meta.get('capture_end')) <= end or meta['seq'] <= 1:
                                continue
                            seq = meta['seq']
                            before = reader.load_frame(seq - 1, clone=False)
                            if _binding(dict(source_id=bound['source_id'], identity=before.get('identity'), state=before)) != bound:
                                continue
                            if not start <= str(before.get('capture_end')) < str(meta['capture_end']):
                                continue
                            old_ids = {u.get('unit_id') for u in (before.get('entities') or {}).get('field_units') or []}
                            frame = reader.load_frame(seq, clone=False)
                            if _binding(dict(source_id=bound['source_id'], identity=frame.get('identity'), state=frame)) != bound:
                                continue
                            units = (frame.get('entities') or {}).get('field_units') or []
                            for unit in units:
                                if unit.get('unit_id') is None or unit['unit_id'] in old_ids:
                                    continue
                                reader._fh.seek(meta['offset'])
                                line = reader._fh.readline()
                                hits.append(dict(display_name=unit_display(unit, general_names(frame)),
                                    unit_snapshot={k:deepcopy(unit[k]) for k in UNIT_FIELDS if k in unit},
                                    observed_at=frame['capture_end'], snapshot_id=frame.get('snapshot_id'),
                                    sortie_archive_reference=dict(archive=str(manifest_path.parent.relative_to(self.root)),
                                        seq=seq, record_sha256=hashlib.sha256(line).hexdigest(), binding=bound)))
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    continue
        return hits
