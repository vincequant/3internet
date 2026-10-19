"""Optional P52 runtime UI patches, entered through p51_shadow_inject.py.

No automatic activation, game-file write, remote worker, network API, or
world-state write. One element per transaction. Cave pages remain allocated
until process exit so an old return address cannot reach freed memory.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time

SANPK_SHA = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
SEALED = bytes.fromhex('33c0c20400')
# key -> (VA, expected current bytes, payload symbol, detour opcode).
SITES = {
    'panel-create': (0x484F35, SEALED, 'ui_panel_create', 0xe9),
    'stat-12c': (0x499EB3, SEALED, 'ui_stat_12c', 0xe9),
    'stat-12d': (0x499F8A, SEALED, 'ui_stat_12d', 0xe9),
    'stat-12e': (0x49A052, SEALED, 'ui_stat_12e', 0xe9),
    'stat-12f': (0x49A11A, SEALED, 'ui_stat_12f', 0xe9),
    'stat-130': (0x49A1E2, SEALED, 'ui_stat_130', 0xe9),
    'stat-131': (0x49A2AA, SEALED, 'ui_stat_131', 0xe9),
    'stat-132': (0x49A372, SEALED, 'ui_stat_132', 0xe9),
    'cards-init': (0x484C5D, SEALED, 'ui_cards_init', 0xe9),
    'cards-update': (0x484C7E, SEALED, 'ui_cards_update', 0xe9),
    # This call is inside the tile-color renderer, not the shared visibility
    # predicates. A first predicate true skips its explored-only fallback.
    'map-tiles': (0x4330E0, bytes.fromhex('e87d550300'), 'ui_visible_xy', 0xe8),
    # Detail-card paint gate, including the overwritten TEST's flags.
    'map-unit-sight': (0x47DD11, bytes.fromhex('e84ca9feff'), 'ui_visible_xy', 0xe8),
    'map-unit-detail': (0x47E755, bytes.fromhex('ff507485c0'), 'ui_visible_test', 0xe8),
    'map-city-detail': (0x47FF2B, bytes.fromhex('ff507485c0'), 'ui_visible_test', 0xe8),
    'map-city-skin': (0x48055A, bytes.fromhex('ff507485c0'), 'ui_visible_test', 0xe8),
    'map-site-detail': (0x4817AA, bytes.fromhex('ff507485c0'), 'ui_visible_test', 0xe8),
    'map-marker-detail': (0x4820F2, bytes.fromhex('ff507485c0'), 'ui_visible_test', 0xe8),
}

FIELDS = (
    {'id': 0x12c, 'name': '信望', 'source': 'lord+0x17:u8', 'max': 200},
    {'id': 0x12d, 'name': '支配率', 'source': '0x46814a(lord)', 'max': 100},
    {'id': 0x12e, 'name': '金', 'source': 'lord+0x1c:u32', 'max': 10000000},
    {'id': 0x12f, 'name': '米', 'source': 'lord+0x18:u32', 'max': 10000000},
    {'id': 0x130, 'name': '步兵库存', 'source': 'lord+0x20:u32', 'max': 2000000},
    {'id': 0x131, 'name': '骑兵库存', 'source': 'lord+0x26:u32', 'max': 2000000},
    {'id': 0x132, 'name': '弓兵库存', 'source': 'lord+0x2c:u32', 'max': 2000000},
)


def detour(site, destination, opcode=0xe9):
    return bytes([opcode]) + struct.pack('<i', destination-site-5)


def display_scale(current, maximum):
    """Exact numeric-bar scale branches at 0x484385, including boundaries."""
    if current > 100000 or current == maximum:
        return (0, maximum)
    if current > 50000:
        return (50000, min(maximum, 100000))
    if current > 30000:
        return (30000, min(maximum, 50000))
    return (0, min(maximum, 30000))


def plan(code_base, entries, element):
    site, before, symbol, opcode = SITES[element]
    return {'element': element, 'site': site, 'before': before.hex(),
            'after': detour(site, code_base+entries[symbol], opcode).hex(),
            'symbol': symbol, 'destination': code_base+entries[symbol]}


def patch_transaction(changes, read, protected_write):
    """Caller holds the target threads. Check all sites, undo partial writes."""
    for site, before, after in changes:
        if read(site, len(before)) != before:
            raise ValueError('unexpected patch bytes at '+hex(site))
    attempted = []
    try:
        for site, before, after in changes:
            attempted.append((site, before))
            protected_write(site, after)
            if read(site, len(after)) != after:
                raise OSError('patch readback failed at '+hex(site))
    except BaseException as original:
        failures = []
        for site, before in reversed(attempted):
            try:
                protected_write(site, before)
                if read(site, len(before)) != before:
                    raise OSError('rollback readback mismatch')
            except BaseException as exc:
                failures.append('%s: %s' % (hex(site), exc))
        if failures:
            raise RuntimeError('patch failed; rollback incomplete: '+ '; '.join(failures)) from original
        raise


def run(args, c, w, k, handle, pid, created, read, write):
    from p51_shadow_inject import find_module
    from thread_probe import CONTEXT, threads_of
    prefix = os.environ.get('WINEPREFIX', '').rstrip('/\\')
    if Path(prefix).name != 'prefix-fengye-shadow':
        raise SystemExit('UI patches require explicit prefix-fengye-shadow')
    module = find_module(pid, 'SANPK.exe')
    if not module or module['base'] != 0x400000:
        raise SystemExit('unsupported image base')
    disk = Path(r'C:\sgi\run-3.5\3I\SANPK.exe')
    if hashlib.sha256(disk.read_bytes()).hexdigest() != SANPK_SHA:
        raise SystemExit('unsupported shadow SANPK SHA')
    build = Path(__file__).resolve().parent/'ui-build'
    code = (build/'shadow_ui.bin').read_bytes()
    meta = json.loads((build/'shadow_ui.json').read_text())
    if hashlib.sha256(code).hexdigest() != meta['sha256'] or len(code) != meta['size']:
        raise SystemExit('payload hash/length mismatch')
    action = args.ui_action
    element = args.ui_element
    if not args.state:
        raise SystemExit('UI mode requires its own --state file')
    path = Path(args.state)
    state = json.loads(path.read_text()) if path.exists() else {}
    if state and (state.get('schema') != 'p52-shadow-ui-1' or state.get('pid') != pid or
                  state.get('creation') != created or state.get('sanpk_sha256') != SANPK_SHA or
                  state.get('payload_sha256') != meta['sha256'] or state.get('prefix') != prefix):
        raise SystemExit('stale/different UI state; retain it and select a new state file')
    addr = int(state.get('code_addr', '0'), 16)
    if addr and read(addr, len(code)) != code:
        raise SystemExit('installed payload does not match state')

    def summary():
        rows = []
        for name, (site, before, _, _) in SITES.items():
            current = read(site, len(before))
            after = bytes.fromhex(plan(addr, meta['entries'], name)['after']) if addr else None
            status = 'enabled' if after and current == after else 'sealed_or_original' if current == before else 'unexpected'
            rows.append({'element': name, 'site': hex(site), 'status': status,
                         'bytes': current.hex() if current is not None else None})
        return {'schema': 'p52-shadow-ui-check-1', 'pid': pid, 'creation': created,
                'code_addr': hex(addr), 'elements': rows, 'fields': FIELDS,
                'live_acceptance': False, 'world_follow': 'not_measured_by_this_tool'}

    if action == 'check':
        print(json.dumps(summary(), ensure_ascii=False)); return
    if element is None:
        raise SystemExit('select exactly one --ui-element')
    if action == 'plan' or args.dry_run:
        row = plan(addr or 0x200000, meta['entries'], element)
        print(json.dumps({'action': 'plan', 'hypothetical_address': not bool(addr),
                          'change': row, 'live_acceptance': False}, ensure_ascii=False)); return

    k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenThread.restype = w.HANDLE
    k.SuspendThread.argtypes = [w.HANDLE]; k.SuspendThread.restype = w.DWORD
    k.ResumeThread.argtypes = [w.HANDLE]; k.ResumeThread.restype = w.DWORD
    k.GetThreadContext.argtypes = [w.HANDLE, c.POINTER(CONTEXT)]
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]

    def protected(site, raw):
        old = w.DWORD()
        if not k.VirtualProtectEx(handle, c.c_void_p(site), len(raw), 0x40, c.byref(old)):
            raise OSError('VirtualProtectEx '+hex(site))
        try:
            if not write(site, raw):
                raise OSError('WriteProcessMemory '+hex(site))
            if not k.FlushInstructionCache(handle, c.c_void_p(site), len(raw)):
                raise OSError('FlushInstructionCache '+hex(site))
        finally:
            previous = w.DWORD()
            if not k.VirtualProtectEx(handle, c.c_void_p(site), len(raw), old.value, c.byref(previous)):
                raise OSError('restore page protection '+hex(site))

    def save():
        temporary = path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
        os.replace(str(temporary), str(path))

    if not addr:
        if action == 'revert':
            raise SystemExit('no UI installation bound to this process')
        site, before, _, _ = SITES[element]
        if read(site, len(before)) != before:
            raise SystemExit('unexpected entry bytes; no allocation/patch performed')
        addr = k.VirtualAllocEx(handle, None, len(code), 0x3000, 0x04)
        if not addr:
            raise OSError('VirtualAllocEx')
        if not write(addr, code) or read(addr, len(code)) != code:
            raise OSError('payload readback')
        old = w.DWORD()
        if not k.VirtualProtectEx(handle, c.c_void_p(addr), len(code), 0x20, c.byref(old)):
            raise OSError('protect payload RX')
        if not k.FlushInstructionCache(handle, c.c_void_p(addr), len(code)):
            raise OSError('flush payload')
        state.update(schema='p52-shadow-ui-1', pid=pid, creation=created, prefix=prefix,
                     sanpk_sha256=SANPK_SHA, payload_sha256=meta['sha256'], code_addr=hex(addr),
                     elements={}, history=[])
        save()
    row = plan(addr, meta['entries'], element)
    site, before, after = row['site'], bytes.fromhex(row['before']), bytes.fromhex(row['after'])
    if action == 'revert':
        before, after = after, before
    if read(site, len(after)) == after:
        print(json.dumps({'action': 'already', 'element': element, 'state': summary()})); return
    state['intent'] = {'action': action, 'element': element, 'wall': time.time()}; save()
    held = []
    try:
        # Atomic entry detour with all target threads quiesced; no UI calls on
        # an injector thread, no installation-time dialog or synchronization.
        for tid in threads_of(pid):
            th = k.OpenThread(0x4a, False, tid)
            if not th:
                raise OSError('OpenThread '+str(tid))
            if k.SuspendThread(th) == 0xffffffff:
                k.CloseHandle(th); raise OSError('SuspendThread '+str(tid))
            held.append(th)
            context = CONTEXT(); context.ContextFlags = 0x10007
            if not k.GetThreadContext(th, c.byref(context)):
                raise OSError('GetThreadContext '+str(tid))
            if site <= context.Eip < site+len(after):
                raise ValueError('thread at patch entry; retry later')
        patch_transaction([(site, before, after)], read, protected)
        state['elements'][element] = action == 'install'
        state['history'].append(dict(state['intent'], outcome='applied_and_read_back'))
        state.pop('intent', None)
        save()
    except BaseException as exc:
        state['last_error'] = str(exc); save(); raise
    finally:
        failures = []
        for th in reversed(held):
            if k.ResumeThread(th) == 0xffffffff:
                failures.append(int(th))
            k.CloseHandle(th)
        if failures:
            raise RuntimeError('ResumeThread failed: '+str(failures))
    print(json.dumps({'action': action, 'element': element, 'state': summary()}, ensure_ascii=False))
