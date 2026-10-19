"""Resident-driver operations, called ONLY by p51_shadow_inject.py.

The installer binds prefix, binary SHA, PID creation, core, patch bytes and
thread identity. Existing D workers must drain before starting the resident.
Recovery is separate, once-only, and wakes ONLY the core's local UI queue.

v2 hook set (2026-10-18 evening, after the 21:43 opening crash and the 22:2x
E-agent double-drive wedge): see INSTALL_HOOKS below — the native spawner call
and the main-UI wait path are intentionally left ORIGINAL; native spawns are
absorbed at the redirected worker callback instead.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time

MAGIC = 0x31524853  # SHR1
SANPK_SHA = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
OFFSETS = {'owner_tid':0x10, 'in_flight':0x14, 'started':0x18,
           'sync_started':0x1c, 'sync_completed':0x20, 'returned':0x24,
           'rejected':0x28, 'ui_pumps':0x2c, 'status':0x30, 'error':0x34,
           'recovery_allowed_tid':0x64, 'afx_thread_object':0x7c}

# v2 install hook set (2026-10-18 evening, two field incidents):
#  * NOT patched: 0x44474E (native-spawner call). NOP-ing this call site broke
#    the caller's continuation — the hidden ghost AV'd at 0x444786 the moment
#    the host pushed the opening frames (crash records 133/134, 21:43:58).
#    The call stays intact; native spawns are absorbed at the callback.
#  * NOT installed: 0x44A8D9 (main-UI local-wait hook). Its "pump instead of
#    wait" path was the second opening-crash suspect (0x4169B8 NULL -> AV in
#    the 0x444756 pump) and is unnecessary for the fresh-process flow.
#  * The spawned callback (0x44B8BE) is redirected to resident_worker; the
#    owner gate turns every extra spawn into a clean duplicate return — a
#    single driver by construction (no E-class double-drive wedge).
INSTALL_HOOKS = (
    (0x44b8be, '8b4c2404e8', 'resident_worker', 'single-mfc-callback'),
    (0x44b8ca, 'b8881f4f00', 'resident_d_guard', 'exclusive-D-entry'),
    (0x44b924, '6a08899ec4060000', 'resident_sync_begin', 'count-startsync-success'),
    (0x44bb10, '8dbe87000000', 'resident_sync_end', 'count-endsync-return'),
)
PATCHED_SITES = tuple(entry[0] for entry in INSTALL_HOOKS)
# v2.1: post-round dwell. The worker yields this long between rounds so the
# game's own per-frame/render loop can run (2026-10-18 live round 2: data kept
# pace at year 201 while the client screen froze at 200 spring — the worker
# re-entered D almost continuously). Human rounds take >=10 s, so 1.5 s costs
# nothing. Written into the blob at +0x1b0 and read by the patched wait site
# (patch_resident_v21.py, gadget at bin offset 0x400); tunable per install.
DWELL_MS = 1500
# v2.2: the player's phase-end sender (static, 2026-10-18 late):
# __thiscall EndPhase(phase_obj) at 0x49b181 — reads only [this+0x3c]==G
# (G=core-0x912) and [this+0x8a6]==0 (not ended this round), builds
# CSanInetPhaseEndCmd (X=[core+0x6c0] my_slot, V=0x444857(core)=remaining round
# time) and submits it via 0x446482(G,cmd) into G's local command queue.
# The worker calls it once per changed round deadline (G+0x6c) through a fake
# `this` object (blob-0xa00 = code page +0x600).
ENDPHASE_SENDER = 0x49b181


def jump(source, target, size):
    if size < 5:
        raise ValueError('short hook')
    return b'\xe9'+struct.pack('<i', target-source-5)+b'\x90'*(size-5)


def active_d_threads(capture):
    """Actual frame chains, not stale raw-stack code-like integers."""
    return [t['tid'] for t in capture['threads'] if any(
        0x44b8be <= int(f['return'],16) < 0x44bba5
        for f in t.get('frames', []))]


def validate_capture(capture, pid, creation, age=30):
    if capture.get('pid') != pid or capture.get('creation') != creation:
        raise ValueError('capture process identity mismatch')
    if not 0 <= time.time()-capture['finished_wall'] <= age:
        raise ValueError('capture stale; acquire a fresh all-thread capture')
    if any(t.get('error') or t.get('resume_result') == 0xffffffff
           for t in capture['threads']):
        raise ValueError('incomplete thread capture')


def build_blob(core, main_tid, pointers, flag, receipt, dwell_ms=DWELL_MS):
    b = bytearray(0x200)
    values = {0:MAGIC, 4:1, 8:core, 0xc:main_tid,
              0x38:pointers['Sleep'], 0x3c:pointers['GetCurrentThreadId'],
              0x40:pointers['GetFileAttributesA'], 0x44:0x44b8ca,
              0x50:pointers['WaitForSingleObject'], 0x54:pointers['GetTickCount'],
              0x58:0x44b88e, 0x5c:0x444756,
              0x68:pointers['CreateFileA'], 0x6c:pointers['WriteFile'], 0x74:0xffffffff,
              0x1b0:int(dwell_ms), 0x1c0:ENDPHASE_SENDER}
    for off, val in values.items():
        struct.pack_into('<I', b, off, val)
    for off, path in ((0x80,flag), (0x100,receipt)):
        raw = path.encode('ascii')
        if len(raw) >= 128:
            raise ValueError('resident path exceeds 127 ASCII bytes')
        b[off:off+len(raw)] = raw
    return bytes(b)


def run(args, c, w, k, h, pid, created, read, write):
    from p51_shadow_inject import find_module, process_creation
    from thread_probe import CONTEXT, threads_of
    if 'prefix-fengye-shadow' not in os.environ.get('WINEPREFIX',''):
        raise SystemExit('resident requires explicit prefix-fengye-shadow WINEPREFIX')
    exe = Path(r'C:\sgi\run-3.5\3I\SANPK.exe')
    if hashlib.sha256(exe.read_bytes()).hexdigest() != SANPK_SHA:
        raise SystemExit('shadow SANPK disk SHA mismatch (no disk files changed)')
    sanpk = find_module(pid, 'SANPK.exe')
    if not sanpk or sanpk['base'] != 0x400000:
        raise SystemExit('unsupported SANPK image base')
    if not args.state:
        raise SystemExit('--state required')
    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    same = state.get('pid') == pid and state.get('creation') == created
    blob = int(state.get('blob_addr','0'),16) if same else 0
    installed = bool(blob and read(blob,4) == struct.pack('<I',MAGIC))

    k.OpenThread.argtypes = [w.DWORD,w.BOOL,w.DWORD]
    k.OpenThread.restype = w.HANDLE
    k.SuspendThread.argtypes = [w.HANDLE]
    k.SuspendThread.restype = w.DWORD
    k.ResumeThread.argtypes = [w.HANDLE]
    k.ResumeThread.restype = w.DWORD
    k.GetThreadContext.argtypes = [w.HANDLE,c.POINTER(CONTEXT)]
    k.VirtualProtectEx.argtypes = [w.HANDLE,c.c_void_p,c.c_size_t,w.DWORD,c.POINTER(w.DWORD)]
    k.FlushInstructionCache.argtypes = [w.HANDLE,c.c_void_p,c.c_size_t]

    def u32(addr):
        raw = read(addr,4)
        if raw is None:
            raise ValueError('unreadable dword '+hex(addr))
        return struct.unpack('<I',raw)[0]

    def save():
        temp = state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(state,indent=2)+'\n')
        os.replace(str(temp),str(state_path))

    def protected(addr, data):
        old = w.DWORD()
        if not k.VirtualProtectEx(h,c.c_void_p(addr),len(data),0x40,c.byref(old)):
            raise OSError('VirtualProtectEx '+hex(addr))
        try:
            if not write(addr,data) or read(addr,len(data)) != data:
                raise OSError('patch readback '+hex(addr))
            if not k.FlushInstructionCache(h,c.c_void_p(addr),len(data)):
                raise OSError('FlushInstructionCache')
        finally:
            unused = w.DWORD()
            k.VirtualProtectEx(h,c.c_void_p(addr),len(data),old.value,c.byref(unused))

    def transaction(changes):
        held=[];done=[]
        try:
            for tid in threads_of(pid):
                th=k.OpenThread(0x4a,False,tid)
                if not th:
                    raise OSError('OpenThread '+str(tid))
                prior=k.SuspendThread(th)
                if prior == 0xffffffff:
                    k.CloseHandle(th)
                    raise OSError('SuspendThread '+str(tid))
                held.append(th)
                ctx=CONTEXT();ctx.ContextFlags=0x10007
                if not k.GetThreadContext(th,c.byref(ctx)):
                    raise OSError('GetThreadContext '+str(tid))
                if any(a <= ctx.Eip < a+len(after) for a,before,after in changes):
                    raise ValueError('thread executing a patch site; retry capture')
            # Check every byte before performing any mutation.
            for a,before,after in changes:
                if read(a,len(before)) != before:
                    raise ValueError('unexpected original bytes '+hex(a))
            for a,before,after in changes:
                protected(a,after);done.append((a,before,after))
        except BaseException:
            for a,before,after in reversed(done):
                protected(a,before)
            raise
        finally:
            for th in reversed(held):
                k.ResumeThread(th);k.CloseHandle(th)

    action = args.resident_action
    if action == 'check':
        result = {'installed':installed,'pid':pid,'creation':created,'state':state}
        if installed:
            result['counters']={n:u32(blob+off) for n,off in OFFSETS.items()}
            result['core_fields']={hex(off):u32(int(state['core'],16)+off)
                                   for off in (-0x8aa,-0x8a6,0x660,0x678,0x6bc)}
            result['patches_ok']=all(read(int(p['address'],16),len(bytes.fromhex(p['after'])))
                                   == bytes.fromhex(p['after']) for p in state['patches'])
        print(json.dumps(result));return

    if action == 'install':
        if installed:
            raise SystemExit('resident already installed; use check/start, never --force')
        if args.force:
            raise SystemExit('--force is forbidden for resident')
        if not args.flag or not args.receipt or not args.agent_bin:
            raise SystemExit('resident install needs --flag --receipt --agent-bin')
        meta = json.loads(Path(args.agent_bin).with_suffix('.json').read_text())
        code = Path(args.agent_bin).read_bytes()
        if meta['sha256'] != hashlib.sha256(code).hexdigest() or len(code)>0x1000:
            raise SystemExit('resident payload manifest mismatch')
        legacy = json.loads(Path(args.legacy_state).read_text()) if args.legacy_state else None
        if legacy:
            if legacy['pid'] != pid or legacy['creation'] != created:
                raise SystemExit('legacy identity mismatch')
            core=int(legacy['core'],16)
        elif args.core:
            core=int(args.core,0)
        else:
            import sys
            os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
            sys.path.insert(0,args.bridge)
            from collector import Collector
            col=Collector(pid)
            try:
                col.bind();core=int(col.core)
            finally:
                col.close()
        if u32(0x53bb30) != core:
            raise SystemExit('core anchor mismatch')
        # The main window is owned by the UI thread, not by a worker.
        user = c.WinDLL('user32', use_last_error=True)
        callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        # The game's main window uses its own registered class name (not MFC's
        # default "Afx:"), so pick the owner thread of the largest visible
        # non-infrastructure top-level window instead of matching a class
        # prefix. Infrastructure windows observed live: tooltips_class32, IME,
        # Wine IME, NetHookCoreWindow2012.
        SKIP_CLASSES = ('tooltips_class32', 'IME', 'Wine IME', 'NetHookCoreWindow2012')
        user.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        candidates = []

        @callback
        def enum_window(hwnd, param):
            wp = w.DWORD(); tid = user.GetWindowThreadProcessId(hwnd, c.byref(wp))
            if wp.value != pid or not user.IsWindowVisible(hwnd):
                return True
            name = c.create_unicode_buffer(256)
            user.GetClassNameW(hwnd, name, 256)
            if name.value in SKIP_CLASSES:
                return True
            rc = w.RECT()
            if not user.GetWindowRect(hwnd, c.byref(rc)):
                return True
            area = max(0, rc.right - rc.left) * max(0, rc.bottom - rc.top)
            candidates.append((area, tid, name.value))
            return True

        user.EnumWindows(enum_window, 0)
        if not candidates:
            raise SystemExit('no visible SANPK main window found')
        candidates.sort(key=lambda t: t[0], reverse=True)
        area, main_tid, cls = candidates[0]
        big = {c[1] for c in candidates if c[0] > area // 4}
        if len(big) != 1:
            raise SystemExit('ambiguous SANPK main window owners: ' + str(candidates))
        target_k=find_module(pid,'kernel32.dll')
        if not target_k or target_k['base'] != k.GetModuleHandleW('kernel32.dll'):
            raise SystemExit('kernel32 mapping mismatch')
        pointers={n:int(k.GetProcAddress(k.GetModuleHandleW('kernel32.dll'),n.encode()) or 0)
                  for n in ('Sleep','GetCurrentThreadId','GetFileAttributesA',
                            'WaitForSingleObject','GetTickCount','CreateFileA','WriteFile')}
        if not all(pointers.values()):
            raise SystemExit('missing kernel32 export')
        addr=k.VirtualAllocEx(h,None,0x2000,0x3000,0x40)
        if not addr:
            raise SystemExit('VirtualAllocEx failed')
        blob=addr+0x1000
        entries={n:addr+off for n,off in meta['entries'].items()}
        data=build_blob(core,main_tid,pointers,args.flag,args.receipt)
        if not write(addr,code) or not write(blob,data) or read(addr,len(code))!=code:
            raise SystemExit('resident payload readback failed')
        specs=list(INSTALL_HOOKS)
        changes=[]
        for a,orig,entry,label in specs:
            before=bytes.fromhex(orig)
            after=jump(a,entries[entry],len(before)) if entry else b'\x90'*len(before)
            changes.append((a,before,after))
        if legacy:
            oldaddr=int(legacy['code_addr'],16)
            oldcode=read(oldaddr,legacy['code_size'])
            if hashlib.md5(oldcode).hexdigest() != 'eaaecd0d296bf1afe86508d094caceef':
                raise SystemExit('legacy E SHA/MD5 differs; do not guess offsets')
            changes.append((oldaddr+0x1ab,bytes.fromhex('8b46308b00'),
                            jump(oldaddr+0x1ab,entries['resident_legacy_park'],5)))
            changes.append((oldaddr+0x213,bytes.fromhex('ff5618'),b'\x90'*3))
        if args.dry_run:
            print(json.dumps({'dry_run':True,'core':hex(core),'main_tid':main_tid,
                              'patches':[hex(a) for a,b,n in changes]}));return
        transaction(changes)
        state={'schema':'p51-shadow-resident-1','hookset':'v2','pid':pid,'creation':created,
               'core':hex(core),'main_tid':main_tid,'code_addr':hex(addr),'blob_addr':hex(blob),
               'entries':{n:hex(a) for n,a in entries.items()},'sha256':meta['sha256'],
               'flag':args.flag,'receipt':args.receipt,'installed_wall':time.time(),
               'patches':[{'address':hex(a),'before':b.hex(),'after':n.hex()}
                          for a,b,n in changes]}
        save();print(json.dumps(state));return

    if not installed:
        raise SystemExit('resident not installed in this exact process')
    if args.force:
        raise SystemExit('--force is forbidden for resident')
    core=int(state['core'],16)
    entries={n:int(a,16) for n,a in state['entries'].items()}
    if action in ('start','recover','release'):
        if not args.recover_capture:
            raise SystemExit('--recover-capture required for a fresh all-thread proof')
        capture=json.loads((Path(args.recover_capture)/'capture.json').read_text())
        validate_capture(capture,pid,created)
        if {t['tid'] for t in capture['threads']} != set(threads_of(pid)):
            raise SystemExit('thread set changed; acquire a new capture')
    if action == 'start':
        if state.get('started_wall') or u32(blob+0x10):
            raise SystemExit('resident already started; never spawn twice')
        if active_d_threads(capture):
            raise SystemExit('live D worker exists; never reset f6bc/spawn over it')
        if u32(core+0x660) != 0 or u32(core+0x6bc) not in (0,2):
            raise SystemExit('UI queue / completion not drained')
        # With no live D this merely lets the original UI acknowledge flag=2.
        transaction([(core-0x8aa,read(core-0x8aa,4),struct.pack('<I',3)),
                     (blob+0x64,read(blob+0x64,4),b'\0'*4)])
        state['started_wall']=time.time();state['start_intent']=True;save()
        tid=w.DWORD()
        th=k.CreateRemoteThread(h,None,0,c.c_void_p(entries['resident_boot']),
                               c.c_void_p(blob),0,c.byref(tid))
        if not th:
            state['start_error']='CreateRemoteThread failed; inspect before retry';save()
            raise SystemExit(state['start_error'])
        k.CloseHandle(th)
        state['bootstrap_tid']=tid.value;save()
        print(json.dumps({'started':True,'bootstrap_tid':tid.value,'state':state}));return
    if action == 'recover':
        if state.get('recovery'):
            raise SystemExit('warm recovery is once-only; no duplicate wake')
        dthreads=active_d_threads(capture)
        if args.release_tid not in dthreads:
            raise SystemExit('--release-tid must identify an observed old D worker')
        slots=[];waiters=[]
        for t in capture['threads']:
            frames=[f for f in t.get('frames',[]) if int(f['return'],16)==0x44a8ea]
            if frames:
                if len(frames)!=1 or t['tid'] not in dthreads+[state['main_tid']]:
                    raise SystemExit('unexpected UI queue waiter')
                slots.append((int(frames[0]['ebp'],16)+4,struct.pack('<I',0x44a8ea),
                              struct.pack('<I',entries['resident_ui_return'])))
                waiters.append(t['tid'])
        if sorted(waiters) != sorted(dthreads+[state['main_tid']]):
            raise SystemExit('not all D/UI threads are proven local-queue waiters')
        net=find_module(pid,'Koeinm.dll')['base']+0x12170
        event=u32(core+0x678);abort_event=u32(net+0x84a4)
        if not event or event==0xffffffff or event==abort_event:
            raise SystemExit('UI event invalid or aliases forbidden abort event')
        slots.append((blob+0x64,read(blob+0x64,4),struct.pack('<I',args.release_tid)))
        transaction(slots)
        state['recovery']={'wall':time.time(),'waiters':waiters,'D_threads':dthreads,
            'allowed_tid':args.release_tid,'ui_event':event,'abort_event_distinct':True,
            'stack_return_slots':[hex(a) for a,b,n in slots[:-1]],'wake_intent':True}
        save()
        # The event handle belongs to the TARGET's handle table; a plain
        # SetEvent from this process fails (wake_rc=0 was observed live on the
        # first attempt). Execute SetEvent inside the target via a remote
        # thread instead: kernel32 is mapped identically in both processes
        # (checked above), and the target's own handle table resolves it.
        k.CreateRemoteThread.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t,
                                         c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.GetExitCodeThread.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        set_event_addr = int(k.GetProcAddress(k.GetModuleHandleW('kernel32.dll'),
                                              b'SetEvent') or 0)
        if not set_event_addr:
            raise SystemExit('cannot resolve SetEvent for the remote wake')
        rtid = w.DWORD()
        rth = k.CreateRemoteThread(h, None, 0, c.c_void_p(set_event_addr),
                                   c.c_void_p(event), 0, c.byref(rtid))
        wake_rc = 0
        if rth:
            k.WaitForSingleObject(rth, 5000)
            rcode = w.DWORD()
            k.GetExitCodeThread(rth, c.byref(rcode))
            wake_rc = int(rcode.value)
            k.CloseHandle(rth)
        state['recovery']['wake_rc'] = wake_rc
        state['recovery']['wake_via'] = 'remote-thread SetEvent (target handle table)'
        state['recovery']['remote_wake_tid'] = int(rtid.value)
        save()
        print(json.dumps(state['recovery']))
        return
    if action == 'release':
        prior=u32(blob+0x64)
        if not state.get('recovery') or prior in threads_of(pid):
            raise SystemExit('previous recovery worker still alive; do not overlap')
        if args.release_tid not in active_d_threads(capture):
            raise SystemExit('next worker not present in actual D frame chains')
        transaction([(blob+0x64,read(blob+0x64,4),struct.pack('<I',args.release_tid))])
        state.setdefault('recovery_releases',[]).append({'wall':time.time(),
                        'previous_tid':prior,'next_tid':args.release_tid})
        save();print(json.dumps(state['recovery_releases'][-1]));return
    raise SystemExit('unknown resident action')
