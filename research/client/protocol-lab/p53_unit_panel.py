"""Optional, identity-bound P53 runtime site/cave transaction via P51.

Install is inert. Watch explicitly leases inspection for 2 seconds at a time.
No remote thread, native order, world write or synchronization event.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from p52_shadow_ui import SANPK_SHA, patch_transaction, detour

SITE, BEFORE, MAGIC = 0x4988e3, bytes.fromhex('398eda080000'), 0x33505553
MAILBOX_OFFSET, MAILBOX_SIZE = 0x1000, 0x80


def make_mailbox():
    blob = bytearray(MAILBOX_SIZE)
    struct.pack_into('<I', blob, 0, MAGIC)
    return bytes(blob)


def click_from_mailbox(raw):
    if len(raw) != MAILBOX_SIZE or struct.unpack_from('<I', raw)[0] != MAGIC:
        raise ValueError('invalid click mailbox')
    values = struct.unpack_from('<20I', raw)
    if values[3] == 0 or values[3] & 1:
        return None
    return dict(version=values[3], view=values[4], document=values[5], core=values[6],
                hwnd=values[7], point=list(struct.unpack_from('<2i', raw, 0x20)),
                origin=list(struct.unpack_from('<2i', raw, 0x28)),
                dimensions=list(struct.unpack_from('<4i', raw, 0x30)),
                clock_hex=raw[0x40:0x4c].hex(), tick=values[19])


def tick_age(now, then):
    return (now-then) & 0xffffffff


def run(args, c, w, k, handle, pid, created, read, write):
    from p51_shadow_inject import find_module
    from thread_probe import CONTEXT, threads_of
    prefix = os.environ.get('WINEPREFIX', '').rstrip('/\\')
    if Path(prefix).name != 'prefix-fengye-shadow':
        raise SystemExit('unit-panel requires explicit prefix-fengye-shadow')
    module = find_module(pid, 'SANPK.exe')
    if (not created or not module or module['base'] != 0x400000 or
            hashlib.sha256(Path(r'C:\sgi\run-3.5\3I\SANPK.exe').read_bytes()).hexdigest() != SANPK_SHA):
        raise SystemExit('unit-panel image identity mismatch')
    directory = Path(__file__).resolve().parent/'unit-panel-build'
    code = (directory/'unit_click.bin').read_bytes()
    meta = json.loads((directory/'unit_click.json').read_text())
    if (hashlib.sha256(code).hexdigest() != meta['sha256'] or len(code) != meta['size']
            or meta['mailbox_offset'] != MAILBOX_OFFSET):
        raise SystemExit('unit-panel payload hash/layout mismatch')
    if not args.state:
        raise SystemExit('unit-panel requires a separate --state file')
    path = Path(args.state)
    state = json.loads(path.read_text()) if path.exists() else {}
    expected = dict(schema='p53-unit-panel-state-1', pid=pid, creation=created,
                    prefix=prefix, sanpk_sha256=SANPK_SHA, payload_sha256=meta['sha256'])
    if state and any(state.get(key) != value for key, value in expected.items()):
        raise SystemExit('stale unit-panel state; retain and choose a new file')
    address = int(state.get('code_addr', '0'), 16)
    mailbox = address+MAILBOX_OFFSET if address else 0
    if address and (read(address, len(code)) != code or read(mailbox, 4) != struct.pack('<I', MAGIC)):
        raise SystemExit('payload/mailbox differs from bound state')
    after = detour(SITE, address)+b'\x90' if address else None
    action = args.panel_action

    def summary():
        current = read(SITE, len(BEFORE))
        status = 'installed' if after and current == after else 'original' if current == BEFORE else 'unexpected'
        raw = read(mailbox, MAILBOX_SIZE) if mailbox else None
        return dict(schema='p53-unit-panel-check-1', pid=pid, creation=created,
                    site=hex(SITE), status=status, bytes=current.hex() if current else None,
                    code_addr=hex(address), mailbox=hex(mailbox),
                    enabled_word=struct.unpack_from('<I', raw, 4)[0] if raw else 0,
                    default_enabled=False, live_acceptance=False)

    if action == 'check':
        print(json.dumps(summary())); return
    if action == 'plan' or args.dry_run:
        print(json.dumps(dict(action='plan', site=hex(SITE), before=BEFORE.hex(),
                    after=(after or detour(SITE, 0x200000)+b'\x90').hex(),
                    hypothetical_address=not bool(address), activation=False))); return
    if action == 'watch':
        if not address or read(SITE, len(BEFORE)) != after:
            raise SystemExit('install the inert click site before watch')
        from p53_unit_watch import watch
        watch(args, c, w, k, pid, created, read, write, mailbox, after)
        return

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

    def protected(site, raw):
        old = w.DWORD()
        if not k.VirtualProtectEx(handle, c.c_void_p(site), len(raw), 0x40, c.byref(old)):
            raise OSError('protect site')
        try:
            if not write(site, raw) or not k.FlushInstructionCache(handle, c.c_void_p(site), len(raw)):
                raise OSError('write/flush site')
        finally:
            previous = w.DWORD()
            if not k.VirtualProtectEx(handle, c.c_void_p(site), len(raw), old.value, c.byref(previous)):
                raise OSError('restore site protection')

    if not address:
        if action != 'install' or read(SITE, len(BEFORE)) != BEFORE:
            raise SystemExit('original site required before allocation')
        address = k.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x04)
        if not address:
            raise OSError('allocate unit-panel cave')
        mailbox = address+MAILBOX_OFFSET
        if (not write(address, code) or read(address, len(code)) != code or
                not write(mailbox, make_mailbox()) or read(mailbox, MAILBOX_SIZE) != make_mailbox()):
            raise OSError('unit-panel allocation readback')
        old = w.DWORD()
        if (not k.VirtualProtectEx(handle, c.c_void_p(address), 0x1000, 0x20, c.byref(old))
                or not k.FlushInstructionCache(handle, c.c_void_p(address), len(code))):
            raise OSError('unit-panel payload protect/flush')
        state.update(expected, code_addr=hex(address), history=[])
        save()
        after = detour(SITE, address)+b'\x90'
    source, destination = (after, BEFORE) if action == 'revert' else (BEFORE, after)
    if action == 'revert':
        # The mailbox is private state. Stop leases before restoring the entry.
        if not write(mailbox+4, b'\0'*8) or read(mailbox+4, 8) != b'\0'*8:
            raise OSError('disable inspection lease')
    if read(SITE, len(BEFORE)) == destination:
        print(json.dumps(dict(action='already', state=summary()))); return
    state['intent'] = dict(action=action, wall=time.time()); save()
    held = []
    try:
        for tid in threads_of(pid):
            thread = k.OpenThread(0x4a, False, tid)
            if not thread:
                raise OSError('OpenThread '+str(tid))
            if k.SuspendThread(thread) == 0xffffffff:
                k.CloseHandle(thread); raise OSError('SuspendThread '+str(tid))
            held.append(thread)
            context = CONTEXT(); context.ContextFlags = 0x10007
            if not k.GetThreadContext(thread, c.byref(context)):
                raise OSError('GetThreadContext '+str(tid))
            if SITE <= context.Eip < SITE+len(BEFORE):
                raise ValueError('thread at patch site; retry later')
        patch_transaction([(SITE, source, destination)], read, protected)
        state['history'].append(dict(state['intent'], result='applied_and_read_back'))
        state.pop('intent', None); save()
    except BaseException as exc:
        state['last_error'] = str(exc); save(); raise
    finally:
        failed = []
        for thread in reversed(held):
            if k.ResumeThread(thread) == 0xffffffff:
                failed.append(int(thread))
            k.CloseHandle(thread)
        if failed:
            raise RuntimeError('ResumeThread failed: '+str(failed))
    print(json.dumps(dict(action=action, state=summary())))
