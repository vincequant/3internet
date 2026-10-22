"""Read local parameter receipts without promoting them to committed orders.

Derived viewer data only: original panel logs and replay frames are untouched.
Each receipt requires an earlier source-bound modification intent in that file.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path

from replay_modifications import context, identity_key

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'infantry':'步兵训练', 'cavalry':'骑兵训练', 'bow':'弓兵训练', 'alms':'施舍'}
MAX_FILES = 16
MAX_BATCH = 1024 * 1024
MAX_ROWS = 256


def bound_matches(bound, ctx):
    try:
        if (not isinstance(ctx.get('process'),dict) or type(ctx.get('force_id')) is not int
                or type(bound['pid']) is not int or type(bound['created']) is not int):return False
        process = dict(pid=bound['pid'], creation_filetime=bound['created'], path=bound['image'])
        return (bound['source_id'] == ctx['source_id'] and bound['build'] == ctx['game_build']
                and identity_key(process) == identity_key(ctx['process'])
                and bound['core'] == int(str(ctx['core_address']), 0))
    except (KeyError, TypeError, ValueError):
        return False


def same_scope(first, second):
    return (all(first.get(k) == second.get(k) for k in
                ('source_id','game_build','core_address','player_session_id','force_id'))
            and identity_key(first.get('process') or {}) == identity_key(second.get('process') or {}))


class InputEvidenceReader:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else ROOT / 'quick-control-records'
        self.files = {}

    def _scan(self, path):
        stat = path.stat(); key = (stat.st_dev, stat.st_ino)
        item = self.files.get(path)
        if item is None or item['key'] != key or stat.st_size < item['offset']:
            item = dict(key=key, offset=0, bound=None, scope=None, rows=[], errors=0, omitted=0, skipping=False)
            self.files[path] = item
        with path.open('rb') as handle:
            handle.seek(item['offset']); raw = handle.read(MAX_BATCH)
        end = raw.rfind(b'\n') + 1
        if not end:
            if len(raw) == MAX_BATCH:
                item.update(offset=item['offset']+len(raw), bound=None, scope=None, skipping=True)
                item['errors'] += 1
            return item
        offset = item['offset']; item['offset'] += end
        for line in raw[:end].splitlines(keepends=True):
            at = offset; offset += len(line)
            if item['skipping']:
                item['skipping'] = False
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):raise ValueError('not an event')
            except (ValueError, UnicodeError):
                item.update(bound=None, scope=None); item['errors'] += 1; continue
            kind = row.get('kind')
            if kind in ('bound','ready'):
                item['bound'] = row.get('bound'); item['scope'] = None
            elif kind == 'modification_recorded':
                ctx = row.get('event') or {}
                if not isinstance(ctx,dict):
                    item['scope']=None;item['errors']+=1;continue
                item['scope'] = ctx if (ctx.get('action') == 'auto_x3'
                    and ctx.get('stage') == 'before_mutation_intent'
                    and bound_matches(item['bound'] or {}, ctx)) else None
            elif kind == 'auto_x3_operand' and item['scope']:
                action = row.get('action'); before = row.get('operand_before'); after = row.get('operand_after')
                hits = row.get('new_hits'); omitted = row.get('omitted_intermediate_operands')
                if (action not in LABELS or type(before) is not int or type(after) is not int
                        or type(hits) is not int or not 1 <= hits <= 0xffffffff
                        or type(omitted) is not int or omitted != hits-1):
                    item['errors'] += 1; continue
                valid = (0 <= before <= 4 and after == (before+5)*3-5) if action == 'alms' else (
                    1 <= before <= 255 and after == before*3)
                try:stamp = datetime.fromisoformat(row['at'])
                except (KeyError, ValueError, TypeError):
                    item['errors'] += 1; continue
                if not valid or row.get('operand_verified') is not True or stamp.tzinfo is None:
                    item['errors'] += 1; continue
                item['rows'].append(dict(scope=dict(item['scope']), action=action, observed_at=row['at'],
                    operand_before=before, operand_after=after, new_hits=hits,
                    omitted_intermediate_operands=omitted, command_committed=None,
                    server_result_verified=False, source_file=path.name, source_byte_offset=at,
                    source_line_sha256=hashlib.sha256(line).hexdigest()))
                if len(item['rows']) > MAX_ROWS:
                    item['rows'].pop(0); item['omitted'] += 1
        return item

    def read(self, payload, remote=False):
        result = dict(status='unavailable', rows=[], complete_command_stream=False,
                      scope='local_auto_x3_input_parameters', errors=0, omitted_rows=0, files_limited=False)
        if remote:
            result['status'] = 'remote_not_imported'; return result
        try:
            if payload.get('fresh') is not True or payload.get('error'):return result
            current = context(payload)
            paths = sorted(self.folder.glob('[0-9]*.jsonl'))
            result['files_limited'] = len(paths) > MAX_FILES
            paths = paths[-MAX_FILES:]
            self.files = {p:item for p,item in self.files.items() if p in paths}
            for path in paths:
                try:item = self._scan(path)
                except OSError:
                    result['errors'] += 1; continue
                result['errors'] += item['errors']; result['omitted_rows'] += item['omitted']
                result['rows'].extend(r for r in item['rows'] if same_scope(r['scope'],current))
            result['rows'].sort(key=lambda r:(datetime.fromisoformat(r['observed_at']), r['source_file'], r['source_byte_offset']))
            if len(result['rows']) > MAX_ROWS:
                result['omitted_rows'] += len(result['rows'])-MAX_ROWS
                result['rows'] = result['rows'][-MAX_ROWS:]
            result['status'] = 'partial_local_input_evidence'
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            result['errors'] += 1
        return result


def input_line(row):
    stamp = datetime.fromisoformat(row['observed_at']).astimezone().strftime('%m-%d %H:%M:%S')
    before, after = row['operand_before'], row['operand_after']
    parameter = f'随机加值 {before+5}→{after+5}' if row['action']=='alms' else f'政治参数 {before}→{after}'
    missing = f'；另有{row["omitted_intermediate_operands"]}次参数未逐笔保留' if row['omitted_intermediate_operands'] else ''
    return f'{stamp}  {LABELS[row["action"]]}  {parameter}（×3） · 入队／结算未确认{missing}'
