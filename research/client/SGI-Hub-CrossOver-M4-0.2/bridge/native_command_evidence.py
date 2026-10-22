"""Decode retained, hash-checked native queue observations for the local viewer.

No target access, writes, input, replay edits, or action-training labels. The
queue's capture session is NOT a match. Re-observing retained bytes does not
prove another command; identical queue entries are grouped, with count unknown.
Layouts: SANPK 3.5 serializers 435a44, 436a6f, 436bba, 436d45.
"""
from datetime import datetime
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct

from network_payloads import SANPK_BUILD, KOEINM_SHA, DIRECTORY_NAME, is_supported_network_sha
from replay_modifications import identity_key

ROOT = Path(__file__).resolve().parents[1]
CLASSES = {'CSanInetDomesticCmd': (18, 29),
           'CSanInetDiplomacyCmd': (19, 44),
           'CSanInetPersonnelCmd': (20, 21),
           'CSanInetUnitNetCmdCreate': (16, 41)}
MAX_FILES = 128
MAX_TRACKED_FILES = 16384
MAX_BATCH = 4 * 1024 * 1024
MAX_LINE = 64 * 1024
MAX_ROWS = 512
# Verified menu -> map-click -> Domestic constructor chain in SANPK_BUILD.
# UI placement modes are NOT these serialized construction parameters.
CONSTRUCTION_ACTIONS = {4: '建火计', 5: '建落石', 6: '建陷阱',
                        7: '建练兵所', 8: '建牧场', 9: '建弓工坊'}


def decode(raw):
    """Only a new MFC class, schema 1, empty base CString, exact byte length.

    Reject class references, Unicode/nonempty strings, and unknown layouts;
    these need independent research, never a guessed offset or action label.
    """
    if not isinstance(raw, bytes) or not 6 <= len(raw) <= 4096:
        raise ValueError('payload length')
    tag, schema, length = struct.unpack_from('<3H', raw)
    if tag != 0xffff or schema != 1 or not 1 <= length <= 64:
        raise ValueError('class header')
    name = raw[6:6+length].decode('ascii')
    if name not in CLASSES:
        raise ValueError('unsupported class')
    body = raw[6+length:]
    expected_type, expected_size = CLASSES[name]
    if len(body) != expected_size or body[12] != 0:
        raise ValueError('unsupported serialized layout')
    kind, subtype, sender_raw = struct.unpack_from('<3i', body)
    # Base +0x0c is an action operand, NOT a player slot. Domestic 4/5/8
    # serialize packed map coordinates here (base serializer 0x435a44).
    # Keep the legacy field name for existing evidence/cache compatibility;
    # attribution always comes from the separately decoded actor_force_id.
    if kind != expected_type or not 0 <= subtype <= 255:
        raise ValueError('base fields')
    row = dict(native_class=name, native_type=kind, subtype=subtype,
               sender_raw=sender_raw, decoded_from_raw=True,
               match_id=None, game_quarter=None, command_committed=None,
               server_result_verified=False, action_training_eligible=False)
    if kind == 16:
        # 0x483e04 serializer; 0x4a7711..0x4a7789 UI construction.
        # The packet has troop kind, owner, three officers, soldiers/rice,
        # and placement operands. It does NOT carry the resulting unit ID.
        if subtype != 0:
            raise ValueError('unsupported create subtype')
        troop, actor, *generals = struct.unpack_from('<5h', body, 13)
        soldiers, rice = struct.unpack_from('<2i', body, 23)
        placement = list(struct.unpack_from('<2hih', body, 31))
        if (not 0 <= troop <= 3 or any(g < -1 or g > 65534 for g in generals)
                or not 0 <= soldiers <= 2000000 or not 0 <= rice <= 2**31-1):
            raise ValueError('sortie operands')
        row.update(actor_force_id=actor, troop_kind_raw=troop,
                   general_ids_raw=generals, soldiers_raw=soldiers, rice_raw=rice,
                   placement_raw=placement, action='出征')
    elif kind == 18:
        actor, parameter, value, extra = struct.unpack_from('<4i', body, 13)
        row.update(actor_force_id=actor, parameter_raw=parameter,
                   value_raw=value, extra_raw=extra)
        row['action'] = ({0: {0:'步兵训练', 1:'骑兵训练', 2:'弓兵训练'}.get(parameter, '训练（兵种未解码）'),
                          2:'施舍',
                          3:{0:'卖米', 1:'买米'}.get(parameter, '米交易（方向未解码）'),
                          4:CONSTRUCTION_ACTIONS.get(parameter, '内政指令 #4（类别未解码）'),
                          5:'拆除', 8:'侦察'}.get(subtype, f'内政指令 #{subtype}'))
        if subtype in (4, 5, 8):
            row['target_xy_raw'] = list(struct.unpack_from('<2H', body, 8))
            row['base_value_semantics'] = 'packed_coordinates_not_sender'
    elif kind == 19:
        flags = list(body[13:18])
        actor, other, other2, parameter = struct.unpack_from('<4i', body, 18)
        cards = list(struct.unpack_from('<5H', body, 34))
        row.update(actor_force_id=actor, flags_raw=flags, other_raw=other,
                   other2_raw=other2, parameter_raw=parameter, cards_raw=cards)
        row['action'] = {3:'更换外交卡片', 4:'外交卡片排序'}.get(subtype, f'外交指令 #{subtype}')
    else:
        actor, target = struct.unpack_from('<2i', body, 13)
        row.update(actor_force_id=actor, target_raw=target)
        row['action'] = {0:'普通录用', 1:'接纳仕官', 2:'解雇武将',
                         5:'加增武将'}.get(subtype, f'人事指令 #{subtype}')
    if not 0 <= row['actor_force_id'] < 32:
        raise ValueError('actor force bounds')
    return row


