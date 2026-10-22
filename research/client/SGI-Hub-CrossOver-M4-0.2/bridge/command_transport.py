"""Source-verified packet records over the existing loopback/SSH read-only API.

No new listener, arbitrary file endpoint, game calls, or replay changes. Wire
rows carry the exact original line so the viewer rechecks binding, SHA and
operands independently. Sampling dates remain a source-derived display hint.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

from command_display import retain_calendars, sampling_calendar
from command_effects import valid_change, retain_effects
from scout_location import valid_reference
from command_personnel import valid_personnel
from command_construction import valid_construction
from command_phase_values import valid_phase_value
from native_command_evidence import (CommandEvidenceReader, ROOT, MAX_LINE,
                                     MAX_ROWS, _binding, _accept, decode)

SCHEMA = 'native-command-transfer-1'
MAX_TRANSFER = 2 * 1024 * 1024


def validate_row(row, binding, line):
    relative = Path(row['source_file'])
    folder = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:20]
    if (relative.is_absolute() or '..' in relative.parts or '\\' in row['source_file']
            or len(relative.parts) != 2 or relative.parts[0] != folder
            or type(row['source_byte_offset']) is not int or row['source_byte_offset'] < 0
            or not line.endswith(b'\n') or len(line) > MAX_LINE
            or hashlib.sha256(line).hexdigest() != row['source_line_sha256']):
        raise ValueError('original line provenance')
    event = json.loads(line)
    raw, _ = _accept(event, binding)
    decoded = decode(raw)
    if (event['captured_at'] != row['observed_at']
            or event['raw_sha256'] != row['raw_sha256'] or event['raw_hex'] != row['raw_hex']
            or any(row.get(k) != v for k, v in decoded.items())):
        raise ValueError('decoded record mismatch')
    result = dict(decoded, **{k:row[k] for k in ('source_file','source_byte_offset',
                  'source_line_sha256','raw_sha256','raw_hex','observed_at')},
                  evidence='native_queue_bytes',process_scope_only=True,repeated_command_count=None)
    if row.get('queue_entry_hex',event['entry_hex']) != event['entry_hex']:
        raise ValueError('queue entry mismatch')
    result['queue_entry_hex'] = event['entry_hex']
    calendar = sampling_calendar({'sampling_calendar':row.get('sampling_calendar')}, {})
    if calendar:
        result['sampling_calendar'] = dict(year_u16=calendar[0],season_u16=calendar[1],
                                          basis='sampling_time_correlation')
    changes = row.get('state_changes') or []
    if not isinstance(changes,list) or len(changes)>2 or any(not valid_change(result,c) for c in changes):
        raise ValueError('state correlation bounds')
    if changes:result['state_changes']=deepcopy(changes)
    if 'scout_reference' in row:
        if not valid_reference(result,row['scout_reference'],binding):
            raise ValueError('scout reference binding/bounds')
        result['scout_reference']=deepcopy(row['scout_reference'])
    if 'personnel_reference' in row:
        if not valid_personnel(result,row['personnel_reference'],binding):
            raise ValueError('personnel reference binding/bounds')
        result['personnel_reference']=deepcopy(row['personnel_reference'])
    if 'construction_reference' in row:
        if not valid_construction(result,row['construction_reference'],binding):
            raise ValueError('construction reference binding/bounds')
        result['construction_reference']=deepcopy(row['construction_reference'])
    values = row.get('phase_changes') or []
    if not isinstance(values,list) or len(values)>2 or any(not valid_phase_value(result,v,binding) for v in values):
        raise ValueError('phase value binding/bounds')
    if values:result['phase_changes']=deepcopy(values)
    return result


class SourceCommandExporter:
    def __init__(self, root=ROOT):
        from command_view_store import CommandViewStore
        self.root = Path(root)
        self.reader = CommandEvidenceReader(root)
        self.views = CommandViewStore(root)
        self.lock = threading.Lock()
        from sortie_observations import SortieObservations
        self.sorties = SortieObservations(root)
        self.sortie_lock = threading.Lock()

    def export(self, payload):
        with self.lock:
            commands = self.reader.read(payload)
            if commands.get('status') != 'partial_native_queue_evidence':
                return dict(schema=SCHEMA,status='unavailable',rows=[])
            try:
                commands = self.views.remember(payload, commands)
            except (OSError,ValueError):
                commands = retain_calendars(commands,(payload.get('state') or {}).get('history'))
            return self._transfer(commands)

    def _transfer(self, commands):
        result = {k:deepcopy(v) for k,v in commands.items() if k != 'rows'}
        result.update(schema=SCHEMA,rows=[])
        # Transfer newest evidence first within an explicit response budget.
        budget = 4096
        for row in reversed(commands['rows']):
            try:
                relative = Path(row['source_file'])
                if relative.is_absolute() or '..' in relative.parts or '\\' in row['source_file']:
                    raise ValueError('journal path')
                path = self.root/'native-payload-observations'/relative
                # No symlink may escape the source's packet journal directory.
                if not path.resolve().is_relative_to((self.root/'native-payload-observations').resolve()):
                    raise ValueError('journal path escape')
                with path.open('rb') as stream:
                    stream.seek(row['source_byte_offset']);line=stream.readline(MAX_LINE+1)
                exported = validate_row(row,commands['binding'],line)
                exported['source_line_b64'] = base64.b64encode(line).decode('ascii')
                size = len(json.dumps(exported,ensure_ascii=True).encode()) + 2
                if budget + size > MAX_TRANSFER:
                    result['omitted_rows'] += 1
                    continue
                budget += size;result['rows'].append(exported)
            except (OSError,ValueError,KeyError,TypeError):
                result['errors'] += 1
        result['rows'].reverse()
        return result

    def attach(self, payload):
        with self.sortie_lock:
            payload = self.sorties.attach(payload)
        result = dict(payload)
        if payload.get('state') and payload.get('fresh') is True:
            try:transfer = self.export(payload)
            except (OSError,ValueError,KeyError,TypeError):
                transfer = dict(schema=SCHEMA,status='unavailable',rows=[])
            result['state'] = dict(payload['state'],native_command_transfer=transfer)
        elif payload.get('source_id'):
            # Kept separate from live state: no fresh flag or player identity
            # is restored when a source game exits or collection disconnects.
            with self.lock:
                retained = self.views.load(payload['source_id'])
                if retained:
                    wire = {k:deepcopy(v) for k,v in retained.items()
                            if k in ('source_id','binding','force_names','general_names','selected_force_id')}
                    wire['native_command_evidence'] = self._transfer(retained['native_command_evidence'])
                    result['retained_command_transfer'] = wire
        return result


def import_retained(payload):
    """Offline remote view, verified originals but never a usable game state."""
    try:
        wire = payload.get('retained_command_transfer')
        if payload.get('fresh') is True or not isinstance(wire,dict):
            return None
        if len(json.dumps(wire,ensure_ascii=True).encode()) > MAX_TRANSFER + 65536:
            return None
        bound = wire['binding']; transfer = wire['native_command_evidence']
        from network_payloads import SANPK_BUILD
        if (wire['source_id'] != payload.get('source_id') or bound.get('source_id') != wire['source_id']
                or bound.get('build') != SANPK_BUILD or transfer.get('binding') != bound
                or transfer.get('schema') != SCHEMA or transfer.get('complete_command_stream') is not False
                or transfer.get('process_scope_only') is not True):
            return None
        rows = transfer['rows']
        if not isinstance(rows,list) or not 1 <= len(rows) <= MAX_ROWS:
            return None
        verified = []
        for row in rows:
            encoded = row['source_line_b64']
            if type(encoded) is not str or len(encoded)>((MAX_LINE+2)//3)*4:
                return None
            verified.append(validate_row(row,bound,base64.b64decode(encoded,validate=True)))
        names = {}
        for key, maximum in (('force_names',32),('general_names',512)):
            value = wire.get(key) or {}
            if not isinstance(value,dict) or len(value)>maximum or any(
                    not str(k).isdigit() or type(v) is not str or not 0<len(v)<=64 for k,v in value.items()):
                return None
            names[key] = deepcopy(value)
        evidence = {k:deepcopy(v) for k,v in transfer.items() if k not in ('rows','schema')}
        evidence.update(rows=verified,capture_status={'phase':'waiting','error':'offline'})
        return dict(source_id=wire['source_id'],binding=deepcopy(bound),retained_only=True,
                    selected_force_id=wire.get('selected_force_id'),native_command_evidence=evidence,**names)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return None


def import_commands(payload):
    result = dict(rows=[],complete_command_stream=False,process_scope_only=True,
                  status='remote_not_imported',errors=0,unsupported=0,gaps=0,
                  omitted_rows=0,files_limited=False,scan_pending=False)
    if payload.get('fresh') is not True or payload.get('error'):
        result['status']='remote_unavailable';return result
    transfer = (payload.get('state') or {}).get('native_command_transfer')
    if transfer is None:return result
    try:
        if (not isinstance(transfer,dict) or transfer.get('schema') != SCHEMA
                or len(json.dumps(transfer,ensure_ascii=True).encode()) > MAX_TRANSFER):
            raise ValueError('transfer schema/size')
        if transfer.get('status')=='unavailable':
            result['status']='remote_unavailable';return result
        binding = _binding(payload)
        if (transfer.get('binding') != binding
                or transfer.get('status') != 'partial_native_queue_evidence'
                or transfer.get('complete_command_stream') is not False
                or transfer.get('process_scope_only') is not True):
            raise ValueError('transfer source binding')
        rows=transfer['rows']
        if not isinstance(rows,list) or len(rows)>MAX_ROWS:
            raise ValueError('transfer rows')
        verified=[]
        for row in rows:
            encoded=row['source_line_b64']
            if type(encoded) is not str or len(encoded)>((MAX_LINE+2)//3)*4:
                raise ValueError('original line size')
            line=base64.b64decode(encoded,validate=True)
            verified.append(validate_row(row,binding,line))
        for key in ('errors','unsupported','gaps','omitted_rows'):
            value=transfer.get(key,0)
            if type(value) is not int or value<0:raise ValueError('transfer counter')
            result[key]=value
        for key in ('files_limited','scan_pending'):
            result[key]=transfer.get(key) is True
        result.update(status='partial_native_queue_evidence',binding=binding,rows=verified,
                      transport='source_verified_original_lines',
                      capture_status=deepcopy(transfer.get('capture_status') or {}))
        result = retain_effects(result, (payload.get('state') or {}).get('history'))
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        result.update(status='remote_invalid',errors=1,rows=[])
    return result
