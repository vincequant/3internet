#!/usr/bin/env python3
"""Narrow P53 CLI: reuse P52 UI runtime, or the P53 paint-only extension.

Kept separate from the shared multi-purpose injector to preserve concurrent
work. Only the explicit shadow executable path and exact process are accepted.
No agent/arming/start/network actions are exposed by this entry point.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=('ui','hidden-ui'), required=True)
    ap.add_argument('--ui-action', choices=('plan','check','install','revert'), default='check')
    ap.add_argument('--ui-element')
    ap.add_argument('--state', required=True)
    ap.add_argument('--expected-pid', required=True, type=int)
    ap.add_argument('--expected-creation', required=True, type=int)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if sys.platform != 'win32':raise SystemExit('run under shadow Win32 Python')
    from p51_shadow_inject import _win, find_process, process_creation
    c,w,k = _win()
    targets = find_process('SANPK.exe')
    if len(targets) != 1 or targets[0][0] != args.expected_pid:
        raise SystemExit('target changed since preflight; no write performed')
    pid = args.expected_pid; created = process_creation(pid)
    if not created or created != args.expected_creation:
        raise SystemExit('target creation differs; no write performed')
    # check/plan only request QUERY|READ. Mutation also needs VM_OPERATION|WRITE,
    # never CREATE_THREAD. The two runtime implementations do not spawn one.
    rights = 0x410 if args.ui_action in ('check','plan') or args.dry_run else 0x438
    handle = k.OpenProcess(rights,False,pid)
    if not handle:raise c.WinError(c.get_last_error())
    try:
        k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
        k.QueryFullProcessImageNameW.restype=w.BOOL
        buf=c.create_unicode_buffer(32768);length=w.DWORD(len(buf))
        expected=os.path.normcase(os.path.abspath(r'C:\sgi\run-3.5\3I\SANPK.exe'))
        if (not k.QueryFullProcessImageNameW(handle,0,buf,c.byref(length)) or
                os.path.normcase(os.path.abspath(buf.value)) != expected):
            raise SystemExit('optional UI target path mismatch; no write performed')
        def read(address,size):
            raw=c.create_string_buffer(size);got=c.c_size_t()
            ok=k.ReadProcessMemory(handle,c.c_void_p(address),raw,size,c.byref(got))
            return raw.raw if ok and got.value==size else None
        def write(address,raw):
            if rights==0x410:raise RuntimeError('read-only check/plan attempted a write')
            got=c.c_size_t()
            ok=k.WriteProcessMemory(handle,c.c_void_p(address),raw,len(raw),c.byref(got))
            return bool(ok) and got.value==len(raw)
        if args.mode=='ui':
            from p52_shadow_ui import run,SITES
            if args.ui_element and args.ui_element not in SITES:raise SystemExit('unknown P52 element')
        else:
            from p53_hidden_draw import run
        run(args,c,w,k,handle,pid,created,read,write)
    finally:
        k.CloseHandle(handle)


if __name__=='__main__':main()
