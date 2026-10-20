"""Local display cache for source-bound original commands and sampling dates.

Not a game snapshot, replay, identity confirmation, or training action source.
Original packet journals are never changed. A restored cache remains offline.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from command_display import retain_calendars
from command_effects import retain_effects, valid_change
from scout_location import retain_locations, valid_reference
from command_personnel import retain_personnel, valid_personnel
from command_construction import retain_construction, valid_construction
from command_phase_values import retain_phase_values, valid_phase_value
from native_command_evidence import ROOT, MAX_LINE, MAX_ROWS, SANPK_BUILD, _accept, decode

SCHEMA = 'retained-command-view-1'
MAX_CACHE = 4 * 1024 * 1024


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _legacy_decode(row, decoded):
    """Recognize only the exact pre-312 trade/construction interpretation.

    Called after original journal/hash validation. All wire operands and all
    other decoded fields must still match; arbitrary relabeling is rejected.
    """
    if decoded['native_type'] != 18:
        return False
    if decoded['subtype'] == 4:
        if (row.get('action') != '买米' or 'target_xy_raw' in row
                or 'base_value_semantics' in row):
            return False
        derived = {'action', 'target_xy_raw', 'base_value_semantics'}
    elif decoded['subtype'] == 3:
        if row.get('action') != '卖米' or decoded['parameter_raw'] == 0:
            return False
        derived = {'action'}
    else:
        return False
    return all(row.get(k) == v for k, v in decoded.items() if k not in derived)


class CommandViewStore:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.last = None
        self.signature = None
        self.disk_stamp = None

    def path(self, source):
        return self.root / 'command-view-cache' / (hashlib.sha256(source.encode()).hexdigest()[:20] + '.json')

    def save(self, data):
        """Atomic derived cache only; callers supply verified native evidence."""
        raw = json.dumps(dict(data=data, sha256=_digest(data)), ensure_ascii=False).encode()
        if len(raw) > MAX_CACHE:
            raise ValueError('command display cache too large')
        path = self.path(data['source_id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        # A local GUI and the read-only HTTP exporter may save concurrently.
        # Each owns its temporary file; atomic replace never steals another's.
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
            temp=Path(handle.name);handle.write(raw)
        try:temp.replace(path)
        finally:temp.unlink(missing_ok=True)
        self.last = deepcopy(data)
        stat=path.stat();self.disk_stamp=(stat.st_ino,stat.st_mtime_ns,stat.st_size)

    def remember(self, payload, commands):
        state = payload.get('state') or {}
        bound = commands.get('binding') or {}
        if (payload.get('fresh') is not True or payload.get('error')
                or bound.get('source_id') != payload.get('source_id')):
            return commands
        if self.last is None or self.last.get('source_id') != payload['source_id']:
            self.load(payload['source_id'])
        else:
            # The GUI and HTTP exporter have independent readers. Reload an
            # atomically replaced cache before merging a partial/empty batch.
            try:
                stat=self.path(payload['source_id']).stat()
                if self.disk_stamp != (stat.st_ino,stat.st_mtime_ns,stat.st_size):
                    self.last=None;self.load(payload['source_id'])
            except FileNotFoundError:
                pass
        merged = deepcopy(commands)
        if self.last and self.last.get('binding') == bound:
            # Cold-start batches must not erase previously verified evidence.
            # Same entry+payload across recoveries stays one observation group.
            known = {}
            old_commands = self.last['native_command_evidence']
            for row in list(old_commands['rows']) + list(merged.get('rows') or []):
                key = row.get('queue_entry_hex') or row['source_line_sha256'], row['raw_sha256']
                previous = known.get(key)
                if previous is None or row['observed_at'] < previous['observed_at']:
                    known[key] = deepcopy(row)
            all_rows = sorted(known.values(), key=lambda r:r['observed_at'])
            merged['rows'] = all_rows[-MAX_ROWS:]
            for key in ('errors','unsupported','gaps','omitted_rows'):
                merged[key] = max(merged.get(key,0), old_commands.get(key,0))
            merged['omitted_rows'] += max(0,len(all_rows)-MAX_ROWS)
        enriched = retain_calendars(merged, state.get('history'), state.get('snapshot_id'))
        enriched = retain_effects(enriched, state.get('history'))
        # Existing dated rows survive a history window being pruned or reset.
        if self.last and self.last.get('binding') == bound:
            known = {r['source_line_sha256']: r for r in self.last['native_command_evidence']['rows']}
            for row in enriched['rows']:
                old = known.get(row['source_line_sha256']) or {}
                before, after = old.get('sampling_calendar') or {}, row.get('sampling_calendar') or {}
                same = all(before.get(k) == after.get(k) for k in ('year_u16', 'season_u16'))
                if before and old.get('observed_at') == row.get('observed_at') and (not after or same):
                    row['sampling_calendar'] = deepcopy(before)
                if not row.get('state_changes') and old.get('observed_at') == row.get('observed_at'):
                    row['state_changes'] = [deepcopy(c) for c in old.get('state_changes', []) if valid_change(row,c)]
                if valid_reference(row, old.get('scout_reference'), bound):
                    row['scout_reference'] = deepcopy(old['scout_reference'])
                if valid_personnel(row, old.get('personnel_reference'), bound):
                    row['personnel_reference'] = deepcopy(old['personnel_reference'])
                if valid_construction(row, old.get('construction_reference'), bound):
                    row['construction_reference'] = deepcopy(old['construction_reference'])
                if not row.get('phase_changes'):
                    row['phase_changes'] = [deepcopy(v) for v in old.get('phase_changes', []) if valid_phase_value(row,v,bound)]
        enriched = retain_locations(enriched, state)
        enriched = retain_personnel(enriched, state)
        enriched = retain_construction(enriched, state)
        enriched = retain_phase_values(enriched, state.get('history'))
        actors = {r['actor_force_id'] for r in enriched['rows']}
        targets = {r.get('target_raw') for r in enriched['rows'] if r.get('native_type')==20 and r.get('subtype')!=0}
        generals = (state.get('entities') or {}).get('generals', [])
        names = {}
        for gid in targets:
            matches = [g.get('name') for g in generals if g.get('general_id_raw')==gid and g.get('name')]
            if len(matches)==1:names[str(gid)]=matches[0]
        if not generals and self.last and self.last.get('binding')==bound:
            names=deepcopy(self.last.get('general_names') or {})
        data = dict(schema=SCHEMA, source_id=payload['source_id'], binding=deepcopy(bound),
                    general_names=names,
                    selected_force_id=state.get('player_force_id'),
                    force_names={str(f['force_id']): f.get('name') or str(f['force_id'])
                                 for f in (state.get('entities') or {}).get('lords', []) if f.get('force_id') in actors},
                    native_command_evidence=enriched)
        signature = _digest(data)
        if signature != self.signature:
            self.save(data)
            self.signature = signature
        return enriched

    def load(self, source, remote=False):
        if remote:
            return None
        if self.last and self.last.get('source_id') == source:
            try:
                stat=self.path(source).stat()
                if self.disk_stamp == (stat.st_ino,stat.st_mtime_ns,stat.st_size):
                    return self._offline(self.last)
            except FileNotFoundError:
                pass
            self.last=None
        path = self.path(source)
        try:
            if path.stat().st_size > MAX_CACHE:
                return None
            wrapper = json.loads(path.read_bytes())
            data = wrapper['data']; bound = data['binding']
            if (wrapper['sha256'] != _digest(data) or data.get('schema') != SCHEMA
                    or data.get('source_id') != source or bound.get('source_id') != source
                    or bound.get('build') != SANPK_BUILD):
                return None
            rows = data['native_command_evidence']['rows']
            if not rows or len(rows) > MAX_ROWS:
                return None
            # Validate against retained original journal lines, not cache labels.
            folder = hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest()[:20]
            migrated = False
            for row in rows:
                relative = Path(row['source_file'])
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != folder:
                    return None
                with (self.root / 'native-payload-observations' / relative).open('rb') as stream:
                    offset = row['source_byte_offset']
                    if type(offset) is not int or offset < 0:
                        return None
                    stream.seek(offset); line = stream.readline(MAX_LINE + 1)
                if len(line) > MAX_LINE or hashlib.sha256(line).hexdigest() != row['source_line_sha256']:
                    return None
                event = json.loads(line)
                raw, _ = _accept(event, bound)
                decoded = decode(raw)
                if (event['captured_at'] != row['observed_at']
                        or event['raw_sha256'] != row['raw_sha256'] or event['raw_hex'] != row['raw_hex']):
                    return None
                legacy = False
                if any(row.get(k) != v for k, v in decoded.items()):
                    if not _legacy_decode(row, decoded):
                        return None
                    legacy = migrated = True
                    row.update(decoded)
                if 'queue_entry_hex' in row and row['queue_entry_hex'] != event['entry_hex']:
                    return None
                row['queue_entry_hex'] = event['entry_hex']
                if 'scout_reference' in row and not valid_reference(row,row['scout_reference'],bound):
                    return None
                if 'personnel_reference' in row and not valid_personnel(row,row['personnel_reference'],bound):
                    return None
                if 'construction_reference' in row and not valid_construction(row,row['construction_reference'],bound):
                    return None
                if legacy:
                    # The old mapping correlated construction with rice. Drop
                    # only obsolete, otherwise-valid legacy correlations. Gold
                    # stays an observed stage net, never a per-command result.
                    old_metrics_row = dict(row, subtype=3, parameter_raw=1)
                    row['state_changes'] = [c for c in row.get('state_changes') or [] if valid_change(row,c)]
                retained_values = []
                for value in row.get('phase_changes') or []:
                    if valid_phase_value(row,value,bound):
                        retained_values.append(value)
                    elif not (legacy and valid_phase_value(old_metrics_row,value,bound)):
                        return None
                if legacy:
                    row['phase_changes'] = retained_values
            if migrated:
                self.save(data)
            self.last = data
            stat=path.stat();self.disk_stamp=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
            return self._offline(data)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None

    @staticmethod
    def _offline(data):
        result = deepcopy(data)
        result['retained_only'] = True
        result['native_command_evidence']['capture_status'] = {'phase': 'waiting', 'error': 'offline'}
        return result