def _binding(payload):
    # Read-only packet attribution is decoded actor_force_id. It must not
    # depend on the mutation API's confirmed-local-player prerequisite.
    state, process = payload.get('state') or {}, payload.get('identity') or {}
    core = int(str(state.get('core_address')), 0)
    if (type(process.get('pid')) is not int or process['pid'] <= 0
            or type(process.get('creation_filetime')) is not int or process['creation_filetime'] <= 0
            or type(process.get('path')) is not str or not 0 < len(process['path']) <= 1024
            or type(payload.get('source_id')) is not str or not 0 < len(payload['source_id']) <= 64
            or not 0 < core < 2**32
            or state.get('identity') and identity_key(state['identity']) != identity_key(process)):
        raise ValueError('read-only source process binding')
    return dict(pid=process['pid'], created=process['creation_filetime'], image=process['path'],
                core=core, build=state['build_sha256'], source_id=payload['source_id'])


def _accept(event, binding):
    if (event.get('schema') != 'native-payload-observation-1'
            or event.get('fake') is not False or event.get('read_only') is not True
            or event.get('no_target_calls') is not True
            or event.get('binding') != binding or event.get('build') != SANPK_BUILD
            or event.get('source_id') != binding['source_id'] or event.get('core') != binding['core']
            or identity_key(event.get('target') or {}) != identity_key(dict(
                pid=binding['pid'], creation_filetime=binding['created'], path=binding['image']))):
        raise ValueError('source binding')
    module = event.get('module') or {}
    if not is_supported_network_sha(module.get('sha256')) or module.get('fake') is not False:
        raise ValueError('module hash')
    raw_hex = event.get('raw_hex')
    if type(raw_hex) is not str or len(raw_hex) > 8192:
        raise ValueError('raw bounds')
    raw = bytes.fromhex(raw_hex)
    if len(raw) != event.get('payload_length') or hashlib.sha256(raw).hexdigest() != event.get('raw_sha256'):
        raise ValueError('raw hash')
    when = datetime.fromisoformat(event['captured_at'])
    if when.tzinfo is None:
        raise ValueError('capture timezone')
    entry_hex = event.get('entry_hex')
    if type(entry_hex) is not str or len(entry_hex) != 24:
        raise ValueError('queue entry')
    metadata, pointer, size = struct.unpack('<3I', bytes.fromhex(entry_hex))
    if (pointer != event.get('payload_pointer') or size != len(raw)
            or metadata != event.get('metadata_raw')
            or event.get('queue') not in ('primary', 'alternate')):
        raise ValueError('queue entry mismatch')
    return raw, when


