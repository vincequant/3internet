"""Read-only lobby nicknames from the verified player-slot layout.

P(s)=core+4+s*0x87 is enabled only for the build whose static evidence
established that layout. The lobby copies P+0x0E into a row and draws it with
DrawTextA. Decoding uses the target ntdll!NlsAnsiCodePage USHORT. The helper
process GetACP is not a fallback. Stability samples memory.read again after
the string bytes; a page cache is not a second observation.
"""
import codecs
import struct

from target_codepage import read_target_nls_ansi_code_page

VERIFIED_BUILD = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
SLOT_COUNT = 8
SLOT_STRIDE = 0x87
SLOT_BASE = 4
SLOT_BYTES = 0x4A
OFF_SOURCE = 6
OFF_NAME = 0x0E
OFF_STATE = 0x42
OFF_FORCE = 0x46
POINTER_MIN = 0x1000C
POINTER_MAX = 0x7FFEFF00
CORE_MIN = 0x10000
CORE_LIMIT = 0x7FFE0000
NAME_MAX = 128
CAPACITY_MAX = 4096
EMPTY_LABEL = '大厅昵称未提供'
DECODING_LIMITATION = (
    'ansi_code_page is the target ntdll!NlsAnsiCodePage USHORT read by ReadProcessMemory. '
    'Target code was not executed and target GetACP was not called. '
    'SANPK has no RT_MANIFEST or external manifest, and the helper manifest has no activeCodePage. '
    'The same Wine prefix can still give the helper a different GetACP, so the helper code page is not a fallback. '
    'If the target value is unavailable, nickname bytes stay raw and undecoded. '
    'source_metadata is not an account id.'
)
_MISSING = object()
_SLOT_SPAN = SLOT_BASE + (SLOT_COUNT - 1) * SLOT_STRIDE + SLOT_BYTES

STATIC_SOURCE = {
    'kind': 'static_layout',
    'build_sha256': VERIFIED_BUILD,
    'slot': 'P(s)=core+4+s*0x87, s=0..7',
    'source_metadata': 'DWORD P+6; namespace is not a proven account id',
    'state_raw': 'DWORD P+0x42; unclassified, including value 2',
    'force_id': 'DWORD P+0x46',
    'nickname': 'CString pointer DWORD P+0x0E; header ptr-12; DrawTextA uses GetACP',
    'not_nickname': 'DWORD P+0x0A',
    'evidence': 'identity-ledger I4 I6; 46592c NetMsg_GetUserName; 46ea53->42de4b; 42e0c6->42e26b DrawTextA IAT 4fb764',
}
LOBBY_STATIC_SOURCE = dict(STATIC_SOURCE,
    kind='document_lobby_layout',
    slot='doc=core-0x912; P(s)=doc+0xB4+s*0x87, s=0..7',
    force_id='DWORD P+0x46, raw selection; not a final match attribution',
    evidence='4438c1/443978 embedded core; 46ea53 UI slots; 42bc5a/472e34 copy to core')
DOC_VTABLE = 0x504D40
CORE_VTABLE = 0x5053C0
PLAYER_VTABLE = 0x507B80
CORE_ANCHOR = 0x53BB30


def _normalize_acp(acp):
    if type(acp) is not int or not 0 < acp <= 65535:
        return None
    try:
        codecs.lookup('cp%d' % acp)
    except LookupError:
        return None
    return acp


def _valid_core(core):
    if type(core) is not int:
        return False
    if core < CORE_MIN or core > CORE_LIMIT:
        return False
    return core + _SLOT_SPAN <= CORE_LIMIT


def _layout(build, verified, note, acp=None, acp_source=None, directly=False, evidence=None):
    layout = {
        'verified': verified,
        'status': 'verified' if verified else 'unknown',
        'build_sha256': build,
        'ansi_code_page': acp,
        'ansi_code_page_source': acp_source,
        'target_ansi_code_page_directly_observed': directly,
        'target_code_executed': False,
        'decoding_limitation': DECODING_LIMITATION,
        'note': note,
        'static_source': STATIC_SOURCE if verified else {
            'applied': False,
            'reason': 'layout_not_verified_for_this_build',
            'verified_build_sha256': VERIFIED_BUILD,
        },
    }
    if evidence is not None:
        layout['ansi_code_page_evidence'] = evidence
    return layout


def _failed_view(build, note):
    return {'player_slots': [], 'layout': _layout(build, False, note)}


