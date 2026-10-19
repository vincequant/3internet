#!/usr/bin/env python3
"""P51 shadow injector — runs under Win32 py32 inside the shadow Wine prefix.

Injects the once-only D8 agent (built by p51_shadow_agent_build.py) into the
shadow client's SANPK.exe. Everything the agent needs is passed as one data
blob: kernel32 function pointers, Koeinm module base / netobj / export slots,
and the trigger/receipt file paths. The agent itself (339 bytes, no imports,
no relocations) polls, gates on IsConnected + pre-start state, performs ONE
reliable submit 0x4C80 -> 0x4B60, writes a binary receipt, and never retries.

Discipline: single shot. The injector refuses to run when a receipt already
exists (operator must clear state explicitly with --reset) and refuses to
double-inject one process (state file + blob magic probe), unless --force.

Usage (under wine py32):
  python.exe p51_shadow_inject.py \
      --target-name SANPK.exe \
      --flag    'Z:\\Users\\vk\\sgi-fengye-lab\\shadow\\shadow_go.flag' \
      --receipt 'Z:\\Users\\vk\\sgi-fengye-lab\\shadow\\shadow_d8_receipt.bin' \
      --state   'Z:\\Users\\vk\\sgi-fengye-lab\\shadow\\inject-state.json' \
      [--dry-run] [--check] [--force] [--smoke]

Pure-python helpers (parse_exports / build_blob) are import-safe on macOS and
covered by test_p51_shadow.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

MAGIC = 0x31474853          # 'SHG1' blob marker (bytes 53 48 47 31)
MAGIC2 = 0x32474853         # 'SHG2' receipt marker
BLOB_SIZE = 0x134
KOEINM_SHA_ORIGINAL = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
KOEINM_SHA_R2 = '28476038d67d2f330860d88b3dd0be53594354107cfd26ecb36ddf8512d111d8'
KOEINM_SHA_ALLOWED = (KOEINM_SHA_ORIGINAL, KOEINM_SHA_R2)
RVA_IS_CONNECTED = 0x20B0   # golden: _NetMsg_IsConnected@0
RVA_GET_IP = 0x22B0         # golden: _NetMsg_GetIPAddress@4
RVA_ACCEPT_EXIT = 0x2380    # golden: _NetMsg_AcceptEXIT@4
RVA_4C80 = 0x4C80           # GetHostOrSelfID (cdecl)
RVA_4B60 = 0x4B60           # reliable submit (cdecl)
NETOBJ_RVA = 0x12170
STATE_OFF = 0x84A8          # netobj pre-start state (== 1)
DEFAULT_POINTER_NAMES = ('GetFileAttributesA', 'CreateFileA', 'WriteFileA', 'CloseHandle',
                         'Sleep', 'GetTickCount', 'is_connected', 'get_ip',
                         'submit_4c80', 'submit_4b60')
ACCEPTEXIT_POINTER_NAMES = ('GetFileAttributesA', 'CreateFileA', 'WriteFileA', 'CloseHandle',
                            'Sleep', 'GetTickCount', 'is_connected', 'get_ip', 'accept_exit')


# ---------------------------------------------------------------- pure helpers

def parse_exports(path):
    """Return {name: rva} for a PE32 DLL. Pure; used for Koeinm export RVAs."""
    data = Path(path).read_bytes()
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('not a PE')
    opt = pe + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    if magic != 0x10B:
        raise ValueError('not PE32')
    dd = opt + 96
    edir_rva, edir_sz = struct.unpack_from('<II', data, dd)
    if not edir_rva or not edir_sz:
        raise ValueError('no export directory')
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    optsz = struct.unpack_from('<H', data, pe + 20)[0]
    secs = []
    for i in range(nsec):
        off = opt + optsz + i * 40
        vs, va, rs, rp = struct.unpack_from('<IIII', data, off + 8)
        secs.append((va, vs, rp, rs))

    def rva2off(rva):
        for va, vs, rp, rs in secs:
            if va <= rva < va + max(vs, rs):
                return rp + (rva - va)
        return None

    eo = rva2off(edir_rva)
    nfunc = struct.unpack_from('<I', data, eo + 0x14)[0]
    nnames = struct.unpack_from('<I', data, eo + 0x18)[0]
    aof, aon, aoo = struct.unpack_from('<III', data, eo + 0x1C)
    fo, noo, oo = rva2off(aof), rva2off(aon), rva2off(aoo)
    out = {}
    for i in range(nnames):
        name_rva = struct.unpack_from('<I', data, noo + i * 4)[0]
        name_off = rva2off(name_rva)
        name = data[name_off:data.index(b'\0', name_off)].decode('latin1')
        ordinal = struct.unpack_from('<H', data, oo + i * 2)[0]
        if ordinal < nfunc:
            out[name] = struct.unpack_from('<I', data, fo + ordinal * 4)[0]
    return out


def build_blob(magic, netobj, pointers, flag_path, receipt_path, pointer_names=None):
    """Layout must match the agent assembly exactly (offsets in manifest.json)."""
    names = pointer_names if pointer_names is not None else DEFAULT_POINTER_NAMES
    blob = bytearray(BLOB_SIZE)

    def put32(off, val):
        struct.pack_into('<I', blob, off, val & 0xFFFFFFFF)

    def put_path(off, text, limit=128):
        raw = text.encode('utf-8')
        if len(raw) >= limit:
            raise ValueError('path too long')
        blob[off:off + len(raw)] = raw

    put32(0x00, magic)
    put32(0x04, 0)
    put32(0x08, netobj)
    for i, key in enumerate(names):
        if key not in pointers:
            raise ValueError('missing pointer: ' + key)
        put32(0x0C + i * 4, pointers[key])
    put_path(0x34, flag_path)
    put_path(0xB4, receipt_path)
    return bytes(blob)


def blob_summary(blob):
    return {
        'magic': '0x%08x' % struct.unpack_from('<I', blob, 0)[0],
        'netobj': '0x%08x' % struct.unpack_from('<I', blob, 8)[0],
        'pointers': ['0x%08x' % struct.unpack_from('<I', blob, 0x0C + i * 4)[0] for i in range(10)],
    }


ROUNDS_BLOB_SIZE = 0x144
ROUNDS_POINTER_NAMES = ('GetFileAttributesA', 'CreateFileA', 'WriteFileA', 'SetEvent',
                        'Sleep', 'GetTickCount')


def build_rounds_blob(magic, netobj, core, fn_d, pointers, flag_path, receipt_path, max_rounds):
    """Blob layout for the rounds agent (agent_rounds.bin). Offsets are the
    contract with the assembly; keep in sync with ROUNDS_ASM in the builder."""
    blob = bytearray(ROUNDS_BLOB_SIZE)

    def put32(off, val):
        struct.pack_into('<I', blob, off, val & 0xFFFFFFFF)

    def put_path(off, text, limit=128):
        raw = text.encode('utf-8')
        if len(raw) >= limit:
            raise ValueError('path too long')
        blob[off:off + len(raw)] = raw

    put32(0x00, magic)
    put32(0x04, 0)
    put32(0x08, netobj)
    for i, key in enumerate(ROUNDS_POINTER_NAMES):
        if key not in pointers:
            raise ValueError('missing pointer: ' + key)
        put32(0x0C + i * 4, pointers[key])
    put32(0x24, core)
    put32(0x28, fn_d)
    put32(0x2C, core - 0x8AA)   # app round state field [G+0x68], G = core-0x912
    put32(0x30, core + 0x6BC)   # round-complete flag
    put_path(0x34, flag_path)
    put_path(0xB4, receipt_path)
    put32(0x134, max_rounds)
    return bytes(blob)


def parse_receipt(data):
    """24-byte receipt -> dict (pure, for receipts and tests)."""
    if len(data) != 24:
        raise ValueError('receipt must be 24 bytes, got %d' % len(data))
    magic2, rc, own, target, tick, pad = struct.unpack('<IIIIII', data)
    return {'magic2': hex(magic2), 'rc': rc, 'own': own, 'target': target, 'tick': tick, 'pad': pad}


# ---------------------------------------------------------------- win32 layer

def _win():
    import ctypes as c
    from ctypes import wintypes as w
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAllocEx.restype = c.c_void_p
    k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.WriteProcessMemory.restype = w.BOOL
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.CreateRemoteThread.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    k.CreateRemoteThread.restype = w.HANDLE
    k.GetModuleHandleW.argtypes = [w.LPCWSTR]
    k.GetModuleHandleW.restype = c.c_void_p
    k.GetProcAddress.argtypes = [c.c_void_p, c.c_char_p]
    k.GetProcAddress.restype = c.c_void_p
    k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
    k.GetProcessTimes.restype = w.BOOL
    return c, w, k


class PEntry:
    pass


def find_process(name):
    c, w, k = _win()
    class Entry(c.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                    ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD),
                    ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                    ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == c.c_void_p(-1).value:
        raise OSError('process snapshot failed')
    e = Entry()
    e.dwSize = c.sizeof(e)
    found = []
    try:
        ok = k.Process32FirstW(snap, c.byref(e))
        while ok:
            if e.szExeFile.lower() == name.lower():
                found.append((e.th32ProcessID, e.szExeFile))
            ok = k.Process32NextW(snap, c.byref(e))
    finally:
        k.CloseHandle(snap)
    return found


def find_module(pid, dll_name):
    """Cross-process module lookup. psapi first (Wine: Toolhelp foreign snapshot
    is broken), Toolhelp as fallback (works on some builds / same-process)."""
    c, w, k = _win()
    h = k.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
    if not h:
        return None
    try:
        try:
            psapi = c.WinDLL('psapi', use_last_error=True)
            psapi.EnumProcessModules.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
            psapi.GetModuleBaseNameW.argtypes = [w.HANDLE, c.c_void_p, w.LPWSTR, w.DWORD]

            class ModInfo(c.Structure):
                _fields_ = [('lpBaseOfDll', c.c_void_p), ('SizeOfImage', w.DWORD), ('EntryPoint', c.c_void_p)]

            psapi.GetModuleInformation.argtypes = [w.HANDLE, c.c_void_p, c.POINTER(ModInfo), w.DWORD]
        except OSError:
            psapi = None
        if psapi is not None:
            arr = (c.c_void_p * 1024)()
            need = w.DWORD(0)
            if psapi.EnumProcessModules(h, arr, c.sizeof(arr), c.byref(need)):
                count = need.value // c.sizeof(c.c_void_p)
                buf = c.create_unicode_buffer(260)
                for i in range(min(count, 1024)):
                    if not psapi.GetModuleBaseNameW(h, arr[i], buf, 260):
                        continue
                    if buf.value.lower() == dll_name.lower():
                        size = 0
                        mi = ModInfo()
                        try:
                            if psapi.GetModuleInformation(h, arr[i], c.byref(mi), c.sizeof(mi)):
                                size = int(mi.SizeOfImage)
                        except (OSError, TypeError):
                            size = 0
                        return {'base': int(arr[i]), 'size': size, 'via': 'psapi'}
        class MEntry(c.Structure):
            _fields_ = [('dwSize', w.DWORD), ('th32ModuleID', w.DWORD), ('th32ProcessID', w.DWORD),
                        ('GlblcntUsage', w.DWORD), ('ProccntUsage', w.DWORD), ('modBaseAddr', c.c_void_p),
                        ('modBaseSize', w.DWORD), ('hModule', c.c_void_p), ('szModule', c.c_char * 256),
                        ('szExePath', c.c_char * 260)]
        snap = k.CreateToolhelp32Snapshot(0x18, pid)
        if snap == c.c_void_p(-1).value or not snap:
            return None
        m = MEntry()
        m.dwSize = c.sizeof(m)
        try:
            ok = k.Module32FirstW(snap, c.byref(m))
            while ok:
                if m.szModule.lower() == dll_name.lower().encode():
                    return {'base': int(m.modBaseAddr or 0), 'size': int(m.modBaseSize), 'via': 'toolhelp'}
                ok = k.Module32NextW(snap, c.byref(m))
        finally:
            k.CloseHandle(snap)
        return None
    finally:
        k.CloseHandle(h)


def process_creation(pid):
    c, w, k = _win()
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        ft = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[c.byref(t) for t in ft]):
            return None
        return (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
    finally:
        k.CloseHandle(h)


def kernel32_pointers():
    c, w, k = _win()
    k32 = k.GetModuleHandleW('kernel32.dll')
    # Wine builds vary in which A-suffixed names are exported (e.g. WriteFileA is
    # often only WriteFile). All candidates are byte-identical semantics for our
    # usage (raw byte buffers, ASCII paths).
    names = (('GetFileAttributesA', 'GetFileAttributes'), ('CreateFileA', 'CreateFile'),
             ('WriteFileA', 'WriteFile'), ('CloseHandle',), ('Sleep',), ('GetTickCount',),
             ('SetEvent',))
    out = {}
    for candidates in names:
        addr = 0
        for name in candidates:
            addr = int(k.GetProcAddress(k32, name.encode()) or 0)
            if addr:
                out[candidates[0]] = addr
                break
        if not addr:
            raise OSError('GetProcAddress failed: ' + '/'.join(candidates))
    out['_kernel32_base'] = int(k32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-name', default='SANPK.exe')
    ap.add_argument('--agent-bin', help='agent binary (required for agent/smoke/acceptexit)')
    ap.add_argument('--mode', choices=['agent', 'smoke', 'acceptexit', 'nullguard', 'rounds', 'suppress', 'resident', 'ui'], default='agent')
    ap.add_argument('--ui-action', choices=['plan', 'check', 'install', 'revert'], default='check')
    ap.add_argument('--ui-element', help='P52: select exactly one optional UI element; never enabled by normal arm')
    ap.add_argument('--resident-action', choices=['install','check','recover','release','start'], default='check')
    ap.add_argument('--legacy-state', help='identity-bound old E state, for live migration only')
    ap.add_argument('--recover-capture', help='fresh shadow_stall_probe output directory')
    ap.add_argument('--release-tid', type=int, help='observed old D worker to release in order')
    ap.add_argument('--bridge', help='shadow bridge dir with collector.py (rounds mode)')
    ap.add_argument('--core', help='game core pointer (rounds mode; auto via --bridge if omitted)')
    ap.add_argument('--max-rounds', type=int, default=1)
    ap.add_argument('--rounds-variant', choices=['a', 'b'], default='b',
                    help="'a' = direct D call from the injected thread; 'b' (default) = call the "
                         "game's own AfxBeginThread spawner 0x44B88E (MFC thread state correct)")
    ap.add_argument('--revert', action='store_true',
                    help='suppress mode: write the original bytes back (undo)')
    ap.add_argument('--koeinm', help='path to 3I/Koeinm.dll (agent mode)')
    ap.add_argument('--flag', help='trigger file Windows path (agent mode)')
    ap.add_argument('--receipt', help='receipt file Windows path (agent/smoke/acceptexit)')
    ap.add_argument('--state', help='injector state file Windows path')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    if sys.platform != 'win32':
        raise SystemExit('this tool must run under Win32 python (wine py32)')
    c, w, k = _win()

    if args.mode not in ('nullguard', 'suppress', 'resident', 'ui'):
        if not args.agent_bin:
            raise SystemExit('%s mode needs --agent-bin' % args.mode)
        if not args.receipt:
            raise SystemExit('%s mode needs --receipt' % args.mode)
        code = Path(args.agent_bin).read_bytes()
        if not code:
            raise SystemExit('empty agent binary')
    else:
        code = None

    # target
    targets = find_process(args.target_name)
    if args.check and not targets:
        print(json.dumps({'status': 'no_target', 'target_name': args.target_name}, ensure_ascii=False))
        return
    if len(targets) != 1:
        raise SystemExit('%d processes named %s (need exactly 1)' % (len(targets), args.target_name))
    pid = targets[0][0]

    # process open (VM ops + create thread; no world write besides our blob)
    RIGHTS = 0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400  # CREATE_THREAD|OP|READ|WRITE|QUERY
    h = k.OpenProcess(RIGHTS, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed err=%d' % c.get_last_error())

    created = process_creation(pid)

    def read_proc(addr, size):
        buf = c.create_string_buffer(size)
        got = c.c_size_t()
        ok = k.ReadProcessMemory(h, c.c_void_p(addr), buf, size, c.byref(got))
        return buf.raw if ok and got.value == size else None

    def write_proc(addr, data):
        got = c.c_size_t()
        ok = k.WriteProcessMemory(h, c.c_void_p(addr), data, len(data), c.byref(got))
        return bool(ok) and got.value == len(data)

    if args.mode in ('resident', 'ui'):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        if args.mode == 'resident':
            from p51_shadow_resident import run
        else:
            from p52_shadow_ui import run, SITES
            if args.ui_element is not None and args.ui_element not in SITES:
                raise SystemExit('unknown UI element: '+args.ui_element)
        try:
            run(args, c, w, k, h, pid, created, read_proc, write_proc)
        finally:
            k.CloseHandle(h)
        return

    # runtime nullguard: keep the on-disk EXE original (version check reads the
    # file) and patch the running process's code in memory instead.
    #
    # Patches (RVAs against SANPK 3.5 df9b5225; shadow prefix only). Batch 2+3:
    #   lord-deref 0x84F7A: movzbl 0x17(%esi),%eax -> xor eax,eax; nop; nop
    #   entry-stub-FUN484F35 0x84F35: entry -> xor eax,eax; ret $4
    #     (FUN_484F35 "my-force HUD rebuild": six null-lord landmines; single
    #      caller 0x4870A4, __thiscall(1 stacked arg), ret $4, eax unused)
    #   pred1/2/3 0x68662/0x686C7/0x68724: "isValid" predicates
    #     `push edi/esi; mov ecx,edi/esi; cmpl $0,0x89(%edi/esi)` -> JMP to cave
    #     stubs: this==NULL -> xor eax,eax; ret $8 (2 stacked args, callee
    #     cleans: 0x4686C4/0x468721/0x468765); else reproduce prologue+cmpl and
    #     rejoin the body (resume 0x46866C / 0x4686D1 / 0x46872E).
    #   entry-stub-499EB3/499F8A/49A052 0x99EB3/0x99F8A/0x9A052: sibling UI
    #     refreshers (element ids 0x12c/0x12d/0x12e) that deref a NULL resource
    #     from 0x4195A9; __thiscall(1 stacked arg), ret $4, eax unused by all
    #     call sites -> entry stubs.
    #   entry-stub-49A11A/49A1E2/49A2AA/49A372 0x9A11A..0x9A372 (2026-10-18):
    #     elements 0x12f..0x132, the remaining siblings of the same UI family;
    #     setters 0x444E53..0x444F7A call them and ignore eax; their untrapped
    #     NULL deref (mov 0x3c(%edi), edi=0) interrupts the app round
    #     state-machine tick between lock [0x53BA54]=1 and its release, leaving
    #     the global lock stuck and freezing the round machine for good.
    #     Same convention -> entry stubs.
    #   cave-pred1/2/3 0x84F40/0x84F60/0x84F80: 24-byte conditional stubs in the
    #     now-dead body of FUN_484F35 (entry-stubbed -> body unreachable; no
    #     external jumps into the body, verified in the full dump).
    NULLGUARD_PATCHES = (
        (0x84F7A, '0fb64617', '31c09090', 'lord-deref'),
        (0x84F35, 'b868594f00', '33c0c20400', 'entry-stub-FUN484F35'),
        (0x68662, '578bf983bf', 'e9d9c80100', 'pred1-condstub'),
        (0x686C7, '578bf983bf', 'e994c80100', 'pred2-condstub'),
        (0x68724, '568bf183be', 'e957c80100', 'pred3-condstub'),
        (0x99EB3, '515355568b', '33c0c20400', 'entry-stub-499EB3'),
        (0x99F8A, '558bec83ec', '33c0c20400', 'entry-stub-499F8A'),
        (0x9A052, '558bec83ec', '33c0c20400', 'entry-stub-49A052'),
        (0x9A11A, '558bec83ec', '33c0c20400', 'entry-stub-49A11A'),
        (0x9A1E2, '558bec83ec', '33c0c20400', 'entry-stub-49A1E2'),
        (0x9A2AA, '558bec83ec', '33c0c20400', 'entry-stub-49A2AA'),
        (0x9A372, '558bec83ec', '33c0c20400', 'entry-stub-49A372'),
        # 2026-10-18 PM: the "copy [arg] into this+0x38 + virtual notify"
        # siblings. The revived tick called 0x484C7E with this=NULL (des eat-ed
        # my-force): `leal 0x38(%esi),%ecx; call copy` on a NULL object then
        # AV'd inside the copy's resize at 0x4CD14A (near-null deref of 0x38).
        # Stub both siblings (thiscall + 1 stack arg -> xor eax,eax; ret 4).
        (0x84C7E, '568bf1ff74', '33c0c20400', 'entry-stub-484C7E'),
        (0x84C5D, '837c240400', '33c0c20400', 'entry-stub-484C5D'),
        # 2026-10-18 PM #2 (REVERTED 2026-10-19 19:xx): the "unmatched lookups
        # return the container" shim (0x195AF: xor edi,edi -> mov edi,eax) is
        # NOT applied here anymore. Returning the container is a type lie:
        # callers read [ret+0x3C] / pass ret on as an element and the observer
        # client later died with this=0xfffffXXX inside the training dialog.
        # The type-safe replacement lives in patch_element_fallback.py
        # (retargets the 0x4195C4 cast call so a miss returns the first real
        # element of the requested class instead of the container).
        # 2026-10-18 PM #3: null out-ptr guard for the element-id dispatcher at
        # 0x484A88 (`mov eax,[esp+8]; mov [eax],esi; mov [eax+4],edx`): crash
        # #112/#113 was a write to NULL (fault 0x484A8C, element 0x12D family,
        # UI path). Cave stub: skip the two stores when the out-pointer is
        # null; otherwise byte-identical behaviour. Cave lives in the dead
        # body of entry-stubbed 0x49A1E2 (0x49A1F0, 17 bytes).
        (0x84A88, '8b44240889', 'e963570100', 'guard-484A88-null-outptr'),
        (0x9A1F0, 'ff1558b74f0068300100008bceffb6ea07',
                  '8b44240885c0740589308950045ec20400', 'cave-484A88-guard'),
        (0x84F40, '53894df08b4d085657e8ed68fcff8b4d0850e8f1affcff6a',
                  '85c9740f578bf983bf8900000000e91937feff33c0c20800', 'cave-pred1'),
        (0x84F60, '5989450833db3bc3895dfc740b8bc8e88df1ffff8bf8eb02',
                  '85c9740f578bf983bf8900000000e95e37feff33c0c20800', 'cave-pred2'),
        (0x84F80, 'fcff68c800000050682c0100008bcfe81203000033c05350',
                  '85c9740f568bf183be8900000000e99b37feff33c0c20800', 'cave-pred3'),
        # 2026-10-18 evening #4: null node-field guard in the my-force UI
        # refresh FUN_00492ad0 (tick chain 0x443ee5 -> 0x444756 -> 0x4886d6 ->
        # FUN_00492ad0). Crash at the autumn transition (crash ledger rec 128):
        # Eip=0x492b20 movsx ecx,word [eax+8] with eax = [[edi]+8] == NULL
        # -> AV at address 0x8. Cave stub: skip list nodes whose field-8
        # pointer is null; otherwise byte-identical behaviour. Cave lives in
        # the dead body of entry-stubbed 0x49A1E2 (0x49A210, 21 bytes).
        (0x92B1D, '8b40080fbf4808', 'e976ee00009090', 'guard-492B20-null-node-field'),
        (0x9A210, 'ffd38bce8945fce8c70e00008945f88b473c3b4508',
                  '8b400885c074090fbf4808e90489ffffe9f088ffff', 'cave-492B20-guard'),
    )
    if args.mode == 'nullguard':
        mod = find_module(pid, 'SANPK.exe')
        if not mod:
            raise SystemExit('SANPK.exe module not found in target')
        results = []
        for rva, orig_hex, patched_hex, label in NULLGUARD_PATCHES:
            addr = mod['base'] + rva
            size = len(bytes.fromhex(patched_hex))
            cur = read_proc(addr, size)
            if cur is None:
                raise SystemExit('cannot read patch site 0x%x' % addr)
            if cur == bytes.fromhex(orig_hex):
                if args.dry_run:
                    results.append({'site': label, 'addr': hex(addr), 'action': 'would-apply'})
                    continue
                if not write_proc(addr, bytes.fromhex(patched_hex)):
                    raise SystemExit('WriteProcessMemory failed at 0x%x err=%d' % (addr, c.get_last_error()))
                check = read_proc(addr, size)
                if check != bytes.fromhex(patched_hex):
                    raise SystemExit('verify readback mismatch at 0x%x' % addr)
                results.append({'site': label, 'addr': hex(addr), 'action': 'applied'})
            elif cur == bytes.fromhex(patched_hex):
                results.append({'site': label, 'addr': hex(addr), 'action': 'already'})
            else:
                raise SystemExit('unexpected bytes at 0x%x: %s' % (addr, cur.hex()))
        print(json.dumps({'mode': 'nullguard', 'base': hex(mod['base']), 'via': mod.get('via'),
                          'patches': results}, ensure_ascii=False))
        return

    SUPPRESS_PATCHES = (
        (0x32C5, 'e826f2ffff', '31c0909090', 'suppress-control1-upload'),
        (0x358D, 'e89eefffff', '31c0909090', 'suppress-control2-upload'),
    )
    if args.mode == 'suppress':
        # Read-only-for-the-host mode: NOP the two Koeinm member-side uploads
        # (control1 at 0x32C5 -> 0x24F0, control2 at 0x358D -> 0x2530). Each
        # call site takes the send's rc in eax; `xor eax,eax` yields rc=0 so
        # the local state machine proceeds to its blocking wait, which the
        # naturally broadcast control5/control3 satisfy. The host never sees
        # the observer's readiness -> never waits for it. In-memory, shadow
        # process only; disappears when the client restarts.
        mod = find_module(pid, 'Koeinm.dll')
        if not mod:
            raise SystemExit('Koeinm.dll not found in target')
        results = []
        for rva, orig_hex, patched_hex, label in SUPPRESS_PATCHES:
            addr = mod['base'] + rva
            size = len(bytes.fromhex(patched_hex))
            cur = read_proc(addr, size)
            if cur is None:
                raise SystemExit('cannot read patch site 0x%x' % addr)
            want, alt = bytes.fromhex(orig_hex), bytes.fromhex(patched_hex)
            if args.revert:
                want, alt = alt, want
            if cur == want:
                if args.dry_run:
                    results.append({'site': label, 'addr': hex(addr), 'action': 'would-apply'})
                    continue
                if not write_proc(addr, alt):
                    raise SystemExit('WriteProcessMemory failed at 0x%x err=%d' % (addr, c.get_last_error()))
                check = read_proc(addr, size)
                if check != alt:
                    raise SystemExit('verify readback mismatch at 0x%x' % addr)
                results.append({'site': label, 'addr': hex(addr), 'action': 'reverted' if args.revert else 'applied'})
            elif cur == alt:
                results.append({'site': label, 'addr': hex(addr), 'action': 'already-' + ('reverted' if args.revert else 'applied')})
            else:
                raise SystemExit('unexpected bytes at 0x%x: %s' % (addr, cur.hex()))
        print(json.dumps({'mode': 'suppress', 'revert': args.revert, 'base': hex(mod['base']),
                          'via': mod.get('via'), 'patches': results}, ensure_ascii=False))
        return

    if args.mode == 'rounds':
        # Round-follow agent: drives the client's own per-round driver D
        # (SANPK +0x4B8CA, ecx=core) on a dedicated thread, per the operator's
        # trigger file. See p51_shadow_agent_build.py ROUNDS_ASM for the blob
        # contract. Fire ONLY while a match is actually running.
        if not args.receipt or not args.flag:
            raise SystemExit('rounds mode needs --flag and --receipt')
        receipt_exists = Path(args.receipt).exists()
        if receipt_exists and not args.force:
            raise SystemExit('receipt already exists (%s); one-shot discipline — move it away first' % args.receipt)
        sanpk = find_module(pid, 'SANPK.exe')
        if not sanpk:
            raise SystemExit('SANPK.exe module not found in target')
        if args.core:
            core_val = str(args.core)
            core = int(core_val, 16) if core_val.lower().startswith('0x') else int(core_val)
        else:
            if not args.bridge:
                raise SystemExit('rounds mode needs --core or --bridge')
            os.environ.setdefault('SGI_GAME_EXE', r'C:\sgi\run-3.5\3I\SANPK.exe')
            sys.path.insert(0, args.bridge)
            from collector import Collector
            col = Collector(pid)
            try:
                col.bind()
                core = int(col.core)
            finally:
                col.close()
        fn_d = int(sanpk['base']) + (0x4B88E if args.rounds_variant == 'b' else 0x4B8CA)
        koeinm = find_module(pid, 'Koeinm.dll')
        netobj = (int(koeinm['base']) + NETOBJ_RVA) if koeinm else 0
        pointers = kernel32_pointers()
        pointers.pop('_kernel32_base', None)
        blob = build_rounds_blob(MAGIC, netobj, core, fn_d, pointers, args.flag, args.receipt,
                                 int(args.max_rounds))
        plan = {'mode': 'rounds', 'variant': args.rounds_variant, 'pid': pid,
                'code_size': len(code), 'blob_size': len(blob),
                'core': hex(core), 'fn': hex(fn_d), 'netobj': hex(netobj),
                'sanpk': {'base': hex(int(sanpk['base'])), 'via': sanpk.get('via')},
                'max_rounds': int(args.max_rounds),
                'flag': args.flag, 'receipt': args.receipt}
        if args.dry_run:
            plan['dry_run'] = True
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return
        size = len(code) + len(blob) + 0x40
        addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x40)  # COMMIT|RESERVE, RWX
        if not addr:
            raise SystemExit('VirtualAllocEx failed err=%d' % c.get_last_error())
        blob_addr = addr + ((len(code) + 0xF) & ~0xF)
        if not write_proc(addr, code) or not write_proc(blob_addr, blob):
            raise SystemExit('WriteProcessMemory failed err=%d' % c.get_last_error())
        check = read_proc(addr, len(code))
        if check != code:
            raise SystemExit('code verification readback mismatch')
        tid = w.DWORD(0)
        th = k.CreateRemoteThread(h, None, 0, c.c_void_p(addr), c.c_void_p(blob_addr), 0, c.byref(tid))
        if not th:
            raise SystemExit('CreateRemoteThread failed err=%d' % c.get_last_error())
        k.CloseHandle(th)
        result = dict(plan, code_addr=hex(addr), blob_addr=hex(blob_addr), thread_id=tid.value,
                      creation=created)
        if args.state:
            Path(args.state).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # state / idempotency
    state = {}
    if args.state:
        try:
            state = json.loads(Path(args.state).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
    prior_addr = None
    same_process = bool(state.get('pid') == pid and created and state.get('creation') == created)
    if same_process and state.get('blob_addr'):
        try:
            prior_addr = int(state['blob_addr'], 16) if isinstance(state['blob_addr'], str) else int(state['blob_addr'])
        except (TypeError, ValueError):
            prior_addr = None
    prior_magic = read_proc(prior_addr, 4) if prior_addr else None
    prior_magic_value = struct.unpack('<I', prior_magic)[0] if prior_magic else None
    already = same_process and prior_magic_value == MAGIC

    receipt_exists = False
    try:
        receipt_exists = Path(args.receipt).exists()
    except OSError:
        pass

    if args.check:
        sent = None
        if prior_addr:
            raw = read_proc(prior_addr + 4, 4)
            sent = struct.unpack('<I', raw)[0] if raw else None
        koeinm = find_module(pid, 'Koeinm.dll')
        live = None
        if koeinm:
            state_raw = read_proc(koeinm['base'] + NETOBJ_RVA + STATE_OFF, 4)
            live = {'base': hex(koeinm['base']), 'via': koeinm['via'],
                    'state_raw': struct.unpack('<I', state_raw)[0] if state_raw else None}
        print(json.dumps({'status': 'ok', 'pid': pid, 'creation': created,
                          'state_same_process': same_process, 'state': state,
                          'blob_magic': hex(prior_magic_value) if prior_magic_value is not None else None,
                          'already_injected': already, 'sent_flag': sent,
                          'receipt_exists': receipt_exists, 'koeinm': live}, ensure_ascii=False))
        return

    if already and not args.force:
        raise SystemExit('already injected into pid %d (blob @0x%x); use --force to override' % (pid, prior_addr))
    if receipt_exists and not args.force:
        raise SystemExit('receipt already exists (%s); one-shot discipline — move it away first' % args.receipt)

    # pointers + module info
    pointers = kernel32_pointers()
    k32_self = pointers.pop('_kernel32_base')
    target_k32 = find_module(pid, 'kernel32.dll')
    if not target_k32:
        raise SystemExit('cannot enumerate target modules (Toolhelp)')
    if target_k32['base'] != k32_self:
        raise SystemExit('kernel32 base differs (self=0x%x target=0x%x) — PEB resolution required'
                         % (k32_self, target_k32['base']))

    netobj = 0
    mod_info = None
    pointer_names = DEFAULT_POINTER_NAMES
    if args.mode in ('agent', 'acceptexit'):
        if not (args.koeinm and args.flag):
            raise SystemExit('%s mode needs --koeinm and --flag' % args.mode)
        sha = hashlib.sha256(Path(args.koeinm).read_bytes()).hexdigest()
        if sha not in KOEINM_SHA_ALLOWED:
            raise SystemExit('unexpected Koeinm SHA: ' + sha)
        ex = parse_exports(args.koeinm)
        golden = {'_NetMsg_IsConnected@0': RVA_IS_CONNECTED,
                  '_NetMsg_GetIPAddress@4': RVA_GET_IP}
        if args.mode == 'acceptexit':
            golden['_NetMsg_AcceptEXIT@4'] = RVA_ACCEPT_EXIT
        for name, rva in golden.items():
            if name not in ex:
                raise SystemExit('export missing: ' + name)
            if ex[name] != rva:
                raise SystemExit('export RVA drift (%s); refusing to inject' % name)
        koeinm = find_module(pid, 'Koeinm.dll')
        if not koeinm:
            raise SystemExit('Koeinm.dll not loaded in target yet')
        base = koeinm['base']
        bounds = 'checked'
        if koeinm['size'] and base + NETOBJ_RVA + STATE_OFF + 4 > base + koeinm['size']:
            raise SystemExit('netobj outside module image (base=0x%x size=0x%x)' % (base, koeinm['size']))
        if not koeinm['size']:
            bounds = 'size unavailable; bounds check skipped'
        mod_info = {'base': hex(base), 'size': koeinm['size'], 'via': koeinm['via'],
                    'bounds': bounds, 'netobj': hex(base + NETOBJ_RVA)}
        netobj = base + NETOBJ_RVA
        pointers.update({
            'is_connected': base + RVA_IS_CONNECTED,
            'get_ip': base + RVA_GET_IP,
        })
        if args.mode == 'agent':
            pointers.update({
                'submit_4c80': base + RVA_4C80,
                'submit_4b60': base + RVA_4B60,
            })
        else:
            pointers.update({'accept_exit': base + RVA_ACCEPT_EXIT})
            pointer_names = ACCEPTEXIT_POINTER_NAMES
    else:
        for key in ('is_connected', 'get_ip', 'submit_4c80', 'submit_4b60'):
            pointers[key] = 0

    blob = build_blob(MAGIC, netobj, pointers, args.flag or 'Z:\\none', args.receipt,
                      pointer_names)
    plan = {'pid': pid, 'code_size': len(code), 'blob_size': len(blob),
            'mode': args.mode, 'netobj': hex(netobj), 'module': mod_info,
            'summary': blob_summary(blob)}
    if args.dry_run:
        plan['dry_run'] = True
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    # allocate + write
    size = len(code) + len(blob) + 0x40
    addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x40)  # COMMIT|RESERVE, RWX
    if not addr:
        raise SystemExit('VirtualAllocEx failed err=%d' % c.get_last_error())
    blob_addr = addr + ((len(code) + 0xF) & ~0xF)
    if not write_proc(addr, code) or not write_proc(blob_addr, blob):
        raise SystemExit('WriteProcessMemory failed err=%d' % c.get_last_error())
    check = read_proc(addr, len(code))
    if check != code:
        raise SystemExit('code verification readback mismatch')

    tid = w.DWORD(0)
    th = k.CreateRemoteThread(h, None, 0, c.c_void_p(addr), c.c_void_p(blob_addr), 0, c.byref(tid))
    if not th:
        raise SystemExit('CreateRemoteThread failed err=%d' % c.get_last_error())
    k.CloseHandle(th)

    result = dict(plan, code_addr=hex(addr), blob_addr=hex(blob_addr), thread_id=tid.value,
                  creation=created)
    if args.state:
        Path(args.state).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
