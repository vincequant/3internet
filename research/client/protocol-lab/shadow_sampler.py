#!/usr/bin/env python3
"""Shadow world-state sampler — runs under Win32 py32 inside the shadow prefix.

Finds SANPK.exe in the same bottle, binds the typed collector chain
(collector.py, staged next to this script) and writes one JSON snapshot per
capture plus an index line. Read-only by construction: the collector family
opens processes with PROCESS_VM_READ|QUERY only and never writes game memory.

Usage (under wine py32, WINEPREFIX = shadow prefix):
  python.exe shadow_sampler.py --dir 'Z:\\...\\shadow\\samples' \
      --bridge 'Z:\\...\\shadow\\bridge' [--interval 30] [--duration 0] [--once]

Stop: create a file named STOP inside --dir (checked every loop).
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
import sys
import time
from ctypes import wintypes as w
from pathlib import Path


def find_sanpk():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]

    class Entry(c.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                    ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD),
                    ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                    ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]

    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == c.c_void_p(-1).value or not snap:
        return None
    e = Entry()
    e.dwSize = c.sizeof(e)
    pid = None
    try:
        ok = k.Process32FirstW(snap, c.byref(e))
        while ok:
            if e.szExeFile.lower() == 'sanpk.exe':
                pid = int(e.th32ProcessID)
            ok = k.Process32NextW(snap, c.byref(e))
    finally:
        k.CloseHandle(snap)
    return pid


def append_index(outdir, doc):
    with (outdir / 'index.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True, help='output directory (windows path)')
    ap.add_argument('--bridge', required=True, help='staged bridge module dir (windows path)')
    ap.add_argument('--interval', type=float, default=30.0)
    ap.add_argument('--duration', type=float, default=0.0, help='0 = run until STOP file')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--game-exe', default=r'C:\sgi\run-3.5\3I\SANPK.exe')
    args = ap.parse_args()

    os.environ.setdefault('SGI_GAME_EXE', args.game_exe)
    sys.path.insert(0, args.bridge)
    outdir = Path(args.dir)
    outdir.mkdir(parents=True, exist_ok=True)

    from collector import Collector  # staged; raises on import problems

    started = time.time()
    print(json.dumps({'ev': 'sampler_start', 'dir': str(outdir), 'bridge': args.bridge}), flush=True)
    while True:
        if (outdir / 'STOP').exists():
            append_index(outdir, {'wall': time.time(), 'status': 'stop_requested'})
            break
        pid = find_sanpk()
        if not pid:
            append_index(outdir, {'wall': time.time(), 'status': 'no_target'})
        else:
            try:
                col = Collector(pid)
                try:
                    binding = col.bind()
                    snap = col.capture()
                finally:
                    col.close()
                stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime())
                name = 'state-%s-%d.json' % (stamp, int(time.time() * 1000) % 100000)
                (outdir / name).write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding='utf-8')
                counts = {k: v['count'] for k, v in snap.get('coverage', {}).items()}
                append_index(outdir, {'wall': time.time(), 'status': 'ok', 'pid': pid, 'file': name,
                                      'counts': counts, 'timing': snap.get('timing', {}),
                                      'build_sha256': snap.get('build_sha256')})
            except Exception as error:
                append_index(outdir, {'wall': time.time(), 'status': 'error', 'pid': pid,
                                      'error': type(error).__name__ + ': ' + str(error)[:200]})
        if args.once or (args.duration and time.time() - started >= args.duration):
            break
        time.sleep(max(1.0, args.interval))
    append_index(outdir, {'wall': time.time(), 'status': 'sampler_end'})
    print(json.dumps({'ev': 'sampler_end', 'elapsed': round(time.time() - started, 1)}), flush=True)


if __name__ == '__main__':
    main()
