"""Optional typed bitmap-paint switches; never called by normal arming.

Only an RX cave and 4afc5c are written. Independent bits select immutable code
entries; no game object/bitmap/network data is patched. Caves are never freed
in a live process. One identity-bound state and one element per transaction.
"""
import hashlib
import json
import os
from pathlib import Path
import time

from p52_shadow_ui import SANPK_SHA, detour, patch_transaction
from p53_hidden_draw_build import GROUPS, SITE, ORIGINAL


def mask_for(elements):
    result = 0
    for element in elements:
        result |= GROUPS[element][0]
    return result


def run(args, c, w, k, handle, pid, created, read, write):
    from p51_shadow_inject import find_module
    from thread_probe import CONTEXT, threads_of
    prefix = os.environ.get('WINEPREFIX', '').rstrip('/\\')
    if Path(prefix).name != 'prefix-fengye-shadow':
        raise SystemExit('explicit prefix-fengye-shadow required')
    module = find_module(pid, 'SANPK.exe')
    disk = Path(r'C:\sgi\run-3.5\3I\SANPK.exe')
    if (not created or not module or module['base'] != 0x400000 or
            hashlib.sha256(disk.read_bytes()).hexdigest() != SANPK_SHA):
        raise SystemExit('unsupported process/image identity')
    build = Path(__file__).resolve().parent/'hidden-build'
    raw = (build/'hidden_draw.bin').read_bytes()
    meta = json.loads((build/'hidden_draw.json').read_text())
    if hashlib.sha256(raw).hexdigest() != meta['sha256'] or len(raw) != meta['size']:
        raise SystemExit('hidden payload hash/size mismatch')
    if not args.state:
        raise SystemExit('a separate --state path is required')
    path = Path(args.state)
    state = json.loads(path.read_text()) if path.exists() else {}
    identity = dict(schema='p53-hidden-draw-state-1', pid=pid, creation=created,
                    prefix=prefix, sanpk_sha256=SANPK_SHA, payload_sha256=meta['sha256'])
    if state and any(state.get(key) != value for key, value in identity.items()):
        raise SystemExit('stale/different hidden state; preserve it and use a new path')
    addr = int(state.get('code_addr', '0'), 16)
    mask = state.get('mask', 0)
    if type(mask) is not int or not 0 <= mask < (1 << len(GROUPS)) or (mask and not addr):
        raise SystemExit('invalid hidden state')
    if addr and read(addr, len(raw)) != raw:
        raise SystemExit('hidden cave differs from recorded payload')

    def entry(value, base=None):
        if value == 0:
            return ORIGINAL
        return detour(SITE, (addr if base is None else base)+meta['entries']['hidden_%d' % value], 0xe8)

    def summary():
        current = read(SITE, 5)
        matches = current == entry(mask)
        return dict(schema='p53-hidden-draw-check-1', pid=pid, creation=created,
                    code_addr=hex(addr), mask=mask, site=hex(SITE),
                    bytes=current.hex() if current else None, consistent=matches,
                    elements=[dict(element=name, status=('enabled' if mask & bit else 'sealed_or_original')
                                   if matches else 'unexpected') for name, (bit, _) in GROUPS.items()],
                    writes='code cave / paint CALL; no world writes', live_acceptance=False)

    action, name = args.ui_action, args.ui_element
    if action == 'check':
        print(json.dumps(summary(), ensure_ascii=False)); return
    if name not in GROUPS:
        raise SystemExit('select exactly one hidden element')
    bit = GROUPS[name][0]
    next_mask = mask & ~bit if action == 'revert' else mask | bit
    if not summary()['consistent']:
        raise SystemExit('paint CALL differs from state; no write performed')
    if action == 'plan' or args.dry_run:
        print(json.dumps(dict(action='plan', element=name, before_mask=mask,
              after_mask=next_mask, site=hex(SITE), before=entry(mask).hex(),
              after=entry(next_mask, addr or 0x200000).hex(),
              hypothetical_address=not bool(addr), live_acceptance=False))); return
    if next_mask == mask:
        print(json.dumps(dict(action='already', element=name, state=summary()))); return

    k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenThread.restype = w.HANDLE
    k.SuspendThread.argtypes = [w.HANDLE]; k.SuspendThread.restype = w.DWORD
    k.ResumeThread.argtypes = [w.HANDLE]; k.ResumeThread.restype = w.DWORD
    k.GetThreadContext.argtypes = [w.HANDLE, c.POINTER(CONTEXT)]
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]

    def save():
        temporary = path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
        os.replace(str(temporary), str(path))

    def protected(site, content):
        previous = w.DWORD()
        if not k.VirtualProtectEx(handle, c.c_void_p(site), len(content), 0x40, c.byref(previous)):
            raise OSError('VirtualProtectEx')
        try:
            if not write(site, content) or not k.FlushInstructionCache(handle, c.c_void_p(site), len(content)):
                raise OSError('write/flush failed at '+hex(site))
        finally:
            ignored = w.DWORD()
            if not k.VirtualProtectEx(handle, c.c_void_p(site), len(content), previous.value, c.byref(ignored)):
                raise OSError('restore page protection')

    if not addr:
        addr = k.VirtualAllocEx(handle, None, len(raw), 0x3000, 0x04)
        if not addr or not write(addr, raw) or read(addr, len(raw)) != raw:
            raise OSError('allocate/write cave')
        previous = w.DWORD()
        if (not k.VirtualProtectEx(handle, c.c_void_p(addr), len(raw), 0x20, c.byref(previous)) or
                not k.FlushInstructionCache(handle, c.c_void_p(addr), len(raw))):
            raise OSError('protect/flush RX cave')
        state.update(identity, code_addr=hex(addr), mask=0, history=[]); save()
    before, after = entry(mask), entry(next_mask)
    state['intent'] = dict(action=action, element=name, wall=time.time(), before_mask=mask, after_mask=next_mask)
    save()
    held = []
    try:
        tids = threads_of(pid)
        if not tids:
            raise OSError('no target threads')
        for tid in tids:
            th = k.OpenThread(0x4a, False, tid)
            if not th:
                raise OSError('OpenThread '+str(tid))
            if k.SuspendThread(th) == 0xffffffff:
                k.CloseHandle(th); raise OSError('SuspendThread '+str(tid))
            held.append(th)
            context = CONTEXT(); context.ContextFlags = 0x10007
            if not k.GetThreadContext(th, c.byref(context)):
                raise OSError('GetThreadContext')
            if SITE <= context.Eip < SITE+5:
                raise ValueError('thread at paint CALL; retry later')
        patch_transaction([(SITE, before, after)], read, protected)
        mask = next_mask
        state['mask'] = mask
        state['history'].append(dict(state.pop('intent'), outcome='applied_and_read_back'))
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
    print(json.dumps(dict(action=action, element=name, state=summary()), ensure_ascii=False))
