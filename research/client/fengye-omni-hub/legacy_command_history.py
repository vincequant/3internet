"""Read old UI agent *files* into the local display ledger, never execute them.

Only p60_ui_<hex>.json and the same stem's .bin inside service.lab are read.
The JSON file mtime is an observed file-write time, not a proven command time.
No pre-send state exists, so a local receipt can never establish completion.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import struct

_PATTERN = re.compile(r'^p60_ui_([0-9a-f]{8,32})\.json$', re.IGNORECASE)
_PRESETS = {'train', 'build', 'alms', 'rice', 'personnel'}
_KEYS = ('magic2 rc core own gate_before gate_after phase tick '
         'vtable kind subtype operand f14 f18 f1c f20').split()
_MAGIC = 0x53365243
_OFFSETS = {0x04: 'kind', 0x08: 'subtype', 0x0c: 'operand',
            0x14: 'f14', 0x18: 'f18', 0x1c: 'f1c', 0x20: 'f20'}
_SOURCE_NOTE = '舊版發送記錄／沒有發送前快照，無法補驗'


def _fields(plan):
    items = plan.get('fields')
    if not isinstance(items, list):
        return {}
    fields = {}
    for item in items:
        if not isinstance(item, dict) or type(item.get('val')) is not int:
            raise ValueError('fields 格式不完整')
        value = item.get('off')
        if type(value) is int:
            offset = value
        elif isinstance(value, str):
            offset = int(value, 0)
        else:
            raise ValueError('field offset 無法確認')
        if offset in fields:
            raise ValueError('field offset 重複')
        if offset not in _OFFSETS:
            raise ValueError('非既有 UI 命令 ABI 的欄位')
        fields[offset] = item['val']
    return fields


def _decode(plan):
    preset = plan['preset']
    fields = _fields(plan)
    expected_kind = 20 if preset == 'personnel' else 18
    expected_subtype = {'train': 0, 'alms': 2, 'rice': 3, 'build': 4}.get(preset)
    if 0x04 in fields and fields[0x04] != expected_kind:
        raise ValueError('preset 與 kind 不一致')
    if expected_subtype is not None and 0x08 in fields and fields[0x08] != expected_subtype:
        raise ValueError('preset 與 subtype 不一致')
    expected_class = 'personnel' if preset == 'personnel' else 'domestic'
    if plan.get('class') != expected_class:
        raise ValueError('preset 與 class 不一致')
    params = {}
    if 0x14 in fields:
        params['actor'] = fields[0x14]
    if preset == 'personnel':
        for offset, key in ((0x08, 'subtype'), (0x18, 'target_id')):
            if offset in fields:
                params[key] = fields[offset]
        required = (0x04, 0x08, 0x0c, 0x14, 0x18)
    else:
        for offset, key in ((0x1c, 'value'), (0x20, 'extra')):
            if offset in fields:
                params[key] = fields[offset]
        if preset == 'train' and 0x18 in fields:
            params['troop'] = fields[0x18]
        elif preset == 'rice' and 0x18 in fields:
            params['buy'] = fields[0x18]
        elif preset == 'alms' and 0x18 in fields:
            params['parameter'] = fields[0x18]
        elif preset == 'build':
            if 0x18 in fields:
                params['build_type'] = fields[0x18]
            if 0x1c in fields:
                params['city'] = fields[0x1c]
            if 0x0c in fields:
                packed = fields[0x0c] & 0xffffffff
                params.update(x=packed & 0xffff, y=(packed >> 16) & 0xffff)
        required = tuple(_OFFSETS)
    missing = ['0x%x' % offset for offset in required if offset not in fields]
    return fields, params, missing


def _read_record(path):
    """Return a display-only job from a trusted filename; leave files intact."""
    match = _PATTERN.fullmatch(path.name)
    if match is None or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('不是本機 UI state 檔')
    raw = path.read_bytes()
    plan = json.loads(raw.decode('utf-8'))
    if not isinstance(plan, dict) or plan.get('mode') != 'generic_cmd':
        raise ValueError('不是 generic_cmd UI 記錄')
    if plan.get('preset') not in _PRESETS or plan.get('plan_only'):
        raise ValueError('不是支援的已建立 UI agent 記錄')
    if type(plan.get('thread_id')) is not int or plan['thread_id'] <= 0:
        raise ValueError('缺少已建立 agent 的 thread_id')
    fields, params, missing = _decode(plan)
    tag = match.group(1).lower()
    observed_time = path.stat().st_mtime
    receipt_path = path.with_suffix('.bin')
    receipt, receipt_hash, receipt_error, receipt_at = None, None, None, None
    if receipt_path.exists():
        try:
            if receipt_path.is_symlink():
                raise ValueError('回執為連結，未讀取')
            if receipt_path.stat().st_size != 64:
                raise ValueError('回執長度不符')
            receipt_raw = receipt_path.read_bytes()
            data = dict(zip(_KEYS, struct.unpack('<16I', receipt_raw)))
            if data['magic2'] != _MAGIC:
                raise ValueError('回執識別不符')
            for offset, field in _OFFSETS.items():
                if offset in fields and fields[offset] & 0xffffffff != data[field]:
                    raise ValueError('回執與原 state 欄位不一致：' + field)
            receipt = {key: data[key] for key in
                       ('rc', 'kind', 'subtype', 'operand', 'f14', 'f18', 'f1c', 'f20', 'phase', 'tick')}
            receipt['magic_ok'] = True
            receipt_hash = sha256(receipt_raw).hexdigest()
            receipt_at = receipt_path.stat().st_mtime
        except (OSError, ValueError, struct.error) as exc:
            receipt_error = str(exc)
    status = 'legacy_sent' if receipt is not None and not missing else 'legacy_unknown'
    note = _SOURCE_NOTE
    if receipt is not None:
        note += '；本機回執 rc=%s，' % receipt['rc']
        note += '遊戲實際效果未核實' if receipt['rc'] else '本機回報未發送成功'
    else:
        note += '；沒有可核實的本機回執，是否發送未知'
    if missing:
        note += '；部分參數未知（' + '、'.join(missing) + '）'
    if receipt_error:
        note += '；' + receipt_error
    # Old state did not record WINEPREFIX. Keep the known console namespace
    # for the ledger's existing schema, but do not claim it as source evidence.
    known_prefix = plan.get('prefix') if plan.get('prefix') in {
        'prefix-fengye-shadow', 'prefix-sikarugir10', 'prefix-dingman-local'} else None
    prefix = known_prefix or 'prefix-fengye-shadow'
    if known_prefix is None:
        note += '；舊檔未記錄客戶端 prefix'
    pid = plan.get('pid') if type(plan.get('pid')) is int and plan['pid'] > 0 else None
    creation = plan.get('creation') if type(plan.get('creation')) is int else None
    job = {'id': 'legacy-' + tag, 'tag': tag, 'created': observed_time,
           'prefix': prefix, 'source_prefix': known_prefix,
           'preset': plan['preset'], 'status': status, 'params': params,
           'actor_label': str(params['actor']) if 'actor' in params else '未知勢力',
           'target_pid': pid, 'receipt': receipt, 'error': receipt_error,
           'note': note, 'auto_slot': False,
           'legacy': {'source': '舊版發送記錄', 'state_file': path.name,
                      'state_sha256': sha256(raw).hexdigest(),
                      'state_file_mtime': observed_time, 'time_semantics': 'state_file_write_time',
                      'process_creation_filetime': creation, 'source_prefix_known': known_prefix is not None,
                      'missing_fields': missing, 'receipt_file': receipt_path.name if receipt is not None else None,
                      'receipt_sha256': receipt_hash,
                      'no_pre_send_snapshot': True, 'effect_verified': False},
           'events': [{'at': observed_time, 'status': status, 'note': note}]}
    if receipt_at is not None:
        job['receipt_at'] = receipt_at
    return job


def import_legacy_jobs(service):
    """Opt-in local-ledger import; call before starting the service's workers.

    A configured ``history_path`` opts in, including a first run whose file has
    not been created yet. Imported rows never enter service.queue and are not
    current unknown-send/slot guards. Receipt/state/flag files are never written.
    """
    if getattr(service, 'history_path', None) is None:
        return {'ok': True, 'enabled': False, 'imported': 0, 'skipped': 0, 'errors': []}
    errors, candidates = [], []
    lab = Path(service.lab)
    try:
        for path in lab.glob('p60_ui_*.json'):
            if _PATTERN.fullmatch(path.name) and not path.is_symlink():
                try:
                    candidates.append((path.stat().st_mtime, path))
                except OSError as exc:
                    errors.append({'file': path.name, 'error': str(exc)})
    except OSError as exc:
        return {'ok': False, 'enabled': True, 'imported': 0, 'skipped': 0,
                'errors': [{'error': str(exc)}]}
    imported, skipped = 0, 0
    with service.lock:
        seen = {str(job.get('tag')).lower() for job in service.jobs if job.get('tag')}
        for _, path in sorted(candidates, key=lambda item: item[0], reverse=True)[:100]:
            tag = _PATTERN.fullmatch(path.name).group(1).lower()
            if tag in seen:
                skipped += 1
                continue
            try:
                job = _read_record(path)
            except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
                skipped += 1
                errors.append({'file': path.name, 'error': str(exc)})
                continue
            service.jobs.append(job)
            seen.add(tag)
            imported += 1
        service.jobs.sort(key=lambda job: job.get('created', 0))
        if imported:
            service._save_history()
    return {'ok': True, 'enabled': True, 'imported': imported, 'skipped': skipped, 'errors': errors}
