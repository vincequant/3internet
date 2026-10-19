#!/usr/bin/env python3
"""D-only entry; reuse P51 Win32/process helpers without changing its router.

No game launch, network operation or automatic install. Default action=check.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--panel-action', choices=['plan','check','install','revert','watch'], default='check')
    ap.add_argument('--state', required=True)
    ap.add_argument('--expected-pid', type=int)
    ap.add_argument('--expected-creation', type=int)
    ap.add_argument('--panel-fields', default='identity')
    ap.add_argument('--panel-log')
    ap.add_argument('--panel-seconds', type=int, default=1800)
    ap.add_argument('--bridge', help='optional exact SHA-matching pure rule directory')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if Path(os.environ.get('WINEPREFIX', '').rstrip('/\\')).name != 'prefix-fengye-shadow':
        raise SystemExit('explicit prefix-fengye-shadow required before process discovery')
    if sys.platform != 'win32':
        raise SystemExit('run under shadow Wine Win32 Python')
    from p51_shadow_inject import _win, find_process, process_creation
    from p53_unit_panel import run
    c,w,k = _win()
    targets = find_process('SANPK.exe')
    if not targets and args.panel_action == 'check':
        print('{"status":"no_target","activation":false}')
        return
    if len(targets) != 1:
        raise SystemExit('need exactly one SANPK in the shadow prefix')
    pid=targets[0][0];created=process_creation(pid)
    if (not created or (args.expected_pid is not None and pid!=args.expected_pid)
            or (args.expected_creation is not None and created!=args.expected_creation)):
        raise SystemExit('process identity mismatch')
    readonly = args.panel_action in ('check','plan') or args.dry_run
    # P51's VM/process helpers, with no CREATE_THREAD right requested.
    rights = 0x0400|0x0010 if readonly else 0x0400|0x0010|0x0020|0x0008
    handle=k.OpenProcess(rights,False,pid)
    if not handle:
        raise OSError('OpenProcess')

    def read(address,size):
        buffer=c.create_string_buffer(size);got=c.c_size_t()
        ok=k.ReadProcessMemory(handle,c.c_void_p(address),buffer,size,c.byref(got))
        return buffer.raw if ok and got.value==size else None

    def write(address,raw):
        if readonly:
            raise ValueError('write attempted in read-only action')
        got=c.c_size_t()
        return bool(k.WriteProcessMemory(handle,c.c_void_p(address),raw,len(raw),c.byref(got))) and got.value==len(raw)

    try:
        if process_creation(pid)!=created:
            raise ValueError('target changed before entry')
        run(args,c,w,k,handle,pid,created,read,write)
    finally:
        k.CloseHandle(handle)


if __name__=='__main__':main()