def _blank(slot, reason):
    return {
        'slot': slot,
        'source_metadata': None,
        'state_raw': None,
        'force_id': None,
        'nickname': None,
        'raw_hex': None,
        'encoding': None,
        'status': 'unknown',
        'stability': {'slot': False, 'header': False, 'bytes': False},
        'static_source': STATIC_SOURCE,
        'reason': reason,
    }


def _once(memory, address, size):
    if type(address) is not int or type(size) is not int or size < 0 or address < 0:
        return None
    data = memory.read(address, size)
    if data is None or isinstance(data, bool) or not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    raw = bytes(data)
    if len(raw) != size:
        return None
    return raw


def _matches(memory, address, size, expected):
    try:
        got = _once(memory, address, size)
    except Exception:
        return False
    return got == expected


def _pair(memory, address, size):
    """Two adjacent reads. A later sample must still be compared with these bytes."""
    try:
        first = _once(memory, address, size)
    except Exception:
        first = None
        failed = True
    else:
        failed = False
    try:
        second = _once(memory, address, size)
    except Exception:
        return None, 'read_error'
    if failed or first is None or second is None:
        return None, 'read_error' if failed or (first is None and second is None) else 'unstable'
    if first != second:
        return None, 'unstable'
    return first, None


def _lord_count(lords, force_id):
    count = 0
    for lord in lords or []:
        if not isinstance(lord, dict):
            continue
        fid = lord.get('force_id')
        if type(fid) is int and fid == force_id:
            count += 1
    return count


def _read_slot(memory, core, slot, acp):
    return _read_slot_at(memory, core + SLOT_BASE + slot * SLOT_STRIDE, slot, acp)


def _read_slot_at(memory, address, slot, acp, static_source=STATIC_SOURCE, expected_vtable=None):
    row = _blank(slot, 'unknown')
    row['static_source'] = static_source
    fixed, problem = _pair(memory, address, SLOT_BYTES)
    if fixed is None:
        row['reason'] = problem or 'read_error'
        return row
    if expected_vtable is not None and struct.unpack_from('<I', fixed)[0] != expected_vtable:
        row['reason'] = 'player_vtable_mismatch'
        return row
    row['stability']['slot'] = True
    source = struct.unpack_from('<I', fixed, OFF_SOURCE)[0]
    state = struct.unpack_from('<I', fixed, OFF_STATE)[0]
    force = struct.unpack_from('<I', fixed, OFF_FORCE)[0]
    pointer = struct.unpack_from('<I', fixed, OFF_NAME)[0]
    row['source_metadata'] = source
    row['state_raw'] = state
    row['force_id'] = force
    if pointer < POINTER_MIN or pointer >= POINTER_MAX:
        row['reason'] = 'pointer_out_of_bounds'
        return row
    header, problem = _pair(memory, pointer - 12, 12)
    if header is None:
        row['reason'] = problem or 'unstable'
        return row
    refcount, length, capacity = struct.unpack('<iii', header)
    del refcount
    if length < 0 or capacity < 0 or capacity > CAPACITY_MAX or length > min(capacity, NAME_MAX):
        row['reason'] = 'invalid_cstring_header'
        return row
    row['stability']['header'] = True
    payload, problem = _pair(memory, pointer, length + 1)
    if payload is None:
        row['reason'] = problem or 'unstable'
        return row
    slot_ok = _matches(memory, address, SLOT_BYTES, fixed)
    header_ok = _matches(memory, pointer - 12, 12, header)
    payload_ok = _matches(memory, pointer, length + 1, payload)
    if not (slot_ok and header_ok and payload_ok):
        blank = _blank(slot, 'unstable')
        blank['static_source'] = static_source
        return blank
    if payload[-1:] != b'\0':
        row['reason'] = 'missing_nul'
        return row
    row['stability']['bytes'] = True
    raw = payload[:-1]
    row['raw_hex'] = raw.hex()
    if length == 0:
        row['reason'] = 'empty_nickname'
        return row
    if acp is None:
        row['reason'] = 'code_page_unavailable'
        return row
    try:
        text = raw.decode('cp%d' % acp)
    except UnicodeDecodeError:
        row['reason'] = 'decode_failed'
        return row
    row['_decoded'] = text
    row['_encoding'] = 'cp%d' % acp
    row['reason'] = None
    return row


