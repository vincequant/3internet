#!/usr/bin/env python3
"""Bounded read-only Win32 thread/lock capture; never repairs the target.

Run in prefix-fengye-shadow. Unlike the old thread_probe, reads stop at the
stack base and retain every code hit, separately from actual EBP frames.
Suspend/resume pairs are protected by finally; files are written after resume.
"""
from __future__ import annotations

import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import sys
import time


def stack_hits(raw, base):
    return [{'offset': i, 'address': hex(base+i), 'value': hex(v[0])}
            for i, v in zip(range(0, len(raw)-3, 4), struct.iter_unpack('<I', raw[:len(raw)//4*4]))
            if 0x400000 <= v[0] < 0x4f0000 or 0x1d0000 <= v[0] < 0x220000]


def frame_chain(read, bp, sp, top):
    frames = []
    seen = set()
    for _ in range(128):
        if bp in seen or bp < sp or bp+8 > top or bp % 4:
            break
        seen.add(bp)
        raw = read(bp, 8)
        if len(raw) != 8:
            break
        next_bp, ret = struct.unpack('<II', raw)
        frames.append({'ebp': hex(bp), 'return': hex(ret), 'next': hex(next_bp)})
        if next_bp <= bp:
            break
        bp = next_bp
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from thread_probe import CONTEXT, threads_of
    from p51_shadow_inject import _win, find_module, process_creation
    c_, w_, k = _win()
    state = json.loads(Path(args.state).read_text())
    creation = process_creation(args.pid)
    if state['pid'] != args.pid or state['creation'] != creation:
        raise SystemExit('process identity mismatch')
    h = k.OpenProcess(0x410, False, args.pid)
    if not h:
        raise SystemExit('OpenProcess failed')

    def read(addr, size):
        buf = c.create_string_buffer(size)
        got = c.c_size_t()
        k.ReadProcessMemory(h, c.c_void_p(addr), buf, size, c.byref(got))
        return buf.raw[:got.value]

    def u32(addr):
        b = read(addr, 4)
        return struct.unpack('<I', b)[0] if len(b) == 4 else None

    class TBI(c.Structure):
        _fields_ = [('exit', w.LONG), ('teb', c.c_void_p), ('pid', c.c_void_p),
                    ('tid', c.c_void_p), ('affinity', c.c_void_p), ('priority', w.LONG),
                    ('base_priority', w.LONG)]

    nt = c.WinDLL('ntdll')
    nt.NtQueryInformationThread.argtypes = [w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p]
    k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenThread.restype = w.HANDLE
    k.SuspendThread.argtypes = [w.HANDLE]
    k.SuspendThread.restype = w.DWORD
    k.ResumeThread.argtypes = [w.HANDLE]
    k.ResumeThread.restype = w.DWORD
    k.GetThreadContext.argtypes = [w.HANDLE, c.POINTER(CONTEXT)]
    k.GetThreadTimes.argtypes = [w.HANDLE]+[c.POINTER(w.FILETIME)]*4

    sanpk = find_module(args.pid, 'SANPK.exe')
    modbase = sanpk['base']
    # These are virtual addresses in the preferred-base disassembly, not RVAs.
    delta = modbase-0x400000
    ranges = [(0x443ee5, 0x1a0), (0x4446f5, 0x61), (0x44b88e, 0x31),
              (0x4bd240, 0x98), (0x4b9c00, 0xc5), (0x44a6dd, 0x60),
              (0x41e174, 0x1e), (0x4fb298, 0x20)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {'wall': time.time(), 'pid': args.pid, 'creation': creation,
              'sanpk': sanpk, 'threads': [], 'locks': [], 'code': []}
    try:
        for va, size in ranges:
            raw = read(va+delta, size)
            name = 'code-%x.bin' % va
            (out/name).write_bytes(raw)
            result['code'].append({'va':hex(va+delta), 'size':len(raw),
                                   'file':name, 'sha256':hashlib.sha256(raw).hexdigest()})
        core = int(state['core'], 16)
        (out/'core-queue.bin').write_bytes(read(core+0x654, 0x60))
        result['queue']={hex(off):u32(core+off) for off in range(0x654,0x69c,4)}
        result['app_thread_fields']={hex(va):u32(va+delta) for va in (0x53bb30,0x53ba54,0x53ba58)}
        (out/'hotfix.bin').write_bytes(read(0x560000+delta,0x1100))
        result['fields'] = {name:u32(addr) for name, addr in (
            ('tick_lock_53ba54', 0x53ba54+delta), ('accum', core-0x8a6),
            ('G68', core-0x8aa), ('f6bc', core+0x6bc))}
        if state.get('blob_addr'):
            (out/'round-agent-blob.bin').write_bytes(read(int(state['blob_addr'],16), 0x180))
        for index in range(32):
            ptr = u32(0x537628+delta+4*index)
            if ptr:
                raw = read(ptr,24)
                if len(raw)==24:
                    words = struct.unpack('<6I',raw)
                    result['locks'].append({'index':index,'ptr':hex(ptr),
                        'debug':hex(words[0]),'lock_count':c.c_int32(words[1]).value,
                        'recursion':words[2],'owner_tid':words[3],
                        'semaphore':hex(words[4]),'spin':words[5]})
        for tid in threads_of(args.pid):
            rec = {'tid':tid}
            th = k.OpenThread(0x4a, False, tid)
            if not th:
                rec['error']='OpenThread';result['threads'].append(rec);continue
            suspended=False
            raw=b''
            try:
                tbi=TBI()
                status=nt.NtQueryInformationThread(th,0,c.byref(tbi),c.sizeof(tbi),None)
                top=u32(int(tbi.teb or 0)+4) if status==0 else None
                limit=u32(int(tbi.teb or 0)+8) if status==0 else None
                start=c.c_void_p()
                nt.NtQueryInformationThread(th,9,c.byref(start),c.sizeof(start),None)
                rec.update(start=hex(start.value or 0),teb=hex(tbi.teb or 0),
                           stack_base=hex(top or 0),stack_limit=hex(limit or 0))
                ts=[w.FILETIME() for _ in range(4)]
                if k.GetThreadTimes(th,*[c.byref(t) for t in ts]):
                    rec['times']=[(t.dwHighDateTime<<32)|t.dwLowDateTime for t in ts]
                prev=k.SuspendThread(th)
                if prev==0xffffffff:
                    rec['error']='SuspendThread';continue
                suspended=True
                ctx=CONTEXT();ctx.ContextFlags=0x10007
                if not k.GetThreadContext(th,c.byref(ctx)):
                    rec['error']='GetThreadContext';continue
                rec['registers']={n:hex(getattr(ctx,n)) for n in (
                    'Eip','Esp','Ebp','Eax','Ebx','Ecx','Edx','Esi','Edi','EFlags')}
                end=min(top or ctx.Esp+0x4000,ctx.Esp+0x10000)
                at=ctx.Esp
                while at<end:
                    chunk=read(at,min(0x1000-(at%0x1000),end-at))
                    if not chunk:break
                    raw+=chunk;at+=len(chunk)
                rec['frames']=frame_chain(read,ctx.Ebp,ctx.Esp,end)
                rec['stack_hits']=stack_hits(raw,ctx.Esp)
                rec['stack_bytes']=len(raw)
                rec['raw_head']=[hex(v[0]) for v in struct.iter_unpack('<I',raw[:len(raw)//4*4][:256])]
            finally:
                if suspended:
                    rec['resume_result']=k.ResumeThread(th)
                k.CloseHandle(th)
                result['threads'].append(rec)
            if raw:
                (out/('stack-%d.bin'%tid)).write_bytes(raw)
        result['finished_wall']=time.time()
        (out/'capture.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,ensure_ascii=False))
    finally:
        k.CloseHandle(h)


if __name__=='__main__':
    main()