class CommandEvidenceReader:
    """Bounded incremental scan of only this process/source's journal folder."""
    def __init__(self, root=ROOT):
        self.root = Path(root) / DIRECTORY_NAME
        self.binding = None
        self.files = {}
        self.groups = {}
        self.errors = self.unsupported = self.gaps = self.omitted = 0

    def _event(self, event, line, path, offset, binding):
        if event.get('kind') == 'network_payload_gap':
            self.gaps += 1
            return
        if event.get('kind') != 'network_payload_observation':
            return
        raw, when = _accept(event, binding)
        try:
            decoded = decode(raw)
        except (ValueError, UnicodeError, struct.error):
            self.unsupported += 1
            return
        # Across worker recoveries a stale queue entry can be seen again.
        # Pointer/metadata reuse (ABA) cannot be excluded: no order count claim.
        # The same entry is copied between primary and alternate arrays too.
        key = (event['entry_hex'], event['raw_sha256'])
        source = dict(source_file=path.relative_to(self.root).as_posix(), source_byte_offset=offset,
                      source_line_sha256=hashlib.sha256(line).hexdigest(),
                      raw_sha256=event['raw_sha256'], raw_hex=event['raw_hex'],
                      queue_entry_hex=event['entry_hex'])
        group = self.groups.get(key)
        if group is None:
            group = dict(decoded, **source, observed_at=event['captured_at'],
                         last_observed_at=event['captured_at'], observations=0,
                         evidence='native_queue_bytes', process_scope_only=True,
                         repeated_command_count=None)
            self.groups[key] = group
        elif when < datetime.fromisoformat(group['observed_at']):
            group.update(source, observed_at=event['captured_at'])
        group['observations'] += 1
        if when > datetime.fromisoformat(group['last_observed_at']):
            group['last_observed_at'] = event['captured_at']
        if len(self.groups) > MAX_ROWS:
            oldest = min(self.groups, key=lambda k:self.groups[k]['observed_at'])
            del self.groups[oldest]
            self.omitted += 1

    def read(self, payload, remote=False):
        result = dict(rows=[], complete_command_stream=False, process_scope_only=True,
                      status='unavailable', errors=0, unsupported=0, gaps=0,
                      omitted_rows=0, files_limited=False, scan_pending=False)
        if remote:
            from command_transport import import_commands
            return import_commands(payload)
        try:
            if payload.get('fresh') is not True or payload.get('error'):
                return result
            binding = _binding(payload)
            if binding['build'] != SANPK_BUILD:
                return result
            if self.binding != binding:
                self.binding=binding; self.files={}; self.groups={}
                self.errors=self.unsupported=self.gaps=self.omitted=0
            digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode('utf8')).hexdigest()[:20]
            folder = self.root / digest
            paths = sorted(folder.glob('*-seg-*.jsonl'), key=lambda p:(p.stat().st_mtime_ns, p.name))
            # MAX_FILES limits work per call, not which retained journals can
            # ever be read. Cold starts used to permanently discard early
            # segments. Keep bounded cursors and drain the oldest backlog.
            result['files_limited'] = len(paths) > MAX_TRACKED_FILES
            paths = paths[-MAX_TRACKED_FILES:]
            self.files = {p:v for p,v in self.files.items() if p in paths}
            budget = MAX_BATCH
            visited = 0
            for path in paths:
                stat = path.stat(); token = (stat.st_dev, stat.st_ino)
                cursor = self.files.get(path)
                if cursor is None:
                    cursor = self.files[path] = dict(token=token, offset=0)
                elif cursor['token'] != token or stat.st_size < cursor['offset']:
                    # Already rendered provenance would no longer address the
                    # same bytes. Drop the whole cache rather than misattribute.
                    self.binding=None; self.files={}; self.groups={}
                    raise ValueError('journal replaced or truncated')
                if cursor['offset'] >= stat.st_size:
                    continue
                if budget <= 0 or visited >= MAX_FILES:
                    result['scan_pending']=True; continue
                visited += 1
                with path.open('rb') as handle:
                    handle.seek(cursor['offset'])
                    raw = handle.read(min(budget, MAX_BATCH))
                budget -= len(raw)
                end = raw.rfind(b'\n') + 1
                if not end:
                    # Writer may still be completing a line. Oversized complete
                    # lines remain unread and visibly pending, never half parsed.
                    result['scan_pending']=True
                    continue
                offset=cursor['offset']; cursor['offset'] += end
                for line in raw[:end].splitlines(keepends=True):
                    at=offset; offset += len(line)
                    try:
                        if len(line)>MAX_LINE: raise ValueError('record length')
                        event=json.loads(line)
                        if not isinstance(event,dict):raise ValueError('record type')
                        self._event(event,line,path,at,binding)
                    except (ValueError, UnicodeError, KeyError, TypeError, struct.error):
                        self.errors += 1
                result['scan_pending'] |= cursor['offset'] < stat.st_size
            # Attribution is decoded actor, not whichever force is selected.
            result.update(status='partial_native_queue_evidence',
                          binding=deepcopy(binding),
                          rows=deepcopy(sorted(self.groups.values(),key=lambda r:r['observed_at'])),
                          errors=self.errors, unsupported=self.unsupported, gaps=self.gaps,
                          omitted_rows=self.omitted,
                          capture_status={k:(payload.get('native_payload_observations') or {}).get(k)
                                          for k in ('enabled','phase','error','last_error')})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            result['errors'] += 1
        return result


def command_line(row):
    stamp = datetime.fromisoformat(row['observed_at']).astimezone().strftime('%m-%d %H:%M:%S')
    kind, subtype = row['native_type'], row['subtype']
    detail = ''
    if kind == 18 and subtype == 0:
        detail = f'政治参数 {row["value_raw"]}'
    elif kind == 18 and subtype in (4, 5, 8):
        detail = '目标坐标 ' + ', '.join(str(n) for n in row['target_xy_raw'])
    elif kind == 18 and subtype == 2:
        detail = f'随机加值参数 {row["extra_raw"]+5}'
    elif kind == 20:
        detail = ('城关' if subtype == 0 else '武将') + f' #{row["target_raw"]}'
    elif kind == 19 and subtype in (3,4):
        detail = '卡片序列 ' + '、'.join(str(n) for n in row['cards_raw'] if n)
    else:
        detail = f'原生编号 {kind}/{subtype}'
    return f'{stamp} 首次采样  {row["action"]}  {detail} · 原始封包／结算未确认'