def _finalize(rows, lords):
    counts = {}
    for row in rows:
        force_id = row.get('force_id')
        if row['stability']['slot'] and type(force_id) is int:
            counts[force_id] = counts.get(force_id, 0) + 1
    for row in rows:
        decoded = row.pop('_decoded', None)
        encoding = row.pop('_encoding', None)
        stable = row['stability']['slot'] and row['stability']['header'] and row['stability']['bytes']
        force_id = row.get('force_id')
        unique_slot = stable and type(force_id) is int and counts.get(force_id) == 1
        lords_found = _lord_count(lords, force_id) if type(force_id) is int else 0
        if not unique_slot:
            row['nickname'] = None
            row['encoding'] = None
            row['status'] = 'unknown'
            if stable and type(force_id) is int and counts.get(force_id, 0) > 1:
                row['reason'] = 'duplicate_force'
            continue
        if lords_found != 1:
            row['nickname'] = None
            row['encoding'] = None
            row['status'] = 'unknown'
            row['reason'] = 'duplicate_lord' if lords_found > 1 else 'invalid_force'
            continue
        if decoded:
            row['nickname'] = decoded
            row['encoding'] = encoding
            row['status'] = 'confirmed'
            row['reason'] = None
            continue
        row['nickname'] = None
        row['encoding'] = None
        row['status'] = 'unknown'
        if row['reason'] == 'empty_nickname':
            continue
        if row['reason'] is None:
            row['reason'] = 'unknown'
    return rows


def _target_code_page(memory):
    """Use only a fresh target NlsAnsiCodePage observation. No helper fallback."""
    try:
        evidence = read_target_nls_ansi_code_page(memory)
    except Exception:
        evidence = None
    if not isinstance(evidence, dict):
        return None, 'target_ntdll_unavailable', False, None
    if evidence.get('target_code_executed') is not False or evidence.get('read_only') is not True:
        return None, 'target_ntdll_unavailable', False, None
    if evidence.get('double_read') is not True or evidence.get('source') != 'target_ntdll_NlsAnsiCodePage':
        return None, 'target_ntdll_unavailable', False, None
    acp = _normalize_acp(evidence.get('codepage'))
    raw_hex = evidence.get('raw_hex')
    path = evidence.get('module_path')
    base = evidence.get('module_base')
    export_rva = evidence.get('export_rva')
    try:
        raw_matches = type(raw_hex) is str and bytes.fromhex(raw_hex) == struct.pack('<H', acp)
    except (TypeError, ValueError):
        raw_matches = False
    if (acp is None or not raw_matches or type(path) is not str or not path.lower().endswith('\\ntdll.dll')
            or type(base) is not int or type(export_rva) is not int):
        return None, 'target_ntdll_unavailable', False, None
    published = {
        'module_path': path,
        'module_base': base,
        'export_rva': export_rva,
        'raw_hex': raw_hex,
        'double_read': True,
        'read_only': True,
        'target_code_executed': False,
        'source': 'target_ntdll_NlsAnsiCodePage',
    }
    return acp, 'target_ntdll_NlsAnsiCodePage', True, published


def read_player_slots(memory, core, build_sha256, lords, ansi_code_page=_MISSING):
    """Return at most eight slot rows. Per-slot failures stay unknown."""
    if build_sha256 != VERIFIED_BUILD:
        return _failed_view(build_sha256, '玩家槽昵称布局未验证')
    if not _valid_core(core):
        view = _failed_view(build_sha256, '玩家槽核心地址无效，结果未知')
        view['player_slots'] = [_blank(slot, 'invalid_core') for slot in range(SLOT_COUNT)]
        return view
    evidence = None
    directly = False
    if ansi_code_page is _MISSING:
        acp, acp_source, directly, evidence = _target_code_page(memory)
    else:
        acp = _normalize_acp(ansi_code_page)
        acp_source = 'explicit_test_parameter'
    rows = []
    for slot in range(SLOT_COUNT):
        try:
            rows.append(_read_slot(memory, core, slot, acp))
        except Exception:
            rows.append(_blank(slot, 'read_error'))
    return {
        'player_slots': _finalize(rows, lords),
        'layout': _layout(build_sha256, True, '已按研究构建读取', acp, acp_source, directly, evidence),
    }


def read_player_slots_bound(memory, core, build_sha256, lords, ansi_code_page=_MISSING):
    """Snapshot binding. A reader failure leaves slots empty and unknown."""
    try:
        view = read_player_slots(memory, core, build_sha256, lords, ansi_code_page)
    except Exception:
        return _failed_view(build_sha256, '玩家槽读取失败，结果未知')
    layout = view.get('layout') if isinstance(view, dict) else None
    rows = view.get('player_slots') if isinstance(view, dict) else None
    if not isinstance(layout, dict) or layout.get('build_sha256') != build_sha256 or not isinstance(rows, list):
        return _failed_view(build_sha256, '玩家槽结果与快照构建不一致')
    view['player_slots'] = rows[:SLOT_COUNT]
    return view


def read_lobby_player_slots(memory, core, build_sha256):
    """Document UI observations before/after selection; never final force attribution."""
    if build_sha256 != VERIFIED_BUILD or not _valid_core(core) or core - 0x912 < CORE_MIN:
        return _failed_view(build_sha256, '开局前玩家布局或根地址未验证')
    doc = core - 0x912
    try:
        core_vt = struct.pack('<I', CORE_VTABLE)
        doc_vt = struct.pack('<I', DOC_VTABLE)
        anchor = struct.pack('<I', core)
        if (not _matches(memory, CORE_ANCHOR, 4, anchor)
                or not _matches(memory, core, 4, core_vt) or not _matches(memory, doc, 4, doc_vt)):
            return _failed_view(build_sha256, '开局前玩家根对象不匹配')
        acp, source, directly, evidence = _target_code_page(memory)
        rows = []
        for slot in range(SLOT_COUNT):
            try:
                row = _read_slot_at(memory, doc + 0xB4 + slot * SLOT_STRIDE, slot, acp,
                                    LOBBY_STATIC_SOURCE, PLAYER_VTABLE)
            except Exception:
                row = _blank(slot, 'read_error')
                row['static_source'] = LOBBY_STATIC_SOURCE
            row['nickname'] = row.pop('_decoded', None)
            row['encoding'] = row.pop('_encoding', None)
            row['force_id_raw'] = row.pop('force_id')
            row['force_attribution_confirmed'] = False
            row['status'] = 'observed' if row['nickname'] else 'unknown'
            rows.append(row)
        if (not _matches(memory, CORE_ANCHOR, 4, anchor)
                or not _matches(memory, core, 4, core_vt) or not _matches(memory, doc, 4, doc_vt)):
            return _failed_view(build_sha256, '开局前玩家根对象采样期间变化')
        layout = _layout(build_sha256, True, '选择画面玩家观测；势力归属尚未最终确认',
                         acp, source, directly, evidence)
        layout['static_source'] = LOBBY_STATIC_SOURCE
        layout['force_attribution_confirmed'] = False
        layout['core_anchor'] = {'address': CORE_ANCHOR, 'value': core, 'stable': True,
                                 'limitation': 'anchor/vtables do not prove atomic object lifetime'}
        return {'player_slots': rows, 'layout': layout}
    except Exception:
        return _failed_view(build_sha256, '开局前玩家读取失败，结果未知')


def display_nickname(snapshot, force_id):
    """Confirmed nickname, the empty-lobby label, or None when unknown.

    Uses only the current snapshot. Bool is not a force id.
    """
    if type(force_id) is not int or not isinstance(snapshot, dict):
        return None
    layout = snapshot.get('player_slots_layout') or {}
    if not isinstance(layout, dict):
        return None
    if layout.get('build_sha256') != snapshot.get('build_sha256') or layout.get('build_sha256') != VERIFIED_BUILD:
        return None
    if not layout.get('verified'):
        return None
    source = layout.get('ansi_code_page_source')
    if source == 'target_ntdll_NlsAnsiCodePage':
        if layout.get('target_ansi_code_page_directly_observed') is not True:
            return None
    elif source != 'explicit_test_parameter':
        return None
    acp = layout.get('ansi_code_page')
    hits = []
    for row in snapshot.get('player_slots') or []:
        if not isinstance(row, dict) or type(row.get('force_id')) is not int or row.get('force_id') != force_id:
            continue
        source = row.get('static_source') or {}
        if not isinstance(source, dict) or source.get('build_sha256') != VERIFIED_BUILD:
            continue
        stability = row.get('stability') or {}
        if not (stability.get('slot') and stability.get('header') and stability.get('bytes')):
            continue
        hits.append(row)
    if len(hits) != 1:
        return None
    row = hits[0]
    if row.get('status') == 'confirmed' and type(row.get('nickname')) is str and row['nickname']:
        if type(acp) is not int or row.get('encoding') != 'cp%d' % acp:
            return None
        return row['nickname']
    if row.get('status') == 'unknown' and row.get('reason') == 'empty_nickname':
        return EMPTY_LABEL
    return None
